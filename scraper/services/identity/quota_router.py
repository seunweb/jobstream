"""
Quota & Feature Flag System
- Enforces plan limits (active jobs, featured slots, team seats, job credits)
- Tracks usage per tenant
- Feature flags control access to platform features
- Admin can override any tenant's limits/features
"""

import json, logging, uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user
from services.identity.admin_router import require_platform_admin

log = logging.getLogger(__name__)
router = APIRouter(prefix="/quota", tags=["quota"])

# ── Default feature sets per plan type ───────────────────────────────────────

DEFAULT_FREE_LIMITS = {
    "active_jobs": 2,
    "featured_slots": 0,
    "team_seats": 1,
    "job_credits": None,       # None = subscription-based (not credit-based)
    "applications_per_job": 50,
}

DEFAULT_FREE_FEATURES = {
    "post_jobs": True,
    "featured_jobs": False,
    "applications_dashboard": True,
    "applications_export": False,
    "team_management": False,
    "analytics": False,
    "candidate_database": False,
    "custom_branding": False,
    "api_access": False,
    "ai_screening": False,
    "priority_support": False,
    "duplicate_jobs": True,
    "draft_jobs": True,
}

# Candidate plan feature defaults
DEFAULT_CANDIDATE_FREE_FEATURES = {
    "apply_jobs": True,
    "save_jobs": True,
    "basic_profile": True,
    "track_applications": True,
    "unlimited_saves": False,
    "ai_cv": False,
    "ai_job_match": False,
    "ai_cover_letter": False,
    "ai_interview": False,
    "priority_visibility": False,
    "advanced_search": False,
    "salary_insights": False,
    "recruiter_contact": False,
    "profile_boost": False,
}

DEFAULT_CANDIDATE_FREE_LIMITS = {
    "saved_jobs": 10,
    "applications_per_month": None,  # unlimited
    "profile_views": None,
}

# ── DB migration ──────────────────────────────────────────────────────────────

_quota_migrated = False

def _ensure_quota_tables():
    global _quota_migrated
    if _quota_migrated:
        return
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tenant_quotas (
                        tenant_id       TEXT PRIMARY KEY,
                        plan_id         TEXT DEFAULT 'free',
                        plan_type       TEXT DEFAULT 'free',
                        -- Limits (None = unlimited)
                        active_jobs     INTEGER DEFAULT 2,
                        featured_slots  INTEGER DEFAULT 0,
                        team_seats      INTEGER DEFAULT 1,
                        job_credits     INTEGER DEFAULT NULL,
                        credits_used    INTEGER DEFAULT 0,
                        applications_per_job INTEGER DEFAULT 50,
                        -- Feature flags
                        features        JSONB DEFAULT '{}',
                        -- Override (admin can set custom limits)
                        is_overridden   BOOLEAN DEFAULT FALSE,
                        override_note   TEXT DEFAULT '',
                        -- Subscription info
                        subscription_id TEXT,
                        expires_at      TIMESTAMP,
                        updated_at      TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS job_credits_log (
                        id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id   TEXT NOT NULL,
                        user_id     TEXT,
                        job_id      INTEGER,
                        action      TEXT,  -- 'used', 'refunded', 'purchased', 'expired'
                        credits     INTEGER DEFAULT 1,
                        note        TEXT,
                        created_at  TIMESTAMP DEFAULT NOW()
                    )
                """)
            else:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tenant_quotas (
                        tenant_id TEXT PRIMARY KEY,
                        plan_id TEXT DEFAULT 'free', plan_type TEXT DEFAULT 'free',
                        active_jobs INTEGER DEFAULT 2, featured_slots INTEGER DEFAULT 0,
                        team_seats INTEGER DEFAULT 1, job_credits INTEGER,
                        credits_used INTEGER DEFAULT 0, applications_per_job INTEGER DEFAULT 50,
                        features TEXT DEFAULT '{}', is_overridden INTEGER DEFAULT 0,
                        override_note TEXT DEFAULT '', subscription_id TEXT,
                        expires_at TEXT, updated_at TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS job_credits_log (
                        id TEXT PRIMARY KEY, tenant_id TEXT, user_id TEXT,
                        job_id INTEGER, action TEXT, credits INTEGER DEFAULT 1,
                        note TEXT, created_at TEXT
                    )
                """)
        _quota_migrated = True
    except Exception as e:
        log.warning(f"Quota migration skipped: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _j(val, default=None):
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val) if val else (default or {})
    except Exception:
        return default or {}


