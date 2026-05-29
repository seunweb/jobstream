"""
JobStream API
FastAPI server exposing job board data + triggering scrapes.
Run: uvicorn main:app --reload
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    init_db, get_companies, add_company, delete_company,
    get_jobs, get_job, upsert_jobs, mark_jobs_inactive,
    create_application, get_applications, update_application_status,
    start_scrape_run, finish_scrape_run, get_scrape_history,
)
from scraper import scrape_all, scrape_company

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Database initialised")
    scheduler.add_job(run_scheduled_scrape, "interval", hours=2, id="auto_scrape")
    scheduler.start()
    logger.info("Scheduler started (scraping every 2 hours)")
    yield
    scheduler.shutdown()


app = FastAPI(
    title="JobStream API",
    description="Automated job board scraper & applications API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Scrape helpers
# ---------------------------------------------------------------------------

async def run_scrape_task():
    """Scrape all active companies."""
    companies = get_companies(active_only=True)
    if not companies:
        logger.info("No active companies to scrape")
        return
    await _do_scrape(companies)


async def run_single_company_task(company: dict):
    """Scrape a single company."""
    await _do_scrape([company])


async def _do_scrape(companies: list[dict]):
    run_id = start_scrape_run()
    total_found = total_new = 0
    error_msg = ""
    try:
        scraped_jobs = await scrape_all(companies)
        by_url: dict[str, list] = {}
        for j in scraped_jobs:
            by_url.setdefault(j.source_url, []).append(j)
        for url, jobs in by_url.items():
            found, new = upsert_jobs(jobs)
            total_found += found
            total_new += new
            mark_jobs_inactive(url, [j.fingerprint for j in jobs])
        logger.info(f"Scrape complete: {total_found} found, {total_new} new")
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Scrape failed: {e}")
    finally:
        finish_scrape_run(run_id, total_found, total_new, error_msg)


async def run_scheduled_scrape():
    logger.info("Running scheduled scrape…")
    await run_scrape_task()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Routes — Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


# ---------------------------------------------------------------------------
# Routes — Companies
# ---------------------------------------------------------------------------

@app.get("/companies")
def list_companies():
    return get_companies()


@app.post("/companies", status_code=201)
def create_company(body: CompanyIn):
    try:
        return add_company(body.name, body.url)
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/companies/{company_id}", status_code=204)
def remove_company(company_id: int):
    delete_company(company_id)


# ---------------------------------------------------------------------------
# Routes — Jobs
# ---------------------------------------------------------------------------

@app.get("/jobs")
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


@app.get("/jobs/{job_id}")
def get_single_job(job_id: int):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ---------------------------------------------------------------------------
# Routes — Applications
# ---------------------------------------------------------------------------

@app.post("/jobs/{job_id}/apply", status_code=201)
def apply_for_job(job_id: int, body: ApplicationIn):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"message": "Application submitted", "application": create_application(job_id, body.dict())}


@app.get("/applications")
def list_applications(job_id: Optional[int] = Query(None)):
    return get_applications(job_id)


@app.patch("/applications/{app_id}/status")
def set_application_status(app_id: int, body: StatusUpdate):
    try:
        update_application_status(app_id, body.status)
        return {"message": "Status updated"}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Routes — Scraper
# ---------------------------------------------------------------------------

@app.post("/scrape", status_code=202)
async def trigger_scrape(background_tasks: BackgroundTasks):
    """Scrape all active companies."""
    background_tasks.add_task(run_scrape_task)
    return {"message": "Scrape started for all companies"}


@app.post("/scrape/{company_id}", status_code=202)
async def trigger_single_scrape(company_id: int, background_tasks: BackgroundTasks):
    """Scrape a single company by ID."""
    companies = get_companies(active_only=True)
    company = next((c for c in companies if c["id"] == company_id), None)
    if not company:
        raise HTTPException(404, "Company not found")
    background_tasks.add_task(run_single_company_task, company)
    return {"message": f"Scrape started for {company['name']}"}


@app.get("/scrape/history")
def scrape_history():
    return get_scrape_history()


@app.get("/scrape/status")
def scrape_status():
    history = get_scrape_history(limit=1)
    last = history[0] if history else None
    next_run = None
    job = scheduler.get_job("auto_scrape")
    if job and job.next_run_time:
        next_run = job.next_run_time.isoformat()
    return {"last_run": last, "next_run": next_run}
