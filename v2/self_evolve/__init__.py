"""Self-evolving factor-strategy engine.

An LLM proposes single-hypothesis CONFIG deltas to a deterministic factor
strategy; deltas are bounded by the protocol in ``config.py`` and evaluated under
strict train/val/test sample isolation. This package is the kernel — the
strategy code and config loader the agent is allowed to drive, with hard limits.
"""
