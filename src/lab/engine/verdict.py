"""Phase 6C: verdict logic adapted from stock-analyze-skills hard rules."""

from __future__ import annotations

from dataclasses import dataclass

from src.lab.engine.metrics import Metrics


@dataclass
class Verdict:
    label: str           # 'insufficient'|'reject'|'overfit'|'weak'|'underperform_bench'|'positive_edge'
    text: str            # 1-3 sentence prose explanation
    degradation_ratio: float


def make_verdict(is_m: Metrics, oos_m: Metrics, benchmark_cagr: float | None) -> Verdict:
    if oos_m.n_trades < 5 or is_m.n_trades < 5:
        return Verdict(
            label="insufficient",
            text=("Insufficient trades to evaluate "
                  f"(IS={is_m.n_trades}, OOS={oos_m.n_trades}; need >=5 each). "
                  "Loosen entry conditions or extend the window."),
            degradation_ratio=0.0,
        )
    if is_m.cagr <= 0:
        return Verdict(
            label="reject",
            text=(f"Strategy LOSES money in-sample (IS CAGR {is_m.cagr*100:+.1f}%; "
                  f"OOS {oos_m.cagr*100:+.1f}%). No edge to begin with - reject. "
                  "Try different signals, a longer window, or fewer filters."),
            degradation_ratio=0.0,
        )
    degradation = oos_m.cagr / is_m.cagr
    if oos_m.cagr < 0:
        return Verdict(
            label="reject",
            text=(f"Strategy LOSES money out-of-sample (OOS CAGR {oos_m.cagr*100:+.1f}%). "
                  f"In-sample edge ({is_m.cagr*100:+.1f}% CAGR) was overfit or regime-dependent. "
                  "Reject - do not deploy."),
            degradation_ratio=degradation,
        )
    if degradation < 0.4:
        return Verdict(
            label="overfit",
            text=(f"Strategy showed in-sample edge ({is_m.cagr*100:+.1f}% CAGR) but "
                  f"OOS degraded heavily ({oos_m.cagr*100:+.1f}% CAGR, ratio {degradation:.2f}). "
                  "Likely overfit - be skeptical."),
            degradation_ratio=degradation,
        )
    if degradation < 0.6:
        return Verdict(
            label="weak",
            text=(f"Positive edge in BOTH IS ({is_m.cagr*100:+.1f}%) and "
                  f"OOS ({oos_m.cagr*100:+.1f}%) after costs, "
                  f"but degradation ratio {degradation:.2f} is below 0.6. "
                  "Suggest re-testing on other markets / windows before sizing capital."),
            degradation_ratio=degradation,
        )
    if benchmark_cagr is not None and oos_m.cagr < benchmark_cagr:
        return Verdict(
            label="underperform_bench",
            text=(f"Strategy generated positive edge ({oos_m.cagr*100:+.1f}% OOS CAGR) "
                  f"but underperformed benchmark ({benchmark_cagr*100:+.1f}%). "
                  "Consider passive alternative."),
            degradation_ratio=degradation,
        )
    bench_str = f"{benchmark_cagr*100:+.1f}%" if benchmark_cagr is not None else "n/a"
    return Verdict(
        label="positive_edge",
        text=(f"POSITIVE edge in BOTH IS ({is_m.cagr*100:+.1f}%) and "
              f"OOS ({oos_m.cagr*100:+.1f}%) after costs, outperforming benchmark "
              f"({bench_str}). "
              "Suggest re-test on N peers + a different window before sizing capital."),
        degradation_ratio=degradation,
    )
