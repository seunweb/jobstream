"""
Admin Billing Management Router
- Revenue dashboard stats
- Plan CRUD with custom durations and per-currency pricing
- Order management
- FX rate management
- IP-based currency detection
"""

import os, json, logging, uuid
from datetime import datetime, timezone
from typing import Optional, List, Union
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from pydantic import BaseModel

from core.database import get_conn, USE_POSTGRES
from services.identity.dependencies import get_current_user
from services.identity.admin_router import require_platform_admin
from core.audit import log_action

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/billing", tags=["admin-billing"])

CURRENCY_SYMBOLS = {
    "USD":"$","NGN":"N","GBP":"£","EUR":"€","KES":"KSh","GHS":"GH₵",
    "ZAR":"R","UGX":"USh","TZS":"TSh","RWF":"Fr","EGP":"E£","MAD":"MAD",
    "CAD":"CA$","AUD":"A$","INR":"₹",
}
COUNTRY_CURRENCY = {
    "NG":"NGN","US":"USD","GB":"GBP","DE":"EUR","FR":"EUR","KE":"KES",
    "GH":"GHS","ZA":"ZAR","UG":"UGX","TZ":"TZS","RW":"RWF","EG":"EGP",
    "MA":"MAD","CA":"CAD","AU":"AUD","IN":"INR","NL":"EUR","IT":"EUR",
    "ES":"EUR","BE":"EUR",
}

# Lazy migration
_migrated = False

def _ensure_tables():
    global _migrated
    if _migrated:
        return
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS billing_plans (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        type TEXT DEFAULT 'employer', description TEXT DEFAULT '',
                        is_active BOOLEAN DEFAULT TRUE, is_featured BOOLEAN DEFAULT FALSE,
                        sort_order INTEGER DEFAULT 0,
                        features JSONB DEFAULT '{}', feature_list JSONB DEFAULT '[]', limits JSONB DEFAULT '{}',
                        prices JSONB DEFAULT '{}', durations JSONB DEFAULT '[]',
                        gateways JSONB DEFAULT '{}',
                        created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS billing_orders (
                        id TEXT PRIMARY KEY, user_id TEXT, tenant_id TEXT, plan_id TEXT,
                        duration TEXT DEFAULT 'monthly', amount NUMERIC(12,2),
                        currency TEXT DEFAULT 'NGN', amount_usd NUMERIC(12,2),
                        status TEXT DEFAULT 'pending', gateway TEXT DEFAULT 'paystack',
                        gateway_ref TEXT, gateway_data JSONB DEFAULT '{}',
                        ip_address TEXT, country_code TEXT,
                        created_at TIMESTAMP DEFAULT NOW(), paid_at TIMESTAMP, expires_at TIMESTAMP
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fx_rates (
                        currency TEXT PRIMARY KEY,
                        rate_to_usd NUMERIC(18,6) DEFAULT 1.0,
                        updated_at TIMESTAMP DEFAULT NOW()
                    )
                """)
                default_rates = [
                    ("USD",1.0),("NGN",0.00063),("GBP",1.27),("EUR",1.09),
                    ("KES",0.0077),("GHS",0.067),("ZAR",0.055),("UGX",0.00027),
                    ("TZS",0.00038),("CAD",0.73),("AUD",0.65),("INR",0.012),
                    ("EGP",0.021),("MAD",0.099),("RWF",0.00077),
                ]
                for curr, rate in default_rates:
                    cur.execute(
                        "INSERT INTO fx_rates(currency,rate_to_usd) VALUES(%s,%s) ON CONFLICT(currency) DO NOTHING",
                        (curr, rate)
                    )
            else:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS billing_plans (
                        id TEXT PRIMARY KEY, name TEXT, type TEXT DEFAULT 'employer',
                        description TEXT DEFAULT '', is_active INTEGER DEFAULT 1,
                        is_featured INTEGER DEFAULT 0, sort_order INTEGER DEFAULT 0,
                        features TEXT DEFAULT '{}', feature_list TEXT DEFAULT '[]', limits TEXT DEFAULT '{}',
                        prices TEXT DEFAULT '{}', durations TEXT DEFAULT '[]',
                        gateways TEXT DEFAULT '{}', created_at TEXT, updated_at TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS billing_orders (
                        id TEXT PRIMARY KEY, user_id TEXT, tenant_id TEXT, plan_id TEXT,
                        duration TEXT, amount REAL, currency TEXT, amount_usd REAL,
                        status TEXT DEFAULT 'pending', gateway TEXT, gateway_ref TEXT,
                        gateway_data TEXT, ip_address TEXT, country_code TEXT,
                        created_at TEXT, paid_at TEXT, expires_at TEXT
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS fx_rates (
                        currency TEXT PRIMARY KEY, rate_to_usd REAL DEFAULT 1.0, updated_at TEXT
                    )
                """)
        # Add feature_list to existing billing_plans if missing
        try:
            if USE_POSTGRES:
                cur.execute("ALTER TABLE billing_plans ADD COLUMN IF NOT EXISTS feature_list JSONB DEFAULT '[]'")
            else:
                cur.execute("ALTER TABLE billing_plans ADD COLUMN feature_list TEXT DEFAULT '[]'")
        except Exception:
            pass

        # Add amount_usd to existing billing_orders if missing
        try:
            if USE_POSTGRES:
                cur.execute("ALTER TABLE billing_orders ADD COLUMN IF NOT EXISTS amount_usd NUMERIC(12,2)")
            else:
                cur.execute("ALTER TABLE billing_orders ADD COLUMN amount_usd REAL")
        except Exception:
            pass  # column already exists

        _migrated = True
        log.info("Billing tables ready")
    except Exception as e:
        log.warning(f"Billing migration skipped: {e}")


def _j(val):
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val) if val else {}
    except Exception:
        return {}


