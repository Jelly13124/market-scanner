"""Offline tests for the fixed train/val/test sample split (Task 2).

Sample isolation is the load-bearing discipline of the self-evolve loop: the
evolution reads train (propose) + val (keep/rollback) only — TEST is never
touched inside the loop. These tests pin the immutable windows, the
``sample_of`` date classifier, and the deterministic monthly ``rebalance_dates``.

Everything here is pure Python — no network, no data files.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from v2.self_evolve.samples import SAMPLES, rebalance_dates, sample_of


# ---------------------------------------------------------------------------
# 1. sample_of — date → sample name, non-overlapping windows
# ---------------------------------------------------------------------------


def test_sample_of_classifies_each_window():
    assert sample_of("2016-06-15") == "train"
    assert sample_of("2022-03-01") == "val"
    assert sample_of("2024-01-01") == "test"
    assert sample_of("2025-07-04") == "test"


def test_sample_of_boundaries_inclusive():
    # The closed endpoints of each window classify into that window.
    assert sample_of("2016-01-01") == "train"
    assert sample_of("2021-12-31") == "train"
    assert sample_of("2022-01-01") == "val"
    assert sample_of("2023-12-31") == "val"
    assert sample_of("2024-01-01") == "test"


def test_sample_of_before_all_is_none():
    assert sample_of("2015-12-31") is None
    assert sample_of("1999-01-01") is None


def test_windows_do_not_overlap():
    # No calendar date may classify into two samples. Walk every day across the
    # full span (plus a margin on each side) and assert each lands in at most
    # one window. This is the programmatic non-overlap guarantee.
    start = date(2014, 1, 1)
    end = date(2031, 12, 31)
    d = start
    one_day = timedelta(days=1)
    while d <= end:
        iso = d.isoformat()
        hits = [name for name in SAMPLES if _in_window(iso, name)]
        assert len(hits) <= 1, f"{iso} classified into multiple samples: {hits}"
        # sample_of must agree with the window membership.
        assert sample_of(iso) == (hits[0] if hits else None)
        d += one_day


def _in_window(iso: str, name: str) -> bool:
    lo, hi = SAMPLES[name]
    return lo <= iso <= hi


def test_samples_has_expected_windows():
    assert SAMPLES["train"] == ("2016-01-01", "2021-12-31")
    assert SAMPLES["val"] == ("2022-01-01", "2023-12-31")
    assert SAMPLES["test"] == ("2024-01-01", "2030-12-31")


# ---------------------------------------------------------------------------
# 2. rebalance_dates — first trading day of each month within the window
# ---------------------------------------------------------------------------


def _daily_calendar(start: date, end: date) -> list[str]:
    """Every weekday (Mon-Fri) in ``[start, end]`` as ascending ISO strings.

    A rough stand-in for a trading-day calendar — good enough to exercise the
    "first trading day of each month" logic without a real exchange calendar.
    """
    out: list[str] = []
    d = start
    one_day = timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:  # 0=Mon .. 4=Fri
            out.append(d.isoformat())
        d += one_day
    return out


def test_rebalance_dates_monthly_val_one_per_month():
    # ~2 years of weekday "trading days" spanning the val window and beyond.
    days = _daily_calendar(date(2021, 6, 1), date(2024, 6, 30))
    reb = rebalance_dates("val", days, freq="monthly")

    # Every returned date is inside the val window and ascending.
    assert reb == sorted(reb)
    assert all(SAMPLES["val"][0] <= d <= SAMPLES["val"][1] for d in reb)

    # 24 calendar months across 2022-2023 → exactly 24 rebalance dates.
    assert len(reb) == 24
    months = [d[:7] for d in reb]
    assert months == sorted(set(months))  # one per month, no dupes, ascending

    # Each is the FIRST trading day present for its month.
    by_month: dict[str, list[str]] = {}
    for d in days:
        if SAMPLES["val"][0] <= d <= SAMPLES["val"][1]:
            by_month.setdefault(d[:7], []).append(d)
    for d in reb:
        assert d == by_month[d[:7]][0]


def test_rebalance_dates_first_is_first_business_day_of_2022():
    days = _daily_calendar(date(2021, 6, 1), date(2024, 6, 30))
    reb = rebalance_dates("val", days, freq="monthly")
    # 2022-01-01 is a Saturday; first weekday is Monday 2022-01-03.
    assert reb[0] == "2022-01-03"
    assert reb[-1].startswith("2023-12")


def test_rebalance_dates_excludes_out_of_window_days():
    # Days entirely outside the window must never appear, even if passed in.
    days = _daily_calendar(date(2021, 6, 1), date(2024, 6, 30))
    reb = rebalance_dates("val", days, freq="monthly")
    assert all(not d.startswith("2021") for d in reb)
    assert all(not d.startswith("2024") for d in reb)


def test_rebalance_dates_train_window():
    days = _daily_calendar(date(2016, 1, 1), date(2021, 12, 31))
    reb = rebalance_dates("train", days, freq="monthly")
    # 6 years × 12 months = 72 rebalance dates, all in [2016, 2021].
    assert len(reb) == 72
    assert all(SAMPLES["train"][0] <= d <= SAMPLES["train"][1] for d in reb)


# ---------------------------------------------------------------------------
# 3. edge cases
# ---------------------------------------------------------------------------


def test_rebalance_dates_empty_input():
    assert rebalance_dates("val", []) == []


def test_rebalance_dates_no_days_in_window():
    # All supplied days fall outside the val window → empty result.
    days = _daily_calendar(date(2016, 1, 1), date(2016, 12, 31))
    assert rebalance_dates("val", days, freq="monthly") == []


def test_rebalance_dates_unknown_sample_raises():
    with pytest.raises(KeyError):
        rebalance_dates("holdout", ["2022-01-03"], freq="monthly")


def test_rebalance_dates_unknown_freq_raises():
    days = _daily_calendar(date(2022, 1, 1), date(2022, 3, 31))
    with pytest.raises(ValueError):
        rebalance_dates("val", days, freq="weekly")
