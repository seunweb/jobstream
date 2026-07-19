"""
JobStream Scraper Engine
Supports Greenhouse, Lever, Oracle HCM, Workday, and generic career pages.
"""

import asyncio
import hashlib
import httpx
import logging
import re
from typing import Optional
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

# Workday
# ---------------------------------------------------------------------------
# Uses the CXS (Candidate Experience Service) JSON API — no browser needed.
# POST /wday/cxs/{tenant}/{site}/jobs for listings
# GET  /wday/cxs/{tenant}/{site}/jobs/{externalPath} for description
#
# URL format:  https://{tenant}.{wd_server}.myworkdayjobs.com/en-US/{site}/jobs
# OR:          https://{tenant}.{wd_server}.myworkdayjobs.com/{site}
# Examples:    https://airtel.wd3.myworkdayjobs.com/Airtel_Nigeria
#              https://kainos.wd3.myworkdayjobs.com/Careers

def _parse_workday_url(url: str) -> dict:
    """
    Parse a Workday career page URL into its components.
    Returns: {tenant, wd_server, site, base_url, api_base}
    """
    from urllib.parse import urlparse as _up
    p = _up(url)
    host_parts = p.netloc.split('.')
    tenant    = host_parts[0]
    wd_server = host_parts[1] if len(host_parts) > 1 else 'wd3'
    # Site is the first meaningful path segment (skip en-US, jobs, etc.)
    path_parts = [x for x in p.path.strip('/').split('/') if x and x not in ('en-US', 'jobs', 'en-GB', 'fr-FR')]
    site = path_parts[0] if path_parts else tenant
    base_url  = f"{p.scheme}://{p.netloc}"
    api_base  = f"{base_url}/wday/cxs/{tenant}/{site}"
    return {"tenant": tenant, "wd_server": wd_server, "site": site, "base_url": base_url, "api_base": api_base}


