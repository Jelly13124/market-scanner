"""Phase 8: Eastmoney F10 fundamentals fetcher (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from v2.data.ashare.eastmoney_fundamentals import (
    fetch_financial_metrics, fetch_company_facts,
)


def _mock_session(json_payload):
    """Build a fake session whose .get(...).json() returns the payload."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_payload
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_fetch_financial_metrics_parses_eastmoney_shape():
    # Eastmoney F10 financial-indicators endpoint returns:
    # {"result": {"data": [{"REPORT_DATE": "2024-09-30",
    #   "BASIC_EPS": 12.34, "TOTAL_OPERATE_INCOME": 1.2e11, ...}]}}
    payload = {
        "result": {
            "data": [
                {
                    "REPORT_DATE": "2024-09-30",
                    "BASIC_EPS": 50.12,
                    "TOTAL_OPERATE_INCOME": 1.2e11,
                    "NETPROFIT": 4.5e10,
                    "ROE_AVG": 25.6,
                    "GROSSPROFIT_MARGIN": 92.0,
                    "DEBT_ASSET_RATIO": 15.3,
                },
                {
                    "REPORT_DATE": "2024-06-30",
                    "BASIC_EPS": 32.10,
                    "TOTAL_OPERATE_INCOME": 8.0e10,
                    "NETPROFIT": 3.2e10,
                    "ROE_AVG": 18.2,
                    "GROSSPROFIT_MARGIN": 91.5,
                    "DEBT_ASSET_RATIO": 16.0,
                },
            ]
        }
    }
    sess = _mock_session(payload)
    metrics = fetch_financial_metrics(
        "600519.SH", "2026-05-26", period="ttm", limit=4, session=sess,
    )
    assert len(metrics) == 2
    assert metrics[0].report_period == "2024-09-30"
    assert metrics[0].earnings_per_share == 50.12
    assert metrics[0].return_on_equity == 0.256
    assert metrics[0].gross_margin == 0.92
    assert metrics[0].debt_to_assets == 0.153


def test_fetch_company_facts_parses_eastmoney_shape():
    payload = {
        "jbzl": {
            "SECURITY_NAME_ABBR": "贵州茅台",
            "INDUSTRYNAME": "白酒",
            "SECTOR_NAME": "食品饮料",
            "AREA_NAME": "贵州",
            "EMP_NUM": 30000,
            "LISTING_DATE": "2001-08-27",
        }
    }
    sess = _mock_session(payload)
    facts = fetch_company_facts("600519.SH", session=sess)
    assert facts is not None
    assert facts.name == "贵州茅台"
    assert facts.industry == "白酒"
    assert facts.sector == "食品饮料"
    assert facts.number_of_employees == 30000


def test_fetch_financial_metrics_returns_empty_on_empty_payload():
    sess = _mock_session({"result": {"data": []}})
    metrics = fetch_financial_metrics(
        "600519.SH", "2026-05-26", session=sess,
    )
    assert metrics == []


def test_fetch_company_facts_returns_none_on_missing_jbzl():
    sess = _mock_session({})
    facts = fetch_company_facts("600519.SH", session=sess)
    assert facts is None
