"""DataHealth - deterministic section that inspects SharedData and
reports which inputs are present/fresh/missing. No LLM call.

Output: markdown table with rows matching the SOP Data Health spec
(Quote, Daily/Weekly chart, Financials, Macro, Sector, News, etc.).
"""

from __future__ import annotations

from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext


def _row(item: str, present: bool, source: str, notes: str = "") -> str:
    status = "OK" if present else "missing"
    return f"| {item} | {status} | {source} | {notes} |"


class DataHealthSection(Section):
    name = "data_health"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        s = ctx.shared
        rows = [
            "| Item | Status | Source | Notes |",
            "|---|---|---|---|",
            _row("Live Quote", bool(s.quote), "Finnhub", "Current quote; daily bars are separate"),
            _row("Daily chart / indicators", len(s.prices) >= 50, "v2/data",
                 f"{len(s.prices)} daily bars"),
            _row("Weekly chart / indicators", len(s.prices) >= 250, "v2/data (resampled)",
                 ""),
            _row("Financials / filings", bool(s.financials), "v2/data",
                 f"{len(s.financials)} periods"),
            _row("Earnings release / transcript", bool(s.earnings_history), "v2/data",
                 f"{len(s.earnings_history)} earnings"),
            _row("Macro data", bool(s.spy_prices), "SPY proxy",
                 f"{len(s.spy_prices)} SPY bars"),
            _row("Sector / peer data", bool(s.sector_etf_prices), "Sector ETF",
                 f"{len(s.sector_etf_prices)} bars"),
            _row("News / catalysts", bool(s.news), "v2/data",
                 f"{len(s.news)} items"),
            _row("Insider trades", bool(s.insider_trades), "v2/data",
                 f"{len(s.insider_trades)} trades"),
            _row("Analyst actions", bool(s.analyst_actions), "v2/data",
                 f"{len(s.analyst_actions)} actions"),
        ]
        rows.append(_row("MongoDB storage", s.storage_status == "ready", "MongoDB", s.storage_status + "; online fallback enabled"))
        md = "## Data Health\n\n" + "\n".join(rows) + "\n"
        return SectionPayload(
            name=self.name, markdown=md, structured={"storage_status": s.storage_status, "inputs": s.quality},
            skipped=False, persona_used=None,
        )


SECTION_REGISTRY["data_health"] = DataHealthSection()
