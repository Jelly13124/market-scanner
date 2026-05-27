"""SnapshotBuilder — pull per-ticker metrics into SnapshotRow.

US path: yfinance .info + .history + .earnings_dates.
CN path: see Task 4 — mootdx + akshare wrapper (`ashare_metrics`).

Per-ticker exceptions are caught + logged; the loop never aborts on
one bad ticker. This matches the v2/scanner runner invariant.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Literal

import yfinance as yf

from app.backend.repositories.screener_repository import SnapshotRow
from v2.scanner.universes.loader import load_universe

logger = logging.getLogger(__name__)


def _to_decimal(value, *, scale: int | None = None) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if scale is not None:
            q = Decimal(10) ** -scale
            d = d.quantize(q)
        return d
    except (ValueError, ArithmeticError):
        return None


def _to_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


_RATING_NORMALIZE = {
    "strong_buy": "strong_buy",
    "strongbuy": "strong_buy",
    "buy": "buy",
    "outperform": "buy",
    "hold": "neutral",
    "neutral": "neutral",
    "underperform": "sell",
    "sell": "sell",
    "strong_sell": "strong_sell",
    "strongsell": "strong_sell",
}


def _normalize_rating(raw: str | None) -> str | None:
    if not raw:
        return None
    return _RATING_NORMALIZE.get(raw.lower().replace(" ", ""), None)


class SnapshotBuilder:
    """Iterate a universe; build one SnapshotRow per ticker."""

    def __init__(self, *, ashare_metrics=None) -> None:
        # ashare_metrics is injected in Task 4; US path doesn't need it.
        self._ashare = ashare_metrics

    # ------------------------------------------------------------ US ----

    def build_for_ticker_us(self, ticker: str, asof: date) -> SnapshotRow:
        """Pull yfinance metrics into SnapshotRow. Missing fields → None."""
        t = yf.Ticker(ticker)
        info = getattr(t, "info", None) or {}

        # .history(period='1y') for perf windows
        try:
            hist = t.history(period="1y")
        except Exception as e:
            logger.warning("yfinance history failed for %s: %s", ticker, e)
            hist = None

        perf = self._compute_perf(hist) if hist is not None and not hist.empty else {}

        # earnings dates
        recent_ed, upcoming_ed = self._extract_earnings_dates(t, asof)

        return SnapshotRow(
            ticker=ticker,
            market="US",
            snapshot_date=asof,
            price=_to_decimal(info.get("regularMarketPrice"), scale=4),
            prev_close=_to_decimal(info.get("regularMarketPreviousClose"), scale=4),
            change_pct=self._compute_change_pct(info),
            volume=_to_int(info.get("regularMarketVolume")),
            avg_volume_10d=_to_int(info.get("averageDailyVolume10Day")),
            rel_volume=self._compute_rel_volume(info),
            market_cap=_to_decimal(info.get("marketCap"), scale=2),
            pe_ttm=_to_decimal(info.get("trailingPE"), scale=3),
            pe_forward=_to_decimal(info.get("forwardPE"), scale=3),
            pb=_to_decimal(info.get("priceToBook"), scale=3),
            ps=_to_decimal(info.get("priceToSalesTrailing12Months"), scale=3),
            peg=_to_decimal(info.get("pegRatio"), scale=3),
            eps_growth_yoy=_to_decimal(info.get("earningsGrowth"), scale=4),
            revenue_growth_yoy=_to_decimal(info.get("revenueGrowth"), scale=4),
            roe=_to_decimal(info.get("returnOnEquity"), scale=4),
            profit_margin=_to_decimal(info.get("profitMargins"), scale=4),
            dividend_yield_pct=_to_decimal(info.get("dividendYield"), scale=4),
            beta=_to_decimal(info.get("beta"), scale=3),
            sector=info.get("sector"),
            industry=info.get("industry"),
            exchange=info.get("exchange"),
            analyst_rating=_normalize_rating(info.get("recommendationKey")),
            analyst_count=_to_int(info.get("numberOfAnalystOpinions")),
            target_mean_price=_to_decimal(info.get("targetMeanPrice"), scale=4),
            recent_earnings_date=recent_ed,
            upcoming_earnings_date=upcoming_ed,
            perf_1d=perf.get("perf_1d"),
            perf_5d=perf.get("perf_5d"),
            perf_1m=perf.get("perf_1m"),
            perf_3m=perf.get("perf_3m"),
            perf_ytd=perf.get("perf_ytd"),
            perf_1y=perf.get("perf_1y"),
            data_source="yfinance",
        )

    # ----------------------------------------------------- helpers ----

    def _compute_change_pct(self, info: dict) -> Decimal | None:
        p = info.get("regularMarketPrice")
        pc = info.get("regularMarketPreviousClose")
        if p is None or pc is None or pc == 0:
            return None
        return _to_decimal((p - pc) / pc, scale=4)

    def _compute_rel_volume(self, info: dict) -> Decimal | None:
        v = info.get("regularMarketVolume")
        avg = info.get("averageDailyVolume10Day")
        if v is None or not avg:
            return None
        return _to_decimal(v / avg, scale=3)

    def _compute_perf(self, hist) -> dict:
        """Closes-based perf for {1d, 5d, 1m, 3m, ytd, 1y}."""
        closes = hist["Close"].dropna()
        if closes.empty:
            return {}
        last = float(closes.iloc[-1])

        def _ago(days: int) -> Decimal | None:
            if len(closes) <= days:
                return None
            prev = float(closes.iloc[-1 - days])
            if prev == 0:
                return None
            return _to_decimal((last - prev) / prev, scale=4)

        # YTD = first trading day of current year
        try:
            year_start = closes.index[closes.index.year == closes.index[-1].year][0]
            ytd_prev = float(closes.loc[year_start])
            ytd = _to_decimal((last - ytd_prev) / ytd_prev, scale=4) if ytd_prev else None
        except Exception:
            ytd = None

        return {
            "perf_1d":  _ago(1),
            "perf_5d":  _ago(5),
            "perf_1m":  _ago(21),
            "perf_3m":  _ago(63),
            "perf_ytd": ytd,
            "perf_1y":  _ago(252),
        }

    def _extract_earnings_dates(self, t, asof: date) -> tuple[date | None, date | None]:
        try:
            ed = getattr(t, "earnings_dates", None)
            if ed is None or ed.empty:
                return None, None
            dates = sorted(d.date() for d in ed.index.to_pydatetime())
            past = [d for d in dates if d <= asof]
            future = [d for d in dates if d > asof]
            recent = past[-1] if past else None
            upcoming = future[0] if future else None
            return recent, upcoming
        except Exception as e:
            logger.debug("earnings_dates parse failed: %s", e)
            return None, None

    # --------------------------------------------------- universe ----

    def build_for_universe(
        self,
        market: Literal["US", "CN"],
        universe_kind: str,
        asof: date,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[SnapshotRow]:
        tickers = load_universe(universe_kind)
        if not tickers:
            logger.warning("Empty universe for kind=%s", universe_kind)
            return []

        builder = (self.build_for_ticker_us if market == "US"
                   else self.build_for_ticker_cn)

        rows: list[SnapshotRow] = []
        for i, t in enumerate(tickers, 1):
            try:
                rows.append(builder(t, asof))
            except Exception as e:
                logger.warning("Snapshot failed for %s: %s", t, e)
            if on_progress is not None:
                on_progress(i, len(tickers))
        return rows

    # CN path injected in Task 4
    def build_for_ticker_cn(self, ticker: str, asof: date) -> SnapshotRow:
        raise NotImplementedError("CN path lands in Task 4 (ashare_metrics)")
