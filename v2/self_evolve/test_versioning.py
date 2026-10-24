"""Offline tests for the version store, optimization-path log, and the LLM
config-delta proposer seam (Task 6).

Everything here is OFFLINE: the proposer's ``llm_fn`` is always STUBBED — the
real DeepSeek binding is never exercised. The version store is plain JSON on a
tmp dir.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from v2.self_evolve.config import ADJUSTABLE, StrategyConfig, load_config
from v2.self_evolve.proposer import propose
from v2.self_evolve.versioning import (
    append_path_log,
    list_versions,
    read_path_log,
    read_version,
    write_version,
)

BASELINE = Path(__file__).resolve().parents[2] / "strategy_skill" / "skill_config.yaml"


def _cfg() -> StrategyConfig:
    return load_config(BASELINE)


# ---------------------------------------------------------------------------
# 1. versioning: write/read round-trip, path log append/read, list, missing dir
# ---------------------------------------------------------------------------


def test_write_then_read_round_trips_record(tmp_path):
    record = {
        "config": dataclasses.asdict(_cfg()),
        "train_metrics": {"sharpe": 1.2},
        "val_metrics": {"sharpe": 0.9},
        "hypothesis": "trend regime favors momentum",
        "kept": True,
        "attribution": {"momentum": 0.6},
    }
    path = write_version(tmp_path, "v001", record)
    assert Path(path).is_file()
    assert Path(path) == Path(tmp_path) / "versions" / "v001" / "version.json"

    got = read_version(tmp_path, "v001")
    assert got == record


def test_append_path_log_three_then_read_in_order(tmp_path):
    entries = [
        {"v_id": "v001", "hypothesis": "a", "val_sharpe": 0.5, "kept": False},
        {"v_id": "v002", "hypothesis": "b", "val_sharpe": 0.8, "kept": True},
        {"v_id": "v003", "hypothesis": "c", "val_sharpe": 0.7, "kept": False},
    ]
    for e in entries:
        append_path_log(tmp_path, e)

    got = read_path_log(tmp_path)
    assert got == entries

    # The on-disk file is one JSON object per line (jsonl).
    raw = (Path(tmp_path) / "versions" / "path_log.jsonl").read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == 3
    assert json.loads(lines[0])["v_id"] == "v001"


def test_list_versions_lists_written_ids_sorted(tmp_path):
    write_version(tmp_path, "v003", {"kept": False})
    write_version(tmp_path, "v001", {"kept": True})
    write_version(tmp_path, "v002", {"kept": False})
    assert list_versions(tmp_path) == ["v001", "v002", "v003"]


def test_reads_on_missing_base_dir_do_not_crash(tmp_path):
    missing = tmp_path / "nope"
    assert list_versions(missing) == []
    assert read_path_log(missing) == []
    assert read_version(missing, "v999") == {}


# ---------------------------------------------------------------------------
# 2. proposer happy path
# ---------------------------------------------------------------------------


def test_propose_happy_returns_validated_delta():
    cfg = _cfg()
    stub = lambda _prompt: '{"path":"factor_weights.momentum","value":0.4,"hypothesis":"trend regime"}'
    out = propose("KERNEL", cfg, [], llm_fn=stub)
    assert out == {
        "path": "factor_weights.momentum",
        "value": 0.4,
        "hypothesis": "trend regime",
    }
    # The returned path is an ADJUSTABLE one.
    assert out["path"] in ADJUSTABLE


def test_propose_passes_a_prompt_string_to_llm_fn():
    cfg = _cfg()
    seen = {}

    def stub(prompt):
        seen["prompt"] = prompt
        return '{"path":"top_n","value":40,"hypothesis":"more breadth"}'

    out = propose("MY-KERNEL-DISCIPLINE", cfg, [{"v_id": "v001", "val_sharpe": 0.5, "delta": {}, "kept": True}], llm_fn=stub)
    assert out["path"] == "top_n" and out["value"] == 40
    # The prompt carries the kernel and at least one ADJUSTABLE path name.
    assert "MY-KERNEL-DISCIPLINE" in seen["prompt"]
    assert "factor_weights.momentum" in seen["prompt"]


# ---------------------------------------------------------------------------
# 3. proposer rejects bad proposals → None, never raises
# ---------------------------------------------------------------------------


def test_propose_rejects_out_of_range_value():
    cfg = _cfg()
    stub = lambda _p: '{"path":"top_n","value":5,"hypothesis":"too few"}'  # below [20, 50]
    assert propose("K", cfg, [], llm_fn=stub) is None


def test_propose_rejects_unknown_path():
    cfg = _cfg()
    stub = lambda _p: '{"path":"foo.bar","value":1,"hypothesis":"nope"}'
    assert propose("K", cfg, [], llm_fn=stub) is None


def test_propose_rejects_non_json_garbage():
    cfg = _cfg()
    stub = lambda _p: "I think you should raise momentum a bit, no JSON here."
    assert propose("K", cfg, [], llm_fn=stub) is None


def test_propose_returns_none_when_llm_fn_raises():
    cfg = _cfg()

    def boom(_p):
        raise RuntimeError("network down")

    # Must NOT propagate — returns None.
    assert propose("K", cfg, [], llm_fn=boom) is None


def test_propose_rejects_non_numeric_value():
    cfg = _cfg()
    stub = lambda _p: '{"path":"top_n","value":"lots","hypothesis":"strings not allowed"}'
    assert propose("K", cfg, [], llm_fn=stub) is None


# ---------------------------------------------------------------------------
# 4. proposer tolerates code fences / surrounding prose
# ---------------------------------------------------------------------------


def test_propose_parses_json_in_code_fences():
    cfg = _cfg()
    fenced = "Sure, here is my proposal:\n" "```json\n" '{"path": "lookback.momentum_days", "value": 200, "hypothesis": "longer trend"}\n' "```\n" "Hope that helps!"
    out = propose("K", cfg, [], llm_fn=lambda _p: fenced)
    assert out == {
        "path": "lookback.momentum_days",
        "value": 200,
        "hypothesis": "longer trend",
    }


def test_propose_parses_first_json_object_amid_prose():
    cfg = _cfg()
    # cost_bps is an adjustable top-level scalar (range [0, 50]); used here purely
    # to exercise JSON-extraction-amid-prose. (tilt_strength was dropped from
    # ADJUSTABLE in final review H1, so it would now be rejected as inert.)
    prose = 'My reasoning is long. Proposal: {"path":"cost_bps","value":15.0,"hypothesis":"more realistic costs"} -- done.'
    out = propose("K", cfg, [], llm_fn=lambda _p: prose)
    assert out["path"] == "cost_bps"
    assert out["value"] == 15.0
