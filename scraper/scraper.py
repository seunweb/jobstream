"""
JobStream Scraper Engine
Supports Greenhouse, Lever, Oracle HCM, Workday, and generic career pages.
"""

import asyncio
import hashlib
import httpx
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


@dataclass
class ScrapedJob:
    title: str
    company: str
    source_url: str
    location: str = "Not specified"
    job_type: str = "Full-time"
    department: str = "General"
    salary: str = ""
    description: str = ""
    apply_url: str = ""
    scraped_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.title}|{self.company}|{self.source_url}".lower()
        return hashlib.md5(raw.encode()).hexdigest()



# ---------------------------------------------------------------------------
# Description fetcher — visits individual job page to get full description
# ---------------------------------------------------------------------------

async def fetch_job_description(page: Page, apply_url: str) -> str:
    """Visit the job detail page and extract the full description."""
    if not apply_url or not apply_url.startswith("http"):
        return ""
    try:
        await page.goto(apply_url, wait_until="networkidle", timeout=20000)
        await asyncio.sleep(1)
        soup = BeautifulSoup(await page.content(), "html.parser")

        # Remove noise
        for tag in soup.select("nav, header, footer, script, style, [class*='nav'], [class*='header'], [class*='footer'], [class*='cookie'], [class*='banner']"):
            tag.decompose()

        # Common description container selectors
        selectors = [
            "[class*='job-description']", "[class*='jobDescription']",
            "[class*='description']", "[class*='job-details']",
            "[class*='jobDetails']", "[class*='job-content']",
            "[class*='posting-content']", "[class*='content']",
            "article", "main", ".details", "#job-description",
            "#jobDescription", "[data-testid*='description']",
        ]

        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 100:
                    # Clean up excessive blank lines
                    lines = [l.strip() for l in text.splitlines()]
                    cleaned = "\n".join(l for l in lines if l)
                    return cleaned[:5000]  # cap at 5000 chars

        # Fallback: get body text
        body = soup.find("body")
        if body:
            text = body.get_text(separator="\n", strip=True)
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            return "\n".join(lines[:80])

    except Exception as e:
        logger.warning(f"Could not fetch description from {apply_url}: {e}")
    return ""

# ---------------------------------------------------------------------------
# Oracle HCM — direct API with required headers
# ---------------------------------------------------------------------------

