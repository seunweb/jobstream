"""
MFA — Multi-Factor Authentication (TOTP)
Phase 4 Security Hardening.

Uses standard TOTP (RFC 6238) compatible with:
- Google Authenticator
- Authy
- 1Password
- Any TOTP app

Requires: pyotp
"""

import base64
import logging
import os
import re
from typing import Optional

log = logging.getLogger(__name__)


def generate_totp_secret() -> str:
    """Generate a new base32 TOTP secret."""
    try:
        import pyotp
        return pyotp.random_base32()
    except ImportError:
        # Fallback if pyotp not installed
        import secrets
        raw = secrets.token_bytes(20)
        return base64.b32encode(raw).decode("utf-8")


def get_totp_uri(secret: str, email: str, issuer: str = "JobStream") -> str:
    """
    Generate otpauth:// URI for QR code generation.
    Scan with Google Authenticator or any TOTP app.
    """
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=email, issuer_name=issuer)
    except ImportError:
        # Manual construction if pyotp not installed
        from urllib.parse import quote
        return (
            f"otpauth://totp/{quote(issuer)}:{quote(email)}"
            f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1"
            f"&digits=6&period=30"
        )


def verify_totp(secret: str, code: str) -> bool:
    """
    Verify a 6-digit TOTP code.
    Accepts current window + 1 window drift for clock skew.
    """
    if not secret or not code:
        return False
    code = re.sub(r"\s", "", code)  # strip spaces
    try:
        import pyotp
        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=1)
    except ImportError:
        log.error("pyotp not installed — MFA verification unavailable")
        return False


def get_qr_code_url(totp_uri: str) -> str:
    """
    Return a QR code image URL using Google Charts API.
    The frontend can display this as an <img> for the user to scan.
    """
    from urllib.parse import quote
    return (
        f"https://chart.googleapis.com/chart"
        f"?chs=200x200&chld=M|0&cht=qr&chl={quote(totp_uri)}"
    )
