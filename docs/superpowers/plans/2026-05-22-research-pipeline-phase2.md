# Per-Stock Research Pipeline — Phase 2 (Personas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layer the persona dimension onto Phase 1's pipeline — 8 investor persona prompt fragments, an LLM-driven router that picks which persona analyzes each module, three persona-capable modules that actually use their persona param, and a new debate module that fires when the router picks two personas.

**Architecture:** Stay linear (no LangGraph yet — same reasoning as Phase 1: the conditional shape is simple enough that a Python function reads clearer). Router is one extra LLM call up front when `request.use_personas=True`. Modules consult their persona arg and prepend a persona system prompt when set. Debate is a single LLM call that simulates a two-round transcript between the router-picked pair.

**Tech Stack:** Same as Phase 1 — Python 3.13, Pydantic v2, DeepSeek-chat via `src/research/llm.py`. No new deps.

**Spec:** `docs/superpowers/specs/2026-05-22-research-pipeline-design.md`
**Phase 1 plan (for reference):** `docs/superpowers/plans/2026-05-22-research-pipeline-phase1.md`

**This plan is Phase 2 of 3.** Phase 3 adds production wiring (DB tables + Alembic + API + HTML email + scheduler).

---

## File structure (Phase 2)

```
src/research/
  personas/                       # NEW namespace
    __init__.py                   # PERSONA_REGISTRY: dict[str, PersonaPrompt]
    base.py                       # PersonaPrompt ABC
    buffett.py munger.py graham.py fisher.py
    lynch.py wood.py burry.py druckenmiller.py
  router.py                       # NEW: persona-router LLM agent
  modules/
    debate.py                     # NEW: two-persona transcript module
    fundamentals.py               # MODIFY: use persona arg
    valuation.py                  # MODIFY: use persona arg
    risk_position.py              # MODIFY: use persona arg
  pipeline.py                     # MODIFY: wire router + debate
  __main__.py                     # MODIFY: --use-personas flag

tests/research/
  test_personas.py                # NEW: ABC + all 8 personas
  test_router.py                  # NEW
  test_module_debate.py           # NEW
  test_module_fundamentals.py     # MODIFY: add persona tests
  test_module_valuation.py        # MODIFY: add persona tests
  test_module_risk_position.py    # MODIFY: add persona tests
  test_pipeline.py                # MODIFY: add use_personas paths
  test_cli.py                     # MODIFY: add --use-personas flag
```