def get_tenant_quota(tenant_id: str) -> dict:
    """Get quota and feature flags for a tenant. Creates free quota if missing."""
    _ensure_quota_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT * FROM tenant_quotas WHERE tenant_id = {ph}", (str(tenant_id),))
        row = cur.fetchone()
        if row:
            q = dict(row)
            q["features"] = _j(q.get("features"), DEFAULT_FREE_FEATURES)
            return q

    # No quota record — create free tier
    features = {**DEFAULT_FREE_FEATURES}
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO tenant_quotas
                    (tenant_id, plan_id, plan_type, active_jobs, featured_slots,
                     team_seats, job_credits, credits_used, applications_per_job,
                     features, updated_at)
                VALUES (%s,'free','free',2,0,1,NULL,0,50,%s,NOW())
                ON CONFLICT (tenant_id) DO NOTHING
            """, (str(tenant_id), json.dumps(features)))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO tenant_quotas
                    (tenant_id, plan_id, plan_type, active_jobs, featured_slots,
                     team_seats, job_credits, credits_used, applications_per_job,
                     features, updated_at)
                VALUES (?,?,?,2,0,1,NULL,0,50,?,?)
            """, (str(tenant_id), 'free', 'free', json.dumps(features), now))

    return {
        "tenant_id": str(tenant_id),
        "plan_id": "free", "plan_type": "free",
        "active_jobs": 2, "featured_slots": 0,
        "team_seats": 1, "job_credits": None, "credits_used": 0,
        "applications_per_job": 50,
        "features": features,
        "is_overridden": False,
    }


def apply_plan_to_tenant(tenant_id: str, plan_id: str, plan: dict,
                          duration_id: str = "monthly", expires_at: str = None):
    """Apply a plan's limits and features to a tenant after payment."""
    _ensure_quota_tables()
    limits = _j(plan.get("limits"), {})
    features = _j(plan.get("features"), {})

    # Merge with defaults
    merged_features = {**DEFAULT_FREE_FEATURES, **features}
    if isinstance(plan.get("features"), list):
        # features stored as list of strings — convert to flags
        merged_features = {**DEFAULT_FREE_FEATURES}
        for f in plan["features"]:
            key = f.lower().replace(" ", "_").replace("-","_")
            merged_features[key] = True

    plan_type = plan.get("type", "employer")
    # Determine if credit-based or subscription
    durations = _j(plan.get("durations"), [])
    dur = next((d for d in durations if d.get("id") == duration_id), {})
    is_credit = plan_type == "credit" or limits.get("job_credits") is not None

    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO tenant_quotas
                    (tenant_id, plan_id, plan_type, active_jobs, featured_slots,
                     team_seats, job_credits, credits_used, applications_per_job,
                     features, subscription_id, expires_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,0,%s,%s,NULL,%s,NOW())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    plan_id=EXCLUDED.plan_id, plan_type=EXCLUDED.plan_type,
                    active_jobs=EXCLUDED.active_jobs, featured_slots=EXCLUDED.featured_slots,
                    team_seats=EXCLUDED.team_seats, job_credits=EXCLUDED.job_credits,
                    credits_used=CASE WHEN billing_plans.type='credit'
                                 THEN tenant_quotas.credits_used ELSE 0 END,
                    applications_per_job=EXCLUDED.applications_per_job,
                    features=EXCLUDED.features, expires_at=EXCLUDED.expires_at,
                    updated_at=NOW()
            """, (
                str(tenant_id), plan_id, plan_type,
                limits.get("active_jobs", 5),
                limits.get("featured_slots", 0),
                limits.get("team_seats", 1),
                limits.get("job_credits"),
                limits.get("applications_per_job", 100),
                json.dumps(merged_features),
                expires_at,
            ))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO tenant_quotas
                    (tenant_id, plan_id, plan_type, active_jobs, featured_slots,
                     team_seats, job_credits, credits_used, applications_per_job,
                     features, subscription_id, expires_at, updated_at)
                VALUES (?,?,?,?,?,?,?,0,?,?,NULL,?,?)
            """, (
                str(tenant_id), plan_id, plan_type,
                limits.get("active_jobs", 5),
                limits.get("featured_slots", 0),
                limits.get("team_seats", 1),
                limits.get("job_credits"),
                limits.get("applications_per_job", 100),
                json.dumps(merged_features),
                expires_at, now,
            ))
    log.info(f"Plan applied: tenant={tenant_id} plan={plan_id} expires={expires_at}")


def check_feature(tenant_id: str, feature: str) -> bool:
    """Returns True if tenant has access to a feature."""
    if not tenant_id:
        return False
    quota = get_tenant_quota(str(tenant_id))
    features = quota.get("features", {})
    return bool(features.get(feature, False))


