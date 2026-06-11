"""
Oracle Cloud HCM Careers Scraper
Based on: https://jobo.world/ats/oraclecloud

Uses Oracle REST API + page scraping fallback for full descriptions.
"""

import re
import time
import uuid
import html as html_module
import json as json_mod
import logging
from typing import Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=3, backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _required_headers() -> dict:
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


def html_to_readable(html_str: str) -> str:
    """
    Convert Oracle HTML job description to clean readable text.
    Output uses **bold** for headings and bullet for lists.
    The JobCard renderer in App.jsx converts these to styled React elements.
    """
    if not html_str or not html_str.strip():
        return ""

    text = html_module.unescape(html_str)

    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "\u2022 ", text, flags=re.IGNORECASE)
    text = re.sub(r"</ul>|</ol>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<ul[^>]*>|<ol[^>]*>", "\n", text, flags=re.IGNORECASE)

    for tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
        text = re.sub(f"<{tag}[^>]*>", "\n\n**", text, flags=re.IGNORECASE)
        text = re.sub(f"</{tag}>", "**\n", text, flags=re.IGNORECASE)

    text = re.sub(r"<strong[^>]*>|<b[^>]*>", "**", text, flags=re.IGNORECASE)
    text = re.sub(r"</strong>|</b>", "**", text, flags=re.IGNORECASE)

    text = re.sub(r"<[^>]+>", "", text)

    lines = []
    for line in text.split("\n"):
        line = re.sub(r" {2,}", " ", line.strip())
        lines.append(line)

    result = []
    blank_count = 0
    for line in lines:
        if line == "":
            blank_count += 1
            if blank_count <= 1:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)

    return "\n".join(result).strip()


def discover_site_number(careers_url: str, session: requests.Session) -> str:
    """Extract Oracle site number from URL or page."""
    match = re.search(r"/sites/([^/?#]+)", careers_url)
    if match:
        site = match.group(1).rstrip("/")
        if site:
            logger.info(f"Site number from URL: {site}")
            return site

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
    """Try multiple Oracle API parameter formats until one succeeds."""
    formats = [
        lambda: session.get(url, params={
            "onlyData": "true",
            "expand": "requisitionList.workLocation,requisitionList.secondaryLocations",
            "finder": f"findReqs;siteNumber={site_number}",
            "limit": limit,
            "offset": offset,
        }, headers=_required_headers(), timeout=20),
        lambda: session.get(url, params={
            "onlyData": "true",
            "finder": f"findReqs;siteNumber={site_number},limit={limit},offset={offset}",
        }, headers=_required_headers(), timeout=20),
        lambda: session.get(url, params={
            "onlyData": "true",
            "siteNumber": site_number,
            "limit": limit,
            "offset": offset,
        }, headers=_required_headers(), timeout=20),
    ]

    last_error = None
    for i, make_req in enumerate(formats):
        try:
            resp = make_req()
            if resp.status_code == 200:
                logger.info(f"Oracle format {i+1} succeeded")
                return resp.json()
            last_error = f"{resp.status_code}: {resp.text[:100]}"
        except Exception as e:
            last_error = str(e)
    raise Exception(f"All Oracle list formats failed. Last: {last_error}")


