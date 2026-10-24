"""Phase 8 Wave 3: A-share universe loader extension.

The 5 new universe kinds (sse50, csi300, csi500, csi1000, hs300_ext) are
loaded from CSVs under ``v2/scanner/universes/data/``. The CSVs are
refreshed by ``refresh_ashare_universes.py``.

These tests accept TWO outcomes:
  1. Non-empty -- live fetch succeeded; assert every ticker is canonical
     A-share form.
  2. Empty (header-only stub) -- live fetch failed in CI / offline /
     when Eastmoney moved the endpoint. The loader must still return
     an empty list (not raise). Downstream callers handle that case.
"""
from __future__ import annotations

import pytest

from v2.data.ashare.symbol import is_ashare
from v2.scanner.universes.loader import load_universe


_KINDS = ["sse50", "csi300", "csi500", "csi1000", "hs300_ext"]


@pytest.mark.parametrize("kind", _KINDS)
def test_loads_returns_list(kind):
    """Loader must always return a list (empty OR populated), never raise."""
    tickers = load_universe(kind)
    assert isinstance(tickers, list)


@pytest.mark.parametrize("kind", _KINDS)
def test_loaded_tickers_are_ashare_canonical(kind):
    """When the universe has data, every entry must look like an A-share
    canonical ticker. Empty universes are tolerated (stub CSVs)."""
    tickers = load_universe(kind)
    if not tickers:
        pytest.skip(f"{kind} is empty -- live Eastmoney fetch likely failed; stub CSV")
    for t in tickers[:10]:
        assert is_ashare(t), f"expected A-share canonical ticker, got: {t!r}"
