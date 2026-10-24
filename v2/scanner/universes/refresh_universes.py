"""Refresh the bundled universe CSVs from public sources.

Usage:
    python -m v2.scanner.universes.refresh_universes                # all
    python -m v2.scanner.universes.refresh_universes --kind sp500   # one
    python -m v2.scanner.universes.refresh_universes --dry-run      # preview

Sources (all free, no auth):

    sp500
        Wikipedia "List of S&P 500 companies" — first wikitable on the page,
        columns: Symbol, Security, GICS Sector.

    nasdaq100
        Wikipedia "NASDAQ-100" — the table with "Ticker" column. The page
        also has historical change tables; we pick the constituents table by
        heuristic (longest "Ticker" column).

    russell3000
        iShares IWV ETF holdings CSV. BlackRock publishes the full daily
        holding list as CSV at a stable URL — about 3000 rows with an 8-line
        preamble we skip.

    all_us
        NASDAQ Trader symbol directory:
            https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt
            https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt
        Pipe-separated. Filter rows where Test Issue=N and ETF=N.

The fetchers are best-effort and degrade loudly: if the source 404s or
schema-shifts, the script logs and exits non-zero rather than overwriting a
CSV with garbage.

Output CSV format mirrors the existing seed files:
    # comment lines (optional)
    ticker,name,sector
    AAPL,Apple Inc.,Technology
    ...
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Callable

import requests

logger = logging.getLogger("refresh_universes")

_DIR = Path(__file__).parent

# Expected approximate sizes — used to sanity-check fetches.
_EXPECTED_SIZES = {
    "sp500": (450, 550),
    "nasdaq100": (95, 110),
    "russell3000": (2500, 3200),
    "all_us": (4000, 9000),
}

_USER_AGENT = "ai-hedge-fund/refresh_universes (https://github.com/virattt/ai-hedge-fund)"


# ---------------------------------------------------------------------------
# Fetchers — return list[(ticker, name, sector)]
# ---------------------------------------------------------------------------


def fetch_sp500() -> list[tuple[str, str, str]]:
    """Wikipedia: List of S&P 500 companies."""
    import pandas as pd  # heavy import; lazy

    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    logger.info("Fetching S&P 500 from %s", url)
    tables = pd.read_html(url, storage_options={"User-Agent": _USER_AGENT})
    # The first table on this page is the constituents table.
    if not tables:
        raise RuntimeError("Wikipedia SP500 page returned no tables")
    df = tables[0]

    # Column names have varied over time. Try a few.
    sym_col = next((c for c in df.columns if str(c).lower() in ("symbol", "ticker symbol")), None)
    name_col = next((c for c in df.columns if "security" in str(c).lower() or "company" in str(c).lower()), None)
    sector_col = next((c for c in df.columns if "gics sector" in str(c).lower() or str(c).lower() == "sector"), None)
    if sym_col is None:
        raise RuntimeError(f"SP500 table: can't locate ticker column among {list(df.columns)}")

    rows: list[tuple[str, str, str]] = []
    for _, r in df.iterrows():
        ticker = str(r[sym_col]).strip().upper()
        # Wikipedia uses ".B" notation already (BRK.B etc.) — keep as-is.
        if not ticker or ticker == "NAN":
            continue
        name = str(r[name_col]).strip() if name_col else ""
        sector = str(r[sector_col]).strip() if sector_col else ""
        rows.append((ticker, name, sector))
    return rows


def fetch_nasdaq100() -> list[tuple[str, str, str]]:
    """Wikipedia: NASDAQ-100."""
    import pandas as pd

    url = "https://en.wikipedia.org/wiki/Nasdaq-100"
    logger.info("Fetching NASDAQ-100 from %s", url)
    tables = pd.read_html(url, storage_options={"User-Agent": _USER_AGENT})

    # Heuristic: the constituents table has a 'Ticker' or 'Symbol' column and
    # ~100 rows. Pick the table that best matches.
    best = None
    for t in tables:
        cols_lower = [str(c).lower() for c in t.columns]
        has_ticker = any(c in ("ticker", "symbol") for c in cols_lower)
        if has_ticker and 70 <= len(t) <= 130:
            if best is None or abs(len(t) - 100) < abs(len(best) - 100):
                best = t
    if best is None:
        raise RuntimeError(
            f"Couldn't locate the NASDAQ-100 constituents table; got {len(tables)} tables on the page"
        )

    sym_col = next((c for c in best.columns if str(c).lower() in ("ticker", "symbol")), None)
    name_col = next((c for c in best.columns if str(c).lower() in ("company", "security")), None)
    sector_col = next((c for c in best.columns if "sector" in str(c).lower() or "industry" in str(c).lower()), None)

    rows: list[tuple[str, str, str]] = []
    for _, r in best.iterrows():
        ticker = str(r[sym_col]).strip().upper()
        if not ticker or ticker == "NAN":
            continue
        name = str(r[name_col]).strip() if name_col else ""
        sector = str(r[sector_col]).strip() if sector_col else ""
        rows.append((ticker, name, sector))
    return rows


def fetch_russell3000() -> list[tuple[str, str, str]]:
    """iShares IWV holdings CSV."""
    # iShares' download endpoint takes a fund-page ID. IWV's:
    url = (
        "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf"
        "/1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund"
    )
    logger.info("Fetching Russell 3000 from iShares (IWV)")
    r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=60)
    r.raise_for_status()
    text = r.text

    # The file has a 9-ish-line BlackRock preamble before the CSV header.
    # Find the line that starts with 'Ticker,' and parse from there.
    lines = text.splitlines()
    start_idx = None
    for i, line in enumerate(lines):
        if line.startswith('"Ticker"') or line.startswith("Ticker,") or line.startswith("Ticker\t"):
            start_idx = i
            break
    if start_idx is None:
        raise RuntimeError("Russell 3000: couldn't find CSV header line (no 'Ticker,' found)")

    csv_text = "\n".join(lines[start_idx:])
    reader = csv.DictReader(io.StringIO(csv_text))
    rows: list[tuple[str, str, str]] = []
    for row in reader:
        ticker = (row.get("Ticker") or "").strip().upper()
        if not ticker or ticker == "-":
            continue
        # iShares uses "Asset Class" — skip cash / FX / futures (Equity only).
        asset = (row.get("Asset Class") or "").strip().lower()
        if asset and asset != "equity":
            continue
        name = (row.get("Name") or "").strip()
        sector = (row.get("Sector") or "").strip()
        rows.append((ticker, name, sector))
    return rows


def fetch_all_us() -> list[tuple[str, str, str]]:
    """NASDAQ Trader symbol directory: nasdaqlisted.txt + otherlisted.txt."""
    urls = [
        ("nasdaq", "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"),
        ("other",  "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"),
    ]
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    for src, url in urls:
        logger.info("Fetching %s from %s", src, url)
        r = requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=60)
        r.raise_for_status()
        lines = r.text.splitlines()
        if not lines:
            raise RuntimeError(f"NASDAQ Trader {src} returned no body")

        # Last line is a 'File Creation Time' footer — drop it.
        if lines[-1].startswith("File Creation Time"):
            lines = lines[:-1]

        reader = csv.DictReader(lines, delimiter="|")
        # Columns differ between files; figure them out from the header.
        sym_field = "Symbol" if "Symbol" in reader.fieldnames else "ACT Symbol"
        name_field = "Security Name"
        # ETF / Test flags — file conventions:
        #   nasdaqlisted.txt: 'ETF' = 'Y'/'N', 'Test Issue' = 'Y'/'N'
        #   otherlisted.txt:  'ETF' = 'Y'/'N', 'Test Issue' = 'Y'/'N'
        for row in reader:
            if (row.get("Test Issue") or "").strip().upper() == "Y":
                continue
            if (row.get("ETF") or "").strip().upper() == "Y":
                continue
            ticker = (row.get(sym_field) or "").strip().upper()
            # NASDAQ uses '$' in some symbols (e.g. preferred stocks). Skip
            # non-common-stock notations that contain '$' or '.WS' (warrants).
            if not ticker or "$" in ticker or ticker.endswith(".WS"):
                continue
            if ticker in seen:
                continue
            seen.add(ticker)
            name = (row.get(name_field) or "").strip()
            rows.append((ticker, name, ""))
    return rows


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_csv(path: Path, rows: list[tuple[str, str, str]], *, source_note: str) -> None:
    today = date.today().isoformat()
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(f"ticker,name,sector\n")
        fh.write(f"# Refreshed {today} via refresh_universes.py\n")
        fh.write(f"# Source: {source_note}\n")
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        for t, n, s in rows:
            writer.writerow([t, n, s])
    logger.info("Wrote %d rows to %s", len(rows), path)


def _validate_size(kind: str, rows: list) -> bool:
    lo, hi = _EXPECTED_SIZES.get(kind, (0, 10**9))
    if not (lo <= len(rows) <= hi):
        logger.error(
            "Refusing to write %s: got %d rows, expected %d..%d (source probably changed)",
            kind, len(rows), lo, hi,
        )
        return False
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_FETCHERS: dict[str, tuple[Callable[[], list], str, str]] = {
    "sp500":       (fetch_sp500,       "sp500.csv",            "Wikipedia / List_of_S%26P_500_companies"),
    "nasdaq100":   (fetch_nasdaq100,   "nasdaq100.csv",        "Wikipedia / Nasdaq-100"),
    "russell3000": (fetch_russell3000, "russell3000.csv",      "iShares IWV holdings CSV"),
    "all_us":      (fetch_all_us,      "nyse_nasdaq_all.csv",  "NASDAQ Trader symbol directory"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh bundled universe CSVs")
    parser.add_argument(
        "--kind", choices=[*_FETCHERS, "all"], default="all",
        help="Which universe to refresh (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch + parse but do NOT write the CSV (size sanity check only).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    kinds = list(_FETCHERS) if args.kind == "all" else [args.kind]
    failures = 0

    for kind in kinds:
        fetcher, filename, source_note = _FETCHERS[kind]
        try:
            rows = fetcher()
        except Exception as e:
            logger.error("Fetch %s failed: %s", kind, e)
            failures += 1
            continue

        if not _validate_size(kind, rows):
            failures += 1
            continue

        if args.dry_run:
            logger.info("[dry-run] %s OK — %d rows (would write to %s)", kind, len(rows), filename)
            continue

        write_csv(_DIR / filename, rows, source_note=source_note)

    if failures:
        logger.error("%d / %d universes failed to refresh", failures, len(kinds))
        return 1
    logger.info("All %d universe(s) refreshed successfully", len(kinds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
