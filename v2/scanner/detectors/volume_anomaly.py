"""Volume anomaly detector.

Fires when today's volume z-scores above ``volume_z_threshold`` against
trailing 20-day mean **AND** today's close-to-close return is small
(``|ret| < return_max_pct``). The anti-gate is intentional: stocks that
moved on big volume are already covered by ``IntradayMoveDetector`` (which
captures close_vs_open + gap). This detector specifically captures the
Wyckoff "stopping volume" / distribution-day pattern — high volume on a
flat day, often a sign of institutional accumulation or distribution
without obvious price reaction.

Direction is signed by today's return: positive ret → bullish volume
absorption, negative ret → bearish distribution. When ret is essentially
zero, direction is neutral.

Stable name attribute ``"price_volume_anomaly"`` is preserved for DB
backward-compatibility with historical ``WatchlistEntry`` rows.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import EventDetector, EventTrigger, close_of, parse_date as _parse_date
from v2.scanner.models import ScanContext




class VolumeAnomalyDetector(EventDetector):
    """Trigger on outsized volume on a flat-return day."""

    name = "price_volume_anomaly"

    def __init__(
        self,
        *,
        lookback_days: int = 60,
        volume_window: int = 20,
        volume_z_threshold: float = 2.5,
        return_max_pct: float = 0.015,
    ) -> None:
        self._lookback_days = lookback_days
        self._volume_window = volume_window
        self._vol_thresh = volume_z_threshold
        self._return_max_pct = return_max_pct

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
        if not prices or len(prices) < self._volume_window + 2:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        # Prefer split- and dividend-adjusted closes so ex-div days don't fake
        # a -2% move when computing today's return.
        closes = np.array([close_of(p) for p in prices_sorted])
        volumes = np.array([float(p.volume) for p in prices_sorted])

        # Today's close-to-close return — needed for the anti-gate and direction.
        if closes[-2] <= 0:
            return None
        today_ret = float((closes[-1] - closes[-2]) / closes[-2])

        today_vol = float(volumes[-1])
        trailing_vols = volumes[-(self._volume_window + 1) : -1]
        if len(trailing_vols) < 5 or trailing_vols.mean() == 0:
            return None
        vol_mean = float(trailing_vols.mean())
        # Volume std floor of 10% of mean — protects against near-zero-std
        # blowup on illiquid micro-caps where 20-day average volume is nearly
        # constant.
        vol_std = max(float(trailing_vols.std(ddof=1)), vol_mean * 0.10)
        z_vol = (today_vol - vol_mean) / vol_std

        vol_hit = z_vol >= self._vol_thresh
        return_calm = abs(today_ret) < self._return_max_pct

        components = {
            "today_return": float(today_ret),
            "today_volume": float(today_vol),
            "z_volume": float(z_vol),
            "trailing_vol_mean": float(vol_mean),
            "return_max_pct": float(self._return_max_pct),
        }

        if not vol_hit:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=f"z_vol={z_vol:+.2f} (below {self._vol_thresh:.1f})",
                components=components,
                asof_date=end_date,
            )

        if not return_calm:
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=(
                    f"vol z={z_vol:+.2f} but ret {today_ret*100:+.2f}% — IDAY territory"
                ),
                components=components,
                asof_date=end_date,
            )

        # Direction follows return sign; tie-break to neutral if return is ~0.
        if today_ret > 1e-4:
            direction = "bullish"
            sign = 1.0
        elif today_ret < -1e-4:
            direction = "bearish"
            sign = -1.0
        else:
            direction = "neutral"
            sign = 1.0

        severity = z_vol * sign

        return EventTrigger(
            detector=self.name,
            triggered=True,
            severity_z=float(severity),
            direction=direction,
            reason=f"volume z={z_vol:+.2f} on flat day (ret {today_ret*100:+.2f}%)",
            components=components,
            asof_date=end_date,
        )
