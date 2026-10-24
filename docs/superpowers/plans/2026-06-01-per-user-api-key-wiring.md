# Per-user API key wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development.
> Steps use `- [ ]`. Fresh implementer per task; two-stage review (spec-compliance
> then code-quality). This touches the LLM + auth + multi-tenant path — review
> carefully; a tenant-isolation bug here leaks one user's keys/credits to another.

**Goal:** Thread each logged-in user's own LLM API keys through the analyze (+ Lab
chat) pipeline so a deployed app spends the USER's credits; a user without the
needed key fails fast with "add your key in Settings"; the host's `.env` keys are
NEVER reachable by a normal user request; crons/scanner/backtest/data stay on host
keys. Plus: encrypt stored user keys at rest.

**Architecture:** Add an explicit `api_keys: dict | None = None` parameter (default
None = host behaviour) down the chain `route → run_sop → SectionContext →
run_llm_section → call_research_llm → get_model`. Block the host-env fallback on the
user path. Carry keys as an explicit value across the `ThreadPoolExecutor` fan-out
(never a global/thread-local). Fernet-encrypt `ApiKey.key_value` at rest.

**Tech stack:** FastAPI (sync), SQLAlchemy, the existing `ApiKeyService`,
`cryptography` (Fernet).

**Spec:** `docs/superpowers/specs/2026-06-01-per-user-api-key-wiring-design.md`

---

## Constraints (paste into every implementer prompt)

- Python `C:\Users\Jerry\anaconda3\python.exe`; tests `-m pytest`; from repo root
  with `PYTHONPATH=.` and `PYTHONIOENCODING=utf-8`.
- Branch **`feature/per-user-keys`** off the multi-tenant line (the branch that has
  `app/backend/auth/` + `ApiKeyService` + the per-user models — verify
  `ApiKeyService` imports before starting). Commit per task; conventional message;
  **NO Co-Authored-By; never --no-verify**. Explicit `git add <paths>` — never
  `-A`, never stage `.claude/settings.local.json`. Black hook → re-add + re-commit.
- All subagents **opus**.
- **Tenant safety is load-bearing:** `api_keys` must be an explicit argument the
  whole way — NEVER `os.environ`, a module global, or a thread-local. Two concurrent
  analyze runs for different users must never see each other's keys.
- **No host-key leak:** a normal user request must never reach `os.getenv("*_API_KEY")`
  for an LLM provider. Crons keep the host fallback (default `None` path).
- Don't break the cron tests (they call `run_sop`/`run_research` with no `api_keys`).

---

## Wave A — Thread `api_keys` through the analyze path

### Task A1: `get_model` no-fallback flag + `call_research_llm` forwarding

**Files:** Modify `src/llm/models.py`, `src/research/llm.py`; Test
`tests/research/test_llm_keys.py` (new).

- [ ] **Step 1 — failing test:**
```python
def test_call_research_llm_forwards_user_keys(monkeypatch):
    captured = {}
    def fake_get_model(name, provider, api_keys=None, allow_env_fallback=True):
        captured["api_keys"] = api_keys; captured["fallback"] = allow_env_fallback
        return _FakeLLM()
    monkeypatch.setattr("src.research.llm.get_model", fake_get_model)
    call_research_llm("prompt", _OutModel, api_keys={"DEEPSEEK_API_KEY": "u-key"})
    assert captured["api_keys"] == {"DEEPSEEK_API_KEY": "u-key"}
    assert captured["fallback"] is False   # user path disables env fallback

def test_get_model_no_env_fallback_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "HOST")
    # user dict missing the provider + allow_env_fallback=False → must NOT use HOST
    with pytest.raises(Exception):
        get_model("deepseek-chat", "DeepSeek", api_keys={}, allow_env_fallback=False)
```
- [ ] **Step 2** — run, FAIL.
- [ ] **Step 3 — implement.**
  - `src/llm/models.py:142` `get_model(...)`: add `allow_env_fallback: bool = True`.
    For each provider change `(api_keys or {}).get("X") or os.getenv("X")` to:
    `key = (api_keys or {}).get("X"); if not key and allow_env_fallback: key = os.getenv("X")`.
    If still no key → raise a clear `ValueError(f"No API key for {provider}")`.
  - `src/research/llm.py:150` `call_research_llm(...)`: add `api_keys: dict | None =
    None`; at line 169 call `get_model(model_name, model_provider, api_keys=api_keys,
    allow_env_fallback=(api_keys is None))`. (api_keys None = host/cron path → fallback
    on; a non-None dict = user path → fallback off.)
