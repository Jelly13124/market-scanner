"""Bounded config loader/validator — the PROTOCOL boundary of the self-evolve loop.

The self-evolve engine lets an LLM propose changes to a deterministic factor
strategy. To keep the search safe and reproducible, the LLM is NOT handed free
rein over the codebase: it may only edit fields declared in :data:`ADJUSTABLE`,
and only within their declared ranges. This module is the gate that enforces
that contract.

Pieces:

* :class:`StrategyConfig` — a plain dataclass mirroring ``skill_config.yaml``.
  Factor weights are **sum-normalized to 1.0** when a config is built, so what
  the LLM tunes are *relative* weights.
* :data:`ADJUSTABLE` — the allow-list. Maps a dotted path (e.g.
  ``"factor_weights.momentum"``, ``"top_n"``) to its ``(min, max)`` bound. Any
  path NOT in this dict is fixed-kernel and off-limits.
* :func:`load_config` — parse yaml → build → validate.
* :func:`validate` — raise :class:`ConfigError` on any out-of-range field.
* :func:`apply_delta` — apply one (or more) bounded edits, returning a NEW
  validated config; the input is never mutated.

Everything here is pure Python + PyYAML. No network, no LLM, no pandas.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when a config violates the protocol boundary.

    Either a field is outside its :data:`ADJUSTABLE` range, a delta targets an
    unknown / non-adjustable path, or the structure is malformed. Subclasses
    ``ValueError`` so callers that already catch ``ValueError`` keep working.
    """


# ---------------------------------------------------------------------------
# The protocol boundary.
# ---------------------------------------------------------------------------
#
# Each entry is a dotted path the LLM is allowed to edit, mapped to its closed
# ``[min, max]`` numeric range. Paths NOT listed here are part of the fixed
# kernel (rebalance cadence, lookback windows, etc.) and are rejected by
# ``apply_delta``. ``factor_weights.*`` entries are bounded [0, 1]; they are
# re-normalized to sum to 1.0 after every edit, so the bound just forbids
# negative / absurd magnitudes — the *ratio* is what ends up mattering.
ADJUSTABLE: dict[str, tuple[float, float]] = {
    # Composite factor blend (relative weights, each in [0, 1]).
    "factor_weights.momentum": (0.0, 1.0),
    "factor_weights.low_vol": (0.0, 1.0),
    "factor_weights.reversal": (0.0, 1.0),
    "factor_weights.value": (0.0, 1.0),
    "factor_weights.quality": (0.0, 1.0),
    # Part C: 6 new factors (NEUTRAL until computed — see factors.py). Each is a
    # relative weight in [0, 1], re-normalized into the blend like the originals.
    "factor_weights.max_lottery": (0.0, 1.0),
    "factor_weights.high_52w": (0.0, 1.0),
    "factor_weights.turnover": (0.0, 1.0),
    "factor_weights.resid_mom": (0.0, 1.0),
    "factor_weights.gross_prof": (0.0, 1.0),
    "factor_weights.asset_growth": (0.0, 1.0),
    # Lookback windows (trading days).
    "lookback.momentum_days": (120, 300),
    "lookback.vol_days": (20, 120),
    "lookback.reversal_days": (5, 42),
    # Part C: lookbacks for the new windowed factors (max-lottery short window,
    # 52-week-high window, turnover averaging window, residual-momentum window).
    "lookback.max_days": (10, 42),
    "lookback.hi_days": (120, 300),
    "lookback.to_days": (10, 63),
    "lookback.resid_days": (120, 300),
    # Portfolio construction.
    "top_n": (20, 50),
    "max_weight": (0.03, 0.08),
    # Liquidity universe filters (drop bottom percentile each).
    "liquidity_pct.mktcap_pct": (0.0, 1.0),
    "liquidity_pct.advol_pct": (0.0, 1.0),
    # Transaction-cost assumption (basis points). A real lever: the backtest
    # charges it against per-period returns, so the loop optimizes NET.
    "cost_bps": (0.0, 50.0),
    # tilt_strength / holding_buffer are intended future levers but are not yet
    # read by the strategy; excluded from ADJUSTABLE so the proposer can't waste
    # iterations tuning an inert knob (see final review H1).
}

# The canonical factor keys, in display order. The first five are computed; the
# six Part-C additions are registered here (and re-normalized into the blend) but
# remain NEUTRAL — absent from factor rows, scored z=0 — until their later
# factor-implementation tasks land. ``factors.FACTOR_KEYS`` MUST mirror this.
FACTOR_KEYS: tuple[str, ...] = (
    "momentum",
    "low_vol",
    "reversal",
    "value",
    "quality",
    "max_lottery",
    "high_52w",
    "turnover",
    "resid_mom",
    "gross_prof",
    "asset_growth",
)


@dataclass
class StrategyConfig:
    """Deterministic factor-strategy config — mirrors ``skill_config.yaml``.

    Factor weights are sum-normalized to 1.0 at construction time via
    :meth:`__post_init__`. The fixed-kernel fields (``rebalance``, ``cost_bps``)
    are stored for reproducibility but are NOT in :data:`ADJUSTABLE`.
    """

    factor_weights: dict[str, float]
    lookback: dict[str, int]
    top_n: int
    holding_buffer: int
    max_weight: float
    liquidity_pct: dict[str, float]
    tilt_strength: float
    rebalance: str = "monthly"
    cost_bps: float = 10.0

    def __post_init__(self) -> None:
        # Normalize factor weights to sum to 1.0. Done here (not only in
        # load_config) so apply_delta's rebuilt config is normalized too.
        self.factor_weights = _normalize_weights(self.factor_weights)


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    """Return a copy of ``weights`` scaled to sum to 1.0.

    Negative or non-numeric values are left as-is so :func:`validate` can flag
    them — normalization is not the place to enforce the [0, 1] bound (a
    negative weight would make the sum meaningless). When the total is
    non-positive (all-zero, or sums cancel), the weights are returned unchanged
    and ``validate`` is relied on to reject the degenerate config.
    """
    total = 0.0
    numeric = True
    for v in weights.values():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            numeric = False
            break
        total += float(v)
    if not numeric or total <= 0.0:
        return dict(weights)
    return {k: float(v) / total for k, v in weights.items()}


