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
    industry: str = ""
    salary: str = ""
    description: str = ""
    apply_url: str = ""
    logo_url: str = ""
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

# Known wd_server numbers for common companies — prevents wrong server assumption
_KNOWN_WD_SERVERS = {
    "shell": "wd3", "mtn": "wd3", "airtel": "wd3", "kainos": "wd3",
    "unilever": "wd3", "microsoft": "wd3", "google": "wd3",
    "meta": "wd5", "amazon": "wd1", "oracle": "wd1",
}


def _parse_workday_url(url: str) -> dict:
    """
    Extract tenant, site, wd_server from any Workday URL format.

    Handles:
    - https://{tenant}.wd{N}.myworkdayjobs.com/{locale}/{site}   (standard)
    - https://{tenant}.wd{N}.myworkdayjobs.com/{site}             (no locale)
    - https://jobs.myworkdaysite.com/recruiting/{tenant}/{site}   (alt format)

    Issue from guide: do NOT assume wd3 — always read from URL.
    Fallback only when URL doesn't contain wd server info.
    """
    import re as _re

    # Standard: https://{tenant}.wd{N}.myworkdayjobs.com/...
    m = _re.match(
        r'https://([^.]+)\.(wd\d+)\.myworkdayjobs\.com'
        r'(?:/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+))?',
        url
    )
    if m:
        tenant = m.group(1)
        wd_server = m.group(2)           # exact wd server from URL — never assume
        site = m.group(3) or tenant      # fall back to tenant name if path is empty
        return {"tenant": tenant, "wd_server": wd_server, "site": site}

    # Alternative: https://jobs.myworkdaysite.com/recruiting/{tenant}/{site}
    m = _re.match(
        r'https://(?:jobs\.)?myworkdaysite\.com/recruiting/([^/]+)/([^/?#]+)',
        url
    )
    if m:
        tenant = m.group(1)
        site = m.group(2)
        # Look up known wd_server or default to wd3
        wd_server = _KNOWN_WD_SERVERS.get(tenant.lower(), "wd3")
        return {"tenant": tenant, "wd_server": wd_server, "site": site}

    # Last-resort manual parse (rare edge cases)
    parsed = urlparse(url)
    netloc_parts = parsed.netloc.split(".")
    tenant = netloc_parts[0]
    # Find wd server in netloc e.g. shell.wd3.myworkdayjobs.com
    wd_server = next(
        (p for p in netloc_parts if p.startswith("wd") and p[2:].isdigit()),
        _KNOWN_WD_SERVERS.get(tenant.lower(), "wd3")
    )
    path_parts = [
        p for p in parsed.path.strip("/").split("/")
        if p and not _re.match(r'^[a-z]{2}-[A-Z]{2}$', p)
    ]
    site = path_parts[0] if path_parts else tenant
    return {"tenant": tenant, "wd_server": wd_server, "site": site}


def _workday_html_to_text(html_str: str) -> str:
    """Convert Workday HTML description to readable plain text."""
    if not html_str:
        return ""
    import html as _html_mod
    import re as _re
    NL = chr(10)
    text = _html_mod.unescape(html_str)
    text = _re.sub(r"<br\s*/?>", NL, text, flags=_re.IGNORECASE)
    text = _re.sub(r"</p>", NL + NL, text, flags=_re.IGNORECASE)
    text = _re.sub(r"</li>", NL, text, flags=_re.IGNORECASE)
    text = _re.sub(r"<li[^>]*>", "\u2022 ", text, flags=_re.IGNORECASE)
    text = _re.sub(r"</ul>|</ol>", NL, text, flags=_re.IGNORECASE)
    for tag in ["h1", "h2", "h3", "h4"]:
        text = _re.sub(f"<{tag}[^>]*>", NL + NL + "**", text, flags=_re.IGNORECASE)
        text = _re.sub(f"</{tag}>", "**" + NL, text, flags=_re.IGNORECASE)
    text = _re.sub(r"<strong[^>]*>|<b[^>]*>", "**", text, flags=_re.IGNORECASE)
    text = _re.sub(r"</strong>|</b>", "**", text, flags=_re.IGNORECASE)
    text = _re.sub(r"<[^>]+>", "", text)
    result, blanks = [], 0
    for ln in text.split(NL):
        ln = _re.sub(r" {2,}", " ", ln.strip())
        if ln == "":
            blanks += 1
            if blanks <= 1:
                result.append(ln)
        else:
            blanks = 0
            result.append(ln)
    return NL.join(result).strip()

