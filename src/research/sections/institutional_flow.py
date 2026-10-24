"""InstitutionalFlow - deterministic section that surfaces the dealer-gamma
(GEX) + FINRA off-exchange short-volume data to the *reader*.

This data already feeds the agent's QUANT CONTEXT prompt (see
``src.research.quant_context``), but until now it was invisible in the rendered
HTML report. This section renders it as a human-readable "Institutional
Positioning" block + a gamma-walls bar chart.

No LLM call. Best-effort: both fetches are network touches isolated behind the
``institutional_flow`` adapters (each returns ``None`` on failure), so this
section degrades to a short "data unavailable" note rather than crashing.

HONESTY (load-bearing labels):
  * dealer gamma = an options-implied *model snapshot*, not a position report.
  * short% = the FINRA Reg-SHO daily short-volume PROXY, NOT true dark-pool/ATS
    flow (much of it is routine market-maker hedging).
"""

from __future__ import annotations

from src.research.charts.render import png_to_b64_uri, render_gamma_walls_png

# Import the module (not the names) so tests can monkeypatch
# ``institutional_flow.fetch_gamma_exposure`` / ``fetch_short_volume`` on the
# section module and have the patch take effect here.
from src.research.institutional_flow import fetch_gamma_exposure, fetch_short_volume
from src.research.llm import localized_heading
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections.base import Section, SectionContext


def _fmt_gamma_dollars(num: float | None) -> str:
    """Compact signed dollar formatter: ``$X.XXB`` / ``-$X.XXB`` at >=1e9, else
    ``$XXXm`` / ``-$XXXm`` (millions). ``None`` -> ``n/a``. Mirrors the prompt
    block's formatter so the reader sees the same units the agent did."""
    if num is None:
        return "n/a"
    try:
        n = float(num)
    except (TypeError, ValueError):
        return "n/a"
    sign = "-" if n < 0 else ""
    mag = abs(n)
    if mag >= 1e9:
        return f"{sign}${mag / 1e9:.2f}B"
    return f"{sign}${mag / 1e6:.0f}m"


def _fmt_num(num: float | None, digits: int = 2) -> str:
    if num is None:
        return "n/a"
    try:
        return f"{float(num):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_pct(num: float | None) -> str:
    """A short *fraction* (0..1) as a level, e.g. 0.482 -> '48.2%'. Unsigned —
    a short fraction is always >=0, so no '+/-'."""
    if num is None:
        return "n/a"
    try:
        return f"{float(num) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _regime_phrase(regime: str | None) -> str:
    if regime == "negative":
        return "NEGATIVE — dealers net short gamma -> hedging AMPLIFIES moves (squeeze-prone)"
    if regime == "positive":
        return "POSITIVE — dealers net long gamma -> hedging DAMPENS moves (pinned to walls)"
    return str(regime or "flat").upper()


def _gamma_markdown(gex: dict) -> list[str]:
    """Markdown lines for the dealer-gamma sub-block (assumes gex is non-None)."""
    lines: list[str] = []
    lines.append("**Dealer gamma (GEX)** — options-implied model snapshot, not a position " "report. Net GEX is dollars of dealer gamma per 1% move in the underlying.")
    lines.append("")
    spot = gex.get("spot")
    regime = gex.get("regime")
    flip = gex.get("gamma_flip")
    lines.append(f"- Spot: {_fmt_num(spot)}")
    lines.append(f"- Regime: {_regime_phrase(regime)}")
    lines.append(f"- Net GEX: {_fmt_gamma_dollars(gex.get('total_gex'))} per 1% move")
    lines.append(f"- Call gamma: {_fmt_gamma_dollars(gex.get('call_gex'))}  |  " f"Put gamma: {_fmt_gamma_dollars(gex.get('put_gex'))}")
    if flip is not None:
        lines.append(f"- Gamma flip: {_fmt_num(flip)} (above = net long-gamma/stable, " "below = short-gamma/unstable)")
    else:
        lines.append("- Gamma flip: n/a")

    walls = gex.get("walls") or []
    if walls:
        lines.append("")
        lines.append("Gamma walls (dealer-hedging levels that act as support/resistance):")
        lines.append("")
        lines.append("| Strike | Dealer $-gamma (per 1% move) |")
        lines.append("|---|---|")
        for w in walls[:5]:
            if not isinstance(w, dict):
                continue
            lines.append(f"| {_fmt_num(w.get('strike'))} | {_fmt_gamma_dollars(w.get('gamma_dollars'))} |")
    return lines


def _short_volume_markdown(sv: dict) -> list[str]:
    """Markdown lines for the off-exchange short-pressure sub-block."""
    lines: list[str] = []
    lines.append("**Off-exchange short pressure** — FINRA Reg-SHO daily short volume. This " "is a PROXY, NOT true dark-pool/ATS flow (much is routine market-maker " "hedging), so read the level cautiously.")
    lines.append("")
    date = sv.get("date")
    n_days = sv.get("n_days")
    trend = str(sv.get("trend") or "flat").upper()
    lines.append(f"- Latest short volume: {_fmt_pct(sv.get('short_pct'))} of total " f"({date if date else 'n/a'})")
    lines.append(f"- {n_days if n_days is not None else 'n/a'}-day average: " f"{_fmt_pct(sv.get('avg_short_pct'))}  |  Trend: {trend}")
    return lines


class InstitutionalFlowSection(Section):
    name = "institutional_flow"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        lang = getattr(ctx.request, "report_language", "en")
        heading = localized_heading("## Institutional Positioning", lang)
        ticker = ctx.request.ticker

        # Best-effort fetches — each adapter already returns None on failure and
        # never raises, but guard anyway so a section never crashes the report.
        try:
            gex = fetch_gamma_exposure(ticker)
        except Exception:  # noqa: BLE001 — best-effort; treat as no data
            gex = None
        try:
            sv = fetch_short_volume(ticker)
        except Exception:  # noqa: BLE001 — best-effort; treat as no data
            sv = None

        if not gex and not sv:
            md = f"{heading}\n\n" "Institutional positioning data (dealer gamma + off-exchange short " "volume) is unavailable for this ticker right now.\n"
            return SectionPayload(
                name=self.name,
                markdown=md,
                structured=None,
                skipped=False,
                persona_used=None,
            )

        body: list[str] = [heading, ""]
        if gex:
            body.extend(_gamma_markdown(gex))
            body.append("")
        if sv:
            body.extend(_short_volume_markdown(sv))
            body.append("")

        md = "\n".join(body).rstrip() + "\n"

        structured: dict | None = None
        if gex:
            caption = "Dealer gamma walls (options-implied). Bars = per-strike dealer " "$-gamma per 1% move; green dashed = spot, red dotted = gamma flip. " "High-gamma strikes tend to act as hedging-driven support/resistance."
            structured = {
                "charts": [
                    {
                        "src": png_to_b64_uri(render_gamma_walls_png(gex)),
                        "alt": "Gamma walls",
                        "caption": caption,
                    }
                ]
            }

        return SectionPayload(
            name=self.name,
            markdown=md,
            structured=structured,
            skipped=False,
            persona_used=None,
        )


SECTION_REGISTRY["institutional_flow"] = InstitutionalFlowSection()
