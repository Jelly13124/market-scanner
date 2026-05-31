"""Findings-report renderer + verdict logic for the scanner-evaluation harness.

This module is the LAST mile of the eval pipeline: it turns the raw scorecard
rows (``detector_scorecard.score_all_detectors`` + ``signal_ic.score_all_signals``)
into the human-readable morning report. It is what the user reads first, so
clarity beats cleverness.

THE FRAMING (load-bearing)
--------------------------
The scanner is an **LLM-cost pre-filter**: its job is to concentrate the
expensive LLM budget on bars that actually move. So the PRIMARY detector verdict
is **interestingness vs random** — does the detector flag bigger movers than a
random baseline? Direction-adjusted alpha is shown only as *secondary colour*
and must NEVER be the sole basis for a CUT. A detector that flags big movers but
has no directional edge is still a useful screener.

Signals are point-in-time cross-sectional factors, judged by mean rank-IC.

Verdicts are computed from the **5d** rows (the primary horizon). The 20d rows
are carried through to the scorecard tables for colour but do not drive any
verdict.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Verdicts use this horizon's rows. Rows of other horizons are colour only.
PRIMARY_HORIZON = "5d"

#: Detector verdict thresholds.
_DET_MIN_N = 30  # below this total fires → DATA-LIMITED
_DET_MIN_COVERAGE = 0.5  # below this max coverage → DATA-LIMITED
_DET_T = 2.0  # |t| significance bar
_DET_KEEP_REGIMES = 2  # regimes that must clear (diff>0, t>=2) to KEEP

#: Signal verdict thresholds.
_SIG_MIN_N_DATES = 4  # below this max n_dates → DATA-LIMITED
_SIG_MIN_COVERAGE = 0.5  # below this max coverage → DATA-LIMITED
_SIG_IC = 0.02  # |mean_ic| bar for KEEP / INVERTED
_SIG_IC_DEAD = 0.01  # below this |mean_ic| in every regime → CUT
_SIG_T = 2.0  # |ic_t| significance bar
_SIG_KEEP_REGIMES = 2  # regimes that must clear to KEEP / INVERTED


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _primary(rows: list[dict]) -> list[dict]:
    """Keep only the primary-horizon rows of *rows*."""
    return [r for r in rows if r.get("horizon") == PRIMARY_HORIZON]


def _group_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    """Group *rows* by ``row[key]``, preserving first-seen order of the keys."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r[key], []).append(r)
    return out


