"""The evolution LOOP — the deterministic keep/rollback driver of self-evolve.

This is the load-bearing orchestrator. Given price ``bundles`` and a baseline
:class:`~v2.self_evolve.config.StrategyConfig`, it runs ``iterations`` rounds of:

    propose a bounded delta  →  apply it  →  backtest train + val  →
    KEEP it (if it strictly beats the running-best on VALIDATION Sharpe and
    clears the turnover / drawdown guardrails) or ROLL BACK to the running-best.

Every round is persisted via :mod:`v2.self_evolve.versioning` (a full
``version.json`` plus a one-line ``path_log.jsonl`` entry) so the optimization
path is replayable, and the loop is RESUMABLE: pointed at a ``base_dir`` that
already holds versions, it continues the round counter and restores the
running-best from the last KEPT version rather than starting over.

THE hard invariant (sample isolation): the loop reads **train** (to evaluate a
candidate's fit) and **val** (to decide keep/rollback) ONLY. The held-out
**test** window is NEVER backtested anywhere in here — that is what keeps the
final out-of-sample evaluation honest. The two backtest call sites below pass
``"train"`` / ``"val"`` as literals and nothing in this module ever passes
``"test"``.

Seams ``propose_fn`` and ``backtest_fn`` are injectable so tests stub them
offline; they default to the real :func:`v2.self_evolve.proposer.propose` and
:func:`v2.self_evolve.backtest.backtest`. The loop NEVER raises on a single bad
round — a proposer that declines, a delta that fails to apply, or a backtest
that returns junk all degrade to "roll back / skip this round".

Pure orchestration — no network, no LLM, no pandas of its own (the injected
backtest may use them).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, fields

from v2.self_evolve import backtest as _backtest_mod
from v2.self_evolve import proposer as _proposer_mod
from v2.self_evolve.config import ConfigError, StrategyConfig, apply_delta
from v2.self_evolve.versioning import (
    append_path_log,
    list_versions,
    read_path_log,
    read_version,
    write_version,
)

logger = logging.getLogger(__name__)

#: The id stamped for the baseline (un-evolved) config.
_BASELINE_ID = "v0"

#: Per-round version id prefix; round ``r`` is ``f"{_ROUND_PREFIX}{r}"`` → ``v0.0.<r>``.
_ROUND_PREFIX = "v0.0."

#: Guardrail constants (documented, sensible defaults).
#: A kept candidate's val turnover may not exceed ``base_turnover × TURNOVER_MULT``…
TURNOVER_MULT = 1.5
#: …and its val max-drawdown may not be worse than the running-best's by more
#: than ``MAXDD_TOLERANCE_PP`` percentage points (drawdown is a NEGATIVE percent).
MAXDD_TOLERANCE_PP = 5.0


def _rebuild_config(config_dict: dict) -> StrategyConfig:
    """Reconstruct a :class:`StrategyConfig` from a persisted ``asdict`` mapping.

    Only known dataclass fields are consumed (forward/backward-compatible with a
    record that carried extra keys). ``__post_init__`` re-normalizes the factor
    weights — idempotent for an already-normalized stored config.
    """
    known = {f.name for f in fields(StrategyConfig)}
    kwargs = {k: v for k, v in config_dict.items() if k in known}
    return StrategyConfig(**kwargs)


def _round_id(r: int) -> str:
    return f"{_ROUND_PREFIX}{r}"


def _parse_round(v_id: str) -> int | None:
    """Round number from a ``v0.0.<r>`` id, or ``None`` for anything else (e.g. ``v0``)."""
    if not v_id.startswith(_ROUND_PREFIX):
        return None
    tail = v_id[len(_ROUND_PREFIX) :]
    try:
        return int(tail)
    except ValueError:
        return None


def _resume_state(base_dir):
    """Best-effort resume: (start_round, running_best_config, best_sharpe, best_maxdd).

    Returns ``None`` when ``base_dir`` holds no prior versions (fresh start).
    Otherwise scans the on-disk versions to find:

    * ``start_round`` — one past the highest ``v0.0.<r>`` round seen, so the new
      run continues the counter instead of clobbering existing versions; and
    * the running-best — taken from the LAST KEPT version (the most recent round
      whose ``kept`` is True, else the ``v0`` baseline), restoring its config and
      its val Sharpe / max-drawdown so keep/rollback picks up where it left off.

    Anything unreadable is skipped; this never raises.
    """
    existing = list_versions(base_dir)
    if not existing:
        return None

    # Highest round index present → resume counter just past it.
    max_round = 0
    for v_id in existing:
        r = _parse_round(v_id)
        if r is not None and r > max_round:
            max_round = r
    start_round = max_round + 1

    # Walk rounds high→low to find the last KEPT version; fall back to v0.
    best_record: dict | None = None
    for r in range(max_round, 0, -1):
        rec = read_version(base_dir, _round_id(r))
        if rec.get("kept") is True and isinstance(rec.get("config"), dict):
            best_record = rec
            break
    if best_record is None:
        v0 = read_version(base_dir, _BASELINE_ID)
        if isinstance(v0.get("config"), dict):
            best_record = v0

    if best_record is None:
        # Versions exist but none are readable enough to restore a config.
        return start_round, None, None, None

    try:
        cfg = _rebuild_config(best_record["config"])
    except (TypeError, ValueError, KeyError):
        return start_round, None, None, None

    val_m = best_record.get("val_metrics") or {}
    return start_round, cfg, val_m.get("sharpe"), val_m.get("max_drawdown")


def _keep(candidate_val: dict, best_sharpe, best_maxdd, turnover_ceiling) -> bool:
    """The deterministic KEEP rule. ``True`` → keep the candidate, else roll back.

    Keep iff ALL hold:

    * the candidate's val Sharpe is not ``None`` and strictly beats the
      running-best (``> best_sharpe``; a ``None`` best — degenerate baseline — is
      treated as ``-inf`` so any real Sharpe clears it);
    * val turnover is within the ceiling ``base_turnover × TURNOVER_MULT``; and
    * val max-drawdown is no worse than ``best_maxdd - MAXDD_TOLERANCE_PP``
      (drawdown is a negative percent; "not worse by more than 5pp").

    A missing turnover / drawdown on the candidate fails the corresponding
    guardrail (we cannot certify a metric we don't have).
    """
    sharpe = candidate_val.get("sharpe")
    if sharpe is None:
        return False
    floor_sharpe = float("-inf") if best_sharpe is None else best_sharpe
    if not (sharpe > floor_sharpe):
        return False

    turnover = candidate_val.get("turnover")
    if turnover is None or turnover > turnover_ceiling:
        return False

    maxdd = candidate_val.get("max_drawdown")
    if maxdd is None:
        return False
    # If we have no baseline drawdown to compare against, the Sharpe + turnover
    # gates suffice; otherwise enforce the "not worse by > 5pp" floor.
    if best_maxdd is not None and maxdd < best_maxdd - MAXDD_TOLERANCE_PP:
        return False

    return True


def evolve(
    bundles,
    base_config: StrategyConfig,
    *,
    iterations: int,
    base_dir,
    skill_md: str = "",
    propose_fn=None,
    backtest_fn=None,
) -> list[dict]:
    """Run the evolution loop and return the optimization path log.

    Parameters
    ----------
    bundles
        ``{ticker: bundle}`` passed straight through to ``backtest_fn`` — opaque
        to the loop itself.
    base_config
        The baseline :class:`StrategyConfig`. On a FRESH ``base_dir`` it seeds the
        running-best (recorded as ``v0``); when RESUMING it is overridden by the
        last kept version restored from disk.
    iterations
        Number of propose→evaluate rounds to attempt this invocation. A round
        that the proposer declines (``None``) or whose delta fails to apply is
        skipped (writes no version) but still consumes one iteration.
    base_dir
        Directory for the version store / path log (see
        :mod:`v2.self_evolve.versioning`). Resumed if it already holds versions.
    skill_md
        Kernel / discipline text forwarded to ``propose_fn``.
    propose_fn
        ``propose_fn(skill_md, config, val_history, *, llm_fn=None) -> dict | None``.
        Defaults to :func:`v2.self_evolve.proposer.propose`.
    backtest_fn
        ``backtest_fn(bundles, config, sample) -> metrics``. Defaults to
        :func:`v2.self_evolve.backtest.backtest`. **Only ever called with**
        ``sample`` in ``{"train", "val"}`` — never ``"test"``.

    Returns
    -------
    list[dict]
        The full path log (``read_path_log(base_dir)``) — every ``v0`` / ``v0.0.<r>``
        entry across this and any prior runs, in append order.
    """
    propose_fn = propose_fn or _proposer_mod.propose
    # One shared factor cache for the whole run: bundles are immutable across all
    # iterations, so a weight-only delta is a pure hit. Only bound when the DEFAULT
    # backtest is used — an injected backtest_fn keeps its (bundles, config, sample)
    # contract untouched (it never receives a cache kwarg).
    if backtest_fn is None:
        _factor_cache: dict = {}

        def backtest_fn(b, c, s):
            return _backtest_mod.backtest(b, c, s, cache=_factor_cache)

    # -- 1. Establish the running-best, resuming from disk if possible.
    resumed = _resume_state(base_dir)
    if resumed is None:
        # Fresh start: backtest the baseline on TRAIN + VAL (never test) and
        # record it as v0 — the initial running-best.
        base_train = backtest_fn(bundles, base_config, "train")
        base_val = backtest_fn(bundles, base_config, "val")
        current_config = base_config
        best_sharpe = base_val.get("sharpe")
        best_maxdd = base_val.get("max_drawdown")
        base_turnover = base_val.get("turnover")

        write_version(
            base_dir,
            _BASELINE_ID,
            {
                "config": asdict(base_config),
                "train_metrics": base_train,
                "val_metrics": base_val,
                "hypothesis": "baseline",
                "kept": True,
                "attribution": {"parent": None, "delta": None},
            },
        )
        append_path_log(
            base_dir,
            {"v_id": _BASELINE_ID, "hypothesis": "baseline", "val_sharpe": best_sharpe, "kept": True},
        )
        start_round = 1
    else:
        start_round, restored_cfg, best_sharpe, best_maxdd = resumed
        current_config = restored_cfg if restored_cfg is not None else base_config
        # Recover the baseline turnover ceiling from the persisted v0 record so
        # the guardrail stays anchored to the ORIGINAL baseline across resumes.
        base_turnover = None
        v0 = read_version(base_dir, _BASELINE_ID)
        v0_val = v0.get("val_metrics") if isinstance(v0, dict) else None
        if isinstance(v0_val, dict):
            base_turnover = v0_val.get("turnover")
        logger.info("evolve: resuming at round %d (best val sharpe=%s)", start_round, best_sharpe)

    # The turnover guardrail ceiling. If the baseline had no measurable turnover
    # (degenerate baseline), fall back to +inf so the guardrail is a no-op rather
    # than rejecting everything — Sharpe + drawdown still gate keeps.
    turnover_ceiling = base_turnover * TURNOVER_MULT if isinstance(base_turnover, (int, float)) else float("inf")

    # -- 2. Evolution rounds.
    for offset in range(iterations):
        r = start_round + offset
        v_id = _round_id(r)

        # Build the val-history view the proposer sees from the live path log.
        val_history = read_path_log(base_dir)

        # a. Propose. A None proposal (or a proposer that itself raises) skips the
        #    round and writes nothing.
        try:
            prop = propose_fn(skill_md, current_config, val_history, llm_fn=None)
        except Exception as exc:  # a stubbed/real proposer must never crash the loop.
            logger.warning("evolve: propose_fn raised on round %d; skipping: %s", r, exc)
            continue
        if not prop:
            logger.info("evolve: round %d proposer declined (None); skipping", r)
            continue

        # b. Apply the bounded delta. A ConfigError (out-of-range / bad path) skips.
        try:
            candidate = apply_delta(current_config, {prop["path"]: prop["value"]})
        except (ConfigError, KeyError, TypeError) as exc:
            logger.warning("evolve: round %d delta %r rejected; skipping: %s", r, prop, exc)
            continue

        # c. Score the candidate on TRAIN + VAL. NEVER "test".
        try:
            train_m = backtest_fn(bundles, candidate, "train")
            val_m = backtest_fn(bundles, candidate, "val")
        except Exception as exc:  # a junk backtest is a rolled-back round, not a crash.
            logger.warning("evolve: round %d backtest raised; skipping: %s", r, exc)
            continue

        # d. Keep / rollback decision.
        kept = _keep(val_m, best_sharpe, best_maxdd, turnover_ceiling)

        # e. On keep, the candidate becomes the new running-best.
        if kept:
            current_config = candidate
            best_sharpe = val_m.get("sharpe")
            best_maxdd = val_m.get("max_drawdown")

        # f. Persist the round (whether kept or rolled back).
        hypothesis = prop.get("hypothesis", "")
        write_version(
            base_dir,
            v_id,
            {
                "config": asdict(candidate),
                "train_metrics": train_m,
                "val_metrics": val_m,
                "hypothesis": hypothesis,
                "kept": kept,
                "attribution": {"path": prop.get("path"), "value": prop.get("value")},
            },
        )
        append_path_log(
            base_dir,
            {"v_id": v_id, "hypothesis": hypothesis, "val_sharpe": val_m.get("sharpe"), "kept": kept},
        )

    # -- 3. Return the full optimization path.
    return read_path_log(base_dir)
