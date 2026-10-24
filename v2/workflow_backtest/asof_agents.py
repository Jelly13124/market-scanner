from __future__ import annotations

import contextlib

import src.tools.api as _api
import v2.data.factory as _factory


@contextlib.contextmanager
def asof_agent_context(dispatcher, scan_date: str):
    """Force every agent data read for ``scan_date`` through ``dispatcher`` (as-of-safe).

    The agents reach market data through MULTIPLE paths, so a single patch is
    not enough. This context manager clamps all of them to ``scan_date`` and
    restores the originals on exit:

      * ``src.tools.api._v2_client_cache`` — the hybrid-client singleton that
        ``_get_v2_client()`` short-circuits on. Swapped to ``dispatcher``.
      * ``v2.data.factory.get_provider_factory`` — ``src.agents.sector_agent``
        and ``src.agents.macro_agent`` call this DIRECTLY (bypassing api.py),
        so we replace it with a factory whose returned callable yields
        ``dispatcher``.
      * Those two agents' module-level dict caches, which would otherwise
        serve stale cross-date values: ``sector_agent._SECTOR_CACHE`` and
        ``_ETF_PRICES``, and ``macro_agent._CACHE``. Cleared on entry, their
        contents restored on exit.

    Residual leak: ``search_line_items`` (yfinance, used elsewhere) is NOT
    clamped to ``scan_date`` — it can still pull data after the as-of point.
    This is accepted: the A/B comparison (scanner-filtered vs random baseline)
    cancels this common-mode bias because both arms share the identical leak.
    """
    dispatcher.set_asof(scan_date)
    saved_cache = _api._v2_client_cache
    saved_factory = _factory.get_provider_factory
    cleared = []  # (cache_dict, original_copy)
    try:
        _api._v2_client_cache = dispatcher
        _factory.get_provider_factory = lambda: (lambda: dispatcher)
        for modname, attrs in (
            ("src.agents.sector_agent", ("_SECTOR_CACHE", "_ETF_PRICES")),
            ("src.agents.macro_agent", ("_CACHE",)),
        ):
            try:
                mod = __import__(modname, fromlist=["*"])
            except Exception:
                continue
            for a in attrs:
                cache = getattr(mod, a, None)
                if isinstance(cache, dict):
                    cleared.append((cache, dict(cache)))
                    cache.clear()
        yield dispatcher
    finally:
        _api._v2_client_cache = saved_cache
        _factory.get_provider_factory = saved_factory
        for cache, original in cleared:
            cache.clear()
            cache.update(original)
