# Deploy Paper Forward-Test Unattended — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the 4-light-sleeve paper forward-test to the live Fly app so it accrues real out-of-sample data unattended, gated by a `PAPER_SLEEVES` env so the heavy `factor_evolved` sleeve is excluded until sub-project B+C.

**Architecture:** One small TDD code change (an env-gated `active_sleeves()` that `run_once` iterates instead of the hardcoded `SLEEVE_NAMES`), then a deploy runbook of ordered `fly`/`git` commands. The harness + scheduler are already wired; the entrypoint runs `alembic upgrade head` on a persisted SQLite volume; the always-on machine runs APScheduler. The deploy is verified live by runbook criteria, not the test suite.

**Tech Stack:** Python (anaconda interpreter), pytest, SQLite/Alembic, APScheduler, Fly.io (Docker), Git.

**Ownership legend:** 🟦 **CLAUDE-RUN** (local, no outward effect — code, tests, dry checks). 🟥 **USER-RUN** (outward/irreversible — the user runs these in-session via the `!` prefix so output lands here; Claude interprets). The actual deploy is USER-RUN and is **not** a test-suite step.

**Global constraints (every task):**
- Python: `C:\Users\Jerry\anaconda3\python.exe` (Poetry not on PATH).
- Tests: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest <path> -q` — OFFLINE only (stub seams, scratch SQLite; no network/LLM/Fly).
- Commit per code task; conventional message; **NO Co-Authored-By**; never `--no-verify`; explicit `git add <paths>` (never `-A`); never stage `.claude/settings.local.json`.
- `black` on touched `.py` before commit. Branch `main`.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `src/paper_trading/sleeves.py` | Sleeve target logic + the sleeve roster | **Modify**: add `active_sleeves()` reading `PAPER_SLEEVES`. |
| `src/paper_trading/run.py` | CLI + scheduler drivers | **Modify**: `run_once` iterates `active_sleeves()` (line ~192) instead of `SLEEVE_NAMES`; fix the import. |
| `fly.toml` | Prod env + machine config | **Modify**: add `PAPER_SLEEVES` to `[env]` (the 4 light sleeves). |
| `src/paper_trading/test_sleeves.py` | Unit tests for sleeve logic | **Modify**: add `active_sleeves()` tests. |
| `src/paper_trading/test_run_active_sleeves.py` | run_once honors the gate | **Create**: one focused offline test. |

Current facts confirmed (do not re-derive):
- `sleeves.py:48` — `SLEEVE_NAMES = ("scanner_agent", "scanner_only", "spy_benchmark", "scanner_agent_flow", "factor_evolved")` (5-tuple) and a module `logger` already exists (`sleeves.py:38`).
- `run.py:41` — `from .sleeves import SLEEVE_NAMES, compute_targets`; `run.py:192` — `for sleeve_name in SLEEVE_NAMES:` is the ONLY iteration site (the CLI `main()` iterates the returned `summaries` dict, not `SLEEVE_NAMES`).
- `marks.py:174` — `mark_all` iterates `session.query(PaperSleeve).all()` (DB rows), so an un-seeded `factor_evolved` is never marked. No change needed in `marks.py`.

---

## Task 1: `active_sleeves()` env gate in sleeves.py

**Files:**
- Modify: `src/paper_trading/sleeves.py` (add `import os` + the function after `SLEEVE_NAMES`)
- Test: `src/paper_trading/test_sleeves.py`

- [ ] **Step 1: Write the failing tests** — append to `src/paper_trading/test_sleeves.py`:

```python
import importlib

from src.paper_trading import sleeves as sleeves_mod
from src.paper_trading.sleeves import SLEEVE_NAMES, active_sleeves


def test_active_sleeves_unset_returns_all(monkeypatch):
    monkeypatch.delenv("PAPER_SLEEVES", raising=False)
    assert active_sleeves() == SLEEVE_NAMES


def test_active_sleeves_blank_returns_all(monkeypatch):
    monkeypatch.setenv("PAPER_SLEEVES", "   ")
    assert active_sleeves() == SLEEVE_NAMES