- [ ] **Step 4** — PASS. Run `tests/research/` to confirm no regression.
- [ ] **Step 5 — commit.** `feat(keys): get_model env-fallback flag + call_research_llm forwards api_keys`

### Task A2: `SectionContext.api_keys` + `run_llm_section` passes it

**Files:** Modify `src/research/sections/base.py`, `src/research/sections/_llm_runner.py`;
Test `tests/research/test_llm_section_runner.py` (extend).

- [ ] **Step 1 — failing test:** build a `SectionContext(..., api_keys={"OPENAI_API_KEY":
  "u"})`, monkeypatch `call_research_llm` to capture its `api_keys` kwarg, run
  `run_llm_section(...)`, assert it received `{"OPENAI_API_KEY": "u"}`. A context with
  `api_keys=None` → `call_research_llm` gets `None`.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `base.py:33` `SectionContext`: add `api_keys: dict | None
  = None`. `_llm_runner.py:59`: pass `api_keys=ctx.api_keys` to `call_research_llm`.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(keys): thread api_keys through SectionContext + run_llm_section`

### Task A3: `run_sop` threads keys into every `SectionContext` (tenant-safe)

**Files:** Modify `src/research/sop_orchestrator.py`; Test `tests/research/test_sop_keys.py` (new).

- [ ] **Step 1 — failing test:** `run_sop(request, api_keys={"X":"u"})` → every
  `SectionContext` built (line 187) carries `api_keys={"X":"u"}`. **Tenant-safety test:**
  two `run_sop` calls with different `api_keys` interleaved (or assert the dict is read
  from the arg/ctx, not any global) → each section sees its OWN dict. (Mock the section
  runner to record the ctx.api_keys it saw per call.)
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `run_sop(request, ..., api_keys: dict | None = None)`
  (line 110); pass `api_keys=api_keys` into every `SectionContext(...)` at line 187
  (and any other SectionContext construction). The `ThreadPoolExecutor` `_run_one`
  closure must capture it via the ctx (already passed) — NOT a global.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(keys): run_sop threads per-user api_keys into SectionContext (tenant-safe)`

### Task A4: analyze route fetches user keys + validates (no-leak)

**Files:** Modify `app/backend/routes/research.py`; Test
`tests/research/test_analyze_route_keys.py` (new) or extend the route tests.

- [ ] **Step 1 — failing test:** (a) a user WITH a DEEPSEEK key → the route calls
  `run_sop` with `api_keys` containing it (mock `run_sop`, assert). (b) a NON-superuser
  with NO key for the configured provider → the route returns **400** with the
  "Add your <provider> API key in Settings" message and `run_sop` is NOT called.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** In `trigger_analyze` (research.py:277), before `run_sop`
  (line 291): `svc = ApiKeyService(db, current_user.id)`; resolve the provider the
  pipeline will use (the env `RESEARCH_MODEL_PROVIDER` / request); `svc.require_api_key
  (<provider>)` inside try/except → on `ApiKeyError` return `HTTPException(400, msg)`.
  Then `keys = svc.get_api_keys_dict()` and `run_sop(internal_req, api_keys=keys)`.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(keys): analyze route uses the user's keys + fails fast without them`

---

## Wave B — Extend coverage

### Task B1: Lab chat uses the user's keys

**Files:** Modify `app/backend/routes/lab.py`, `src/lab/chat.py`; Test (new/extend lab tests).

