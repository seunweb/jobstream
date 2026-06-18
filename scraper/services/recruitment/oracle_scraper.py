"""
Oracle Cloud HCM Careers Scraper — v2
Key insight: Oracle returns description in THREE separate fields:
  ExternalDescriptionStr, ExternalResponsibilitiesStr, ExternalQualificationsStr

When the detail API returns empty fields, we scrape the public job page
which renders the full description in the DOM (often after the Apply button).
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
    retry = Retry(total=3, backoff_factor=1.0,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"])
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
    """Convert Oracle HTML to clean text with **bold** headings and bullet points."""
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


def build_full_description(detail: dict) -> str:
    """
    Combine Oracle's three description fields into one formatted description.
    """
    sections = []
    desc = detail.get("ExternalDescriptionStr", "").strip()
    if desc:
        sections.append(html_to_readable(desc))

    responsibilities = detail.get("ExternalResponsibilitiesStr", "").strip()
    if responsibilities:
        cleaned = html_to_readable(responsibilities)
        if cleaned:
            sections.append("**Key Responsibilities**\n\n" + cleaned)

    qualifications = detail.get("ExternalQualificationsStr", "").strip()
    if qualifications:
        cleaned = html_to_readable(qualifications)
        if cleaned:
            sections.append("**Qualifications & Requirements**\n\n" + cleaned)

    flex_fields = detail.get("requisitionFlexFields", [])
    if flex_fields:
        lines = []
        for f in flex_fields:
            prompt = f.get("Prompt", "")
            value = f.get("Value", "")
            if prompt and value:
                lines.append(f"\u2022 {prompt}: {value}")
        if lines:
            sections.append("**Additional Information**\n\n" + "\n".join(lines))

    skills = detail.get("skills", [])
    if skills:
        skill_list = [s.get("Skill", "") for s in skills if s.get("Skill")]
        if skill_list:
            sections.append("**Required Skills**\n\n" + "\n".join(f"\u2022 {s}" for s in skill_list))

    return "\n\n".join(sections).strip()


def scrape_job_page_description(
    domain: str,
    site_number: str,
    req_number: str,
    session: requests.Session,
) -> str:
    """
    Scrape full job description from the public Oracle CX job page.
    Oracle renders all job info in the page HTML — often after the Apply button.
    Tries multiple extraction strategies.
    """
    url = (
        f"https://{domain}/hcmUI/CandidateExperience"
        f"/en/sites/{site_number}/job/{req_number}"
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
            logger.debug(f"Page scrape {resp.status_code} for {url}")
            return ""

        page = resp.text

        # Strategy 1: JSON data embedded in <script type="application/json">
        for m in re.finditer(
            r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>',
            page, re.DOTALL | re.IGNORECASE
        ):
            try:
                data = json_mod.loads(m.group(1))
                desc = _find_description_in_json(data)
                if desc and len(desc) > 100:
                    logger.info(f"Oracle page: found description in JSON ({len(desc)} chars)")
                    return html_to_readable(desc)
            except Exception:
                continue

        # Strategy 2: Look for Oracle-specific content sections in HTML
        # Oracle CX renders job description in divs with data-bind or specific classes
        # The content often appears in a section after the apply button

        # Try known Oracle DOM patterns
        patterns = [
            # Oracle CX standard section containers
            r'<div[^>]+class=["\'][^"\']*requisition-info[^"\']*["\'][^>]*>(.*?)</div\s*>',
            r'<div[^>]+class=["\'][^"\']*job-description[^"\']*["\'][^>]*>(.*?)</div\s*>',
            r'<section[^>]+class=["\'][^"\']*job-detail[^"\']*["\'][^>]*>(.*?)</section\s*>',
            # Data-bind patterns Oracle uses
            r'<div[^>]+data-bind=["\'][^"\']*description[^"\']*["\'][^>]*>(.*?)</div\s*>',
            # Knockout.js template content
            r'<!-- ko[^>]*description[^>]*-->(.*?)<!-- /ko -->',
        ]
        for pattern in patterns:
            m = re.search(pattern, page, re.DOTALL | re.IGNORECASE)
            if m and len(m.group(1)) > 100:
                text = html_to_readable(m.group(1))
                if text:
                    logger.info(f"Oracle page: found via pattern ({len(text)} chars)")
                    return text

        # Strategy 3: Extract all visible text between known Oracle landmarks
        # Find content that appears after "Job Description" heading
        # Oracle pages typically have: Job Details | Apply | Description sections
        heading_patterns = [
            r'(?:Job Description|About the Role|Job Summary|Role Overview)'
            r'</[^>]+>\s*</[^>]+>(.*?)(?=<(?:button|a)[^>]*apply|$)',
        ]
        for pattern in heading_patterns:
            m = re.search(pattern, page, re.DOTALL | re.IGNORECASE)
            if m and len(m.group(1)) > 100:
                text = html_to_readable(m.group(1)[:5000])
                if len(text) > 100:
                    logger.info(f"Oracle page: found via heading search ({len(text)} chars)")
                    return text

        # Strategy 4: Extract large text blocks from the page
        # Remove script/style, then find largest coherent text block
        clean = re.sub(r'<script[^>]*>.*?</script>', '', page, flags=re.DOTALL)
        clean = re.sub(r'<style[^>]*>.*?</style>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<nav[^>]*>.*?</nav>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<header[^>]*>.*?</header>', '', clean, flags=re.DOTALL)
        clean = re.sub(r'<footer[^>]*>.*?</footer>', '', clean, flags=re.DOTALL)

        # Find divs with substantial text content
        div_contents = re.findall(r'<div[^>]*>((?:(?!<div).){200,})</div>', clean, re.DOTALL)
        if div_contents:
            best = max(div_contents, key=len)
            text = html_to_readable(best)
            if len(text) > 150:
                logger.info(f"Oracle page: found via largest div ({len(text)} chars)")
                return text

        logger.warning(f"Oracle page scrape: no description found at {url}")
        return ""

    except Exception as e:
        logger.warning(f"Oracle page scrape failed for {req_number}: {e}")
        return ""


def _find_description_in_json(obj, depth=0) -> str:
    """Recursively search JSON data for a description field."""
    if depth > 8:
        return ""
    if isinstance(obj, dict):
        for key in ["ExternalDescriptionStr", "ExternalDescription",
                    "ShortDescriptionStr", "description", "jobDescription",
                    "fullDescription", "Body", "Content"]:
            if key in obj and isinstance(obj[key], str) and len(obj[key]) > 100:
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


def discover_site_number(careers_url: str, session: requests.Session) -> str:
    match = re.search(r"/sites/([^/?#]+)", careers_url)
    if match:
        site = match.group(1).rstrip("/")
        if site:
            return site
    try:
        resp = session.get(careers_url, timeout=15, headers=_required_headers())
        m = re.search(r"siteNumber:\s*['\"]?(CX_\d+)['\"]?", resp.text)
        if m:
            return m.group(1)
    except Exception as e:
        logger.warning(f"Could not fetch careers page: {e}")
    raise ValueError(f"Could not discover Oracle site number from {careers_url}")


def _try_fetch_page(url, site_number, offset, limit, session):
    formats = [
        lambda: session.get(url, params={
            "onlyData": "true",
            "expand": "requisitionList.workLocation,requisitionList.secondaryLocations",
            "finder": f"findReqs;siteNumber={site_number}",
            "limit": limit, "offset": offset,
        }, headers=_required_headers(), timeout=20),
        lambda: session.get(url, params={
            "onlyData": "true",
            "finder": f"findReqs;siteNumber={site_number},limit={limit},offset={offset}",
        }, headers=_required_headers(), timeout=20),
        lambda: session.get(url, params={
            "onlyData": "true", "siteNumber": site_number,
            "limit": limit, "offset": offset,
        }, headers=_required_headers(), timeout=20),
    ]
    last_error = None
    for make_req in formats:
        try:
            resp = make_req()
            if resp.status_code == 200:
                return resp.json()
            last_error = f"{resp.status_code}"
        except Exception as e:
            last_error = str(e)
    raise Exception(f"All Oracle list formats failed. Last: {last_error}")


def fetch_all_jobs(domain, site_number, session, limit=25):
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
        for item in items:
            all_jobs.extend(item.get("requisitionList", []))
            if total is None:
                total = item.get("TotalJobsCount", 0)
        logger.info(f"Oracle: fetched {len(all_jobs)} / {total or '?'} jobs")
        if not data.get("hasMore", False) or len(all_jobs) >= (total or 9999):
            break
        offset += limit
        time.sleep(0.5)
    return all_jobs


def get_job_details(domain: str, site_number: str, job_id: str,
                    session: requests.Session) -> Optional[dict]:
    """Fetch full job details. Tries quoted then unquoted finder format."""
    url = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
    for finder in [
        f'ById;Id="{job_id}",siteNumber={site_number}',
        f"ById;Id={job_id},siteNumber={site_number}",
    ]:
        params = {"expand": "all", "onlyData": "true", "finder": finder}
        for attempt in range(2):
            try:
                response = session.get(url, params=params,
                                       headers=_required_headers(), timeout=45)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("items"):
                        detail = data["items"][0]
                        has_desc = bool(detail.get("ExternalDescriptionStr", "").strip())
                        has_resp = bool(detail.get("ExternalResponsibilitiesStr", "").strip())
                        has_qual = bool(detail.get("ExternalQualificationsStr", "").strip())
                        logger.info(f"Detail {job_id}: desc={has_desc} resp={has_resp} qual={has_qual}")
                        return detail
                elif response.status_code in (400, 404):
                    break
            except requests.exceptions.Timeout:
                if attempt == 0:
                    logger.warning(f"Detail timeout for {job_id}, retrying...")
                    time.sleep(3)
                    continue
                logger.warning(f"Detail fetch gave up for {job_id}")
                return None
            except Exception as e:
                logger.warning(f"Detail fetch error {job_id}: {e}")
                return None
    return None


def normalize_job(raw, detail, company_name, source_url, domain, site_number):
    job_id = str(raw.get("Id") or raw.get("id") or "")
    req_number = str(
        raw.get("RequisitionNumber") or raw.get("requisitionNumber") or job_id
    )
    title = (
        raw.get("Title") or raw.get("title")
        or (detail or {}).get("Title") or "Untitled Position"
    )
    location = (
        raw.get("PrimaryLocation") or raw.get("primaryLocation")
        or raw.get("Location") or (detail or {}).get("PrimaryLocation")
        or "Not specified"
    )
    if isinstance(location, list):
        location = ", ".join(location)

    raw_type = (raw.get("WorkerType") or raw.get("workerType") or "").upper()
    type_map = {
        "FULL_TIME": "Full-time", "PART_TIME": "Part-time",
        "CONTRACT": "Contract", "TEMPORARY": "Contract", "INTERN": "Internship",
    }
    job_type = type_map.get(raw_type, "Full-time")

    # Build description from detail API fields
    description = ""
    if detail:
        description = build_full_description(detail)

    # If API gave us nothing, scrape the public job page
    if not description or len(description.strip()) < 50:
        logger.info(f"API description empty for '{title}' — scraping job page...")
        page_desc = scrape_job_page_description(domain, site_number, req_number, _build_session())
        if page_desc and len(page_desc) > len(description):
            description = page_desc
            logger.info(f"Page scrape got {len(description)} chars for '{title}'")

    # Last resort: use short description from list API
    if not description:
        description = html_to_readable(
            raw.get("ShortDescriptionStr", "") or raw.get("ShortDescription", "")
        )

    # Department from category
    department = (
        raw.get("CategoryLabel") or raw.get("PrimaryJobCategory")
        or (detail or {}).get("PrimaryJobCategory") or ""
    )

    apply_url = (
        f"https://{domain}/hcmUI/CandidateExperience"
        f"/en/sites/{site_number}/job/{req_number}"
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
    def __init__(self, careers_url, company_name="Unknown", fetch_details=True):
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
            detail = None
            if self.fetch_details and job_id:
                detail = get_job_details(domain, site_number, job_id, self._session)
                time.sleep(0.5)

            job = normalize_job(
                raw=raw, detail=detail,
                company_name=self.company_name,
                source_url=self.careers_url,
                domain=domain, site_number=site_number,
            )
            normalized.append(job)
            logger.info(
                f"Job {i+1}/{len(raw_jobs)}: {job['title'][:45]} "
                f"— {len(job['description'])} chars desc"
            )

        logger.info(f"Oracle complete: {len(normalized)} jobs for {self.company_name}")
        return normalized


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    url = sys.argv[1] if len(sys.argv) > 1 else (
        "https://ehle.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs"
    )
    company = sys.argv[2] if len(sys.argv) > 2 else "MTN Nigeria"
    scraper = OracleCloudScraper(careers_url=url, company_name=company)
    jobs = scraper.run()
    for j in jobs[:3]:
        print(f"\n=== {j['title']} ===\n{j['description'][:600]}\n")
    print(f"Total: {len(jobs)} jobs")
