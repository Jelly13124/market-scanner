"""Re-render findings_scanner_eval.md from the on-disk scorecard CSVs.

The expensive part of the eval (detector replay + signal IC) is already captured
in scanner_eval/{detectors,signals}.csv. When only the *report* layer changes
(e.g. the horizon-normalization fix), re-rendering from the CSVs is instant and
avoids a multi-hour re-run.

Usage:
    PYTHONPATH=. python scripts/rerender_eval_report.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from v2.scanner.eval.regimes import RegimeWindow
from v2.scanner.eval.report import write_report

REPO = Path(__file__).resolve().parents[1]

# Non-numeric columns kept as strings; everything else coerced to float so the
# report formatters (which do arithmetic) work on CSV round-tripped rows.
_STR_COLS = {"detector", "signal", "regime", "regime_label", "horizon"}


def _load(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        coerced = {}
        for k, v in r.items():
            if k in _STR_COLS:
                coerced[k] = v
            else:
                try:
                    coerced[k] = float(v)
                except (TypeError, ValueError):
                    coerced[k] = v
        out.append(coerced)
    return out


# Regime windows as classified from real SPY in the 2026-05-31 run (see run log).
REGIMES = [
    RegimeWindow(name="bear_2022", start="2022-01-03", end="2022-10-14",
                 spy_return=-0.2427, max_drawdown=-0.2450, trend_r2=0.63,
                 n_bars=198, label="BEAR"),
    RegimeWindow(name="bull_2023_24", start="2023-10-27", end="2024-07-16",
                 spy_return=0.3898, max_drawdown=-0.0535, trend_r2=0.91,
                 n_bars=179, label="BULL"),
    RegimeWindow(name="choppy_2025", start="2025-02-18", end="2025-08-01",
                 spy_return=0.0228, max_drawdown=-0.1876, trend_r2=0.42,
                 n_bars=115, label="CHOPPY"),
]


def _load_phase3():
    """Load the Phase-3 summary JSON if the standalone run produced one."""
    import json

    p = REPO / "scanner_eval" / "phase3_summary.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def main() -> None:
    det = _load(REPO / "scanner_eval" / "detectors.csv")
    sig = _load(REPO / "scanner_eval" / "signals.csv")
    phase3 = _load_phase3()
    out = REPO / "findings_scanner_eval.md"
    tag = "Phase 1+2+3" if phase3 else "Phase 1+2"
    write_report(
        out,
        detector_rows=det,
        signal_rows=sig,
        regimes=REGIMES,
        phase3=phase3,
        universe="nasdaq100_sp500 (80-ticker subset)",
        generated_at=f"2026-05-31 ({tag})",
    )
    print(f"re-rendered {out} (phase3={'yes' if phase3 else 'no'})")


if __name__ == "__main__":
    main()
