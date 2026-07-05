"""
SEO & Growth Service Router
Phase 9 — Search engine optimisation, job alerts, sitemap, job expiry.
"""

import re
import json
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response, Depends, Request
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(tags=["seo"])


# ── Slug helpers ──────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    """Convert text to URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def make_job_slug(title: str, company: str, job_id: int) -> str:
    """Create a unique job slug: software-engineer-mtn-123."""
    return f"{slugify(title)}-{slugify(company)}-{job_id}"


def make_org_slug(name: str) -> str:
    """Create company slug: mtn-nigeria."""
    return slugify(name)


# ── Job by slug ───────────────────────────────────────────────────────────────

@router.get("/jobs/by-slug/{slug}")
def get_job_by_slug(slug: str):
    """
    Get job by SEO slug.
    Slug format: {title}-{company}-{id}
    Tries multiple extraction strategies to handle both UUID and integer IDs.
    """
    with get_conn() as conn:
        cur = conn.cursor()

        # Strategy 1: extract UUID from end of slug (PostgreSQL)
        uuid_match = re.search(
            r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
            slug, re.IGNORECASE
        )
        # PostgreSQL uses boolean TRUE, SQLite uses integer 1
        active_check = "is_active = TRUE" if USE_POSTGRES else "is_active = 1"

        if uuid_match:
            job_id = uuid_match.group(1)
            cur.execute(
                f"SELECT * FROM jobs WHERE id = {'%s' if USE_POSTGRES else '?'} AND {active_check}",
                (job_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        # Strategy 2: extract numeric ID from end of slug
        int_match = re.search(r"-(\d+)$", slug)
        if int_match:
            job_id = int(int_match.group(1))
            cur.execute(
                f"SELECT * FROM jobs WHERE id = {'%s' if USE_POSTGRES else '?'} AND {active_check}",
                (job_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)
            # Also try without is_active filter (job might be unpublished)
            cur.execute(
                f"SELECT * FROM jobs WHERE id = {'%s' if USE_POSTGRES else '?'}",
                (job_id,)
            )
            row = cur.fetchone()
            if row:
                return dict(row)

        # Strategy 3: fuzzy title match
        parts = slug.rsplit("-", 1)
        if len(parts) == 2:
            title_part = parts[0].replace("-", " ")
            if USE_POSTGRES:
                cur.execute(
                    f"SELECT * FROM jobs WHERE {active_check} "
                    "AND title ILIKE %s ORDER BY created_at DESC LIMIT 1",
                    (f"%{title_part}%",)
                )
            else:
                cur.execute(
                    f"SELECT * FROM jobs WHERE {active_check} "
                    "AND title LIKE ? ORDER BY created_at DESC LIMIT 1",
                    (f"%{title_part}%",)
                )
            row = cur.fetchone()
            if row:
                return dict(row)

        raise HTTPException(404, f"Job not found for slug: {slug}")


@router.get("/organizations/by-slug/{slug}")
def get_org_by_slug(slug: str):
    """Get organization by SEO slug."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM organizations WHERE slug = %s AND is_active = TRUE" if USE_POSTGRES
            else "SELECT * FROM organizations WHERE slug = ? AND is_active = 1",
            (slug,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Company not found")
        org = dict(row)

        # Get job count
        cur.execute(
            "SELECT COUNT(*) FROM jobs WHERE company ILIKE %s AND is_active = 1" if USE_POSTGRES
            else "SELECT COUNT(*) FROM jobs WHERE company LIKE ? AND is_active = 1",
            (f"%{org['name']}%",)
        )
        count_row = cur.fetchone()
        org["job_count"] = int(list(dict(count_row).values())[0]) if USE_POSTGRES else count_row[0]
        return org


# ── Sitemap ───────────────────────────────────────────────────────────────────

@router.get("/sitemap.xml", response_class=Response)
def generate_sitemap(
    app_url: str = Query(""),
):
    """
    Generate XML sitemap for all active jobs and company pages.
    Submit to Google Search Console for indexing.
    """
    import os
    base_url = os.environ.get("APP_URL", "https://jobstream.ng").rstrip("/")

    with get_conn() as conn:
        cur = conn.cursor()

        # Static pages
        static_pages = [
            {"url": base_url, "priority": "1.0", "freq": "daily"},
            {"url": f"{base_url}/companies", "priority": "0.8", "freq": "daily"},
        ]

        # Active jobs
        cur.execute(
            "SELECT id, title, company, created_at FROM jobs WHERE is_active = 1 ORDER BY created_at DESC LIMIT 5000"
        )
        jobs = [dict(r) for r in cur.fetchall()]

        # Active organizations
        cur.execute(
            "SELECT slug, name, updated_at FROM organizations WHERE is_active = 1 AND slug IS NOT NULL"
            if USE_POSTGRES else
            "SELECT slug, name, updated_at FROM organizations WHERE is_active = 1 AND slug IS NOT NULL"
        )
        orgs = [dict(r) for r in cur.fetchall()]

    # Build XML
    urls = []

    for page in static_pages:
        urls.append(f"""  <url>
    <loc>{page['url']}</loc>
    <changefreq>{page['freq']}</changefreq>
    <priority>{page['priority']}</priority>
  </url>""")

    for job in jobs:
        slug = make_job_slug(job["title"], job["company"], job["id"])
        lastmod = str(job.get("created_at", ""))[:10]
        urls.append(f"""  <url>
    <loc>{base_url}/jobs/{slug}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>""")

    for org in orgs:
        if org.get("slug"):
            urls.append(f"""  <url>
    <loc>{base_url}/companies/{org['slug']}</loc>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>""")

    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(urls)
        + "\n</urlset>"
    )

    return Response(
        content=sitemap,
        media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ── JSON-LD structured data ───────────────────────────────────────────────────

@router.get("/jobs/{job_id}/structured-data")
def get_job_structured_data(job_id: int):
    """
    Return JSON-LD structured data for a job.
    Include in <script type="application/ld+json"> on the job page.
    Google uses this for rich job search results.
    """
    import os
    base_url = os.environ.get("APP_URL", "https://jobstream.ng").rstrip("/")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM jobs WHERE id = %s" if USE_POSTGRES
            else "SELECT * FROM jobs WHERE id = ?",
            (job_id,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Job not found")
        job = dict(row)

    slug = make_job_slug(job["title"], job["company"], job["id"])
    job_url = f"{base_url}/jobs/{slug}"

    # Google's JobPosting schema
    structured_data = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": job["title"],
        "description": job.get("description", ""),
        "datePosted": str(job.get("created_at", ""))[:10],
        "hiringOrganization": {
            "@type": "Organization",
            "name": job["company"],
            "sameAs": job.get("source_url", ""),
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": job.get("location", "Nigeria"),
                "addressCountry": "NG",
            }
        },
        "employmentType": _map_employment_type(job.get("job_type", "")),
        "url": job_url,
        "identifier": {
            "@type": "PropertyValue",
            "name": "JobStream",
            "value": str(job["id"]),
        },
    }

    # Add salary if present
    if job.get("salary"):
        structured_data["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": "NGN",
            "value": {
                "@type": "QuantitativeValue",
                "value": job["salary"],
                "unitText": "MONTH",
            }
        }

    # Add expiry if we know it
    if job.get("expires_at"):
        structured_data["validThrough"] = str(job["expires_at"])[:10]

    return structured_data


def _map_employment_type(job_type: str) -> str:
    """Map job type to Google's schema.org employment type."""
    mapping = {
        "full-time": "FULL_TIME",
        "part-time": "PART_TIME",
        "contract":  "CONTRACTOR",
        "internship": "INTERN",
        "remote":    "FULL_TIME",
        "temporary": "TEMPORARY",
    }
    return mapping.get(job_type.lower(), "FULL_TIME")


# ── Job Alerts ────────────────────────────────────────────────────────────────

# Industries available for job alerts — used by frontend dropdown too
ALERT_INDUSTRIES = [
    "Telecommunications", "Banking & Finance", "Oil & Gas", "Information Technology",
    "Healthcare", "Education", "Manufacturing", "FMCG", "Retail & E-commerce",
    "Real Estate & Construction", "Logistics & Supply Chain", "Agriculture",
    "Media & Entertainment", "Hospitality & Tourism", "Government & NGO",
    "Legal", "Consulting", "Insurance", "Energy & Utilities", "Other",
]

# Valid send times (24h, Africa/Lagos)
ALERT_SEND_TIMES = ["06:00", "08:00", "12:00", "17:00", "20:00"]


class JobAlertIn(BaseModel):
    email: str
    keywords: str          # comma-separated job titles/skills: "software engineer, python"
    location: Optional[str] = ""    # optional — e.g. "Lagos, Nigeria" or "Remote"
    industry: Optional[str] = ""     # e.g. "Telecommunications"
    job_type: Optional[str] = ""
    frequency: Optional[str] = "daily"   # daily | weekly
    send_time: Optional[str] = "08:00"   # preferred delivery time
    timezone: Optional[str] = "Africa/Lagos"  # IANA timezone e.g. "Europe/London"
    captcha_answer: Optional[int] = None
    captcha_expected: Optional[int] = None


class JobAlertUpdateIn(BaseModel):
    keywords: Optional[str] = None
    location: Optional[str] = None
    industry: Optional[str] = None
    job_type: Optional[str] = None
    frequency: Optional[str] = None
    send_time: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None


def _get_optional_user(request):
    """Best-effort: return current user dict if a valid token is present, else None."""
    try:
        from services.identity.security import decode_token
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return None
        payload = decode_token(auth[7:])
        if not payload:
            return None
        from services.identity.router import get_user_by_id
        return get_user_by_id(payload["sub"])
    except Exception:
        return None


@router.get("/job-alerts/meta")
def job_alerts_meta():
    """Return industry list and send-time options for the alert form."""
    return {"industries": ALERT_INDUSTRIES, "send_times": ALERT_SEND_TIMES}


@router.post("/job-alerts", status_code=201)
async def create_job_alert(body: JobAlertIn, request: Request):
    """
    Subscribe to job alerts for matching keywords + location (+ optional industry).
    - Logged-in users: alert is linked to their account, manageable under My Alerts.
    - Guests: must answer the simple math captcha to prevent spam.
    """
    user = _get_optional_user(request)

    if not user:
        # Guest — require captcha
        if body.captcha_answer is None or body.captcha_expected is None:
            raise HTTPException(400, "Captcha required")
        if body.captcha_answer != body.captcha_expected:
            raise HTTPException(400, "Incorrect captcha answer. Please try again.")

    alert_id = str(uuid.uuid4())
    token = str(uuid.uuid4())
    user_id = str(user["id"]) if user else None
    email = (user["email"] if user else body.email).lower()

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO job_alerts
                    (id, user_id, email, keywords, location, industry, job_type,
                     frequency, send_time, timezone, unsubscribe_token, is_active, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,NOW())
                ON CONFLICT (email, keywords, location) DO UPDATE SET
                    is_active = TRUE, industry = EXCLUDED.industry,
                    job_type = EXCLUDED.job_type, frequency = EXCLUDED.frequency,
                    send_time = EXCLUDED.send_time, timezone = EXCLUDED.timezone,
                    user_id = EXCLUDED.user_id, updated_at = NOW()
            """, (alert_id, user_id, email, body.keywords, body.location,
                  body.industry, body.job_type, body.frequency, body.send_time,
                  getattr(body, "timezone", None) or "Africa/Lagos", token))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO job_alerts
                    (id, user_id, email, keywords, location, industry, job_type,
                     frequency, send_time, timezone, unsubscribe_token, is_active, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,1,datetime('now'))
            """, (alert_id, user_id, email, body.keywords, body.location,
                  body.industry, body.job_type, body.frequency, body.send_time,
                  getattr(body, "timezone", None) or "Africa/Lagos", token))

    log.info(f"Job alert created for {email}: {body.keywords} in {body.location}")
    return {
        "message": f"Job alert created. You will receive {body.frequency} emails ({body.send_time}) when new jobs match '{body.keywords}' in {body.location}.",
        "id": alert_id,
    }


@router.get("/job-alerts/my")
async def list_my_job_alerts(request: Request):
    """List job alerts belonging to the logged-in user."""
    user = _get_optional_user(request)
    if not user:
        raise HTTPException(401, "Sign in to view your alerts")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT id, keywords, location, industry, job_type, frequency,
                       send_time, is_active, created_at
                FROM job_alerts WHERE user_id = %s
                ORDER BY created_at DESC
            """, (str(user["id"]),))
        else:
            cur.execute("""
                SELECT id, keywords, location, industry, job_type, frequency,
                       send_time, is_active, created_at
                FROM job_alerts WHERE user_id = ?
                ORDER BY created_at DESC
            """, (str(user["id"]),))
        return [dict(r) for r in cur.fetchall()]


@router.patch("/job-alerts/{alert_id}")
async def update_job_alert(alert_id: str, body: JobAlertUpdateIn, request: Request):
    """Update one of the logged-in user's job alerts."""
    user = _get_optional_user(request)
    if not user:
        raise HTTPException(401, "Sign in to manage your alerts")

    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    set_clauses = []
    params = []
    ph = "%s" if USE_POSTGRES else "?"
    for k, v in updates.items():
        set_clauses.append(f"{k} = {ph}")
        params.append(v)
    params += [str(user["id"]), alert_id]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE job_alerts SET {', '.join(set_clauses)} "
            f"WHERE user_id = {ph} AND id = {ph}",
            params
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Alert not found")

    return {"message": "Alert updated"}


@router.delete("/job-alerts/mine/{alert_id}")
async def delete_my_job_alert(alert_id: str, request: Request):
    """Delete one of the logged-in user's job alerts."""
    user = _get_optional_user(request)
    if not user:
        raise HTTPException(401, "Sign in to manage your alerts")

    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"DELETE FROM job_alerts WHERE user_id = {ph} AND id = {ph}",
            (str(user["id"]), alert_id)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Alert not found")
    return {"message": "Alert deleted"}


@router.delete("/job-alerts/{token}")
async def unsubscribe_job_alert(token: str):
    """Unsubscribe from job alerts using token from email (guest flow)."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE job_alerts SET is_active = FALSE WHERE unsubscribe_token = %s" if USE_POSTGRES
            else "UPDATE job_alerts SET is_active = 0 WHERE unsubscribe_token = ?",
            (token,)
        )
    return {"message": "Unsubscribed successfully"}


@router.get("/job-alerts/send")
async def send_job_alerts(
    current_user: dict = Depends(get_current_user),
):
    """
    Manually trigger job alert emails for alerts due NOW.
    In production call this every hour via a Railway cron.
    """
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    sent = await _dispatch_job_alerts(respect_send_time=False)
    return {"message": f"Sent {sent} job alert emails"}


@router.get("/admin/alerts/diagnose")
async def diagnose_alerts(
    keywords: str = "",
    location: str = "",
    industry: str = "",
    current_user: dict = Depends(get_current_user),
):
    """
    Admin diagnostic: test exactly what jobs would match an alert.
    Use this to debug why alerts are not delivering.
    """
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]

    # Count total active jobs
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1")
        row = cur.fetchone()
        total_active = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

        # Sample of active jobs for reference
        cur.execute(
            "SELECT title, company, industry, location FROM jobs "
            "WHERE is_active = 1 ORDER BY created_at DESC LIMIT 10"
        )
        sample = [dict(r) for r in cur.fetchall()]

    # Run the actual match
    matched = _find_matching_jobs(kw_list, location, industry, hours=24 * 90)

    return {
        "total_active_jobs": total_active,
        "query": {"keywords": kw_list, "location": location, "industry": industry},
        "matched_count": len(matched),
        "matched_jobs": matched,
        "sample_active_jobs": sample,
        "hint": (
            "If matched_count=0 but sample_active_jobs has jobs you expect to match, "
            "check that the keyword appears in the job title, description, or company name."
        ),
    }


@router.post("/job-alerts/cron")
async def cron_send_alerts(request: Request):
    """
    Called by an external cron service (Railway Cron, cron-job.org, etc.) every hour.
    Only sends to users whose preferred send_time matches the current UTC hour.

    Protected by CRON_SECRET env var — pass it as header X-Cron-Secret.
    If CRON_SECRET is not set, the endpoint runs unprotected (not recommended for prod).
    """
    import os
    expected_secret = os.environ.get("CRON_SECRET", "")
    if expected_secret:
        provided = request.headers.get("x-cron-secret", "")
        if provided != expected_secret:
            raise HTTPException(403, "Invalid cron secret")

    import os as _os
    from datetime import datetime as _dt2, timezone as _tz2
    triggered_at = _dt2.now(_tz2.utc).isoformat()
    log.info(f"Cron job triggered at {triggered_at}")

    # Record this cron execution so admin can verify it's running
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            if USE_POSTGRES:
                cur.execute("""
                    INSERT INTO admin_settings (key, value, updated_at)
                    VALUES ('cron_last_run', %s, NOW())
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """, (triggered_at,))
            else:
                cur.execute(
                    "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('cron_last_run', ?)",
                    (triggered_at,)
                )
    except Exception as e:
        log.warning(f"Could not record cron run: {e}")

    sent = await _dispatch_job_alerts(respect_send_time=True)
    log.info(f"Cron job complete: {sent} alert(s) sent at {triggered_at}")
    return {"sent": sent, "triggered_at": triggered_at}


@router.get("/job-alerts/cron-status")
async def public_cron_status():
    """Public endpoint — shows when cron last ran and how many alerts were active."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("cron_last_run",)
            )
            row = cur.fetchone()
            last_run = dict(row)["value"] if row else None

            cur.execute(
                "SELECT COUNT(*) FROM job_alerts WHERE is_active = TRUE"
                if USE_POSTGRES else
                "SELECT COUNT(*) FROM job_alerts WHERE is_active = 1"
            )
            row = cur.fetchone()
            active_alerts = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

            cur.execute(
                "SELECT COUNT(*) FROM alert_delivery_log WHERE sent_at > NOW() - INTERVAL '24 hours'"
                if USE_POSTGRES else
                "SELECT COUNT(*) FROM alert_delivery_log WHERE sent_at > datetime('now', '-24 hours')"
            )
            row = cur.fetchone()
            sent_24h = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

    except Exception as e:
        return {"error": str(e)}

    from datetime import datetime as _dt2, timezone as _tz2
    return {
        "cron_last_run": last_run,
        "current_utc": _dt2.now(_tz2.utc).isoformat(),
        "active_alerts": active_alerts,
        "emails_sent_last_24h": sent_24h,
        "status": "✓ Cron is running" if last_run else "⚠ Cron has never run — check cron-job.org",
    }


@router.get("/job-alerts/debug")
async def debug_alerts():
    """
    Public debug endpoint — shows active alerts and whether they match any jobs.
    Remove or protect this after debugging.
    """
    import os
    app_url = os.environ.get("APP_URL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    resend_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "")

    # Get active alerts
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, keywords, location, industry, frequency, send_time "
            "FROM job_alerts WHERE is_active = TRUE" if USE_POSTGRES
            else "SELECT id, email, keywords, location, industry, frequency, send_time "
            "FROM job_alerts WHERE is_active = 1"
        )
        alerts = [dict(r) for r in cur.fetchall()]

        # Count total active jobs
        cur.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1")
        row = cur.fetchone()
        total_jobs = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

        # Sample 5 job titles
        cur.execute(
            "SELECT title, company, industry FROM jobs WHERE is_active = 1 "
            "ORDER BY created_at DESC LIMIT 5"
        )
        sample_jobs = [dict(r) for r in cur.fetchall()]

    # Test matching for each alert
    results = []
    for alert in alerts:
        keywords = [k.strip() for k in alert["keywords"].split(",") if k.strip()]
        matched = _find_matching_jobs(
            keywords,
            alert.get("location", "") or "",
            alert.get("industry", "") or "",
            hours=24 * 90,
        )
        results.append({
            "email": alert["email"][:4] + "***",
            "keywords": alert["keywords"],
            "location": alert.get("location", ""),
            "industry": alert.get("industry", ""),
            "matched_jobs": len(matched),
            "sample_match": matched[0]["title"] if matched else None,
        })

    return {
        "total_active_alerts": len(alerts),
        "total_active_jobs": total_jobs,
        "sample_jobs": sample_jobs,
        "email_transport": "SMTP" if smtp_host else ("Resend" if resend_key else "NONE"),
        "from_email": from_email,
        "app_url": app_url,
        "alert_matches": results,
    }


@router.get("/job-alerts/cron-status")
async def cron_status(current_user: dict = Depends(get_current_user)):
    """Admin: check when alerts were last sent, to verify cron is running."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(sent_at) as last_sent, COUNT(*) as total_sends "
            "FROM alert_delivery_log WHERE sent_at > NOW() - INTERVAL '24 hours'"
            if USE_POSTGRES else
            "SELECT MAX(sent_at) as last_sent, COUNT(*) as total_sends "
            "FROM alert_delivery_log WHERE sent_at > datetime('now', '-24 hours')"
        )
        row = dict(cur.fetchone())
    return {
        "last_sent_at": row.get("last_sent"),
        "sends_last_24h": row.get("total_sends", 0),
        "cron_secret_configured": bool(__import__("os").environ.get("CRON_SECRET", "")),
    }


async def _dispatch_job_alerts(respect_send_time: bool = False):
    """
    Match active alerts against new jobs and send emails.
    If respect_send_time=True, only send to users whose send_time matches
    the current hour (so cron can run every hour safely).
    """
    import os
    import urllib.request
    from datetime import datetime as _dt, timezone as _tz

    # Each alert uses its own timezone — now_hour is UTC reference only
    now_utc = _dt.now(_tz.utc)
    now_hour = now_utc.strftime("%H:00")  # UTC fallback for alerts without timezone
    log.info(f"Cron dispatch: UTC={now_hour}, checking {len(alerts)} active alerts")

    resend_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
    app_url = os.environ.get("APP_URL", "https://jobstream.ng").rstrip("/")
    sent = 0

    # Load custom email template if set
    template = None
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("alert_email_template",)
            )
            row = cur.fetchone()
            if row:
                template = dict(row)["value"]
    except Exception:
        pass

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, email, keywords, location, industry, frequency, send_time, "
            "timezone, unsubscribe_token, last_sent_at FROM job_alerts WHERE is_active = TRUE"
            if USE_POSTGRES else
            "SELECT id, email, keywords, location, industry, frequency, send_time, "
            "timezone, unsubscribe_token, last_sent_at FROM job_alerts WHERE is_active = 1"
        )
        alerts = [dict(r) for r in cur.fetchall()]

    for alert in alerts:
        keywords = [k.strip() for k in alert["keywords"].split(",") if k.strip()]
        if not keywords:
            continue

        # Check preferred send_time in the alert's own timezone
        if respect_send_time:
            alert_time = (alert.get("send_time") or "08:00").strip()[:5]
            alert_tz   = (alert.get("timezone")  or "Africa/Lagos").strip()
            try:
                import zoneinfo as _zi
                local_now = _dt.now(_zi.ZoneInfo(alert_tz)).strftime("%H:00")
            except Exception:
                local_now = now_hour  # fallback
            log.info(
                f"Alert {alert.get('email','')[:6]}*** | "
                f"send_time={alert_time} | tz={alert_tz} | "
                f"local_now={local_now} | match={'YES' if alert_time == local_now else 'NO'}"
            )
            if alert_time != local_now:
                continue  # Not this alert's hour yet in their timezone

        hours = 24 if alert.get("frequency") == "daily" else 168
        matching_jobs = _find_matching_jobs(
            keywords,
            alert.get("location", "") or "",
            alert.get("industry", "") or "",
            hours,
        )

        if not matching_jobs:
            continue

        try:
            log_id = _send_alert_email(
                app_url=app_url,
                to_email=alert["email"],
                keywords=keywords,
                jobs=matching_jobs,
                token=alert.get("unsubscribe_token") or str(uuid.uuid4()),
                alert_id=str(alert["id"]),
                location=alert.get("location", "") or "",
                industry=alert.get("industry", "") or "",
                template=template,
            )
        except Exception as e:
            log.error(f"Alert email failed for {alert.get('email')}: {e}")
            continue
        # Record delivery
        if log_id:
            try:
                with get_conn() as conn:
                    cur = conn.cursor()
                    ph = "%s" if USE_POSTGRES else "?"
                    cur.execute(
                        f"INSERT INTO alert_delivery_log "
                        f"(id, alert_id, email, keywords, jobs_count) "
                        f"VALUES ({ph},{ph},{ph},{ph},{ph})",
                        (log_id, str(alert["id"]), alert["email"],
                         ", ".join(keywords), len(matching_jobs))
                    )
                    cur.execute(
                        ("UPDATE job_alerts SET last_sent_at = NOW() WHERE id = %s"
                         if USE_POSTGRES else
                         "UPDATE job_alerts SET last_sent_at = datetime('now') WHERE id = ?"),
                        (str(alert["id"]),)
                    )
            except Exception as e:
                log.error(f"Failed to log delivery: {e}")
        sent += 1

    return sent


def _find_matching_jobs(keywords: list, location: str, industry: str, hours: int) -> list:
    """
    Find active jobs matching ANY of the keywords.

    Matching strategy (in priority order for each keyword):
      1. Title exact word match  — "analyst" matches "Financial Analyst" not "psychoanalyst"
      2. Title substring match   — broader fallback for multi-word keywords like "product manager"
      3. Company name match      — for company-based alerts

    Description is intentionally NOT searched — it is too broad and causes false positives
    (e.g. "analyst" appears in any job description that mentions financial analysis).

    Location and industry are optional ANDed filters — blank = ignored.
    Returns up to 10 deduplicated jobs ordered by newest first.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        all_results = []

        for kw in keywords[:10]:  # check all keywords
            kw = kw.strip()
            if not kw:
                continue

            # Build location / industry / time conditions (shared across all queries)
            extra_conditions = ["is_active = 1"]
            extra_params = []

            loc = (location or "").strip()
            if loc and loc.lower() not in ("any", "anywhere", "remote"):
                if USE_POSTGRES:
                    extra_conditions.append("location ILIKE %s")
                else:
                    extra_conditions.append("location LIKE ?")
                extra_params.append(f"%{loc}%")
            elif loc.lower() == "remote":
                if USE_POSTGRES:
                    extra_conditions.append("location ILIKE %s")
                else:
                    extra_conditions.append("location LIKE ?")
                extra_params.append("%remote%")

            ind = (industry or "").strip()
            if ind:
                if USE_POSTGRES:
                    extra_conditions.append("industry ILIKE %s")
                else:
                    extra_conditions.append("industry LIKE ?")
                extra_params.append(f"%{ind}%")

            if USE_POSTGRES:
                extra_conditions.append(
                    f"created_at > NOW() - INTERVAL '{int(hours)} hours'"
                )
            else:
                extra_conditions.append("created_at > datetime('now', ?)")
                extra_params.append(f"-{int(hours)} hours")

            base_where = " AND ".join(extra_conditions)

            # ── Strategy 1: word-boundary title match ────────────────────────
            # Matches "Analyst" in "Financial Analyst" but NOT in "psychoanalyst"
            if USE_POSTGRES:
                sql = (
                    "SELECT id, title, company, location, job_type, industry, "
                    "apply_url, source_url, 1 as match_rank "
                    f"FROM jobs WHERE {base_where} "
                    "AND (title ~* %s OR title ILIKE %s) "
                    "ORDER BY created_at DESC LIMIT 10"
                )
                word_pattern = r"(^|\s|,|/|-)" + re.escape(kw) + r"($|\s|,|/|-)"
                title_like = f"% {kw} %"
                params = extra_params + [word_pattern, title_like]
            else:
                sql = (
                    "SELECT id, title, company, location, job_type, industry, "
                    "apply_url, source_url, 1 as match_rank "
                    f"FROM jobs WHERE {base_where} "
                    "AND title LIKE ? "
                    "ORDER BY created_at DESC LIMIT 10"
                )
                params = extra_params + [f"%{kw}%"]

            log.debug(f"Keyword '{kw}' title query | params={params}")
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            log.info(f"  Keyword '{kw}' → {len(rows)} title matches")
            all_results.extend(rows)

            # ── Strategy 2: company name match ───────────────────────────────
            if USE_POSTGRES:
                sql2 = (
                    "SELECT id, title, company, location, job_type, industry, "
                    "apply_url, source_url, 2 as match_rank "
                    f"FROM jobs WHERE {base_where} "
                    "AND company ILIKE %s "
                    "ORDER BY created_at DESC LIMIT 5"
                )
                params2 = extra_params + [f"%{kw}%"]
            else:
                sql2 = (
                    "SELECT id, title, company, location, job_type, industry, "
                    "apply_url, source_url, 2 as match_rank "
                    f"FROM jobs WHERE {base_where} "
                    "AND company LIKE ? "
                    "ORDER BY created_at DESC LIMIT 5"
                )
                params2 = extra_params + [f"%{kw}%"]

            cur.execute(sql2, params2)
            all_results.extend([dict(r) for r in cur.fetchall()])

        # Deduplicate by id, keeping first (highest priority) occurrence
        seen = set()
        unique = []
        for job in all_results:
            if job["id"] not in seen:
                seen.add(job["id"])
                unique.append(job)

        log.info(
            f"_find_matching_jobs keywords={keywords} loc={location!r} "
            f"ind={industry!r} hours={hours} → {len(unique)} jobs"
        )
        return unique[:10]


def _send_alert_email(
    app_url,
    to_email, keywords, jobs, token,
    alert_id="", location="", industry="",
    template=None,
    api_key=None, from_email=None,  # kept for backward compat, ignored
):
    """
    Send job alert email via core.email (SMTP or Resend).
    Returns a log_id (UUID) on success, raises on failure.
    """
    from core.email import send_email
    import urllib.request as _urllib_request

    log_id = str(uuid.uuid4())
    tracking_pixel = (
        f'<img src="{app_url}/track/open/{log_id}" '
        f'width="1" height="1" style="display:none" />'
    )

    # Build jobs HTML block — use job ID directly (most reliable, no slug parsing)
    jobs_html = ""
    import base64 as _b64
    for job in jobs[:5]:
        job_id = str(job.get("id", ""))
        # ?jobid=ID param — read by frontend to open specific job by database ID
        direct_url = f"{app_url}/?jobid={job_id}"
        encoded_dest = _b64.urlsafe_b64encode(direct_url.encode()).decode()
        tracked_url = f"{app_url}/track/click/{log_id}?dest={encoded_dest}"
        industry_tag = f" &middot; {job['industry']}" if job.get("industry") else ""
        jobs_html += (
            f'<div style="padding:12px 0;border-bottom:1px solid #f0f0f0">'
            f'<a href="{tracked_url}" style="font-size:14px;font-weight:600;color:#0071E3;text-decoration:none">'
            f'{job["title"]}</a>'
            f'<div style="font-size:12px;color:#888;margin-top:2px">'
            f'{job["company"]} &middot; {job.get("location","")}{industry_tag}</div>'
            f'</div>'
        )

    if template:
        # Use admin-customised template — substitute placeholders
        location_html = f" &middot; {location}" if location else ""
        industry_html = f" &middot; {industry}" if industry else ""
        html = (template
                .replace("{{keywords}}", ", ".join(keywords))
                .replace("{{#if location}} &middot; {{location}}{{/if}}", location_html)
                .replace("{{#if industry}} &middot; {{industry}}{{/if}}", industry_html)
                .replace("{{jobs_html}}", jobs_html)
                .replace("{{app_url}}", app_url)
                .replace("{{unsubscribe_url}}", f"{app_url}/job-alerts/unsubscribe/{token}")
                )
    else:
        location_line = f" &middot; {location}" if location else ""
        industry_line = f" &middot; {industry}" if industry else ""
        html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f4f4f6;margin:0;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:36px;">
  <h1 style="font-size:18px;color:#1d1d1f;margin-bottom:4px;">&#9889; JobStream</h1>
  <h2 style="font-size:20px;color:#1d1d1f;margin-bottom:6px;">New jobs for you</h2>
  <p style="font-size:13px;color:#888;margin-bottom:20px">
    Matching: <strong>{', '.join(keywords)}</strong>{location_line}{industry_line}
  </p>
  {jobs_html}
  <div style="text-align:center;margin-top:24px">
    <a href="{app_url}" style="display:inline-block;padding:12px 28px;background:#0071E3;
       color:#fff;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px">
      View all jobs
    </a>
  </div>
  <p style="font-size:11px;color:#ccc;text-align:center;margin-top:24px">
    <a href="{app_url}/job-alerts/unsubscribe/{token}" style="color:#ccc">Unsubscribe</a>
  </p>
  {tracking_pixel}
</div>
</body>
</html>"""

    try:
        payload = json.dumps({
            "from": f"JobStream Alerts <{from_email}>",
            "to": [to_email],
            "subject": f"New jobs: {', '.join(keywords[:2])}",
            "html": html,
        }).encode("utf-8")

        subject = f"New jobs: {', '.join(keywords[:2])}"
        send_email(to_email=to_email, subject=subject, html=html, from_name="JobStream Alerts")
        return log_id
    except Exception as e:
        log.error(f"Alert email failed for {to_email}: {e}")
        raise


# ── Job expiry ────────────────────────────────────────────────────────────────

@router.post("/jobs/expire")
async def expire_old_jobs(
    days: int = Query(60),
    current_user: dict = Depends(get_current_user),
):
    """
    Archive scraped jobs older than N days.
    Manual jobs are never auto-expired.
    """
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                UPDATE jobs SET is_active = 0
                WHERE source = 'scraped'
                AND is_active = 1
                AND created_at < NOW() - INTERVAL '%s days'
            """, (days,))
            count = cur.rowcount
        else:
            cur.execute("""
                UPDATE jobs SET is_active = 0
                WHERE source = 'scraped'
                AND is_active = 1
                AND created_at < datetime('now', ?)
            """, (f"-{days} days",))
            count = cur.rowcount

    log.info(f"Expired {count} jobs older than {days} days")
    return {"message": f"Archived {count} scraped jobs older than {days} days"}

