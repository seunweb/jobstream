"""
JobStream API - corrected alternative entry point.

Run locally:
    uvicorn main_corrected:app --reload --port 8000

This file intentionally does not replace main.py.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Environment variables must be loaded before importing database/auth modules,
# because those modules read configuration during import.
load_dotenv(Path(__file__).with_name(".env"))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from auth.dependencies import get_current_user, require_role
from auth.models import ADD_AUTH_TABLES, ADD_AUTH_TABLES_SQLITE
from auth.router import router as auth_router
from database import (
    USE_POSTGRES,
    add_company,
    create_application,
    delete_company,
    finish_scrape_run,
    get_applications,
    get_companies,
    get_conn,
    get_job,
    get_jobs,
    get_scrape_history,
    init_db,
    start_scrape_run,
    update_application_status,
    upsert_jobs,
)
from scraper import fetch_job_description, scrape_company

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ADMIN_ROLES = ("admin", "recruiter")
scheduler = AsyncIOScheduler()
scrape_lock = asyncio.Lock()


def _cors_origins() -> list[str]:
    configured = os.environ.get("CORS_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:3000", "http://localhost:5173"]


def _mark_company_jobs_inactive(source_url: str, fingerprints: list[str]) -> None:
    """Mark missing jobs inactive, including when a successful scrape returns none."""
    with get_conn() as conn:
        cur = conn.cursor()
        if not fingerprints:
            placeholder = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"UPDATE jobs SET is_active = 0 WHERE source_url = {placeholder}",
                (source_url,),
            )
        elif USE_POSTGRES:
            cur.execute(
                "UPDATE jobs SET is_active = 0 "
                "WHERE source_url = %s AND NOT (fingerprint = ANY(%s))",
                (source_url, fingerprints),
            )
        else:
            placeholders = ",".join("?" for _ in fingerprints)
            cur.execute(
                f"UPDATE jobs SET is_active = 0 "
                f"WHERE source_url = ? AND fingerprint NOT IN ({placeholders})",
                [source_url, *fingerprints],
            )


def _refresh_jobs(scraped_jobs: list) -> tuple[int, int]:
    """Refresh all scraped fields while preserving job IDs and applications."""
    _, new_count = upsert_jobs(scraped_jobs)
    with get_conn() as conn:
        cur = conn.cursor()
        for job in scraped_jobs:
            if USE_POSTGRES:
                cur.execute(
                    """
                    UPDATE jobs
                    SET title = %s, company = %s, source_url = %s, location = %s,
                        job_type = %s, department = %s, salary = %s,
                        description = %s, apply_url = %s, is_active = 1,
                        scraped_at = %s
                    WHERE fingerprint = %s
                    """,
                    (
                        job.title, job.company, job.source_url, job.location,
                        job.job_type, job.department, job.salary, job.description,
                        job.apply_url, job.scraped_at.isoformat(), job.fingerprint,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE jobs
                    SET title = ?, company = ?, source_url = ?, location = ?,
                        job_type = ?, department = ?, salary = ?,
                        description = ?, apply_url = ?, is_active = 1,
                        scraped_at = ?
                    WHERE fingerprint = ?
                    """,
                    (
                        job.title, job.company, job.source_url, job.location,
                        job.job_type, job.department, job.salary, job.description,
                        job.apply_url, job.scraped_at.isoformat(), job.fingerprint,
                    ),
                )
    return len(scraped_jobs), new_count


async def _do_scrape(companies: list[dict], refresh_existing: bool = False) -> None:
    if scrape_lock.locked():
        logger.info("Waiting for the active scrape operation to finish")

    async with scrape_lock:
        run_id = start_scrape_run()
        total_found = total_new = 0
        errors: list[str] = []

        try:
            for company in companies:
                try:
                    jobs = await scrape_company(company["url"], company["name"])
                    found, new = (
                        _refresh_jobs(jobs) if refresh_existing else upsert_jobs(jobs)
                    )
                    _mark_company_jobs_inactive(
                        company["url"], [job.fingerprint for job in jobs]
                    )
                    total_found += found
                    total_new += new
                except Exception as exc:
                    message = f"{company['name']}: {exc}"
                    errors.append(message)
                    logger.exception("Scrape failed for %s", company["name"])

            logger.info("Scrape complete: %s found, %s new", total_found, total_new)
        finally:
            finish_scrape_run(
                run_id,
                total_found,
                total_new,
                "; ".join(errors),
            )


async def run_scrape_task() -> None:
    companies = get_companies(active_only=True)
    if companies:
        await _do_scrape(companies)
    else:
        logger.info("No active companies to scrape")


async def run_single_company_task(company: dict) -> None:
    await _do_scrape([company])


async def run_force_rescrape(company: dict) -> None:
    # Refresh records in place so applications keep valid job references.
    await _do_scrape([company], refresh_existing=True)


async def run_scheduled_scrape() -> None:
    logger.info("Running scheduled scrape")
    await run_scrape_task()


