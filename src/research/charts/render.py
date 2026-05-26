"""Chart rendering primitives for the SOP Technical section.

Phase 10 rewrite: matches the visual style of the reference VST/COHR/PDD
reports (matplotlib + mplfinance candlesticks + SMA overlay + volume
subplot + auto support/resistance horizontal lines + RSI subplot).

Public functions:

    render_daily_kline_png(prices, sr_levels=None)        -> bytes (PNG)
    render_weekly_kline_png(prices, sr_levels=None)       -> bytes (PNG)
    render_intraday_png(prices)                           -> bytes (PNG)
    render_equity_curve_png(closes, signal_indices, ...)  -> bytes (PNG)
    render_equity_curve_b64(...)                          -> str (data URI)

    # Backwards-compat (Phase 4-9 callers):
    render_kline_png(closes_or_prices, kind)              -> bytes (PNG)
        — accepts either list[float] (legacy) or list[Price] (new).
          When given closes-only, falls back to a line chart since
          candlesticks need OHLCV.

All renderers are best-effort: empty/short inputs render a "No data"
placeholder PNG rather than raising — the orchestrator never has to
guard against chart failure.

The ``matplotlib.use("Agg")`` call MUST precede any other matplotlib
import (Windows headless precedent: v2/event_study/plot.py).
"""

from __future__ import annotations

import base64
import io
from typing import Any, Literal

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — backend selection must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import mplfinance as mpf  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402


_FIGSIZE_DEFAULT = (10, 6)
_FIGSIZE_INTRADAY = (10, 4)
_DPI = 90

# Bull = red, bear = green (Asia convention — matches the user's
# reference reports). mplfinance ships market color helpers.
_MC = mpf.make_marketcolors(
    up="#e11d48",     # red rising candle body
    down="#16a34a",   # green falling
    edge="inherit",
    wick={"up": "#e11d48", "down": "#16a34a"},
    volume={"up": "#fca5a5", "down": "#86efac"},
)
_STYLE = mpf.make_mpf_style(
    base_mpl_style="default",
    marketcolors=_MC,
    gridstyle=":",
    gridcolor="#e5e7eb",
    facecolor="white",
    edgecolor="#9ca3af",
    rc={"font.size": 9},
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _no_data_png(message: str = "No data", figsize=_FIGSIZE_DEFAULT) -> bytes:
    """Render a tiny placeholder PNG so callers always get valid bytes."""
    fig, ax = plt.subplots(figsize=figsize, dpi=_DPI)
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


def _to_dataframe(prices: list) -> pd.DataFrame | None:
    """Coerce a list of Price-like objects to an OHLCV DataFrame indexed
    by date. Returns None if the input is empty / malformed / closes-only."""
    if not prices:
        return None
    rows = []
    for p in prices:
        # Support both v2.data.models.Price (Pydantic) and dict / raw float
        if isinstance(p, (int, float)):
            return None  # closes-only — caller falls back to line chart
        d = p if isinstance(p, dict) else getattr(p, "model_dump", lambda: p.__dict__)()
        try:
            rows.append({
                "Date": pd.to_datetime(d.get("time") or d.get("date")),
                "Open": float(d.get("open", d.get("close", 0))),
                "High": float(d.get("high", d.get("close", 0))),
                "Low": float(d.get("low", d.get("close", 0))),
                "Close": float(d.get("close", 0)),
                "Volume": float(d.get("volume", 0)),
            })
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows).set_index("Date").sort_index()
    return df


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly (W-FRI close)."""
    agg = df.resample("W-FRI").agg({
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }).dropna(how="any")
    return agg


def _auto_sr_levels(df: pd.DataFrame, n_levels: int = 3) -> list[float]:
    """Best-effort support/resistance: 52w high, 52w low, 60d high/low.
    Returns up to n_levels unique price levels rounded to 2 decimals.
    """
    if df.empty:
        return []
    last_52w = df.tail(252) if len(df) > 252 else df
    last_60d = df.tail(60) if len(df) > 60 else df
    raw = [
        float(last_52w["High"].max()),
        float(last_52w["Low"].min()),
        float(last_60d["High"].max()),
        float(last_60d["Low"].min()),
    ]
    # Dedup by 1% bands so we don't show three near-identical lines
    deduped: list[float] = []
    for x in sorted(raw):
        if not deduped or abs(x - deduped[-1]) / max(deduped[-1], 1) > 0.01:
            deduped.append(round(x, 2))
    return deduped[:n_levels + 1]


def _rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI. Returns NaN for the first ``period`` rows."""
    delta = closes.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ---------------------------------------------------------------------------
