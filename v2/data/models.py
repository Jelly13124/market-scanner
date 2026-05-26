"""Pydantic models for Financial Datasets API responses.

Field names and nullability match the FD backend serializers.
All models use ``extra="ignore"`` for forward-compatibility.
"""

from __future__ import annotations

from pydantic import BaseModel


_IGNORE = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

class Price(BaseModel):
    """Single OHLCV bar.

    ``adjusted_close`` is split- and dividend-adjusted (when the provider
    supplies it). Return calculations should prefer it over ``close`` to avoid
    false-positive moves on ex-div / split days.
    """

    model_config = _IGNORE

    open: float
    close: float
    high: float
    low: float
    volume: int
    time: str
    adjusted_close: float | None = None


# ---------------------------------------------------------------------------
# Financial Metrics
# ---------------------------------------------------------------------------

class FinancialMetrics(BaseModel):
    """Financial ratios and per-share metrics from /financial-metrics.

    Only ticker, report_period, and period are guaranteed non-null.
    All ratio/metric fields are nullable (NaN/Inf sanitised to null).
    """

    model_config = _IGNORE

    ticker: str
    report_period: str
    period: str
    currency: str | None = None

    # Valuation
    market_cap: float | None = None
    enterprise_value: float | None = None
    price_to_earnings_ratio: float | None = None
    price_to_book_ratio: float | None = None
    price_to_sales_ratio: float | None = None
    enterprise_value_to_ebitda_ratio: float | None = None
    enterprise_value_to_revenue_ratio: float | None = None
    free_cash_flow_yield: float | None = None
    peg_ratio: float | None = None

    # Profitability
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    return_on_equity: float | None = None
    return_on_assets: float | None = None
    return_on_invested_capital: float | None = None

    # Efficiency
    asset_turnover: float | None = None
    inventory_turnover: float | None = None
    receivables_turnover: float | None = None
    days_sales_outstanding: float | None = None
    operating_cycle: float | None = None
    working_capital_turnover: float | None = None

    # Liquidity
    current_ratio: float | None = None
    quick_ratio: float | None = None
    cash_ratio: float | None = None
    operating_cash_flow_ratio: float | None = None

    # Leverage
    debt_to_equity: float | None = None
    debt_to_assets: float | None = None
    interest_coverage: float | None = None

    # Growth
    revenue_growth: float | None = None
    earnings_growth: float | None = None
    book_value_growth: float | None = None
    earnings_per_share_growth: float | None = None
    free_cash_flow_growth: float | None = None
    operating_income_growth: float | None = None
    ebitda_growth: float | None = None

    # Per-share
    payout_ratio: float | None = None
    earnings_per_share: float | None = None
    book_value_per_share: float | None = None
    free_cash_flow_per_share: float | None = None


# ---------------------------------------------------------------------------
# Insider Trades
# ---------------------------------------------------------------------------

class InsiderTrade(BaseModel):
    """Single insider transaction from /insider-trades."""

    model_config = _IGNORE

    ticker: str
    name: str
    filing_date: str
    is_board_director: bool = False
    issuer: str | None = None
    title: str | None = None
    transaction_date: str | None = None
    transaction_type: str | None = None
    transaction_shares: float | None = None
    transaction_price_per_share: float | None = None
    transaction_value: float | None = None
    shares_owned_before_transaction: float | None = None
    shares_owned_after_transaction: float | None = None
    security_title: str | None = None


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

class CompanyNews(BaseModel):
    """Single news article from /news."""

    model_config = _IGNORE

    ticker: str
    title: str
    source: str
    date: str | None = None
    url: str | None = None
    # FD's polarity label, typically one of "positive" / "negative" / "neutral".
    # Nullable because not every article is scored.
    sentiment: str | None = None
    # Continuous polarity score, when the provider supplies one. EODHD's
    # /sentiments endpoint returns a daily "normalized" score (~[-1, +1] but
    # positive-skewed in practice) — far more sensitive than the 3-bucket
    # label. Detectors should prefer this over ``sentiment`` when present.
    sentiment_score: float | None = None


# ---------------------------------------------------------------------------
# Company Facts
# ---------------------------------------------------------------------------

class CompanyFacts(BaseModel):
    """Company metadata from /company/facts."""

    model_config = _IGNORE

    ticker: str
    is_active: bool = True
    name: str | None = None
    cik: str | None = None
    sector: str | None = None
    industry: str | None = None
    category: str | None = None
    exchange: str | None = None
    location: str | None = None
    sec_filings_url: str | None = None
    sic_code: str | None = None
    sic_industry: str | None = None
    sic_sector: str | None = None
    market_cap: float | None = None
    number_of_employees: int | None = None
    weighted_average_shares: int | None = None


# ---------------------------------------------------------------------------
# Earnings
# ---------------------------------------------------------------------------

class EarningsData(BaseModel):
    """Financial data for a single earnings period (quarterly or annual)."""

    model_config = _IGNORE

    # Actuals vs. estimates
    revenue: float | None = None
    estimated_revenue: float | None = None
    revenue_surprise: str | None = None  # "BEAT" | "MISS" | "MEET"
    earnings_per_share: float | None = None
    estimated_earnings_per_share: float | None = None
    eps_surprise: str | None = None  # "BEAT" | "MISS" | "MEET"

    # Income statement
    net_income: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    weighted_average_shares: float | None = None
    weighted_average_shares_diluted: float | None = None
    free_cash_flow: float | None = None

    # Balance sheet
    cash_and_equivalents: float | None = None
    total_debt: float | None = None
    total_assets: float | None = None
    total_liabilities: float | None = None
    shareholders_equity: float | None = None

    # Cash flow
    net_cash_flow_from_operations: float | None = None
    capital_expenditure: float | None = None
    net_cash_flow_from_investing: float | None = None
    net_cash_flow_from_financing: float | None = None
    change_in_cash_and_equivalents: float | None = None

    # Period-over-period changes (omitted from response if null)
    revenue_chg: float | None = None
    net_income_chg: float | None = None
    operating_income_chg: float | None = None
    gross_profit_chg: float | None = None
    free_cash_flow_chg: float | None = None


