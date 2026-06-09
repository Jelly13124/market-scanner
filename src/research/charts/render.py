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
    up="#e11d48",  # red rising candle body
    down="#16a34a",  # green falling
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
        0.5,
        0.5,
        message,
        ha="center",
        va="center",
        transform=ax.transAxes,
        fontsize=14,
        color="#9ca3af",
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
            rows.append(
                {
                    "Date": pd.to_datetime(d.get("time") or d.get("date")),
                    "Open": float(d.get("open", d.get("close", 0))),
                    "High": float(d.get("high", d.get("close", 0))),
                    "Low": float(d.get("low", d.get("close", 0))),
                    "Close": float(d.get("close", 0)),
                    "Volume": float(d.get("volume", 0)),
                }
            )
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    df = pd.DataFrame(rows).set_index("Date").sort_index()
    return df


def _resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Resample daily OHLCV to weekly (W-FRI close)."""
    agg = (
        df.resample("W-FRI")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(how="any")
    )
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
    return deduped[: n_levels + 1]


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
            addplots.append(
                mpf.make_addplot(
                    sma,
                    color={20: "#f59e0b", 50: "#2563eb", 200: "#8b5cf6"}.get(n, "#6b7280"),
                    width=1.0,
                    linestyle="-",
                    label=f"SMA{n}",
                )
            )

    panel_ratios = [3, 1]  # main : volume
    rsi_panel_idx = None
    if include_rsi and len(df) > 20:
        rsi_series = _rsi(df["Close"], period=14)
        rsi_panel_idx = 2
        addplots.append(
            mpf.make_addplot(
                rsi_series,
                panel=rsi_panel_idx,
                color="#0891b2",
                width=1.0,
                ylabel="RSI(14)",
            )
        )
        # 30 / 70 reference lines
        addplots.append(
            mpf.make_addplot(
                pd.Series(30, index=df.index),
                panel=rsi_panel_idx,
                color="#cbd5e1",
                width=0.6,
                linestyle="--",
            )
        )
        addplots.append(
            mpf.make_addplot(
                pd.Series(70, index=df.index),
                panel=rsi_panel_idx,
                color="#cbd5e1",
                width=0.6,
                linestyle="--",
            )
        )
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
                xytext=(4, 0),
                textcoords="offset points",
                color="#6b7280",
                fontsize=8,
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
            ax.plot(sma_xs, sma_ys, color="#f59e0b", linewidth=1.0, linestyle="--", label="SMA50")

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
# Fundamental / valuation / relative-strength panels (Phase 11)
# ---------------------------------------------------------------------------


def _get_field(obj: Any, name: str):
    """Read a field from a Pydantic model, dict, or duck-typed object.

    Mirrors the defensiveness of ``_to_dataframe``: tolerates ``.get`` on
    dicts and ``getattr`` on objects, returning None when absent.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _sorted_by_period(financials: list) -> list:
    """Sort financial rows by ``report_period`` ascending.

    Rows without a usable report_period sort last (empty-string key) so a
    malformed entry never crashes the comparison.
    """
    if not financials:
        return []
    return sorted(
        financials,
        key=lambda f: str(_get_field(f, "report_period") or ""),
    )


def _extract_closes(prices: list) -> list[float]:
    """Pull a list of close prices from Price objects / dicts / raw floats.

    Best-effort: rows that can't be coerced to float are skipped. Mirrors the
    OHLCV defensiveness of ``_to_dataframe`` but keeps closes-only callers.
    """
    if not prices:
        return []
    out: list[float] = []
    for p in prices:
        if isinstance(p, (int, float)):
            try:
                out.append(float(p))
            except (TypeError, ValueError):
                continue
            continue
        val = _get_field(p, "close")
        if val is None:
            continue
        try:
            out.append(float(val))
        except (TypeError, ValueError):
            continue
    return out


