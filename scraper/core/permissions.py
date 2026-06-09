"""
Permission checking middleware and helpers.
Used by all service routers to enforce RBAC.
"""

from functools import wraps
from fastapi import HTTPException, status, Depends
from services.identity.dependencies import get_current_user
from core.database import get_conn, USE_POSTGRES


def get_user_permissions(user_id: str, tenant_id: str = None) -> list[str]:
    """
    Fetch all permission slugs for a user.
    Returns list like ['job.create', 'job.edit', 'candidate.view']
    """
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
        return [r["slug"] if hasattr(r, "keys") else r[0] for r in rows]


def require_permission(permission: str):
    """
    FastAPI dependency factory.
    Usage: user = Depends(require_permission("job.create"))
    """
    async def dependency(current_user: dict = Depends(get_current_user)):
        user_permissions = get_user_permissions(
            str(current_user["id"]),
            str(current_user.get("tenant_id", ""))
        )
        # Super admin bypass
        if current_user.get("role") == "super_admin":
            return current_user
        if permission not in user_permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission required: {permission}"
            )
        return current_user
    return dependency
