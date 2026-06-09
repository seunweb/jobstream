"""
Recruitment Service Router
Handles jobs, applications, scraping, interviews, offers.
Preserves all existing endpoints exactly — zero breaking changes.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks, Depends
from pydantic import BaseModel

from core.database import (
    get_conn, USE_POSTGRES,
    get_companies, add_company, delete_company,
    get_jobs, get_job, upsert_jobs, mark_jobs_inactive,
    create_application, get_applications, update_application_status,
    start_scrape_run, finish_scrape_run, get_scrape_history,
)
from services.identity.dependencies import get_current_user

router = APIRouter(tags=["recruitment"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CompanyIn(BaseModel):
    name: str
    url: str


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
        return add_company(body.name, body.url)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.delete("/companies/{company_id}", status_code=204)
def remove_company(company_id: int):
    delete_company(company_id)


# ── Jobs ──────────────────────────────────────────────────────────────────────

@router.get("/jobs")
def list_jobs(
    search: str = Query(""),
    job_type: str = Query(""),
    department: str = Query(""),
    company: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    jobs, total = get_jobs(search, job_type, department, company, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "jobs": jobs}


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
    return {"message": "Application submitted", "application": create_application(job_id, data)}


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