def test_active_sleeves_subset_in_canonical_order(monkeypatch):
    # request out of order + with whitespace; result follows SLEEVE_NAMES order
    monkeypatch.setenv("PAPER_SLEEVES", "scanner_only , spy_benchmark,scanner_agent")
    assert active_sleeves() == ("scanner_agent", "scanner_only", "spy_benchmark")


def test_active_sleeves_excludes_factor_evolved(monkeypatch):
    monkeypatch.setenv(
        "PAPER_SLEEVES", "scanner_agent,scanner_only,spy_benchmark,scanner_agent_flow"
    )
    result = active_sleeves()
    assert "factor_evolved" not in result
    assert result == ("scanner_agent", "scanner_only", "spy_benchmark", "scanner_agent_flow")


def test_active_sleeves_drops_unknown_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("PAPER_SLEEVES", "scanner_only,bogus_sleeve")
    with caplog.at_level("WARNING"):
        result = active_sleeves()
    assert result == ("scanner_only",)
    assert any("bogus_sleeve" in r.message for r in caplog.records)


def test_active_sleeves_all_unknown_falls_back_to_all(monkeypatch, caplog):
    # a fully garbage env must never silently run zero sleeves
    monkeypatch.setenv("PAPER_SLEEVES", "nope,nada")
    with caplog.at_level("WARNING"):
        result = active_sleeves()
    assert result == SLEEVE_NAMES


def test_active_sleeves_never_raises(monkeypatch):
    monkeypatch.setenv("PAPER_SLEEVES", ",,, ,")
    # only commas/space -> no tokens -> treated as blank -> all
    assert active_sleeves() == SLEEVE_NAMES
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest src/paper_trading/test_sleeves.py -q`
Expected: FAIL with `ImportError: cannot import name 'active_sleeves'`.

- [ ] **Step 3: Implement `active_sleeves()`** — in `src/paper_trading/sleeves.py`, add `import os` to the imports (after `import logging`), and add this function immediately after the `SLEEVE_NAMES` definition (line ~48):

```python
def active_sleeves() -> tuple[str, ...]:
    """The sleeves to run unattended, from the ``PAPER_SLEEVES`` env var.

    ``PAPER_SLEEVES`` is a comma-separated list. Unset/blank -> all
    :data:`SLEEVE_NAMES` (local default, so nothing changes off prod). Names not
    in ``SLEEVE_NAMES`` are dropped with a warning. A request that leaves zero
    known sleeves falls back to all (never silently runs nothing). The result
    preserves ``SLEEVE_NAMES`` order. Never raises.

    Prod sets ``PAPER_SLEEVES`` to the 4 light sleeves so the heavy
    ``factor_evolved`` sleeve is excluded from the unattended forward test until
    its backtest/bundle path is sped up (sub-project B+C).
    """
    raw = os.environ.get("PAPER_SLEEVES", "").strip()
    if not raw:
        return SLEEVE_NAMES
    requested = [tok.strip() for tok in raw.split(",") if tok.strip()]
    if not requested:
        return SLEEVE_NAMES
    known = set(SLEEVE_NAMES)
    for tok in requested:
        if tok not in known:
            logger.warning("active_sleeves: ignoring unknown sleeve %r (not in SLEEVE_NAMES)", tok)
    selected = {tok for tok in requested if tok in known}
    if not selected:
        logger.warning(
            "active_sleeves: PAPER_SLEEVES=%r had no known sleeves; falling back to all", raw
        )
        return SLEEVE_NAMES
    return tuple(name for name in SLEEVE_NAMES if name in selected)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest src/paper_trading/test_sleeves.py -q`
Expected: PASS (all, including the pre-existing sleeve tests).

- [ ] **Step 5: black + commit**

```bash
C:\Users\Jerry\anaconda3\python.exe -m black src/paper_trading/sleeves.py src/paper_trading/test_sleeves.py
git add src/paper_trading/sleeves.py src/paper_trading/test_sleeves.py
git commit -m "feat(paper-trading): PAPER_SLEEVES env gate (active_sleeves) for unattended runs"
```

---

## Task 2: `run_once` iterates `active_sleeves()` + fly.toml env

**Files:**
- Modify: `src/paper_trading/run.py` (import on line 41; loop on line ~192)
- Modify: `fly.toml` (`[env]` block)
- Test: `src/paper_trading/test_run_active_sleeves.py` (create)

- [ ] **Step 1: Write the failing test** — create `src/paper_trading/test_run_active_sleeves.py`. It reuses the offline scaffolding pattern from `src/paper_trading/test_smoke.py` (scratch SQLite via `app.backend.database` test engine + stub seams). Read `test_smoke.py` first and lift its session/seam fixture; the new assertion is the sleeve set:

```python
"""run_once honors the PAPER_SLEEVES gate (offline)."""
import pytest