async def scrape_workday(url: str, company: str, page=None) -> list[ScrapedJob]:
    """
    Scrape all jobs from a Workday career site using the CXS API.
    Fetches full descriptions for each job via API.
    If API returns 406 (blocked), falls back to Playwright browser rendering.
    Reference: https://jobo.world/ats/workday
    """
    import requests as _requests
    import time as _time

    jobs = []
    try:
        cfg = _parse_workday_url(url)
        tenant = cfg["tenant"]
        site = cfg["site"]
        wd_server = cfg["wd_server"]
        base = f"https://{tenant}.{wd_server}.myworkdayjobs.com"

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Accept-Language": "en-US",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": f"{base}/en-US/{site}",
        }

        list_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"
        batch = 20
        offset = 0
        total = None
        all_postings = []
        sitemap_urls = {}  # path → full URL, from sitemap discovery

        # ── Step 0 (optional): discover job URLs via sitemap ─────────────────
        # Per jobo.world Step 6: siteMap.xml (capital S) lists all job URLs.
        # We use this to get the externalUrl for each job when available,
        # and as a fallback source of job paths if the listing API fails.
        try:
            from xml.etree import ElementTree as _ET
            sitemap_url = f"{base}/en-US/{site}/siteMap.xml"
            sm_resp = _requests.get(sitemap_url, headers={
                "Accept": "application/xml",
                "User-Agent": headers["User-Agent"],
            }, timeout=15)
            if sm_resp.status_code == 200:
                root = _ET.fromstring(sm_resp.content)
                ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
                for loc_el in root.findall(".//ns:url/ns:loc", ns):
                    loc = loc_el.text or ""
                    if "/job/" in loc:
                        # Extract path portion after the base
                        job_path = loc.replace(f"{base}/", "").lstrip("/")
                        sitemap_urls[job_path] = loc
                logger.info(
                    f"Workday {company}: sitemap found {len(sitemap_urls)} job URLs"
                )
        except Exception as e_sm:
            logger.debug(f"Workday sitemap not available: {e_sm}")

        # ── Step 1: fetch all job listings with pagination ───────────────────
        while True:
            payload = {
                "appliedFacets": {},
                "limit": batch,
                "offset": offset,
                "searchText": "",
            }
            try:
                resp = _requests.post(list_url, json=payload, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.error(f"Workday list API failed at offset {offset}: {e}")
                break

            postings = data.get("jobPostings", [])
            if total is None:
                total = data.get("total", 0)
            if not postings:
                break

            all_postings.extend(postings)
            logger.info(f"Workday {company}: fetched {len(all_postings)} / {total} jobs")

            # Per guide: stop when empty OR offset + limit >= total
            if len(postings) < batch:
                # Got fewer than requested — we're at the end
                break
            if total and offset + batch >= total:
                break
            offset += batch
            _time.sleep(1.5)  # 1.5s between pages — per best practices

        logger.info(f"Workday {company}: {len(all_postings)} total listings found")

        # ── Step 2: fetch full details for each job ───────────────────────────
        # Workday requires specific Accept/Content-Type headers or returns 406.
        # We try 3 header strategies to handle different Workday tenant configs.
        detail_header_variants = [
            # Variant 1: standard JSON (works for most tenants)
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{base}/en-US/{site}",
                "User-Agent": headers["User-Agent"],
            },
            # Variant 2: Workday vendor MIME type (required by some tenants like Shell)
            {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/json",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{base}/en-US/{site}",
                "User-Agent": headers["User-Agent"],
            },
            # Variant 3: browser-like full Accept (most permissive)
            {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": f"{base}/en-US/{site}",
                "User-Agent": headers["User-Agent"],
            },
        ]

        import re as _re

        async def _fetch_workday_detail(path_for_api: str, full_page_url: str = "") -> dict:
            """
            Fetch full job detail per jobo.world guide Step 5.
            URL: GET /wday/cxs/{tenant}/{site}/job/{externalPath}
            where externalPath is used AS-IS from the listing response.

            Falls back to Playwright browser if API returns 406 (blocked tenant).
            """
            # Per guide: pass externalPath directly — no stripping
            # Try both the raw path and without locale prefix as safety net
            alt_path = _re.sub(r"^[a-z]{2}-[A-Z]{2}/", "", path_for_api)
            candidate_urls = [
                f"{base}/wday/cxs/{tenant}/{site}/job/{path_for_api}",
                f"{base}/wday/cxs/{tenant}/{site}/job/{alt_path}",
            ]
            for det_url in candidate_urls:
                for hdrs in detail_header_variants:
                    try:
                        r = _requests.get(det_url, headers=hdrs, timeout=30)
                        if r.status_code == 200:
                            logger.debug(f"    Detail API OK: {det_url[:70]}")
                            return r.json()
                    except Exception:
                        continue

                # Strategy 3: Playwright browser rendering
                # Required for Shell and other tenants that block server-side requests.
                # Workday SPAs render job descriptions client-side after JS executes.
                if page is not None:
                    page_url = full_page_url or f"{base}/en-US/{site}/job/{path_for_api}"
                    try:
                        logger.info(f"    Playwright: loading {page_url[:70]}")

                        # Use networkidle — Workday SPAs need JS to fully execute
                        await page.goto(page_url, wait_until="networkidle", timeout=35000)

                        # Wait specifically for the description container
                        selectors_to_try = [
                            "[data-automation-id='jobPostingDescription']",
                            "[data-automation-id='job-posting-description']",
                            ".job-description",
                            "[class*='description']",
                        ]
                        found_selector = None
                        for sel in selectors_to_try:
                            try:
                                await page.wait_for_selector(sel, timeout=6000)
                                found_selector = sel
                                break
                            except Exception:
                                continue

                        if found_selector:
                            el = await page.query_selector(found_selector)
                            if el:
                                inner = await el.inner_html()
                                if len(inner) > 100:
                                    logger.info(
                                        f"    Playwright selector '{found_selector}': "
                                        f"{len(inner)} chars"
                                    )
                                    return {"jobDescription": inner,
                                            "_source": "playwright_selector"}

                        # Try JavaScript evaluation to extract innerText directly
                        # This works even if the selector approach misses due to shadow DOM
                        body_text = await page.evaluate("""() => {
                            // Try Workday automation IDs first
                            const selectors = [
                                '[data-automation-id="jobPostingDescription"]',
                                '[data-automation-id="job-posting-description"]',
                                '.job-description',
                                '[class*="description"]',
                                'section[class*="job"]',
                                'article',
                                'main',
                            ];
                            for (const sel of selectors) {
                                const el = document.querySelector(sel);
                                if (el && el.innerText && el.innerText.length > 200) {
                                    return el.innerText;
                                }
                            }
                            // Last resort: all visible body text
                            return document.body ? document.body.innerText : '';
                        }""")

                        if body_text and len(body_text) > 200:
                            # Filter out nav/header noise — description should be
                            # the longest contiguous paragraph block
                            lines = [l.strip() for l in body_text.split(chr(10)) if l.strip()]
                            # Find the start of the actual job content
                            # (skip short lines that are nav items)
                            content_lines = []
                            in_content = False
                            for line in lines:
                                if len(line) > 80:
                                    in_content = True
                                if in_content:
                                    content_lines.append(line)
                            result = chr(10).join(content_lines).strip()
                            if len(result) > 200:
                                logger.info(
                                    f"    Playwright JS eval: {len(result)} chars"
                                )
                                return {"jobDescription": result,
                                        "_source": "playwright_text"}

                    except Exception as e_pw:
                        logger.warning(
                            f"    Playwright failed for '{title[:30]}': {e_pw}"
                        )

                return {}

        for i, posting in enumerate(all_postings):
            title = (posting.get("title") or "").strip()
            if not title:
                continue

            external_path = posting.get("externalPath", "")
            external_url = posting.get("externalUrl", "")
            location = posting.get("locationsText") or "Not specified"
            # Prefer externalUrl from listing, then sitemap, then construct from path
            path_key = external_path.lstrip("/")
            apply_url = (
                external_url
                or sitemap_urls.get(path_key)
                or (f"{base}{external_path}" if external_path else url)
            )

            # Extract requisition ID from bulletFields (per jobo.world guide)
            # Formats vary: JR_12345, JR_12345-1, REQ12345, R-00066362, WD-12345
            import re as _re_req
            req_id = None
            for field in posting.get("bulletFields", []):
                if isinstance(field, str) and _re_req.match(
                    r'^(JR_|REQ|R-|WD-|WD\d|IND-|P-|HF-|GL-)\S+',
                    field, _re_req.IGNORECASE
                ):
                    req_id = field
                    break
            # Also accept any purely numeric or alphanum-dash ID in bulletFields
            if not req_id:
                for field in posting.get("bulletFields", []):
                    if isinstance(field, str) and _re_req.match(r'^[\w][\w\-]{3,}$', field):
                        req_id = field
                        break

            # Posted date
            posted_on = posting.get("postedOn", "")

            description = ""
            department = ""
            job_type = "Full-time"

            if external_path:
                try:
                    path_for_api = external_path.lstrip("/")
                    det = await _fetch_workday_detail(path_for_api, apply_url)

                    if det:
                        raw_desc = det.get("jobDescription", "") or ""
                        description = _workday_html_to_text(raw_desc)

                        # Time type → job_type (per guide Step 5)
                        time_type = (det.get("timeType") or "").lower()
                        if "part" in time_type:
                            job_type = "Part-time"
                        elif "contract" in time_type or "temp" in time_type:
                            job_type = "Contract"
                        elif "intern" in time_type:
                            job_type = "Internship"

                        # Department from category (per guide Step 5)
                        department = (
                            det.get("jobPostingCategory", {}).get("descriptor", "")
                            or det.get("jobFamily", {}).get("descriptor", "")
                            or ""
                        )

                        # Additional locations — merge into location string
                        add_locs = det.get("additionalLocations", [])
                        if add_locs and isinstance(add_locs, list):
                            extra = ", ".join(
                                l.get("descriptor", "") if isinstance(l, dict) else str(l)
                                for l in add_locs if l
                            )
                            if extra and extra not in location:
                                location = f"{location}, {extra}"

                        # Req ID from detail if not found in bulletFields
                        if not req_id:
                            req_id = det.get("jobReqId") or det.get("jobId") or req_id

                        logger.info(
                            f"  Workday {i+1}/{len(all_postings)}: "
                            f"'{title[:40]}' — {len(description)} chars"
                        )
                    else:
                        logger.warning(
                            f"  Workday detail: all strategies failed for '{title[:35]}'"
                        )
                except Exception as e:
                    logger.warning(f"  Workday detail error for '{title[:30]}': {e}")

                _time.sleep(1.0)  # 1s between detail fetches

            # Use requisition ID in fingerprint if available for better dedup
            fingerprint_title = f"{req_id}:{title}" if req_id else title

            jobs.append(ScrapedJob(
                title=title,
                company=company,
                source_url=url,
                location=location,
                job_type=job_type,
                department=department,
                description=description,
                apply_url=apply_url,
            ))

        logger.info(f"Workday {company}: scraped {len(jobs)} jobs with descriptions")

    except Exception as e:
        logger.error(f"Workday scrape failed for {url}: {e}")

    return jobs


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