async def _workday_fetch_listings(client, api_base: str, referer: str, limit: int = 20, offset: int = 0) -> dict:
    """POST to Workday CXS jobs endpoint — returns paginated listing."""
    url = f"{api_base}/jobs"
    headers = {
        "Accept":           "application/json",
        "Content-Type":     "application/json",
        "Accept-Language":  "en-US",
        "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer":          referer,
        "Origin":           referer.split('/en-US')[0].split('/wday')[0],
    }
    payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
    resp = await client.post(url, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.json()


async def _workday_fetch_detail(
    client,
    api_base: str,
    external_path: str,
    referer: str,
    base_url: str = "",
) -> dict:
    """
    GET individual Workday job detail.

    Correct URL pattern per Workday CXS API docs:
      https://{tenant}.{wd_server}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{externalPath}

    The externalPath from the listing response is the full path including
    locale and site, e.g. /en-US/Airtel_Nigeria/job/Lagos/Engineer_JR-001
    We use it as-is — the CXS endpoint handles the path segments.

    Returns keys: title, location, additionalLocations, timeType, jobReqId,
                  startDate, jobDescription (HTML string), jobPostingDescription
    """
    # Build detail URL
    # externalPath from listing can be in two formats:
    #   Format A (locale prefix): /en-US/ShellCareers/job/London/Engineer_R123
    #   Format B (job prefix):    /job/London/Engineer_R123
    #   Format C (slug only):     /London/Engineer_R123
    #
    # Correct CXS detail URL: {api_base}/job/{location}/{slug}
    # api_base already ends with /wday/cxs/{tenant}/{site}
    # So we must NOT prepend /job/ if externalPath already contains /job/

    import re as _re

    path = external_path.strip('/')

    # Strip locale prefix like en-US/SiteName/ if present
    path = _re.sub(r'^[a-z]{2}-[A-Z]{2}/[^/]+/', '', path)

    # Now path is either:
    #   job/London/Engineer_R123   (already has /job/)
    #   London/Engineer_R123       (no /job/ prefix)
    if path.startswith('job/'):
        url = f"{api_base}/{path}"
    else:
        url = f"{api_base}/job/{path}"

    # Workday detail endpoint requires these exact headers
    # 406 Not Acceptable means Accept header is wrong
    # Try multiple header combinations — Workday instances vary in what they accept
    header_variants = [
        # Variant 1: clean JSON headers (no Content-Type on GET)
        {
            "Accept":          "application/json",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer":         referer,
        },
        # Variant 2: with X-Workday-Client
        {
            "Accept":           "application/json",
            "Accept-Language":  "en-US,en;q=0.9",
            "User-Agent":       "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer":          referer,
            "X-Workday-Client": "WD-careers",
        },
        # Variant 3: with Content-Type
        {
            "Accept":        "application/json",
            "Content-Type":  "application/json",
            "User-Agent":    "Mozilla/5.0",
            "Referer":       referer,
        },
    ]

    try:
        for headers in header_variants:
            resp = await client.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    # Shell (and many Workday tenants) nest everything under
                    # 'jobPostingInfo' — unwrap it so parsers get a flat dict
                    if isinstance(data, dict) and 'jobPostingInfo' in data:
                        posting_info = data['jobPostingInfo'] or {}
                        # Merge top-level keys into posting_info so we keep
                        # hiringOrganization etc. too
                        merged = dict(posting_info)
                        for k, v in data.items():
                            if k != 'jobPostingInfo':
                                merged.setdefault(k, v)
                        return merged
                    return data
                except Exception:
                    pass  # not JSON, try next variant
            if resp.status_code not in (406, 415, 400):
                # Only retry on header-related errors
                break
        logger.debug(f"Workday detail: all header variants failed for {url}, last status={resp.status_code}")

        if resp.status_code == 404:
            # Try stripping down to just the slug portion after /job/
            m = _re.search(r'/job/(.+)$', path)
            if m:
                alt_url = f"{api_base}/job/{m.group(1)}"
                alt = await client.get(alt_url, headers=headers, timeout=12)
                if alt.status_code == 200:
                    return alt.json()

        logger.debug(f"Workday detail {resp.status_code} for {url}")
        return {}
    except Exception as e:
        logger.debug(f"Workday detail error for {url}: {e}")
        return {}


def _parse_workday_job(posting: dict, company: str, source_url: str, detail: dict = None) -> "ScrapedJob | None":
    """
    Parse a Workday job posting + detail into a ScrapedJob.

    posting fields (from listing):
      title, locationsText, postedOn, externalPath, bulletFields, category

    detail fields (from /job/{path}):
      title, location, additionalLocations, timeType, jobReqId,
      startDate, jobDescription (HTML string), jobPostingDescription
    """
    import html as _h
    detail = detail or {}

    # Title — prefer detail (more complete), fall back to listing
    title = (detail.get('title') or posting.get('title') or '').strip()
    if not title:
        return None

    # External path for apply URL
    ext_path = posting.get('externalPath', '') or ''

    # Apply URL — build from source_url base + externalPath
    from urllib.parse import urlparse as _up
    parsed = _up(source_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    apply_url = f"{base}{ext_path}" if ext_path else source_url

    # ── Location ──────────────────────────────────────────────────────────────
    # Primary location from detail
    loc_from_detail = ''
    # Location may be at top level or inside jobPostingInfo (Shell pattern)
    _loc_source = detail.get('location') or detail.get('primaryLocation') or {}
    if _loc_source:
        loc_from_detail = _loc_source.get('descriptor', '') if isinstance(_loc_source, dict) else str(_loc_source)

    # Additional locations from detail
    add_locs = []
    for al in (detail.get('additionalLocations') or []):
        name = al.get('descriptor', '') if isinstance(al, dict) else str(al)
        if name:
            add_locs.append(name)

    # Fall back to listing locationsText
    loc_from_listing = posting.get('locationsText', '') or ''
    if not loc_from_listing:
        loc_list = posting.get('locations') or []
        loc_from_listing = '; '.join(
            l.get('descriptor', '') for l in loc_list
            if isinstance(l, dict) and l.get('descriptor')
        )

    # Combine: primary + additional + listing
    all_locs = [l for l in [loc_from_detail] + add_locs if l]
    if not all_locs and loc_from_listing:
        all_locs = parse_locations(loc_from_listing)
    location = '; '.join(all_locs) if all_locs else 'Remote'

    # ── Job type ──────────────────────────────────────────────────────────────
    job_type = _infer_job_type(title)
    # timeType from detail: "Full_time", "Part_time", "Temporary"
    time_type = detail.get('timeType', '') or ''
    if time_type:
        tt = time_type.lower().replace('_', ' ')
        if 'part' in tt:      job_type = 'Part-time'
        elif 'full' in tt:    job_type = 'Full-time'
        elif 'temp' in tt:    job_type = 'Temporary'
        elif 'intern' in tt:  job_type = 'Internship'
    # Also check job category
    cat = detail.get('jobCategory') or posting.get('category') or {}
    if isinstance(cat, dict) and cat.get('descriptor'):
        job_type = _infer_job_type(cat['descriptor']) or job_type

    # ── Department ────────────────────────────────────────────────────────────
    dept_obj = detail.get('jobFamily') or posting.get('category') or {}
    dept = dept_obj.get('descriptor', 'General') if isinstance(dept_obj, dict) else 'General'

    # ── Description ───────────────────────────────────────────────────────────
    # Workday uses different field names across tenants. Try all known variants.
    description = ''
    raw_desc = ''

    # All known Workday description field names (vary by tenant/version):
    for field in [
        'jobDescription',            # most common — plain HTML string
        'jobPostingDescription',     # alternate name
        'description',               # simplified tenants
        'jobSummary',                # some Oracle-integrated Workday instances
    ]:
        val = detail.get(field, '')
        if not val:
            continue
        # Value may be a plain string or a dict with a 'content' key
        if isinstance(val, dict):
            val = (val.get('content') or val.get('description')
                   or val.get('text') or val.get('value') or '')
        if val and str(val).strip():
            raw_desc = str(val)
            break

    # Also check inside nested 'jobPostingInfo' block (Shell and many Workday tenants)
    # This is the most common nesting pattern — jobPostingInfo.jobDescription
    if not raw_desc:
        for info_key in ('jobPostingInfo', 'postingInfo', 'jobPosting'):
            info_block = detail.get(info_key) or {}
            if not isinstance(info_block, dict):
                continue
            candidate = (info_block.get('jobDescription') or
                         info_block.get('description') or
                         info_block.get('jobSummary') or '')
            if isinstance(candidate, dict):
                candidate = (candidate.get('content') or
                             candidate.get('text') or '')
            if candidate and str(candidate).strip():
                raw_desc = str(candidate)
                break

    if raw_desc:
        description = _clean_html(_h.unescape(str(raw_desc)))

    # ── Salary ────────────────────────────────────────────────────────────────
    salary = ''
    comp = detail.get('compensation') or detail.get('salaryRange') or {}
    if isinstance(comp, dict):
        mn = comp.get('minimum') or comp.get('min')
        mx = comp.get('maximum') or comp.get('max')
        cur = comp.get('currency', 'USD')
        period = comp.get('period', '') or comp.get('frequency', '')
        if mn and mx:
            salary = f"{cur} {int(float(mn)):,} – {int(float(mx)):,}"
            if period: salary += f" / {period.lower()}"
        elif mn:
            salary = f"{cur} {int(float(mn)):,}+"

    # ── Extra metadata in description prefix ──────────────────────────────────
    meta_parts = []
    req_id = detail.get('jobReqId') or (posting.get('bulletFields') or [''])[0]
    if req_id:       meta_parts.append(f"Req ID: {req_id}")
    if time_type:    meta_parts.append(f"Time type: {time_type.replace('_',' ')}")
    start = detail.get('startDate', '')
    if start:        meta_parts.append(f"Start date: {start}")
    if meta_parts and description:
        description = "\n".join(meta_parts) + "\n\n" + description
    elif meta_parts:
        description = "\n".join(meta_parts)
    return ScrapedJob(
        title=title,
        company=company,
        source_url=source_url,
        location=location,
        department=dept,
        job_type=job_type,
        description=description,
        apply_url=apply_url,
        salary=salary,
    )


async def scrape_workday(url: str, company: str, page: "Page | None" = None) -> list[ScrapedJob]:
    """
    Scrape Workday jobs via the CXS JSON API (no browser/Playwright needed).

    Strategy:
    1. POST /wday/cxs/{tenant}/{site}/jobs — paginated listings
    2. GET  /wday/cxs/{tenant}/{site}/jobs/{externalPath} — per-job description
    3. HTML fallback via Playwright if API fails

    The listing response does NOT include job descriptions.
    Descriptions require a per-job GET request to the detail endpoint.
    Capped at 50 detail requests per scrape run (rate limiting).
    """
    jobs = []
    info = _parse_workday_url(url)
    tenant   = info['tenant']
    site     = info['site']
    api_base = info['api_base']
    base_url = info['base_url']
    referer  = f"{base_url}/en-US/{site}/jobs"

    logger.info(f"Workday CXS API: tenant={tenant}, site={site}, api={api_base}")

    # ── Strategy 1: CXS JSON API ─────────────────────────────────────────────
    try:
        all_postings = []
        offset = 0
        limit  = 20
        total  = None

        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            while True:
                data = await _workday_fetch_listings(client, api_base, referer, limit=limit, offset=offset)
                postings = data.get('jobPostings', [])
                if total is None:
                    total = data.get('total', 0)
                    logger.info(f"Workday: {total} total jobs for {tenant}/{site}")
                if not postings:
                    break
                all_postings.extend(postings)
                offset += len(postings)
                if offset >= total or offset >= 200:  # cap at 200 jobs
                    break
                await asyncio.sleep(0.3)

        if not all_postings:
            logger.warning(f"Workday: no listings returned for {tenant}/{site}")
        else:
            # Fetch descriptions for each job (cap at 50)
            logger.info(f"Workday: fetching descriptions for {min(len(all_postings), 50)} jobs")
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                for posting in all_postings[:50]:
                    ext_path = posting.get('externalPath', '')
                    detail   = {}
                    if ext_path:
                        try:
                            detail = await _workday_fetch_detail(client, api_base, ext_path, referer)
                        except Exception as e:
                            logger.debug(f"Workday detail failed for {ext_path}: {e}")
                    parsed = _parse_workday_job(posting, company, url, detail)
                    if parsed:
                        jobs.append(parsed)
                    await asyncio.sleep(0.2)

            # Jobs beyond cap 50 — add without description
            for posting in all_postings[50:]:
                parsed = _parse_workday_job(posting, company, url, {})
                if parsed:
                    jobs.append(parsed)

            logger.info(f"Workday CXS API: {len(jobs)} jobs from {tenant}/{site}")
            return jobs

    except Exception as e:
        logger.warning(f"Workday CXS API failed for {url}: {e}")

    # ── Strategy 2: HTML fallback via Playwright ──────────────────────────────
    if page is None:
        logger.warning(f"Workday: CXS API failed and no Playwright page available for {url}")
        return jobs
    try:
        logger.info(f"Workday: falling back to Playwright for {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await asyncio.sleep(2)
        soup = BeautifulSoup(await page.content(), "html.parser")
        for item in soup.select('[data-automation-id="jobTitle"], .css-19uc56f, .gwt-Label'):
            title = item.get_text(strip=True)
            if not title or len(title) < 3:
                continue
            parent = item.find_parent('li') or item.find_parent('article') or item.find_parent('div')
            loc_el = parent.select_one('[data-automation-id="jobLocation"], .css-bmklzm') if parent else None
            location = loc_el.get_text(strip=True) if loc_el else 'Remote'
            link_el = parent.select_one('a[href]') if parent else item.find_parent('a')
            apply_url = base_url + link_el['href'] if link_el and link_el.get('href', '').startswith('/') else (link_el['href'] if link_el else url)
            jobs.append(ScrapedJob(
                title=title, company=company, source_url=url,
                location=location, department='General',
                job_type=_infer_job_type(title), apply_url=apply_url,
            ))
        logger.info(f"Workday HTML fallback: {len(jobs)} jobs from {url}")
    except Exception as e:
        logger.error(f"Workday HTML fallback failed for {url}: {e}")

    return jobs


# ── User-agent rotation ───────────────────────────────────────────────────────
_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ── Cache (24h TTL) ───────────────────────────────────────────────────────────
import time as _time
_GH_CACHE: dict = {}
CACHE_TTL = 60 * 60 * 24

def _cache_get(token: str):
    e = _GH_CACHE.get(token)
    if e and (_time.time() - e[0]) < CACHE_TTL:
        logger.info(f"Greenhouse cache HIT for {token} ({(_time.time()-e[0])/3600:.1f}h old, {len(e[1])} jobs)")
        return e[1]
    return None

def _cache_set(token: str, jobs: list):
    _GH_CACHE[token] = (_time.time(), jobs)
    logger.info(f"Greenhouse cache SET for {token}: {len(jobs)} jobs")

def _cache_invalidate(token: str):
    _GH_CACHE.pop(token, None)

# ── Helpers ───────────────────────────────────────────────────────────────────
def _extract_greenhouse_token(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).path.strip("/").split("/")[0]

def _greenhouse_base_url(url: str):
    host = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url).netloc.lower()
    eu = ".eu." in host
    return (
        "https://boards-api.eu.greenhouse.io"  if eu else "https://boards-api.greenhouse.io",
        "https://boards.eu.greenhouse.io"       if eu else "https://boards.greenhouse.io",
        "https://job-boards.eu.greenhouse.io"   if eu else "https://job-boards.greenhouse.io",
    )

def _infer_job_type(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("part-time", "part time")): return "Part-time"
    if any(k in t for k in ("contract", "freelance")): return "Contract"
    if any(k in t for k in ("intern", "internship")): return "Internship"
    return "Full-time"

def _clean_html(html_str: str, max_chars: int = 8000) -> str:
    """
    Convert job description HTML to structured, readable plain text.

    Handles the Shell/Workday pattern where metadata labels are <p><b>Label:</b></p>
    followed by the value as a bare text node or next <p>, and body text uses
    <p>, <ul>/<li>, and <h*> tags.
    """
    import html as _h
    from bs4 import NavigableString
    if not html_str:
        return ""
    decoded = _h.unescape(html_str)
    soup = BeautifulSoup(decoded, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    def node_text(node):
        return node.get_text(separator=" ", strip=True) if hasattr(node, "get_text") else str(node).strip()

    def is_label_p(p):
        """<p> whose only non-whitespace child is a <b> or <strong> = a label."""
        kids = [c for c in p.children
                if not (isinstance(c, NavigableString) and not c.strip())]
        return (len(kids) == 1
                and hasattr(kids[0], "name")
                and kids[0].name in ("b", "strong"))

    # ── Tokenise the DOM into typed tokens ────────────────────────────────────
    tokens = []

    def walk(node):
        if isinstance(node, NavigableString):
            t = str(node).replace("\xa0", " ").strip()
            if t:
                tokens.append(("text", t))
            return
        if not hasattr(node, "name") or not node.name:
            return
        tag = node.name.lower()

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            t = node_text(node)
            if t:
                tokens.append(("heading", t))

        elif tag == "p":
            if is_label_p(node):
                tokens.append(("label", node_text(node).rstrip(": ")))
            else:
                t = node_text(node).replace("\xa0", "").strip()
                if t:
                    tokens.append(("para", t))

        elif tag in ("ul", "ol"):
            items = [node_text(li)
                     for li in node.find_all("li", recursive=False)
                     if node_text(li)]
            if items:
                tokens.append(("list", items, tag))

        elif tag in ("strong", "b"):
            t = node_text(node)
            if t:
                tokens.append(("bold", t))

        elif tag == "br":
            pass  # ignore bare <br>

        else:  # div, span, section, body, html …
            for child in node.children:
                walk(child)

    for child in soup.children:
        walk(child)

    # ── Render tokens → lines ─────────────────────────────────────────────────
    out = []
    i = 0
    while i < len(tokens):
        kind = tokens[i][0]

        if kind == "heading":
            label = tokens[i][1]
            out += ["", label.upper(), "-" * min(len(label), 50)]

        elif kind == "label":
            label = tokens[i][1].rstrip(":")
            # Consume next token if it's the inline value
            if i + 1 < len(tokens) and tokens[i + 1][0] in ("text", "para"):
                out.append(f"\n{label}: {tokens[i + 1][1]}")
                i += 1
            elif i + 1 < len(tokens) and tokens[i + 1][0] == "list":
                out.append(f"\n{label}:")
                for item in tokens[i + 1][1]:
                    out.append(f"  • {item}")
                i += 1
            else:
                out.append(f"\n{label}:")

        elif kind == "bold":
            t = tokens[i][1].rstrip(":")
            out.append(f"\n{t}:")

        elif kind == "para":
            out += ["", tokens[i][1]]

        elif kind == "text":
            out.append(tokens[i][1])

        elif kind == "list":
            out.append("")
            for item in tokens[i][1]:
                out.append(f"  • {item}")

        i += 1

    text = "\n".join(out)
    # Collapse 3+ blank lines to 2
    import re as _re
    text = _re.sub(r"\n{3,}", "\n\n", text).strip()

    # ── Convert to frontend markdown-like format ───────────────────────────
    # The job detail renderer understands:
    #   **TEXT**  → bold section heading
    #   - item    → bullet point
    # Convert our plain-text tokens to this format:
    output_lines = []
    for line in text.splitlines():
        # All-caps lines or "Label:" lines → **heading**
        stripped = line.strip()
        if _re.match(r'^[A-Z][A-Z\s\&\/\-]{3,}:?\s*$', stripped) and len(stripped) < 60:
            output_lines.append(f"**{stripped.rstrip(':')}**")
        # "Label: value" metadata lines → bold label + value
        elif _re.match(r'^[A-Z][^\n]{2,40}:\s+\S', stripped) and len(stripped) < 80:
            output_lines.append(f"**{stripped}**")
        # Bullet points (  • item or  - item)
        elif stripped.startswith("•"):
            output_lines.append(f"- {stripped[1:].strip()}")
        # Dashes that are section dividers → skip
        elif _re.match(r'^-{3,}$', stripped):
            output_lines.append("")
        else:
            output_lines.append(line)

    final = "\n".join(output_lines)
    final = _re.sub(r"\n{3,}", "\n\n", final).strip()
    return final[:max_chars]

def parse_locations(location_str: str) -> list:
    if not location_str: return []
    return [l.strip() for l in location_str.split(";") if l.strip()]

def _parse_greenhouse_job(job: dict, token: str, company: str, source_url: str):
    import html as _h
    title = (job.get("title") or "").strip()
    if not title: return None
    job_id = job.get("id", "")
    loc = job.get("location") or {}
    raw_location = loc.get("name") or loc.get("city") or "" if isinstance(loc, dict) else str(loc or "")
    if not raw_location:
        offices = job.get("offices") or []
        raw_location = "; ".join(o.get("name","") for o in offices if isinstance(o,dict) and o.get("name"))
    if not raw_location:
        raw_location = job.get("job_post_location") or ""
    locations = parse_locations(raw_location) or ["Remote"]
    location = locations[0]
    all_locations = "; ".join(locations)
    depts = job.get("departments") or job.get("department") or []
    if isinstance(depts, list) and depts:
        dept = depts[0].get("name","General") if isinstance(depts[0], dict) else str(depts[0])
    elif isinstance(depts, str):
        dept = depts
    else:
        dept = "General"
    host = source_url.split("/")[2] if source_url.startswith("http") else ""
    rmx = "https://job-boards.eu.greenhouse.io" if ".eu." in host else "https://job-boards.greenhouse.io"
    apply_url = job.get("absolute_url") or job.get("url") or (f"{rmx}/{token}/jobs/{job_id}" if job_id else "")
    raw_desc = _h.unescape(job.get("content") or job.get("description") or "")
    description = _clean_html(raw_desc)
    salary = ""
    pay_ranges = job.get("pay_ranges") or []
    if pay_ranges:
        parts = []
        for pr in pay_ranges:
            mn, mx, cur = pr.get("min"), pr.get("max"), pr.get("currency","USD")
            if mn and mx: parts.append(f"{cur} {int(mn):,} – {int(mx):,}")
            elif mn: parts.append(f"{cur} {int(mn):,}+")
        salary = " | ".join(parts)
    if not salary:
        pay = job.get("pay_range") or job.get("salary_range") or {}
        if isinstance(pay, dict):
            mn = pay.get("min_amount") or pay.get("min")
            mx = pay.get("max_amount") or pay.get("max")
            cur = pay.get("currency_type") or pay.get("currency","USD")
            if mn and mx: salary = f"{cur} {int(mn):,} – {int(mx):,}"
            elif mn: salary = f"{cur} {int(mn):,}+"
    job_type = _infer_job_type(title)
    emp = job.get("employment_type") or (job.get("employment") or {}).get("name","")
    if emp:
        el = emp.lower()
        if "part" in el: job_type = "Part-time"
        elif "contract" in el: job_type = "Contract"
        elif "intern" in el: job_type = "Internship"
    if len(locations) > 1:
        description = f"Locations: {all_locations}\n\n" + description if description else f"Locations: {all_locations}"
    return ScrapedJob(
        title=title, company=company, source_url=source_url,
        location=all_locations, department=dept, job_type=job_type,
        description=description, apply_url=apply_url, salary=salary,
    )

async def _gh_get(client, url: str, retries: int = 3):
    """GET with proxy routing + exponential backoff."""
    proxied = url
    delay = 0.3
    last_exc = None
    for attempt in range(retries):
        try:
            resp = await client.get(proxied, headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "User-Agent": _UA_LIST[attempt % len(_UA_LIST)],
                "Referer": url.split("?")[0],
            }, timeout=30)
            if resp.status_code == 403:
                logger.warning(f"Greenhouse 403 on {url}, attempt {attempt+1} — may be IP-based blocking")
                await asyncio.sleep(delay * (2 ** attempt)); continue
            if resp.status_code == 429:
                await asyncio.sleep(delay * (2 ** attempt)); continue
            if resp.status_code >= 500:
                await asyncio.sleep(delay * (2 ** attempt)); continue
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e; await asyncio.sleep(delay * (2 ** attempt))
    raise httpx.HTTPError(f"Greenhouse: {retries} retries failed for {url}") from last_exc

async def _gh_job_detail(client, token: str, job_id: int, api_base: str, remix_base: str) -> dict:
    """
    Fetch individual job detail — the ONLY way to get description text.
    Greenhouse listing endpoints never include descriptions.
    """
    # Strategy A: Remix detail endpoint
    try:
        url = f"{remix_base}/{token}/jobs/{job_id}?_data="
        resp = await _gh_get(client, url)
        if resp.status_code == 200:
            data = resp.json()
            jp = data.get("jobPost") or {}
            import html as _h
            raw = _h.unescape(jp.get("content") or data.get("content") or "")
            desc = _clean_html(raw)
            pay_ranges = [
                {"min": pr.get("min"), "max": pr.get("max"), "currency": pr.get("currency","USD"), "title": pr.get("title","")}
                for pr in (data.get("pay_ranges") or []) if pr.get("min") or pr.get("max")
            ]
            emp = data.get("employment") or {}
            loc = data.get("job_post_location") or (jp.get("location") or {}).get("name") or ""
            depts = data.get("departments") or []
            dept = depts[0].get("name","") if depts and isinstance(depts[0], dict) else ""
            logger.debug(f"GH detail OK [{job_id}]: {len(desc)} chars")
            return {"description": desc, "pay_ranges": pay_ranges,
                    "employment_type": emp.get("name","") if isinstance(emp,dict) else "",
                    "location": loc, "department": dept,
                    "apply_url": f"{remix_base}/{token}/jobs/{job_id}#app"}
    except Exception as e:
        logger.debug(f"GH Remix detail failed {job_id}: {e}")
    # Strategy B: boards-api individual job
    try:
        url = f"{api_base}/v1/boards/{token}/jobs/{job_id}"
        resp = await _gh_get(client, url)
        if resp.status_code == 200:
            data = resp.json()
            import html as _h
            desc = _clean_html(_h.unescape(data.get("content","") or ""))
            loc = data.get("location") or {}
            depts = data.get("departments") or []
            return {"description": desc, "pay_ranges": [],
                    "employment_type": "",
                    "location": loc.get("name","") if isinstance(loc,dict) else str(loc),
                    "department": depts[0].get("name","") if depts else "",
                    "apply_url": data.get("absolute_url","")}
    except Exception as e:
        logger.debug(f"GH boards-api detail failed {job_id}: {e}")
    logger.warning(f"GH: could not fetch detail for job {job_id} on {token}")
    return {}

async def _fetch_details_for_jobs(jobs: list, token: str, api_base: str, remix_base: str):
    """Fetch description + metadata for all jobs via their detail endpoints."""
    import re
    logger.info(
        f"Greenhouse: fetching descriptions for {min(len(jobs),50)} jobs "
        "direct"
    )
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as dc:
        for job in jobs[:50]:
            m = re.search(r'/jobs/([0-9]+)', job.apply_url or "")
            if not m:
                continue
            detail = await _gh_job_detail(dc, token, int(m.group(1)), api_base, remix_base)
            if detail:
                if detail.get("description"):
                    job.description = detail["description"]
                if detail.get("pay_ranges") and not job.salary:
                    tmp = _parse_greenhouse_job({**detail}, token, job.company, job.source_url)
                    if tmp and tmp.salary:
                        job.salary = tmp.salary
                if detail.get("employment_type"):
                    job.job_type = _infer_job_type(detail["employment_type"]) or job.job_type
                if detail.get("location") and job.location in ("Remote","Not specified",""):
                    job.location = detail["location"]
            await asyncio.sleep(0.25)

async def scrape_greenhouse(page, url: str, company: str) -> list:
    """
    Scrape Greenhouse jobs — 3 strategies + per-job description fetching.

    Strategies (tried in order):
    1. Remix paginated loader  job-boards.*.greenhouse.io/?page=N&_data=
    2. boards-api              boards-api.*.greenhouse.io/v1/boards/{token}/jobs?content=true
    3. HTML fallback           boards.*.greenhouse.io/{token} via Playwright




    Descriptions are fetched via individual job detail endpoints after listing,
    because listing APIs NEVER include description text.
    Results are cached for 24 hours.
    """
    jobs = []
    token = _extract_greenhouse_token(url)
    if not token:
        logger.warning(f"Greenhouse: could not extract token from {url}")
        return jobs

    cached = _cache_get(token)
    if cached:
        return cached

    api_base, board_base, remix_base = _greenhouse_base_url(url)

    # Validate token
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as probe:
            pr = await probe.head(f"{board_base}/{token}", headers={"User-Agent": _UA_LIST[0]})
            if pr.status_code == 404:
                logger.error(f"Greenhouse: invalid token or board not found: {token}")
                return jobs
    except Exception as e:
        logger.debug(f"Greenhouse probe failed for {token}: {e}")

    # ── Strategy 1: Remix paginated loader ───────────────────────────────────
    try:
        raw_jobs = []
        pg = 1
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            while True:
                resp = await _gh_get(client, f"{remix_base}/{token}?page={pg}&_data=")
                resp.raise_for_status()
                data = resp.json()
                page_jobs = data.get("jobPosts", {}).get("data", [])
                if not page_jobs:
                    break
                raw_jobs.extend(page_jobs)
                total_pages = data.get("jobPosts", {}).get("total_pages", 1)
                if pg >= total_pages:
                    break
                pg += 1
                await asyncio.sleep(0.3)

        for job in raw_jobs:
            parsed = _parse_greenhouse_job(job, token, company, url)
            if parsed:
                jobs.append(parsed)

        if jobs:
            with_desc = sum(1 for j in jobs if j.description)
            logger.info(
                f"Greenhouse Remix API: {len(jobs)} jobs from {token} ({pg} pages), "
                f"{with_desc} with descriptions"
            )
            if with_desc == 0:
                # content field was empty in listing - fetch individually
                # (happens when IP is blocked and listing returns partial data)
                logger.warning(
                    f"Greenhouse: listing returned no descriptions for {token} "
                    "(may be IP-based blocking — use GitHub Actions for reliable access)"
                )
                await _fetch_details_for_jobs(jobs, token, api_base, remix_base)
            _cache_set(token, jobs)
            return jobs

    except Exception as e:
        logger.warning(f"Greenhouse Remix loader failed for {token}: {e}")

    # ── Strategy 2: boards-api JSON ──────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            resp = await _gh_get(client, f"{api_base}/v1/boards/{token}/jobs?content=true")
            resp.raise_for_status()
            data = resp.json()

        for job in data.get("jobs", []):
            parsed = _parse_greenhouse_job(job, token, company, url)
            if parsed:
                jobs.append(parsed)

        if jobs:
            with_desc = sum(1 for j in jobs if j.description)
            logger.info(f"Greenhouse boards-api: {len(jobs)} jobs from {token}, {with_desc} with desc")
            if with_desc == 0:
                await _fetch_details_for_jobs(jobs, token, api_base, remix_base)
            _cache_set(token, jobs)
            return jobs

    except Exception as e:
        logger.warning(f"Greenhouse boards-api failed for {token}: {e}")

    # ── Strategy 3: HTML fallback via Playwright ─────────────────────────────
    if page is None:
        logger.debug(f"Greenhouse: no Playwright page, skipping HTML fallback for {token}")
        return jobs
    try:
        await page.goto(f"{board_base}/{token}", wait_until="networkidle", timeout=25000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        for section in soup.select(".opening"):
            title_el = section.select_one("a")
            if not title_el: continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href","")
            apply_url = f"{board_base}{href}" if href.startswith("/") else href
            loc_el = section.select_one(".location")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            dept = "General"
            parent = section.find_parent("section")
            if parent:
                h2 = parent.select_one("h2, h3")
                if h2: dept = h2.get_text(strip=True)
            jobs.append(ScrapedJob(title=title, company=company, source_url=url,
                                   location=location, department=dept,
                                   job_type=_infer_job_type(title), apply_url=apply_url))
        if jobs:
            await _fetch_details_for_jobs(jobs, token, api_base, remix_base)
            logger.info(f"Greenhouse HTML fallback: {len(jobs)} jobs from {token}")
            _cache_set(token, jobs)
    except NotImplementedError:
        logger.warning(f"Greenhouse: Playwright not available ({token})")
    except Exception as e:
        logger.error(f"Greenhouse HTML fallback failed for {url}: {e}")

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
# Odoo Job Board scraper
# ---------------------------------------------------------------------------

async def scrape_odoo_job_page(page: Page, job_url: str, source_url: str, company: str) -> Optional[ScrapedJob]:
    """
    Fetch a single Odoo job detail page.
    Uses httpx for reliable HTML extraction then formats the description.
    """
    try:
        # Use httpx directly - more reliable than Playwright for static Odoo pages
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(job_url, headers=headers)
            resp.raise_for_status()
            html = resp.text

        soup = BeautifulSoup(html, "html.parser")

        # Title
        h1 = soup.find("h1")
        if not h1:
            return None
        title = h1.get_text(strip=True)

        # Department
        department = "General"
        h5 = soup.find("h5")
        if h5:
            dept_text = h5.get_text(strip=True).strip("-").strip()
            if dept_text:
                department = dept_text

        # Job type
        body_text = soup.get_text(" ").lower()
        job_type = "Full-time"
        if "part-time" in body_text or "part time" in body_text:
            job_type = "Part-time"
        elif "contract" in body_text:
            job_type = "Contract"
        elif "intern" in body_text:
            job_type = "Internship"

        # Location
        location = "Not specified"
        full_text = soup.get_text("\n")
        for line in full_text.splitlines():
            line = line.strip()
            if re.match(r"^Location\s*:", line, re.I):
                loc = re.sub(r"^Location\s*:\s*", "", line, flags=re.I).strip()
                if loc:
                    location = loc
                    break

        # ----------------------------------------------------------------
        # Extract description - remove noise then get structured content
        # ----------------------------------------------------------------
        for tag in soup.select("nav, header, footer, script, style, .navbar, .o_header, .o_footer, img, .o_menu_sections, .o_top_menu"):
            tag.decompose()

        # Find content between h1 and footer images/links section
        wrap = soup.select_one("#wrap") or soup.find("main") or soup.find("body")
        if not wrap:
            return None

        footer_keywords = [
            "useful links", "connect with us", "follow us",
            "copyright", "powered by", "whistle blower", "fraud alert"
        ]

        desc_parts = []
        found_title = False

        def extract_node(node, depth=0):
            nonlocal found_title

            if not hasattr(node, "name") or node.name is None:
                # Text node
                if not found_title:
                    return
                text = str(node).strip()
                if text and len(text) > 1:
                    desc_parts.append(("text", text))
                return

            tag = node.name.lower()

            # Skip known noise
            if tag in ["script", "style", "img", "button", "input", "form"]:
                return

            # Mark when we pass the h1
            if tag == "h1":
                found_title = True
                return

            if not found_title:
                for child in node.children:
                    extract_node(child, depth+1)
                return

            text = node.get_text(strip=True)
            if not text:
                return

            # Stop at footer
            if any(kw in text.lower() for kw in footer_keywords):
                return

            # Headings → bold markers
            if tag in ["h2", "h3", "h4", "h5", "h6"]:
                desc_parts.append(("heading", text))
                return

            # Lists
            if tag in ["ul", "ol"]:
                for li in node.find_all("li", recursive=False):
                    li_text = li.get_text(strip=True)
                    if li_text and not any(kw in li_text.lower() for kw in footer_keywords):
                        desc_parts.append(("bullet", li_text))
                return

            if tag == "li":
                if not any(kw in text.lower() for kw in footer_keywords):
                    desc_parts.append(("bullet", text))
                return

            # Paragraphs and divs — recurse into children
            if tag in ["p", "div", "section", "article", "span"]:
                # Check if it has block children — if so recurse
                has_block = any(
                    hasattr(c, "name") and c.name in ["p","div","ul","ol","h2","h3","h4","h5","h6","section"]
                    for c in node.children
                )
                if has_block:
                    for child in node.children:
                        extract_node(child, depth+1)
                else:
                    # Leaf node — get text directly
                    if text and not any(kw in text.lower() for kw in footer_keywords):
                        desc_parts.append(("text", text))
                return

            # Default — recurse
            for child in node.children:
                extract_node(child, depth+1)

        for child in wrap.children:
            extract_node(child)

        # Build formatted description
        # Step 1: Collapse all whitespace within each part (fixes broken sentences)
        cleaned_parts = []
        for part_type, part_text in desc_parts:
            # Collapse internal whitespace and line breaks into single spaces
            part_text = " ".join(part_text.split())
            part_text = part_text.strip()
            if not part_text or len(part_text) < 2:
                continue
            # Skip nav noise
            nav_noise = {"home","forum","jobs","blog","help","contact us","sign in","all jobs","apply now!","apply now","search","0","#"}
            if part_text.lower() in nav_noise:
                continue
            cleaned_parts.append((part_type, part_text))

        # Step 2: Handle fake bullets — lines starting with · or - that came in as text
        normalized = []
        for part_type, part_text in cleaned_parts:
            # Detect fake bullets: ·, •, -, –, or lowercase 'o' used as bullet prefix
            if part_type == "text" and re.match(r"^([·•\-–]|o\s+[A-Z]|o\s+[a-z])\s*", part_text):
                clean = re.sub(r"^[·•\-–o]+\s*", "", part_text).strip()
                if clean:
                    normalized.append(("bullet", clean))
            else:
                normalized.append((part_type, part_text))

        # Step 3: Merge fragmented text lines into proper sentences/paragraphs
        merged = []
        for part_type, part_text in normalized:
            if not merged:
                merged.append((part_type, part_text))
                continue
            prev_type, prev_text = merged[-1]
            # Merge consecutive text fragments that form one sentence
            if (part_type == "text" and prev_type == "text" and
                    not prev_text.endswith((".", "!", "?", ":")) and
                    not part_text[0].isupper()):
                merged[-1] = ("text", prev_text + " " + part_text)
            else:
                merged.append((part_type, part_text))

        # Step 4: Build final output lines
        lines_out = []
        prev_type = None
        for part_type, part_text in merged:
            if part_type == "heading":
                if lines_out:
                    lines_out.append("")
                lines_out.append(f"**{part_text}**")
                lines_out.append("")
            elif part_type == "bullet":
                lines_out.append(f"\u2022 {part_text}")
            elif part_type == "text":
                if prev_type == "bullet":
                    lines_out.append("")
                lines_out.append(part_text)
            prev_type = part_type

        # Step 5: Remove consecutive blank lines
        final = []
        prev_blank = False
        for line in lines_out:
            if line == "":
                if not prev_blank:
                    final.append(line)
                prev_blank = True
            else:
                final.append(line)
                prev_blank = False

        description = "\n".join(final).strip()

        logger.info(f"  v {title} - {len(description)} chars, location: {location}")

        if not description:
            logger.warning(f"  ! Empty description for {job_url}")

        return ScrapedJob(
            title=title,
            company=company,
            source_url=source_url,
            location=location,
            job_type=job_type,
            department=department,
            description=description,
            apply_url=job_url,
        )

    except Exception as e:
        logger.warning(f"  x Failed to scrape {job_url}: {e}")
        return None

async def scrape_odoo(page: Page, url: str, company: str) -> list[ScrapedJob]:
    """
    Scrapes Odoo-based job boards.
    1. Visits the jobs listing page and finds all /jobs/<slug> links
    2. Visits each job detail page to fetch the full description
    """
    jobs = []
    try:
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        await page.goto(url, wait_until="networkidle", timeout=25000)
        await asyncio.sleep(2)
        soup = BeautifulSoup(await page.content(), "html.parser")

        # Collect all job detail links — /jobs/<slug> but not /jobs/apply/<slug>
        job_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = href if href.startswith("http") else base_url + href
            if (
                "/jobs/" in full
                and "/jobs/apply/" not in full
                and full != url
                and full != base_url + "/jobs"
                and full not in job_links
            ):
                job_links.append(full)

        logger.info(f"Odoo: found {len(job_links)} job links at {url}")

        for job_url in job_links:
            job = await scrape_odoo_job_page(page, job_url, url, company)
            if job:
                jobs.append(job)

    except Exception as e:
        logger.error(f"Odoo scrape failed for {url}: {e}")

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
    if "odoo" in url.lower():
        return "odoo"
    return "generic"


async def scrape_company(
    url: str,
    company: str,
    industry: str = "",
    logo_url: str = "",
) -> list[ScrapedJob]:
    ats = detect_ats(url)
    logger.info(f"Scraping {company} ({url}) via {ats} strategy")

    jobs = []

    # ── API-based scrapers (no Playwright needed) ─────────────────────────────
    if ats == "oracle":
        jobs = await scrape_oracle_hcm(url, company)

    elif ats == "workday":
        jobs = await scrape_workday(url, company)

    elif ats == "greenhouse":
        # Greenhouse uses Remix API + boards-api — no browser needed
        # Playwright is only used as a last-resort fallback inside scrape_greenhouse
        # and only when page is not None
        jobs = await scrape_greenhouse(None, url, company)

    # ── Browser-based scrapers (Playwright required) ──────────────────────────
    else:
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning(
                f"Playwright not available — skipping {company} ({ats}). "
                "Run: playwright install chromium"
            )
            return []
        try:
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
                    if ats == "odoo":
                        jobs = await scrape_odoo(page, url, company)
                    elif ats == "lever":
                        jobs = await scrape_lever(page, url, company)
                    else:
                        jobs = await scrape_generic(page, url, company)
                finally:
                    await browser.close()
        except NotImplementedError:
            logger.warning(
                f"Playwright cannot launch on this OS/event loop — "
                f"skipping {company} ({ats}). "
                "Use Railway deployment or GitHub Actions for browser-based scrapers."
            )
            return []

    logger.info(f"  -> Found {len(jobs)} jobs at {company}")

    # Stamp logo_url on all jobs
    if logo_url:
        for j in jobs:
            if not getattr(j, "logo_url", ""):
                j.logo_url = logo_url

    # Stamp industry on all jobs
    if industry:
        for j in jobs:
            if not getattr(j, "industry", ""):
                j.industry = industry

    return jobs



# ---------------------------------------------------------------------------
# Oracle HCM adapter
# Converts OracleCloudScraper output to ScrapedJob dataclass
# ---------------------------------------------------------------------------

def scrape_oracle(company_name: str, careers_url: str) -> list[ScrapedJob]:
    """
    Scrape an Oracle HCM careers portal and return ScrapedJob objects.
    Uses the REST API with correct Oracle headers — no Playwright needed.
    Reference: https://jobo.world/ats/oraclecloud
    """
    try:
        from services.recruitment.oracle_scraper import OracleCloudScraper
        scraper = OracleCloudScraper(
            careers_url=careers_url,
            company_name=company_name,
            fetch_details=True,
        )
        raw_jobs = scraper.run()
    except Exception as e:
        logger.error(f"Oracle scraper failed for {company_name}: {e}")
        return []

    jobs = []
    for r in raw_jobs:
        jobs.append(ScrapedJob(
            title=r.get("title", ""),
            company=r.get("company", company_name),
            source_url=r.get("source_url", careers_url),
            location=r.get("location", "Not specified"),
            job_type=r.get("job_type", "Full-time"),
            department=r.get("department", "General"),
            description=r.get("description", ""),
            apply_url=r.get("apply_url", careers_url),
            salary=r.get("salary", ""),
        ))

    logger.info(f"Oracle adapter: {len(jobs)} jobs for {company_name}")
    return jobs


async def scrape_all(companies: list[dict]) -> list[ScrapedJob]:
    """
    Scrape all companies.
    Oracle HCM portals → fast REST API scraper (no browser needed).
    All other portals → Playwright browser scraper.
    """
    def is_oracle(url: str) -> bool:
        return any(p in url.lower() for p in [
            "oraclecloud.com", "hcmui/candidateexperience",
        ])

    def try_oracle_api(company: dict) -> tuple[bool, list]:
        """Try REST API first. If blocked (403), return False to use Playwright."""
        try:
            import requests as req
            from urllib.parse import urlparse
            parsed = urlparse(company["url"])
            base = f"{parsed.scheme}://{parsed.netloc}"
            test_url = f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=CX_1,limit=1,offset=0"
            r = req.get(test_url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 403 and "allowlist" in r.text.lower():
                logger.info(f"Oracle API blocked for {company['name']} — using Playwright instead")
                return False, []
            jobs = scrape_oracle(company["name"], company["url"])
            return True, jobs
        except Exception as e:
            logger.warning(f"Oracle API attempt failed for {company['name']}: {e} — using Playwright")
            return False, []

    oracle_cos = [c for c in companies if is_oracle(c.get("url", ""))]
    browser_cos = [c for c in companies if not is_oracle(c.get("url", ""))]

    all_jobs: list[ScrapedJob] = []

    # Oracle — try REST API first, fall back to Playwright if blocked
    oracle_fallback = []
    for company in oracle_cos:
        success, jobs = try_oracle_api(company)
        if success:
            all_jobs.extend(jobs)
        else:
            oracle_fallback.append(company)  # will be scraped by Playwright

    browser_cos = browser_cos + oracle_fallback  # merge fallbacks

    # Non-Oracle + Oracle fallbacks — Playwright
    if browser_cos:
        semaphore = asyncio.Semaphore(3)

        async def guarded_scrape(c):
            async with semaphore:
                return await scrape_company(
                    c["url"], c["name"],
                    c.get("industry", ""),
                    c.get("logo_url", ""),
                )

        results = await asyncio.gather(
            *[guarded_scrape(c) for c in browser_cos], return_exceptions=True
        )
        for r in results:
            if isinstance(r, list):
                all_jobs.extend(r)
            else:
                logger.error(f"Scrape error: {r}")

    return all_jobs

