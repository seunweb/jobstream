# JobStream — Software Development Lifecycle (SDLC)
## Nigeria's Workforce Operating System

*Version 1.0 — July 2026*

---

## Overview

JobStream follows an **Agile iterative SDLC** adapted for a two-person team (founder + AI-assisted engineering). Sprints are 2-week cycles with continuous deployment to Railway via GitHub. The model prioritises shipping working software over exhaustive upfront planning while maintaining quality gates before each release.

```
Plan → Design → Build → Test → Deploy → Monitor → Review → Plan
  └─────────────────── 2-week sprint ──────────────────────────┘
```

---

## 1. Planning

### 1.1 Roadmap Governance
The product roadmap (13 phases) is the single source of truth for what gets built. Each sprint picks items from the current phase before moving to the next.

**Inputs to planning:**
- Roadmap phase priority
- User feedback / bug reports
- Security and compliance requirements
- Technical debt backlog
- Infrastructure needs

**Sprint Planning Artefacts:**
| Artefact | Description | Owner |
|---|---|---|
| Sprint Goal | 1-sentence statement of what this sprint achieves | Founder |
| Feature List | Specific features/fixes to be built | Both |
| Acceptance Criteria | Definition of "done" for each item | Founder |
| Risk Register | Known blockers and mitigations | Both |

### 1.2 Environment Strategy
```
Developer Machine (local)
    │  sqlite + uvicorn --reload
    │  npm run dev
    ↓
Staging (Railway — staging branch)
    │  PostgreSQL (staging DB)
    │  Auto-deploy on push to staging
    ↓
Production (Railway — main branch)
       PostgreSQL (production DB)
       Auto-deploy on push to main
       Cloudflare in front
```

**Branch strategy:**
```
main          ← production (protected, PR-only)
staging       ← staging environment (direct push ok)
feature/*     ← individual feature branches
fix/*         ← bug fix branches
```

---

## 2. Requirements

### 2.1 Types of Requirements

**Functional Requirements** — what the system does
- Captured as user stories: *"As a [candidate/employer/admin], I want to [action] so that [benefit]"*
- Example: *"As a candidate, I want to save jobs so that I can apply later"*

**Non-Functional Requirements** — how the system performs
| Requirement | Target | Current Status |
|---|---|---|
| API response time | < 500ms (p95) | Not measured |
| Uptime | 99.5% | Not monitored |
| Page load time | < 3s on 3G | Not measured |
| Concurrent users | 1,000 initial | Not stress tested |
| Data retention | 3 years | Not defined |

**Security Requirements**
- All passwords hashed with bcrypt
- JWT tokens expire in 24h (access) / 30 days (refresh)
- HTTPS only (enforced by Railway + Cloudflare)
- NDPR compliance for Nigerian user data
- No PII in logs

**Compliance Requirements**
- NDPR (Nigeria Data Protection Regulation)
- Privacy Policy and Terms of Service before public launch
- Cookie consent for tracking/analytics

### 2.2 Requirement Sign-off
Before a feature enters the build phase, the following must be defined:
- [ ] User story written
- [ ] Acceptance criteria defined
- [ ] API contract agreed (endpoint, request, response shape)
- [ ] UI mockup or wireframe (even rough)
- [ ] Database schema changes identified

---

## 3. Design

### 3.1 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Cloudflare (CDN + WAF)                │
└────────────────────────┬────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
┌────────▼────────┐           ┌──────────▼──────────┐
│  Frontend       │           │  Backend (FastAPI)   │
│  React 18/Vite  │◄──────────│  Python 3.10+        │
│  Railway static │  REST API │  Railway service     │
└─────────────────┘           └──────────┬───────────┘
                                         │
                         ┌───────────────┼───────────────┐
                         │               │               │
               ┌─────────▼──┐  ┌────────▼────┐  ┌──────▼────┐
               │ PostgreSQL  │  │ File Storage│  │ Email     │
               │ (Railway)   │  │ (R2/S3 TBD) │  │ (SMTP/    │
               └────────────┘  └─────────────┘  │  Resend)  │
                                                 └───────────┘
