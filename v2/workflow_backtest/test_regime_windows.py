from v2.workflow_backtest.regime_windows import weekly_scan_dates, build_schedule
from v2.data.models import Price


def test_weekly_scan_dates_every_5():
    days = [f"2025-03-{i:02d}" for i in range(1, 21)]  # 20 ordered date strings
    out = weekly_scan_dates("2025-03-01", "2025-03-20", days, every=5)
    assert out == ["2025-03-01", "2025-03-06", "2025-03-11", "2025-03-16"]


def test_weekly_scan_dates_respects_window():
    days = ["2022-01-05", "2022-06-01", "2025-03-10"]
    assert weekly_scan_dates("2025-01-01", "2025-12-31", days, every=1) == ["2025-03-10"]


def test_build_schedule_flags_post_cutoff():
    # 2 candidate windows: one in 2022 (pre-cutoff), one in 2025 (post-cutoff).
    cands = [{"name": "bear_2022", "start": "2022-01-03", "end": "2022-03-31"},
             {"name": "win_2025", "start": "2025-03-01", "end": "2025-03-31"}]
    trading_days = ["2022-01-03", "2022-02-01", "2022-03-01", "2025-03-03", "2025-03-10", "2025-03-17"]
    spy = [Price(open=400, close=400, high=400, low=400, volume=1, time=d) for d in trading_days]
    sched = build_schedule(trading_days, spy, candidates=cands, post_cutoff_start="2025-01-01",
                           run_date="2025-04-01", every=1)
    by_post = {row["is_post_cutoff"] for row in sched}
    assert by_post == {True, False}
    assert all(row["is_post_cutoff"] for row in sched if row["scan_date"].startswith("2025"))
    assert all(not row["is_post_cutoff"] for row in sched if row["scan_date"].startswith("2022"))
    assert all("regime_label" in row for row in sched)
