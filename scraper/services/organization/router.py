"""
Organization Service Router
Handles organizations, departments, teams, locations.
Powers company profile pages on the job board.
"""

import uuid
import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from core.audit import log_org, AuditAction
from services.identity.dependencies import get_current_user

router = APIRouter(prefix="/organizations", tags=["organization"])
departments_router = APIRouter(prefix="/departments", tags=["organization"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class OrganizationIn(BaseModel):
    name: str
    legal_name: Optional[str] = None
    previous_names: Optional[list] = []
    industry: Optional[str] = None
    size: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = "NG"
    rc_number: Optional[str] = None
    tin: Optional[str] = None
    slug: Optional[str] = None


class DepartmentIn(BaseModel):
    name: str
    code: Optional[str] = None
    parent_id: Optional[str] = None


class LocationIn(BaseModel):
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = "NG"
    is_remote: Optional[bool] = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def row_to_dict(row) -> dict:
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields
    for field in ("previous_names",):
        if field in d and isinstance(d[field], str):
            try:
                d[field] = json.loads(d[field])
            except Exception:
                d[field] = []
    return d


def q(pg, sq="?"):
    return pg if USE_POSTGRES else sq


# ── Organization Routes ───────────────────────────────────────────────────────

@router.get("/all")
def list_all_organizations(
    current_user: dict = Depends(get_current_user),
):
    """
    Return organizations for the job posting dropdown.
    - Platform admins: all organizations
    - Employers: only their own tenant's organization
    """
    role = current_user.get("role", "")
    tenant_id = current_user.get("tenant_id")
    is_admin = role in ("super_admin", "platform_admin")

    with get_conn() as conn:
        cur = conn.cursor()
        if is_admin:
            cur.execute(
                "SELECT id, name, industry, website, logo_url FROM organizations ORDER BY name"
            )
        elif tenant_id:
            # Employers only see their own organization
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT id, name, industry, website, logo_url FROM organizations WHERE tenant_id = {ph} ORDER BY name",
                (tenant_id,)
            )
        else:
            return []
        return [dict(r) for r in cur.fetchall()]


@router.get("")
def list_organizations(
    search: str = Query(""),
    industry: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """List all organizations — used for company directory."""
    conditions = ["is_active = TRUE"] if USE_POSTGRES else ["is_active = 1"]
    params = []

    if search:
        conditions.append("name ILIKE %s" if USE_POSTGRES else "name LIKE ?")
        params.append(f"%{search}%")

    if industry:
        conditions.append("industry = %s" if USE_POSTGRES else "industry = ?")
        params.append(industry)

    where = " AND ".join(conditions)
    params += [limit, offset]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM organizations WHERE {where} ORDER BY name LIMIT {'%s' if USE_POSTGRES else '?'} OFFSET {'%s' if USE_POSTGRES else '?'}",
            params
        )
        return [row_to_dict(r) for r in cur.fetchall()]


@router.post("", status_code=201)
def create_organization(body: OrganizationIn):
    """Create a new organization. Auto-generates slug from name if not provided."""
    import re as _re
    org_id = str(uuid.uuid4())
    prev_names = json.dumps(body.previous_names or [])

    # Generate slug from name if not provided
    slug = (body.slug or "").strip()
    if not slug:
        slug = _re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")

    with get_conn() as conn:
        cur = conn.cursor()
        # Check for duplicate name or slug
        if USE_POSTGRES:
            cur.execute("SELECT id FROM organizations WHERE name ILIKE %s OR slug = %s",
                        (body.name, slug))
        else:
            cur.execute("SELECT id FROM organizations WHERE name LIKE ? OR slug = ?",
                        (body.name, slug))
        existing = cur.fetchone()
        if existing:
            raise HTTPException(409, f"Organization '{body.name}' already exists")

        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO organizations
                    (id, name, legal_name, previous_names, industry, size,
                     website, logo_url, description, country, rc_number, tin, slug)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING *
            """, (org_id, body.name, body.legal_name, prev_names,
                  body.industry, body.size, body.website, body.logo_url,
                  body.description, body.country, body.rc_number, body.tin, slug))
            result = row_to_dict(cur.fetchone())
        else:
            cur.execute("""
                INSERT INTO organizations
                    (id, name, legal_name, previous_names, industry, size,
                     website, logo_url, description, country, rc_number, tin, slug)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (org_id, body.name, body.legal_name, prev_names,
                  body.industry, body.size, body.website, body.logo_url,
                  body.description, body.country, body.rc_number, body.tin, slug))
            cur.execute("SELECT * FROM organizations WHERE id = ?", (org_id,))
            result = row_to_dict(cur.fetchone())
        log_org(AuditAction.ORG_CREATED, "system", result.get("id",""), result.get("name",""))
        return result


@router.get("/slug/{slug}")
def get_organization_by_slug(slug: str):
    """Get organization by slug — for company profile URLs."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM organizations WHERE slug = %s AND is_active = TRUE" if USE_POSTGRES
            else "SELECT * FROM organizations WHERE slug = ? AND is_active = 1",
            (slug,)
        )
        org = cur.fetchone()
        if not org:
            raise HTTPException(404, "Organization not found")
        return row_to_dict(org)


@router.get("/{org_id}")
def get_organization(org_id: str):
    """Get organization by ID."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM organizations WHERE id = %s" if USE_POSTGRES
            else "SELECT * FROM organizations WHERE id = ?",
            (org_id,)
        )
        org = cur.fetchone()
        if not org:
            raise HTTPException(404, "Organization not found")
        return row_to_dict(org)


