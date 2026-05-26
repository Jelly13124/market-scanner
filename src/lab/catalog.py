"""Phase 6A: CATALOG of all 18 strategy blocks.

Consumed by:
  - LLM chat prompt builder (via get_llm_prompt_text())
  - Frontend SpecBlockCard renderer (via the JSON schema)
  - REST GET /lab/catalog endpoint
"""

from __future__ import annotations

import typing
from typing import get_args, get_origin

from pydantic import BaseModel

from src.lab.spec.blocks_entry import (
    BollingerBreakEntry, DonchianBreakEntry, MACDEntry, MACrossEntry,
    PriceVsMAEntry, RSICrossEntry, RSIEntry, VolumeSpikeEntry,
)
from src.lab.spec.blocks_exit import (
    StopLossExit, TakeProfitExit, TimeStopExit, TrailingStopExit,
)
from src.lab.spec.blocks_filters import (
    LiquidityFilter, TrendFilter, VolatilityFilter,
)
from src.lab.spec.blocks_sizing import (
    EqualWeightSizing, FixedPctSizing, VolTargetedSizing,
)


def _entry(model, description):
    return {
        "category": "entry",
        "description": description,
        "schema": model.model_json_schema(),
    }


def _exit(model, description):
    return {
        "category": "exit",
        "description": description,
        "schema": model.model_json_schema(),
    }


def _sizing(model, description):
    return {
        "category": "sizing",
        "description": description,
        "schema": model.model_json_schema(),
    }


def _filter(model, description):
    return {
        "category": "filter",
        "description": description,
        "schema": model.model_json_schema(),
    }


CATALOG: dict[str, dict] = {
    # Entry blocks (8)
    "rsi": _entry(RSIEntry,
        "Buy when RSI(period) crosses below `level` (oversold_buy) "
        "or above `level` (overbought_short, v1 long-only treats as no-op)."),
    "rsi_cross": _entry(RSICrossEntry,
        "Buy when RSI crosses up/down through `level` (more reactive than threshold)."),
    "ma_cross": _entry(MACrossEntry,
        "Golden cross (fast SMA crosses above slow SMA) or death cross. "
        "Classic trend-following entry; ma_type=sma|ema."),
    "price_vs_ma": _entry(PriceVsMAEntry,
        "Filter or entry: close price above/below MA(period). Often used as filter."),
    "macd": _entry(MACDEntry,
        "MACD events: bullish_cross (MACD line up through signal), bearish_cross, "
        "or histogram sign flip. Captures momentum shifts."),
    "bollinger_break": _entry(BollingerBreakEntry,
        "Close outside +/- num_std x stddev of MA(period). Breakout strategy."),
    "donchian_break": _entry(DonchianBreakEntry,
        "Close above N-day high (break_up) or below N-day low (break_down). "
        "Turtle-style breakout."),
    "volume_spike": _entry(VolumeSpikeEntry,
        "Volume > multiplier x avg_period day average. Confirms conviction."),
    # Exit blocks (4)
    "stop_loss": _exit(StopLossExit,
        "Exit when loss reaches `value` (mode=pct, 0.05=5%) or "
        "`value`xATR(14) below entry (mode=atr)."),
    "take_profit": _exit(TakeProfitExit,
        "Exit when gain reaches pct (0.10 = +10%) above entry."),
    "trailing_stop": _exit(TrailingStopExit,
        "Trailing stop: exit when price drops `value` from highest-since-entry "
        "(mode=pct or atr)."),
    "time_stop": _exit(TimeStopExit,
        "Exit unconditionally after `bars` periods since entry."),
    # Sizing blocks (3)
    "fixed_pct": _sizing(FixedPctSizing,
        "Each position = pct of total equity (0.05 = 5%/position)."),
    "equal_weight": _sizing(EqualWeightSizing,
        "Split available cash across current + new positions at entry time."),
    "vol_targeted": _sizing(VolTargetedSizing,
        "Position size = target_dollar_vol / ATR(atr_period). "
        "Larger position when stock is less volatile."),
    # Filter blocks (3)
    "trend": _filter(TrendFilter,
        "Only enter when MA(ma_period) is rising or falling. Macro trend filter."),
    "volatility": _filter(VolatilityFilter,
        "Only enter when current ATR is between percentile_min and percentile_max "
        "of its trailing distribution."),
    "liquidity": _filter(LiquidityFilter,
        "Only consider tickers with at least min_daily_dollar_volume over "
        "lookback_days."),
}


