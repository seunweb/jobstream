# ── Serve built React frontend from FastAPI (same domain = no CORS) ──────────
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pathlib as _pathlib

_DIST = _pathlib.Path(__file__).parent.parent / "dist"

"""
JobStream API v2.0 — Modular Architecture
Modules: Identity, Organization, Recruitment
All existing endpoints preserved — zero breaking changes.
"""

import sys
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

# ── Windows: Playwright requires ProactorEventLoop ────────────────────────────
# SelectorEventLoop (Windows default) does not support subprocesses.
# Must be set before any asyncio usage.
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES, init_db
from core.security import SecurityHeadersMiddleware, get_cors_origins
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
from services.recruitment.seo_router import router as seo_router
from services.people.router import router as people_router
from services.identity.rbac_router import router as rbac_router
from services.identity.admin_router import platform_router, tenant_router
from services.identity.ai_router import router as ai_router
from services.identity.billing_router import router as billing_router
from services.identity.analytics_router import router as analytics_router
from services.identity.rbac_models import (
    RBAC_TABLES_POSTGRES, RBAC_TABLES_SQLITE,
    seed_system_roles_and_permissions,
)
from services.identity.models import (
    ADD_AUTH_TABLES, ADD_AUTH_TABLES_SQLITE,
    ADD_PERSONS_TABLES_POSTGRES, ADD_PERSONS_TABLES_SQLITE,
    ADD_PERSON_ID_TO_APPLICATIONS_POSTGRES,
    ADD_PERSON_ID_TO_APPLICATIONS_SQLITE,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


SAVED_JOBS_POSTGRES = """
CREATE TABLE IF NOT EXISTS saved_jobs (
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    job_id      INTEGER,
    saved_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_saved_jobs_user ON saved_jobs(user_id);
"""

SAVED_JOBS_SQLITE = """
CREATE TABLE IF NOT EXISTS saved_jobs (
    user_id     TEXT,
    job_id      INTEGER,
    saved_at    TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, job_id)
);
CREATE INDEX IF NOT EXISTS idx_saved_jobs_user ON saved_jobs(user_id);
"""

TENANTS_POSTGRES = """
CREATE TABLE IF NOT EXISTS tenants (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) UNIQUE NOT NULL,
    plan            VARCHAR(50) DEFAULT 'free',
    status          VARCHAR(20) DEFAULT 'active',
    logo_url        TEXT,
    primary_color   VARCHAR(7),
    custom_domain   VARCHAR(255),
    settings        JSONB DEFAULT '{}',
    ai_settings     JSONB DEFAULT '{}',
    country         VARCHAR(2) DEFAULT 'NG',
    timezone        VARCHAR(50) DEFAULT 'Africa/Lagos',
    currency        VARCHAR(3) DEFAULT 'NGN',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tenants_slug   ON tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenants_domain ON tenants(custom_domain);
"""

TENANTS_SQLITE = """
CREATE TABLE IF NOT EXISTS tenants (
    id              TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    name            TEXT NOT NULL,
    slug            TEXT UNIQUE NOT NULL,
    plan            TEXT DEFAULT 'free',
    status          TEXT DEFAULT 'active',
    logo_url        TEXT,
    primary_color   TEXT,
    custom_domain   TEXT,
    settings        TEXT DEFAULT '{}',
    ai_settings     TEXT DEFAULT '{}',
    country         TEXT DEFAULT 'NG',
    timezone        TEXT DEFAULT 'Africa/Lagos',
    currency        TEXT DEFAULT 'NGN',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tenants_slug ON tenants(slug);
"""

AUDIT_LOGS_POSTGRES = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID,
    user_id         UUID,
    action          VARCHAR(100) NOT NULL,
    module          VARCHAR(50) NOT NULL DEFAULT 'platform',
    resource_type   VARCHAR(50),
    resource_id     TEXT,
    old_value       JSONB,
    new_value       JSONB,
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant_time  ON audit_logs(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user_time    ON audit_logs(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action       ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_resource     ON audit_logs(resource_type, resource_id);
"""

AUDIT_LOGS_SQLITE = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id       TEXT,
    user_id         TEXT,
    action          TEXT NOT NULL,
    module          TEXT NOT NULL DEFAULT 'platform',
    resource_type   TEXT,
    resource_id     TEXT,
    old_value       TEXT,
    new_value       TEXT,
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_user_time ON audit_logs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_action    ON audit_logs(action);
"""

ADMIN_TABLES_POSTGRES = """
CREATE TABLE IF NOT EXISTS admin_industries (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS alert_delivery_log (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id   TEXT NOT NULL,
    email      TEXT NOT NULL,
    keywords   TEXT,
    jobs_count INTEGER DEFAULT 0,
    sent_at    TIMESTAMPTZ DEFAULT NOW(),
    opened_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_adl_alert ON alert_delivery_log(alert_id);
CREATE INDEX IF NOT EXISTS idx_adl_sent  ON alert_delivery_log(sent_at);
"""

ADMIN_TABLES_SQLITE = """
CREATE TABLE IF NOT EXISTS admin_industries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admin_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_delivery_log (
    id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    alert_id   TEXT NOT NULL,
    email      TEXT NOT NULL,
    keywords   TEXT,
    jobs_count INTEGER DEFAULT 0,
    sent_at    TEXT DEFAULT (datetime('now')),
    opened_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_adl_alert ON alert_delivery_log(alert_id);
"""

BILLING_TABLES_POSTGRES = """
CREATE TABLE IF NOT EXISTS subscription_plans (
    id          VARCHAR(50) PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    type        VARCHAR(20) NOT NULL,
    price_ngn   INTEGER DEFAULT 0,
    interval    VARCHAR(20),
    features    JSONB DEFAULT '[]',
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE,
    plan_id             VARCHAR(50),
    status              VARCHAR(20) DEFAULT 'active',
    started_at          TIMESTAMPTZ DEFAULT NOW(),
    expires_at          TIMESTAMPTZ,
    cancelled_at        TIMESTAMPTZ,
    paystack_reference  VARCHAR(100),
    paystack_sub_code   VARCHAR(100),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS billing_transactions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    plan_id     VARCHAR(50),
    amount      INTEGER NOT NULL,
    currency    VARCHAR(3) DEFAULT 'NGN',
    status      VARCHAR(20) DEFAULT 'pending',
    reference   VARCHAR(100) UNIQUE,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_subs_user    ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_txn_user     ON billing_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_txn_ref      ON billing_transactions(reference);
"""

BILLING_TABLES_SQLITE = """
CREATE TABLE IF NOT EXISTS subscription_plans (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    price_ngn   INTEGER DEFAULT 0,
    interval    TEXT,
    features    TEXT DEFAULT '[]',
    is_active   INTEGER DEFAULT 1,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id             TEXT REFERENCES users(id) ON DELETE CASCADE,
    plan_id             TEXT,
    status              TEXT DEFAULT 'active',
    started_at          TEXT DEFAULT (datetime('now')),
    expires_at          TEXT,
    cancelled_at        TEXT,
    paystack_reference  TEXT,
    paystack_sub_code   TEXT,
    created_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS billing_transactions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id     TEXT REFERENCES users(id) ON DELETE CASCADE,
    plan_id     TEXT,
    amount      INTEGER NOT NULL,
    currency    TEXT DEFAULT 'NGN',
    status      TEXT DEFAULT 'pending',
    reference   TEXT UNIQUE,
    metadata    TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_txn_ref   ON billing_transactions(reference);
"""

JOB_ALERTS_POSTGRES = """
CREATE TABLE IF NOT EXISTS job_alerts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id) ON DELETE CASCADE,
    email               VARCHAR(255) NOT NULL,
    keywords            TEXT NOT NULL,
    location            VARCHAR(255) NOT NULL DEFAULT '',
    industry            VARCHAR(100),
    job_type            VARCHAR(50),
    frequency           VARCHAR(20) DEFAULT 'daily',
    send_time           VARCHAR(5) DEFAULT '08:00',
    unsubscribe_token   UUID DEFAULT gen_random_uuid(),
    is_active           BOOLEAN DEFAULT TRUE,
    last_sent_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(email, keywords, location)
);
CREATE INDEX IF NOT EXISTS idx_alerts_email  ON job_alerts(email);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON job_alerts(is_active);
CREATE INDEX IF NOT EXISTS idx_alerts_user   ON job_alerts(user_id);
"""

JOB_ALERTS_SQLITE = """
CREATE TABLE IF NOT EXISTS job_alerts (
    id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    user_id             TEXT REFERENCES users(id) ON DELETE CASCADE,
    email               TEXT NOT NULL,
    keywords            TEXT NOT NULL,
    location            TEXT NOT NULL DEFAULT '',
    industry            TEXT,
    job_type            TEXT,
    frequency           TEXT DEFAULT 'daily',
    send_time           TEXT DEFAULT '08:00',
    unsubscribe_token   TEXT DEFAULT (lower(hex(randomblob(16)))),
    is_active           INTEGER DEFAULT 1,
    last_sent_at        TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(email, keywords, location)
);
CREATE INDEX IF NOT EXISTS idx_alerts_email ON job_alerts(email);
CREATE INDEX IF NOT EXISTS idx_alerts_user  ON job_alerts(user_id);
"""

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

    # 3b. Tenants table
    schema = TENANTS_POSTGRES if USE_POSTGRES else TENANTS_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 3c. Add tenant_id to users and organizations
    if USE_POSTGRES:
        run_single_migration("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id)")
        run_single_migration("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id)")
        run_single_migration("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id)")
        run_single_migration("ALTER TABLE applications ADD COLUMN IF NOT EXISTS tenant_id UUID REFERENCES tenants(id)")
        run_single_migration("CREATE INDEX IF NOT EXISTS idx_users_tenant ON users(tenant_id)")
        run_single_migration("CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON jobs(tenant_id)")
    else:
        run_single_migration("ALTER TABLE users ADD COLUMN tenant_id TEXT")
        run_single_migration("ALTER TABLE organizations ADD COLUMN tenant_id_v2 TEXT")
        run_single_migration("ALTER TABLE jobs ADD COLUMN tenant_id TEXT")
        run_single_migration("ALTER TABLE applications ADD COLUMN tenant_id TEXT")

    # 3b. Admin tables
    schema = ADMIN_TABLES_POSTGRES if USE_POSTGRES else ADMIN_TABLES_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 3c. Billing tables
    schema = BILLING_TABLES_POSTGRES if USE_POSTGRES else BILLING_TABLES_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 3d. Job alerts table
    schema = JOB_ALERTS_POSTGRES if USE_POSTGRES else JOB_ALERTS_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 3e. Job alerts — add new columns to existing tables (idempotent)
    if USE_POSTGRES:
        for stmt in [
            "ALTER TABLE job_alerts ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
            "ALTER TABLE job_alerts ADD COLUMN IF NOT EXISTS industry VARCHAR(100)",
            "ALTER TABLE job_alerts ADD COLUMN IF NOT EXISTS send_time VARCHAR(5) DEFAULT '08:00'",
            "ALTER TABLE job_alerts ALTER COLUMN location SET DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_alerts_user ON job_alerts(user_id)",
        ]:
            run_single_migration(stmt)
    else:
        for stmt in [
            "ALTER TABLE job_alerts ADD COLUMN user_id TEXT",
            "ALTER TABLE job_alerts ADD COLUMN industry TEXT",
            "ALTER TABLE job_alerts ADD COLUMN send_time TEXT DEFAULT '08:00'",
        ]:
            run_single_migration(stmt)

    # 4. Audit logs table
    schema = AUDIT_LOGS_POSTGRES if USE_POSTGRES else AUDIT_LOGS_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 5. Saved jobs table
    schema = SAVED_JOBS_POSTGRES if USE_POSTGRES else SAVED_JOBS_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 5. RBAC tables (Phase 7)
    schema = RBAC_TABLES_POSTGRES if USE_POSTGRES else RBAC_TABLES_SQLITE
    for stmt in schema.strip().split(";"):
        s = stmt.strip()
        if s:
            run_single_migration(s)

    # 6. Persons tables (Push 3 - unified people layer)
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
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'scraped'",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS slug VARCHAR(255)",
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS logo_url TEXT",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id)",
            "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS source VARCHAR(20) DEFAULT 'scraped'",
            "CREATE INDEX IF NOT EXISTS idx_orgs_slug ON organizations(slug)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_org ON jobs(organization_id)",
            # Phase 4 — MFA columns
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret TEXT",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_login_attempts INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ",
            # Phase 4 — sessions enrichment
            "ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_active_at TIMESTAMPTZ DEFAULT NOW()",
        ]
        for stmt in column_migrations:
            run_single_migration(stmt)
    else:
        # SQLite - try adding columns
        run_single_migration("ALTER TABLE organizations ADD COLUMN slug TEXT")
        run_single_migration("ALTER TABLE organizations ADD COLUMN logo_url TEXT")
        run_single_migration("ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT 'scraped'")
        run_single_migration(ADD_ORG_COLUMN_TO_JOBS_SQLITE.strip())
        # Phase 4 — MFA columns
        run_single_migration("ALTER TABLE users ADD COLUMN mfa_enabled INTEGER DEFAULT 0")
        run_single_migration("ALTER TABLE users ADD COLUMN mfa_secret TEXT")
        run_single_migration("ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER DEFAULT 0")
        run_single_migration("ALTER TABLE users ADD COLUMN locked_until TEXT")
        run_single_migration("ALTER TABLE sessions ADD COLUMN last_active_at TEXT")

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

    # Seed system roles and permissions
    try:
        seed_system_roles_and_permissions()
    except Exception as e:
        log.warning(f"RBAC seed failed (may already exist): {e}")

    from services.recruitment.tasks import run_scheduled_scrape
    from core.database import get_conn, USE_POSTGRES

    # Load admin-configured interval (default 4 hours)
    def _get_scrape_interval_hours() -> int:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                ph = "%s" if USE_POSTGRES else "?"
                cur.execute(
                    f"SELECT value FROM admin_settings WHERE key = {ph}",
                    ("scrape_interval_hours",)
                )
                row = cur.fetchone()
                if row:
                    return max(1, int(dict(row)["value"]))
        except Exception:
            pass
        return 4  # default 4 hours

    interval_hours = _get_scrape_interval_hours()
    log.info(f"Streamer interval: every {interval_hours} hour(s)")
    scheduler.add_job(run_scheduled_scrape, "interval", hours=interval_hours, id="auto_scrape")
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

# Hardened CORS — only allow known origins
# Build allowed origins — always include wildcard fallback for Railway
_cors_origins = get_cors_origins()
# Ensure both Railway services can talk to each other
_extra_origins = os.environ.get("ALLOWED_ORIGINS", "")
if _extra_origins:
    for _o in _extra_origins.split(","):
        _o = _o.strip().rstrip("/")
        if _o and _o not in _cors_origins:
            _cors_origins.append(_o)

# Also add APP_URL variants (with and without trailing slash)
_app_url = os.environ.get("APP_URL", "").rstrip("/")
if _app_url and _app_url not in _cors_origins:
    _cors_origins.append(_app_url)

import logging as _logging
_logging.getLogger(__name__).info(f"CORS origins: {_cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=r"https://.*\.up\.railway\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Cron-Secret"],
)

# Security headers on every response
app.add_middleware(SecurityHeadersMiddleware)

# Register all routers
app.include_router(identity_router)       # /auth/*
app.include_router(org_router)            # /organizations/*
app.include_router(departments_router)    # /departments
app.include_router(recruitment_router)    # /jobs /applications /scrape /companies
app.include_router(people_router)         # /persons/*
app.include_router(seo_router)            # /jobs/slug, /sitemap, /job-alerts
app.include_router(ai_router)             # /ai/*
app.include_router(billing_router)        # /billing/*
app.include_router(analytics_router)      # /analytics/*
app.include_router(rbac_router)           # /rbac/*
app.include_router(platform_router)       # /admin/*
app.include_router(tenant_router)         # /workspace/*


# ── Audit Log API ────────────────────────────────────────────────────────────

from core.audit import get_audit_logs, AuditAction

@app.get("/audit/logs")
async def query_audit_logs(
    user_id: Optional[str] = None,
    action: str = None,
    resource_type: str = None,
    module: str = None,
    limit: int = 50,
    offset: int = 0,
    current_user: dict = Depends(get_current_user),
):
    """Query audit logs — admin only."""
    if current_user.get("role") not in ("super_admin", "admin"):
        raise HTTPException(403, "Admin access required")
    return get_audit_logs(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        module=module,
        limit=min(limit, 200),
        offset=offset,
    )

@app.get("/audit/my-logs")
async def my_audit_logs(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """Get audit logs for the current user."""
    return get_audit_logs(
        user_id=str(current_user["id"]),
        limit=min(limit, 100),
    )


# ── Tenant Onboarding ─────────────────────────────────────────────────────────

from core.tenant import create_tenant, link_user_to_tenant, PLAN_LIMITS

class TenantOnboardIn(BaseModel):
    name: str
    slug: str
    country: Optional[str] = "NG"
    currency: Optional[str] = "NGN"


@app.post("/tenants/onboard", status_code=201)
async def onboard_tenant(
    body: TenantOnboardIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new tenant workspace and link current user as owner.
    Called when an employer registers their organization.
    """
    from core.audit import log_action, AuditAction
    import re

    # Validate slug
    slug = body.slug.lower().strip().replace(" ", "-")
    if not re.match(r'^[a-z0-9-]+$', slug):
        raise HTTPException(400, "Slug can only contain lowercase letters, numbers and hyphens")

    try:
        tenant = create_tenant(
            name=body.name,
            slug=slug,
            country=body.country,
            currency=body.currency,
        )
        link_user_to_tenant(str(current_user["id"]), tenant["id"], "org_owner")
        log_action(
            "tenant.created",
            user_id=str(current_user["id"]),
            resource_type="tenant",
            resource_id=tenant["id"],
            new_value={"name": body.name, "slug": slug},
            module="organization",
        )
        return {"message": "Workspace created", "tenant": tenant}
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(400, f"Slug '{slug}' is already taken. Try a different one.")
        raise HTTPException(500, f"Failed to create workspace: {str(e)}")


@app.get("/tenants/me")
async def get_my_tenant(current_user: dict = Depends(get_current_user)):
    """Get the tenant workspace for the current user."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        return {"tenant": None, "message": "No workspace. Create one via POST /tenants/onboard"}
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM tenants WHERE id = %s" if USE_POSTGRES
            else "SELECT * FROM tenants WHERE id = ?",
            (tenant_id,)
        )
        row = cur.fetchone()
        if not row:
            return {"tenant": None}
        tenant = dict(row)
        limits = PLAN_LIMITS.get(tenant.get("plan", "free"), PLAN_LIMITS["free"])
        return {"tenant": tenant, "limits": limits}


@app.patch("/tenants/me")
async def update_tenant_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Update tenant settings — logo, branding, AI settings."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No workspace found")

    body = await request.json()
    allowed = {"name", "logo_url", "primary_color", "custom_domain",
               "settings", "ai_settings", "timezone", "currency"}
    updates = {k: v for k, v in body.items() if k in allowed}

    if not updates:
        raise HTTPException(400, "No valid fields to update")

    import json as json_lib
    set_clauses = []
    params = []
    for k, v in updates.items():
        if k in ("settings", "ai_settings") and isinstance(v, dict):
            v = json_lib.dumps(v)
        set_clauses.append(f"{k} = {'%s' if USE_POSTGRES else '?'}")
        params.append(v)

    if USE_POSTGRES:
        set_clauses.append("updated_at = NOW()")
        params.append(tenant_id)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE tenants SET {', '.join(set_clauses)} WHERE id = %s",
                params
            )
    else:
        set_clauses.append("updated_at = datetime('now')")
        params.append(tenant_id)
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE tenants SET {', '.join(set_clauses)} WHERE id = ?",
                params
            )

    return {"message": "Settings updated"}


