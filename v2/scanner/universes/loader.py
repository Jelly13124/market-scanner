"""Load stock universes from bundled CSV snapshots.

Universe kinds:
    sp500            — S&P 500 constituents (~500)
    nasdaq100        — NASDAQ-100 constituents (~100)
    nasdaq100_sp500  — Union of NASDAQ-100 + S&P 500, deduped (~530); the
                       recommended default for new scanner configs
    russell3000      — Russell 3000 constituents (~3000)
    all_us           — NYSE + NASDAQ + AMEX active common stock (~6000-8000)
    custom           — caller-supplied ticker list (no CSV lookup)

The CSVs are simple ``ticker,name,sector`` files. Only the first column is
read; the rest is metadata for humans browsing the file.

Bundled CSVs are seed snapshots. Refresh quarterly via
``v2/scanner/universes/refresh_universes.py``.
"""

from __future__ import annotations

import csv
import sys
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent

_FILES = {
    "sp500": _DIR / "sp500.csv",
    "nasdaq100": _DIR / "nasdaq100.csv",
    "russell3000": _DIR / "russell3000.csv",
    "all_us": _DIR / "nyse_nasdaq_all.csv",
}

# Composite universes are deterministic unions of the above. Each value is a
# tuple of source kinds; the loader returns the deduped concatenation in the
# given order.
_COMPOSITE = {
    "nasdaq100_sp500": ("nasdaq100", "sp500"),
}


@cache
def _load_csv(kind: str) -> tuple[str, ...]:
    """Read a bundled CSV and return its ticker column. Cached per-kind."""
    path = _FILES[kind]
    if not path.exists():
        raise FileNotFoundError(f"Universe CSV missing: {path}")
    tickers: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header or header[0].strip().lower() != "ticker":
            raise ValueError(f"{path} must have 'ticker' as the first column, got: {header}")
        for row in reader:
            if not row:
                continue
            ticker = row[0].strip().upper()
            if ticker and not ticker.startswith("#"):
                tickers.append(ticker)
    return tuple(tickers)


def load_universe(
    kind: str,
    custom: list[str] | None = None,
    watchlist_tickers: list[str] | None = None,
) -> list[str]:
    """Return the ticker list for *kind*.

    Args:
        kind:               'sp500' | 'nasdaq100' | 'nasdaq100_sp500' |
                            'russell3000' | 'all_us' | 'custom' | 'watchlist'
        custom:             required when kind == 'custom'; ignored otherwise
        watchlist_tickers:  required when kind == 'watchlist'; the resolved
                            tickers list from a UserWatchlist row
    """
    if kind == "custom" or kind == "watchlist":
        source: list[str] | None = custom if kind == "custom" else watchlist_tickers
        if not source:
            arg_name = "custom" if kind == "custom" else "watchlist_tickers"
            raise ValueError(
                f"kind={kind!r} requires {arg_name} (non-empty ticker list)"
            )
        # Dedupe + uppercase while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for t in source:
            u = t.strip().upper()
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out
    if kind in _COMPOSITE:
        seen: set[str] = set()
        out: list[str] = []
        for sub in _COMPOSITE[kind]:
            for ticker in _load_csv(sub):
                if ticker not in seen:
                    seen.add(ticker)
                    out.append(ticker)
        return out
    if kind not in _FILES:
        valid = ", ".join(sorted({*_FILES, *_COMPOSITE, "custom", "watchlist"}))
        raise ValueError(f"Unknown universe kind: {kind!r}. Valid: {valid}")
    return list(_load_csv(kind))


def _main() -> None:
    """CLI: ``python -m v2.scanner.universes.loader <kind> [limit]``."""
    if len(sys.argv) < 2:
        valid = "|".join(sorted({*_FILES, *_COMPOSITE}))
        print(
            f"Usage: python -m v2.scanner.universes.loader <{valid}> [limit]",
            file=sys.stderr,
        )
        sys.exit(2)
    kind = sys.argv[1]
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    tickers = load_universe(kind)
    if limit is not None:
        tickers = tickers[:limit]
    for t in tickers:
        print(t)
    print(f"\n({len(tickers)} tickers shown; kind={kind})", file=sys.stderr)


if __name__ == "__main__":
    _main()
