"""Tests for v2/pipeline/templates.py."""

from __future__ import annotations

import pytest

from v2.pipeline.templates import (
    DEFAULT_TEMPLATE,
    TEMPLATES,
    resolve_analysts,
)


def test_default_template_is_in_templates():
    assert DEFAULT_TEMPLATE in TEMPLATES


def test_every_template_keys_validate_against_analyst_config():
    """No template can ship with a typo that would blow up at runtime."""
    from src.utils.analysts import ANALYST_CONFIG
    valid = set(ANALYST_CONFIG.keys())
    for name, keys in TEMPLATES.items():
        bad = [k for k in keys if k not in valid]
        assert not bad, f"template {name!r} has unknown keys: {bad}"


def test_every_template_starts_with_scanner_signal():
    """``scanner_signal`` is the whole point of the bridge — must always
    be in the roster so downstream agents see the scanner context."""
    for name, keys in TEMPLATES.items():
        assert "scanner_signal" in keys, f"{name} missing scanner_signal"


def test_resolve_with_template_returns_template_list():
    out = resolve_analysts(template="balanced")
    assert out == TEMPLATES["balanced"]


def test_resolve_default_template_when_both_args_none():
    out = resolve_analysts(template=None, custom=None)
    assert out == TEMPLATES[DEFAULT_TEMPLATE]


def test_resolve_custom_prepends_scanner_signal_if_missing():
    out = resolve_analysts(custom=["warren_buffett", "fundamentals_analyst"])
    assert out[0] == "scanner_signal"
    assert "warren_buffett" in out
    assert "fundamentals_analyst" in out


def test_resolve_custom_keeps_scanner_signal_position_if_already_present():
    # User explicitly puts scanner_signal in their list — don't double-add.
    out = resolve_analysts(custom=["warren_buffett", "scanner_signal", "technical_analyst"])
    assert out.count("scanner_signal") == 1


def test_resolve_template_and_custom_mutually_exclusive():
    with pytest.raises(ValueError, match="either template OR custom"):
        resolve_analysts(template="balanced", custom=["warren_buffett"])


def test_resolve_unknown_template_raises():
    with pytest.raises(ValueError, match="unknown template"):
        resolve_analysts(template="no_such_template")


def test_resolve_custom_empty_raises():
    with pytest.raises(ValueError, match="cannot be empty"):
        resolve_analysts(custom=[])


def test_resolve_unknown_analyst_in_custom_raises():
    with pytest.raises(ValueError, match="unknown analyst key"):
        resolve_analysts(custom=["warren_buffett", "made_up_persona"])


def test_resolve_dedupes_preserving_order():
    out = resolve_analysts(custom=[
        "warren_buffett", "fundamentals_analyst", "warren_buffett",
    ])
    # scanner_signal auto-prepended, then de-duped list follows
    assert out == ["scanner_signal", "warren_buffett", "fundamentals_analyst"]
