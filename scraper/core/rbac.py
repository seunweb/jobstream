"""
Role-Based Access Control (RBAC)
Phase 7 — Enterprise-grade permission system.

Architecture:
- Permissions are atomic slugs: job.create, payroll.process, etc.
- Roles are named collections of permissions
- Users are assigned roles per tenant
- API endpoints declare required permissions via require_permission()

Scope levels:
- platform: global admin roles (Super Admin, Platform Admin)
- organization: employer roles (Org Owner, HR Admin, Recruiter, etc.)
- candidate: job seeker roles (Candidate, Premium Candidate)
"""

import logging
from functools import lru_cache
from typing import Optional
from fastapi import HTTPException, Depends, Request

from services.identity.dependencies import get_current_user

log = logging.getLogger(__name__)


# ── System roles ──────────────────────────────────────────────────────────────

SYSTEM_ROLES = {
    # Platform scope
    "super_admin": {
        "name": "Super Admin",
        "scope": "platform",
        "description": "Full platform access. All permissions.",
        "permissions": ["*"],  # wildcard — all permissions
    },
    "platform_admin": {
        "name": "Platform Admin",
        "scope": "platform",
        "description": "Manage tenants, users, content.",
        "permissions": [
            "user.view", "user.invite", "user.suspend",
            "tenant.view", "tenant.manage",
            "job.view", "job.moderate",
            "audit.view", "audit.export",
            "analytics.view", "analytics.export",
        ],
    },
    "support_agent": {
        "name": "Support Agent",
        "scope": "platform",
        "description": "View-only access to help users.",
        "permissions": [
            "user.view", "tenant.view",
            "job.view", "application.view",
            "audit.view",
        ],
    },

    # Organization scope
    "org_owner": {
        "name": "Organization Owner",
        "scope": "organization",
        "description": "Full access to their organization workspace.",
        "permissions": [
            "job.create", "job.edit", "job.delete", "job.publish",
            "candidate.view", "candidate.export",
            "application.view", "application.review",
            "interview.schedule", "interview.feedback",
            "offer.create", "offer.approve",
            "employee.create", "employee.edit", "employee.view",
            "payroll.view", "payroll.process", "payroll.approve",
            "leave.approve", "leave.manage",
            "attendance.view", "attendance.manage",
            "performance.review", "performance.manage",
            "analytics.view", "analytics.export",
            "billing.view", "billing.manage",
            "settings.manage",
            "team.invite", "team.manage",
            "role.assign",
            "audit.view",
        ],
    },
    "hr_admin": {
        "name": "HR Admin",
        "scope": "organization",
        "description": "Manage all HR functions.",
        "permissions": [
            "job.create", "job.edit", "job.publish",
            "candidate.view", "candidate.export",
            "application.view", "application.review",
            "interview.schedule", "interview.feedback",
            "offer.create",
            "employee.create", "employee.edit", "employee.view",
            "leave.approve", "leave.manage",
            "attendance.view", "attendance.manage",
            "performance.review",
            "analytics.view",
            "team.invite",
            "audit.view",
        ],
    },
    "recruiter": {
        "name": "Recruiter",
        "scope": "organization",
        "description": "Manage recruitment pipeline.",
        "permissions": [
            "job.create", "job.edit", "job.publish",
            "candidate.view",
            "application.view", "application.review",
            "interview.schedule", "interview.feedback",
            "offer.create",
            "analytics.view",
        ],
    },
    "hiring_manager": {
        "name": "Hiring Manager",
        "scope": "organization",
        "description": "Review candidates and provide feedback.",
        "permissions": [
            "job.view",
            "candidate.view",
            "application.view", "application.review",
            "interview.feedback",
        ],
    },
    "interviewer": {
        "name": "Interviewer",
        "scope": "organization",
        "description": "Submit interview feedback only.",
        "permissions": [
            "candidate.view",
            "application.view",
            "interview.feedback",
        ],
    },

    # Candidate scope
    "candidate": {
        "name": "Candidate",
        "scope": "candidate",
        "description": "Job seeker — apply, save jobs, manage profile.",
        "permissions": [
            "job.view",
            "application.create",
            "profile.edit",
            "saved_jobs.manage",
        ],
    },
    "premium_candidate": {
        "name": "Premium Candidate",
        "scope": "candidate",
        "description": "Candidate with AI and priority features.",
        "permissions": [
            "job.view",
            "application.create",
            "profile.edit",
            "saved_jobs.manage",
            "ai.resume_optimizer",
            "ai.job_matcher",
            "ai.interview_prep",
            "ai.auto_apply",
        ],
    },
}


# ── Full permission catalog ────────────────────────────────────────────────────

