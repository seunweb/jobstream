"""
Analytics & Reporting Router
Phase 12 — Platform, employer and candidate analytics.

Design principles:
- Never run heavy analytics on transactional tables directly
- Aggregate queries are cached where possible
- All exports are streamed as CSV
- Tenant-scoped: employers only see their own data
"""

import csv
import io
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/analytics", tags=["analytics"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin access required")
    return current_user


def require_org(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") not in (
        "super_admin", "platform_admin", "org_owner", "hr_admin", "recruiter"
    ):
        raise HTTPException(403, "Employer access required")
    return current_user


def ph():
    return "%s" if USE_POSTGRES else "?"


def count_row(row) -> int:
    if not row:
        return 0
    d = dict(row)
    return int(list(d.values())[0])


def days_ago(n: int) -> str:
    if USE_POSTGRES:
        return f"NOW() - INTERVAL '{n} days'"
    return f"datetime('now', '-{n} days')"


# ════════════════════════════════════════════════════════════════
# PLATFORM ANALYTICS (admin only)
# ════════════════════════════════════════════════════════════════

@router.get("/platform/overview")
async def platform_overview(
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(require_admin),
):
    """Platform-wide KPIs for the admin dashboard."""
    with get_conn() as conn:
        cur = conn.cursor()

        # Core counts
        total_users     = count_row(_q(cur, "SELECT COUNT(*) FROM users"))
        total_jobs      = count_row(_q(cur, "SELECT COUNT(*) FROM jobs WHERE is_active=1"))
        total_orgs      = count_row(_q(cur, "SELECT COUNT(*) FROM organizations WHERE is_active=1"))
        total_apps      = count_row(_q(cur, "SELECT COUNT(*) FROM applications"))
        total_tenants   = count_row(_q(cur, "SELECT COUNT(*) FROM tenants WHERE status='active'"))

        # Growth over period
        new_users   = _count_since(cur, "users", "created_at", days)
        new_jobs    = _count_since(cur, "jobs", "created_at", days)
        new_apps    = _count_since(cur, "applications", "submitted_at", days)

        # Daily signups last 30 days
        daily_signups = _daily_counts(cur, "users", "created_at", 30)

        # Daily applications last 30 days
        daily_apps = _daily_counts(cur, "applications", "submitted_at", 30)

        # Jobs by type
        cur.execute(
            "SELECT job_type, COUNT(*) as count FROM jobs "
            "WHERE is_active=1 GROUP BY job_type ORDER BY count DESC"
        )
        jobs_by_type = [dict(r) for r in cur.fetchall()]

        # Jobs by source
        cur.execute(
            "SELECT source, COUNT(*) as count FROM jobs "
            "WHERE is_active=1 GROUP BY source ORDER BY count DESC"
        )
        jobs_by_source = [dict(r) for r in cur.fetchall()]

        # Top hiring companies
        cur.execute(
            "SELECT company, COUNT(*) as job_count FROM jobs "
            "WHERE is_active=1 GROUP BY company ORDER BY job_count DESC LIMIT 10"
        )
        top_companies = [dict(r) for r in cur.fetchall()]

        # Application funnel
        cur.execute(
            "SELECT status, COUNT(*) as count FROM applications "
            "GROUP BY status ORDER BY count DESC"
        )
        app_funnel = [dict(r) for r in cur.fetchall()]

        # Revenue (if billing enabled)
        if USE_POSTGRES:
            cur.execute(
                "SELECT COALESCE(SUM(amount),0) as total FROM billing_transactions "
                "WHERE status='success'"
            )
        else:
            cur.execute(
                "SELECT COALESCE(SUM(amount),0) as total FROM billing_transactions "
                "WHERE status='success'"
            )
        rev_row = cur.fetchone()
        total_revenue = int(dict(rev_row)["total"]) if rev_row else 0

    return {
        "period_days": days,
        "totals": {
            "users": total_users,
            "jobs": total_jobs,
            "organizations": total_orgs,
            "applications": total_apps,
            "tenants": total_tenants,
            "revenue_ngn": total_revenue,
        },
        "growth": {
            "new_users": new_users,
            "new_jobs": new_jobs,
            "new_applications": new_apps,
        },
        "charts": {
            "daily_signups": daily_signups,
            "daily_applications": daily_apps,
            "jobs_by_type": jobs_by_type,
            "jobs_by_source": jobs_by_source,
            "application_funnel": app_funnel,
        },
        "top_companies": top_companies,
    }


