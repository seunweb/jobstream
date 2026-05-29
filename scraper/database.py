"""
JobStream Database Layer
Supports both PostgreSQL (production) and SQLite (local dev).
Set DATABASE_URL env var for PostgreSQL, otherwise falls back to SQLite.

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

# Use PostgreSQL if DATABASE_URL is set, otherwise SQLite
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    logger.info("Using PostgreSQL")
else:
    import sqlite3
    logger.info(f"Using SQLite at {DB_PATH}")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

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


def placeholder(n: int) -> str:
    """Return correct placeholders for the DB driver."""
    if USE_POSTGRES:
        return ", ".join(f"${i}" for i in range(1, n + 1))
    return ", ".join("?" * n)


def ph(n: int) -> str:
    return placeholder(n)


def adapt(sql: str) -> str:
    """Convert SQLite ? placeholders to PostgreSQL $1, $2... style."""
    if not USE_POSTGRES:
        return sql
    count = 0
    result = []
    for ch in sql:
        if ch == "?":
            count += 1
            result.append(f"${count}")
        else:
            result.append(ch)
    return "".join(result)


def row_to_dict(row) -> dict:
    if row is None:
        return None
    if USE_POSTGRES:
        return dict(row)
    return dict(row)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    active      INTEGER DEFAULT 1,
    added_at    TEXT DEFAULT (CURRENT_TIMESTAMP)
);

CREATE TABLE IF NOT EXISTS jobs (
    id           SERIAL PRIMARY KEY,
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
    created_at   TEXT DEFAULT (CURRENT_TIMESTAMP)
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
    submitted_at TEXT DEFAULT (CURRENT_TIMESTAMP)
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

CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_active  ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_apps_job     ON applications(job_id);
"""

SCHEMA_SQLITE = SCHEMA.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        schema = SCHEMA if USE_POSTGRES else SCHEMA_SQLITE
        # Execute each statement separately
        for stmt in schema.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
    _seed_companies()


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
                    "INSERT INTO companies (name, url) SELECT $1, $2 WHERE NOT EXISTS (SELECT 1 FROM companies WHERE url = $2)",
                    (name, url)
                )
            else:
                cur.execute(
                    "INSERT OR IGNORE INTO companies (name, url) VALUES (?, ?)",
                    (name, url)
                )


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

def get_companies(active_only=True) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        q = "SELECT * FROM companies"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY name"
        cur.execute(q)
        return [row_to_dict(r) for r in cur.fetchall()]


def add_company(name: str, url: str) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO companies (name, url) VALUES ($1, $2) RETURNING *",
                (name, url)
            )
            return row_to_dict(cur.fetchone())
        else:
            cur.execute("INSERT INTO companies (name, url) VALUES (?, ?)", (name, url))
            cur.execute("SELECT * FROM companies WHERE url = ?", (url,))
            return row_to_dict(cur.fetchone())


