"""Universe loaders for the scanner.

Public API:
    load_universe(kind, custom=None) -> list[str]
"""

from v2.scanner.universes.loader import load_universe

__all__ = ["load_universe"]
