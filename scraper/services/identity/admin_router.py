"""
Admin Dashboard Router
Phase 8 — Platform and tenant administration.

Platform Admin endpoints (super_admin / platform_admin only):
- Overview stats
- Tenant management
- User management
- Job moderation
- System health
- Audit log viewer

Tenant Dashboard endpoints (org_owner / hr_admin):
- Workspace overview
- Team management
- Pipeline stats
"""

import logging
from typing import Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from core.rbac import require_permission, has_permission
from core.audit import get_audit_logs
from services.identity.dependencies import get_current_user

log = logging.getLogger(__name__)

platform_router = APIRouter(prefix="/admin", tags=["admin"])
tenant_router   = APIRouter(prefix="/workspace", tags=["workspace"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def require_platform_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Platform admin access required")
    return current_user


def require_org_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in (
        "super_admin", "platform_admin", "org_owner", "hr_admin"
    ):
        raise HTTPException(403, "Organization admin access required")
    return current_user


def count_query(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return 0
    d = dict(row)
    return int(list(d.values())[0])


# ════════════════════════════════════════════════════════════════
# PLATFORM ADMIN
# ════════════════════════════════════════════════════════════════

@platform_router.get("/overview")
async def platform_overview(
    current_user: dict = Depends(require_platform_admin),
):
    """Platform-wide stats for the admin dashboard."""
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"

        total_tenants    = count_query(cur, "SELECT COUNT(*) FROM tenants")
        active_tenants   = count_query(cur, f"SELECT COUNT(*) FROM tenants WHERE status = {ph}", ("active",))
        total_users      = count_query(cur, "SELECT COUNT(*) FROM users")
        total_jobs       = count_query(cur, "SELECT COUNT(*) FROM jobs WHERE is_active = 1")
        manual_jobs      = count_query(cur, f"SELECT COUNT(*) FROM jobs WHERE source = {ph} AND is_active = 1", ("manual",))
        scraped_jobs     = count_query(cur, f"SELECT COUNT(*) FROM jobs WHERE source = {ph} AND is_active = 1", ("scraped",))
        total_apps       = count_query(cur, "SELECT COUNT(*) FROM applications")
        total_orgs       = count_query(cur, ("SELECT COUNT(*) FROM organizations WHERE is_active = TRUE" if USE_POSTGRES else "SELECT COUNT(*) FROM organizations WHERE is_active = 1"))

        # New users last 30 days
        if USE_POSTGRES:
            new_users_30d = count_query(cur,
                "SELECT COUNT(*) FROM users WHERE created_at > NOW() - INTERVAL '30 days'"
            )
        else:
            new_users_30d = count_query(cur,
                "SELECT COUNT(*) FROM users WHERE created_at > datetime('now', '-30 days')"
            )

        # Applications last 7 days
        if USE_POSTGRES:
            apps_7d = count_query(cur,
                "SELECT COUNT(*) FROM applications WHERE submitted_at > NOW() - INTERVAL '7 days'"
            )
        else:
            apps_7d = count_query(cur,
                "SELECT COUNT(*) FROM applications WHERE submitted_at > datetime('now', '-7 days')"
            )

        # Jobs by type breakdown
        cur.execute("""
            SELECT job_type, COUNT(*) as count
            FROM jobs WHERE is_active = 1
            GROUP BY job_type ORDER BY count DESC
        """)
        jobs_by_type = [dict(r) for r in cur.fetchall()]

        # Recent tenants
        cur.execute(
            "SELECT id, name, slug, plan, status, created_at FROM tenants ORDER BY created_at DESC LIMIT 5"
        )
        recent_tenants = [dict(r) for r in cur.fetchall()]

        # Top companies by job count
        cur.execute("""
            SELECT company, COUNT(*) as job_count
            FROM jobs WHERE is_active = 1
            GROUP BY company ORDER BY job_count DESC LIMIT 10
        """)
        top_companies = [dict(r) for r in cur.fetchall()]

    return {
        "users":          {"total": total_users, "new_30d": new_users_30d},
        "tenants":        {"total": total_tenants, "active": active_tenants},
        "jobs":           {"total": total_jobs, "manual": manual_jobs, "scraped": scraped_jobs, "by_type": jobs_by_type},
        "applications":   {"total": total_apps, "last_7d": apps_7d},
        "organizations":  {"total": total_orgs},
        "top_companies":  top_companies,
        "recent_tenants": recent_tenants,
    }


@platform_router.patch("/users/{user_id}/role")
async def assign_user_role(
    user_id: str,
    request: Request,
    current_user: dict = Depends(require_platform_admin),
):
    """Assign a role to any user."""
    body = await request.json()
    new_role = body.get("role", "").strip()
    if not new_role:
        raise HTTPException(400, "Role required")

    valid_roles = [
        "candidate", "premium_candidate",
        "org_owner", "hr_admin", "recruiter", "hiring_manager", "interviewer",
        "super_admin", "platform_admin", "support_agent",
    ]
    if new_role not in valid_roles:
        raise HTTPException(400, f"Invalid role. Must be one of: {', '.join(valid_roles)}")

    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET role = {ph} WHERE id = {ph}", (new_role, user_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "User not found")

    log.info(f"Admin {current_user['email']} assigned role {new_role} to user {user_id}")
    return {"message": f"Role updated to {new_role}"}


@platform_router.post("/users", status_code=201)
async def admin_create_user(
    request: Request,
    current_user: dict = Depends(require_platform_admin),
):
    """Admin: create a new user account with optional confirmation email."""
    import bcrypt, uuid as _uuid
    from core.email import send_email

    body = await request.json()
    full_name = body.get("full_name", "").strip()
    email = body.get("email", "").lower().strip()
    password = body.get("password") or _uuid.uuid4().hex[:12]
    role = body.get("role", "candidate")
    send_confirmation = body.get("send_confirmation", True)

    if not email or not full_name:
        raise HTTPException(400, "full_name and email required")

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    user_id = str(_uuid.uuid4())
    ph = "%s" if USE_POSTGRES else "?"

    with get_conn() as conn:
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute("""
                    INSERT INTO users (id, email, full_name, password_hash, role, status)
                    VALUES (%s,%s,%s,%s,%s,'active')
                """, (user_id, email, full_name, pw_hash, role))
            else:
                cur.execute("""
                    INSERT INTO users (id, email, full_name, password_hash, role, status)
                    VALUES (?,?,?,?,?,'active')
                """, (user_id, email, full_name, pw_hash, role))
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise HTTPException(409, f"User with email {email} already exists")
            raise HTTPException(400, str(e))

    if send_confirmation:
        import os
        app_url = os.environ.get("APP_URL", "http://localhost:3000")
        html = f"""<!DOCTYPE html>
<html><body style="font-family:Arial,sans-serif;background:#f4f4f6;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:40px;">
  <h1 style="font-size:20px;color:#1d1d1f;">⚡ JobStream</h1>
  <h2 style="font-size:18px;color:#1d1d1f;">Your account has been created</h2>
  <p style="color:#555;font-size:14px;">Hi {full_name},</p>
  <p style="color:#555;font-size:14px;">Your JobStream account has been created with role: <strong>{role}</strong></p>
  <p style="color:#555;font-size:14px;">Login at <a href="{app_url}">{app_url}</a></p>
  <p style="color:#555;font-size:14px;">Temporary password: <code>{password}</code></p>
  <p style="color:#aaa;font-size:12px;">Please change your password after logging in.</p>
</div></body></html>"""
        try:
            send_email(to_email=email, subject="Your JobStream account", html=html)
        except Exception as e:
            log.warning(f"Could not send confirmation to {email}: {e}")

    return {"message": f"User {email} created", "id": user_id, "temp_password": password if not send_confirmation else None}


@platform_router.get("/tenants")
async def list_tenants(
    search: str = Query(""),
    plan: str = Query(""),
    status: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(require_platform_admin),
):
    """List all tenants with filtering."""
    conditions = []
    params = []
    ph = "%s" if USE_POSTGRES else "?"

    if search:
        conditions.append(f"(name ILIKE {ph} OR slug ILIKE {ph})" if USE_POSTGRES
                         else f"(name LIKE {ph} OR slug LIKE {ph})")
        params += [f"%{search}%", f"%{search}%"]
    if plan:
        conditions.append(f"plan = {ph}")
        params.append(plan)
    if status:
        conditions.append(f"status = {ph}")
        params.append(status)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM tenants {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
            params
        )
        tenants = [dict(r) for r in cur.fetchall()]

        # Count
        count_params = params[:-2]
        cur.execute(f"SELECT COUNT(*) FROM tenants {where}", count_params)
        row = cur.fetchone()
        total = int(list(dict(row).values())[0])

    return {"tenants": tenants, "total": total}


@platform_router.patch("/tenants/{tenant_id}/status")
async def update_tenant_status(
    tenant_id: str,
    current_user: dict = Depends(require_platform_admin),
):
    """Suspend or activate a tenant."""
    body_data = {}
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM tenants WHERE id = %s" if USE_POSTGRES
            else "SELECT status FROM tenants WHERE id = ?",
            (tenant_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Tenant not found")
        current_status = dict(row)["status"]
        new_status = "suspended" if current_status == "active" else "active"
        if USE_POSTGRES:
            cur.execute(
                "UPDATE tenants SET status = %s WHERE id = %s",
                (new_status, tenant_id)
            )
        else:
            cur.execute(
                "UPDATE tenants SET status = ? WHERE id = ?",
                (new_status, tenant_id)
            )

    from core.audit import log_action
    log_action(
        "tenant.status_changed",
        user_id=str(current_user["id"]),
        resource_type="tenant",
        resource_id=tenant_id,
        old_value={"status": current_status},
        new_value={"status": new_status},
        module="admin",
    )
    return {"message": f"Tenant {new_status}", "status": new_status}


@platform_router.patch("/tenants/{tenant_id}/plan")
async def update_tenant_plan(
    tenant_id: str,
    current_user: dict = Depends(require_platform_admin),
):
    """Upgrade or change tenant plan."""
    # Get plan from request body
    import json
    body = {}
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT plan FROM tenants WHERE id = %s" if USE_POSTGRES
            else "SELECT plan FROM tenants WHERE id = ?",
            (tenant_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Tenant not found")
    return {"message": "Use PATCH /tenants/me to update plan settings"}


@platform_router.get("/users")
async def list_all_users(
    search: str = Query(""),
    role: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(require_platform_admin),
):
    """List all users on the platform."""
    conditions = []
    params = []
    ph = "%s" if USE_POSTGRES else "?"

    if search:
        conditions.append(
            f"(email ILIKE {ph} OR full_name ILIKE {ph})" if USE_POSTGRES
            else f"(email LIKE {ph} OR full_name LIKE {ph})"
        )
        params += [f"%{search}%", f"%{search}%"]
    if role:
        conditions.append(f"role = {ph}")
        params.append(role)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params += [limit, offset]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT id, email, full_name, role, status, created_at, "
            f"last_login_at, last_ip, mfa_enabled FROM users {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
            params
        )
        users = [dict(r) for r in cur.fetchall()]

        count_params = params[:-2]
        cur.execute(f"SELECT COUNT(*) FROM users {where}", count_params)
        row = cur.fetchone()
        total = int(list(dict(row).values())[0])

    return {"users": users, "total": total}


@platform_router.patch("/users/{user_id}/status")
async def toggle_user_status(
    user_id: str,
    current_user: dict = Depends(require_platform_admin),
):
    """Suspend or activate a user account."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT status FROM users WHERE id = %s" if USE_POSTGRES
            else "SELECT status FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        current_status = dict(row)["status"]
        new_status = "suspended" if current_status == "active" else "active"
        if USE_POSTGRES:
            cur.execute("UPDATE users SET status = %s WHERE id = %s", (new_status, user_id))
        else:
            cur.execute("UPDATE users SET status = ? WHERE id = ?", (new_status, user_id))

    from core.audit import log_action, AuditAction
    log_action(
        AuditAction.USER_SUSPENDED if new_status == "suspended" else "user.activated",
        user_id=str(current_user["id"]),
        resource_type="user",
        resource_id=user_id,
        new_value={"status": new_status},
        module="admin",
    )
    return {"message": f"User {new_status}", "status": new_status}


@platform_router.get("/jobs")
async def list_all_jobs(
    search: str = Query(""),
    source: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(require_platform_admin),
):
    """List all jobs — for content moderation."""
    conditions = ["1=1"]
    params = []
    ph = "%s" if USE_POSTGRES else "?"

    if search:
        conditions.append(
            f"(title ILIKE {ph} OR company ILIKE {ph})" if USE_POSTGRES
            else f"(title LIKE {ph} OR company LIKE {ph})"
        )
        params += [f"%{search}%", f"%{search}%"]
    if source:
        conditions.append(f"source = {ph}")
        params.append(source)

    where = "WHERE " + " AND ".join(conditions)
    params += [limit, offset]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
            params
        )
        jobs = [dict(r) for r in cur.fetchall()]

        count_params = params[:-2]
        cur.execute(f"SELECT COUNT(*) FROM jobs {where}", count_params)
        row = cur.fetchone()
        total = int(list(dict(row).values())[0])

    return {"jobs": jobs, "total": total}


@platform_router.patch("/jobs/{job_id}")
async def admin_patch_job(
    job_id: int,
    request: Request,
    current_user: dict = Depends(require_platform_admin),
):
    """Update job fields — is_active, title, description, etc."""
    body = await request.json()
    with get_conn() as conn:
        cur = conn.cursor()
        updatable = ["title", "description", "location", "salary", "department", "job_type"]
        for field in updatable:
            if field in body:
                ph = "%s" if USE_POSTGRES else "?"
                cur.execute(f"UPDATE jobs SET {field} = {ph} WHERE id = {ph}", (body[field], job_id))
        if "is_active" in body:
            val = 1 if body["is_active"] else 0  # SMALLINT column — use 1/0
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(f"UPDATE jobs SET is_active = {ph} WHERE id = {ph}", (val, job_id))
    return {"message": "Job updated"}


@platform_router.delete("/jobs/{job_id}", status_code=204)
async def admin_delete_job(
    job_id: int,
    current_user: dict = Depends(require_platform_admin),
):
    """Hard delete a job — for moderation."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM jobs WHERE id = %s" if USE_POSTGRES
            else "DELETE FROM jobs WHERE id = ?",
            (job_id,)
        )
    from core.audit import log_action
    log_action(
        "job.deleted",
        user_id=str(current_user["id"]),
        resource_type="job",
        resource_id=str(job_id),
        module="admin",
    )


@platform_router.get("/audit")
async def admin_audit_logs(
    user_id: str = Query(None),
    action: str = Query(None),
    module: str = Query(None),
    resource_type: str = Query(None),
    limit: int = Query(50, le=500),
    offset: int = Query(0),
    current_user: dict = Depends(require_platform_admin),
):
    """Query platform audit logs."""
    logs = get_audit_logs(
        user_id=user_id,
        action=action,
        module=module,
        resource_type=resource_type,
        limit=limit,
        offset=offset,
    )
    return {"logs": logs, "total": len(logs)}


@platform_router.get("/health")
async def system_health(
    current_user: dict = Depends(require_platform_admin),
):
    """System health check — DB connectivity, table counts."""
    import time
    start = time.time()
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        db_latency_ms = round((time.time() - start) * 1000, 2)
        db_status = "ok"
    except Exception as e:
        db_latency_ms = -1
        db_status = str(e)

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": {"status": db_status, "latency_ms": db_latency_ms},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ════════════════════════════════════════════════════════════════
# TENANT / WORKSPACE DASHBOARD
# ════════════════════════════════════════════════════════════════

@tenant_router.get("/overview")
async def workspace_overview(
    current_user: dict = Depends(require_org_admin),
):
    """Overview stats for the employer workspace dashboard."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        # Return empty overview so the employer page renders without error
        return {
            "tenant": None,
            "active_jobs": 0,
            "total_applications": 0,
            "apps_by_status": [],
            "recent_applications": [],
            "message": "No workspace yet. Create one via the Employer onboarding flow.",
        }

    ph = "%s" if USE_POSTGRES else "?"

    with get_conn() as conn:
        cur = conn.cursor()

        active_jobs  = count_query(cur,
            f"SELECT COUNT(*) FROM jobs WHERE tenant_id = {ph} AND is_active = 1", (tenant_id,))
        total_apps   = count_query(cur,
            f"SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id = j.id WHERE j.tenant_id = {ph}",
            (tenant_id,))

        # Applications by status
        if USE_POSTGRES:
            cur.execute("""
                SELECT a.status, COUNT(*) as count
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE j.tenant_id = %s
                GROUP BY a.status ORDER BY count DESC
            """, (tenant_id,))
        else:
            cur.execute("""
                SELECT a.status, COUNT(*) as count
                FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE j.tenant_id = ?
                GROUP BY a.status ORDER BY count DESC
            """, (tenant_id,))
        apps_by_status = [dict(r) for r in cur.fetchall()]

        # New applications last 7 days
        if USE_POSTGRES:
            new_apps_7d = count_query(cur, """
                SELECT COUNT(*) FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE j.tenant_id = %s
                AND a.submitted_at > NOW() - INTERVAL '7 days'
            """, (tenant_id,))
        else:
            new_apps_7d = count_query(cur, """
                SELECT COUNT(*) FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE j.tenant_id = ?
                AND a.submitted_at > datetime('now', '-7 days')
            """, (tenant_id,))

        # Top jobs by applications
        if USE_POSTGRES:
            cur.execute("""
                SELECT j.id, j.title, j.company, COUNT(a.id) as app_count
                FROM jobs j
                LEFT JOIN applications a ON a.job_id = j.id
                WHERE j.tenant_id = %s AND j.is_active = 1
                GROUP BY j.id, j.title, j.company
                ORDER BY app_count DESC LIMIT 5
            """, (tenant_id,))
        else:
            cur.execute("""
                SELECT j.id, j.title, j.company, COUNT(a.id) as app_count
                FROM jobs j
                LEFT JOIN applications a ON a.job_id = j.id
                WHERE j.tenant_id = ? AND j.is_active = 1
                GROUP BY j.id, j.title, j.company
                ORDER BY app_count DESC LIMIT 5
            """, (tenant_id,))
        top_jobs = [dict(r) for r in cur.fetchall()]

        # Hired count
        if USE_POSTGRES:
            hired = count_query(cur, """
                SELECT COUNT(*) FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE j.tenant_id = %s AND a.status = 'hired'
            """, (tenant_id,))
        else:
            hired = count_query(cur, """
                SELECT COUNT(*) FROM applications a
                JOIN jobs j ON a.job_id = j.id
                WHERE j.tenant_id = ? AND a.status = 'hired'
            """, (tenant_id,))

        # Team members
        team_count = count_query(cur,
            f"SELECT COUNT(*) FROM users WHERE tenant_id = {ph}", (tenant_id,))

    offer_rate = round((hired / total_apps * 100), 1) if total_apps > 0 else 0

    return {
        "jobs":           {"active": active_jobs},
        "applications":   {
            "total": total_apps,
            "new_7d": new_apps_7d,
            "by_status": apps_by_status,
        },
        "hiring":         {"hired": hired, "offer_rate": offer_rate},
        "team":           {"members": team_count},
        "top_jobs":       top_jobs,
    }


@tenant_router.get("/team")
async def list_team(
    current_user: dict = Depends(require_org_admin),
):
    """List all team members in the workspace."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No workspace found")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, full_name, role, status, created_at FROM users WHERE tenant_id = %s ORDER BY created_at" if USE_POSTGRES
            else "SELECT id, email, full_name, role, status, created_at FROM users WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,)
        )
        return [dict(r) for r in cur.fetchall()]


class InviteTeamIn(BaseModel):
    email: str
    role: str = "recruiter"


@tenant_router.post("/team/invite", status_code=201)
async def invite_team_member(
    body: InviteTeamIn,
    current_user: dict = Depends(require_org_admin),
):
    """
    Invite a team member to the workspace.
    Phase 8: Creates placeholder — full email invite in Phase 9.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No workspace found")

    valid_roles = ["hr_admin", "recruiter", "hiring_manager", "interviewer"]
    if body.role not in valid_roles:
        raise HTTPException(400, f"Role must be one of: {', '.join(valid_roles)}")

    from core.audit import log_action
    log_action(
        "team.invite_sent",
        user_id=str(current_user["id"]),
        resource_type="user",
        metadata={"email": body.email, "role": body.role, "tenant_id": tenant_id},
        module="admin",
    )

    # TODO Phase 9: Send invite email via Resend
    return {
        "message": f"Invite sent to {body.email} as {body.role}",
        "note": "Email invite will be sent when email service is configured for this workspace"
    }


@tenant_router.get("/applications")
async def workspace_applications(
    status: str = Query(""),
    job_id: int = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(require_org_admin),
):
    """Get all applications across the workspace."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No workspace found")

    ph = "%s" if USE_POSTGRES else "?"
    conditions = [f"j.tenant_id = {ph}"]
    params = [tenant_id]

    if status:
        conditions.append(f"a.status = {ph}")
        params.append(status)
    if job_id:
        conditions.append(f"a.job_id = {ph}")
        params.append(job_id)

    where = "WHERE " + " AND ".join(conditions)
    params += [limit, offset]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT a.*, j.title as job_title, j.company
            FROM applications a
            JOIN jobs j ON a.job_id = j.id
            {where}
            ORDER BY a.submitted_at DESC
            LIMIT {ph} OFFSET {ph}
        """, params)
        return [dict(r) for r in cur.fetchall()]


@tenant_router.get("/pipeline")
async def workspace_pipeline(
    current_user: dict = Depends(require_org_admin),
):
    """Kanban-style pipeline view — all active applications by stage."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No workspace found")

    stages = ["new", "reviewing", "shortlisted", "interview", "offer", "hired", "rejected"]
    ph = "%s" if USE_POSTGRES else "?"

    pipeline = {}
    with get_conn() as conn:
        cur = conn.cursor()
        for stage in stages:
            if USE_POSTGRES:
                cur.execute("""
                    SELECT a.*, j.title as job_title, j.company
                    FROM applications a
                    JOIN jobs j ON a.job_id = j.id
                    WHERE j.tenant_id = %s AND a.status = %s
                    ORDER BY a.submitted_at DESC
                    LIMIT 20
                """, (tenant_id, stage))
            else:
                cur.execute("""
                    SELECT a.*, j.title as job_title, j.company
                    FROM applications a
                    JOIN jobs j ON a.job_id = j.id
                    WHERE j.tenant_id = ? AND a.status = ?
                    ORDER BY a.submitted_at DESC
                    LIMIT 20
                """, (tenant_id, stage))
            pipeline[stage] = [dict(r) for r in cur.fetchall()]

    return {"pipeline": pipeline, "stages": stages}
