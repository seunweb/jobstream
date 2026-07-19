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

# Security imports
from core.security import (
    check_rate_limit, login_tracker,
    sanitise, sanitise_email, validate_password,
)
# Audit imports
from core.audit import log_auth, log_action, AuditAction


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
    """Send password reset email via SMTP (local) or Resend (production)."""
    from core.email import send_email

    app_url = os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")
    reset_url = f"{app_url}/reset-password?token={token}"
    log.info(f"Sending reset email to {to_email} | reset_url={reset_url}")

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
</div>
</body>
</html>"""
    try:
        send_email(to_email=to_email, subject="Reset your JobStream password", html=html)
        return True
    except Exception as e:
        log.error(f"Failed to send reset email: {e}")
        return False


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request):
    # Rate limit registration
    check_rate_limit(request, "auth")

    email = sanitise_email(body.email)
    full_name = sanitise(body.full_name, max_length=255)

    if get_user_by_email(email):
        raise HTTPException(400, "Email already registered")

    # Enforce password policy
    ok, msg = validate_password(body.password)
    if not ok:
        raise HTTPException(400, msg)
    user_id = str(uuid.uuid4())
    password_hash = hash_password(body.password)
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO users (id, email, password_hash, full_name, role) VALUES (%s, %s, %s, %s, 'candidate')",
                (user_id, email, password_hash, full_name)
            )
        else:
            cur.execute(
                "INSERT INTO users (id, email, password_hash, full_name, role) VALUES (?, ?, ?, ?, 'candidate')",
                (user_id, email, password_hash, full_name)
            )
    # Auto-assign Candidate Free plan
    try:
        from services.identity.billing_router import _get_free_plan_from_db
        from services.identity.quota_router import apply_plan_to_tenant
        candidate_free = _get_free_plan_from_db("candidate")
        if candidate_free:
            # For candidates, tenant_id is their user_id (no org workspace)
            apply_plan_to_tenant(
                tenant_id=user_id,
                plan_id=candidate_free["id"],
                plan=candidate_free,
                expires_at=None,
            )
    except Exception as _pe:
        import logging as _l
        _l.getLogger(__name__).warning(f"Could not assign candidate free plan: {_pe}")

    access_token = create_access_token(user_id, email, "candidate")
    refresh_token = create_refresh_token(user_id)
    create_session(user_id, refresh_token, request)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "user": {"id": user_id, "email": email, "full_name": full_name, "role": "candidate"}
    }


@router.post("/login")
async def login(body: LoginIn, request: Request):
    # Rate limit login attempts
    check_rate_limit(request, "auth")

    email = sanitise_email(body.email)

    # Check account lockout
    locked, seconds = login_tracker.is_locked(email)
    if locked:
        minutes = max(1, seconds // 60)
        raise HTTPException(
            429,
            f"Account temporarily locked due to too many failed attempts. "
            f"Try again in {minutes} minute{'s' if minutes != 1 else ''}."
        )

    user = get_user_by_email(email)
    if not user or not verify_password(body.password, user["password_hash"]):
        login_tracker.record_failure(email)
        failures = login_tracker.get_failure_count(email)
        remaining = max(0, login_tracker.MAX_ATTEMPTS - failures)
        # Audit failed login
        log_action(
            AuditAction.USER_LOGIN_FAILED,
            resource_type="user", resource_id=email,
            metadata={"email": email, "failures": failures},
            request=request, module="identity",
        )
        detail = "Invalid email or password"
        if remaining <= 2 and remaining > 0:
            detail += f" ({remaining} attempt{'s' if remaining != 1 else ''} remaining)"
        raise HTTPException(401, detail)

    if user["status"] != "active":
        raise HTTPException(403, "Account suspended. Contact support.")

    # Clear failed attempts on success
    login_tracker.record_success(email)
    log_auth(AuditAction.USER_LOGIN, str(user["id"]), email, request)

    # Record last login time and IP
    client_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(
                    "UPDATE users SET last_login_at = NOW(), last_ip = %s WHERE id = %s",
                    (client_ip[:45], str(user["id"]))
                )
            else:
                cur.execute(
                    "UPDATE users SET last_login_at = datetime('now'), last_ip = ? WHERE id = ?",
                    (client_ip[:45], str(user["id"]))
                )
    except Exception:
        pass  # non-critical

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
async def logout(body: RefreshIn, request: Request):
    delete_session(body.refresh_token)
    log_action(AuditAction.USER_LOGOUT, request=request, module="identity")
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
    log_action(
        AuditAction.PASSWORD_RESET_DONE,
        user_id=user_id,
        resource_type="user", resource_id=user_id,
        module="identity",
    )
    return {"message": "Password reset successfully. Please sign in with your new password."}


# ── Session Management ────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(request: Request):
    """List all active sessions for the current user."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT id, ip_address, user_agent, last_active_at, created_at, expires_at
                FROM sessions
                WHERE user_id = %s AND expires_at > NOW()
                ORDER BY created_at DESC
            """, (payload["sub"],))
        else:
            cur.execute("""
                SELECT id, ip_address, user_agent, created_at, expires_at
                FROM sessions
                WHERE user_id = ? AND expires_at > datetime('now')
                ORDER BY created_at DESC
            """, (payload["sub"],))
        return [dict(r) for r in cur.fetchall()]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(session_id: str, request: Request):
    """Revoke a specific session (remote logout)."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "DELETE FROM sessions WHERE id = %s AND user_id = %s",
                (session_id, payload["sub"])
            )
        else:
            cur.execute(
                "DELETE FROM sessions WHERE id = ? AND user_id = ?",
                (session_id, payload["sub"])
            )