def _get_rates():
    _ensure_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT currency, rate_to_usd FROM fx_rates")
        return {dict(r)["currency"]: float(dict(r)["rate_to_usd"]) for r in cur.fetchall()}


def _convert(usd_amount, currency, rates):
    """Convert USD amount to target currency."""
    if currency == "USD":
        return usd_amount
    rate = rates.get(currency, 1.0)  # 1 currency = X USD, so 1 USD = 1/rate currency
    return round(usd_amount / rate, 2) if rate else usd_amount


def _first_val(row):
    return list(dict(row).values())[0] if row else 0


# ── Revenue stats ─────────────────────────────────────────────────────────────

@router.get("/stats")
async def billing_stats(current_user: dict = Depends(require_platform_admin)):
    _ensure_tables()
    with get_conn() as conn:
        cur = conn.cursor()

        # Support both amount_usd (new) and amount_ngn (legacy) column names
        amt_col = "amount_usd"
        try:
            cur.execute(f"SELECT COALESCE(SUM({amt_col}),0) FROM billing_orders WHERE status='paid'")
            cur.fetchone()
        except Exception:
            amt_col = "amount_ngn"  # fallback to legacy column

        cur.execute(f"SELECT COALESCE(SUM({amt_col}),0) FROM billing_orders WHERE status='paid'")
        total = float(_first_val(cur.fetchone()))

        if USE_POSTGRES:
            cur.execute(f"SELECT COALESCE(SUM({amt_col}),0) FROM billing_orders WHERE status='paid' AND paid_at >= DATE_TRUNC('month',NOW())")
        else:
            cur.execute(f"SELECT COALESCE(SUM({amt_col}),0) FROM billing_orders WHERE status='paid' AND paid_at >= DATE('now','start of month')")
        this_month = float(_first_val(cur.fetchone()))

        if USE_POSTGRES:
            cur.execute(f"SELECT COALESCE(SUM({amt_col}),0) FROM billing_orders WHERE status='paid' AND paid_at >= DATE_TRUNC('month',NOW())-INTERVAL '1 month' AND paid_at < DATE_TRUNC('month',NOW())")
        else:
            cur.execute(f"SELECT COALESCE(SUM({amt_col}),0) FROM billing_orders WHERE status='paid' AND paid_at >= DATE('now','start of month','-1 month') AND paid_at < DATE('now','start of month')")
        last_month = float(_first_val(cur.fetchone()))

        cur.execute("SELECT COUNT(*) FROM subscriptions WHERE status='active'")
        active_subs = int(_first_val(cur.fetchone()))

        if USE_POSTGRES:
            cur.execute("SELECT COUNT(*) FROM billing_orders WHERE paid_at >= DATE_TRUNC('month',NOW())")
        else:
            cur.execute("SELECT COUNT(*) FROM billing_orders WHERE paid_at >= DATE('now','start of month')")
        orders_month = int(_first_val(cur.fetchone()))

        cur.execute("SELECT plan_id, COUNT(*) as count, COALESCE(SUM(amount_usd),0) as revenue FROM billing_orders WHERE status='paid' GROUP BY plan_id ORDER BY revenue DESC")
        by_plan = [dict(r) for r in cur.fetchall()]

        cur.execute("SELECT currency, COUNT(*) as count, COALESCE(SUM(amount),0) as revenue FROM billing_orders WHERE status='paid' GROUP BY currency ORDER BY count DESC")
        by_currency = [dict(r) for r in cur.fetchall()]

        if USE_POSTGRES:
            cur.execute("SELECT o.*, u.email FROM billing_orders o LEFT JOIN users u ON u.id::text=o.user_id WHERE o.status='paid' ORDER BY o.paid_at DESC LIMIT 10")
        else:
            cur.execute("SELECT o.*, u.email FROM billing_orders o LEFT JOIN users u ON u.id=o.user_id WHERE o.status='paid' ORDER BY o.paid_at DESC LIMIT 10")
        recent = [dict(r) for r in cur.fetchall()]

    growth = round((this_month - last_month) / last_month * 100, 1) if last_month > 0 else 0
    return {
        "total_revenue_usd": total,
        "revenue_this_month_usd": this_month,
        "revenue_last_month_usd": last_month,
        "mrr_usd": this_month,
        "arr_usd": this_month * 12,
        "growth_pct": growth,
        "active_subscriptions": active_subs,
        "orders_this_month": orders_month,
        "by_plan": by_plan,
        "by_currency": by_currency,
        "recent_orders": recent,
    }


