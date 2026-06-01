# Deploying to Fly.io — runbook

How to put the app on the public internet (semi-public: open registration + email
verification + rate limiting). Cost ≈ **$12/mo** (Fly shared-cpu-1x 2 GB) + a volume
(~$0.50/mo) + a domain (~$10/yr). **Each user brings their own LLM keys → you pay $0
for usage.**

## What's in the box

- `Dockerfile` — multi-stage: builds the frontend (vite) + the python backend into one
  image that serves the API at root **and** the built SPA from the same origin.
- `docker/entrypoint.sh` — runs `alembic upgrade head` on the machine (where the volume
  is), then uvicorn.
- `fly.toml` — one machine + a volume for SQLite, auto-TLS, `/health` check. **Fill in
  every `CHANGE-ME` first.**

## Prerequisites

1. A **Fly.io account** → install flyctl: `iwr https://fly.io/install.ps1 -useb | iex`
   (Windows PowerShell) or `curl -L https://fly.io/install.sh | sh`. Then `fly auth login`.
2. A **domain** (~$10/yr, Cloudflare Registrar / Porkbun) — optional at first; you can
   launch on the free `*.fly.dev` host and add the domain later.
3. The code on the deploy branch: `feature/per-user-keys` (it has the multi-tenant auth +
   the per-user-key wiring + email-verify + rate-limit). Either deploy from this branch,
   or merge it to `main` first — your call.

---

## Deploy — step by step

### 1. Launch the app (creates the Fly app, picks a name + region)
```powershell
cd C:\Users\Jerry\Desktop\ai-hedge-fund
fly launch --no-deploy
```
- It detects the `Dockerfile` + `fly.toml`. Choose an **app name** (becomes
  `<name>.fly.dev`) and a **region near you** (e.g. `nrt` Tokyo, `sjc` US-West).
- Let it update `fly.toml`'s `app`/`primary_region`. Then **edit `fly.toml`**: replace
  the three `CHANGE-ME.fly.dev` with your real `<name>.fly.dev` (in `VITE_API_URL` and
  `FRONTEND_ORIGINS`).

### 2. Create the SQLite volume (one-time)
```powershell
fly volumes create data --size 3 --region <same-region-as-app>
```
(3 GB is plenty for SQLite + backups. It mounts at `/data` per `fly.toml`.)

### 3. Set the secrets (never put these in fly.toml or git)
```powershell
# generate two strong secrets:
$jwt = python -c "import secrets; print(secrets.token_hex(32))"
$enc = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

fly secrets set `
  JWT_SECRET=$jwt `
  APP_ENCRYPTION_KEY=$enc `
  RESEND_API_KEY=<your-resend-key> `
  RESEND_FROM_EMAIL=<verified-sender@yourdomain> `
  EODHD_API_KEY=<your-eodhd-key> `
  FINNHUB_API_KEY=<your-finnhub-key>
```
- `JWT_SECRET` — signs auth tokens (NOT the dev default).
- `APP_ENCRYPTION_KEY` — Fernet key that encrypts users' stored API keys at rest.
- `RESEND_*` — sends the email-verification mails (sign up at resend.com, verify a
  sender domain for deliverability). **Without these, verification emails won't send.**
- `EODHD_API_KEY` / `FINNHUB_API_KEY` — the HOST's market-data keys for the SHARED
  scanner snapshot + crons (cheap, ~$20/mo EODHD). Users do NOT supply these — only their
  own LLM keys. **No host LLM keys are needed** (per-user).
- (Optional: `INVITE_CODES=code1,code2` if you later want invite-gating.)

### 4. Deploy
```powershell
fly deploy
```
The image builds (frontend + backend), the entrypoint runs `alembic upgrade head` against
the fresh volume, uvicorn boots. First build takes a few minutes.

### 5. Smoke-test
```powershell
fly open                      # opens https://<name>.fly.dev
fly logs                      # watch the boot + requests
```
In the browser: register an account → check your email → click the verify link → in
Settings add your own LLM key (e.g. DeepSeek) → run an analysis. It should spend YOUR key
(a user with no key gets "Add your … API key in Settings").

### 6. Custom domain + TLS (optional)
```powershell
fly certs add yourapp.com
```
Fly prints a DNS record — add it at your registrar (an `A`/`AAAA` or `CNAME`). Wait for
the cert to go green (`fly certs show yourapp.com`). Then update `fly.toml`'s
`VITE_API_URL` + `FRONTEND_ORIGINS` to `https://yourapp.com` and `fly deploy` again (the
SPA bundle bakes the URL at build time, so it must be rebuilt for the new domain).

---

## Day-2 operations

- **Update / redeploy:** `git pull` (or push your branch) → `fly deploy`.
- **Logs:** `fly logs`. **SSH in:** `fly ssh console`.
- **Scale RAM** (if the nightly scanner scan OOMs on 2 GB): `fly scale memory 4096`.
- **Backups:** Fly takes **daily volume snapshots** automatically (~5-day retention) —
  `fly volumes snapshots list <vol-id>`. For continuous SQLite backup, add **litestream**
  to Cloudflare R2/S3 later (recommended once you have real users).
- **One machine only.** SQLite + the in-process APScheduler require exactly one instance
  (`min_machines_running = 1`, `auto_stop_machines = false`). Do **not** `fly scale count`
  above 1 — two machines would diverge the SQLite DB.

## Known ceilings (by design)

- **SQLite, single instance** — fine for a semi-public friend-scale app. `DATABASE_URL`
  makes a future Postgres swap a one-env-var change if you outgrow it.
- **Email deliverability** depends on a verified Resend sender domain.
- **2 GB** is comfortable for steady use; the heavy bit is the nightly scanner scan —
  scale to 4 GB or move scans off-peak if needed.

## Security recap (already built)

- Users' LLM keys are **encrypted at rest** (Fernet, `APP_ENCRYPTION_KEY`) and **never**
  returned in full by the API (masked `••••last4`).
- A normal user can never reach the host's `.env` LLM keys (the analyze/lab paths fail
  fast without the user's own key); the legacy `/research/run` is superuser-only.
- Email verification + IP rate limiting guard the public surface; HTTPS enforced by Fly.
