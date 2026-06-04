from __future__ import annotations

from v2.scanner.eval.regimes import DEFAULT_CANDIDATES, classify_regimes


def weekly_scan_dates(start, end, trading_days, every=5):
    """Every ``every``-th trading day within the inclusive ``[start, end]`` window.

    Filters ``trading_days`` (ordered date strings) to those with
    ``start <= d <= end``, then keeps indices 0, every, 2*every, ...
    Pure and deterministic — no external dependencies.
    """
    in_window = [d for d in trading_days if start <= d <= end]
    return in_window[::every]


def build_schedule(
    trading_days,
    spy_prices,
    *,
    candidates=None,
    post_cutoff_start="2025-01-01",
    run_date,
    every=5,
):
    """Regime-segmented weekly scan-date schedule with a post-cutoff flag.

    Windows = ``candidates or DEFAULT_CANDIDATES`` plus a synthesized
    ``post_cutoff`` window ``[post_cutoff_start, run_date]``. All windows are
    classified together via ``classify_regimes(spy_prices, all_windows)``. For
    each classified window, emit one row per ``weekly_scan_dates`` pick:

        {"scan_date", "regime_name", "regime_label", "is_post_cutoff"}

    ``is_post_cutoff`` is ``scan_date >= post_cutoff_start``. Windows shouldn't
    overlap, so no dedup is performed on the flat output.
    """
    all_windows = list(candidates or DEFAULT_CANDIDATES)
    all_windows.append(
        {"name": "post_cutoff", "start": post_cutoff_start, "end": run_date}
    )

    classified = classify_regimes(spy_prices, all_windows)

    rows = []
    for window in classified:
        for d in weekly_scan_dates(window.start, window.end, trading_days, every):
            rows.append(
                {
                    "scan_date": d,
                    "regime_name": window.name,
                    "regime_label": window.label,
                    "is_post_cutoff": d >= post_cutoff_start,
                }
            )
    return rows
