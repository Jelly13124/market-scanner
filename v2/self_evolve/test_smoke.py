"""OFFLINE end-to-end smoke for the self-evolve loop + run report (Task 8).

This is the *only* test that drives the whole pipeline end to end —
``evolve`` (the keep/rollback loop) → a SINGLE post-loop ``backtest`` on the
held-out ``test`` sample → ``write_report`` (md + html + iteration-path PNG) —
and it does so with ZERO network and ZERO LLM:

* The bundles are small SYNTHETIC ``SimpleNamespace`` price series spanning the
  train+val+test windows, exactly the duck-typed shape the real backtest reads.
* The proposer is a STUB emitting canned deltas; the real DeepSeek proposer is
  never imported or called. We assert that explicitly: ``src.llm.models`` must
  not be in ``sys.modules`` after the run.

The load-bearing contracts pinned here:

1. The ``test`` sample is read EXACTLY ONCE, and only AFTER the loop returns
   (the loop itself reads train+val only — proven by the sample recorder).
2. ``write_report`` emits ``self_evolve_report.md`` + ``self_evolve_report.html``;
   the html embeds version ids, an inline ``data:image/png`` chart, and a numeric
   test Sharpe.
3. ``render_iteration_path_png`` returns real PNG bytes (``\\x89PNG`` magic).

No pandas of our own, no data files — pure synthetic Python.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from types import SimpleNamespace

from v2.self_evolve.backtest import backtest
from v2.self_evolve.config import StrategyConfig
from v2.self_evolve.loop import evolve
from v2.self_evolve.report import render_iteration_path_png, write_report
from v2.self_evolve.versioning import read_version


# ---------------------------------------------------------------------------
# Synthetic bundles spanning train + val + test
# ---------------------------------------------------------------------------

# train = [2016-01-01, 2021-12-31], val = [2022-01-01, 2023-12-31],
# test  = [2024-01-01, 2030-12-31]. The smoke only needs each window to contain
# >1 monthly rebalance, so we span a daily calendar from inside train (2021, also
# giving a year of pre-val lookback history) through the first half of the test
# window (2024 H1). That keeps the real backtest exercising ALL THREE samples
# while staying fast.
_HIST_START = date(2021, 1, 1)
_SPAN_END = date(2024, 6, 30)


def _price(d: str, close: float, volume: float) -> SimpleNamespace:
    return SimpleNamespace(time=d, close=close, volume=volume)


def _daily_dates(start: date, end: date) -> list[date]:
    out: list[date] = []
    d = start
    one = timedelta(days=1)
    while d <= end:
        out.append(d)
        d += one
    return out


_DAYS = _daily_dates(_HIST_START, _SPAN_END)


def _bundle(close_fn, *, volume: float = 2_000_000.0) -> SimpleNamespace:
    prices = [_price(d.isoformat(), float(close_fn(i)), volume) for i, d in enumerate(_DAYS)]
    return SimpleNamespace(prices=prices, metrics_history=[])


def _synthetic_bundles() -> dict:
    """Five names ramping upward at different slopes over the whole span.

    A steadily rising, non-degenerate cross-section so every sample window
    (train/val/test) has >1 monthly rebalance and a well-defined book.
    """
    slopes = {"A": 0.10, "B": 0.09, "C": 0.08, "D": 0.07, "E": 0.06}
    return {t: _bundle(lambda i, s=s: 100.0 + s * i + (i % 5) * 0.5) for t, s in slopes.items()}


def _base_config() -> StrategyConfig:
    return StrategyConfig(
        factor_weights={"momentum": 0.30, "low_vol": 0.25, "reversal": 0.15, "value": 0.15, "quality": 0.15},
        lookback={"momentum_days": 120, "vol_days": 20, "reversal_days": 5},
        top_n=30,
        holding_buffer=5,
        max_weight=0.08,  # top of the ADJUSTABLE [0.03, 0.08] range — deltas must keep it valid
        liquidity_pct={"mktcap_pct": 0.0, "advol_pct": 0.0},
        tilt_strength=0.5,
    )


def _scripted_propose(deltas):
    """A ``propose_fn`` emitting ``deltas`` in order then ``None`` — never the LLM."""
    seq = list(deltas)
    state = {"n": 0}

    def propose_fn(skill_md, config, val_history, *, llm_fn=None):
        i = state["n"]
        state["n"] += 1
        return seq[i] if i < len(seq) else None

    return propose_fn


def _best_config_from_versions(base_dir, path_log) -> StrategyConfig:
    """Rebuild the last KEPT version's config — what run.py hands write_report."""
    last_kept = None
    for entry in path_log:
        if entry.get("kept"):
            last_kept = entry.get("v_id")
    rec = read_version(base_dir, last_kept)
    cfg = rec.get("config") or {}
    return StrategyConfig(**cfg)