# ── Plans CRUD ────────────────────────────────────────────────────────────────

class PlanIn(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "employer"
    description: str = ""
    is_active: bool = True
    is_featured: bool = False
    sort_order: int = 0
    features: Union[dict, List[str]] = {}  # dict of feature flags OR list of strings (legacy)
    limits: dict = {}
    prices: dict = {}
    durations: List[dict] = []
    gateways: dict = {}
    feature_list: list = []  # Marketing bullet points shown on pricing page


@router.get("/plans")
async def list_plans(current_user: dict = Depends(require_platform_admin)):
    _ensure_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM billing_plans ORDER BY sort_order, name")
        plans = []
        for r in cur.fetchall():
            p = dict(r)
            for k in ["features","feature_list","limits","prices","durations","gateways"]:
                p[k] = _j(p.get(k))
            plans.append(p)
    return plans


@router.post("/plans", status_code=201)
async def create_plan(body: PlanIn, current_user: dict = Depends(require_platform_admin)):
    _ensure_tables()
    plan_id = body.id or f"plan_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            try:
                cur.execute(
                    "INSERT INTO billing_plans(id,name,type,description,is_active,is_featured,sort_order,features,feature_list,limits,prices,durations,gateways,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())",
                    (plan_id, body.name, body.type, body.description, body.is_active, body.is_featured, body.sort_order,
                     json.dumps(body.features), json.dumps(body.feature_list), json.dumps(body.limits), json.dumps(body.prices),
                     json.dumps(body.durations), json.dumps(body.gateways))
                )
            except Exception:
                # feature_list column may not exist yet - run migration then retry
                _ensure_tables()
                cur.execute(
                    "INSERT INTO billing_plans(id,name,type,description,is_active,is_featured,sort_order,features,feature_list,limits,prices,durations,gateways,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())",
                    (plan_id, body.name, body.type, body.description, body.is_active, body.is_featured, body.sort_order,
                     json.dumps(body.features), json.dumps(body.feature_list), json.dumps(body.limits), json.dumps(body.prices),
                     json.dumps(body.durations), json.dumps(body.gateways))
                )
        else:
            cur.execute(
                "INSERT INTO billing_plans(id,name,type,description,is_active,is_featured,sort_order,features,feature_list,limits,prices,durations,gateways,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (plan_id, body.name, body.type, body.description, 1 if body.is_active else 0,
                 1 if body.is_featured else 0, body.sort_order,
                 json.dumps(body.features), json.dumps(body.feature_list), json.dumps(body.limits),
                 json.dumps(body.prices), json.dumps(body.durations), json.dumps(body.gateways), now, now)
            )
    return {"id": plan_id, "message": "Plan created"}


