# Detector Invariant Test Suite — Design

**Date**: 2026-05-21
**Status**: design approved, awaiting plan
**Author**: brainstorming session with user

## Context

`CLAUDE.md` declares four load-bearing invariants for `v2/scanner/detectors/*.py`:

1. Every z-score has a real std floor (not the `arr.std() or 1e-6` anti-pattern, which only fires when std is **exactly** 0.0 — the bug that produced the documented GEHC z=+55 trillion).
2. Signals never raise — return a sentinel result instead.
3. Detectors return `None` for "no data" vs `EventTrigger(triggered=False)` for "ran cleanly, didn't fire" — these are semantically distinct in downstream stats.
4. Per-worker `DataClient` is mandatory — `requests.Session` is not thread-safe; the runner pools clients via `queue.Queue`.

Today these are enforced by human review. With 10 detectors and growing complexity (one detector — `analyst_rating.py` — already swallows exceptions on two paths with no logging), we need automated enforcement so the invariants stop drifting silently.

## Goals

- Codify 8 invariant rules (the 4 CLAUDE.md ones plus 4 observable best-practices) as pytest tests.
- Make violations point to file:line so fixes are trivial to apply.
- Fix all existing violations as part of landing this so the test ships green.

## Non-goals

- Auto-fix. Every violation needs human judgment.
- Linting `v2/signals/` (different contract — `BaseSignal`, not `EventDetector`).
- Replacing `v2/scanner/test_detectors.py` (behavioral tests, complementary).
- Pre-commit hook (pytest catches it; one less config to maintain).

## Architecture

Single test file: `tests/test_detector_invariants.py`.

Each invariant is one `@pytest.mark.parametrize` test function, parameterized over every detector file in `v2/scanner/detectors/` (excluding `__init__.py`, `base.py`). On failure the assertion message includes `path:line — RULE-N (description)`.

Three checking techniques mixed by rule:

| Technique | Used for | Why |
|---|---|---|
| AST walk (`ast` module) | Rules 1, 3, 4, 5, 7 | Structural checks need real syntax tree |
| Runtime introspection (`importlib` + `inspect`) | Rules 6, 8 | Class attributes and signatures live on the class object |
| Source regex | Rule 2 (cheap pre-scan) | Forbidden pattern is a literal substring; AST confirmation is cheap follow-up |

## Rule catalog

