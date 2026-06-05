"""Phase 11: build a comprehensive QUANT CONTEXT block from SharedData
and inject it into every section's LLM prompt.

The motivation: the SOP pipeline was sending the LLM nothing but a
ticker symbol + objective, so the LLM hallucinated every number. The
reference SKILL the user maintains works because it computes RSI / MACD
/ KDJ / SMA / S/R / market cap / PE / etc. up-front and crams them into
the prompt — the LLM is a narrative generator over real numbers, not a
guess generator.

Public API:
    build_quant_context(shared, ticker) -> str
        Returns a markdown-ish text block ready to drop into any prompt.
        Empty-data fields render as "n/a" rather than crash — so even
        a totally empty SharedData produces a valid (if sparse) block.

    QUANT_CONTEXT_DIRECTIVE: str
        The "do not invent numbers" instruction. Section runners
        concatenate this AFTER the block.

Indicators implemented (closes-only, no OHLCV dependency for portability):
    - RSI(14)            Wilder's smoothing
    - MACD(12,26,9)      EMA-based + signal line + histogram
    - KDJ(9,3,3)         period 9, smoothing 3 (needs high/low/close)
    - Bollinger(20,2)    upper/middle/lower + %B
    - ATR(14)            true range moving avg (needs high/low/close)
    - SMA20/50/200       + distance-from-price as %
    - 52w / 60d S/R      max/min of closes over those windows
    - Volume metrics     today, 5d avg, 10d avg, 20d avg, ratio
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Indicator math (no pandas dependency — pure stdlib for portability)
# ---------------------------------------------------------------------------


def _ema(series: list[float], period: int) -> list[float]:
    """Exponential moving average. Returns same length as input; first
    `period-1` slots filled with the SMA seed value at index period-1
    and NaN before that. We use float('nan') sentinel."""
    if not series or len(series) < period:
        return [float("nan")] * len(series)
    out = [float("nan")] * len(series)
    alpha = 2.0 / (period + 1)
    out[period - 1] = sum(series[:period]) / period
    for i in range(period, len(series)):
        out[i] = alpha * series[i] + (1 - alpha) * out[i - 1]
    return out


def _wilder(series: list[float], period: int) -> list[float]:
    """Wilder's smoothing (used by RSI and ATR). alpha = 1/period."""
    if not series or len(series) < period:
        return [float("nan")] * len(series)
    out = [float("nan")] * len(series)
    out[period - 1] = sum(series[:period]) / period
    for i in range(period, len(series)):
        out[i] = (out[i - 1] * (period - 1) + series[i]) / period
    return out


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    avg_gain = _wilder(gains, period)[-1]
    avg_loss = _wilder(losses, period)[-1]
    if avg_loss == 0 or math.isnan(avg_gain) or math.isnan(avg_loss):
        return None
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(closes: list[float], fast: int = 12, slow: int = 26, sig: int = 9):
    if len(closes) < slow + sig:
        return None, None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = [
        f - s if not (math.isnan(f) or math.isnan(s)) else float("nan")
        for f, s in zip(ema_fast, ema_slow)
    ]
    # Signal = EMA of MACD line over `sig`
    valid_macd = [m for m in macd_line if not math.isnan(m)]
    if len(valid_macd) < sig:
        return macd_line[-1], None, None
    signal_partial = _ema(valid_macd, sig)
    signal_last = signal_partial[-1]
    macd_last = macd_line[-1]
    hist = macd_last - signal_last
    return macd_last, signal_last, hist


def _kdj(highs: list[float], lows: list[float], closes: list[float],
         n: int = 9, k_sm: int = 3, d_sm: int = 3):
    """Returns (K, D, J) last values. Standard A-share / TradingView KDJ."""
    if len(closes) < n:
        return None, None, None
    rsv = []
    for i in range(n - 1, len(closes)):
        h = max(highs[i - n + 1:i + 1])
        l = min(lows[i - n + 1:i + 1])
        rsv.append(100 * (closes[i] - l) / (h - l)) if h != l else rsv.append(50.0)
    # K = SMA of RSV smoothing k_sm (commonly EMA with alpha=1/3)
    k = [50.0]
    for r in rsv:
        k.append((2 * k[-1] + r) / 3)
    d = [50.0]
    for kv in k[1:]:
        d.append((2 * d[-1] + kv) / 3)
    j_last = 3 * k[-1] - 2 * d[-1]
    return k[-1], d[-1], j_last


