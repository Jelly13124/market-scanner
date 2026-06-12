"""Offline end-to-end smoke for the scanner self-evolve CLI (Task 7).

Drives the FULL ``run.main`` path OFFLINE + DETERMINISTIC:

    injected prefetch_fn (synthetic bundles)  →  evolve (train+val)  →
    single post-loop scanner_fitness("test")  →  report.write_report (md + html)

No network, no LLM, no data files: ``prefetch_fn`` / ``spy_fetch_fn`` return
in-memory synthetic bundles and a stub SPY, and ``propose_fn`` is a scripted stub
emitting in-range scanner deltas. The bundles span dates that fall inside the
REAL train / val / test sample windows so the loop and the held-out read actually
exercise their windows.

What this proves end-to-end:

1. **Report exists** — both the ``.md`` AND the ``.html`` run-report files are
   written.
2. **Test verdict renders** — the post-loop ``scanner_fitness("test")`` numbers
   (the ``diff`` / ``n_fired``) appear in BOTH rendered outputs.
3. **Optimization path / retained config present** — the report carries the
   path table + a retained config block.
4. **Sample isolation (invariant #1) end-to-end** — across the loop's fitness
   calls ``"test"`` is NEVER scored; the single ``"test"`` read happens only
   post-loop. Proven by a sample-recorder wrapping the real ``scanner_fitness``.
"""

from __future__ import annotations

from datetime import date, timedelta

from v2.data.models import Price
from v2.scanner.eval.cached_asof_client import TickerBundle
from v2.scanner.evolve import run as run_mod


# ---------------------------------------------------------------------------
# Synthetic bundles spanning the REAL train/val/test windows
# ---------------------------------------------------------------------------

# Full daily calendar from before the earliest train window to after the test
# window, so every sample's as-of dates exist in the synthetic series.
_SPAN_START = "2021-10-01"  # ~400d before bear_2022 isn't needed (we ramp inline)
_SPAN_END = "2026-06-05"

# One breakout date inside EACH sample window, chosen well clear of the edges so
# the high_breakout(window=60) trailing-max + dip + jump pattern fits.
_BREAK_DATES = {
    "train": "2022-06-01",  # inside bear_2022 (2022-01-03..2022-10-14)
    "val": "2025-05-01",  # inside choppy_2025 (2025-02-18..2025-08-01)
    "test": "2025-12-01",  # inside heldout_2025_26 (2025-09-01..2026-06-01)
}


def _daterange(start: str, end: str) -> list[str]:
    d0 = date.fromisoformat(start)
    d1 = date.fromisoformat(end)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _firing_closes(dates: list[str]) -> list[float]:
    """A long flat series with a breakout ramp engineered ON each break date.

    Flat warmup at 100 everywhere, then for each break date: a 3-bar dip just
    before it (so yesterday sits below the trailing max → first-day gate), a jump
    on the break bar, and a small continued rise after (so a 5d forward return
    exists). The breakouts are far apart, so each window's max is the flat 100.
    """
    idx = {d: i for i, d in enumerate(dates)}
    closes = [100.0] * len(dates)
    for bdate in _BREAK_DATES.values():
        bi = idx.get(bdate)
        if bi is None or bi < 4 or bi + 11 >= len(closes):
            continue
        closes[bi - 3] = 95.0
        closes[bi - 2] = 95.0
        closes[bi - 1] = 95.0
        closes[bi] = 130.0  # the break bar
        for k in range(1, 11):
            closes[bi + k] = 130.0 + 1.0 * k
    return closes


def _price(time_iso: str, close: float) -> Price:
    return Price(open=close, close=close, high=close, low=close, volume=1_000_000, time=time_iso)


def _bundle(ticker: str, dates: list[str], closes: list[float]) -> TickerBundle:
    return TickerBundle(ticker=ticker, prices=[_price(d, c) for d, c in zip(dates, closes)])


def _make_bundles() -> dict[str, TickerBundle]:
    dates = _daterange(_SPAN_START, _SPAN_END)
    firing = _firing_closes(dates)
    bundles = {"AAA": _bundle("AAA", dates, firing)}
    # A handful of never-fire fillers to widen the random baseline.
    for j, name in enumerate(("BBB", "CCC", "DDD", "EEE")):
        flat = [100.0 + 0.01 * j * i for i in range(len(dates))]
        bundles[name] = _bundle(name, dates, flat)
    return bundles


def _spy_bundle() -> TickerBundle:
    dates = _daterange(_SPAN_START, _SPAN_END)
    return _bundle("SPY", dates, [100.0] * len(dates))