@router.delete("/sessions", status_code=204)
async def revoke_all_sessions(request: Request):
    """Revoke all sessions — logs out from all devices."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("DELETE FROM sessions WHERE user_id = %s", (payload["sub"],))
        else:
            cur.execute("DELETE FROM sessions WHERE user_id = ?", (payload["sub"],))


# ── MFA Setup ─────────────────────────────────────────────────────────────────

@router.post("/mfa/setup")
async def mfa_setup(request: Request):
    """Generate MFA secret and QR code URI for the current user."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")

    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    from core.mfa import generate_totp_secret, get_totp_uri, get_qr_code_url
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user["email"])
    qr_url = get_qr_code_url(uri)

    # Store secret temporarily — only activated after user verifies
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE users SET mfa_secret = %s WHERE id = %s",
                (secret, payload["sub"])
            )
        else:
            cur.execute(
                "UPDATE users SET mfa_secret = ? WHERE id = ?",
                (secret, payload["sub"])
            )

    return {
        "secret": secret,
        "qr_url": qr_url,
        "message": "Scan the QR code with your authenticator app then verify"
    }


class MFAVerifyIn(BaseModel):
    code: str


@router.post("/mfa/verify")
async def mfa_verify(body: MFAVerifyIn, request: Request):
    """Verify TOTP code and enable MFA on the account."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")

    user = get_user_by_id(payload["sub"])
    if not user or not user.get("mfa_secret"):
        raise HTTPException(400, "MFA not set up. Call /auth/mfa/setup first.")

    from core.mfa import verify_totp
    if not verify_totp(user["mfa_secret"], body.code):
        raise HTTPException(400, "Invalid code. Check your authenticator app.")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE users SET mfa_enabled = TRUE WHERE id = %s",
                (payload["sub"],)
            )
        else:
            cur.execute(
                "UPDATE users SET mfa_enabled = 1 WHERE id = ?",
                (payload["sub"],)
            )

    log_auth(AuditAction.MFA_ENABLED, payload["sub"], user["email"], request)
    return {"message": "MFA enabled successfully"}


@router.post("/mfa/disable")
async def mfa_disable(body: MFAVerifyIn, request: Request):
    """Disable MFA — requires valid TOTP code to confirm."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")
    payload = decode_token(auth_header[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")

    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(404, "User not found")

    from core.mfa import verify_totp
    if not verify_totp(user.get("mfa_secret", ""), body.code):
        raise HTTPException(400, "Invalid code")

    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE users SET mfa_enabled = FALSE, mfa_secret = NULL WHERE id = %s",
                (payload["sub"],)
            )
        else:
            cur.execute(
                "UPDATE users SET mfa_enabled = 0, mfa_secret = NULL WHERE id = ?",
                (payload["sub"],)
            )

    log_auth(AuditAction.MFA_DISABLED, payload["sub"], user["email"], request)
    return {"message": "MFA disabled"}