from src.paper_trading import run as run_mod


def test_run_once_only_runs_active_sleeves(monkeypatch, paper_session):
    """With PAPER_SLEEVES set to a 2-sleeve subset, run_once touches only those.

    `paper_session` is the scratch-SQLite session fixture from test_smoke.py
    (copy it into this module or a shared conftest). Seams are no-op stubs:
    the scan returns nothing, the agent/factor return nothing, prices are empty
    — every sleeve collapses to "no conviction", which is enough to prove the
    ITERATION SET without needing live data.
    """
    monkeypatch.setenv("PAPER_SLEEVES", "spy_benchmark,scanner_only")

    def run_scan_fn(scan_date, top_n):
        return []

    def agent_fn(tickers, scan_date):
        return {}

    def factor_fn(scan_date):
        return []

    def price_fn(ticker):
        return 100.0  # priceable so spy_benchmark can seed SPY

    summaries = run_mod.run_once(
        session=paper_session,
        run_scan_fn=run_scan_fn,
        agent_fn=agent_fn,
        factor_fn=factor_fn,
        price_fn=price_fn,
        scan_date="2026-06-10",
        week_key="2026-W24",
    )

    assert set(summaries.keys()) == {"spy_benchmark", "scanner_only"}
    # factor_evolved (and the agent sleeves) must NOT have been run/seeded
    from app.backend.database.models import PaperSleeve

    seeded = {s.name for s in paper_session.query(PaperSleeve).all()}
    assert "factor_evolved" not in seeded
```

> **Scaffolding note (not a placeholder):** copy the `paper_session` fixture verbatim from `test_smoke.py` (the scratch-DB setup that creates the paper tables). If `test_smoke.py` builds the DB inline rather than via a fixture, extract that setup into a `@pytest.fixture` named `paper_session` in this file. Do not invent a new DB layer.

- [ ] **Step 2: Run the test to verify it fails**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest src/paper_trading/test_run_active_sleeves.py -q`
Expected: FAIL — `run_once` still iterates all 5 `SLEEVE_NAMES`, so `summaries` has 5 keys (assert on the 2-key set fails).

- [ ] **Step 3: Make `run_once` iterate `active_sleeves()`** — in `src/paper_trading/run.py`:

Change the import on line 41 from:
```python
from .sleeves import SLEEVE_NAMES, compute_targets  # noqa: E402
```
to:
```python
from .sleeves import active_sleeves, compute_targets  # noqa: E402
```

Change the loop (line ~192) from:
```python
        for sleeve_name in SLEEVE_NAMES:
```
to:
```python
        for sleeve_name in active_sleeves():
```