# ════════════════════════════════════════════════════════════════
# ADMIN — Industry list management
# ════════════════════════════════════════════════════════════════

def _get_industries_from_db() -> list[str]:
    """Return merged list: built-in + any admin-added industries."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM admin_industries ORDER BY name")
            db_industries = [r["name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
        return sorted(set(ALERT_INDUSTRIES) | set(db_industries))
    except Exception:
        return ALERT_INDUSTRIES


@router.get("/admin/industries")
async def list_industries(current_user: dict = Depends(get_current_user)):
    """Admin: list all available industries (built-in + custom)."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    return {"industries": _get_industries_from_db()}


@router.post("/admin/industries")
async def add_industry(
    name: str,
    current_user: dict = Depends(get_current_user),
):
    """Admin: add a custom industry to the list."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    if not name.strip():
        raise HTTPException(400, "Industry name cannot be empty")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT OR IGNORE INTO admin_industries (name) VALUES ({ph})" if not USE_POSTGRES
            else "INSERT INTO admin_industries (name) VALUES (%s) ON CONFLICT DO NOTHING",
            (name.strip(),)
        )
    return {"message": f"Industry '{name.strip()}' added", "industries": _get_industries_from_db()}


@router.delete("/admin/industries/{name}")
async def remove_industry(
    name: str,
    current_user: dict = Depends(get_current_user),
):
    """Admin: remove a custom industry (built-ins cannot be removed)."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    if name in ALERT_INDUSTRIES:
        raise HTTPException(400, "Cannot remove a built-in industry. You can only remove custom ones.")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"DELETE FROM admin_industries WHERE name = {ph}", (name,))
    return {"message": f"Industry '{name}' removed", "industries": _get_industries_from_db()}