def _bollinger(closes: list[float], period: int = 20, stddev: float = 2.0):
    if len(closes) < period:
        return None, None, None, None
    window = closes[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    sd = math.sqrt(var)
    upper = mean + stddev * sd
    lower = mean - stddev * sd
    pct_b = (closes[-1] - lower) / (upper - lower) if upper != lower else 0.5
    return upper, mean, lower, pct_b


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    trs: list[float] = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    smoothed = _wilder(trs, period)[-1]
    return smoothed if not math.isnan(smoothed) else None


def _sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _ret_over(closes: list[float], n: int) -> float | None:
    """Simple return over the last ``n`` bars; None if insufficient history."""
    if len(closes) < n + 1:
        return None
    a, b = closes[-n - 1], closes[-1]
    return (b / a - 1.0) if a else None


# ---------------------------------------------------------------------------
# Helpers to coerce Price / FinancialMetrics objects to plain floats
# ---------------------------------------------------------------------------


def _get(obj: Any, attr: str, default=None):
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _ohlcv(prices: list) -> tuple[list[float], list[float], list[float], list[float]]:
    """Extract opens/highs/lows/closes/volumes lists from list[Price]-like
    objects. Returns (highs, lows, closes, volumes)."""
    highs, lows, closes, vols = [], [], [], []
    for p in prices or []:
        c = _get(p, "close")
        if c is None:
            continue
        h = _get(p, "high", c)
        l = _get(p, "low", c)
        v = _get(p, "volume", 0)
        try:
            highs.append(float(h))
            lows.append(float(l))
            closes.append(float(c))
            vols.append(float(v) if v is not None else 0.0)
        except (TypeError, ValueError):
            continue
    return highs, lows, closes, vols


def _fmt_pct(num: float | None, digits: int = 1) -> str:
    if num is None or (isinstance(num, float) and math.isnan(num)):
        return "n/a"
    return f"{num * 100:+.{digits}f}%"


def _fmt(num: float | None, digits: int = 2) -> str:
    if num is None or (isinstance(num, float) and math.isnan(num)):
        return "n/a"
    return f"{num:.{digits}f}"


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_quant_context(shared: Any, ticker: str) -> str:
    """Return a markdown-ish QUANT CONTEXT block for one ticker.

    Best-effort: any missing field renders as `n/a` rather than crash.
    Caller is expected to concatenate `QUANT_CONTEXT_DIRECTIVE` after
    this block in the prompt.
    """
    if shared is None:
        return "=== QUANT CONTEXT ===\n(no shared data available)\n=== END CONTEXT ===\n"

    prices = _get(shared, "prices") or []
    financials = _get(shared, "financials") or []
    earnings = _get(shared, "earnings_history") or []
    facts = _get(shared, "company_facts") or {}
    news = _get(shared, "news") or []
    analyst_targets = _get(shared, "analyst_targets")
    scan_date = _get(shared, "scan_date") or "today"

    highs, lows, closes, vols = _ohlcv(prices)
    _, _, sector_closes, _ = _ohlcv(_get(shared, "sector_etf_prices") or [])
    _, _, spy_closes, _ = _ohlcv(_get(shared, "spy_prices") or [])

    # ---- price + trend ----
    last_close = closes[-1] if closes else None
    prev_close = closes[-2] if len(closes) >= 2 else None
    today_pct = ((last_close / prev_close - 1) if (last_close and prev_close) else None)
    sma20, sma50, sma200 = _sma(closes, 20), _sma(closes, 50), _sma(closes, 200)
    dist_sma20 = (last_close / sma20 - 1) if (last_close and sma20) else None
    dist_sma50 = (last_close / sma50 - 1) if (last_close and sma50) else None
    dist_sma200 = (last_close / sma200 - 1) if (last_close and sma200) else None

    # ---- 52w / 60d support resistance ----
    hi52 = max(closes[-252:]) if len(closes) >= 5 else None
    lo52 = min(closes[-252:]) if len(closes) >= 5 else None
    hi60 = max(closes[-60:]) if len(closes) >= 5 else None
    lo60 = min(closes[-60:]) if len(closes) >= 5 else None

    # ---- volume ----
    v_today = vols[-1] if vols else None
    v5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else None
    v10 = sum(vols[-10:]) / 10 if len(vols) >= 10 else None
    v20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else None
    vol_ratio = (v_today / v20) if (v_today and v20) else None

    # ---- indicators ----
    rsi = _rsi(closes, 14)
    macd_v, macd_sig, macd_hist = _macd(closes)
    kdj_k, kdj_d, kdj_j = _kdj(highs, lows, closes)
    bb_u, bb_m, bb_l, bb_pct = _bollinger(closes)
    atr = _atr(highs, lows, closes, 14)
    atr_pct = (atr / last_close) if (atr and last_close) else None

    # ---- fundamentals ----
    fin = financials[0] if financials else None
    pe = _get(fin, "price_to_earnings_ratio")
    pb = _get(fin, "price_to_book_ratio")
    ps = _get(fin, "price_to_sales_ratio")
    roe = _get(fin, "return_on_equity")
    gm = _get(fin, "gross_margin")
    nm = _get(fin, "net_margin")
    rev_growth = _get(fin, "revenue_growth")
    eps_growth = _get(fin, "earnings_per_share_growth")
    debt_eq = _get(fin, "debt_to_equity")
    market_cap = _get(fin, "market_cap") or _get(facts, "market_cap")
    # Previously-unsurfaced fields the LLM was inventing from memory. They
    # already exist on FinancialMetrics — surface them so the narrative cites
    # real values instead of fabricating PEG / EV multiples / FCF.
    ev = _get(fin, "enterprise_value")
    ev_ebitda = _get(fin, "enterprise_value_to_ebitda_ratio")
    ev_rev = _get(fin, "enterprise_value_to_revenue_ratio")
    peg = _get(fin, "peg_ratio")
    fcf_yield = _get(fin, "free_cash_flow_yield")
    fcf_ps = _get(fin, "free_cash_flow_per_share")
    op_margin = _get(fin, "operating_margin")
    roa = _get(fin, "return_on_assets")
    roic = _get(fin, "return_on_invested_capital")
    current_ratio = _get(fin, "current_ratio")
    quick_ratio = _get(fin, "quick_ratio")
    interest_cov = _get(fin, "interest_coverage")

    # ---- relative performance vs sector ETF + SPY (grounded, not from memory) ----
    def _rel(n):
        t = _ret_over(closes, n)
        s = _ret_over(sector_closes, n)
        m = _ret_over(spy_closes, n)
        return (
            t,
            (t - s) if (t is not None and s is not None) else None,
            (t - m) if (t is not None and m is not None) else None,
        )
    t20, rel_sec_20, rel_spy_20 = _rel(20)
    t60, rel_sec_60, rel_spy_60 = _rel(60)

    # ---- earnings ----
    last_q = earnings[0] if earnings else None
    q_eps = _get(_get(last_q, "quarterly"), "earnings_per_share") if last_q else None
    q_rev = _get(_get(last_q, "quarterly"), "revenue") if last_q else None
    q_period = _get(last_q, "report_period") if last_q else None

    # ---- company facts ----
    name = _get(facts, "name") or ticker
    sector = _get(facts, "sector") or "n/a"
    industry = _get(facts, "industry") or "n/a"
    exchange = _get(facts, "exchange") or "n/a"

    # ---- analyst ----
    a_mean = _get(analyst_targets, "mean_target") if analyst_targets else None
    a_high = _get(analyst_targets, "high_target") if analyst_targets else None
    a_low = _get(analyst_targets, "low_target") if analyst_targets else None
    upside = ((a_mean / last_close - 1) if (a_mean and last_close) else None)

    # ---- news (top 12) ----
    news_lines = []
    for n in (news or [])[:12]:
        title = _get(n, "title", "")
        date = _get(n, "date", "")
        src = _get(n, "source", "")
        if title:
            news_lines.append(f"  - {date} [{src}] {title}")
    news_block = "\n".join(news_lines) if news_lines else "  (no recent news in window)"

    # ---- assemble ----
    cap_str = _fmt(market_cap, 0) if market_cap else "n/a"

    body = f"""=== QUANT CONTEXT (as of {scan_date}) ===

COMPANY
  ticker: {ticker}
  name: {name}
  sector: {sector}
  industry: {industry}
  exchange: {exchange}

PRICE
  last_close: {_fmt(last_close)}
  today_pct_change: {_fmt_pct(today_pct)}
  market_cap: {cap_str}
  bars_available: {len(closes)}

TREND (moving averages)
  sma20:  {_fmt(sma20)}   (distance from price: {_fmt_pct(dist_sma20)})
  sma50:  {_fmt(sma50)}   (distance from price: {_fmt_pct(dist_sma50)})
  sma200: {_fmt(sma200)}  (distance from price: {_fmt_pct(dist_sma200)})

SUPPORT / RESISTANCE
  52w_high: {_fmt(hi52)}
  52w_low:  {_fmt(lo52)}
  60d_high: {_fmt(hi60)}
  60d_low:  {_fmt(lo60)}

VOLUME
  today: {_fmt(v_today, 0)}
  5d_avg: {_fmt(v5, 0)}
  10d_avg: {_fmt(v10, 0)}
  20d_avg: {_fmt(v20, 0)}
  ratio (today/20d): {_fmt(vol_ratio, 2)}

TECHNICAL INDICATORS (current values)
  RSI(14): {_fmt(rsi, 1)}            {"overbought" if (rsi and rsi > 70) else ("oversold" if (rsi and rsi < 30) else "neutral")}
  MACD(12,26,9): line {_fmt(macd_v, 3)}, signal {_fmt(macd_sig, 3)}, hist {_fmt(macd_hist, 3)}
  KDJ(9,3,3): K {_fmt(kdj_k, 1)}, D {_fmt(kdj_d, 1)}, J {_fmt(kdj_j, 1)}
  Bollinger(20,2): upper {_fmt(bb_u)}, middle {_fmt(bb_m)}, lower {_fmt(bb_l)}, %B {_fmt(bb_pct, 2)}
  ATR(14): {_fmt(atr, 2)}  ({_fmt_pct(atr_pct, 1)} of price)

FUNDAMENTALS (latest quarter on file)
  P/E: {_fmt(pe, 2)}
  P/B: {_fmt(pb, 2)}
  P/S: {_fmt(ps, 2)}
  PEG: {_fmt(peg, 2)}
  EV/EBITDA: {_fmt(ev_ebitda, 2)}
  EV/Revenue: {_fmt(ev_rev, 2)}
  enterprise_value: {_fmt(ev, 0) if ev else "n/a"}
  FCF_yield: {_fmt_pct(fcf_yield)}
  FCF_per_share: {_fmt(fcf_ps, 2)}
  gross_margin: {_fmt_pct(gm)}
  operating_margin: {_fmt_pct(op_margin)}
  net_margin: {_fmt_pct(nm)}
  ROE: {_fmt_pct(roe)}
  ROA: {_fmt_pct(roa)}
  ROIC: {_fmt_pct(roic)}
  revenue_growth_yoy: {_fmt_pct(rev_growth)}
  eps_growth_yoy: {_fmt_pct(eps_growth)}
  debt_to_equity: {_fmt(debt_eq, 2)}
  current_ratio: {_fmt(current_ratio, 2)}
  quick_ratio: {_fmt(quick_ratio, 2)}
  interest_coverage: {_fmt(interest_cov, 2)}

RELATIVE PERFORMANCE (price return vs benchmarks — use these for any "outperformed/underperformed" claim)
  ticker 20d return: {_fmt_pct(t20)}   vs sector ETF: {_fmt_pct(rel_sec_20)}   vs SPY: {_fmt_pct(rel_spy_20)}
  ticker 60d return: {_fmt_pct(t60)}   vs sector ETF: {_fmt_pct(rel_sec_60)}   vs SPY: {_fmt_pct(rel_spy_60)}

LAST EARNINGS REPORT
  period: {q_period or "n/a"}
  EPS: {_fmt(q_eps, 2)}
  revenue: {_fmt(q_rev, 0)}

ANALYST CONSENSUS (forward target prices)
  mean: {_fmt(a_mean)}     (implied upside: {_fmt_pct(upside)})
  high: {_fmt(a_high)}
  low:  {_fmt(a_low)}

RECENT NEWS (top 12 headlines — the ONLY source for company-specific events/products/holdings)
{news_block}

=== END QUANT CONTEXT ===
"""
    return body


# Strong anti-hallucination directive. Appended AFTER the QUANT CONTEXT
# in every section's prompt. Phrased as a hard rule with rationale.

QUANT_CONTEXT_DIRECTIVE = """
CRITICAL DATA RULES (read before writing):
  1. Every numeric value you cite — prices, percentages, ratios, multiples,
     technical indicator readings, market cap, EPS, revenue, target prices —
     MUST come from the QUANT CONTEXT block above. Do NOT invent numbers
     based on what you "think" the company's metrics look like.
  2. When a field shows "n/a" in the QUANT CONTEXT, write "data unavailable"
     rather than guessing. It is better to omit a metric than to invent one.
  3. For derived numbers (e.g. distance from a moving average, % above
     support), compute from the values given — do not estimate.
  4. Phrase narrative around the ACTUAL numbers. e.g. "RSI(14) at 47.3
     is neutral" — NOT "RSI is around 50".
  5. If the QUANT CONTEXT is sparse (many n/a's), state explicitly in
     your output that data coverage is limited and which fields are
     missing. Do NOT fabricate to fill the gap.
  6. NON-NUMERIC company facts — product metrics (ARR, MAU, user/subscriber
     counts, bookings), institutional holdings / 13F filings, M&A or
     acquisitions, executive / leadership changes, named competitor
     statistics, or specific analyst-firm calls — may ONLY be stated if they
     appear in the RECENT NEWS headlines above. Do NOT recall them from
     training memory: that knowledge is stale (training cutoff) and
     unverifiable. If it is not in the news, omit it or tag it "(unverified)".
  7. For relative performance ("outperformed / underperformed the sector or
     the market by X%"), use ONLY the RELATIVE PERFORMANCE block. Do NOT name
     a specific thematic benchmark ETF unless it is the one provided.

"""