def _extract_greenhouse_token(url: str) -> str:
    """Extract company token from Greenhouse URL.
    Handles all regional and legacy formats:
      https://job-boards.greenhouse.io/{token}
      https://job-boards.eu.greenhouse.io/{token}
      https://boards.greenhouse.io/{token}
      https://boards.eu.greenhouse.io/{token}
      https://job-boards.greenhouse.io/{token}/jobs
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    # path is like "anthropic" or "anthropic/jobs"
    token = path.split("/")[0]
    return token


def _greenhouse_base_url(url: str) -> tuple[str, str]:
    """
    Return (api_base, board_base) for the correct Greenhouse region.
    EU: job-boards.eu.greenhouse.io  -> boards-api.eu.greenhouse.io
    US: job-boards.greenhouse.io     -> boards-api.greenhouse.io
    """
    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    if ".eu." in host or host.startswith("eu."):
        return (
            "https://boards-api.eu.greenhouse.io",
            "https://boards.eu.greenhouse.io",
            "https://job-boards.eu.greenhouse.io",
        )
    return (
        "https://boards-api.greenhouse.io",
        "https://boards.greenhouse.io",
        "https://job-boards.greenhouse.io",
    )


async def _greenhouse_get(client: httpx.AsyncClient, url: str, retries: int = 3) -> httpx.Response:
    """
    GET with exponential backoff for Greenhouse API calls.
    Handles 429 Too Many Requests and transient 5xx errors.
    """
    delay = 0.3
    last_exc = None
    for attempt in range(retries):
        try:
            resp = await client.get(url, headers={
                "Accept": "application/json",
                "User-Agent": "JobStream/1.0",
            })
            if resp.status_code == 429:
                wait = delay * (2 ** attempt)
                logger.warning(f"Greenhouse 429 on {url}, backing off {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            if resp.status_code >= 500:
                wait = delay * (2 ** attempt)
                logger.warning(f"Greenhouse {resp.status_code} on {url}, retry in {wait:.1f}s")
                await asyncio.sleep(wait)
                continue
            return resp
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            last_exc = e
            wait = delay * (2 ** attempt)
            logger.warning(f"Greenhouse request error ({e}), retry in {wait:.1f}s")
            await asyncio.sleep(wait)
    raise httpx.HTTPError(f"Greenhouse: all {retries} retries failed for {url}") from last_exc


# ── Greenhouse result cache ───────────────────────────────────────────────────
# Caches scraped job IDs per token for CACHE_TTL seconds (default 24h).
# Jobs already in the DB (by fingerprint) are skipped on repeat runs.
# The cache is in-process (dict) — survives between scrape cycles in the same
# worker process but resets on restart. DB-level deduplication via fingerprint
# is the authoritative guard.

import time as _time
_GH_CACHE: dict[str, tuple[float, list]] = {}   # token -> (timestamp, [ScrapedJob])
CACHE_TTL = 60 * 60 * 24   # 24 hours in seconds


def _cache_get(token: str) -> list | None:
    """Return cached jobs for token if fresh, else None."""
    entry = _GH_CACHE.get(token)
    if entry and (_time.time() - entry[0]) < CACHE_TTL:
        age_h = (_time.time() - entry[0]) / 3600
        logger.info(f"Greenhouse cache HIT for {token} ({age_h:.1f}h old, {len(entry[1])} jobs)")
        return entry[1]
    return None


def _cache_set(token: str, jobs: list) -> None:
    """Store jobs in cache with current timestamp."""
    _GH_CACHE[token] = (_time.time(), jobs)
    logger.info(f"Greenhouse cache SET for {token}: {len(jobs)} jobs, TTL {CACHE_TTL//3600}h")


def _cache_invalidate(token: str) -> None:
    """Force-expire cache for a token (e.g. after admin manual refresh)."""
    _GH_CACHE.pop(token, None)
    logger.info(f"Greenhouse cache INVALIDATED for {token}")


def parse_locations(location_str: str) -> list[str]:
    """Parse semicolon-separated Greenhouse location string into a list."""
    if not location_str:
        return []
    return [loc.strip() for loc in location_str.split(";") if loc.strip()]


def _infer_job_type(title: str) -> str:
    """Infer job type from title keywords."""
    t = title.lower()
    if any(k in t for k in ("part-time", "part time")):
        return "Part-time"
    if any(k in t for k in ("contract", "freelance", "contractor")):
        return "Contract"
    if any(k in t for k in ("intern", "internship", "graduate")):
        return "Internship"
    if any(k in t for k in ("temporary", "temp ")):
        return "Temporary"
    return "Full-time"


def _clean_html(html_str: str) -> str:
    """Strip HTML tags from description, decode entities, return clean text."""
    import html as html_mod
    if not html_str:
        return ""
    # Decode HTML entities first (e.g. &amp; &lt; &#39; etc.)
    decoded = html_mod.unescape(html_str)
    soup = BeautifulSoup(decoded, "html.parser")
    # Replace block elements with newlines for readability
    for tag in soup.find_all(["br", "p", "li", "h1", "h2", "h3", "h4", "div"]):
        tag.insert_before("\n")
    text = soup.get_text(separator=" ", strip=True)
    # Clean up whitespace
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return "\n".join(lines)[:5000]


def _parse_greenhouse_job(job: dict, token: str, company: str, source_url: str) -> "ScrapedJob | None":
    """
    Parse a single Greenhouse job dict (from any API endpoint) into a ScrapedJob.
    Handles both Remix loader format and boards-api format.
    """
    import html as html_mod

    title = (job.get("title") or "").strip()
    if not title:
        return None

    job_id = job.get("id", "")

    # ── Location ──────────────────────────────────────────────────────────────
    loc = job.get("location") or {}
    if isinstance(loc, dict):
        raw_location = loc.get("name") or loc.get("city") or ""
    elif isinstance(loc, str):
        raw_location = loc
    else:
        raw_location = ""

    # Fallback to offices list if location string is empty
    if not raw_location:
        offices = job.get("offices") or []
        if offices and isinstance(offices[0], dict):
            raw_location = "; ".join(o.get("name", "") for o in offices if o.get("name"))

    # Also check job_post_location (from Remix detail endpoint)
    if not raw_location:
        raw_location = job.get("job_post_location") or ""

    # Parse semicolon-separated locations; store primary for DB, keep all for display
    locations = parse_locations(raw_location) or ["Remote"]
    location = locations[0]  # primary location stored in DB
    # Attach all locations as metadata for potential multi-location display
    all_locations = "; ".join(locations)

    # ── Department ────────────────────────────────────────────────────────────
    depts = job.get("departments") or job.get("department") or []
    if isinstance(depts, list) and depts:
        dept = depts[0].get("name", "General") if isinstance(depts[0], dict) else str(depts[0])
    elif isinstance(depts, str):
        dept = depts
    else:
        dept = "General"

    # ── Apply URL ─────────────────────────────────────────────────────────────
    # Derive correct regional base from source_url
    src_host = source_url.split("/")[2] if source_url.startswith("http") else "job-boards.greenhouse.io"
    _rmx = "https://job-boards.eu.greenhouse.io" if ".eu." in src_host else "https://job-boards.greenhouse.io"
    apply_url = (
        job.get("absolute_url") or
        job.get("url") or
        (f"{_rmx}/{token}/jobs/{job_id}" if job_id else "")
    )

    # ── Description ───────────────────────────────────────────────────────────
    # content field contains full HTML description with entities
    raw_desc = job.get("content") or job.get("description") or ""
    description = _clean_html(raw_desc)

    # ── Pay range (may be empty — not all companies publish salaries) ──────────
    salary = ""
    # Prefer pay_ranges list (from Remix detail endpoint)
    pay_ranges = job.get("pay_ranges") or []
    if pay_ranges and isinstance(pay_ranges, list):
        parts = []
        for pr in pay_ranges:
            currency = pr.get("currency", "USD")
            mn = pr.get("min")
            mx = pr.get("max")
            label = pr.get("title", "")
            if mn and mx:
                chunk = f"{currency} {int(mn):,} – {int(mx):,}"
            elif mn:
                chunk = f"{currency} {int(mn):,}+"
            elif mx:
                chunk = f"up to {currency} {int(mx):,}"
            else:
                continue
            if label:
                chunk += f" ({label})"
            parts.append(chunk)
        salary = " | ".join(parts)
    # Fall back to legacy pay_range / salary_range single object
    if not salary:
        pay = job.get("pay_range") or job.get("salary_range") or {}
        if pay and isinstance(pay, dict):
            min_pay = pay.get("min_amount") or pay.get("min")
            max_pay = pay.get("max_amount") or pay.get("max")
            currency = pay.get("currency_type") or pay.get("currency", "USD")
            unit = pay.get("pay_period") or pay.get("unit", "")
            if min_pay and max_pay:
                salary = f"{currency} {int(min_pay):,} – {int(max_pay):,}"
                if unit:
                    salary += f" / {unit.lower()}"
            elif min_pay:
                salary = f"{currency} {int(min_pay):,}+"

    # ── Job type heuristic ────────────────────────────────────────────────────
    job_type = _infer_job_type(title)
    # Also check employment_type field if present (from detail endpoint)
    emp_type = job.get("employment_type") or job.get("job_type") or ""
    if not emp_type:
        emp_obj = job.get("employment") or {}
        emp_type = emp_obj.get("name", "") if isinstance(emp_obj, dict) else str(emp_obj)
    if emp_type:
        emp_lower = emp_type.lower()
        if "part" in emp_lower:
            job_type = "Part-time"
        elif "contract" in emp_lower or "freelance" in emp_lower:
            job_type = "Contract"
        elif "intern" in emp_lower:
            job_type = "Internship"
        elif "full" in emp_lower:
            job_type = "Full-time"

    # Prepend all locations to description if job is multi-location
    if len(locations) > 1:
        location_note = f"Locations: {all_locations}\n\n"
        description = location_note + description if description else location_note

    return ScrapedJob(
        title=title,
        company=company,
        source_url=source_url,
        location=all_locations,   # store all locations joined for searchability
        department=dept,
        job_type=job_type,
        description=description,
        apply_url=apply_url,
        salary=salary,
    )


async def _fetch_greenhouse_job_details(client: "httpx.AsyncClient", token: str, job_id: int, api_base: str = "https://boards-api.greenhouse.io", remix_base: str = "https://job-boards.greenhouse.io") -> dict:
    """
    Fetch individual job details using the Remix ?_data= pattern.
    Primary:  https://job-boards.greenhouse.io/{token}/jobs/{id}?_data=
    Fallback: https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}
    Returns a normalised dict with keys: title, location, description,
    employment_type, pay_ranges, department, published_at, apply_url.
    """
    # ── Strategy 1: Remix detail loader ──────────────────────────────────────
    try:
        remix_url = f"{remix_base}/{token}/jobs/{job_id}?_data="
        resp = await _greenhouse_get(client, remix_url)
        if resp.status_code == 200:
            data = resp.json()
            job_post = data.get("jobPost") or {}

            # Pay ranges — list of {min, max, currency, title}
            pay_ranges = [
                {
                    "min":      pr.get("min"),
                    "max":      pr.get("max"),
                    "currency": pr.get("currency", "USD"),
                    "title":    pr.get("title", ""),
                }
                for pr in (data.get("pay_ranges") or [])
                if pr.get("min") or pr.get("max")
            ]

            # Employment type
            emp = data.get("employment") or {}
            employment_type = emp.get("name", "") if isinstance(emp, dict) else str(emp)

            # Department
            depts = data.get("departments") or []
            department = depts[0].get("name", "") if depts and isinstance(depts[0], dict) else ""

            # Location
            location = (
                data.get("job_post_location") or
                (job_post.get("location") or {}).get("name") or
                ""
            )

            return {
                "id":              data.get("jobPostId") or job_id,
                "title":           job_post.get("title", ""),
                "location":        location,
                "description":     job_post.get("content", ""),
                "employment_type": employment_type,
                "pay_ranges":      pay_ranges,
                "department":      department,
                "published_at":    data.get("published_at", ""),
                "apply_url":       f"https://job-boards.greenhouse.io/{token}/jobs/{job_id}#app",
                "_source":         "remix",
            }
    except Exception as e:
        logger.debug(f"Greenhouse Remix detail failed for {job_id}: {e}")

    # ── Strategy 2: boards-api fallback ──────────────────────────────────────
    try:
        resp = await _greenhouse_get(
            client,
            f"{api_base}/v1/boards/{token}/jobs/{job_id}",
        )
        if resp.status_code == 200:
            data = resp.json()
            loc = data.get("location") or {}
            depts = data.get("departments") or []
            return {
                "id":              data.get("id") or job_id,
                "title":           data.get("title", ""),
                "location":        loc.get("name", "") if isinstance(loc, dict) else str(loc),
                "description":     data.get("content", ""),
                "employment_type": "",
                "pay_ranges":      [],
                "department":      depts[0].get("name", "") if depts else "",
                "published_at":    data.get("updated_at", ""),
                "apply_url":       data.get("absolute_url", ""),
                "_source":         "boards-api",
            }
    except Exception as e:
        logger.debug(f"Greenhouse boards-api detail failed for {job_id}: {e}")

    return {}


async def scrape_greenhouse(page: Page, url: str, company: str) -> list[ScrapedJob]:
    """
    Scrape Greenhouse jobs using three strategies in order:

    1. Remix paginated loader  (job-boards.greenhouse.io/?page=N&_data=)
       - New board format, paginated JSON, full descriptions
       - Fetches individual job details (?_data=) for pay_ranges + employment_type
       - Best for large boards (100s of jobs across multiple pages)

    2. Boards API  (boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true)
       - Classic single-request endpoint, all jobs + descriptions in one call
       - No pagination needed, simpler — best for smaller boards
       - Falls back automatically if Remix endpoint returns no data

    3. HTML scraping via Playwright  (boards.greenhouse.io/{token})
       - Last resort when both APIs are unavailable/disabled
       - Fetches individual job pages for descriptions (slow, capped at 15)

    Token extraction handles both URL formats:
      https://job-boards.greenhouse.io/{token}
      https://boards.greenhouse.io/{token}
    """
    jobs = []
    token = _extract_greenhouse_token(url)
    if not token:
        logger.warning(f"Could not extract Greenhouse token from {url}")
        return jobs

    # ── Cache check ──────────────────────────────────────────────────────────
    cached = _cache_get(token)
    if cached:
        return cached

    # ── Validate token / detect custom domain redirects ──────────────────────
    # Some companies use custom domains that 301/302 away from greenhouse.io.
    # A HEAD request on the board URL tells us if the token is valid before
    # we attempt any scraping.
    api_base, board_base, remix_base = _greenhouse_base_url(url)

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as probe:
            probe_resp = await probe.head(
                f"{board_base}/{token}",
                headers={"User-Agent": "JobStream/1.0"},
            )
            if probe_resp.status_code == 404:
                logger.error(f"Greenhouse: invalid token or board not found: {token}")
                return jobs
            # If final URL no longer contains greenhouse.io the company uses a
            # custom domain — log it but continue anyway (APIs may still work)
            if "greenhouse.io" not in str(probe_resp.url):
                logger.warning(
                    f"Greenhouse: {token} redirected to custom domain {probe_resp.url}. "
                    "API endpoints may still be available."
                )
    except Exception as e:
        logger.debug(f"Greenhouse probe failed for {token}: {e}")  # non-fatal

    # ── Strategy 1: Remix paginated loader ──────────────────────────────────
    # https://job-boards.greenhouse.io/{token}?page=N&_data=
    # Returns JSON: { jobPosts: { data: [...], total_pages: N } }
    try:
        raw_jobs = []
        pg = 1
        base = f"{remix_base}/{token}"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            while True:
                resp = await _greenhouse_get(client, f"{base}?page={pg}&_data=")
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

        # Fetch pay range details for jobs that have an id but no pay_range
        # (batch fetch up to 20 to avoid too many requests)
        ids_needing_details = [
            j.get("id") for j in raw_jobs
            if j.get("id") and not j.get("pay_range") and not j.get("salary_range")
        ][:20]

        detail_map = {}
        if ids_needing_details:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as detail_client:
                for jid in ids_needing_details:
                    detail = await _fetch_greenhouse_job_details(detail_client, token, jid, api_base, remix_base)
                    if detail:
                        detail_map[jid] = detail
                    await asyncio.sleep(0.15)

        for job in raw_jobs:
            jid = job.get("id")
            if jid and jid in detail_map:
                detail = detail_map[jid]
                # Merge: detail fields fill gaps, listing title/location take priority
                merged = {**detail, **{k: v for k, v in job.items() if v is not None and v != ""}}
                # Always prefer detail pay_ranges and employment_type (richer)
                if detail.get("pay_ranges"):
                    merged["pay_ranges"] = detail["pay_ranges"]
                if detail.get("employment_type"):
                    merged["employment_type"] = detail["employment_type"]
                if detail.get("description") and not job.get("content"):
                    merged["content"] = detail["description"]
                job = merged
            parsed = _parse_greenhouse_job(job, token, company, url)
            if parsed:
                jobs.append(parsed)

        if jobs:
            # Fetch descriptions for jobs that came back empty from the listing
            # (Remix listing API may omit content — detail endpoint has it)
            empty_desc = [j for j in jobs if not j.description]
            if empty_desc:
                logger.info(f"Greenhouse: fetching descriptions for {len(empty_desc)} jobs via detail API")
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as dc:
                    for job in empty_desc[:30]:  # cap at 30 detail requests
                        job_id = None
                        # Extract job ID from apply_url
                        import re as _re
                        m = _re.search(r'/jobs/(\d+)', job.apply_url)
                        if m:
                            job_id = int(m.group(1))
                            detail = await _fetch_greenhouse_job_details(dc, token, job_id, api_base, remix_base)
                            if detail.get("description"):
                                job.description = _clean_html(detail["description"])
                            if detail.get("pay_ranges") and not job.salary:
                                # Re-parse salary from detail
                                tmp = _parse_greenhouse_job(
                                    {**detail, "pay_ranges": detail["pay_ranges"]},
                                    token, job.company, job.source_url
                                )
                                if tmp and tmp.salary:
                                    job.salary = tmp.salary
                        await asyncio.sleep(0.2)
            logger.info(f"Greenhouse Remix API: {len(jobs)} jobs from {token} ({pg} pages)")
            _cache_set(token, jobs)
            return jobs

    except Exception as e:
        logger.warning(f"Greenhouse Remix loader failed for {token}: {e}")

    # ── Strategy 2: boards-api.greenhouse.io JSON API ────────────────────────
    # Classic endpoint, returns all jobs in one call with full content
    try:
        api_url = f"{api_base}/v1/boards/{token}/jobs?content=true"
        async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
            resp = await _greenhouse_get(client, api_url)
            resp.raise_for_status()
            data = resp.json()

        for job in data.get("jobs", []):
            parsed = _parse_greenhouse_job(job, token, company, url)
            if parsed:
                jobs.append(parsed)

        if jobs:
            logger.info(f"Greenhouse boards-api: {len(jobs)} jobs from {token}")
            _cache_set(token, jobs)
            return jobs

    except Exception as e:
        logger.warning(f"Greenhouse boards-api failed for {token}: {e}")

    # ── Strategy 3: HTML fallback via Playwright ─────────────────────────────
    # Note: Playwright may not be available in all environments (e.g. Windows
    # event loop, Railway containers without browsers). Catch all errors here
    # so a Playwright failure never prevents strategies 1 & 2 results.
    if page is None:
        logger.debug(f"Greenhouse: no Playwright page available, skipping HTML fallback for {token}")
        return jobs
    try:
        board_url = f"{board_base}/{token}"
        await page.goto(board_url, wait_until="networkidle", timeout=25000)
        soup = BeautifulSoup(await page.content(), "html.parser")
        for section in soup.select(".opening"):
            title_el = section.select_one("a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            apply_url = f"{board_base}{href}" if href.startswith("/") else href
            loc_el = section.select_one(".location")
            location = loc_el.get_text(strip=True) if loc_el else "Remote"
            dept = "General"
            parent = section.find_parent("section")
            if parent:
                h2 = parent.select_one("h2, h3")
                if h2:
                    dept = h2.get_text(strip=True)
            jobs.append(ScrapedJob(
                title=title, company=company, source_url=url,
                location=location, department=dept,
                job_type=_infer_job_type(title), apply_url=apply_url,
            ))
        for job in jobs[:15]:
            if job.apply_url:
                job.description = await fetch_job_description(page, job.apply_url)
        logger.info(f"Greenhouse HTML fallback: {len(jobs)} jobs from {token}")
        if jobs:
            _cache_set(token, jobs)
    except NotImplementedError:
        logger.warning(f"Greenhouse: Playwright not available in this environment (Windows/no-browser). "
                       f"Only API strategies used for {token}.")
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
    if "odoo" in url.lower() or "/jobs" in url:
        return "odoo"
    return "generic"


async def scrape_company(url: str, company: str, industry: str = "", logo_url: str = "") -> list[ScrapedJob]:
    ats = detect_ats(url)
    logger.info(f"Scraping {company} ({url}) via {ats} strategy")

    # Oracle uses direct HTTP API calls — no browser needed
    if ats == "oracle":
        jobs = await scrape_oracle_hcm(url, company)
        return _apply_industry(jobs, industry)

    # Greenhouse uses HTTP API calls (Remix loader + boards-api) — no browser needed
    # Playwright is only used as a last-resort fallback inside scrape_greenhouse itself
    if ats == "greenhouse":
        jobs = await scrape_greenhouse(None, url, company)
        return _apply_industry(jobs, industry)

    # All other ATS use browser for JS rendering
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
                if ats == "workday":
                    jobs = await scrape_workday(url, company, page=page)
                elif ats == "odoo":
                    jobs = await scrape_odoo(page, url, company)
                elif ats == "lever":
                    jobs = await scrape_lever(page, url, company)
                else:
                    jobs = await scrape_generic(page, url, company)
            finally:
                await browser.close()
    except NotImplementedError:
        logger.warning(f"Playwright not available in this environment — skipping {company} ({ats})")
        jobs = []

    logger.info(f"  -> Found {len(jobs)} jobs at {company}")
    jobs = _apply_industry(jobs, industry)
    if logo_url:
        for j in jobs:
            if not j.logo_url:
                j.logo_url = logo_url
    return jobs


def _apply_industry(jobs: list[ScrapedJob], industry: str) -> list[ScrapedJob]:
    """Stamp every scraped job with the company's configured industry."""
    if industry:
        for j in jobs:
            j.industry = industry
    return jobs



# ---------------------------------------------------------------------------
# Oracle HCM adapter
# Converts OracleCloudScraper output to ScrapedJob dataclass
# ---------------------------------------------------------------------------

def scrape_oracle(company_name: str, careers_url: str, industry: str = "") -> list[ScrapedJob]:
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
            industry=industry,
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
            jobs = scrape_oracle(company["name"], company["url"], company.get("industry", ""))
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
                return await scrape_company(c["url"], c["name"], c.get("industry", ""), c.get("logo_url", ""))

        results = await asyncio.gather(
            *[guarded_scrape(c) for c in browser_cos], return_exceptions=True
        )
        for r in results:
            if isinstance(r, list):
                all_jobs.extend(r)
            else:
                logger.error(f"Scrape error: {r}")

    return all_jobs

