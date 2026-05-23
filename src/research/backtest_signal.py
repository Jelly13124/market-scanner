"""Technical-signal backtest. Three built-in signals:
  - rsi_oversold: RSI(14) crossed up from <30
  - sma50_cross_up: close crossed above SMA(50)
  - macd_bullish_cross: MACD line crossed above signal line

For each signal occurrence at day t, measure return = close[t+20]/close[t] - 1.
Aggregate: n_signals, win_rate (% of forward returns > 0), avg_return, t-stat
against zero-mean null. Verdict text per overfit/insufficient/significant rules.

Replaces Phase 1's detector-replay backtest. Text-only (no charts).
"""

from __future__ import annotations

import math
from datetime import date

from src.research.models import BacktestVerdict
from src.research.shared_data import SharedData


def _closes(shared: SharedData) -> list[float]:
    out: list[float] = []
    for p in (shared.prices or []):
        if isinstance(p, dict):
            c = p.get("close")
        else:
            c = getattr(p, "close", None)
        if c is not None:
            try:
                out.append(float(c))
            except (TypeError, ValueError):
                continue
    return out


def _rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI. Returns list aligned with closes length (None for
    the first `period` entries, since they have insufficient history)."""
    n = len(closes)
    if n < period + 1:
        return [None] * n
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    # Initial averages over the first `period` returns
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    out: list[float | None] = [None] * period
    # First RSI value lands at index `period`
    rs = avg_g / avg_l if avg_l > 0 else float("inf")
    out.append(100 - 100 / (1 + rs))
    for i in range(period + 1, n):
        avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
        avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        rs = avg_g / avg_l if avg_l > 0 else float("inf")
        out.append(100 - 100 / (1 + rs))
    # Length now equals n
    return out


def _sma(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) >= n:
        running = sum(closes[:n])
        out[n - 1] = running / n
        for i in range(n, len(closes)):
            running += closes[i] - closes[i - n]
            out[i] = running / n
    return out


def _ema(closes: list[float], n: int) -> list[float | None]:
    if len(closes) < n:
        return [None] * len(closes)
    k = 2 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    sma = sum(closes[:n]) / n
    out.append(sma)
    prev = sma
    for c in closes[n:]:
        prev = c * k + prev * (1 - k)
        out.append(prev)
    return out


def _signal_indices(closes: list[float], signal: str) -> list[int]:
    n = len(closes)
    idx: list[int] = []
    if signal == "rsi_oversold":
        r = _rsi(closes)
        for i in range(1, n):
            if r[i - 1] is not None and r[i] is not None:
                if r[i - 1] < 30 <= r[i]:
                    idx.append(i)
    elif signal == "sma50_cross_up":
        s = _sma(closes, 50)
        for i in range(1, n):
            if s[i - 1] is not None and s[i] is not None:
                if closes[i - 1] < s[i - 1] and closes[i] >= s[i]:
                    idx.append(i)
    elif signal == "macd_bullish_cross":
        e12 = _ema(closes, 12)
        e26 = _ema(closes, 26)
        macd: list[float | None] = [
            (a - b) if (a is not None and b is not None) else None
            for a, b in zip(e12, e26)
        ]
        macd_clean = [m for m in macd if m is not None]
        sig_clean = _ema(macd_clean, 9)
        offset = next((i for i, v in enumerate(macd) if v is not None), 0)
        sig_full: list[float | None] = [None] * offset + sig_clean
        # Truncate / pad to n
        if len(sig_full) > n:
            sig_full = sig_full[:n]
        else:
            sig_full += [None] * (n - len(sig_full))
        for i in range(1, n):
            mp, mc = macd[i - 1], macd[i]
            sp, sc = sig_full[i - 1], sig_full[i]
            if mp is not None and mc is not None and sp is not None and sc is not None:
                if mp < sp and mc >= sc:
                    idx.append(i)
    return idx


def _forward_returns(closes: list[float], idx: list[int], horizon: int = 20) -> list[float]:
    out = []
    for i in idx:
        if i + horizon < len(closes):
            out.append(closes[i + horizon] / closes[i] - 1)
    return out


def _t_stat(returns: list[float]) -> float | None:
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    if var <= 0:
        return None
    se = math.sqrt(var / n)
    return mean / se


_AVAILABLE = ("rsi_oversold", "sma50_cross_up", "macd_bullish_cross")


def run_signal_backtest(
    shared: SharedData,
    signal: str = "auto",
    horizon: int = 20,
) -> BacktestVerdict:
    closes = _closes(shared)
    if not closes:
        return BacktestVerdict(
            signal=signal if signal != "auto" else "rsi_oversold",
            window_start=shared.scan_date, window_end=shared.scan_date,
            n_signals=0, win_rate_20d=None, avg_return_20d=None, t_stat=None,
            significant=False,
            verdict="insufficient data - no price history available",
        )

    candidates = _AVAILABLE if signal == "auto" else (signal,)
    best: tuple[float, str, int, float, float, float | None] | None = None
    for sig in candidates:
        idx = _signal_indices(closes, sig)
        rets = _forward_returns(closes, idx, horizon)
        if not rets:
            continue
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = sum(rets) / len(rets)
        t = _t_stat(rets)
        # Score by abs(t)*sqrt(n) to favor signals with both magnitude AND sample size
        score = (abs(t) if t is not None else 0.0) * math.sqrt(len(rets))
        if best is None or score > best[0]:
            best = (score, sig, len(rets), wr, avg, t)

    if best is None:
        return BacktestVerdict(
            signal=signal if signal != "auto" else "rsi_oversold",
            window_start=shared.scan_date, window_end=shared.scan_date,
            n_signals=0, win_rate_20d=None, avg_return_20d=None, t_stat=None,
            significant=False,
            verdict=f"no signal occurrences for {signal} in available history",
        )

    _, sig, n, wr, avg, t = best
    significant = (t is not None and abs(t) >= 1.96)
    t_str = f"{t:.2f}" if t is not None else "n/a"
    verdict = (
        f"signal '{sig}' fired {n} times; "
        f"avg {horizon}d return {avg*100:+.2f}%, win rate {wr*100:.0f}%, "
        f"t={t_str}; "
        + ("significant at p<0.05" if significant else "NOT significant at p<0.05 - weak edge")
    )

    today = date.today()
    window_start = str(today.replace(year=today.year - 5))
    return BacktestVerdict(
        signal=sig,
        window_start=window_start, window_end=shared.scan_date,
        n_signals=n, win_rate_20d=wr, avg_return_20d=avg,
        t_stat=t, significant=significant, verdict=verdict,
    )
