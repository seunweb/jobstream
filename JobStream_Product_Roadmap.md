# JobStream — Nigeria's Workforce Operating System
## Full Product Roadmap (Updated July 2026)

**Vision:** Africa's most complete workforce intelligence platform — from job discovery to full HR operations.  
**Current Stage:** Pre-launch v1.0 (core job board + employer dashboard)  
**Stack:** React 18 (Vite) + FastAPI (Python) + PostgreSQL (Railway)  
**Live URLs:**  
- Frontend: https://practical-creativity-production-2972.up.railway.app  
- Backend: https://jobstream-production-088c.up.railway.app  

---

## Phase Status Legend
- ✅ **Complete** — Built and deployed
- 🟡 **Partial** — Built but needs fixes or polish
- 🔴 **Pending** — Planned, not yet built
- 🚧 **In Progress** — Currently being worked on

---

## Phase 1 — Foundation & Stability ✅
*Goal: Solid base before adding features*

| Feature | Status | Notes |
|---|---|---|
| PostgreSQL on Railway | ✅ | SQLite for local dev, PG in production |
| JWT authentication | ✅ | Access + refresh tokens |
| Password hashing (bcrypt) | ✅ | |
| Role-based access control | ✅ | candidate / employer / admin / platform_admin |
| Email (SMTP / Resend) | ✅ | Password reset, notifications |
| Scraper (Greenhouse, Oracle HCM, Workday, Lever) | 🟡 | Greenhouse EU working, Playwright unreliable locally |
| Scrape logs per company | ✅ | |
| Duplicate detection (fingerprint) | ✅ | MD5(title+company+source_url) |
| Health endpoint | ✅ | GET /health |
| Environment-based config | ✅ | DATABASE_URL, SECRET_KEY, SMTP_* |
| Railway deployment (CI/CD via GitHub) | ✅ | Auto-deploy on push to main |

---

## Phase 2 — Job Seeker Experience ✅
*Goal: Make the platform useful for candidates*

| Feature | Status | Notes |
|---|---|---|
| Job listing with search & filters | ✅ | Title, location, industry, type, department |
| Job detail page (SEO URLs) | ✅ | /jobs/{slug}-{id} |
| Save jobs / bookmarks | ✅ | |
| Apply to jobs (in-site + external) | ✅ | Apply mode: insite / external / email |
| Application status tracker | ✅ | Submitted → Reviewed → Shortlisted → Offered |
| My Applications page | ✅ | |
| Email job alerts | ✅ | Keyword + location + industry filters |
| Candidate profile | ✅ | Bio, skills, experience, CV upload |
| Social sharing (WhatsApp, LinkedIn, X, Telegram) | ✅ | |
| Dark / light mode | ✅ | |

---

## Phase 3 — Employer Dashboard ✅
*Goal: Enable companies to post and manage jobs directly*

| Feature | Status | Notes |
|---|---|---|
| Employer workspace (multi-tenant) | ✅ | Each company = isolated tenant |
| Job posting (draft / publish / deadline) | ✅ | |
| Application management | ✅ | View, filter, update status |
| Team invitations | ✅ | Invite colleagues to workspace |
| Company profile page | ✅ | Public-facing company page |
| Employer analytics | ✅ | Views, applies, conversion per job |
| Applications export | 🔴 | CSV export planned |
| Bulk job actions | 🟡 | Admin has it, employer dashboard partial |

---

## Phase 4 — Monetisation & Billing ✅
*Goal: Revenue infrastructure*

| Feature | Status | Notes |
|---|---|---|
| Billing plans (Admin-managed) | ✅ | Create/edit/duplicate/draft plans in admin |
| Candidate plans | ✅ | Free + Premium, feature-flag controlled |
| Employer plans | ✅ | Free / Starter / Growth / Enterprise |
| Plan feature flags | ✅ | Per-flag access control (post_jobs, ai_screening, etc.) |
| Plan limits | ✅ | active_jobs, team_seats, featured_slots |
| Paystack integration | 🟡 | Webhook built, needs live key testing |
| Flutterwave integration | 🔴 | Planned for non-NGN markets |
| Paddle integration | 🔴 | Planned for global/USD billing |
| FX rates (admin-managed) | ✅ | USD base, convert to NGN/GBP/etc. |
| Billing history | ✅ | Orders visible in admin |
| Invoice generation | 🔴 | PDF invoices not yet built |
| Free trial logic | 🔴 | Not yet implemented |

