"""Institutional-flow signals from public options data.

First module: dealer **gamma exposure (GEX)** — the signal traders use to find
"gamma walls" (support/resistance from dealer hedging) and squeeze zones.

Dealer sign convention (the SqueezeMetrics / SpotGamma standard)
---------------------------------------------------------------
We assume dealers are **long calls / short puts** relative to the retail flow
they take the other side of, so:

    net GEX = Σ(call dollar-gamma) − Σ(put dollar-gamma)

Interpretation:
  * **positive GEX** → dealers are net *long* gamma. To stay hedged they sell
    rallies and buy dips, which *suppresses* volatility and *pins* price toward
    high-gamma strikes.
  * **negative GEX** → dealers are net *short* gamma. Hedging now *amplifies*
    moves (buy strength / sell weakness) — squeeze-prone, trend-extending.

All gamma values are expressed in **dollars per 1% move** in the underlying
(the conventional unit), via the `* spot^2 * 0.01` scaling below.

Nothing in this module raises on bad/empty input: degenerate chains collapse to
a flat, zeroed result so callers can treat it as "no signal" rather than an
error path. The only network touch (yfinance) is isolated behind an injectable
`fetch_fn` seam so the computation can be unit-tested fully offline.
"""

from __future__ import annotations

import math

# Standard-normal PDF normalising constant: 1 / sqrt(2*pi).
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)

# Default annual risk-free rate used in the Black-Scholes d1 term. 4% is a
# reasonable proxy for short-dated T-bill yields; gamma is only weakly sensitive
# to r, so this is not a load-bearing assumption.
_DEFAULT_RISK_FREE = 0.04

# Contract multiplier: one listed equity option covers 100 shares.
_CONTRACT_SIZE = 100.0


def _norm_pdf(x: float) -> float:
    """Standard-normal probability density function N'(x)."""
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


def _bs_gamma(spot: float, strike: float, iv: float, t_years: float, r: float = _DEFAULT_RISK_FREE) -> float:
    """Black-Scholes gamma for a European option.

        gamma = N'(d1) / (spot * iv * sqrt(t))
        d1    = (ln(spot/strike) + (r + iv^2/2) * t) / (iv * sqrt(t))

    Gamma is identical for a call and a put at the same strike, so a single
    function serves both legs.

    Guard: any non-physical input (iv <= 0, t <= 0, spot <= 0, strike <= 0)
    returns 0.0 rather than raising — these options simply contribute no gamma.
    """
    if iv <= 0.0 or t_years <= 0.0 or spot <= 0.0 or strike <= 0.0:
        return 0.0
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / (iv * sqrt_t)
    return _norm_pdf(d1) / (spot * iv * sqrt_t)


def _empty_gex() -> dict:
    """The canonical 'no signal' result for empty/degenerate chains."""
    return {
        "total_gex": 0.0,
        "regime": "flat",
        "call_gex": 0.0,
        "put_gex": 0.0,
        "walls": [],
        "gamma_flip": None,
    }


def compute_gex(spot: float, chains: list[dict]) -> dict:
    """Compute dealer gamma exposure from an option chain.

    Parameters
    ----------
    spot : float
        Current underlying price.
    chains : list[dict]
        One dict per option: ``{"type": "call"|"put", "strike": float,
        "open_interest": float, "iv": float, "t_years": float}``.

    Returns
    -------
    dict with keys:
        ``total_gex``  net dealer GEX (call − put), $ per 1% move.
        ``regime``     "positive" (>=0), "negative" (<0), or "flat" (no data).
        ``call_gex``   Σ call dollar-gamma.
        ``put_gex``    Σ put dollar-gamma.
        ``walls``      top-5 strikes by |aggregate call+put dollar-gamma|,
                       each ``{"strike", "gamma_dollars"}``, sorted desc.
        ``gamma_flip`` strike nearest where cumulative-by-strike net GEX
                       crosses zero (best-effort; None if not computable).

    Per-option dollar gamma is ``g * open_interest * 100 * spot^2 * 0.01``
    (gamma dollars per 1% move). Never raises — bad input is skipped, and an
    empty result is returned for degenerate chains.
    """
    if spot is None or spot <= 0.0 or not chains:
        return _empty_gex()

    call_gex = 0.0
    put_gex = 0.0
    # Per-strike aggregates. call/put magnitude for "walls"; signed net for the
    # gamma-flip crossing.
    wall_by_strike: dict[float, float] = {}
    net_by_strike: dict[float, float] = {}

    dollar_factor = _CONTRACT_SIZE * spot * spot * 0.01

    for opt in chains:
        try:
            strike = float(opt["strike"])
            iv = float(opt["iv"])
            t_years = float(opt["t_years"])
            oi = float(opt["open_interest"])
        except (KeyError, TypeError, ValueError):
            # Malformed option — skip it rather than poison the whole result.
            continue

        opt_type = str(opt.get("type", "")).lower()
        if opt_type not in ("call", "put"):
            continue

        g = _bs_gamma(spot, strike, iv, t_years)
        if g == 0.0 or oi == 0.0:
            # No gamma contribution, but still a valid (just empty) option.
            continue

        dollar_gamma = g * oi * dollar_factor

        if opt_type == "call":
            call_gex += dollar_gamma
            signed = dollar_gamma
        else:
            put_gex += dollar_gamma
            signed = -dollar_gamma

        wall_by_strike[strike] = wall_by_strike.get(strike, 0.0) + dollar_gamma
        net_by_strike[strike] = net_by_strike.get(strike, 0.0) + signed

    total_gex = call_gex - put_gex

    if not wall_by_strike:
        # Chains were non-empty but contributed no gamma (all OI/iv/t zero).
        return _empty_gex()

    walls = [{"strike": k, "gamma_dollars": v} for k, v in wall_by_strike.items()]
    walls.sort(key=lambda w: abs(w["gamma_dollars"]), reverse=True)
    walls = walls[:5]

    regime = "positive" if total_gex >= 0.0 else "negative"

    return {
        "total_gex": total_gex,
        "regime": regime,
        "call_gex": call_gex,
        "put_gex": put_gex,
        "walls": walls,
        "gamma_flip": _gamma_flip(net_by_strike),
    }


