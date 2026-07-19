"""
Recruitment Service Router
Handles jobs, applications, scraping, interviews, offers.
Preserves all existing endpoints exactly — zero breaking changes.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends, Request
from pydantic import BaseModel

from core.audit import log_job, log_application, log_action, AuditAction
from core.database import (
    get_conn, USE_POSTGRES,
    get_companies, add_company, delete_company, update_company_industry,
    get_jobs, get_job, upsert_jobs, mark_jobs_inactive,
    create_application, get_applications, update_application_status,
    start_scrape_run, finish_scrape_run, get_scrape_history,
)
from services.identity.dependencies import get_current_user, get_optional_user
import logging
log = logging.getLogger(__name__)

router = APIRouter(tags=["recruitment"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CompanyIn(BaseModel):
    name: str
    url: str
    industry: str = ""
    logo_url: str = ""


class CompanyUpdateIn(BaseModel):
    industry: str = ""
    logo_url: str = ""


class ApplicationIn(BaseModel):
    name: str
    email: str
    phone: str = ""
    resume_url: str = ""
    cover_note: str = ""


class StatusUpdate(BaseModel):
    status: str


# ── Companies ─────────────────────────────────────────────────────────────────

@router.get("/companies")
def list_companies():
    return get_companies()


@router.post("/companies", status_code=201)
def create_company(body: CompanyIn):
    try:
        return add_company(body.name, body.url, body.industry, body.logo_url)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.patch("/companies/{company_id}")
def patch_company(company_id: int, body: CompanyUpdateIn):
    """Update a company's industry (used to retroactively tag scraped jobs)."""
    try:
        return update_company_industry(company_id, body.industry)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.delete("/companies/{company_id}", status_code=204)
def remove_company(company_id: int):
    delete_company(company_id)


@router.get("/companies/export")
def export_companies(current_user: dict = Depends(get_current_user)):
    """Export all active companies as JSON — use this to migrate companies between environments."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    companies = get_companies(active_only=False)
    return {"companies": companies, "count": len(companies)}


@router.post("/companies/import")
async def import_companies(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    Bulk import companies from a JSON list.
    Accepts: {"companies": [{"name": "...", "url": "...", "industry": "..."}, ...]}
    Skips duplicates (by URL). Use to migrate companies from local to Railway.
    """
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    body = await request.json()
    companies = body.get("companies", [])
    if not companies:
        raise HTTPException(400, "No companies provided")

    inserted = 0
    skipped = 0
    with get_conn() as conn:
        cur = conn.cursor()
        for c in companies:
            name = (c.get("name") or "").strip()
            url = (c.get("url") or "").strip()
            industry = (c.get("industry") or "").strip()
            if not name or not url:
                skipped += 1
                continue
            try:
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO companies (name, url, industry, active) VALUES (%s, %s, %s, 1) "
                        "ON CONFLICT (url) DO UPDATE SET name = EXCLUDED.name, industry = EXCLUDED.industry",
                        (name, url, industry)
                    )
                else:
                    cur.execute(
                        "INSERT OR REPLACE INTO companies (name, url, industry, active) VALUES (?, ?, ?, 1)",
                        (name, url, industry)
                    )
                inserted += 1
            except Exception as e:
                log.warning(f"Import skip {name}: {e}")
                skipped += 1

    return {
        "message": f"Imported {inserted} companies, skipped {skipped}",
        "inserted": inserted,
        "skipped": skipped,
    }


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(
    search: str = Query(""),
    job_type: str = Query(""),
    department: str = Query(""),
    company: str = Query(""),
    industry: str = Query(""),
    location: str = Query(""),
    source: str = Query(""),
    include_inactive: int = Query(0),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    current_user: dict = Depends(get_optional_user),
):
    # Employers can see their own inactive jobs
    show_inactive = bool(include_inactive) and current_user and current_user.get("role") in (
        "org_owner", "hr_admin", "super_admin", "platform_admin"
    )
    # Tenant isolation: if requesting manual jobs, scope to current tenant
    tenant_filter = ""
    if source == "manual" and current_user:
        tenant_id = current_user.get("tenant_id")
        role = current_user.get("role", "")
        if role not in ("super_admin", "platform_admin") and tenant_id:
            tenant_filter = tenant_id
        elif not tenant_id and role not in ("super_admin", "platform_admin"):
            # No tenant — return empty
            return {"total": 0, "limit": limit, "offset": offset, "jobs": []}

    jobs, total = get_jobs(
        search=search, job_type=job_type, department=department,
        company=company, industry=industry, location=location,
        source=source,
        include_inactive=show_inactive,
        tenant_id=tenant_filter,
        limit=limit, offset=offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "jobs": jobs}


