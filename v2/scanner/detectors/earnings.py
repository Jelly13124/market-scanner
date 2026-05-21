"""Earnings detectors.

Two detectors live in this module:

* ``EarningsSurpriseDetector`` — fires AFTER a BEAT/MISS, severity z-scored
  against trailing 4 quarters. Retained as a registered class (importable from
  tests / legacy configs) but unregistered from ``ALL_DETECTORS`` in favor of
  the unified detector below.
* ``EarningsEventDetector`` — unified "earnings catalyst window" signal that
  covers both 5 business days BEFORE a scheduled report (from the bulk
  earnings calendar in ``ScanContext.upcoming_earnings_days_to``) and 5
  business days AFTER a filing (from ``fd.get_earnings_history``). One
  severity scalar, components include a signed ``biz_days_to_event`` and a
  ``phase`` flag (1 = pre-event, 2 = post-event).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.data.models import EarningsRecord
from v2.event_study.filters import filter_retrospective_earnings
from v2.scanner.detectors.base import EventDetector, EventTrigger
from v2.scanner.models import ScanContext


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def _business_days_between(start: date, end: date) -> int:
    """Inclusive count of weekdays between two dates."""
    if start > end:
        return -_business_days_between(end, start)
    days = 0
    cur = start
    while cur < end:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def _surprise_pct(actual: float | None, estimate: float | None) -> float | None:
    """Continuous surprise as % of |estimate|. Returns None when not computable."""
    if actual is None or estimate is None:
        return None
    if estimate == 0:
        return None
    return (actual - estimate) / abs(estimate)


class EarningsSurpriseDetector(EventDetector):
    """Trigger on fresh earnings filings with BEAT/MISS."""

    name = "earnings_surprise"

    def __init__(
        self,
        *,
        window_days: int = 5,
        history_quarters: int = 4,
        categorical_floor_z: float = 2.0,
        # ~5 years of quarters — enough trailing history for the z-score to
        # find 4 prior surprises even when replaying older scan dates in a
        # backtest. yfinance's get_earnings_dates caps around 25 anyway.
        fetch_limit: int = 20,
    ) -> None:
        self._window_days = window_days
        self._history_quarters = history_quarters
        self._floor_z = categorical_floor_z
        self._fetch_limit = fetch_limit

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        records = fd.get_earnings_history(ticker, limit=self._fetch_limit)
        if not records:
            return None

        records = filter_retrospective_earnings(records)
        # Drop records FD returned without a filing_date — defensive,
        # filter_retrospective_earnings already drops most via try/except, but
        # the contract for downstream sort is strict-str.
        records = [r for r in records if r.filing_date]
        if not records:
            return None

        # Sort by filing_date desc (most recent first)
        records = sorted(records, key=lambda r: r.filing_date, reverse=True)

        # Filter to filings AS OF end_date — providers that return a fresh
        # trailing history (yfinance) will include filings AFTER end_date when
        # we're replaying backtests. Without this filter, the "latest" record
        # is always today's filing regardless of scan_date and the detector
        # never fires for any historical date.
        try:
            today = _parse_date(end_date)
        except (ValueError, TypeError):
            return None

        as_of = [r for r in records if _parse_date(r.filing_date) <= today]
        if not as_of:
            return None
        latest = as_of[0]
        # Position of `latest` inside the full sorted list — older records
        # come after it. ``records[latest_idx + 1:]`` is the trailing history
        # we want to z-score against.
        latest_idx = records.index(latest)

        try:
            filing = _parse_date(latest.filing_date)
        except (ValueError, TypeError):
            return None

        biz_days = _business_days_between(filing, today)
        if biz_days < 0 or biz_days > self._window_days:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"latest filing {latest.filing_date} is {biz_days} biz-days from {end_date}",
                asof_date=end_date,
            )

        q = latest.quarterly
        if q is None or q.eps_surprise is None:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason="no quarterly eps_surprise on latest filing",
                asof_date=end_date,
            )

        label = q.eps_surprise.upper()
        if label == "MEET":
            return EventTrigger(
                detector=self.name,
                triggered=False,
                direction="neutral",
                reason="MEET — no surprise",
                asof_date=end_date,
            )

        direction = "bullish" if label == "BEAT" else "bearish"
        sign = 1.0 if direction == "bullish" else -1.0

        # Build cross-sectional std of trailing surprises for z-scoring this one.
        # Slice STARTS at latest_idx + 1 (not 1) so backtest mode walks back
        # from the as-of filing rather than from today's newest record.
        current_surprise = _surprise_pct(q.earnings_per_share, q.estimated_earnings_per_share)
        history_pcts: list[float] = []
        for r in records[latest_idx + 1 : latest_idx + 1 + self._history_quarters]:
            if r.quarterly is None:
                continue
            s = _surprise_pct(
                r.quarterly.earnings_per_share,
                r.quarterly.estimated_earnings_per_share,
            )
            if s is not None:
                history_pcts.append(s)

        components: dict[str, float] = {
            "biz_days_since_filing": float(biz_days),
            "history_n": float(len(history_pcts)),
        }

        if current_surprise is not None and len(history_pcts) >= 2:
            hist = np.array(history_pcts)
            mu = float(hist.mean())
            sigma_raw = float(hist.std(ddof=1))
            # Std floor: 5% of estimate. Without this, an ultra-stable history
            # (e.g. four consecutive identical surprises) collapses std to ~0
            # and z explodes by orders of magnitude — same pattern that gave
            # GEHC insider z=+55,257,210,785,000 before the insider-detector
            # fix. When the baseline is uninformative, fall back to the
            # categorical floor.
            sigma_floor = 0.05
            if sigma_raw < sigma_floor:
                severity = self._floor_z * sign
                components["surprise_pct"] = float(current_surprise)
                components["history_mean"] = float(mu)
                components["history_std"] = float(sigma_raw)
                components["raw_z"] = 0.0  # floor applied — z not computed
            else:
                z = (current_surprise - mu) / sigma_raw
                # Floor at the categorical baseline so a tiny BEAT still scores like BEAT.
                severity = max(abs(z), self._floor_z) * sign
                components["surprise_pct"] = float(current_surprise)
                components["history_mean"] = float(mu)
                components["history_std"] = float(sigma_raw)
                components["raw_z"] = float(z)
        else:
            severity = self._floor_z * sign
            if current_surprise is not None:
                components["surprise_pct"] = float(current_surprise)

        reason = (
            f"{label} {latest.source_type or '?'} filed {latest.filing_date}; "
            f"|z|={abs(severity):.2f}"
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


class EarningsEventDetector(EventDetector):
    """Unified earnings-window detector — fires pre- OR post-event.

    Pre-event side reads ``ctx.upcoming_earnings_days_to[ticker]`` (set by
    the runner's bulk calendar load); severity scales 5 → 1 across days
    +0 → +5 with d=0/d=1 sharing the peak. Direction is neutral.

    Post-event side reads ``fd.get_earnings_history`` and looks for the
    most recent filing whose ``filing_date`` ≤ ``end_date`` and lies inside
    the last ``post_window_days`` business days. Severity is the magnitude
    of the EPS surprise z-scored against trailing ``history_quarters``
    surprises, floored at ``categorical_floor_z``. Direction is bullish
    (BEAT) or bearish (MISS); MEET → ``triggered=False``.

    When both sides match (rare — would require two earnings in ~11 days),
    the side with smaller ``|biz_days|`` wins; tie breaks to the post side
    (concrete result beats anticipation).
    """

    name = "earnings_event"

    def __init__(
        self,
        *,
        post_window_days: int = 5,
        pre_window_days: int = 5,
        history_quarters: int = 4,
        categorical_floor_z: float = 2.0,
        fetch_limit: int = 20,
        pre_severity_top: float = 5.0,
        pre_severity_min: float = 1.0,
    ) -> None:
        self._post_window = post_window_days
        self._pre_window = pre_window_days
        self._history_quarters = history_quarters
        self._floor_z = categorical_floor_z
        self._fetch_limit = fetch_limit
        self._pre_top = pre_severity_top
        self._pre_min = pre_severity_min

    def _pre_severity_for_days(self, days_out: int) -> float:
        # Mirrors the old EarningsUpcomingDetector ramp: d=0 and d=1 share the
        # peak (last full trading day before report = same urgency as day-of).
        steps = max(days_out - 1, 0)
        return max(self._pre_top - float(steps), self._pre_min)

    def detect(
        self,
        ticker: str,
        end_date: str,
        fd: DataClient,
        *,
        ctx: ScanContext | None = None,
    ) -> EventTrigger | None:
        try:
            today = _parse_date(end_date)
        except (ValueError, TypeError):
            return None

        # ---- 1. Pre-event side -----------------------------------------
        pre_days_to: int | None = None
        if ctx is not None and ctx.upcoming_earnings_days_to is not None:
            days_to = ctx.upcoming_earnings_days_to.get(ticker)
            if days_to is not None:
                d = int(days_to)
                if 0 <= d <= self._pre_window:
                    pre_days_to = d

        # ---- 2. Post-event side ----------------------------------------
        post_record = None
        post_biz_days: int | None = None
        post_records: list[EarningsRecord] = []
        post_latest_idx: int | None = None

        records = fd.get_earnings_history(ticker, limit=self._fetch_limit)
        if records:
            records = filter_retrospective_earnings(records)
            records = [r for r in records if r.filing_date]
            if records:
                records = sorted(records, key=lambda r: r.filing_date, reverse=True)
                as_of = [r for r in records if _parse_date(r.filing_date) <= today]
                if as_of:
                    latest = as_of[0]
                    try:
                        bd = _business_days_between(_parse_date(latest.filing_date), today)
                    except (ValueError, TypeError):
                        bd = -1
                    if 0 <= bd <= self._post_window:
                        post_record = latest
                        post_biz_days = bd
                        post_records = records
                        post_latest_idx = records.index(latest)

        # ---- 3. No-fire path ------------------------------------------
        if pre_days_to is None and post_record is None:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=(
                    f"no earnings within ±{self._pre_window}d "
                    f"(pre) / +{self._post_window}d (post)"
                ),
                asof_date=end_date,
            )

        # ---- 4. Side selection ----------------------------------------
        # Smaller |biz_days| wins; tie → post (concrete > anticipation).
        use_post = False
        if post_record is not None and pre_days_to is not None:
            use_post = (post_biz_days or 0) <= pre_days_to
        elif post_record is not None:
            use_post = True

        if use_post:
            assert post_record is not None and post_biz_days is not None and post_latest_idx is not None
            return self._build_post_trigger(
                end_date=end_date,
                records=post_records,
                latest=post_record,
                latest_idx=post_latest_idx,
                biz_days=post_biz_days,
            )
        return self._build_pre_trigger(end_date, pre_days_to)  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Per-side builders
    # ------------------------------------------------------------------

    def _build_pre_trigger(self, end_date: str, days_to: int) -> EventTrigger:
        severity = self._pre_severity_for_days(days_to)
        when = "today" if days_to == 0 else ("tomorrow" if days_to == 1 else f"in {days_to} days")
        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction="neutral",
            reason=f"earnings {when} (pre-event)",
            components={
                # Negative = future, positive = past. d=0 stays 0.
                "biz_days_to_event": float(-days_to),
                "phase": 1.0,  # 1 = pre-event
                "pre_window_days": float(self._pre_window),
            },
            asof_date=end_date,
        )

    def _build_post_trigger(
        self,
        *,
        end_date: str,
        records: list[EarningsRecord],
        latest: EarningsRecord,
        latest_idx: int,
        biz_days: int,
    ) -> EventTrigger:
        q = latest.quarterly
        if q is None or q.eps_surprise is None:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"filed {latest.filing_date}: no quarterly surprise data",
                components={"biz_days_to_event": float(biz_days), "phase": 2.0},
                asof_date=end_date,
            )

        label = q.eps_surprise.upper()
        if label == "MEET":
            return EventTrigger(
                detector=self.name,
                triggered=False,
                direction="neutral",
                reason=f"MEET — filed {latest.filing_date}, no surprise",
                components={"biz_days_to_event": float(biz_days), "phase": 2.0},
                asof_date=end_date,
            )

        direction = "bullish" if label == "BEAT" else "bearish"
        sign = 1.0 if direction == "bullish" else -1.0

        # Trailing surprise distribution for z-scoring; starts AFTER the
        # as-of record, mirroring the as-of fix in EarningsSurpriseDetector.
        current_surprise = _surprise_pct(q.earnings_per_share, q.estimated_earnings_per_share)
        history_pcts: list[float] = []
        for r in records[latest_idx + 1 : latest_idx + 1 + self._history_quarters]:
            if r.quarterly is None:
                continue
            s = _surprise_pct(
                r.quarterly.earnings_per_share,
                r.quarterly.estimated_earnings_per_share,
            )
            if s is not None:
                history_pcts.append(s)

        components: dict[str, float] = {
            "biz_days_to_event": float(biz_days),
            "phase": 2.0,  # 2 = post-event
            "history_n": float(len(history_pcts)),
        }

        if current_surprise is not None and len(history_pcts) >= 2:
            hist = np.array(history_pcts)
            mu = float(hist.mean())
            sigma_raw = float(hist.std(ddof=1))
            sigma_floor = 0.05
            if sigma_raw < sigma_floor:
                severity = self._floor_z * sign
                components["surprise_pct"] = float(current_surprise)
                components["history_mean"] = float(mu)
                components["history_std"] = float(sigma_raw)
                components["raw_z"] = 0.0
            else:
                z = (current_surprise - mu) / sigma_raw
                severity = max(abs(z), self._floor_z) * sign
                components["surprise_pct"] = float(current_surprise)
                components["history_mean"] = float(mu)
                components["history_std"] = float(sigma_raw)
                components["raw_z"] = float(z)
        else:
            severity = self._floor_z * sign
            if current_surprise is not None:
                components["surprise_pct"] = float(current_surprise)

        reason = (
            f"{label} filed {latest.filing_date} ({biz_days} biz-days ago); "
            f"|z|={abs(severity):.2f} (post-event)"
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
