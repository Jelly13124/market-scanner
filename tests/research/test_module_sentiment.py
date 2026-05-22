"""Sentiment module: aggregate insider flow + recent news sentiment +
analyst-action net upgrades into a single narrative."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from src.research.modules.sentiment import SentimentModule
from src.research.models import ResearchRequest
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=False, scanner_context=None,
    )


def _shared():
    insider_trades = [
        SimpleNamespace(
            transaction_date="2026-05-15", name="CEO",
            transaction_shares=10_000, transaction_value=1_500_000,
            transaction_type="P",
        ),
    ]
    news = [
        SimpleNamespace(date="2026-05-20", sentiment="positive"),
        SimpleNamespace(date="2026-05-19", sentiment="positive"),
        SimpleNamespace(date="2026-05-18", sentiment="neutral"),
    ]
    actions = [
        SimpleNamespace(action_date="2026-05-21", action="up"),
        SimpleNamespace(action_date="2026-05-20", action="up"),
    ]
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[],
        insider_trades=insider_trades, news=news,
        analyst_actions=actions, analyst_targets=None,
        earnings_history=[], company_facts={},
        sector_etf_prices=[], spy_prices=[],
    )


class TestSentimentModule:
    def test_name(self):
        assert SentimentModule().name == "sentiment"

    @patch("src.research.modules.sentiment.call_research_llm")
    def test_aggregates_all_three(self, mock_llm):
        from src.research.modules.sentiment import _SentimentNarrative
        mock_llm.return_value = _SentimentNarrative(narrative="Bullish-tilt.")
        out = SentimentModule().run(_req(), None, _shared())
        assert out.skipped is False
        assert out.key_metrics["insider_net_value"] == 1_500_000.0
        assert out.key_metrics["news_positive_pct"] > 0
        assert out.key_metrics["analyst_net_upgrades"] == 2.0

    def test_skipped_when_all_empty(self):
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=[], insider_trades=[],
            news=[], analyst_actions=[], analyst_targets=None,
            earnings_history=[], company_facts={},
            sector_etf_prices=[], spy_prices=[],
        )
        out = SentimentModule().run(_req(), None, shared)
        assert out.skipped is True