def _gamma_flip(net_by_strike: dict[float, float]) -> float | None:
    """Best-effort gamma-flip strike: the price level where cumulative net GEX
    (summed across strikes from low to high) crosses zero.

    Walking strikes low→high and accumulating the signed per-strike net gamma
    gives a running profile of dealer positioning by price. The point where that
    cumulative sum changes sign is the regime boundary ("gamma flip") traders
    watch — below it dealers are short gamma, above it long (or vice versa).

    Returns the strike nearest the crossing (the lower bracket of the sign
    change), or None if the cumulative profile never crosses zero (single
    strike, or strictly one-sided positioning).
    """
    if len(net_by_strike) < 2:
        return None

    strikes = sorted(net_by_strike)
    cumulative = 0.0
    prev_cum = 0.0
    prev_strike: float | None = None
    flip: float | None = None
    best_dist = math.inf

    for k in strikes:
        cumulative += net_by_strike[k]
        if prev_strike is not None and (prev_cum == 0.0 or (prev_cum < 0.0) != (cumulative < 0.0)):
            # Sign changed (or we sat exactly on zero) between prev_strike and k.
            # Pick whichever bracket strike has the smaller |cumulative|.
            for cand_strike, cand_cum in ((prev_strike, prev_cum), (k, cumulative)):
                dist = abs(cand_cum)
                if dist < best_dist:
                    best_dist = dist
                    flip = cand_strike
        prev_cum = cumulative
        prev_strike = k

    return flip


def _default_fetch_fn(ticker: str, max_expiries: int) -> tuple[float, list[dict]]:
    """Production data source: pull the options chain from yfinance.

    Lazily imports yfinance so the dependency is only required when actually
    fetching live data (tests inject their own ``fetch_fn`` and never import it).

    Returns ``(spot, chains)`` where ``chains`` is the list-of-dicts shape
    expected by :func:`compute_gex`. Raises on any failure; the caller in
    :func:`fetch_gamma_exposure` converts that into ``None``.
    """
    import math as _math
    from datetime import date

    import yfinance as yf  # type: ignore[import-not-found]

    tk = yf.Ticker(ticker)

    hist = tk.history(period="1d")
    spot = float(hist["Close"].iloc[-1])

    today = date.today()
    expiries = list(tk.options or [])[:max_expiries]

    chains: list[dict] = []
    for exp in expiries:
        try:
            exp_date = date.fromisoformat(exp)
        except (TypeError, ValueError):
            continue
        t_years = (exp_date - today).days / 365.0
        if t_years <= 0.0:
            continue

        oc = tk.option_chain(exp)
        for opt_type, frame in (("call", oc.calls), ("put", oc.puts)):
            if frame is None:
                continue
            for row in frame.itertuples(index=False):
                strike = float(getattr(row, "strike"))
                iv = float(getattr(row, "impliedVolatility", 0.0) or 0.0)
                oi_raw = getattr(row, "openInterest", 0.0)
                try:
                    oi = float(oi_raw)
                except (TypeError, ValueError):
                    oi = 0.0
                if _math.isnan(oi):
                    oi = 0.0
                chains.append(
                    {
                        "type": opt_type,
                        "strike": strike,
                        "open_interest": oi,
                        "iv": iv,
                        "t_years": t_years,
                    }
                )

    return spot, chains


