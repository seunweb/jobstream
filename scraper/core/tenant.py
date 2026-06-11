"""
Multi-tenancy Core
Phase 6 — Tenant isolation and context management.

Architecture: Shared database with tenant_id on all business entities.
Every query is automatically scoped to the current tenant.

Tenant resolution order:
1. JWT token (tenant_id claim)
2. Request header (X-Tenant-ID)
3. Custom domain lookup
4. Default public tenant (job board)
"""

import logging
import uuid
from typing import Optional
from fastapi import Request, HTTPException, Depends

log = logging.getLogger(__name__)

# Public tenant ID — used for the public job board (no org context)
PUBLIC_TENANT_ID = "00000000-0000-0000-0000-000000000000"


# ── Tenant context ────────────────────────────────────────────────────────────

class TenantContext:
    """Holds tenant info for the current request."""
    def __init__(
        self,
        tenant_id: str,
        slug: str = "",
        plan: str = "free",
        settings: dict = None,
    ):
        self.tenant_id = tenant_id
        self.slug = slug
        self.plan = plan
        self.settings = settings or {}

    @property
    def is_public(self) -> bool:
        return self.tenant_id == PUBLIC_TENANT_ID

    def __repr__(self):
        return f"TenantContext(id={self.tenant_id}, slug={self.slug})"


# ── Tenant resolution ─────────────────────────────────────────────────────────

def get_tenant_by_id(tenant_id: str) -> Optional[dict]:
    try:
        from core.database import get_conn, USE_POSTGRES
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM tenants WHERE id = %s AND status = 'active'" if USE_POSTGRES
                else "SELECT * FROM tenants WHERE id = ? AND status = 'active'",
                (tenant_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log.error(f"Tenant lookup failed: {e}")
        return None


def get_tenant_by_slug(slug: str) -> Optional[dict]:
    try:
        from core.database import get_conn, USE_POSTGRES
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM tenants WHERE slug = %s AND status = 'active'" if USE_POSTGRES
                else "SELECT * FROM tenants WHERE slug = ? AND status = 'active'",
                (slug,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log.error(f"Tenant slug lookup failed: {e}")
        return None


def get_tenant_by_domain(domain: str) -> Optional[dict]:
    try:
        from core.database import get_conn, USE_POSTGRES
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM tenants WHERE custom_domain = %s AND status = 'active'" if USE_POSTGRES
                else "SELECT * FROM tenants WHERE custom_domain = ? AND status = 'active'",
                (domain,)
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        log.error(f"Tenant domain lookup failed: {e}")
        return None


def resolve_tenant(request: Request, user: dict = None) -> TenantContext:
    """
    Resolve the tenant for the current request.
    Falls back to public tenant if none found.
    """
    # 1. From authenticated user's JWT
    if user and user.get("tenant_id"):
        tid = user["tenant_id"]
        tenant = get_tenant_by_id(tid)
        if tenant:
            return TenantContext(
                tenant_id=str(tenant["id"]),
                slug=tenant.get("slug", ""),
                plan=tenant.get("plan", "free"),
                settings=tenant.get("settings") or {},
            )

    # 2. From request header
    header_tid = request.headers.get("X-Tenant-ID", "")
    if header_tid:
        tenant = get_tenant_by_id(header_tid)
        if tenant:
            return TenantContext(
                tenant_id=str(tenant["id"]),
                slug=tenant.get("slug", ""),
                plan=tenant.get("plan", "free"),
            )

    # 3. From custom domain
    host = request.headers.get("host", "").split(":")[0]
    if host and "localhost" not in host and "railway.app" not in host:
        tenant = get_tenant_by_domain(host)
        if tenant:
            return TenantContext(
                tenant_id=str(tenant["id"]),
                slug=tenant.get("slug", ""),
                plan=tenant.get("plan", "free"),
            )

    # 4. Default to public tenant
    return TenantContext(tenant_id=PUBLIC_TENANT_ID)


# ── Tenant CRUD ───────────────────────────────────────────────────────────────

def create_tenant(
    name: str,
    slug: str,
    plan: str = "free",
    country: str = "NG",
    currency: str = "NGN",
    timezone: str = "Africa/Lagos",
) -> dict:
    """Create a new tenant. Called during employer onboarding."""
    from core.database import get_conn, USE_POSTGRES

    tenant_id = str(uuid.uuid4())
    slug = slug.lower().strip().replace(" ", "-")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO tenants
                    (id, name, slug, plan, country, currency, timezone, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'active')
                RETURNING *
            """, (tenant_id, name, slug, plan, country, currency, timezone))
            row = cur.fetchone()
            return dict(row)
        else:
            cur.execute("""
                INSERT INTO tenants
                    (id, name, slug, plan, country, currency, timezone, status)
                VALUES (?,?,?,?,?,?,?,'active')
            """, (tenant_id, name, slug, plan, country, currency, timezone))
            cur.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
            return dict(cur.fetchone())


def link_user_to_tenant(user_id: str, tenant_id: str, role: str = "org_owner"):
    """Link a user to a tenant with a role."""
    from core.database import get_conn, USE_POSTGRES
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                UPDATE users SET tenant_id = %s, role = %s WHERE id = %s
            """, (tenant_id, role, user_id))
        else:
            cur.execute("""
                UPDATE users SET tenant_id = ?, role = ? WHERE id = ?
            """, (tenant_id, role, user_id))


# ── Plan limits ───────────────────────────────────────────────────────────────

PLAN_LIMITS = {
    "free": {
        "max_jobs":        3,
        "max_team_members": 1,
        "max_pipelines":   1,
        "ai_enabled":      False,
        "analytics":       "basic",
        "white_label":     False,
    },
    "starter": {
        "max_jobs":        10,
        "max_team_members": 3,
        "max_pipelines":   3,
        "ai_enabled":      False,
        "analytics":       "standard",
        "white_label":     False,
    },
    "growth": {
        "max_jobs":        50,
        "max_team_members": 10,
        "max_pipelines":   10,
        "ai_enabled":      True,
        "analytics":       "advanced",
        "white_label":     False,
    },
    "enterprise": {
        "max_jobs":        -1,   # unlimited
        "max_team_members": -1,
        "max_pipelines":   -1,
        "ai_enabled":      True,
        "analytics":       "full",
        "white_label":     True,
    },
}


def check_plan_limit(tenant: TenantContext, feature: str, current_count: int = 0) -> bool:
    """
    Check if a tenant can use a feature based on their plan.
    Returns True if allowed, raises HTTPException if not.
    """
    limits = PLAN_LIMITS.get(tenant.plan, PLAN_LIMITS["free"])
    limit = limits.get(feature, 0)

    if limit == -1:  # unlimited
        return True

    if isinstance(limit, bool):
        if not limit:
            raise HTTPException(
                403,
                f"Feature '{feature}' not available on the {tenant.plan} plan. "
                f"Please upgrade to access this feature."
            )
        return True

    if current_count >= limit:
        raise HTTPException(
            403,
            f"Plan limit reached: {feature} is limited to {limit} on the "
            f"{tenant.plan} plan. Please upgrade to continue."
        )
    return True