ALL_PERMISSIONS = {
    # Identity
    "user.view":            "View users",
    "user.invite":          "Invite users",
    "user.suspend":         "Suspend users",
    "role.assign":          "Assign roles",
    "audit.view":           "View audit logs",
    "audit.export":         "Export audit logs",

    # Tenant
    "tenant.view":          "View tenants",
    "tenant.manage":        "Manage tenants",

    # Recruitment
    "job.view":             "View jobs",
    "job.create":           "Create jobs",
    "job.edit":             "Edit jobs",
    "job.delete":           "Delete jobs",
    "job.publish":          "Publish jobs",
    "job.moderate":         "Moderate job listings (platform)",
    "candidate.view":       "View candidates",
    "candidate.export":     "Export candidate data",
    "application.view":     "View applications",
    "application.create":   "Submit applications",
    "application.review":   "Review and update applications",
    "interview.schedule":   "Schedule interviews",
    "interview.feedback":   "Submit interview feedback",
    "offer.create":         "Create offers",
    "offer.approve":        "Approve offers",

    # Employee
    "employee.create":      "Create employee records",
    "employee.edit":        "Edit employee records",
    "employee.view":        "View employee records",
    "employee.terminate":   "Terminate employees",
    "contract.manage":      "Manage contracts",

    # Payroll
    "payroll.view":         "View payroll",
    "payroll.process":      "Process payroll",
    "payroll.approve":      "Approve payroll",
    "salary.manage":        "Manage salary structures",

    # Attendance
    "attendance.view":      "View attendance",
    "attendance.manage":    "Manage attendance",
    "timesheet.approve":    "Approve timesheets",

    # Leave
    "leave.request":        "Request leave",
    "leave.approve":        "Approve leave",
    "leave.manage":         "Manage leave policies",

    # Performance
    "goal.create":          "Create goals",
    "review.submit":        "Submit reviews",
    "performance.review":   "Manage performance reviews",
    "performance.manage":   "Manage performance settings",

    # Learning
    "course.enroll":        "Enroll in courses",
    "course.manage":        "Manage courses",

    # Analytics
    "analytics.view":       "View analytics",
    "analytics.export":     "Export analytics",

    # Billing
    "billing.view":         "View billing",
    "billing.manage":       "Manage subscription",

    # Settings
    "settings.manage":      "Manage workspace settings",
    "team.invite":          "Invite team members",
    "team.manage":          "Manage team",

    # Profile
    "profile.edit":         "Edit own profile",
    "saved_jobs.manage":    "Save and manage saved jobs",

    # AI
    "ai.resume_optimizer":  "Use AI resume optimizer",
    "ai.job_matcher":       "Use AI job matching",
    "ai.interview_prep":    "Use AI interview preparation",
    "ai.auto_apply":        "Use AI auto-apply",
}


# ── Permission checking ───────────────────────────────────────────────────────

def get_user_permissions(user_id: str, tenant_id: str = None) -> set[str]:
    """
    Get all permissions for a user.
    Checks user_roles → roles → permissions chain.
    Falls back to role field on user for simple cases.
    """
    try:
        from core.database import get_conn, USE_POSTGRES
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    SELECT DISTINCT p.slug
                    FROM permissions p
                    JOIN role_permissions rp ON rp.permission_id = p.id
                    JOIN user_roles ur ON ur.role_id = rp.role_id
                    WHERE ur.user_id = %s
                      AND (ur.tenant_id = %s OR ur.tenant_id IS NULL)
                """, (user_id, tenant_id))
            else:
                cur.execute("""
                    SELECT DISTINCT p.slug
                    FROM permissions p
                    JOIN role_permissions rp ON rp.permission_id = p.id
                    JOIN user_roles ur ON ur.role_id = rp.role_id
                    WHERE ur.user_id = ?
                      AND (ur.tenant_id = ? OR ur.tenant_id IS NULL)
                """, (user_id, tenant_id))
            rows = cur.fetchall()
            if rows:
                return {dict(r)["slug"] for r in rows}
    except Exception as e:
        log.warning(f"DB permission check failed: {e}")

    return set()


def has_permission(user: dict, permission: str) -> bool:
    """
    Check if user has a specific permission.
    Super admin bypasses all checks.
    Falls back to role-based check if DB permissions not set up.
    """
    role = user.get("role", "candidate")

    # Super admin bypass
    if role == "super_admin":
        return True

    # Check system role permissions
    system_role = SYSTEM_ROLES.get(role, {})
    role_perms = system_role.get("permissions", [])

    # Wildcard check
    if "*" in role_perms:
        return True

    if permission in role_perms:
        return True

    # DB-level permissions (populated when roles are explicitly assigned)
    user_id = str(user.get("id", ""))
    tenant_id = str(user.get("tenant_id", "")) if user.get("tenant_id") else None
    if user_id:
        db_perms = get_user_permissions(user_id, tenant_id)
        if permission in db_perms:
            return True

    return False


def require_permission(permission: str):
    """
    FastAPI dependency — enforce permission on endpoint.

    Usage:
        @router.post("/jobs")
        async def create_job(user = Depends(require_permission("job.create"))):
    """
    async def dependency(current_user: dict = Depends(get_current_user)):
        if not has_permission(current_user, permission):
            raise HTTPException(
                status_code=403,
                detail=f"You do not have permission to perform this action. Required: {permission}"
            )
        return current_user
    return dependency


def require_any_permission(*permissions: str):
    """Require at least one of the given permissions."""
    async def dependency(current_user: dict = Depends(get_current_user)):
        for perm in permissions:
            if has_permission(current_user, perm):
                return current_user
        raise HTTPException(
            403,
            f"Permission required: one of {', '.join(permissions)}"
        )
    return dependency
