"""Bounded config loader/validator — the PROTOCOL boundary of the scanner-evolve loop.

The scanner self-evolve engine lets an LLM propose changes to the deterministic
event-driven scanner: detector thresholds, per-detector severity multipliers,
and the result ``top_n``. To keep the search safe and reproducible, the LLM is
NOT handed free rein: it may only edit fields declared in
:data:`SCANNER_ADJUSTABLE`, and only within their declared ranges. This module
is the gate that enforces that contract.

The fundamental scoring kernel is pinned: ``event_weight == 1.0`` and
``quant_weight == 0.0``. Those are NOT adjustable — invariant #2 says the
proposer can never re-enable the known-bad fundamental signals.

Pieces:

* :class:`ScannerEvolveConfig` — a plain dataclass mirroring
  ``scanner_skill_config.yaml``.
* :data:`SCANNER_ADJUSTABLE` — the allow-list. Maps a dotted path (e.g.
  ``"detectors.intraday_move.z_threshold"``, ``"top_n"``) to its ``(min, max)``
  bound. Any path NOT in this dict is fixed-kernel and off-limits.
* :func:`load_config` — parse yaml → build → validate.
* :func:`validate` — raise :class:`ConfigError` on any out-of-range / malformed
  field.
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

    Either a field is outside its :data:`SCANNER_ADJUSTABLE` range, a delta
    targets an unknown / non-adjustable path, or the structure is malformed.
    Subclasses ``ValueError`` so callers that already catch ``ValueError`` keep
    working.
    """


# ---------------------------------------------------------------------------
# The expected structure (locked to the real detector constructors).
# ---------------------------------------------------------------------------
#
# The SINGLE tunable detector and its adjustable param keys. The evolve set was
# re-scoped (2026-06-12) to ``intraday_move`` ONLY — the one detector with strong
# positive interestingness-vs-random (t=8). The old price detectors (high_breakout,
# ma_cross, gap, rsi_divergence) had negative/weak interestingness and left the
# evolve adjustable set. Names + baseline defaults mirror
# v2/scanner/detectors/intraday_move.py exactly.
_DETECTOR_PARAMS: dict[str, tuple[str, ...]] = {
    "intraday_move": ("z_window", "close_vs_open_pct", "gap_pct", "range_pct", "z_threshold"),
}
_DETECTOR_NAMES: tuple[str, ...] = tuple(_DETECTOR_PARAMS)

# Integer-valued adjustable paths (z_window + top_n; the rest are floats). Used
# by :func:`validate` to enforce int-ness.
_INT_PATHS: frozenset[str] = frozenset(
    {
        "detectors.intraday_move.z_window",
        "top_n",
    }
)


# ---------------------------------------------------------------------------
# The protocol boundary.
# ---------------------------------------------------------------------------
#
# Each entry is a dotted path the LLM is allowed to edit, mapped to its closed
# ``[min, max]`` numeric range. Paths NOT listed here are part of the fixed
# kernel (``event_weight``, ``quant_weight``) and are rejected by
# ``apply_delta``. Each baseline default lies inside its range.
SCANNER_ADJUSTABLE: dict[str, tuple[float, float]] = {
    # intraday_move detector thresholds.
    "detectors.intraday_move.z_window": (20, 120),
    "detectors.intraday_move.close_vs_open_pct": (0.02, 0.10),
    "detectors.intraday_move.gap_pct": (0.015, 0.08),
    "detectors.intraday_move.range_pct": (0.03, 0.12),
    "detectors.intraday_move.z_threshold": (1.5, 4.0),
    # Per-detector severity multiplier.
    "severity_mult.intraday_move": (0.5, 2.0),
    # Result count.
    "top_n": (10, 50),
}


@dataclass
class ScannerEvolveConfig:
    """Deterministic scanner config — mirrors ``scanner_skill_config.yaml``.

    ``detectors`` holds the per-detector adjustable params, ``severity_mult``
    the per-detector severity multipliers, ``top_n`` the result count. The
    fixed-kernel fields (``event_weight``, ``quant_weight``) are stored for
    reproducibility but are NOT in :data:`SCANNER_ADJUSTABLE`.
    """

    detectors: dict[str, dict[str, float]]
    severity_mult: dict[str, float]
    top_n: int
    event_weight: float = 1.0
    quant_weight: float = 0.0