---

## Phase 5 — Admin & Platform Management ✅
*Goal: Full control for platform operators*

| Feature | Status | Notes |
|---|---|---|
| Platform admin dashboard | ✅ | Revenue, plans, orders, FX, quotas |
| Tenant management | ✅ | View, suspend, activate workspaces |
| Company profile editing (admin) | ✅ | Logo, about, website, industry, HQ, contact |
| Quota overrides per tenant | ✅ | Override any tenant's plan limits/features |
| User management | ✅ | List, role-assign, create users |
| Job management | ✅ | Search, filter, edit, bulk actions |
| Scraper management | ✅ | Add/remove companies, trigger scrapes |
| Alert management | ✅ | View, cancel user alerts |
| FX rate management | ✅ | Admin-editable, auto-refresh |
| Audit logs | 🟡 | Route exists, table missing in DB |
| Email template editor | 🟡 | UI built, backend partial |
| Nav settings per role | ✅ | Admin-configurable navigation |
| Admin settings (JSON) | ✅ | Key-value store for platform config |

---

## Phase 6 — AI Features 🟡
*Goal: Intelligent matching and productivity tools*

| Feature | Status | Notes |
|---|---|---|
| AI CV Optimiser | 🟡 | UI built, needs AI endpoint wiring |
| AI Job Match Scoring | 🟡 | Scoring logic partial |
| AI Cover Letter Writer | 🟡 | UI built |
| AI Interview Preparation | 🟡 | UI built |
| AI Screening (employer) | 🔴 | Auto-score incoming applications |
| Job description generator | 🔴 | Help employers write JDs |
| Salary insights | 🔴 | Market rate predictions |

---

## Phase 7 — Analytics & Reporting 🟡
*Goal: Data-driven decisions for employers and platform*

| Feature | Status | Notes |
|---|---|---|
| Platform revenue dashboard | ✅ | MRR, total revenue, plan breakdown |
| Employer analytics (per job) | ✅ | Views, applies, conversion |
| Candidate analytics | 🔴 | Profile views, application success rate |
| Scraper performance reports | 🟡 | Basic logs, no dashboard view |
| Export reports (CSV/PDF) | 🔴 | Not yet built |
| Cohort analysis | 🔴 | Future |

---

## Phase 8 — Workspace & Team Tools 🟡
*Goal: Full team collaboration for employers*

| Feature | Status | Notes |
|---|---|---|
| Team seats & invitations | ✅ | |
| Role permissions within workspace | 🟡 | Admin vs member, needs granular perms |
| Applicant pipeline (Kanban) | 🔴 | Drag-and-drop pipeline view |
| Notes on applicants | 🔴 | Internal team notes |
| Interview scheduling | 🔴 | Calendar integration |
| Offer letter generation | 🔴 | |
| Bulk email to applicants | 🔴 | |

---

## Phase 9 — SEO & Growth ✅
*Goal: Organic traffic from Google*

| Feature | Status | Notes |
|---|---|---|
| SEO job URLs | ✅ | /jobs/{slug} |
| Sitemap.xml | 🔴 | Not yet wired to Railway |
| robots.txt | 🔴 | Missing |
| Structured data (JSON-LD) | 🔴 | Schema.org JobPosting markup |
| Open Graph tags | 🟡 | Basic, not per-job |
| Company SEO pages | ✅ | /companies/{slug} |
| Job alerts (email digest) | ✅ | |
| Referral system | 🔴 | |

---

## Phase 10 — Scraper Intelligence 🟡
*Goal: Reliable, broad job data coverage*