@router.patch("/{org_id}")
def update_organization(org_id: str, body: OrganizationIn):
    """Update organization details."""
    prev_names = json.dumps(body.previous_names or [])
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                UPDATE organizations SET
                    name=%s, legal_name=%s, previous_names=%s, industry=%s,
                    size=%s, website=%s, logo_url=%s, description=%s,
                    country=%s, rc_number=%s, tin=%s, updated_at=NOW()
                WHERE id=%s
            """, (body.name, body.legal_name, prev_names, body.industry,
                  body.size, body.website, body.logo_url, body.description,
                  body.country, body.rc_number, body.tin, org_id))
        else:
            cur.execute("""
                UPDATE organizations SET
                    name=?, legal_name=?, previous_names=?, industry=?,
                    size=?, website=?, logo_url=?, description=?,
                    country=?, rc_number=?, tin=?, updated_at=datetime('now')
                WHERE id=?
            """, (body.name, body.legal_name, prev_names, body.industry,
                  body.size, body.website, body.logo_url, body.description,
                  body.country, body.rc_number, body.tin, org_id))
    return {"message": "Organization updated"}


@router.delete("/{org_id}", status_code=204)
def delete_organization(org_id: str):
    """Soft delete organization."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE organizations SET is_active = FALSE WHERE id = %s" if USE_POSTGRES
            else "UPDATE organizations SET is_active = 0 WHERE id = ?",
            (org_id,)
        )


@router.get("/{org_id}/jobs")
def get_organization_jobs(
    org_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """Get all active jobs for a company — for company profile page."""
    with get_conn() as conn:
        cur = conn.cursor()
        # Get org name first
        cur.execute(
            "SELECT name FROM organizations WHERE id = %s" if USE_POSTGRES
            else "SELECT name FROM organizations WHERE id = ?",
            (org_id,)
        )
        org = cur.fetchone()
        if not org:
            raise HTTPException(404, "Organization not found")

        org_name = dict(org)["name"]

        # Match by company name (works for both scraped and manual jobs)
        # organization_id match will work once jobs are linked to orgs in Phase 3
        if USE_POSTGRES:
            cur.execute("""
                SELECT * FROM jobs
                WHERE is_active = 1
                  AND company ILIKE %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
            """, (f"%{org_name}%", limit, offset))
        else:
            cur.execute("""
                SELECT * FROM jobs
                WHERE is_active = 1
                  AND company LIKE ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """, (f"%{org_name}%", limit, offset))

        jobs = [dict(r) for r in cur.fetchall()]

        # Count
        if USE_POSTGRES:
            cur.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active = 1 AND company ILIKE %s",
                (f"%{org_name}%",)
            )
        else:
            cur.execute(
                "SELECT COUNT(*) FROM jobs WHERE is_active = 1 AND company LIKE ?",
                (f"%{org_name}%",)
            )

        row = cur.fetchone()
        total = list(dict(row).values())[0] if USE_POSTGRES else row[0]

        return {"total": int(total), "jobs": jobs, "organization": org_name}


@router.get("/{org_id}/departments")
def list_departments(org_id: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM departments WHERE organization_id = %s AND is_active = TRUE ORDER BY name" if USE_POSTGRES
            else "SELECT * FROM departments WHERE organization_id = ? AND is_active = 1 ORDER BY name",
            (org_id,)
        )
        return [dict(r) for r in cur.fetchall()]


@router.post("/{org_id}/departments", status_code=201)
def create_department(org_id: str, body: DepartmentIn):
    dept_id = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO departments (id, organization_id, name, code, parent_id) VALUES (%s,%s,%s,%s,%s)",
                (dept_id, org_id, body.name, body.code, body.parent_id)
            )
        else:
            cur.execute(
                "INSERT INTO departments (id, organization_id, name, code, parent_id) VALUES (?,?,?,?,?)",
                (dept_id, org_id, body.name, body.code, body.parent_id)
            )
    return {"id": dept_id, "name": body.name, "organization_id": org_id}


@router.get("/{org_id}/locations")
def list_locations(org_id: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM locations WHERE organization_id = %s AND is_active = TRUE ORDER BY name" if USE_POSTGRES
            else "SELECT * FROM locations WHERE organization_id = ? AND is_active = 1 ORDER BY name",
            (org_id,)
        )
        return [dict(r) for r in cur.fetchall()]


@router.post("/{org_id}/locations", status_code=201)
def create_location(org_id: str, body: LocationIn):
    loc_id = str(uuid.uuid4())
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO locations
                    (id, organization_id, name, address, city, state, country, is_remote)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (loc_id, org_id, body.name, body.address, body.city,
                  body.state, body.country, body.is_remote))
        else:
            cur.execute("""
                INSERT INTO locations
                    (id, organization_id, name, address, city, state, country, is_remote)
                VALUES (?,?,?,?,?,?,?,?)
            """, (loc_id, org_id, body.name, body.address, body.city,
                  body.state, body.country, 1 if body.is_remote else 0))
    return {"id": loc_id, "name": body.name, "organization_id": org_id}


# ── Standalone departments router ─────────────────────────────────────────────

@departments_router.get("")
def list_all_departments():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM departments WHERE is_active = TRUE ORDER BY name" if USE_POSTGRES
            else "SELECT * FROM departments WHERE is_active = 1 ORDER BY name"
        )
        return [dict(r) for r in cur.fetchall()]
