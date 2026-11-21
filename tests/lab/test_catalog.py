"""Phase 6A: CATALOG dict + JSON schema export for strategy blocks."""

from __future__ import annotations

from src.lab.catalog import CATALOG, get_llm_prompt_text


def test_catalog_has_legacy_and_shared_blocks():
    expected_types = {
        "rsi", "rsi_cross", "ma_cross", "price_vs_ma", "macd",
        "bollinger_break", "donchian_break", "volume_spike",
        "relative_volume", "range_breakout", "relative_strength",
        "stop_loss", "take_profit", "trailing_stop", "time_stop",
        "fixed_pct", "equal_weight", "vol_targeted",
        "trend", "volatility", "liquidity",
    }
    assert set(CATALOG.keys()) == expected_types


def test_each_block_has_required_metadata():
    for name, entry in CATALOG.items():
        assert "category" in entry
        assert entry["category"] in {"entry", "exit", "sizing", "filter"}
        assert "description" in entry
        assert len(entry["description"]) > 20  # not empty
        assert "schema" in entry  # Pydantic JSON schema
        assert isinstance(entry["schema"], dict)
        assert entry["schema"].get("properties")  # has fields


def test_llm_prompt_text_includes_all_blocks():
    text = get_llm_prompt_text()
    for name in CATALOG:
        assert name in text
    # Should be reasonable size — ~600-1500 tokens worth
    assert 1000 < len(text) < 8000
