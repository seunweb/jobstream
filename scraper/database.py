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


def adapt(sql: str) -> str:
    """Convert ? placeholders to $1,$2... for PostgreSQL."""
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


def row_to_dict(row) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

POSTGRES_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS companies (
        id       SERIAL PRIMARY KEY,
        name     TEXT NOT NULL,
        url      TEXT NOT NULL UNIQUE,
        active   INTEGER DEFAULT 1,
        added_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS jobs (
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
        is_active   INTEGER DEFAULT 1,
        scraped_at  TEXT NOT NULL,
        created_at  TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS applications (
        id           SERIAL PRIMARY KEY,
        job_id       INTEGER NOT NULL REFERENCES jobs(id),
        name         TEXT NOT NULL,
        email        TEXT NOT NULL,
        phone        TEXT DEFAULT '',
        resume_url   TEXT DEFAULT '',
        cover_note   TEXT DEFAULT '',
        status       TEXT DEFAULT 'new',
        submitted_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS scrape_runs (
        id          SERIAL PRIMARY KEY,
        started_at  TEXT NOT NULL,
        finished_at TEXT,
        jobs_found  INTEGER DEFAULT 0,
        jobs_new    INTEGER DEFAULT 0,
        status      TEXT DEFAULT 'running',
        error       TEXT DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)",
    "CREATE INDEX IF NOT EXISTS idx_jobs_active  ON jobs(is_active)",
    "CREATE INDEX IF NOT EXISTS idx_apps_job     ON applications(job_id)",
]

SQLITE_SCHEMA = [s.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
                 for s in POSTGRES_SCHEMA]


def init_db():
    schema = POSTGRES_SCHEMA if USE_POSTGRES else SQLITE_SCHEMA
    with get_conn() as conn:
        cur = conn.cursor()
        for stmt in schema:
            cur.execute(stmt)
    _seed_companies()
    logger.info("Database schema ready")


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
                    "INSERT INTO companies (name, url) SELECT %s, %s WHERE NOT EXISTS (SELECT 1 FROM companies WHERE url = %s)",
                    (name, url, url)
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
                "INSERT INTO companies (name, url) VALUES (%s, %s) RETURNING *",
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
                          (fingerprint,title,company,source_url,location,
                           job_type,department,salary,description,apply_url,scraped_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                        job.fingerprint, job.title, job.company, job.source_url,
                        job.location, job.job_type, job.department,
                        job.salary, job.description, job.apply_url,
                        job.scraped_at.isoformat()
                    ))
                else:
                    cur.execute("""
                        INSERT INTO jobs
                          (fingerprint,title,company,source_url,location,
                           job_type,department,salary,description,apply_url,scraped_at)
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
        like = f"%{search}%"
        if USE_POSTGRES:
            conditions.append("(title ILIKE %s OR company ILIKE %s OR location ILIKE %s)")
        else:
            conditions.append("(title LIKE ? OR company LIKE ? OR location LIKE ?)")
        params.extend([like, like, like])
    if job_type:
        conditions.append("job_type = %s" if USE_POSTGRES else "job_type = ?")
        params.append(job_type)
    if department:
        conditions.append("department = %s" if USE_POSTGRES else "department = ?")
        params.append(department)
    if company:
        conditions.append("company = %s" if USE_POSTGRES else "company = ?")
        params.append(company)

    where = " AND ".join(conditions)

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params)
        row = cur.fetchone()
        total = row["count"] if USE_POSTGRES else row[0]

        if USE_POSTGRES:
            cur.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [limit, offset]
            )
        else:
            cur.execute(
                f"SELECT * FROM jobs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
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
                INSERT INTO applications (job_id,name,email,phone,resume_url,cover_note)
                VALUES (%s,%s,%s,%s,%s,%s) RETURNING *
            """, (
                job_id, data["name"], data["email"],
                data.get("phone",""), data.get("resume_url",""), data.get("cover_note","")
            ))
            return row_to_dict(cur.fetchone())
        else:
            cur.execute("""
                INSERT INTO applications (job_id,name,email,phone,resume_url,cover_note)
                VALUES (?,?,?,?,?,?)
            """, (
                job_id, data["name"], data["email"],
                data.get("phone",""), data.get("resume_url",""), data.get("cover_note","")
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
    valid = {"new","reviewing","interview","offered","rejected"}
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
            adapt("UPDATE scrape_runs SET finished_at=?,jobs_found=?,jobs_new=?,status=?,error=? WHERE id=?"),
            (datetime.utcnow().isoformat(), jobs_found, jobs_new, status, error, run_id)
        )


def get_scrape_history(limit=10) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(adapt("SELECT * FROM scrape_runs ORDER BY started_at DESC LIMIT ?"), (limit,))
        return [row_to_dict(r) for r in cur.fetchall()]
