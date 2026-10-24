"""DeepSeek -> SiliconFlow routing in get_model (offline: only constructs clients)."""

from langchain_deepseek import ChatDeepSeek
from langchain_openai import ChatOpenAI

from src.llm.models import ModelProvider, get_model


def test_deepseek_routes_through_siliconflow_when_key_set(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test")
    m = get_model("deepseek-v4-pro", ModelProvider.DEEPSEEK, allow_env_fallback=True)
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == "deepseek-ai/DeepSeek-V4-Pro"  # mapped id
    assert "siliconflow.cn" in str(m.openai_api_base)


def test_unmapped_deepseek_name_falls_back_to_prefix(monkeypatch):
    monkeypatch.setenv("SILICONFLOW_API_KEY", "sk-test")
    m = get_model("deepseek-something", ModelProvider.DEEPSEEK)
    assert isinstance(m, ChatOpenAI)
    assert m.model_name == "deepseek-ai/deepseek-something"


def test_falls_back_to_direct_deepseek_without_siliconflow_key(monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-direct")
    m = get_model("deepseek-v4-pro", ModelProvider.DEEPSEEK)
    assert isinstance(m, ChatDeepSeek)
    assert m.model_name == "deepseek-v4-pro"  # unchanged on the direct path
