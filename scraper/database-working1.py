"""
JobStream Database Layer
Auto-detects PostgreSQL or SQLite based on DATABASE_URL env var.

PostgreSQL:  DATABASE_URL=postgresql://user:pass@host:5432/jobstream
SQLite:      DB_PATH=/app/data/jobstream.db (default)
"""

import os
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH = os.environ.get("DB_PATH", "./jobstream.db")
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    logger.info("Using PostgreSQL")
else:
    import sqlite3
    logger.info(f"Using SQLite at {DB_PATH}")


@contextmanager
def get_conn():
    if USE_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    else:
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


def row_to_dict(row) -> Optional[dict]:
    return dict(row) if row else None


def q(sql: str) -> str:
    """Convert ? placeholders to %s for PostgreSQL."""
    return sql.replace("?", "%s") if USE_POSTGRES else sql


# ---------------------------------------------------------------------------
# Schema — uses TEXT/INTEGER everywhere to work in both DBs
# ---------------------------------------------------------------------------

PG_TABLES = """
CREATE TABLE IF NOT EXISTS companies (
    id       SERIAL PRIMARY KEY,
    name     TEXT NOT NULL,
    url      TEXT NOT NULL UNIQUE,
    active   SMALLINT DEFAULT 1,
    added_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jobs (
    id          SERIAL PRIMARY KEY,
    fingerprint TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    location    TEXT DEFAULT 'Not specified',
    job_type    TEXT DEFAULT 'Full-time',
    department  TEXT DEFAULT 'General',
    salary      TEXT DEFAULT '',
    description TEXT DEFAULT '',
    apply_url   TEXT DEFAULT '',
    is_active   SMALLINT DEFAULT 1,
    scraped_at  TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS applications (
    id           SERIAL PRIMARY KEY,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    phone        TEXT DEFAULT '',
    resume_url   TEXT DEFAULT '',
    cover_note   TEXT DEFAULT '',
    status       TEXT DEFAULT 'new',
    submitted_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id          SERIAL PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    jobs_found  INTEGER DEFAULT 0,
    jobs_new    INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'running',
    error       TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_jobs_company  ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_active   ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_apps_job      ON applications(job_id);
"""

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS companies (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    url      TEXT NOT NULL UNIQUE,
    active   INTEGER DEFAULT 1,
    added_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT UNIQUE NOT NULL,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    source_url  TEXT NOT NULL,
    location    TEXT DEFAULT 'Not specified',
    job_type    TEXT DEFAULT 'Full-time',
    department  TEXT DEFAULT 'General',
    salary      TEXT DEFAULT '',
    description TEXT DEFAULT '',
    apply_url   TEXT DEFAULT '',
    is_active   INTEGER DEFAULT 1,
    scraped_at  TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS applications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id),
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    phone        TEXT DEFAULT '',
    resume_url   TEXT DEFAULT '',
    cover_note   TEXT DEFAULT '',
    status       TEXT DEFAULT 'new',
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
"""


def init_db():
    schema = PG_TABLES if USE_POSTGRES else SQLITE_TABLES
    with get_conn() as conn:
        cur = conn.cursor()
        for stmt in schema.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
    _seed_companies()
    logger.info("Database ready")


def _seed_companies():
    defaults = [
        ("Stripe",      "https://stripe.com/jobs"),
        ("Paystack",    "https://paystack.com/careers"),
        ("Flutterwave", "https://flutterwave.com/careers"),
        ("Andela",      "https://andela.com/talent"),
    ]
    with get_conn() as conn:
        cur = conn.cursor()
        for name, url in defaults:
            if USE_POSTGRES:
                cur.execute(
                    "INSERT INTO companies (name, url, active) VALUES (%s, %s, 1) ON CONFLICT (url) DO NOTHING",
                    (name, url)
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO companies (name, url, active) VALUES (?, ?, 1)",
                    (name, url)
                )


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def get_companies(active_only=True) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        if active_only:
            cur.execute("SELECT * FROM companies WHERE active = 1 ORDER BY name")
        else:
            cur.execute("SELECT * FROM companies ORDER BY name")
        return [row_to_dict(r) for r in cur.fetchall()]


def add_company(name: str, url: str) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO companies (name, url, active) VALUES (%s, %s, 1) ON CONFLICT (url) DO UPDATE SET active = 1 RETURNING *",
                (name, url)
            )
            return row_to_dict(cur.fetchone())
        else:
            cur.execute("INSERT OR IGNORE INTO companies (name, url, active) VALUES (?, ?, 1)", (name, url))
            cur.execute("SELECT * FROM companies WHERE url = ?", (url,))
            return row_to_dict(cur.fetchone())


def delete_company(company_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q("UPDATE companies SET active = 0 WHERE id = ?"), (company_id,))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def upsert_jobs(scraped) -> tuple[int, int]:
    new_count = 0
    with get_conn() as conn:
        cur = conn.cursor()
        for job in scraped:
            cur.execute(q("SELECT id FROM jobs WHERE fingerprint = ?"), (job.fingerprint,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    q("UPDATE jobs SET scraped_at = ?, is_active = 1 WHERE fingerprint = ?"),
                    (job.scraped_at.isoformat(), job.fingerprint)
                )
            else:
                cur.execute(q("""
                    INSERT INTO jobs
                      (fingerprint, title, company, source_url, location,
                       job_type, department, salary, description, apply_url, is_active, scraped_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """), (
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
    conditions = ["is_active = 1"]
    params = []

    if search:
        like = f"%{search}%"
        if USE_POSTGRES:
            conditions.append("(title ILIKE %s OR company ILIKE %s OR location ILIKE %s)")
        else:
            conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ?)")
        params.extend([like, like, like])
    if job_type:
        conditions.append(q("job_type = ?"))
        params.append(job_type)
    if department:
        conditions.append(q("department = ?"))
        params.append(department)
    if company:
        conditions.append(q("company = ?"))
        params.append(company)

    where = " AND ".join(conditions)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params)
        count_row = cur.fetchone()
        total = list(count_row.values())[0] if USE_POSTGRES else count_row[0]

        cur.execute(
            f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT {q('?')} OFFSET {q('?')}",
            params + [limit, offset]
        )
        return [row_to_dict(r) for r in cur.fetchall()], total


def get_job(job_id: int) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q("SELECT * FROM jobs WHERE id = ?"), (job_id,))
        return row_to_dict(cur.fetchone())


def mark_jobs_inactive(source_url: str, current_fingerprints: list[str]):
    if not current_fingerprints:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE jobs SET is_active = 0 WHERE source_url = %s AND NOT (fingerprint = ANY(%s))",
                (source_url, current_fingerprints)
            )
        else:
            placeholders = ",".join("?" * len(current_fingerprints))
            cur.execute(
                f"UPDATE jobs SET is_active = 0 WHERE source_url = ? AND fingerprint NOT IN ({placeholders})",
                [source_url] + current_fingerprints
            )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def create_application(job_id: int, data: dict) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO applications (job_id, name, email, phone, resume_url, cover_note)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING *
            """, (
                job_id, data["name"], data["email"],
                data.get("phone", ""), data.get("resume_url", ""), data.get("cover_note", "")
            ))
            return row_to_dict(cur.fetchone())
        else:
            cur.execute("""
                INSERT INTO applications (job_id, name, email, phone, resume_url, cover_note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                job_id, data["name"], data["email"],
                data.get("phone", ""), data.get("resume_url", ""), data.get("cover_note", "")
            ))
            cur.execute("SELECT * FROM applications WHERE rowid = last_insert_rowid()")
            return row_to_dict(cur.fetchone())


def get_applications(job_id: int = None) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        if job_id:
            cur.execute(
                q("SELECT a.*, j.title AS job_title FROM applications a JOIN jobs j ON a.job_id = j.id WHERE a.job_id = ? ORDER BY a.submitted_at DESC"),
                (job_id,)
            )
        else:
            cur.execute(
                "SELECT a.*, j.title AS job_title FROM applications a JOIN jobs j ON a.job_id = j.id ORDER BY a.submitted_at DESC"
            )
        return [row_to_dict(r) for r in cur.fetchall()]


def update_application_status(app_id: int, status: str):
    valid = {"new", "reviewing", "interview", "offered", "rejected"}
    if status not in valid:
        raise ValueError(f"Invalid status: {status}")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q("UPDATE applications SET status = ? WHERE id = ?"), (status, app_id))


# ---------------------------------------------------------------------------
# Scrape Runs
# ---------------------------------------------------------------------------

def start_scrape_run() -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO scrape_runs (started_at) VALUES (%s) RETURNING id",
                (datetime.utcnow().isoformat(),)
            )
            return row_to_dict(cur.fetchone())["id"]
        else:
            cur.execute("INSERT INTO scrape_runs (started_at) VALUES (?)", (datetime.utcnow().isoformat(),))
            cur.execute("SELECT last_insert_rowid()")
            return cur.fetchone()[0]


def finish_scrape_run(run_id: int, jobs_found: int, jobs_new: int, error: str = ""):
    status = "error" if error else "success"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            q("UPDATE scrape_runs SET finished_at = ?, jobs_found = ?, jobs_new = ?, status = ?, error = ? WHERE id = ?"),
            (datetime.utcnow().isoformat(), jobs_found, jobs_new, status, error, run_id)
        )


def get_scrape_history(limit=10) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q("SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT ?"), (limit,))
        return [row_to_dict(r) for r in cur.fetchall()]
