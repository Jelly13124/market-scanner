"""OBV/Price divergence detector.

On-Balance Volume (Granville 1963) is a cumulative running total:

    OBV[t] = OBV[t-1] + sign(close[t] - close[t-1]) * volume[t]

The classic interpretation — well-supported by the microstructure literature
(Blume/Easley/O'Hara 1994, Lee/Swaminathan 2000) — is that when OBV trends
*away from* price, informed money is repositioning before the price catches
up. The signal we want is divergence:

* **Bullish (accumulation)**: price drifts down or sideways while OBV climbs
  — buyers are absorbing supply on down days.
* **Bearish (distribution)**: price drifts up while OBV falls — sellers
  are unloading on up days, hiding behind retail bid.

To make those statements quantitative we measure the 20-day linear slope of
both series, then z-score each against the trailing 60 daily readings of
the same slope so divergence magnitude is comparable across tickers and
volatility regimes. Fires when the two z-scores have opposite signs AND
their gap exceeds ``divergence_threshold`` (default 2σ).

Why this is distinct from ``price_volume_anomaly``: PVA looks at a single
day's volume vs its own history; OBV captures *the directional accumulation
that volume aggregates into over a window*. A stock can have unremarkable
daily volumes that nevertheless OBV-trend the opposite way from price.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np

from v2.data.protocol import DataClient
from v2.scanner.detectors.base import (
    EventDetector,
    EventTrigger,
    close_of,
    parse_date as _parse_date,
)
from v2.scanner.models import ScanContext


def _compute_obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
    """Cumulative OBV series anchored at 0 for the first bar.

    Equal-close days neither add nor subtract — matches Granville's original
    rule (some platforms treat equal as +volume; we don't).
    """
    if len(closes) != len(volumes) or len(closes) < 2:
        return np.zeros_like(closes)
    deltas = np.sign(np.diff(closes))  # -1, 0, +1
    contrib = deltas * volumes[1:]
    obv = np.concatenate(([0.0], np.cumsum(contrib)))
    return obv


def _slope_normalized(series: np.ndarray) -> float | None:
    """Linear-regression slope per step, normalized by the series mean.

    Normalization makes the slope unitless ("fraction-of-mean per step") so
    OBV and price slopes are on comparable scales before z-scoring. Returns
    None when the mean is non-positive or the series is degenerate.
    """
    n = len(series)
    if n < 2:
        return None
    mean = float(np.mean(np.abs(series)))
    if mean <= 0.0:
        return None
    x = np.arange(n, dtype=float)
    # np.polyfit deg=1 returns [slope, intercept]
    try:
        slope = float(np.polyfit(x, series, 1)[0])
    except (np.linalg.LinAlgError, ValueError):
        return None
    return slope / mean


class OBVDivergenceDetector(EventDetector):
    """Trigger on bullish/bearish OBV-vs-price divergence."""

    name = "obv_divergence"

    def __init__(
        self,
        *,
        slope_window: int = 20,
        z_history: int = 60,
        divergence_threshold: float = 2.0,
        lookback_days: int = 200,
        severity_cap: float = 5.0,
    ) -> None:
        self._slope_window = slope_window
        self._z_history = z_history
        self._div_thresh = divergence_threshold
        self._lookback = lookback_days
        self._sev_cap = severity_cap

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

        # We need ``slope_window + z_history`` rolling-window readings, which
        # means roughly ``slope_window + z_history + slope_window`` bars
        # (each reading consumes one extra bar of leading history). Plus a
        # margin for weekends/holidays we ask for ~200 calendar days.
        start = (today - timedelta(days=self._lookback)).isoformat()
        prices = fd.get_prices(ticker, start, end_date)
        min_bars = self._slope_window + self._z_history + 1
        if not prices or len(prices) < min_bars:
            return None

        prices_sorted = sorted(prices, key=lambda p: p.time[:10])
        closes_list = [close_of(p) for p in prices_sorted]
        volumes_list = [
            float(p.volume) if p.volume is not None else None
            for p in prices_sorted
        ]
        if any(c is None or c <= 0 for c in closes_list):
            return None
        if any(v is None or v < 0 for v in volumes_list):
            return None
        closes = np.array(closes_list, dtype=float)
        volumes = np.array(volumes_list, dtype=float)

        obv = _compute_obv(closes, volumes)

        # Build rolling 20d slope series for both OBV and price. We need
        # ``z_history + 1`` consecutive readings: the latest = today's
        # slope; the prior z_history readings form the baseline distribution.
        n_readings = self._z_history + 1
        obv_slopes: list[float] = []
        price_slopes: list[float] = []
        for offset in range(n_readings):
            end_idx = len(closes) - offset
            start_idx = end_idx - self._slope_window
            if start_idx < 0:
                return None
            o_slope = _slope_normalized(obv[start_idx:end_idx])
            p_slope = _slope_normalized(closes[start_idx:end_idx])
            if o_slope is None or p_slope is None:
                return None
            obv_slopes.append(o_slope)
            price_slopes.append(p_slope)
        # Reverse so the LAST entry is today.
        obv_slopes.reverse()
        price_slopes.reverse()

        obv_today = obv_slopes[-1]
        price_today = price_slopes[-1]
        obv_hist = np.array(obv_slopes[:-1])
        price_hist = np.array(price_slopes[:-1])

        # Z-score each today-slope against its own trailing history. Floor the
        # std at a small positive value to dodge the "GEHC-style" collapse
        # documented in v2/scanner/README.md (see PVA detector). 1e-6 of the
        # mean magnitude is small enough to still flag genuine moves and big
        # enough to avoid infinities when history is dead-flat.
        def _z(today: float, hist: np.ndarray) -> tuple[float, float, float]:
            mu = float(hist.mean())
            sigma = float(hist.std(ddof=1))
            floor = max(abs(mu) * 1e-3, 1e-6)
            sigma_eff = max(sigma, floor)
            return (today - mu) / sigma_eff, mu, sigma_eff

        obv_z, obv_mu, obv_sigma = _z(obv_today, obv_hist)
        price_z, price_mu, price_sigma = _z(price_today, price_hist)

        components = {
            "obv_slope_today": float(obv_today),
            "obv_slope_z": float(obv_z),
            "price_slope_today": float(price_today),
            "price_slope_z": float(price_z),
            "divergence_magnitude": float(abs(obv_z - price_z)),
            "divergence_threshold": float(self._div_thresh),
        }

        # Divergence requires opposite signs AND a big enough gap. Same-sign
        # = no divergence; small opposite-sign gap = noise.
        signs_disagree = (obv_z > 0 > price_z) or (obv_z < 0 < price_z)
        gap = abs(obv_z - price_z)

        if not (signs_disagree and gap > self._div_thresh):
            reason = (
                f"no divergence: obv_z={obv_z:+.2f} price_z={price_z:+.2f} "
                f"gap={gap:.2f} (threshold={self._div_thresh:.2f})"
            )
            return EventTrigger(
                detector=self.name,
                triggered=False,
                reason=reason,
                components=components,
                asof_date=end_date,
            )

        if obv_z > 0:
            direction = "bullish"  # accumulation: OBV rising while price falling
            kind = "accumulation"
        else:
            direction = "bearish"  # distribution: OBV falling while price rising
            kind = "distribution"

        # Severity = how many sigma apart the two series are, capped to keep
        # the composite ranking bounded.
        severity = min(gap, self._sev_cap)
        reason = (
            f"{kind}: obv_z={obv_z:+.2f} vs price_z={price_z:+.2f} "
            f"(|gap|={gap:.2f} > {self._div_thresh:.2f})"
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
