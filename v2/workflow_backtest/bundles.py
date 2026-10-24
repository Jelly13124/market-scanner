from __future__ import annotations

from v2.scanner.eval.historical_events import enrich_bundle
from v2.scanner.eval.run_eval import prefetch_price_bundles


def build_bundles(tickers, provider_factory, start_date, end_date, *, enrich=True, deadline=None):
    """Prefetch a TickerBundle per ticker (prices, then optionally enrich with
    earnings/insider/news/metrics). enrich=False keeps it offline/price-only."""
    bundles = prefetch_price_bundles(tickers, provider_factory, start_date, end_date)
    if enrich:
        client = provider_factory()
        for b in bundles.values():
            try:
                enrich_bundle(b, start_date=start_date, end_date=end_date,
                              insider_client=client, news_client=client, deadline=deadline)
            except Exception:
                pass
    return bundles
