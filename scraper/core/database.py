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
        try:
            conn = psycopg2.connect(
                DATABASE_URL,
                cursor_factory=psycopg2.extras.RealDictCursor,
                connect_timeout=5,
            )
        except psycopg2.OperationalError as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            raise
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
    industry TEXT DEFAULT '',
    logo_url TEXT DEFAULT '',
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
    industry    TEXT DEFAULT '',
    salary      TEXT DEFAULT '',
    description TEXT DEFAULT '',
    apply_url   TEXT DEFAULT '',
    logo_url    TEXT DEFAULT '',
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

CREATE TABLE IF NOT EXISTS audit_logs (
    id          SERIAL PRIMARY KEY,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    resource_id TEXT DEFAULT '',
    user_id     TEXT DEFAULT '',
    ip_address  TEXT DEFAULT '',
    details     JSONB DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS global_industries (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS global_departments (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

SQLITE_TABLES = """
CREATE TABLE IF NOT EXISTS companies (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    url      TEXT NOT NULL UNIQUE,
    industry TEXT DEFAULT '',
    logo_url TEXT DEFAULT '',
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
    industry    TEXT DEFAULT '',
    salary      TEXT DEFAULT '',
    description TEXT DEFAULT '',
    apply_url   TEXT DEFAULT '',
    logo_url    TEXT DEFAULT '',
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

CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL,
    resource_id TEXT DEFAULT '',
    user_id     TEXT DEFAULT '',
    ip_address  TEXT DEFAULT '',
    details     TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS global_industries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS global_departments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def init_db():
    schema = PG_TABLES if USE_POSTGRES else SQLITE_TABLES
    with get_conn() as conn:
        cur = conn.cursor()
        for stmt in schema.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
    _migrate_industry_columns()
    _migrate_user_tracking_columns()
    _migrate_job_extra_columns()
    _migrate_featured_column()
    _migrate_alert_timezone_column()
    _migrate_schema()          # adds logo_url to companies
    _seed_companies()
    _seed_global_data()
    logger.info("Database ready")


def _migrate_job_extra_columns():
    """Add apply_mode and deadline columns to jobs if missing."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            try:
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS apply_mode TEXT DEFAULT 'insite'")
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS deadline DATE")
            except Exception as e:
                logger.warning(f"Migration skipped: {e}")
        else:
            for col, typ in [("apply_mode", "TEXT DEFAULT 'insite'"), ("deadline", "TEXT")]:
                try:
                    cur.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")
                except Exception:
                    pass


def _migrate_featured_column():
    """Add is_featured column to jobs if missing."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            try:
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE")
            except Exception: pass
        else:
            try:
                cur.execute("ALTER TABLE jobs ADD COLUMN is_featured INTEGER DEFAULT 0")
            except Exception: pass


def _migrate_alert_timezone_column():
    """Add timezone and companies columns to job_alerts if missing."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            try:
                cur.execute(
                    "ALTER TABLE job_alerts ADD COLUMN IF NOT EXISTS timezone VARCHAR(60) DEFAULT 'Africa/Lagos'"
                )
                cur.execute(
                    "ALTER TABLE job_alerts ADD COLUMN IF NOT EXISTS companies TEXT DEFAULT ''"
                )
            except Exception as e:
                logger.warning(f"Migration skipped: {e}")
        else:
            try:
                cur.execute("ALTER TABLE job_alerts ADD COLUMN timezone TEXT DEFAULT 'Africa/Lagos'")
            except Exception:
                pass


def _migrate_user_tracking_columns():
    """Add last_login_at, last_ip, mfa_enabled to users if missing."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            for stmt in [
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_ip VARCHAR(45)",
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN DEFAULT FALSE",
            ]:
                try: cur.execute(stmt)
                except Exception as e: logger.warning(f"Migration skipped: {e}")
        else:
            for col, defn in [
                ("last_login_at", "TEXT"),
                ("last_ip", "TEXT"),
                ("mfa_enabled", "INTEGER DEFAULT 0"),
            ]:
                try: cur.execute(f"ALTER TABLE users ADD COLUMN {col} {defn}")
                except Exception: pass


def _migrate_industry_columns():
    """Add industry columns to companies/jobs if missing (older DBs)."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            stmts = [
                "ALTER TABLE companies ADD COLUMN IF NOT EXISTS industry TEXT DEFAULT ''",
                "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS industry TEXT DEFAULT ''",
                "CREATE INDEX IF NOT EXISTS idx_jobs_industry ON jobs(industry)",
            ]
            for s in stmts:
                try:
                    cur.execute(s)
                except Exception as e:
                    logger.warning(f"Migration skipped: {e}")
        else:
            for table in ("companies", "jobs"):
                try:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN industry TEXT DEFAULT ''")
                except Exception:
                    pass  # column already exists



def _migrate_schema():
    """Add columns introduced after initial deploy."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("ALTER TABLE companies ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT ''")
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT ''")
                # Fix scraped_at type mismatch — stored as TEXT but COALESCE needs TIMESTAMP
                # Convert to TIMESTAMP if it's still TEXT (safe — isoformat strings parse correctly)
                cur.execute("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name='jobs' AND column_name='scraped_at'
                            AND data_type='text'
                        ) THEN
                            ALTER TABLE jobs ALTER COLUMN scraped_at TYPE TIMESTAMP
                            USING scraped_at::timestamp;
                        END IF;
                    END $$;
                """)
                # Company profile fields on tenants
                for col in [
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'pending'",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS verification_note TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS verified_at TIMESTAMP",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS verified_by TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS cover_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS about TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS website TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS industry TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS company_size TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS founded_year INTEGER",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS hq_location TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS linkedin_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS twitter_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_email TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contact_phone TEXT DEFAULT ''",
                ]:
                    cur.execute(col)
            else:
                for sql in [
                    "ALTER TABLE companies ADD COLUMN logo_url TEXT DEFAULT ''",
                    "ALTER TABLE jobs ADD COLUMN logo_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN logo_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN cover_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN about TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN website TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN industry TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN company_size TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN founded_year INTEGER",
                    "ALTER TABLE tenants ADD COLUMN hq_location TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN linkedin_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN twitter_url TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN contact_email TEXT DEFAULT ''",
                    "ALTER TABLE tenants ADD COLUMN contact_phone TEXT DEFAULT ''",
                ]:
                    try:
                        cur.execute(sql)
                    except Exception:
                        pass  # column already exists
    except Exception as e:
        pass  # non-fatal


def _seed_companies():
    """No default companies — all companies are managed via the admin UI."""
    pass


def _seed_global_data():
    """Seed default industries and departments if tables are empty."""
    DEFAULT_INDUSTRIES = [
        "Banking & Finance", "Telecommunications", "Oil & Gas", "Information Technology",
        "Healthcare", "Education", "Manufacturing", "Retail & Consumer Goods",
        "Media & Entertainment", "Transportation & Logistics", "Agriculture",
        "Construction & Real Estate", "Energy", "Government & Public Sector",
        "Non-Profit & NGO", "Professional Services", "Hospitality & Tourism",
        "Legal", "Insurance", "E-Commerce",
    ]
    DEFAULT_DEPARTMENTS = [
        "General", "Engineering & IT", "Sales & Business Development",
        "Marketing & Communications", "Finance & Accounting", "Human Resources",
        "Operations", "Customer Success", "Product Management", "Design & UX",
        "Legal & Compliance", "Supply Chain & Logistics", "Research & Development",
        "Strategy & Analytics", "Executive & Leadership",
    ]
    ph = "%s" if USE_POSTGRES else "?"
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM global_industries")
            row = cur.fetchone()
            count = list(row)[0] if row else 0
            if count == 0:
                for i, name in enumerate(DEFAULT_INDUSTRIES):
                    try:
                        cur.execute(
                            f"INSERT INTO global_industries (name, sort_order) VALUES ({ph},{ph})",
                            (name, i)
                        )
                    except Exception:
                        pass
            cur.execute("SELECT COUNT(*) FROM global_departments")
            row = cur.fetchone()
            count = list(row)[0] if row else 0
            if count == 0:
                for i, name in enumerate(DEFAULT_DEPARTMENTS):
                    try:
                        cur.execute(
                            f"INSERT INTO global_departments (name, sort_order) VALUES ({ph},{ph})",
                            (name, i)
                        )
                    except Exception:
                        pass
    except Exception as e:
        log.warning(f"_seed_global_data: {e}")



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


def add_company(name: str, url: str, industry: str = "", logo_url: str = "") -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO companies (name, url, industry, logo_url, active) VALUES (%s, %s, %s, %s, 1) "
                "ON CONFLICT (url) DO UPDATE SET active = 1, industry = EXCLUDED.industry, logo_url = EXCLUDED.logo_url RETURNING *",
                (name, url, industry, logo_url)
            )
            return row_to_dict(cur.fetchone())
        else:
            cur.execute(
                "INSERT OR REPLACE INTO companies (name, url, industry, logo_url, active) VALUES (?, ?, ?, ?, 1)",
                (name, url, industry, logo_url)
            )
            cur.execute("UPDATE companies SET industry = ? WHERE url = ?", (industry, url))
            cur.execute("SELECT * FROM companies WHERE url = ?", (url,))
            return row_to_dict(cur.fetchone())