def fetch_gamma_exposure(ticker: str, *, max_expiries: int = 8, fetch_fn=None) -> dict | None:
    """Live adapter: fetch a ticker's options chain and compute its GEX.

    Parameters
    ----------
    ticker : str
        Underlying symbol, e.g. ``"AAPL"``.
    max_expiries : int
        Number of nearest expiries to include (default 8).
    fetch_fn : callable, optional
        Injectable data seam ``fetch_fn(ticker, max_expiries) -> (spot, chains)``.
        Defaults to the yfinance-backed :func:`_default_fetch_fn`. Tests pass a
        stub so no network call happens.

    Returns
    -------
    dict | None
        ``{"ticker": ..., "spot": ..., **compute_gex(spot, chains)}`` on success,
        or ``None`` if the fetch fails (best-effort — never raises).
    """
    fn = fetch_fn or _default_fetch_fn
    try:
        spot, chains = fn(ticker, max_expiries)
    except Exception as exc:  # noqa: BLE001 — best-effort live adapter
        print(f"[institutional_flow] gamma fetch failed for {ticker!r}: {exc}")
        return None

    return {"ticker": ticker, "spot": spot, **compute_gex(spot, chains)}


# ===========================================================================
# Second signal: FINRA Reg-SHO daily short volume ("off-exchange pressure")
# ===========================================================================
#
# FINRA publishes a free, no-auth daily file of consolidated short-sale volume
# by symbol. We read it as an *off-exchange short-pressure PROXY*:
#
#     short_pct = ShortVolume / TotalVolume   (a 0..1 fraction)
#
# IMPORTANT (honesty): this is NOT true ATS/dark-pool volume. That requires the
# FINRA-authenticated *weekly* ATS files. The daily Reg-SHO short-volume feed is
# a public proxy — a large fraction is routine market-maker hedging, so the
# level is *not* directional on its own. Label it as a proxy everywhere.
#
# File: https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt
#   * Needs a browser-ish User-Agent header; bare requests can be refused.
#   * Weekends / holidays have no file → HTTP 403. We walk back day by day.
#   * Pipe-delimited; header row:
#       Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market
#   * A symbol may appear on MULTIPLE rows (one per Market code). We AGGREGATE:
#     sum ShortVolume and TotalVolume across all of a symbol's rows for the day.

# CDN endpoint template for the consolidated (CNMS) daily short-volume file.
_FINRA_REGSHO_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"

# Some servers (FINRA's CDN included) refuse requests without a browser-like
# User-Agent. A minimal one is enough.
_FINRA_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch_finra_day(date_str: str, *, http_get=None) -> str | None:
    """GET the FINRA Reg-SHO daily short-volume file for ``date_str``.

    Parameters
    ----------
    date_str : str
        The trading date as ``YYYYMMDD`` (the format embedded in the filename).
    http_get : callable, optional
        Injectable HTTP seam ``http_get(url, headers=, timeout=) -> response``
        with ``.status_code`` and ``.text``. Defaults to ``requests.get``
        (lazily imported so the dependency is only needed for live fetches).
        Tests pass a stub so no network call happens.

    Returns
    -------
    str | None
        The raw file text on HTTP 200, else ``None`` (weekend/holiday → 403,
        or any transport error — best-effort, never raises).
    """
    get = http_get
    if get is None:
        import requests  # lazy: only needed for the live path

        get = requests.get

    url = _FINRA_REGSHO_URL.format(date=date_str)
    try:
        resp = get(url, headers=_FINRA_HEADERS, timeout=15)
    except Exception:  # noqa: BLE001 — best-effort; treat any failure as no-data
        return None

    if getattr(resp, "status_code", None) != 200:
        return None
    return resp.text


def _parse_finra_short_volume(text: str, ticker: str) -> tuple[float, float] | None:
    """Aggregate one ticker's (short_volume, total_volume) from a FINRA file.

    The file is pipe-delimited with a header row. A symbol can appear on several
    rows (one per ``Market`` code); we sum ShortVolume and TotalVolume across all
    of the ticker's rows. Malformed rows (missing columns / non-numeric volumes)
    are skipped silently rather than poisoning the aggregate.

    Returns ``(short_volume, total_volume)`` if the ticker appears on ≥1 valid
    row with a positive total volume, else ``None``.
    """
    if not text:
        return None

    want = ticker.strip().upper()
    short_total = 0.0
    total_total = 0.0
    found = False

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        # Need at least Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume.
        if len(parts) < 5:
            continue
        symbol = parts[1].strip().upper()
        if symbol != want:
            continue
        try:
            short_v = float(parts[2])
            total_v = float(parts[4])
        except (TypeError, ValueError):
            # Header row ("ShortVolume"/"TotalVolume") or a corrupt row — skip.
            continue
        short_total += short_v
        total_total += total_v
        found = True

    if not found or total_total <= 0.0:
        return None
    return short_total, total_total


