"""Offline tests for the paper-trading performance report (Task 7).

Fully offline: a scratch in-memory SQLite engine + ``Session`` (same setup as
``test_performance.py``) plus ``tmp_path`` for the written files. No network, no
LLM — the chart is rendered on the headless Agg backend and the report is read
back off disk.

The cases pin the load-bearing contracts:
  * ``render_sleeves_equity_png`` returns real PNG bytes for a multi-sleeve
    series and a placeholder PNG (never a raise) for empty input;
  * ``write_report`` writes both files, embeds the chart as an inline data URI,
    names every sleeve, shows the PASS/FAIL verdict, and returns the two paths +
    a ``passed`` bool; and
  * ``write_report`` survives an empty DB (no sleeves) without raising.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.backend.database.connection import Base
from app.backend.database.models import (
    PaperEquityMark,
    PaperPosition,
    PaperSleeve,
)
from src.paper_trading.report import (
    render_sleeves_equity_png,
    write_report,
)


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


# -- fixtures / helpers -------------------------------------------------------


@pytest.fixture()
def session():
    """Fresh in-memory SQLite session with the paper-trading tables created."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as sess:
        yield sess
    engine.dispose()


def _make_sleeve(session, name: str, starting_cash: float = 100_000.0) -> PaperSleeve:
    sleeve = PaperSleeve(name=name, starting_cash=starting_cash)
    session.add(sleeve)
    session.flush()  # assign sleeve.id
    return sleeve


def _add_marks(session, sleeve_id, equities, *, start_day: int = 1) -> None:
    for offset, equity in enumerate(equities):
        date = f"2026-06-{start_day + offset:02d}"
        session.add(PaperEquityMark(sleeve_id=sleeve_id, date=date, equity=float(equity)))


def _add_closed_position(session, sleeve_id, ticker, entry=100.0, exit_=110.0) -> None:
    session.add(
        PaperPosition(
            sleeve_id=sleeve_id,
            ticker=ticker,
            shares=10.0,
            entry_date="2026-06-01",
            entry_price=entry,
            exit_date="2026-06-05",
            exit_price=exit_,
            status="closed",
        )
    )


def _seed_three_sleeves(session) -> None:
    """Three sleeves with rising curves + a couple closed positions on the agent."""
    a = _make_sleeve(session, "scanner_agent")
    o = _make_sleeve(session, "scanner_only")
    s = _make_sleeve(session, "spy_benchmark")
    _add_marks(session, a.id, [100_000.0, 102_000.0, 101_000.0, 108_000.0])
    _add_marks(session, o.id, [100_000.0, 100_500.0, 101_000.0, 104_000.0])
    _add_marks(session, s.id, [100_000.0, 100_200.0, 100_400.0, 100_600.0])
    _add_closed_position(session, a.id, "AAA")
    _add_closed_position(session, a.id, "BBB")
    session.commit()


# -- 1. render_sleeves_equity_png ---------------------------------------------


def test_render_sleeves_equity_png_three_series() -> None:
    equity_by_sleeve = {
        "scanner_agent": [("2026-06-01", 100_000.0), ("2026-06-02", 102_000.0), ("2026-06-03", 108_000.0)],
        "scanner_only": [("2026-06-01", 100_000.0), ("2026-06-02", 100_500.0), ("2026-06-03", 104_000.0)],
        "spy_benchmark": [("2026-06-01", 100_000.0), ("2026-06-02", 100_200.0), ("2026-06-03", 100_600.0)],
    }
    out = render_sleeves_equity_png(equity_by_sleeve)
    assert isinstance(out, bytes)
    assert out[:4] == b"\x89PNG"
    assert out.startswith(PNG_SIGNATURE)
    assert len(out) > 1000


def test_render_sleeves_equity_png_empty_dict_still_png() -> None:
    out = render_sleeves_equity_png({})
    assert isinstance(out, bytes)
    assert out[:4] == b"\x89PNG"
    assert len(out) > 200  # the "No data" placeholder is still a real PNG


def test_render_sleeves_equity_png_all_empty_series_still_png() -> None:
    # Every sleeve present but with an empty series → placeholder, no raise.
    out = render_sleeves_equity_png({"scanner_agent": [], "spy_benchmark": []})
    assert out[:4] == b"\x89PNG"


def test_render_sleeves_equity_png_unparseable_dates_falls_back_to_index() -> None:
    # Non-ISO date strings must not raise — the renderer falls back to an index axis.
    out = render_sleeves_equity_png({"scanner_agent": [("day-1", 100_000.0), ("day-2", 101_000.0)]})
    assert out[:4] == b"\x89PNG"
    assert len(out) > 1000


# -- 2. write_report happy path -----------------------------------------------


def test_write_report_happy_path(session, tmp_path) -> None:
    _seed_three_sleeves(session)

    out_dir = str(tmp_path / "report_out")
    result = write_report(out_dir, session=session)

    # Returned dict shape.
    assert set(result.keys()) == {"report_md", "report_html", "passed"}
    assert isinstance(result["passed"], bool)
    assert result["report_md"] == os.path.join(out_dir, "paper_trading_report.md")
    assert result["report_html"] == os.path.join(out_dir, "paper_trading_report.html")

    # Both files exist on disk.
    assert os.path.isfile(result["report_md"])
    assert os.path.isfile(result["report_html"])

    html = open(result["report_html"], encoding="utf-8").read()
    # All three sleeve names appear.
    for name in ("scanner_agent", "scanner_only", "spy_benchmark"):
        assert name in html
    # The equity chart is embedded inline as a base64 data URI <img>.
    assert "data:image/png;base64," in html
    assert "<img" in html
    # The verdict word is rendered (PASS or FAIL) + the literal "passed=" label.
    assert ("PASS" in html) or ("FAIL" in html)
    assert "passed=" in html

    md = open(result["report_md"], encoding="utf-8").read()
    for name in ("scanner_agent", "scanner_only", "spy_benchmark"):
        assert name in md
    # The markdown metrics table renders a percent total_return + a % drawdown.
    assert "%" in md


def test_write_report_drawdown_not_double_scaled(session, tmp_path) -> None:
    # A real mid-curve dip yields a single-digit-percent drawdown. If the report
    # wrongly multiplied the already-×100 percent by 100 again it would print a
    # value with |x| >> 100 — assert the agent row stays a sane percent.
    a = _make_sleeve(session, "scanner_agent")
    _add_marks(session, a.id, [100_000.0, 102_000.0, 101_000.0, 105_000.0])
    session.commit()

    out_dir = str(tmp_path / "dd")
    result = write_report(out_dir, session=session)
    md = open(result["report_md"], encoding="utf-8").read()
    # ~ -0.98% expected; certainly not -98.xx% (the double-scaled bug).
    assert "-0.98%" in md


# -- 3. write_report on an empty DB -------------------------------------------


def test_write_report_empty_db(session, tmp_path) -> None:
    out_dir = str(tmp_path / "empty")
    result = write_report(out_dir, session=session)  # no sleeves seeded

    assert os.path.isfile(result["report_md"])
    assert os.path.isfile(result["report_html"])
    # Empty DB can't graduate → passed is False, no raise.
    assert result["passed"] is False

    html = open(result["report_html"], encoding="utf-8").read()
    # Still a self-contained HTML with an embedded (placeholder) chart.
    assert "data:image/png;base64," in html
    assert "FAIL" in html
