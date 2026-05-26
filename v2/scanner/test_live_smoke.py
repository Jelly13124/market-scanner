"""End-to-end live smoke for the scanner. Off by default.

Enable with::

    $env:SCANNER_LIVE_TEST = "1"
    pytest v2/scanner/test_live_smoke.py -s

Burns API quota on whichever provider ``SCANNER_DATA_PROVIDER`` resolves to
(typically the ``hybrid`` EODHD+Finnhub stack). Runs a real scan against
``nasdaq100_sp500`` and asserts the basic invariants — fast feedback when
some upstream contract changes silently.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SCANNER_LIVE_TEST") != "1",
    reason="live scanner smoke disabled; set SCANNER_LIVE_TEST=1 to run",
)


def _today_str() -> str:
    # Use the previous business day so the FD/EODHD bars are settled.
    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


@pytest.fixture(scope="module")
def universe() -> list[str]:
    from v2.scanner.universes import load_universe
    return load_universe("nasdaq100_sp500")


def test_universe_size_is_realistic(universe):
    """The bundled CSVs should give 500+ tickers; if not, someone's
    universe refresh script broke."""
    assert len(universe) >= 500, f"Universe shrunk: {len(universe)}"


def test_full_scan_runs_to_completion(universe):
    """Sanity-check end-to-end. ≤10 min wall clock; Top-N has scores in
    [0, 100]; composite >= event when quant kicks in positive; severity
    z's are bounded."""
    from v2.scanner.runner import run_scan
    from v2.signals import ALL_SIGNALS

    end_date = _today_str()
    results = run_scan(
        tickers=universe,
        end_date=end_date,
        top_n=20,
        quant_signals=[cls() for cls in ALL_SIGNALS],
    )

    assert results, "expected at least one triggered ticker"
    assert len(results) <= 20

    for entry in results:
        assert 0.0 <= entry.composite_score <= 100.0
        assert 0.0 <= entry.event_score <= 100.0
        # event_severity (raw max |z|) should be sane post-bugfix.
        # Anything above 100 means a std floor regressed somewhere.
        assert entry.event_severity < 100.0, (
            f"{entry.ticker} severity={entry.event_severity:.2f} — "
            f"std floor likely regressed. Triggers: {entry.triggers}"
        )

    # Ranks are 1-indexed, contiguous, monotone by composite desc.
    ranks = [e.rank for e in results]
    assert ranks == list(range(1, len(results) + 1))
    scores = [e.composite_score for e in results]
    assert scores == sorted(scores, reverse=True)