**What is NOT touched in Phase 2:**
- `src/research/models.py` (Phase 1 dataclasses are stable)
- `src/research/shared_data.py`
- `src/research/llm.py`
- `src/research/synthesizer.py` (persona assignments don't affect synthesizer logic — synthesizer just reads module outputs)
- The other 5 modules (macro, sector, financials, technical, sentiment) — they have `supports_personas = []` and stay objective.
- `src/research/modules/detector_backtest.py` (no LLM, no persona)
- `src/agents/`, `v2/`, `app/backend/` (legacy, A/B preserved)

---

## Task 1: PersonaPrompt ABC + Buffett + registry scaffold

**Files:**
- Create: `src/research/personas/__init__.py`
- Create: `src/research/personas/base.py`
- Create: `src/research/personas/buffett.py`
- Create: `tests/research/test_personas.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_personas.py`:

```python
"""PersonaPrompt ABC contract + Buffett implementation as the first
concrete persona. Subsequent personas added in Task 2."""

from __future__ import annotations

import pytest

from src.research.personas import PERSONA_REGISTRY
from src.research.personas.base import PersonaPrompt
from src.research.personas.buffett import BuffettPrompt


class TestPersonaABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            PersonaPrompt()  # type: ignore[abstract]

    def test_concrete_persona_has_name_and_description(self):
        p = BuffettPrompt()
        assert p.name == "buffett"
        assert isinstance(p.description, str) and len(p.description) > 10

    def test_concrete_persona_emits_system_addition(self):
        p = BuffettPrompt()
        sys_add = p.system_addition()
        assert isinstance(sys_add, str)
        # Should reference Buffett-flavored language
        lower = sys_add.lower()
        assert any(kw in lower for kw in ("moat", "owner earnings", "margin of safety"))

    def test_concrete_persona_emits_module_lens(self):
        p = BuffettPrompt()
        # When asked about fundamentals, returns a module-specific lens
        lens = p.module_lens("fundamentals")
        assert isinstance(lens, str)
        # Unknown module returns empty string (no specialization)
        assert p.module_lens("nonexistent_module") == ""


class TestPersonaRegistry:
    def test_buffett_registered(self):
        assert "buffett" in PERSONA_REGISTRY
        assert isinstance(PERSONA_REGISTRY["buffett"], BuffettPrompt)

    def test_registry_keys_match_persona_name(self):
        """Each registered key must match the persona's .name attribute."""
        for key, persona in PERSONA_REGISTRY.items():
            assert key == persona.name, f"Registry key {key} != persona.name {persona.name}"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_personas.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the ABC + Buffett + registry**

Write `src/research/personas/base.py`:

```python
"""Base class for investor persona prompt fragments.

A persona is a reusable analytical lens that any persona-capable module
(fundamentals, valuation, risk_position) can prepend to its LLM prompt
to shift the analytical voice from objective to character-driven.

Each persona ships:
  * ``name`` — stable identifier (lowercase, no spaces). The router
    emits this string in its assignments JSON.
  * ``description`` — one-line summary for the CLI / report footer.
  * ``system_addition()`` — prompt fragment prepended to the LLM system
    role. Establishes the persona's framework and voice.
  * ``module_lens(module_name)`` — optional per-module specialization
    (e.g., Buffett's "owner earnings" angle for valuation vs his
    "moat strength" angle for fundamentals). Returns empty string when
    the persona has no module-specific guidance.

Refusal / abstain logic does NOT live on the persona. The router
decides who engages based on the ticker profile; modules blindly apply
whatever persona the router picked. Single source of truth.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class PersonaPrompt(ABC):
    """Abstract base for an investor persona prompt fragment."""

    name: str = "base"
    description: str = "abstract persona"

    @abstractmethod
    def system_addition(self) -> str:
        """Persona's analytical framework + voice as a prompt fragment.

        Prepended to the LLM's system role by persona-capable modules.
        Should be 3-6 sentences. Cite the persona's signature techniques.
        """
        ...

    def module_lens(self, module_name: str) -> str:
        """Optional per-module specialization. Default: no specialization."""
        return ""
```

Write `src/research/personas/buffett.py`:

```python
"""Warren Buffett persona — quality compounders with durable moats."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class BuffettPrompt(PersonaPrompt):
    name = "buffett"
    description = (
        "Quality compounders with durable economic moats, conservative "
        "balance sheets, and owner earnings well above reported EPS."
    )

    def system_addition(self) -> str:
        return (
            "You are Warren Buffett. Your framework: invest only in businesses "
            "with durable competitive moats (brand, network effect, switching "
            "costs, low-cost producer), run by capable and honest management, "
            "at prices that leave a meaningful margin of safety against your "
            "intrinsic-value estimate based on owner earnings. You measure "
            "quality by long-term ROIC and the predictability of free cash "
            "flow ten years out. You ignore quarterly noise and macro forecasts."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "fundamentals":
            return (
                "Emphasize moat durability, ROIC, FCF margin stability, and "
                "management's capital-allocation track record. Discount any "
                "revenue growth that doesn't translate to free cash flow."
            )
        if module_name == "valuation":
            return (
                "Anchor on owner earnings (net income + D&A − maintenance "
                "capex) divided by a conservative cap rate. Reject any "
                "valuation that requires above-trend growth to justify the "
                "current price. Margin of safety = at least 30% below your "
                "intrinsic value estimate."
            )
        return ""
```

Write `src/research/personas/__init__.py`:

```python
"""Investor persona prompt fragments for persona-capable modules.

The PERSONA_REGISTRY is keyed by persona.name. The persona-router
(src/research/router.py) emits assignment names from this set; modules
look them up here to get the prompt fragment.

Phase 2 ships 8 personas. The registry is intentionally hand-maintained
(not auto-discovered) so the router's output set stays explicit and
easy to validate.
"""

from src.research.personas.base import PersonaPrompt
from src.research.personas.buffett import BuffettPrompt

PERSONA_REGISTRY: dict[str, PersonaPrompt] = {
    "buffett": BuffettPrompt(),
}

__all__ = ["PERSONA_REGISTRY", "PersonaPrompt", "BuffettPrompt"]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_personas.py -v
```
Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/personas/__init__.py src/research/personas/base.py src/research/personas/buffett.py tests/research/test_personas.py
git commit -m "feat(research): PersonaPrompt ABC + Buffett + registry scaffold

Phase 2 foundation. PersonaPrompt ABC exposes name, description,
system_addition(), and optional module_lens(module_name) for per-
module specialization. Buffett ships first as the canonical example;
remaining 7 personas land in Task 2. PERSONA_REGISTRY is hand-
maintained (not auto-discovered) so the router's output domain stays
explicit.

Refusal logic lives on the router, not the persona — single source
of truth for who-engages-when.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: Add 7 more personas

**Files:**
- Create: `src/research/personas/munger.py`
- Create: `src/research/personas/graham.py`
- Create: `src/research/personas/fisher.py`
- Create: `src/research/personas/lynch.py`
- Create: `src/research/personas/wood.py`
- Create: `src/research/personas/burry.py`
- Create: `src/research/personas/druckenmiller.py`
- Modify: `src/research/personas/__init__.py` (register all 7)
- Modify: `tests/research/test_personas.py` (add coverage)

- [ ] **Step 1: Extend the test**

Append to `tests/research/test_personas.py`:

```python
import pytest

from src.research.personas.burry import BurryPrompt
from src.research.personas.druckenmiller import DruckenmillerPrompt
from src.research.personas.fisher import FisherPrompt
from src.research.personas.graham import GrahamPrompt
from src.research.personas.lynch import LynchPrompt
from src.research.personas.munger import MungerPrompt
from src.research.personas.wood import WoodPrompt


_ALL_PERSONAS = [
    ("buffett", BuffettPrompt),
    ("munger", MungerPrompt),
    ("graham", GrahamPrompt),
    ("fisher", FisherPrompt),
    ("lynch", LynchPrompt),
    ("wood", WoodPrompt),
    ("burry", BurryPrompt),
    ("druckenmiller", DruckenmillerPrompt),
]


@pytest.mark.parametrize("name,cls", _ALL_PERSONAS, ids=[n for n, _ in _ALL_PERSONAS])
def test_each_persona_basics(name, cls):
    p = cls()
    assert p.name == name
    assert isinstance(p.description, str) and len(p.description) > 10
    sys_add = p.system_addition()
    assert isinstance(sys_add, str)
    assert len(sys_add) > 100   # at least a few sentences


def test_registry_has_all_eight():
    expected = {n for n, _ in _ALL_PERSONAS}
    assert set(PERSONA_REGISTRY.keys()) == expected


def test_personas_signature_keywords():
    """Spot-check each persona references its signature analytical concepts.
    Catches accidental prompt swaps."""
    expectations = {
        "munger":        ["roic", "capital", "predictable"],
        "graham":        ["net-net", "graham number", "margin of safety"],
        "fisher":        ["scuttlebutt", "r&d", "long-term"],
        "lynch":         ["garp", "peg", "categor"],   # six-category framework
        "wood":          ["disruptive", "innovation", "exponential"],
        "burry":         ["fcf yield", "deep value", "contrarian"],
        "druckenmiller": ["macro", "asymmetric", "concentrated"],
    }
    for name, keywords in expectations.items():
        prompt = PERSONA_REGISTRY[name].system_addition().lower()
        for kw in keywords:
            assert kw in prompt, f"{name} prompt missing '{kw}'"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_personas.py -v
```
Expected: ModuleNotFoundError for the 7 new persona modules.

- [ ] **Step 3: Implement the 7 personas**

Write `src/research/personas/munger.py`:

```python
"""Charlie Munger persona — quality of business above all."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class MungerPrompt(PersonaPrompt):
    name = "munger"
    description = (
        "Quality of business above price: high ROIC, predictable cash "
        "flows, capable capital allocation, businesses you can understand "
        "in 30 seconds."
    )

    def system_addition(self) -> str:
        return (
            "You are Charlie Munger. Your framework: a great business at a "
            "fair price beats a fair business at a great price. You demand "
            "high ROIC, predictable economics, and capital allocators who "
            "have demonstrably grown per-share intrinsic value over a decade. "
            "You use multi-disciplinary mental models — economics, "
            "psychology, history — to spot durable competitive advantages "
            "and avoid stupidity. If you can't explain the business to a "
            "smart 12-year-old in 30 seconds, it's not in your circle of "
            "competence."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "fundamentals":
            return (
                "Lead with ROIC. Anything below 15% is suspect unless the "
                "business has overwhelming structural advantages. Probe "
                "capital allocation: buybacks at sensible prices, no "
                "diworsification, dividend discipline aligned with "
                "reinvestment opportunities."
            )
        if module_name == "valuation":
            return (
                "Don't try to be precise. Decide whether the business is "
                "obviously cheap, obviously expensive, or in the murky "
                "middle. If murky, pass. Demand high quality first, then "
                "let valuation be the gating filter."
            )
        return ""
```

Write `src/research/personas/graham.py`:

```python
"""Benjamin Graham persona — quantitative deep value."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class GrahamPrompt(PersonaPrompt):
    name = "graham"
    description = (
        "Quantitative deep value: Net-Net working capital, Graham number, "
        "conservative balance sheet, multi-year dividend record."
    )

    def system_addition(self) -> str:
        return (
            "You are Benjamin Graham. Your framework is quantitative deep "
            "value with a wide margin of safety. Prefer companies trading "
            "below net-net working capital (current assets minus all "
            "liabilities), or where the Graham number (sqrt(22.5 * EPS * "
            "Book Value per share)) exceeds price by at least 50%. Demand "
            "a long, unbroken dividend record and a balance sheet you would "
            "lend the company money against. Treat Mr. Market as a manic "
            "depressive who occasionally offers irrational prices."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "valuation":
            return (
                "Compute the Graham number and a clean Net-Net working "
                "capital figure. Quote both alongside the current price. "
                "Reject any valuation that requires future growth — pay "
                "only for what's on the balance sheet today."
            )
        if module_name == "fundamentals":
            return (
                "Anchor on tangible book value, current ratio above 2, "
                "long-term debt below working capital, and ten years of "
                "uninterrupted earnings."
            )
        return ""
```

Write `src/research/personas/fisher.py`:

```python
"""Phil Fisher persona — long-term growth quality + scuttlebutt research."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class FisherPrompt(PersonaPrompt):
    name = "fisher"
    description = (
        "Long-term growth quality with deep qualitative research on "
        "management, R&D pipeline, and sales organization."
    )

    def system_addition(self) -> str:
        return (
            "You are Phil Fisher. Your framework is long-term growth quality "
            "verified by deep qualitative scuttlebutt — talking to customers, "
            "competitors, suppliers, and former employees. You look for "
            "companies with above-average R&D intensity that translates into "
            "products with long runways. You value management depth, sales "
            "force effectiveness, and a culture that rewards initiative. "
            "Pay a fair price for an excellent growth company and hold for "
            "many years; avoid heavy dividends that signal management ran "
            "out of internal reinvestment opportunities."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "fundamentals":
            return (
                "Emphasize R&D as a share of revenue, gross-margin trend "
                "(rising = pricing power from product superiority), and any "
                "evidence of recurring product success cycles. Probe whether "
                "the management bench extends three levels deep."
            )
        return ""
```

Write `src/research/personas/lynch.py`:

```python
"""Peter Lynch persona — GARP with the six-category framework."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class LynchPrompt(PersonaPrompt):
    name = "lynch"
    description = (
        "Growth at a Reasonable Price with the six-category framework "
        "(slow growers, stalwarts, cyclicals, fast growers, turnarounds, "
        "asset plays)."
    )

    def system_addition(self) -> str:
        return (
            "You are Peter Lynch. Your framework is GARP (growth at a "
            "reasonable price). Classify every company into one of six "
            "categories before analyzing — slow grower, stalwart, cyclical, "
            "fast grower, turnaround, or asset play — because the right "
            "questions differ. Anchor on the PEG ratio (P/E divided by "
            "earnings growth %); below 1 is interesting, below 0.5 is rare. "
            "Invest in what you know — if you can't describe the business in "
            "two sentences to your spouse, skip it."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "valuation":
            return (
                "Compute PEG explicitly. Note which of the six categories "
                "this company is in — fast growers warrant different "
                "valuation tolerance than stalwarts. For cyclicals, ignore "
                "trailing P/E and use mid-cycle earnings power."
            )
        if module_name == "fundamentals":
            return (
                "Classify the category first. Then anchor on metrics "
                "relevant to that category: same-store-sales for retail "
                "stalwarts, earnings reacceleration for turnarounds, "
                "hidden book value for asset plays."
            )
        return ""
```

Write `src/research/personas/wood.py`:

```python
"""Cathie Wood persona — disruptive innovation with exponential growth models."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class WoodPrompt(PersonaPrompt):
    name = "wood"
    description = (
        "Disruptive innovation in large TAMs, modeled with 5-year "
        "exponential growth curves and high R&D intensity."
    )

    def system_addition(self) -> str:
        return (
            "You are Cathie Wood. Your framework is investing in disruptive "
            "innovation — genomics, AI, robotics, blockchain, energy "
            "transition — where exponential cost-decline curves (Wright's "
            "Law) unlock massive new TAMs. Model with 5-year horizons; "
            "expect volatility and concentration. Tolerate near-term losses "
            "if R&D intensity (R&D / revenue > 10%) is funding a credible "
            "exponential trajectory. Avoid mature dividend-paying value "
            "stocks — they live in the wrong half of the disruption curve."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "valuation":
            return (
                "Build a 5-year exponential revenue model. Probability-"
                "weight your bull case (50% CAGR target) against base "
                "(30%) and bear (10% or insolvency). Use enterprise "
                "value / 2030E revenue rather than trailing multiples."
            )
        return ""
```

Write `src/research/personas/burry.py`:

```python
"""Michael Burry persona — deep value with FCF yield and contrarian setups."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class BurryPrompt(PersonaPrompt):
    name = "burry"
    description = (
        "Deep value with FCF yield >= 15%, contrarian setups, and "
        "balance-sheet-anchored downside protection."
    )

    def system_addition(self) -> str:
        return (
            "You are Michael Burry. Your framework is deep value with a "
            "contrarian bias. Anchor on FCF yield — 15% or higher is the "
            "starting point — and EV/EBIT below 8. Demand a balance sheet "
            "you can stress-test against revenue declines and rate shocks. "
            "Look for setups the market hates: out-of-favor industries, "
            "post-bankruptcy survivors, hidden assets. Position size scales "
            "with conviction; cut losers fast when the thesis breaks."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "valuation":
            return (
                "Lead with FCF yield (free cash flow / enterprise value). "
                "Compute EV/EBIT and tangible book per share. Stress-test "
                "the bear case: what is this worth if revenue drops 30%?"
            )
        if module_name == "risk_position":
            return (
                "Position size aggressively when the FCF-yield/quality "
                "ratio is exceptional, but predefine the exit: thesis-"
                "break signals beat technical stops. No averaging down "
                "into a deteriorating fundamental story."
            )
        return ""
```

Write `src/research/personas/druckenmiller.py`:

```python
"""Stanley Druckenmiller persona — macro-first asymmetric concentrated bets."""

from __future__ import annotations

from src.research.personas.base import PersonaPrompt


class DruckenmillerPrompt(PersonaPrompt):
    name = "druckenmiller"
    description = (
        "Macro-first with asymmetric risk:reward, concentrated bets, "
        "momentum overlay, and capital-preservation discipline."
    )

    def system_addition(self) -> str:
        return (
            "You are Stanley Druckenmiller. Your framework is macro-first: "
            "Fed policy, liquidity, rates, and currency regime determine "
            "which sectors and styles work right now. Make concentrated, "
            "asymmetric bets where downside is bounded and upside is "
            "multi-bagger. Use price momentum as confirmation, not as "
            "primary signal. Above all, preserve capital — get out fast "
            "when the macro regime turns against you, even if it costs "
            "you to be wrong twice in a row."
        )

    def module_lens(self, module_name: str) -> str:
        if module_name == "risk_position":
            return (
                "Tie position size to macro conviction AND asymmetry. Stop "
                "should be tight (driven by regime-change risk, not "
                "volatility-band noise). Target should be 3-5x the stop "
                "distance — concentrated bets demand asymmetric payoffs."
            )
        return ""
```

Modify `src/research/personas/__init__.py` to register all 8:

```python
"""Investor persona prompt fragments for persona-capable modules.

The PERSONA_REGISTRY is keyed by persona.name. The persona-router
(src/research/router.py) emits assignment names from this set; modules
look them up here to get the prompt fragment.

Phase 2 ships 8 personas. The registry is intentionally hand-maintained
(not auto-discovered) so the router's output set stays explicit and
easy to validate.
"""

from src.research.personas.base import PersonaPrompt
from src.research.personas.buffett import BuffettPrompt
from src.research.personas.burry import BurryPrompt
from src.research.personas.druckenmiller import DruckenmillerPrompt
from src.research.personas.fisher import FisherPrompt
from src.research.personas.graham import GrahamPrompt
from src.research.personas.lynch import LynchPrompt
from src.research.personas.munger import MungerPrompt
from src.research.personas.wood import WoodPrompt

PERSONA_REGISTRY: dict[str, PersonaPrompt] = {
    "buffett":       BuffettPrompt(),
    "munger":        MungerPrompt(),
    "graham":        GrahamPrompt(),
    "fisher":        FisherPrompt(),
    "lynch":         LynchPrompt(),
    "wood":          WoodPrompt(),
    "burry":         BurryPrompt(),
    "druckenmiller": DruckenmillerPrompt(),
}

__all__ = [
    "PERSONA_REGISTRY", "PersonaPrompt",
    "BuffettPrompt", "BurryPrompt", "DruckenmillerPrompt",
    "FisherPrompt", "GrahamPrompt", "LynchPrompt",
    "MungerPrompt", "WoodPrompt",
]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_personas.py -v
```
Expected: ~15 tests pass (5 from Task 1 + 8 parametrized + registry-count + signature-keywords).

- [ ] **Step 5: Commit**

```bash
git add src/research/personas/ tests/research/test_personas.py
git commit -m "feat(research): 7 more investor personas (full Phase 2 set)

Munger (ROIC + predictability), Graham (Net-Net + Graham number),
Fisher (scuttlebutt + R&D), Lynch (GARP + six-category framework),
Wood (disruptive innovation), Burry (FCF yield + contrarian),
Druckenmiller (macro-first asymmetric bets). Each ships system_addition()
plus optional module_lens for the modules where the persona has a
sharper specialization.

PERSONA_REGISTRY now has all 8 entries the router can emit.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: persona-router LLM agent

**Files:**
- Create: `src/research/router.py`
- Create: `tests/research/test_router.py`

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_router.py`:

```python
"""persona-router: one LLM call returns {module_name: persona_name | list | None}
based on ticker profile + scanner_context."""

from __future__ import annotations

from unittest.mock import patch

from src.research.router import route_personas, _RouterOutput
from src.research.shared_data import SharedData
from src.research.models import ResearchRequest


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=True,
        scanner_context={"triggered_detectors": ["earnings_event"]},
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[],
        company_facts={"sector": "Technology", "market_cap": 3.0e12,
                       "weighted_average_shares": 24e9},
        sector_etf_prices=[], spy_prices=[],
    )


class TestRoutePersonas:
    @patch("src.research.router.call_research_llm")
    def test_returns_assignments_dict(self, mock_llm):
        mock_llm.return_value = _RouterOutput(
            fundamentals="munger",
            valuation="wood",
            risk_position="druckenmiller",
            debate=["wood", "burry"],
            rationale="Tech growth name; valuation tension between innovation premium and FCF reality.",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["fundamentals"] == "munger"
        assert assignments["valuation"] == "wood"
        assert assignments["risk_position"] == "druckenmiller"
        assert assignments["debate"] == ["wood", "burry"]

    @patch("src.research.router.call_research_llm")
    def test_invalid_persona_coerced_to_none(self, mock_llm):
        """Router LLM may hallucinate a persona name. Validator coerces
        unknown names to None for that module."""
        mock_llm.return_value = _RouterOutput(
            fundamentals="hallucinated",  # not in PERSONA_REGISTRY
            valuation="buffett",
            risk_position=None,
            debate=[],
            rationale="x",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["fundamentals"] is None
        assert assignments["valuation"] == "buffett"
        assert assignments["risk_position"] is None
        assert assignments["debate"] == []

    @patch("src.research.router.call_research_llm")
    def test_debate_requires_exactly_two(self, mock_llm):
        """Debate slot only fires with exactly 2 personas; 1 or 3+ → empty."""
        mock_llm.return_value = _RouterOutput(
            fundamentals=None, valuation=None, risk_position=None,
            debate=["buffett"],  # only 1 → reject
            rationale="x",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["debate"] == []

    @patch("src.research.router.call_research_llm")
    def test_debate_personas_must_be_valid(self, mock_llm):
        """Both debate personas must be in registry; any invalid → empty."""
        mock_llm.return_value = _RouterOutput(
            fundamentals=None, valuation=None, risk_position=None,
            debate=["wood", "hallucinated"],
            rationale="x",
        )
        assignments = route_personas(_req(), _shared())
        assert assignments["debate"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_router.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement**

Write `src/research/router.py`:

```python
"""Persona-router — one LLM call decides which investor persona
analyzes each module on this ticker.

Input:
  * ResearchRequest (ticker, holding_status, etc.)
  * SharedData (ticker profile: sector, market_cap, revenue_growth, etc.)

Output:
  dict mapping module name → persona name (str), list of two personas
  (list[str], for debate), or None (objective).

Invalid persona names returned by the LLM are coerced to None for that
module. The debate slot is dropped to [] unless it contains exactly two
valid persona names.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ResearchRequest
from src.research.personas import PERSONA_REGISTRY
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _RouterOutput(BaseModel):
    """LLM output: per-module persona assignments + a rationale string."""

    fundamentals: str | None = Field(
        default=None,
        description="Persona for the fundamentals module, or null for objective.",
    )
    valuation: str | None = Field(
        default=None,
        description="Persona for the valuation module, or null for objective.",
    )
    risk_position: str | None = Field(
        default=None,
        description="Persona for the risk_position module, or null for objective.",
    )
    debate: list[str] = Field(
        default_factory=list,
        description=(
            "Either an empty list (no debate) or EXACTLY two persona names "
            "for a two-round debate panel. Three or more is invalid."
        ),
    )
    rationale: str = Field(
        description="1-2 sentence explanation of the assignment choices."
    )


def _ticker_profile(shared: SharedData) -> dict:
    """Distill SharedData into the compact profile the router LLM needs."""
    facts = shared.company_facts or {}
    revenue_growth = 0.0
    profitable = False
    if shared.financials:
        latest = shared.financials[0]
        revenue_growth = float(getattr(latest, "revenue_growth", 0) or 0)
        # Net income > 0 from earnings_history if available, else null
    return {
        "ticker": shared.ticker,
        "sector": facts.get("sector") or facts.get("industry") or "Unknown",
        "market_cap": float(facts.get("market_cap") or 0),
        "revenue_growth": revenue_growth,
        "profitable": profitable,
    }


def route_personas(
    request: ResearchRequest,
    shared: SharedData,
) -> dict[str, str | list[str] | None]:
    """Run the router LLM and return validated per-module assignments.

    Persona names not in PERSONA_REGISTRY are coerced to None.
    Debate list is dropped to [] unless it contains exactly two valid names.
    """
    profile = _ticker_profile(shared)
    triggered = []
    if request.scanner_context:
        triggered = request.scanner_context.get("triggered_detectors") or []

    available = sorted(PERSONA_REGISTRY.keys())
    persona_descriptions = "\n".join(
        f"  * {name}: {PERSONA_REGISTRY[name].description}"
        for name in available
    )

    prompt = (
        f"You are routing investor personas to analytical modules for "
        f"ticker {profile['ticker']}.\n\n"
        f"Ticker profile:\n"
        f"  Sector: {profile['sector']}\n"
        f"  Market cap: ${profile['market_cap'] / 1e9:.1f}B\n"
        f"  Revenue growth (YoY): {profile['revenue_growth'] * 100:+.1f}%\n"
        f"  Scanner triggers: {triggered or 'none'}\n\n"
        f"Available personas:\n{persona_descriptions}\n\n"
        f"Assign a persona to each of: fundamentals, valuation, risk_position.\n"
        f"Use null for any module where no persona is a strong fit (the "
        f"module then runs objective).\n\n"
        f"Optionally pick EXACTLY two personas for a debate slot when their "
        f"frameworks would genuinely disagree on this ticker (e.g., a tech "
        f"growth name might warrant Wood vs Burry). If no two-persona "
        f"debate is justified, return an empty debate list.\n\n"
        f"Also return a 1-2 sentence rationale explaining your choices."
    )

    out = call_research_llm(
        prompt, _RouterOutput,
        default_factory=lambda: _RouterOutput(
            fundamentals=None, valuation=None, risk_position=None,
            debate=[], rationale="Router LLM failed; defaulting to objective.",
        ),
    )

    def _valid(name: str | None) -> str | None:
        if name is None:
            return None
        if name in PERSONA_REGISTRY:
            return name
        logger.warning("Router emitted unknown persona %r; coercing to None", name)
        return None

    debate_valid: list[str] = []
    if (isinstance(out.debate, list) and len(out.debate) == 2
            and all(p in PERSONA_REGISTRY for p in out.debate)):
        debate_valid = list(out.debate)
    elif out.debate:
        logger.warning(
            "Router emitted debate=%r; require exactly 2 valid personas, dropping",
            out.debate,
        )

    return {
        "fundamentals":  _valid(out.fundamentals),
        "valuation":     _valid(out.valuation),
        "risk_position": _valid(out.risk_position),
        "debate":        debate_valid,
        "_rationale":    out.rationale,  # surfaced in report footer
    }
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_router.py -v
```
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/router.py tests/research/test_router.py
git commit -m "feat(research): persona-router LLM agent

One LLM call returns per-module persona assignments. Validation layer
coerces unknown persona names to None and drops debate slot unless it
contains exactly two registry-valid names. Rationale string surfaces
in report footer.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Refactor fundamentals module to use persona

**Files:**
- Modify: `src/research/modules/fundamentals.py`
- Modify: `tests/research/test_module_fundamentals.py`

- [ ] **Step 1: Extend the test**

Append to `tests/research/test_module_fundamentals.py`:

```python
class TestFundamentalsPersonaPath:
    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_buffett_persona_recorded(self, mock_llm):
        from src.research.modules.fundamentals import _FundamentalsNarrative
        mock_llm.return_value = _FundamentalsNarrative(
            narrative="Quality moat per Buffett lens.",
        )
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        out = FundamentalsModule().run(_req(), "buffett", shared)
        assert out.persona_used == "buffett"

    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_buffett_prompt_includes_persona_voice(self, mock_llm):
        from src.research.modules.fundamentals import _FundamentalsNarrative
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _FundamentalsNarrative(narrative="ok")
        mock_llm.side_effect = _capture
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        FundamentalsModule().run(_req(), "buffett", shared)
        # Persona system prompt should reference Buffett's voice
        prompt_text = captured["prompt"].lower()
        assert any(kw in prompt_text for kw in ("buffett", "moat", "owner earnings"))

    @patch("src.research.modules.fundamentals.call_research_llm")
    def test_unsupported_persona_coerced_to_none(self, mock_llm):
        """Router could pick a persona not in this module's supports_personas;
        _coerce_persona returns None and the module runs objective."""
        from src.research.modules.fundamentals import _FundamentalsNarrative
        mock_llm.return_value = _FundamentalsNarrative(narrative="objective.")
        shared = SharedData(
            ticker="NVDA", scan_date="2026-05-22",
            prices=[], financials=_fundamentals(),
            insider_trades=[], news=[], analyst_actions=[],
            analyst_targets=None, earnings_history=[],
            company_facts={}, sector_etf_prices=[], spy_prices=[],
        )
        # Wood is NOT in fundamentals.supports_personas
        out = FundamentalsModule().run(_req(), "wood", shared)
        assert out.persona_used is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_fundamentals.py -v
```
Expected: new tests fail (persona prompt not yet injected).

- [ ] **Step 3: Modify fundamentals.py**

Read `src/research/modules/fundamentals.py`. Make these edits:

1. Change the class attribute `supports_personas: list[str] = []` to:
```python
    supports_personas: list[str] = ["buffett", "munger", "fisher"]
```

2. Update the `run()` method to use the persona. Find the existing prompt construction (the `prompt = (f"Company fundamentals ..."` block) and prepend a persona system fragment when `persona is not None`.

Replace the `run()` body's prompt+call section so it becomes:

```python
        persona_obj = None
        if persona is not None:
            from src.research.personas import PERSONA_REGISTRY
            persona_obj = PERSONA_REGISTRY.get(persona)

        objective_prompt = (
            f"Company fundamentals for {request.ticker} "
            f"(latest period: {_safe(lambda: latest.report_period, 'recent')}):\n"
            f"  Revenue growth (YoY): {metrics['revenue_growth'] * 100:+.1f}%\n"
            f"  Gross margin: {metrics['gross_margin'] * 100:.1f}%\n"
            f"  Operating margin: {metrics['operating_margin'] * 100:.1f}%\n"
            f"  Net margin: {metrics['net_margin'] * 100:.1f}%\n"
            f"  ROIC: {metrics['roic'] * 100:.1f}%\n"
            f"  FCF margin: {metrics['fcf_margin'] * 100:.1f}%\n"
            f"  Debt/Equity: {metrics['debt_to_equity']:.2f}\n"
            f"\nWrite 3-5 sentences objectively describing the company's\n"
            f"profitability, capital efficiency, and apparent moat strength.\n"
            f"Anchor every claim on a number above. Do not predict price."
        )

        if persona_obj is not None:
            prompt = (
                persona_obj.system_addition()
                + "\n\n"
                + persona_obj.module_lens(self.name)
                + "\n\n"
                + objective_prompt
            )
        else:
            prompt = objective_prompt

        narrative = call_research_llm(
            prompt, _FundamentalsNarrative,
            default_factory=lambda: _FundamentalsNarrative(
                narrative=(
                    f"Revenue growth {metrics['revenue_growth'] * 100:+.1f}%, "
                    f"net margin {metrics['net_margin'] * 100:.1f}%, "
                    f"ROIC {metrics['roic'] * 100:.1f}%."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=persona,
            markdown=narrative.markdown if hasattr(narrative, "markdown") else narrative.narrative,
            key_metrics=metrics,
        )
```

(The last line preserves backward compat — `narrative.narrative` is the existing pydantic field.)

Wait — the pydantic model is `_FundamentalsNarrative` with field `narrative: str`. So `narrative.narrative` is correct. Remove the `hasattr` defensive fallback — it's confusing. Use:

```python
        return ModuleResult(
            module_name=self.name, persona_used=persona,
            markdown=narrative.narrative,
            key_metrics=metrics,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_fundamentals.py -v
```
Expected: original 3 tests + 3 new persona tests = 6 pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/fundamentals.py tests/research/test_module_fundamentals.py
git commit -m "feat(research): fundamentals module uses persona param

supports_personas now lists buffett/munger/fisher. When persona is set
and valid (passes _coerce_persona), the module prepends the persona's
system_addition + module_lens to the objective prompt. ModuleResult
records persona_used so the synthesizer and HTML report can surface it.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Refactor valuation module to use persona

**Files:**
- Modify: `src/research/modules/valuation.py`
- Modify: `tests/research/test_module_valuation.py`

- [ ] **Step 1: Extend the test**

Append to `tests/research/test_module_valuation.py`:

```python
class TestValuationPersonaPath:
    @patch("src.research.modules.valuation.call_research_llm")
    def test_graham_persona_records_and_prepends(self, mock_llm):
        from src.research.modules.valuation import _ValuationNarrative
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _ValuationNarrative(narrative="Graham number says cheap.")
        mock_llm.side_effect = _capture
        out = ValuationModule().run(_req(), "graham", _shared())
        assert out.persona_used == "graham"
        assert any(kw in captured["prompt"].lower()
                   for kw in ("graham", "net-net", "margin of safety"))

    @patch("src.research.modules.valuation.call_research_llm")
    def test_unsupported_persona_coerced_to_none(self, mock_llm):
        from src.research.modules.valuation import _ValuationNarrative
        mock_llm.return_value = _ValuationNarrative(narrative="objective.")
        # Lynch is NOT in valuation.supports_personas
        out = ValuationModule().run(_req(), "lynch", _shared())
        assert out.persona_used is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_valuation.py -v
```

- [ ] **Step 3: Modify valuation.py**

Read `src/research/modules/valuation.py`. Apply the same pattern as Task 4:

1. Change `supports_personas: list[str] = []` to:
```python
    supports_personas: list[str] = ["buffett", "graham", "munger", "fisher"]
```

2. Wrap the existing `prompt = (f"Valuation snapshot for {request.ticker}..."` construction with persona prepending. After the existing prompt is built, replace the `narrative = call_research_llm(...)` block with:

```python
        objective_prompt = prompt  # capture the just-built prompt
        if persona is not None:
            from src.research.personas import PERSONA_REGISTRY
            persona_obj = PERSONA_REGISTRY.get(persona)
            if persona_obj is not None:
                objective_prompt = (
                    persona_obj.system_addition()
                    + "\n\n"
                    + persona_obj.module_lens(self.name)
                    + "\n\n"
                    + prompt
                )

        narrative = call_research_llm(
            objective_prompt, _ValuationNarrative,
            default_factory=lambda: _ValuationNarrative(
                narrative=(
                    f"Price ${price:.2f}; fair value range "
                    f"${rng[0]:.2f}-${rng[1]:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=persona,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_valuation.py -v
```
Expected: original 4 tests + 2 new persona tests = 6 pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/valuation.py tests/research/test_module_valuation.py
git commit -m "feat(research): valuation module uses persona param

supports_personas now lists buffett/graham/munger/fisher. Persona
system_addition + module_lens prepended to the objective valuation
prompt when set. ModuleResult records persona_used.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Refactor risk_position module to use persona

**Files:**
- Modify: `src/research/modules/risk_position.py`
- Modify: `tests/research/test_module_risk_position.py`

- [ ] **Step 1: Extend the test**

Append to `tests/research/test_module_risk_position.py`:

```python
class TestRiskPositionPersonaPath:
    @patch("src.research.modules.risk_position.call_research_llm")
    def test_druckenmiller_persona_recorded(self, mock_llm):
        from src.research.modules.risk_position import _RiskNarrative
        captured = {}
        def _capture(prompt, model, **kw):
            captured["prompt"] = prompt
            return _RiskNarrative(narrative="Macro-aware plan.")
        mock_llm.side_effect = _capture
        out = RiskPositionModule().run(
            _req(), "druckenmiller", _shared(), prior_results=_prior(),
        )
        assert out.persona_used == "druckenmiller"
        assert any(kw in captured["prompt"].lower()
                   for kw in ("druckenmiller", "macro", "asymmetric"))

    @patch("src.research.modules.risk_position.call_research_llm")
    def test_unsupported_persona_coerced_to_none(self, mock_llm):
        from src.research.modules.risk_position import _RiskNarrative
        mock_llm.return_value = _RiskNarrative(narrative="objective.")
        # Wood is NOT in risk_position.supports_personas
        out = RiskPositionModule().run(
            _req(), "wood", _shared(), prior_results=_prior(),
        )
        assert out.persona_used is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_risk_position.py -v
```

- [ ] **Step 3: Modify risk_position.py**

Read `src/research/modules/risk_position.py`. Apply the same pattern:

1. Change `supports_personas: list[str] = []` to:
```python
    supports_personas: list[str] = ["druckenmiller", "burry"]
```

2. Wrap the existing prompt with persona prepending. After the existing prompt is built, replace the `narrative = call_research_llm(...)` block with:

```python
        objective_prompt = prompt
        if persona is not None:
            from src.research.personas import PERSONA_REGISTRY
            persona_obj = PERSONA_REGISTRY.get(persona)
            if persona_obj is not None:
                objective_prompt = (
                    persona_obj.system_addition()
                    + "\n\n"
                    + persona_obj.module_lens(self.name)
                    + "\n\n"
                    + prompt
                )

        narrative = call_research_llm(
            objective_prompt, _RiskNarrative,
            default_factory=lambda: _RiskNarrative(
                narrative=(
                    f"Stop ${stop_price:.2f}, target ${target_price:.2f}, "
                    f"R:R {metrics['risk_reward_ratio']:.2f}."
                )
            ),
        )
        return ModuleResult(
            module_name=self.name, persona_used=persona,
            markdown=narrative.narrative, key_metrics=metrics,
        )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_risk_position.py -v
```
Expected: original 3 tests + 2 new persona tests = 5 pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/risk_position.py tests/research/test_module_risk_position.py
git commit -m "feat(research): risk_position module uses persona param

supports_personas now lists druckenmiller/burry. Persona system prompt
prepended when set; ModuleResult records persona_used.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: New debate module

**Files:**
- Create: `src/research/modules/debate.py`
- Create: `tests/research/test_module_debate.py`

The debate module is NOT an AnalysisModule subclass (different signature — it consumes persona_assignments, not just a single persona). Pipeline (Task 8) calls it directly.

- [ ] **Step 1: Write the failing test**

Write `tests/research/test_module_debate.py`:

```python
"""Debate module: simulate a two-round transcript between two router-picked
personas. Single LLM call producing the full transcript."""

from __future__ import annotations

from unittest.mock import patch

from src.research.models import ResearchRequest, ModuleResult
from src.research.modules.debate import run_debate, _DebateTranscript
from src.research.shared_data import SharedData


def _req():
    return ResearchRequest(
        ticker="NVDA", holding_status="watching",
        target_position_pct=0.05, risk_tolerance="moderate",
        report_goal="new_entry", use_personas=True, scanner_context=None,
    )


def _shared():
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[],
        news=[], analyst_actions=[], analyst_targets=None,
        earnings_history=[], company_facts={"sector": "Technology"},
        sector_etf_prices=[], spy_prices=[],
    )


class TestDebate:
    @patch("src.research.modules.debate.call_research_llm")
    def test_returns_module_result_with_transcript(self, mock_llm):
        mock_llm.return_value = _DebateTranscript(
            transcript=(
                "**Wood (Round 1):** ...\n\n"
                "**Burry (Round 1):** ...\n\n"
                "**Wood (Round 2):** ...\n\n"
                "**Burry (Round 2):** ..."
            ),
            verdict="Wood's growth thesis is more probable.",
        )
        out = run_debate(_req(), _shared(), ["wood", "burry"])
        assert isinstance(out, ModuleResult)
        assert out.module_name == "debate"
        assert "Wood" in out.markdown
        assert "Burry" in out.markdown
        assert out.skipped is False

    def test_skipped_when_not_two_personas(self):
        """Caller should ensure 2 personas — but defensive check too."""
        out = run_debate(_req(), _shared(), ["wood"])
        assert out.skipped is True

    def test_skipped_when_invalid_personas(self):
        out = run_debate(_req(), _shared(), ["wood", "hallucinated"])
        assert out.skipped is True
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_debate.py -v
```

- [ ] **Step 3: Implement**

Write `src/research/modules/debate.py`:

```python
"""Debate module — simulate a 2-round transcript between two router-picked
investor personas.

NOT an AnalysisModule subclass — the signature differs (consumes a list
of persona names, not a single persona). Pipeline calls run_debate()
directly when router.persona_assignments['debate'] has exactly 2 entries.

Phase 2 v1: single LLM call that simulates the full debate. Cheaper
than dispatching one call per persona per round. Phase 3 or later may
expand to true multi-agent dispatch if outputs disappoint.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from src.research.llm import call_research_llm
from src.research.models import ModuleResult, ResearchRequest
from src.research.personas import PERSONA_REGISTRY
from src.research.shared_data import SharedData

logger = logging.getLogger(__name__)


class _DebateTranscript(BaseModel):
    transcript: str = Field(
        description=(
            "Two-round debate transcript. Each round contains one statement "
            "from each persona. Use markdown bold for speaker labels: "
            "`**Buffett (Round 1):**`"
        )
    )
    verdict: str = Field(
        description="1-2 sentences identifying which persona made the stronger case."
    )


def run_debate(
    request: ResearchRequest,
    shared_data: SharedData,
    personas: list[str],
) -> ModuleResult:
    """Run a two-persona debate. ``personas`` must be a list of exactly
    two persona names present in PERSONA_REGISTRY. Otherwise returns a
    skipped ModuleResult."""
    if len(personas) != 2 or not all(p in PERSONA_REGISTRY for p in personas):
        return ModuleResult(
            module_name="debate", persona_used=None, markdown="",
            skipped=True,
            skip_reason=f"debate needs exactly 2 valid personas, got {personas}",
        )

    p1 = PERSONA_REGISTRY[personas[0]]
    p2 = PERSONA_REGISTRY[personas[1]]

    sector = (shared_data.company_facts or {}).get("sector", "Unknown")

    prompt = (
        f"You are simulating a two-round investment debate between two "
        f"famous investors about ticker {request.ticker} ({sector} sector).\n\n"
        f"=== Persona A: {p1.name.title()} ===\n"
        f"{p1.system_addition()}\n\n"
        f"=== Persona B: {p2.name.title()} ===\n"
        f"{p2.system_addition()}\n\n"
        f"Run the debate as follows:\n"
        f"  Round 1: {p1.name.title()} states their thesis on {request.ticker} "
        f"(2-4 sentences).\n"
        f"  Round 1: {p2.name.title()} states their thesis (2-4 sentences).\n"
        f"  Round 2: {p1.name.title()} responds to the strongest point {p2.name.title()} "
        f"made, sharpening or conceding (2-3 sentences).\n"
        f"  Round 2: {p2.name.title()} does the same against {p1.name.title()}'s thesis (2-3 sentences).\n\n"
        f"Format each statement with a markdown bold label like "
        f"`**{p1.name.title()} (Round 1):**` followed by the prose.\n\n"
        f"Finally produce a 1-2 sentence VERDICT identifying which persona made the "
        f"stronger case on this ticker AT THIS MOMENT — given the sector and "
        f"the ticker's profile. Do not split the difference; pick one."
    )

    out = call_research_llm(
        prompt, _DebateTranscript,
        default_factory=lambda: _DebateTranscript(
            transcript=(
                f"**{p1.name.title()}:** debate LLM failed.\n\n"
                f"**{p2.name.title()}:** debate LLM failed."
            ),
            verdict="Debate generation failed; no verdict.",
        ),
    )

    markdown = out.transcript + "\n\n**Verdict:** " + out.verdict
    return ModuleResult(
        module_name="debate",
        persona_used=f"{personas[0]}+{personas[1]}",
        markdown=markdown,
        key_metrics={},
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_module_debate.py -v
```
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/modules/debate.py tests/research/test_module_debate.py
git commit -m "feat(research): debate module (two-persona transcript)

Single LLM call simulates a 2-round debate between two router-picked
personas. Cheaper than per-persona-per-round dispatch; the LLM
roleplays both sides given each persona's system_addition. Returns a
ModuleResult with the full transcript + a one-line verdict in
markdown. NOT an AnalysisModule subclass (signature differs);
pipeline calls it directly when router emits debate=[a, b].

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Wire router + persona + debate into pipeline

**Files:**
- Modify: `src/research/pipeline.py`
- Modify: `tests/research/test_pipeline.py`

- [ ] **Step 1: Extend the test**

Append to `tests/research/test_pipeline.py`:

```python
class TestRunResearchPersonaPath:
    @patch("src.research.pipeline.fetch_shared_data")
    @patch("src.research.pipeline.synthesize")
    @patch("src.research.pipeline.replay_trade_plan")
    @patch("src.research.pipeline.route_personas")
    @patch("src.research.pipeline.run_debate")
    def test_use_personas_runs_router_and_debate(
        self, mock_debate, mock_router, mock_replay, mock_synth, mock_fetch,
    ):
        from src.research.pipeline import run_research
        from src.research.modules.base import AnalysisModule

        mock_fetch.return_value = _shared()
        mock_router.return_value = {
            "fundamentals": "buffett",
            "valuation": "graham",
            "risk_position": None,
            "debate": ["wood", "burry"],
            "_rationale": "tech growth tension",
        }
        mock_synth.return_value = ("# r", TradePlan(
            direction="long", entry_price=145.0, target_price=165.0,
            stop_price=138.0, horizon_days=30, sizing_pct=0.05,
            confidence=70, rationale="x",
        ))
        mock_replay.return_value = BacktestSummary(
            matches_found=0, win_rate=None, avg_pnl_pct=None,
            max_drawdown_pct=None, avg_holding_days=None,
            sample_quality="insufficient", caveat="x",
        )
        mock_debate.return_value = ModuleResult(
            module_name="debate", persona_used="wood+burry",
            markdown="debate text", key_metrics={},
        )

        class _Stub(AnalysisModule):
            name = "fundamentals"
            supports_personas = ["buffett"]
            def run(self, request, persona, shared_data):
                # Module receives the router-picked persona
                return ModuleResult(
                    module_name="fundamentals", persona_used=persona,
                    markdown="stub", key_metrics={},
                )

        req = ResearchRequest(
            ticker="NVDA", holding_status="watching",
            target_position_pct=0.05, risk_tolerance="moderate",
            report_goal="new_entry", use_personas=True,
            scanner_context=None,
        )
        with patch("src.research.pipeline.ALL_MODULES", [_Stub]):
            state = run_research(req)

        # Router was called, assignments stored
        mock_router.assert_called_once()
        assert state["persona_assignments"]["fundamentals"] == "buffett"
        assert state["persona_assignments"]["debate"] == ["wood", "burry"]
        # Module received the persona
        assert state["module_results"]["fundamentals"].persona_used == "buffett"
        # Debate ran and is in module_results
        mock_debate.assert_called_once()
        assert "debate" in state["module_results"]
        assert state["module_results"]["debate"].markdown == "debate text"

    @patch("src.research.pipeline.fetch_shared_data")
    @patch("src.research.pipeline.route_personas")
    @patch("src.research.pipeline.run_debate")
    def test_no_personas_skips_router_and_debate(
        self, mock_debate, mock_router, mock_fetch,
    ):
        """When use_personas=False, router is never called, debate never fires."""
        from src.research.pipeline import run_research
        mock_fetch.return_value = _shared()
        with patch("src.research.pipeline.ALL_MODULES", []), \
             patch("src.research.pipeline.synthesize",
                   return_value=("r", TradePlan(
                       direction="stand_aside", entry_price=None,
                       target_price=None, stop_price=None, horizon_days=0,
                       sizing_pct=0.0, confidence=0, rationale="x",
                   ))), \
             patch("src.research.pipeline.replay_trade_plan",
                   return_value=BacktestSummary(
                       matches_found=0, win_rate=None, avg_pnl_pct=None,
                       max_drawdown_pct=None, avg_holding_days=None,
                       sample_quality="insufficient", caveat="x",
                   )):
            state = run_research(_req(scanner_ctx=None))  # use_personas=False
        mock_router.assert_not_called()
        mock_debate.assert_not_called()
        assert state["persona_assignments"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_pipeline.py -v
```

- [ ] **Step 3: Modify pipeline.py**

Read `src/research/pipeline.py`. Make these changes:

1. Add imports near the top:
```python
from src.research.router import route_personas
from src.research.modules.debate import run_debate
```

2. Modify `run_research()` to:
   - Call route_personas() when use_personas=True
   - Look up per-module persona from assignments when running each module
   - Call run_debate() when assignments['debate'] has 2 personas

Full replacement of the function body (starting at `scan_date = _scan_date(request)`):

```python
    scan_date = _scan_date(request)
    shared = fetch_shared_data(request.ticker, scan_date)

    # Router (Phase 2). Only when use_personas; otherwise every module
    # runs objective and debate never fires.
    persona_assignments: dict[str, str | list[str] | None] | None = None
    if request.use_personas:
        try:
            persona_assignments = route_personas(request, shared)
        except Exception as e:
            logger.exception("router failed: %s", e)
            persona_assignments = None

    def _persona_for(module_name: str) -> str | None:
        if not persona_assignments:
            return None
        value = persona_assignments.get(module_name)
        if isinstance(value, str):
            return value
        return None

    module_results: dict[str, ModuleResult] = {}

    risk_position_module = None
    for module_cls in ALL_MODULES:
        if module_cls.__name__ == "RiskPositionModule":
            risk_position_module = module_cls
            continue
        module = module_cls()
        try:
            result = module.run(
                request,
                persona=_persona_for(module.name),
                shared_data=shared,
            )
        except Exception as e:
            logger.exception(
                "module %s raised — should not happen per ABC contract: %s",
                module.name, e,
            )
            result = ModuleResult(
                module_name=module.name, persona_used=None, markdown="",
                skipped=True, skip_reason=f"Unhandled exception: {e}",
            )
        module_results[module.name] = result

    if risk_position_module is not None:
        try:
            m = risk_position_module()
            sig = inspect.signature(m.run)
            kwargs = {}
            if "prior_results" in sig.parameters:
                kwargs["prior_results"] = module_results
            result = m.run(
                request,
                persona=_persona_for("risk_position"),
                shared_data=shared,
                **kwargs,
            )
        except Exception as e:
            logger.exception("risk_position raised: %s", e)
            result = ModuleResult(
                module_name="risk_position", persona_used=None, markdown="",
                skipped=True, skip_reason=f"Unhandled exception: {e}",
            )
        module_results["risk_position"] = result

    # Debate (Phase 2). Only when router picked exactly 2 personas.
    if persona_assignments:
        debate_personas = persona_assignments.get("debate") or []
        if isinstance(debate_personas, list) and len(debate_personas) == 2:
            try:
                debate_result = run_debate(request, shared, debate_personas)
            except Exception as e:
                logger.exception("debate raised: %s", e)
                debate_result = ModuleResult(
                    module_name="debate", persona_used=None, markdown="",
                    skipped=True, skip_reason=f"Unhandled exception: {e}",
                )
            module_results["debate"] = debate_result

    report_md, plan = synthesize(request, module_results)

    triggered: list[str] = []
    if request.scanner_context:
        triggered = list(request.scanner_context.get("triggered_detectors") or [])
    backtest = replay_trade_plan(BacktestInputs(
        ticker=request.ticker,
        triggered_detectors=triggered,
        plan=plan,
        history_csv=_history_csv_path(request.ticker),
    ))

    return ResearchState(
        request=request,
        persona_assignments=persona_assignments,
        module_results=module_results,
        report_markdown=report_md,
        strategy=plan,
        backtest_summary=backtest,
        rendered_html=None,  # Phase 3 populates
    )
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_pipeline.py -v
```
Expected: original 2 tests + 2 new persona tests = 4 pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/pipeline.py tests/research/test_pipeline.py
git commit -m "feat(research): pipeline wires router + persona + debate

When request.use_personas=True, run route_personas first; pass each
module's router-assigned persona via the persona kwarg. After all
analytical modules complete, fire run_debate when assignments['debate']
has exactly 2 valid personas. Stash final persona_assignments in
ResearchState for the CLI and (Phase 3) HTML renderer to surface.

use_personas=False short-circuits both router and debate — Phase 1
behavior preserved.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: CLI --use-personas flag + persona surfaces in summary

**Files:**
- Modify: `src/research/__main__.py`
- Modify: `tests/research/test_cli.py`

- [ ] **Step 1: Extend the test**

Append to `tests/research/test_cli.py`:

```python
class TestCLIPersonas:
    def test_use_personas_flag_sets_request_field(self, capsys):
        """--use-personas should set request.use_personas=True. Patch
        run_research to capture the request."""
        from src.research.__main__ import main
        captured = {}
        def _capture(request):
            captured["req"] = request
            return _fake_state()
        with patch("src.research.__main__.run_research", side_effect=_capture):
            main(["--ticker", "NVDA", "--use-personas"])
        assert captured["req"].use_personas is True

    def test_persona_assignments_shown_in_summary(self, capsys):
        from src.research.__main__ import main
        state = _fake_state()
        state["persona_assignments"] = {
            "fundamentals": "buffett",
            "valuation": "graham",
            "risk_position": None,
            "debate": ["wood", "burry"],
            "_rationale": "growth vs value tension",
        }
        with patch("src.research.__main__.run_research", return_value=state):
            main(["--ticker", "NVDA", "--use-personas"])
        out = capsys.readouterr().out
        assert "buffett" in out
        assert "graham" in out
        assert "debate" in out.lower() or "wood" in out.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_cli.py -v
```

- [ ] **Step 3: Modify `src/research/__main__.py`**

Read the current file. Add the `--use-personas` flag to the argparse definition. Find:

```python
    p.add_argument("--goal",
                   choices=["new_entry", "hold_review", "exit_decision",
                            "general_research"],
                   default="general_research")
    p.add_argument("-v", "--verbose", action="store_true")
```

Replace with:

```python
    p.add_argument("--goal",
                   choices=["new_entry", "hold_review", "exit_decision",
                            "general_research"],
                   default="general_research")
    p.add_argument("--use-personas", action="store_true",
                   help="Enable persona-router + persona-aware modules + "
                        "optional debate panel. Adds 1-2 LLM calls per ticker.")
    p.add_argument("-v", "--verbose", action="store_true")
```

In `main()`, change the ResearchRequest construction:

```python
    request = ResearchRequest(
        ticker=args.ticker.upper(),
        holding_status=args.holding_status,
        target_position_pct=args.position_pct,
        risk_tolerance=args.risk,
        report_goal=args.goal,
        use_personas=args.use_personas,
        scanner_context=None,
    )
```

Modify `_print_summary()` to surface persona assignments. After the existing block that prints the BACKTEST section and BEFORE the REPORT section, add:

```python
    assignments = state.get("persona_assignments")
    if assignments:
        print()
        print("-" * 72)
        print("  PERSONA ASSIGNMENTS")
        print("-" * 72)
        for module_name in ("fundamentals", "valuation", "risk_position"):
            persona = assignments.get(module_name)
            display = persona if persona else "objective"
            print(f"  {module_name:<16s}: {display}")
        debate = assignments.get("debate") or []
        if isinstance(debate, list) and len(debate) == 2:
            print(f"  {'debate':<16s}: {debate[0]} vs {debate[1]}")
        else:
            print(f"  {'debate':<16s}: (none)")
        rationale = assignments.get("_rationale")
        if rationale:
            print(f"  Rationale: {rationale}")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/test_cli.py -v
```
Expected: original 2 + 2 new = 4 pass.

- [ ] **Step 5: Commit**

```bash
git add src/research/__main__.py tests/research/test_cli.py
git commit -m "feat(research): CLI --use-personas flag + assignment summary

python -m src.research --ticker NVDA --use-personas --risk moderate
runs the router + persona-aware modules + optional debate. Summary
now prints a PERSONA ASSIGNMENTS section showing per-module persona
or 'objective', plus the debate pair if active, plus the router's
rationale string.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: End-to-end smoke + progress.md

**Files:**
- Modify: `progress.md`

- [ ] **Step 1: Run the full research suite**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest tests/research/ -v --tb=short
```
Expected: all green. Approximate count: Phase 1's 54 tests + Phase 2's additions (~25 new tests) = ~79.

Capture the final passed count.

- [ ] **Step 2: Confirm no regression in the broader suite**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m pytest -q --tb=no 2>&1 | tail -10
```
Capture pass/fail. The 20 pre-existing live-API failures from Phase 1's session should still be the only failures.

- [ ] **Step 3: Smoke a real ticker WITH personas**

```bash
PYTHONIOENCODING=utf-8 'C:/Users/Jerry/anaconda3/python.exe' -m src.research --ticker NVDA --use-personas --risk moderate --goal new_entry 2>&1 | tail -80
```

Expected within 30-90s:
- Router output visible in PERSONA ASSIGNMENTS section
- At least one module's narrative references the assigned persona
- If router picked 2 debate personas: debate transcript appears in REPORT body
- Trade plan + backtest sections same as Phase 1

If smoke can't run (DEEPSEEK_API_KEY missing, free-tier 401, etc.), capture and note. Don't fail the task.

- [ ] **Step 4: Update progress.md**

Add a new dated session block AT THE TOP of `progress.md` (after `# Progress Log`, before existing entries):

```
## Session — 2026-05-22 (Research pipeline Phase 2 landed)
```

Content should cover:
- WHAT shipped: src/research/personas/ namespace (8 investor personas + ABC + registry), src/research/router.py (LLM persona router), src/research/modules/debate.py (two-persona debate), 3 refactored modules (fundamentals, valuation, risk_position) now USE their persona param, pipeline + CLI wired for use_personas, ~25 new tests
- 10 commits, list them (use `git log --oneline <phase2-start>..HEAD` to get the SHAs)
- Smoke result
- Phase 3 (DB + API + cron + HTML email) deferred to next plan

- [ ] **Step 5: Commit**

```bash
git add progress.md
git commit -m "docs: log research pipeline Phase 2 landing

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-review

**Spec coverage** (Phase 2 subset):
- PersonaPrompt ABC + 8 persona files → Tasks 1-2 ✓
- persona-router LLM agent → Task 3 ✓
- Persona-capable modules (fundamentals/valuation/risk_position) wired → Tasks 4-6 ✓
- Debate module → Task 7 ✓
- Pipeline integration → Task 8 ✓
- CLI `--use-personas` → Task 9 ✓
- End-to-end smoke + progress → Task 10 ✓

**Spec sections deferred to Phase 3** (intentional, noted in plan header):
- DB models + Alembic migration
- API routes
- HTML template + render
- Email render
- Scheduler integration
- Frontend research request panel

**Placeholder scan**: no TBD / TODO / "add appropriate" / vague steps. Tasks 4-6 reference the existing modules and provide a specific replacement pattern (read file → apply edits → drop persona-prepend block) rather than full replacement code — acceptable because Phase 1 module code is committed and reading it gives the implementer full context.

**Type consistency**:
- `PERSONA_REGISTRY: dict[str, PersonaPrompt]` — used identically across Tasks 1-3 and modules 4-6
- `_RouterOutput` Pydantic fields (`fundamentals`, `valuation`, `risk_position`, `debate`, `rationale`) — match the dict keys returned by `route_personas` and consumed by `_persona_for` in pipeline
- `run_debate(request, shared_data, personas: list[str]) -> ModuleResult` — used identically in module file + pipeline
- `persona_obj.system_addition()` and `persona_obj.module_lens(module_name)` — same signature across all 3 module refactors
- `ResearchState.persona_assignments` — `dict | None`; populated by pipeline, read by CLI; types align

**Risks acknowledged**:
- Router LLM may hallucinate persona names — handled at validator layer in `route_personas()` (coerce unknown to None, drop bad debate slots)
- Persona-router cost: 1 LLM call/ticker when `use_personas=True`. Acceptable (~$0.001/ticker at deepseek pricing)
- Debate single-call quality: the LLM playing both sides may produce milder disagreement than a true multi-agent debate. If outputs disappoint, Phase 3+ can expand to per-persona dispatch
- Module persona prompts are long when prepended — system_addition (~150 words) + module_lens (~80 words) + objective prompt (~150 words) = ~400 words. Well under DeepSeek's context budget
- Three modules now have similar persona-prepend code blocks. Acceptable duplication for v1; could be extracted into a `_with_persona(prompt, persona, module_name)` helper if a 4th module needs it later