@router.patch("/plans/{plan_id}")
async def update_plan(plan_id: str, body: PlanIn, current_user: dict = Depends(require_platform_admin)):
    _ensure_tables()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "UPDATE billing_plans SET name=%s,type=%s,description=%s,is_active=%s,is_featured=%s,sort_order=%s,features=%s,feature_list=%s,limits=%s,prices=%s,durations=%s,gateways=%s,updated_at=NOW() WHERE id=%s",
                (body.name, body.type, body.description, body.is_active, body.is_featured, body.sort_order,
                 json.dumps(body.features), json.dumps(body.feature_list), json.dumps(body.limits),
                 json.dumps(body.prices), json.dumps(body.durations), json.dumps(body.gateways), plan_id)
            )
        else:
            cur.execute(
                "UPDATE billing_plans SET name=?,type=?,description=?,is_active=?,is_featured=?,sort_order=?,features=?,feature_list=?,limits=?,prices=?,durations=?,gateways=?,updated_at=? WHERE id=?",
                (body.name, body.type, body.description, 1 if body.is_active else 0,
                 1 if body.is_featured else 0, body.sort_order,
                 json.dumps(body.features), json.dumps(body.feature_list), json.dumps(body.limits),
                 json.dumps(body.prices), json.dumps(body.durations), json.dumps(body.gateways), now, plan_id)
            )
    return {"message": "Plan updated"}


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: str, current_user: dict = Depends(require_platform_admin)):
    _ensure_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"DELETE FROM billing_plans WHERE id={ph}", (plan_id,))


# ── FX Rates ──────────────────────────────────────────────────────────────────

class FxRateIn(BaseModel):
    currency: str
    rate_to_usd: float


@router.get("/fx-rates")
async def list_fx_rates(current_user: dict = Depends(require_platform_admin)):
    rates = _get_rates()
    return [{"currency": k, "symbol": CURRENCY_SYMBOLS.get(k, k), "rate_to_usd": v}
            for k, v in sorted(rates.items())]


@router.patch("/fx-rates")
async def update_fx_rate(body: FxRateIn, current_user: dict = Depends(require_platform_admin)):
    """Manually override a single FX rate."""
    _ensure_tables()
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO fx_rates(currency,rate_to_usd,updated_at) VALUES(%s,%s,NOW()) ON CONFLICT(currency) DO UPDATE SET rate_to_usd=EXCLUDED.rate_to_usd,updated_at=NOW()",
                (body.currency.upper(), body.rate_to_usd)
            )
        else:
            cur.execute(
                "INSERT OR REPLACE INTO fx_rates(currency,rate_to_usd,updated_at) VALUES(?,?,?)",
                (body.currency.upper(), body.rate_to_usd, now)
            )
    return {"message": f"1 {body.currency} = {body.rate_to_usd} NGN"}


