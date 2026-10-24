"""``search_line_items`` implementation backed by yfinance financial statements.

The v1 Financial Datasets ``/financials/search/line-items`` endpoint exposes
arbitrary balance-sheet / income-statement / cash-flow rows per fiscal
period. The v2 hybrid client (Finnhub / EODHD / yfinance) does NOT have a
1:1 equivalent — Finnhub free only gives a few headline metrics, EODHD
fundamentals are on a paid tier we don't have. yfinance's
``Ticker.income_stmt / .balance_sheet / .cashflow`` DataFrames give us the
raw rows for free.

This module:
  * Maps each v1 line-item key to its yfinance row name (and, for ratio
    items, falls back to ``v2.composite_client.get_financial_metrics``).
  * Cherry-picks the requested fields per fiscal period.
  * Returns a list of v1 ``LineItem`` instances (extra='allow', so each
    instance carries the requested fields as dynamic attributes — exactly
    what callers like ``warren_buffett_agent`` do
    ``getattr(item, 'revenue', None)`` on).

Limitations vs the original FD endpoint:
  * ``period='ttm'`` is served with annual data (yfinance has no TTM
    endpoint). Real TTM would require summing trailing 4 quarters per
    flow item — adds complexity for marginal accuracy. Agents already
    treat single-period vs trailing differences leniently.
  * Coverage is limited to what yfinance exposes (~22 of the 30 unique
    line items requested across the 19 agents; the remaining 4 ratio
    items pull from financial-metrics fallback). Items with no source
    are populated as ``None``.
"""

from __future__ import annotations

import logging
from typing import Any

from src.data.cache import Cache
from src.data.models import LineItem

logger = logging.getLogger(__name__)


# v1 line_item key → yfinance source ("income"/"balance"/"cashflow") + row name.
# Where the field is a financial-metrics ratio rather than a statement row,
# the source is "metric" and the value is fetched from get_financial_metrics
# per matching report_period.
_YF_MAP: dict[str, tuple[str, str | tuple[str, ...]]] = {
    # ---------- income statement ----------
    "revenue":                   ("income",  "Total Revenue"),
    "gross_profit":              ("income",  "Gross Profit"),
    "operating_income":          ("income",  "Operating Income"),
    "ebit":                      ("income",  "EBIT"),
    "ebitda":                    ("income",  "EBITDA"),
    "net_income":                ("income",  "Net Income"),
    "earnings_per_share":        ("income",  "Basic EPS"),
    "operating_expense":         ("income",  "Operating Expense"),
    "research_and_development":  ("income",  "Research And Development"),
    "interest_expense":          ("income",  "Interest Expense"),
    "depreciation_and_amortization": ("income", "Reconciled Depreciation"),

    # ---------- balance sheet ----------
    "total_assets":              ("balance", "Total Assets"),
    "current_assets":            ("balance", "Current Assets"),
    "total_liabilities":         ("balance", "Total Liabilities Net Minority Interest"),
    "current_liabilities":       ("balance", "Current Liabilities"),
    "shareholders_equity":       ("balance", "Stockholders Equity"),
    "cash_and_equivalents":      ("balance", "Cash And Cash Equivalents"),
    "total_debt":                ("balance", "Total Debt"),
    "working_capital":           ("balance", "Working Capital"),
    "goodwill_and_intangible_assets": ("balance", "Goodwill And Other Intangible Assets"),
    "outstanding_shares":        ("balance", "Share Issued"),

    # ---------- cash flow ----------
    "free_cash_flow":            ("cashflow", "Free Cash Flow"),
    "capital_expenditure":       ("cashflow", "Capital Expenditure"),
    "dividends_and_other_cash_distributions": ("cashflow", "Cash Dividends Paid"),
    # Composite: net stock activity = issuance - repurchase
    "issuance_or_purchase_of_equity_shares": (
        "cashflow_composite",
        ("Issuance Of Capital Stock", "Repurchase Of Capital Stock"),
    ),

    # ---------- derived (computed in code) ----------
    "book_value_per_share":      ("derived", "book_value_per_share"),

    # ---------- financial-metrics ratio fallbacks ----------
    "debt_to_equity":            ("metric", "debt_to_equity"),
    "gross_margin":              ("metric", "gross_margin"),
    "operating_margin":          ("metric", "operating_margin"),
    "return_on_invested_capital": ("metric", "return_on_invested_capital"),
}


def _safe_float(v: Any) -> float | None:
    """Float coercion that also strips NaN."""
    if v is None:
        return None
    try:
        import math
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _row_value(df, row_name: str, col):
    """Look up one cell in a yfinance DataFrame. Returns None if missing."""
    if df is None or df.empty:
        return None
    if row_name not in df.index:
        return None
    try:
        return _safe_float(df.at[row_name, col])
    except Exception:
        return None


