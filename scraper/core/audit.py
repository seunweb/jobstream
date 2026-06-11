"""
Audit Logging Service
Phase 5 — Every significant action is recorded.

Tracks:
- Authentication events (login, logout, register, password reset)
- Profile changes
- Job CRUD (create, update, delete)
- Application events (submitted, status changed)
- Organization changes
- Admin actions
- Security events (lockout, MFA enable/disable)

Design principles:
- Never let audit logging crash the main flow (always wrapped in try/except)
- Each log entry is immutable (no UPDATE on audit_logs)
- Indexed for fast filtering by tenant, user, action, resource
"""

import logging
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import Request

log = logging.getLogger(__name__)


# ── Action constants ──────────────────────────────────────────────────────────

class AuditAction:
    # Auth
    USER_REGISTERED     = "user.registered"
    USER_LOGIN          = "user.login"
    USER_LOGIN_FAILED   = "user.login_failed"
    USER_LOGOUT         = "user.logout"
    USER_LOCKED         = "user.locked"
    PASSWORD_RESET_REQ  = "user.password_reset_requested"
    PASSWORD_RESET_DONE = "user.password_reset_completed"
    MFA_ENABLED         = "user.mfa_enabled"
    MFA_DISABLED        = "user.mfa_disabled"
    SESSION_REVOKED     = "user.session_revoked"
    ALL_SESSIONS_REVOKED = "user.all_sessions_revoked"

    # Profile
    PROFILE_UPDATED     = "profile.updated"
    PERSON_CREATED      = "person.created"
    PERSON_UPDATED      = "person.updated"

    # Jobs
    JOB_CREATED         = "job.created"
    JOB_UPDATED         = "job.updated"
    JOB_DELETED         = "job.deleted"
    JOB_SCRAPED         = "job.scraped"

    # Applications
    APPLICATION_SUBMITTED  = "application.submitted"
    APPLICATION_STATUS_CHANGED = "application.status_changed"

    # Organizations
    ORG_CREATED         = "organization.created"
    ORG_UPDATED         = "organization.updated"
    ORG_DELETED         = "organization.deleted"

    # Admin
    ADMIN_ACTION        = "admin.action"
    ROLE_ASSIGNED       = "admin.role_assigned"
    USER_SUSPENDED      = "admin.user_suspended"

    # Security
    RATE_LIMIT_HIT      = "security.rate_limit_hit"
    SUSPICIOUS_REQUEST  = "security.suspicious_request"


# ── Core logging function ─────────────────────────────────────────────────────

def log_action(
    action: str,
    user_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    old_value: Optional[dict] = None,
    new_value: Optional[dict] = None,
    metadata: Optional[dict] = None,
    request: Optional[Request] = None,
    module: str = "platform",
):
    """
    Record an audit log entry.
    Safe to call anywhere — never raises exceptions.
    """
    try:
        from core.database import get_conn, USE_POSTGRES

        ip_address = None
        user_agent = None
        if request:
            ip_address = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent", "")[:500]

        payload = {}
        if old_value:
            payload["old"] = old_value
        if new_value:
            payload["new"] = new_value
        if metadata:
            payload["meta"] = metadata

        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    INSERT INTO audit_logs
                        (tenant_id, user_id, action, module,
                         resource_type, resource_id,
                         old_value, new_value,
                         ip_address, user_agent, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    tenant_id, user_id, action, module,
                    resource_type, resource_id,
                    json.dumps(old_value) if old_value else None,
                    json.dumps(new_value) if new_value else None,
                    ip_address, user_agent,
                    datetime.now(timezone.utc).isoformat()
                ))
            else:
                cur.execute("""
                    INSERT INTO audit_logs
                        (tenant_id, user_id, action, module,
                         resource_type, resource_id,
                         old_value, new_value,
                         ip_address, user_agent, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    tenant_id, user_id, action, module,
                    resource_type, resource_id,
                    json.dumps(old_value) if old_value else None,
                    json.dumps(new_value) if new_value else None,
                    ip_address, user_agent,
                    datetime.now(timezone.utc).isoformat()
                ))

    except Exception as e:
        # Never crash the main flow
        log.error(f"Audit log failed for action={action}: {e}")


# ── Convenience wrappers ──────────────────────────────────────────────────────

def log_auth(action: str, user_id: str, email: str, request: Request, extra: dict = None):
    log_action(
        action=action,
        user_id=user_id,
        resource_type="user",
        resource_id=user_id,
        metadata={"email": email, **(extra or {})},
        request=request,
        module="identity",
    )


def log_job(action: str, user_id: str, job_id, job_title: str, request: Request = None):
    log_action(
        action=action,
        user_id=user_id,
        resource_type="job",
        resource_id=str(job_id),
        metadata={"title": job_title},
        request=request,
        module="recruitment",
    )


def log_application(
    action: str,
    user_id: str,
    app_id,
    job_title: str,
    old_status: str = None,
    new_status: str = None,
    request: Request = None,
):
    log_action(
        action=action,
        user_id=user_id,
        resource_type="application",
        resource_id=str(app_id),
        old_value={"status": old_status} if old_status else None,
        new_value={"status": new_status} if new_status else None,
        metadata={"job_title": job_title},
        request=request,
        module="recruitment",
    )


def log_org(action: str, user_id: str, org_id: str, org_name: str, request: Request = None):
    log_action(
        action=action,
        user_id=user_id,
        resource_type="organization",
        resource_id=org_id,
        metadata={"name": org_name},
        request=request,
        module="organization",
    )


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_audit_logs(
    user_id: str = None,
    tenant_id: str = None,
    action: str = None,
    resource_type: str = None,
    module: str = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Query audit logs with filters."""
    try:
        from core.database import get_conn, USE_POSTGRES

        conditions = []
        params = []

        if user_id:
            conditions.append("user_id = %s" if USE_POSTGRES else "user_id = ?")
            params.append(user_id)
        if tenant_id:
            conditions.append("tenant_id = %s" if USE_POSTGRES else "tenant_id = ?")
            params.append(tenant_id)
        if action:
            conditions.append("action = %s" if USE_POSTGRES else "action = ?")
            params.append(action)
        if resource_type:
            conditions.append("resource_type = %s" if USE_POSTGRES else "resource_type = ?")
            params.append(resource_type)
        if module:
            conditions.append("module = %s" if USE_POSTGRES else "module = ?")
            params.append(module)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        ph = "%s" if USE_POSTGRES else "?"
        params += [limit, offset]

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT * FROM audit_logs {where} ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
                params
            )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        log.error(f"Failed to query audit logs: {e}")
        return []
