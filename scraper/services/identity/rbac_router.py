"""
RBAC Management Router
Endpoints for managing roles and assigning them to users.
"""

import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from core.rbac import (
    SYSTEM_ROLES, ALL_PERMISSIONS,
    has_permission, require_permission,
)
from services.identity.dependencies import get_current_user

router = APIRouter(prefix="/rbac", tags=["rbac"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AssignRoleIn(BaseModel):
    user_id: str
    role_slug: str
    tenant_id: Optional[str] = None


class CreateRoleIn(BaseModel):
    name: str
    slug: str
    scope: str = "organization"
    description: Optional[str] = None
    permissions: list[str] = []


# ── Permission catalog ────────────────────────────────────────────────────────

@router.get("/permissions")
async def list_permissions(current_user: dict = Depends(get_current_user)):
    """List all available permissions grouped by module."""
    grouped: dict[str, list] = {}
    for slug, name in ALL_PERMISSIONS.items():
        module = slug.split(".")[0]
        grouped.setdefault(module, [])
        grouped[module].append({"slug": slug, "name": name})
    return {"permissions": grouped, "total": len(ALL_PERMISSIONS)}


# ── System roles ──────────────────────────────────────────────────────────────

@router.get("/roles/system")
async def list_system_roles(current_user: dict = Depends(get_current_user)):
    """List all built-in system roles."""
    return [
        {
            "slug": slug,
            "name": r["name"],
            "scope": r["scope"],
            "description": r.get("description", ""),
            "permission_count": len(r["permissions"]),
        }
        for slug, r in SYSTEM_ROLES.items()
    ]


@router.get("/roles")
async def list_roles(current_user: dict = Depends(get_current_user)):
    """List all roles (system + custom for tenant)."""
    tenant_id = current_user.get("tenant_id")
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT r.*, COUNT(rp.permission_id) as permission_count
                FROM roles r
                LEFT JOIN role_permissions rp ON rp.role_id = r.id
                WHERE r.tenant_id IS NULL OR r.tenant_id = %s
                GROUP BY r.id
                ORDER BY r.scope, r.name
            """, (tenant_id,))
        else:
            cur.execute("""
                SELECT r.*, COUNT(rp.permission_id) as permission_count
                FROM roles r
                LEFT JOIN role_permissions rp ON rp.role_id = r.id
                WHERE r.tenant_id IS NULL OR r.tenant_id = ?
                GROUP BY r.id
                ORDER BY r.scope, r.name
            """, (tenant_id,))
        return [dict(r) for r in cur.fetchall()]


@router.post("/roles", status_code=201)
async def create_custom_role(
    body: CreateRoleIn,
    current_user: dict = Depends(require_permission("role.assign")),
):
    """Create a custom role for the tenant."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No tenant workspace found")

    # Validate permissions
    invalid = [p for p in body.permissions if p not in ALL_PERMISSIONS]
    if invalid:
        raise HTTPException(400, f"Unknown permissions: {', '.join(invalid)}")

    role_id = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO roles (id, tenant_id, name, slug, scope, description, is_system)
                VALUES (%s,%s,%s,%s,%s,%s,FALSE)
                ON CONFLICT (tenant_id, slug) DO NOTHING
            """, (role_id, tenant_id, body.name, body.slug,
                  body.scope, body.description))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO roles
                    (id, tenant_id, name, slug, scope, description, is_system)
                VALUES (?,?,?,?,?,?,0)
            """, (role_id, tenant_id, body.name, body.slug,
                  body.scope, body.description))

        # Assign permissions
        for perm_slug in body.permissions:
            cur.execute(
                "SELECT id FROM permissions WHERE slug = %s" if USE_POSTGRES
                else "SELECT id FROM permissions WHERE slug = ?",
                (perm_slug,)
            )
            perm = cur.fetchone()
            if perm:
                perm_id = dict(perm)["id"]
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO role_permissions (role_id, permission_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (role_id, perm_id)
                    )
                else:
                    cur.execute(
                        "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?,?)",
                        (role_id, perm_id)
                    )

    return {"message": "Role created", "id": role_id}


