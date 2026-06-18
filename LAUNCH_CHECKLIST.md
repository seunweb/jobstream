# JobStream Launch Checklist

## Pre-launch

### Environment
- [ ] `SECRET_KEY` set to a strong 32+ char random string
- [ ] `DATABASE_URL` pointing to Railway PostgreSQL
- [ ] `RESEND_API_KEY` configured and domain verified
- [ ] `PAYSTACK_SECRET_KEY` and `PAYSTACK_PUBLIC_KEY` set
- [ ] `ANTHROPIC_API_KEY` set
- [ ] `APP_URL` set to Railway frontend URL
- [ ] `ALLOWED_ORIGINS` set to Railway frontend URL

### Paystack
- [ ] Paystack account verified and live keys active
- [ ] Webhook URL set: `https://your-api.up.railway.app/billing/webhook`
- [ ] Test payment successful on staging

### Resend
- [ ] Domain verified on resend.com
- [ ] `FROM_EMAIL` updated from `onboarding@resend.dev` to your domain email

### Security
- [ ] HTTPS enforced on Railway
- [ ] Rate limiting tested (try 11 failed logins)
- [ ] Webhook signature verification working

### Content
- [ ] At least 10 companies added to Streamer Config
- [ ] First scrape completed successfully
- [ ] Company logos showing correctly

### SEO
- [ ] Sitemap submitted to Google Search Console: `https://your-site.com/sitemap.xml`
- [ ] Privacy Policy and Terms pages reviewed
- [ ] Meta description added to index.html

## Post-launch

- [ ] Set up Railway cron for job alerts: `POST /job-alerts/send` (daily)
- [ ] Set up Railway cron for job expiry: `POST /jobs/expire?days=60` (weekly)
- [ ] Monitor Railway logs for errors
- [ ] Set up uptime monitoring (UptimeRobot free tier)
- [ ] Create admin account and set role to `super_admin`
