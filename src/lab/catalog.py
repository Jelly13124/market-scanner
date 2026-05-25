"""Phase 6A: CATALOG of all 18 strategy blocks.

Consumed by:
  - LLM chat prompt builder (via get_llm_prompt_text())
  - Frontend SpecBlockCard renderer (via the JSON schema)
  - REST GET /lab/catalog endpoint
"""

from __future__ import annotations

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


def get_llm_prompt_text() -> str:
    """Build the catalog section of the LLM system prompt.

    Format: category-grouped, one line per block: `name (category): description`.
    Used by src/lab/chat.py to assemble the chat prompt.
    """
    by_cat: dict[str, list[str]] = {"entry": [], "exit": [], "sizing": [], "filter": []}
    for name, entry in CATALOG.items():
        by_cat[entry["category"]].append(f"  {name}: {entry['description']}")

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
        "CRITICAL: only use these exact block names. Do NOT invent new blocks.",
        "If user asks for something not covered, suggest the closest catalog block "
        "or say so explicitly.",
    ]
    return "\n".join(out)
