"""Pydantic models for the scanner pipeline.

These are the in-process types — pure Python, no DB, no HTTP. The backend
service layer translates them to/from SQLAlchemy + REST schemas.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Direction = Literal["bullish", "bearish", "neutral"]


class ScannerWeights(BaseModel):
    """Composite-score weights. Configurable per ScannerConfig."""

    # Quant overlay OFF by default (2026-06-01). The detector-only composite beat
    # SPY in all 3 regimes (bear +1.04% / bull +0.79% / choppy +1.93% 5d alpha),
    # while turning the quant signals ON dragged it down every regime (−1.83% in
    # bear). See findings_scanner_eval.md (Phase 3). Reversible per-config — set
    # quant_weight > 0 on a ScannerConfig to re-enable once the fundamental signals
    # have a real point-in-time data source. Signal CODE is kept, just unweighted.
    event_weight: float = 1.00
    quant_weight: float = 0.00
    factor_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "momentum": 0.30,
            "value": 0.20,
            "quality": 0.20,
            "earnings_quality": 0.15,
            "technical": 0.15,
        },
        description="Within the quant term; renormalized over factors present.",
    )
    enabled_detectors: list[str] | None = Field(
        default=None,
        description=(
            "Detector .name strings to run for this config. None means run "
            "all registered detectors (preserves pre-feature behavior). Empty "
            "list is rejected at validation."
        ),
    )
    detector_severity_mult: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "Per-detector severity multipliers applied to abs(severity_z) "
            "before the max-takes-all in event_score. Missing keys default "
            "to 1.0 (neutral). Values must be in [0.0, 5.0]."
        ),
    )

    @field_validator("enabled_detectors")
    @classmethod
    def _validate_enabled_detectors(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError("enabled_detectors cannot be empty — pick at least one")
        # Lazy import to avoid circular dependency
        # (v2.scanner.detectors → base.py → v2.scanner.models).
        from v2.scanner.detectors import ALL_DETECTORS, LEGACY_DETECTOR_ALIASES
        registered = {c().name for c in ALL_DETECTORS}
        # Legacy keys (e.g. "earnings_surprise") pass validation; they get
        # rewritten to the canonical replacement below so the rest of the
        # pipeline only ever sees current names.
        valid = registered | set(LEGACY_DETECTOR_ALIASES.keys())
        bad = sorted(set(v) - valid)
        if bad:
            raise ValueError(
                f"unknown detector name(s): {bad}; valid: {sorted(registered)}"
            )
        # Dedupe + alias rewrite while preserving order.
        seen: set[str] = set()
        out: list[str] = []
        for name in v:
            canonical = LEGACY_DETECTOR_ALIASES.get(name, name)
            if canonical not in seen:
                seen.add(canonical)
                out.append(canonical)
        return out

    @field_validator("detector_severity_mult")
    @classmethod
    def _validate_severity_mult(cls, v: dict[str, float]) -> dict[str, float]:
        if not v:
            return v
        from v2.scanner.detectors import ALL_DETECTORS, LEGACY_DETECTOR_ALIASES
        registered = {c().name for c in ALL_DETECTORS}
        valid = registered | set(LEGACY_DETECTOR_ALIASES.keys())
        bad_names = sorted(set(v.keys()) - valid)
        if bad_names:
            raise ValueError(
                f"unknown detector name(s) in detector_severity_mult: {bad_names}; "
                f"valid: {sorted(registered)}"
            )
        for name, mult in v.items():
            if not isinstance(mult, (int, float)):
                raise ValueError(
                    f"detector_severity_mult[{name}] must be numeric, got {type(mult).__name__}"
                )
            if not (0.0 <= float(mult) <= 5.0):
                raise ValueError(
                    f"detector_severity_mult[{name}]={mult} out of range [0.0, 5.0]"
                )
        # Rewrite legacy keys → canonical. If both an old and new key exist
        # we keep the canonical entry's value (user-specified wins over
        # auto-aliased default).
        out: dict[str, float] = {}
        for name, mult in v.items():
            canonical = LEGACY_DETECTOR_ALIASES.get(name, name)
            if canonical in out:
                continue
            out[canonical] = float(mult)
        return out


class ScoredEntry(BaseModel):
    """One ranked ticker produced by the scanner.

    ``event_severity`` is the raw, un-clipped max ``|severity_z|`` across all
    triggered detectors. It exists purely as a deterministic tiebreaker when
    multiple tickers all hit ``composite_score = 100`` (severity clipped at
    5σ). Without it, top-N picks ties get arbitrarily ordered by thread
    completion timing.
    """

    ticker: str
    composite_score: float = Field(..., ge=0.0, le=100.0)
    direction: Direction = "neutral"
    event_score: float = Field(..., ge=0.0, le=100.0)
    quant_score: float | None = None
    event_severity: float = Field(0.0, ge=0.0)
    # Triggered EventTrigger objects, serialized to dicts for portability.
    triggers: list[dict] = Field(default_factory=list)
    rank: int = 0


class ScanContext(BaseModel):
    """Per-ticker shared cache passed to detectors so they can dedupe API calls.

    Detectors are free to read/write to this; the runner constructs a fresh one
    per ticker. Keep it lean — no detector-specific blobs here, just things
    multiple detectors care about.

    ``benchmark_prices`` is the same shared list reference (read-only) injected
    into every per-ticker context so detectors like ``IntradayMoveDetector``
    can subtract market-wide moves to isolate idiosyncratic flow.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    ticker: str
    end_date: str
    market_cap: float | None = None
    benchmark_prices: list[Any] | None = None
    # Precomputed benchmark same-day (cvo, gap) keyed by ISO date string,
    # populated once by the runner from ``benchmark_prices``. Empty/None when
    # no benchmark is configured. Keeps IntradayMoveDetector from
    # rebuilding this dict per ticker (was O(60 × n_tickers) → now O(60)).
    benchmark_cvo_gap_by_date: dict[str, tuple[float, float]] | None = None
    # Per-ticker historical analyst-target snapshots (oldest→newest) for the
    # past N days, populated by the runner BEFORE the worker pool starts
    # (M9.d). Each entry is duck-typed; the consuming detector accesses
    # ``.asof_date``, ``.target_median``, ``.target_mean``. None = no
    # snapshots available, detector falls back to no-op.
    target_snapshots: list[Any] | None = None
    # Map of ticker → calendar-days-to-next-earnings (within configured
    # lookahead window). Populated once by the runner via Finnhub's
    # /calendar/earnings bulk endpoint and shared by reference across all
    # per-ticker contexts (M9.f). ``None`` = scanner didn't load a
    # calendar (older config / Finnhub fetch failed); detector returns
    # ``None`` cleanly. A populated dict missing a given ticker means
    # "calendar loaded but ticker has no event in window" → detector
    # returns ``triggered=False``.
    upcoming_earnings_days_to: dict[str, int] | None = None
