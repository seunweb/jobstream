"""
Shared email utility for JobStream.

Strategy:
  1. If SMTP_HOST is set → use SMTP (Gmail port 587 locally, or any SMTP server)
  2. Else if RESEND_API_KEY is set → use Resend HTTP API (Railway production)
  3. Else → log warning, skip send

Environment variables:
  SMTP_HOST       e.g. smtp.gmail.com
  SMTP_PORT       e.g. 587
  SMTP_USER       e.g. you@gmail.com
  SMTP_PASS       Gmail App Password (NOT your account password)
  FROM_EMAIL      e.g. you@gmail.com or alerts@yourdomain.com
  RESEND_API_KEY  sk_live_... (production only)
"""

import os
import json
import smtplib
import logging
import urllib.request
import urllib.error
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)


def send_email(
    to_email: str,
    subject: str,
    html: str,
    from_name: str = "JobStream",
) -> bool:
    """
    Send an HTML email. Returns True on success, False on failure.
    Tries SMTP first, then Resend. Raises on hard failure so callers
    can surface the real error message.
    """
    from_email = os.environ.get("FROM_EMAIL", "")
    smtp_host = os.environ.get("SMTP_HOST", "")
    resend_key = os.environ.get("RESEND_API_KEY", "")

    if not to_email:
        raise ValueError("No recipient email address")

    if smtp_host:
        return _send_via_smtp(to_email, subject, html, from_email, from_name)
    elif resend_key:
        return _send_via_resend(to_email, subject, html, from_email, from_name, resend_key)
    else:
        log.warning(
            "No email transport configured. "
            "Set SMTP_HOST (local) or RESEND_API_KEY (production)."
        )
        return False


def _send_via_smtp(
    to_email: str,
    subject: str,
    html: str,
    from_email: str,
    from_name: str,
) -> bool:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", from_email)
    password = os.environ.get("SMTP_PASS", "")

    if not password:
        raise ValueError(
            "SMTP_PASS not set. For Gmail use an App Password "
            "(Google Account → Security → 2-Step Verification → App Passwords)"
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email or user}>"
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(from_email or user, [to_email], msg.as_string())
        log.info(f"SMTP sent → {to_email} ({subject})")
        return True
    except smtplib.SMTPAuthenticationError as e:
        raise ValueError(
            f"SMTP authentication failed: {e}. "
            "For Gmail, make sure you're using an App Password not your main password."
        )
    except Exception as e:
        raise ValueError(f"SMTP send failed: {e}")


def _send_via_resend(
    to_email: str,
    subject: str,
    html: str,
    from_email: str,
    from_name: str,
    api_key: str,
) -> bool:
    if not from_email:
        raise ValueError(
            "FROM_EMAIL not set. "
            "Set FROM_EMAIL to a verified domain address on resend.com"
        )

    # Try the official Resend SDK first (avoids Cloudflare 1010 errors)
    try:
        import resend as resend_sdk
        resend_sdk.api_key = api_key
        params = {
            "from": f"{from_name} <{from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
        result = resend_sdk.Emails.send(params)
        log.info(f"Resend SDK → {to_email}: id={result.get('id')}")
        return True
    except ImportError:
        log.debug("Resend SDK not installed, falling back to HTTP")
    except Exception as sdk_err:
        log.warning(f"Resend SDK failed: {sdk_err}, trying HTTP fallback")

    # Fallback: direct HTTP with full browser-like headers
    payload = json.dumps({
        "from": f"{from_name} <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; JobStream/1.0)",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            log.info(f"Resend HTTP → {to_email}: {body}")
        return True
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise ValueError(f"Resend {e.code}: {err}")
    except Exception as e:
        raise ValueError(f"Resend send failed: {e}")