async def scrape_oracle_hcm(url: str, company: str) -> list[ScrapedJob]:
    """
    Oracle HCM requires three special headers to return job data:
      - ora-irc-cx-userid: any random UUID
      - ora-irc-language: language code
      - content-type: application/json
    Without these the API returns empty results.
    """
    jobs = []
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Extract site ID from URL path e.g. /sites/CX_1/
        site_match = re.search(r'/sites/([^/]+)', parsed.path)
        site_id = site_match.group(1) if site_match else "CX_1"

        # Required headers — ora-irc-cx-userid must be a valid UUID
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "ora-irc-cx-userid": str(uuid.uuid4()),
            "ora-irc-language": "en",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }

        api_url = (
            f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true"
            f"&expand=requisitionList.secondaryLocations"
            f"&finder=findReqs;siteNumber={site_id},sortBy=POSTING_DATES_DESC"
            f"&limit=100&offset=0"
        )

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(api_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        req_list = []
        for item in data.get("items", []):
            req_list.extend(item.get("requisitionList", []))

        logger.info(f"Oracle HCM: raw response has {len(req_list)} requisitions")

        for req in req_list:
            title = req.get("requisitionTitle", "").strip()
            if not title:
                continue

            primary_loc = req.get("primaryLocation", "")
            secondary = req.get("secondaryLocations", [])
            all_locs = [primary_loc] + [
                l.get("locationName", "") for l in secondary if isinstance(l, dict)
            ]
            location = ", ".join(filter(None, all_locs)) or "Not specified"

            department = req.get("jobFamily", "") or req.get("jobFunction", "") or "General"

            job_type_raw = req.get("workHours", "").lower()
            if "part" in job_type_raw:
                job_type = "Part-time"
            elif "contract" in job_type_raw:
                job_type = "Contract"
            else:
                job_type = "Full-time"

            req_id = req.get("requisitionNumber", "")
            apply_url = (
                f"{base}/hcmUI/CandidateExperience/en/sites/{site_id}/job/{req_id}"
                if req_id else url
            )

            jobs.append(ScrapedJob(
                title=title, company=company, source_url=url,
                location=location, job_type=job_type,
                department=department, apply_url=apply_url,
            ))

        logger.info(f"Oracle HCM: found {len(jobs)} jobs at {company}")

    except Exception as e:
        logger.error(f"Oracle HCM scrape failed for {url}: {e}")

    return jobs


# ---------------------------------------------------------------------------
# Workday (REST API)
# ---------------------------------------------------------------------------

async def scrape_workday(url: str, company: str) -> list[ScrapedJob]:
    jobs = []
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        tenant = parsed.netloc.split(".")[0]
        path_parts = [p for p in parsed.path.strip("/").split("/") if p and p != "en-US"]
        board = path_parts[-1] if path_parts else "careers"

        api_url = f"{base}/wday/cxs/{tenant}/{board}/jobs"
        payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.post(api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        for item in data.get("jobPostings", []):
            title = item.get("title", "").strip()
            if not title:
                continue
            location = item.get("locationsText", "Not specified")
            external_path = item.get("externalPath", "")
            apply_url = f"{base}{external_path}" if external_path else url
            jobs.append(ScrapedJob(
                title=title, company=company, source_url=url,
                location=location, apply_url=apply_url,
            ))

        logger.info(f"Workday: found {len(jobs)} jobs at {company}")
    except Exception as e:
        logger.error(f"Workday scrape failed for {url}: {e}")
    return jobs


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

async def scrape_greenhouse(page: Page, url: str, company: str) -> list[ScrapedJob]:
    jobs = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        for section in soup.select(".opening"):
            title_el = section.select_one("a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            apply_url = f"https://boards.greenhouse.io{href}" if href.startswith("/") else href
            loc_el = section.select_one(".location")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            dept = "General"
            parent = section.find_parent("section")
            if parent:
                h2 = parent.select_one("h2, h3")
                if h2:
                    dept = h2.get_text(strip=True)
            jobs.append(ScrapedJob(title=title, company=company, source_url=url,
                                   location=location, department=dept, apply_url=apply_url))

        # Fetch descriptions for each job (cap at 10 to avoid timeout)
        for job in jobs[:10]:
            if job.apply_url:
                job.description = await fetch_job_description(page, job.apply_url)

    except Exception as e:
        logger.error(f"Greenhouse scrape failed for {url}: {e}")
    return jobs


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

async def scrape_lever(page: Page, url: str, company: str) -> list[ScrapedJob]:
    jobs = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=20000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        for posting in soup.select(".posting"):
            title_el = posting.select_one("h5")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link_el = posting.select_one("a.posting-btn-submit")
            apply_url = link_el["href"] if link_el else url
            loc_el = posting.select_one(".sort-by-location")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            dept_el = posting.select_one(".sort-by-team")
            dept = dept_el.get_text(strip=True) if dept_el else "General"
            jobs.append(ScrapedJob(title=title, company=company, source_url=url,
                                   location=location, department=dept, apply_url=apply_url))

        # Fetch descriptions for each job (cap at 10)
        for job in jobs[:10]:
            if job.apply_url:
                job.description = await fetch_job_description(page, job.apply_url)

    except Exception as e:
        logger.error(f"Lever scrape failed for {url}: {e}")
    return jobs


# ---------------------------------------------------------------------------
# Generic (fallback)
# ---------------------------------------------------------------------------

async def scrape_generic(page: Page, url: str, company: str) -> list[ScrapedJob]:
    jobs = []
    try:
        await page.goto(url, wait_until="networkidle", timeout=25000)
        await asyncio.sleep(2)
        soup = BeautifulSoup(await page.content(), "html.parser")

        job_selectors = ["li.job", ".job-listing", ".job-post", ".careers-item",
                         "[data-job]", ".position", ".vacancy", "article.job",
                         ".job-card", ".open-position"]
        found_els = []
        for sel in job_selectors:
            els = soup.select(sel)
            if els:
                found_els = els
                break

        if not found_els:
            keywords = ["engineer","developer","designer","manager","analyst",
                        "director","lead","specialist","coordinator","officer"]
            found_els = [a for a in soup.find_all("a", href=True)
                         if any(k in a.get_text(strip=True).lower() for k in keywords)
                         and 5 < len(a.get_text(strip=True)) < 100]

        for el in found_els[:50]:
            title = ""
            for tag in ["h1","h2","h3","h4"]:
                t = el.find(tag)
                if t:
                    title = t.get_text(strip=True)
                    break
            if not title:
                title = el.get_text(strip=True)[:80]
            if not title or len(title) < 4:
                continue

            link = el.find("a")
            apply_url = ""
            if link and link.get("href"):
                href = link["href"]
                apply_url = href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/")

            text = el.get_text(" ").lower()
            location = "Remote" if "remote" in text else "Hybrid" if "hybrid" in text else "Not specified"
            job_type = "Contract" if "contract" in text else "Part-time" if "part-time" in text else "Full-time"

            jobs.append(ScrapedJob(title=title, company=company, source_url=url,
                                   location=location, job_type=job_type,
                                   apply_url=apply_url or url))

        # Fetch descriptions for each job (cap at 10)
        for job in jobs[:10]:
            if job.apply_url and job.apply_url != url:
                job.description = await fetch_job_description(page, job.apply_url)

    except PlaywrightTimeout:
        logger.warning(f"Timeout scraping {url}")
    except Exception as e:
        logger.error(f"Generic scrape failed for {url}: {e}")
    return jobs


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def detect_ats(url: str) -> str:
    if "greenhouse.io" in url:
        return "greenhouse"
    if "lever.co" in url:
        return "lever"
    if "oraclecloud.com" in url or "fa.em" in url:
        return "oracle"
    if "myworkdayjobs.com" in url:
        return "workday"
    return "generic"


async def scrape_company(url: str, company: str) -> list[ScrapedJob]:
    ats = detect_ats(url)
    logger.info(f"Scraping {company} ({url}) via {ats} strategy")

    # Oracle and Workday use direct HTTP API calls — no browser needed
    if ats == "oracle":
        return await scrape_oracle_hcm(url, company)
    if ats == "workday":
        return await scrape_workday(url, company)

    # Browser-based scrapers
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        try:
            if ats == "greenhouse":
                jobs = await scrape_greenhouse(page, url, company)
            elif ats == "lever":
                jobs = await scrape_lever(page, url, company)
            else:
                jobs = await scrape_generic(page, url, company)
        finally:
            await browser.close()

    logger.info(f"  -> Found {len(jobs)} jobs at {company}")
    return jobs


async def scrape_all(companies: list[dict]) -> list[ScrapedJob]:
    semaphore = asyncio.Semaphore(3)

    async def guarded_scrape(c):
        async with semaphore:
            return await scrape_company(c["url"], c["name"])

    results = await asyncio.gather(
        *[guarded_scrape(c) for c in companies], return_exceptions=True
    )

    all_jobs = []
    for r in results:
        if isinstance(r, list):
            all_jobs.extend(r)
        else:
            logger.error(f"Scrape error: {r}")
    return all_jobs
