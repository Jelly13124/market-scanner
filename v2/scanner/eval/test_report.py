"""Tests for the findings-report renderer + verdict logic.

Fixed (no-randomness) row fixtures drive each verdict branch and the markdown
renderer. The PRIMARY detector verdict is interestingness-vs-random (does the
detector flag bigger movers than random) — directional alpha is shown as
secondary colour only and must NEVER be the sole basis for a CUT. Verdicts read
the 5d rows; 20d rows are included in the fixtures to prove they're ignored.
"""

from __future__ import annotations

from v2.scanner.eval.regimes import RegimeWindow
from v2.scanner.eval.report import (
    PRIMARY_HORIZON,
    build_verdict_index,
    classify_detector_verdict,
    classify_signal_verdict,
    render_report,
    write_report,
)


# ---------------------------------------------------------------------------
# Fixtures (fixed, deterministic)
# ---------------------------------------------------------------------------

_REGIME_NAMES = ("bear_2022", "bull_2023_24", "choppy_2025")
_REGIME_LABELS = ("BEAR", "BULL", "CHOPPY")


def _det_rows(name, *, diff, t, n_fired, coverage, dir_alpha=0.001):
    """One detector's rows across 3 regimes, both horizons.

    The 20d rows carry deliberately verdict-flipping junk values so that any
    test passing if 20d leaked into the verdict would fail.
    """
    rows = []
    for rname, rlabel in zip(_REGIME_NAMES, _REGIME_LABELS):
        rows.append(
            {
                "detector": name,
                "regime": rname,
                "regime_label": rlabel,
                "horizon": "5d",
                "n_fired": n_fired,
                "coverage": coverage,
                "interestingness_diff": diff,
                "interestingness_t": t,
                "abs_mean_fired": 0.05,
                "abs_mean_baseline": 0.05 - diff,
                "signed_mean_fired": 0.01,
                "dir_alpha_mean": dir_alpha,
                "dir_alpha_t": 1.5,
            }
        )
        # 20d row: junk that would flip every verdict if (wrongly) consulted.
        rows.append(
            {
                "detector": name,
                "regime": rname,
                "regime_label": rlabel,
                "horizon": "20d",
                "n_fired": 0,
                "coverage": 0.0,
                "interestingness_diff": -99.0,
                "interestingness_t": -99.0,
                "abs_mean_fired": 0.0,
                "abs_mean_baseline": 0.0,
                "signed_mean_fired": 0.0,
                "dir_alpha_mean": -99.0,
                "dir_alpha_t": -99.0,
            }
        )
    return rows


def _sig_rows(name, *, mean_ic, ic_t, n_dates, coverage):
    rows = []
    for rname, rlabel in zip(_REGIME_NAMES, _REGIME_LABELS):
        rows.append(
            {
                "signal": name,
                "regime": rname,
                "regime_label": rlabel,
                "horizon": "5d",
                "mean_ic": mean_ic,
                "ic_t": ic_t,
                "n_dates": n_dates,
                "coverage": coverage,
            }
        )
        rows.append(
            {
                "signal": name,
                "regime": rname,
                "regime_label": rlabel,
                "horizon": "20d",
                "mean_ic": -99.0,
                "ic_t": -99.0,
                "n_dates": 0,
                "coverage": 0.0,
            }
        )
    return rows


# Detectors
KEEP_DET = _det_rows("keep_det", diff=0.03, t=3.0, n_fired=40, coverage=0.9)
CUT_DET = _det_rows("cut_det", diff=-0.001, t=0.1, n_fired=50, coverage=0.9)
DATA_LIMITED_DET = _det_rows("dl_det", diff=0.03, t=3.0, n_fired=3, coverage=0.1)

# Signals
KEEP_SIG = _sig_rows("keep_sig", mean_ic=0.05, ic_t=3.0, n_dates=10, coverage=0.9)
INVERTED_SIG = _sig_rows("inv_sig", mean_ic=-0.05, ic_t=-3.0, n_dates=10, coverage=0.9)
DATA_LIMITED_SIG = _sig_rows("dl_sig", mean_ic=0.05, ic_t=3.0, n_dates=1, coverage=0.2)


def _rows_5d(rows):
    return [r for r in rows if r["horizon"] == PRIMARY_HORIZON]


