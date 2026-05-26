"""LLM-generated "Why this pick" gist per ticker for email notifications.

Each call asks the LLM for ~60 Chinese characters summarizing why the
PM took its position, given the scanner triggers + top analyst signals
+ PM reasoning. Used purely as an email-side decoration — render.py
treats the gist as optional and renders without it on any failure.

**Why a separate module from render.py**: render.py stays pure (no
network) so its tests run instantly and don't need LLM mocking. The
dispatcher pre-computes a `gist_map` and hands it to render as a
plain dict.

**Failure isolation**: every per-ticker LLM call is wrapped — a 401
on one ticker doesn't kill the others. If ALL fail (e.g. no API key
configured), the resulting dict is empty and render renders the email
without any gist sections.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Max characters of PM reasoning we include in the prompt — long
# reasoning eats tokens and the LLM only needs the gist.
_PROMPT_REASONING_CAP = 400
# Max gist length we keep — LLM tends to over-deliver; trim defensively
# so the email row doesn't blow up.
_GIST_CHAR_CAP = 80


class _GistResponse(BaseModel):
    """LLM output shape. We coerce to JSON mode + structured output via
    the standard ``call_llm`` helper so a stray prefix sentence doesn't
    blow up our 60-char target."""

    gist: str = Field(description="60-character Chinese take on why this pick makes sense (or doesn't).")


def _top_analyst_signals(
    analyst_signals: dict[str, dict[str, Any]], ticker: str, k: int = 2,
) -> list[tuple[str, dict[str, Any]]]:
    """Return up to k (analyst_key, sig_dict) pairs ordered by descending
    confidence — feeds the LLM the strongest opinions to summarize."""
    per_analyst: list[tuple[str, dict[str, Any]]] = []
    for analyst_key, ticker_to_sig in (analyst_signals or {}).items():
        sig = (ticker_to_sig or {}).get(ticker)
        if not sig:
            continue
        per_analyst.append((analyst_key, sig))

    def _conf(item: tuple[str, dict[str, Any]]) -> float:
        c = item[1].get("confidence")
        return float(c) if isinstance(c, (int, float)) else -1.0

    return sorted(per_analyst, key=_conf, reverse=True)[:k]


def _build_prompt_text(
    *,
    ticker: str,
    decision: dict[str, Any],
    scanner_triggers: list[str],
    top_analysts: list[tuple[str, dict[str, Any]]],
) -> str:
    """Render the single user message that feeds the LLM. Short, factual,
    Chinese-output instruction. Format keeps token usage low."""
    action = (decision.get("action") or "hold").upper()
    qty = decision.get("quantity", "—")
    conf = decision.get("confidence", "—")
    pm_reasoning = str(decision.get("reasoning") or "").strip()[:_PROMPT_REASONING_CAP]

    triggers_line = ", ".join(scanner_triggers) if scanner_triggers else "无"

    analyst_lines: list[str] = []
    for key, sig in top_analysts:
        short_name = key.replace("_agent", "").replace("_", " ")
        s = sig.get("signal", "neutral")
        c = sig.get("confidence", "—")
        analyst_lines.append(f"- {short_name}: {s} (conf {c})")
    analysts_block = "\n".join(analyst_lines) if analyst_lines else "（无 analyst 信号）"

    return (
        "你是一名严格的中文交易复盘助手。\n"
        "用一句话（不超过 60 个汉字）说清楚 PM 这次决策的核心理由或风险。\n"
        "禁止 markdown、禁止换行、禁止英文引号。基于以下事实：\n\n"
        f"标的：{ticker}\n"
        f"PM 决策：{action} 数量={qty} conf={conf}\n"
        f"PM reasoning：{pm_reasoning or '（无）'}\n"
        f"Scanner 触发器：{triggers_line}\n"
        "最强 analyst 信号：\n"
        f"{analysts_block}\n"
    )


def _generate_one(
    *,
    ticker: str,
    decision: dict[str, Any],
    scanner_triggers: list[str],
    top_analysts: list[tuple[str, dict[str, Any]]],
    model_name: str,
    model_provider: str,
    call_llm_fn=None,
) -> str | None:
    """Render prompt + one LLM call. Returns the gist (truncated) or None
    on any failure. Caller swallows None silently — gist is decorative."""
    # Lazy import so tests don't drag in the LLM stack.
    if call_llm_fn is None:
        from src.utils.llm import call_llm as call_llm_fn  # type: ignore[no-redef]
    from src.llm.models import get_model

    prompt = _build_prompt_text(
        ticker=ticker, decision=decision,
        scanner_triggers=scanner_triggers, top_analysts=top_analysts,
    )

    # Build a minimal "state" the call_llm helper happily passes through to
    # get_model(). We don't pass it through call_llm's state arg because
    # that requires the full AgentState shape — instead, bypass and use
    # get_model directly with structured output, mirroring call_llm's
    # internal happy path. This keeps the gist call free of agent
    # workflow dependencies.
    try:
        llm = get_model(model_name, model_provider, api_keys=None)
        if llm is None:
            return None
        # Try JSON-mode structured output first (works on OpenAI, DeepSeek,
        # Anthropic). Fallback to plain text otherwise.
        structured = llm.with_structured_output(_GistResponse, method="json_mode")
        result = structured.invoke(prompt)
        gist = getattr(result, "gist", None) or ""
        gist = gist.strip()
        if not gist:
            return None
        if len(gist) > _GIST_CHAR_CAP:
            gist = gist[:_GIST_CHAR_CAP].rstrip() + "…"
        return gist
    except Exception as e:
        # Decorative feature — never break the email over a bad LLM call.
        logger.warning(
            "gist generation failed for %s (%s/%s): %s",
            ticker, model_provider, model_name, e,
        )
        return None


def generate_gists(
    run: Any,
    *,
    model_name: str,
    model_provider: str,
    call_llm_fn=None,
) -> dict[str, str]:
    """Generate a per-ticker gist for every ticker in ``run.agent_decisions``.

    Returns a dict ``{ticker: gist}`` — keys are only present for tickers
    where the LLM call succeeded. Empty dict means no gists at all
    (e.g. provider misconfigured, every call failed). Caller passes the
    result to ``render_pipeline_html(run, gist_map=...)`` which renders
    the email with or without per-ticker gists transparently.

    Per-ticker failures are isolated: one 401 doesn't stop the rest.
    """
    agent_decisions = (
        getattr(run, "agent_decisions_json", None)
        or getattr(run, "agent_decisions", None)
        or {}
    )
    analyst_signals = (
        getattr(run, "analyst_signals_json", None)
        or getattr(run, "analyst_signals", None)
        or {}
    )
    if not agent_decisions:
        return {}

    out: dict[str, str] = {}
    for ticker, decision in agent_decisions.items():
        # Scanner triggers from the scanner_signal agent's own reasoning,
        # or fall back to empty.
        scanner_block = (analyst_signals.get("scanner_signal_agent") or {}).get(ticker) or {}
        scanner_triggers: list[str] = []
        reasoning = scanner_block.get("reasoning")
        if isinstance(reasoning, dict):
            tnames = reasoning.get("triggered_detectors")
            if isinstance(tnames, list):
                scanner_triggers = [str(t) for t in tnames]
        # If we couldn't recover detector names from reasoning, that's
        # fine — the prompt still goes through with "无".

        top_analysts = _top_analyst_signals(analyst_signals, ticker, k=2)

        gist = _generate_one(
            ticker=ticker,
            decision=decision,
            scanner_triggers=scanner_triggers,
            top_analysts=top_analysts,
            model_name=model_name,
            model_provider=model_provider,
            call_llm_fn=call_llm_fn,
        )
        if gist:
            out[ticker] = gist
    return out