def check_job_quota(tenant_id: str) -> dict:
    """Check if tenant can post more jobs."""
    quota = get_tenant_quota(str(tenant_id))
    plan_type = quota.get("plan_type", "free")

    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(
            f"SELECT COUNT(*) FROM jobs WHERE tenant_id = {ph} AND source = 'manual' AND is_active = 1",
            (str(tenant_id),)
        )
        active_jobs = int(list(dict(cur.fetchone()).values())[0] or 0)

    limit = quota.get("active_jobs")
    credits = quota.get("job_credits")
    credits_used = quota.get("credits_used", 0)
    remaining = None

    if credits is not None:
        # Credit-based plan
        remaining = credits - credits_used
        can_post = remaining > 0
    elif limit is not None:
        # Subscription with active job limit
        remaining = limit - active_jobs
        can_post = active_jobs < limit
    else:
        can_post = True

    return {
        "can_post": can_post,
        "active_jobs": active_jobs,
        "limit": limit,
        "credits": credits,
        "credits_used": credits_used,
        "remaining": remaining,
        "plan_id": quota.get("plan_id","free"),
    }


def use_job_credit(tenant_id: str, user_id: str, job_id: int):
    """Deduct one job credit when a job is posted (credit-based plans only)."""
    _ensure_quota_tables()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(
            f"UPDATE tenant_quotas SET credits_used = credits_used + 1, updated_at = {'NOW()' if USE_POSTGRES else ph} WHERE tenant_id = {ph}",
            (() if USE_POSTGRES else (now,)) + (str(tenant_id),)
        )
        log_id = str(uuid.uuid4())
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO job_credits_log(id,tenant_id,user_id,job_id,action,credits,created_at)
                VALUES(gen_random_uuid()::text,%s,%s,%s,'used',1,NOW())
            """, (str(tenant_id), str(user_id), job_id))
        else:
            cur.execute("""
                INSERT INTO job_credits_log(id,tenant_id,user_id,job_id,action,credits,created_at)
                VALUES(?,?,?,?,'used',1,?)
            """, (log_id, str(tenant_id), str(user_id), job_id, now))


# ── API Endpoints ─────────────────────────────────────────────────────────────

@router.get("/my")
async def my_quota(current_user: dict = Depends(get_current_user)):
    """Get current user's quota and usage."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        return {
            "plan_id": "free", "plan_type": "free",
            "active_jobs": 0, "limit": 2, "credits": None,
            "featured_slots": 0, "team_seats": 1,
            "features": DEFAULT_FREE_FEATURES,
            "can_post": True, "remaining": 2,
        }

    quota = get_tenant_quota(str(tenant_id))
    job_status = check_job_quota(str(tenant_id))

    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        # Count active featured jobs
        cur.execute(
            f"SELECT COUNT(*) FROM jobs WHERE tenant_id = {ph} AND source='manual' AND is_featured = TRUE AND is_active = 1"
            if USE_POSTGRES else
            f"SELECT COUNT(*) FROM jobs WHERE tenant_id = {ph} AND source='manual' AND is_featured = 1 AND is_active = 1",
            (str(tenant_id),)
        )
        active_featured = int(list(dict(cur.fetchone()).values())[0] or 0)

        # Count team members
        cur.execute(
            f"SELECT COUNT(*) FROM users WHERE tenant_id = {ph}",
            (str(tenant_id),)
        )
        team_count = int(list(dict(cur.fetchone()).values())[0] or 0)

    return {
        "plan_id": quota.get("plan_id", "free"),
        "plan_type": quota.get("plan_type", "free"),
        "expires_at": str(quota.get("expires_at","")) if quota.get("expires_at") else None,
        "features": quota.get("features", DEFAULT_FREE_FEATURES),
        # Jobs
        "active_jobs": job_status["active_jobs"],
        "job_limit": job_status["limit"],
        "job_credits": job_status["credits"],
        "credits_used": job_status["credits_used"],
        "can_post": job_status["can_post"],
        "jobs_remaining": job_status["remaining"],
        # Featured
        "active_featured": active_featured,
        "featured_limit": quota.get("featured_slots", 0),
        "featured_remaining": max(0, (quota.get("featured_slots",0) or 0) - active_featured),
        # Team
        "team_count": team_count,
        "team_limit": quota.get("team_seats", 1),
        "team_remaining": max(0, (quota.get("team_seats",1) or 1) - team_count),
    }


@router.get("/check/{feature}")
async def check_feature_access(feature: str, current_user: dict = Depends(get_current_user)):
    """Check if current user has access to a specific feature."""
    tenant_id = current_user.get("tenant_id")
    has_access = check_feature(str(tenant_id), feature) if tenant_id else False
    return {"feature": feature, "has_access": has_access}


# ── Admin quota management ────────────────────────────────────────────────────

class QuotaOverride(BaseModel):
    active_jobs: Optional[int] = None
    featured_slots: Optional[int] = None
    team_seats: Optional[int] = None
    job_credits: Optional[int] = None
    features: Optional[dict] = None
    expires_at: Optional[str] = None
    override_note: str = ""