@router.get("/jobs/mine")
def get_my_jobs(
    current_user: dict = Depends(get_current_user),
):
    """
    Get jobs belonging to the current user's tenant ONLY.
    Strict tenant isolation — never returns another tenant's jobs.
    """
    tenant_id = current_user.get("tenant_id")
    user_id = str(current_user.get("id", ""))
    role = current_user.get("role", "")

    # Super/platform admins see all manual jobs for oversight
    is_platform_admin = role in ("super_admin", "platform_admin")

    with get_conn() as conn:
        cur = conn.cursor()

        if is_platform_admin and not tenant_id:
            # Platform admin with no tenant — show all for oversight only
            cur.execute(
                "SELECT * FROM jobs WHERE source = 'manual' ORDER BY created_at DESC"
                if USE_POSTGRES else
                "SELECT * FROM jobs WHERE source = 'manual' ORDER BY created_at DESC"
            )
        elif tenant_id:
            # Strict isolation: only jobs belonging to THIS tenant
            cur.execute(
                "SELECT * FROM jobs WHERE tenant_id = %s AND source = 'manual' ORDER BY created_at DESC"
                if USE_POSTGRES else
                "SELECT * FROM jobs WHERE tenant_id = ? AND source = 'manual' ORDER BY created_at DESC",
                (tenant_id,)
            )
        else:
            # No tenant assigned — return empty, not another company's jobs
            return {"jobs": [], "total": 0}

        jobs = [dict(r) for r in cur.fetchall()]
    return {"jobs": jobs, "total": len(jobs)}


@router.post("/jobs/backfill-industry")
async def backfill_job_industries(
    current_user: dict = Depends(get_current_user),
):
    """
    Admin: for every job that has no industry set, look up the company
    in the companies table and apply that industry. Run once after
    setting industries on existing companies.
    """
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    updated = 0
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, industry FROM companies "
            "WHERE industry IS NOT NULL AND industry != '' AND active = 1"
        )
        companies = {dict(r)["name"]: dict(r)["industry"] for r in cur.fetchall()}
        log.info(f"Backfill industry: {len(companies)} companies with industry set")
        for company_name, industry in companies.items():
            if USE_POSTGRES:
                cur.execute(
                    "UPDATE jobs SET industry = %s "
                    "WHERE company ILIKE %s AND (industry IS NULL OR industry = '')",
                    (industry, company_name)
                )
            else:
                cur.execute(
                    "UPDATE jobs SET industry = ? "
                    "WHERE company LIKE ? AND (industry IS NULL OR industry = '')",
                    (industry, company_name)
                )
            updated += cur.rowcount

    return {"message": f"Updated {updated} jobs with industry from {len(companies)} companies"}



@router.post("/jobs/{job_id}/save", status_code=201)
async def save_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Save a job for later."""
    user_id = str(current_user["id"])
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO saved_jobs (user_id, job_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, job_id) DO NOTHING
            """, (user_id, job_id))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO saved_jobs (user_id, job_id)
                VALUES (?, ?)
            """, (user_id, job_id))
    return {"message": "Job saved"}


@router.delete("/jobs/{job_id}/save", status_code=204)
async def unsave_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Remove a saved job."""
    user_id = str(current_user["id"])
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM saved_jobs WHERE user_id = %s AND job_id = %s" if USE_POSTGRES
            else "DELETE FROM saved_jobs WHERE user_id = ? AND job_id = ?",
            (user_id, job_id)
        )


