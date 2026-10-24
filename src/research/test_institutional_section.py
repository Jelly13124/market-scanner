"""Offline tests for the Institutional Positioning report section + the
gamma-walls chart renderer.

No network: ``fetch_gamma_exposure`` / ``fetch_short_volume`` are monkeypatched
on the SECTION module (``src.research.sections.institutional_flow``) so neither
yfinance nor requests is ever touched. The section is a non-LLM Python renderer,
so no LLM call happens either.
"""

from __future__ import annotations

from src.research import models
from src.research.charts.render import render_gamma_walls_png
from src.research.models import AnalyzeRequest, SECTION_ORDER
from src.research.sections import SECTION_REGISTRY
from src.research.sections import institutional_flow as sec
from src.research.sections.base import SectionContext
from src.research.sections.institutional_flow import InstitutionalFlowSection
from src.research.shared_data import SharedData


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _req(lang: str = "en") -> AnalyzeRequest:
    return AnalyzeRequest(
        ticker="NVDA",
        objective="medium_term",
        position_budget_usd=10000,
        already_holds=False,
        cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=False,
        report_language=lang,
    )


def _shared() -> SharedData:
    return SharedData(
        ticker="NVDA",
        scan_date="2026-06-08",
        prices=[1, 2, 3],
        financials=[],
        insider_trades=[],
        news=[],
        analyst_actions=[],
        analyst_targets=None,
        earnings_history=[],
        company_facts={"name": "NVIDIA"},
        sector_etf_prices=[],
        spy_prices=[],
    )


def _ctx(lang: str = "en") -> SectionContext:
    return SectionContext(request=_req(lang), shared=_shared(), persona=None, prior={})


def _gamma_dict() -> dict:
    return {
        "ticker": "NVDA",
        "spot": 742.0,
        "total_gex": -3.51e9,
        "regime": "negative",
        "call_gex": 1.0e9,
        "put_gex": 4.51e9,
        "walls": [
            {"strike": 740.0, "gamma_dollars": 0.94e9},
            {"strike": 745.0, "gamma_dollars": 0.82e9},
            {"strike": 735.0, "gamma_dollars": -0.59e9},
        ],
        "gamma_flip": 738.0,
    }


def _shortvol_dict() -> dict:
    return {
        "ticker": "NVDA",
        "date": "2026-06-05",
        "short_pct": 0.482,
        "short_volume": 4_820_000.0,
        "total_volume": 10_000_000.0,
        "avg_short_pct": 0.441,
        "trend": "rising",
        "n_days": 10,
    }


# --------------------------------------------------------------------------- #
# 1. Section renders with stub gamma + short-vol → markdown + chart
# --------------------------------------------------------------------------- #


def test_section_renders_gamma_and_shortvol(monkeypatch):
    monkeypatch.setattr(sec, "fetch_gamma_exposure", lambda t: _gamma_dict())
    monkeypatch.setattr(sec, "fetch_short_volume", lambda t: _shortvol_dict())

    out = InstitutionalFlowSection().run(_ctx())

    assert out.name == "institutional_flow"
    assert out.skipped is False

    md = out.markdown
    # Heading + the load-bearing dealer-gamma vocabulary.
    assert "Institutional" in md
    assert "gamma" in md.lower()
    assert "GEX" in md
    # The regime is surfaced honestly.
    assert "NEGATIVE" in md
    # Off-exchange short proxy with the latest level + trend.
    assert "48.2%" in md
    assert "RISING" in md
    assert "proxy" in md.lower()
    assert "NOT true dark-pool" in md

    # Chart attached as a data: URI PNG via structured["charts"].
    assert isinstance(out.structured, dict)
    charts = out.structured["charts"]
    assert isinstance(charts, list) and len(charts) == 1
    assert charts[0]["src"].startswith("data:image/png")
    assert charts[0]["alt"] == "Gamma walls"
    assert charts[0]["caption"]


def test_section_renders_with_only_shortvol_and_no_chart(monkeypatch):
    # Gamma absent but short-vol present → still renders, no chart (chart needs
    # gamma walls).
    monkeypatch.setattr(sec, "fetch_gamma_exposure", lambda t: None)
    monkeypatch.setattr(sec, "fetch_short_volume", lambda t: _shortvol_dict())

    out = InstitutionalFlowSection().run(_ctx())

    assert out.skipped is False
    assert "48.2%" in out.markdown
    assert out.structured is None  # no gamma → no chart


# --------------------------------------------------------------------------- #
# 2. Both fetches None → graceful note, no crash, no chart
# --------------------------------------------------------------------------- #


def test_both_none_graceful_note(monkeypatch):
    monkeypatch.setattr(sec, "fetch_gamma_exposure", lambda t: None)
    monkeypatch.setattr(sec, "fetch_short_volume", lambda t: None)

    out = InstitutionalFlowSection().run(_ctx())

    assert out.name == "institutional_flow"
    assert out.skipped is False  # honest "unavailable" note, not a skip
    assert "Institutional" in out.markdown
    assert "unavailable" in out.markdown.lower()
    assert out.structured is None  # no chart


def test_fetch_raises_is_swallowed(monkeypatch):
    # An adapter that raises must NOT crash the section (best-effort).
    def _boom(_t):
        raise RuntimeError("network down")

    monkeypatch.setattr(sec, "fetch_gamma_exposure", _boom)
    monkeypatch.setattr(sec, "fetch_short_volume", _boom)

    out = InstitutionalFlowSection().run(_ctx())
    assert out.skipped is False
    assert "unavailable" in out.markdown.lower()


def test_zh_heading_localized(monkeypatch):
    monkeypatch.setattr(sec, "fetch_gamma_exposure", lambda t: None)
    monkeypatch.setattr(sec, "fetch_short_volume", lambda t: None)

    out = InstitutionalFlowSection().run(_ctx(lang="zh"))
    assert "机构持仓" in out.markdown


# --------------------------------------------------------------------------- #
# 3. render_gamma_walls_png — real dict → PNG; empty walls → placeholder PNG
# --------------------------------------------------------------------------- #


def test_render_gamma_walls_png_returns_png_bytes():
    b = render_gamma_walls_png(_gamma_dict())
    assert isinstance(b, bytes)
    assert b[:4] == b"\x89PNG"


def test_render_gamma_walls_png_empty_walls_is_placeholder():
    # Empty walls list → placeholder PNG, no raise.
    b = render_gamma_walls_png({"spot": 100.0, "walls": []})
    assert b[:4] == b"\x89PNG"


def test_render_gamma_walls_png_missing_keys_is_placeholder():
    # Completely empty / missing dict → placeholder PNG, no raise.
    assert render_gamma_walls_png({})[:4] == b"\x89PNG"
    assert render_gamma_walls_png(None)[:4] == b"\x89PNG"


def test_render_gamma_walls_png_single_wall_no_flip():
    # Single wall, no gamma_flip → still a valid PNG (width fallback path).
    gex = {"spot": 50.0, "walls": [{"strike": 50.0, "gamma_dollars": 1.2e8}]}
    assert render_gamma_walls_png(gex)[:4] == b"\x89PNG"


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #


def test_registered_and_in_section_order():
    assert "institutional_flow" in SECTION_REGISTRY
    assert isinstance(SECTION_REGISTRY["institutional_flow"], InstitutionalFlowSection)
    assert "institutional_flow" in SECTION_ORDER
    # Inserted right after technical.
    idx = SECTION_ORDER.index("institutional_flow")
    assert SECTION_ORDER[idx - 1] == "technical"
    assert models.SECTION_ORDER is SECTION_ORDER