# ---------------------------------------------------------------------------
# The end-to-end OFFLINE smoke
# ---------------------------------------------------------------------------


def test_end_to_end_offline_smoke(tmp_path):
    # Guard: the LLM stack must not be imported at any point in this test.
    sys.modules.pop("src.llm.models", None)

    bundles = _synthetic_bundles()
    base = _base_config()
    base_dir = tmp_path / "skill"
    out_dir = tmp_path / "out"

    # Record every sample the loop backtests, so we can PROVE the loop never
    # touched "test" — the held-out sample is read only once, post-loop, below.
    seen_samples: list[str] = []

    def recording_backtest(b, config, sample):
        seen_samples.append(sample)
        return backtest(b, config, sample)

    # A couple of bounded deltas (well in range) so the loop does real work.
    propose_fn = _scripted_propose(
        [
            {"path": "top_n", "value": 25, "hypothesis": "tighter book"},
            {"path": "factor_weights.momentum", "value": 0.5, "hypothesis": "lean momentum"},
            None,
        ]
    )

    path_log = evolve(
        bundles,
        base,
        iterations=3,
        base_dir=base_dir,
        skill_md="KERNEL",
        propose_fn=propose_fn,
        backtest_fn=recording_backtest,
    )

    # --- Sample isolation: the loop read train+val only, NEVER test.
    assert "train" in seen_samples
    assert "val" in seen_samples
    assert "test" not in seen_samples
    # The loop did real work: the path has the baseline plus >=1 evolved round.
    assert len(path_log) >= 2

    # --- best_config = last KEPT version's config (what run.py resolves).
    best_config = _best_config_from_versions(base_dir, path_log)

    # --- The ONE and ONLY test read: a single post-loop backtest on "test".
    # The loop above recorded ZERO "test" reads; this is the first and only one.
    assert seen_samples.count("test") == 0
    test_metrics = backtest(bundles, best_config, "test")
    assert test_metrics["n_rebalances"] > 1  # the test window produced a real curve

    # --- Render the report.
    out = write_report(
        out_dir,
        base_dir=base_dir,
        bundles=bundles,
        best_config=best_config,
        test_metrics=test_metrics,
    )

    md_path = out["report_md"]
    html_path = out["report_html"]
    assert md_path and html_path
    assert (out_dir / "self_evolve_report.md").is_file()
    assert (out_dir / "self_evolve_report.html").is_file()

    html = (out_dir / "self_evolve_report.html").read_text(encoding="utf-8")
    md = (out_dir / "self_evolve_report.md").read_text(encoding="utf-8")

    # Version ids from the path appear in the report (the iteration path table).
    ids = [e["v_id"] for e in path_log]
    assert "v0" in ids  # sanity: the baseline is in the path
    for vid in ids:
        assert vid in html
        assert vid in md

    # An inline PNG is embedded in the html.
    assert "data:image/png" in html

    # The TEST Sharpe (a number) is reported and returned.
    assert "test_sharpe" in out
    ts = out["test_sharpe"]
    assert ts is None or isinstance(ts, (int, float))
    # The test sample produced a real Sharpe here; it must surface in the html
    # and equal what the loop's single test backtest computed.
    assert ts == test_metrics["sharpe"]
    if ts is not None:
        # The report renders the test Sharpe to 3 decimals; that exact number
        # must appear in the html (a real test-Sharpe number is surfaced).
        assert f"{float(ts):.3f}" in html

    # The honest caveat is present.
    assert "val improvement" in html.lower() or "val improvement" in md.lower()

    # --- The chart helper returns real PNG bytes.
    png = render_iteration_path_png(path_log)
    assert isinstance(png, (bytes, bytearray))
    assert bytes(png[:4]) == b"\x89PNG"

    # --- The smoke NEVER imported the LLM stack.
    assert "src.llm.models" not in sys.modules


def test_render_iteration_path_png_never_raises_on_sparse():
    # A degenerate / empty path log must still yield a valid placeholder PNG.
    for sparse in ([], [{"v_id": "v0", "val_sharpe": None, "kept": True}]):
        png = render_iteration_path_png(sparse)
        assert isinstance(png, (bytes, bytearray))
        assert bytes(png[:4]) == b"\x89PNG"
