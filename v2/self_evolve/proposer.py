"""The LLM proposer seam — turns the kernel + recent val history into ONE
bounded config delta.

This is the only place the self-evolve loop hands the wheel to an LLM, and it is
deliberately narrow: the model is asked for a SINGLE single-field change to an
:data:`~v2.self_evolve.config.ADJUSTABLE` parameter, and whatever comes back is
validated through :func:`~v2.self_evolve.config.apply_delta` before it is
trusted. A bad proposal (malformed JSON, an unknown / non-adjustable path, an
out-of-range value, or an ``llm_fn`` that raises) yields ``None`` — never an
exception. The loop treats ``None`` as "skip this iteration."

Return shape (the loop consumes this):

    {"path": <one of ADJUSTABLE>, "value": <number>, "hypothesis": <one line>}
    # or None

``llm_fn`` is injectable so tests stub it offline; the default lazily binds
DeepSeek so importing this module never touches the network.
"""

from __future__ import annotations

import json
import logging

from v2.self_evolve.config import ADJUSTABLE, StrategyConfig
from v2.self_evolve.config import apply_delta as _factor_apply_delta

try:  # asdict on a StrategyConfig; dataclasses is stdlib so this always succeeds.
    from dataclasses import asdict
except ImportError:  # pragma: no cover - defensive only
    asdict = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

#: Default model coordinates for the lazily-bound DeepSeek ``llm_fn``. Only
#: touched when ``propose`` is called WITHOUT an explicit ``llm_fn`` — tests
#: always inject a stub, so this never runs offline.
_DEFAULT_MODEL = "deepseek-v4-pro"


def _default_llm_fn(prompt: str) -> str:
    """Lazily bind DeepSeek and return the raw completion text.

    Imported and constructed inside the call (not at module import) so that
    merely importing :mod:`proposer` — as the offline test-suite does — never
    pulls in the LLM stack or reaches the network.
    """
    from src.llm.models import ModelProvider, get_model

    model = get_model(_DEFAULT_MODEL, ModelProvider.DEEPSEEK)
    return model.invoke(prompt).content


def _build_prompt(skill_md: str, config: StrategyConfig, val_history: list[dict], adjustable: dict) -> str:
    """Assemble the proposer prompt from kernel + current config + recent history.

    The prompt is intentionally explicit about the OUTPUT contract (a single
    JSON object with ``path`` / ``value`` / ``hypothesis``) and lists the exact
    set of legal paths (from ``adjustable``) so the model cannot wander outside
    the allow-list.
    """
    config_dict = asdict(config) if asdict is not None else {}
    recent = val_history[-5:] if val_history else []
    adjustable_lines = "\n".join(f"  - {path}: range [{lo}, {hi}]" for path, (lo, hi) in adjustable.items())

    return (
        "You are tuning a deterministic factor strategy. You may ONLY change one\n"
        "single field, and only within its declared range.\n\n"
        "=== KERNEL / DISCIPLINE ===\n"
        f"{skill_md}\n\n"
        "=== CURRENT CONFIG ===\n"
        f"{json.dumps(config_dict, indent=2, sort_keys=True)}\n\n"
        "=== RECENT VALIDATION HISTORY (most recent last) ===\n"
        f"{json.dumps(recent, indent=2, sort_keys=False)}\n\n"
        "=== ADJUSTABLE PARAMETERS (path: range) ===\n"
        f"{adjustable_lines}\n\n"
        "=== TASK ===\n"
        "Propose ONE single-field change to an ADJUSTABLE parameter that you\n"
        "hypothesize will improve validation Sharpe. Respond with a SINGLE JSON\n"
        "object and nothing else:\n"
        '{"path": <one of the ADJUSTABLE paths above>, '
        '"value": <number>, "hypothesis": <one line>}'
    )


def _extract_json_object(text: str) -> dict | None:
    """Extract the first balanced ``{...}`` JSON object from ``text``.

    Tolerates code fences (```json … ```) and surrounding prose by scanning for
    the first ``{`` and walking to its matching ``}`` with brace-depth tracking
    (string-/escape-aware so braces inside string values don't fool it). Returns
    the parsed dict, or ``None`` if nothing parseable is found.
    """
    if not isinstance(text, str):
        return None
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    obj = json.loads(candidate)
                except ValueError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


def propose(
    skill_md: str,
    config: StrategyConfig,
    val_history: list[dict],
    *,
    llm_fn=None,
    adjustable=None,
    apply_delta=None,
) -> dict | None:
    """Ask the LLM for ONE bounded config delta; validate it; return it or ``None``.

    Parameters
    ----------
    skill_md
        The kernel / discipline text (the fixed strategy contract) injected into
        the prompt.
    config
        The current :class:`~v2.self_evolve.config.StrategyConfig`; both prompt
        context and the validation baseline.
    val_history
        Recent ``{v_id, val_sharpe, delta, kept}`` records; the last few are
        shown to the model.
    llm_fn
        ``llm_fn(prompt: str) -> str`` returning the raw completion. Injected by
        tests; defaults to a lazily-bound DeepSeek call.
    adjustable
        The allow-list mapping ``{path: (lo, hi)}`` used for the path check and
        the prompt. Defaults to the factor
        :data:`~v2.self_evolve.config.ADJUSTABLE`. The scanner injects
        ``SCANNER_ADJUSTABLE``.
    apply_delta
        The authoritative ``apply_delta(config, {path: value}) -> config`` gate
        (raises a ``ValueError`` subclass on a bad delta). Defaults to the factor
        :func:`~v2.self_evolve.config.apply_delta`. Must be paired with the
        matching ``adjustable`` allow-list.

    Returns
    -------
    dict | None
        ``{"path": <adjustable path>, "value": <number>, "hypothesis": <str>}``
        when the proposal validates (the path is in ``adjustable`` AND
        ``apply_delta`` accepts it in-range), else ``None``. NEVER raises — bad
        JSON, unknown/out-of-range paths, and an ``llm_fn`` that raises all map to
        ``None`` (logged at debug).
    """
    fn = llm_fn or _default_llm_fn
    adjustable = ADJUSTABLE if adjustable is None else adjustable
    apply_delta = _factor_apply_delta if apply_delta is None else apply_delta

    prompt = _build_prompt(skill_md, config, val_history or [], adjustable)

    try:
        raw = fn(prompt)
    except Exception as exc:  # llm_fn failures must not escape.
        logger.debug("proposer: llm_fn raised: %s", exc)
        return None

    obj = _extract_json_object(raw if isinstance(raw, str) else str(raw))
    if obj is None:
        logger.debug("proposer: no JSON object found in response")
        return None

    path = obj.get("path")
    value = obj.get("value")
    hypothesis = obj.get("hypothesis", "")

    if not isinstance(path, str) or path not in adjustable:
        logger.debug("proposer: path %r not in adjustable allow-list", path)
        return None
    # Numeric-but-not-bool (apply_delta enforces this too, but reject early so a
    # bool/str never reaches it).
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        logger.debug("proposer: value %r for %r is not numeric", value, path)
        return None

    # The authoritative gate: apply_delta re-checks the range and rebuilds a
    # validated config. If it complains (a ValueError subclass — both factor and
    # scanner ConfigError subclass ValueError), the proposal is rejected.
    try:
        apply_delta(config, {path: value})
    except ValueError as exc:
        logger.debug("proposer: apply_delta rejected {%r: %r}: %s", path, value, exc)
        return None

    return {"path": path, "value": value, "hypothesis": hypothesis}