# Override the public meta endpoint to include custom industries
@router.get("/job-alerts/meta-admin")
async def job_alerts_meta_admin(current_user: dict = Depends(get_current_user)):
    """Admin version — includes DB-backed industry list."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    return {"industries": _get_industries_from_db(), "send_times": ALERT_SEND_TIMES}


# ════════════════════════════════════════════════════════════════
# ADMIN — Email alert template editor
# ════════════════════════════════════════════════════════════════

DEFAULT_ALERT_TEMPLATE = """<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f4f4f6;margin:0;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:36px;">
  <h1 style="font-size:18px;color:#1d1d1f;margin-bottom:4px;">&#9889; JobStream</h1>
  <h2 style="font-size:20px;color:#1d1d1f;margin-bottom:6px;">New jobs for you</h2>
  <p style="font-size:13px;color:#888;margin-bottom:20px">
    Matching: <strong>{{keywords}}</strong>
    {{#if location}} &middot; {{location}}{{/if}}
    {{#if industry}} &middot; {{industry}}{{/if}}
  </p>
  {{jobs_html}}
  <div style="text-align:center;margin-top:24px">
    <a href="{{app_url}}" style="display:inline-block;padding:12px 28px;background:#0071E3;
       color:#fff;border-radius:10px;text-decoration:none;font-weight:600;font-size:14px">
      View all jobs
    </a>
  </div>
  <p style="font-size:11px;color:#ccc;text-align:center;margin-top:24px">
    <a href="{{unsubscribe_url}}" style="color:#ccc">Unsubscribe</a>
  </p>
</div>
</body>
</html>"""


@router.get("/admin/alert-template")
async def get_alert_template(current_user: dict = Depends(get_current_user)):
    """Admin: get the current email alert HTML template."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM admin_settings WHERE key = 'alert_email_template'")
            row = cur.fetchone()
            template = dict(row)["value"] if row else DEFAULT_ALERT_TEMPLATE
    except Exception:
        template = DEFAULT_ALERT_TEMPLATE
    return {"template": template}


@router.post("/admin/alert-template")
async def save_alert_template(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: save a custom email alert HTML template."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    body = await request.json()
    template = body.get("template", "").strip()
    if not template:
        raise HTTPException(400, "Template cannot be empty")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO admin_settings (key, value) VALUES ('alert_email_template', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (template,))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO admin_settings (key, value, updated_at)
                VALUES ('alert_email_template', ?, datetime('now'))
            """, (template,))
    return {"message": "Template saved"}


@router.post("/admin/alert-template/reset")
async def reset_alert_template(current_user: dict = Depends(get_current_user)):
    """Admin: revert to the default email template."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO admin_settings (key, value) VALUES ('alert_email_template', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (DEFAULT_ALERT_TEMPLATE,))
        else:
            cur.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('alert_email_template', ?)",
                (DEFAULT_ALERT_TEMPLATE,)
            )
    return {"message": "Template reset to default", "template": DEFAULT_ALERT_TEMPLATE}


@router.post("/admin/alert-template/test")
async def send_test_alert_email(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: send a test alert email immediately to a given address."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    import os
    body = await request.json()
    to_email = body.get("email", "").strip()
    template = body.get("template", None)

    if not to_email:
        raise HTTPException(400, "Email address required")

    resend_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
    app_url = os.environ.get("APP_URL", "https://jobstream.ng").rstrip("/")

    if not resend_key:
        raise HTTPException(503, "RESEND_API_KEY not configured")

    sample_jobs = [
        {"id": 0, "title": "Senior Network Engineer", "company": "MTN Nigeria",
         "location": "Lagos, Nigeria", "industry": "Telecommunications"},
        {"id": 1, "title": "Software Developer", "company": "Airtel Africa",
         "location": "Abuja, Nigeria", "industry": "Telecommunications"},
    ]

    try:
        log_id = _send_alert_email(
            api_key=resend_key,
            from_email=from_email,
            app_url=app_url,
            to_email=to_email,
            keywords=["Network Engineer", "Software Developer"],
            jobs=sample_jobs,
            token="test-unsubscribe-token",
            alert_id="test",
            location="Lagos, Nigeria",
            industry="Telecommunications",
            template=template,
        )
    except Exception as e:
        raise HTTPException(502, str(e))

    if not log_id:
        raise HTTPException(502, f"Email send failed. FROM_EMAIL={from_email!r} — make sure this domain is verified on Resend.")

    return {"message": f"Test email sent to {to_email} from {from_email}"}


@router.post("/admin/alerts/{alert_id}/send-now")
async def send_alert_now(
    alert_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Admin: immediately dispatch a job alert email to one user,
    regardless of their preferred send_time. Useful for testing.
    """
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    import os
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT * FROM job_alerts WHERE id = {ph}", (alert_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Alert not found")
        alert = dict(row)

    keywords = [k.strip() for k in alert["keywords"].split(",") if k.strip()]

    log.info(f"send-now: alert {alert_id} | keywords={keywords} | "
             f"location={alert.get('location','')!r} | industry={alert.get('industry','')!r}")

    # Admin send-now: search across last 90 days AND also try without time filter
    matching_jobs = _find_matching_jobs(
        keywords,
        alert.get("location", "") or "",
        alert.get("industry", "") or "",
        hours=24 * 90,
    )

    # If still nothing, try without location/industry filters (broadest possible match)
    if not matching_jobs:
        log.info(f"No results with filters — retrying without location/industry")
        matching_jobs = _find_matching_jobs(keywords, "", "", hours=24 * 90)

    if not matching_jobs:
        # Query what IS in the DB so admin can diagnose
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1")
            row = cur.fetchone()
            total = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])
        raise HTTPException(404,
            f"No matching jobs found for keywords: {keywords}. "
            f"Platform has {total} active jobs. "
            f"Check that job titles contain these keywords."
        )

    log.info(f"send-now: found {len(matching_jobs)} matching jobs for alert {alert_id}")

    app_url = os.environ.get("APP_URL", "https://jobstream.ng").rstrip("/")

    template = None
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("alert_email_template",)
            )
            row = cur.fetchone()
            if row:
                template = dict(row)["value"]
    except Exception:
        pass

    try:
        token = alert.get("unsubscribe_token") or str(uuid.uuid4())
        log_id = _send_alert_email(
            app_url=app_url,
            to_email=alert["email"],
            keywords=keywords,
            jobs=matching_jobs,
            token=token,
            alert_id=alert_id,
            location=alert.get("location", "") or "",
            industry=alert.get("industry", "") or "",
            template=template,
        )
    except Exception as e:
        import traceback
        log.error(f"send-now failed: {traceback.format_exc()}")
        raise HTTPException(502, f"Email failed: {e}")

    if log_id:
        try:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"INSERT INTO alert_delivery_log "
                    f"(id, alert_id, email, keywords, jobs_count) VALUES ({ph},{ph},{ph},{ph},{ph})",
                    (log_id, alert_id, alert["email"], ", ".join(keywords), len(matching_jobs))
                )
                cur.execute(
                    ("UPDATE job_alerts SET last_sent_at = NOW() WHERE id = %s"
                        if USE_POSTGRES else
                        "UPDATE job_alerts SET last_sent_at = datetime('now') WHERE id = ?"),
                    (alert_id,)
                )
        except Exception as e:
            log.error(f"Failed to log manual send: {e}")

    return {
        "message": f"Alert sent to {alert['email']} with {len(matching_jobs)} jobs",
        "jobs_count": len(matching_jobs),
        "from": os.environ.get("FROM_EMAIL", ""),
    }


# ════════════════════════════════════════════════════════════════
# ADMIN — Alert monitoring: delivery log + open tracking
# ════════════════════════════════════════════════════════════════

@router.get("/admin/alerts")
async def admin_list_alerts(
    search: str = Query(""),
    is_active: str = Query(""),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    current_user: dict = Depends(get_current_user),
):
    """Admin: list all job alerts with delivery stats."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")

    conditions = []
    params = []
    ph = "%s" if USE_POSTGRES else "?"

    if search:
        like = f"%{search}%"
        if USE_POSTGRES:
            conditions.append("(email ILIKE %s OR keywords ILIKE %s)")
        else:
            conditions.append("(email LIKE ? OR keywords LIKE ?)")
        params += [like, like]
    if is_active in ("0", "1"):
        conditions.append(f"is_active = {ph}")
        params.append(int(is_active))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM job_alerts {where}", params)
        row = cur.fetchone()
        total = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

        cur.execute(
            f"SELECT id, email, keywords, location, industry, frequency, send_time, "
            f"is_active, last_sent_at, created_at FROM job_alerts {where} "
            f"ORDER BY created_at DESC LIMIT {ph} OFFSET {ph}",
            params + [limit, offset]
        )
        alerts = [dict(r) for r in cur.fetchall()]

        # Enrich with delivery stats
        for alert in alerts:
            cur.execute(
                f"SELECT COUNT(*) FROM alert_delivery_log WHERE alert_id = {ph}",
                (alert["id"],)
            )
            row = cur.fetchone()
            alert["emails_sent"] = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

            cur.execute(
                f"SELECT COUNT(*) FROM alert_delivery_log WHERE alert_id = {ph} AND opened_at IS NOT NULL",
                (alert["id"],)
            )
            row = cur.fetchone()
            alert["emails_opened"] = int(list(dict(row).values())[0]) if USE_POSTGRES else int(row[0])

    return {"total": total, "alerts": alerts}


@router.patch("/admin/alerts/{alert_id}")
async def admin_update_alert(
    alert_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: force-activate or deactivate an alert."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    body = await request.json()
    is_active = body.get("is_active")
    if is_active is None:
        raise HTTPException(400, "Provide is_active")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE job_alerts SET is_active = {ph} WHERE id = {ph}",
            (1 if is_active else 0, alert_id)
        )
    return {"message": "Alert updated"}


@router.get("/admin/alerts/{alert_id}/log")
async def alert_delivery_log(
    alert_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Admin: view delivery history for a specific alert."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"SELECT * FROM alert_delivery_log WHERE alert_id = {ph} "
            f"ORDER BY sent_at DESC LIMIT 50",
            (alert_id,)
        )
        return [dict(r) for r in cur.fetchall()]


@router.get("/admin/settings/streamer")
async def get_streamer_settings():
    """Get streamer interval setting."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("scrape_interval_hours",)
            )
            row = cur.fetchone()
            hours = int(dict(row)["value"]) if row else 4
    except Exception:
        hours = 4
    return {"scrape_interval_hours": hours}


@router.post("/admin/settings/streamer")
async def save_streamer_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: set how many hours between automatic scrape runs."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    body = await request.json()
    hours = max(1, int(body.get("scrape_interval_hours", 4)))
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO admin_settings (key, value) VALUES ('scrape_interval_hours', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (str(hours),))
        else:
            cur.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('scrape_interval_hours', ?)",
                (str(hours),)
            )
    return {
        "message": f"Streamer interval set to {hours} hour(s). Restart the backend to apply.",
        "scrape_interval_hours": hours,
    }


@router.get("/admin/settings/brand")
async def get_brand_settings():
    """Get brand settings (public — loaded on app init)."""
    default = {"name": "JobStream", "logo_url": ""}
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("brand_settings",)
            )
            row = cur.fetchone()
            if row:
                import json as _json
                return _json.loads(dict(row)["value"])
    except Exception:
        pass
    return default


@router.post("/admin/settings/brand")
async def save_brand_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: save platform name and logo URL."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    import json as _json
    body = await request.json()
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO admin_settings (key, value) VALUES ('brand_settings', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (_json.dumps(body),))
        else:
            cur.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('brand_settings', ?)",
                (_json.dumps(body),)
            )
    return {"message": "Brand settings saved", "settings": body}


@router.get("/admin/settings/nav")
async def get_nav_settings():
    """Get nav visibility settings (public — loaded on app init)."""
    default = {
        "guest":     ["jobs", "companies", "postjob"],
        "candidate": ["jobs", "companies", "myapps", "saved", "myalerts", "ai", "billing"],
        "employer":  ["jobs", "companies", "employer", "applications", "analytics", "billing"],
        "admin":     ["jobs", "companies", "myapps", "saved", "employer", "applications",
                      "ai", "billing", "analytics", "workspace", "admin", "scraper"],
    }
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("nav_settings",)
            )
            row = cur.fetchone()
            if row:
                import json as _json
                return _json.loads(dict(row)["value"])
    except Exception:
        pass
    return default


@router.post("/admin/settings/nav")
async def save_nav_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: control which sidebar menu items each user type sees."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    import json as _json
    body = await request.json()
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO admin_settings (key, value) VALUES ('nav_settings', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (_json.dumps(body),))
        else:
            cur.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('nav_settings', ?)",
                (_json.dumps(body),)
            )
    return {"message": "Nav settings saved", "settings": body}


@router.get("/admin/settings/theme")
async def get_theme_settings():
    """Get theme settings (public — loaded on app init)."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(
                f"SELECT value FROM admin_settings WHERE key = {ph}",
                ("theme_settings",)
            )
            row = cur.fetchone()
            if row:
                import json as _json
                return _json.loads(dict(row)["value"])
    except Exception:
        pass
    return {"accent_color": "#0071E3", "bg_dark": "#0a0a0c", "bg_light": "#f5f5f7"}


@router.post("/admin/settings/theme")
async def save_theme_settings(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin: save frontend theme colors."""
    if current_user.get("role") not in ("super_admin", "platform_admin"):
        raise HTTPException(403, "Admin only")
    import json as _json
    body = await request.json()
    ph = "%s" if USE_POSTGRES else "?"
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO admin_settings (key, value) VALUES ('theme_settings', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
            """, (_json.dumps(body),))
        else:
            cur.execute(
                "INSERT OR REPLACE INTO admin_settings (key, value) VALUES ('theme_settings', ?)",
                (_json.dumps(body),)
            )
    return {"message": "Theme saved", "settings": body}


@router.get("/track/click/{log_id}")
async def track_email_click(log_id: str, dest: str = "", redirect: str = ""):
    """
    Track when a user clicks a link in a job alert email.
    Accepts either:
      - dest: base64-encoded destination URL (preferred — handles nested params)
      - redirect: plain URL (legacy fallback)
    """
    import base64 as _b64

    # Decode destination URL
    final_url = "/"
    if dest:
        try:
            final_url = _b64.urlsafe_b64decode(dest.encode()).decode()
        except Exception:
            final_url = dest  # use as-is if decode fails
    elif redirect:
        final_url = redirect

    # Record the open/click in delivery log
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            sql = (
                "UPDATE alert_delivery_log SET opened_at = NOW() "
                "WHERE id = %s AND opened_at IS NULL"
                if USE_POSTGRES else
                "UPDATE alert_delivery_log SET opened_at = datetime('now') "
                "WHERE id = ? AND opened_at IS NULL"
            )
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(sql, (log_id,))
            rows_updated = cur.rowcount
            log.info(f"Email click: log_id={log_id} rows_updated={rows_updated} → {final_url}")
    except Exception as e:
        log.warning(f"Track click DB update failed: {e}")

    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=final_url, status_code=302)


@router.get("/track/open/{log_id}")
async def track_email_open(log_id: str):
    """
    1x1 transparent pixel served when recipient opens an alert email.
    The <img> tag in the email HTML calls this endpoint.
    """
    ph = "%s" if USE_POSTGRES else "?"
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            sql = (
                "UPDATE alert_delivery_log SET opened_at = NOW() WHERE id = %s AND opened_at IS NULL"
                if USE_POSTGRES else
                "UPDATE alert_delivery_log SET opened_at = datetime('now') WHERE id = ? AND opened_at IS NULL"
            )
            cur.execute(sql, (log_id,))
    except Exception as e:
        log.warning(f"Track open failed for {log_id}: {e}")

    # Return a 1x1 transparent GIF
    gif = (
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff"
        b"\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,"
        b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )
    from fastapi.responses import Response as FastAPIResponse
    return FastAPIResponse(content=gif, media_type="image/gif",
                          headers={"Cache-Control": "no-cache, no-store"})
