"""Small LLM-call helper for the research pipeline.

Why a separate helper instead of reusing src/utils/llm.py:call_llm?
The legacy helper extracts model config from AgentState (the LangGraph
state used by src/agents/). The research pipeline has its own state
shape and doesn't need that coupling. This helper takes raw prompts +
pydantic models and uses the DeepSeek default that matches the
production cron's cost target (~$0.0005/call).

Override via env vars RESEARCH_MODEL_NAME / RESEARCH_MODEL_PROVIDER for
local experimentation.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, TypeVar

from pydantic import BaseModel
from src.llm.models import get_model

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_PROVIDER = "DeepSeek"


def _schema_hint(pydantic_model: type[BaseModel]) -> str:
    """Produce a one-liner-per-field schema hint for the LLM."""
    schema = pydantic_model.model_json_schema()
    props = schema.get("properties", {})
    if not props:
        return "Respond as a JSON object."
    lines = ["Respond as a JSON object with these exact fields:"]
    for name, info in props.items():
        desc = info.get("description", "")
        type_hint = info.get("type", "string")
        if desc:
            lines.append(f'  "{name}" ({type_hint}): {desc}')
        else:
            lines.append(f'  "{name}" ({type_hint})')
    return "\n".join(lines)


def call_research_llm(
    prompt,
    pydantic_model: type[_T],
    *,
    max_retries: int = 3,
    default_factory: Callable[[], _T] | None = None,
) -> _T:
    """Call the LLM with structured output. Retry on parse/transient
    errors up to ``max_retries``. If all retries fail and
    ``default_factory`` is provided, return its result; otherwise
    re-raise the last exception.

    ``prompt`` can be anything the LangChain ``invoke`` accepts — a
    string, a ChatPromptTemplate, a message list. Callers usually
    pre-format into a string for simplicity.
    """
    model_name = os.environ.get("RESEARCH_MODEL_NAME", _DEFAULT_MODEL)
    model_provider = os.environ.get("RESEARCH_MODEL_PROVIDER", _DEFAULT_PROVIDER)

    llm = get_model(model_name, model_provider)
    structured = llm.with_structured_output(pydantic_model, method="json_mode")

    # DeepSeek (and other json_mode providers) require:
    #   (a) the prompt to contain the literal word "json"
    #   (b) field-name hints, because json_mode does NOT share the
    #       pydantic schema with the model — without hints DeepSeek
    #       invents field names like {"summary": ...} when we expected
    #       {"narrative": ...}.
    # We append a concrete schema hint listing the expected fields and
    # their descriptions. Structured prompts (ChatPromptTemplate /
    # message lists) are left alone — advanced callers handle this
    # themselves.
    if isinstance(prompt, str):
        hint = _schema_hint(pydantic_model)
        prompt = prompt + "\n\n" + hint

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return structured.invoke(prompt)
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "call_research_llm attempt %d/%d failed: %s",
                attempt + 1, max_retries, exc,
            )
            if attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))

    if default_factory is not None:
        logger.warning("call_research_llm exhausted retries; using default_factory")
        return default_factory()
    assert last_exc is not None
    raise last_exc