# v1 candlestick charts
# ---------------------------------------------------------------------------


def _render_kline(
    df: pd.DataFrame,
    *,
    sma_periods: list[int],
    sr_levels: list[float] | None,
    title: str,
    figsize: tuple[int, int],
    include_rsi: bool = True,
) -> bytes:
    """Shared candlestick renderer for daily + weekly."""
    if df is None or len(df) < 2:
        return _no_data_png(figsize=figsize)

    # mplfinance addplots: SMA overlays + horizontal S/R lines + RSI subplot
    addplots: list[Any] = []

    for n in sma_periods:
        if len(df) >= n:
            sma = df["Close"].rolling(window=n).mean()
            addplots.append(mpf.make_addplot(
                sma, color={20: "#f59e0b", 50: "#2563eb", 200: "#8b5cf6"}.get(n, "#6b7280"),
                width=1.0, linestyle="-",
                label=f"SMA{n}",
            ))

    panel_ratios = [3, 1]  # main : volume
    rsi_panel_idx = None
    if include_rsi and len(df) > 20:
        rsi_series = _rsi(df["Close"], period=14)
        rsi_panel_idx = 2
        addplots.append(mpf.make_addplot(
            rsi_series, panel=rsi_panel_idx, color="#0891b2",
            width=1.0, ylabel="RSI(14)",
        ))
        # 30 / 70 reference lines
        addplots.append(mpf.make_addplot(
            pd.Series(30, index=df.index), panel=rsi_panel_idx,
            color="#cbd5e1", width=0.6, linestyle="--",
        ))
        addplots.append(mpf.make_addplot(
            pd.Series(70, index=df.index), panel=rsi_panel_idx,
            color="#cbd5e1", width=0.6, linestyle="--",
        ))
        panel_ratios = [3, 1, 1]

    # Horizontal support/resistance lines via hlines
    hlines = None
    if sr_levels:
        hlines = dict(
            hlines=sr_levels,
            colors=["#9ca3af"] * len(sr_levels),
            linestyle="--",
            linewidths=0.8,
        )

    try:
        fig, axlist = mpf.plot(
            df,
            type="candle",
            style=_STYLE,
            addplot=addplots if addplots else None,
            hlines=hlines,
            volume=True,
            panel_ratios=panel_ratios,
            figsize=figsize,
            returnfig=True,
            tight_layout=True,
            ylabel="Price",
            ylabel_lower="Volume",
            warn_too_much_data=10_000,
        )
    except Exception:
        return _no_data_png("Chart render failed", figsize=figsize)

    fig.suptitle(title, fontsize=11, y=0.995)

    # Annotate S/R levels on the right edge of the main panel
    if sr_levels and axlist:
        ax = axlist[0]
        x_right = len(df) - 1
        for lv in sr_levels:
            ax.annotate(
                f"{lv:.2f}",
                xy=(x_right, lv),
                xytext=(4, 0), textcoords="offset points",
                color="#6b7280", fontsize=8,
                va="center",
            )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_daily_kline_png(
    prices: list,
    *,
    sr_levels: list[float] | None = None,
    title: str | None = None,
) -> bytes:
    """Daily candlestick chart with SMA20/50/200 + volume + RSI(14) subplot
    + auto support/resistance horizontal lines.

    Accepts ``list[Price]`` (full OHLCV). Falls back to a "No data" PNG
    when input is empty, malformed, or closes-only (legacy callers).
    """
    df = _to_dataframe(prices)
    if df is None or len(df) < 2:
        return _no_data_png()
    if sr_levels is None:
        sr_levels = _auto_sr_levels(df)
    return _render_kline(
        df,
        sma_periods=[20, 50, 200],
        sr_levels=sr_levels,
        title=title or "Daily K-line",
        figsize=_FIGSIZE_DEFAULT,
        include_rsi=True,
    )


