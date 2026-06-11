"""
Oracle Cloud HCM Careers Scraper
Based on: https://jobo.world/ats/oraclecloud

Uses Oracle's public REST API to extract job listings.
No Playwright needed — pure HTTP requests.

Key headers required:
  - ora-irc-cx-userid: any UUID
  - ora-irc-language: en
  - content-type: application/vnd.oracle.adf.resourceitem+json;charset=utf-8
"""

import re
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def html_to_readable(html_str: str) -> str:
    """
    Convert Oracle HTML job description to clean readable text.
    Preserves structure: **bold headings** and • bullet points.
    The JobCard renderer in App.jsx handles **text** → bold and • → bullets.
    """
    if not html_str or not html_str.strip():
        return ""

    import html as html_module

    # Decode HTML entities
    text = html_module.unescape(html_str)

    # Block-level elements → newlines
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</li>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li[^>]*>', '• ', text, flags=re.IGNORECASE)
    text = re.sub(r'</ul>|</ol>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<ul[^>]*>|<ol[^>]*>', '\n', text, flags=re.IGNORECASE)

    # Headings → **text**
    for tag in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        text = re.sub(f'<{tag}[^>]*>', '\n\n**', text, flags=re.IGNORECASE)
        text = re.sub(f'</{tag}>', '**\n', text, flags=re.IGNORECASE)

    # Bold/strong → **text**
    text = re.sub(r'<strong[^>]*>|<b[^>]*>', '**', text, flags=re.IGNORECASE)
    text = re.sub(r'</strong>|</b>', '**', text, flags=re.IGNORECASE)

    # Strip all remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Clean up lines
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        line = re.sub(r' {2,}', ' ', line)
        lines.append(line)

    # Collapse to max 1 consecutive blank line
    result = []
    blank_count = 0
    for line in lines:
        if line == '':
            blank_count += 1
            if blank_count <= 1:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    return '\n'.join(result).strip()


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _required_headers() -> dict:
    """Oracle HCM requires these exact headers on every request."""
    return {
        "ora-irc-cx-userid": str(uuid.uuid4()),
        "ora-irc-language": "en",
        "content-type": "application/vnd.oracle.adf.resourceitem+json;charset=utf-8",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }


def discover_site_number(careers_url: str, session: requests.Session) -> str:
    """
    Extract Oracle site number (e.g. CX_1, CX_45001) from careers page.
    Tries HTML, cookies, then URL path.
    """
    # Strategy 1: extract from URL path directly
    match = re.search(r"/sites/([^/?#]+)", careers_url)
    if match:
        site = match.group(1).rstrip("/")
        if site:
            logger.info(f"Site number from URL: {site}")
            return site

    # Strategy 2: fetch page and look in JS
    try:
        resp = session.get(careers_url, timeout=15, headers=_required_headers())
        html = resp.text

        match = re.search(r"siteNumber:\s*['\"]?(CX_\d+)['\"]?", html)
        if match:
            logger.info(f"Site number from JS: {match.group(1)}")
            return match.group(1)

        if "ORA_CX_SITE_NUMBER" in resp.cookies:
            site = resp.cookies["ORA_CX_SITE_NUMBER"]
            logger.info(f"Site number from cookie: {site}")
            return site
    except Exception as e:
        logger.warning(f"Could not fetch careers page: {e}")

    raise ValueError(f"Could not discover Oracle site number from {careers_url}")


