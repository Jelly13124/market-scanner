"""Phase 6A: Pydantic validation for all 18 strategy blocks.

Each block type is a Pydantic v2 model with a `type` discriminator
literal. Validation rejects out-of-range parameters at construction
time so the LLM never produces a runtime crash via with_structured_output.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.lab.spec.blocks_entry import (
    RSIEntry, RSICrossEntry, MACrossEntry, PriceVsMAEntry,
    MACDEntry, BollingerBreakEntry, DonchianBreakEntry, VolumeSpikeEntry,
)


class TestRSIEntry:
    def test_default_fields(self):
        b = RSIEntry(direction="oversold_buy")
        assert b.type == "rsi"
        assert b.period == 14
        assert b.level == 30

    def test_period_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            RSIEntry(direction="oversold_buy", period=1)
        with pytest.raises(ValidationError):
            RSIEntry(direction="oversold_buy", period=101)

    def test_level_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            RSIEntry(direction="oversold_buy", level=-1)
        with pytest.raises(ValidationError):
            RSIEntry(direction="oversold_buy", level=101)

    def test_invalid_direction_rejected(self):
        with pytest.raises(ValidationError):
            RSIEntry(direction="sideways")


class TestRSICrossEntry:
    def test_default(self):
        b = RSICrossEntry(direction="up")
        assert b.type == "rsi_cross" and b.period == 14 and b.level == 30


class TestMACrossEntry:
    def test_default(self):
        b = MACrossEntry()
        assert b.type == "ma_cross" and b.fast == 50 and b.slow == 200
        assert b.ma_type == "sma" and b.direction == "golden"

    def test_invalid_ma_type_rejected(self):
        with pytest.raises(ValidationError):
            MACrossEntry(ma_type="hull")


class TestPriceVsMAEntry:
    def test_above(self):
        b = PriceVsMAEntry(direction="above")
        assert b.type == "price_vs_ma" and b.ma_period == 200


class TestMACDEntry:
    def test_bullish_cross(self):
        b = MACDEntry(trigger="bullish_cross")
        assert b.type == "macd" and b.fast == 12 and b.slow == 26 and b.signal == 9


class TestBollingerBreakEntry:
    def test_default(self):
        b = BollingerBreakEntry(direction="break_up")
        assert b.type == "bollinger_break" and b.period == 20 and b.num_std == 2.0


class TestDonchianBreakEntry:
    def test_default(self):
        b = DonchianBreakEntry(direction="break_up")
        assert b.type == "donchian_break" and b.period == 20

    def test_period_too_large_rejected(self):
        with pytest.raises(ValidationError):
            DonchianBreakEntry(direction="break_up", period=300)


class TestVolumeSpikeEntry:
    def test_default(self):
        b = VolumeSpikeEntry()
        assert b.type == "volume_spike" and b.multiplier == 2.0

    def test_multiplier_too_large_rejected(self):
        with pytest.raises(ValidationError):
            VolumeSpikeEntry(multiplier=11.0)