| # | Rule | Detection | Severity |
|---|---|---|---|
| 1 | Every `.std()` / `.std(ddof=…)` call's result has a `max(...)` call somewhere in its AST ancestor chain within the same function (heuristic for floor-application) | AST: scan `Call` nodes where `.func.attr == "std"`, walk parent chain; require a `Call(func=Name(id="max"))` ancestor before reaching `FunctionDef`. False-positives suppressible with `# noqa: std-floor` on the line | ERROR |
| 2 | The forbidden `float(...) or NUMBER` and `(... .std()) or NUMBER` patterns do not appear | regex first (`r"\bstd\([^)]*\)\s*or\s"` and `r"or\s+\d+e-?\d+"`); AST confirms it's an `or` short-circuit, not a comment | ERROR |
| 3 | Every assignment to `components[...]` or `components.update({...})` has a `float(...)` call or float literal as RHS | AST: find `Subscript` assignments with `components` target; check `value` is `Call(func=Name(id="float"))` or `Constant(value=float)` | ERROR |
| 4 | No statement of form `self.<ANY> = fd` inside `detect()` (single-method check sufficient — class-body access to `fd` is impossible since it's a method param) | AST: in `detect` body, no `Assign(targets=[Attribute(value=Name(id="self"))], value=Name(id="fd"))` | ERROR |
| 5 | Any `except Exception:` block contains either a `logger.*` call (warning/error/exception) OR a `raise` statement (re-raise / re-raise as different exception is acceptable) | AST: walk `ExceptHandler` whose type is `Name(id="Exception")`; require either a `Call(func=Attribute(value=Name(id="logger"), ...))` OR a `Raise` node in the body | WARNING (still test-fail) |
| 6 | `name` class attribute is a non-empty string, not `"base"`, and unique across all detectors | introspect: import each module, collect `EventDetector` subclasses, assert no dupes | ERROR |
| 7 | When `EventTrigger(direction=...)` is given a string-literal value, it must be one of `"bullish"`, `"bearish"`, `"neutral"`. Variable references and conditional expressions skipped (best-effort static check) | AST: find `Call(func=Name(id="EventTrigger"))`; for each `direction=` keyword whose value is `Constant`, require value in the allowed set | ERROR |
| 8 | `detect` method's return annotation is `EventTrigger | None` (or equivalent `Optional[EventTrigger]`) | introspect: `inspect.signature(cls.detect).return_annotation` | ERROR |

## Test organization

```python
DETECTOR_DIR = Path("v2/scanner/detectors")
DETECTOR_FILES = sorted(
    p for p in DETECTOR_DIR.glob("*.py")
    if p.name not in {"__init__.py", "base.py"}
)

@pytest.mark.parametrize("path", DETECTOR_FILES, ids=lambda p: p.stem)
def test_std_floor_wrapping(path: Path) -> None:
    violations = scan_std_floor_wrapping(path)
    assert not violations, format_violations(path, violations)

@pytest.mark.parametrize("path", DETECTOR_FILES, ids=lambda p: p.stem)
def test_components_dict_all_float(path: Path) -> None:
    ...

# 8 such tests total
```

Helper module: place the AST visitors and runtime checks in `tests/_detector_lint.py` (private helper, prefix underscore so pytest doesn't collect). One `Violation` dataclass with `(line, rule_id, message)` fields. One `format_violations(path, violations)` for assertion messages.

## Expected violations (preliminary)

From a quick look at `analyst_rating.py`:

- `:103` — bare `except Exception:` swallows actions fetch (RULE-5)
- `:110` — bare `except Exception:` swallows targets fetch (RULE-5)

Other 9 detectors not yet scanned. Conservative estimate: 5–15 total violations. Most likely:
- More bare `except Exception:` swallows (RULE-5)
- A few components values not explicitly cast to `float()` (RULE-3) — e.g. when a numpy scalar is written directly
- Maybe one or two missing return type annotations (RULE-8)

The "old GEHC bug" std anti-pattern (RULE-2) was supposedly already fixed across the board — RULE-2 should find zero. If it finds something, that's the highest-value catch.

## Fix workflow

1. Build linter test file (no enforcement yet — use `pytest.skip` decorator initially)
2. Remove the skip, run `pytest tests/test_detector_invariants.py -v` → full violation list
3. Fix each violation, re-run after each fix
4. Final commit: linter + all fixes together; test is green

Failure mode protection: if the existing `v2/scanner/test_detectors.py` (1743 LoC, behavioral tests) starts failing after the fixes, that's a real regression — investigate before forcing through.

## Risks

| Risk | Mitigation |
|---|---|
| False positives on RULE-1 (std-floor) for non-z-score uses of `.std()` (e.g., volatility computation that's not a z-score) | Allowlist via inline comment `# noqa: std-floor` recognized by the AST walker; document in the lint helper docstring |
| False positives on RULE-7 (direction literal) when direction is computed from a complex expression | The check already permits Name references; only literal Strings outside the allowed set trigger |
| Test execution speed | All 8 tests × 10 detectors = 80 cases, all pure AST/regex (no I/O). Should run in <1s |
| `tests/_detector_lint.py` private helper might be collected by pytest if convention varies | Use the leading underscore in the filename; verify with `pytest --collect-only` after creation |

## Verification

```powershell
# After implementing the linter (with violations to fix)
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/test_detector_invariants.py -v
# Expect: 8 tests, several parametrized cases failing with clear messages

# After all fixes
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/test_detector_invariants.py -v
# Expect: all green

# Full suite still passes (no regression from fixes)
C:\Users\Jerry\anaconda3\python.exe -m pytest -q
# Expect: same pass count as before, plus the new invariant tests
```

## Out of scope (future)

- Lint v2/signals (BaseSignal contract is different — return SignalResult always, never None)
- Lint the scanner runner / scoring layer for the per-worker DataClient invariant (RULE-4 is detector-side only; runner-side enforcement is a separate concern)
- Pre-commit hook (skipped per user choice — pytest is the canonical gate)
- Performance test asserting all 10 detectors run inside a budget (different concern, separate spec)
