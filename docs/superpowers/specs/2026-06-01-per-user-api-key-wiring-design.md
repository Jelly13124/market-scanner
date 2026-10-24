# Per-user API key wiring (Phase 1 — deploy prerequisite)

**Status:** design 2026-06-01, mapped by code audit. For review → writing-plans →
implementation. This is **Phase 1** of the deploy project and a HARD prerequisite
for `2026-06-01-public-deployment-design.md` — without it, every user's analysis
bills the host's `.env`. Branch: the multi-tenant feature line (where auth +
`ApiKeyService` live; not on `main`).

## Goal

Thread each logged-in user's OWN LLM API keys (already stored per-user in the DB)
through the analyze/research (and optionally Lab-chat) pipeline, so a deployed
multi-tenant app spends the USER's credits — and a user without keys gets a clear
"add your key in Settings" error instead of silently using the host's. Background
crons, the scanner, backtests, and market-data fetches **stay on host keys**
(cheap shared infra). Surfaced as part of this: **encrypt the stored keys at rest**
before going public.

## What already exists (do not rebuild)

- `src/llm/models.py:142` `get_model(model_name, model_provider, api_keys: dict | None = None)`
  — already reads `(api_keys or {}).get("X_API_KEY") or os.getenv("X_API_KEY")` for
  every provider. **Mechanism done.**
- `app/backend/services/api_key_service.py:55` `get_api_keys_dict()` → `{provider:
  key}` in EXACTLY the shape `get_model` wants (keys like `DEEPSEEK_API_KEY`). No
  remapping. `require_api_key(provider)` (line 80) raises
  `ApiKeyError("Add your <provider> API key in Settings")`.
- Per-user `ApiKey` model (`database/models.py:7`), CRUD, and the frontend Settings
  UI (`api-keys.tsx`) — all built. Providers collected match the model lookups.

## The threading chain (the core change)

Add an `api_keys: dict | None = None` parameter (default `None` = host behaviour, so
crons compile unchanged) through this EXACT chain:

1. `src/llm/models.py:142` `get_model` — **already has the param.**
2. **`src/research/llm.py:169` `call_research_llm(...)` — THE KEYSTONE.** Today it
   calls `get_model(model_name, model_provider)` with no keys. Add an `api_keys`
   param and forward: `get_model(..., api_keys=api_keys)`.
3. `src/research/sections/_llm_runner.py:59` `run_llm_section(*, section_name, ctx,
   ...)` — read `ctx.api_keys`, pass to `call_research_llm`. (Covers all 14 LLM
   sections — they all funnel through here.)
4. `src/research/sections/base.py:33` `SectionContext` — add an `api_keys: dict |
   None = None` field (the natural carrier; every section already gets `ctx`).
5. `src/research/sop_orchestrator.py:110` `run_sop(request, ..., api_keys=None)` +
   the `SectionContext(...)` build at line 187 — thread `api_keys` into every
   `SectionContext`.
6. `app/backend/routes/research.py:291` (the `/research/analyze` route,
   `current_user` in scope) — fetch and pass:
   ```python
   keys = ApiKeyService(db, current_user.id).get_api_keys_dict()
   run_sop(internal_req, api_keys=keys)
   ```

## The no-host-key-leak policy (CRITICAL correctness)

`get_model` does `... or os.getenv(...)`. So if the user's dict lacks the needed
provider, it **falls back to the host's env key** — leaking the host's credits to
any user. The wiring MUST prevent this for user requests. Two-part fix:

