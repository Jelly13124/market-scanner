"""v2 Daily Market Scanner.

Stage-1 pure-quant scanner: takes a stock universe, runs event detectors and
quant factor signals per ticker, returns a ranked Top-N watchlist. No LLM calls.

Submodules:
    universes/   universe loaders + bundled CSV snapshots
    detectors/   (M2) event detectors — earnings, insider, price/vol, news
    scoring      (M2) composite score combining event severity + quant factors
    runner       (M3) orchestrator with thread-pool concurrency
"""
