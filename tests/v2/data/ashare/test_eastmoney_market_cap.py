"""Phase 8: market cap fetcher (Tencent quote endpoint, mocked)."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.ashare.eastmoney_market_cap import fetch_market_cap


def test_parses_market_cap():
    # Tencent quote endpoint returns plain-text v_sz000001="50~ping_an_bank~000001~..."
    # Field 45 is total market cap in 亿元 (100m). We convert to RMB.
    txt = 'v_sh600519="1~贵州茅台~600519~1700.00~1690.00~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~21354.00~21354.00~~~~~~~~~~~~~"'
    resp = MagicMock()
    resp.status_code = 200
    resp.text = txt
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp

    cap = fetch_market_cap("600519.SH", "2026-05-26", session=sess)
    # 21354.00 亿元 == 21354 * 100_000_000 RMB
    assert cap == 21354.00 * 100_000_000


def test_returns_none_on_unparseable():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "garbage"
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    assert fetch_market_cap("600519.SH", "2026-05-26", session=sess) is None


def test_returns_none_on_short_fields():
    # Too few fields (Tencent revision drift) -> safe None
    resp = MagicMock()
    resp.status_code = 200
    resp.text = 'v_sh600519="1~name~600519~1700"'
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    assert fetch_market_cap("600519.SH", "2026-05-26", session=sess) is None
