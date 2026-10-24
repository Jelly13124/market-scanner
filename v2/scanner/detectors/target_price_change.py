"""Target-price change detector (M9.d).

Fires when the consensus analyst target_median has moved meaningfully over
the last N days. This is the detector users intuitively expect when they
say "analysts changed their target price for this stock" — it specifically
captures forward-looking analyst conviction shifts, distinct from rating
word changes (``analyst_rating``) which only fire on Buy/Sell/Hold
re-labelings.

Data source: per-ticker daily snapshots of ``analyst_price_targets``
persisted in the DB by ``ScannerService`` at the start of each scan
(table ``analyst_target_snapshots``, unique on ``(ticker, asof_date)``).
The runner pre-loads the trailing N days into
``ScanContext.target_snapshots`` so the detector is a pure function of
the injected history.

Bootstrap: at least 2 daily snapshots are needed to compute a change.
On the very first scan day this returns ``None`` for every ticker. Once
a 2nd day of snapshots accumulates the detector starts firing on the
real signal. This is documented in the detector's ``None`` reason and
in ``progress.md``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date as _parse_date
from v2.scanner.models import ScanContext




class TargetPriceChangeDetector(EventDetector):
    """Trigger on a meaningful drift in median analyst target over N days."""

    name = "target_price_change"

    def __init__(
        self,
        *,
        lookback_days: int = 7,
        min_pct_change: float = 0.05,
        severity_scale: float = 0.02,
        severity_cap: float = 5.0,
    ) -> None:
        # ``lookback_days`` is the maximum window we'll look back for the
        # comparison snapshot. We pick the OLDEST snapshot in that window
        # (not "exactly N days ago") so the detector tolerates weekend
        # gaps + missed scan days gracefully.
        self._lookback = lookback_days
        self._min_pct = min_pct_change
        # severity = pct_change / scale → a 5% change → severity 2.5.
        self._scale = severity_scale
        self._cap = severity_cap

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

        snapshots = (ctx.target_snapshots if ctx is not None else None) or []
        # Need at least 2 distinct dates to compute change. Single-row
        # bootstrap day → exclude this ticker from stats (return None).
        if len(snapshots) < 2:
            return None

        # Today's snapshot — the newest entry within the window. ``snapshots``
        # is oldest→newest by repo contract. Snapshot rows are either
        # ``AnalystTargetSnapshot`` ORM instances (production) or the
        # ``_Snapshot`` duck-type used in tests; both expose ``asof_date``,
        # ``target_median``, ``target_mean`` as plain attributes — no need
        # for ``getattr`` defensiveness on field presence.
        today_row = snapshots[-1]
        today_target = today_row.target_median
        if today_target is None or today_target <= 0:
            return None

        # Find the oldest snapshot within ``lookback_days`` (inclusive). We
        # use the OLDEST so a 7-day target shift can use up to 7 calendar
        # days of base; if only 2 days of history exist we use yesterday.
        cutoff = today - timedelta(days=self._lookback)
        baseline_row = None
        for row in snapshots[:-1]:  # exclude today
            row_date = _parse_date(row.asof_date)
            if row_date is None:
                continue
            if cutoff <= row_date <= today:
                baseline_row = row
                break  # snapshots are oldest→newest, this is the oldest in-window
        if baseline_row is None:
            return None

        baseline_target = baseline_row.target_median
        if baseline_target is None or baseline_target <= 0:
            return None

        pct_change = (today_target - baseline_target) / baseline_target

        components: dict[str, float] = {
            "today_target_median": float(today_target),
            "baseline_target_median": float(baseline_target),
            "pct_change": float(pct_change),
            "lookback_days": float(self._lookback),
            "snapshots_available": float(len(snapshots)),
        }
        # Surface today's target_mean too — useful tiebreaker when median
        # is unchanged but the mean shifted (an outlier analyst moved).
        today_mean = today_row.target_mean
        if today_mean is not None:
            components["today_target_mean"] = float(today_mean)

        if abs(pct_change) < self._min_pct:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=(
                    f"target_median {pct_change*100:+.2f}% over "
                    f"{self._lookback}d (need ≥{self._min_pct*100:.1f}%)"
                ),
                components=components,
                asof_date=end_date,
            )

        severity_mag = min(abs(pct_change) / self._scale, self._cap)
        sign = 1.0 if pct_change > 0 else -1.0
        severity = severity_mag * sign
        direction = "bullish" if pct_change > 0 else "bearish"

        reason = (
            f"target_median {baseline_target:.2f} → {today_target:.2f} "
            f"({pct_change*100:+.2f}% since {baseline_row.asof_date})"
        )

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction=direction,
            reason=reason,
            components=components,
            asof_date=end_date,
        )