def update_company_industry(company_id: int, industry: str) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q("UPDATE companies SET industry = ? WHERE id = ?"), (industry, company_id))
        cur.execute(q("SELECT * FROM companies WHERE id = ?"), (company_id,))
        return row_to_dict(cur.fetchone())


def delete_company(company_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(q("UPDATE companies SET active = 0 WHERE id = ?"), (company_id,))


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _get_company_logo(cur, company_name: str) -> str:
    """Look up logo_url from companies table by company name."""
    try:
        cur.execute("SELECT logo_url FROM companies WHERE name = ? OR name LIKE ? LIMIT 1",
                    (company_name, f"%{company_name}%"))
        row = cur.fetchone()
        return (row[0] or "") if row else ""
    except Exception:
        return ""


def _get_company_industry(cur, company_name: str) -> str:
    """
    Look up the industry configured for a company in the companies table.
    Tries exact match first, then case-insensitive LIKE match.
    """
    if not company_name:
        return ""
    try:
        # Exact match first
        cur.execute(
            q("SELECT industry FROM companies WHERE name = ? AND active = 1"),
            (company_name,)
        )
        row = cur.fetchone()
        if row:
            val = dict(row).get("industry") or ""
            if val.strip():
                return val.strip()

        # Fuzzy match — company name in DB may differ slightly
        cur.execute(
            q("SELECT industry FROM companies WHERE active = 1 AND ? LIKE '%' || name || '%'"),
            (company_name,)
        )
        row = cur.fetchone()
        if row:
            val = dict(row).get("industry") or ""
            if val.strip():
                return val.strip()

        # Reverse fuzzy — name in DB contains the scraped company name
        cur.execute(
            q("SELECT industry FROM companies WHERE active = 1 AND name LIKE ?"),
            (f"%{company_name}%",)
        )
        row = cur.fetchone()
        if row:
            val = dict(row).get("industry") or ""
            return val.strip()

    except Exception:
        pass
    return ""


def upsert_jobs(scraped) -> tuple[int, int]:
    """
    Insert or update scraped jobs in the DB.

    Each job is wrapped in its own savepoint (PostgreSQL) so a single
    failure — e.g. a missing column, bad value, or constraint violation —
    does NOT abort the entire batch. Failed jobs are logged and skipped.
    """
    from core.classify import classify_job
    import logging as _log
    log = _log.getLogger(__name__)

    new_count = 0
    err_count = 0

    with get_conn() as conn:
        cur = conn.cursor()

        # Ensure logo_url column exists (may be missing on older Railway DBs)
        if USE_POSTGRES:
            try:
                cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT ''")
            except Exception:
                conn.rollback()

        for i, job in enumerate(scraped):
            sp = f"sp_{i}"
            try:
                if USE_POSTGRES:
                    cur.execute(f"SAVEPOINT {sp}")

                job_type, department = classify_job(
                    job.title, job.description,
                    getattr(job, "job_type", "Full-time"),
                    getattr(job, "department", "General"),
                )
                industry = (getattr(job, "industry", "") or "").strip()
                if not industry:
                    industry = _get_company_industry(cur, job.company)

                cur.execute(q("SELECT id FROM jobs WHERE fingerprint = ?"), (job.fingerprint,))
                existing = cur.fetchone()

                if existing:
                    job_logo = getattr(job, "logo_url", "") or _get_company_logo(cur, job.company)
                    try:
                        cur.execute(
                            q("UPDATE jobs SET scraped_at=?, is_active=1, job_type=?, department=?, "
                              "industry=?, logo_url=COALESCE(NULLIF(?,''),logo_url) WHERE fingerprint=?"),
                            (job.scraped_at.isoformat(), job_type, department, industry, job_logo, job.fingerprint)
                        )
                    except Exception:
                        # logo_url column may not exist — retry without it
                        if USE_POSTGRES: cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        cur.execute(
                            q("UPDATE jobs SET scraped_at=?, is_active=1, job_type=?, department=?, industry=? WHERE fingerprint=?"),
                            (job.scraped_at.isoformat(), job_type, department, industry, job.fingerprint)
                        )
                else:
                    job_logo = getattr(job, "logo_url", "") or _get_company_logo(cur, job.company)
                    try:
                        cur.execute(q("""
                            INSERT INTO jobs
                              (fingerprint, title, company, source_url, location,
                               job_type, department, industry, salary, description,
                               apply_url, logo_url, is_active, scraped_at)
                            VALUES (?,?,?,?,?, ?,?,?,?,?, ?,?,1,?)
                        """), (
                            job.fingerprint, job.title, job.company, job.source_url, job.location,
                            job_type, department, industry, job.salary, job.description,
                            job.apply_url, job_logo, job.scraped_at.isoformat()
                        ))
                    except Exception:
                        # Retry without logo_url in case column missing
                        if USE_POSTGRES: cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        cur.execute(q("""
                            INSERT INTO jobs
                              (fingerprint, title, company, source_url, location,
                               job_type, department, industry, salary, description,
                               apply_url, is_active, scraped_at)
                            VALUES (?,?,?,?,?, ?,?,?,?,?, ?,1,?)
                        """), (
                            job.fingerprint, job.title, job.company, job.source_url, job.location,
                            job_type, department, industry, job.salary, job.description,
                            job.apply_url, job.scraped_at.isoformat()
                        ))
                    new_count += 1

                if USE_POSTGRES:
                    cur.execute(f"RELEASE SAVEPOINT {sp}")

            except Exception as e:
                err_count += 1
                log.error(f"upsert_jobs: failed to save '{job.title}' ({job.company}): {e}")
                if USE_POSTGRES:
                    try:
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                    except Exception:
                        pass

    if err_count:
        log.warning(f"upsert_jobs: {err_count}/{len(scraped)} jobs failed to save")

    return len(scraped), new_count


def get_jobs(
    search: str = "",
    job_type: str = "",
    department: str = "",
    company: str = "",
    industry: str = "",
    location: str = "",
    source: str = "",
    include_inactive: bool = False,
    tenant_id: str = "",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    if include_inactive:
        conditions = []  # show all including unpublished
    else:
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
        if USE_POSTGRES:
            conditions.append("department ILIKE %s")
        else:
            conditions.append("department LIKE ?")
        params.append(f"%{department}%")
    if company:
        conditions.append(q("company = ?"))
        params.append(company)
    if industry:
        if USE_POSTGRES:
            conditions.append("industry ILIKE %s")
        else:
            conditions.append("industry LIKE ?")
        params.append(f"%{industry}%")
    if location:
        if USE_POSTGRES:
            conditions.append("location ILIKE %s")
        else:
            conditions.append("location LIKE ?")
        params.append(f"%{location}%")
    if source:
        conditions.append("source = %s" if USE_POSTGRES else "source = ?")
        params.append(source)
    if tenant_id:
        # Strict tenant isolation
        conditions.append("tenant_id = %s" if USE_POSTGRES else "tenant_id = ?")
        params.append(tenant_id)

    where = " AND ".join(conditions) if conditions else "1=1"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM jobs WHERE {where}", params)
        count_row = cur.fetchone()
        total = int(list(count_row.values())[0]) if USE_POSTGRES else int(count_row[0])

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