def delete_company(company_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(adapt("UPDATE companies SET active = 0 WHERE id = ?"), (company_id,))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def upsert_jobs(scraped) -> tuple[int, int]:
    new_count = 0
    with get_conn() as conn:
        cur = conn.cursor()
        for job in scraped:
            cur.execute(adapt("SELECT id FROM jobs WHERE fingerprint = ?"), (job.fingerprint,))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    adapt("UPDATE jobs SET scraped_at = ?, is_active = 1 WHERE fingerprint = ?"),
                    (job.scraped_at.isoformat(), job.fingerprint)
                )
            else:
                if USE_POSTGRES:
                    cur.execute("""
                        INSERT INTO jobs
                          (fingerprint, title, company, source_url, location,
                           job_type, department, salary, description, apply_url, scraped_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    """, (
                        job.fingerprint, job.title, job.company, job.source_url,
                        job.location, job.job_type, job.department,
                        job.salary, job.description, job.apply_url,
                        job.scraped_at.isoformat()
                    ))
                else:
                    cur.execute("""
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
    conditions = ["is_active = 1"]
    params = []

    if search:
        if USE_POSTGRES:
            conditions.append("(title ILIKE $%d OR company ILIKE $%d OR location ILIKE $%d)")
        else:
            conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if job_type:
        params.append(job_type)
        conditions.append(f"job_type = {'$'+str(len(params)) if USE_POSTGRES else '?'}")
    if department:
        params.append(department)
        conditions.append(f"department = {'$'+str(len(params)) if USE_POSTGRES else '?'}")
    if company:
        params.append(company)
        conditions.append(f"company = {'$'+str(len(params)) if USE_POSTGRES else '?'}")

    where = " AND ".join(conditions)

    # Fix ILIKE placeholder numbering for postgres
    if USE_POSTGRES and search:
        base = len(params) - 2
        where = where.replace(
            "(title ILIKE $%d OR company ILIKE $%d OR location ILIKE $%d)",
            f"(title ILIKE ${base} OR company ILIKE ${base+1} OR location ILIKE ${base+2})"
        )

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params)
        total = cur.fetchone()[0] if not USE_POSTGRES else list(cur.fetchone().values())[0]

        params.extend([limit, offset])
        if USE_POSTGRES:
            cur.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}",
                params
            )
        else:
            cur.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params
            )
        return [row_to_dict(r) for r in cur.fetchall()], total


def get_job(job_id: int) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(adapt("SELECT * FROM jobs WHERE id = ?"), (job_id,))
        return row_to_dict(cur.fetchone())


def mark_jobs_inactive(source_url: str, current_fingerprints: list[str]):
    if not current_fingerprints:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE jobs SET is_active = 0 WHERE source_url = %s AND fingerprint != ALL(%s)",
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
                VALUES ($1,$2,$3,$4,$5,$6) RETURNING *
            """, (
                job_id, data["name"], data["email"],
                data.get("phone", ""), data.get("resume_url", ""),
                data.get("cover_note", "")
            ))
            return row_to_dict(cur.fetchone())
        else:
            cur.execute("""
                INSERT INTO applications (job_id, name, email, phone, resume_url, cover_note)
                VALUES (?,?,?,?,?,?)
            """, (
                job_id, data["name"], data["email"],
                data.get("phone", ""), data.get("resume_url", ""),
                data.get("cover_note", "")
            ))
            cur.execute("SELECT * FROM applications WHERE rowid = last_insert_rowid()")
            return row_to_dict(cur.fetchone())


def get_applications(job_id: int = None) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        if job_id:
            cur.execute(
                adapt("SELECT a.*, j.title job_title FROM applications a JOIN jobs j ON a.job_id = j.id WHERE a.job_id = ? ORDER BY a.submitted_at DESC"),
                (job_id,)
            )
        else:
            cur.execute(
                "SELECT a.*, j.title job_title FROM applications a JOIN jobs j ON a.job_id = j.id ORDER BY a.submitted_at DESC"
            )
        return [row_to_dict(r) for r in cur.fetchall()]


def update_application_status(app_id: int, status: str):
    valid = {"new", "reviewing", "interview", "offered", "rejected"}
    if status not in valid:
        raise ValueError(f"Invalid status: {status}")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(adapt("UPDATE applications SET status = ? WHERE id = ?"), (status, app_id))


# ---------------------------------------------------------------------------
# Scrape Runs
# ---------------------------------------------------------------------------

def start_scrape_run() -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO scrape_runs (started_at) VALUES ($1) RETURNING id",
                (datetime.utcnow().isoformat(),)
            )
            return cur.fetchone()["id"]
        else:
            cur.execute(
                "INSERT INTO scrape_runs (started_at) VALUES (?)",
                (datetime.utcnow().isoformat(),)
            )
            cur.execute("SELECT last_insert_rowid()")
            return cur.fetchone()[0]


def finish_scrape_run(run_id: int, jobs_found: int, jobs_new: int, error: str = ""):
    status = "error" if error else "success"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            adapt("UPDATE scrape_runs SET finished_at=?, jobs_found=?, jobs_new=?, status=?, error=? WHERE id=?"),
            (datetime.utcnow().isoformat(), jobs_found, jobs_new, status, error, run_id)
        )


def get_scrape_history(limit=10) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(adapt("SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT ?"), (limit,))
        return [row_to_dict(r) for r in cur.fetchall()]
