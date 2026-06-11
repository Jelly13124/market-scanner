"""CapitalStructure - balance-sheet health section (250-450 words).

Builds a deterministic, GROUNDED data block from the latest *knowable* annual
line items (yfinance via ``src.tools.api.search_line_items``, with the standard
~60-day reporting-availability lag) and hands it to the section LLM runner. The
LLM narrates leverage / debt serviceability / liquidity / capital allocation
using ONLY those numbers — the block is prepended so the existing
anti-hallucination directive governs it.

Grounded ratios (each None/zero-denominator guarded → "n/a"):
  * debt/equity        = total_debt / shareholders_equity
  * net debt           = total_debt − cash_and_equivalents
  * leverage           = total_liabilities / total_assets
  * interest coverage  = operating_income / interest_expense  (omitted entirely
                         when operating income is unavailable)
  * cash               = cash_and_equivalents
  * shares outstanding = outstanding_shares (+ YoY dilution when a prior year is
                         knowable)

NEVER raises: the only network touch (search_line_items) is wrapped in
try/except → ``[]``; with no usable data the block renders a "data unavailable"
note and the ticker is still reported.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

# Import the symbol on THIS module (not via ``api.search_line_items``) so tests
# can monkeypatch ``capital_structure.search_line_items`` and have it take
# effect here, mirroring the institutional_flow section's fetch-seam pattern.
from src.tools.api import search_line_items
from src.research.models import SectionPayload
from src.research.sections import SECTION_REGISTRY
from src.research.sections._llm_runner import run_llm_section
from src.research.sections.base import Section, SectionContext, load_prompt


# The point-in-time reporting-availability lag (calendar days). Matches the
# self-evolve backtest's FUNDAMENTAL_AVAILABILITY_LAG_DAYS: at ``scan_date`` we
# may only read filings whose period ended on/before ``scan_date − 60d``.
_FUNDAMENTAL_AVAILABILITY_LAG_DAYS = 60

# The balance-sheet / income-statement rows the block needs (see line_items.py
# _YF_MAP for the yfinance row each maps to).
_LINE_ITEMS = [
    "total_debt",
    "shareholders_equity",
    "total_liabilities",
    "total_assets",
    "cash_and_equivalents",
    "operating_income",
    "interest_expense",
    "outstanding_shares",
]


class _Narrative(BaseModel):
    narrative: str = Field(description="250-450 word markdown body interpreting the balance " "sheet. No top-level heading.")


_SYSTEM_PROMPT = load_prompt("modules/capital_structure.md")


# --------------------------------------------------------------------------- #
# date + as-of helpers (local — keeps src/research/ free of a v2 cross-dep)
# --------------------------------------------------------------------------- #


def _parse_iso(s) -> str | None:
    """``YYYY-MM-DD`` prefix of an ISO date, or None if unparseable."""
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def _minus_days(iso: str, n: int) -> str:
    d = datetime.strptime(iso[:10], "%Y-%m-%d").date() - timedelta(days=n)
    return d.isoformat()


def _latest_lagged(items: list, asof: str):
    """Newest record with ``report_period <= asof − 60d`` (or None)."""
    cutoff = _minus_days(asof, _FUNDAMENTAL_AVAILABILITY_LAG_DAYS)
    best = None
    best_d: str | None = None
    for it in items or []:
        d = _parse_iso(getattr(it, "report_period", None))
        if d is None or d > cutoff:
            continue
        if best_d is None or d > best_d:
            best, best_d = it, d
    return best


def _prior_year(items: list, latest) -> object | None:
    """Newest record strictly older than ``latest`` (for YoY dilution)."""
    if latest is None:
        return None
    top_d = _parse_iso(getattr(latest, "report_period", None))
    if top_d is None:
        return None
    best = None
    best_d: str | None = None
    for it in items or []:
        d = _parse_iso(getattr(it, "report_period", None))
        if d is None or d >= top_d:
            continue
        if best_d is None or d > best_d:
            best, best_d = it, d
    return best


# --------------------------------------------------------------------------- #
# number formatting + safe-ratio helpers
# --------------------------------------------------------------------------- #


def _num(v):
    """Coerce to float, dropping None / NaN / non-numeric -> None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _ratio(numer, denom) -> str:
    """Guarded ratio → 2dp string, or 'n/a' on missing/zero denominator."""
    n, d = _num(numer), _num(denom)
    if n is None or d is None or d == 0.0:
        return "n/a"
    return f"{n / d:.2f}"


