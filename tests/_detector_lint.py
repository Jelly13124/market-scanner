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
import importlib
import inspect
import re
import typing
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
    # Require EXACTLY {EventTrigger, NoneType} — reject wider unions like
    # Union[EventTrigger, str, None] which would defeat the rule's purpose.
    arg_names = {getattr(a, "__name__", str(a)) for a in args}
    return arg_names == {"EventTrigger", "NoneType"}


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
