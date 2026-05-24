"""Chart rendering primitives for the SOP Technical section.

Three public functions:

    render_kline_png(closes, kind)          -> bytes (PNG)
    render_equity_curve_png(closes, signal_indices, horizon=20) -> bytes (PNG)
    render_equity_curve_b64(...)            -> str ('data:image/png;base64,...')

All renderers are best-effort: empty/short inputs render a "No data"
placeholder PNG rather than raising, so the orchestrator never has to
guard against chart failure.

The ``matplotlib.use("Agg")`` call MUST precede any other matplotlib
import (Windows headless precedent: v2/event_study/plot.py).
"""

from __future__ import annotations

import base64
import io
from typing import Literal

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — backend selection must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402


_FIGSIZE = (8, 4)
_DPI = 80


def _no_data_png(message: str = "No data") -> bytes:
    """Render a tiny placeholder PNG so callers always get valid bytes."""
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    ax.text(
        0.5, 0.5, message,
        ha="center", va="center",
        transform=ax.transAxes,
        fontsize=14, color="#9ca3af",
    )
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _sma(closes: list[float], n: int) -> list[float | None]:
    """Simple moving average aligned to ``closes`` (None until enough history)."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) >= n:
        running = sum(closes[:n])
        out[n - 1] = running / n
        for i in range(n, len(closes)):
            running += closes[i] - closes[i - n]
            out[i] = running / n
    return out


def render_kline_png(
    closes: list[float],
    kind: Literal["daily", "weekly"] = "daily",
) -> bytes:
    """Render a price line + SMA50 overlay PNG.

    OHLC isn't available (shared data only carries closes), so this is a
    line chart, not candlesticks. Weekly resamples by taking every 5th
    close (~one bar per trading week).
    """
    if not closes:
        return _no_data_png()

    series = list(closes) if kind == "daily" else list(closes[::5])
    if len(series) < 2:
        return _no_data_png()

    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    xs = list(range(len(series)))
    ax.plot(xs, series, color="#2563eb", linewidth=1.2, label="Close")

    sma = _sma(series, 50)
    sma_xs = [i for i, v in enumerate(sma) if v is not None]
    sma_ys = [v for v in sma if v is not None]
    if sma_ys:
        ax.plot(sma_xs, sma_ys, color="#f59e0b", linewidth=1.0,
                linestyle="--", label="SMA50")

    ax.set_title(f"{kind.capitalize()} Close" + (" (resampled)" if kind == "weekly" else ""))
    ax.set_xlabel("Bar")
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_equity_curve_png(
    closes: list[float],
    signal_indices: list[int],
    horizon: int = 20,
) -> bytes:
    """Render an equity curve PNG.

    Starting at $1.00, multiply by ``(1 + forward_return)`` at each
    signal index (forward return = ``closes[i + horizon] / closes[i] - 1``).
    The curve is flat between signals. If no signals fire, returns a flat
    line at 1.0 with a "no signals" note.
    """
    if not closes:
        return _no_data_png()

    n = len(closes)
    equity = [1.0] * n
    cum = 1.0
    applied = 0
    for i in signal_indices:
        if 0 <= i < n and i + horizon < n:
            ret = closes[i + horizon] / closes[i] - 1.0
            cum *= (1.0 + ret)
            applied += 1
        # Always extend the flat segment from i onward to the new cum value
        if 0 <= i < n:
            for j in range(i, n):
                equity[j] = cum

    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    ax.plot(range(n), equity, color="#16a34a", linewidth=1.4)
    ax.axhline(1.0, color="#9ca3af", linewidth=0.8, linestyle=":")
    title = f"Equity curve ({applied} signals, {horizon}d horizon)"
    if applied == 0:
        title = "Equity curve (no signals fired in window)"
    ax.set_title(title)
    ax.set_xlabel("Bar")
    ax.set_ylabel("Equity ($1 start)")
    ax.grid(True, alpha=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_equity_curve_b64(
    closes: list[float],
    signal_indices: list[int],
    horizon: int = 20,
) -> str:
    """Same as ``render_equity_curve_png`` but b64-encoded as a data URI
    ready to drop straight into ``<img src="...">`` for inline email use.
    """
    png = render_equity_curve_png(closes, signal_indices, horizon=horizon)
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"
