"""Offline tests for the FINRA Reg-SHO short-volume ("off-exchange pressure")
signal.

No network: the per-day fetch is exercised only through an injected stub
``day_fetch``, and ``_fetch_finra_day`` itself is tested with a stub ``http_get``.
``requests`` is never imported or called here.
"""

from __future__ import annotations

from src.research.institutional_flow import (
    _fetch_finra_day,
    _parse_finra_short_volume,
    fetch_short_volume,
)


# --------------------------------------------------------------------------- #
# Canned FINRA file bodies (pipe-delimited, with header row).
# --------------------------------------------------------------------------- #

_HEADER = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"


def _file(date: str, rows: list[str]) -> str:
    """Assemble a FINRA-style file body: header + given data rows."""
    return "\n".join([_HEADER, *rows]) + "\n"


# AAPL appears on TWO market rows on this day -> must aggregate:
#   short = 300 + 200 = 500 ; total = 600 + 400 = 1000 ; short_pct = 0.50
_DAY_NEWEST = _file(
    "20260605",
    [
        "20260605|AAPL|300|0|600|Q",
        "20260605|AAPL|200|10|400|B",  # second Market row for AAPL
        "20260605|MSFT|100|0|500|Q",
    ],
)

# Single AAPL row: short 400 / total 1000 = 0.40
_DAY_MID = _file(
    "20260604",
    [
        "20260604|AAPL|400|0|1000|Q",
        "20260604|MSFT|250|0|500|Q",
    ],
)

# Single AAPL row: short 360 / total 1000 = 0.36 ; plus a malformed row.
_DAY_OLD = _file(
    "20260603",
    [
        "20260603|AAPL|360|0|1000|Q",
        "garbage-without-pipes",  # malformed -> skipped
        "20260603|AAPL|bad|0|notanum|Q",  # non-numeric volumes -> skipped
    ],
)


def _stub_day_fetch(mapping: dict[str, str | None]):
    """Build a ``day_fetch(date_str) -> text|None`` stub from a YYYYMMDD map."""

    def _fetch(date_str: str):
        return mapping.get(date_str)

    return _fetch


# --------------------------------------------------------------------------- #
# _parse_finra_short_volume — aggregation + malformed-row handling
# --------------------------------------------------------------------------- #


def test_parse_aggregates_multiple_market_rows():
    agg = _parse_finra_short_volume(_DAY_NEWEST, "AAPL")
    assert agg is not None
    short_v, total_v = agg
    # 300+200 short, 600+400 total across AAPL's two Market rows.
    assert short_v == 500.0
    assert total_v == 1000.0


def test_parse_skips_malformed_rows():
    # _DAY_OLD has a no-pipe line and a non-numeric AAPL line; only the one
    # valid AAPL row (360/1000) should count.
    agg = _parse_finra_short_volume(_DAY_OLD, "AAPL")
    assert agg == (360.0, 1000.0)


def test_parse_missing_ticker_returns_none():
    assert _parse_finra_short_volume(_DAY_NEWEST, "TSLA") is None


def test_parse_is_case_insensitive():
    assert _parse_finra_short_volume(_DAY_NEWEST, "aapl") == (500.0, 1000.0)


def test_parse_empty_text_returns_none():
    assert _parse_finra_short_volume("", "AAPL") is None


# --------------------------------------------------------------------------- #
# fetch_short_volume — multi-day walk, skipping no-file days, trend/avg/n_days
# --------------------------------------------------------------------------- #


