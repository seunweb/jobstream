"""
Recruitment background tasks — scraping, backfill, force rescrape.
Moved from main.py to keep main.py clean.
"""

import asyncio
import logging
from core.database import get_conn, USE_POSTGRES, get_companies, upsert_jobs, mark_jobs_inactive, start_scrape_run, finish_scrape_run
from services.recruitment.scraper import scrape_all, fetch_job_description, _cache_invalidate, _extract_greenhouse_token

log = logging.getLogger(__name__)


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
        log.info(f"Scrape complete: {total_found} found, {total_new} new")

        # ── Dispatch job alerts after every scrape that found new jobs ────────
        if total_new > 0:
            try:
                from services.recruitment.seo_router import _dispatch_job_alerts
                sent = await _dispatch_job_alerts(respect_send_time=False)
                log.info(f"Post-scrape alerts: sent {sent} email(s) for {total_new} new jobs")
            except Exception as alert_err:
                log.warning(f"Post-scrape alert dispatch failed: {alert_err}")

    except Exception as e:
        error_msg = str(e)
        log.error(f"Scrape failed: {e}")
    finally:
        finish_scrape_run(run_id, total_found, total_new, error_msg)


async def run_scrape_task():
    companies = get_companies(active_only=True)
    if not companies:
        log.info("No active companies to scrape")
        return
    await _do_scrape(companies)


async def run_single_company_task(company: dict):
    await _do_scrape([company])


async def run_scheduled_scrape():
    log.info("Running scheduled scrape...")
    await run_scrape_task()


async def run_backfill():
    from playwright.async_api import async_playwright
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, apply_url FROM jobs WHERE (description IS NULL OR description = '') AND apply_url != '' ORDER BY id"
        )
        jobs = [dict(r) for r in cur.fetchall()]
    log.info(f"Backfill: {len(jobs)} jobs need descriptions")
    if not jobs:
        return
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        )
        page = await context.new_page()
        for i, job in enumerate(jobs):
            log.info(f"Backfill [{i+1}/{len(jobs)}]: {job['title']}")
            try:
                desc = await fetch_job_description(page, job["apply_url"])
                if desc:
                    with get_conn() as conn:
                        cur = conn.cursor()
                        if USE_POSTGRES:
                            cur.execute("UPDATE jobs SET description = %s WHERE id = %s", (desc, job["id"]))
                        else:
                            cur.execute("UPDATE jobs SET description = ? WHERE id = ?", (desc, job["id"]))
            except Exception as e:
                log.error(f"  Backfill error: {e}")
            await asyncio.sleep(1)
        await browser.close()
    log.info("Backfill complete!")


async def run_force_rescrape(company: dict):
    # Invalidate Greenhouse cache for this company so fresh data is fetched
    src_url = company.get("source_url", "")
    if "greenhouse.io" in src_url:
        token = _extract_greenhouse_token(src_url)
        if token:
            _cache_invalidate(token)
            log.info(f"Greenhouse cache invalidated for {token} (force rescrape)")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("DELETE FROM jobs WHERE source_url = %s", (company["url"],))
        else:
            cur.execute("DELETE FROM jobs WHERE source_url = ?", (company["url"],))
    await _do_scrape([company])
