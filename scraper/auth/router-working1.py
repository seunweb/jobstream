"""
Authentication routes: register, login, logout, refresh, me.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, EmailStr

from auth.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token
)
from database import get_conn, USE_POSTGRES

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class RefreshIn(BaseModel):
    refresh_token: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE email = %s" if USE_POSTGRES
            else "SELECT * FROM users WHERE email = ?",
            (email.lower(),)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE id = %s" if USE_POSTGRES
            else "SELECT * FROM users WHERE id = ?",
            (user_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_session(user_id: str, refresh_token: str, request: Request):
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO sessions (user_id, refresh_token, ip_address, user_agent, expires_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (
                user_id, refresh_token,
                request.client.host if request.client else None,
                request.headers.get("user-agent"),
                expires.isoformat()
            ))
        else:
            cur.execute("""
                INSERT INTO sessions (user_id, refresh_token, ip_address, user_agent, expires_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                user_id, refresh_token,
                request.client.host if request.client else None,
                request.headers.get("user-agent"),
                expires.isoformat()
            ))


def delete_session(refresh_token: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM sessions WHERE refresh_token = %s" if USE_POSTGRES
            else "DELETE FROM sessions WHERE refresh_token = ?",
            (refresh_token,)
        )


def session_exists(refresh_token: str) -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM sessions WHERE refresh_token = %s AND expires_at > NOW()" if USE_POSTGRES
            else "SELECT id FROM sessions WHERE refresh_token = ? AND expires_at > datetime('now')",
            (refresh_token,)
        )
        return cur.fetchone() is not None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request):
    """Create a new user account."""
    email = body.email.lower().strip()

    # Check existing
    if get_user_by_email(email):
        raise HTTPException(400, "Email already registered")

    # Validate password
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    user_id = str(uuid.uuid4())
    password_hash = hash_password(body.password)

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO users (id, email, password_hash, full_name, role)
                VALUES (%s, %s, %s, %s, 'candidate')
            """, (user_id, email, password_hash, body.full_name.strip()))
        else:
            cur.execute("""
                INSERT INTO users (id, email, password_hash, full_name, role)
                VALUES (?, ?, ?, ?, 'candidate')
            """, (user_id, email, password_hash, body.full_name.strip()))

    # Issue tokens
    access_token = create_access_token(user_id, email, "candidate")
    refresh_token = create_refresh_token(user_id)
    create_session(user_id, refresh_token, request)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": user_id,
            "email": email,
            "full_name": body.full_name.strip(),
            "role": "candidate",
        }
    }


@router.post("/login")
async def login(body: LoginIn, request: Request):
    """Login with email and password."""
    email = body.email.lower().strip()
    user = get_user_by_email(email)

    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    if user["status"] != "active":
        raise HTTPException(403, "Account suspended. Contact support.")

    access_token = create_access_token(str(user["id"]), email, user["role"])
    refresh_token = create_refresh_token(str(user["id"]))
    create_session(str(user["id"]), refresh_token, request)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {
            "id": str(user["id"]),
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        }
    }


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request):
    """Issue new access token using refresh token."""
    if not session_exists(body.refresh_token):
        raise HTTPException(401, "Invalid or expired refresh token")

    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")

    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")

    # Rotate refresh token
    delete_session(body.refresh_token)
    new_refresh = create_refresh_token(str(user["id"]))
    create_session(str(user["id"]), new_refresh, request)
    new_access = create_access_token(str(user["id"]), user["email"], user["role"])

    return {
        "access_token": new_access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.post("/logout")
async def logout(body: RefreshIn):
    """Invalidate refresh token."""
    delete_session(body.refresh_token)
    return {"message": "Logged out successfully"}


@router.get("/me")
async def me(request: Request):
    """Get current user profile from token."""
    from auth.dependencies import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(401, "Invalid token")
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")
    return {
        "id": str(user["id"]),
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "status": user["status"],
        "created_at": str(user["created_at"]),
    }


@router.patch("/me")
async def update_profile(request: Request):
    """Update current user's name."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    token = auth_header[7:]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(401, "Invalid token")

    body = await request.json()
    full_name = body.get("full_name", "").strip()
    if not full_name:
        raise HTTPException(400, "full_name is required")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET full_name = %s WHERE id = %s" if USE_POSTGRES
            else "UPDATE users SET full_name = ? WHERE id = ?",
            (full_name, payload["sub"])
        )
    return {"message": "Profile updated"}
