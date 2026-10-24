"""Scanner self-evolve package — bounded config protocol for detector tuning.

The scanner self-evolve loop lets an LLM tune detector thresholds + severity
multipliers + ``top_n`` of the event-driven scanner, while the fundamental
``quant_weight`` stays pinned at 0 (the known-bad signals can never be
re-enabled). This package's :mod:`config` module is the protocol boundary.
"""
