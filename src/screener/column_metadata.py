"""Static metadata for the 16 Screener chips.

Single source of truth for: chip kind, display labels (en/zh), data
type, format hint, step, min/max bounds, multi-select option lists.
The /screener/snapshot/columns endpoint serves this directly.
"""

from __future__ import annotations

from typing import Any


_GICS_SECTORS_US = [
    "Technology", "Healthcare", "Financial Services", "Consumer Cyclical",
    "Communication Services", "Industrials", "Consumer Defensive",
    "Energy", "Utilities", "Real Estate", "Basic Materials",
]

_SHENWAN_SECTORS_CN = [
    "白酒", "食品饮料", "银行", "电力设备", "电子", "医药生物",
    "汽车", "计算机", "通信", "传媒", "化工", "钢铁", "有色金属",
    "国防军工", "建筑材料", "公用事业", "房地产", "商贸零售",
    "纺织服饰", "轻工制造", "机械设备", "煤炭", "石油石化",
    "交通运输", "农林牧渔", "社会服务", "美容护理", "环保",
    "综合", "非银金融",
]

_ANALYST_RATINGS = [
    {"value": "strong_buy",   "label_en": "Strong Buy",   "label_zh": "强力买入"},
    {"value": "buy",          "label_en": "Buy",          "label_zh": "买入"},
    {"value": "neutral",      "label_en": "Neutral",      "label_zh": "中性"},
    {"value": "sell",         "label_en": "Sell",         "label_zh": "卖出"},
    {"value": "strong_sell",  "label_en": "Strong Sell",  "label_zh": "强力卖出"},
]


COLUMN_METADATA: list[dict[str, Any]] = [
    # ---- Row 1 ----
    {"slug": "price", "label_en": "Price", "label_zh": "价格",
     "kind": "range", "format": "currency", "step": 1,
     "filter_min": "price_min", "filter_max": "price_max"},
    {"slug": "chg_pct", "label_en": "Chg %", "label_zh": "涨跌幅",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "chg_pct_min", "filter_max": "chg_pct_max"},
    {"slug": "mcap", "label_en": "Mkt cap", "label_zh": "市值",
     "kind": "range", "format": "abbreviated_currency", "step": 1e9,
     "filter_min": "mcap_min", "filter_max": "mcap_max"},
    {"slug": "pe", "label_en": "P/E", "label_zh": "市盈率",
     "kind": "range", "format": "multiplier", "step": 1,
     "filter_min": "pe_min", "filter_max": "pe_max"},
    {"slug": "eps_growth", "label_en": "EPS dil growth", "label_zh": "EPS 增长",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "eps_growth_min", "filter_max": "eps_growth_max"},
    {"slug": "div_yield", "label_en": "Div yield %", "label_zh": "股息率",
     "kind": "range", "format": "percent", "step": 0.001,
     "filter_min": "div_yield_min", "filter_max": "div_yield_max"},
    {"slug": "sector", "label_en": "Sector", "label_zh": "板块",
     "kind": "multi_select", "filter_key": "sector_in",
     "options_us": [{"value": s, "label_en": s, "label_zh": s} for s in _GICS_SECTORS_US],
     "options_cn": [{"value": s, "label_en": s, "label_zh": s} for s in _SHENWAN_SECTORS_CN]},
    {"slug": "analyst_rating", "label_en": "Analyst rating", "label_zh": "分析师评级",
     "kind": "multi_select", "filter_key": "analyst_rating_in",
     "options": _ANALYST_RATINGS},
    {"slug": "perf_1d", "label_en": "Perf 1D", "label_zh": "1 日表现",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "perf_1d_min", "filter_max": "perf_1d_max"},

    # ---- Row 2 ----
    {"slug": "revenue_growth", "label_en": "Revenue growth", "label_zh": "营收增长",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "revenue_growth_min", "filter_max": "revenue_growth_max"},
    {"slug": "peg", "label_en": "PEG", "label_zh": "PEG",
     "kind": "range", "format": "multiplier", "step": 0.1,
     "filter_min": "peg_min", "filter_max": "peg_max"},
    {"slug": "roe", "label_en": "ROE", "label_zh": "ROE",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "roe_min", "filter_max": "roe_max"},
    {"slug": "beta", "label_en": "Beta", "label_zh": "Beta",
     "kind": "range", "format": "multiplier", "step": 0.1,
     "filter_min": "beta_min", "filter_max": "beta_max"},
    {"slug": "recent_earnings", "label_en": "Recent earnings", "label_zh": "上次财报",
     "kind": "date_range",
     "filter_after": "recent_earnings_after", "filter_before": "recent_earnings_before"},
    {"slug": "upcoming_earnings", "label_en": "Upcoming earnings", "label_zh": "下次财报",
     "kind": "date_range",
     "filter_after": "upcoming_earnings_after", "filter_before": "upcoming_earnings_before"},
    {"slug": "perf_extended", "label_en": "Perf 5D/1M/3M/YTD/1Y", "label_zh": "扩展表现",
     "kind": "range", "format": "percent", "step": 0.01,
     "filter_min": "perf_1y_min", "filter_max": "perf_1y_max"},
]
