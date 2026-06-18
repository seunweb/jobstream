"""
Billing & Subscription Router
Phase 11 — Paystack integration, plans, invoices.

Plans:
  Candidate:  Free | Premium (₦2,500/month)
  Employer:   Free (3 jobs) | Starter (₦15,000/mo, 10 jobs)
               | Growth (₦35,000/mo, 50 jobs) | Enterprise (custom)

Paystack flow:
  1. POST /billing/initiate  → get Paystack payment URL
  2. User pays on Paystack
  3. Paystack calls POST /billing/webhook
  4. Webhook verifies + activates plan
"""

import os
import json
import hmac
import hashlib
import logging
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Header
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user
from core.audit import log_action

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])


# ── Plan definitions ──────────────────────────────────────────────────────────

PLANS = {
    # Candidate plans
    "candidate_free": {
        "name": "Free",
        "type": "candidate",
        "price_ngn": 0,
        "interval": None,
        "features": [
            "Apply to unlimited jobs",
            "Save up to 10 jobs",
            "Basic profile",
            "My Applications tracking",
        ],
        "limits": {"saved_jobs": 10, "ai_credits": 0},
    },
    "candidate_premium": {
        "name": "Premium",
        "type": "candidate",
        "price_ngn": 2500,
        "interval": "monthly",
        "paystack_plan_code": os.environ.get("PAYSTACK_PLAN_CANDIDATE_PREMIUM", ""),
        "features": [
            "Everything in Free",
            "Unlimited saved jobs",
            "AI CV Optimiser",
            "AI Job Match Scoring",
            "AI Cover Letter Writer",
            "AI Interview Preparation",
            "Priority profile visibility",
        ],
        "limits": {"saved_jobs": -1, "ai_credits": 50},
    },

    # Employer plans
    "employer_free": {
        "name": "Free",
        "type": "employer",
        "price_ngn": 0,
        "interval": None,
        "features": [
            "Post up to 3 jobs",
            "Basic applicant tracking",
            "Company profile page",
        ],
        "limits": {"max_jobs": 3, "team_members": 1, "ai_credits": 0},
    },
    "employer_starter": {
        "name": "Starter",
        "type": "employer",
        "price_ngn": 15000,
        "interval": "monthly",
        "paystack_plan_code": os.environ.get("PAYSTACK_PLAN_EMPLOYER_STARTER", ""),
        "features": [
            "Post up to 10 jobs",
            "Full applicant pipeline",
            "Team: up to 3 members",
            "AI Job Description Writer",
            "Email notifications",
        ],
        "limits": {"max_jobs": 10, "team_members": 3, "ai_credits": 20},
    },
    "employer_growth": {
        "name": "Growth",
        "type": "employer",
        "price_ngn": 35000,
        "interval": "monthly",
        "paystack_plan_code": os.environ.get("PAYSTACK_PLAN_EMPLOYER_GROWTH", ""),
        "features": [
            "Post up to 50 jobs",
            "Full applicant pipeline",
            "Team: up to 10 members",
            "All AI features",
            "Advanced analytics",
            "Priority listing",
        ],
        "limits": {"max_jobs": 50, "team_members": 10, "ai_credits": 100},
    },
    "employer_enterprise": {
        "name": "Enterprise",
        "type": "employer",
        "price_ngn": 0,  # custom pricing
        "interval": "monthly",
        "features": [
            "Unlimited jobs",
            "Unlimited team members",
            "White-label career portal",
            "Dedicated account manager",
            "Custom AI settings",
            "SLA support",
        ],
        "limits": {"max_jobs": -1, "team_members": -1, "ai_credits": -1},
    },
}


# ── Paystack helpers ──────────────────────────────────────────────────────────

