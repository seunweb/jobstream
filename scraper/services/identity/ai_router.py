"""
AI Service Router
Phase 10 — Claude-powered AI features for candidates and employers.

All AI calls go through this single router so:
- Usage can be tracked and rate-limited per user/tenant
- Premium feature gates are enforced in one place
- Prompts can be updated without touching business logic
"""

import os
import json
import logging
import urllib.request
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from services.identity.dependencies import get_current_user
from core.audit import log_action

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])

# Claude model to use
CLAUDE_MODEL = "claude-sonnet-4-20250514"


# ── Claude API helper ─────────────────────────────────────────────────────────

def call_claude(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 1500,
) -> str:
    """
    Call Claude API and return text response.
    Uses Anthropic API key from environment.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "AI service not configured. Add ANTHROPIC_API_KEY to environment variables.")

    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log.error(f"Claude API error {e.code}: {body[:200]}")
        raise HTTPException(502, f"AI service error: {e.code}")
    except Exception as e:
        log.error(f"Claude API failed: {e}")
        raise HTTPException(502, "AI service temporarily unavailable")


def log_ai_usage(user_id: str, feature: str, tokens_est: int = 0):
    """Log AI feature usage for analytics and billing."""
    log_action(
        f"ai.{feature}",
        user_id=user_id,
        resource_type="ai_usage",
        metadata={"feature": feature, "tokens_est": tokens_est},
        module="ai",
    )


# ── Schemas ───────────────────────────────────────────────────────────────────

class CVOptimiseIn(BaseModel):
    cv_text: str
    target_role: Optional[str] = ""
    target_industry: Optional[str] = ""

class JobMatchIn(BaseModel):
    job_id: Optional[int] = None
    job_title: Optional[str] = ""
    job_description: Optional[str] = ""
    candidate_profile: Optional[str] = ""
    candidate_skills: Optional[list] = []
    years_experience: Optional[int] = 0

class ApplicationWriterIn(BaseModel):
    job_title: str
    company: str
    job_description: Optional[str] = ""
    candidate_name: str
    candidate_skills: Optional[list] = []
    years_experience: Optional[int] = 0
    tone: Optional[str] = "professional"  # professional | friendly | concise

class InterviewPrepIn(BaseModel):
    job_title: str
    company: Optional[str] = ""
    job_description: Optional[str] = ""
    interview_type: Optional[str] = "general"  # general | technical | behavioral

class JobDescriptionWriterIn(BaseModel):
    job_title: str
    company: str
    department: Optional[str] = ""
    location: Optional[str] = "Lagos, Nigeria"
    job_type: Optional[str] = "Full-time"
    key_responsibilities: Optional[str] = ""
    requirements: Optional[str] = ""
    industry: Optional[str] = ""

class HRAssistantIn(BaseModel):
    question: str
    context: Optional[str] = ""  # e.g. "Nigerian labour law", "employee handbook"


# ── CV Optimiser ──────────────────────────────────────────────────────────────

@router.post("/cv/optimise")
async def optimise_cv(
    body: CVOptimiseIn,
    current_user: dict = Depends(get_current_user),
):
    """
    AI-powered CV review and improvement suggestions.
    Returns structured feedback with specific recommendations.
    """
    if not body.cv_text or len(body.cv_text.strip()) < 50:
        raise HTTPException(400, "Please provide your CV text (minimum 50 characters)")

    system = """You are an expert Nigerian HR consultant and CV writer with 15+ years 
experience helping professionals across Africa land their dream jobs. You know what 
Nigerian and African employers look for. Be specific, actionable and encouraging."""

    user_msg = f"""Please review and optimise this CV{f' for a {body.target_role} role' if body.target_role else ''}{f' in {body.target_industry}' if body.target_industry else ''}.

CV TEXT:
{body.cv_text[:3000]}

Provide your response in this exact format:

**Overall Score: X/10**

**Strengths**
• [List 3-4 specific strengths of this CV]

**Critical Improvements**
• [List 3-5 specific changes that will have the biggest impact]

**Optimised Summary**
[Write an improved professional summary (3-4 sentences) they can use directly]

**Keywords to Add**
[List 8-10 industry keywords missing from the CV that ATS systems look for]

