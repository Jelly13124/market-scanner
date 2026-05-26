"""Macro regime analyst — global market context as a first-class signal.

Replaces the earlier ``macro_context.py`` prompt-injection layer with
a proper analyst agent. The change: PM + every other agent + email
reports now see the macro signal explicitly, instead of just the
three personas whose prompts we had hard-wired the context block into.

Mechanics:
  * Fetch SPY 20 trading days + ^VIX once per scan_date (module-level
    cache keyed on date — multiple ticker calls in the same workflow
    reuse the snapshot, no repeated HTTP).
  * Same signal value written for every ticker in the workflow — macro
    is portfolio-level, not ticker-specific. Reasoning explicitly says
    so to head off "why are all 5 tickers identical?" confusion.

Signal mapping:
  regime + vol → signal, confidence

  regime=up, vol=low/normal     → bullish, conf scales with trend strength
  regime=up, vol=high           → neutral (rally on high vol = unstable)
  regime=down, vol=low/normal   → bearish, conf scales with trend
  regime=down, vol=high         → bearish, but lower conf (panic selling)
  regime=chop                   → neutral, low conf
  regime=unknown                → neutral, conf=0 (data unavailable)

Confidence ceiling 80 — we never claim >80% conviction from macro alone
because micro signals can still override.
"""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timedelta
from typing import Any

from langchain_core.messages import HumanMessage

from src.graph.state import AgentState, show_agent_reasoning
from src.utils.progress import progress

logger = logging.getLogger(__name__)


# Module-level cache so the macro snapshot is fetched once per scan_date
# regardless of how many tickers iterate through. Keyed on scan_date so
# back-to-back pipelines on different dates don't stale-cache.
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, dict[str, Any]] = {}


