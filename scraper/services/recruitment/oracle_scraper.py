"""
Oracle Cloud HCM Careers Scraper
Reference: https://jobo.world/ats/oraclecloud

Key insight: Oracle returns description in THREE separate fields:
  - ExternalDescriptionStr       (job overview / about the role)
  - ExternalQualificationsStr    (qualifications & requirements)
  - ExternalResponsibilitiesStr  (key responsibilities)

All three must be combined for the full job description.
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
    Convert Oracle HTML to clean text with **bold** headings and bullet points.
    App.jsx JobCard renderer converts these to styled React elements.
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


def build_full_description(detail: dict) -> str:
    """
    Combine Oracle's three description fields into one formatted description.
    ExternalDescriptionStr     = About the role / Job Purpose
    ExternalResponsibilitiesStr = Key Responsibilities
    ExternalQualificationsStr  = Qualifications & Requirements
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

    # Also grab flex fields (custom fields some Oracle tenants use)
    flex_fields = detail.get("requisitionFlexFields", [])
    if flex_fields:
        flex_lines = []
        for f in flex_fields:
            prompt = f.get("Prompt", "")
            value = f.get("Value", "")
            if prompt and value:
                flex_lines.append(f"\u2022 {prompt}: {value}")
        if flex_lines:
            sections.append("**Additional Information**\n\n" + "\n".join(flex_lines))

    # Skills list
    skills = detail.get("skills", [])
    if skills:
        skill_list = [s.get("Skill", "") for s in skills if s.get("Skill")]
        if skill_list:
            sections.append("**Required Skills**\n\n" + "\n".join(f"\u2022 {s}" for s in skill_list))

    return "\n\n".join(sections).strip()


def discover_site_number(careers_url: str, session: requests.Session) -> str:
    match = re.search(r"/sites/([^/?#]+)", careers_url)
    if match:
        site = match.group(1).rstrip("/")
        if site:
            logger.info(f"Site number from URL: {site}")
            return site
    try:
        resp = session.get(careers_url, timeout=15, headers=_required_headers())
        m = re.search(r"siteNumber:\s*['\"]?(CX_\d+)['\"]?", resp.text)
        if m:
            logger.info(f"Site number from JS: {m.group(1)}")
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
            "onlyData": "true",
            "siteNumber": site_number,
            "limit": limit, "offset": offset,
        }, headers=_required_headers(), timeout=20),
    ]
    last_error = None
    for i, make_req in enumerate(formats):
        try:
            resp = make_req()
            if resp.status_code == 200:
                logger.info(f"Oracle list format {i+1} succeeded")
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
            logger.error(f"Oracle list API failed at offset {offset}: {e}")
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


def get_job_details(domain: str, site_number: str, job_id: str,
                    session: requests.Session) -> Optional[dict]:
    """
    Fetch full job details from Oracle Cloud API.
    Exact implementation from jobo.world/ats/oraclecloud guide.
    Returns dict with ExternalDescriptionStr, ExternalQualificationsStr,
    ExternalResponsibilitiesStr, skills, requisitionFlexFields etc.
    """
    url = f"https://{domain}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"

    # Try with quoted ID first (standard), then unquoted fallback
    for finder in [
        f'ById;Id="{job_id}",siteNumber={site_number}',
        f"ById;Id={job_id},siteNumber={site_number}",
    ]:
        params = {
            "expand": "all",
            "onlyData": "true",
            "finder": finder,
        }
        for attempt in range(2):
            try:
                response = session.get(
                    url, params=params,
                    headers=_required_headers(),
                    timeout=45,
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("items"):
                        detail = data["items"][0]
                        # Log what fields we got
                        has_desc  = bool(detail.get("ExternalDescriptionStr", "").strip())
                        has_resp  = bool(detail.get("ExternalResponsibilitiesStr", "").strip())
                        has_qual  = bool(detail.get("ExternalQualificationsStr", "").strip())
                        logger.info(
                            f"Detail for {job_id}: "
                            f"desc={has_desc} resp={has_resp} qual={has_qual}"
                        )
                        return detail
                elif response.status_code in (400, 404):
                    break  # try next finder format
            except requests.exceptions.Timeout:
                if attempt == 0:
                    logger.warning(f"Detail timeout for job {job_id}, retrying in 3s...")
                    time.sleep(3)
                    continue
                logger.warning(f"Detail fetch gave up for job {job_id}")
                return None
            except Exception as e:
                logger.warning(f"Detail fetch error for job {job_id}: {e}")
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
        or raw.get("Location")
        or (detail or {}).get("PrimaryLocation") or "Not specified"
    )
    if isinstance(location, list):
        location = ", ".join(location)

    raw_type = (raw.get("WorkerType") or raw.get("workerType") or "").upper()
    type_map = {
        "FULL_TIME": "Full-time", "PART_TIME": "Part-time",
        "CONTRACT": "Contract", "TEMPORARY": "Contract", "INTERN": "Internship",
    }
    job_type = type_map.get(raw_type, "Full-time")

    # Build full description from all three Oracle fields
    if detail:
        description = build_full_description(detail)
    else:
        # Fallback to short description from list API
        description = html_to_readable(
            raw.get("ShortDescriptionStr", "")
            or raw.get("ShortDescription", "")
        )

    department = (
        raw.get("CategoryLabel") or raw.get("PrimaryJobCategory")
        or (detail or {}).get("PrimaryJobCategory") or "General"
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
    """
    Oracle HCM scraper — fetches all three description fields per job.
    """
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
                f"— {len(job['description'])} chars"
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
    scraper = OracleCloudScraper(careers_url=url, company_name=company)
    jobs = scraper.run()
    for j in jobs[:2]:
        print(f"\n=== {j['title']} ===\n{j['description'][:800]}\n")
    print(f"Total: {len(jobs)} jobs")
