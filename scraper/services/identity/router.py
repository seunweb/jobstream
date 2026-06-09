"""
Authentication routes with Resend API for email (works on Railway free plan).
"""

import os
import uuid
import logging

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr

from services.identity.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    SECRET_KEY, ALGORITHM
)
from core.database import get_conn, USE_POSTGRES
from jose import jwt

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    full_name: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class RefreshIn(BaseModel):
    refresh_token: str

class ForgotPasswordIn(BaseModel):
    email: EmailStr

class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


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
            cur.execute(
                "INSERT INTO sessions (user_id, refresh_token, ip_address, user_agent, expires_at) VALUES (%s, %s, %s, %s, %s)",
                (user_id, refresh_token,
                 request.client.host if request.client else None,
                 request.headers.get("user-agent"),
                 expires.isoformat())
            )
        else:
            cur.execute(
                "INSERT INTO sessions (user_id, refresh_token, ip_address, user_agent, expires_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, refresh_token,
                 request.client.host if request.client else None,
                 request.headers.get("user-agent"),
                 expires.isoformat())
            )


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


def send_reset_email(to_email: str, token: str, full_name: str) -> bool:
    """Send password reset email via Resend API with User-Agent header fix."""
    import requests

    resend_api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "onboarding@resend.dev")
    app_url = os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")

    reset_url = f"{app_url}/reset-password?token={token}"
    log.info(f"Attempting to send reset email to {to_email}")
    log.info(f"Reset URL: {reset_url}")

    if not resend_api_key:
        log.warning("RESEND_API_KEY not set - email not sent")
        log.info(f"Manual reset link: {reset_url}")
        return False

    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;background:#f4f4f6;margin:0;padding:20px;">
<div style="max-width:480px;margin:0 auto;background:#fff;border-radius:16px;padding:40px;">
  <h1 style="font-size:20px;color:#1d1d1f;">&#9889; JobStream</h1>
  <h2 style="font-size:22px;color:#1d1d1f;margin-bottom:8px;">Reset your password</h2>
  <p style="color:#666;font-size:14px;line-height:1.6;">
    Hi {full_name},<br><br>
    Click the button below to reset your password. This link expires in 1 hour.
  </p>
  <div style="text-align:center;margin:32px 0;">
    <a href="{reset_url}"
       style="display:inline-block;padding:14px 32px;background:#0071E3;color:#fff;
              border-radius:10px;text-decoration:none;font-weight:600;font-size:15px;">
      Reset password
    </a>
  </div>
  <p style="color:#bbb;font-size:12px;text-align:center;">
    If you did not request this, ignore this email.
  </p>
  <hr style="border:none;border-top:1px solid #f0f0f0;margin:24px 0;">
  <p style="color:#ccc;font-size:11px;text-align:center;">JobStream &middot; Nigeria's Job Platform</p>
</div>
</body>
</html>"""

    headers = {
        "Authorization": f"Bearer {resend_api_key}",
        "Content-Type": "application/json",
        "User-Agent": "jobstream/1.0.0",
    }

    payload = {
        "from": f"JobStream <{from_email}>",
        "to": [to_email],
        "subject": "Reset your JobStream password",
        "html": html,
    }

    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers=headers,
            json=payload,
            timeout=15,
        )
        if response.status_code in (200, 201):
            result = response.json()
            log.info(f"Reset email sent via Resend: id={result.get('id')}")
            return True
        else:
            log.error(f"Resend API error {response.status_code}: {response.text}")
            return False
    except Exception as e:
        log.error(f"Failed to send reset email: {e}")
        return False


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request):
    email = body.email.lower().strip()
    if get_user_by_email(email):
        raise HTTPException(400, "Email already registered")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    user_id = str(uuid.uuid4())
    password_hash = hash_password(body.password)
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO users (id, email, password_hash, full_name, role) VALUES (%s, %s, %s, %s, 'candidate')",
                (user_id, email, password_hash, body.full_name.strip())
            )
        else:
            cur.execute(
                "INSERT INTO users (id, email, password_hash, full_name, role) VALUES (?, ?, ?, ?, 'candidate')",
                (user_id, email, password_hash, body.full_name.strip())
            )
    access_token = create_access_token(user_id, email, "candidate")
    refresh_token = create_refresh_token(user_id)
    create_session(user_id, refresh_token, request)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {"id": user_id, "email": email, "full_name": body.full_name.strip(), "role": "candidate"}
    }


@router.post("/login")
async def login(body: LoginIn, request: Request):
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
        "user": {"id": str(user["id"]), "email": user["email"], "full_name": user["full_name"], "role": user["role"]}
    }


@router.post("/refresh")
async def refresh(body: RefreshIn, request: Request):
    if not session_exists(body.refresh_token):
        raise HTTPException(401, "Invalid or expired refresh token")
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid refresh token")
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(401, "User not found")
    delete_session(body.refresh_token)
    new_refresh = create_refresh_token(str(user["id"]))
    create_session(str(user["id"]), new_refresh, request)
    new_access = create_access_token(str(user["id"]), user["email"], user["role"])
    return {"access_token": new_access, "refresh_token": new_refresh, "token_type": "bearer"}


@router.post("/logout")
async def logout(body: RefreshIn):
    delete_session(body.refresh_token)
    return {"message": "Logged out successfully"}


@router.get("/me")
async def me(request: Request):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
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
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
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


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordIn):
    email = body.email.lower().strip()
    user = get_user_by_email(email)
    if not user:
        return {"message": "If that email exists, a reset link has been sent"}
    expire = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(user["id"]), "type": "reset", "exp": expire, "jti": str(uuid.uuid4())},
        SECRET_KEY, algorithm=ALGORITHM
    )
    send_reset_email(email, token, user["full_name"] or "there")
    return {"message": "If that email exists, a reset link has been sent"}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordIn):
    payload = decode_token(body.token)
    if not payload or payload.get("type") != "reset":
        raise HTTPException(400, "Invalid or expired reset link")
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    user_id = payload["sub"]
    new_hash = hash_password(body.new_password)
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
        else:
            cur.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM sessions WHERE user_id = %s" if USE_POSTGRES
            else "DELETE FROM sessions WHERE user_id = ?",
            (user_id,)
        )
    return {"message": "Password reset successfully. Please sign in with your new password."}
