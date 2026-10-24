"""Eastmoney quarterly earnings history for A-shares.

Reuses the same financial-indicators endpoint as fundamentals but
parses through the EarningsRecord shape (flat per-period). The actual
SOP analyze pipeline cares about period-level EPS + revenue + YoY,
which all live in REPORT_DATE / BASIC_EPS / TOTAL_OPERATE_INCOME /
NETPROFIT / YOY_NETPROFIT.

Model note: EarningsRecord has no top-level eps/revenue/net_income;
those live on the nested EarningsData via quarterly=.
"""

from __future__ import annotations

from typing import Any

import requests

from v2.data.models import EarningsData, EarningsRecord

_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
    "reportName=RPT_LICO_FN_CPD&columns=ALL"
    "&filter=(SECURITY_CODE=\"{code}\")"
    "&pageNumber=1&pageSize={page_size}"
    "&sortColumns=REPORT_DATE&sortTypes=-1"
)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_earnings_history(
    canonical_ticker: str,
    *,
    limit: int = 12,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[EarningsRecord]:
    sess = session or requests.Session()
    code = canonical_ticker.split('.', 1)[0]
    url = _URL.format(code=code, page_size=max(limit, 1))
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    rows = (payload.get("result") or {}).get("data") or []
    out: list[EarningsRecord] = []
    for row in rows[:limit]:
        quarterly = EarningsData(
            earnings_per_share=_f(row.get("BASIC_EPS")),
            revenue=_f(row.get("TOTAL_OPERATE_INCOME")),
            net_income=_f(row.get("NETPROFIT")),
            net_income_chg=_f(row.get("YOY_NETPROFIT")),
        )
        out.append(EarningsRecord(
            ticker=canonical_ticker,
            report_period=row.get("REPORT_DATE", "").split(" ")[0],
            source_type="eastmoney_f10",
            fiscal_period="quarterly",
            currency="CNY",
            quarterly=quarterly,
        ))
    return out
