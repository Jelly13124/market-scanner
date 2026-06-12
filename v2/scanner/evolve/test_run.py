"""Offline tests for the scanner-evolve wiring (Task 6).

Everything here is OFFLINE + DETERMINISTIC: a STUB proposer emits a scripted
scanner delta, and the fitness is either STUBBED (controlled metric dicts) or the
real :func:`scanner_fitness` over tiny synthetic bundles. No network, no LLM, no
data files.

What these prove:

1. **Wiring** — ``evolve_scanner`` with a stub proposer + stub fitness writes a
   path log with ``v0`` + round versions under ``base_dir``.
2. **keep / rollback** — ``_scanner_keep`` directly AND via the loop: a candidate
   with higher ``diff`` + adequate ``n_fired`` + non-worse ``t_stat`` is KEPT; a
   collapsed-``n_fired`` candidate is ROLLED BACK; a lower-``diff`` candidate is
   ROLLED BACK.
3. **Sample isolation** (invariant #1) — across the WHOLE run the fitness is NEVER
   called with ``sample == "test"``.
4. **Resumable** — re-running on the same ``base_dir`` continues the round counter
   and restores the running-best.
5. **Factor engine untouched** — a factor-style ``evolve(...)`` with NO seams
   still behaves identically.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from v2.scanner.evolve import run as run_mod
from v2.scanner.evolve.config import ScannerEvolveConfig, load_config
from v2.scanner.evolve.run import _scanner_keep, evolve_scanner
from v2.self_evolve.versioning import list_versions, read_path_log, read_version

from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "scanner_skill_config.yaml"


# ---------------------------------------------------------------------------
# Fixtures: a real base config + scriptable proposer / fitness stubs
# ---------------------------------------------------------------------------


def _base_config() -> ScannerEvolveConfig:
    return load_config(_CONFIG_PATH)


def _scripted_propose(deltas):
    """A ``propose_fn`` emitting ``deltas`` in order, then ``None`` forever.

    Matches the proposer seam signature ``(skill, config, val_history, *, llm_fn=None)``.
    """
    seq = list(deltas)
    calls = {"n": 0}

    def propose_fn(skill, config, val_history, *, llm_fn=None):
        i = calls["n"]
        calls["n"] += 1
        return seq[i] if i < len(seq) else None

    propose_fn.calls = calls
    return propose_fn


def _fit(*, diff, t_stat=2.0, n_fired=100, alpha_5d=None):
    return {"fitness": diff, "diff": diff, "t_stat": t_stat, "n_fired": n_fired, "alpha_5d": alpha_5d}


def _keyed_fitness(table, *, default=None, record=None):
    """A stub ``scanner_fitness`` keyed by ``(gap.threshold, sample)``.

    Each scripted delta moves ``detectors.gap.threshold`` to a distinct value, so
    the candidate's gap threshold identifies which round we're scoring. ``record``
    (if given) collects every ``sample`` arg — used by the isolation test.

    Signature mirrors the real ``scanner_fitness`` (the loop calls it positionally
    as ``fitness(bundles, config, sample, ...)`` via ``evolve_scanner``'s closure;
    the closure passes only the 3 positional args + kwargs we ignore).
    """

    def fitness_fn(bundles, config, sample, **kwargs):
        if record is not None:
            record.append(sample)
        key = (config.detectors["gap"]["threshold"], sample)
        if key in table:
            return table[key]
        if default is not None:
            return default
        return _fit(diff=0.0)

    return fitness_fn


# ---------------------------------------------------------------------------
# 1. _scanner_keep — drive the keep rule directly
# ---------------------------------------------------------------------------


def test_scanner_keep_higher_diff_adequate_fired_nonworse_t_is_kept():
    base = _fit(diff=0.01, t_stat=2.0, n_fired=100)
    best = _fit(diff=0.01, t_stat=2.0, n_fired=100)
    cand = _fit(diff=0.02, t_stat=2.1, n_fired=90)  # higher diff, fine n_fired, better t
    assert _scanner_keep(cand, best, base) is True


def test_scanner_keep_collapsed_n_fired_rolled_back():
    base = _fit(diff=0.01, n_fired=100)  # floor = max(5, 50) = 50
    best = _fit(diff=0.01, n_fired=100)
    cand = _fit(diff=0.05, n_fired=10)  # huge diff but only 10 fired (< 50): REJECT
    assert _scanner_keep(cand, best, base) is False


def test_scanner_keep_abs_floor_when_baseline_tiny():
    # base n_fired = 2 → 0.5*2 = 1, but the absolute floor is 5.
    base = _fit(diff=0.01, n_fired=2)
    best = _fit(diff=0.01, n_fired=2)
    cand = _fit(diff=0.05, n_fired=4)  # 4 < 5 absolute floor: REJECT
    assert _scanner_keep(cand, best, base) is False
    cand_ok = _fit(diff=0.05, n_fired=6)  # 6 >= 5: passes the fired guardrail
    assert _scanner_keep(cand_ok, best, base) is True


def test_scanner_keep_lower_diff_rolled_back():
    base = _fit(diff=0.02, n_fired=100)
    best = _fit(diff=0.02, n_fired=100)
    cand = _fit(diff=0.01, n_fired=100)  # diff DROPS: REJECT
    assert _scanner_keep(cand, best, base) is False


def test_scanner_keep_worse_t_stat_rolled_back():
    base = _fit(diff=0.01, t_stat=3.0, n_fired=100)
    best = _fit(diff=0.01, t_stat=3.0, n_fired=100)
    cand = _fit(diff=0.02, t_stat=2.0, n_fired=100)  # diff up but t worse by 1.0 (> _T_TOL=0.5): REJECT
    assert _scanner_keep(cand, best, base) is False


def test_scanner_keep_none_diff_rolled_back():
    assert _scanner_keep({"diff": None, "n_fired": 100}, _fit(diff=0.0), _fit(diff=0.0)) is False


# ---------------------------------------------------------------------------
# 2. Wiring — evolve_scanner writes v0 + round versions
# ---------------------------------------------------------------------------


def test_evolve_scanner_writes_v0_and_round_versions(tmp_path, monkeypatch):
    base = _base_config()
    propose_fn = _scripted_propose([{"path": "detectors.gap.threshold", "value": 4.0, "hypothesis": "wider gap"}])
    table = {
        (3.0, "train"): _fit(diff=0.01),
        (3.0, "val"): _fit(diff=0.01, n_fired=100),
        (4.0, "train"): _fit(diff=0.02),
        (4.0, "val"): _fit(diff=0.02, n_fired=90),  # higher diff, fine n_fired: KEEP
    }
    monkeypatch.setattr(run_mod, "scanner_fitness", _keyed_fitness(table))

    log = evolve_scanner(
        bundles={"AAA": object()},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_fn,
    )

    by_id = {e["v_id"]: e for e in log}
    assert "v0" in by_id
    assert "v0.0.1" in by_id
    assert by_id["v0.0.1"]["kept"] is True
    v1 = read_version(tmp_path, "v0.0.1")
    assert v1["config"]["detectors"]["gap"]["threshold"] == 4.0
    assert "v0.0.1" in list_versions(tmp_path)


# ---------------------------------------------------------------------------
# 3. keep / rollback via the loop
# ---------------------------------------------------------------------------


def test_loop_keeps_higher_diff_rolls_back_lower_and_collapsed(tmp_path, monkeypatch):
    base = _base_config()
    # Round 1: threshold 4.0, higher diff + fine n_fired → KEEP.
    # Round 2: threshold 4.5, LOWER diff → ROLLBACK.
    # Round 3: threshold 2.5, higher diff but COLLAPSED n_fired → ROLLBACK.
    propose_fn = _scripted_propose(
        [
            {"path": "detectors.gap.threshold", "value": 4.0, "hypothesis": "a"},
            {"path": "detectors.gap.threshold", "value": 4.5, "hypothesis": "b"},
            {"path": "detectors.gap.threshold", "value": 2.5, "hypothesis": "c"},
        ]
    )
    table = {
        (3.0, "train"): _fit(diff=0.01),
        (3.0, "val"): _fit(diff=0.01, n_fired=100),
        (4.0, "train"): _fit(diff=0.02),
        (4.0, "val"): _fit(diff=0.02, t_stat=2.0, n_fired=90),  # KEEP
        (4.5, "train"): _fit(diff=0.005),
        (4.5, "val"): _fit(diff=0.005, n_fired=80),  # lower diff than 0.02 → ROLLBACK
        (2.5, "train"): _fit(diff=0.09),
        (2.5, "val"): _fit(diff=0.09, n_fired=5),  # collapsed (< 0.5*100=50) → ROLLBACK
    }
    monkeypatch.setattr(run_mod, "scanner_fitness", _keyed_fitness(table))

    log = evolve_scanner(
        bundles={"AAA": object()},
        base_config=base,
        iterations=3,
        base_dir=tmp_path,
        propose_fn=propose_fn,
    )
    by_id = {e["v_id"]: e for e in log}
    assert by_id["v0.0.1"]["kept"] is True
    assert by_id["v0.0.2"]["kept"] is False
    assert by_id["v0.0.3"]["kept"] is False
    # The kept round-1 candidate (threshold 4.0) stayed the running-best.
    assert read_version(tmp_path, "v0.0.1")["config"]["detectors"]["gap"]["threshold"] == 4.0


# ---------------------------------------------------------------------------
# 4. SAMPLE ISOLATION — "test" is NEVER scored inside the loop
# ---------------------------------------------------------------------------


def test_test_sample_never_scored_in_loop(tmp_path, monkeypatch):
    base = _base_config()
    propose_fn = _scripted_propose(
        [
            {"path": "detectors.gap.threshold", "value": 4.0, "hypothesis": "a"},
            {"path": "detectors.gap.threshold", "value": 4.5, "hypothesis": "b"},
            None,  # a declined round, for good measure
            {"path": "detectors.gap.threshold", "value": 2.5, "hypothesis": "c"},
        ]
    )
    table = {
        (3.0, "train"): _fit(diff=0.01),
        (3.0, "val"): _fit(diff=0.01, n_fired=100),
        (4.0, "train"): _fit(diff=0.02),
        (4.0, "val"): _fit(diff=0.02, n_fired=90),
        (4.5, "train"): _fit(diff=0.03),
        (4.5, "val"): _fit(diff=0.03, n_fired=85),
        (2.5, "train"): _fit(diff=0.04),
        (2.5, "val"): _fit(diff=0.04, n_fired=80),
    }
    seen: list[str] = []
    monkeypatch.setattr(run_mod, "scanner_fitness", _keyed_fitness(table, record=seen))

    evolve_scanner(
        bundles={"AAA": object()},
        base_config=base,
        iterations=4,
        base_dir=tmp_path,
        propose_fn=propose_fn,
    )

    # The critical assertion: test is held out across the ENTIRE loop run.
    assert "test" not in seen
    # The recorder is NOT vacuously empty — train + val WERE exercised.
    assert "train" in seen
    assert "val" in seen


# ---------------------------------------------------------------------------
# 5. Resumable — counter continues + running-best restored
# ---------------------------------------------------------------------------


def test_resume_continues_counter_and_running_best(tmp_path, monkeypatch):
    base = _base_config()

    # --- First run: one improving round (threshold -> 4.0, kept).
    propose_a = _scripted_propose([{"path": "detectors.gap.threshold", "value": 4.0, "hypothesis": "run1 keep"}])
    table = {
        (3.0, "train"): _fit(diff=0.01),
        (3.0, "val"): _fit(diff=0.01, n_fired=100),
        (4.0, "train"): _fit(diff=0.02),
        (4.0, "val"): _fit(diff=0.02, t_stat=2.0, n_fired=90),
        # second run proposes threshold -> 4.5
        (4.5, "train"): _fit(diff=0.03),
        (4.5, "val"): _fit(diff=0.03, t_stat=2.0, n_fired=85),
    }
    monkeypatch.setattr(run_mod, "scanner_fitness", _keyed_fitness(table))

    log1 = evolve_scanner(
        bundles={"AAA": object()},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_a,
    )
    assert {e["v_id"] for e in log1} == {"v0", "v0.0.1"}

    # --- Second run on the SAME base_dir: must RESUME.
    # The running-best is the kept v0.0.1 (threshold 4.0), so the proposer must SEE
    # threshold == 4.0, and the new version must be v0.0.2 (counter continued).
    seen_thresh = []
    inner = _scripted_propose([{"path": "detectors.gap.threshold", "value": 4.5, "hypothesis": "run2 keep"}])

    def spy_propose(skill, config, val_history, *, llm_fn=None):
        seen_thresh.append(config.detectors["gap"]["threshold"])
        return inner(skill, config, val_history, llm_fn=llm_fn)

    log2 = evolve_scanner(
        bundles={"AAA": object()},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=spy_propose,
    )

    assert seen_thresh == [4.0]  # resumed running-best, NOT base 3.0
    ids2 = {e["v_id"] for e in log2}
    assert "v0.0.2" in ids2
    assert sum(1 for e in log2 if e["v_id"] == "v0") <= 1  # no second baseline
    assert "v0.0.1" in list_versions(tmp_path)
    by_id = {e["v_id"]: e for e in log2}
    assert by_id["v0.0.2"]["kept"] is True


# ---------------------------------------------------------------------------
# 6. Factor engine untouched — a no-seam evolve still works
# ---------------------------------------------------------------------------


def test_factor_evolve_with_no_seams_still_works(tmp_path):
    from v2.self_evolve.config import StrategyConfig
    from v2.self_evolve.loop import evolve

    base = StrategyConfig(
        factor_weights={
            "momentum": 0.30,
            "low_vol": 0.25,
            "reversal": 0.15,
            "value": 0.15,
            "quality": 0.15,
            "max_lottery": 0.0,
            "high_52w": 0.0,
            "turnover": 0.0,
            "resid_mom": 0.0,
            "gross_prof": 0.0,
            "asset_growth": 0.0,
        },
        lookback={
            "momentum_days": 120,
            "vol_days": 20,
            "reversal_days": 5,
            "max_days": 21,
            "hi_days": 252,
            "to_days": 21,
            "resid_days": 252,
        },
        top_n=30,
        holding_buffer=5,
        max_weight=0.05,
        liquidity_pct={"mktcap_pct": 0.2, "advol_pct": 0.2},
        tilt_strength=0.5,
    )

    def factor_metrics(sharpe, turnover=0.10, max_drawdown=-10.0):
        return {"sharpe": sharpe, "turnover": turnover, "max_drawdown": max_drawdown, "n_rebalances": 24}

    table = {
        (30, "train"): factor_metrics(0.9),
        (30, "val"): factor_metrics(1.0),
        (40, "train"): factor_metrics(1.4),
        (40, "val"): factor_metrics(1.5, turnover=0.11, max_drawdown=-9.0),
    }

    def backtest_fn(bundles, config, sample):
        return table.get((config.top_n, sample), factor_metrics(0.0))

    propose_fn = _scripted_propose([{"path": "top_n", "value": 40, "hypothesis": "more breadth"}])

    log = evolve(
        bundles={},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=backtest_fn,
    )
    by_id = {e["v_id"]: e for e in log}
    assert by_id["v0"]["kept"] is True
    assert by_id["v0.0.1"]["kept"] is True
    assert by_id["v0.0.1"]["val_sharpe"] == 1.5