def load_config(path: str | Path) -> StrategyConfig:
    """Parse a yaml config, build a :class:`StrategyConfig`, and validate it.

    Raises :class:`ConfigError` on a malformed file or an out-of-range value.
    """
    p = Path(path)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {p}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse yaml at {p}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config root must be a mapping, got {type(raw).__name__}")

    cfg = _from_dict(raw)
    validate(cfg)
    return cfg


def _from_dict(raw: dict[str, Any]) -> StrategyConfig:
    """Build a :class:`StrategyConfig` from a parsed-yaml dict.

    Only keys matching dataclass fields are consumed; unknown top-level keys
    raise so a typo in the baseline yaml fails loudly rather than silently
    no-op'ing.
    """
    known = {f.name for f in fields(StrategyConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown config key(s): {unknown}; allowed: {sorted(known)}")
    required = {
        "factor_weights",
        "lookback",
        "top_n",
        "holding_buffer",
        "max_weight",
        "liquidity_pct",
        "tilt_strength",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ConfigError(f"missing required config key(s): {missing}")
    return StrategyConfig(**raw)


def _get_path(cfg: StrategyConfig, path: str) -> Any:
    """Read a dotted ADJUSTABLE path off a config (e.g. ``factor_weights.momentum``)."""
    head, _, tail = path.partition(".")
    container = getattr(cfg, head)
    if tail:
        return container[tail]
    return container


def validate(config: StrategyConfig) -> None:
    """Raise :class:`ConfigError` if any field is outside its declared range.

    Checks every path in :data:`ADJUSTABLE` against the live config, plus two
    structural invariants:

    * factor_weights covers exactly :data:`FACTOR_KEYS`, and
    * factor_weights sums to 1.0 (i.e. it was normalized).
    """
    # Factor-weight key set.
    if set(config.factor_weights) != set(FACTOR_KEYS):
        raise ConfigError(f"factor_weights keys must be {sorted(FACTOR_KEYS)}, got {sorted(config.factor_weights)}")

    # Every adjustable path within its [min, max] bound.
    for path, (lo, hi) in ADJUSTABLE.items():
        try:
            value = _get_path(config, path)
        except KeyError as exc:
            raise ConfigError(f"config missing adjustable path {path!r}") from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path} must be numeric, got {type(value).__name__}: {value!r}")
        if not (lo <= value <= hi):
            raise ConfigError(f"{path}={value} out of range [{lo}, {hi}]")

    # factor_weights must be normalized (sum to 1.0). Negative weights make the
    # sum diverge from 1.0 and are caught by the per-path [0, 1] check above,
    # but we re-assert the invariant here so a non-normalized config can't slip
    # through if someone constructs StrategyConfig fields by hand.
    wsum = sum(config.factor_weights.values())
    if abs(wsum - 1.0) > 1e-6:
        raise ConfigError(f"factor_weights must sum to 1.0, got {wsum}")

    # Fixed-kernel sanity (not adjustable, but a malformed baseline should fail).
    if config.rebalance != "monthly":
        raise ConfigError(f"rebalance is fixed to 'monthly', got {config.rebalance!r}")
    if config.cost_bps < 0:
        raise ConfigError(f"cost_bps must be >= 0, got {config.cost_bps}")


def apply_delta(config: StrategyConfig, delta: dict[str, Any]) -> StrategyConfig:
    """Apply bounded edits and return a NEW validated config (input untouched).

    ``delta`` maps dotted :data:`ADJUSTABLE` paths to new values. An unknown
    path, a non-adjustable path, or a value outside the declared range raises
    :class:`ConfigError`. Because the result is rebuilt through
    :class:`StrategyConfig`, factor weights are re-normalized to sum to 1.0.
    """
    if not isinstance(delta, dict):
        raise ConfigError(f"delta must be a dict, got {type(delta).__name__}")

    # Deep-copy so the caller's config is never mutated, even on partial failure.
    draft = copy.deepcopy(config)

    for path, new_value in delta.items():
        if path not in ADJUSTABLE:
            raise ConfigError(f"path {path!r} is not adjustable; allowed: {sorted(ADJUSTABLE)}")
        if isinstance(new_value, bool) or not isinstance(new_value, (int, float)):
            raise ConfigError(f"delta value for {path!r} must be numeric, " f"got {type(new_value).__name__}: {new_value!r}")
        lo, hi = ADJUSTABLE[path]
        if not (lo <= new_value <= hi):
            raise ConfigError(f"{path}={new_value} out of range [{lo}, {hi}]")
        _set_path(draft, path, float(new_value))

    # Rebuild from field values so __post_init__ re-normalizes factor_weights,
    # then re-validate the whole thing.
    rebuilt = StrategyConfig(**{f.name: getattr(draft, f.name) for f in fields(StrategyConfig)})
    validate(rebuilt)
    return rebuilt


def _set_path(cfg: StrategyConfig, path: str, value: Any) -> None:
    """Write a dotted ADJUSTABLE path on a config in place."""
    head, _, tail = path.partition(".")
    if tail:
        getattr(cfg, head)[tail] = value
    else:
        setattr(cfg, head, value)