**Formatting Tips**
• [2-3 specific formatting suggestions]"""

    result = call_claude(system, user_msg, max_tokens=1500)
    log_ai_usage(str(current_user["id"]), "cv_optimise")
    return {"result": result, "feature": "cv_optimise"}


# ── Job Match Scoring ─────────────────────────────────────────────────────────

@router.post("/job/match")
async def score_job_match(
    body: JobMatchIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Score how well a candidate matches a job.
    Returns percentage match with detailed breakdown.
    """
    # Fetch job from DB if job_id provided
    job_title = body.job_title
    job_description = body.job_description

    if body.job_id:
        from core.database import get_conn, USE_POSTGRES
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT title, description, department FROM jobs WHERE id = %s" if USE_POSTGRES
                else "SELECT title, description, department FROM jobs WHERE id = ?",
                (body.job_id,)
            )
            row = cur.fetchone()
            if row:
                job = dict(row)
                job_title = job_title or job["title"]
                job_description = job_description or job["description"]

    if not job_title:
        raise HTTPException(400, "Provide job_id or job_title")

    skills_str = ", ".join(body.candidate_skills) if body.candidate_skills else "Not specified"

    system = """You are a senior recruiter and talent assessment specialist. 
You evaluate candidate-job fit objectively and provide actionable insights. 
Be specific and honest — don't inflate scores."""

    user_msg = f"""Score this candidate's match for the following job.

JOB TITLE: {job_title}
JOB DESCRIPTION: {(job_description or 'Not provided')[:1500]}

CANDIDATE PROFILE:
- Experience: {body.years_experience} years
- Skills: {skills_str}
- Additional info: {(body.candidate_profile or 'Not provided')[:500]}

Respond in this exact format:

**Match Score: X%**

**Skills Match**
• Matched skills: [list skills candidate has that job requires]
• Missing skills: [list important skills the candidate lacks]

**Experience Assessment**
[2-3 sentences on experience fit]

**Recommendation**
[1 sentence: Strong Match / Good Match / Partial Match / Not a Match, with reason]

**Tips to Improve Match**
• [2-3 specific things candidate can do to improve their chances]"""

    result = call_claude(system, user_msg, max_tokens=1000)
    log_ai_usage(str(current_user["id"]), "job_match")
    return {"result": result, "feature": "job_match", "job_title": job_title}


# ── Application Writer ────────────────────────────────────────────────────────

@router.post("/application/write")
async def write_application(
    body: ApplicationWriterIn,
    current_user: dict = Depends(get_current_user),
):
    """
    AI writes a tailored cover letter / application note.
    Tone can be professional, friendly or concise.
    """
    skills_str = ", ".join(body.candidate_skills) if body.candidate_skills else "diverse skills"
    tone_guide = {
        "professional": "formal and professional, suitable for corporate roles",
        "friendly": "warm and personable while remaining professional",
        "concise": "brief and punchy — 3 short paragraphs maximum",
    }.get(body.tone, "professional")

    system = f"""You are an expert cover letter writer who helps African professionals 
land jobs at top companies. Write in a {tone_guide} tone. 
Use the candidate's actual details. Do not use generic filler sentences.
Write as if you ARE the candidate — use first person."""

    user_msg = f"""Write a compelling cover letter / application note for:

CANDIDATE: {body.candidate_name}
APPLYING FOR: {body.job_title} at {body.company}
EXPERIENCE: {body.years_experience} years
SKILLS: {skills_str}
JOB DESCRIPTION: {(body.job_description or 'Not provided')[:1000]}

Requirements:
- Address it to the Hiring Manager
- Open with a strong hook — not "I am writing to apply for..."
- Highlight 2-3 specific relevant skills/experiences
- Show genuine enthusiasm for {body.company} specifically
- End with a clear call to action
- Keep it under 300 words"""

    result = call_claude(system, user_msg, max_tokens=800)
    log_ai_usage(str(current_user["id"]), "application_write")
    return {"result": result, "feature": "application_write"}


# ── Interview Preparation ─────────────────────────────────────────────────────