- [ ] **Step 1 — failing test:** the lab-chat route (`lab.py:188` `trigger_chat`,
  `current_user` in scope) → `run_chat_turn` → `chat.py:131` `call_research_llm`
  receives the user's `api_keys`. A keyless non-superuser → 400.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** Thread `api_keys` from the route (fetch via
  `ApiKeyService(db, current_user.id)`, validate) → `run_chat_turn(..., api_keys=...)`
  → `call_research_llm(..., api_keys=api_keys)` at `chat.py:131`.
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(keys): Lab chat uses the user's keys`

### Task B2: disable legacy `/research/run` for non-superusers

**Files:** Modify `app/backend/routes/research.py`; Test (extend route tests).

- [ ] **Step 1 — failing test:** a non-superuser calling `/research/run`
  (research.py:101 `trigger_run`) → **403** ("this endpoint is deprecated; use
  /research/analyze"). A superuser → still works (host keys, unchanged).
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** In `trigger_run`, if `not current_user.is_superuser`:
  raise `HTTPException(403, ...)`. (Avoids the legacy `pipeline.py` path leaking host
  keys; per the spec default. If a future need arises, thread keys instead.)
- [ ] **Step 4** — PASS.
- [ ] **Step 5 — commit.** `feat(keys): gate legacy /research/run to superusers (prevent host-key leak)`

---

## Wave C — Encrypt user keys at rest

### Task C1: Fernet-encrypt `ApiKey.key_value`

**Files:** Modify `app/backend/services/api_key_service.py` +
`repositories/api_key_repository.py` + `models/...schemas.py` (mask response); new
`app/backend/auth/key_crypto.py`; migration if existing rows; Test
`tests/test_api_key_crypto.py` (new).

- [ ] **Step 1 — failing test:** with `APP_ENCRYPTION_KEY` set, writing a key stores
  CIPHERTEXT (the raw DB `key_value` != the plaintext) and `get_api_keys_dict()`
  returns the DECRYPTED plaintext; the API response (`ApiKeyResponse`) returns a MASKED
  value (`••••last4`), never the plaintext.
- [ ] **Step 2** — FAIL.
- [ ] **Step 3 — implement.** `key_crypto.py`: `encrypt(plaintext)` / `decrypt(cipher)`
  via `cryptography.fernet.Fernet(os.environ["APP_ENCRYPTION_KEY"])` (a base64 32-byte
  key). Encrypt on write in the repository/service; decrypt in `get_api_keys_dict` /
  `get_api_key`. Change `ApiKeyResponse.key_value` to a masked field. If
  `APP_ENCRYPTION_KEY` is unset, keep plaintext + log a loud warning (dev). One-time
  data migration: if existing plaintext rows exist, encrypt them (detect-and-encrypt
  on read, or a migration script). Add `cryptography` to deps if missing.
- [ ] **Step 4** — PASS + the existing api-key tests stay green (adapt any that
  asserted plaintext over the API).
- [ ] **Step 5 — commit.** `feat(keys): encrypt user API keys at rest (Fernet) + mask in responses`

---

## Wave V — End-to-end verification

### Task V1: full-flow + isolation + cron-unchanged

- [ ] Integration test: a user with keys runs `/research/analyze` (mock `get_model`) →
  the user's keys reach `get_model`, host env never read. A keyless user → 400.
- [ ] Tenant isolation: two users' concurrent analyze (or two SectionContexts) → no
  cross-contamination (each `get_model` call gets its own dict).
- [ ] Cron unchanged: `run_sop(req)` / `run_research(req)` with no `api_keys` → host
  env path; the scheduler/research cron tests stay green.
- [ ] Full backend suite green; commit any test fixups.

---

## Self-review (done)

- **Spec coverage:** threading chain (A1–A4), Lab chat (B1), legacy gate (B2),
  encryption (C1), isolation/no-leak/cron verification (V1) — every spec item mapped. ✓
- **No placeholders:** concrete file:line targets + tests per task. ✓
- **Tenant safety + no-leak:** A1 (fallback flag), A3 (explicit arg, no globals), A4
  (validate + fail fast), V1 (isolation test) — the load-bearing properties are each
  tested. ✓
