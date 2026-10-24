"""Sentiment module — insider flow + news polarity + analyst revisions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.modules.base import AnalysisModule
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _SentimentNarrative(BaseModel):
    narrative: str = Field(
        description="3-5 sentences synthesizing insider, news, and analyst signals."
    )


def _window_filter(items, date_attr: str, scan_date: str, days: int = 30):
    cutoff = (datetime.strptime(scan_date, "%Y-%m-%d") - timedelta(days=days)).date()
    out = []
    for it in items:
        d = getattr(it, date_attr, None)
        if not d:
            continue
        try:
            dd = datetime.strptime(d[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        if dd >= cutoff:
            out.append(it)
    return out


class SentimentModule(AnalysisModule):
    name = "sentiment"
    supports_personas: list[str] = []

    def run(self, request, persona, shared_data: SharedData) -> ModuleResult:
        persona = self._coerce_persona(persona)

        insider_recent = _window_filter(
            shared_data.insider_trades, "transaction_date",
            shared_data.scan_date, days=30,
        )
        news_recent = _window_filter(
            shared_data.news, "date", shared_data.scan_date, days=14,
        )
        actions_recent = _window_filter(
            shared_data.analyst_actions, "action_date",
            shared_data.scan_date, days=14,
        )

        if not insider_recent and not news_recent and not actions_recent:
            return ModuleResult(
                module_name=self.name, persona_used=None, markdown="",
                skipped=True,
                skip_reason="No sentiment signals in 14-30 day window",
            )

        net_insider = sum(
            float(getattr(t, "transaction_value", 0) or 0)
            for t in insider_recent
        )
        pos = sum(1 for n in news_recent if (getattr(n, "sentiment", "") or "").lower() == "positive")
        neg = sum(1 for n in news_recent if (getattr(n, "sentiment", "") or "").lower() == "negative")
        n_news = len(news_recent) or 1
        net_upgrades = sum(
            (1 if (getattr(a, "action", "") or "").lower() == "up" else
             -1 if (getattr(a, "action", "") or "").lower() == "down" else 0)
            for a in actions_recent
        )

        metrics = {
            "insider_net_value": round(net_insider, 2),
            "insider_trade_count_30d": float(len(insider_recent)),
            "news_positive_pct": round(pos / n_news * 100, 1) if news_recent else 0.0,
            "news_negative_pct": round(neg / n_news * 100, 1) if news_recent else 0.0,
            "analyst_net_upgrades": float(net_upgrades),
        }
        prompt = (
            f"Sentiment snapshot for {request.ticker} as of {shared_data.scan_date}:\n"
            f"  Insider net $ flow (30d): ${net_insider:+,.0f} "
            f"({len(insider_recent)} trades)\n"
            f"  News polarity (14d): {pos} positive, {neg} negative, "
            f"{len(news_recent) - pos - neg} neutral\n"
            f"  Analyst net upgrades (14d): {net_upgrades:+d}\n"
            f"\nWrite 3-5 sentences synthesizing what these three signals\n"
            f"jointly say about market positioning. Note any divergence.\n"
            f"Anchor on numbers; do not predict direction."
        )
        narrative = call_research_llm(
            prompt, _SentimentNarrative,
            default_factory=lambda: _SentimentNarrative(
                narrative=(
                    f"Insider ${net_insider:+,.0f}, "
                    f"news {pos}+/{neg}-, analyst net {net_upgrades:+d}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=None,
            markdown=narrative.narrative, key_metrics=metrics,
        )
