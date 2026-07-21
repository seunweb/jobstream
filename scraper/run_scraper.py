"""
Standalone scraper runner for GitHub Actions.
Connects directly to Railway PostgreSQL and scrapes all active companies.

Usage:
  python run_scraper.py                        # scrape all companies
  COMPANY_URL=https://... python run_scraper.py  # scrape one company
  FORCE_RESCRAPE=true python run_scraper.py    # bypass 24h cache
"""

import os
import sys
import asyncio
import logging
from datetime import datetime

# Add scraper root to path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("run_scraper")


async def main():
    from core.database import get_conn, USE_POSTGRES, init_db
    from services.recruitment.scraper import scrape_company, _cache_invalidate, _extract_greenhouse_token
    from services.recruitment.tasks import upsert_jobs

    log.info(f"JobStream Scraper — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"Database: {'PostgreSQL (Railway)' if USE_POSTGRES else 'SQLite (local)'}")

    # Init DB (runs migrations)
    init_db()

    company_url  = os.getenv("COMPANY_URL", "").strip()
    force        = os.getenv("FORCE_RESCRAPE", "false").lower() == "true"

    # Load companies from DB
    with get_conn() as conn:
        cur = conn.cursor()
        if company_url:
            if USE_POSTGRES:
                cur.execute("SELECT id, name, url, industry, logo_url FROM companies WHERE url=%s AND active=1", (company_url,))
            else:
                cur.execute("SELECT id, name, url, industry, logo_url FROM companies WHERE url=? AND active=1", (company_url,))
        else:
            cur.execute("SELECT id, name, url, industry, logo_url FROM companies WHERE active=1 ORDER BY id")

        cols = [d[0] for d in cur.description]
        companies = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not companies:
        log.warning("No active companies found to scrape")
        return

    log.info(f"Scraping {len(companies)} companies...")

    # Invalidate cache if force rescrape
    if force:
        for c in companies:
            if "greenhouse.io" in c.get("url", ""):
                token = _extract_greenhouse_token(c["url"])
                if token:
                    _cache_invalidate(token)
                    log.info(f"Cache invalidated for {token}")

    total_found = 0
    total_new   = 0
    failed      = []

    for company in companies:
        name     = company["name"]
        url      = company["url"]
        industry = company.get("industry", "")
        logo_url = company.get("logo_url", "")

        try:
            log.info(f"Scraping: {name} ({url})")
            jobs = await scrape_company(url, name, industry, logo_url)

            if jobs:
                inserted = upsert_jobs(jobs)
                log.info(f"  → {len(jobs)} found, {inserted} new")
                total_found += len(jobs)
                total_new   += inserted
            else:
                log.warning(f"  → 0 jobs found")

        except Exception as e:
            log.error(f"  → FAILED: {e}")
            failed.append({"name": name, "url": url, "error": str(e)})

    # Summary
    log.info("")
    log.info("=" * 50)
    log.info(f"Scrape complete: {total_found} found, {total_new} new")
    log.info(f"Failed: {len(failed)}")
    for f in failed:
        log.info(f"  ✗ {f['name']}: {f['error'][:80]}")
    log.info("=" * 50)

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
