"""AshareMetrics — thin wrapper test (no real network)."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def test_get_quote_shape():
    from src.screener.ashare_metrics import AshareMetrics
    fake_mootdx = MagicMock()
    fake_mootdx.quotes.return_value = {
        "price": 1700.5, "last_close": 1685.0,
        "vol": 25000, "amount": 4.25e10,
    }
    m = AshareMetrics(mootdx_client=fake_mootdx, akshare_module=MagicMock())
    q = m.get_quote("600519.SH")
    assert q["price"] == 1700.5
    assert q["prev_close"] == 1685.0
    assert q["volume"] == 25000 * 100  # mootdx volume is in 手 (lots of 100)


def test_get_quote_handles_dataframe():
    """Real mootdx returns a single-row DataFrame, not a dict. Regression for
    'truth value of a DataFrame is ambiguous' raised by `if not q`."""
    from src.screener.ashare_metrics import AshareMetrics
    import pandas as pd
    fake_mootdx = MagicMock()
    fake_mootdx.quotes.return_value = pd.DataFrame(
        [{"code": "600519", "price": 1275.98, "last_close": 1303.0,
          "vol": 45889, "volume": 45889, "amount": 5.89e9}]
    )
    m = AshareMetrics(mootdx_client=fake_mootdx, akshare_module=MagicMock())
    q = m.get_quote("600519.SH")
    assert q["price"] == 1275.98
    assert q["prev_close"] == 1303.0
    assert q["volume"] == 45889 * 100


def test_get_quote_handles_empty_dataframe():
    from src.screener.ashare_metrics import AshareMetrics
    import pandas as pd
    fake_mootdx = MagicMock()
    fake_mootdx.quotes.return_value = pd.DataFrame()
    m = AshareMetrics(mootdx_client=fake_mootdx, akshare_module=MagicMock())
    q = m.get_quote("BOGUS.SH")
    assert q == {"price": None, "prev_close": None,
                 "volume": None, "avg_volume_10d": None}


def test_get_quote_handles_unknown_symbol():
    from src.screener.ashare_metrics import AshareMetrics
    fake_mootdx = MagicMock()
    fake_mootdx.quotes.return_value = None
    m = AshareMetrics(mootdx_client=fake_mootdx, akshare_module=MagicMock())
    q = m.get_quote("BOGUS.SH")
    assert q == {"price": None, "prev_close": None,
                 "volume": None, "avg_volume_10d": None}


def test_get_fundamentals_calls_akshare():
    """akshare returns a DataFrame — wrap it through __getitem__ mocks."""
    from src.screener.ashare_metrics import AshareMetrics
    import pandas as pd
    fake_ak = MagicMock()
    fake_ak.stock_individual_info_em.return_value = pd.DataFrame(
        {"item": ["总市值", "市盈率(动)", "市净率", "行业"],
         "value": [2.12e12, 28.5, 8.2, "白酒"]}
    )
    m = AshareMetrics(mootdx_client=MagicMock(), akshare_module=fake_ak)
    f = m.get_fundamentals("600519")
    assert f["market_cap"] == 2.12e12
    assert f["pe_ttm"] == 28.5
    assert f["pb"] == 8.2
    assert f["sector"] == "白酒"