| Feature | Status | Notes |
|---|---|---|
| Greenhouse (US + EU) | ✅ | Remix API + boards-api + HTML fallback |
| Oracle HCM | ✅ | |
| Workday | 🟡 | Works but Playwright dependency |
| Lever | 🟡 | Playwright dependent |
| Odoo | 🟡 | Playwright dependent |
| Generic HTML scraper | 🟡 | Playwright dependent |
| Ashby | 🔴 | Growing ATS, needs adding |
| SmartRecruiters | 🔴 | |
| Teamtailor | 🔴 | |
| Pay range extraction | ✅ | Via Greenhouse detail API |
| Multi-location parsing | ✅ | Semicolon-separated |
| 24h result caching | ✅ | In-process cache with TTL |
| Bot detection bypass | 🟡 | UA rotation, 403 retry, not Cloudflare-proof |
| Job expiry / staleness | 🔴 | Jobs never auto-expire |
| Company logo from scraper | ✅ | logo_url on companies + jobs |

---

## Phase 11 — Security & Compliance 🔴
*Goal: Production-grade security before scale*

| Feature | Status | Notes |
|---|---|---|
| Staging environment | 🔴 | Separate Railway service needed |
| Cloudflare (DDoS, WAF, SSL) | 🔴 | Not yet configured |
| SQL injection audit | 🟡 | 19 f-strings in SQL need review |
| Input sanitisation (XSS) | 🔴 | No HTML stripping on user inputs |
| Rate limiting (auth endpoints) | 🟡 | Global rate limit exists, not per-endpoint |
| Audit log table | 🔴 | Route exists but no DB table |
| NDPR compliance | 🔴 | Privacy Policy, ToS, cookie consent needed |
| Employer verification | 🔴 | No approval flow for new employers |
| Password reset flow | ✅ | |
| Session management | ✅ | Refresh tokens, logout |
| API docs restriction (/docs) | 🔴 | FastAPI /docs exposed publicly |
| Backup strategy | 🔴 | No automated PG backups |
| Secret rotation process | 🔴 | |

---

## Phase 12 — Infrastructure & DevOps 🟡
*Goal: Reliable, scalable deployment*

| Feature | Status | Notes |
|---|---|---|
| Dockerfile (backend) | 🔴 | Currently Nixpacks auto-detect |
| Playwright on Railway | 🟡 | Optional install, graceful skip |
| Staging / Production split | 🔴 | Same Railway service for both |
| CI/CD pipeline | ✅ | GitHub → Railway auto-deploy |
| Environment-based config | ✅ | .env / Railway Variables |
| Health checks | ✅ | /health endpoint |
| Error monitoring (Sentry) | 🔴 | No error tracking |
| Uptime monitoring | 🔴 | No alerting on downtime |
| Log aggregation | 🔴 | Railway logs only, no persistent log store |
| CDN for static assets | 🔴 | All served from Railway |
| CV/file storage (S3/R2) | 🔴 | No file upload infrastructure |
| Email deliverability (SPF/DKIM) | 🔴 | Plain SMTP, will hit spam |
| Transactional email provider | 🔴 | Resend/Sendgrid not yet integrated |

---

## Phase 13 — Scale & Expansion 🔴
*Goal: Pan-African workforce platform*

| Feature | Status | Notes |
|---|---|---|
| Multi-country support | 🔴 | Ghana, Kenya, South Africa, Egypt |
| Multi-currency billing | 🟡 | FX rates exist, gateways per country TBD |
| Mobile app (React Native) | 🔴 | |
| Candidate database (employer search) | 🔴 | Employers pay to search CVs |
| Recruitment agency tools | 🔴 | Bulk pipeline, agency sub-accounts |
| HR module (onboarding, payroll) | 🔴 | Long-term vision |
| API for third-party integrations | 🔴 | Public API with developer keys |
| Marketplace (background checks, assessments) | 🔴 | Partner integrations |
| White-label for enterprises | 🔴 | Custom domain, branding |

---

## Pre-Launch Checklist (v1.0 Public)

