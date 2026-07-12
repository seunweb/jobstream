"""
Multi-Gateway Payment Router
- Paystack    → NGN (Nigeria) — 1.5% + ₦100, capped ₦2,000
- Flutterwave → African currencies (KES,GHS,ZAR,UGX,TZS,RWF,EGP,MAD) — 1.4%
- Paddle      → Global (USD,GBP,EUR,CAD,AUD,INR + others) — 5% + $0.50

Markup strategy: prices shown to users already include gateway fees
so the platform nets the full plan price every time.

Markup formulas (solve for gross so net = plan_price):
  Paystack:    gross = (net + 100_kobo) / (1 - 0.015)   [NGN kobo]
  Flutterwave: gross = net / (1 - 0.014)
  Paddle:      gross = (net + 0.50) / (1 - 0.05)
"""

import os, json, hmac, hashlib, logging, uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import BaseModel
from typing import Optional

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user
from services.identity.billing_admin_router import (
    _get_rates, _convert, CURRENCY_SYMBOLS, COUNTRY_CURRENCY,
    _ensure_tables, _first_val
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

# ── Gateway routing ───────────────────────────────────────────────────────────

GATEWAY_MAP = {
    "NGN": "paystack",
    "KES": "flutterwave", "GHS": "flutterwave", "ZAR": "flutterwave",
    "UGX": "flutterwave", "TZS": "flutterwave", "RWF": "flutterwave",
    "EGP": "flutterwave", "MAD": "flutterwave",
    "USD": "paddle", "GBP": "paddle", "EUR": "paddle",
    "CAD": "paddle", "AUD": "paddle", "INR": "paddle",
}

# Gateway fee structures
GATEWAY_FEES = {
    "paystack":    {"pct": 0.015, "fixed_usd": 0.063},  # 1.5% + ₦100 (~$0.063)
    "flutterwave": {"pct": 0.014, "fixed_usd": 0.0},    # 1.4%, no fixed
    "paddle":      {"pct": 0.05,  "fixed_usd": 0.50},   # 5% + $0.50
}


def get_gateway(currency: str) -> str:
    return GATEWAY_MAP.get(currency.upper(), "paddle")


def gross_price(net_usd: float, gateway: str) -> float:
    """
    Calculate gross price to charge so we net the full plan price.
    gross = (net + fixed) / (1 - pct)
    """
    fees = GATEWAY_FEES.get(gateway, GATEWAY_FEES["paddle"])
    return round((net_usd + fees["fixed_usd"]) / (1 - fees["pct"]), 2)


# ── Schemas ───────────────────────────────────────────────────────────────────

class InitiatePaymentIn(BaseModel):
    plan_id: str
    duration_id: str
    currency: Optional[str] = None
    gateway: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_plan(plan_id: str) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT * FROM billing_plans WHERE id = {ph}", (plan_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, f"Plan '{plan_id}' not found")
        p = dict(row)
        for k in ["features", "limits", "prices", "durations", "gateways"]:
            try:
                p[k] = json.loads(p[k]) if isinstance(p[k], str) else (p[k] or {})
            except Exception:
                p[k] = {}
        return p


def _get_duration(plan: dict, duration_id: str) -> dict:
    durations = plan.get("durations", [])
    if isinstance(durations, str):
        try: durations = json.loads(durations)
        except: durations = []
    for d in durations:
        if d.get("id") == duration_id:
            return d
    raise HTTPException(400, f"Duration '{duration_id}' not found in plan")


def _create_order(user_id, tenant_id, plan_id, duration_id,
                   amount_gross_local, amount_net_usd, amount_gross_usd,
                   currency, gateway, ip, country) -> str:
    order_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute("""
                INSERT INTO billing_orders
                    (id, user_id, tenant_id, plan_id, duration, amount,
                     currency, amount_usd, status, gateway,
                     ip_address, country_code, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,NOW())
            """, (order_id, str(user_id), str(tenant_id or ""),
                  plan_id, duration_id, amount_gross_local,
                  currency, amount_net_usd, gateway, ip, country))
        else:
            cur.execute("""
                INSERT INTO billing_orders
                    (id, user_id, tenant_id, plan_id, duration, amount,
                     currency, amount_usd, status, gateway,
                     ip_address, country_code, created_at)
                VALUES (?,?,?,?,?,?,?,?,'pending',?,?,?,?)
            """, (order_id, str(user_id), str(tenant_id or ""),
                  plan_id, duration_id, amount_gross_local,
                  currency, amount_net_usd, gateway, ip, country, now))
    return order_id


def _activate_subscription(order_id, user_id, tenant_id, plan_id,
                             duration_id, amount_usd, currency, gateway_ref):
    plan = _get_plan(plan_id)
    dur = _get_duration(plan, duration_id)
    months = int(dur.get("months", 1))
    expires_at = datetime.now(timezone.utc) + timedelta(days=30 * months)
    now = datetime.now(timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"

        if USE_POSTGRES:
            cur.execute(
                "UPDATE billing_orders SET status='paid', gateway_ref=%s, paid_at=NOW(), expires_at=%s WHERE id=%s",
                (gateway_ref, expires_at.isoformat(), order_id)
            )
            cur.execute("""
                INSERT INTO subscriptions
                    (id, user_id, tenant_id, plan_id, status, gateway,
                     current_period_start, current_period_end, created_at)
                VALUES (gen_random_uuid(),%s,%s,%s,'active',%s,NOW(),%s,NOW())
                ON CONFLICT (tenant_id) DO UPDATE SET
                    plan_id=EXCLUDED.plan_id, status='active',
                    current_period_end=EXCLUDED.current_period_end,
                    gateway=EXCLUDED.gateway
            """, (str(user_id), str(tenant_id or ""), plan_id,
                  "multi", expires_at.isoformat()))
        else:
            cur.execute(
                "UPDATE billing_orders SET status='paid', gateway_ref=?, paid_at=?, expires_at=? WHERE id=?",
                (gateway_ref, now, expires_at.isoformat(), order_id)
            )
            sub_id = str(uuid.uuid4())
            cur.execute("""
                INSERT OR REPLACE INTO subscriptions
                    (id, user_id, tenant_id, plan_id, status, gateway,
                     current_period_start, current_period_end, created_at)
                VALUES (?,?,?,?,'active','multi',?,?,?)
            """, (sub_id, str(user_id), str(tenant_id or ""), plan_id,
                  now, expires_at.isoformat(), now))

        cur.execute(
            f"UPDATE tenants SET plan = {ph} WHERE id = {ph}",
            (plan_id, str(tenant_id or ""))
        )
    # Apply plan limits and features to tenant
    try:
        from services.identity.quota_router import apply_plan_to_tenant
        from services.identity.billing_admin_router import _get_plan as _bp
        plan_data = _bp(plan_id)
        apply_plan_to_tenant(str(tenant_id or user_id), plan_id, plan_data,
                             duration_id, expires_at.isoformat())
    except Exception as qe:
        log.warning(f"Quota apply failed: {qe}")

    log.info(f"Subscription activated: user={user_id} plan={plan_id} until={expires_at.date()}")


# ── Detect currency from IP ───────────────────────────────────────────────────

def _detect_currency(request: Request) -> tuple[str, str]:
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not ip:
        ip = request.client.host
    if ip in ("127.0.0.1", "::1"):
        return "USD", "US"
    try:
        import urllib.request as _req
        with _req.urlopen(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3) as r:
            data = json.loads(r.read())
        country = data.get("countryCode", "US")
        return COUNTRY_CURRENCY.get(country, "USD"), country
    except Exception:
        return "USD", "US"


# ── Pricing endpoint ──────────────────────────────────────────────────────────

@router.get("/pricing")
async def pricing(request: Request, currency: str = Query("")):
    """
    Public pricing page data.
    Returns plan prices in local currency WITH gateway markup included.
    Customer sees one clean price; platform nets the full plan amount.
    """
    if not currency:
        currency, _ = _detect_currency(request)

    rates = _get_rates()
    rate = rates.get(currency, 1.0)   # 1 currency = rate USD
    symbol = CURRENCY_SYMBOLS.get(currency, "$")
    gateway = get_gateway(currency)

    _ensure_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        active = "is_active = TRUE" if USE_POSTGRES else "is_active = 1"
        cur.execute(f"SELECT * FROM billing_plans WHERE {active} ORDER BY sort_order")
        plans = []
        for r in cur.fetchall():
            p = dict(r)
            for k in ["features", "limits", "prices", "durations", "gateways"]:
                try:
                    p[k] = json.loads(p[k]) if isinstance(p[k], str) else (p[k] or {})
                except Exception:
                    p[k] = {}

            usd_prices = p["prices"].get("USD", {})
            p["pricing"] = {}
            for dur_id, net_usd in usd_prices.items():
                net_usd = float(net_usd)
                # Calculate gross so we net the plan price after gateway fees
                gross_usd = gross_price(net_usd, gateway)
                # Convert gross to local currency
                gross_local = round(gross_usd / rate, 2) if rate else gross_usd
                # Format display price
                if currency in ("NGN", "KES", "GHS", "UGX", "TZS", "RWF"):
                    display = f"{symbol}{gross_local:,.0f}"  # no decimals for large currencies
                else:
                    display = f"{symbol}{gross_local:,.2f}"

                p["pricing"][dur_id] = {
                    "net_usd": net_usd,           # what platform receives
                    "gross_usd": gross_usd,        # what customer pays in USD
                    "gross_local": gross_local,    # what customer pays in local currency
                    "currency": currency,
                    "symbol": symbol,
                    "display": display,            # formatted display price
                    "gateway": gateway,
                }
            plans.append(p)

    return {
        "plans": plans,
        "currency": currency,
        "symbol": symbol,
        "gateway": gateway,
    }


# ── Initiate payment ──────────────────────────────────────────────────────────

@router.post("/initiate")
async def initiate_payment(
    body: InitiatePaymentIn,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    _ensure_tables()
    plan = _get_plan(body.plan_id)
    dur = _get_duration(plan, body.duration_id)

    # Detect currency
    if body.currency:
        currency = body.currency.upper()
        country = "XX"
    else:
        currency, country = _detect_currency(request)

    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.client.host
    rates = _get_rates()
    rate = rates.get(currency, 1.0)
    symbol = CURRENCY_SYMBOLS.get(currency, "$")
    gateway = body.gateway or get_gateway(currency)

    # Calculate prices
    usd_prices = plan.get("prices", {}).get("USD", {})
    net_usd = float(usd_prices.get(body.duration_id, 0))
    if net_usd == 0:
        raise HTTPException(400, "No price configured for this plan/duration")

    gross_usd = gross_price(net_usd, gateway)
    gross_local = round(gross_usd / rate, 2) if rate else gross_usd

    frontend_url = os.environ.get("FRONTEND_URL", os.environ.get("APP_URL", "")).rstrip("/")
    success_url = body.success_url or f"{frontend_url}/?billing=success"
    cancel_url = body.cancel_url or f"{frontend_url}/?billing=cancel"

    order_id = _create_order(
        current_user["id"], current_user.get("tenant_id"),
        body.plan_id, body.duration_id,
        gross_local, net_usd, gross_usd,
        currency, gateway, ip, country
    )

    email = current_user.get("email", "")
    name = current_user.get("full_name", email)
    checkout_url = None

    # ── Paystack (NGN) ────────────────────────────────────────────────────────
    if gateway == "paystack":
        key = os.environ.get("PAYSTACK_SECRET_KEY", "")
        if not key:
            raise HTTPException(503, "Paystack not configured")
        import urllib.request as _req
        amount_kobo = int(gross_local * 100)
        payload = json.dumps({
            "email": email,
            "amount": amount_kobo,
            "currency": "NGN",
            "reference": order_id,
            "callback_url": f"{frontend_url}/?billing=success&order={order_id}",
            "metadata": {
                "order_id": order_id, "plan_id": body.plan_id,
                "duration_id": body.duration_id,
                "user_id": str(current_user["id"]),
                "tenant_id": str(current_user.get("tenant_id", "")),
            }
        }).encode()
        req = _req.Request(
            "https://api.paystack.co/transaction/initialize",
            data=payload,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"}
        )
        try:
            with _req.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            checkout_url = resp["data"]["authorization_url"]
        except Exception as e:
            raise HTTPException(502, f"Paystack error: {e}")

    # ── Flutterwave (African currencies) ──────────────────────────────────────
    elif gateway == "flutterwave":
        key = os.environ.get("FLW_SECRET_KEY", "")
        if not key:
            raise HTTPException(503, "Flutterwave not configured")
        import urllib.request as _req
        payload = json.dumps({
            "tx_ref": order_id,
            "amount": gross_local,
            "currency": currency,
            "redirect_url": f"{frontend_url}/?billing=success&order={order_id}",
            "customer": {"email": email, "name": name},
            "meta": {
                "order_id": order_id, "plan_id": body.plan_id,
                "user_id": str(current_user["id"]),
            },
            "customizations": {
                "title": plan.get("name", ""),
                "description": f"{dur.get('label', '')} subscription",
            },
        }).encode()
        req = _req.Request(
            "https://api.flutterwave.com/v3/payments",
            data=payload,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"}
        )
        try:
            with _req.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            checkout_url = resp["data"]["link"]
        except Exception as e:
            raise HTTPException(502, f"Flutterwave error: {e}")

    # ── Paddle (Global) ───────────────────────────────────────────────────────
    elif gateway == "paddle":
        key = os.environ.get("PADDLE_API_KEY", "")
        client_token = os.environ.get("PADDLE_CLIENT_TOKEN", "")
        if not key:
            raise HTTPException(503, "Paddle not configured (missing PADDLE_API_KEY)")
        import urllib.request as _req

        # Paddle Billing API - create a transaction
        paddle_env = os.environ.get("PADDLE_ENV", "sandbox")
        base_url = "https://api.paddle.com" if paddle_env == "production" else "https://sandbox-api.paddle.com"

        payload = json.dumps({
            "items": [{
                "quantity": 1,
                "price": {
                    "description": f"{plan.get('name','')} - {dur.get('label','')}",
                    "unit_price": {
                        "amount": str(int(gross_usd * 100)),  # cents
                        "currency_code": "USD",
                    },
                    "billing_cycle": None,  # one-time
                    "name": f"{plan.get('name','')} {dur.get('label','')}",
                }
            }],
            "customer": {"email": email},
            "custom_data": {
                "order_id": order_id,
                "plan_id": body.plan_id,
                "duration_id": body.duration_id,
                "user_id": str(current_user["id"]),
                "tenant_id": str(current_user.get("tenant_id", "")),
            },
            "checkout": {
                "url": f"{frontend_url}/?billing=success&order={order_id}",
            }
        }).encode()

        req = _req.Request(
            f"{base_url}/transactions",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
        )
        try:
            with _req.urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
            checkout_url = resp["data"]["checkout"]["url"]
        except Exception as e:
            raise HTTPException(502, f"Paddle error: {e}")
    else:
        raise HTTPException(400, f"Unknown gateway: {gateway}")

    if currency in ("NGN", "KES", "GHS", "UGX", "TZS", "RWF"):
        display_price = f"{symbol}{gross_local:,.0f}"
    else:
        display_price = f"{symbol}{gross_local:,.2f}"

    return {
        "order_id": order_id,
        "checkout_url": checkout_url,
        "gateway": gateway,
        "currency": currency,
        "symbol": symbol,
        "display_price": display_price,
        "amount_local": gross_local,
        "amount_usd": gross_usd,
        "plan": plan.get("name"),
        "duration": dur.get("label"),
    }


# ── Webhooks ──────────────────────────────────────────────────────────────────

@router.post("/webhook/paystack")
async def paystack_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("x-paystack-signature", "")
    secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
    expected = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(400, "Invalid signature")
    data = json.loads(body)
    if data.get("event") != "charge.success":
        return {"received": True}
    d = data["data"]
    order_id = d.get("reference") or d.get("metadata", {}).get("order_id", "")
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT * FROM billing_orders WHERE id = {ph}", (order_id,))
        order = cur.fetchone()
    if not order:
        return {"received": True}
    order = dict(order)
    _activate_subscription(order_id, order["user_id"], order["tenant_id"],
                           order["plan_id"], order["duration"],
                           order["amount_usd"], order["currency"], str(d.get("id", "")))
    return {"received": True}


@router.post("/webhook/flutterwave")
async def flutterwave_webhook(request: Request):
    body_text = await request.body()
    sig = request.headers.get("verif-hash", "")
    expected = os.environ.get("FLW_WEBHOOK_HASH", "")
    if expected and sig != expected:
        raise HTTPException(400, "Invalid signature")
    data = json.loads(body_text)
    if data.get("event") != "charge.completed" or data.get("data", {}).get("status") != "successful":
        return {"received": True}
    d = data["data"]
    order_id = d.get("tx_ref", "")
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT * FROM billing_orders WHERE id = {ph}", (order_id,))
        order = cur.fetchone()
    if not order:
        return {"received": True}
    order = dict(order)
    _activate_subscription(order_id, order["user_id"], order["tenant_id"],
                           order["plan_id"], order["duration"],
                           order["amount_usd"], order["currency"], str(d.get("id", "")))
    return {"received": True}


@router.post("/webhook/paddle")
async def paddle_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("paddle-signature", "")
    secret = os.environ.get("PADDLE_WEBHOOK_SECRET", "")
    if secret and sig:
        try:
            parts = {k: v for part in sig.split(";") for k, v in [part.split("=", 1)]}
            ts = parts.get("ts", "")
            signed = f"{ts}:{body.decode()}"
            expected = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, parts.get("h1", "")):
                raise HTTPException(400, "Invalid Paddle signature")
        except HTTPException:
            raise
        except Exception as e:
            log.warning(f"Paddle sig error: {e}")

    data = json.loads(body)
    event = data.get("event_type", "")
    if event not in ("transaction.completed", "transaction.paid"):
        return {"received": True}

    txn = data.get("data", {})
    custom = txn.get("custom_data", {})
    order_id = custom.get("order_id", "")
    gateway_ref = txn.get("id", "")

    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT * FROM billing_orders WHERE id = {ph}", (order_id,))
        order = cur.fetchone()
    if not order:
        return {"received": True}
    order = dict(order)
    _activate_subscription(order_id, order["user_id"], order["tenant_id"],
                           order["plan_id"], order["duration"],
                           order["amount_usd"], order["currency"], gateway_ref)
    return {"received": True}


# ── Verify & subscription endpoints ──────────────────────────────────────────

@router.get("/verify/{order_id}")
async def verify_payment(order_id: str, current_user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT * FROM billing_orders WHERE id = {ph}", (order_id,))
        order = cur.fetchone()
    if not order:
        raise HTTPException(404, "Order not found")
    order = dict(order)
    return {
        "order_id": order_id,
        "status": order["status"],
        "plan_id": order["plan_id"],
        "currency": order["currency"],
        "amount": order["amount"],
        "paid_at": str(order.get("paid_at", "")) if order.get("paid_at") else None,
    }


@router.get("/my-subscription")
async def my_subscription(current_user: dict = Depends(get_current_user)):
    tenant_id = current_user.get("tenant_id")
    user_id = str(current_user["id"])
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        if tenant_id:
            cur.execute(
                f"SELECT * FROM subscriptions WHERE tenant_id = {ph} AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (str(tenant_id),)
            )
        else:
            cur.execute(
                f"SELECT * FROM subscriptions WHERE user_id = {ph} AND status = 'active' ORDER BY created_at DESC LIMIT 1",
                (user_id,)
            )
        sub = cur.fetchone()
        if not sub:
            return {"plan": "free", "status": "free", "expires_at": None}
        sub = dict(sub)
        if sub.get("plan_id"):
            try:
                plan = _get_plan(sub["plan_id"])
                sub["plan_name"] = plan.get("name", "")
                sub["plan_features"] = plan.get("features", [])
            except Exception:
                pass
    return sub