@router.get("/platform/hiring")
async def platform_hiring_analytics(
    days: int = Query(90),
    current_user: dict = Depends(require_admin),
):
    """Platform-wide hiring funnel analytics."""
    with get_conn() as conn:
        cur = conn.cursor()

        # Conversion rates
        total_apps = count_row(_q(cur, "SELECT COUNT(*) FROM applications"))
        hired = _count_where(cur, "applications", "status='hired'")
        rejected = _count_where(cur, "applications", "status='rejected'")
        shortlisted = _count_where(cur, "applications", "status='shortlisted'")
        interviewed = _count_where(cur, "applications", "status='interview'")

        hire_rate = round((hired / total_apps * 100), 1) if total_apps else 0

        # Avg time to hire (days between submitted_at and status change)
        # Approximation using created_at
        if USE_POSTGRES:
            cur.execute("""
                SELECT AVG(
                    EXTRACT(EPOCH FROM (NOW() - submitted_at)) / 86400
                ) as avg_days
                FROM applications WHERE status='hired'
            """)
        else:
            cur.execute("""
                SELECT AVG(
                    (julianday('now') - julianday(submitted_at))
                ) as avg_days
                FROM applications WHERE status='hired'
            """)
        row = cur.fetchone()
        avg_ttf = round(dict(row).get("avg_days") or 0, 1)

        # Monthly hiring trend
        monthly_hired = _monthly_counts(cur, "applications",
                                        "submitted_at", 6, "status='hired'")

        # Top departments hiring
        cur.execute(
            "SELECT j.department, COUNT(a.id) as app_count "
            "FROM applications a JOIN jobs j ON a.job_id=j.id "
            "GROUP BY j.department ORDER BY app_count DESC LIMIT 8"
        )
        by_dept = [dict(r) for r in cur.fetchall()]

    return {
        "funnel": {
            "total_applications": total_apps,
            "shortlisted": shortlisted,
            "interviewed": interviewed,
            "hired": hired,
            "rejected": rejected,
            "hire_rate_pct": hire_rate,
        },
        "avg_time_to_hire_days": avg_ttf,
        "monthly_hired": monthly_hired,
        "by_department": by_dept,
    }


# ════════════════════════════════════════════════════════════════
# EMPLOYER / TENANT ANALYTICS
# ════════════════════════════════════════════════════════════════