def paystack_request(endpoint: str, method: str = "GET", data: dict = None) -> dict:
    """Make a request to Paystack API."""
    secret_key = os.environ.get("PAYSTACK_SECRET_KEY", "")
    if not secret_key:
        raise HTTPException(503, "Billing not configured. Add PAYSTACK_SECRET_KEY.")

    url = f"https://api.paystack.co{endpoint}"
    payload = json.dumps(data).encode() if data else None

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {secret_key}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        log.error(f"Paystack API error {e.code}: {body[:200]}")
        raise HTTPException(502, f"Billing service error: {e.code}")


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Paystack webhook HMAC-SHA512 signature."""
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "").encode()
    computed = hmac.new(secret, payload, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)


# ── Plan endpoints ────────────────────────────────────────────────────────────

@router.get("/plans")
def list_plans(plan_type: str = ""):
    """List all available plans."""
    plans = []
    for plan_id, plan in PLANS.items():
        if plan_type and plan["type"] != plan_type:
            continue
        plans.append({
            "id": plan_id,
            "name": plan["name"],
            "type": plan["type"],
            "price_ngn": plan["price_ngn"],
            "interval": plan.get("interval"),
            "features": plan["features"],
            "limits": plan["limits"],
        })
    return plans


@router.get("/my-subscription")
async def get_my_subscription(current_user: dict = Depends(get_current_user)):
    """Get current user's active subscription."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT s.*, p.name as plan_name, p.price_ngn
                FROM subscriptions s
                JOIN subscription_plans p ON s.plan_id = p.id
                WHERE s.user_id = %s AND s.status = 'active'
                ORDER BY s.created_at DESC LIMIT 1
            """, (str(current_user["id"]),))
        else:
            cur.execute("""
                SELECT s.*, p.name as plan_name, p.price_ngn
                FROM subscriptions s
                JOIN subscription_plans p ON s.plan_id = p.id
                WHERE s.user_id = ? AND s.status = 'active'
                ORDER BY s.created_at DESC LIMIT 1
            """, (str(current_user["id"]),))
        row = cur.fetchone()
        if not row:
            role = current_user.get("role", "candidate")
            default = "candidate_free" if role == "candidate" else "employer_free"
            plan = PLANS[default]
            return {
                "plan_id": default,
                "plan_name": plan["name"],
                "status": "active",
                "is_free": True,
                "features": plan["features"],
                "limits": plan["limits"],
            }
        sub = dict(row)
        plan_key = sub.get("plan_id", "candidate_free")
        plan_def = PLANS.get(plan_key, PLANS["candidate_free"])
        sub["features"] = plan_def["features"]
        sub["limits"] = plan_def["limits"]
        sub["is_free"] = plan_def["price_ngn"] == 0
        return sub


# ── Payment initiation ────────────────────────────────────────────────────────

class InitiatePaymentIn(BaseModel):
    plan_id: str
    callback_url: Optional[str] = ""


@router.post("/initiate")
async def initiate_payment(
    body: InitiatePaymentIn,
    current_user: dict = Depends(get_current_user),
):
    """
    Initiate Paystack payment for a plan.
    Returns authorization_url to redirect user to Paystack.
    """
    plan = PLANS.get(body.plan_id)
    if not plan:
        raise HTTPException(400, f"Unknown plan: {body.plan_id}")
    if plan["price_ngn"] == 0:
        raise HTTPException(400, "Free plans don't require payment")

    app_url = os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")
    callback = body.callback_url or f"{app_url}/billing/success"

    reference = f"js_{body.plan_id}_{uuid.uuid4().hex[:12]}"

    payload = {
        "email": current_user["email"],
        "amount": plan["price_ngn"] * 100,  # Paystack uses kobo
        "currency": "NGN",
        "reference": reference,
        "callback_url": callback,
        "metadata": {
            "user_id": str(current_user["id"]),
            "plan_id": body.plan_id,
            "plan_name": plan["name"],
        },
        "channels": ["card", "bank", "ussd", "mobile_money"],
    }

    # Use subscription if plan has a Paystack plan code
    if plan.get("paystack_plan_code"):
        payload["plan"] = plan["paystack_plan_code"]

    result = paystack_request("/transaction/initialize", "POST", payload)

    if not result.get("status"):
        raise HTTPException(502, "Failed to initialize payment")

    # Record pending transaction
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO billing_transactions
                    (id, user_id, plan_id, amount, currency, reference, status)
                VALUES (%s,%s,%s,%s,'NGN',%s,'pending')
                ON CONFLICT (reference) DO NOTHING
            """, (str(uuid.uuid4()), str(current_user["id"]),
                  body.plan_id, plan["price_ngn"], reference))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO billing_transactions
                    (id, user_id, plan_id, amount, currency, reference, status)
                VALUES (?,?,?,?,'NGN',?,'pending')
            """, (str(uuid.uuid4()), str(current_user["id"]),
                  body.plan_id, plan["price_ngn"], reference))

    log.info(f"Payment initiated: {reference} for {current_user['email']} ({body.plan_id})")

    return {
        "authorization_url": result["data"]["authorization_url"],
        "reference": reference,
        "amount_ngn": plan["price_ngn"],
        "plan": plan["name"],
    }


@router.get("/verify/{reference}")
async def verify_payment(
    reference: str,
    current_user: dict = Depends(get_current_user),
):
    """Manually verify a payment reference (for callback page)."""
    result = paystack_request(f"/transaction/verify/{reference}")

    if not result.get("status"):
        raise HTTPException(400, "Verification failed")

    txn = result["data"]
    if txn["status"] == "success":
        await _activate_subscription(
            txn["metadata"]["user_id"],
            txn["metadata"]["plan_id"],
            reference,
            txn["amount"] // 100,
        )
        return {"status": "success", "message": "Payment verified and subscription activated"}

    return {"status": txn["status"], "message": "Payment not completed"}


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str = Header(None),
):
    """
    Paystack webhook — called automatically when payment is made.
    Verify signature then activate subscription.
    """
    payload = await request.body()

    if not x_paystack_signature:
        raise HTTPException(400, "Missing signature")

    if not verify_webhook_signature(payload, x_paystack_signature):
        log.warning("Invalid Paystack webhook signature")
        raise HTTPException(400, "Invalid signature")

    event = json.loads(payload)
    event_type = event.get("event", "")
    data = event.get("data", {})

    log.info(f"Paystack webhook: {event_type}")

    if event_type == "charge.success":
        metadata = data.get("metadata", {})
        user_id = metadata.get("user_id")
        plan_id = metadata.get("plan_id")
        reference = data.get("reference")
        amount = data.get("amount", 0) // 100

        if user_id and plan_id:
            await _activate_subscription(user_id, plan_id, reference, amount)

    elif event_type == "subscription.disable":
        # Subscription cancelled — downgrade to free
        customer_email = data.get("customer", {}).get("email", "")
        if customer_email:
            await _cancel_subscription_by_email(customer_email)

    return {"status": "ok"}


async def _activate_subscription(
    user_id: str,
    plan_id: str,
    reference: str,
    amount: int,
):
    """Activate a subscription after successful payment."""
    plan = PLANS.get(plan_id, {})
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=30)

    with get_conn() as conn:
        cur = conn.cursor()

        # Cancel existing active subscriptions
        if USE_POSTGRES:
            cur.execute(
                "UPDATE subscriptions SET status='cancelled' WHERE user_id=%s AND status='active'",
                (user_id,)
            )
        else:
            cur.execute(
                "UPDATE subscriptions SET status='cancelled' WHERE user_id=? AND status='active'",
                (user_id,)
            )

        # Create new subscription
        sub_id = str(uuid.uuid4())
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO subscriptions
                    (id, user_id, plan_id, status, started_at, expires_at, paystack_reference)
                VALUES (%s,%s,%s,'active',%s,%s,%s)
            """, (sub_id, user_id, plan_id,
                  now.isoformat(), expires_at.isoformat(), reference))
        else:
            cur.execute("""
                INSERT INTO subscriptions
                    (id, user_id, plan_id, status, started_at, expires_at, paystack_reference)
                VALUES (?,?,'active',?,?,?,?)
            """, (sub_id, plan_id, user_id,
                  now.isoformat(), expires_at.isoformat(), reference))

        # Update transaction status
        if USE_POSTGRES:
            cur.execute(
                "UPDATE billing_transactions SET status='success' WHERE reference=%s",
                (reference,)
            )
        else:
            cur.execute(
                "UPDATE billing_transactions SET status='success' WHERE reference=?",
                (reference,)
            )

        # Update user role/plan
        new_role = "premium_candidate" if "candidate" in plan_id else "org_owner"
        if USE_POSTGRES:
            cur.execute("UPDATE users SET role=%s WHERE id=%s", (new_role, user_id))
        else:
            cur.execute("UPDATE users SET role=? WHERE id=?", (new_role, user_id))

        # Update tenant plan if employer
        if "employer" in plan_id:
            plan_tier = plan_id.replace("employer_", "")
            if USE_POSTGRES:
                cur.execute(
                    "UPDATE tenants SET plan=%s WHERE id=(SELECT tenant_id FROM users WHERE id=%s)",
                    (plan_tier, user_id)
                )
            else:
                cur.execute(
                    "UPDATE tenants SET plan=? WHERE id=(SELECT tenant_id FROM users WHERE id=?)",
                    (plan_tier, user_id)
                )

    log_action(
        "billing.subscription_activated",
        user_id=user_id,
        resource_type="subscription",
        resource_id=sub_id,
        new_value={"plan_id": plan_id, "amount": amount, "reference": reference},
        module="billing",
    )
    log.info(f"Subscription activated: {plan_id} for user {user_id}")


