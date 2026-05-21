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