_NAME_TO_MODEL: dict[str, type[BaseModel]] = {
    "rsi": RSIEntry, "rsi_cross": RSICrossEntry, "ma_cross": MACrossEntry,
    "price_vs_ma": PriceVsMAEntry, "macd": MACDEntry,
    "bollinger_break": BollingerBreakEntry, "donchian_break": DonchianBreakEntry,
    "volume_spike": VolumeSpikeEntry,
    "stop_loss": StopLossExit, "take_profit": TakeProfitExit,
    "trailing_stop": TrailingStopExit, "time_stop": TimeStopExit,
    "fixed_pct": FixedPctSizing, "equal_weight": EqualWeightSizing,
    "vol_targeted": VolTargetedSizing,
    "trend": TrendFilter, "volatility": VolatilityFilter, "liquidity": LiquidityFilter,
}


def _field_signature(model: type[BaseModel]) -> str:
    """Render a compact `field:type=default` signature for LLM consumption.

    Skips the `type` discriminator (always fixed). Inlines Literal options so
    the LLM emits the exact enum values, not paraphrased English.
    """
    parts: list[str] = []
    for fname, finfo in model.model_fields.items():
        if fname == "type":
            continue
        ann = finfo.annotation
        if get_origin(ann) is typing.Literal:
            type_str = "Literal[" + "|".join(repr(a) for a in get_args(ann)) + "]"
        elif ann is int:
            type_str = "int"
        elif ann is float:
            type_str = "float"
        elif ann is str:
            type_str = "str"
        elif ann is bool:
            type_str = "bool"
        else:
            type_str = getattr(ann, "__name__", str(ann))
        if finfo.is_required():
            parts.append(f"{fname}:{type_str} (required)")
        else:
            parts.append(f"{fname}:{type_str}={finfo.default!r}")
    return ", ".join(parts) if parts else "(no fields)"


def get_llm_prompt_text() -> str:
    """Build the catalog section of the LLM system prompt.

    Each block line: `name: description` followed by an indented `fields:` line
    listing exact field names + Literal enum values. The field signatures are
    introspected from the Pydantic models so they cannot drift from the schema.
    """
    by_cat: dict[str, list[str]] = {"entry": [], "exit": [], "sizing": [], "filter": []}
    for name, entry in CATALOG.items():
        model = _NAME_TO_MODEL[name]
        sig = _field_signature(model)
        by_cat[entry["category"]].append(
            f"  {name}: {entry['description']}\n    fields: type:Literal['{name}'], {sig}"
        )

    out = [
        "AVAILABLE STRATEGY BLOCKS (catalog v1, 18 blocks):",
        "",
        "Entry signals (pick 1-5, combine via combiner='and'/'or'):",
        *by_cat["entry"],
        "",
        "Exit signals (any one triggers close; pick 1-5):",
        *by_cat["exit"],
        "",
        "Position sizing (pick exactly 1):",
        *by_cat["sizing"],
        "",
        "Entry filters (ALL must pass; pick 0-5):",
        *by_cat["filter"],
        "",
        "CRITICAL RULES:",
        "  1. Only use the block names listed above. Do NOT invent new blocks.",
        "  2. Use the EXACT field names + Literal values shown after 'fields:'.",
        "     Do not paraphrase (e.g. for bollinger_break use direction='break_up',",
        "     NOT 'above'; for macd use trigger='bullish_cross', NOT event=...).",
        "  3. Every block MUST include 'type': '<block_name>' as its first key.",
        "  4. If user asks for something not covered, suggest the closest catalog",
        "     block or say so explicitly.",
    ]
    return "\n".join(out)