@router.get("/admin/tenants")
async def list_tenant_quotas(current_user: dict = Depends(require_platform_admin)):
    """List all tenant quotas for admin overview."""
    _ensure_quota_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT tq.*, t.name as tenant_name,
                   COUNT(j.id) as jobs_posted
            FROM tenant_quotas tq
            LEFT JOIN tenants t ON t.id::text = tq.tenant_id
            LEFT JOIN jobs j ON j.tenant_id::text = tq.tenant_id AND j.source='manual'
            GROUP BY tq.tenant_id, t.name
            ORDER BY tq.updated_at DESC
        """ if USE_POSTGRES else """
            SELECT tq.*, t.name as tenant_name,
                   COUNT(j.id) as jobs_posted
            FROM tenant_quotas tq
            LEFT JOIN tenants t ON t.id = tq.tenant_id
            LEFT JOIN jobs j ON j.tenant_id = tq.tenant_id AND j.source='manual'
            GROUP BY tq.tenant_id, t.name
            ORDER BY tq.updated_at DESC
        """)
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["features"] = _j(row.get("features"), DEFAULT_FREE_FEATURES)
            rows.append(row)
    return rows


@router.patch("/admin/tenants/{tenant_id}")
async def override_tenant_quota(
    tenant_id: str, body: QuotaOverride,
    current_user: dict = Depends(require_platform_admin)
):
    """Admin override of any tenant's quota and features."""
    _ensure_quota_tables()
    quota = get_tenant_quota(tenant_id)
    now = datetime.now(timezone.utc).isoformat()

    updates = {}
    if body.active_jobs is not None: updates["active_jobs"] = body.active_jobs
    if body.featured_slots is not None: updates["featured_slots"] = body.featured_slots
    if body.team_seats is not None: updates["team_seats"] = body.team_seats
    if body.job_credits is not None: updates["job_credits"] = body.job_credits
    if body.expires_at is not None: updates["expires_at"] = body.expires_at
    if body.features:
        existing = quota.get("features", {})
        existing.update(body.features)
        updates["features"] = json.dumps(existing)
    updates["is_overridden"] = True
    updates["override_note"] = body.override_note

    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        set_clause = ", ".join(f"{k} = {ph}" for k in updates)
        vals = list(updates.values()) + [tenant_id]
        cur.execute(
            f"UPDATE tenant_quotas SET {set_clause}, updated_at = {'NOW()' if USE_POSTGRES else ph} WHERE tenant_id = {ph}",
            vals if USE_POSTGRES else vals[:-1] + [now, tenant_id]
        )

    return {"message": f"Quota updated for tenant {tenant_id}", "updates": updates}


@router.post("/admin/tenants/{tenant_id}/reset")
async def reset_tenant_credits(
    tenant_id: str,
    current_user: dict = Depends(require_platform_admin)
):
    """Reset job credits used counter (e.g. after purchasing more credits)."""
    _ensure_quota_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(
            f"UPDATE tenant_quotas SET credits_used = 0, updated_at = {'NOW()' if USE_POSTGRES else ph} WHERE tenant_id = {ph}",
            ((tenant_id,) if USE_POSTGRES else (datetime.now(timezone.utc).isoformat(), tenant_id))
        )
    return {"message": "Credits reset"}


@router.get("/admin/feature-flags")
async def list_feature_flags(current_user: dict = Depends(require_platform_admin)):
    """List all available feature flags with descriptions."""
    return {
        "flags": [
            {"key": "post_jobs",            "label": "Post Jobs",              "description": "Can post manual job listings"},
            {"key": "featured_jobs",         "label": "Featured Jobs",          "description": "Can mark jobs as featured (gold badge, top placement)"},
            {"key": "applications_dashboard","label": "Applications Dashboard", "description": "Can view and manage job applications"},
            {"key": "applications_export",   "label": "Export Applications",    "description": "Can export applicant data to CSV"},
            {"key": "team_management",       "label": "Team Management",        "description": "Can invite and manage team members"},
            {"key": "analytics",             "label": "Analytics",              "description": "Access to job performance and application analytics"},
            {"key": "candidate_database",    "label": "Candidate Database",     "description": "Access to searchable candidate pool"},
            {"key": "custom_branding",       "label": "Custom Branding",        "description": "Custom logo and brand colors on job listings"},
            {"key": "api_access",            "label": "API Access",             "description": "Programmatic access to post jobs via API"},
            {"key": "ai_screening",          "label": "AI Screening",           "description": "AI-powered candidate screening and ranking"},
            {"key": "priority_support",      "label": "Priority Support",       "description": "Dedicated support channel"},
            {"key": "duplicate_jobs",        "label": "Duplicate Jobs",         "description": "Can duplicate existing job listings"},
            {"key": "draft_jobs",            "label": "Draft Jobs",             "description": "Can save jobs as drafts before publishing"},
        ]
    }