def _try_fetch_page(
    url: str,
    site_number: str,
    offset: int,
    limit: int,
    session: requests.Session,
) -> dict:
    """
    Try multiple Oracle API parameter formats.
    Different Oracle tenants use different finder syntax.
    Returns raw API response dict or raises on all failures.
    """
    # Format variations to try in order
    formats = [
        # Format A: raw semicolon in finder (most common)
        lambda: session.get(
            url,
            params={
                "onlyData": "true",
                "expand": "requisitionList.workLocation,requisitionList.secondaryLocations",
                "finder": f"findReqs;siteNumber={site_number}",
                "limit": limit,
                "offset": offset,
            },
            headers=_required_headers(),
            timeout=20,
        ),
        # Format B: limit/offset inside finder
        lambda: session.get(
            url,
            params={
                "onlyData": "true",
                "finder": f"findReqs;siteNumber={site_number},limit={limit},offset={offset}",
            },
            headers=_required_headers(),
            timeout=20,
        ),
        # Format C: minimal params
        lambda: session.get(
            url,
            params={
                "onlyData": "true",
                "siteNumber": site_number,
                "limit": limit,
                "offset": offset,
            },
            headers=_required_headers(),
            timeout=20,
        ),
        # Format D: full facets list
        lambda: session.get(
            url,
            params={
                "onlyData": "true",
                "expand": "requisitionList.workLocation,requisitionList.otherWorkLocations,requisitionList.secondaryLocations",
                "finder": f"findReqs;siteNumber={site_number},sortBy=POSTING_DATES_DESC",
                "facetsList": "LOCATIONS;WORK_LOCATIONS;WORKPLACE_TYPES;TITLES;CATEGORIES;ORGANIZATIONS;POSTING_DATES;FLEX_FIELDS",
                "limit": limit,
                "offset": offset,
            },
            headers=_required_headers(),
            timeout=20,
        ),
    ]

    last_error = None
    for i, make_request in enumerate(formats):
        try:
            resp = make_request()
            logger.debug(f"Oracle format {i+1}: status {resp.status_code}")
            if resp.status_code == 200:
                logger.info(f"Oracle format {i+1} succeeded")
                return resp.json()
            elif resp.status_code in (400, 422):
                last_error = f"{resp.status_code}: {resp.text[:200]}"
                logger.debug(f"Oracle format {i+1} failed: {last_error}")
                continue
            else:
                resp.raise_for_status()
        except Exception as e:
            last_error = str(e)
            logger.debug(f"Oracle format {i+1} exception: {e}")
            continue

    raise Exception(f"All Oracle API formats failed. Last error: {last_error}")


def fetch_all_jobs(
    domain: str,
    site_number: str,
    session: requests.Session,
    limit: int = 25,
) -> list[dict]:
    """Paginate through all job requisitions, trying multiple API formats."""
    url = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    all_jobs = []
    offset = 0
    total = None

    while True:
        try:
            data = _try_fetch_page(url, site_number, offset, limit, session)
        except Exception as e:
            logger.error(f"Oracle API request failed at offset {offset}: {e}")
            break

        items = data.get("items", [])
        if not items:
            logger.info(f"Oracle: no items in response at offset {offset}")
            break

        page_jobs = []
        for item in items:
            jobs_in_item = item.get("requisitionList", [])
            page_jobs.extend(jobs_in_item)
            if total is None:
                total = item.get("TotalJobsCount", item.get("totalResults", 0))

        all_jobs.extend(page_jobs)
        logger.info(f"Oracle: fetched {len(all_jobs)} / {total or '?'} jobs")

        has_more = data.get("hasMore", False)
        if not has_more or len(page_jobs) == 0:
            break

        offset += limit
        time.sleep(0.5)

    return all_jobs


def fetch_job_detail(
    domain: str,
    site_number: str,
    job_id: str,
    session: requests.Session,
) -> Optional[dict]:
    """Fetch full job description using job ID. Retries once on timeout."""
    url = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"

    # Try two finder formats
    finder_formats = [
        f'ById;Id="{job_id}",siteNumber={site_number}',
        f"ById;Id={job_id},siteNumber={site_number}",
    ]

    for finder in finder_formats:
        params = {
            "expand": "all",
            "onlyData": "true",
            "finder": finder,
        }
        for attempt in range(2):  # retry once on timeout
            try:
                resp = session.get(url, params=params, headers=_required_headers(), timeout=45)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    return items[0] if items else None
                elif resp.status_code == 400:
                    break  # try next finder format
                else:
                    resp.raise_for_status()
            except requests.exceptions.Timeout:
                if attempt == 0:
                    logger.warning(f"Detail timeout for job {job_id}, retrying...")
                    time.sleep(2)
                    continue
                logger.warning(f"Detail fetch timed out for job {job_id} after retry, skipping")
                return None
            except Exception as e:
                logger.warning(f"Could not fetch detail for job {job_id}: {e}")
                return None
    return None