def _macro_snapshot(scan_date: str, provider_factory=None) -> dict[str, Any]:
    """Cached SPY + VIX snapshot for a given scan_date.

    Side-effect free: returns a fresh dict per call (the cache stores a
    copy, callers can mutate the returned dict safely).
    """
    with _CACHE_LOCK:
        cached = _CACHE.get(scan_date)
        if cached is not None:
            return dict(cached)

    snapshot: dict[str, Any] = {
        "scan_date": scan_date,
        "spy_return_20d": None,
        "spy_vol_20d": None,
        "regime": "unknown",
        "vix_level": None,
        "vol_regime": "unknown",
    }

    # SPY trend + vol via the v2 hybrid client
    try:
        from v2.data.factory import get_provider_factory
        factory = provider_factory or get_provider_factory()
        client = factory()
        try:
            end_dt = datetime.strptime(scan_date, "%Y-%m-%d").date()
            start_dt = end_dt - timedelta(days=45)  # buffer for ~30 trading days
            prices = client.get_prices(
                "SPY", start_date=start_dt.isoformat(), end_date=scan_date,
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        if prices and len(prices) >= 21:
            closes = [float(p.close) for p in sorted(prices, key=lambda p: p.time[:10])]
            tail21 = closes[-21:]
            ret_20d = (tail21[-1] / tail21[0]) - 1.0
            snapshot["spy_return_20d"] = round(ret_20d, 4)
            if ret_20d > 0.01:
                snapshot["regime"] = "up"
            elif ret_20d < -0.01:
                snapshot["regime"] = "down"
            else:
                snapshot["regime"] = "chop"
            # Annualized vol of last 20 daily returns
            daily = [tail21[i + 1] / tail21[i] - 1.0 for i in range(20)]
            mean = sum(daily) / 20
            var = sum((d - mean) ** 2 for d in daily) / 19
            snapshot["spy_vol_20d"] = round(math.sqrt(var) * math.sqrt(252), 3)
    except Exception as e:
        logger.warning("macro_agent: SPY fetch failed for %s: %s", scan_date, e)

    # VIX level via yfinance (^VIX is the standard symbol)
    try:
        import yfinance as yf
        vix_ticker = yf.Ticker("^VIX")
        hist = vix_ticker.history(
            start=(datetime.strptime(scan_date, "%Y-%m-%d") - timedelta(days=10)).date().isoformat(),
            end=(datetime.strptime(scan_date, "%Y-%m-%d") + timedelta(days=1)).date().isoformat(),
            auto_adjust=False,
        )
        if hist is not None and not hist.empty:
            vix_close = float(hist["Close"].iloc[-1])
            snapshot["vix_level"] = round(vix_close, 2)
            if vix_close > 25:
                snapshot["vol_regime"] = "high"
            elif vix_close < 15:
                snapshot["vol_regime"] = "low"
            else:
                snapshot["vol_regime"] = "normal"
    except Exception as e:
        logger.debug("macro_agent: VIX fetch failed for %s: %s", scan_date, e)

    with _CACHE_LOCK:
        _CACHE[scan_date] = dict(snapshot)
    return snapshot


def _classify(snapshot: dict[str, Any]) -> tuple[str, int, str]:
    """Map a macro snapshot to (signal, confidence, reasoning_facts)."""
    regime = snapshot.get("regime", "unknown")
    vol_regime = snapshot.get("vol_regime", "unknown")
    spy_ret = snapshot.get("spy_return_20d")
    vix = snapshot.get("vix_level")

    facts_bits = []
    if spy_ret is not None:
        facts_bits.append(f"SPY 20d {spy_ret * 100:+.1f}% ({regime})")
    if vix is not None:
        facts_bits.append(f"VIX {vix:.1f} ({vol_regime})")
    facts_str = " | ".join(facts_bits) if facts_bits else "macro data unavailable"

    if regime == "unknown":
        return "neutral", 0, facts_str
    if regime == "chop":
        return "neutral", 20, facts_str

    abs_trend = abs(spy_ret) if spy_ret is not None else 0.0
    # Map trend strength → confidence base. 2% over 20d ≈ floor; 8% ≈ ceiling.
    base_conf = min(80, max(25, int(abs_trend * 1000)))

    if regime == "up":
        if vol_regime == "high":
            # Rally on high vol — unstable, can flip → don't take strong directional bet
            return "neutral", 30, facts_str + " (rally on high vol = unstable)"
        return "bullish", base_conf, facts_str + " — risk-on backdrop"
    # regime == "down"
    if vol_regime == "high":
        # Panic selling — directionally bearish but uncertain magnitude
        return "bearish", min(50, base_conf), facts_str + " (panic selling — directional but noisy)"
    return "bearish", base_conf, facts_str + " — risk-off backdrop"


def macro_agent(state: AgentState, agent_id: str = "macro_agent"):
    """Emit a portfolio-level macro signal for every ticker in the workflow.

    Same value written per ticker because macro is portfolio-level; the
    PM correctly weighs it as one analyst voice. ``provider_factory`` is
    pulled from ``state`` if the orchestrator stashed one (the pipeline
    does); otherwise falls back to env-driven default.
    """
    data = state["data"]
    tickers: list[str] = data.get("tickers") or []
    end_date: str = data.get("end_date") or ""

    progress.update_status(agent_id, None, "Fetching SPY + VIX snapshot")
    snapshot = _macro_snapshot(end_date, provider_factory=None)
    signal, confidence, facts = _classify(snapshot)

    reasoning = (
        f"{facts}. Portfolio-level macro context — same signal applied "
        f"to every ticker in this run; persona/analyst opinions on the "
        f"specific ticker should be weighed alongside this regime overlay."
    )

    analysis: dict[str, dict] = {}
    for ticker in tickers:
        analysis[ticker] = {
            "signal": signal,
            "confidence": confidence,
            "reasoning": reasoning,
            "metrics": {
                "spy_return_20d": snapshot.get("spy_return_20d"),
                "spy_vol_20d": snapshot.get("spy_vol_20d"),
                "vix_level": snapshot.get("vix_level"),
                "regime": snapshot.get("regime"),
                "vol_regime": snapshot.get("vol_regime"),
            },
        }
        progress.update_status(agent_id, ticker, "Done")

    if state.get("metadata", {}).get("show_reasoning"):
        show_agent_reasoning(analysis, "Macro Agent")

    signals = data.setdefault("analyst_signals", {})
    signals[agent_id] = analysis

    message = HumanMessage(content=json.dumps(analysis), name=agent_id)
    progress.update_status(agent_id, None, "Done")
    return {"messages": [message], "data": data}
