# Public deployment — Vultr + Docker Compose + Caddy (semi-public)

**Status:** design 2026-06-01, brainstormed interactively. For review →
writing-plans → implementation. This is **Phase 2** of the deploy project; **Phase
1 (per-user API key wiring) is a hard prerequisite** — see the sibling spec
`2026-06-01-per-user-api-key-wiring-design.md`. Do NOT deploy publicly until users
bring their own keys (else the host pays for everyone).

## Goal

Put the multi-tenant app on the public internet for **semi-public** use (open
registration, modest scale) on a **Vultr** VPS, behind one domain with automatic
HTTPS, with basic abuse protection. Cost to the host stays ~$0 for LLM/data usage
(per-user keys) + ~$24/mo VPS + ~$10/yr domain.

## Locked decisions (from brainstorming)

1. **Per-user keys** — host pays $0 for usage (Phase 1 prerequisite).
2. **Semi-public** — open registration + **email verification** + **rate limiting**
   + optional invite codes.
3. **Vultr** VPS — a **NEW** Cloud Compute instance, **2 vCPU / 4 GB (~$24/mo)**;
   do NOT reuse the existing 1 GB VPN instances (a scanner scan uses ~0.8–1 GB →
   OOM on 1 GB) and don't co-host with the VPN. Ubuntu 24.04. (2 GB ~$12 is a tight
   fallback if cost-sensitive.)
4. **Domain** — buy one (~$10/yr, Cloudflare Registrar / Porkbun), Cloudflare DNS,
   A-record → VPS IP.
5. **Single VPS + Docker Compose + Caddy** (auto-TLS). **Stay on SQLite** (user's
   standing decision) — on a persisted Docker volume.

## Architecture

```
            yourapp.com  (A record → Vultr IP)
                  │
        ┌─────────▼─────────┐  Caddy (reverse proxy + automatic HTTPS)
        │   /          →    │  frontend static (vite build), file_server
        │   /api/*     →    │  backend:8000 (uvicorn)  ── APScheduler inside
        └───────────────────┘
                  │
        SQLite file on a Docker named volume (WAL + busy_timeout + nightly backup)
```

**Single domain + `/api` sub-path** → no CORS, auth can be same-origin (more
robust than the dev cross-origin localStorage flow; see Auth below). Compose
services: `caddy`, `backend`. Frontend is built to static assets and served by
Caddy (either baked into the caddy image or a shared volume from a frontend build
stage).

## Components / files (create or adapt)

| File | Purpose |
|---|---|
| `docker/Dockerfile.backend` | adapt existing `docker/Dockerfile`: install Python deps, run `uvicorn app.backend.main:app --host 0.0.0.0 --port 8000` (no `--reload`); entrypoint runs `alembic upgrade head` first. |
| `docker/Dockerfile.frontend` | multi-stage: `vite build` (with `VITE_API_URL=/api`) → output static to a stage Caddy serves. |
| `docker/Caddyfile` | `yourapp.com { handle /api/* { reverse_proxy backend:8000 } handle { root * /srv; try_files {path} /index.html; file_server } }` — automatic HTTPS via Let's Encrypt. |
| `docker/docker-compose.prod.yml` | services `caddy` (ports 80/443, volumes: caddy_data, frontend static), `backend` (env_file .env, volume sqlite_data:/data); `restart: unless-stopped`. |
| `.env.prod.example` | documents the prod env (below); the real `.env` is created ON the VPS, never committed. |
| `docs/DEPLOY.md` | step-by-step runbook (provision → DNS → docker → up → backups → updates). |

## Production configuration (the `.env` on the VPS)

- `JWT_SECRET` — a strong random 32+ byte secret (NOT the dev default
  `dev-insecure-change-me`). Generate with `openssl rand -hex 32`.
- `DATABASE_URL=sqlite:////data/app.db` — on the persisted volume. WAL +
  busy_timeout already configured in `connection.py`.
- `RESEND_API_KEY` + `RESEND_FROM_EMAIL` — for email verification + notifications
  (Resend already wired). Verify a sender domain in Resend for deliverability.
- Per-user keys mean NO host LLM keys are required for user requests; but the
  SHARED background jobs (snapshot/cron) still need the host's market-data keys
  (`EODHD_API_KEY`, `FINNHUB_API_KEY`, …) in `.env` — keep those.