def normalize_job(
    raw: dict,
    detail: Optional[dict],
    company_name: str,
    source_url: str,
    domain: str,
    site_number: str,
) -> dict:
    """Convert Oracle API response to normalized job dict."""
    job_id = str(raw.get("Id") or raw.get("id") or "")
    req_number = str(
        raw.get("RequisitionNumber")
        or raw.get("requisitionNumber")
        or job_id
    )

    title = (
        raw.get("Title")
        or raw.get("title")
        or (detail or {}).get("Title")
        or "Untitled Position"
    )

    location = (
        raw.get("PrimaryLocation")
        or raw.get("primaryLocation")
        or raw.get("Location")
        or (detail or {}).get("PrimaryLocation")
        or "Not specified"
    )
    if isinstance(location, list):
        location = ", ".join(location)

    # Job type
    raw_type = (raw.get("WorkerType") or raw.get("workerType") or "").upper()
    type_map = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACT": "Contract",
        "TEMPORARY": "Contract",
        "INTERN": "Internship",
    }
    job_type = type_map.get(raw_type, "Full-time")

    # Description — prefer full detail page
    raw_html = ""
    if detail:
        raw_html = (
            detail.get("ExternalDescriptionStr", "")
            or detail.get("ExternalDescription", "")
            or detail.get("ShortDescriptionStr", "")
            or detail.get("ShortDescription", "")
        )
    if not raw_html:
        raw_html = (
            raw.get("ShortDescriptionStr", "")
            or raw.get("ShortDescription", "")
        )

    description = html_to_readable(raw_html)

    # Department/category
    department = (
        raw.get("CategoryLabel")
        or raw.get("PrimaryJobCategory")
        or (detail or {}).get("PrimaryJobCategory")
        or "General"
    )

    # Apply URL — deep link to specific job
    apply_url = (
        f"https://{domain}/hcmUI/CandidateExperience/en/sites/{site_number}/job/{req_number}"
        if req_number else source_url
    )

    return {
        "title": title,
        "company": company_name,
        "source_url": source_url,
        "location": location,
        "job_type": job_type,
        "department": department,
        "description": description,
        "apply_url": apply_url,
        "salary": "",
    }


class OracleCloudScraper:
    """
    End-to-end Oracle HCM scraper.
    Automatically discovers site number, paginates, and normalizes jobs.

    Args:
        careers_url:   Public Oracle HCM careers page URL
        company_name:  Company name to tag jobs with
        fetch_details: Fetch full descriptions (slower but richer). Default True.
    """

    def __init__(
        self,
        careers_url: str,
        company_name: str = "Unknown",
        fetch_details: bool = True,
    ):
        self.careers_url = careers_url
        self.company_name = company_name
        self.fetch_details = fetch_details
        self._session = _build_session()

    def run(self) -> list[dict]:
        logger.info(f"Oracle HCM scrape: {self.careers_url}")

        # Discover site config
        parsed = urlparse(self.careers_url)
        domain = parsed.netloc
        site_number = discover_site_number(self.careers_url, self._session)
        logger.info(f"Domain: {domain} | Site: {site_number}")

        # Fetch all raw jobs
        raw_jobs = fetch_all_jobs(domain, site_number, self._session)
        logger.info(f"Raw jobs: {len(raw_jobs)}")

        # Normalize
        normalized = []
        for i, raw in enumerate(raw_jobs):
            job_id = str(raw.get("Id") or raw.get("id") or "")

            detail = None
            if self.fetch_details and job_id:
                detail = fetch_job_detail(domain, site_number, job_id, self._session)
                # Small pause to avoid rate limiting
                time.sleep(0.5)

            job = normalize_job(
                raw=raw,
                detail=detail,
                company_name=self.company_name,
                source_url=self.careers_url,
                domain=domain,
                site_number=site_number,
            )
            normalized.append(job)

            desc_len = len(job.get("description", ""))
            logger.debug(f"Job {i+1}/{len(raw_jobs)}: {job.get('title','?')[:40]} — {desc_len} chars desc")

            if (i + 1) % 10 == 0:
                logger.info(f"Processed {i+1}/{len(raw_jobs)} jobs")

        logger.info(f"Oracle complete: {len(normalized)} jobs for {self.company_name}")
        return normalized


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch"
    )
    company = sys.argv[2] if len(sys.argv) > 2 else "Test Company"

    scraper = OracleCloudScraper(careers_url=url, company_name=company, fetch_details=False)
    jobs = scraper.run()
    print(json.dumps(jobs[:3], indent=2, default=str))
    print(f"\nTotal: {len(jobs)} jobs")