@router.post("/fx-rates/refresh")
async def refresh_fx_rates(current_user: dict = Depends(require_platform_admin)):
    """
    Auto-fetch latest FX rates from frankfurter.app (ECB rates, free, no API key).
    Falls back to exchangerate-api open endpoint.
    NGN is the base — we fetch NGN rate against all currencies.
    """
    import urllib.request as _req
    _ensure_tables()

    updated = {}
    errors = []

    # Strategy 1: frankfurter.app — fetch how many NGN per 1 of each currency
    # We query base=NGN to get NGN as base, then invert
    try:
        url = "https://api.frankfurter.app/latest?base=USD&symbols=NGN,GBP,EUR,KES,GHS,ZAR,UGX,TZS,CAD,AUD,INR,EGP,MAD"
        with _req.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        rates_usd = data.get("rates", {})
        ngn_per_usd = float(rates_usd.get("NGN", 1600))

        # Convert: 1 currency = X NGN
        currency_to_ngn = {"NGN": 1.0, "USD": ngn_per_usd}
        for curr, usd_rate in rates_usd.items():
            if curr == "NGN":
                continue
            # 1 USD = usd_rate of curr, 1 USD = ngn_per_usd NGN
            # so 1 curr = ngn_per_usd / usd_rate NGN
            currency_to_ngn[curr] = round(ngn_per_usd / float(usd_rate), 4)

        # Extra African currencies not on frankfurter — use rough estimates
        # These are stable enough; update monthly
        extras = {
            "RWF": round(ngn_per_usd / 1300, 4),   # ~1300 RWF per USD
            "UGX": round(ngn_per_usd / 3700, 4),   # ~3700 UGX per USD
            "TZS": round(ngn_per_usd / 2600, 4),   # ~2600 TZS per USD
            "MAD": round(ngn_per_usd / 10, 4),     # ~10 MAD per USD
        }
        currency_to_ngn.update({k: v for k, v in extras.items() if k not in currency_to_ngn})

        # Save to DB
        now = datetime.now(timezone.utc).isoformat()
        with get_conn() as conn:
            cur = conn.cursor()
            for curr, rate in currency_to_ngn.items():
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO fx_rates(currency,rate_to_usd,updated_at) VALUES(%s,%s,NOW()) ON CONFLICT(currency) DO UPDATE SET rate_to_usd=EXCLUDED.rate_to_usd,updated_at=NOW()",
                        (curr, rate)
                    )
                else:
                    cur.execute(
                        "INSERT OR REPLACE INTO fx_rates(currency,rate_to_usd,updated_at) VALUES(?,?,?)",
                        (curr, rate, now)
                    )
                updated[curr] = rate

        log.info(f"FX rates auto-refreshed: {len(updated)} currencies updated")
        return {
            "message": f"FX rates updated for {len(updated)} currencies",
            "source": "frankfurter.app (ECB)",
            "rates": updated,
            "updated_at": now,
        }

    except Exception as e:
        errors.append(f"frankfurter.app failed: {e}")
        log.warning(f"FX auto-refresh error: {e}")

    # Strategy 2: open.er-api.com (free, no key, 1500 req/month)
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        with _req.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        rates = data.get("rates", {})
        ngn_per_usd = float(rates.get("NGN", 1600))

        currency_to_ngn = {}
        for curr in ["NGN","USD","GBP","EUR","KES","GHS","ZAR","CAD","AUD","INR","EGP","MAD","UGX","TZS","RWF"]:
            r = float(rates.get(curr, 1))
            currency_to_ngn[curr] = round(ngn_per_usd / r, 4) if r else 1.0
        currency_to_ngn["NGN"] = 1.0

        now = datetime.now(timezone.utc).isoformat()
        with get_conn() as conn:
            cur = conn.cursor()
            for curr, rate in currency_to_ngn.items():
                if USE_POSTGRES:
                    cur.execute(
                        "INSERT INTO fx_rates(currency,rate_to_usd,updated_at) VALUES(%s,%s,NOW()) ON CONFLICT(currency) DO UPDATE SET rate_to_usd=EXCLUDED.rate_to_usd,updated_at=NOW()",
                        (curr, rate)
                    )
                else:
                    cur.execute(
                        "INSERT OR REPLACE INTO fx_rates(currency,rate_to_usd,updated_at) VALUES(?,?,?)",
                        (curr, rate, now)
                    )
                updated[curr] = rate

        return {
            "message": f"FX rates updated for {len(updated)} currencies",
            "source": "open.er-api.com",
            "rates": updated,
            "updated_at": now,
        }

    except Exception as e:
        errors.append(f"open.er-api.com failed: {e}")
        log.warning(f"FX fallback error: {e}")

    raise HTTPException(503, f"Could not fetch FX rates: {'; '.join(errors)}")