def fetch_short_volume(
    ticker: str,
    *,
    lookback_days: int = 10,
    today: str | None = None,
    day_fetch=None,
) -> dict | None:
    """Build an off-exchange short-pressure proxy for ``ticker`` from FINRA.

    Walks back from ``today`` up to ``lookback_days`` *calendar* days, fetching
    each day's FINRA Reg-SHO file and collecting this ticker's aggregated
    ``(short_volume, total_volume, short_pct)`` for every date a file exists
    (newest first). Days with no file (weekend/holiday → 403/None) are skipped.

    Parameters
    ----------
    ticker : str
        Symbol to extract, e.g. ``"AAPL"``.
    lookback_days : int
        Max number of calendar days to walk back (default 10).
    today : str, optional
        Anchor date as ``YYYY-MM-DD`` or ``YYYYMMDD``. Defaults to
        ``date.today()`` — but tests always pass an explicit value so the walk
        is deterministic and never touches the real clock in an uncontrollable
        way.
    day_fetch : callable, optional
        Injectable per-day seam ``day_fetch(date_str_YYYYMMDD) -> str | None``.
        Defaults to :func:`_fetch_finra_day`. Tests pass a stub so no network
        call happens.

    Returns
    -------
    dict | None
        On ≥1 available day::

            {
                "ticker":        str,
                "date":          str,    # latest date with data, YYYY-MM-DD
                "short_pct":     float,  # latest short_volume / total_volume
                "short_volume":  float,  # latest day's aggregated short volume
                "total_volume":  float,  # latest day's aggregated total volume
                "avg_short_pct": float,  # mean short_pct over all collected days
                "trend":         str,    # "rising"/"falling"/"flat" (latest vs
                                         #   mean of the older days)
                "n_days":        int,    # number of days with data collected
            }

        ``None`` if no day had data, or on any failure (best-effort — the walk
        never raises).
    """
    from datetime import date, timedelta

    fetch = day_fetch or _fetch_finra_day

    try:
        anchor = _parse_anchor_date(today)
    except Exception:  # noqa: BLE001 — bad input → no signal rather than crash
        return None

    # Collected per-day records, newest first. Each: (date_iso, short_pct,
    # short_volume, total_volume).
    days: list[tuple[str, float, float, float]] = []

    try:
        for offset in range(max(int(lookback_days), 0)):
            d = anchor - timedelta(days=offset)
            date_str = d.strftime("%Y%m%d")
            text = fetch(date_str)
            if not text:
                continue  # weekend/holiday/no-file — skip
            agg = _parse_finra_short_volume(text, ticker)
            if agg is None:
                continue  # ticker absent / no usable rows that day
            short_v, total_v = agg
            short_pct = short_v / total_v if total_v > 0.0 else 0.0
            days.append((d.strftime("%Y-%m-%d"), short_pct, short_v, total_v))
    except Exception:  # noqa: BLE001 — best-effort; partial data still usable below
        pass

    if not days:
        return None

    latest_date, latest_pct, latest_short, latest_total = days[0]
    pcts = [rec[1] for rec in days]
    avg_pct = sum(pcts) / len(pcts)

    # Trend: compare the latest day against the mean of the *older* days. With
    # only one day of data there is nothing to compare → "flat".
    older = pcts[1:]
    if older:
        older_avg = sum(older) / len(older)
        # 1 percentage-point (0.01) dead-band so micro-noise reads "flat".
        if latest_pct > older_avg + 0.01:
            trend = "rising"
        elif latest_pct < older_avg - 0.01:
            trend = "falling"
        else:
            trend = "flat"
    else:
        trend = "flat"

    return {
        "ticker": ticker,
        "date": latest_date,
        "short_pct": latest_pct,
        "short_volume": latest_short,
        "total_volume": latest_total,
        "avg_short_pct": avg_pct,
        "trend": trend,
        "n_days": len(days),
    }


def _parse_anchor_date(today: str | None):
    """Resolve the walk anchor to a ``datetime.date``.

    Accepts ``None`` (→ today), ``YYYY-MM-DD``, or ``YYYYMMDD``. Raises
    ``ValueError`` on an unparseable string (the caller turns that into None).
    """
    from datetime import date, datetime

    if today is None:
        return date.today()
    s = str(today).strip()
    if "-" in s:
        return datetime.strptime(s, "%Y-%m-%d").date()
    return datetime.strptime(s, "%Y%m%d").date()