1. **Validate up front in the route:** before `run_sop`, resolve the configured
   model provider (the same `os.environ` model/provider the pipeline uses, or the
   request's) and check the user has that key — `ApiKeyService(db, current_user.id)
   .require_api_key(<provider>)`; on miss, return HTTP 400 with the
   `"Add your <provider> API key in Settings"` message. Fail fast, no run.
2. **Defence in depth in `get_model`:** add an `allow_env_fallback: bool = True`
   param; the user path passes `allow_env_fallback=False` so a partial user dict can
   NEVER reach `os.getenv`. Crons keep the default `True`. (Alternatively gate the
   fallback on "is this a host/system context" — but an explicit flag threaded with
   `api_keys` is simplest and testable.)

## Thread-safety (the single hardest part)

`run_sop` fans 10 sections out on a `ThreadPoolExecutor`
(`sop_orchestrator.py:232-241` + the batch at 260-269). The per-user `api_keys`
dict MUST be carried as an explicit value in each `SectionContext` (captured in the
`_run_one` closure), **never** via `os.environ`, a thread-local, or any process
global — concurrent multi-tenant analyze runs would otherwise race and
cross-contaminate tenants' keys. The chain above (api_keys → run_sop →
SectionContext → run_llm_section) keeps it an explicit argument the whole way, which
is exactly what makes it tenant-safe. A test must assert two concurrent runs with
different keys never see each other's.

## Scope

- **MUST (this spec):** the SOP `/research/analyze` path (route → run_sop → sections).
  This is the main, expensive analyze flow.
- **SHOULD (same pattern, small):** Lab strategy chat — `app/backend/routes/lab.py:214`
  `run_chat_turn` → `src/lab/chat.py:131` `call_research_llm`. `current_user` in
  scope; same keystone. Wire it too (Lab chat burns LLM credits).
- **OPTIONAL:** the legacy `/research/run` path — `routes/research.py:111`
  `run_research` → `src/research/pipeline.py:55` → `modules/*.run`. If that route is
  still user-facing, thread the same param through `run_research` + each
  `module.run`. If it's deprecated, leave it on host keys and DISABLE it for
  non-superusers (so it can't leak). Decide in review.

## Keep host (do NOT thread user keys)

- **Crons** (`scheduler_service.py` `_run_research_job_body:453`, snapshot:547,
  preset:~586, scanner cron ~330) — no logged-in user; `api_keys=None` → host env.
  Separable (distinct functions; default `None` keeps them compiling).
- **Scanner scan** (`scanner_service.py` `run_scan`) — pure quant, no LLM.
- **Backtest** (`run_backtest`) — pure quant.
- **Market-data keys** (FINANCIAL_DATASETS / FINNHUB / EODHD, `v2/data/*`) — cheap
  shared snapshot; the frontend deliberately doesn't collect them. Host-only.
- **Auto-SOP-after-scan** (`scanner_service.py:244,551`) — background/owner context;
  default host. (Could bill the config owner via `ApiKeyService(db, config.user_id)`
  later, but it's a system action — default host.)

## Security: encrypt keys at rest (flagged — recommended before public)

Audit finding: user API keys are stored **PLAINTEXT** (`models.py:17` comment says
"encrypted in production" — NOT implemented; no `Fernet`/`cryptography` anywhere;
`ApiKeyResponse.key_value` even returns plaintext over the API). Storing *other
people's* LLM keys plaintext on a public box is a real risk. **Decision (default for
review):** before public launch, encrypt `key_value` at rest with Fernet keyed by an
`APP_ENCRYPTION_KEY` env secret — encrypt on write in `ApiKeyRepository`, decrypt in
`get_api_keys_dict`; stop returning raw `key_value` in API responses (return a
masked `••••last4`). Additive migration (re-encrypt is moot — they're new). This can
be a sub-task of this spec or a fast-follow, but MUST land before semi-public launch.

## Testing

- Analyze route passes the user's keys: mock `get_model`, assert it receives the
  user's `api_keys` dict (not host env), for a user with keys.
- No host leak: a non-superuser with NO key for the configured provider → the route
  returns 400 "Add your <provider> key", `run_sop`/`get_model` never reached with the
  host key. Assert `get_model` (with `allow_env_fallback=False`) returns/raises
  rather than reading `os.getenv`.
- Tenant isolation: two `SectionContext`s with different `api_keys` run through
  `run_llm_section` concurrently → each calls `get_model` with its OWN dict (no
  cross-contamination). 
- Cron unchanged: `run_sop(req)` / `run_research(req)` with no `api_keys` still uses
  host env (default None path) — existing cron tests stay green.
- Lab chat (if in scope): same "uses user keys" assertion.
- Encryption (if in scope): round-trip encrypt→store→decrypt; API response masks the
  key.

## Decisions (for review)

1. **Wire analyze (must) + Lab chat (should); decide legacy `/research/run`** —
   thread it or disable-for-non-superuser.
2. **No-leak via route-validate + `allow_env_fallback=False`** on the user path.
3. **api_keys carried in `SectionContext`** (explicit arg), never globals — tenant
   safety.
4. **Encrypt keys at rest (Fernet)** before public — in this spec or a fast-follow.
5. Data-provider keys stay host-shared (not per-user).

## Out of scope

- Per-user data-provider keys (host-shared snapshot stays).
- Azure OpenAI per-user (its `get_model` branch is env-only — needs a separate
  change; default: not offered to users).
- The deployment itself (Phase 2, sibling spec).
