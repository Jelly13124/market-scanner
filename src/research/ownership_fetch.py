"""Ownership data fetch from yfinance (best-effort).

Surfaces who owns a stock — insider %, institutional %, the institutional
holder count, and the top institutional holders — for the Ownership Structure
report section. yfinance exposes this via three attributes on a ``Ticker``:

  * ``.info`` — ``heldPercentInsiders`` / ``heldPercentInstitutions`` /
    ``sharesOutstanding`` (fractions 0..1 for the two pct fields).
  * ``.major_holders`` — a small DataFrame; recent yfinance keys an
    ``institutionsCount`` row in its ``Value`` column.
  * ``.institutional_holders`` — a DataFrame with ``Holder`` + ``pctHeld``
    (fraction 0..1) columns; we take the top rows.

NOTHING here raises. The only network touch (yfinance) is wrapped in a single
try/except so any failure — offline, delisted ticker, schema drift — degrades
to an all-``None`` dict. yfinance is imported lazily *inside* the function so
importing this module stays offline (tests inject a fake ``sys.modules``
entry).
"""

from __future__ import annotations

# How many top institutional holders to surface in the report block.
_TOP_HOLDERS_N = 10


def _none_result() -> dict:
    """The canonical 'no data' shape — every key present, all ``None``."""
    return {
        "insider_pct": None,
        "institution_pct": None,
        "institution_count": None,
        "top_holders": None,
        "shares_outstanding": None,
    }


def _coerce_float(v) -> float | None:
    """Best-effort float coercion (drops NaN / non-numeric)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _coerce_int(v) -> int | None:
    f = _coerce_float(v)
    return int(f) if f is not None else None


def _institutions_count(major_holders) -> int | None:
    """Pull ``institutionsCount`` out of the ``.major_holders`` DataFrame.

    yfinance versions differ: the modern shape is a DataFrame indexed by metric
    name (``institutionsCount``, ``insidersPercentHeld``, ...) with a single
    ``Value`` column. Be liberal — try the labelled cell, fall back to scanning
    the frame for the row. Returns ``None`` on any miss.
    """
    if major_holders is None:
        return None
    try:
        # Modern shape: df.loc["institutionsCount", "Value"].
        if "institutionsCount" in getattr(major_holders, "index", []):
            col = "Value" if "Value" in getattr(major_holders, "columns", []) else major_holders.columns[0]
            return _coerce_int(major_holders.loc["institutionsCount", col])
    except Exception:  # noqa: BLE001 — best-effort; fall through to None
        pass
    return None


def _top_holders(institutional_holders) -> list[dict] | None:
    """Top institutional holders as ``[{name, pct}, ...]`` (pct a 0..1 fraction).

    Returns ``None`` when the ``.institutional_holders`` DataFrame is missing,
    and an empty list when it exists but has no usable rows.
    """
    if institutional_holders is None:
        return None
    try:
        if getattr(institutional_holders, "empty", False):
            return []
        cols = list(getattr(institutional_holders, "columns", []))
        name_col = "Holder" if "Holder" in cols else (cols[0] if cols else None)
        pct_col = "pctHeld" if "pctHeld" in cols else None
        if name_col is None:
            return []
        rows: list[dict] = []
        for _, row in institutional_holders.head(_TOP_HOLDERS_N).iterrows():
            name = row.get(name_col)
            pct = _coerce_float(row.get(pct_col)) if pct_col else None
            if name is None:
                continue
            rows.append({"name": str(name), "pct": pct})
        return rows
    except Exception:  # noqa: BLE001 — best-effort; treat as no usable rows
        return []


def fetch_ownership(ticker: str) -> dict:
    """Best-effort ownership snapshot for ``ticker`` from yfinance.

    Returns a dict with keys ``insider_pct`` (0..1 fraction), ``institution_pct``
    (0..1 fraction), ``institution_count`` (int), ``top_holders``
    (``list[{name, pct}]`` or ``None``), and ``shares_outstanding`` (int).

    Never raises: any failure — network, delisted ticker, yfinance schema drift
    — yields the all-``None`` shape so the calling section degrades to a "data
    unavailable" note while still reporting the ticker.
    """
    try:
        import yfinance as yf  # lazy: keep module import offline

        tk = yf.Ticker(ticker)
        info = getattr(tk, "info", None) or {}

        insider_pct = _coerce_float(info.get("heldPercentInsiders"))
        institution_pct = _coerce_float(info.get("heldPercentInstitutions"))
        shares_outstanding = _coerce_int(info.get("sharesOutstanding"))

        institution_count = _institutions_count(getattr(tk, "major_holders", None))
        top_holders = _top_holders(getattr(tk, "institutional_holders", None))

        return {
            "insider_pct": insider_pct,
            "institution_pct": institution_pct,
            "institution_count": institution_count,
            "top_holders": top_holders,
            "shares_outstanding": shares_outstanding,
        }
    except Exception as exc:  # noqa: BLE001 — best-effort; never raise
        print(f"[ownership_fetch] fetch failed for {ticker!r}: {exc}")
        return _none_result()
