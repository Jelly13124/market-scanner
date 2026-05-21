"""Insider cluster detector — asymmetric buy/sell (per task_plan_scanner_v2 §3.2).

Empirical reality (Cohen-Malloy-Pomorski 2012): insider BUYS carry strong
information content; insider SELLS are weaker because they're driven by
diversification, taxes, and 10b5-1 plans as often as by conviction.

This detector reflects that asymmetry:

  Buy (bullish)
    cluster: ≥ ``cluster_min_buyers`` (default 2) distinct insiders same direction
    single:  ≥ $250k AND transaction_type='P' (open-market purchase only — not M,A,F,G)
    severity multiplier × ``buy_severity_mult`` (default 1.3)

  Sell (bearish)
    cluster: ≥ ``cluster_min_sellers`` (default 4) distinct insiders same direction
    single:  ≥ 1% of market cap (so only a meaningful sell, not a routine trim)
    severity multiplier × ``sell_severity_mult`` (default 0.7)

Severity z-scores the recent-window's gross notional against monthly buckets
over the trailing 365 days, with a std floor that prevents collapsed
baselines from blowing up the z (see M6.b history). After z-scoring the
multiplier is applied, and the result is hard-clipped at ``severity_cap``
(default ±5.0) to prevent extreme-outlier cases like ADBE 2026-05-16 where
gross_value=$11M against mu=$50k baseline gave z=-110 — way beyond what
the composite-score 5σ clip expects to see at this layer.

Stable ``.name = "insider_cluster"`` for backward-compat with historical
``WatchlistEntry`` rows.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.data.models import InsiderTrade
from v2.scanner.detectors.base import EventDetector, EventTrigger, parse_date as _parse_date
from v2.scanner.models import ScanContext


def _trade_value(t: InsiderTrade) -> float:
    """Signed dollar value of a trade. Positive = buy, negative = sell."""
    if t.transaction_value is not None:
        return float(t.transaction_value)
    if t.transaction_shares is not None and t.transaction_price_per_share is not None:
        return float(t.transaction_shares) * float(t.transaction_price_per_share)
    return 0.0


class InsiderClusterDetector(EventDetector):
    """Trigger on unusual insider buying or selling activity."""

    name = "insider_cluster"

    def __init__(
        self,
        *,
        cluster_window_days: int = 14,
        cluster_min_buyers: int = 2,
        cluster_min_sellers: int = 4,
        single_buy_dollar_threshold: float = 250_000.0,
        single_sell_market_cap_pct: float = 0.01,
        buy_severity_mult: float = 1.3,
        sell_severity_mult: float = 0.7,
        severity_cap: float = 5.0,
        history_days: int = 365,
        fetch_limit: int = 1000,
    ) -> None:
        self._window = cluster_window_days
        self._min_buyers = cluster_min_buyers
        self._min_sellers = cluster_min_sellers
        self._single_buy_dollars = single_buy_dollar_threshold
        self._single_sell_pct = single_sell_market_cap_pct
        self._buy_mult = buy_severity_mult
        self._sell_mult = sell_severity_mult
        self._severity_cap = severity_cap
        self._history_days = history_days
        self._fetch_limit = fetch_limit

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

        start_date = (today - timedelta(days=self._history_days)).isoformat()
        trades = fd.get_insider_trades(
            ticker, end_date=end_date, start_date=start_date, limit=self._fetch_limit,
        )
        if not trades:
            return None

        # Filter by transaction_date when available, falling back to filing_date.
        def _trade_date(t: InsiderTrade) -> date | None:
            return _parse_date(t.transaction_date or t.filing_date)

        recent_cutoff = today - timedelta(days=self._window)
        recent: list[InsiderTrade] = []
        rest: list[InsiderTrade] = []
        for t in trades:
            d = _trade_date(t)
            if d is None:
                continue
            (recent if d >= recent_cutoff else rest).append(t)

        if not recent:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason="no insider trades in recent window",
                asof_date=end_date,
            )

        # Cluster: distinct insider names per direction. Also track the
        # biggest single buy (only if it's an open-market 'P' purchase) and
        # the biggest single sell separately — they trigger via different
        # asymmetric paths.
        buyers: set[str] = set()
        sellers: set[str] = set()
        biggest_p_buy_abs = 0.0
        biggest_sell_abs = 0.0
        net_value = 0.0
        gross_value = 0.0
        for t in recent:
            v = _trade_value(t)
            net_value += v
            gross_value += abs(v)
            abs_v = abs(v)
            name = (t.name or "").strip()
            tcode = (t.transaction_type or "").strip().upper()
            if v > 0:
                if name:
                    buyers.add(name)
                # Only 'P' (open-market purchase) qualifies for the single-buy
                # path. Stock awards (A), option exercises (M), withholding (F),
                # gifts (G) all map to v>0 but carry no conviction signal.
                if tcode == "P" and abs_v > biggest_p_buy_abs:
                    biggest_p_buy_abs = abs_v
            elif v < 0:
                if name:
                    sellers.add(name)
                if abs_v > biggest_sell_abs:
                    biggest_sell_abs = abs_v

        # Cluster path: asymmetric thresholds.
        cluster_dir: str | None = None
        if len(buyers) >= self._min_buyers and len(buyers) > len(sellers):
            cluster_dir = "bullish"
        elif len(sellers) >= self._min_sellers and len(sellers) > len(buyers):
            cluster_dir = "bearish"

        # Single big trade — only fetch market cap when we need it (for the
        # sell path's 1%-of-MC check; buy path uses a dollar threshold).
        market_cap = ctx.market_cap if (ctx and ctx.market_cap) else None
        big_buy = biggest_p_buy_abs >= self._single_buy_dollars
        big_sell = False
        if biggest_sell_abs > 0:
            if market_cap is None:
                market_cap = fd.get_market_cap(ticker, end_date)
                if ctx is not None:
                    ctx.market_cap = market_cap
            big_sell = bool(
                market_cap and biggest_sell_abs > self._single_sell_pct * market_cap
            )
        big_single = big_buy or big_sell

        # Track which path triggered for debugging.
        direction_path = "none"
        if cluster_dir is not None:
            direction_path = "cluster"
        elif big_buy:
            direction_path = "single_buy"
        elif big_sell:
            direction_path = "single_sell"

        def _build_components(
            *,
            net_value_: float = 0.0,
            monthly_grosses_: list[float] | None = None,
            raw_z: float = 0.0,
            direction_mult: float = 1.0,
            severity_capped: bool = False,
            path_cluster: bool = False,
            path_single_buy: bool = False,
            path_single_sell: bool = False,
        ) -> dict[str, float]:
            """Shared components shape for both trigger/no-trigger branches.

            Keeps the dict from drifting between the two paths — the
            previous version diverged on which fields were present, which
            made downstream consumers (UI, debugging, alerts) need to
            handle each branch's different shape.
            """
            mg = monthly_grosses_ or []
            return {
                "recent_buyers": float(len(buyers)),
                "recent_sellers": float(len(sellers)),
                "recent_gross": float(gross_value),
                "recent_net": float(net_value_),
                "biggest_p_buy_abs": float(biggest_p_buy_abs),
                "biggest_sell_abs": float(biggest_sell_abs),
                "history_months": float(len(mg)),
                "history_mean": float(np.mean(mg)) if mg else 0.0,
                "raw_z": float(raw_z),
                "direction_mult": float(direction_mult),
                "severity_capped": 1.0 if severity_capped else 0.0,
                "market_cap": float(market_cap or 0.0),
                "direction_path_cluster": 1.0 if path_cluster else 0.0,
                "direction_path_single_buy": 1.0 if path_single_buy else 0.0,
                "direction_path_single_sell": 1.0 if path_single_sell else 0.0,
            }

        if cluster_dir is None and not big_single:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=(
                    f"{len(buyers)}B (need≥{self._min_buyers}) / "
                    f"{len(sellers)}S (need≥{self._min_sellers}) in "
                    f"{self._window}d; biggest_P_buy=${biggest_p_buy_abs:,.0f}, "
                    f"biggest_sell=${biggest_sell_abs:,.0f}"
                ),
                components=_build_components(net_value_=net_value),
                asof_date=end_date,
            )

        # Direction: cluster wins; else use which single-path fired.
        if cluster_dir is not None:
            direction = cluster_dir
        elif big_buy:
            direction = "bullish"
        else:
            direction = "bearish"

        # Severity z: gross_value vs monthly windows from rest of history.
        monthly_grosses: list[float] = []
        if rest:
            bucket: dict[date, float] = defaultdict(float)
            for t in rest:
                d = _trade_date(t)
                if d is None:
                    continue
                month_anchor = date(d.year, d.month, 1)
                bucket[month_anchor] += abs(_trade_value(t))
            monthly_grosses = list(bucket.values())

        if len(monthly_grosses) >= 2:
            arr = np.array(monthly_grosses)
            mu = float(arr.mean())
            sigma_raw = float(arr.std(ddof=1))
            # Std floor: max($1k, 10% of mean). Without this, M-code option
            # exercises (which we map to 0 shares since M6.b) collapse the
            # historical baseline to all-zeros → std ≈ 0 → z explodes by ~14
            # orders of magnitude (seen with GEHC: z=+55,257,210,785,000).
            # When the baseline is genuinely uninformative, fall back to the
            # same conservative magnitude we use when there's no baseline at all.
            sigma_floor = max(mu * 0.10, 1000.0)
            if sigma_raw < sigma_floor:
                z = 2.5 if cluster_dir is not None else 2.0
            else:
                z = (gross_value - mu) / sigma_raw
        else:
            # No baseline — assign a conservative magnitude tied to trigger strength.
            z = 2.5 if cluster_dir is not None else 2.0

        sign = 1.0 if direction == "bullish" else -1.0
        # Asymmetric severity multiplier: buys carry more information than
        # sells (Cohen-Malloy-Pomorski 2012), so a same-magnitude buy beats
        # a same-magnitude sell in the composite ranking.
        direction_mult = self._buy_mult if direction == "bullish" else self._sell_mult
        raw_severity = abs(z) * direction_mult
        # Hard cap. Without this, ADBE 2026-05-16 type cases (gross=$11M
        # vs mu=$50k baseline, sigma=$100k → z=-110) blow past the 5σ
        # composite clip and make the scoring degenerate at the top.
        capped_severity = min(raw_severity, self._severity_cap)
        severity = capped_severity * sign

        reason_bits: list[str] = []
        if cluster_dir is not None:
            n = len(buyers if direction == "bullish" else sellers)
            reason_bits.append(f"{n} insider {direction[:4]} in {self._window}d")
        if big_buy:
            reason_bits.append(f"P-buy ${biggest_p_buy_abs:,.0f}")
        if big_sell and market_cap:
            pct = 100.0 * biggest_sell_abs / market_cap
            reason_bits.append(f"sell {pct:.2f}% of MC")

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction=direction,
            reason="; ".join(reason_bits),
            components=_build_components(
                net_value_=net_value,
                monthly_grosses_=monthly_grosses,
                raw_z=z,
                direction_mult=direction_mult,
                severity_capped=raw_severity > self._severity_cap,
                path_cluster=cluster_dir is not None,
                path_single_buy=cluster_dir is None and big_buy,
                path_single_sell=cluster_dir is None and big_sell,
            ),
            asof_date=end_date,
        )