@router.get("/fx-rates/auto-refresh-status")
async def fx_refresh_status(current_user: dict = Depends(require_platform_admin)):
    """Check when FX rates were last updated."""
    _ensure_tables()
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT MIN(updated_at) as oldest, MAX(updated_at) as newest, COUNT(*) as count FROM fx_rates")
        row = dict(cur.fetchone())
    return {
        "currencies_stored": row.get("count", 0),
        "oldest_update": str(row.get("oldest", "")),
        "newest_update": str(row.get("newest", "")),
    }


# ── Orders ────────────────────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(
    status: str = Query(""), plan_id: str = Query(""),
    currency: str = Query(""), limit: int = Query(50), offset: int = Query(0),
    current_user: dict = Depends(require_platform_admin),
):
    _ensure_tables()
    conditions, params = [], []
    ph = "%s" if USE_POSTGRES else "?"
    if status: conditions.append(f"o.status={ph}"); params.append(status)
    if plan_id: conditions.append(f"o.plan_id={ph}"); params.append(plan_id)
    if currency: conditions.append(f"o.currency={ph}"); params.append(currency)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with get_conn() as conn:
        cur = conn.cursor()
        join = "LEFT JOIN users u ON u.id::text=o.user_id" if USE_POSTGRES else "LEFT JOIN users u ON u.id=o.user_id"
        cur.execute(f"SELECT o.*,u.email,u.full_name FROM billing_orders o {join} {where} ORDER BY o.created_at DESC LIMIT {ph} OFFSET {ph}", params + [limit, offset])
        orders = [dict(r) for r in cur.fetchall()]
        cur.execute(f"SELECT COUNT(*) FROM billing_orders o {where}", params)
        total = int(_first_val(cur.fetchone()))
    return {"orders": orders, "total": total}


@router.patch("/orders/{order_id}")
async def update_order(order_id: str, request: Request, current_user: dict = Depends(require_platform_admin)):
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("pending","paid","failed","refunded","cancelled"):
        raise HTTPException(400, "Invalid status")
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"UPDATE billing_orders SET status={ph} WHERE id={ph}", (new_status, order_id))
    return {"message": f"Order updated to {new_status}"}


# ── IP Currency Detection ─────────────────────────────────────────────────────

@router.get("/detect-currency")
async def detect_currency(request: Request):
    import urllib.request as _req
    ip = request.headers.get("X-Forwarded-For","").split(",")[0].strip() or request.client.host
    if ip in ("127.0.0.1","::1"):
        return {"currency":"NGN","symbol":"N","country":"NG","ip":ip}
    try:
        with _req.urlopen(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=3) as r:
            data = json.loads(r.read())
        country = data.get("countryCode","NG")
    except Exception:
        country = "NG"
    currency = COUNTRY_CURRENCY.get(country, "USD")
    rates = _get_rates()
    return {"currency":currency,"symbol":CURRENCY_SYMBOLS.get(currency,currency),"country":country,"ip":ip,"rate_to_usd":rates.get(currency,1.0)}


# ── Public plans with currency conversion ─────────────────────────────────────

@router.get("/public-plans")
async def public_plans(currency: str = "NGN", plan_type: str = ""):
    _ensure_tables()
    rates = _get_rates()
    with get_conn() as conn:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        active = "is_active=TRUE" if USE_POSTGRES else "is_active=1"
        if plan_type:
            cur.execute(f"SELECT * FROM billing_plans WHERE {active} AND type={ph} ORDER BY sort_order", (plan_type,))
        else:
            cur.execute(f"SELECT * FROM billing_plans WHERE {active} ORDER BY sort_order")
        plans = []
        for r in cur.fetchall():
            p = dict(r)
            for k in ["features","limits","prices","durations","gateways"]:
                p[k] = _j(p.get(k))
            usd_prices = p["prices"].get("USD", {})
            p["prices_converted"] = {
                dur_id: {
                    "amount": _convert(usd_prices.get(dur_id,0), currency, rates),
                    "currency": currency,
                    "symbol": CURRENCY_SYMBOLS.get(currency, currency),
                    "amount_usd": ngn_prices.get(dur_id, 0),
                }
                for dur_id in usd_prices
            }
            plans.append(p)
    return {"plans": plans, "currency": currency, "symbol": CURRENCY_SYMBOLS.get(currency, currency)}
