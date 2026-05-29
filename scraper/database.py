"""
JobStream Database Layer
SQLite for easy local dev — swap DATABASE_URL to postgres:// for production.
"""

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from scraper import ScrapedJob

DB_PATH = Path(__file__).parent / "jobstream.db"


def init_db():
    """Create tables if they don't exist."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL,
            url      TEXT NOT NULL UNIQUE,
            active   INTEGER DEFAULT 1,
            added_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint  TEXT UNIQUE NOT NULL,
            title        TEXT NOT NULL,
            company      TEXT NOT NULL,
            source_url   TEXT NOT NULL,
            location     TEXT DEFAULT 'Not specified',
            job_type     TEXT DEFAULT 'Full-time',
            department   TEXT DEFAULT 'General',
            salary       TEXT DEFAULT '',
            description  TEXT DEFAULT '',
            apply_url    TEXT DEFAULT '',
            is_active    INTEGER DEFAULT 1,
            scraped_at   TEXT NOT NULL,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS applications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id     INTEGER NOT NULL REFERENCES jobs(id),
            name       TEXT NOT NULL,
            email      TEXT NOT NULL,
            phone      TEXT DEFAULT '',
            resume_url TEXT DEFAULT '',
            cover_note TEXT DEFAULT '',
            status     TEXT DEFAULT 'new',
            submitted_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS scrape_runs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            finished_at TEXT,
            jobs_found  INTEGER DEFAULT 0,
            jobs_new    INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running',
            error       TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
        CREATE INDEX IF NOT EXISTS idx_jobs_active  ON jobs(is_active);
        CREATE INDEX IF NOT EXISTS idx_apps_job     ON applications(job_id);
        """)
    _seed_companies()


def _seed_companies():
    """Seed some example companies on first run."""
    defaults = [
        ("Stripe",      "https://stripe.com/jobs"),
        ("Paystack",    "https://paystack.com/careers"),
        ("Flutterwave", "https://flutterwave.com/careers"),
        ("Andela",      "https://andela.com/talent"),
    ]
    with get_conn() as conn:
        for name, url in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO companies (name, url) VALUES (?, ?)",
                (name, url)
            )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def get_companies(active_only=True) -> list[dict]:
    with get_conn() as conn:
        q = "SELECT * FROM companies"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY name"
        return [dict(r) for r in conn.execute(q).fetchall()]


def add_company(name: str, url: str) -> dict:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO companies (name, url) VALUES (?, ?)", (name, url)
        )
        row = conn.execute(
            "SELECT * FROM companies WHERE url = ?", (url,)
        ).fetchone()
        return dict(row)


def delete_company(company_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE companies SET active = 0 WHERE id = ?", (company_id,))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def upsert_jobs(scraped: list[ScrapedJob]) -> tuple[int, int]:
    """
    Insert new jobs, skip duplicates (by fingerprint).
    Returns (total_found, newly_inserted).
    """
    new_count = 0
    with get_conn() as conn:
        for job in scraped:
            existing = conn.execute(
                "SELECT id FROM jobs WHERE fingerprint = ?", (job.fingerprint,)
            ).fetchone()
            if existing:
                # Refresh scraped_at so we know it's still live
                conn.execute(
                    "UPDATE jobs SET scraped_at = ?, is_active = 1 WHERE fingerprint = ?",
                    (job.scraped_at.isoformat(), job.fingerprint)
                )
            else:
                conn.execute("""
                    INSERT INTO jobs
                      (fingerprint, title, company, source_url, location,
                       job_type, department, salary, description, apply_url, scraped_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    job.fingerprint, job.title, job.company, job.source_url,
                    job.location, job.job_type, job.department,
                    job.salary, job.description, job.apply_url,
                    job.scraped_at.isoformat()
                ))
                new_count += 1

    return len(scraped), new_count


def get_jobs(
    search: str = "",
    job_type: str = "",
    department: str = "",
    company: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return (jobs, total_count) with optional filters."""
    conditions = ["is_active = 1"]
    params = []

    if search:
        conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if job_type:
        conditions.append("job_type = ?")
        params.append(job_type)
    if department:
        conditions.append("department = ?")
        params.append(department)
    if company:
        conditions.append("company = ?")
        params.append(company)

    where = " AND ".join(conditions)

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM jobs WHERE {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()

    return [dict(r) for r in rows], total


def get_job(job_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def mark_jobs_inactive(source_url: str, current_fingerprints: list[str]):
    """Mark jobs as inactive if they disappeared from a page."""
    if not current_fingerprints:
        return
    placeholders = ",".join("?" * len(current_fingerprints))
    with get_conn() as conn:
        conn.execute(f"""
            UPDATE jobs SET is_active = 0
            WHERE source_url = ? AND fingerprint NOT IN ({placeholders})
        """, [source_url] + current_fingerprints)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def create_application(job_id: int, data: dict) -> dict:
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO applications (job_id, name, email, phone, resume_url, cover_note)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            job_id, data["name"], data["email"],
            data.get("phone", ""), data.get("resume_url", ""),
            data.get("cover_note", "")
        ))
        row = conn.execute(
            "SELECT * FROM applications WHERE rowid = last_insert_rowid()"
        ).fetchone()
        return dict(row)


def get_applications(job_id: int = None) -> list[dict]:
    with get_conn() as conn:
        if job_id:
            rows = conn.execute(
                "SELECT a.*, j.title job_title FROM applications a JOIN jobs j ON a.job_id = j.id WHERE a.job_id = ? ORDER BY a.submitted_at DESC",
                (job_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT a.*, j.title job_title FROM applications a JOIN jobs j ON a.job_id = j.id ORDER BY a.submitted_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def update_application_status(app_id: int, status: str):
    valid = {"new", "reviewing", "interview", "offered", "rejected"}
    if status not in valid:
        raise ValueError(f"Invalid status: {status}")
    with get_conn() as conn:
        conn.execute("UPDATE applications SET status = ? WHERE id = ?", (status, app_id))


# ---------------------------------------------------------------------------
# Scrape Runs (audit log)
# ---------------------------------------------------------------------------

def start_scrape_run() -> int:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO scrape_runs (started_at) VALUES (?)",
            (datetime.utcnow().isoformat(),)
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def finish_scrape_run(run_id: int, jobs_found: int, jobs_new: int, error: str = ""):
    status = "error" if error else "success"
    with get_conn() as conn:
        conn.execute("""
            UPDATE scrape_runs
            SET finished_at = ?, jobs_found = ?, jobs_new = ?, status = ?, error = ?
            WHERE id = ?
        """, (datetime.utcnow().isoformat(), jobs_found, jobs_new, status, error, run_id))


def get_scrape_history(limit=10) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