def render_fundamental_trends_png(
    financials: list,
    *,
    title: str | None = None,
) -> bytes:
    """Margin & growth trend lines across reporting periods.

    Plots gross/operating/net margin and revenue_growth (all as %) on a single
    axis, one line per series. Series that are entirely None are skipped.
    Needs >=2 periods with at least one usable series, else "No data" PNG.
    """
    rows = _sorted_by_period(financials)
    if len(rows) < 2:
        return _no_data_png("Insufficient fundamental history")

    labels = [str(_get_field(f, "report_period") or "") for f in rows]

    # (field, legend label, color, linewidth) — revenue_growth de-emphasised.
    specs = [
        ("gross_margin", "Gross margin", "#2563eb", 1.6),
        ("operating_margin", "Operating margin", "#8b5cf6", 1.6),
        ("net_margin", "Net margin", "#16a34a", 1.6),
        ("revenue_growth", "Revenue growth", "#f59e0b", 1.2),
    ]

    xs = list(range(len(rows)))
    plotted = 0
    fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
    for field, label, color, lw in specs:
        ys: list[float | None] = []
        any_val = False
        for f in rows:
            v = _get_field(f, field)
            if v is None:
                ys.append(None)
            else:
                try:
                    ys.append(float(v) * 100.0)  # ratios -> percent
                    any_val = True
                except (TypeError, ValueError):
                    ys.append(None)
        if not any_val:
            continue
        # Mask None so matplotlib draws gaps rather than dropping to 0.
        ys_arr = np.array([np.nan if v is None else v for v in ys], dtype=float)
        style = "--" if field == "revenue_growth" else "-"
        ax.plot(
            xs,
            ys_arr,
            color=color,
            linewidth=lw,
            linestyle=style,
            marker="o",
            markersize=3,
            label=label,
        )
        plotted += 1

    if plotted == 0:
        plt.close(fig)
        return _no_data_png("Insufficient fundamental history")

    ax.set_title(title or "Margin & Growth Trends", fontsize=11)
    ax.set_ylabel("Percent (%)")
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.axhline(0.0, color="#9ca3af", linewidth=0.6, linestyle=":")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_valuation_band_png(
    financials: list,
    *,
    current_value: float | None = None,
    metric: str = "price_to_earnings_ratio",
    title: str | None = None,
) -> bytes:
    """A valuation multiple over time with a shaded historical min-max band.

    Marks the most-recent value with a labelled dot. When ``current_value`` is
    supplied, draws a dashed "current" reference line. Needs >=2 non-None
    points for the chosen ``metric``, else "No data" PNG.
    """
    rows = _sorted_by_period(financials)

    labels: list[str] = []
    values: list[float] = []
    for f in rows:
        v = _get_field(f, metric)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        labels.append(str(_get_field(f, "report_period") or ""))
        values.append(fv)

    if len(values) < 2:
        return _no_data_png("Insufficient valuation history")

    xs = list(range(len(values)))
    lo = min(values)
    hi = max(values)

    _METRIC_LABELS = {
        "price_to_earnings_ratio": "P/E",
        "price_to_sales_ratio": "P/S",
        "peg_ratio": "PEG",
        "price_to_book_ratio": "P/B",
    }
    metric_label = _METRIC_LABELS.get(metric, metric)

    fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
    # Shaded min-max band across the full width.
    ax.axhspan(lo, hi, color="#dbeafe", alpha=0.6, label=f"min-max ({lo:.1f}-{hi:.1f})")
    ax.plot(xs, values, color="#2563eb", linewidth=1.6, marker="o", markersize=3, label=metric_label)

    # Mark the latest value with a labelled dot.
    last_x, last_y = xs[-1], values[-1]
    ax.scatter([last_x], [last_y], color="#e11d48", s=40, zorder=5)
    ax.annotate(
        f"{last_y:.1f}",
        xy=(last_x, last_y),
        xytext=(5, 5),
        textcoords="offset points",
        color="#e11d48",
        fontsize=9,
        fontweight="bold",
    )

    if current_value is not None:
        try:
            cv = float(current_value)
            ax.axhline(cv, color="#16a34a", linewidth=1.2, linestyle="--", label=f"current ({cv:.1f})")
        except (TypeError, ValueError):
            pass

    ax.set_title(title or f"Valuation Band ({metric_label})", fontsize=11)
    ax.set_ylabel(metric_label)
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_relative_strength_png(
    prices: list,
    benchmark_prices: list,
    *,
    ticker_label: str = "Ticker",
    benchmark_label: str = "Benchmark",
    title: str | None = None,
) -> bytes:
    """Ticker vs benchmark, both rebased to 100 at the first common bar.

    Series are aligned by truncating to the shorter length from the END (so
    both finish "today"), then each is divided by its own first close * 100.
    Needs >=2 closes on each side, else "No data" PNG.
    """
    t_closes = _extract_closes(prices)
    b_closes = _extract_closes(benchmark_prices)
    if len(t_closes) < 2 or len(b_closes) < 2:
        return _no_data_png("Insufficient data for relative strength")

    # Align by truncating to the shorter length, keeping the most recent bars.
    n = min(len(t_closes), len(b_closes))
    t_closes = t_closes[-n:]
    b_closes = b_closes[-n:]

    t0 = t_closes[0]
    b0 = b_closes[0]
    if not t0 or not b0:  # guard zero / falsy first close (div-by-zero)
        return _no_data_png("Insufficient data for relative strength")

    t_rebased = [c / t0 * 100.0 for c in t_closes]
    b_rebased = [c / b0 * 100.0 for c in b_closes]
    xs = list(range(n))

    fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
    ax.plot(xs, t_rebased, color="#2563eb", linewidth=1.6, label=ticker_label)
    ax.plot(xs, b_rebased, color="#9ca3af", linewidth=1.4, linestyle="--", label=benchmark_label)
    ax.axhline(100.0, color="#cbd5e1", linewidth=0.8, linestyle=":")

    ax.set_title(title or "Relative Strength (rebased=100)", fontsize=11)
    ax.set_xlabel("Bar")
    ax.set_ylabel("Index (start=100)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Institutional positioning — dealer gamma walls (Phase 12)
# ---------------------------------------------------------------------------


def _fmt_gamma_axis(value: float) -> str:
    """Compact $ label for the gamma-walls y-axis ($M / $B)."""
    mag = abs(value)
    if mag >= 1e9:
        return f"${value / 1e9:.1f}B"
    return f"${value / 1e6:.0f}M"


def render_gamma_walls_png(gex: dict, *, title: str | None = None) -> bytes:
    """Bar chart of dealer gamma walls (per-strike dollar-gamma).

    Reads ``gex["walls"]`` (``[{"strike", "gamma_dollars"}, ...]``) and draws one
    bar per strike (x = strike, y = gamma dollars per 1% move, scaled to $M/$B).
    Bars are coloured by sign (positive = blue, negative = amber). A vertical
    line marks ``gex["spot"]`` ("spot") and, when present, ``gex["gamma_flip"]``
    ("flip").

    Best-effort: empty/missing walls render the "No gamma data" placeholder PNG.
    Never raises — any rendering failure falls back to the placeholder.
    """
    walls = (gex or {}).get("walls") or []
    points: list[tuple[float, float]] = []
    for w in walls:
        if not isinstance(w, dict):
            continue
        try:
            strike = float(w["strike"])
            gd = float(w["gamma_dollars"])
        except (KeyError, TypeError, ValueError):
            continue
        points.append((strike, gd))

    if not points:
        return _no_data_png("No gamma data")

    points.sort(key=lambda p: p[0])
    strikes = [p[0] for p in points]
    dollars = [p[1] for p in points]

    try:
        fig, ax = plt.subplots(figsize=_FIGSIZE_DEFAULT, dpi=_DPI)
        colors = ["#2563eb" if d >= 0 else "#f59e0b" for d in dollars]
        # Width relative to strike spacing so bars don't overlap or vanish.
        if len(strikes) > 1:
            spacing = min(abs(strikes[i + 1] - strikes[i]) for i in range(len(strikes) - 1))
            width = max(spacing * 0.6, 1e-6)
        else:
            width = max(abs(strikes[0]) * 0.02, 1.0)
        ax.bar(strikes, dollars, width=width, color=colors, edgecolor="#9ca3af", linewidth=0.5)

        ax.axhline(0.0, color="#9ca3af", linewidth=0.8)

        spot = (gex or {}).get("spot")
        if spot is not None:
            try:
                sv = float(spot)
                ax.axvline(sv, color="#16a34a", linewidth=1.4, linestyle="--")
                ax.annotate(
                    f"spot {sv:.2f}",
                    xy=(sv, 1.0),
                    xycoords=("data", "axes fraction"),
                    xytext=(3, -10),
                    textcoords="offset points",
                    color="#16a34a",
                    fontsize=8,
                    va="top",
                )
            except (TypeError, ValueError):
                pass

        flip = (gex or {}).get("gamma_flip")
        if flip is not None:
            try:
                fv = float(flip)
                ax.axvline(fv, color="#e11d48", linewidth=1.4, linestyle=":")
                ax.annotate(
                    f"flip {fv:.2f}",
                    xy=(fv, 1.0),
                    xycoords=("data", "axes fraction"),
                    xytext=(3, -24),
                    textcoords="offset points",
                    color="#e11d48",
                    fontsize=8,
                    va="top",
                )
            except (TypeError, ValueError):
                pass

        ax.set_title(title or "Dealer Gamma Walls (options-implied)", fontsize=11)
        ax.set_xlabel("Strike")
        ax.set_ylabel("Dealer $-gamma per 1% move")
        # Format the y tick labels as $M/$B without importing matplotlib.ticker.
        yticks = ax.get_yticks()
        ax.set_yticks(yticks)
        ax.set_yticklabels([_fmt_gamma_axis(v) for v in yticks])
        ax.grid(True, axis="y", alpha=0.3)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=_DPI, bbox_inches="tight")
        plt.close(fig)
        return buf.getvalue()
    except Exception:
        return _no_data_png("No gamma data")


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
            cum *= 1.0 + ret
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
