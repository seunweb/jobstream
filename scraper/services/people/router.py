"""
People Service Router
Unified persons layer — handles candidates, future employees, contacts.
All from one persons table — no data migration needed when
a candidate becomes an employee.
"""

import uuid
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user

router = APIRouter(prefix="/persons", tags=["people"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PersonIn(BaseModel):
    first_name: str
    last_name: str
    middle_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    bio: Optional[str] = None
    linkedin_url: Optional[str] = None
    resume_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    years_experience: Optional[int] = None
    lifecycle_stage: Optional[str] = "candidate"
    is_open_to_work: Optional[bool] = True
    work_preference: Optional[str] = "hybrid"


class SkillIn(BaseModel):
    skill: str
    level: Optional[str] = None
    years: Optional[float] = None


class ExperienceIn(BaseModel):
    company: str
    title: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    is_current: Optional[bool] = False
    description: Optional[str] = None


class EducationIn(BaseModel):
    institution: str
    degree: Optional[str] = None
    field: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    grade: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/me")
async def get_my_person_profile(current_user: dict = Depends(get_current_user)):
    """Get the person record linked to the current user."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM persons WHERE user_id = %s" if USE_POSTGRES
            else "SELECT * FROM persons WHERE user_id = ?",
            (str(current_user["id"]),)
        )
        person = cur.fetchone()
        if not person:
            return {}
        p = dict(person)

        # Get skills
        cur.execute(
            "SELECT * FROM person_skills WHERE person_id = %s ORDER BY skill" if USE_POSTGRES
            else "SELECT * FROM person_skills WHERE person_id = ? ORDER BY skill",
            (p["id"],)
        )
        p["skills"] = [dict(r) for r in cur.fetchall()]

        # Get experience
        cur.execute(
            "SELECT * FROM person_experience WHERE person_id = %s ORDER BY started_at DESC" if USE_POSTGRES
            else "SELECT * FROM person_experience WHERE person_id = ? ORDER BY started_at DESC",
            (p["id"],)
        )
        p["experience"] = [dict(r) for r in cur.fetchall()]

        # Get education
        cur.execute(
            "SELECT * FROM person_education WHERE person_id = %s ORDER BY started_at DESC" if USE_POSTGRES
            else "SELECT * FROM person_education WHERE person_id = ? ORDER BY started_at DESC",
            (p["id"],)
        )
        p["education"] = [dict(r) for r in cur.fetchall()]

        return p


@router.put("/me")
async def upsert_my_person_profile(
    body: PersonIn,
    current_user: dict = Depends(get_current_user),
):
    """Create or update the person record for the current user."""
    user_id = str(current_user["id"])

    # Check if person exists
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM persons WHERE user_id = %s" if USE_POSTGRES
            else "SELECT id FROM persons WHERE user_id = ?",
            (user_id,)
        )
        existing = cur.fetchone()

    if existing:
        person_id = dict(existing)["id"]
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    UPDATE persons SET
                        first_name=%s, last_name=%s, middle_name=%s,
                        email=%s, phone=%s, location=%s, bio=%s,
                        linkedin_url=%s, resume_url=%s, portfolio_url=%s,
                        years_experience=%s, lifecycle_stage=%s,
                        is_open_to_work=%s, work_preference=%s,
                        updated_at=NOW()
                    WHERE id=%s
                """, (
                    body.first_name, body.last_name, body.middle_name,
                    body.email or current_user.get("email"), body.phone,
                    body.location, body.bio, body.linkedin_url,
                    body.resume_url, body.portfolio_url, body.years_experience,
                    body.lifecycle_stage, body.is_open_to_work,
                    body.work_preference, person_id
                ))
            else:
                cur.execute("""
                    UPDATE persons SET
                        first_name=?, last_name=?, middle_name=?,
                        email=?, phone=?, location=?, bio=?,
                        linkedin_url=?, resume_url=?, portfolio_url=?,
                        years_experience=?, lifecycle_stage=?,
                        is_open_to_work=?, work_preference=?,
                        updated_at=datetime('now')
                    WHERE id=?
                """, (
                    body.first_name, body.last_name, body.middle_name,
                    body.email or current_user.get("email"), body.phone,
                    body.location, body.bio, body.linkedin_url,
                    body.resume_url, body.portfolio_url, body.years_experience,
                    body.lifecycle_stage, 1 if body.is_open_to_work else 0,
                    body.work_preference, person_id
                ))
    else:
        person_id = str(uuid.uuid4())
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    INSERT INTO persons (
                        id, user_id, first_name, last_name, middle_name,
                        email, phone, location, bio, linkedin_url,
                        resume_url, portfolio_url, years_experience,
                        lifecycle_stage, is_open_to_work, work_preference
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    person_id, user_id,
                    body.first_name, body.last_name, body.middle_name,
                    body.email or current_user.get("email"), body.phone,
                    body.location, body.bio, body.linkedin_url,
                    body.resume_url, body.portfolio_url, body.years_experience,
                    body.lifecycle_stage, body.is_open_to_work, body.work_preference
                ))
            else:
                cur.execute("""
                    INSERT INTO persons (
                        id, user_id, first_name, last_name, middle_name,
                        email, phone, location, bio, linkedin_url,
                        resume_url, portfolio_url, years_experience,
                        lifecycle_stage, is_open_to_work, work_preference
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    person_id, user_id,
                    body.first_name, body.last_name, body.middle_name,
                    body.email or current_user.get("email"), body.phone,
                    body.location, body.bio, body.linkedin_url,
                    body.resume_url, body.portfolio_url, body.years_experience,
                    body.lifecycle_stage, 1 if body.is_open_to_work else 0,
                    body.work_preference
                ))

    return {"message": "Profile saved", "person_id": person_id}


# ── Skills ────────────────────────────────────────────────────────────────────

@router.post("/me/skills", status_code=201)
async def add_skill(
    body: SkillIn,
    current_user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM persons WHERE user_id = %s" if USE_POSTGRES
            else "SELECT id FROM persons WHERE user_id = ?",
            (str(current_user["id"]),)
        )
        person = cur.fetchone()
        if not person:
            raise HTTPException(400, "Create your profile first")

        person_id = dict(person)["id"]
        skill_id = str(uuid.uuid4())

        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO person_skills (id, person_id, skill, level, years) VALUES (%s,%s,%s,%s,%s)",
                (skill_id, person_id, body.skill, body.level, body.years)
            )
        else:
            cur.execute(
                "INSERT INTO person_skills (id, person_id, skill, level, years) VALUES (?,?,?,?,?)",
                (skill_id, person_id, body.skill, body.level, body.years)
            )
    return {"id": skill_id, "skill": body.skill}


@router.delete("/me/skills/{skill_id}", status_code=204)
async def delete_skill(
    skill_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM person_skills WHERE id = %s" if USE_POSTGRES
            else "DELETE FROM person_skills WHERE id = ?",
            (skill_id,)
        )


# ── Experience ────────────────────────────────────────────────────────────────

@router.post("/me/experience", status_code=201)
async def add_experience(
    body: ExperienceIn,
    current_user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM persons WHERE user_id = %s" if USE_POSTGRES
            else "SELECT id FROM persons WHERE user_id = ?",
            (str(current_user["id"]),)
        )
        person = cur.fetchone()
        if not person:
            raise HTTPException(400, "Create your profile first")

        person_id = dict(person)["id"]
        exp_id = str(uuid.uuid4())

        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO person_experience
                    (id, person_id, company, title, started_at, ended_at, is_current, description)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (exp_id, person_id, body.company, body.title,
                  body.started_at, body.ended_at, body.is_current, body.description))
        else:
            cur.execute("""
                INSERT INTO person_experience
                    (id, person_id, company, title, started_at, ended_at, is_current, description)
                VALUES (?,?,?,?,?,?,?,?)
            """, (exp_id, person_id, body.company, body.title,
                  body.started_at, body.ended_at,
                  1 if body.is_current else 0, body.description))
    return {"id": exp_id, "company": body.company, "title": body.title}


@router.delete("/me/experience/{exp_id}", status_code=204)
async def delete_experience(
    exp_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM person_experience WHERE id = %s" if USE_POSTGRES
            else "DELETE FROM person_experience WHERE id = ?",
            (exp_id,)
        )


# ── Education ─────────────────────────────────────────────────────────────────

@router.post("/me/education", status_code=201)
async def add_education(
    body: EducationIn,
    current_user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM persons WHERE user_id = %s" if USE_POSTGRES
            else "SELECT id FROM persons WHERE user_id = ?",
            (str(current_user["id"]),)
        )
        person = cur.fetchone()
        if not person:
            raise HTTPException(400, "Create your profile first")

        person_id = dict(person)["id"]
        edu_id = str(uuid.uuid4())

        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO person_education
                    (id, person_id, institution, degree, field, started_at, ended_at, grade)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (edu_id, person_id, body.institution, body.degree,
                  body.field, body.started_at, body.ended_at, body.grade))
        else:
            cur.execute("""
                INSERT INTO person_education
                    (id, person_id, institution, degree, field, started_at, ended_at, grade)
                VALUES (?,?,?,?,?,?,?,?)
            """, (edu_id, person_id, body.institution, body.degree,
                  body.field, body.started_at, body.ended_at, body.grade))
    return {"id": edu_id, "institution": body.institution}


@router.delete("/me/education/{edu_id}", status_code=204)
async def delete_education(
    edu_id: str,
    current_user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM person_education WHERE id = %s" if USE_POSTGRES
            else "DELETE FROM person_education WHERE id = ?",
            (edu_id,)
        )


# ── Lifecycle transition ──────────────────────────────────────────────────────

@router.patch("/{person_id}/lifecycle")
async def update_lifecycle(
    person_id: str,
    stage: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Move a person through the lifecycle:
    candidate → applicant → interviewed → offered → employee → alumni
    """
    valid_stages = ["candidate", "applicant", "interviewed", "offered",
                    "employee", "alumni", "rejected"]
    if stage not in valid_stages:
        raise HTTPException(400, f"Invalid stage. Must be one of: {', '.join(valid_stages)}")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE persons SET lifecycle_stage=%s, updated_at=NOW() WHERE id=%s",
                (stage, person_id)
            )
        else:
            cur.execute(
                "UPDATE persons SET lifecycle_stage=?, updated_at=datetime('now') WHERE id=?",
                (stage, person_id)
            )
    return {"message": f"Lifecycle updated to {stage}"}