class Earnings(BaseModel):
    """Earnings data from /earnings (single-ticker, latest-period mode)."""

    model_config = _IGNORE

    ticker: str
    report_period: str
    fiscal_period: str | None = None
    currency: str | None = None
    quarterly: EarningsData | None = None
    annual: EarningsData | None = None


class EarningsRecord(BaseModel):
    """One filing from /earnings/?ticker=X&limit=N (flat history mode).

    Each record is a single SEC filing about a fiscal period.
    The same report_period can appear multiple times with different
    source_type values (e.g. 8-K and 10-Q for the same quarter).
    """

    model_config = _IGNORE

    ticker: str
    report_period: str
    source_type: str
    # Nullable: FD occasionally returns records without a filing_date.
    # Downstream filters (filter_retrospective_earnings, detector logic) drop these.
    filing_date: str | None = None
    filing_datetime: str | None = None
    filing_window: str | None = None
    fiscal_period: str | None = None
    currency: str | None = None
    filing_url: str | None = None
    accession_number: str | None = None
    quarterly: EarningsData | None = None
    annual: EarningsData | None = None


# ---------------------------------------------------------------------------
# SEC Filings
# ---------------------------------------------------------------------------

class Filing(BaseModel):
    """Single SEC filing from /filings."""

    model_config = _IGNORE

    ticker: str | None = None
    cik: str | None = None
    accession_number: str | None = None
    filing_type: str | None = None
    filing_date: str | None = None
    report_period: str | None = None
    document_count: int | None = None
    is_xbrl: bool | None = None
    url: str | None = None


# ---------------------------------------------------------------------------
# Analyst data (yfinance-sourced)
# ---------------------------------------------------------------------------

class AnalystTarget(BaseModel):
    """Aggregate analyst price target snapshot for one ticker.

    Source: yfinance ``Ticker.analyst_price_targets`` (Yahoo Finance unofficial).
    All numeric fields nullable — yfinance may return partial dicts when
    coverage is thin.
    """

    model_config = _IGNORE

    ticker: str
    current_price: float | None = None
    target_mean: float | None = None
    target_median: float | None = None
    target_high: float | None = None
    target_low: float | None = None
    n_analysts: int | None = None
    asof_date: str  # YYYY-MM-DD


class AnalystAction(BaseModel):
    """One analyst upgrade / downgrade / initiation event.

    Source: yfinance ``Ticker.upgrades_downgrades``. Fields mirror the Yahoo
    columns (Firm / ToGrade / FromGrade / Action) plus a normalized lowercase
    ``action`` value: 'up', 'down', 'main', 'init', or 'reit'.
    """

    model_config = _IGNORE

    ticker: str
    action_date: str  # YYYY-MM-DD
    firm: str
    from_grade: str | None = None
    to_grade: str | None = None
    action: str  # 'up' | 'down' | 'main' | 'init' | 'reit'


# ---------------------------------------------------------------------------
# Live quote (intraday snapshot)
# ---------------------------------------------------------------------------

class Quote(BaseModel):
    """One ticker's live-ish quote snapshot.

    Sourced from Finnhub ``/quote`` in the hybrid setup. Used by the
    watchlist UI to show current price + today's session change next to
    each scored row. All numeric fields nullable — providers occasionally
    return zero or omit fields for illiquid names.
    """

    model_config = _IGNORE

    ticker: str
    current_price: float | None = None
    prev_close: float | None = None
    percent_change: float | None = None   # today's % move (Finnhub's `dp`)
    asof_timestamp: int | None = None     # epoch seconds (Finnhub's `t`)


class EstimateRevisions(BaseModel):
    """Net analyst EPS-estimate revisions for one period.

    Sourced from yfinance ``Ticker.eps_revisions``, which returns a
    DataFrame indexed by period (``0q`` / ``+1q`` / ``0y`` / ``+1y``)
    with rolling 7-day and 30-day up/down counts. ``EstimateRevisionDetector``
    consumes this and z-scores via fixed scale (yfinance only exposes the
    aggregated counts, not per-analyst history).
    """

    model_config = _IGNORE

    ticker: str
    asof_date: str
    period: str            # one of "0q" / "+1q" / "0y" / "+1y"
    up_last_7d: int = 0
    down_last_7d: int = 0
    up_last_30d: int = 0
    down_last_30d: int = 0


class EarningsCalendarEntry(BaseModel):
    """One scheduled (or recent) earnings event from a provider's calendar feed.

    Used by ``EarningsUpcomingDetector`` to mark tickers with earnings due
    within the next N days — a forward-looking catalyst-risk signal,
    distinct from ``EarningsSurpriseDetector`` which fires only after BEAT/MISS.
    """

    model_config = _IGNORE

    symbol: str
    date: str                              # ISO YYYY-MM-DD of the report
    hour: str | None = None                # 'bmo' (before market open) / 'amc' (after market close) / 'dmh' (during market hours)
    eps_estimate: float | None = None
    revenue_estimate: float | None = None
    year: int | None = None
    quarter: int | None = None
