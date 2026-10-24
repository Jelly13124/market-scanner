"""Tests for the ``run_eval`` integration capstone of the scanner-eval harness.

``run_eval`` orchestrates the whole evaluation in three fail-soft phases,
rewriting the report after each so a partial run still yields a readable
morning report:

  * Phase 1 (guaranteed): prefetch price history → score all detectors + signals
    on price data → write CSVs + report.
  * Phase 2 (best-effort, time-boxed): enrich bundles with historical event /
    fundamental data → RE-score → rewrite report.
  * Phase 3 (bounded): full-replay confirmation per regime quant on/off → rewrite.

These tests NEVER touch the network: EVERY external collaborator is
monkeypatched on the ``run_eval`` module with a fake. We assert the fail-soft
contract (a phase blowing up must not abort the run nor lose the Phase-1
report), the phase-3 key mapping (summary keys → report keys), the
``--no-phase3`` skip, and the ``max_tickers`` slice.
"""

from __future__ import annotations

from pathlib import Path

import v2.scanner.eval.run_eval as run_eval_mod
from v2.scanner.eval.run_eval import run_eval


# ---------------------------------------------------------------------------
# Fakes / helpers
# ---------------------------------------------------------------------------


class _Regime:
    """Minimal stand-in for ``RegimeWindow`` (attr access used by the report)."""

    def __init__(self, name, start, end, label="CHOPPY"):
        self.name = name
        self.start = start
        self.end = end
        self.label = label
        self.spy_return = 0.0
        self.max_drawdown = 0.0
        self.trend_r2 = 0.0


def _det_rows(regimes):
    """One 5d + one 20d detector row per regime for a single fake detector."""
    rows = []
    for r in regimes:
        for h in ("5d", "20d"):
            rows.append(
                {
                    "detector": "fake_det",
                    "regime": r.name,
                    "regime_label": r.label,
                    "horizon": h,
                    "n_fired": 50,
                    "coverage": 0.9,
                    "interestingness_diff": 0.01,
                    "interestingness_t": 3.0,
                    "abs_mean_fired": 0.05,
                    "abs_mean_baseline": 0.04,
                    "signed_mean_fired": 0.01,
                    "dir_alpha_mean": 0.001,
                    "dir_alpha_t": 1.0,
                }
            )
    return rows


def _sig_rows(regimes):
    """One 5d + one 20d signal row per regime for a single fake signal."""
    rows = []
    for r in regimes:
        for h in (5, 20):
            rows.append(
                {
                    "signal": "fake_sig",
                    "regime": r.name,
                    "regime_label": r.label,
                    "horizon": h,
                    "mean_ic": 0.03,
                    "ic_t": 3.0,
                    "n_dates": 10,
                    "coverage": 0.9,
                }
            )
    return rows


def _install_happy_fakes(monkeypatch, report_root, *, universe_tickers=("AAA", "BBB", "CCC")):
    """Patch every external collaborator on the run_eval module with a fake.

    ``report_root`` redirects ``_repo_root()`` so the report lands under the
    test's ``tmp_path`` instead of polluting the real repo root (production
    still writes it to the actual repo root). Returns a ``calls`` dict recording
    what each fake observed, so tests can assert on call counts / arguments.
    """
    regimes = [
        _Regime("bear_2022", "2022-01-03", "2022-10-14", "BEAR"),
        _Regime("bull_2023_24", "2023-10-27", "2024-07-16", "BULL"),
        _Regime("choppy_2025", "2025-02-18", "2025-08-01", "CHOPPY"),
    ]
    calls: dict = {
        "prefetch_tickers": None,
        "score_detectors_bundles": [],
        "score_signals_bundles": [],
        "enrich": 0,
        "run_phase3": 0,
        "summarize": 0,
    }

    def fake_provider_factory():
        return object()  # never used by the fakes; just a sentinel client

    def fake_get_provider_factory():
        return fake_provider_factory

    def fake_load_universe(kind, custom=None):
        return list(universe_tickers)

    def fake_fetch_spy(provider_factory, start, end):
        return ["SPY_PRICES"]

    def fake_classify_regimes(spy_prices, *a, **k):
        return regimes

    def fake_prefetch(tickers, provider_factory, start, end):
        calls["prefetch_tickers"] = list(tickers)
        # one bundle per ticker — a plain object with the attrs enrich touches
        return {t: _Bundle(t) for t in tickers}

    def fake_score_all_detectors(detectors, rgs, bundles, spy, **kw):
        calls["score_detectors_bundles"].append(dict(bundles))
        return _det_rows(rgs)

    def fake_score_all_signals(signals, rgs, bundles, **kw):
        calls["score_signals_bundles"].append(dict(bundles))
        return _sig_rows(rgs)

    def fake_enrich(bundle, **kw):
        calls["enrich"] += 1
        return {"earnings": 0}

    def fake_run_phase3(rgs, **kw):
        calls["run_phase3"] += 1
        return {"_raw": True}

    def fake_summarize_phase3(rr):
        calls["summarize"] += 1
        return {}

    monkeypatch.setattr(run_eval_mod, "get_provider_factory", fake_get_provider_factory)
    monkeypatch.setattr(run_eval_mod, "load_universe", fake_load_universe)
    monkeypatch.setattr(run_eval_mod, "fetch_spy", fake_fetch_spy)
    monkeypatch.setattr(run_eval_mod, "classify_regimes", fake_classify_regimes)
    monkeypatch.setattr(run_eval_mod, "prefetch_price_bundles", fake_prefetch)
    monkeypatch.setattr(run_eval_mod, "score_all_detectors", fake_score_all_detectors)
    monkeypatch.setattr(run_eval_mod, "score_all_signals", fake_score_all_signals)
    monkeypatch.setattr(run_eval_mod, "enrich_bundle", fake_enrich)
    monkeypatch.setattr(run_eval_mod, "run_phase3", fake_run_phase3)
    monkeypatch.setattr(run_eval_mod, "summarize_phase3", fake_summarize_phase3)
    monkeypatch.setattr(run_eval_mod, "_repo_root", lambda: Path(report_root))
    return calls, regimes