def fetch_all_jobs(
    domain: str,
    site_number: str,
    session: requests.Session,
    limit: int = 25,
) -> list[dict]:
    """Paginate through all job requisitions."""
    url = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    all_jobs = []
    offset = 0
    total = None

    while True:
        try:
            data = _try_fetch_page(url, site_number, offset, limit, session)
        except Exception as e:
            logger.error(f"Oracle API failed at offset {offset}: {e}")
            break

        items = data.get("items", [])
        if not items:
            break

        page_jobs = []
        for item in items:
            page_jobs.extend(item.get("requisitionList", []))
            if total is None:
                total = item.get("TotalJobsCount", 0)

        all_jobs.extend(page_jobs)
        logger.info(f"Oracle: fetched {len(all_jobs)} / {total or '?'} jobs")

        if not data.get("hasMore", False) or len(page_jobs) == 0:
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
    """
    Fetch full job description via API.
    Tries 4 different Oracle API formats.
    """
    base = f"https://{domain}"
    detail_url = f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    desc_url = f"{base}/hcmRestApi/resources/latest/recruitingCEJobDescription"

    strategies = [
        (detail_url, {"onlyData": "true", "expand": "all",
                      "finder": 'ById;Id="' + job_id + '",siteNumber=' + site_number}),
        (detail_url, {"onlyData": "true",
                      "finder": "ById;Id=" + job_id + ",siteNumber=" + site_number}),
        (desc_url,   {"onlyData": "true",
                      "finder": 'ByCandidateJobDescriptionId;siteNumber=' + site_number + ',Id="' + job_id + '"'}),
        (detail_url, {"onlyData": "true",
                      "finder": "ById;siteNumber=" + site_number + ",Id=" + job_id}),
    ]

    for i, (url, params) in enumerate(strategies):
        try:
            resp = session.get(url, params=params,
                               headers=_required_headers(), timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", [])
                if items:
                    logger.debug(f"Detail strategy {i+1} succeeded for job {job_id}")
                    return items[0]
            elif resp.status_code in (400, 404, 422):
                continue
        except requests.exceptions.Timeout:
            logger.debug(f"Detail strategy {i+1} timed out for job {job_id}")
            continue
        except Exception as e:
            logger.debug(f"Detail strategy {i+1} error: {e}")
            continue

    return None


def _find_description_in_json(obj, depth=0) -> str:
    """Recursively search JSON data for a description field."""
    if depth > 8:
        return ""
    if isinstance(obj, dict):
        for key in ["ExternalDescriptionStr", "ExternalDescription",
                    "description", "jobDescription", "fullDescription",
                    "ShortDescriptionStr"]:
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 200:
                return obj[key]
        for v in obj.values():
            result = _find_description_in_json(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj[:10]:
            result = _find_description_in_json(item, depth + 1)
            if result:
                return result
    return ""


def fetch_description_from_page(
    domain: str,
    site_number: str,
    req_number: str,
    session: requests.Session,
) -> str:
    """
    Scrape the public job detail page for full description.
    Used when API returns only short description.
    """
    url = (
        "https://" + domain
        + "/hcmUI/CandidateExperience/en/sites/"
        + site_number + "/job/" + req_number
    )

    try:
        resp = session.get(url, headers={
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        }, timeout=30)

        if resp.status_code != 200:
            return ""

        page_html = resp.text

        # Search JSON script tags first (most reliable)
        script_tag_re = re.compile(
            r"<script[^>]+type=[^>]*application/json[^>]*>(.*?)</script>",
            re.DOTALL | re.IGNORECASE,
        )
        for m in script_tag_re.finditer(page_html):
            try:
                data = json_mod.loads(m.group(1))
                desc = _find_description_in_json(data)
                if desc and len(desc) > 200:
                    logger.debug(f"Found description in JSON for {req_number}")
                    return html_to_readable(desc)
            except Exception:
                continue

        # Then try common Oracle CSS class patterns
        class_patterns = [
            "job-description", "jobDescription",
            "description-content", "job-details",
        ]
        for cls in class_patterns:
            pattern = (
                r"<div[^>]+class=[^>]*" + cls + r"[^>]*>(.*?)</div>"
            )
            m = re.search(pattern, page_html, re.DOTALL | re.IGNORECASE)
            if m and len(m.group(1)) > 200:
                logger.debug(f"Found description via CSS class {cls}")
                return html_to_readable(m.group(1))

        return ""

    except Exception as e:
        logger.debug(f"Page fetch failed for {req_number}: {e}")
        return ""


def normalize_job(
    raw: dict,
    detail: Optional[dict],
    page_description: str,
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
        raw.get("Title") or raw.get("title")
        or (detail or {}).get("Title")
        or "Untitled Position"
    )

    location = (
        raw.get("PrimaryLocation") or raw.get("primaryLocation")
        or raw.get("Location")
        or (detail or {}).get("PrimaryLocation")
        or "Not specified"
    )
    if isinstance(location, list):
        location = ", ".join(location)

    raw_type = (raw.get("WorkerType") or raw.get("workerType") or "").upper()
    type_map = {
        "FULL_TIME": "Full-time", "PART_TIME": "Part-time",
        "CONTRACT": "Contract", "TEMPORARY": "Contract",
        "INTERN": "Internship",
    }
    job_type = type_map.get(raw_type, "Full-time")

    # Build description — try in priority order
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

    api_description = html_to_readable(raw_html)

    # Use page description if it's substantially longer than API description
    if page_description and len(page_description) > len(api_description) + 100:
        description = page_description
        logger.debug(f"Using page description for {title[:40]} ({len(description)} chars)")
    else:
        description = api_description
        logger.debug(f"Using API description for {title[:40]} ({len(description)} chars)")

    department = (
        raw.get("CategoryLabel") or raw.get("PrimaryJobCategory")
        or (detail or {}).get("PrimaryJobCategory")
        or "General"
    )

    apply_url = (
        "https://" + domain
        + "/hcmUI/CandidateExperience/en/sites/"
        + site_number + "/job/" + req_number
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
    API first, falls back to page scraping for full descriptions.
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

        parsed = urlparse(self.careers_url)
        domain = parsed.netloc
        site_number = discover_site_number(self.careers_url, self._session)
        logger.info(f"Domain: {domain} | Site: {site_number}")

        raw_jobs = fetch_all_jobs(domain, site_number, self._session)
        logger.info(f"Raw jobs: {len(raw_jobs)}")

        normalized = []
        for i, raw in enumerate(raw_jobs):
            job_id = str(raw.get("Id") or raw.get("id") or "")
            req_number = str(
                raw.get("RequisitionNumber")
                or raw.get("requisitionNumber")
                or job_id
            )

            # Step 1: Try API detail fetch
            detail = None
            if self.fetch_details and job_id:
                detail = fetch_job_detail(domain, site_number, job_id, self._session)
                time.sleep(0.3)

            # Step 2: Check if we got a full description from API
            api_html = ""
            if detail:
                api_html = (
                    detail.get("ExternalDescriptionStr", "")
                    or detail.get("ExternalDescription", "")
                    or detail.get("ShortDescriptionStr", "")
                )
            if not api_html:
                api_html = raw.get("ShortDescriptionStr", "")

            api_desc = html_to_readable(api_html)

            # Step 3: If API description is short (<300 chars), scrape the page
            page_desc = ""
            if len(api_desc) < 300 and req_number:
                logger.info(
                    f"API desc short ({len(api_desc)} chars) for job {i+1}, "
                    f"trying page scrape..."
                )
                page_desc = fetch_description_from_page(
                    domain, site_number, req_number, self._session
                )
                if page_desc:
                    logger.info(f"Page scrape got {len(page_desc)} chars for job {i+1}")
                time.sleep(0.5)

            job = normalize_job(
                raw=raw,
                detail=detail,
                page_description=page_desc,
                company_name=self.company_name,
                source_url=self.careers_url,
                domain=domain,
                site_number=site_number,
            )
            normalized.append(job)

            desc_len = len(job.get("description", ""))
            logger.info(
                f"Job {i+1}/{len(raw_jobs)}: {job.get('title','?')[:40]} "
                f"— {desc_len} chars"
            )

        logger.info(f"Oracle complete: {len(normalized)} jobs for {self.company_name}")
        return normalized


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/jobsearch"
    )
    company = sys.argv[2] if len(sys.argv) > 2 else "Test Company"
    scraper = OracleCloudScraper(careers_url=url, company_name=company, fetch_details=True)
    jobs = scraper.run()
    for j in jobs[:3]:
        print(f"\n=== {j['title']} ===")
        print(j["description"][:500])
    print(f"\nTotal: {len(jobs)} jobs")
