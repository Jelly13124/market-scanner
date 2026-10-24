"""Phase 8: 财联社 (cls.cn) news fetcher (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.ashare.cls_news import fetch_stock_news


def _mock(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_parses_news_list():
    payload = {
        "data": {
            "depth_list": [
                {
                    "id": 100,
                    "title": "贵州茅台2024年净利润同比增长15%",
                    "brief": "...",
                    "ctime": 1716700000,
                    "share_url": "https://www.cls.cn/detail/100",
                    "subjects": [{"subject_name": "白酒"}],
                },
                {
                    "id": 101,
                    "title": "茅台股东大会通过分红方案",
                    "ctime": 1716800000,
                    "share_url": "https://www.cls.cn/detail/101",
                    "subjects": [],
                },
            ]
        }
    }
    sess = _mock(payload)
    news = fetch_stock_news("600519.SH", "2026-05-26", limit=20, session=sess)
    assert len(news) == 2
    assert news[0].title.startswith("贵州茅台")
    assert news[0].source == "财联社"
    assert news[0].url == "https://www.cls.cn/detail/100"


def test_empty_on_no_data():
    sess = _mock({"data": {"depth_list": []}})
    assert fetch_stock_news("600519.SH", "2026-05-26", session=sess) == []
