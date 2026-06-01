# Scheduled screener + report delivery to email (≤3) + Slack

**Status:** spec written autonomously 2026-06-01 while the user slept; defaults
chosen on every ambiguity and recorded under "Decisions". For morning review →
writing-plans → implementation.

**⚠️ Dependency (verified 2026-06-01):** this builds entirely on the **per-user**
notification infra (`notification_subscriptions.user_id`,
`list_enabled_for_event_and_user`, owner-scoped `dispatch_screener_match(user_id)`,
`get_current_user` on the routes). **`main` does NOT have this** — main's
`NotificationSubscription` has no `user_id`. The per-user scoping lives on the
multi-tenant feature line (currently inherited by `feature/scanner-eval`). So this
project must branch off a branch that includes the per-user notification scoping
(the multi-tenant line), OR that work must merge to `main` first. Do NOT branch off
plain `main`. NOT merged.

## Goal

Let a signed-in user, from **Settings**, bind **up to 3 email addresses** (and a
**Slack** channel) and receive, on a schedule:
- **Screener results** — when a saved screener preset matches.
- **Research reports** — a digest of their recent LLM reports.

## The big surprise: ~80% already exists

The infra audit (Explore, 2026-06-01) found most of this is built. Email is **not**
the gap — it already sends via the **Resend REST API** (`EmailHandler`,
`app/backend/services/notifications/email_handler.py`, keys `RESEND_API_KEY` +
`RESEND_FROM_EMAIL`). **Do NOT build SMTP.**

| Capability | Status | Where |
|---|---|---|
| Email transport (Resend) | ✅ done | `services/notifications/email_handler.py` |
| `notification_subscriptions` table (user-scoped) | ✅ done | `database/models.py:221-247` |
| Subscription CRUD + routes + `/test` + audit log | ✅ done | `repositories/notification_repository.py`, `routes/notifications.py`, `notification_deliveries` |
| Dispatcher fan-out (email/webhook), never-raises | ✅ done | `services/notifications/dispatcher.py` (`dispatch_screener_match`, `dispatch_bundled`) |
| Screener preset nightly cron, **owner-scoped** notify | ✅ done | `services/scheduler_service.py:585-625` → `dispatch_screener_match(user_id=p.user_id)` |
| Research report HTML, in-email bundling (img-strip, inline charts) | ✅ done | `services/notifications/bundled_email.py`, `render.py:397-467` |
| Frontend notification CRUD UI (email/webhook radio, test-send) | ✅ done (wrong place) | `components/panels/scanner/notification-settings.tsx` |
| APScheduler cron registration pattern | ✅ done | `scheduler_service.py:314-322` |

So this project is **wiring + 4 small net-new gaps**, not a build-from-scratch.

## Net-new work (the only real gaps)

### Gap 1 — "Up to 3 emails per user" cap (small)
No enforcement exists. Add a count check in `create_subscription`
(`routes/notifications.py:90`): if `channel == "email"` and the user already has 3
enabled email subscriptions, reject with a 409 + a clear message. Mirror the cap in
the frontend (disable "Add email" at 3, show "3/3 used"). Cap = **3 email subs**;
webhook/slack subs are not capped (or a separate small cap — see Decisions).

### Gap 2 — Slack as a first-class channel (small–medium)
Today Slack only "works" as a generic `webhook`, but `WebhookHandler._build_payload`
(`webhook_handler.py:185-207`) emits PipelineRun JSON that Slack **cannot render**.
- Add `SLACK` to `NotificationChannel` enum (`models/notification_schemas.py:16`)
  and accept `channel='slack'` in route validation (`notifications.py:53-73`).
- Add a `SlackHandler` (or a Slack branch in the dispatcher's `_handler_for`,
  `dispatcher.py:336-345`) that POSTs a **Slack-shaped** payload — `{"text": ...}`
  with a compact summary (and optional Block Kit) — to the subscription's `target`
  (a Slack Incoming Webhook URL). Reuse `WebhookHandler`'s httpx POST + SSRF guard +
  retry; only the payload shape differs. Per event_type, render a 1-screen summary
  (screener: "Preset X — N matches, top: …"; research: "K new reports: …" + links
  are auth-gated so inline the titles/scores, not deep links).
- Frontend: add a "Slack" option to the channel radio
  (`notification-settings.tsx:305-324`); `target` label becomes "Slack webhook URL".
- `channel` is `String(20)` in the DB (no enum constraint) → **no migration needed**.

### Gap 3 — Scheduled RESEARCH REPORT delivery (medium)
Today the screener cron emails the **match table** (done). "报告定时推送" wants the
**research reports** themselves. Add a per-user **report-digest delivery** decoupled
from generation:
- A new nightly cron job `report_digest` (reuse the `scheduler_service` cron
  pattern, e.g. `"40 16 * * 1-5"` after the research cron at 16:35). Body: for each
  user who has ≥1 enabled subscription on `event_type='research.bundled'`, gather
  that user's `research_reports` from the last 24h (user-scoped query), and call
  `dispatcher.dispatch_bundled(event_type='research.bundled', reports=[...])` →
  owner-scoped fan-out to their email/slack subs.