- Frontend build-time `VITE_API_URL=/api` (same-origin).
- App config flags: `REGISTRATION_OPEN=true`, `REQUIRE_EMAIL_VERIFICATION=true`,
  `INVITE_CODES=` (optional), rate-limit knobs.

## Auth for a public surface

- The dev flow puts the access token in `localStorage` and is cross-origin
  (5173↔8001). In prod we're **same-origin** (`/` + `/api`), so we CAN move the
  refresh token to an httpOnly+Secure+SameSite cookie (more secure). **Default:
  keep the existing localStorage access-token flow to minimize change** (it works
  same-origin too); note the httpOnly-cookie hardening as a fast follow.
- HTTPS only (Caddy). `Secure` + `SameSite=Lax` on any cookie.
- Strong `JWT_SECRET`; short access TTL (30 min, already) + refresh rotation.

## Abuse protection (semi-public)

1. **Email verification** — on register, issue a one-time verification token, email
   it via Resend; gate login / API use until verified. New: a `verification_token`
   on `User` (or a small table) + a `/auth/verify` route + the email template.
   (Confirm against current auth — the multi-tenant auth may already have a stub.)
2. **Rate limiting** — add `slowapi` (or a lightweight middleware) keyed by IP +
   user: tight limits on `/auth/*` (login/register), modest on analyze/scan
   (these are per-user-key-funded so the cost risk is the USER's, but the VPS CPU
   is shared — cap concurrent scans).
3. **Optional invite codes** — a config flag + a small check at register; off by
   default, on if abuse appears.
4. **Resource guards** — cap concurrent analyze/scan per user; the scanner's heavy
   scans run on the nightly cron, not per-request, to protect the 4 GB box.

## SQLite in production

- WAL + `busy_timeout=30s` already set. Single backend instance (no horizontal
  scaling — SQLite + one APScheduler). Document this as a known ceiling; the
  `DATABASE_URL` env makes a future Postgres swap a 1-var change if scale demands.
- **Backups:** nightly `sqlite3 /data/app.db ".backup /data/backup-$(date).db"`
  (or litestream to object storage) via a cron/compose sidecar; keep N days.
- Volume `sqlite_data` persists across `compose up`/redeploys.

## Prerequisites (must land before deploy)

1. **Phase 1 — per-user key wiring** (sibling spec). Without it, deploy bills the
   host.
2. **Multi-tenant work merged to `main`** (or deploy from the multi-tenant feature
   line) — `main` lacks the per-user models/auth. Confirm + merge.

## Ops runbook (in `docs/DEPLOY.md`)

1. Provision Vultr 4 GB Ubuntu 24.04; create a non-root sudo user; ufw (allow 22/80/443); fail2ban.
2. Buy domain; Cloudflare DNS A-record → VPS IP (proxy off initially for Let's Encrypt, or use DNS-challenge).
3. Install Docker + compose plugin.
4. Clone repo (the deploy branch); create `/data` volume; write `.env` (secrets).
5. `docker compose -f docker/docker-compose.prod.yml up -d --build` (entrypoint runs `alembic upgrade head`).
6. Verify HTTPS, register a test user, verify email, add keys, run an analysis.
7. Updates: `git pull && docker compose ... up -d --build`. Backups: nightly job.

## Testing / verification

- Local: `docker compose -f docker/docker-compose.prod.yml up` against a test
  domain or `localhost` (Caddy `tls internal` for local) — smoke the full flow.
- A deploy checklist in `docs/DEPLOY.md`; a `/health` endpoint for uptime checks.
- Confirm migrations run clean on a fresh volume (fresh DB → `alembic upgrade head`).

## Decisions (defaulted — confirm in review)

1. Vultr new **4 GB** instance (not the 1 GB VPN ones). 2 GB tight fallback.
2. **Single domain + `/api`** (no CORS); keep localStorage access-token auth
   (cookie hardening = fast follow).
3. Caddy auto-TLS (not nginx+certbot).
4. Email verification + rate limiting ON for the public surface; invite codes OFF
   by default.
5. SQLite on a volume + nightly `.backup`; single instance (documented ceiling).
6. Frontend served by Caddy as static (not a separate node server).

## Out of scope

- Horizontal scaling / Postgres / k8s / CDN.
- Per-user verified sender domains.
- Mobile apps.
- The per-user-key WIRING itself (Phase 1, sibling spec).
