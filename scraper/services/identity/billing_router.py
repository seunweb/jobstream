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


def _get_plan_from_db(plan_id: str):
    """Fetch a single plan from billing_plans table. Returns None if not found."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                import psycopg2.extras
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT * FROM billing_plans WHERE id=%s", (plan_id,))
            else:
                cur.execute("SELECT * FROM billing_plans WHERE id=?", (plan_id,))
                cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            if not row:
                return None
            if not USE_POSTGRES:
                row = dict(zip(cols, row))
            row = dict(row)
            for f in ("features", "feature_list", "limits", "prices", "durations", "gateways"):
                if isinstance(row.get(f), str):
                    try:
                        row[f] = json.loads(row[f])
                    except Exception:
                        row[f] = {} if f != "feature_list" and f != "durations" and f != "gateways" else []
            return row
    except Exception:
        return None


def _get_free_plan_from_db(plan_type: str = "candidate"):
    """
    Get the free plan for a given type from DB.
    Looks for a plan with price_usd=0 (or price_ngn=0) first,
    then falls back to the lowest sort_order plan.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                import psycopg2.extras
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # Try to find an explicitly free plan first
                cur.execute(
                    "SELECT * FROM billing_plans WHERE type=%s AND is_active=true "
                    "AND (price_usd=0 OR price_ngn=0 OR id LIKE '%%_free') "
                    "ORDER BY sort_order ASC LIMIT 1",
                    (plan_type,)
                )
                row = cur.fetchone()
                if not row:
                    # No free plan exists — return None so UI shows no current plan
                    return None
            else:
                cur.execute(
                    "SELECT * FROM billing_plans WHERE type=? AND is_active=1 "
                    "AND (price_usd=0 OR price_ngn=0 OR id LIKE ?)"
                    " ORDER BY sort_order ASC LIMIT 1",
                    (plan_type, f"%_free")
                )
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    return None
            if not row:
                return None
            if not USE_POSTGRES:
                row = dict(zip(cols, row))
            row = dict(row)
            for f in ("features", "feature_list", "limits", "prices", "durations", "gateways"):
                if isinstance(row.get(f), str):
                    try:
                        row[f] = json.loads(row[f])
                    except Exception:
                        row[f] = {} if f != "feature_list" and f != "durations" and f != "gateways" else []
            return row
    except Exception:
        return None




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
    """List active plans from DB."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                import psycopg2.extras
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                q = "SELECT * FROM billing_plans WHERE is_active=true"
                params = []
                if plan_type:
                    q += " AND type=%s"
                    params.append(plan_type)
                q += " ORDER BY sort_order ASC, created_at ASC"
                cur.execute(q, params)
                rows = cur.fetchall()
            else:
                # SQLite stores booleans as 0/1 but JSON True may come in as 1 or "true"
                q = "SELECT * FROM billing_plans WHERE is_active NOT IN (0, 'false', 'False', '')"
                params = []
                if plan_type:
                    q += " AND type=?"
                    params.append(plan_type)
                q += " ORDER BY sort_order ASC, created_at ASC"
                cur.execute(q, params)
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        result = []
        for row in rows:
            row = dict(row)
            prices = json.loads(row["prices"]) if isinstance(row.get("prices"), str) else (row.get("prices") or {})
            features = json.loads(row["features"]) if isinstance(row.get("features"), str) else (row.get("features") or {})
            feature_list = json.loads(row["feature_list"]) if isinstance(row.get("feature_list"), str) else (row.get("feature_list") or [])
            limits = json.loads(row["limits"]) if isinstance(row.get("limits"), str) else (row.get("limits") or {})
            durations = json.loads(row["durations"]) if isinstance(row.get("durations"), str) else (row.get("durations") or [])
            usd_price = 0
            if durations and prices.get("USD"):
                first_dur = durations[0].get("id", "")
                usd_price = float(prices["USD"].get(first_dur, 0) or 0)
            try:
                ngn_rate = _get_fx_rate("NGN")
                price_ngn = round(usd_price / ngn_rate) if ngn_rate and usd_price else 0
            except Exception:
                price_ngn = round(usd_price * 1600) if usd_price else 0
            result.append({
                "id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "description": row.get("description", ""),
                "price_ngn": price_ngn,
                "price_usd": usd_price,
                "prices": prices,
                "durations": durations,
                "interval": durations[0].get("id") if durations else "monthly",
                "features": features,
                "feature_list": feature_list,
                "limits": limits,
                "is_featured": bool(row.get("is_featured")),
                "sort_order": row.get("sort_order", 0),
            })
        return result
    except Exception as e:
        raise HTTPException(500, f"Failed to load plans: {e}")

@router.get("/my-subscription")
async def get_my_subscription(current_user: dict = Depends(get_current_user)):
    """Get current user's active subscription."""
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                SELECT s.*, p.name as plan_name
                FROM subscriptions s
                JOIN subscription_plans p ON s.plan_id = p.id
                WHERE s.user_id = %s AND s.status = 'active'
                ORDER BY s.created_at DESC LIMIT 1
            """, (str(current_user["id"]),))
        else:
            cur.execute("""
                SELECT s.*, p.name as plan_name
                FROM subscriptions s
                JOIN subscription_plans p ON s.plan_id = p.id
                WHERE s.user_id = ? AND s.status = 'active'
                ORDER BY s.created_at DESC LIMIT 1
            """, (str(current_user["id"]),))
        row = cur.fetchone()
        if not row:
            role = current_user.get("role", "candidate")
            default = "candidate_free" if role == "candidate" else "employer_free"
            role = current_user.get("role", "candidate")
            plan_type = "candidate" if "candidate" in role else "employer"
            free_plan = _get_free_plan_from_db(plan_type)
            if free_plan:
                return {
                    "plan_id":   free_plan.get("id", plan_type + "_free"),
                    "plan_name": free_plan.get("name", "Free"),
                    "status":    "active",
                    "is_free":   True,
                    "features":  free_plan.get("features", {}),
                    "limits":    free_plan.get("limits", {}),
                }
            # No plan at all — return empty subscription so UI shows "Choose a plan"
            return {
                "plan_id":   None,
                "plan_name": None,
                "status":    "none",
                "is_free":   False,
                "features":  {},
                "limits":    {},
            }
        sub = dict(row)
        plan_key = sub.get("plan_id", "")
        plan_def = _get_plan_from_db(plan_key) or {}
        sub["features"] = plan_def.get("features", {})
        sub["limits"] = plan_def.get("limits", {})
        prices = plan_def.get("prices", {})
        durations = plan_def.get("durations", [])
        usd_price = 0
        if durations and prices.get("USD"):
            usd_price = float(prices["USD"].get(durations[0].get("id",""), 0) or 0)
        sub["is_free"] = usd_price == 0
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
    plan = _get_plan_from_db(body.plan_id)
    if not plan:
        raise HTTPException(400, f"Unknown plan: {body.plan_id}")
    prices = plan.get("prices", {})
    durations = plan.get("durations", [])
    usd_price = 0
    if durations and prices.get("USD"):
        usd_price = float(prices["USD"].get(durations[0].get("id",""), 0) or 0)
    if usd_price == 0:
        raise HTTPException(400, "Free plans don't require payment")
    try:
        ngn_rate = _get_fx_rate("NGN")
        price_ngn = round(usd_price / ngn_rate) if ngn_rate else round(usd_price * 1600)
    except Exception:
        price_ngn = round(usd_price * 1600)

    app_url = os.environ.get("APP_URL", "http://localhost:3000").rstrip("/")
    callback = body.callback_url or f"{app_url}/billing/success"

    reference = f"js_{body.plan_id}_{uuid.uuid4().hex[:12]}"

    payload = {
        "email": current_user["email"],
        "amount": price_ngn * 100,  # Paystack uses kobo
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
                  body.plan_id, price_ngn, reference))
        else:
            cur.execute("""
                INSERT OR IGNORE INTO billing_transactions
                    (id, user_id, plan_id, amount, currency, reference, status)
                VALUES (?,?,?,?,'NGN',?,'pending')
            """, (str(uuid.uuid4()), str(current_user["id"]),
                  body.plan_id, price_ngn, reference))

    log.info(f"Payment initiated: {reference} for {current_user['email']} ({body.plan_id})")

    return {
        "authorization_url": result["data"]["authorization_url"],
        "reference": reference,
        "amount_ngn": price_ngn,
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
    plan = _get_plan_from_db(plan_id) or {}
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
