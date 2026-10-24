"""Phase 6E: LLM chat wrapper for the Lab.

build_chat_prompt assembles:
  [1] Catalog of 18 blocks (~600 tokens)
  [2] Prior strategies summary (~200 tokens)
  [3] Current spec (compact JSON)
  [4] Last N chat messages
  [5] Task instructions + new user message

run_chat_turn calls call_research_llm with the ChatResponse discriminated
union -> either ProposeSpecPatch (LLM wants to change spec) or ChatReply
(LLM just answers conversationally).
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, RootModel

from src.lab.catalog import get_llm_prompt_text
from src.research.llm import call_research_llm


class ProposeSpecPatch(BaseModel):
    kind: Literal["patch"] = "patch"
    rationale: str = Field(min_length=1, max_length=2000)
    patch: dict  # full new StrategySpec dict (v1 = full replace)


class ChatReply(BaseModel):
    kind: Literal["reply"] = "reply"
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(RootModel):
    root: Annotated[Union[ProposeSpecPatch, ChatReply], Field(discriminator="kind")]


_MAX_HISTORY = 20


def build_chat_prompt(
    *,
    current_spec: dict,
    chat_history: list,
    prior_strategies_summary: list[dict],
    user_message: str,
) -> str:
    """Assemble the LLM prompt for one chat turn.

    chat_history items: objects with .role and .content attributes (ORM rows
    or compatible). prior_strategies_summary items: {name, verdict?, cagr?}.
    """
    catalog = get_llm_prompt_text()

    prior_lines = []
    for s in prior_strategies_summary[:5]:
        line = f"  - {s.get('name', '?')}"
        if "verdict" in s and s["verdict"]:
            line += f" - verdict: {s['verdict']}"
        if "cagr" in s and s["cagr"] is not None:
            line += f" (OOS CAGR {s['cagr']*100:+.1f}%)"
        prior_lines.append(line)
    prior_block = "\n".join(prior_lines) if prior_lines else "  (none yet)"

    history_lines = []
    for m in chat_history[-_MAX_HISTORY:]:
        role = getattr(m, "role", "user")
        content = getattr(m, "content", "")
        history_lines.append(f"{role}: {content}")
    history_block = "\n".join(history_lines) if history_lines else "(no prior turns)"

    spec_json = json.dumps(current_spec, indent=2, ensure_ascii=False)

    return f"""You are an expert quantitative strategist assisting the user via chat.
Your job is to help the user iteratively refine a long-only multi-ticker
portfolio strategy using ONLY the catalog blocks listed below.

You MUST respond as JSON with one of two shapes:
  {{ "kind": "reply", "message": "..." }}
    - when the user is asking a question or chatting; no spec change.
  {{ "kind": "patch", "rationale": "...", "patch": <FULL StrategySpec JSON> }}
    - when the user wants the strategy modified. The "patch" field must be
      the COMPLETE new StrategySpec (not a diff). It will be validated.

Hard rules:
  - Use ONLY the catalog block names in `patch`. Inventing block types is a bug.
  - When unsure, ask a clarifying question via "reply" first.
  - Keep "rationale" to 1-2 sentences explaining WHY the patch helps.

{catalog}

USER'S PRIOR STRATEGIES (for context):
{prior_block}

CURRENT STRATEGY SPEC:
```json
{spec_json}
```

RECENT CHAT HISTORY (oldest first):
{history_block}

NEW USER MESSAGE:
{user_message}

Respond now with JSON matching ChatResponse.
"""


def run_chat_turn(
    *,
    current_spec: dict,
    chat_history: list,
    prior_strategies_summary: list[dict],
    user_message: str,
    api_keys: dict | None = None,
) -> ChatResponse:
    """Single chat turn -> ChatResponse (reply or patch).

    On LLM failure returns ChatReply with a generic error message
    rather than raising - callers don't need to handle exceptions.

    ``api_keys`` (multi-tenant): when None, the host/cron path runs with
    env fallback (legacy). When a dict, it is the acting user's stored
    keys and ``call_research_llm`` resolves the model with NO env fallback,
    so the host's keys are never spent on a user's behalf.
    """
    prompt = build_chat_prompt(
        current_spec=current_spec,
        chat_history=chat_history,
        prior_strategies_summary=prior_strategies_summary,
        user_message=user_message,
    )
    return call_research_llm(
        prompt, ChatResponse,
        default_factory=lambda: ChatResponse(root=ChatReply(
            kind="reply",
            message="(LLM call failed - please retry or rephrase.)",
        )),
        api_keys=api_keys,
    )