class _Bundle:
    """Tiny TickerBundle stand-in (attrs enrich would touch)."""

    def __init__(self, ticker):
        self.ticker = ticker
        self.prices = ["P"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_phase1_report_written(tmp_path, monkeypatch):
    """Happy path: the report file exists and carries a detector table."""
    calls, _ = _install_happy_fakes(monkeypatch, tmp_path)

    report_path = run_eval(
        out_dir=str(tmp_path / "out"),
        generated_at="2026-05-31T00:00",
    )

    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "## Detector scorecard" in text
    assert "fake_det" in text
    # Phase 1 scored detectors at least once.
    assert len(calls["score_detectors_bundles"]) >= 1
    # CSVs landed in out_dir.
    assert (tmp_path / "out" / "detectors.csv").exists()
    assert (tmp_path / "out" / "signals.csv").exists()


def test_phase2_failure_is_failsoft(tmp_path, monkeypatch):
    """enrich_bundle raising must NOT abort the run: Phase-1 report survives and
    Phase 3 still runs. No exception escapes run_eval."""
    calls, _ = _install_happy_fakes(monkeypatch, tmp_path)

    def boom(bundle, **kw):
        raise RuntimeError("enrich exploded")

    monkeypatch.setattr(run_eval_mod, "enrich_bundle", boom)

    report_path = run_eval(
        out_dir=str(tmp_path / "out"),
        generated_at="2026-05-31T00:00",
    )

    # Report still on disk (Phase 1 wrote it before Phase 2 blew up).
    assert report_path.exists()
    assert "## Detector scorecard" in report_path.read_text(encoding="utf-8")
    # Phase 3 still got its chance despite Phase 2 failing.
    assert calls["run_phase3"] == 1


def test_no_phase3_skips_it(tmp_path, monkeypatch):
    """do_phase3=False → run_phase3 fake is never called; report still written."""
    calls, _ = _install_happy_fakes(monkeypatch, tmp_path)

    report_path = run_eval(
        out_dir=str(tmp_path / "out"),
        do_phase3=False,
        generated_at="2026-05-31T00:00",
    )

    assert report_path.exists()
    assert calls["run_phase3"] == 0
    assert calls["summarize"] == 0


def test_phase3_key_mapping(tmp_path, monkeypatch):
    """summarize_phase3 returns the quant_on_alpha/quant_off_alpha shape; the
    report must end up containing the phase-3 numbers, proving the summary keys
    were mapped onto the report's expected keys before rendering."""
    calls, _ = _install_happy_fakes(monkeypatch, tmp_path)

    def fake_summarize(rr):
        calls["summarize"] += 1
        return {
            "bear_2022": {
                "mean_alpha_5d": 0.0123,
                "mean_dir_alpha_5d": 0.0099,
                "quant_on_alpha": 0.0456,
                "quant_off_alpha": 0.0011,
                "quant_delta": 0.0445,
                "n_on": 7,
                "n_off": 7,
            }
        }

    monkeypatch.setattr(run_eval_mod, "summarize_phase3", fake_summarize)

    report_path = run_eval(
        out_dir=str(tmp_path / "out"),
        generated_at="2026-05-31T00:00",
    )

    text = report_path.read_text(encoding="utf-8")
    # The phase-3 table renders mean_alpha_5d, quant ON, quant OFF as percentages.
    assert "+1.23%" in text  # mean_alpha_5d 0.0123
    assert "+4.56%" in text  # quant_on  0.0456
    assert "+0.11%" in text  # quant_off 0.0011


def test_max_tickers_slice(tmp_path, monkeypatch):
    """max_tickers=2 with a 5-ticker universe → only 2 tickers reach prefetch."""
    calls, _ = _install_happy_fakes(monkeypatch, tmp_path, universe_tickers=("AAA", "BBB", "CCC", "DDD", "EEE"))

    run_eval(
        out_dir=str(tmp_path / "out"),
        max_tickers=2,
        generated_at="2026-05-31T00:00",
    )

    assert calls["prefetch_tickers"] == ["AAA", "BBB"]
    # The scored bundles were the 2 prefetched ones, not all 5.
    assert set(calls["score_detectors_bundles"][0].keys()) == {"AAA", "BBB"}