### 🔴 Must-have before any public users
- [ ] Staging environment on Railway (separate branch + DB)
- [ ] Cloudflare in front of production domain
- [ ] Fix 19 SQL f-strings (injection risk)
- [ ] Audit log DB table (NDPR requirement)
- [ ] Privacy Policy + Terms of Service pages
- [ ] robots.txt + sitemap.xml
- [ ] Job expiry cron (mark stale jobs inactive)
- [ ] API /docs endpoint restricted in production
- [ ] Delete duplicate Moniepoint company URL from DB

### 🟡 Should-have for soft launch
- [ ] Employer verification / manual approval flow
- [ ] Mobile responsive pass
- [ ] Email deliverability (SPF/DKIM records)
- [ ] Transactional email provider (Resend recommended)
- [ ] Paystack live key end-to-end test
- [ ] Password reset flow end-to-end test
- [ ] Broken apply_url check (scraped jobs with dead links)
- [ ] Error monitoring (Sentry free tier)
- [ ] Analytics (Posthog or Plausible)

### 🟠 Nice-to-have within 30 days of launch
- [ ] Dockerfile for reproducible backend builds
- [ ] CV upload (Cloudflare R2)
- [ ] Automated test suite (Pytest + Playwright)
- [ ] Ashby scraper (fast-growing ATS)
- [ ] API documentation (restrict /docs, publish separate portal)
- [ ] Backup cron (pg_dump to S3 daily)
- [ ] Uptime monitoring (UptimeRobot free)

---

## What Was Built This Session (July 2026)

| Area | What was done |
|---|---|
| Billing admin | Plan modal with search, filter (All/Employer/Candidate/Credit), duplicate, draft, fullscreen, open in new tab, Save/Save as draft |
| Billing admin | Save plan now fast (local state update, no re-fetch) |
| Billing backend | Removed all hardcoded plans — 100% DB-driven |
| Billing backend | Fixed SQLite INSERT missing feature_list (tuple index error) |
| Candidate billing | BillingPage now reads plans from DB, uses feature_list for bullets |
| Candidate features | Admin can now control candidate feature access (apply_jobs, ai_cv, unlimited_saves, etc.) |
| Greenhouse scraper | EU region support (job-boards.eu.greenhouse.io) |
| Greenhouse scraper | 3-strategy architecture: Remix paginated → boards-api → HTML fallback |
| Greenhouse scraper | Pay range extraction via detail endpoint |
| Greenhouse scraper | Multi-location parsing (semicolon-separated) |
| Greenhouse scraper | 24h in-process cache with invalidation on force rescrape |
| Greenhouse scraper | Exponential backoff, 403/429 handling, bot detection UA rotation |
| Greenhouse scraper | Playwright bypassed for Greenhouse (httpx only) |
| Company management | logo_url column on companies + jobs tables |
| Company management | Logo shown in scraper config, passed through to job cards |
| Tenant management | Admin can edit full company profile (about, website, industry, HQ, LinkedIn, etc.) |
| Tenant management | PATCH /admin/tenants/{id}/profile endpoint |
| Quota management | Fixed "no workspaces found" — now queries from tenants table not tenant_quotas |
| Quota management | _get_plan_defaults pulls from billing_plans DB |
| esbuild fixes | Fixed all JSX parse errors (return() in maps, nested templates, $${}  patterns) |

---

## Outstanding Known Issues

| Issue | Severity | Area |
|---|---|---|
| Playwright not available on Railway (browser scraper) | High | Scraper |
| Moniepoint 403 (Cloudflare bot protection on their board) | High | Scraper |
| No staging environment | High | Infrastructure |
| Audit logs table not created in DB | Medium | Compliance |
| 19 SQL f-strings (potential injection) | Medium | Security |
| Job listings never expire | Medium | Data quality |
| Email deliverability (plain SMTP → spam) | Medium | Email |
| Paystack webhook not live-tested | Medium | Billing |
| No employer verification on signup | Medium | Trust & Safety |
| API /docs exposed publicly | Low | Security |
| No automated backup | Low | Infrastructure |
| sitemap.xml not deployed | Low | SEO |
| robots.txt missing | Low | SEO |

---

*Roadmap last updated: July 13, 2026*  
*Sessions: 10 build sessions, ~6 weeks of development*  
*GitHub: seunweb/jobstream*