def _dollars(v) -> str:
    """Signed thous-separated integer dollars, or 'n/a'."""
    f = _num(v)
    if f is None:
        return "n/a"
    return f"{f:,.0f}"


def _capital_block(ctx: SectionContext) -> str:
    """Build the GROUNDED capital-structure markdown from lagged line items.

    Best-effort: a fetch failure or empty/insufficient data yields a short
    "data unavailable" note rather than raising.
    """
    asof = _parse_iso(getattr(ctx.shared, "scan_date", None)) or datetime.today().date().isoformat()
    try:
        items = search_line_items(ctx.request.ticker, _LINE_ITEMS, asof, period="annual")
    except Exception:  # noqa: BLE001 — best-effort; treat as no data
        items = []

    latest = _latest_lagged(items, asof)
    if latest is None:
        return "CAPITAL STRUCTURE (grounded data):\n" "  Balance-sheet line items are unavailable for this ticker right " "now — narrate that the capital-structure data could not be " "retrieved and avoid inventing figures.\n"

    total_debt = getattr(latest, "total_debt", None)
    equity = getattr(latest, "shareholders_equity", None)
    total_liab = getattr(latest, "total_liabilities", None)
    total_assets = getattr(latest, "total_assets", None)
    cash = getattr(latest, "cash_and_equivalents", None)
    op_income = getattr(latest, "operating_income", None)
    interest_exp = getattr(latest, "interest_expense", None)
    shares = getattr(latest, "outstanding_shares", None)

    period = _parse_iso(getattr(latest, "report_period", None)) or "latest"

    # net debt = total_debt − cash (only when both present)
    td, c = _num(total_debt), _num(cash)
    net_debt = _dollars(td - c) if (td is not None and c is not None) else "n/a"

    lines: list[str] = []
    lines.append("CAPITAL STRUCTURE (grounded data):")
    lines.append(f"  Source: latest annual filing, period {period} (60-day availability lag applied).")
    lines.append(f"  Debt / equity: {_ratio(total_debt, equity)}  (total_debt {_dollars(total_debt)} / equity {_dollars(equity)})")
    lines.append(f"  Net debt: {net_debt}  (total_debt {_dollars(total_debt)} − cash {_dollars(cash)})")
    lines.append(f"  Leverage (total_liabilities / total_assets): {_ratio(total_liab, total_assets)}")

    # Interest coverage — omit the line entirely when operating income is absent.
    if _num(op_income) is not None:
        lines.append(f"  Interest coverage (operating_income / interest_expense): {_ratio(op_income, interest_exp)}")

    lines.append(f"  Cash & equivalents: {_dollars(cash)}")

    # Shares outstanding + YoY dilution (when a prior year is knowable).
    shares_line = f"  Shares outstanding: {_dollars(shares)}"
    prior = _prior_year(items, latest)
    prior_shares = _num(getattr(prior, "outstanding_shares", None)) if prior is not None else None
    cur_shares = _num(shares)
    if cur_shares is not None and prior_shares is not None and prior_shares != 0.0:
        yoy = cur_shares / prior_shares - 1.0
        direction = "dilution" if yoy > 0 else ("buyback" if yoy < 0 else "flat")
        shares_line += f"  (YoY {yoy * 100:+.1f}% — {direction})"
    lines.append(shares_line)

    return "\n".join(lines) + "\n"


class CapitalStructureSection(Section):
    name = "capital_structure"
    supports_personas = []

    def run(self, ctx: SectionContext) -> SectionPayload:
        user_prompt = (
            _capital_block(ctx)
            + "\n\n"
            + _SYSTEM_PROMPT
            + "\n\n--- TICKER CONTEXT ---\n"
            + f"Ticker: {ctx.request.ticker}\n"
            + f"Objective: {ctx.request.objective}\n"
            + "\n\n--- YOUR TASK ---\n"
            + "Write a 250-450 word Capital Structure review per the rules "
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
            markdown_heading="## Capital Structure",
        )


SECTION_REGISTRY["capital_structure"] = CapitalStructureSection()
