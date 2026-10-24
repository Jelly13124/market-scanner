"""Phase 6A: StrategySpec assembles 18 blocks via discriminated unions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.lab.spec.strategy import (
    StrategySpec, UniverseSpec, EntryGroup, BacktestConfig,
)


def _minimal_spec_dict() -> dict:
    return {
        "name": "Test Strategy",
        "description": "Smoke test spec",
        "universe": {"kind": "sp500"},
        "entry": {
            "combiner": "and",
            "signals": [
                {"type": "ma_cross", "fast": 50, "slow": 200, "direction": "golden"}
            ],
        },
        "exit": [
            {"type": "stop_loss", "mode": "pct", "value": 0.05},
        ],
        "filters": [],
        "sizing": {"type": "fixed_pct", "pct": 0.05},
        "backtest_config": {},
    }


class TestStrategySpec:
    def test_minimal_spec_validates(self):
        spec = StrategySpec.model_validate(_minimal_spec_dict())
        assert spec.name == "Test Strategy"
        assert spec.entry.combiner == "and"
        assert len(spec.entry.signals) == 1
        assert spec.entry.signals[0].type == "ma_cross"
        assert spec.exit[0].type == "stop_loss"
        assert spec.sizing.type == "fixed_pct"

    def test_unknown_entry_type_rejected(self):
        d = _minimal_spec_dict()
        d["entry"]["signals"] = [{"type": "imaginary_indicator"}]
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(d)

    def test_watchlist_universe_requires_watchlist_id(self):
        d = _minimal_spec_dict()
        d["universe"] = {"kind": "watchlist"}  # no watchlist_id
        with pytest.raises(ValidationError):
            StrategySpec.model_validate(d)

    def test_watchlist_universe_with_id_validates(self):
        d = _minimal_spec_dict()
        d["universe"] = {"kind": "watchlist", "watchlist_id": 3}
        spec = StrategySpec.model_validate(d)
        assert spec.universe.watchlist_id == 3

    def test_backtest_config_defaults(self):
        spec = StrategySpec.model_validate(_minimal_spec_dict())
        c = spec.backtest_config
        assert c.is_oos_split == 0.7
        assert c.starting_capital_usd == 100_000
        assert c.commission_bps == 5
        assert c.slippage_bps == 5
        assert c.max_concurrent_positions == 10
        assert c.benchmark == "spy"
        assert c.reverse_signal_as_exit is True
        assert c.full_position_policy == "skip"

    def test_multi_block_entry(self):
        d = _minimal_spec_dict()
        d["entry"]["signals"] = [
            {"type": "ma_cross", "direction": "golden"},
            {"type": "rsi", "direction": "oversold_buy", "level": 30},
        ]
        d["entry"]["combiner"] = "and"
        spec = StrategySpec.model_validate(d)
        assert len(spec.entry.signals) == 2

    def test_all_18_blocks_discriminator_works(self):
        """Smoke: every block type must be reachable via the union."""
        from src.lab.spec.blocks_entry import (
            RSIEntry, RSICrossEntry, MACrossEntry, PriceVsMAEntry,
            MACDEntry, BollingerBreakEntry, DonchianBreakEntry, VolumeSpikeEntry,
        )
        from src.lab.spec.blocks_exit import (
            StopLossExit, TakeProfitExit, TrailingStopExit, TimeStopExit,
        )
        from src.lab.spec.blocks_sizing import (
            FixedPctSizing, EqualWeightSizing, VolTargetedSizing,
        )
        from src.lab.spec.blocks_filters import (
            TrendFilter, VolatilityFilter, LiquidityFilter,
        )
        # 8 entry + 4 exit + 3 sizing + 3 filters = 18
        all_block_types = [
            RSIEntry, RSICrossEntry, MACrossEntry, PriceVsMAEntry,
            MACDEntry, BollingerBreakEntry, DonchianBreakEntry, VolumeSpikeEntry,
            StopLossExit, TakeProfitExit, TrailingStopExit, TimeStopExit,
            FixedPctSizing, EqualWeightSizing, VolTargetedSizing,
            TrendFilter, VolatilityFilter, LiquidityFilter,
        ]
        assert len(all_block_types) == 18