async def run_backfill() -> None:
    """Fetch missing descriptions while sharing the scrape-operation lock."""
    from playwright.async_api import async_playwright

    async with scrape_lock:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, title, apply_url FROM jobs "
                "WHERE (description IS NULL OR description = '') "
                "AND apply_url != '' ORDER BY id"
            )
            jobs = [dict(row) for row in cur.fetchall()]

        logger.info("Backfill: %s jobs need descriptions", len(jobs))
        if not jobs:
            return

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                page = await context.new_page()
                for index, job in enumerate(jobs, start=1):
                    logger.info("Backfill [%s/%s]: %s", index, len(jobs), job["title"])
                    try:
                        description = await fetch_job_description(page, job["apply_url"])
                        if description:
                            with get_conn() as conn:
                                cur = conn.cursor()
                                placeholder = "%s" if USE_POSTGRES else "?"
                                cur.execute(
                                    f"UPDATE jobs SET description = {placeholder} "
                                    f"WHERE id = {placeholder}",
                                    (description, job["id"]),
                                )
                    except Exception:
                        logger.exception("Backfill failed for job ID %s", job["id"])
                    await asyncio.sleep(1)
            finally:
                await browser.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "./jobstream.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    init_db()
    schema = ADD_AUTH_TABLES if USE_POSTGRES else ADD_AUTH_TABLES_SQLITE
    with get_conn() as conn:
        cur = conn.cursor()
        for statement in schema.strip().split(";"):
            if statement.strip():
                cur.execute(statement.strip())

    # Run the scheduler in only one explicitly selected process when using
    # multiple web workers.
    scheduler_enabled = os.environ.get("ENABLE_SCHEDULER", "true").lower() == "true"
    if scheduler_enabled:
        scheduler.add_job(
            run_scheduled_scrape,
            "interval",
            hours=2,
            id="auto_scrape",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        logger.info("Scheduler started")

    yield

    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="JobStream API", version="0.3.0-corrected", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth_router)


class CompanyIn(BaseModel):
    name: str
    url: str


class ApplicationIn(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: str = ""
    resume_url: str = ""
    cover_note: str = ""


class StatusUpdate(BaseModel):
    status: str


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/companies")
def list_companies():
    return get_companies()


@app.post("/companies", status_code=201)
def create_company(body: CompanyIn, _user: dict = Depends(require_role(*ADMIN_ROLES))):
    try:
        return add_company(body.name, body.url)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/companies/{company_id}", status_code=204)
def remove_company(
    company_id: int,
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    delete_company(company_id)
    return Response(status_code=204)


@app.get("/jobs")
def list_jobs(
    search: str = Query(""),
    job_type: str = Query(""),
    department: str = Query(""),
    company: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    jobs, total = get_jobs(search, job_type, department, company, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "jobs": jobs}


@app.get("/jobs/{job_id}")
def get_single_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.post("/jobs/{job_id}/apply", status_code=201)
async def apply_for_job(
    job_id: int,
    body: ApplicationIn,
    current_user: dict = Depends(get_current_user),
):
    if not get_job(job_id):
        raise HTTPException(404, "Job not found")

    data = body.model_dump()
    data["name"] = data.get("name") or current_user.get("full_name") or ""
    data["email"] = data.get("email") or current_user.get("email") or ""
    if not data["name"] or not data["email"]:
        raise HTTPException(400, "Application name and email are required")

    return {
        "message": "Application submitted",
        "application": create_application(job_id, data),
    }


@app.get("/applications")
def list_applications(
    job_id: Optional[int] = Query(None),
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    return get_applications(job_id)


@app.patch("/applications/{app_id}/status")
def set_application_status(
    app_id: int,
    body: StatusUpdate,
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    try:
        update_application_status(app_id, body.status)
        return {"message": "Status updated"}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _active_company(company_id: int) -> dict:
    company = next(
        (item for item in get_companies(active_only=True) if item["id"] == company_id),
        None,
    )
    if not company:
        raise HTTPException(404, "Company not found")
    return company


@app.post("/scrape", status_code=202)
async def trigger_scrape(
    background_tasks: BackgroundTasks,
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    background_tasks.add_task(run_scrape_task)
    return {"message": "Scrape queued for all companies"}


@app.post("/scrape/backfill-descriptions", status_code=202)
async def backfill_descriptions(
    background_tasks: BackgroundTasks,
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    background_tasks.add_task(run_backfill)
    return {"message": "Backfill queued"}


@app.post("/scrape/{company_id}/force", status_code=202)
async def force_rescrape(
    company_id: int,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    company = _active_company(company_id)
    background_tasks.add_task(run_force_rescrape, company)
    return {"message": f"Safe refresh queued for {company['name']}"}


@app.post("/scrape/{company_id}", status_code=202)
async def trigger_single_scrape(
    company_id: int,
    background_tasks: BackgroundTasks,
    _user: dict = Depends(require_role(*ADMIN_ROLES)),
):
    company = _active_company(company_id)
    background_tasks.add_task(run_single_company_task, company)
    return {"message": f"Scrape queued for {company['name']}"}


@app.get("/scrape/history")
def scrape_history(_user: dict = Depends(require_role(*ADMIN_ROLES))):
    return get_scrape_history()


@app.get("/scrape/status")
def scrape_status(_user: dict = Depends(require_role(*ADMIN_ROLES))):
    history = get_scrape_history(limit=1)
    job = scheduler.get_job("auto_scrape") if scheduler.running else None
    next_run = job.next_run_time.isoformat() if job and job.next_run_time else None
    return {
        "last_run": history[0] if history else None,
        "next_run": next_run,
        "scrape_in_progress": scrape_lock.locked(),
    }