@router.post("/interview/prep")
async def prepare_for_interview(
    body: InterviewPrepIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate tailored interview questions and suggested answers.
    """
    type_guide = {
        "general":    "mix of general, behavioral and role-specific questions",
        "technical":  "focus on technical and problem-solving questions",
        "behavioral": "focus on behavioral (STAR method) questions",
    }.get(body.interview_type, "mix of general and role-specific questions")

    system = """You are a senior interview coach who has helped thousands of candidates 
succeed in interviews at top African and multinational companies. 
Provide realistic questions that are actually asked for this type of role.
Give concise but strong sample answers."""

    user_msg = f"""Prepare interview questions and answers for:

ROLE: {body.job_title}{f' at {body.company}' if body.company else ''}
TYPE: {body.interview_type} interview
JOB DESCRIPTION: {(body.job_description or 'Not provided')[:1000]}

Provide a {type_guide}.

Format your response as:

**About the Interview**
[2-3 sentences about what to expect for this role/company type]

**Top 8 Interview Questions & Suggested Answers**

**Q1: [Question]**
*Suggested answer:* [2-4 sentence answer using STAR where appropriate]

[Continue for Q2 through Q8]

**Key Tips for This Interview**
• [3-4 specific preparation tips]"""

    result = call_claude(system, user_msg, max_tokens=2000)
    log_ai_usage(str(current_user["id"]), "interview_prep")
    return {"result": result, "feature": "interview_prep"}


# ── Job Description Writer ────────────────────────────────────────────────────

@router.post("/job/write-description")
async def write_job_description(
    body: JobDescriptionWriterIn,
    current_user: dict = Depends(get_current_user),
):
    """
    AI writes a complete, engaging job description for employers.
    Returns formatted text ready to paste into the Post Job form.
    """
    system = """You are an expert HR copywriter who creates compelling job descriptions 
for African companies. Write descriptions that attract top talent, are inclusive, 
and rank well on job boards. Be specific about requirements — avoid vague language."""

    user_msg = f"""Write a complete job description for:

COMPANY: {body.company}
JOB TITLE: {body.job_title}
DEPARTMENT: {body.department or 'Not specified'}
LOCATION: {body.location}
TYPE: {body.job_type}
INDUSTRY: {body.industry or 'Not specified'}
KEY RESPONSIBILITIES PROVIDED: {body.key_responsibilities or 'None — generate based on job title'}
REQUIREMENTS PROVIDED: {body.requirements or 'None — generate based on job title'}

Write a complete job description with these sections:
- About the role (2-3 compelling sentences)
- Key Responsibilities (6-8 bullet points)
- Qualifications & Requirements (5-7 bullet points)
- What We Offer (4-5 bullet points)

Use **bold** for section headings. Keep it professional but human.
Total length: 300-450 words."""

    result = call_claude(system, user_msg, max_tokens=1200)
    log_ai_usage(str(current_user["id"]), "job_description_write")
    return {"result": result, "feature": "job_description_write"}


# ── HR Assistant ──────────────────────────────────────────────────────────────

@router.post("/hr/assistant")
async def hr_assistant(
    body: HRAssistantIn,
    current_user: dict = Depends(get_current_user),
):
    """
    General HR assistant — answers HR, labour law and workplace questions.
    Focused on Nigerian and African context.
    """
    if not body.question or len(body.question.strip()) < 5:
        raise HTTPException(400, "Please enter a question")

    system = """You are JobStream's AI HR Assistant — an expert in Nigerian labour law, 
HR best practices, and workplace issues across Africa. You help both employers 
and employees navigate HR challenges. 

Always:
- Reference Nigerian Labour Act or relevant law when applicable
- Be practical and actionable
- Note when professional legal advice is needed for serious matters
- Be balanced — fair to both employer and employee perspectives"""

    user_msg = f"""Question: {body.question}

{f'Context: {body.context}' if body.context else ''}

Please provide a helpful, practical answer focused on Nigerian/African workplace context."""

    result = call_claude(system, user_msg, max_tokens=800)
    log_ai_usage(str(current_user["id"]), "hr_assistant")
    return {"result": result, "feature": "hr_assistant"}


# ── AI Usage stats (admin) ────────────────────────────────────────────────────

@router.get("/usage")
async def ai_usage_stats(
    current_user: dict = Depends(get_current_user),
):
    """Get AI feature usage stats for current user."""
    from core.database import get_conn, USE_POSTGRES
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT action, COUNT(*) as count, MAX(created_at) as last_used
                FROM audit_logs
                WHERE user_id = %s AND module = 'ai'
                GROUP BY action ORDER BY count DESC
            """, (str(current_user["id"]),))
        else:
            cur.execute("""
                SELECT action, COUNT(*) as count, MAX(created_at) as last_used
                FROM audit_logs
                WHERE user_id = ? AND module = 'ai'
                GROUP BY action ORDER BY count DESC
            """, (str(current_user["id"]),))
        return [dict(r) for r in cur.fetchall()]