(`SLEEVE_NAMES` has no other use in `run.py`, so removing it from the import leaves no orphan. Verify with `grep -n SLEEVE_NAMES src/paper_trading/run.py` → no matches after the edit.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest src/paper_trading/test_run_active_sleeves.py -q`
Expected: PASS.

- [ ] **Step 5: Add `PAPER_SLEEVES` to fly.toml** — in `fly.toml`, inside the existing `[env]` block (after the `FRONTEND_BASE_URL` line), add:

```toml
  PAPER_SLEEVES = "scanner_agent,scanner_only,spy_benchmark,scanner_agent_flow"  # 4 light sleeves; factor_evolved excluded until B+C speeds its bundle build
```

- [ ] **Step 6: Full paper-trading suite green (no regressions)**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest src/paper_trading/ -q`
Expected: PASS (the prior 75 + the new tests).

- [ ] **Step 7: black + commit**

```bash
C:\Users\Jerry\anaconda3\python.exe -m black src/paper_trading/run.py src/paper_trading/test_run_active_sleeves.py
git add src/paper_trading/run.py src/paper_trading/test_run_active_sleeves.py fly.toml
git commit -m "feat(paper-trading): run_once honors PAPER_SLEEVES; exclude factor_evolved on prod via fly.toml"
```

---

## Task 3: Pre-flight (🟦 CLAUDE-RUN) — green suite + no-alpaca import guard

No code change. Verifies the deploy won't ship a broken or alpaca-dependent boot path.

- [ ] **Step 1: Full paper-trading + self-evolve suites green**

Run: `PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -m pytest src/paper_trading/ v2/self_evolve/ -q`
Expected: PASS (all). If any fail, STOP — do not proceed to deploy.

- [ ] **Step 2: Verify the scheduler's paper-job import path does NOT drag alpaca** (prod image has no `alpaca-py`):

Run:
```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=C:\Users\Jerry\Desktop\ai-hedge-fund C:\Users\Jerry\anaconda3\python.exe -c "import sys; from src.paper_trading.run import paper_weekly_job, paper_daily_marks_job; bad=sorted(m for m in sys.modules if 'alpaca' in m.lower()); print('ALPACA MODULES:', bad); assert not bad, bad; print('OK: no alpaca at import')"
```
Expected: `ALPACA MODULES: []` then `OK: no alpaca at import` (exit 0). If alpaca appears, STOP — the lazy-import guard regressed and prod boot would crash.

- [ ] **Step 3: Confirm the scheduler registers the paper jobs** (static check, no run):

Run: `grep -n "paper_weekly\|paper_daily_marks\|_register_paper_trading_jobs" app/backend/services/scheduler_service.py`
Expected: shows `_register_paper_trading_jobs` defined + called, and both job IDs registered with `America/New_York` triggers. (No change; this is the go/no-go confirmation.)

---

## Task 4: 🟥 USER-RUN — push main to origin

> All Task 4–10 commands are run by the **USER** in-session with a leading `!` (e.g. `!git push origin main`) so output lands in the conversation. Claude interprets each before the next.

- [ ] **Step 1: Push the 23 commits**

`!git push origin main`
Expected: pushes to `origin/main` without error (also the overdue backup). If rejected (non-fast-forward), STOP and report — do not force-push.

---

## Task 5: 🟥 USER-RUN — confirm prod secrets

- [ ] **Step 1: List secrets (names only; values are never shown)**

`!fly secrets list -a quantlab`
Expected: a table of secret NAMES. Claude checks for `DEEPSEEK_API_KEY` and at least one data-provider key (`EODHD_API_KEY` or `FINNHUB_API_KEY`), plus the existing `JWT_SECRET` / `APP_ENCRYPTION_KEY`.

- [ ] **Step 2: Set any missing key** (only if absent; Claude supplies the exact command; the user pastes the real value — never echoed/committed). Example shape:

`!fly secrets set DEEPSEEK_API_KEY=<paste-value> -a quantlab`
Expected: "Secrets are staged for the next deployment" (or a release if the app is running). Setting a secret triggers a machine restart — acceptable here since we deploy next anyway.

---

## Task 6: 🟥 USER-RUN — pre-deploy volume snapshot (insurance)

- [ ] **Step 1: Find the volume id**

`!fly volumes list -a quantlab`
Expected: one volume named `data` mounted at `/data`; note its id (e.g. `vol_xxxxxxxx`).

- [ ] **Step 2: Snapshot it**

`!fly volumes snapshots create <vol-id>`
Expected: confirms a snapshot was created. This is the DB rollback point.

---

## Task 7: 🟥 USER-RUN — deploy

- [ ] **Step 1: Deploy from current main**

`!fly deploy -a quantlab`
Expected (takes a few minutes): the image builds (frontend + backend), then on the machine the entrypoint runs `alembic upgrade head` (applies the paper-trading migration to `/data/app.db`), then uvicorn boots. Watch for a green release. If the build or release fails, STOP — go to Task 10 (rollback) and report the error.

---

## Task 8: 🟥 USER-RUN — verify boot

- [ ] **Step 1: Tail boot logs**

`!fly logs -a quantlab`
Expected, Claude confirms ALL of:
- `Registered cron job paper_weekly with expression ... (timezone=America/New_York)`
- `Registered cron job paper_daily_marks with expression ... (timezone=America/New_York)`
- no startup traceback from the scheduler; the app reaches "Application startup complete".

- [ ] **Step 2: Health check**

`!curl -s -o /dev/null -w "%{http_code}" https://quantlab.fly.dev/health`
Expected: `200`.

---

## Task 9: 🟥 USER-RUN — seed now + verify accrual

- [ ] **Step 1: Seed this week immediately (don't wait for Monday's cron)**

`!fly ssh console -a quantlab -C "python -m src.paper_trading.run --once --marks"`
Expected: per-sleeve lines for the **4** light sleeves (entered/exited/n_orders/cash) + "marked 4 sleeves". `factor_evolved` must be ABSENT. If a sleeve prints `ERROR ...`, Claude reads it (most likely a missing key → fix via Task 5 and re-run this step).

- [ ] **Step 2: Report — confirm prod is accruing**

`!fly ssh console -a quantlab -C "python -m src.paper_trading.run --report"`
Expected: a summary listing exactly the 4 sleeves, each with positions (except `spy_benchmark` = SPY) + an equity row dated today. **Definition of done for the seed.**

- [ ] **Step 3 (next day, optional): confirm the unattended daily-marks cron fired**

`!fly ssh console -a quantlab -C "python -m src.paper_trading.run --report"`
Expected: a SECOND daily equity mark per sleeve (dated the following weekday), proving the `paper_daily_marks` cron runs without manual intervention. This is the ultimate "unattended" proof.

---

## Task 10: Rollback (🟥 USER-RUN — only if a prior task failed)

- [ ] **App won't boot / bad release:**

`!fly releases -a quantlab` (find the prior good version), then `!fly releases rollback -a quantlab`
Expected: the previous image is restored within seconds; the live app is back. The new code is additive, so a rollback loses only the forward test, not user data.

- [ ] **DB migration corruption:** restore the Task 6 snapshot:

`!fly volumes snapshots list <vol-id>` then follow Fly's restore flow (create a new volume from the snapshot, swap the mount). Claude walks the user through it if needed.

- [ ] **Scheduler-only error (API healthy):** no rollback needed — `main.py` isolates a scheduler failure (the API stays up). Fix forward in a follow-up deploy.

---

## Self-Review (against the spec)

- **Spec coverage:** the one code change (`active_sleeves()` + `run_once` + `fly.toml`) → Tasks 1–2; pre-flight (suite green + no-alpaca) → Task 3; runbook (push/secrets/snapshot/deploy/logs/seed/report) → Tasks 4–9; rollback → Task 10; observability v1 (`--report`) → Task 9 Step 2; factor_evolved exclusion → Tasks 1–2 + verified in Task 9. All spec sections map to a task.
- **Placeholder scan:** the only `<...>` are runtime values the user fills (`<vol-id>`, `<paste-value>`) — legitimate command templates, not unfinished spec. The `paper_session` fixture is explicitly sourced from `test_smoke.py` (reuse, not invent).
- **Type/name consistency:** `active_sleeves` (Task 1) is imported + iterated identically in Task 2; `PAPER_SLEEVES` env name is identical in code, tests, and `fly.toml`; the 4-sleeve list is byte-identical in `fly.toml` (Task 2 Step 5) and the Task 9 expected output.

## Execution Handoff

Tasks 1–3 are CLAUDE-RUN (code + pre-flight). Tasks 4–10 are USER-RUN (outward `fly`/`git`). Recommended: subagent-driven-development for Tasks 1–2 (code), then Claude runs Task 3, then Claude hands the user the Task 4–9 commands one at a time and interprets each output before the next.
