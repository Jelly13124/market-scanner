"""Tests for the bounded Phase-3 full-replay confirmation driver.

Phase 3 replays the REAL scanner Top-N over each regime via the existing
``v2.backtesting.engine.run_backtest``, with quant signals ON and OFF, to
report (a) real Top-N mean 5d alpha and (b) the quant-overlay ablation delta.

These tests NEVER touch the real engine: a fake ``run_backtest`` is injected.
It records its keyword calls and writes a tiny CSV to the ``output_path`` it
is handed, so the path-existence + CSV-mean plumbing is exercised offline.
"""

from __future__ import annotations

from v2.scanner.eval.phase3_backtest import (
    run_phase3,
    summarize_phase3,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Regime:
    """Minimal stand-in for ``RegimeWindow`` (attr access: name/start/end)."""

    def __init__(self, name: str, start: str, end: str) -> None:
        self.name = name
        self.start = start
        self.end = end


def _write_csv(path, rows, *, header="scan_date,ticker,alpha_5d,dir_alpha_5d") -> None:
    """Write a tiny CSV with the given header line + ``rows`` (list of strings)."""
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def _fake_engine_factory(rows_by_quant):
    """Build a fake ``run_backtest`` that records calls + writes a CSV.

    ``rows_by_quant`` maps ``use_quant`` (bool) → list of CSV data-row strings.
    Returns ``(fake_fn, calls)`` where ``calls`` accumulates the kwargs dicts.
    """
    calls: list[dict] = []

    def fake_run_backtest(**kwargs):
        calls.append(kwargs)
        rows = rows_by_quant[kwargs["use_quant_signals"]]
        _write_csv(kwargs["output_path"], rows)
        return len(rows)

    return fake_run_backtest, calls


# ---------------------------------------------------------------------------
# run_phase3
# ---------------------------------------------------------------------------


def test_run_phase3_calls_engine_per_regime_and_quant(tmp_path):
    regimes = [
        _Regime("bear_2022", "2022-01-03", "2022-10-14"),
        _Regime("bull_2023_24", "2023-10-27", "2024-07-16"),
    ]
    two_rows = ["2022-01-03,AAA,0.01,0.02", "2022-01-04,BBB,0.03,0.04"]
    fake, calls = _fake_engine_factory({True: two_rows, False: two_rows})

    result = run_phase3(
        regimes,
        out_dir=tmp_path,
        top_n=20,
        max_days=8,
        run_backtest=fake,
    )

    # 2 regimes x (on, off) = 4 engine calls.
    assert len(calls) == 4

    # Each call carried the right start/end + the toggled quant flag, and a
    # bounded max_days.
    by_name_quant = {(c["start_date"], c["use_quant_signals"]): c for c in calls}
    assert set(by_name_quant.keys()) == {
        ("2022-01-03", True),
        ("2022-01-03", False),
        ("2023-10-27", True),
        ("2023-10-27", False),
    }
    bear_on = by_name_quant[("2022-01-03", True)]
    assert bear_on["end_date"] == "2022-10-14"
    assert bear_on["start_date"] == "2022-01-03"
    assert bear_on["top_n"] == 20
    assert bear_on["max_days"] == 8
    bull_off = by_name_quant[("2023-10-27", False)]
    assert bull_off["end_date"] == "2024-07-16"

    # Result maps each regime to two EXISTING csv paths.
    assert set(result.keys()) == {"bear_2022", "bull_2023_24"}
    for name in ("bear_2022", "bull_2023_24"):
        entry = result[name]
        assert entry["quant_on_csv"] is not None
        assert entry["quant_off_csv"] is not None
        assert entry["quant_on_csv"].exists()
        assert entry["quant_off_csv"].exists()


def test_run_phase3_failsoft(tmp_path):
    regimes = [_Regime("bear_2022", "2022-01-03", "2022-10-14")]
    two_rows = ["2022-01-03,AAA,0.01,0.02", "2022-01-04,BBB,0.03,0.04"]
    calls: list[dict] = []

    def fake_run_backtest(**kwargs):
        calls.append(kwargs)
        if not kwargs["use_quant_signals"]:
            raise RuntimeError("boom on quant=off")
        _write_csv(kwargs["output_path"], two_rows)
        return len(two_rows)

    # No exception escapes.
    result = run_phase3(regimes, out_dir=tmp_path, run_backtest=fake_run_backtest)

    entry = result["bear_2022"]
    assert entry["quant_on_csv"] is not None
    assert entry["quant_on_csv"].exists()
    assert entry["quant_off_csv"] is None
    # Both calls were attempted.
    assert len(calls) == 2


def test_run_phase3_missing_csv_is_none(tmp_path):
    """Engine 'succeeds' but writes nothing → that csv entry is None, no crash."""
    regimes = [_Regime("bear_2022", "2022-01-03", "2022-10-14")]

    def fake_run_backtest(**kwargs):
        return 0  # writes no file

    result = run_phase3(regimes, out_dir=tmp_path, run_backtest=fake_run_backtest)
    entry = result["bear_2022"]
    assert entry["quant_on_csv"] is None
    assert entry["quant_off_csv"] is None


# ---------------------------------------------------------------------------
# summarize_phase3
# ---------------------------------------------------------------------------


def test_summarize_phase3(tmp_path):
    on_csv = tmp_path / "on.csv"
    off_csv = tmp_path / "off.csv"
    # quant ON: alpha_5d mean = (0.001 + 0.003)/2 = 0.002;
    #           dir_alpha_5d mean = (0.002 + 0.004)/2 = 0.003.
    _write_csv(
        on_csv,
        ["2022-01-03,AAA,0.001,0.002", "2022-01-04,BBB,0.003,0.004"],
    )
    # quant OFF: alpha_5d mean = (0.001 + 0.002)/2 = 0.0015.
    _write_csv(
        off_csv,
        ["2022-01-03,AAA,0.001,0.009", "2022-01-04,BBB,0.002,0.009"],
    )

    run_result = {
        "bear_2022": {"quant_on_csv": on_csv, "quant_off_csv": off_csv},
    }
    out = summarize_phase3(run_result)
    d = out["bear_2022"]
    assert d["mean_alpha_5d"] == abs_close(0.002)
    assert d["mean_dir_alpha_5d"] == abs_close(0.003)
    assert d["quant_on_alpha"] == abs_close(0.002)
    assert d["quant_off_alpha"] == abs_close(0.0015)
    assert d["quant_delta"] == abs_close(0.0005)
    assert d["n_on"] == 2
    assert d["n_off"] == 2


def test_summarize_missing_csv(tmp_path):
    run_result = {"bear_2022": {"quant_on_csv": None, "quant_off_csv": None}}
    out = summarize_phase3(run_result)
    d = out["bear_2022"]
    assert d["mean_alpha_5d"] is None
    assert d["mean_dir_alpha_5d"] is None
    assert d["quant_on_alpha"] is None
    assert d["quant_off_alpha"] is None
    assert d["quant_delta"] is None
    assert d["n_on"] == 0
    assert d["n_off"] == 0


def test_summarize_partial_csv(tmp_path):
    """quant_off missing but quant_on present → on numbers real, delta None."""
    on_csv = tmp_path / "on.csv"
    _write_csv(on_csv, ["2022-01-03,AAA,0.002,0.002"])
    run_result = {"bear_2022": {"quant_on_csv": on_csv, "quant_off_csv": None}}
    out = summarize_phase3(run_result)
    d = out["bear_2022"]
    assert d["quant_on_alpha"] == abs_close(0.002)
    assert d["quant_off_alpha"] is None
    assert d["quant_delta"] is None
    assert d["n_on"] == 1
    assert d["n_off"] == 0


# ---------------------------------------------------------------------------
# tiny float comparison helper
# ---------------------------------------------------------------------------


class _AbsClose:
    def __init__(self, target: float, tol: float = 1e-9) -> None:
        self.target = target
        self.tol = tol

    def __eq__(self, other) -> bool:
        return other is not None and abs(float(other) - self.target) <= self.tol

    def __repr__(self) -> str:  # pragma: no cover - debug aid only
        return f"~{self.target}"


def abs_close(target: float) -> _AbsClose:
    return _AbsClose(target)