def _attr(obj, name, default=None):
    """``getattr`` for objects, ``.get`` for dicts — RegimeWindow OR dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _fmt_pct(x) -> str:
    """A return/alpha as a signed percentage, e.g. ``+3.00%`` (``—`` if None)."""
    if x is None:
        return "—"
    return f"{x * 100:+.2f}%"


def _fmt_ic(x) -> str:
    """An IC value to 3 decimals, signed (``—`` if None)."""
    if x is None:
        return "—"
    return f"{x:+.3f}"


def _fmt_t(x) -> str:
    """A t-stat in parentheses, e.g. ``(t=3.0)`` (``(t=—)`` if None)."""
    if x is None:
        return "(t=—)"
    return f"(t={x:.1f})"


def _fmt_diff(x) -> str:
    """An interestingness diff (a |return| gap) as signed percentage points."""
    if x is None:
        return "—"
    return f"{x * 100:+.2f}pp"


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def classify_detector_verdict(rows_5d: list[dict]) -> str:
    """Verdict for one detector from its 5d rows across regimes.

    PRIMARY axis is interestingness-vs-random; directional alpha is never the
    sole basis for a CUT (it isn't consulted here at all).

      * **DATA-LIMITED** if ``max(coverage) < 0.5`` OR ``sum(n_fired) < 30`` —
        too thin to trust either way.
      * **KEEP** if ``interestingness_diff > 0`` AND ``interestingness_t >= 2``
        in at least 2 regimes — reliably flags bigger movers than random.
      * **CUT** if it fired enough (``sum(n_fired) >= 30``) AND either the mean
        interestingness diff is ``<= 0`` OR no single regime clears (diff>0,
        t>=2) — fired plenty but never beat random.
      * **WATCH** otherwise (suggestive but not yet conclusive).
    """
    rows = _primary(rows_5d)
    if not rows:
        return "DATA-LIMITED"

    coverages = [float(r.get("coverage", 0.0)) for r in rows]
    n_total = sum(int(r.get("n_fired", 0)) for r in rows)
    if max(coverages, default=0.0) < _DET_MIN_COVERAGE or n_total < _DET_MIN_N:
        return "DATA-LIMITED"

    diffs = [float(r.get("interestingness_diff", 0.0)) for r in rows]
    sig_positive = sum(1 for r in rows if float(r.get("interestingness_diff", 0.0)) > 0 and float(r.get("interestingness_t", 0.0)) >= _DET_T)
    if sig_positive >= _DET_KEEP_REGIMES:
        return "KEEP"

    mean_diff = sum(diffs) / len(diffs)
    if mean_diff <= 0 or sig_positive == 0:
        return "CUT"

    return "WATCH"


def classify_signal_verdict(rows_5d: list[dict]) -> str:
    """Verdict for one signal from its 5d rows across regimes.

    * **DATA-LIMITED** if ``max(coverage) < 0.5`` OR ``max(n_dates) < 4``.
    * **KEEP** if ``mean_ic >= 0.02`` AND ``ic_t >= 2`` in >= 2 regimes.
    * **INVERTED** if ``mean_ic <= -0.02`` AND ``ic_t <= -2`` in >= 2 regimes
      — a real signal pointing the wrong way (tradeable flipped).
    * **CUT** if it has enough dates (``max(n_dates) >= 4``) AND every regime's
      ``|mean_ic| < 0.01`` — pure noise.
    * **WATCH** otherwise.
    """
    rows = _primary(rows_5d)
    if not rows:
        return "DATA-LIMITED"

    coverages = [float(r.get("coverage", 0.0)) for r in rows]
    n_dates_max = max((int(r.get("n_dates", 0)) for r in rows), default=0)
    if max(coverages, default=0.0) < _SIG_MIN_COVERAGE or n_dates_max < _SIG_MIN_N_DATES:
        return "DATA-LIMITED"

    keep = sum(1 for r in rows if float(r.get("mean_ic", 0.0)) >= _SIG_IC and float(r.get("ic_t", 0.0)) >= _SIG_T)
    if keep >= _SIG_KEEP_REGIMES:
        return "KEEP"

    inverted = sum(1 for r in rows if float(r.get("mean_ic", 0.0)) <= -_SIG_IC and float(r.get("ic_t", 0.0)) <= -_SIG_T)
    if inverted >= _SIG_KEEP_REGIMES:
        return "INVERTED"

    if n_dates_max >= _SIG_MIN_N_DATES and all(abs(float(r.get("mean_ic", 0.0))) < _SIG_IC_DEAD for r in rows):
        return "CUT"

    return "WATCH"


def build_verdict_index(detector_rows, signal_rows) -> dict:
    """``{"detectors": {name: verdict}, "signals": {name: verdict}}``.

    Accepts the FULL (mixed-horizon) row lists; each classifier filters to the
    primary horizon itself. Used by the headline + the scorecard sort, and a
    convenient handle for tests.
    """
    det_groups = _group_by(detector_rows, "detector")
    sig_groups = _group_by(signal_rows, "signal")
    return {
        "detectors": {name: classify_detector_verdict(rows) for name, rows in det_groups.items()},
        "signals": {name: classify_signal_verdict(rows) for name, rows in sig_groups.items()},
    }


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

#: Verdict display order for the scorecard tables.
_DET_ORDER = {"KEEP": 0, "WATCH": 1, "CUT": 2, "DATA-LIMITED": 3}
_SIG_ORDER = {"KEEP": 0, "INVERTED": 1, "WATCH": 2, "CUT": 3, "DATA-LIMITED": 4}


def _sorted_names(verdicts: dict[str, str], order: dict[str, int]) -> list[str]:
    """Names sorted by verdict bucket (per *order*), then alphabetically."""
    return sorted(
        verdicts,
        key=lambda name: (order.get(verdicts[name], 99), name),
    )


# ---------------------------------------------------------------------------
# Rendering — sections
# ---------------------------------------------------------------------------


def _names_for(verdicts: dict[str, str], wanted: str) -> list[str]:
    """Alphabetical names whose verdict equals *wanted*."""
    return sorted(n for n, v in verdicts.items() if v == wanted)


def _join(names: list[str]) -> str:
    """Comma-join names, or an em dash placeholder when empty."""
    return ", ".join(names) if names else "—"


def _render_headline(index: dict) -> list[str]:
    det = index["detectors"]
    sig = index["signals"]
    lines = ["## Headline", ""]
    lines.append(f"**Useful detectors:** {_join(_names_for(det, 'KEEP'))}")
    lines.append(f"**Useless (consider cutting):** {_join(_names_for(det, 'CUT'))}")
    lines.append(f"**Data-limited:** {_join(_names_for(det, 'DATA-LIMITED'))}")
    lines.append("")
    lines.append(f"**Useful signals:** {_join(_names_for(sig, 'KEEP'))}")
    lines.append(f"**Inverted:** {_join(_names_for(sig, 'INVERTED'))}")
    lines.append(f"**Useless:** {_join(_names_for(sig, 'CUT'))}")
    lines.append(f"**Data-limited:** {_join(_names_for(sig, 'DATA-LIMITED'))}")
    lines.append("")
    return lines


def _det_cell(row: dict | None) -> str:
    """Per-regime detector cell: ``n / Δint (t) / dirα`` (``—`` if no row)."""
    if row is None:
        return "—"
    n = int(row.get("n_fired", 0))
    diff = _fmt_diff(row.get("interestingness_diff"))
    t = _fmt_t(row.get("interestingness_t"))
    da = _fmt_pct(row.get("dir_alpha_mean"))
    return f"{n} / {diff} {t} / {da}"


def _render_detector_table(detector_rows, index, regimes) -> list[str]:
    verdicts = index["detectors"]
    names = _sorted_names(verdicts, _DET_ORDER)
    # Column order follows the regime windows we were given (5d rows only).
    rows_5d = _primary(detector_rows)
    by_det = _group_by(rows_5d, "detector")
    regime_names = [_attr(r, "name") for r in regimes]
    regime_labels = {_attr(r, "name"): _attr(r, "label", _attr(r, "name")) for r in regimes}

    header = ["Detector", "Verdict"] + [f"{regime_labels[rn]} ({rn})" for rn in regime_names]
    lines = ["## Detector scorecard", ""]
    lines.append("Per-regime cell: `n / Δinterestingness (t) / dir-α`. " "Interestingness-vs-random is primary; dir-α is secondary colour.")
    lines.append("")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for name in names:
        cells_by_regime = {r["regime"]: r for r in by_det.get(name, [])}
        cells = [_det_cell(cells_by_regime.get(rn)) for rn in regime_names]
        lines.append("| " + " | ".join([name, verdicts[name]] + cells) + " |")
    lines.append("")
    return lines


def _sig_cell(row: dict | None) -> str:
    """Per-regime signal cell: ``IC (t) / n`` (``—`` if no row)."""
    if row is None:
        return "—"
    ic = _fmt_ic(row.get("mean_ic"))
    t = _fmt_t(row.get("ic_t"))
    n = int(row.get("n_dates", 0))
    return f"{ic} {t} / {n}"


def _render_signal_table(signal_rows, index, regimes) -> list[str]:
    verdicts = index["signals"]
    names = _sorted_names(verdicts, _SIG_ORDER)
    rows_5d = _primary(signal_rows)
    by_sig = _group_by(rows_5d, "signal")
    regime_names = [_attr(r, "name") for r in regimes]
    regime_labels = {_attr(r, "name"): _attr(r, "label", _attr(r, "name")) for r in regimes}

    header = ["Signal", "Verdict"] + [f"{regime_labels[rn]} ({rn})" for rn in regime_names]
    lines = ["## Signal scorecard", ""]
    lines.append("Per-regime cell: `mean rank-IC (t) / n_dates`.")
    lines.append("")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for name in names:
        cells_by_regime = {r["regime"]: r for r in by_sig.get(name, [])}
        cells = [_sig_cell(cells_by_regime.get(rn)) for rn in regime_names]
        lines.append("| " + " | ".join([name, verdicts[name]] + cells) + " |")
    lines.append("")
    return lines


def _render_phase3(phase3) -> list[str]:
    lines = ["## Phase 3 — full-replay confirmation", ""]
    if phase3 is None:
        lines.append("_pending / not run_")
        lines.append("")
        return lines
    lines.append("Bounded full-replay over each regime: mean 5d alpha, and the quant " "overlay ON vs OFF delta.")
    lines.append("")
    lines.append("| Regime | mean alpha 5d | quant ON | quant OFF | ON − OFF |")
    lines.append("|---|---|---|---|---|")
    for regime, d in phase3.items():
        mean_alpha = d.get("mean_alpha_5d")
        on = d.get("quant_on")
        off = d.get("quant_off")
        delta = (on - off) if (on is not None and off is not None) else None
        lines.append(
            "| "
            + " | ".join(
                [
                    str(regime),
                    _fmt_pct(mean_alpha),
                    _fmt_pct(on),
                    _fmt_pct(off),
                    _fmt_pct(delta),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _render_regimes(regimes) -> list[str]:
    lines = ["## Regime windows", ""]
    lines.append("| Regime | Label | Dates | SPY return | Max drawdown | Trend R² |")
    lines.append("|---|---|---|---|---|---|")
    for r in regimes:
        name = _attr(r, "name", "?")
        label = _attr(r, "label", "?")
        start = _attr(r, "start", "?")
        end = _attr(r, "end", "?")
        spy = _attr(r, "spy_return")
        mdd = _attr(r, "max_drawdown")
        r2 = _attr(r, "trend_r2")
        r2_s = "—" if r2 is None else f"{float(r2):.2f}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(name),
                    str(label),
                    f"{start} → {end}",
                    _fmt_pct(spy),
                    _fmt_pct(mdd),
                    r2_s,
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _render_methodology() -> list[str]:
    return [
        "## Methodology & caveats",
        "",
        "- **No lookahead.** Detectors/signals decide through `CachedAsOfClient`, " "which clamps every read to `<= asof`; forward returns are measured from " "the full (post-asof) series only at scoring time.",
        "- **Adjusted close** preferred everywhere, so ex-div / split days don't " "manufacture fake moves.",
        "- **Fundamental availability lag (~60d).** Point-in-time fundamentals are " "treated as available only after a reporting lag, so value/quality factors " "aren't credited with data they couldn't have had.",
        "- **Survivorship bias.** The universe is a *current* snapshot " "(delisted names absent), which flatters long-only stats — read directional " "alpha with that caveat.",
        "- **Interestingness is primary.** The scanner is an LLM-cost pre-filter; a " "detector earns its budget by flagging bigger movers than random. " "Directional alpha is secondary colour and never the sole basis for a CUT.",
        "- **Low-n / low-coverage → DATA-LIMITED.** Detectors/signals that barely " "fired or covered little of the universe are flagged, not judged.",
        "- **Seeded baselines.** Random interestingness baselines use a fixed seed, " "so the report is deterministic and reproducible.",
        "",
    ]


# ---------------------------------------------------------------------------
# render_report / write_report
# ---------------------------------------------------------------------------


def render_report(
    *,
    detector_rows,
    signal_rows,
    regimes,
    phase3=None,
    universe="nasdaq100_sp500",
    generated_at="(pending)",
) -> str:
    """Render the complete markdown evaluation report.

    Sections, in order: title + intro, Headline, Detector scorecard, Signal
    scorecard, Phase 3, Regime windows, Methodology & caveats.
    """
    index = build_verdict_index(detector_rows, signal_rows)

    lines: list[str] = []
    lines.append("# Scanner detector & signal usefulness — evaluation report")
    lines.append("")
    lines.append(f"Regime-segmented usefulness study over `{universe}`. Primary axis is " "**interestingness vs random** (does it flag bigger movers than random); " "directional alpha / IC is secondary colour. " f"Generated at: {generated_at}.")
    lines.append("")

    lines.extend(_render_headline(index))
    lines.extend(_render_detector_table(detector_rows, index, regimes))
    lines.extend(_render_signal_table(signal_rows, index, regimes))
    lines.extend(_render_phase3(phase3))
    lines.extend(_render_regimes(regimes))
    lines.extend(_render_methodology())

    return "\n".join(lines).rstrip() + "\n"


def write_report(path, **kwargs) -> None:
    """Render via :func:`render_report` and write it to *path* as UTF-8."""
    text = render_report(**kwargs)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    logger.info("wrote eval report to %s (%d chars)", path, len(text))
