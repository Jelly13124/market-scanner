"""call_research_llm should call the underlying LLM with structured
output, retry up to 3x on parse failures, and return the pydantic
model. Default factory fires on terminal failure."""

from __future__ import annotations

from unittest.mock import patch, MagicMock
from pydantic import BaseModel

from src.research.llm import call_research_llm


class _DummyOut(BaseModel):
    text: str


class TestCallResearchLLM:
    @patch("src.research.llm.get_model")
    def test_happy_path_returns_pydantic(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.return_value = _DummyOut(text="hi")
        mock_get_model.return_value = mock_model

        out = call_research_llm("prompt text", _DummyOut)
        assert isinstance(out, _DummyOut)
        assert out.text == "hi"

    @patch("src.research.llm.get_model")
    def test_default_factory_on_terminal_failure(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.side_effect = ValueError("boom")
        mock_get_model.return_value = mock_model

        out = call_research_llm(
            "prompt", _DummyOut,
            default_factory=lambda: _DummyOut(text="fallback"),
        )
        assert out.text == "fallback"

    @patch("src.research.llm.get_model")
    def test_no_default_factory_raises(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.with_structured_output.return_value.invoke.side_effect = ValueError("boom")
        mock_get_model.return_value = mock_model

        with __import__("pytest").raises(ValueError):
            call_research_llm("prompt", _DummyOut)