@router.get("/jobs/saved")
async def get_saved_jobs(current_user: dict = Depends(get_current_user)):
    """Get all jobs saved by the current user."""
    user_id = str(current_user["id"])
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT j.*, s.saved_at
                FROM jobs j
                JOIN saved_jobs s ON j.id = s.job_id
                WHERE s.user_id = %s AND j.is_active = 1
                ORDER BY s.saved_at DESC
            """, (user_id,))
        else:
            cur.execute("""
                SELECT j.*, s.saved_at
                FROM jobs j
                JOIN saved_jobs s ON j.id = s.job_id
                WHERE s.user_id = ? AND j.is_active = 1
                ORDER BY s.saved_at DESC
            """, (user_id,))
        return [dict(r) for r in cur.fetchall()]


@router.get("/jobs/saved/ids")
async def get_saved_job_ids(request: Request):
    """Get IDs of saved jobs. Returns empty list if not authenticated."""
    from services.identity.security import decode_token
    try:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return []
        payload = decode_token(auth[7:])
        if not payload:
            return []
        user_id = payload.get("sub", "")
        if not user_id:
            return []
    except Exception:
        return []

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT job_id FROM saved_jobs WHERE user_id = %s" if USE_POSTGRES
            else "SELECT job_id FROM saved_jobs WHERE user_id = ?",
            (user_id,)
        )
        return [row[0] if not USE_POSTGRES else dict(row)["job_id"]
                for row in cur.fetchall()]


# ── Manual Job Posting ────────────────────────────────────────────────────────

class ManualJobIn(BaseModel):
    title: str
    company: str
    organization_id: Optional[str] = None
    location: str = "Lagos, Nigeria"
    job_type: str = "Full-time"
    department: str = "General"
    description: str = ""
    salary: str = ""
    apply_url: str = ""
    apply_email: str = ""
    apply_mode: str = "insite"  # insite | url | email
    deadline: Optional[str] = None  # ISO date string e.g. "2026-08-01"
    is_draft: bool = False  # True = save as draft (not published)



@router.get("/jobs/{job_id}")
def get_single_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ── Applications ──────────────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/apply", status_code=201)
async def apply_for_job(
    job_id: int,
    body: ApplicationIn,
    current_user: dict = Depends(get_current_user),
):
    """Submit application — requires authentication."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    data = body.dict()
    if not data.get("name"):
        data["name"] = current_user.get("full_name", "")
    if not data.get("email"):
        data["email"] = current_user.get("email", "")
    application = create_application(job_id, data)

    # Send confirmation email (non-blocking)
    try:
        send_application_confirmation(
            to_email=data["email"],
            full_name=data["name"],
            job_title=job.get("title", ""),
            company=job.get("company", ""),
        )
    except Exception as e:
        logging.getLogger(__name__).error(f"Confirmation email failed: {e}")

    log_application(
        AuditAction.APPLICATION_SUBMITTED,
        user_id=str(current_user["id"]),
        app_id=application.get("id", job_id),
        job_title=job.get("title", ""),
        new_status="new",
    )
    return {"message": "Application submitted", "application": application}


def send_application_confirmation(
    to_email: str,
    full_name: str,
    job_title: str,
    company: str,
) -> bool:
    """Send application confirmation email via Resend API."""
    import os, urllib.request, json as json_lib, logging
    log = logging.getLogger(__name__)

    resend_api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
    app_url = os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")

    if not resend_api_key:
        log.warning("RESEND_API_KEY not set — confirmation email not sent")
        return False

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f4f4f6;margin:0;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:40px;">
  <h1 style="font-size:20px;color:#1d1d1f;margin-bottom:4px;">&#9889; JobStream</h1>
  <hr style="border:none;border-top:1px solid #f0f0f0;margin:16px 0 24px;">
  <h2 style="font-size:22px;color:#1d1d1f;margin-bottom:8px;">Application received!</h2>
  <p style="color:#444;font-size:14px;line-height:1.7;">
    Hi {full_name},<br><br>
    Your application for <strong>{job_title}</strong> at <strong>{company}</strong>
    has been successfully submitted.<br><br>
    We will notify you if the employer responds. In the meantime,
    you can track your applications on JobStream.
  </p>
  <div style="text-align:center;margin:28px 0;">
    <a href="{app_url}"
       style="display:inline-block;padding:12px 28px;background:#0071E3;color:#fff;
              border-radius:10px;text-decoration:none;font-weight:600;font-size:14px;">
      View my applications
    </a>
  </div>
  <p style="color:#bbb;font-size:11px;text-align:center;margin-top:24px;">
    JobStream &middot; Nigeria's Job Platform
  </p>
