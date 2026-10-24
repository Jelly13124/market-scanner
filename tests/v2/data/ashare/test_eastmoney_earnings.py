"""Phase 8: Eastmoney quarterly earnings history (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.ashare.eastmoney_earnings import fetch_earnings_history


def _mock_session(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_parses_quarterly_earnings():
    # Eastmoney earnings preview/actual endpoint shape:
    # {"result": {"data": [
    #   {"REPORT_DATE": "2024-12-31", "BASIC_EPS": 60.5,
    #    "TOTAL_OPERATE_INCOME": 1.7e11,
    #    "NETPROFIT": 8.6e10, "YOY_NETPROFIT": 18.5}, ...]}}
    payload = {
        "result": {
            "data": [
                {
                    "REPORT_DATE": "2024-12-31",
                    "BASIC_EPS": 60.5,
                    "TOTAL_OPERATE_INCOME": 1.7e11,
                    "NETPROFIT": 8.6e10,
                    "YOY_NETPROFIT": 18.5,
                },
                {
                    "REPORT_DATE": "2024-09-30",
                    "BASIC_EPS": 50.12,
                    "TOTAL_OPERATE_INCOME": 1.2e11,
                    "NETPROFIT": 4.5e10,
                    "YOY_NETPROFIT": 15.2,
                },
            ]
        }
    }
    sess = _mock_session(payload)
    records = fetch_earnings_history("600519.SH", limit=4, session=sess)
    assert len(records) == 2
    assert records[0].report_period == "2024-12-31"
    assert records[0].source_type == "eastmoney_f10"
    assert records[0].fiscal_period == "quarterly"
    assert records[0].currency == "CNY"
    # EPS / revenue / net_income live on the nested quarterly EarningsData
    assert records[0].quarterly is not None
    assert records[0].quarterly.earnings_per_share == 60.5
    assert records[0].quarterly.revenue == 1.7e11
    assert records[0].quarterly.net_income == 8.6e10


def test_returns_empty_on_empty():
    sess = _mock_session({"result": {"data": []}})
    assert fetch_earnings_history("600519.SH", session=sess) == []