@router.get("/employer/overview")
async def employer_overview(
    days: int = Query(30),
    current_user: dict = Depends(require_org),
):
    """Employer hiring analytics for their workspace."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "No workspace. Create one first.")

    with get_conn() as conn:
        cur = conn.cursor()
        p = ph()

        # Active jobs
        cur.execute(
            f"SELECT COUNT(*) FROM jobs WHERE tenant_id={p} AND is_active=1",
            (tenant_id,)
        )
        active_jobs = count_row(cur.fetchone())

        # Total applications across workspace jobs
        cur.execute(
            f"SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id "
            f"WHERE j.tenant_id={p}",
            (tenant_id,)
        )
        total_apps = count_row(cur.fetchone())

        # Applications by status
        cur.execute(
            f"SELECT a.status, COUNT(*) as count FROM applications a "
            f"JOIN jobs j ON a.job_id=j.id WHERE j.tenant_id={p} "
            f"GROUP BY a.status ORDER BY count DESC",
            (tenant_id,)
        )
        by_status = [dict(r) for r in cur.fetchall()]

        # Hired this period
        if USE_POSTGRES:
            cur.execute(
                f"SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id "
                f"WHERE j.tenant_id={p} AND a.status='hired' "
                f"AND a.submitted_at > NOW() - INTERVAL '{days} days'",
                (tenant_id,)
            )
        else:
            cur.execute(
                f"SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id "
                f"WHERE j.tenant_id={p} AND a.status='hired' "
                f"AND a.submitted_at > datetime('now', '-{days} days')",
                (tenant_id,)
            )
        hired_period = count_row(cur.fetchone())

        # New applications this period
        if USE_POSTGRES:
            cur.execute(
                f"SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id "
                f"WHERE j.tenant_id={p} "
                f"AND a.submitted_at > NOW() - INTERVAL '{days} days'",
                (tenant_id,)
            )
        else:
            cur.execute(
                f"SELECT COUNT(*) FROM applications a JOIN jobs j ON a.job_id=j.id "
                f"WHERE j.tenant_id={p} "
                f"AND a.submitted_at > datetime('now', '-{days} days')",
                (tenant_id,)
            )
        new_apps_period = count_row(cur.fetchone())

        # Top performing jobs
        cur.execute(
            f"SELECT j.id, j.title, j.company, COUNT(a.id) as app_count, "
            f"SUM(CASE WHEN a.status='hired' THEN 1 ELSE 0 END) as hired_count "
            f"FROM jobs j LEFT JOIN applications a ON a.job_id=j.id "
            f"WHERE j.tenant_id={p} AND j.is_active=1 "
            f"GROUP BY j.id, j.title, j.company ORDER BY app_count DESC LIMIT 10",
            (tenant_id,)
        )
        top_jobs = [dict(r) for r in cur.fetchall()]

        # Daily applications trend
        daily_apps = _daily_counts_tenant(cur, tenant_id, days=min(days, 30))

        # Source breakdown (where candidates found the job)
        cur.execute(
            f"SELECT COALESCE(a.source, 'direct') as source, COUNT(*) as count "
            f"FROM applications a JOIN jobs j ON a.job_id=j.id "
            f"WHERE j.tenant_id={p} GROUP BY source ORDER BY count DESC",
            (tenant_id,)
        )
        by_source = [dict(r) for r in cur.fetchall()]

    hire_rate = round((hired_period / new_apps_period * 100), 1) if new_apps_period else 0

    return {
        "period_days": days,
        "summary": {
            "active_jobs": active_jobs,
            "total_applications": total_apps,
            "new_applications": new_apps_period,
            "hired": hired_period,
            "hire_rate_pct": hire_rate,
        },
        "pipeline": by_status,
        "top_jobs": top_jobs,
        "daily_trend": daily_apps,
        "by_source": by_source,
    }


@router.get("/employer/jobs/{job_id}")
async def job_analytics(
    job_id: int,
    current_user: dict = Depends(require_org),
):
    """Detailed analytics for a specific job."""
    tenant_id = current_user.get("tenant_id")

    with get_conn() as conn:
        cur = conn.cursor()
        p = ph()

        # Verify job belongs to tenant
        cur.execute(
            f"SELECT id, title, company, created_at FROM jobs WHERE id={p} AND tenant_id={p}",
            (job_id, tenant_id)
        )
        job = cur.fetchone()
        if not job and current_user.get("role") not in ("super_admin", "platform_admin"):
            raise HTTPException(404, "Job not found")
        job = dict(job) if job else {}

        # Applications over time (daily for last 30 days)
        if USE_POSTGRES:
            cur.execute("""
                SELECT DATE(submitted_at) as date, COUNT(*) as count
                FROM applications WHERE job_id=%s
                GROUP BY DATE(submitted_at)
                ORDER BY date
            """, (job_id,))
        else:
            cur.execute("""
                SELECT DATE(submitted_at) as date, COUNT(*) as count
                FROM applications WHERE job_id=?
                GROUP BY DATE(submitted_at)
                ORDER BY date
            """, (job_id,))
        daily = [dict(r) for r in cur.fetchall()]

        # Status breakdown
        cur.execute(
            f"SELECT status, COUNT(*) as count FROM applications "
            f"WHERE job_id={p} GROUP BY status ORDER BY count DESC",
            (job_id,)
        )
        by_status = [dict(r) for r in cur.fetchall()]

        # Total
        cur.execute(
            f"SELECT COUNT(*) FROM applications WHERE job_id={p}", (job_id,)
        )
        total = count_row(cur.fetchone())

    hired_count = next((s["count"] for s in by_status if s["status"] == "hired"), 0)
    conv_rate = round((hired_count / total * 100), 1) if total else 0

    return {
        "job": job,
        "total_applications": total,
        "hired": hired_count,
        "conversion_rate_pct": conv_rate,
        "by_status": by_status,
        "daily_trend": daily,
    }


# ════════════════════════════════════════════════════════════════
# CANDIDATE ANALYTICS
# ════════════════════════════════════════════════════════════════

@router.get("/candidate/overview")
async def candidate_analytics(
    current_user: dict = Depends(get_current_user),
):
    """Analytics for the current candidate — application success rates."""
    email = current_user.get("email", "")

    with get_conn() as conn:
        cur = conn.cursor()
        p = ph()

        cur.execute(
            f"SELECT COUNT(*) FROM applications WHERE email={p}", (email,)
        )
        total = count_row(cur.fetchone())

        cur.execute(
            f"SELECT status, COUNT(*) as count FROM applications "
            f"WHERE email={p} GROUP BY status ORDER BY count DESC",
            (email,)
        )
        by_status = [dict(r) for r in cur.fetchall()]

        # Response rate (anything beyond 'new')
        responded = sum(
            s["count"] for s in by_status
            if s["status"] not in ("new", "rejected", "withdrawn")
        )
        response_rate = round((responded / total * 100), 1) if total else 0

        # Applications by month
        if USE_POSTGRES:
            cur.execute("""
                SELECT TO_CHAR(submitted_at, 'YYYY-MM') as month,
                       COUNT(*) as count
                FROM applications WHERE email=%s
                GROUP BY month ORDER BY month DESC LIMIT 6
            """, (email,))
        else:
            cur.execute("""
                SELECT STRFTIME('%Y-%m', submitted_at) as month,
                       COUNT(*) as count
                FROM applications WHERE email=?
                GROUP BY month ORDER BY month DESC LIMIT 6
            """, (email,))
        monthly = [dict(r) for r in cur.fetchall()]

        # Recent applications with job details
        if USE_POSTGRES:
            cur.execute("""
                SELECT a.id, a.status, a.submitted_at,
                       j.title as job_title, j.company
                FROM applications a
                LEFT JOIN jobs j ON a.job_id=j.id
                WHERE a.email=%s
                ORDER BY a.submitted_at DESC LIMIT 10
            """, (email,))
        else:
            cur.execute("""
                SELECT a.id, a.status, a.submitted_at,
                       j.title as job_title, j.company
                FROM applications a
                LEFT JOIN jobs j ON a.job_id=j.id
                WHERE a.email=?
                ORDER BY a.submitted_at DESC LIMIT 10
            """, (email,))
        recent = [dict(r) for r in cur.fetchall()]

    hired = next((s["count"] for s in by_status if s["status"] == "hired"), 0)
    shortlisted = next((s["count"] for s in by_status if s["status"] == "shortlisted"), 0)

    return {
        "summary": {
            "total_applications": total,
            "shortlisted": shortlisted,
            "hired": hired,
            "response_rate_pct": response_rate,
        },
        "by_status": by_status,
        "monthly_trend": list(reversed(monthly)),
        "recent_applications": recent,
    }


# ════════════════════════════════════════════════════════════════
# CSV EXPORTS
# ════════════════════════════════════════════════════════════════

@router.get("/export/applications")
async def export_applications_csv(
    current_user: dict = Depends(require_org),
):
    """Export all workspace applications as CSV."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id and current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(400, "No workspace found")

    with get_conn() as conn:
        cur = conn.cursor()
        if tenant_id and current_user.get("role") not in ("super_admin", "platform_admin"):
            cur.execute("""
                SELECT a.id, a.name, a.email, a.phone, a.status,
                       j.title as job_title, j.company, j.location,
                       a.submitted_at, a.cover_note, a.resume_url
                FROM applications a
                JOIN jobs j ON a.job_id=j.id
                WHERE j.tenant_id=%s
                ORDER BY a.submitted_at DESC
            """ if USE_POSTGRES else """
                SELECT a.id, a.name, a.email, a.phone, a.status,
                       j.title as job_title, j.company, j.location,
                       a.submitted_at, a.cover_note, a.resume_url
                FROM applications a
                JOIN jobs j ON a.job_id=j.id
                WHERE j.tenant_id=?
                ORDER BY a.submitted_at DESC
            """, (tenant_id,))
        else:
            cur.execute("""
                SELECT a.id, a.name, a.email, a.phone, a.status,
                       j.title as job_title, j.company, j.location,
                       a.submitted_at, a.cover_note, a.resume_url
                FROM applications a
                LEFT JOIN jobs j ON a.job_id=j.id
                ORDER BY a.submitted_at DESC
            """)
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Email", "Phone", "Status",
                     "Job Title", "Company", "Location",
                     "Applied At", "Cover Note", "Resume URL"])
    for row in rows:
        writer.writerow(list(dict(row).values()))

    output.seek(0)
    filename = f"applications_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/export/jobs")
