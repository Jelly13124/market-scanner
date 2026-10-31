"""Current provider factory selected by SCANNER_DATA_PROVIDER.

The runtime default remains hybrid. Explicit fd/finnhub options remain for legacy consumers.
Hybrid uses optional MongoDB cache with online fallback.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Callable

from v2.data.client import FDClient
from v2.data.protocol import DataClient


_CLIENT_OVERRIDE = ContextVar("market_data_client_override", default=None)


def get_default_provider() -> str:
    return os.environ.get("SCANNER_DATA_PROVIDER", "hybrid").strip().lower()


def _resolve(provider: str | None) -> str:
    return (provider or get_default_provider()).strip().lower()


_VALID_PROVIDERS = ("fd", "finnhub", "hybrid")


def _bad_provider(p: str) -> ValueError:
    return ValueError(
        f"Unknown data provider: {p!r}. Valid: {', '.join(_VALID_PROVIDERS)}. "
        "Set SCANNER_DATA_PROVIDER env var to override."
    )


def make_data_client(provider: str | None = None) -> DataClient:
    """Instantiate one DataClient of the selected provider."""
    override = _CLIENT_OVERRIDE.get()
    if override is not None:
        return override
    p = _resolve(provider)
    if p == "fd":
        return FDClient()
    if p == "finnhub":
        from v2.data.finnhub_client import FinnhubClient
        return FinnhubClient()
    if p == "hybrid":
        from v2.data.composite_client import make_hybrid_client
        return make_hybrid_client()
    raise _bad_provider(p)


def get_provider_factory(provider: str | None = None, *, finnhub_api_key: str | None = None) -> Callable[[], DataClient]:
    """Return a zero-arg callable that builds fresh clients (one per worker)."""
    override = _CLIENT_OVERRIDE.get()
    if override is not None:
        return lambda: override
    p = _resolve(provider)
    if p == "fd":
        return FDClient
    if p == "finnhub":
        from v2.data.finnhub_client import FinnhubClient
        return (lambda: FinnhubClient(api_key=finnhub_api_key)) if finnhub_api_key is not None else FinnhubClient
    if p == "hybrid":
        from v2.data.composite_client import make_hybrid_client
        return (lambda: make_hybrid_client(finnhub_api_key=finnhub_api_key)) if finnhub_api_key is not None else make_hybrid_client
    raise _bad_provider(p)


def recommend_max_workers(provider: str | None = None) -> int:
    """Conservative worker-count cap for rate-limited providers.

    Hybrid concurrency is capped conservatively for its Finnhub component.
    Provider quotas and account permissions require separate validation.
    """
    p = _resolve(provider)
    if p in ("finnhub", "hybrid"):
        return 4
    return 16