_REGIMES = [
    RegimeWindow(
        name="bear_2022",
        start="2022-01-03",
        end="2022-10-14",
        spy_return=-0.25,
        max_drawdown=-0.27,
        trend_r2=0.85,
        n_bars=195,
        label="BEAR",
    ),
    RegimeWindow(
        name="bull_2023_24",
        start="2023-10-27",
        end="2024-07-16",
        spy_return=0.33,
        max_drawdown=-0.05,
        trend_r2=0.9,
        n_bars=180,
        label="BULL",
    ),
    RegimeWindow(
        name="choppy_2025",
        start="2025-02-18",
        end="2025-08-01",
        spy_return=0.02,
        max_drawdown=-0.12,
        trend_r2=0.1,
        n_bars=115,
        label="CHOPPY",
    ),
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_detector_verdicts():
    assert classify_detector_verdict(_rows_5d(KEEP_DET)) == "KEEP"
    assert classify_detector_verdict(_rows_5d(CUT_DET)) == "CUT"
    assert classify_detector_verdict(_rows_5d(DATA_LIMITED_DET)) == "DATA-LIMITED"


def test_signal_verdicts():
    assert classify_signal_verdict(_rows_5d(KEEP_SIG)) == "KEEP"
    assert classify_signal_verdict(_rows_5d(INVERTED_SIG)) == "INVERTED"
    assert classify_signal_verdict(_rows_5d(DATA_LIMITED_SIG)) == "DATA-LIMITED"


def test_verdicts_ignore_20d_rows():
    # Passing the FULL row set (5d + junk 20d) must yield the same verdicts: the
    # classifier filters to 5d itself when given mixed horizons via the index.
    idx = build_verdict_index(
        KEEP_DET + CUT_DET + DATA_LIMITED_DET,
        KEEP_SIG + INVERTED_SIG + DATA_LIMITED_SIG,
    )
    assert idx["detectors"]["keep_det"] == "KEEP"
    assert idx["detectors"]["cut_det"] == "CUT"
    assert idx["detectors"]["dl_det"] == "DATA-LIMITED"
    assert idx["signals"]["keep_sig"] == "KEEP"
    assert idx["signals"]["inv_sig"] == "INVERTED"
    assert idx["signals"]["dl_sig"] == "DATA-LIMITED"


def _render_kwargs(phase3=None):
    return dict(
        detector_rows=KEEP_DET + CUT_DET + DATA_LIMITED_DET,
        signal_rows=KEEP_SIG + INVERTED_SIG + DATA_LIMITED_SIG,
        regimes=_REGIMES,
        phase3=phase3,
    )


def test_render_contains_headline_and_tables():
    md = render_report(**_render_kwargs(phase3=None))
    assert md.startswith("# Scanner detector")
    assert "## Headline" in md
    assert "## Detector scorecard" in md
    assert "## Signal scorecard" in md
    assert "## Methodology" in md
    # KEEP detector listed under a Useful section; CUT under Useless.
    assert "keep_det" in md
    assert "cut_det" in md
    # phase3 is None → pending marker present.
    assert "pending" in md.lower()
    # Regime windows table renders the regime labels.
    assert "## Regime windows" in md
    assert "BEAR" in md

    # Headline ordering: the "Useful detectors" line names keep_det; the
    # "Useless" line names cut_det. Verify they land on the intended lines.
    useful_det_line = next(ln for ln in md.splitlines() if ln.startswith("**Useful detectors"))
    assert "keep_det" in useful_det_line
    useless_det_line = next(ln for ln in md.splitlines() if ln.startswith("**Useless"))
    assert "cut_det" in useless_det_line


def test_render_with_phase3():
    phase3 = {"bear_2022": {"mean_alpha_5d": 0.001, "quant_on": 0.002, "quant_off": 0.0015}}
    md = render_report(**_render_kwargs(phase3=phase3))
    assert "bear_2022" in md
    # A quant ON vs OFF line is rendered somewhere in the Phase 3 section.
    low = md.lower()
    assert "quant" in low
    assert "on" in low and "off" in low
    assert "## Phase 3" in md


def test_write_report_roundtrip(tmp_path):
    out = tmp_path / "report.md"
    write_report(out, **_render_kwargs(phase3=None))
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# Scanner detector")