def render_weekly_kline_png(
    prices: list,
    *,
    sr_levels: list[float] | None = None,
    title: str | None = None,
) -> bytes:
    """Weekly candlestick. Resamples daily OHLCV to W-FRI bars, then
    overlays SMA20/50/200 (in weeks). Adds RSI(14) subplot."""
    df = _to_dataframe(prices)
    if df is None or len(df) < 5:
        return _no_data_png()
    weekly = _resample_weekly(df)
    if len(weekly) < 2:
        return _no_data_png()
    if sr_levels is None:
        sr_levels = _auto_sr_levels(weekly)
    return _render_kline(
        weekly,
        sma_periods=[20, 50, 200],
        sr_levels=sr_levels,
        title=title or "Weekly K-line",
        figsize=_FIGSIZE_DEFAULT,
        include_rsi=True,
    )


def render_intraday_png(
    prices: list,
    *,
    title: str | None = None,
) -> bytes:
    """Intraday (5-min) candlestick + volume. Same renderer, smaller
    figure, no RSI subplot (intraday RSI is noisy)."""
    df = _to_dataframe(prices)
    if df is None or len(df) < 2:
        return _no_data_png("No intraday data", figsize=_FIGSIZE_INTRADAY)
    return _render_kline(
        df,
        sma_periods=[],
        sr_levels=None,
        title=title or "Intraday (5-min)",
        figsize=_FIGSIZE_INTRADAY,
        include_rsi=False,
    )


# ---------------------------------------------------------------------------
# Backwards compatibility — kept so existing callers don't break.
# ---------------------------------------------------------------------------


def render_kline_png(
    prices_or_closes: list,
    kind: Literal["daily", "weekly"] = "daily",
) -> bytes:
    """Backwards-compat shim. Accepts either:
       - list[Price] / list[dict] with OHLCV → routes to new candlestick render
       - list[float] (closes only) → falls back to line chart
    """
    if not prices_or_closes:
        return _no_data_png()

    # Detect closes-only by sampling the first element
    first = prices_or_closes[0]
    if isinstance(first, (int, float)):
        return _legacy_line_kline(list(prices_or_closes), kind)

    if kind == "weekly":
        return render_weekly_kline_png(prices_or_closes)
    return render_daily_kline_png(prices_or_closes)


def _legacy_line_kline(closes: list[float], kind: str) -> bytes:
    """Phase 4-9 line chart — kept only for tests and callers that
    haven't been updated to pass full Price objects yet."""
    series = list(closes) if kind == "daily" else list(closes[::5])
    if len(series) < 2:
        return _no_data_png()

    fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
    xs = list(range(len(series)))
    ax.plot(xs, series, color="#2563eb", linewidth=1.2, label="Close")

    if len(series) >= 50:
        running = sum(series[:50])
        sma = [None] * 50
        sma[49] = running / 50
        for i in range(50, len(series)):
            running += series[i] - series[i - 50]
            sma.append(running / 50)
        sma_xs = [i for i, v in enumerate(sma) if v is not None]
        sma_ys = [v for v in sma if v is not None]
        if sma_ys:
            ax.plot(sma_xs, sma_ys, color="#f59e0b", linewidth=1.0,
                    linestyle="--", label="SMA50")

    ax.set_title(f"{kind.capitalize()} Close (line, OHLCV unavailable)")
    ax.set_xlabel("Bar")
    ax.set_ylabel("Price")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Equity curve (unchanged from Phase 5)
# ---------------------------------------------------------------------------


def render_equity_curve_png(
    closes: list[float],
    signal_indices: list[int],
    horizon: int = 20,
) -> bytes:
    """Render an equity curve PNG.

    Starting at $1.00, multiply by ``(1 + forward_return)`` at each
    signal index. Flat between signals.
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
        if 0 <= i < n:
            for j in range(i, n):
                equity[j] = cum

    fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
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
    """Base64 data URI version of ``render_equity_curve_png``."""
    png = render_equity_curve_png(closes, signal_indices, horizon=horizon)
    b64 = base64.b64encode(png).decode("ascii")
    return f"data:image/png;base64,{b64}"


def png_to_b64_uri(png_bytes: bytes) -> str:
    """Convert raw PNG bytes to a data: URI for inline <img src=> embedding."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"
