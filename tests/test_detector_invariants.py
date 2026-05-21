"""Static-analysis tests for v2/scanner/detectors/*.py.

Enforces the four load-bearing invariants from CLAUDE.md plus four
observable best-practices. See docs/superpowers/specs/2026-05-21-
detector-invariant-tests-design.md for the rule catalog.

Each rule is one parameterized test; the parameter is the detector
file path. Failure message points to file:line so fixes are trivial.
"""

from __future__ import annotations

import pytest

from tests._detector_lint import (
    DETECTOR_FILES,
    collect_all_detector_names,
    format_violations,
    scan_detector_name_attribute,
    scan_detect_return_annotation,
    scan_forbidden_std_pattern,
)


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


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_no_forbidden_std_pattern(path):
    """RULE-2: no `... .std(...) or NUMBER` fallback patterns."""
    violations = scan_forbidden_std_pattern(path)
    assert not violations, format_violations(path, violations)


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


@pytest.mark.parametrize("path", DETECTOR_FILES, ids=_ids)
def test_detect_return_annotation(path):
    """RULE-8: detect() return type is EventTrigger | None."""
    violations = scan_detect_return_annotation(path)
    assert not violations, format_violations(path, violations)
