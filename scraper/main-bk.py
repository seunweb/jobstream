"""
JobStream API v2.0 — Modular Architecture
Modules: Identity, Organization, Recruitment
All existing endpoints preserved — zero breaking changes.
"""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES, init_db
from services.identity.router import router as identity_router
from services.identity.dependencies import get_current_user
from services.identity.models import ADD_AUTH_TABLES, ADD_AUTH_TABLES_SQLITE
from services.organization.router import router as org_router
from services.organization.router import departments_router
from services.organization.models import (
    ADD_ORG_TABLES_POSTGRES, ADD_ORG_TABLES_SQLITE,
    ADD_ORG_COLUMN_TO_JOBS_SQLITE
)
from services.recruitment.router import router as recruitment_router
from services.people.router import router as people_router
from services.identity.models import (
    ADD_AUTH_TABLES, ADD_AUTH_TABLES_SQLITE,
    ADD_PERSONS_TABLES_POSTGRES, ADD_PERSONS_TABLES_SQLITE,
    ADD_PERSON_ID_TO_APPLICATIONS_POSTGRES,
    ADD_PERSON_ID_TO_APPLICATIONS_SQLITE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


DOMAIN_EVENTS_POSTGRES = """
CREATE TABLE IF NOT EXISTS domain_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   UUID,
    event_type  VARCHAR(100) NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    processed   BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMPTZ,
    error       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_events_type ON domain_events(event_type);
"""

DOMAIN_EVENTS_SQLITE = """
CREATE TABLE IF NOT EXISTS domain_events (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tenant_id   TEXT,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    processed   INTEGER DEFAULT 0,
    processed_at TEXT,
    error       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_type ON domain_events(event_type);
"""


def run_single_migration(stmt: str):
    """Run a single migration statement in its own connection so failures don't block others."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(stmt)
        return True
    except Exception as e:
        log.warning(f"Migration skipped: {str(e)[:100]}")
        return False


def run_migrations():
    """Run all service migrations. Each statement runs in isolation."""

    # Collect all statements
    schemas = []

    # 1. Identity tables
    schemas.append(ADD_AUTH_TABLES if USE_POSTGRES else ADD_AUTH_TABLES_SQLITE)

    # 2. Organization tables
    schemas.append(ADD_ORG_TABLES_POSTGRES if USE_POSTGRES else ADD_ORG_TABLES_SQLITE)

    # 3. Domain events
    schemas.append(DOMAIN_EVENTS_POSTGRES if USE_POSTGRES else DOMAIN_EVENTS_SQLITE)

    # Run all schema statements
    for schema in schemas:
        for stmt in schema.strip().split(";"):
            s = stmt.strip()
            if s:
                run_single_migration(s)

    # 4. Persons tables (Push 3 - unified people layer)
    schema = ADD_PERSONS_TABLES_POSTGRES if USE_POSTGRES else ADD_PERSONS_TABLES_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 5. Link applications to persons (nullable - existing data safe)
    if USE_POSTGRES:
        run_single_migration(ADD_PERSON_ID_TO_APPLICATIONS_POSTGRES.strip())
    else:
        run_single_migration(ADD_PERSON_ID_TO_APPLICATIONS_SQLITE.strip())

    # 6. Add new columns safely (each in own connection)
    if USE_POSTGRES:
        column_migrations = [
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS slug VARCHAR(255)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS logo_url TEXT",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id)",
            "CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(organization_id)",
        ]
        for stmt in column_migrations:
            run_single_migration(stmt)
    else:
        # SQLite - try adding columns
        run_single_migration("ALTER TABLE organizations ADD COLUMN slug TEXT")
        run_single_migration("ALTER TABLE organizations ADD COLUMN logo_url TEXT")
        run_single_migration(ADD_ORG_COLUMN_TO_JOBS_SQLITE.strip())

    log.info("All migrations complete")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "./jobstream.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        init_db()
        run_migrations()
        log.info("Database ready")
    except Exception as e:
        log.error(f"Database init failed: {e}")
        raise

    from services.recruitment.tasks import run_scheduled_scrape
    scheduler.add_job(run_scheduled_scrape, "interval", hours=2, id="auto_scrape")
    scheduler.start()
    log.info("Scheduler started")
    yield
    scheduler.shutdown()


app = FastAPI(
    title="JobStream API",
    description="Workforce Operating System — Recruitment Module",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(identity_router)       # /auth/*
app.include_router(org_router)            # /organizations/*
app.include_router(departments_router)    # /departments
app.include_router(recruitment_router)    # /jobs /applications /scrape /companies
app.include_router(people_router)         # /persons/*


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "modules": ["identity", "organization", "recruitment", "people"],
        "time": datetime.utcnow().isoformat(),
    }


# ── Candidate Profile (Phase 2) ───────────────────────────────────────────────

class ProfileIn(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    skills: Optional[list] = None
    linkedin_url: Optional[str] = None
    resume_url: Optional[str] = None
    years_experience: Optional[int] = None


@app.get("/profile/me")
async def get_my_profile(current_user: dict = Depends(get_current_user)):
    import json
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM candidate_profiles WHERE user_id = %s" if USE_POSTGRES
            else "SELECT * FROM candidate_profiles WHERE user_id = ?",
            (str(current_user["id"]),)
        )
        row = cur.fetchone()
        if not row:
            return {}
        data = dict(row)
        if data.get("skills") and isinstance(data["skills"], str):
            try:
                data["skills"] = json.loads(data["skills"])
            except Exception:
                data["skills"] = []
        return data


@app.put("/profile/me")
async def update_my_profile(
    body: ProfileIn,
    current_user: dict = Depends(get_current_user),
):
    import json
    user_id = str(current_user["id"])
    skills_json = json.dumps(body.skills or [])

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO candidate_profiles
                    (user_id, full_name, phone, location, bio, skills,
                     linkedin_url, resume_url, years_experience)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (user_id) DO UPDATE SET
                    full_name=EXCLUDED.full_name, phone=EXCLUDED.phone,
                    location=EXCLUDED.location, bio=EXCLUDED.bio,
                    skills=EXCLUDED.skills, linkedin_url=EXCLUDED.linkedin_url,
                    resume_url=EXCLUDED.resume_url,
                    years_experience=EXCLUDED.years_experience,
                    updated_at=NOW()
            """, (user_id, body.full_name, body.phone, body.location,
                  body.bio, skills_json, body.linkedin_url,
                  body.resume_url, body.years_experience))
        else:
            cur.execute("""
                INSERT INTO candidate_profiles
                    (user_id, full_name, phone, location, bio, skills,
                     linkedin_url, resume_url, years_experience)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT (user_id) DO UPDATE SET
                    full_name=excluded.full_name, phone=excluded.phone,
                    location=excluded.location, bio=excluded.bio,
                    skills=excluded.skills, linkedin_url=excluded.linkedin_url,
                    resume_url=excluded.resume_url,
                    years_experience=excluded.years_experience
            """, (user_id, body.full_name, body.phone, body.location,
                  body.bio, skills_json, body.linkedin_url,
                  body.resume_url, body.years_experience))

    if body.full_name:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("UPDATE users SET full_name=%s WHERE id=%s", (body.full_name, user_id))
            else:
                cur.execute("UPDATE users SET full_name=? WHERE id=?", (body.full_name, user_id))

    return {"message": "Profile saved"}