def search_line_items(
    *,
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    cache: Cache | None = None,
) -> list[LineItem]:
    """Cherry-pick the requested line items per fiscal period.

    Returns up to ``limit`` periods, newest-first, ending on/before
    ``end_date``. Each returned ``LineItem`` carries the requested fields
    as dynamic attributes (LineItem has ``model_config = {'extra': 'allow'}``).
    """
    cache_key = f"{ticker}_{period}_{end_date}_{limit}_{'-'.join(sorted(line_items))}"
    if cache is not None:
        cached = cache.get_line_items(cache_key)
        if cached:
            return [LineItem(**li) for li in cached[:limit]]

    # Lazy yfinance import + fetch the 3 DataFrames once per ticker.
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        income_df = t.income_stmt if period == "annual" or period == "ttm" else t.quarterly_income_stmt
        balance_df = t.balance_sheet if period == "annual" or period == "ttm" else t.quarterly_balance_sheet
        cash_df = t.cashflow if period == "annual" or period == "ttm" else t.quarterly_cashflow
    except Exception as e:
        logger.warning("yfinance fetch failed for %s: %s", ticker, e)
        return []

    # Determine the period columns. Use whichever statement has the most
    # columns as the period index — they're usually identical anyway.
    candidate_cols = []
    for df in (income_df, balance_df, cash_df):
        if df is not None and not df.empty:
            candidate_cols = list(df.columns)
            break
    if not candidate_cols:
        return []

    # Filter to columns at or before end_date.
    import pandas as pd
    try:
        end_ts = pd.to_datetime(end_date)
    except Exception:
        end_ts = None
    if end_ts is not None:
        candidate_cols = [c for c in candidate_cols if pd.to_datetime(c) <= end_ts]
    # Newest first; cap to limit.
    candidate_cols = sorted(candidate_cols, reverse=True)[:limit]

    # For "metric" line items, fetch financial_metrics once per call so we
    # can look up matching report_periods.
    metric_lookup: dict[str, dict[str, float | None]] = {}
    if any(_YF_MAP.get(li, (None, None))[0] == "metric" for li in line_items):
        try:
            from v2.data.composite_client import make_hybrid_client
            client = make_hybrid_client()
            v2_metrics = client.get_financial_metrics(
                ticker, end_date, period=period, limit=limit * 2,
            )
            for m in v2_metrics:
                metric_lookup[m.report_period] = m.model_dump()
        except Exception as e:
            logger.debug("financial_metrics fallback fetch failed for %s: %s", ticker, e)

    # Build a LineItem per period.
    out: list[LineItem] = []
    for col in candidate_cols:
        report_period = str(col)[:10]  # e.g. "2024-09-30"
        fields: dict[str, Any] = {
            "ticker": ticker,
            "report_period": report_period,
            "period": period,
            "currency": "USD",
        }
        for li in line_items:
            mapping = _YF_MAP.get(li)
            if mapping is None:
                fields[li] = None
                continue
            source, row_name = mapping
            if source == "income":
                fields[li] = _row_value(income_df, row_name, col)
            elif source == "balance":
                fields[li] = _row_value(balance_df, row_name, col)
            elif source == "cashflow":
                fields[li] = _row_value(cash_df, row_name, col)
            elif source == "cashflow_composite":
                issuance = _row_value(cash_df, row_name[0], col) or 0
                repurchase = _row_value(cash_df, row_name[1], col) or 0
                # Net positive = net issuance, negative = net repurchase
                fields[li] = issuance + repurchase  # repurchase is already negative in yfinance
            elif source == "derived":
                # Compute on the fly using already-fetched values.
                if li == "book_value_per_share":
                    eq = _row_value(balance_df, "Stockholders Equity", col)
                    sh = _row_value(balance_df, "Share Issued", col)
                    fields[li] = (eq / sh) if (eq is not None and sh) else None
                else:
                    fields[li] = None
            elif source == "metric":
                # Find the closest report_period in metric_lookup.
                m = metric_lookup.get(report_period)
                if m is None:
                    # Try year-close match (FD often uses end-of-quarter dates
                    # that don't exactly match yfinance's fiscal-year dates).
                    for rp, md in metric_lookup.items():
                        if rp.startswith(report_period[:4]):
                            m = md
                            break
                fields[li] = m.get(row_name) if m else None
            else:
                fields[li] = None
        out.append(LineItem(**fields))

    if cache is not None and out:
        cache.set_line_items(cache_key, [li.model_dump() for li in out])
    return out
