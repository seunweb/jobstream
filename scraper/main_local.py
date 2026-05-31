"""
JobStream API - Local Development Mode
Runs the full API without Playwright/scraping.
Scraping is handled by Railway in production.
Run: uvicorn main_local:app --reload --port 8000
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import (
    USE_POSTGRES, get_conn,
    init_db, get_companies, add_company, delete_company,
    get_jobs, get_job, upsert_jobs, mark_jobs_inactive,
    create_application, get_applications, update_application_status,
    start_scrape_run, finish_scrape_run, get_scrape_history,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("DB_PATH", "./jobstream.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    try:
        init_db()
        logger.info("Database initialised (local mode)")
    except Exception as e:
        logger.error(f"Database init failed: {e}")
        raise
    yield


app = FastAPI(
    title="JobStream API (Local)",
    description="Local dev mode — scraping disabled, all other features work",
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
    return {"status": "ok", "mode": "local", "time": datetime.utcnow().isoformat()}


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
# Routes — Scraper (stubs — scraping runs on Railway only)
# ---------------------------------------------------------------------------

@app.post("/scrape", status_code=202)
def trigger_scrape():
    return {"message": "Scraping is handled by Railway in production. Run the full main.py there."}


@app.post("/scrape/backfill-descriptions", status_code=202)
def backfill():
    return {"message": "Backfill runs on Railway only."}


@app.post("/scrape/{company_id}/force", status_code=202)
def force_rescrape(company_id: int):
    return {"message": "Force rescrape runs on Railway only."}


@app.post("/scrape/{company_id}", status_code=202)
def trigger_single_scrape(company_id: int):
    return {"message": "Scraping runs on Railway only."}


@app.get("/scrape/history")
def scrape_history():
    return get_scrape_history()


@app.get("/scrape/status")
def scrape_status():
    history = get_scrape_history(limit=1)
    return {"last_run": history[0] if history else None, "next_run": None, "mode": "local"}
