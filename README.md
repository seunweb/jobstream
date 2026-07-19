# JobStream — Nigeria's Workforce Operating System

> The most complete job board and HR platform for the African market. Built for job seekers, employers, and recruiters — powered by intelligent job aggregation, billing, and workspace management.

[![Deploy Status](https://img.shields.io/badge/deploy-Railway-purple)](https://railway.app)
[![Stack](https://img.shields.io/badge/stack-React%20%2B%20FastAPI%20%2B%20PostgreSQL-blue)]()
[![License](https://img.shields.io/badge/license-Private-red)]()

---

## Live URLs

| Environment | Frontend | Backend |
|---|---|---|
| **Production** | https://practical-creativity-production-2972.up.railway.app | https://jobstream-production-088c.up.railway.app |
| **Staging** | _(not yet configured)_ | _(not yet configured)_ |

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Tech Stack](#tech-stack)
4. [Local Development Setup](#local-development-setup)
5. [Environment Variables](#environment-variables)
6. [Database](#database)
7. [API Reference](#api-reference)
8. [Frontend Structure](#frontend-structure)
9. [Scraper System](#scraper-system)
10. [Deployment](#deployment)
11. [Branch Strategy](#branch-strategy)
12. [Testing](#testing)
13. [Known Issues & Backlog](#known-issues--backlog)
14. [Roadmap](#roadmap)

---

## Project Overview

JobStream aggregates jobs from major Nigerian and African employers via ATS scrapers (Greenhouse, Oracle HCM, Workday, Lever) and enables employers to post jobs directly. The platform supports:

- **Job seekers** — browse, search, save, apply, track applications, set alerts
- **Employers** — post jobs, manage applications, team workspace, analytics
- **Platform admin** — manage tenants, billing plans, quotas, scraper companies
- **Multi-tenant** — each employer gets an isolated workspace

**Phase:** v1.0 pre-launch (core job board + employer dashboard)  
**GitHub:** `seunweb/jobstream`

---

## Architecture

```
Cloudflare (DDoS + WAF + SSL)  [planned]
         │
    ┌────┴────────────────────────┐
    │                             │
Frontend (Vite/React)     Backend (FastAPI)
Railway static            Railway service
    │                             │
    └──────── REST API ───────────┘
                                  │
                    ┌─────────────┼────────────┐
                    │             │            │
              PostgreSQL    File Storage    Email
              (Railway)     (R2 - planned) (SMTP/Resend)
```

**Key design decisions:**
- Single-page application — all React in one `src/App.jsx` file
- SQLite locally, PostgreSQL in production (same codebase, auto-detected)
- Multi-tenant via `tenant_id` row-level isolation
- Soft deletes only (`is_active` flag) — no hard deletes in production
- Schema migrations run automatically on startup

---

## Tech Stack

### Frontend
| Package | Version | Purpose |
|---|---|---|
| React | 18 | UI framework |
| Vite | 5 | Build tool |
| esbuild | (via Vite) | JSX compiler |

> ⚠️ **No UI component library** — all components are custom. See [esbuild JSX Rules](#esbuild-jsx-rules) for critical constraints.

### Backend
| Package | Version | Purpose |
|---|---|---|
| FastAPI | 0.111.0 | API framework |
| Uvicorn | 0.30.1 | ASGI server |
| psycopg2-binary | 2.9.9 | PostgreSQL driver |
| python-jose | 3.3.0 | JWT tokens |
| passlib / bcrypt | 1.7.4 / 4.0.1 | Password hashing |
| httpx | 0.27.0 | Async HTTP (scraper) |
| beautifulsoup4 | 4.12.3 | HTML parsing (scraper fallback) |
| playwright | 1.44.0 | Browser automation (optional) |
| apscheduler | 3.10.4 | Cron jobs (alerts, scraper) |
| slowapi | 0.1.9 | Rate limiting |
| resend | ≥2.0.0 | Transactional email |
| pyotp | 2.9.0 | 2FA (future) |

---

## Local Development Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- Git

### 1. Clone the repository

```bash
git clone https://github.com/seunweb/jobstream.git
cd jobstream
```

### 2. Backend setup

```bash
cd scraper

# Create and activate virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Optional: install Playwright browsers (needed for Workday/Lever scraping)
playwright install chromium
```

Create a local `.env` file in the `scraper/` directory:

```env
# Leave DATABASE_URL empty to use SQLite locally
DATABASE_URL=

SECRET_KEY=your-local-dev-secret-key-min-32-chars
APP_URL=http://localhost:5173

# Email (optional for local dev)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@email.com
SMTP_PASS=your-app-password

# Payments (use test keys locally)
PAYSTACK_SECRET=sk_test_xxxxx
```

Start the backend:

```bash
# From scraper/ directory
uvicorn main:app --reload --port 8000
```

Backend runs at: http://localhost:8000  
API docs: http://localhost:8000/docs  
Health check: http://localhost:8000/health

### 3. Frontend setup

```bash
# From project root
npm install
npm run dev
```

Frontend runs at: http://localhost:5173

> The frontend proxies API calls to `http://localhost:8000` in development.

### 4. Create an admin account

After starting the backend for the first time, the SQLite database is created automatically. Register a user via the UI, then promote them to platform admin via the database:

```sql
-- SQLite (local)
UPDATE users SET role = 'platform_admin' WHERE email = 'your@email.com';

-- PostgreSQL (Railway)
UPDATE users SET role = 'platform_admin' WHERE email = 'your@email.com';
```

---

## Environment Variables

### Backend (Railway API service)

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string from Railway. Empty = SQLite |
| `SECRET_KEY` | Yes | JWT signing secret. Min 32 characters. Never commit this. |
| `APP_URL` | Yes | Frontend public URL (e.g. `https://your-site.up.railway.app`) |
| `SMTP_HOST` | Optional | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | Optional | SMTP port (587 for TLS) |
| `SMTP_USER` | Optional | SMTP sender email address |
| `SMTP_PASS` | Optional | SMTP app password (Gmail: 16-char app password) |
| `RESEND_API_KEY` | Optional | Resend.com API key for transactional email |
| `PAYSTACK_SECRET` | Optional | Paystack secret key (`sk_live_xxx` or `sk_test_xxx`) |
| `PAYSTACK_WEBHOOK_SECRET` | Optional | Paystack webhook signing secret |
| `PADDLE_API_KEY` | Optional | Paddle.com API key (future) |
| `CLOUDFLARE_TOKEN` | Optional | Cloudflare API token (future) |

> Set all variables in Railway → Service → Variables. Never put them in code.

### Frontend (Railway frontend service)

The frontend is a static build — it has no server-side environment variables. The backend URL is hardcoded in `src/App.jsx` as the `api()` helper base URL.

---

## Database

### Engine
- **Local development:** SQLite (auto-created at `scraper/jobstream.db`)
- **Production:** PostgreSQL via Railway managed database

The codebase detects which to use automatically:
```python
USE_POSTGRES = bool(os.getenv("DATABASE_URL"))
```

### Schema Management
There is no migration framework (no Alembic). Migrations are plain SQL functions in `scraper/core/database.py`:

```python
def init_db():
    # 1. Create tables (idempotent CREATE TABLE IF NOT EXISTS)
    # 2. Run all _migrate_* functions (add columns to existing tables)
    # 3. Seed initial data
```

**To add a new column:**
```python
# In _migrate_schema() in database.py:
cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS my_column TEXT DEFAULT ''")
```

Then also run manually on Railway PostgreSQL:
```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS my_column TEXT DEFAULT '';
```

### Key Tables

| Table | Description |
|---|---|
| `users` | All users (candidates, employers, admins) |
| `tenants` | Employer workspaces |
| `tenant_members` | User ↔ tenant membership |
| `jobs` | All job listings (scraped + posted) |
| `applications` | Job applications |
| `companies` | Scraper source companies |
| `billing_plans` | Admin-managed subscription plans |
| `billing_orders` | Payment records |
| `subscriptions` | Active user subscriptions |
| `tenant_quotas` | Per-tenant limit overrides |
| `job_alerts` | User alert subscriptions |
| `fx_rates` | Currency rates (USD base) |
| `admin_settings` | Platform-wide key/value config |
| `audit_logs` | _(planned — table not yet created)_ |

### Useful Queries

```sql
-- Check all active employers
SELECT t.name, t.slug, t.plan_id, t.status, COUNT(j.id) as jobs
FROM tenants t
LEFT JOIN jobs j ON j.tenant_id = t.id::text AND j.source = 'manual'
GROUP BY t.id ORDER BY t.created_at DESC;

-- Check recent applications
SELECT a.created_at, u.email, j.title, j.company, a.status
FROM applications a
JOIN users u ON u.id = a.user_id
JOIN jobs j ON j.id = a.job_id
ORDER BY a.created_at DESC LIMIT 20;

-- Check active billing plans
SELECT id, name, type, is_active, is_featured FROM billing_plans ORDER BY sort_order;

-- Promote user to platform admin
UPDATE users SET role = 'platform_admin' WHERE email = 'admin@example.com';
```

---

## API Reference

Full interactive docs available at `/docs` (FastAPI auto-generated).

> ⚠️ The `/docs` endpoint is currently public. Restrict it before production launch.

### Authentication
All protected endpoints require:
```
Authorization: Bearer {access_token}
```

Tokens obtained from `POST /auth/login`.

### Core Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Health check |
| POST | `/auth/register` | None | Register new user |
| POST | `/auth/login` | None | Login, returns JWT |
| POST | `/auth/refresh` | None | Refresh access token |
| POST | `/auth/logout` | User | Logout, revoke token |
| POST | `/auth/forgot-password` | None | Send reset email |
| POST | `/auth/reset-password` | None | Reset with token |
| GET | `/jobs` | None | List jobs (paginated) |
| GET | `/jobs/{id}` | None | Job detail |
| POST | `/jobs` | Employer | Create job |
| PATCH | `/jobs/{id}` | Employer | Update job |
| DELETE | `/jobs/{id}` | Employer | Delete job |
| GET | `/billing/plans` | None | List active plans |
| GET | `/billing/my-subscription` | User | Current user plan |
| POST | `/billing/initiate` | User | Start Paystack payment |
| POST | `/billing/webhook` | None | Paystack webhook |
| GET | `/admin/billing/plans` | Admin | All plans |
| POST | `/admin/billing/plans` | Admin | Create plan |
| PATCH | `/admin/billing/plans/{id}` | Admin | Update plan |
| DELETE | `/admin/billing/plans/{id}` | Admin | Delete plan |
| GET | `/admin/tenants` | Admin | List all workspaces |
| PATCH | `/admin/tenants/{id}/profile` | Admin | Update company profile |
| GET | `/quota/admin/tenants` | Admin | Tenant quota overview |
| PATCH | `/quota/admin/tenants/{id}` | Admin | Override tenant quota |
| GET | `/companies` | None | Scraper companies |
| POST | `/companies` | Admin | Add scraper company |
| DELETE | `/companies/{id}` | Admin | Remove company |

---

## Frontend Structure

The entire frontend is a single React file: **`src/App.jsx`** (~6,600 lines).

### Page Components (functions in App.jsx)

| Component | Route | Role |
|---|---|---|
| `JobsPage` | Default / `?page=jobs` | Candidate job board |
| `JobDetailPage` | `?jobid=xxx` | Individual job |
| `CompanyProfilePage` | `?company=xxx` | Company page |
| `MyApplicationsPage` | `?page=myapps` | Candidate applications |
| `SavedJobsPage` | `?page=saved` | Bookmarked jobs |
| `BillingPage` | `?page=billing` | Candidate/employer billing |
| `PricingPage` | `?page=pricing` | Public pricing page |
| `EmployerPage` | `?page=employer` | Employer dashboard |
| `AnalyticsPage` | `?page=analytics` | Employer analytics |
| `AIPage` | `?page=ai` | AI tools |
| `AdminDashboardPage` | `?page=admin` | Platform admin |
| `ScraperPage` | `?page=scraper` | Scraper management |

### Shared Utilities

```javascript
api(path, options)     // Authenticated fetch wrapper
toast(message)         // Toast notification
isDark                 // Dark mode boolean (from context)
user                   // Current user object
```

### ⚠️ esbuild JSX Rules

These patterns **break the Vite build** and must never be used:

```javascript
// ❌ return( on its own line inside .map() block body
items.map(item => {
  const x = item.id;
  return (          // ← BREAKS BUILD
    <div>{x}</div>
  );
})

// ✅ Correct
items.map(item => {
  const x = item.id;
  return <div>{x}</div>;
})

// ❌ Nested template literals
`outer ${`inner ${val}`}`

// ✅ Correct
"outer " + "inner " + val

// ❌ $${} pattern (dollar before template expression)
`Price: $${amount}`

// ✅ Correct
"Price: $" + amount

// ❌ Arrow function returning object literal
const fn = (t) => ({key: t.value})

// ✅ Correct
function fn(t) { return {key: t.value}; }
```

---

## Scraper System

### How It Works

1. Admin adds a company URL in **Admin → Scraper**
2. Scheduler runs every N hours (configurable)
3. ATS type is auto-detected from the URL
4. Appropriate scraper strategy is used
5. New jobs are inserted; existing jobs have `scraped_at` updated

### Supported ATS

| ATS | Strategy | Status |
|---|---|---|
| **Greenhouse** (US + EU) | HTTP API (Remix loader + boards-api) | ✅ |
| **Oracle HCM** | Direct API | ✅ |
| **Workday** | Playwright (browser) | 🟡 Playwright required |
| **Lever** | Playwright (browser) | 🟡 Playwright required |
| **Odoo** | Playwright (browser) | 🟡 Playwright required |
| **Generic HTML** | Playwright (browser) | 🟡 Playwright required |

### Greenhouse URL Formats

Both US and EU regional boards are supported:
```
https://job-boards.greenhouse.io/{company_token}
https://job-boards.eu.greenhouse.io/{company_token}
https://boards.greenhouse.io/{company_token}
```

### Adding a Company

In Admin → Scraper → Add Company:
- **Name:** Company display name
- **URL:** The ATS career page URL
- **Industry:** Sector (for job classification)
- **Logo URL:** Direct image URL (optional)

### Playwright Dependency

Playwright is **optional**. Greenhouse and Oracle HCM work without it. If Playwright is not installed, browser-dependent scrapers log a warning and skip gracefully.

To install (required for Workday/Lever/generic sites):
```bash
playwright install chromium --with-deps
```

---

## Deployment

### Infrastructure
- **Hosting:** Railway (both frontend and backend)
- **Database:** Railway managed PostgreSQL
- **CDN / Security:** Cloudflare _(planned)_
- **Email:** SMTP via Gmail / Resend _(transition planned)_
- **File storage:** _(planned — Cloudflare R2)_

### Deploy to Production

Deployment is automatic on push to `main`:

```bash
git add -A
git commit -m "Description of changes"
git push origin main
# Railway auto-deploys within ~2 minutes
```

### Manual Deploy Steps

1. Run `npm run build` locally — must pass with zero errors
2. Push to `staging` branch first
3. Test on staging environment
4. Create PR from `staging` → `main`
5. Merge after testing passes
6. Monitor Railway logs for 10 minutes after deploy

### Database Migrations on Railway

After adding new columns, run the SQL manually in Railway's PostgreSQL console:

```sql
-- Example: adding a new column
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS my_field TEXT DEFAULT '';
```

Or connect via psql:
```bash
psql $DATABASE_URL
```

### Railway Environment Setup

Each Railway service needs these variables set under **Variables**:

**Backend service:**
- All variables from the [Environment Variables](#environment-variables) section above

**Frontend service:**
- No variables needed (static build)

---

## Branch Strategy

```
main          Production branch — protected
              Auto-deploys to production on push
              Only merge via PR from staging

staging       Staging branch
              Auto-deploys to staging Railway service
              Direct push allowed for quick fixes

feature/*     Feature development
              e.g. feature/greenhouse-eu-support
              PR into staging when ready

fix/*         Bug fixes
              e.g. fix/billing-500-error
              PR into staging (or main for hotfixes)
```

### Commit Message Convention

```
feat: add Greenhouse EU region support
fix: billing plan save 500 error (missing feature_list param)
chore: update requirements.txt
docs: update README with scraper setup
refactor: extract plan modal to reduce App.jsx complexity
security: fix SQL injection in jobs filter
```

---

## Testing

### Build Test (required before every push)

```bash
npm run build
```
Must complete with **zero errors**. Common failure: esbuild JSX parse errors (see [esbuild JSX Rules](#esbuild-jsx-rules)).

### Manual Test Checklist

Before merging to main, verify:

**Core flows:**
- [ ] Register as candidate → browse jobs → apply
- [ ] Register as employer → post job → see application
- [ ] Login as admin → view dashboard → manage plans
- [ ] Password reset email arrives and works

**Billing:**
- [ ] Billing page shows DB plans (not hardcoded)
- [ ] Plan modal: create, edit, duplicate, draft, search, filter
- [ ] Save plan updates local state immediately (no slow reload)

**Scraper:**
- [ ] Add Greenhouse company → trigger scrape → jobs appear
- [ ] Jobs have descriptions and salary where available
- [ ] No duplicate jobs created on re-scrape

### Automated Tests

_(Planned — not yet implemented)_

```bash
# Backend unit + integration tests
cd scraper
pytest tests/ -v

# E2E tests
npx playwright test
```

---

## Known Issues & Backlog

### Active Issues

| Issue | Severity | Area |
|---|---|---|
| Playwright not installed on Railway | High | Scraper |
| Moniepoint 403 (Cloudflare bot protection) | High | Scraper |
| Audit logs table not created | Medium | Compliance |
| 19 SQL f-strings (injection risk) | Medium | Security |
| Job listings never auto-expire | Medium | Data quality |
| Plain SMTP → emails land in spam | Medium | Email |
| API /docs exposed publicly | Low | Security |
| No automated DB backups | Low | Infrastructure |
| sitemap.xml not deployed | Low | SEO |
| robots.txt missing | Low | SEO |

### Pre-Launch TODO

```bash
# Critical
1. Set up staging environment on Railway
2. Put Cloudflare in front of production
3. Fix 19 SQL f-strings → parameterised queries
4. Create audit_logs table in DB
5. Add Privacy Policy + Terms of Service pages
6. Add robots.txt and sitemap.xml
7. Add job expiry cron job
8. Restrict /docs in production

# Important
9. Set up employer verification/approval flow
10. Mobile responsive audit
11. Switch to Resend for transactional email
12. End-to-end Paystack live key test
13. Set up Sentry error monitoring
14. Set up UptimeRobot uptime monitoring
```

---

## Roadmap

See [**JobStream_Product_Roadmap.md**](./JobStream_Product_Roadmap.md) for the full 13-phase roadmap with completion status.

**Current phase:** Pre-launch v1.0  
**Next milestone:** Staging environment + Cloudflare + Security audit

---

## Project Structure

```
jobstream/
├── src/
│   └── App.jsx                       # Entire frontend (~6,600 lines)
├── public/
│   ├── robots.txt                    # (TODO)
│   └── sitemap.xml                   # (TODO)
├── scraper/
│   ├── main.py                       # FastAPI app entry point
│   ├── requirements.txt              # Python dependencies
│   ├── railway.toml                  # Railway deployment config
│   ├── core/
│   │   ├── database.py               # Schema, migrations, DB helpers
│   │   ├── security.py               # JWT, rate limiting, CORS
│   │   └── email.py                  # Email sending (SMTP + Resend)
│   └── services/
│       ├── identity/
│       │   ├── auth_router.py        # Register, login, password reset
│       │   ├── admin_router.py       # Platform admin endpoints
│       │   ├── billing_router.py     # Plans, subscriptions, Paystack
│       │   ├── billing_admin_router.py # Admin plan management
│       │   ├── quota_router.py       # Tenant quota management
│       │   └── dependencies.py       # Auth dependencies, role guards
│       └── recruitment/
│           ├── scraper.py            # All ATS scrapers (Greenhouse, Oracle, etc.)
│           ├── router.py             # Jobs, companies, applications API
│           ├── tasks.py              # Scraper task runner
│           └── seo_router.py         # Sitemap, SEO endpoints
├── package.json                      # Frontend dependencies
├── vite.config.js                    # Vite build config
├── README.md                         # This file
├── JobStream_Product_Roadmap.md      # 13-phase product roadmap
└── JobStream_SDLC.md                 # Software development lifecycle
```

---

## Contributing

This is currently a private project. If you have access:

1. Never push directly to `main`
2. Always run `npm run build` before pushing
3. Test on staging before production
4. Document new environment variables here when added
5. Update the roadmap status when features are completed

---

## Support & Contact

- **Project owner:** Oluwaseun Adebayo
- **GitHub:** seunweb/jobstream
- **Platform:** Universe Careers

---

*Last updated: July 13, 2026*
