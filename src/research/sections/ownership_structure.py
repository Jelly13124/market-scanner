"""OwnershipStructure - who-owns-it section (200-400 words).

Builds a deterministic, GROUNDED data block from ``fetch_ownership`` (yfinance,
best-effort) + the insider-transactions enrich already on ``ctx.shared`` and
hands it to the section LLM runner. The LLM narrates ownership split,
institutional conviction, insider signal, and dilution using ONLY those numbers
— the block is prepended so the existing anti-hallucination directive governs
it.

Grounded fields (each None-guarded → "n/a"):
  * insider %            (heldPercentInsiders, a 0..1 fraction → %)
  * institution %        (heldPercentInstitutions, a 0..1 fraction → %)
  * institution count    (major_holders institutionsCount)
  * top holders          (institutional_holders → name + % of shares)
  * shares outstanding
  * recent insider net   (signed Σ transaction_shares over the lookback window)

NEVER raises: the ownership fetch is best-effort (wrapped here too); with no
ownership data the block renders a "data unavailable" note and the ticker is
still reported.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Import the symbol on THIS module so tests can monkeypatch
# ``ownership_structure.fetch_ownership`` and have it take effect here, mirroring
# the institutional_flow section's fetch-seam pattern.
from src.research.ownership_fetch import fetch_ownership
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


class _Narrative(BaseModel):
    narrative: str = Field(description="200-400 word markdown body on the ownership structure. " "No top-level heading.")


_SYSTEM_PROMPT = load_prompt("modules/ownership_structure.md")


def _num(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _pct(frac) -> str:
    """A 0..1 fraction as a percentage string, or 'n/a'."""
    f = _num(frac)
    if f is None:
        return "n/a"
    return f"{f * 100:.2f}%"


def _int(v) -> str:
    f = _num(v)
    if f is None:
        return "n/a"
    return f"{f:,.0f}"


def _insider_net(insider_trades) -> tuple[float | None, int]:
    """Signed Σ ``transaction_shares`` over the enrich window + the trade count.

    Positive = net buying, negative = net selling. Returns ``(None, 0)`` when
    there are no trades with a usable signed share count.
    """
    total = 0.0
    n = 0
    for t in insider_trades or []:
        shares = _num(getattr(t, "transaction_shares", None))
        if shares is None:
            continue
        total += shares
        n += 1
    if n == 0:
        return None, 0
    return total, n


def _ownership_block(ctx: SectionContext) -> str:
    """Build the GROUNDED ownership markdown. Best-effort: a fetch failure or
    all-None ownership yields a short "data unavailable" note, never raises."""
    try:
        own = fetch_ownership(ctx.request.ticker)
    except Exception:  # noqa: BLE001 — best-effort; treat as no data
        own = None
    own = own or {}

    insider_pct = own.get("insider_pct")
    institution_pct = own.get("institution_pct")
    institution_count = own.get("institution_count")
    top_holders = own.get("top_holders")
    shares_outstanding = own.get("shares_outstanding")

    net_shares, n_trades = _insider_net(getattr(ctx.shared, "insider_trades", None))

    # "No ownership data at all" → a single honest note (the insider net may
    # still be present, but on its own it's thin; only short-circuit when BOTH
    # the ownership fetch and the insider enrich are empty).
    have_ownership = any(v is not None for v in (insider_pct, institution_pct, institution_count, shares_outstanding)) or bool(top_holders)
    if not have_ownership and net_shares is None:
        return "OWNERSHIP STRUCTURE (grounded data):\n" "  Ownership data (insider / institutional holdings + insider " "transactions) is unavailable for this ticker right now — narrate " "that the ownership data could not be retrieved and avoid inventing " "figures.\n"

    lines: list[str] = []
    lines.append("OWNERSHIP STRUCTURE (grounded data):")
    lines.append(f"  Insider ownership: {_pct(insider_pct)}")
    lines.append(f"  Institutional ownership: {_pct(institution_pct)}")
    lines.append(f"  Institutional holders (count): {_int(institution_count)}")
    lines.append(f"  Shares outstanding: {_int(shares_outstanding)}")

    if top_holders:
        lines.append("  Top institutional holders:")
        for h in top_holders[:10]:
            if not isinstance(h, dict):
                continue
            name = h.get("name") or "?"
            lines.append(f"    - {name}: {_pct(h.get('pct'))} of shares")
    else:
        lines.append("  Top institutional holders: n/a")

    # Recent insider net (signed share count over the enrich lookback window).
    if net_shares is None:
        lines.append("  Recent insider transactions (net shares): n/a")
    else:
        direction = "net buying" if net_shares > 0 else ("net selling" if net_shares < 0 else "flat")
        lines.append(f"  Recent insider transactions (net shares): {net_shares:,.0f} across {n_trades} trade(s) — {direction}")

    return "\n".join(lines) + "\n"


class OwnershipStructureSection(Section):
    name = "ownership_structure"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _ownership_block(ctx)
            + "\n\n"
            + _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 200-400 word Ownership Structure review per the rules "
            + "above. Output as the 'narrative' field — markdown WITHOUT the "
            + "top heading. Use ONLY the numbers in the grounded block; when a "
            + "value is 'n/a' or absent, say the data was insufficient rather "
            + "than estimating it."
        )
        return run_llm_section(
            section_name=self.name,
            ctx=ctx,
            prompt=user_prompt,
            output_model=_Narrative,
            markdown_heading="## Ownership Structure",
        )


SECTION_REGISTRY["ownership_structure"] = OwnershipStructureSection()
