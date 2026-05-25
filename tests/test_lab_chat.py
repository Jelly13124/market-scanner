"""Phase 6E: LLM chat wrapper — prompt building + ProposeSpecPatch/ChatReply union."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from src.lab.chat import (
    ChatReply,
    ChatResponse,
    ProposeSpecPatch,
    build_chat_prompt,
    run_chat_turn,
)


def _spec():
    return {
        "name": "X", "description": "",
        "universe": {"kind": "sp500"},
        "entry": {"combiner": "and", "signals": [
            {"type": "ma_cross", "fast": 50, "slow": 200, "direction": "golden"}
        ]},
        "exit": [{"type": "stop_loss", "mode": "pct", "value": 0.05}],
        "filters": [], "sizing": {"type": "fixed_pct", "pct": 0.05},
        "backtest_config": {},
    }


def _msg(role, content, created_at=None):
    return SimpleNamespace(
        id=1, role=role, content=content,
        created_at=created_at or datetime(2026, 5, 25),
        spec_snapshot_json=None, spec_patch_json=None, patch_accepted=None,
    )


def test_build_chat_prompt_includes_catalog_and_history():
    history = [_msg("user", "first message"), _msg("assistant", "first reply")]
    prior_strategies = [{"name": "MA Cross", "verdict": "weak"}]
    prompt = build_chat_prompt(
        current_spec=_spec(),
        chat_history=history,
        prior_strategies_summary=prior_strategies,
        user_message="now make it better",
    )
    assert "AVAILABLE STRATEGY BLOCKS" in prompt
    assert "MA Cross" in prompt
    assert "first message" in prompt
    assert "now make it better" in prompt


@patch("src.lab.chat.call_research_llm")
def test_run_chat_turn_returns_reply(mock_llm):
    mock_llm.return_value = ChatResponse(
        root=ChatReply(message="Sure, that's a good idea.")
    )
    result = run_chat_turn(
        current_spec=_spec(),
        chat_history=[],
        prior_strategies_summary=[],
        user_message="hello",
    )
    assert isinstance(result.root, ChatReply)
    assert "good idea" in result.root.message


@patch("src.lab.chat.call_research_llm")
def test_run_chat_turn_returns_patch(mock_llm):
    new_spec = _spec()
    new_spec["entry"]["signals"][0]["fast"] = 20
    mock_llm.return_value = ChatResponse(
        root=ProposeSpecPatch(
            rationale="Shortened the fast MA per your request",
            patch=new_spec,
        )
    )
    result = run_chat_turn(
        current_spec=_spec(),
        chat_history=[],
        prior_strategies_summary=[],
        user_message="make fast MA 20",
    )
    assert isinstance(result.root, ProposeSpecPatch)
    assert result.root.patch["entry"]["signals"][0]["fast"] == 20
