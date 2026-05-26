# CLAUDE.md

Behavioral guidelines + project-specific invariants for Claude sessions on this repo.

---

## Project Invariants (read first)

These are the hard rules for working on this codebase. Skip these and things break.

### Environment

- **Python interpreter**: `C:\Users\Jerry\anaconda3\python.exe`. Poetry is NOT on PATH — invoke anaconda Python directly. Never assume `python`/`poetry` resolves correctly.
- **Shell**: Windows PowerShell. For colored CLI output (logs, progress bars, ANSI), prefix with `$env:PYTHONIOENCODING="utf-8"` or set it inline.
- **Bash is also available** via the Bash tool for POSIX scripts — use it when shelling out to `pytest`, `grep`, etc.
- **OS-specific paths**: prefer absolute paths over relative for any tool input.

### Running the dev servers

- **Backend**: `uvicorn app.backend.main:app --host 127.0.0.1 --port 8001 --log-level info` from repo root. Set `PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1` so logs flush in real time.
- **Frontend**: `npm run dev` from `app/frontend/`. Reads `app/frontend/.env.local` for `VITE_API_URL` (currently `http://localhost:8001`).

### Windows uvicorn gotchas (load-bearing)

- **Do NOT use `--reload`** in this environment. Two reasons:
  1. The reloader's parent process buffers child stdout — `INFO: 127.0.0.1:xxxx - "POST..."` request logs never appear, making it impossible to debug what the running server is doing. Plain uvicorn flushes them immediately.
  2. On Windows, force-killing the parent leaks the child's listening socket. After 5+ kill/restart cycles you end up with 5 dead PIDs still bound to the port. Windows won't release them without a reboot.
- **If the listener port leaks**: don't fight it. Switch to the next port (8001 → 8002 etc.) and update `app/frontend/.env.local` to match. Faster than waiting for Windows to clean up.

### Secrets

- **API keys live ONLY in `.env`**, which is gitignored. Never commit `.env`.
- Known keys you may use in tests: `FINANCIAL_DATASETS_API_KEY`, `FINNHUB_API_KEY`, `EODHD_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `FRED_API_KEY`.
- Never echo or log API keys.

### Scanner Pipeline Invariants

These are load-bearing — violating them produces wrong results (sometimes silently):

1. **Every z-score has a std floor.** Patterns like `sigma = float(arr.std()) or 1e-6` are forbidden — they only fire the fallback when std is *exactly* 0.0, missing the "collapsed but nonzero" case that produced GEHC z=+55,257,210,785,000. Use a real floor (e.g. `max(mean * 0.10, $1000)`) and fall back to a categorical magnitude when below it. Documented per-detector in `v2/scanner/README.md`.
2. **Signals NEVER raise.** On missing/insufficient data, return `SignalResult(value=0.0, metadata={"reason": "..."})`. The runner isolates per-signal exceptions anyway, but a raise is a bug to investigate, not a feature.
3. **Detectors return `None` vs `EventTrigger(triggered=False)` for distinct cases.** `None` = "no data, exclude this ticker entirely." `EventTrigger(triggered=False)` = "ran cleanly, just didn't fire — keep the ticker in stats."
4. **Per-worker `DataClient` is mandatory** — `requests.Session` is not thread-safe across threads. The runner pools clients via `queue.Queue`. Don't memoize a single client as a module-level singleton.

### Workflow

- **After completing each task, use the `planning-with-files` skill to update `progress.md`**. Don't batch progress updates — write them per-task so the log reflects actual work history, not after-the-fact reconstruction.
- Active source-of-truth files at repo root: `progress.md`, `task_plan.md`, `findings.md`. Read these when resuming a session.

---

## Behavioral Guidelines

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
