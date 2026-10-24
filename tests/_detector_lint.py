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


def _rhs_is_float_compatible(value: ast.AST) -> bool:
    """Return True when ``value`` is one of:
      * ``float(...)`` call
      * float literal (``Constant(value=float)``)
      * the literal ``0`` integer-typed constant (``Constant(value=0)``)
        — covered because Python normalizes; explicit float typing
        preferred but we allow it to reduce noise
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