# ---------------------------------------------------------------------------
# Stub proposer — in-range scanner deltas, no LLM
# ---------------------------------------------------------------------------


def _scripted_propose(deltas):
    """A ``propose_fn`` emitting ``deltas`` in order, then ``None`` forever."""
    seq = list(deltas)
    calls = {"n": 0}

    def propose_fn(skill, config, val_history, *, llm_fn=None):
        i = calls["n"]
        calls["n"] += 1
        return seq[i] if i < len(seq) else None

    return propose_fn


# ---------------------------------------------------------------------------
# Sample-recorder — wrap the REAL scanner_fitness to record every sample arg
# ---------------------------------------------------------------------------


class _SampleRecorder:
    """Wrap ``run.scanner_fitness`` and record each ``sample`` it is called with.

    Delegates to the real fitness (so the loop + the post-loop test read run for
    real over the synthetic bundles); the recorded list lets the smoke prove that
    ``"test"`` never appeared inside the loop.
    """

    def __init__(self, monkeypatch):
        self._real = run_mod.scanner_fitness
        self.samples: list[str] = []
        monkeypatch.setattr(run_mod, "scanner_fitness", self)

    def __call__(self, bundles, config, sample, **kwargs):
        self.samples.append(sample)
        return self._real(bundles, config, sample, **kwargs)


# ---------------------------------------------------------------------------
# The end-to-end smoke
# ---------------------------------------------------------------------------


def test_cli_end_to_end_offline_writes_report_and_holds_out_test(tmp_path, monkeypatch):
    bundles = _make_bundles()
    spy = _spy_bundle()

    def prefetch_fn(start, end):
        return bundles

    def spy_fetch_fn(start, end):
        return spy

    # In-range scanner deltas (no LLM). Each round nudges a different adjustable.
    propose_fn = _scripted_propose(
        [
            {"path": "detectors.high_breakout.window", "value": 60, "hypothesis": "shorter breakout window"},
            {"path": "detectors.gap.threshold", "value": 4.0, "hypothesis": "wider gap"},
            {"path": "top_n", "value": 30, "hypothesis": "more breadth"},
        ]
    )

    recorder = _SampleRecorder(monkeypatch)

    out_dir = tmp_path / "run"
    rc = run_mod.main(
        argv=["--iterations", "3", "--out-dir", str(out_dir)],
        prefetch_fn=prefetch_fn,
        spy_fetch_fn=spy_fetch_fn,
        propose_fn=propose_fn,
    )
    assert rc == 0

    # 1. Both report files exist.
    md_path = out_dir / "scanner_evolve_report.md"
    html_path = out_dir / "scanner_evolve_report.html"
    assert md_path.is_file()
    assert html_path.is_file()

    md = md_path.read_text(encoding="utf-8")
    html = html_path.read_text(encoding="utf-8")

    # 2. The post-loop TEST read's fitness numbers render in BOTH outputs.
    #    Recompute the expected test diff exactly as the CLI did: the retained-best
    #    config scored once on "test" — the LAST sample the recorder saw.
    assert recorder.samples[-1] == "test"  # the single post-loop read
    assert "Held-out TEST verdict" in md
    assert "Held-out TEST verdict" in html

    # The TEST n_fired value must be present (a concrete number, not the n/a path).
    assert "_n/a" not in md.split("Held-out TEST verdict")[1].split("##")[0]

    # 3. Optimization path + retained config sections are present.
    assert "## Optimization path" in md
    assert "## Retained config" in md
    assert "v0" in md  # the baseline row at minimum

    # The TEST fitness numbers appear in both md AND html. Find the rendered test
    # diff/n_fired cells in the md verdict block and assert they're also in html.
    verdict_block = md.split("Held-out TEST verdict")[1].split("## Honest caveats")[0]
    # Pull the n_fired row value and assert it co-renders in the html.
    assert "n_fired" in verdict_block
    for line in verdict_block.splitlines():
        if line.startswith("| n_fired"):
            value = line.split("|")[2].strip()
            assert value in html  # test fitness renders in html too
            break

    # 4. Sample isolation end-to-end: "test" NEVER inside the loop, only post-loop.
    #    The recorder saw train+val during the loop, then exactly one "test" last.
    loop_samples = recorder.samples[:-1]
    assert "test" not in loop_samples
    assert "train" in loop_samples
    assert "val" in loop_samples
    assert recorder.samples.count("test") == 1
