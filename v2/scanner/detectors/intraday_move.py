"""Intraday move detector.

Three orthogonal sub-signals on today's OHLC bar:

  * ``close_vs_open`` — intraday return (open → close). Catches days where the
    market dominated the action, regardless of overnight gap.
  * ``gap``           — overnight return (prev_close → open). Catches reactions
    to overnight catalysts (earnings, news, macro).
  * ``range``         — intraday volatility (high − low) / open. Catches
    wide-swing days even when the close ends near the open.

Each sub-signal fires when EITHER its absolute magnitude crosses a hard
threshold OR its z-score against a trailing-window distribution does.
Severity is the most extreme of the three z-scores, signed by ``close_vs_open``
(or neutral when only ``range`` fires).

**Benchmark adjustment**: when ``ctx.benchmark_prices`` is populated (the
runner pre-fetches SPY/QQQ once and shares the same list), ``close_vs_open``
and ``gap`` are reported net of the benchmark's same-day move so a stock
that simply tracked the market doesn't trigger. ``range`` stays raw —
volatility is not a market-relative quantity. Both today's value and the
trailing-window baseline are adjusted, so the z-score stays apples-to-apples.

Complements ``VolumeAnomalyDetector``: that one fires on volume anomalies
specifically when the day's return is FLAT (anti-gate); this one owns the
case where price moved.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date as _parse_date
from v2.scanner.models import ScanContext




class IntradayMoveDetector(EventDetector):
    """Trigger on outsized intraday return, overnight gap, or intraday range."""

    name = "intraday_move"

    def __init__(
        self,
        *,
        lookback_days: int = 90,
        z_window: int = 60,
        close_vs_open_pct: float = 0.04,
        gap_pct: float = 0.03,
        range_pct: float = 0.06,
        z_threshold: float = 2.5,
    ) -> None:
        self._lookback_days = lookback_days
        self._z_window = z_window
        self._cvo_pct = close_vs_open_pct
        self._gap_pct = gap_pct
        self._range_pct = range_pct
        self._z_thresh = z_threshold

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        today = _parse_date(end_date)
        if today is None:
            return None

        start = (today - timedelta(days=self._lookback_days)).isoformat()
        prices = fd.get_prices(ticker, start, end_date)
        if not prices or len(prices) < self._z_window + 2:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        # Today is the most recent bar; we need yesterday for the gap.
        today_bar = prices_sorted[-1]
        prev_bar = prices_sorted[-2]

        # OHLC fields are nullable on some providers — skip a sub-signal cleanly
        # rather than crash. ``open`` is the load-bearing field: without it,
        # nothing in this detector works.
        if today_bar.open is None or today_bar.open <= 0:
            return None

        today_open = float(today_bar.open)
        today_close = float(today_bar.close)
        today_high = float(today_bar.high) if today_bar.high is not None else None
        today_low = float(today_bar.low) if today_bar.low is not None else None
        prev_close = float(prev_bar.close) if prev_bar.close is not None else None
        if prev_close is None or prev_close <= 0:
            return None

        # --- benchmark same-day cvo/gap lookup (SPY/QQQ-relative) -----------
        # Production: runner pre-computes the date → (cvo, gap) dict once and
        # shares the same reference across every per-ticker ScanContext.
        # Test/standalone: when the precomputed dict isn't injected but raw
        # ``benchmark_prices`` are, we build the dict inline as a fallback —
        # cost is one O(W) pass on first call per ticker, still O(1) per bar
        # in the trailing-window loop.
        bench_cvo_gap: dict[str, tuple[float, float]] = (
            ctx.benchmark_cvo_gap_by_date if ctx is not None else None
        ) or {}
        if not bench_cvo_gap and ctx is not None and ctx.benchmark_prices:
            sorted_bench = sorted(ctx.benchmark_prices, key=lambda p: p.time[:10])
            prev_b: object | None = None
            for p in sorted_bench:
                if p.open is None or p.open <= 0:
                    prev_b = p
                    continue
                op = float(p.open)
                cl = float(p.close) if p.close is not None else op
                bcvo_ = (cl - op) / op
                bgap_ = 0.0
                if prev_b is not None and getattr(prev_b, "close", None) is not None:
                    pc = float(prev_b.close)
                    if pc > 0:
                        bgap_ = (op - pc) / pc
                bench_cvo_gap[p.time[:10]] = (bcvo_, bgap_)
                prev_b = p
        use_adjusted = len(bench_cvo_gap) > 0

        def _bench_cvo_gap(date_str: str, _prev_date_str: str = "") -> tuple[float, float]:
            """Return (bench_cvo, bench_gap) for the given date; (0, 0) if the
            benchmark has no bar on that date (silent fallback). The
            ``_prev_date_str`` kwarg is kept for API compat; the dict already
            accounts for the previous bar's close."""
            return bench_cvo_gap.get(date_str, (0.0, 0.0))

        # --- compute today's three sub-signals -------------------------------
        raw_cvo = (today_close - today_open) / today_open
        raw_gap = (today_open - prev_close) / prev_close
        spy_cvo, spy_gap = (0.0, 0.0)
        if use_adjusted:
            spy_cvo, spy_gap = _bench_cvo_gap(today_bar.time[:10], prev_bar.time[:10])

        cvo = raw_cvo - spy_cvo if use_adjusted else raw_cvo
        gap = raw_gap - spy_gap if use_adjusted else raw_gap
        rng: float | None = None
        if today_high is not None and today_low is not None:
            rng = (today_high - today_low) / today_open

        # --- trailing distributions for each sub-signal ----------------------
        # Build series over the trailing z_window bars (excluding today).
        # When benchmark is available, subtract its same-day cvo/gap from each
        # historical bar so the z-score baseline is apples-to-apples with today.
        window = prices_sorted[-(self._z_window + 1) : -1]

        cvo_series: list[float] = []
        gap_series: list[float] = []
        rng_series: list[float] = []
        prev_bar_for_gap = None
        for i, p in enumerate(window):
            if p.open is None or p.open <= 0 or p.close is None:
                prev_bar_for_gap = p
                continue
            p_cvo = (float(p.close) - float(p.open)) / float(p.open)
            p_gap: float | None = None
            if prev_bar_for_gap is not None and prev_bar_for_gap.close is not None:
                pc = float(prev_bar_for_gap.close)
                if pc > 0:
                    p_gap = (float(p.open) - pc) / pc

            if use_adjusted:
                prev_date_str = (
                    prev_bar_for_gap.time[:10] if prev_bar_for_gap is not None else ""
                )
                b_cvo, b_gap = _bench_cvo_gap(p.time[:10], prev_date_str)
                p_cvo = p_cvo - b_cvo
                if p_gap is not None:
                    p_gap = p_gap - b_gap

            cvo_series.append(p_cvo)
            if p_gap is not None:
                gap_series.append(p_gap)
            if p.high is not None and p.low is not None:
                rng_series.append((float(p.high) - float(p.low)) / float(p.open))
            prev_bar_for_gap = p

        def _mean_std(series: list[float], floor: float = 0.005) -> tuple[float, float] | None:
            """Return (mean, std-with-floor) or None when sample is too small.

            Note: cvo and gap are naturally near-zero-mean (close-to-open and
            overnight returns), so demeaning is a small correction. ``range``
            (high-low)/open is strictly positive with a meaningful baseline
            mean — without demeaning ``z = today/std`` is a magnitude not a
            z-score, and even normal-range days fire the gate (production
            bug observed 2026-05-16: range firing on 14/18 IDAY triggers
            with values 2-4% — that's typical, not anomalous).
            """
            if len(series) < 5:
                return None
            arr = np.array(series)
            mean = float(arr.mean())
            std = max(float(arr.std(ddof=1)), floor)
            return mean, std

        cvo_stats = _mean_std(cvo_series)
        gap_stats = _mean_std(gap_series)
        rng_stats = _mean_std(rng_series)

        z_cvo = ((cvo - cvo_stats[0]) / cvo_stats[1]) if cvo_stats is not None else 0.0
        z_gap = ((gap - gap_stats[0]) / gap_stats[1]) if gap_stats is not None else 0.0
        z_rng = (
            (rng - rng_stats[0]) / rng_stats[1]
            if (rng is not None and rng_stats is not None) else 0.0
        )

        # --- gates: (absolute magnitude crosses threshold) OR (z crosses) ----
        cvo_hit = (abs(cvo) >= self._cvo_pct) or (abs(z_cvo) >= self._z_thresh)
        gap_hit = (abs(gap) >= self._gap_pct) or (abs(z_gap) >= self._z_thresh)
        # range is one-sided (only "wide" is interesting, not "narrow").
        rng_hit = rng is not None and ((rng >= self._range_pct) or (z_rng >= self._z_thresh))

        components = {
            "today_open": float(today_open),
            "today_close": float(today_close),
            "today_high": float(today_high) if today_high is not None else 0.0,
            "today_low": float(today_low) if today_low is not None else 0.0,
            "prev_close": float(prev_close),
            "close_vs_open": float(cvo),
            "gap": float(gap),
            "range": float(rng) if rng is not None else 0.0,
            "z_cvo": float(z_cvo),
            "z_gap": float(z_gap),
            "z_range": float(z_rng),
            # SPY/QQQ-relative diagnostics
            "raw_cvo": float(raw_cvo),
            "raw_gap": float(raw_gap),
            "spy_cvo": float(spy_cvo),
            "spy_gap": float(spy_gap),
            "adjusted_cvo": float(cvo),
            "adjusted_gap": float(gap),
            "benchmark_used": 1.0 if use_adjusted else 0.0,
        }

        if not (cvo_hit or gap_hit or rng_hit):
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=(
                    f"cvo {cvo*100:+.2f}% (z={z_cvo:+.2f}); "
                    f"gap {gap*100:+.2f}% (z={z_gap:+.2f}); "
                    f"range {(rng or 0)*100:.2f}% (z={z_rng:+.2f})"
                ),
                components=components,
                asof_date=end_date,
            )

        # --- direction: signed by close_vs_open; neutral when only range fires
        if cvo > 1e-4:
            direction = "bullish"
            sign = 1.0
        elif cvo < -1e-4:
            direction = "bearish"
            sign = -1.0
        else:
            direction = "neutral"
            sign = 1.0

        # severity = max absolute z, signed
        severity_mag = max(abs(z_cvo), abs(z_gap), abs(z_rng))
        severity = severity_mag * sign

        bits: list[str] = []
        if cvo_hit:
            bits.append(f"cvo {cvo*100:+.2f}% (z={z_cvo:+.2f})")
        if gap_hit:
            bits.append(f"gap {gap*100:+.2f}% (z={z_gap:+.2f})")
        if rng_hit:
            bits.append(f"range {(rng or 0)*100:.2f}% (z={z_rng:+.2f})")

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction=direction,
            reason="; ".join(bits),
            components=components,
            asof_date=end_date,
        )
