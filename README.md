# JobStream — Nigeria's Workforce Operating System

A full-stack recruitment and HR platform built for the African market.  
Powered by FastAPI, PostgreSQL, React and Claude AI.

---

## Live Demo
- **Frontend:** https://your-frontend.up.railway.app
- **API Docs:** https://your-api.up.railway.app/docs
- **Health:** https://your-api.up.railway.app/health

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, CSS-in-JS |
| Backend | Python 3.12, FastAPI |
| Database | PostgreSQL (Railway) |
| Auth | JWT (access + refresh tokens) |
| Email | Resend API |
| Payments | Paystack |
| AI | Anthropic Claude |
| Scraping | Playwright |
| Hosting | Railway |

---

## Architecture

```
jobstream/
├── src/
│   └── App.jsx                    # React SPA (all frontend)
└── scraper/
    ├── main.py                    # FastAPI app entry point
    ├── core/
    │   ├── database.py            # PostgreSQL + SQLite connection
    │   ├── security.py            # Rate limiting, lockout, headers
    │   ├── audit.py               # Audit logging
    │   ├── tenant.py              # Multi-tenancy
    │   ├── rbac.py                # Roles & permissions
    │   ├── events.py              # Domain event bus
    │   └── mfa.py                 # TOTP / 2FA
    └── services/
        ├── identity/              # Auth, users, roles, admin, billing, AI, analytics
        ├── organization/          # Companies, departments, locations
        ├── recruitment/           # Jobs, applications, scraper, Oracle HCM, SEO
        └── people/                # Unified persons layer
```

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.12
- Node.js 18+
- Git

### 1. Clone the repo
```bash
git clone https://github.com/seunweb/jobstream
cd jobstream
```

### 2. Backend setup
```bash
cd scraper
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Create environment file
```bash
cp .env.example .env
```
Edit `.env` with your values (see Environment Variables below).

### 4. Start backend
```bash
uvicorn main:app --reload --port 8000
```

### 5. Frontend setup
```bash
cd ..
npm install
```

### 6. Start frontend
```powershell
# Windows PowerShell
$env:VITE_API_URL="http://localhost:8000"
npx vite build
npx serve dist -l 3000 --single
```

Open http://localhost:3000

---

## Environment Variables

Create `scraper/.env` with these values:

```env
# Database
DATABASE_URL=postgresql://user:pass@host:port/dbname
DB_PATH=./jobstream.db        # SQLite fallback for local dev

# Security
SECRET_KEY=your-32-char-secret-key-here

# Email (Resend)
RESEND_API_KEY=re_xxxxxxxxxxxxxxxx
FROM_EMAIL=onboarding@resend.dev
APP_URL=http://localhost:3000

# Payments (Paystack)
PAYSTACK_SECRET_KEY=sk_live_xxxxxxxxxxxxxxxx
PAYSTACK_PUBLIC_KEY=pk_live_xxxxxxxxxxxxxxxx

# AI (Anthropic)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxx

# CORS (production)
ALLOWED_ORIGINS=https://your-frontend.up.railway.app
```

---

## Deployment (Railway)

### Backend service
1. Create a new Railway project
2. Connect your GitHub repo
3. Set root directory to `scraper/`
4. Add all environment variables in Railway → Variables tab
5. Railway auto-deploys on every `git push`

### Frontend service
1. Add another service in the same Railway project
2. Set root directory to `/` (project root)
3. Build command: `npx vite build`
4. Start command: `npx serve dist -l $PORT --single`
5. Add: `VITE_API_URL=https://your-api.up.railway.app`

### Paystack webhook
In Paystack Dashboard → Settings → Webhooks, add:
```
https://your-api.up.railway.app/billing/webhook
```

---

## API Documentation

Interactive API docs available at `/docs` (Swagger UI) and `/redoc`.

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | /auth/register | Register new user |
| POST | /auth/login | Login |
| GET | /jobs | List all jobs |
| POST | /jobs/{id}/apply | Apply for a job |
| GET | /organizations | List companies |
| POST | /tenants/onboard | Create employer workspace |
| POST | /billing/initiate | Start Paystack payment |
| POST | /billing/webhook | Paystack webhook |
| POST | /ai/cv/optimise | AI CV review |
| POST | /ai/application/write | AI cover letter |
| GET | /analytics/candidate/overview | Candidate stats |
| GET | /sitemap.xml | SEO sitemap |

Full API reference: https://your-api.up.railway.app/docs

---

## Features by Phase

| Phase | Features |
|-------|---------|
| 1 | Job board, scraping, auth, password reset |
| 2 | Candidate profiles, applications, saved jobs, job sharing |
| 3 | Company pages, employer dashboard, manual job posting |
| 4 | Rate limiting, account lockout, MFA, security headers |
| 5 | Audit logging — every action recorded |
| 6 | Multi-tenancy — isolated employer workspaces |
| 7 | RBAC — 14 roles, 45+ permissions |
| 8 | Admin dashboard, workspace dashboard, kanban pipeline |
| 9 | SEO slug URLs, sitemap, JSON-LD, job alerts |
| 10 | Claude AI — CV review, job match, cover letters, interview prep |
| 11 | Paystack billing — candidate and employer plans |
| 12 | Analytics — platform, employer, candidate dashboards + CSV exports |

---

## Supported ATS Scrapers

| ATS | Method |
|-----|--------|
| Greenhouse | Playwright |
| Lever | Playwright |
| Workday | Playwright |
| Oracle HCM | REST API |
| Odoo | Playwright |
| Custom career pages | Playwright |

---

## Roles & Permissions

### Platform roles
- `super_admin` — full access
- `platform_admin` — manage tenants, users, content
- `support_agent` — view-only

### Organisation roles
- `org_owner` — full workspace access
- `hr_admin` — all HR functions
- `recruiter` — manage recruitment pipeline
- `hiring_manager` — review candidates
- `interviewer` — submit feedback

### Candidate roles
- `candidate` — apply, save jobs, profile
- `premium_candidate` — + all AI features

---

## Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit: `git commit -m "Add my feature"`
4. Push: `git push origin feature/my-feature`
5. Open a Pull Request

---

## Licence

MIT Licence — see LICENSE file.

---

## Support

- Email: support@jobstream.ng
- Docs: https://docs.jobstream.ng
- GitHub Issues: https://github.com/seunweb/jobstream/issues
