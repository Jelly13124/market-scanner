"""Phase 8: A-share symbol detection + canonical form normalization."""
from __future__ import annotations

import pytest
from v2.data.ashare.symbol import is_ashare, normalize, infer_exchange


class TestIsAshare:
    @pytest.mark.parametrize("ticker,expected", [
        ("600519", True),         # bare 6 digits
        ("600519.SH", True),
        ("000001.SZ", True),
        ("300750.SZ", True),
        ("688981.SH", True),
        ("830799.BJ", True),
        ("sh600519", True),       # prefix form
        ("SZ.000001", True),
        ("NVDA", False),
        ("BRK.B", False),
        ("AAPL.US", False),
        ("", False),
        ("00519", False),         # 5 digits is not A-share
        ("6005191", False),       # 7 digits is not A-share
    ])
    def test_detection(self, ticker, expected):
        assert is_ashare(ticker) is expected


class TestNormalize:
    @pytest.mark.parametrize("input,expected", [
        ("600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("SH.600519", "600519.SH"),
        ("000001", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("688981", "688981.SH"),
        ("830799", "830799.BJ"),
    ])
    def test_canonical(self, input, expected):
        assert normalize(input) == expected

    def test_raises_on_non_ashare(self):
        with pytest.raises(ValueError):
            normalize("NVDA")


class TestInferExchange:
    @pytest.mark.parametrize("code,exchange", [
        ("600519", "SH"),
        ("601318", "SH"),
        ("688981", "SH"),
        ("900957", "SH"),     # B-share
        ("000001", "SZ"),
        ("002594", "SZ"),
        ("300750", "SZ"),
        ("200002", "SZ"),     # B-share
        ("830799", "BJ"),
        ("872925", "BJ"),
    ])
    def test_inference(self, code, exchange):
        assert infer_exchange(code) == exchange
