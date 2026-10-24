"""Scanner signal analyst — turns v2 scanner output into a standard analyst signal.

The scanner (``v2/scanner/``) produces a ranked daily watchlist with rich
detector context (``triggered_detectors``, ``severity_z``, per-detector
``components``).

This node is the bridge. It runs alongside the persona analysts and the
fundamentals/technicals/etc. nodes; downstream ``risk_management_agent`` and
``portfolio_manager`` weigh its signal the same way as any other analyst.

**Design (2026-05-19 revision)**: scanner direction is now treated as a
raw guess rather than a prediction. The A/B backtest (scanner-flagged vs
random tickers, same agent pipeline) showed scanner adds value by
*filtering* — agents make better decisions on its picks — not by
predicting direction. So this bridge agent:

  * Always outputs ``signal="neutral"``. The detector ``direction`` field
    is intentionally NOT propagated as a directional opinion. Letting the
    persona analysts derive direction independently from clean event
    descriptions avoids contaminating their priors with detector-level
    noise (historical detector direction accuracy was ~42%, worse than
    coin flip on dir-adjusted forward alpha).
  * ``confidence`` = composite_score (attention priority, NOT directional
    conviction).
  * ``reasoning`` (LLM-generated) describes WHAT events fired in concrete
    factual terms without making a buy/sell call. On LLM failure → a
    deterministic fallback summary.

The agent reads ``state['data']['scanner_context']`` populated by the pipeline
orchestrator (or any caller that passes ``scanner_context=`` to
``run_hedge_fund``). When a ticker has no scanner context (e.g., the user
added it manually), the agent abstains cleanly with neutral + 0 confidence.

See project memory ``project-scanner-design-intent`` for the broader
framing.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.llm import call_llm
from src.utils.progress import progress


class _ScannerReasoning(BaseModel):
    """LLM output shape — we only ask the LLM for the prose; signal and
    confidence are computed deterministically from the scanner output."""

    reasoning: str = Field(
        description="2-3 sentences explaining what the scanner signals suggest."
    )


_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an analyst summarizing the output of a multi-detector "
        "quantitative scanner. Your job is to translate raw detector "
        "findings into a short, concrete, FACT-ONLY description of "
        "what events fired today on this ticker. Be specific about WHAT "
        "the detectors observed (e.g. 'unusual insider buying cluster', "
        "'price gapped through 52-week high on 3x volume', 'OBV diverging "
        "from price', 'news sentiment turned sharply positive'). "
        "DO NOT predict direction, DO NOT call it bullish/bearish, "
        "DO NOT make a buy/sell recommendation — downstream persona "
        "analysts and the portfolio manager decide that from the raw "
        "facts you describe. Respond as JSON with a single 'reasoning' "
        "field containing 2-3 sentences.",
    ),
    (
        "human",
        # No rank or composite_score in the prompt: 2026-05-21 §6 quartile
        # backtest showed Top-Bottom spread is -6.80% at 20d (no quant) and
        # the 5d FDR-significant cells (analyst_rating/earnings_event/
        # insider_cluster) are all negative — composite_score is provably
        # anti-predictive at the rank level. Hide rank/score so the LLM
        # judges on raw detector facts only.
        "Ticker: {ticker} (scan date {scan_date})\n"
        "\n"
        "Detectors that fired today:\n"
        "{detector_bullets}",
    ),
])


def _format_components(components: dict[str, float], max_items: int = 4) -> str:
    """Pick the most informative components to surface to the LLM.

    Detector ``components`` dicts can be wide (10+ keys). We don't need to
    flood the prompt with every metric — a few well-chosen ones plus the
    severity is enough for a 2-3 sentence summary.
    """
    if not isinstance(components, dict) or not components:
        return "(no components)"
    # Stable ordering: keys with numeric values, biggest absolute first.
    numeric = [
        (k, v) for k, v in components.items()
        if isinstance(v, (int, float))
    ]
    numeric.sort(key=lambda kv: abs(kv[1]), reverse=True)
    picked = numeric[:max_items]
    bits = []
    for k, v in picked:
        if isinstance(v, float):
            bits.append(f"{k}={v:+.3g}")
        else:
            bits.append(f"{k}={v}")
    # Append a count of non-numeric leftovers so the LLM knows there's more.
    leftover = len(components) - len(picked)
    if leftover > 0:
        bits.append(f"+{leftover} more")
    return ", ".join(bits)


def _detector_bullets(scanner_context: dict[str, Any]) -> str:
    """Compose the per-detector bullet list rendered into the LLM prompt."""
    triggered = scanner_context.get("triggered_detectors") or []
    components_map = scanner_context.get("triggered_components") or {}
    if not triggered:
        return "(no detectors fired)"
    lines = []
    for name in triggered:
        components = components_map.get(name, {})
        sev = None
        # severity_z is at the entry level (max across detectors), but per-detector
        # severity sits inside components for some detectors (e.g. earnings_event
        # exposes raw_z). Fall back to None.
        if isinstance(components, dict):
            sev = components.get("raw_z") or components.get("severity_z")
        sev_str = f" severity_z={sev:+.2f}" if isinstance(sev, (int, float)) else ""
        lines.append(f"  - {name}{sev_str}: {_format_components(components)}")
    return "\n".join(lines)


def _fallback_reasoning(scanner_context: dict[str, Any]) -> str:
    """Deterministic reasoning when the LLM call fails or is skipped.

    Direction-free per the 2026-05-19 redesign — the bridge agent describes
    events without claiming a direction; persona analysts derive direction
    from the events themselves.

    Does NOT include composite_score per the 2026-05-21 §6 finding that
    the score is anti-predictive at rank level. Matches the LLM prompt.
    """
    triggered = scanner_context.get("triggered_detectors") or []
    if not triggered:
        return "Scanner flagged no detectors."
    names = ", ".join(triggered)
    return (
        f"Scanner flagged {len(triggered)} event(s): {names}. "
        f"Directional interpretation left to downstream analysts."
    )


def scanner_signal_agent(
    state: AgentState,
    agent_id: str = "scanner_signal_agent",
) -> dict:
    """Translate scanner output into a per-ticker analyst signal.

    Reads ``state['data']['scanner_context']``; writes per-ticker
    ``{signal, confidence, reasoning}`` to
    ``state['data']['analyst_signals'][agent_id]``.
    """
    data = state.get("data", {})
    tickers: list[str] = data.get("tickers") or []
    scanner_context_all: dict[str, dict] = data.get("scanner_context") or {}

    analysis: dict[str, dict] = {}

    for ticker in tickers:
        progress.update_status(agent_id, ticker, "Reading scanner context")
        ctx = scanner_context_all.get(ticker)

        # Clean abstention — ticker is in the workflow but not in today's
        # scanner watchlist (e.g., user added it manually).
        if ctx is None:
            analysis[ticker] = {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": "Ticker not in today's scanner watchlist.",
            }
            progress.update_status(agent_id, ticker, "Not in scanner — abstain")
            continue

        # composite_score is already 0-100 from the scanner — used as the
        # "how worth-looking-at" attention priority, NOT directional confidence.
        score_raw = ctx.get("composite_score", 0)
        try:
            confidence = max(0, min(100, int(round(float(score_raw)))))
        except (TypeError, ValueError):
            confidence = 0

        # Generate the human-readable reasoning. LLM path with deterministic
        # fallback baked into call_llm's default_factory. Prompt is
        # direction-free — the LLM only describes facts.
        progress.update_status(agent_id, ticker, "Generating reasoning")
        prompt = _PROMPT.invoke({
            "ticker": ticker,
            "scan_date": ctx.get("scan_date", "(unknown)"),
            "detector_bullets": _detector_bullets(ctx),
        })
        result = call_llm(
            prompt=prompt,
            pydantic_model=_ScannerReasoning,
            agent_name=agent_id,
            state=state,
            default_factory=lambda c=ctx: _ScannerReasoning(
                reasoning=_fallback_reasoning(c)
            ),
        )

        # ALWAYS neutral — see module docstring + project memory
        # ``project-scanner-design-intent``. Persona analysts derive
        # direction from the event description in reasoning.
        analysis[ticker] = {
            "signal": "neutral",
            "confidence": confidence,
            "reasoning": result.reasoning,
        }
        progress.update_status(agent_id, ticker, "Done")

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(analysis, "Scanner Signal Agent")

    # Write the signal alongside the other analysts.
    signals = data.setdefault("analyst_signals", {})
    signals[agent_id] = analysis

    message = HumanMessage(content=json.dumps(analysis), name=agent_id)
    progress.update_status(agent_id, None, "Done")
    return {"messages": [message], "data": data}
