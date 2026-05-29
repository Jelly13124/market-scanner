"""ScreenerRepository: bulk upsert, filtered query, cleanup."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, TickerSnapshot
from app.backend.repositories.screener_repository import (
    ScreenerRepository,
    SnapshotRow,
)


@pytest.fixture()
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield ScreenerRepository(db)
    db.close()


def _row(ticker, market="US", snapshot_date=date(2026, 5, 27), **kw):
    base = dict(
        ticker=ticker, market=market, snapshot_date=snapshot_date,
        price=Decimal("100"), market_cap=Decimal("1000000000"),
        pe_ttm=Decimal("20"), sector="Technology",
        analyst_rating="buy", perf_1d=Decimal("0.01"),
        data_source="test",
    )
    base.update(kw)
    return SnapshotRow(**base)


def test_bulk_upsert_inserts(repo):
    rows = [_row("AAPL"), _row("MSFT"), _row("NVDA")]
    n = repo.bulk_upsert(rows)
    assert n == 3
    assert repo.db.query(TickerSnapshot).count() == 3


def test_bulk_upsert_idempotent_on_same_date(repo):
    repo.bulk_upsert([_row("AAPL", price=Decimal("210"))])
    repo.bulk_upsert([_row("AAPL", price=Decimal("215"))])  # same ticker+date
    assert repo.db.query(TickerSnapshot).count() == 1
    out = repo.db.query(TickerSnapshot).filter_by(ticker="AAPL").one()
    assert out.price == Decimal("215")  # updated


def test_latest_snapshot_date(repo):
    repo.bulk_upsert([_row("AAPL", snapshot_date=date(2026, 5, 26))])
    repo.bulk_upsert([_row("AAPL", snapshot_date=date(2026, 5, 27))])
    assert repo.latest_snapshot_date() == date(2026, 5, 27)
    assert repo.latest_snapshot_date(market="US") == date(2026, 5, 27)
    assert repo.latest_snapshot_date(market="CN") is None


def test_query_no_filter_returns_latest(repo):
    repo.bulk_upsert([
        _row("AAPL", snapshot_date=date(2026, 5, 26)),
        _row("AAPL", snapshot_date=date(2026, 5, 27)),
        _row("MSFT", snapshot_date=date(2026, 5, 27)),
    ])
    rows, total = repo.query()
    assert total == 2  # latest date only
    assert {r.ticker for r in rows} == {"AAPL", "MSFT"}


def test_query_price_range_filter(repo):
    repo.bulk_upsert([
        _row("LOW", price=Decimal("50")),
        _row("MID", price=Decimal("200")),
        _row("HI",  price=Decimal("500")),
    ])
    rows, total = repo.query(filters={"price_min": 100, "price_max": 300})
    assert total == 1
    assert rows[0].ticker == "MID"


def test_query_sector_in_filter(repo):
    repo.bulk_upsert([
        _row("AAPL", sector="Technology"),
        _row("JPM",  sector="Financial Services"),
        _row("XOM",  sector="Energy"),
    ])
    rows, total = repo.query(filters={"sector_in": ["Technology", "Energy"]})
    assert total == 2
    assert {r.ticker for r in rows} == {"AAPL", "XOM"}


def test_query_market_filter(repo):
    repo.bulk_upsert([
        _row("AAPL", market="US"),
        _row("600519.SH", market="CN"),
    ])
    rows, _ = repo.query(market=["CN"])
    assert {r.ticker for r in rows} == {"600519.SH"}


def test_query_sort_and_limit(repo):
    repo.bulk_upsert([
        _row("A", market_cap=Decimal("100")),
        _row("B", market_cap=Decimal("300")),
        _row("C", market_cap=Decimal("200")),
    ])
    rows, total = repo.query(sort_by="market_cap", sort_dir="desc", limit=2)
    assert total == 3
    assert [r.ticker for r in rows] == ["B", "C"]


def test_query_unknown_filter_ignored(repo):
    repo.bulk_upsert([_row("AAPL")])
    rows, total = repo.query(filters={"made_up_filter": 42})
    assert total == 1  # didn't crash, didn't drop the row


def test_cleanup_old_snapshots(repo):
    today = date.today()
    repo.bulk_upsert([
        _row("OLD", snapshot_date=today - timedelta(days=40)),
        _row("RECENT", snapshot_date=today - timedelta(days=10)),
        _row("NEW", snapshot_date=today),
    ])
    n = repo.cleanup_old_snapshots(keep_days=30)
    assert n == 1
    remaining = {r.ticker for r in repo.db.query(TickerSnapshot).all()}
    assert remaining == {"RECENT", "NEW"}


def test_query_recent_earnings_after_filter(repo):
    """recent_earnings_after keeps only rows with recent_earnings_date >= the cutoff."""
    repo.bulk_upsert([
        _row("EARLY", recent_earnings_date=date(2026, 1, 10)),
        _row("CUTOFF", recent_earnings_date=date(2026, 3, 1)),
        _row("AFTER", recent_earnings_date=date(2026, 4, 15)),
        _row("NONE"),  # recent_earnings_date=None — should be excluded
    ])
    rows, total = repo.query(filters={"recent_earnings_after": "2026-03-01"})
    tickers = {r.ticker for r in rows}
    assert tickers == {"CUTOFF", "AFTER"}
    assert total == 2


def test_query_recent_earnings_before_filter(repo):
    """recent_earnings_before keeps only rows with recent_earnings_date <= the cutoff."""
    repo.bulk_upsert([
        _row("EARLY", recent_earnings_date=date(2026, 1, 10)),
        _row("CUTOFF", recent_earnings_date=date(2026, 3, 1)),
        _row("AFTER", recent_earnings_date=date(2026, 4, 15)),
    ])
    rows, total = repo.query(filters={"recent_earnings_before": "2026-03-01"})
    tickers = {r.ticker for r in rows}
    assert tickers == {"EARLY", "CUTOFF"}
    assert total == 2


def test_query_perf_1y_range_filter(repo):
    """perf_1y_min keeps only rows with perf_1y >= the threshold."""
    repo.bulk_upsert([
        _row("FLAT",  perf_1y=Decimal("0.05")),
        _row("MID",   perf_1y=Decimal("0.10")),
        _row("HIGH",  perf_1y=Decimal("0.35")),
        _row("BELOW", perf_1y=Decimal("0.09")),
    ])
    rows, total = repo.query(filters={"perf_1y_min": 0.10})
    tickers = {r.ticker for r in rows}
    assert tickers == {"MID", "HIGH"}
    assert total == 2
