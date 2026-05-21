# Detector Invariant Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Codify the four CLAUDE.md detector invariants plus four observable best-practices as eight pytest tests, then fix every existing violation so the test ships green.

**Architecture:** Single test file `tests/test_detector_invariants.py` with one parameterized test per rule, plus a private helper `tests/_detector_lint.py` holding the AST visitors and introspection scanners. Pre-scan has already identified 6 likely violations across `analyst_rating.py`, `bollinger_squeeze.py`, and `earnings.py`. After implementing each rule we run it against all 10 detectors and patch what it finds.

**Tech Stack:** Python `ast` module, `importlib`, `inspect`, pytest with `@pytest.mark.parametrize`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-21-detector-invariant-tests-design.md`

**Detector files in scope** (10 total — exclude `__init__.py`, `base.py`):
- `v2/scanner/detectors/analyst_rating.py`
- `v2/scanner/detectors/bollinger_squeeze.py`
- `v2/scanner/detectors/earnings.py`
- `v2/scanner/detectors/earnings_upcoming.py`
- `v2/scanner/detectors/insider.py`
- `v2/scanner/detectors/intraday_move.py`
- `v2/scanner/detectors/news_sentiment.py`
- `v2/scanner/detectors/obv_divergence.py`
- `v2/scanner/detectors/target_price_change.py`
- `v2/scanner/detectors/volume_anomaly.py`

---

## Task 1: Scaffold the helper module + empty test file

**Files:**
- Create: `tests/_detector_lint.py`
- Create: `tests/test_detector_invariants.py`

- [ ] **Step 1: Create the helper module skeleton**

Write `tests/_detector_lint.py`:

```python
"""Private helper for tests/test_detector_invariants.py.

Filename starts with ``_`` so pytest's default test-discovery glob
(``test_*.py`` / ``*_test.py``) skips it; only the public test file
imports from here.

Holds:
  * ``Violation`` dataclass for uniform reporting.
  * ``DETECTOR_FILES`` constant — the parameterize target.
  * ``scan_*`` functions, one per RULE-N from the spec.
  * ``attach_parents`` AST helper since the stdlib ast module doesn't
    populate ``.parent`` automatically.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_DETECTOR_DIR = Path(__file__).resolve().parent.parent / "v2" / "scanner" / "detectors"

DETECTOR_FILES: list[Path] = sorted(
    p for p in _DETECTOR_DIR.glob("*.py")
    if p.name not in {"__init__.py", "base.py"}
)


@dataclass
class Violation:
    """One rule-violation finding in one detector file."""

    rule: str       # e.g. "RULE-5"
    line: int       # 1-indexed source line
    message: str    # short human-readable description


def attach_parents(tree: ast.AST) -> None:
    """Mutate ``tree`` so every node has a ``.parent`` attribute.

    stdlib ast doesn't track parents; we add them once per parse so
    the scan_* functions can walk upward through the tree.
    """
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]


def format_violations(path: Path, violations: list[Violation]) -> str:
    """Render a list of violations into a pytest assertion message.

    Returns an empty string when there are no violations — caller can
    use this in an assert: ``assert not violations, format_violations(path, violations)``.
    """
    if not violations:
        return ""
    head = f"\n{path} has {len(violations)} invariant violation(s):"
    body = "\n".join(
        f"  {path}:{v.line} {v.rule} {v.message}"
        for v in violations
    )
    return f"{head}\n{body}"
```

- [ ] **Step 2: Create the empty test file**

Write `tests/test_detector_invariants.py`:

```python
"""Static-analysis tests for v2/scanner/detectors/*.py.

Enforces the four load-bearing invariants from CLAUDE.md plus four
observable best-practices. See docs/superpowers/specs/2026-05-21-
detector-invariant-tests-design.md for the rule catalog.

Each rule is one parameterized test; the parameter is the detector
file path. Failure message points to file:line so fixes are trivial.
"""

from __future__ import annotations

import pytest

from tests._detector_lint import DETECTOR_FILES


def _ids(path):
    return path.stem


def test_detector_files_discovered():
    """Sanity: parameterize target is non-empty so missing-files bugs
    don't masquerade as passing tests with zero cases.
    """
    assert len(DETECTOR_FILES) >= 10, (
        f"expected at least 10 detector files in v2/scanner/detectors/, "
        f"got {len(DETECTOR_FILES)}: {[p.name for p in DETECTOR_FILES]}"
    )
```

- [ ] **Step 3: Verify pytest collects test file but skips helper**

Run:

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py --collect-only -q
```

Expected output: shows `tests/test_detector_invariants.py::test_detector_files_discovered` and nothing from `_detector_lint.py`.

Also run:

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: 1 test passes (`test_detector_files_discovered`).

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py
git commit -m "test(scanner): scaffold detector invariant test suite

Empty test file + private helper module for the eight rules spec'd in
docs/superpowers/specs/2026-05-21-detector-invariant-tests-design.md.
Per-rule scan functions and parameterized tests land in subsequent
commits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: RULE-2 — forbidden std-fallback patterns

**Why first:** Expected to find ZERO violations (the GEHC bug was already cleaned up). Fastest win, validates the test infrastructure.

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_forbidden_std_pattern`)
- Modify: `tests/test_detector_invariants.py` (add `test_forbidden_std_pattern`)

- [ ] **Step 1: Add scan function to helper**

Append to `tests/_detector_lint.py`:

```python
import re

_FORBIDDEN_STD_PATTERNS = (
    # `(... .std(...)) or NUMBER` short-circuit
    re.compile(r"\.std\([^)]*\)\s*\)?\s*or\s+\d"),
    # `float(...) or 1e-N` style
    re.compile(r"float\([^)]*\)\s*or\s+\d+e-?\d+"),
)


def scan_forbidden_std_pattern(path: Path) -> list[Violation]:
    """RULE-2: forbidden `... .std(...) or NUMBER` fallback pattern.

    The bug: ``sigma = float(arr.std()) or 1e-6`` only triggers when
    ``arr.std()`` is **exactly** 0.0. Any tiny-but-nonzero std slips
    through and divides into a z-score, producing the catastrophic
    blow-ups documented in v2/scanner/README.md (GEHC z = +55 trillion).
    """
    violations: list[Violation] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Skip comment lines so the rule's own docstring example doesn't
        # match itself.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for pat in _FORBIDDEN_STD_PATTERNS:
            if pat.search(line):
                violations.append(Violation(
                    rule="RULE-2",
                    line=lineno,
                    message="forbidden std `or NUMBER` short-circuit fallback",
                ))
                break
    return violations
```

- [ ] **Step 2: Add parameterized test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import (
    DETECTOR_FILES,
    format_violations,
    scan_forbidden_std_pattern,
)


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_no_forbidden_std_pattern(path):
    """RULE-2: no `... .std(...) or NUMBER` fallback patterns."""
    violations = scan_forbidden_std_pattern(path)
    assert not violations, format_violations(path, violations)
```

Update the imports block at the top:

```python
from tests._detector_lint import (
    DETECTOR_FILES,
    format_violations,
    scan_forbidden_std_pattern,
)
```

- [ ] **Step 3: Run and verify all green**

Run:

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: 11 tests pass (1 sanity + 10 parametrized per detector).

If any violations are found here, that's a surprise — investigate the offending file before continuing (the spec assumes RULE-2 finds nothing).

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py
git commit -m "test(scanner): RULE-2 forbidden std fallback pattern

Reject the \`... .std(...) or NUMBER\` short-circuit that produced
the GEHC z = +55 trillion outlier. Current trunk is clean — no
detector files violate the rule.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: RULE-6 — detector `name` attribute is unique and not 'base'

**Why next:** Pure introspection, no AST. Validates the import-detector-modules path that later rules will reuse.

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_detector_names`)
- Modify: `tests/test_detector_invariants.py` (add `test_detector_names_unique`)

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
import importlib
import inspect


def _import_detector_module(path: Path):
    """Import the detector module at ``path`` and return the module object.

    Uses the canonical dotted name (``v2.scanner.detectors.<stem>``) so
    the import shares state with the rest of the test suite — avoids
    reimporting under a synthetic name that would create duplicate
    class objects.
    """
    module_name = f"v2.scanner.detectors.{path.stem}"
    return importlib.import_module(module_name)


def _detector_subclasses(module) -> list[type]:
    """Return every concrete EventDetector subclass defined in ``module``.

    Filters by ``__module__`` equality to skip re-exported imports.
    """
    from v2.scanner.detectors.base import EventDetector  # local: avoid import cycle at module load
    out: list[type] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if not issubclass(obj, EventDetector) or obj is EventDetector:
            continue
        if obj.__module__ != module.__name__:
            continue
        out.append(obj)
    return out


def scan_detector_name_attribute(path: Path) -> list[Violation]:
    """RULE-6: every detector defines a non-empty, non-'base' ``name``
    class attribute.
    """
    module = _import_detector_module(path)
    classes = _detector_subclasses(module)
    violations: list[Violation] = []
    for cls in classes:
        name = getattr(cls, "name", None)
        line = inspect.getsourcelines(cls)[1]
        if not isinstance(name, str) or not name:
            violations.append(Violation(
                rule="RULE-6",
                line=line,
                message=f"{cls.__name__}.name is missing or empty",
            ))
        elif name == "base":
            violations.append(Violation(
                rule="RULE-6",
                line=line,
                message=f"{cls.__name__}.name is 'base' — must override the ABC default",
            ))
    return violations


def collect_all_detector_names() -> dict[str, list[str]]:
    """Cross-file check: returns a {name -> [class_repr...]} dict for any
    name shared across two or more detector classes. Empty when unique.
    """
    seen: dict[str, list[str]] = {}
    for path in DETECTOR_FILES:
        module = _import_detector_module(path)
        for cls in _detector_subclasses(module):
            name = getattr(cls, "name", None)
            if not isinstance(name, str) or not name or name == "base":
                continue
            seen.setdefault(name, []).append(f"{path.stem}.{cls.__name__}")
    return {k: v for k, v in seen.items() if len(v) >= 2}
```

- [ ] **Step 2: Add tests**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import (
    collect_all_detector_names,
    scan_detector_name_attribute,
)


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_detector_name_attribute(path):
    """RULE-6 (per-file): detector class has a non-empty ``name`` that
    isn't the ABC default 'base'.
    """
    violations = scan_detector_name_attribute(path)
    assert not violations, format_violations(path, violations)


def test_detector_names_are_unique_across_files():
    """RULE-6 (cross-file): no two detector classes share a ``name``.

    Aliasing happens via scanner config rewriting (e.g. legacy
    ``earnings_surprise`` → ``earnings_event`` per the memory note),
    NOT via duplicate class names — that would break the scoring
    weight lookup which is keyed on ``name``.
    """
    duplicates = collect_all_detector_names()
    assert not duplicates, (
        "Detector name collision detected:\n  "
        + "\n  ".join(f"{name}: {classes}" for name, classes in duplicates.items())
    )
```

Update the imports at the top of `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import (
    DETECTOR_FILES,
    collect_all_detector_names,
    format_violations,
    scan_detector_name_attribute,
    scan_forbidden_std_pattern,
)
```

- [ ] **Step 3: Run and verify green**

Run:

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: 22 tests pass (1 sanity + 10 RULE-2 + 10 RULE-6 per-file + 1 RULE-6 cross-file).

If a name collision turns up, that's a real bug — fix by renaming the dupe (likely a copy-paste oversight).

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py
git commit -m "test(scanner): RULE-6 detector name attribute checks

Per-file: name is a non-empty string and not the 'base' ABC default.
Cross-file: no two detector classes share a name (scoring weights are
keyed on name; collision is silent miscount).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: RULE-8 — `detect()` return type annotation

**Why next:** Pure introspection, builds on Task 3's module-import path.

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_detect_return_annotation`)
- Modify: `tests/test_detector_invariants.py` (add `test_detect_return_annotation`)

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
import typing


def _annotation_is_event_trigger_or_none(annotation) -> bool:
    """Return True when ``annotation`` describes ``EventTrigger | None``
    in any of the accepted spellings:

      * ``EventTrigger | None`` (PEP 604, our standard)
      * ``Optional[EventTrigger]`` (legacy typing)
      * ``Union[EventTrigger, None]`` (also legacy)

    The annotation we receive is whatever ``inspect.signature(...)``
    returns. With ``from __future__ import annotations`` (used in every
    detector), that's a string we have to parse via ``typing.get_type_hints``
    on the owning class — but the scanner takes the parsed result and
    inspects ``__origin__`` and ``__args__`` to be language-spelling
    agnostic.
    """
    if annotation is type(None):
        return False
    args = typing.get_args(annotation)
    if not args:
        return False
    # Both UnionType (PEP 604) and Optional resolve to a tuple of args.
    arg_names = {getattr(a, "__name__", str(a)) for a in args}
    if "NoneType" not in arg_names and type(None) not in args:
        return False
    if "EventTrigger" not in arg_names:
        return False
    return True


def scan_detect_return_annotation(path: Path) -> list[Violation]:
    """RULE-8: ``detect()`` method's return annotation resolves to
    ``EventTrigger | None``.
    """
    module = _import_detector_module(path)
    classes = _detector_subclasses(module)
    violations: list[Violation] = []
    for cls in classes:
        if "detect" not in cls.__dict__:
            continue  # inherited from ABC; not the class under inspection
        try:
            hints = typing.get_type_hints(cls.detect)
        except Exception as e:
            violations.append(Violation(
                rule="RULE-8",
                line=inspect.getsourcelines(cls.detect)[1],
                message=f"{cls.__name__}.detect: cannot resolve type hints ({e})",
            ))
            continue
        ret = hints.get("return")
        if ret is None:
            violations.append(Violation(
                rule="RULE-8",
                line=inspect.getsourcelines(cls.detect)[1],
                message=f"{cls.__name__}.detect: missing return annotation",
            ))
            continue
        if not _annotation_is_event_trigger_or_none(ret):
            violations.append(Violation(
                rule="RULE-8",
                line=inspect.getsourcelines(cls.detect)[1],
                message=f"{cls.__name__}.detect: return type is {ret!r}, want EventTrigger | None",
            ))
    return violations
```

- [ ] **Step 2: Add test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import scan_detect_return_annotation


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_detect_return_annotation(path):
    """RULE-8: detect() return type is EventTrigger | None."""
    violations = scan_detect_return_annotation(path)
    assert not violations, format_violations(path, violations)
```

Update imports.

- [ ] **Step 3: Run and verify green (or fix violations)**

Run:

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: all green. If a detector is missing the `EventTrigger | None` annotation, fix the file by updating the signature, e.g.:

```python
def detect(
    self,
    ticker: str,
    end_date: str,
    fd: DataClient,
    *,
    ctx: ScanContext | None = None,
) -> EventTrigger | None:   # ← add or correct this
    ...
```

Re-run and confirm green before committing.

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py [any fixed detector files]
git commit -m "test(scanner): RULE-8 detect() return annotation

Every concrete EventDetector subclass must annotate detect() as
returning EventTrigger | None (or Optional[EventTrigger]). The None
case is the 'no data' contract; loose typing here hides bugs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: RULE-4 — `detect()` doesn't memoize the `fd` client

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_no_client_memoization`)
- Modify: `tests/test_detector_invariants.py` (add `test_no_client_memoization`)

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
def scan_no_client_memoization(path: Path) -> list[Violation]:
    """RULE-4: ``detect()`` does not stash the ``fd`` client on ``self``.

    Background: ``requests.Session`` (the underlying transport for the
    Finnhub / EODHD clients) is not thread-safe across worker threads.
    The runner gives each worker a dedicated client via queue.Queue.
    Memoizing ``self._client = fd`` would shred that isolation — the
    first thread's client survives into other threads' calls.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    attach_parents(tree)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "detect":
            continue
        for stmt in ast.walk(node):
            if not isinstance(stmt, ast.Assign):
                continue
            for target in stmt.targets:
                if not (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"):
                    continue
                if isinstance(stmt.value, ast.Name) and stmt.value.id == "fd":
                    violations.append(Violation(
                        rule="RULE-4",
                        line=stmt.lineno,
                        message=f"self.{target.attr} = fd memoizes a per-call client across threads",
                    ))
    return violations
```

- [ ] **Step 2: Add test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import scan_no_client_memoization


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_no_client_memoization(path):
    """RULE-4: detect() does not stash fd on self."""
    violations = scan_no_client_memoization(path)
    assert not violations, format_violations(path, violations)
```

Update imports.

- [ ] **Step 3: Run and verify green**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: all green. No detector should be doing this; if any are, that's a thread-safety bug — remove the `self._client = fd` assignment and use the parameter directly.

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py
git commit -m "test(scanner): RULE-4 no detect() client memoization

Forbid \`self._client = fd\` inside detect(): the runner hands a
per-thread client via queue.Queue and shared mutation breaks
requests.Session thread-safety.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: RULE-7 — `EventTrigger(direction=...)` literal value check

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_direction_literals`)
- Modify: `tests/test_detector_invariants.py` (add `test_direction_literals`)

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
_ALLOWED_DIRECTIONS = frozenset({"bullish", "bearish", "neutral"})


def scan_direction_literals(path: Path) -> list[Violation]:
    """RULE-7: every ``EventTrigger(direction=<literal>)`` uses a value
    in {"bullish","bearish","neutral"}.

    Non-literal direction values (Name references, conditional
    expressions) are skipped — best-effort static check. Catches the
    typo case: ``direction="bull"`` accepted silently by Pydantic
    only because Direction is a Literal that COULD have been laxer.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # EventTrigger(...) bare or via attribute chain — match the bare name
        called = node.func
        if not (isinstance(called, ast.Name) and called.id == "EventTrigger"):
            continue
        for kw in node.keywords:
            if kw.arg != "direction":
                continue
            if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                if kw.value.value not in _ALLOWED_DIRECTIONS:
                    violations.append(Violation(
                        rule="RULE-7",
                        line=kw.value.lineno,
                        message=f"direction={kw.value.value!r} not in {sorted(_ALLOWED_DIRECTIONS)}",
                    ))
    return violations
```

- [ ] **Step 2: Add test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import scan_direction_literals


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_direction_literals(path):
    """RULE-7: EventTrigger(direction=<literal>) is bullish/bearish/neutral."""
    violations = scan_direction_literals(path)
    assert not violations, format_violations(path, violations)
```

Update imports.

- [ ] **Step 3: Run and verify green**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: green. Any literal typo (e.g. `direction="bull"`) needs the literal corrected.

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py [any fixed files]
git commit -m "test(scanner): RULE-7 direction literal value check

EventTrigger(direction=<str-literal>) must be 'bullish' | 'bearish'
| 'neutral'. Non-literal direction values are skipped (best-effort
static check).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: RULE-3 — `components` dict values are all float

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_components_dict_float`)
- Modify: `tests/test_detector_invariants.py` (add `test_components_dict_float`)
- Possibly modify: detector files where a components value isn't float-cast

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
def _rhs_is_float_compatible(value: ast.AST) -> bool:
    """Return True when ``value`` is one of:
      * ``float(...)`` call
      * float literal (``Constant(value=float)``)
      * the literal ``0.0`` integer-typed constant (``Constant(value=0)``
        — covered because Python normalizes; explicit float typing
        preferred but we allow it to reduce noise)
      * conditional expression where both branches are float-compatible
      * tuple/list (handled by callers if used in updates with tuple)
    """
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name) and value.func.id == "float":
            return True
    if isinstance(value, ast.Constant):
        if isinstance(value.value, float):
            return True
        if value.value is True or value.value is False:  # bool subclass of int — explicit float-cast preferred
            return False
        if isinstance(value.value, int):
            # Allow integer literals (Python normalizes int → float on assign)
            # — bare ints are common for things like ``"history_n": 0``.
            return True
    if isinstance(value, ast.IfExp):
        return _rhs_is_float_compatible(value.body) and _rhs_is_float_compatible(value.orelse)
    return False


def scan_components_dict_float(path: Path) -> list[Violation]:
    """RULE-3: every assignment to ``components`` dict has a
    float-compatible RHS.

    Patterns we catch:
      * ``components["key"] = expr``          → expr must be float-compat
      * ``components = {"key": expr, ...}``   → each value must be float-compat
      * ``components.update({"key": expr})``  → each value must be float-compat

    Patterns we do NOT catch (false-negative — accept the gap):
      * ``components = some_dict_var``  (would need data-flow analysis)
      * ``components.update(some_dict_var)``
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    attach_parents(tree)
    violations: list[Violation] = []

    def _check_value(key_desc: str, value: ast.AST, lineno: int) -> None:
        if not _rhs_is_float_compatible(value):
            violations.append(Violation(
                rule="RULE-3",
                line=lineno,
                message=f"components{key_desc} = <non-float>",
            ))

    for node in ast.walk(tree):
        # Pattern: components["foo"] = expr
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Subscript)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "components"):
                    key_repr = ast.unparse(target.slice) if hasattr(ast, "unparse") else "[...]"
                    _check_value(f"[{key_repr}]", node.value, node.lineno)
            # Pattern: components = {"foo": expr, ...}
            if (len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "components"
                    and isinstance(node.value, ast.Dict)):
                for k, v in zip(node.value.keys, node.value.values):
                    key_repr = (k.value if isinstance(k, ast.Constant) else "?")
                    _check_value(f"[{key_repr!r}]", v, v.lineno)
        # Pattern: components.update({"foo": expr})
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "update"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "components"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Dict)):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                key_repr = (k.value if isinstance(k, ast.Constant) else "?")
                _check_value(f"[{key_repr!r}]", v, v.lineno)
    return violations
```

- [ ] **Step 2: Add test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import scan_components_dict_float


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_components_dict_float(path):
    """RULE-3: every components dict value is float-compatible."""
    violations = scan_components_dict_float(path)
    assert not violations, format_violations(path, violations)
```

Update imports.

- [ ] **Step 3: Run, collect violations, fix one by one**

Run:

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py::test_components_dict_float -v
```

For each reported violation, edit the detector file to wrap the RHS in `float(...)`. Example:

```python
# Before
components["recent_buyers"] = recent_buyers   # int variable

# After
components["recent_buyers"] = float(recent_buyers)
```

Re-run after each fix until green.

- [ ] **Step 4: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py [fixed detector files]
git commit -m "test(scanner): RULE-3 components dict values are float

Every value written to a detector's components dict must be a
float() call, a float literal, or an int literal that Python
normalizes. Catches accidental string/bool insertions that crash
downstream pydantic validation.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: RULE-5 — bare `except Exception:` must log or re-raise

**Pre-known violations:**
- `v2/scanner/detectors/analyst_rating.py:103` — swallows `actions = []`
- `v2/scanner/detectors/analyst_rating.py:110` — swallows `target = None`

Other detector files may have more — let the linter find them.

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_bare_except`)
- Modify: `tests/test_detector_invariants.py` (add `test_bare_except`)
- Modify: `v2/scanner/detectors/analyst_rating.py` (add `logger.warning(...)` lines)
- Possibly other detector files the lint discovers

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
def _block_has_logger_call_or_raise(body: list[ast.stmt]) -> bool:
    """Return True when the statement block contains either a ``logger.*``
    call or a ``raise`` (bare or with expression).
    """
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return True
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logger"):
                return True
    return False


def scan_bare_except(path: Path) -> list[Violation]:
    """RULE-5: ``except Exception:`` blocks must call ``logger.*`` or
    ``raise``. Silent swallows hide real bugs behind the scanner's
    error-isolation runner.

    Permitted handler signatures:
      * ``except Exception:``                  — the bare case
      * ``except Exception as e:``             — common alias form

    Anything narrower (``except ValueError:`` etc.) is NOT covered;
    we trust specific exception handlers to know what they're doing.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # Only the bare/aliased "Exception" pattern; skip narrower handlers
        if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
            continue
        if _block_has_logger_call_or_raise(node.body):
            continue
        violations.append(Violation(
            rule="RULE-5",
            line=node.lineno,
            message="bare `except Exception:` without logger.* call or raise",
        ))
    return violations
```

- [ ] **Step 2: Add test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import scan_bare_except


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_bare_except_handler(path):
    """RULE-5: except Exception: blocks log or re-raise."""
    violations = scan_bare_except(path)
    assert not violations, format_violations(path, violations)
```

Update imports.

- [ ] **Step 3: Run, confirm expected violations**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py::test_bare_except_handler -v
```

Expected: failures on `analyst_rating.py:103` and `analyst_rating.py:110`. Any OTHER detector failures: investigate before fixing — could be intentional swallows that need either a logger call or narrowing the handler.

- [ ] **Step 4: Fix analyst_rating.py**

The file already imports `logging` indirectly? Check first:

```bash
C:/Users/Jerry/anaconda3/python.exe -c "import v2.scanner.detectors.analyst_rating as m; print('logger' in dir(m))"
```

If False, add at the top of `v2/scanner/detectors/analyst_rating.py` (after the existing imports):

```python
import logging

logger = logging.getLogger(__name__)
```

Then patch lines 103 and 110 in `v2/scanner/detectors/analyst_rating.py`:

Find:
```python
        try:
            actions = fd.get_analyst_actions(
                ticker,
                end_date=end_date,
                start_date=baseline_start.isoformat(),
                limit=self._fetch_limit,
            )
        except (NotImplementedError, AttributeError):
            return None
        except Exception:
            actions = []
```

Replace with:
```python
        try:
            actions = fd.get_analyst_actions(
                ticker,
                end_date=end_date,
                start_date=baseline_start.isoformat(),
                limit=self._fetch_limit,
            )
        except (NotImplementedError, AttributeError):
            return None
        except Exception as e:
            logger.warning("analyst_rating: get_analyst_actions(%s) failed: %s", ticker, e)
            actions = []
```

Find:
```python
        try:
            target = fd.get_analyst_targets(ticker, asof_date=end_date)
        except (NotImplementedError, AttributeError):
            target = None
        except Exception:
            target = None
```

Replace with:
```python
        try:
            target = fd.get_analyst_targets(ticker, asof_date=end_date)
        except (NotImplementedError, AttributeError):
            target = None
        except Exception as e:
            logger.warning("analyst_rating: get_analyst_targets(%s) failed: %s", ticker, e)
            target = None
```

- [ ] **Step 5: Fix any other detectors the lint discovered**

For each other violation: same pattern. Add `logger.warning(...)` or `logger.exception(...)` before whatever the swallow sets, and add the `import logging; logger = logging.getLogger(__name__)` boilerplate if the file doesn't have it.

- [ ] **Step 6: Re-run and verify green**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py v2/scanner/detectors/analyst_rating.py [any other fixed files]
git commit -m "test(scanner): RULE-5 bare except must log or re-raise

Plus fix: analyst_rating now logs at WARNING when the optional
analyst-data endpoints fail, instead of silently coercing to empty
inputs that pretend nothing went wrong.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: RULE-1 — `.std()` calls have a floor

**Pre-known violations (all need `# noqa: std-floor` justification or refactor):**
- `bollinger_squeeze.py:49` — `sigma` is a numerator coefficient, not a z-divisor → `# noqa`
- `bollinger_squeeze.py:120` — same as above → `# noqa`
- `earnings.py:178` — uses if-branch clamp (`if sigma_raw < sigma_floor:`) → `# noqa`
- `earnings.py:423` — same as above → `# noqa`

**Files:**
- Modify: `tests/_detector_lint.py` (add `scan_std_floor_wrapping`)
- Modify: `tests/test_detector_invariants.py` (add `test_std_floor_wrapping`)
- Modify: `v2/scanner/detectors/bollinger_squeeze.py` (lines 49, 120)
- Modify: `v2/scanner/detectors/earnings.py` (lines 178, 423)

- [ ] **Step 1: Add scan function**

Append to `tests/_detector_lint.py`:

```python
def _enclosing_function(node: ast.AST) -> ast.FunctionDef | None:
    """Walk ``.parent`` until we hit a FunctionDef, return it."""
    parent = getattr(node, "parent", None)
    while parent is not None and not isinstance(parent, ast.FunctionDef):
        parent = getattr(parent, "parent", None)
    return parent if isinstance(parent, ast.FunctionDef) else None


def scan_std_floor_wrapping(path: Path) -> list[Violation]:
    """RULE-1: each ``.std()`` call has a max() floor applied.

    Accepts ANY of these patterns:
      (a) direct wrap: ``max(arr.std(...), floor)``
      (b) assigned-then-max: ``sigma = arr.std(...); max(sigma, floor)``
          appears later in the same function
      (c) suppression: trailing ``# noqa: std-floor`` on the line
          of the .std() call — documents intentional bare std use
          (numerator coefficient, branched clamp, etc.)
    """
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    tree = ast.parse(source)
    attach_parents(tree)
    violations: list[Violation] = []

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "std"):
            continue
        # (c) noqa suppression
        line_text = source_lines[node.lineno - 1] if node.lineno <= len(source_lines) else ""
        if "# noqa: std-floor" in line_text:
            continue
        # (a) direct max() ancestor before the enclosing function
        ancestor = getattr(node, "parent", None)
        wrapped = False
        while ancestor is not None and not isinstance(ancestor, ast.FunctionDef):
            if (isinstance(ancestor, ast.Call)
                    and isinstance(ancestor.func, ast.Name)
                    and ancestor.func.id == "max"):
                wrapped = True
                break
            ancestor = getattr(ancestor, "parent", None)
        if wrapped:
            continue
        # (b) assigned-then-max in the same function
        # Walk up to find the enclosing Assign whose value-tree contains this .std() node
        assign = getattr(node, "parent", None)
        while assign is not None and not isinstance(assign, (ast.Assign, ast.FunctionDef)):
            assign = getattr(assign, "parent", None)
        if isinstance(assign, ast.Assign) and len(assign.targets) == 1 \
                and isinstance(assign.targets[0], ast.Name):
            var_name = assign.targets[0].id
            func = _enclosing_function(assign)
            if func is not None:
                for inner in ast.walk(func):
                    if (isinstance(inner, ast.Call)
                            and isinstance(inner.func, ast.Name)
                            and inner.func.id == "max"
                            and any(isinstance(a, ast.Name) and a.id == var_name
                                    for a in inner.args)):
                        wrapped = True
                        break
        if wrapped:
            continue

        violations.append(Violation(
            rule="RULE-1",
            line=node.lineno,
            message=".std() result has no max() floor and no `# noqa: std-floor` annotation",
        ))
    return violations
```

- [ ] **Step 2: Add test**

Append to `tests/test_detector_invariants.py`:

```python
from tests._detector_lint import scan_std_floor_wrapping


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_std_floor_wrapping(path):
    """RULE-1: .std() result is wrapped in max() or noqa-suppressed."""
    violations = scan_std_floor_wrapping(path)
    assert not violations, format_violations(path, violations)
```

Update imports.

- [ ] **Step 3: Run, confirm 4 expected violations**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py::test_std_floor_wrapping -v
```

Expected failures: `bollinger_squeeze.py:49`, `bollinger_squeeze.py:120`, `earnings.py:178`, `earnings.py:423`. Other detectors that already use max() directly or the assigned-then-max pattern should pass.

- [ ] **Step 4: Fix bollinger_squeeze.py:49**

Find in `v2/scanner/detectors/bollinger_squeeze.py`:
```python
    sigma = float(tail.std(ddof=1))
    return (2.0 * std_mult * sigma) / mid
```

Replace with:
```python
    sigma = float(tail.std(ddof=1))  # noqa: std-floor (sigma is numerator coefficient, not z-divisor)
    return (2.0 * std_mult * sigma) / mid
```

- [ ] **Step 5: Fix bollinger_squeeze.py:120**

Find in `v2/scanner/detectors/bollinger_squeeze.py`:
```python
            sigma = float(window_slice.std(ddof=1))
            bandwidths.append((2.0 * self._bb_std_mult * sigma) / mid)
```

Replace with:
```python
            sigma = float(window_slice.std(ddof=1))  # noqa: std-floor (sigma is numerator coefficient, not z-divisor)
            bandwidths.append((2.0 * self._bb_std_mult * sigma) / mid)
```

- [ ] **Step 6: Fix earnings.py:178**

Find in `v2/scanner/detectors/earnings.py` around line 178:
```python
            sigma_raw = float(hist.std(ddof=1))
            # Std floor: 5% of estimate. Without this, an ultra-stable history
```

Replace with:
```python
            sigma_raw = float(hist.std(ddof=1))  # noqa: std-floor (clamped via `if sigma_raw < sigma_floor` branch below)
            # Std floor: 5% of estimate. Without this, an ultra-stable history
```

- [ ] **Step 7: Fix earnings.py:423**

Find in `v2/scanner/detectors/earnings.py` around line 423:
```python
            sigma_raw = float(hist.std(ddof=1))
            sigma_floor = 0.05
```

Replace with:
```python
            sigma_raw = float(hist.std(ddof=1))  # noqa: std-floor (clamped via `if sigma_raw < sigma_floor` branch below)
            sigma_floor = 0.05
```

- [ ] **Step 8: Fix any other detectors the lint discovered**

For each: decide between (a) refactor to `max(...)` (preferred when the use is genuinely a z-divisor and no floor exists yet), or (b) add `# noqa: std-floor (<reason>)` if the bare std is safe.

- [ ] **Step 9: Re-run and verify green**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add tests/_detector_lint.py tests/test_detector_invariants.py v2/scanner/detectors/bollinger_squeeze.py v2/scanner/detectors/earnings.py
git commit -m "test(scanner): RULE-1 std floor wrapping

Each .std() call must either be wrapped in max(...) (directly or
via assigned-then-max in the same function) or annotated with
\`# noqa: std-floor\` documenting why the bare std is safe.

Annotated the four pre-existing bare std uses:
  bollinger_squeeze.py:49, 120  — sigma is numerator coefficient
  earnings.py:178, 423          — branched clamp below

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Final verification + integrate into default suite

**Files:**
- Read-only: full pytest run

- [ ] **Step 1: Run the new test file alone**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest tests/test_detector_invariants.py -v
```

Expected: all green. Approximate count: 1 sanity test + (10 detectors × 8 rule tests) + 1 cross-file uniqueness = 82 tests total.

- [ ] **Step 2: Run the full pytest suite to check for regressions**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest -q
```

Expected: the new tests add to the prior pass count, no previously-passing test fails. If any do, the `logger.warning(...)` additions to `analyst_rating.py` or the noqa annotations to `bollinger_squeeze.py` / `earnings.py` accidentally changed behavior — investigate the failing test.

- [ ] **Step 3: Confirm helper module is NOT collected**

```bash
C:/Users/Jerry/anaconda3/python.exe -m pytest --collect-only tests/ -q | grep _detector_lint
```

Expected: empty output. The underscore prefix excludes the helper from default discovery.

- [ ] **Step 4: Smoke a real scanner run unaffected**

Quick smoke that the detector behavior is unchanged:

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m v2.scanner --end-date 2026-05-15 --top 5 --universe nasdaq100 2>&1 | tail -20
```

Expected: ANSI-coloured top-5 watchlist prints with no exceptions. (If background quant-ablation job is still using the scanner, skip this step to avoid contention — the linter only changed logging text and added comments; smoke is for paranoia, not necessity.)

- [ ] **Step 5: Update progress.md per CLAUDE.md workflow rule**

Add a new dated session block to `progress.md` documenting:
- 8 new invariant tests under `tests/test_detector_invariants.py`
- Helper module `tests/_detector_lint.py` (~400 LoC)
- 6 detector violations fixed (analyst_rating logging, bollinger_squeeze + earnings noqa annotations)
- All tests green, no regressions in the broader suite

- [ ] **Step 6: Final commit**

If the progress.md update happens in a separate commit:

```bash
git add progress.md
git commit -m "docs: log detector invariant test suite landing

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage:**
- RULE-1 → Task 9 ✓
- RULE-2 → Task 2 ✓
- RULE-3 → Task 7 ✓
- RULE-4 → Task 5 ✓
- RULE-5 → Task 8 ✓
- RULE-6 → Task 3 ✓
- RULE-7 → Task 6 ✓
- RULE-8 → Task 4 ✓
- Scaffolding → Task 1 ✓
- Final verification → Task 10 ✓
- "Fix existing violations" expectation → embedded per rule task

**Placeholder scan:** no TBD / TODO / "add appropriate" / vague steps. Tasks 8 step 5 and Task 9 step 8 are open-ended ("fix any other detectors the lint discovers") but immediately followed by a re-run-and-verify step — appropriate because the violation list is data-driven.

**Type consistency:**
- `Violation(rule, line, message)` — used consistently across all `scan_*` functions
- `format_violations(path, violations)` — used as `assert not violations, format_violations(...)` everywhere
- `DETECTOR_FILES` — `list[Path]` imported once, parameterized identically in every test
- `_ids(path)` helper used as `ids=_ids` in every `@pytest.mark.parametrize`
- `_import_detector_module(path)` — defined in Task 3, reused in Task 4

**Risks revisited:**
- Tasks 4, 6 import detector modules at test collection time. If a detector module has an import error, ALL parametrized tests fail. Mitigation: the sanity test in Task 1 (`test_detector_files_discovered`) doesn't import; if it fails first, fixes go there. If individual tests fail with ImportError, fix the detector module before the lint runs.
- `typing.get_type_hints` (Task 4) needs the detector module's symbol scope. Using `importlib.import_module(...)` from Task 3 covers this. If a detector uses a forward reference to a name not exported from `v2.scanner.detectors.base`, hints resolution fails — Task 4's scan reports it as `cannot resolve type hints` rather than crashing.