def load_config(path: str | Path) -> ScannerEvolveConfig:
    """Parse a yaml config, build a :class:`ScannerEvolveConfig`, and validate it.

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


def _from_dict(raw: dict[str, Any]) -> ScannerEvolveConfig:
    """Build a :class:`ScannerEvolveConfig` from a parsed-yaml dict.

    Only keys matching dataclass fields are consumed; unknown top-level keys
    raise so a typo in the baseline yaml fails loudly rather than silently
    no-op'ing.
    """
    known = {f.name for f in fields(ScannerEvolveConfig)}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ConfigError(f"unknown config key(s): {unknown}; allowed: {sorted(known)}")
    required = {"detectors", "severity_mult", "top_n"}
    missing = sorted(required - set(raw))
    if missing:
        raise ConfigError(f"missing required config key(s): {missing}")
    return ScannerEvolveConfig(**raw)


def _get_path(cfg: ScannerEvolveConfig, path: str) -> Any:
    """Read a dotted SCANNER_ADJUSTABLE path off a config.

    Handles the 3-level ``detectors.<name>.<param>`` paths, the 2-level
    ``severity_mult.<name>`` paths, and the flat ``top_n``.
    """
    parts = path.split(".")
    container: Any = getattr(cfg, parts[0])
    for key in parts[1:]:
        container = container[key]
    return container


def _set_path(cfg: ScannerEvolveConfig, path: str, value: Any) -> None:
    """Write a dotted SCANNER_ADJUSTABLE path on a config in place."""
    parts = path.split(".")
    if len(parts) == 1:
        setattr(cfg, parts[0], value)
        return
    container: Any = getattr(cfg, parts[0])
    for key in parts[1:-1]:
        container = container[key]
    container[parts[-1]] = value


def validate(config: ScannerEvolveConfig) -> None:
    """Raise :class:`ConfigError` if the config violates the protocol.

    Enforces:

    * ``detectors`` keys == ``{"intraday_move"}`` with exactly its expected
      param keys; ``severity_mult`` keys == ``{"intraday_move"}``.
    * Every :data:`SCANNER_ADJUSTABLE` path within its ``[min, max]`` bound, and
      the integer-valued paths are integer-valued.
    * Fixed kernel: ``event_weight == 1.0`` and ``quant_weight == 0.0``.
    """
    # Structural: detector key set ({"intraday_move"}) + per-detector param key set.
    if set(config.detectors) != set(_DETECTOR_NAMES):
        raise ConfigError(f"detectors keys must be {sorted(_DETECTOR_NAMES)}, got {sorted(config.detectors)}")
    for name, expected_params in _DETECTOR_PARAMS.items():
        params = config.detectors[name]
        if not isinstance(params, dict):
            raise ConfigError(f"detectors.{name} must be a mapping, got {type(params).__name__}")
        if set(params) != set(expected_params):
            raise ConfigError(f"detectors.{name} params must be {sorted(expected_params)}, got {sorted(params)}")

    # Structural: severity_mult key set.
    if set(config.severity_mult) != set(_DETECTOR_NAMES):
        raise ConfigError(f"severity_mult keys must be {sorted(_DETECTOR_NAMES)}, got {sorted(config.severity_mult)}")

    # Every adjustable path within its [min, max] bound (+ int-ness).
    for path, (lo, hi) in SCANNER_ADJUSTABLE.items():
        try:
            value = _get_path(config, path)
        except (KeyError, AttributeError) as exc:
            raise ConfigError(f"config missing adjustable path {path!r}") from exc
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path} must be numeric, got {type(value).__name__}: {value!r}")
        if path in _INT_PATHS and float(value) != int(value):
            raise ConfigError(f"{path} must be an integer, got {value!r}")
        if not (lo <= value <= hi):
            raise ConfigError(f"{path}={value} out of range [{lo}, {hi}]")

    # Fixed kernel — invariant #2: never re-enable the known-bad fundamentals.
    if config.event_weight != 1.0:
        raise ConfigError(f"event_weight is fixed to 1.0, got {config.event_weight!r}")
    if config.quant_weight != 0.0:
        raise ConfigError(f"quant_weight is fixed to 0.0, got {config.quant_weight!r}")


def apply_delta(config: ScannerEvolveConfig, delta: dict[str, Any]) -> ScannerEvolveConfig:
    """Apply bounded edits and return a NEW validated config (input untouched).

    ``delta`` maps dotted :data:`SCANNER_ADJUSTABLE` paths to new values. An
    unknown path, a non-adjustable path (including ``quant_weight`` /
    ``event_weight``), or a value outside the declared range raises
    :class:`ConfigError`. The result is re-validated before return.
    """
    if not isinstance(delta, dict):
        raise ConfigError(f"delta must be a dict, got {type(delta).__name__}")

    # Deep-copy so the caller's config is never mutated, even on partial failure.
    draft = copy.deepcopy(config)

    for path, new_value in delta.items():
        if path not in SCANNER_ADJUSTABLE:
            raise ConfigError(f"path {path!r} is not adjustable; allowed: {sorted(SCANNER_ADJUSTABLE)}")
        if isinstance(new_value, bool) or not isinstance(new_value, (int, float)):
            raise ConfigError(f"delta value for {path!r} must be numeric, got {type(new_value).__name__}: {new_value!r}")
        lo, hi = SCANNER_ADJUSTABLE[path]
        if not (lo <= new_value <= hi):
            raise ConfigError(f"{path}={new_value} out of range [{lo}, {hi}]")
        # Integer-valued paths are stored as int; the rest as float.
        if path in _INT_PATHS:
            if float(new_value) != int(new_value):
                raise ConfigError(f"{path} must be an integer, got {new_value!r}")
            _set_path(draft, path, int(new_value))
        else:
            _set_path(draft, path, float(new_value))

    validate(draft)
    return draft
