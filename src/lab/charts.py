"""Phase 6G: matplotlib chart renderers for Lab backtest results.

All three return PNG bytes (Agg backend) so the FastAPI route can
serve them with content-type image/png.
"""

from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def render_equity_curve_png(
    is_curve: list[float],
    oos_curve: list[float],
    *,
    benchmark_curve: list[float] | None = None,
    midpoint_label: str = "",
) -> bytes:
    fig, ax = plt.subplots(figsize=(10, 4), dpi=80)
    if not is_curve and not oos_curve:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig)

    combined = list(is_curve) + list(oos_curve)
    n_is = len(is_curve)
    x = np.arange(len(combined))
    if is_curve:
        ax.plot(x[:n_is], is_curve, color="#2563eb", linewidth=1.5, label="In-sample")
    if oos_curve:
        ax.plot(x[n_is:], oos_curve, color="#16a34a", linewidth=1.5, label="Out-of-sample")
    if benchmark_curve and len(benchmark_curve) >= len(combined):
        ax.plot(
            x,
            benchmark_curve[: len(combined)],
            color="#94a3b8",
            linewidth=1,
            linestyle="--",
            label="Benchmark (SPY)",
        )
    if n_is > 0 and oos_curve:
        ax.axvline(x=n_is, color="#64748b", linestyle=":", linewidth=1)
        ax.text(
            n_is,
            ax.get_ylim()[1],
            f" {midpoint_label}",
            fontsize=8,
            color="#64748b",
            verticalalignment="top",
        )
    ax.set_xlabel("Trading days")
    ax.set_ylabel("Portfolio value ($)")
    ax.set_title("Equity Curve - In-Sample vs Out-of-Sample")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.3)
    return _save(fig)


def render_drawdown_png(equity_curve: list[float]) -> bytes:
    fig, ax = plt.subplots(figsize=(10, 3), dpi=80)
    if not equity_curve:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig)
    eq = np.array(equity_curve, dtype=float)
    # Guard against zero/negative peaks (shouldn't happen for equity, but be safe)
    peaks = np.maximum.accumulate(eq)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peaks > 0, (eq - peaks) / peaks * 100, 0.0)
    ax.fill_between(np.arange(len(eq)), dd, 0, color="#b91c1c", alpha=0.4)
    ax.plot(dd, color="#b91c1c", linewidth=1)
    ax.set_xlabel("Trading days")
    ax.set_ylabel("Drawdown (%)")
    ax.set_title(f"Drawdown - max {float(dd.min()):.1f}%")
    ax.grid(True, alpha=0.3)
    return _save(fig)


def render_monthly_heatmap_png(trades: list[dict]) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 4), dpi=80)
    if not trades:
        ax.text(0.5, 0.5, "No trades", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return _save(fig)
    # Aggregate trade PnL by year-month
    by_ym: dict[tuple[int, int], float] = {}
    for t in trades:
        exit_date = t.get("exit_date", "") or ""
        try:
            dt = datetime.fromisoformat(exit_date[:10])
        except Exception:
            continue
        key = (dt.year, dt.month)
        by_ym[key] = by_ym.get(key, 0.0) + float(t.get("pnl", 0) or 0)
    if not by_ym:
        ax.text(
            0.5,
            0.5,
            "No dated trades",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        ax.set_axis_off()
        return _save(fig)
    years = sorted({y for (y, _) in by_ym})
    matrix = np.full((len(years), 12), np.nan)
    for (y, m), pnl in by_ym.items():
        matrix[years.index(y), m - 1] = pnl

    # Symmetric color range around zero using abs-max so the diverging
    # RdYlGn colormap centers on 0. Guard against all-NaN matrix (covered
    # by `if not by_ym` above, but defensive).
    valid = matrix[~np.isnan(matrix)]
    if valid.size > 0:
        abs_max = float(np.max(np.abs(valid)))
        if abs_max <= 0:
            abs_max = 1.0
    else:
        abs_max = 1.0
    im = ax.imshow(
        matrix,
        aspect="auto",
        cmap="RdYlGn",
        vmin=-abs_max,
        vmax=abs_max,
    )
    ax.set_xticks(range(12))
    ax.set_xticklabels(["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"])
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels(years)
    ax.set_title("Monthly PnL ($)")
    fig.colorbar(im, ax=ax, shrink=0.6)
    return _save(fig)


def _save(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