- This reuses the existing bundled-email render (`bundled_email.py`) which already
  inlines `rendered_html`, strips server-hosted imgs, and keeps base64 charts.
- **Why a separate delivery job (not wiring generation):** the research-generation
  cron currently runs as the seed superuser and is not yet per-user
  (`scheduler_service.py:464-467`, "Wave 6"). A delivery job keyed on each user's
  subscriptions is multi-tenant-correct today and avoids that gap.

### Gap 4 — Per-preset schedule control + Settings home (small)
- **Schedule:** presets are scheduled all-or-nothing nightly via `schedule_enabled`
  (`models.py:599`) + one global 22:05 cron. Add a `schedule_frequency`
  (`'daily' | 'weekly'`, default `'daily'`) column to `screener_presets`; the
  existing nightly preset cron (`_run_preset_job_body`) skips a preset whose
  frequency is weekly and whose `last_run_at` is < 7 days ago. (Reuses the single
  global cron — NO per-preset APScheduler jobs.) Additive migration.
- **Settings home:** add a **"Notifications"** section to the Settings shell — a nav
  item (`components/settings/settings.tsx:24-43`) + a `case` in the switch
  (`settings.tsx:45-56`) — and relocate/reuse the existing `NotificationSettings`
  component there (it currently lives under the scanner panel). The Settings section
  shows: bound emails (≤3, with the cap UI), the Slack webhook, and which
  events/schedules each delivers.

## Data model

- **Email binding = `notification_subscriptions` rows** (`channel='email'`,
  `user_id`-scoped). NO new table. The "≤3 emails" is a route-level cap.
- **Slack = `notification_subscriptions` rows** (`channel='slack'`, `target` = Slack
  webhook URL). No schema change (channel is a free String).
- **Preset schedule:** `screener_presets.schedule_frequency String(10) default
  'daily'` — one additive Alembic migration (down_revision = current head; BigInteger
  id variant N/A — no new table; SQLite-safe `batch_alter_table` add_column).
- `notification_deliveries` audit log already records every send (reuse).

## Flows (end to end)

1. **Settings → Notifications:** user adds up to 3 emails + a Slack webhook; picks
   which events to receive (screener matches, research digest). Each "add" creates a
   `notification_subscription` row (event_type + channel + target), capped at 3 for
   email.
2. **Scheduled screener:** nightly preset cron (honoring `schedule_frequency`) →
   `dispatch_screener_match(user_id=owner)` → owner's email/slack subs on
   `screener.match` → Resend / Slack.
3. **Scheduled reports:** nightly `report_digest` cron → per user, bundle last-24h
   `research_reports` → `dispatch_bundled` → owner's subs on `research.bundled`.

All owner-scoped via `list_enabled_for_event_and_user` (the multi-tenant template,
`notification_repository.py:106`).

## Testing

- 3-email cap: creating a 4th email sub → 409; 3rd succeeds; webhook/slack uncapped.
- Slack payload: `SlackHandler` emits `{"text": ...}` (assert shape) for screener +
  research events; never raises; SSRF guard intact.
- `report_digest` cron: with a fake dispatcher, asserts per-user bundling of only
  that user's last-24h reports and owner-scoped dispatch (no cross-tenant leak).
- Preset `schedule_frequency`: weekly preset run <7d ago is skipped; daily always
  runs.
- Migration: upgrade/downgrade symmetry, SQLite + Postgres safe (additive column).
- Frontend: `tsc --noEmit` clean; cap UI disables at 3.

## Decisions (defaulted while user asleep — confirm in review)

1. **Email = Resend (existing), NOT SMTP.** Per the audit.
2. **"绑定最多3个邮箱" = ≤3 `notification_subscriptions` email rows per user**, no
   new settings table; cap enforced backend (409) + frontend.
3. **"报告" = the research reports** (LLM HTML), delivered **inline** in a bundled
   email (report deep-links are auth-gated, so inline not link). A nightly per-user
   **digest** of the last 24h reports.
4. **"screener定时" = the existing nightly preset cron**, plus a per-preset
   `schedule_frequency` (daily default / weekly) so it's user-settable — reusing the
   one global cron, no per-preset jobs.
5. **Slack = a first-class `channel='slack'`** with a Slack-shaped payload (Incoming
   Webhook URL in `target`), not the raw generic webhook.
6. **Settings home:** relocate the existing `NotificationSettings` UI into a new
   Settings "Notifications" section.
7. Slack/webhook subs: not capped at 3 (only email is). Confirm if a cap is wanted.

## Out of scope

- Per-user verified sender domain (one global `RESEND_FROM_EMAIL`).
- Public signed report links (so emailed links open without a session).
- Making the research-GENERATION cron per-user (Wave 6) — the digest delivery job
  sidesteps it.
- Discord / Teams / SMS channels.