</div>
</body>
</html>"""

    payload = json_lib.dumps({
        "from": f"JobStream <{from_email}>",
        "to": [to_email],
        "subject": f"Application submitted — {job_title} at {company}",
        "html": html,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {resend_api_key}",
                "Content-Type": "application/json",
                "User-Agent": "jobstream/1.0.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json_lib.loads(resp.read())
            log.info(f"Confirmation email sent: id={result.get('id')}")
            return True
    except Exception as e:
        log.error(f"Confirmation email error: {e}")
        return False


@router.get("/applications")
def list_applications(job_id: Optional[int] = Query(None)):
    return get_applications(job_id)


@router.get("/applications/mine")
async def get_my_applications(current_user: dict = Depends(get_current_user)):
    """Get all applications submitted by the current user."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT a.*, j.title as job_title, j.company, j.location, j.source_url
                FROM applications a
                LEFT JOIN jobs j ON a.job_id = j.id
                WHERE a.email = %s
                ORDER BY a.submitted_at DESC
            """, (current_user["email"],))
        else:
            cur.execute("""
                SELECT a.*, j.title as job_title, j.company, j.location, j.source_url
                FROM applications a
                LEFT JOIN jobs j ON a.job_id = j.id
                WHERE a.email = ?
                ORDER BY a.submitted_at DESC
            """, (current_user["email"],))
        return [dict(r) for r in cur.fetchall()]


@router.patch("/applications/{app_id}/status")
def set_application_status(app_id: int, body: StatusUpdate):
    try:
        update_application_status(app_id, body.status)
        log_application(
            AuditAction.APPLICATION_STATUS_CHANGED,
            user_id=str(current_user["id"]) if hasattr(current_user, "__getitem__") else "system",
            app_id=app_id,
            job_title="",
            new_status=body.status,
        )
        return {"message": "Status updated"}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Scraper ───────────────────────────────────────────────────────────────────

@router.post("/scrape", status_code=202)
async def trigger_scrape(background_tasks: BackgroundTasks):
    from services.recruitment.tasks import run_scrape_task
    background_tasks.add_task(run_scrape_task)
    return {"message": "Scrape started for all companies"}



@router.post("/scrape/backfill-descriptions", status_code=202)
async def backfill_descriptions(background_tasks: BackgroundTasks):
    from services.recruitment.tasks import run_backfill
    background_tasks.add_task(run_backfill)
    return {"message": "Backfill started"}


@router.post("/scrape/{company_id}/force", status_code=202)
async def force_rescrape(company_id: int, background_tasks: BackgroundTasks):
    from services.recruitment.tasks import run_force_rescrape
    companies = get_companies(active_only=True)
    company = next((c for c in companies if c["id"] == company_id), None)
    if not company:
        raise HTTPException(404, "Company not found")
    background_tasks.add_task(run_force_rescrape, company)
    return {"message": f"Force rescrape started for {company['name']}"}


@router.post("/scrape/{company_id}", status_code=202)
async def trigger_single_scrape(company_id: int, background_tasks: BackgroundTasks):
    from services.recruitment.tasks import run_single_company_task
    companies = get_companies(active_only=True)
    company = next((c for c in companies if c["id"] == company_id), None)
    if not company:
        raise HTTPException(404, "Company not found")
    background_tasks.add_task(run_single_company_task, company)
    return {"message": f"Scrape started for {company['name']}"}


@router.get("/scrape/history")
def scrape_history():
    return get_scrape_history()


@router.get("/scrape/status")
def scrape_status(scheduler=None):
    history = get_scrape_history(limit=1)
    last = history[0] if history else None
    return {"last_run": last, "next_run": None}


# ── Saved / Bookmarked Jobs ───────────────────────────────────────────────────

@router.post("/jobs", status_code=201)
async def create_manual_job(
    body: ManualJobIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Post a manual job. Strict ownership checks:
    - User must have a tenant (workspace)
    - organization_id must belong to the user's tenant
    - Prevents posting jobs under companies the user doesn't own
    """
    """Post a job manually — tied to a company profile."""
    import hashlib, datetime as dt

    # Check plan limits before posting
    tenant_id = current_user.get("tenant_id")
    if tenant_id:
        try:
            from core.tenant import get_tenant_by_id, TenantContext, check_plan_limit
            t = get_tenant_by_id(tenant_id)
            if t:
                ctx = TenantContext(tenant_id=tenant_id, plan=t.get("plan", "free"))
                with get_conn() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT COUNT(*) FROM jobs WHERE tenant_id = %s AND is_active = 1 AND source = 'manual'" if USE_POSTGRES
                        else "SELECT COUNT(*) FROM jobs WHERE tenant_id = ? AND is_active = 1 AND source = 'manual'",
                        (tenant_id,)
                    )
                    row = cur.fetchone()
                    count = list(dict(row).values())[0] if USE_POSTGRES else row[0]
                check_plan_limit(ctx, "max_jobs", int(count))
        except HTTPException:
            raise
        except Exception:
            pass

    # ── Anti-impersonation: verify org ownership ────────────────────────────
    _role = current_user.get("role", "")
    _is_admin = _role in ("super_admin", "platform_admin")

    if not _is_admin:
        if not tenant_id:
            raise HTTPException(403, "You must create a workspace before posting jobs.")

        # ── Quota enforcement ─────────────────────────────────────────────
        try:
            from services.identity.quota_router import check_job_quota, check_feature
            quota_status = check_job_quota(str(tenant_id))
            if not quota_status["can_post"]:
                credits = quota_status.get("credits")
                limit = quota_status.get("limit")
                if credits is not None:
                    raise HTTPException(403,
                        f"You have used all {credits} job credits on your plan. "
                        f"Please purchase more credits to continue posting jobs."
                    )
                else:
                    raise HTTPException(403,
                        f"You have reached your plan limit of {limit} active jobs. "
                        f"Upgrade your plan or unpublish existing jobs to post new ones."
                    )
            if not check_feature(str(tenant_id), "post_jobs"):
                raise HTTPException(403, "Your plan does not include job posting. Please upgrade.")
        except HTTPException:
            raise
        except Exception as qe:
            import logging as _log
            _log.getLogger(__name__).warning(f"Quota check failed (non-blocking): {qe}")
        if body.organization_id:
            with get_conn() as _c:
                _cur = _c.cursor()
                _ph = "%s" if USE_POSTGRES else "?"
                _cur.execute(
                    f"SELECT tenant_id FROM organizations WHERE id = {_ph}",
                    (body.organization_id,)
                )
                _org = _cur.fetchone()
                if not _org:
                    raise HTTPException(404, "Organization not found.")
                _org_tenant = str(dict(_org).get("tenant_id") or "")
                if _org_tenant != str(tenant_id):
                    raise HTTPException(403,
                        "You cannot post jobs under a company you do not own. "
                        "Create your own workspace to post jobs."
                    )

    # Build apply_url from email if not provided
    apply_url = body.apply_url
    if not apply_url and body.apply_email:
        apply_url = f"mailto:{body.apply_email}"

    fingerprint = hashlib.md5(
        f"{body.title}|{body.company}|manual".lower().encode()
    ).hexdigest()

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO jobs
                    (title, company, location, job_type, department,
                     description, salary, apply_url, source_url,
                     source, is_active, fingerprint, organization_id,
                     tenant_id, apply_mode, deadline, scraped_at, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'manual',%s,%s,%s,%s,%s,%s,NOW(),NOW())
                RETURNING id
            """, (
                body.title, body.company, body.location, body.job_type,
                body.department, body.description, body.salary,
                apply_url, apply_url, 0 if body.is_draft else 1, fingerprint,
                body.organization_id, current_user.get("tenant_id"),
                body.apply_mode, body.deadline or None
            ))
            job_id = cur.fetchone()["id"]
        else:
            cur.execute("""
                INSERT INTO jobs
                    (title, company, location, job_type, department,
                     description, salary, apply_url, source_url,
                     source, is_active, fingerprint, organization_id,
                     tenant_id, apply_mode, deadline, scraped_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,'manual',?,?,?,?,?,?,datetime('now'),datetime('now'))
            """, (
                body.title, body.company, body.location, body.job_type,
                body.department, body.description, body.salary,
                apply_url, apply_url, 0 if body.is_draft else 1, fingerprint,
                body.organization_id, current_user.get("tenant_id"),
                body.apply_mode, body.deadline or None
            ))
            job_id = cur.lastrowid

    log_job(AuditAction.JOB_CREATED, str(current_user["id"]), job_id, body.title)
    return {"message": "Job posted successfully", "id": job_id}


@router.patch("/jobs/{job_id}")
async def update_job(
    job_id: int,
    body: ManualJobIn,
    current_user: dict = Depends(get_current_user),
):
    """Update a manually posted job."""
    apply_url = body.apply_url
    if not apply_url and body.apply_email:
        apply_url = f"mailto:{body.apply_email}"

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                UPDATE jobs SET
                    title=%s, company=%s, location=%s, job_type=%s,
                    department=%s, description=%s, salary=%s,
                    apply_url=%s, organization_id=%s
                WHERE id=%s AND source='manual'
            """, (
                body.title, body.company, body.location, body.job_type,
                body.department, body.description, body.salary,
                apply_url, body.organization_id, job_id
            ))
        else:
            cur.execute("""
                UPDATE jobs SET
                    title=?, company=?, location=?, job_type=?,
                    department=?, description=?, salary=?,
                    apply_url=?, organization_id=?
                WHERE id=? AND source='manual'
            """, (
                body.title, body.company, body.location, body.job_type,
                body.department, body.description, body.salary,
                apply_url, body.organization_id, job_id
            ))
    return {"message": "Job updated"}


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Soft delete a job (set inactive)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE jobs SET is_active = 0 WHERE id = %s" if USE_POSTGRES
            else "UPDATE jobs SET is_active = 0 WHERE id = ?",
            (job_id,)
        )
    log_job(AuditAction.JOB_DELETED, str(current_user["id"]), job_id, f"job:{job_id}")


