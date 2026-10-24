"""As-of line-item lookups in ``factors`` — 60-day availability lag + prior-year.

These mirror the existing ``_latest_lagged_metric`` discipline exactly: a record
whose ``report_period`` falls inside the 60-day window before ``asof`` (or after
it) is NOT yet knowable and is excluded — the HARD no-lookahead clamp. The
prior-year helper returns the record one fiscal step older than the latest
knowable one, for asset-growth-style YoY factors.

Offline, pure-Python: records are synthetic ``SimpleNamespace`` fakes exposing
only ``report_period`` (+ any payload fields). No network, no pandas.
"""

from __future__ import annotations

from types import SimpleNamespace

from v2.self_evolve.factors import (
    FUNDAMENTAL_AVAILABILITY_LAG_DAYS,
    _latest_lagged_line_item,
    _prior_year_line_item,
)


def _li(report_period: str, **payload) -> SimpleNamespace:
    return SimpleNamespace(report_period=report_period, **payload)


# ---------------------------------------------------------------------------
# _latest_lagged_line_item — 60d lag clamp
# ---------------------------------------------------------------------------


def test_latest_lagged_excludes_record_within_lag_window():
    # asof so the 2023-12-31 record is only ~31 days old (< 60d) → NOT knowable.
    # The 2022-12-31 record (well over 60d) wins.
    asof = "2024-01-31"
    items = [
        _li("2023-12-31", total_assets=1000.0),
        _li("2022-12-31", total_assets=900.0),
    ]
    got = _latest_lagged_line_item(items, asof)
    assert got is not None
    assert got.report_period == "2022-12-31"
    assert got.total_assets == 900.0


def test_latest_lagged_record_exactly_at_cutoff_is_knowable():
    # report_period == asof - 60d is exactly knowable (<= cutoff), so it wins.
    asof = "2024-03-01"
    # 2024-03-01 minus 60 days = 2024-01-01.
    items = [_li("2024-01-01", total_assets=1.0), _li("2023-01-01", total_assets=2.0)]
    got = _latest_lagged_line_item(items, asof)
    assert got is not None
    assert got.report_period == "2024-01-01"


def test_latest_lagged_picks_newest_knowable_of_three():
    asof = "2024-06-30"
    items = [
        _li("2023-12-31", total_assets=300.0),
        _li("2022-12-31", total_assets=200.0),
        _li("2021-12-31", total_assets=100.0),
    ]
    got = _latest_lagged_line_item(items, asof)
    assert got is not None
    assert got.report_period == "2023-12-31"


def test_latest_lagged_all_too_recent_returns_none():
    asof = "2024-01-15"
    # Both records are inside the 60-day window before asof → nothing knowable.
    items = [_li("2024-01-10"), _li("2023-12-20")]
    assert _latest_lagged_line_item(items, asof) is None


def test_latest_lagged_empty_returns_none():
    assert _latest_lagged_line_item([], "2024-06-30") is None


def test_latest_lagged_skips_unparseable_report_period():
    asof = "2024-06-30"
    items = [
        _li("not-a-date", total_assets=999.0),
        _li("2023-12-31", total_assets=300.0),
    ]
    got = _latest_lagged_line_item(items, asof)
    assert got is not None
    assert got.report_period == "2023-12-31"


def test_latest_lagged_never_raises_on_garbage():
    # Missing/None report_period and junk types must not raise.
    items = [_li(None), _li("garbage"), SimpleNamespace()]
    assert _latest_lagged_line_item(items, "2024-06-30") is None


# ---------------------------------------------------------------------------
# _prior_year_line_item — record one fiscal step older than the latest knowable
# ---------------------------------------------------------------------------


def test_prior_year_is_record_below_latest_knowable():
    asof = "2024-06-30"
    items = [
        _li("2023-12-31", total_assets=300.0),
        _li("2022-12-31", total_assets=200.0),
        _li("2021-12-31", total_assets=100.0),
    ]
    # Latest knowable = 2023-12-31, so prior year = 2022-12-31.
    prior = _prior_year_line_item(items, asof)
    assert prior is not None
    assert prior.report_period == "2022-12-31"
    assert prior.total_assets == 200.0


def test_prior_year_when_latest_is_lag_excluded():
    # 2023-12-31 is < 60d old → excluded; latest knowable = 2022-12-31, so the
    # prior-year record is 2021-12-31.
    asof = "2024-01-31"
    items = [
        _li("2023-12-31", total_assets=300.0),
        _li("2022-12-31", total_assets=200.0),
        _li("2021-12-31", total_assets=100.0),
    ]
    prior = _prior_year_line_item(items, asof)
    assert prior is not None
    assert prior.report_period == "2021-12-31"


def test_prior_year_only_one_knowable_returns_none():
    asof = "2024-06-30"  # cutoff = 2024-05-01
    # Only 2023-12-31 is knowable; 2024-05-15 is inside the 60-day lag window
    # (> cutoff) → excluded. With a single knowable record there is no prior.
    items = [_li("2023-12-31"), _li("2024-05-15")]
    assert _latest_lagged_line_item(items, asof) is not None
    assert _prior_year_line_item(items, asof) is None


def test_prior_year_empty_returns_none():
    assert _prior_year_line_item([], "2024-06-30") is None


def test_prior_year_no_knowable_returns_none():
    asof = "2024-01-15"
    items = [_li("2024-01-10"), _li("2023-12-20")]
    assert _prior_year_line_item(items, asof) is None


def test_prior_year_skips_unparseable_between_records():
    asof = "2024-06-30"
    items = [
        _li("2023-12-31", total_assets=300.0),
        _li("bad-date", total_assets=999.0),
        _li("2022-12-31", total_assets=200.0),
    ]
    # Latest knowable = 2023-12-31; prior = 2022-12-31 (unparseable skipped).
    prior = _prior_year_line_item(items, asof)
    assert prior is not None
    assert prior.report_period == "2022-12-31"


def test_lag_constant_is_60():
    assert FUNDAMENTAL_AVAILABILITY_LAG_DAYS == 60
