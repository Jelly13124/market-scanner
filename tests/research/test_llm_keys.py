"""Per-user-keys wave A1.

Two security-sensitive guarantees:

1. ``call_research_llm`` forwards a caller-supplied ``api_keys`` dict to
   ``get_model`` and, when a dict IS supplied (the deployed user path),
   disables env fallback so a partial user dict can never silently reach
   the host's env key.

2. ``get_model`` honours ``allow_env_fallback``: with it OFF and no key
   in the dict it raises loudly instead of constructing a client that
   would otherwise pick up the host key — and with it ON the legacy
   host/cron behaviour (read from ``os.getenv``) is preserved.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel

from src.research.llm import call_research_llm
from src.llm.models import get_model


class _DummyOut(BaseModel):
    text: str


def _fake_llm() -> MagicMock:
    """Minimal stand-in matching the real invocation chain used by
    call_research_llm: ``llm.with_structured_output(...).invoke(...)``."""
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = _DummyOut(text="ok")
    return llm


# --- call_research_llm forwarding -----------------------------------------

def test_call_research_llm_forwards_user_keys(monkeypatch):
    captured = {}

    def fake_get_model(name, provider, api_keys=None, allow_env_fallback=True):
        captured["api_keys"] = api_keys
        captured["fallback"] = allow_env_fallback
        return _fake_llm()

    monkeypatch.setattr("src.research.llm.get_model", fake_get_model)

    out = call_research_llm(
        "prompt text",
        _DummyOut,
        api_keys={"DEEPSEEK_API_KEY": "u-key"},
    )

    assert isinstance(out, _DummyOut)
    assert captured["api_keys"] == {"DEEPSEEK_API_KEY": "u-key"}
    # user path => env fallback MUST be off (no host-key leak)
    assert captured["fallback"] is False


def test_call_research_llm_none_keys_allows_fallback(monkeypatch):
    captured = {}

    def fake_get_model(name, provider, api_keys=None, allow_env_fallback=True):
        captured["api_keys"] = api_keys
        captured["fallback"] = allow_env_fallback
        return _fake_llm()

    monkeypatch.setattr("src.research.llm.get_model", fake_get_model)

    # No api_keys => host/cron path => fallback stays ON.
    call_research_llm("prompt text", _DummyOut)

    assert captured["api_keys"] is None
    assert captured["fallback"] is True


# --- get_model env-fallback control ---------------------------------------

def test_get_model_no_fallback_no_key_raises(monkeypatch):
    # Host key present in env, but a user path (empty dict + fallback off)
    # must NOT reach it -> raise loudly.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "HOST")
    with pytest.raises(ValueError):
        get_model("deepseek-chat", "DeepSeek", api_keys={}, allow_env_fallback=False)


def test_get_model_fallback_on_uses_env(monkeypatch):
    # Host/cron path: api_keys=None, fallback on -> reads env, builds client.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "HOST")
    m = get_model("deepseek-chat", "DeepSeek", api_keys=None, allow_env_fallback=True)
    assert m is not None


def test_get_model_user_key_used_without_fallback(monkeypatch):
    # User supplies their own key + fallback off -> builds a client from the
    # user's key (does not need env at all).
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    m = get_model(
        "deepseek-chat",
        "DeepSeek",
        api_keys={"DEEPSEEK_API_KEY": "u-key"},
        allow_env_fallback=False,
    )
    assert m is not None