async def _cancel_subscription_by_email(email: str):
    """Cancel subscription when Paystack sends disable event."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                UPDATE subscriptions SET status='cancelled'
                WHERE user_id=(SELECT id FROM users WHERE email=%s)
                AND status='active'
            """, (email,))
            cur.execute(
                "UPDATE users SET role='candidate' WHERE email=%s AND role='premium_candidate'",
                (email,)
            )
        else:
            cur.execute("""
                UPDATE subscriptions SET status='cancelled'
                WHERE user_id=(SELECT id FROM users WHERE email=?)
                AND status='active'
            """, (email,))
    log.info(f"Subscription cancelled for {email}")


# ── Invoice / history ─────────────────────────────────────────────────────────

@router.get("/history")
async def billing_history(current_user: dict = Depends(get_current_user)):
    """Get billing history for current user."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT id, plan_id, amount, currency, status, reference, created_at
                FROM billing_transactions
                WHERE user_id = %s
                ORDER BY created_at DESC LIMIT 50
            """, (str(current_user["id"]),))
        else:
            cur.execute("""
                SELECT id, plan_id, amount, currency, status, reference, created_at
                FROM billing_transactions
                WHERE user_id = ?
                ORDER BY created_at DESC LIMIT 50
            """, (str(current_user["id"]),))
        return [dict(r) for r in cur.fetchall()]
