"""Column metadata smoke test — verifies 16-chip shape + bilingual labels."""
from __future__ import annotations


def test_chip_count():
    from src.screener.column_metadata import COLUMN_METADATA
    assert len(COLUMN_METADATA) == 16


def test_chip_required_fields():
    from src.screener.column_metadata import COLUMN_METADATA
    for chip in COLUMN_METADATA:
        assert "slug" in chip
        assert "label_en" in chip
        assert "label_zh" in chip
        assert "kind" in chip
        assert chip["kind"] in ("range", "multi_select", "date_range")


def test_known_chips_present():
    from src.screener.column_metadata import COLUMN_METADATA
    slugs = {c["slug"] for c in COLUMN_METADATA}
    assert {"price", "chg_pct", "mcap", "pe", "eps_growth",
            "div_yield", "sector", "analyst_rating",
            "perf_1d", "revenue_growth", "peg", "roe", "beta",
            "recent_earnings", "upcoming_earnings"}.issubset(slugs)


def test_range_chips_have_step():
    from src.screener.column_metadata import COLUMN_METADATA
    for c in COLUMN_METADATA:
        if c["kind"] == "range":
            assert "step" in c
            assert "format" in c  # e.g. 'currency' | 'percent' | 'multiplier'


def test_multi_select_options():
    from src.screener.column_metadata import COLUMN_METADATA
    sector = next(c for c in COLUMN_METADATA if c["slug"] == "sector")
    assert "options_us" in sector and len(sector["options_us"]) > 5
    rating = next(c for c in COLUMN_METADATA if c["slug"] == "analyst_rating")
    assert set(o["value"] for o in rating["options"]) == {
        "strong_buy", "buy", "neutral", "sell", "strong_sell",
    }