def test_fetch_short_volume_aggregates_and_trends_rising():
    # Anchor 2026-06-06 (a no-file day, e.g. weekend) -> walk back.
    #   06-06 -> None (skipped)
    #   06-05 -> 0.50 (latest, aggregated across 2 Market rows)
    #   06-04 -> 0.40
    #   06-03 -> 0.36
    mapping = {
        "20260606": None,  # 403 / weekend -> skipped
        "20260605": _DAY_NEWEST,
        "20260604": _DAY_MID,
        "20260603": _DAY_OLD,
    }
    out = fetch_short_volume(
        "AAPL",
        lookback_days=10,
        today="2026-06-06",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is not None
    assert out["ticker"] == "AAPL"
    assert out["n_days"] == 3  # the None day was skipped
    assert out["date"] == "2026-06-05"  # latest available
    assert out["short_pct"] == 0.50  # aggregated latest
    assert out["short_volume"] == 500.0
    assert out["total_volume"] == 1000.0
    # avg over [0.50, 0.40, 0.36]
    assert abs(out["avg_short_pct"] - (0.50 + 0.40 + 0.36) / 3) < 1e-9
    # latest 0.50 vs older-days mean (0.38) -> rising.
    assert out["trend"] == "rising"


def test_fetch_short_volume_accepts_dashed_today():
    mapping = {"20260605": _DAY_NEWEST}
    out = fetch_short_volume(
        "AAPL",
        today="2026-06-05",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is not None
    assert out["date"] == "2026-06-05"
    # Also accepts the compact YYYYMMDD anchor form.
    out2 = fetch_short_volume("AAPL", today="20260605", day_fetch=_stub_day_fetch(mapping))
    assert out2 is not None
    assert out2["date"] == "2026-06-05"


def test_fetch_short_volume_single_day_is_flat():
    mapping = {"20260605": _DAY_NEWEST}
    out = fetch_short_volume(
        "AAPL",
        today="2026-06-05",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is not None
    assert out["n_days"] == 1
    assert out["trend"] == "flat"  # nothing older to compare
    assert out["short_pct"] == 0.50


def test_fetch_short_volume_trend_falling():
    # Latest LOW, older HIGH -> falling.
    newest_low = _file("20260605", ["20260605|AAPL|360|0|1000|Q"])  # 0.36
    older_high = _file("20260604", ["20260604|AAPL|500|0|1000|Q"])  # 0.50
    mapping = {"20260605": newest_low, "20260604": older_high}
    out = fetch_short_volume(
        "AAPL",
        today="2026-06-05",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is not None
    assert out["trend"] == "falling"


def test_fetch_short_volume_trend_flat_within_deadband():
    # 0.40 vs 0.395 -> within the 1pp dead-band -> flat.
    newest = _file("20260605", ["20260605|AAPL|400|0|1000|Q"])  # 0.400
    older = _file("20260604", ["20260604|AAPL|395|0|1000|Q"])  # 0.395
    mapping = {"20260605": newest, "20260604": older}
    out = fetch_short_volume(
        "AAPL",
        today="2026-06-05",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is not None
    assert out["trend"] == "flat"


def test_fetch_short_volume_ticker_absent_returns_none():
    # Files exist but never contain the requested ticker.
    mapping = {
        "20260605": _DAY_NEWEST,
        "20260604": _DAY_MID,
    }
    out = fetch_short_volume(
        "NVDA",
        today="2026-06-05",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is None


def test_fetch_short_volume_all_none_days_returns_none():
    # Every day is a 403/no-file -> nothing collected -> None.
    def _all_none(date_str):
        return None

    out = fetch_short_volume(
        "AAPL",
        lookback_days=5,
        today="2026-06-07",
        day_fetch=_all_none,
    )
    assert out is None


def test_fetch_short_volume_respects_lookback_window():
    # Only the 06-05 file exists, but lookback is 1 day from an anchor of 06-07,
    # so the walk only checks 06-07 (no file) -> None.
    mapping = {"20260605": _DAY_NEWEST}
    out = fetch_short_volume(
        "AAPL",
        lookback_days=1,
        today="2026-06-07",
        day_fetch=_stub_day_fetch(mapping),
    )
    assert out is None


def test_fetch_short_volume_bad_today_returns_none():
    out = fetch_short_volume("AAPL", today="not-a-date", day_fetch=_stub_day_fetch({}))
    assert out is None


# --------------------------------------------------------------------------- #
# _fetch_finra_day — stubbed http_get (no network), 200 vs 403 handling
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def test_fetch_finra_day_returns_text_on_200():
    captured = {}

    def _http_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _Resp(200, "BODY")

    out = _fetch_finra_day("20260605", http_get=_http_get)
    assert out == "BODY"
    # Correct CDN URL + browser UA + 15s timeout.
    assert captured["url"] == "https://cdn.finra.org/equity/regsho/daily/CNMSshvol20260605.txt"
    assert captured["headers"]["User-Agent"] == "Mozilla/5.0"
    assert captured["timeout"] == 15


def test_fetch_finra_day_returns_none_on_403():
    def _http_get(url, headers=None, timeout=None):
        return _Resp(403, "Forbidden")

    assert _fetch_finra_day("20260606", http_get=_http_get) is None


def test_fetch_finra_day_returns_none_on_transport_error():
    def _http_get(url, headers=None, timeout=None):
        raise RuntimeError("connection reset")

    assert _fetch_finra_day("20260605", http_get=_http_get) is None