```

### 3.2 Data Architecture
- **Primary DB:** PostgreSQL (Railway managed)
- **Local dev:** SQLite (no Docker needed)
- **Schema migrations:** Manual `ALTER TABLE` functions run on startup (`_migrate_schema()`)
- **Multi-tenancy:** Row-level isolation via `tenant_id` on all employer-owned tables
- **Soft deletes:** `is_active` flag, no hard deletes in production

### 3.3 API Design Principles
- RESTful with resource-based URLs
- JSON request/response
- All authenticated routes require `Authorization: Bearer {token}` header
- Errors return `{"detail": "message"}` with appropriate HTTP status
- Pagination via `?limit=N&offset=N` or `?page=N`

### 3.4 Frontend Design Principles
- Single-page application (SPA) — all routing in `App.jsx`
- Dark / light mode via CSS variables
- Mobile-first responsive design
- No third-party UI component library (custom components)
- esbuild-safe JSX: no `return (` in map callbacks, no nested template literals

---

## 4. Build

### 4.1 Development Environment Setup

**Backend:**
```bash
cd scraper
python -m venv venv
venv/Scripts/activate          # Windows
pip install -r requirements.txt
set DATABASE_URL=              # empty = use SQLite
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
npm install
npm run dev                    # dev server on :5173
```

**Key environment variables:**
```
DATABASE_URL        Railway PostgreSQL connection string
SECRET_KEY          JWT signing secret (min 32 chars)
SMTP_HOST           smtp.gmail.com
SMTP_PORT           587
SMTP_USER           sender@email.com
SMTP_PASS           app-specific password
RESEND_API_KEY      (future) Resend.com API key
PAYSTACK_SECRET     Paystack secret key
PADDLE_API_KEY      (future)
CLOUDFLARE_TOKEN    (future)
APP_URL             Frontend public URL
```

### 4.2 Coding Standards

**Python (Backend):**
- PEP 8 style
- Type hints on all function signatures
- Parameterised SQL queries only — no f-strings in SQL
- `try/except` on all DB operations with meaningful error messages
- Logging via Python's `logging` module (not `print`)
- No secrets in code — environment variables only

**JavaScript/React (Frontend):**
- Functional components with hooks only
- esbuild-safe patterns (see list below)
- State co-located with the component that owns it
- API calls via the shared `api()` helper function
- No `console.log` in production code

**esbuild-Safe JSX Rules (critical for this project):**
```javascript
// ❌ BREAKS BUILD — return( on its own line in map
items.map(x => {
  return (        // ← standalone return( breaks esbuild
    <div>{x}</div>
  );
})

// ✅ CORRECT — implicit arrow return
items.map(x => (
  <div>{x}</div>
))

// ✅ OR — return on same line as JSX
items.map(x => { return <div>{x}</div>; })

// ❌ BREAKS BUILD — nested template literals
`${`inner ${val}`}`

// ✅ CORRECT — string concatenation
"outer " + "inner " + val

// ❌ BREAKS BUILD — $${} pattern
`$${price}`

// ✅ CORRECT
"$" + price
```

### 4.3 File Structure
```
jobstream/
├── src/
│   └── App.jsx                 ← entire frontend (single file SPA)
├── scraper/
│   ├── main.py                 ← FastAPI app, all routers registered
│   ├── requirements.txt
│   ├── railway.toml
│   ├── core/
│   │   ├── database.py         ← schema, migrations, DB helpers
│   │   ├── security.py         ← JWT, rate limiting, CORS
│   │   └── email.py            ← email sending
│   └── services/
│       ├── identity/           ← auth, billing, quotas, admin
│       │   ├── auth_router.py
│       │   ├── billing_router.py
│       │   ├── billing_admin_router.py
│       │   ├── quota_router.py
│       │   ├── admin_router.py
│       │   └── dependencies.py
│       └── recruitment/        ← scraper, jobs, companies
│           ├── scraper.py
│           ├── router.py
│           ├── tasks.py
│           └── seo_router.py
├── public/
│   ├── robots.txt              ← (TODO)
│   └── sitemap.xml             ← (TODO)
└── package.json
```

---

## 5. Testing

### 5.1 Testing Levels

**Level 1 — Developer Testing (current)**
- Manual testing locally before pushing
- `npm run build` must pass (zero esbuild errors)
- API endpoints tested via browser/curl

**Level 2 — Integration Testing (planned)**
```bash
# Backend
pytest scraper/tests/ -v

# Test categories
pytest -m "auth"        # auth endpoints
pytest -m "billing"     # billing and plans
pytest -m "scraper"     # scraper functions
pytest -m "jobs"        # job CRUD
```

**Level 3 — End-to-End Testing (planned)**
```bash
# Playwright E2E
npx playwright test

# Test flows
- Candidate registers → applies to job
- Employer posts job → manages applications
- Admin creates plan → assigns to tenant
- Payment flow (Paystack)
```

### 5.2 Test Checklist (Manual — Pre-release)

**Authentication:**
- [ ] Register new candidate account
- [ ] Register new employer account
- [ ] Login / logout
- [ ] Password reset (email arrives, link works)
- [ ] Token expiry and refresh

**Job Seeker:**
- [ ] Browse jobs (search, filter, paginate)
- [ ] View job detail page
- [ ] Apply to job (in-site application)
- [ ] Apply via external URL redirect
- [ ] Save / unsave a job
- [ ] View My Applications
- [ ] Set up job alert (email arrives)
- [ ] Cancel job alert

**Employer:**
- [ ] Create workspace / onboard
- [ ] Post a job (draft → publish)
- [ ] Set job deadline
- [ ] View applications for a job
- [ ] Update application status
- [ ] Invite team member
- [ ] View analytics

**Admin:**
- [ ] View platform dashboard (revenue, stats)
- [ ] Create / edit / duplicate billing plan
- [ ] Save plan as draft
- [ ] Filter plans by type
- [ ] View and manage tenants
- [ ] Edit tenant company profile
- [ ] Override tenant quotas
- [ ] Manage scraper companies
- [ ] Trigger manual scrape
- [ ] View FX rates / refresh

**Billing:**
- [ ] Candidate sees correct plan on billing page
- [ ] Plan features are enforced (e.g. free cannot access AI features)
- [ ] Upgrade button initiates Paystack flow
- [ ] Paystack webhook updates subscription (staging test)

**Scraper:**
- [ ] Add Greenhouse company (EU + US URL)
- [ ] Jobs scraped with title, location, description, salary
- [ ] Logo appears on job cards
- [ ] Duplicate jobs not created
- [ ] Force rescrape clears cache

### 5.3 Broken Link Audit
```bash
# Check all apply_url fields in the DB
SELECT company, title, apply_url 
FROM jobs 
WHERE is_active = 1 
  AND apply_url != '' 
ORDER BY scraped_at DESC 
LIMIT 100;

# Run link checker (planned)
npx broken-link-checker https://your-site.com --recursive
```

### 5.4 Performance / Stress Testing (planned)

**Tools:** k6 or Locust

**Test scenarios:**
```
Scenario 1 — Browse load
  100 concurrent users browsing jobs for 5 minutes
  Target: p95 < 500ms, 0 errors

Scenario 2 — Apply spike
  50 users simultaneously applying to the same job
  Target: all applications saved, no data loss

Scenario 3 — Scraper run
  Scraping 10 companies simultaneously
  Target: completes in < 5 minutes, no timeouts
```

---

## 6. Deployment

### 6.1 Deployment Pipeline
```
Developer pushes to GitHub
        │
        ├── push to feature/* or fix/*
        │       → no auto-deploy
        │       → create PR to staging
        │
        ├── merge to staging
        │       → Railway auto-deploys to staging
        │       → Manual QA on staging
        │       → Create PR to main
        │
        └── merge to main (after approval)
                → Railway auto-deploys to production
                → Cloudflare cache purge
                → Monitor for 30 minutes
```

### 6.2 Deployment Checklist
Before merging to main:
- [ ] `npm run build` passes locally
- [ ] All manual test checklist items passed on staging
- [ ] No new SQL f-strings introduced
- [ ] Environment variables documented if new ones added
- [ ] DB migration tested on staging first
- [ ] Railway staging deploy succeeded

### 6.3 Database Migrations
Migrations are run automatically on startup via `init_db()`. For new columns:

```python
# In database.py → _migrate_schema()
cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT ''")
```

For Railway (PostgreSQL) — also run manually if needed:
```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS logo_url TEXT DEFAULT '';
```

### 6.4 Rollback Procedure
```bash
# If production deploy breaks:

# Option 1 — Revert in Railway dashboard
# Railway → Deployments → Previous deploy → Redeploy

# Option 2 — Git revert
git revert HEAD
git push origin main

# Option 3 — Database rollback (if schema change broke things)
# Restore from backup (currently manual — pg_dump needed)
ALTER TABLE jobs DROP COLUMN IF EXISTS new_column;
```

---

## 7. Monitoring & Observability

### 7.1 Current Monitoring
| Tool | What | Status |
|---|---|---|
| Railway Logs | Backend stdout/stderr | ✅ Active |
| Railway Metrics | CPU, memory, requests | ✅ Active |
| Health endpoint | GET /health returns 200 | ✅ Active |

### 7.2 Planned Monitoring Stack
| Tool | What | Priority |
|---|---|---|
| Sentry (free) | Error tracking, stack traces | 🔴 High |
| UptimeRobot (free) | Ping every 5 min, alert on downtime | 🔴 High |
| Posthog / Plausible | Product analytics, user behaviour | 🟡 Medium |
| PG activity monitoring | Slow query detection | 🟡 Medium |
| Cloudflare Analytics | Traffic, bots, geographic data | 🟡 Medium |

### 7.3 Alerting
When operational:
- Downtime → Email + WhatsApp alert within 5 minutes
- Error rate > 5% → Sentry alert
- Scraper failure → Email notification
- Paystack webhook failure → Admin dashboard flag

### 7.4 Key Metrics to Track
**Technical:**
- API p95 response time
- Error rate (4xx, 5xx)
- Database connection pool usage
- Scraper success rate per company

**Business:**
- Daily active users (candidates + employers)
- Jobs posted per day
- Applications submitted per day
- Employer signup → first job posted (activation rate)
- Free → paid conversion rate
- Monthly Recurring Revenue (MRR)

---

## 8. Maintenance & Support

### 8.1 Routine Maintenance
| Task | Frequency | Owner |
|---|---|---|
| Review Railway logs for errors | Daily | Founder |
| Check scraper success rates | Daily | Founder |
| Verify email delivery | Weekly | Founder |
| Review billing/payment issues | Weekly | Founder |
| Apply security patches (pip/npm) | Monthly | Engineer |
| Database backup verification | Monthly | Engineer |
| Review and expire old jobs | Automated (TBD) | System |
| FX rate refresh | Automated (daily) | System |

### 8.2 Incident Response
```
Severity 1 (Site down)
  → Immediate investigation
  → Rollback if deploy-related
  → Post incident note

Severity 2 (Feature broken, data at risk)
  → Fix within 4 hours
  → Deploy hotfix to staging first

Severity 3 (Minor issue, workaround exists)
  → Fix in next sprint
  → Log in backlog
```

### 8.3 Technical Debt Register
| Item | Impact | Effort | Sprint |
|---|---|---|---|
| 19 SQL f-strings → parameterised | Security | Medium | Pre-launch |
| Playwright → Nixpacks Dockerfile | Reliability | Medium | Sprint 1 |
| App.jsx split into components | Maintainability | High | Sprint 3 |
| Automated test suite (Pytest) | Quality | High | Sprint 2 |
| Email → Resend transactional | Deliverability | Low | Sprint 1 |
| Job expiry cron | Data quality | Low | Pre-launch |

---

## 9. Documentation

### 9.1 Documentation Types
| Document | Location | Status |
|---|---|---|
| Product Roadmap | JobStream_Product_Roadmap.md | ✅ Current |
| SDLC (this document) | JobStream_SDLC.md | ✅ Current |
| API Reference | /docs (FastAPI auto) | 🟡 Exposed publicly |
| Environment Setup | README.md | 🔴 Missing |
| Database Schema | In database.py comments | 🟡 Partial |
| Deployment Guide | 🔴 Missing | |
| User Guide (employer) | 🔴 Missing | |
| Admin Manual | 🔴 Missing | |

### 9.2 README (Minimum required)
The project root `README.md` should contain:
- Project overview
- Local development setup (backend + frontend)
- Environment variables reference
- Deployment instructions
- Branch strategy
- How to run tests

---

## 10. Security Lifecycle

### 10.1 Security in Each Phase

| Phase | Security Activity |
|---|---|
| Plan | Identify data sensitivity, compliance requirements |
| Design | Threat modelling, auth/authorisation design |
| Build | Code review for injection, parameterised queries, input validation |
| Test | Security test cases, broken auth tests, rate limit tests |
| Deploy | Secrets in env vars only, HTTPS enforced, /docs restricted |
| Monitor | Audit logs, anomaly detection, failed login alerts |

### 10.2 OWASP Top 10 — Current Status
| Risk | Status | Mitigation |
|---|---|---|
| A01 Broken Access Control | 🟡 | RBAC exists, tenant isolation needs audit |
| A02 Cryptographic Failures | ✅ | bcrypt, JWT, HTTPS |
| A03 Injection | 🟡 | 19 f-strings in SQL need fixing |
| A04 Insecure Design | 🟡 | No employer verification |
| A05 Security Misconfiguration | 🔴 | /docs exposed, no Cloudflare WAF |
| A06 Vulnerable Components | 🟡 | No dependency scanning |
| A07 Auth Failures | ✅ | Rate limiting, JWT expiry |
| A08 Software Integrity | 🟡 | No SAST in CI pipeline |
| A09 Logging Failures | 🔴 | Audit log table missing |
| A10 SSRF | 🟡 | Scraper fetches external URLs |

---

## Sprint Template

### Sprint N — [Goal Statement]
**Dates:** DD MMM – DD MMM  
**Sprint Goal:** One sentence describing the sprint outcome

| # | Feature / Fix | Type | Status | Notes |
|---|---|---|---|---|
| 1 | | Feature/Fix/Infra | Todo/In Progress/Done | |

**Definition of Done:**
- Code pushed to staging branch
- Manual test checklist completed on staging
- No new build errors
- Merged to main and deployed

**Retrospective:**
- What went well:
- What to improve:
- Carry-over to next sprint:

---

*Document owner: Oluwaseun Adebayo*  
*Last updated: July 13, 2026*  
*Next review: Before each phase transition*
