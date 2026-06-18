"""
Job Classification Heuristics
Infers job_type and department from job title and description.
Only overrides generic defaults — never overwrites values already set.
"""

import re


# ── Job type detection ────────────────────────────────────────────────────────

_JOB_TYPE_PATTERNS = [
    (r"\b(intern(ship)?|graduate\s+trainee|industrial\s+training|siwes|nysc|attachment)\b", "Internship"),
    (r"\b(contract(or)?|fixed[\s-]?term|temporary|temp\b|consultant|freelance|outsource)\b", "Contract"),
    (r"\bpart[\s-]?time\b", "Part-time"),
]


def detect_job_type(title: str, description: str = "") -> str:
    text = f"{title} {description[:300]}".lower()
    for pattern, job_type in _JOB_TYPE_PATTERNS:
        if re.search(pattern, text):
            return job_type
    return "Full-time"


# ── Department detection ──────────────────────────────────────────────────────
# Each entry: (department_name, [keywords that indicate this department])
# Keywords are checked against the job TITLE first, then description.
# More specific patterns come first to avoid false matches.

_DEPT_KEYWORDS = [
    ("Healthcare", [
        "nurse", "doctor", "physician", "pharmacist", "medical officer", "clinical",
        "healthcare", "laboratory scientist", "radiographer", "dentist", "surgeon",
        "pathologist", "midwife", "dietitian", "physiotherapist", "optometrist",
    ]),
    ("Legal & Compliance", [
        "legal", "counsel", "lawyer", "attorney", "compliance", "regulatory affairs",
        "company secretary", "paralegal", "litigation",
    ]),
    ("Finance & Accounting", [
        "accountant", "accounting", "finance", "financial analyst", "financial controller",
        "treasury", "tax", "audit", "auditor", "bookkeeper", "credit control",
        "financial planning", "revenue assurance", "budget", "cost control",
        "management accountant", "chief financial",
    ]),
    ("Human Resources", [
        "human resources", "hr ", "recruiter", "recruitment", "talent acquisition",
        "talent management", "people operations", "hr business partner",
        "learning and development", "compensation", "benefits", "payroll",
        "employee relations", "workforce planning", "organizational development",
    ]),
    ("Sales & Business Development", [
        "sales", "business development", "account manager", "account executive",
        "key account", "channel manager", "partnerships", "commercial manager",
        "trade", "revenue manager", "enterprise sales", "pre-sales",
    ]),
    ("Marketing & Communications", [
        "marketing", "brand", "communications", "digital marketing", "content",
        "social media", "public relations", "pr ", "seo", "growth marketing",
        "advertising", "campaign", "media planner", "copywriter", "creative director",
    ]),
    ("Product & Design", [
        "product manager", "product owner", "product designer", "ux ", "ui ",
        "user experience", "user interface", "graphic designer", "visual designer",
        "art director", "creative", "interaction designer",
    ]),
    ("Customer Service", [
        "customer service", "customer experience", "call center", "call centre",
        "customer support", "client service", "contact centre", "customer success",
        "helpdesk", "help desk", "service desk", "customer care",
    ]),
    ("Operations & Logistics", [
        "operations", "logistics", "supply chain", "warehouse", "procurement",
        "fleet", "inventory", "distribution", "demand planning", "import", "export",
        "shipping", "freight", "vendor management", "facilities",
    ]),
    ("Administration", [
        "admin", "administrative", "executive assistant", "personal assistant",
        "office manager", "secretary", "receptionist", "office coordinator",
        "document controller",
    ]),
    ("Engineering (Field/Technical)", [
        "field engineer", "field technician", "electrician", "civil engineer",
        "mechanical engineer", "structural engineer", "maintenance engineer",
        "instrumentation", "technical officer", "noc engineer", "tower",
        "transmission engineer", "rf engineer", "network field",
    ]),
    ("Engineering & IT", [
        "software", "developer", "engineer", "engineering", "devops", "sre",
        "data scientist", "data engineer", "data analyst", "network engineer",
        "it support", "infrastructure", "cloud", "backend", "frontend",
        "full stack", "fullstack", "mobile developer", "android", "ios",
        "cybersecurity", "security analyst", "system administrator", "sysadmin",
        "database administrator", "dba", "machine learning", "artificial intelligence",
        "python", "java", "javascript", "architect", "qa engineer", "test engineer",
        "scrum master", "agile coach", "technical",
    ]),
]

# Title-only patterns (higher confidence than description search)
_TITLE_DEPT_KEYWORDS = {name: kws for name, kws in _DEPT_KEYWORDS}


def detect_department(title: str, description: str = "") -> str:
    """
    Return the most specific department match for this job.
    Prioritises title match over description match.
    Returns empty string (not "General") when uncertain — 
    let the caller decide on the default.
    """
    title_lower = title.lower()
    desc_lower = description[:600].lower() if description else ""

    # Phase 1: check title against each department's keywords
    for dept_name, keywords in _DEPT_KEYWORDS:
        for kw in keywords:
            if kw in title_lower:
                return dept_name

    # Phase 2: check description if title gave no match
    for dept_name, keywords in _DEPT_KEYWORDS:
        for kw in keywords:
            if kw in desc_lower:
                return dept_name

    return ""  # Unknown — caller will apply their default


def classify_job(
    title: str,
    description: str = "",
    current_job_type: str = "Full-time",
    current_department: str = "General",
) -> tuple:
    """
    Return (job_type, department).
    Only overrides values that are still the generic defaults.
    """
    job_type = current_job_type
    department = current_department

    # Only override if still at generic default
    if not job_type or job_type == "Full-time":
        detected = detect_job_type(title, description)
        if detected != "Full-time":
            job_type = detected

    # Override department if still at generic default OR empty
    if not department or department in ("General", ""):
        detected = detect_department(title, description)
        department = detected or "General"

    return job_type, department
