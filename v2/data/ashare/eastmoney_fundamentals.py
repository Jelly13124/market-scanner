"""Eastmoney F10 fundamentals -- financial metrics + company facts.

Eastmoney exposes F10 (the 'Form 10' equivalent -- Chinese listed-company
profile pages) as a series of JSON endpoints under emweb.securities.
eastmoney.com. No auth, no API key. Endpoints occasionally change names;
when this module starts returning empty data, check the latest URLs in
the reference repo (simonlin1212/a-stock-data) README.

Fields mapped to our project-native FinancialMetrics use ratios as
fractions (0.25 = 25%) per the existing convention.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from v2.data.models import CompanyFacts, FinancialMetrics

logger = logging.getLogger(__name__)

_FIN_INDICATORS_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
    "reportName=RPT_LICO_FN_CPD&columns=ALL"
    "&filter=(SECURITY_CODE=\"{code}\")"
    "&pageNumber=1&pageSize={page_size}"
    "&sortColumns=REPORT_DATE&sortTypes=-1"
)

_F10_PROFILE_URL = (
    "https://emweb.securities.eastmoney.com/PC_HSF10/CompanyInfo/"
    "PageAjaxJBZL?code={pre_code}"
)


def _code_only(canonical: str) -> str:
    return canonical.split('.', 1)[0]


def _pre_code(canonical: str) -> str:
    """Eastmoney expects e.g. 'SH600519' for the profile endpoint."""
    code, exch = canonical.split('.', 1)
    return f"{exch.upper()}{code}"


def _pct_to_frac(v: Any) -> float | None:
    """Eastmoney returns percentages as numbers (25.6 = 25.6%). Convert
    to fraction (0.256). None passes through; non-numeric -> None."""
    if v is None:
        return None
    try:
        return float(v) / 100.0
    except (TypeError, ValueError):
        return None


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_financial_metrics(
    canonical_ticker: str,
    end_date: str,
    *,
    period: str = "ttm",
    limit: int = 10,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[FinancialMetrics]:
    """Fetch recent quarterly FinancialMetrics from Eastmoney F10.

    `period` is accepted for protocol parity but Eastmoney only ships
    quarterly snapshots. Caller picks the latest `limit` quarters.
    """
    sess = session or requests.Session()
    url = _FIN_INDICATORS_URL.format(
        code=_code_only(canonical_ticker), page_size=max(limit, 1),
    )
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    rows = (payload.get("result") or {}).get("data") or []
    if not rows:
        return []

    out: list[FinancialMetrics] = []
    for row in rows[:limit]:
        out.append(FinancialMetrics(
            ticker=canonical_ticker,
            report_period=row.get("REPORT_DATE", "").split(" ")[0],
            period=period,
            currency="CNY",
            earnings_per_share=_f(row.get("BASIC_EPS")),
            return_on_equity=_pct_to_frac(row.get("ROE_AVG")),
            gross_margin=_pct_to_frac(row.get("GROSSPROFIT_MARGIN")),
            debt_to_assets=_pct_to_frac(row.get("DEBT_ASSET_RATIO")),
            # FinancialMetrics has no top-level revenue/net_income fields
            # (those live on EarningsRecord.quarterly); they are intentionally
            # dropped here. The rest of FinancialMetrics's ~40 fields stay
            # None -- v2 mapping work picks them up as Eastmoney coverage
            # allows.
        ))
    return out


def fetch_company_facts(
    canonical_ticker: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> CompanyFacts | None:
    """Fetch sector / industry / name from Eastmoney F10 'JBZL'
    (basic info) page."""
    sess = session or requests.Session()
    url = _F10_PROFILE_URL.format(pre_code=_pre_code(canonical_ticker))
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    jbzl = payload.get("jbzl")
    if not jbzl:
        return None
    emp_num = jbzl.get("EMP_NUM")
    try:
        employees = int(emp_num) if emp_num is not None else None
    except (TypeError, ValueError):
        employees = None
    return CompanyFacts(
        ticker=canonical_ticker,
        name=jbzl.get("SECURITY_NAME_ABBR"),
        sector=jbzl.get("SECTOR_NAME"),
        industry=jbzl.get("INDUSTRYNAME"),
        cik=None,
        market_cap=None,  # fetched separately via market_cap module
        number_of_employees=employees,
    )