# ── Role assignment ───────────────────────────────────────────────────────────

@router.post("/assign")
async def assign_role(
    body: AssignRoleIn,
    current_user: dict = Depends(require_permission("role.assign")),
):
    """Assign a role to a user."""
    tenant_id = body.tenant_id or current_user.get("tenant_id")

    # Verify role exists
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM roles WHERE slug = %s" if USE_POSTGRES
            else "SELECT id FROM roles WHERE slug = ?",
            (body.role_slug,)
        )
        role = cur.fetchone()
        if not role:
            raise HTTPException(404, f"Role '{body.role_slug}' not found")
        role_id = dict(role)["id"]

        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO user_roles (user_id, role_id, tenant_id, assigned_by)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT (user_id, role_id, tenant_id) DO NOTHING
            """, (body.user_id, role_id, tenant_id, str(current_user["id"])))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO user_roles
                    (user_id, role_id, tenant_id, assigned_by)
                VALUES (?,?,?,?)
            """, (body.user_id, role_id, tenant_id, str(current_user["id"])))

    from core.audit import log_action, AuditAction
    log_action(
        AuditAction.ROLE_ASSIGNED,
        user_id=str(current_user["id"]),
        resource_type="user",
        resource_id=body.user_id,
        new_value={"role": body.role_slug, "tenant_id": tenant_id},
        module="identity",
    )

    return {"message": f"Role '{body.role_slug}' assigned to user"}


@router.delete("/assign")
async def revoke_role(
    body: AssignRoleIn,
    current_user: dict = Depends(require_permission("role.assign")),
):
    """Remove a role from a user."""
    tenant_id = body.tenant_id or current_user.get("tenant_id")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM roles WHERE slug = %s" if USE_POSTGRES
            else "SELECT id FROM roles WHERE slug = ?",
            (body.role_slug,)
        )
        role = cur.fetchone()
        if not role:
            raise HTTPException(404, f"Role '{body.role_slug}' not found")
        role_id = dict(role)["id"]

        if USE_POSTGRES:
            cur.execute(
                "DELETE FROM user_roles WHERE user_id=%s AND role_id=%s AND tenant_id=%s",
                (body.user_id, role_id, tenant_id)
            )
        else:
            cur.execute(
                "DELETE FROM user_roles WHERE user_id=? AND role_id=? AND tenant_id=?",
                (body.user_id, role_id, tenant_id)
            )

    return {"message": "Role revoked"}


@router.get("/users/{user_id}/permissions")
async def get_user_permissions_endpoint(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get all permissions for a specific user."""
    tenant_id = current_user.get("tenant_id")
    from core.rbac import get_user_permissions
    db_perms = get_user_permissions(user_id, tenant_id)

    # Also include role-based permissions
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT role FROM users WHERE id = %s" if USE_POSTGRES
            else "SELECT role FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
        role = dict(row).get("role", "candidate") if row else "candidate"

    system_role = SYSTEM_ROLES.get(role, {})
    role_perms = set(system_role.get("permissions", []))
    if "*" in role_perms:
        role_perms = set(ALL_PERMISSIONS.keys())

    all_perms = db_perms | role_perms
    return {
        "user_id": user_id,
        "role": role,
        "permissions": sorted(all_perms),
        "total": len(all_perms),
    }


@router.get("/my-permissions")
async def my_permissions(current_user: dict = Depends(get_current_user)):
    """Get the current user's permissions."""
    role = current_user.get("role", "candidate")
    system_role = SYSTEM_ROLES.get(role, {})
    role_perms = set(system_role.get("permissions", []))
    if "*" in role_perms:
        role_perms = set(ALL_PERMISSIONS.keys())

    tenant_id = str(current_user.get("tenant_id", "")) if current_user.get("tenant_id") else None
    db_perms = get_user_permissions(str(current_user["id"]), tenant_id)
    all_perms = db_perms | role_perms

    return {
        "role": role,
        "permissions": sorted(all_perms),
        "total": len(all_perms),
    }