@app.get("/tenants/check-slug/{slug}")
async def check_slug(slug: str):
    """Check if a tenant slug is available."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM tenants WHERE slug = %s" if USE_POSTGRES
            else "SELECT id FROM tenants WHERE slug = ?",
            (slug.lower(),)
        )
        exists = cur.fetchone() is not None
    return {"slug": slug, "available": not exists}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "modules": ["identity", "organization", "recruitment", "people", "rbac", "admin", "seo", "ai", "billing", "analytics"],
        "security": ["rate_limiting", "account_lockout", "security_headers", "mfa"],
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


# ── Serve React SPA from FastAPI (same domain = zero CORS) ──────────────────
if _DIST.exists():
    # Serve /assets/* statically
    app.mount("/assets", StaticFiles(directory=str(_DIST / "assets")), name="assets")
    log.info(f"Serving React frontend from {_DIST}")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Catch-all: return index.html for any non-API path (React Router)."""
        # Let actual API routes 404 normally
        api_prefixes = (
            "auth/", "jobs", "companies", "organizations", "applications",
            "scrape", "billing", "analytics", "ai/", "rbac/", "admin/",
            "workspace/", "persons/", "departments", "job-alerts", "track/",
            "sitemap", "health", "docs", "openapi", "redoc",
        )
        if any(full_path.startswith(p) for p in api_prefixes):
            from fastapi import HTTPException
            raise HTTPException(404)
        return FileResponse(str(_DIST / "index.html"))
else:
    log.info(f"No dist/ folder found at {_DIST} — frontend served separately")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True,
                loop="asyncio")
