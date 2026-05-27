"""TickerSnapshot ORM smoke test — verifies column shape and uniqueness."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.backend.database.models import Base, TickerSnapshot


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_insert_minimal_row(session):
    row = TickerSnapshot(
        ticker="AAPL",
        market="US",
        snapshot_date=date(2026, 5, 27),
        price=Decimal("210.50"),
        market_cap=Decimal("3200000000000"),
        sector="Technology",
    )
    session.add(row)
    session.commit()
    out = session.query(TickerSnapshot).filter_by(ticker="AAPL").one()
    assert out.market == "US"
    assert out.sector == "Technology"
    assert out.price == Decimal("210.50")


def test_full_field_set(session):
    row = TickerSnapshot(
        ticker="NVDA", market="US", snapshot_date=date(2026, 5, 27),
        price=Decimal("950.00"), prev_close=Decimal("940.00"),
        change_pct=Decimal("1.0638"), volume=120_000_000,
        avg_volume_10d=100_000_000, rel_volume=Decimal("1.200"),
        market_cap=Decimal("2300000000000"),
        pe_ttm=Decimal("65.123"), pe_forward=Decimal("45.000"),
        pb=Decimal("40.500"), ps=Decimal("30.000"), peg=Decimal("1.500"),
        eps_growth_yoy=Decimal("1.1033"), revenue_growth_yoy=Decimal("0.7820"),
        roe=Decimal("0.9500"), profit_margin=Decimal("0.4200"),
        dividend_yield_pct=Decimal("0.0200"), beta=Decimal("1.500"),
        sector="Technology", industry="Semiconductors", exchange="NASDAQ",
        analyst_rating="strong_buy", analyst_count=45,
        target_mean_price=Decimal("1100.00"),
        recent_earnings_date=date(2026, 5, 22),
        upcoming_earnings_date=date(2026, 8, 21),
        perf_1d=Decimal("0.0106"), perf_5d=Decimal("0.0312"),
        perf_1m=Decimal("0.0820"), perf_3m=Decimal("0.1750"),
        perf_ytd=Decimal("0.4500"), perf_1y=Decimal("1.2300"),
        data_source="yfinance",
    )
    session.add(row)
    session.commit()
    out = session.query(TickerSnapshot).filter_by(ticker="NVDA").one()
    assert out.analyst_rating == "strong_buy"
    assert out.perf_1y == Decimal("1.2300")


def test_unique_ticker_date_constraint(session):
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 27), price=Decimal("210")))
    session.commit()
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 27), price=Decimal("220")))
    with pytest.raises(IntegrityError):
        session.commit()


def test_different_dates_allowed(session):
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 26), price=Decimal("208")))
    session.add(TickerSnapshot(ticker="AAPL", market="US",
                               snapshot_date=date(2026, 5, 27), price=Decimal("210")))
    session.commit()
    assert session.query(TickerSnapshot).filter_by(ticker="AAPL").count() == 2