async def export_jobs_csv(
    current_user: dict = Depends(require_admin),
):
    """Export all jobs as CSV (admin)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, company, location, job_type, department, "
            "source, is_active, created_at FROM jobs ORDER BY created_at DESC"
        )
        rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Title", "Company", "Location", "Type",
                     "Department", "Source", "Active", "Created At"])
    for row in rows:
        writer.writerow(list(dict(row).values()))

    output.seek(0)
    filename = f"jobs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── DB query helpers ──────────────────────────────────────────────────────────

def _q(cur, sql):
    cur.execute(sql)
    return cur.fetchone()


def _count_since(cur, table, col, days) -> int:
    if USE_POSTGRES:
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} > NOW() - INTERVAL '{days} days'"
        )
    else:
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col} > datetime('now', '-{days} days')"
        )
    return count_row(cur.fetchone())


def _count_where(cur, table, condition) -> int:
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {condition}")
    return count_row(cur.fetchone())


def _daily_counts(cur, table, col, days) -> list:
    if USE_POSTGRES:
        cur.execute(f"""
            SELECT DATE({col}) as date, COUNT(*) as count
            FROM {table}
            WHERE {col} > NOW() - INTERVAL '{days} days'
            GROUP BY DATE({col}) ORDER BY date
        """)
    else:
        cur.execute(f"""
            SELECT DATE({col}) as date, COUNT(*) as count
            FROM {table}
            WHERE {col} > datetime('now', '-{days} days')
            GROUP BY DATE({col}) ORDER BY date
        """)
    return [dict(r) for r in cur.fetchall()]


def _daily_counts_tenant(cur, tenant_id, days=30) -> list:
    p = ph()
    if USE_POSTGRES:
        cur.execute(f"""
            SELECT DATE(a.submitted_at) as date, COUNT(*) as count
            FROM applications a JOIN jobs j ON a.job_id=j.id
            WHERE j.tenant_id={p}
            AND a.submitted_at > NOW() - INTERVAL '{days} days'
            GROUP BY DATE(a.submitted_at) ORDER BY date
        """, (tenant_id,))
    else:
        cur.execute(f"""
            SELECT DATE(a.submitted_at) as date, COUNT(*) as count
            FROM applications a JOIN jobs j ON a.job_id=j.id
            WHERE j.tenant_id={p}
            AND a.submitted_at > datetime('now', '-{days} days')
            GROUP BY DATE(a.submitted_at) ORDER BY date
        """, (tenant_id,))
    return [dict(r) for r in cur.fetchall()]


def _monthly_counts(cur, table, col, months, condition="") -> list:
    where = f"AND {condition}" if condition else ""
    if USE_POSTGRES:
        cur.execute(f"""
            SELECT TO_CHAR({col}, 'YYYY-MM') as month, COUNT(*) as count
            FROM {table}
            WHERE {col} > NOW() - INTERVAL '{months * 30} days' {where}
            GROUP BY month ORDER BY month
        """)
    else:
        cur.execute(f"""
            SELECT STRFTIME('%Y-%m', {col}) as month, COUNT(*) as count
            FROM {table}
            WHERE {col} > datetime('now', '-{months * 30} days') {where}
            GROUP BY month ORDER BY month
        """)
    return [dict(r) for r in cur.fetchall()]
