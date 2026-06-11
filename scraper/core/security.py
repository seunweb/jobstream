"""
Platform-wide security middleware and utilities.
Phase 4 — Security Hardening.

Covers:
- Rate limiting (in-memory, Redis-ready)
- Account lockout after failed attempts
- Security headers middleware
- Input sanitisation
- CORS configuration
"""

import re
import time
import logging
import os
from collections import defaultdict
from typing import Optional
from fastapi import Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger(__name__)


# ── Rate Limiter ──────────────────────────────────────────────────────────────
# In-memory for now. Swap _store for Redis at scale.

class RateLimiter:
    """
    Sliding window rate limiter.
    Tracks requests per IP per endpoint group.
    """
    def __init__(self):
        # {key: [(timestamp, count)]}
        self._windows: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """
        Check if request is allowed.
        Returns (allowed, remaining_requests).
        """
        now = time.time()
        cutoff = now - window_seconds

        # Remove expired entries
        self._windows[key] = [t for t in self._windows[key] if t > cutoff]

        count = len(self._windows[key])
        if count >= limit:
            return False, 0

        self._windows[key].append(now)
        return True, limit - count - 1

    def clear(self, key: str):
        self._windows.pop(key, None)


rate_limiter = RateLimiter()

# Rate limit configs
LIMITS = {
    "auth":    (10, 300),   # 10 attempts per 5 minutes
    "apply":   (20, 3600),  # 20 applications per hour
    "scrape":  (5,  600),   # 5 scrape triggers per 10 minutes
    "default": (60, 60),    # 60 requests per minute
}

def check_rate_limit(request: Request, group: str = "default"):
    """Call this in endpoints that need rate limiting."""
    ip = request.client.host if request.client else "unknown"
    limit, window = LIMITS.get(group, LIMITS["default"])
    key = f"{group}:{ip}"
    allowed, remaining = rate_limiter.is_allowed(key, limit, window)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please wait before trying again.",
            headers={"Retry-After": str(window)},
        )
    return remaining


# ── Account Lockout ───────────────────────────────────────────────────────────

class LoginAttemptTracker:
    """
    Track failed login attempts per email.
    Locks account after MAX_ATTEMPTS failures.
    Auto-resets after LOCKOUT_SECONDS.
    """
    MAX_ATTEMPTS = 5
    LOCKOUT_SECONDS = 900  # 15 minutes

    def __init__(self):
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def record_failure(self, email: str):
        now = time.time()
        self._attempts[email].append(now)
        count = self.get_failure_count(email)
        if count >= self.MAX_ATTEMPTS:
            log.warning(f"Account locked: {email} ({count} failed attempts)")

    def record_success(self, email: str):
        self._attempts.pop(email, None)

    def get_failure_count(self, email: str) -> int:
        cutoff = time.time() - self.LOCKOUT_SECONDS
        self._attempts[email] = [
            t for t in self._attempts[email] if t > cutoff
        ]
        return len(self._attempts[email])

    def is_locked(self, email: str) -> tuple[bool, int]:
        """Returns (is_locked, seconds_remaining)."""
        count = self.get_failure_count(email)
        if count < self.MAX_ATTEMPTS:
            return False, 0
        oldest = min(self._attempts[email])
        unlock_at = oldest + self.LOCKOUT_SECONDS
        remaining = max(0, int(unlock_at - time.time()))
        return True, remaining


login_tracker = LoginAttemptTracker()


# ── Security Headers Middleware ───────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds security headers to every response.
    Protects against XSS, clickjacking, MIME sniffing.
    """
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=()"
        )

        # HSTS — only on production (HTTPS)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://api.resend.com https://logo.clearbit.com; "
            "frame-ancestors 'none';"
        )

        return response


# ── Input Sanitisation ────────────────────────────────────────────────────────

# Characters / patterns that should never appear in user inputs
_DANGEROUS_PATTERNS = [
    r"<script[^>]*>.*?</script>",
    r"javascript:",
    r"on\w+\s*=",           # onclick=, onload=, etc.
    r"<iframe",
    r"<object",
    r"<embed",
    r"data:text/html",
    r"vbscript:",
]
_DANGER_RE = re.compile(
    "|".join(_DANGEROUS_PATTERNS), re.IGNORECASE | re.DOTALL
)


def sanitise(value: str, max_length: int = 10_000) -> str:
    """
    Strip dangerous patterns and enforce max length.
    Use on any free-text field before storing.
    """
    if not isinstance(value, str):
        return value
    cleaned = _DANGER_RE.sub("", value)
    return cleaned[:max_length].strip()


def sanitise_email(email: str) -> str:
    """Normalise and validate email format."""
    email = email.strip().lower()[:255]
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(422, "Invalid email address")
    return email


def sanitise_url(url: str) -> str:
    """Ensure URL starts with http/https."""
    url = url.strip()[:2048]
    if url and not re.match(r"^https?://", url, re.IGNORECASE):
        raise HTTPException(422, "URL must start with http:// or https://")
    return url


# ── CORS Configuration ────────────────────────────────────────────────────────

def get_cors_origins() -> list[str]:
    """
    Return allowed CORS origins.
    In production reads from APP_URL env var.
    In development allows localhost.
    """
    origins = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
    ]

    app_url = os.environ.get("APP_URL", "")
    if app_url:
        origins.append(app_url.rstrip("/"))

    # Additional allowed origins from env
    extra = os.environ.get("ALLOWED_ORIGINS", "")
    if extra:
        origins.extend([o.strip() for o in extra.split(",") if o.strip()])

    return list(set(origins))


# ── Password strength ─────────────────────────────────────────────────────────

def validate_password(password: str) -> tuple[bool, str]:
    """
    Enforce password policy:
    - Min 8 characters
    - At least one uppercase letter
    - At least one digit
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain at least one number"
    return True, ""
