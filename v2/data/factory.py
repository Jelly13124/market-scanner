"""Data provider factory — env-driven provider selection.

Read by ``v2.scanner.runner.run_scan`` when ``provider_factory`` is None.
The ``SCANNER_DATA_PROVIDER`` env var picks the provider; default is
``hybrid`` (EODHD prices+news + Finnhub everything else). FD remains
available as an opt-in but is no longer the default since the paid tier
402s on most endpoints in our setup.

Usage::

    from v2.data.factory import make_data_client, get_provider_factory
    client = make_data_client()                  # one-off
    factory = get_provider_factory()             # for thread-pool seeding
"""

from __future__ import annotations

import os
from typing import Callable

from v2.data.client import FDClient
from v2.data.protocol import DataClient


def get_default_provider() -> str:
    return os.environ.get("SCANNER_DATA_PROVIDER", "hybrid").strip().lower()


def _resolve(provider: str | None) -> str:
    return (provider or get_default_provider()).strip().lower()


_VALID_PROVIDERS = ("fd", "finnhub", "eodhd", "hybrid")


def _bad_provider(p: str) -> ValueError:
    return ValueError(
        f"Unknown data provider: {p!r}. Valid: {', '.join(_VALID_PROVIDERS)}. "
        "Set SCANNER_DATA_PROVIDER env var to override."
    )


def make_data_client(provider: str | None = None) -> DataClient:
    """Instantiate one DataClient of the selected provider."""
    p = _resolve(provider)
    if p == "fd":
        return FDClient()
    if p == "finnhub":
        from v2.data.finnhub_client import FinnhubClient
        return FinnhubClient()
    if p == "eodhd":
        from v2.data.eodhd_client import EODHDClient
        return EODHDClient()
    if p == "hybrid":
        from v2.data.composite_client import make_hybrid_client
        return make_hybrid_client()
    raise _bad_provider(p)


def get_provider_factory(provider: str | None = None) -> Callable[[], DataClient]:
    """Return a zero-arg callable that builds fresh clients (one per worker)."""
    p = _resolve(provider)
    if p == "fd":
        return FDClient
    if p == "finnhub":
        from v2.data.finnhub_client import FinnhubClient
        return FinnhubClient
    if p == "eodhd":
        from v2.data.eodhd_client import EODHDClient
        return EODHDClient
    if p == "hybrid":
        from v2.data.composite_client import make_hybrid_client
        return make_hybrid_client
    raise _bad_provider(p)


def recommend_max_workers(provider: str | None = None) -> int:
    """Conservative worker-count cap for rate-limited providers.

    The hybrid is gated by Finnhub's 60 calls/min global cap; EODHD's $20 tier
    has plenty of headroom (1000+/min) but in hybrid mode we're held to the
    slowest component.
    """
    p = _resolve(provider)
    if p in ("finnhub", "hybrid"):
        return 4
    return 16
