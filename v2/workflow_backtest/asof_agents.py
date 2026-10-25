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

      * A context-local provider override shared by the legacy API adapter
        and data factory, without swapping process-global client sessions.
      * Those two agents' module-level dict caches, which would otherwise
        serve stale cross-date values: ``sector_agent._SECTOR_CACHE`` and
        ``_ETF_PRICES``, and ``macro_agent._CACHE``. Cleared on entry, their
        contents restored on exit.

    Unknown statement-publication vintages are not evidence of point-in-time
    availability. Historical statement reads abstain instead of assuming
    a common bias cancels between the two arms.
    """
    dispatcher.set_asof(scan_date)
    token = _factory._CLIENT_OVERRIDE.set(dispatcher)
    cleared = []  # (cache_dict, original_copy)
    try:
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
        _factory._CLIENT_OVERRIDE.reset(token)
        for cache, original in cleared:
            cache.clear()
            cache.update(original)
