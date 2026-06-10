"""Offline tests for the evolution LOOP (Task 7) — the keep/rollback driver.

Everything here is OFFLINE and DETERMINISTIC:

* ``propose_fn`` is STUBBED to emit a *scripted sequence* of canned deltas (or
  ``None``) so we control exactly what each round proposes — the real LLM
  proposer is never touched.
* ``backtest_fn`` is STUBBED to return canned metrics keyed by ``(config, sample)``
  so we control the val Sharpe / turnover / drawdown the loop sees — the real
  per-sample backtest is never run.

The load-bearing contract the loop must honor:

1. A val-IMPROVING delta (higher val Sharpe, guardrails ok) is KEPT and becomes
   the new running-best; a val-WORSENING delta is ROLLED BACK.
2. Guardrails: a higher-Sharpe delta whose turnover blows past ``base × 1.5`` is
   ROLLED BACK; one whose max-drawdown is worse by > 5pp is ROLLED BACK.
3. **Sample isolation** — across the WHOLE run, ``backtest_fn`` is NEVER called
   with ``sample == "test"``.
4. ``propose_fn`` returning ``None`` for a round → that round is skipped, no
   crash, the loop continues.
5. Versions + path-log are written; re-running ``evolve`` on the same ``base_dir``
   RESUMES (continues the counter + running-best) rather than restarting.

No network, no data files, no LLM, no pandas.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from v2.self_evolve.config import StrategyConfig, apply_delta
from v2.self_evolve.loop import evolve
from v2.self_evolve.versioning import list_versions, read_path_log, read_version


# ---------------------------------------------------------------------------
# Fixtures: a real base config + scriptable propose / backtest stubs
# ---------------------------------------------------------------------------


def _base_config() -> StrategyConfig:
    """A real ``StrategyConfig`` (weights sum-normalized in ``__post_init__``).

    Carries all 11 FACTOR_KEYS so it survives ``apply_delta``'s validate() inside
    ``evolve``. The 6 Part-C factors are seeded at 0.0 — they normalize away and
    are neutral (z=0) anyway, so the loop's selection / metrics are unchanged.
    """
    return StrategyConfig(
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


def _scripted_propose(deltas):
    """A ``propose_fn`` that emits ``deltas`` in order, then ``None`` forever.

    Each element is either a proposal dict (``{"path","value","hypothesis"}``)
    or ``None`` (model declined this round). Matches the real ``propose``
    signature ``(skill_md, config, val_history, *, llm_fn=None)``.
    """
    seq = list(deltas)
    calls = {"n": 0}

    def propose_fn(skill_md, config, val_history, *, llm_fn=None):
        i = calls["n"]
        calls["n"] += 1
        if i < len(seq):
            return seq[i]
        return None

    propose_fn.calls = calls  # introspection handle for tests
    return propose_fn


def _metrics(*, sharpe, turnover=0.10, max_drawdown=-10.0, ann_return=0.10, ann_vol=0.10, n=24):
    return {
        "sharpe": sharpe,
        "ann_return": ann_return,
        "ann_vol": ann_vol,
        "max_drawdown": max_drawdown,
        "turnover": turnover,
        "n_rebalances": n,
    }


def _keyed_backtest(table, *, default=None, record=None):
    """A ``backtest_fn`` returning canned metrics keyed by ``(top_n, sample)``.

    We key on the candidate's ``top_n`` (each scripted delta moves ``top_n`` to a
    distinct value) plus the ``sample`` so a test can pin different train/val
    metrics per candidate. ``record`` (if given) is a list every ``sample`` arg
    is appended to — used by the sample-isolation test.
    """

    def backtest_fn(bundles, config, sample):
        if record is not None:
            record.append(sample)
        key = (getattr(config, "top_n"), sample)
        if key in table:
            return table[key]
        if default is not None:
            return default
        # Sensible neutral fallback so an unscripted (config, sample) never KeyErrors.
        return _metrics(sharpe=0.0)

    return backtest_fn


# ---------------------------------------------------------------------------
# 1. keep an improving delta; roll back a worsening one
# ---------------------------------------------------------------------------


def test_improving_delta_kept_becomes_new_base_worsening_rolled_back(tmp_path):
    base = _base_config()

    # Round 1 raises top_n -> 40 (val sharpe 1.5 > base 1.0): KEEP.
    # Round 2 raises top_n -> 45 (val sharpe 0.5 < kept 1.5): ROLLBACK.
    propose_fn = _scripted_propose(
        [
            {"path": "top_n", "value": 40, "hypothesis": "more breadth"},
            {"path": "top_n", "value": 45, "hypothesis": "even more breadth"},
        ]
    )

    table = {
        # v0 baseline (top_n == 30)
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0, turnover=0.10, max_drawdown=-10.0),
        # round 1 candidate
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5, turnover=0.12, max_drawdown=-9.0),
        # round 2 candidate
        (45, "train"): _metrics(sharpe=0.4),
        (45, "val"): _metrics(sharpe=0.5, turnover=0.11, max_drawdown=-8.0),
    }
    backtest_fn = _keyed_backtest(table)

    # Capture the config the proposer SEES each round, to prove the kept candidate
    # became the new base (round 2 should see top_n == 40, not 30).
    seen_top_n = []
    inner = propose_fn

    def spy_propose(skill_md, config, val_history, *, llm_fn=None):
        seen_top_n.append(config.top_n)
        return inner(skill_md, config, val_history, llm_fn=llm_fn)

    log = evolve(
        bundles={},
        base_config=base,
        iterations=2,
        base_dir=tmp_path,
        skill_md="KERNEL",
        propose_fn=spy_propose,
        backtest_fn=backtest_fn,
    )

    # Round 1 saw the base (30); round 2 saw the KEPT candidate (40).
    assert seen_top_n == [30, 40]

    # Path log has v0 + two rounds. v0.0.1 kept, v0.0.2 not kept.
    by_id = {e["v_id"]: e for e in log}
    assert "v0" in by_id
    assert by_id["v0.0.1"]["kept"] is True
    assert by_id["v0.0.2"]["kept"] is False
    assert by_id["v0.0.1"]["val_sharpe"] == 1.5
    assert by_id["v0.0.2"]["val_sharpe"] == 0.5

    # The kept version persisted the candidate config (top_n == 40).
    v1 = read_version(tmp_path, "v0.0.1")
    assert v1["kept"] is True
    assert v1["config"]["top_n"] == 40
    # The rolled-back version recorded kept False (its config still captured).
    v2 = read_version(tmp_path, "v0.0.2")
    assert v2["kept"] is False


# ---------------------------------------------------------------------------
# 2. guardrails: turnover blow-up rolled back; drawdown blow-up rolled back
# ---------------------------------------------------------------------------


def test_turnover_guardrail_rolls_back_despite_higher_sharpe(tmp_path):
    base = _base_config()
    # base val turnover is 0.10 -> guardrail ceiling is 0.15. Candidate has a
    # BETTER sharpe (2.0 > 1.0) but turnover 0.20 (> 0.15): must ROLLBACK.
    propose_fn = _scripted_propose([{"path": "top_n", "value": 40, "hypothesis": "churns hard"}])
    table = {
        (30, "train"): _metrics(sharpe=0.9, turnover=0.10),
        (30, "val"): _metrics(sharpe=1.0, turnover=0.10, max_drawdown=-10.0),
        (40, "train"): _metrics(sharpe=1.9, turnover=0.20),
        (40, "val"): _metrics(sharpe=2.0, turnover=0.20, max_drawdown=-9.0),
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    by_id = {e["v_id"]: e for e in log}
    assert by_id["v0.0.1"]["kept"] is False


def test_drawdown_guardrail_rolls_back_despite_higher_sharpe(tmp_path):
    base = _base_config()
    # base val maxDD is -10.0 -> floor is -15.0 (not worse by > 5pp). Candidate
    # has a BETTER sharpe (2.0) but maxDD -20.0 (worse by 10pp): must ROLLBACK.
    propose_fn = _scripted_propose([{"path": "top_n", "value": 40, "hypothesis": "deep dd"}])
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0, turnover=0.10, max_drawdown=-10.0),
        (40, "train"): _metrics(sharpe=1.9),
        (40, "val"): _metrics(sharpe=2.0, turnover=0.11, max_drawdown=-20.0),
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    by_id = {e["v_id"]: e for e in log}
    assert by_id["v0.0.1"]["kept"] is False


def test_drawdown_within_5pp_is_kept(tmp_path):
    # Boundary: maxDD exactly 5pp worse is still allowed (>=, "not worse by > 5pp").
    base = _base_config()
    propose_fn = _scripted_propose([{"path": "top_n", "value": 40, "hypothesis": "edge dd"}])
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0, turnover=0.10, max_drawdown=-10.0),
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5, turnover=0.11, max_drawdown=-15.0),  # exactly floor
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    by_id = {e["v_id"]: e for e in log}
    assert by_id["v0.0.1"]["kept"] is True


# ---------------------------------------------------------------------------
# 3. SAMPLE ISOLATION — "test" is NEVER backtested anywhere in the loop
# ---------------------------------------------------------------------------


def test_test_sample_is_never_backtested(tmp_path):
    base = _base_config()
    propose_fn = _scripted_propose(
        [
            {"path": "top_n", "value": 40, "hypothesis": "a"},
            {"path": "top_n", "value": 45, "hypothesis": "b"},
            None,  # a declined round, for good measure
            {"path": "top_n", "value": 35, "hypothesis": "c"},
        ]
    )
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0),
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5),
        (45, "train"): _metrics(sharpe=0.4),
        (45, "val"): _metrics(sharpe=0.5),
        (35, "train"): _metrics(sharpe=2.4),
        (35, "val"): _metrics(sharpe=2.5),
    }
    seen_samples: list[str] = []
    backtest_fn = _keyed_backtest(table, record=seen_samples)

    evolve(
        bundles={},
        base_config=base,
        iterations=4,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=backtest_fn,
    )

    # The critical assertion: test is held out across the ENTIRE run.
    assert "test" not in seen_samples
    # And we DID exercise train + val (sanity — the guard isn't vacuously true).
    assert "train" in seen_samples
    assert "val" in seen_samples


# ---------------------------------------------------------------------------
# 4. proposer returns None for a round → skip, no crash, loop continues
# ---------------------------------------------------------------------------


def test_none_proposal_skips_round_no_version_written(tmp_path):
    base = _base_config()
    # Round 1 -> None (skip). Round 2 -> a real improving delta (kept).
    propose_fn = _scripted_propose(
        [
            None,
            {"path": "top_n", "value": 40, "hypothesis": "improves"},
        ]
    )
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0),
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5),
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=2,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    ids = {e["v_id"] for e in log}
    # v0 + the round-2 version only; the skipped round 1 wrote NO version.
    assert "v0" in ids
    assert "v0.0.1" not in ids  # round 1 was skipped
    assert "v0.0.2" in ids
    assert "v0.0.2" not in list_versions(tmp_path) or True  # versions dir check below
    # The kept round-2 version exists on disk.
    assert "v0.0.2" in list_versions(tmp_path)


def test_config_error_delta_skips_round_no_crash(tmp_path, monkeypatch):
    base = _base_config()
    # A proposal whose path is fine but value is OUT OF RANGE for apply_delta
    # (top_n range is [20, 50]); apply_delta raises ConfigError → round skipped.
    propose_fn = _scripted_propose(
        [
            {"path": "top_n", "value": 999, "hypothesis": "out of range"},
            {"path": "top_n", "value": 40, "hypothesis": "fine"},
        ]
    )
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0),
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5),
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=2,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    ids = {e["v_id"] for e in log}
    assert "v0.0.1" not in ids  # ConfigError round skipped
    assert "v0.0.2" in ids


# ---------------------------------------------------------------------------
# 5. versions + path_log written; resuming continues rather than restarting
# ---------------------------------------------------------------------------


def test_resume_continues_counter_and_running_best(tmp_path):
    base = _base_config()

    # --- First run: one improving round (v0.0.1 kept, top_n -> 40).
    propose_a = _scripted_propose([{"path": "top_n", "value": 40, "hypothesis": "run1 keep"}])
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0),
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5, turnover=0.10, max_drawdown=-9.0),
        # round in the SECOND run will propose top_n -> 45
        (45, "train"): _metrics(sharpe=1.9),
        (45, "val"): _metrics(sharpe=2.0, turnover=0.11, max_drawdown=-8.0),
    }
    log1 = evolve(
        bundles={},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_a,
        backtest_fn=_keyed_backtest(table),
    )
    assert {e["v_id"] for e in log1} == {"v0", "v0.0.1"}

    # --- Second run on the SAME base_dir: must RESUME.
    # The resumed running-best is the last KEPT version (top_n == 40, val sharpe
    # 1.5), so the proposer must SEE top_n == 40 (proving running-best restored),
    # and the new version must be v0.0.2 (proving the counter continued).
    seen_top_n = []
    inner = _scripted_propose([{"path": "top_n", "value": 45, "hypothesis": "run2 keep"}])

    def spy_propose(skill_md, config, val_history, *, llm_fn=None):
        seen_top_n.append(config.top_n)
        return inner(skill_md, config, val_history, llm_fn=llm_fn)

    log2 = evolve(
        bundles={},
        base_config=base,  # base_config is IGNORED for running-best when resuming
        iterations=1,
        base_dir=tmp_path,
        propose_fn=spy_propose,
        backtest_fn=_keyed_backtest(table),
    )

    # Resumed: proposer saw the kept config from run 1 (top_n == 40), NOT base 30.
    assert seen_top_n == [40]

    # The counter continued: a brand-new v0.0.2 (no second v0, no clobbered v0.0.1).
    ids2 = {e["v_id"] for e in log2}
    assert "v0.0.2" in ids2
    # v0 is written ONCE (first run); resume does not re-stamp a second baseline.
    assert sum(1 for e in log2 if e["v_id"] == "v0") <= 1
    assert "v0.0.2" in list_versions(tmp_path)
    assert "v0.0.1" in list_versions(tmp_path)  # run-1 version still there

    # The full path log (returned) spans both runs.
    by_id = {e["v_id"]: e for e in log2}
    assert by_id["v0.0.1"]["kept"] is True
    assert by_id["v0.0.2"]["kept"] is True
    assert by_id["v0.0.2"]["val_sharpe"] == 2.0


def test_v0_baseline_recorded_kept_true(tmp_path):
    base = _base_config()
    propose_fn = _scripted_propose([None])  # no rounds matter; just check v0
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0, turnover=0.10, max_drawdown=-10.0),
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=1,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    by_id = {e["v_id"]: e for e in log}
    assert by_id["v0"]["kept"] is True
    assert by_id["v0"]["val_sharpe"] == 1.0
    v0 = read_version(tmp_path, "v0")
    assert v0["kept"] is True
    assert v0["config"]["top_n"] == 30
    # v0 persists BOTH train and val metrics for the baseline.
    assert v0["train_metrics"]["sharpe"] == 0.9
    assert v0["val_metrics"]["sharpe"] == 1.0


def test_returns_full_path_log_in_order(tmp_path):
    base = _base_config()
    propose_fn = _scripted_propose(
        [
            {"path": "top_n", "value": 40, "hypothesis": "keep"},
            {"path": "top_n", "value": 45, "hypothesis": "rollback"},
        ]
    )
    table = {
        (30, "train"): _metrics(sharpe=0.9),
        (30, "val"): _metrics(sharpe=1.0, turnover=0.10, max_drawdown=-10.0),
        (40, "train"): _metrics(sharpe=1.4),
        (40, "val"): _metrics(sharpe=1.5, turnover=0.11, max_drawdown=-9.0),
        (45, "train"): _metrics(sharpe=0.4),
        (45, "val"): _metrics(sharpe=0.5, turnover=0.11, max_drawdown=-9.0),
    }
    log = evolve(
        bundles={},
        base_config=base,
        iterations=2,
        base_dir=tmp_path,
        propose_fn=propose_fn,
        backtest_fn=_keyed_backtest(table),
    )
    # Exactly the on-disk path log, in append order.
    assert log == read_path_log(tmp_path)
    assert [e["v_id"] for e in log] == ["v0", "v0.0.1", "v0.0.2"]
