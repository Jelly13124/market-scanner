"""AshareMetrics — thin wrapper around mootdx + akshare for the CN path.

We keep this separate from snapshot_builder.py so the mootdx /
akshare imports are localized (heavy + optional install). Returns plain
dicts; SnapshotBuilder maps them to SnapshotRow.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


_AK_FIELD_MAP = {
    "总市值": "market_cap",
    "市盈率(动)": "pe_ttm",
    "市净率": "pb",
    "市销率": "ps",
    "PEG值": "peg",
    "净资产收益率": "roe",
    "销售毛利率": "profit_margin",
    "股息率": "dividend_yield_pct",
    "行业": "sector",
    "Beta": "beta",
}


class AshareMetrics:
    """Wraps mootdx (quotes) + akshare (fundamentals + earnings).

    Mootdx returns volume in 手 (1 手 = 100 shares); we multiply.
    Akshare's stock_individual_info_em returns a tall DataFrame
    [item, value]; we map known item names to our dict keys.
    """

    def __init__(self, *, mootdx_client=None, akshare_module=None) -> None:
        if mootdx_client is None:
            from mootdx.quotes import Quotes
            mootdx_client = Quotes.factory(market="std")
        if akshare_module is None:
            import akshare as akshare_module
        self._mootdx = mootdx_client
        self._ak = akshare_module

    @staticmethod
    def _strip_suffix(symbol: str) -> str:
        return symbol.split(".", 1)[0]

    def get_quote(self, symbol: str) -> dict[str, Any]:
        code = self._strip_suffix(symbol)
        try:
            q = self._mootdx.quotes(symbol=code)
        except Exception as e:
            logger.debug("mootdx.quotes failed for %s: %s", symbol, e)
            q = None
        if not q:
            return {"price": None, "prev_close": None,
                    "volume": None, "avg_volume_10d": None}
        price = q.get("price") or q.get("now")
        prev = q.get("last_close") or q.get("prev_close")
        vol_lots = q.get("vol") or q.get("volume") or 0
        return {
            "price": price,
            "prev_close": prev,
            "volume": int(vol_lots) * 100 if vol_lots else None,
            "avg_volume_10d": None,  # mootdx single-quote has no 10d avg
        }

    def get_fundamentals(self, symbol: str) -> dict[str, Any]:
        code = self._strip_suffix(symbol)
        try:
            df = self._ak.stock_individual_info_em(symbol=code)
        except Exception as e:
            logger.debug("akshare fundamentals failed for %s: %s", symbol, e)
            return {}
        if df is None or df.empty:
            return {}
        out: dict[str, Any] = {}
        for _, r in df.iterrows():
            key = _AK_FIELD_MAP.get(str(r.get("item", "")))
            if key:
                out[key] = r.get("value")
        # Exchange inferred from symbol
        if symbol.endswith(".SH") or code.startswith(("6", "9")):
            out["exchange"] = "SSE"
        elif symbol.endswith(".SZ") or code.startswith(("0", "3")):
            out["exchange"] = "SZSE"
        elif symbol.endswith(".BJ") or code.startswith("8"):
            out["exchange"] = "BSE"
        return out

    def get_perf_windows(self, symbol: str, asof: date) -> dict[str, Any]:
        """Compute perf_{1d,5d,1m,3m,ytd,1y} from akshare daily hist."""
        code = self._strip_suffix(symbol)
        try:
            df = self._ak.stock_zh_a_hist(symbol=code, period="daily",
                                          adjust="qfq",
                                          end_date=asof.strftime("%Y%m%d"))
        except Exception as e:
            logger.debug("akshare hist failed for %s: %s", symbol, e)
            return {}
        if df is None or df.empty or "收盘" not in df.columns:
            return {}
        closes = df["收盘"].astype(float).tolist()
        if not closes:
            return {}
        last = closes[-1]

        def _ago(n: int):
            if len(closes) <= n:
                return None
            prev = closes[-1 - n]
            return (last - prev) / prev if prev else None

        ytd = None
        try:
            dates = df["日期"].astype(str).tolist()
            this_year = str(asof.year)
            start_idx = next(i for i, d in enumerate(dates) if d.startswith(this_year))
            prev = closes[start_idx]
            ytd = (last - prev) / prev if prev else None
        except StopIteration:
            ytd = None

        return {
            "perf_1d": _ago(1), "perf_5d": _ago(5),
            "perf_1m": _ago(21), "perf_3m": _ago(63),
            "perf_ytd": ytd, "perf_1y": _ago(252),
        }

    def get_earnings_dates(self, symbol: str) -> tuple[date | None, date | None]:
        """Returns (recent, upcoming). Both can be None."""
        # akshare's earnings calendar endpoint is unstable; v1 returns None.
        # Phase 2 will wire akshare.stock_yjbb_em if needed.
        return (None, None)