# ── Admin Job Management ──────────────────────────────────────────────────────

class AdminJobUpdateIn(BaseModel):
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    department: Optional[str] = None
    industry: Optional[str] = None
    salary: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[int] = None


@router.patch("/admin/jobs/{job_id}")
async def admin_update_job(
    job_id: int,
    body: AdminJobUpdateIn,
    current_user: dict = Depends(get_current_user),
):
    """Admin: edit any job field regardless of source."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    ALLOWED_JOB_FIELDS = {
        "title", "company", "location", "job_type", "department",
        "industry", "salary", "description",
    }
    updates = {k: v for k, v in body.dict().items()
               if v is not None and k in ALLOWED_JOB_FIELDS}
    if not updates:
        raise HTTPException(400, "No fields provided")

    ph = "%s" if USE_POSTGRES else "?"
    set_clauses = [f"{k} = {ph}" for k in updates]
    params = list(updates.values()) + [job_id]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE jobs SET {', '.join(set_clauses)} WHERE id = {ph}",
            params
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Job not found")

    log_job(AuditAction.JOB_UPDATED, str(current_user["id"]), job_id, f"admin_edit:{list(updates.keys())}")
    return {"message": "Job updated", "updated": list(updates.keys())}


@router.patch("/jobs/{job_id}/feature")
async def toggle_feature_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Toggle featured status on a manually posted job."""
    if current_user.get("role") not in ("org_owner", "hr_admin", "super_admin", "platform_admin"):
        raise HTTPException(403, "Not allowed")
    with get_conn() as conn:
        cur = conn.cursor()
        # Get current featured status
        cur.execute(
            "SELECT is_featured FROM jobs WHERE id = %s" if USE_POSTGRES
            else "SELECT is_featured FROM jobs WHERE id = ?",
            (job_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        current = dict(row).get("is_featured") or False
        new_val = not current
        cur.execute(
            "UPDATE jobs SET is_featured = %s WHERE id = %s" if USE_POSTGRES
            else "UPDATE jobs SET is_featured = ? WHERE id = ?",
            (new_val, job_id)
        )
    return {"is_featured": new_val}


@router.post("/admin/jobs/{job_id}/publish")
async def admin_publish_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Admin: publish (make active) a job."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE jobs SET is_active = 1 WHERE id = {ph}", (job_id,))
    return {"message": "Job published"}


@router.post("/admin/jobs/{job_id}/unpublish")
async def admin_unpublish_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Admin: unpublish (hide) a job without deleting it."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"UPDATE jobs SET is_active = 0 WHERE id = {ph}", (job_id,))
    return {"message": "Job unpublished"}


@router.delete("/admin/jobs/{job_id}/hard")
async def admin_hard_delete_job(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Admin: permanently delete a job and its applications."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM applications WHERE job_id = {ph}", (job_id,))
        cur.execute(f"DELETE FROM jobs WHERE id = {ph}", (job_id,))
    log_job(AuditAction.JOB_DELETED, str(current_user["id"]), job_id, "hard_delete")
    return {"message": "Job permanently deleted"}


@router.get("/admin/jobs")
async def admin_list_jobs(
    search: str = Query(""),
    job_type: str = Query(""),
    department: str = Query(""),
    industry: str = Query(""),
    is_active: str = Query(""),  # "0", "1", or "" for all
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(get_current_user),
):
    """Admin: list all jobs including inactive ones."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    conditions = []
    params = []
    ph = "%s" if USE_POSTGRES else "?"

    if search:
        like = f"%{search}%"
        if USE_POSTGRES:
            conditions.append("(title ILIKE %s OR company ILIKE %s)")
        else:
            conditions.append("(title LIKE ? OR company LIKE ?)")
        params += [like, like]
    if job_type:
        conditions.append(f"job_type = {ph}")
        params.append(job_type)
    if department:
        conditions.append(f"department = {ph}")
        params.append(department)
    if industry:
        if USE_POSTGRES:
            conditions.append("industry ILIKE %s")
        else:
            conditions.append("industry LIKE ?")
        params.append(f"%{industry}%")
    if is_active in ("0", "1"):
        conditions.append(f"is_active = {ph}")
        params.append(int(is_active))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM jobs {where}", params)
        row = cur.fetchone()
        total = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

        cur.execute(
            f"SELECT id, title, company, location, job_type, department, industry, "
            f"is_active, source, created_at, description FROM jobs {where} "
            f"ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
            params + [limit, offset]
        )
        jobs = [dict(r) for r in cur.fetchall()]

    return {"total": total, "jobs": jobs, "limit": limit, "offset": offset}


# ── Employer Dashboard — Applications per job ─────────────────────────────────

@router.get("/jobs/{job_id}/applications")
async def get_job_applications(
    job_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get all applications for a specific job — for employer dashboard."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT * FROM applications
                WHERE job_id = %s
                ORDER BY submitted_at DESC
            """, (job_id,))
        else:
            cur.execute("""
                SELECT * FROM applications
                WHERE job_id = ?
                ORDER BY submitted_at DESC
            """, (job_id,))
        return [dict(r) for r in cur.fetchall()]


@router.patch("/applications/{app_id}/status")
async def update_app_status(
    app_id: int,
    body: StatusUpdate,
):
    """Update application status — new, reviewing, shortlisted, rejected, hired."""
    valid = {"new", "reviewing", "shortlisted", "interview", "offer", "hired", "rejected", "withdrawn"}
    if body.status not in valid:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(valid)}")
    try:
        update_application_status(app_id, body.status)
        log_application(
            AuditAction.APPLICATION_STATUS_CHANGED,
            user_id=str(current_user["id"]) if hasattr(current_user, "__getitem__") else "system",
            app_id=app_id,
            job_title="",
            new_status=body.status,
        )
        return {"message": "Status updated"}
    except ValueError as e:
        raise HTTPException(400, str(e))
