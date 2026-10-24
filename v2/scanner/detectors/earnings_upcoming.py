"""Earnings upcoming detector (M9.f) — forward-looking catalyst flag.

Fires when a ticker has a scheduled earnings event within the next
``lookahead_days`` calendar days. Distinct from ``EarningsSurpriseDetector``
which fires only AFTER a BEAT/MISS has been reported — this one is the
"about to be a catalyst" pre-event signal.

The earnings calendar is BULK-loaded once per scan by the runner (via
``ScannerService._load_earnings_calendar``) and injected into every
per-ticker ``ScanContext.upcoming_earnings_days_to``. Detector is then a
pure dict lookup — no per-ticker API call.

**Severity scales with proximity** — the closer to earnings, the more
urgent the catalyst risk / setup signal:

    d=0 (today)    severity = 5.0
    d=1 (tomorrow) severity = 5.0  (still maximum — last full trading day before)
    d=2            severity = 4.0
    d=3            severity = 3.0
    d=4            severity = 2.0
    d=5            severity = 1.0

Direction is always **neutral** — analysts can guess the surprise sign but
the detector deliberately doesn't (that's `EarningsSurpriseDetector`'s job
after the fact, or LLM/user judgement here). Composite-score's direction
logic treats neutral severities as zero, so PRE-EARN puts a ticker in
the watchlist as "needs review" without imposing a stance.

Pairs especially well with `BollingerSqueezeDetector` (statistical setup)
and `MultiHorizonBreakoutDetector` (technical setup) — a stock with a
squeeze AND earnings in 2 days is a classic explosive-move-ahead setup.
"""

from __future__ import annotations

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date as _parse_date
from v2.scanner.models import ScanContext


class EarningsUpcomingDetector(EventDetector):
    """Trigger on imminent (≤ N days) scheduled earnings."""

    name = "earnings_upcoming"

    def __init__(
        self,
        *,
        lookahead_days: int = 5,
        severity_today: float = 5.0,
        severity_min: float = 1.0,
    ) -> None:
        # severity at d=0 and d=1 both equal severity_today (peak); each
        # subsequent day decreases by 1.0, floored at severity_min.
        self._lookahead = lookahead_days
        self._sev_top = severity_today
        self._sev_min = severity_min

    def _severity_for_days(self, days_out: int) -> float:
        """Linear ramp: d=0/1 → severity_today, then -1.0 per extra day,
        floor at severity_min."""
        # max(days-1, 0) so d=0 and d=1 share the peak severity.
        steps = max(days_out - 1, 0)
        sev = self._sev_top - float(steps)
        return max(sev, self._sev_min)

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        # Bootstrap / config without calendar plumbing — exclude this ticker
        # from stats rather than returning a misleading "no upcoming earnings"
        # verdict that's actually "we don't know".
        if ctx is None or ctx.upcoming_earnings_days_to is None:
            return None

        if _parse_date(end_date) is None:
            return None

        days_to = ctx.upcoming_earnings_days_to.get(ticker)
        if days_to is None:
            # Calendar was loaded but this ticker has no scheduled event
            # within lookahead. Clean "ran, nothing fired" verdict.
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"no scheduled earnings in next {self._lookahead}d",
                components={"days_to_earnings": -1.0},
                asof_date=end_date,
            )

        d = int(days_to)
        # Out-of-window — runner's calendar load should already have filtered
        # these out, but be defensive.
        if d < 0 or d > self._lookahead:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"earnings in {d}d — outside {self._lookahead}d window",
                components={"days_to_earnings": float(d)},
                asof_date=end_date,
            )

        severity = self._severity_for_days(d)
        when = "today" if d == 0 else ("tomorrow" if d == 1 else f"in {d} days")
        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction="neutral",
            reason=f"earnings {when}",
            components={
                "days_to_earnings": float(d),
                "lookahead_days": float(self._lookahead),
            },
            asof_date=end_date,
        )
