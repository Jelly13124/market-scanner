"""Tests for the immutable train/val/test regime sample isolation.

Pure Python — no network, no LLM. The scanner self-evolve loop reads ONLY
train+val; the held-out test window is read once post-loop, never inside the
loop. These tests pin the structure, the ``window_of`` / ``sample_of`` contract,
the load-bearing no-overlap isolation invariant, and immutability.
"""

from __future__ import annotations

import pytest

from v2.scanner.eval.regimes import DEFAULT_CANDIDATES
from v2.scanner.evolve import samples
from v2.scanner.evolve.samples import SAMPLES, sample_of, window_of


# ---------------------------------------------------------------------------
# SAMPLES structure
# ---------------------------------------------------------------------------
def test_samples_structure():
    # train = (bear_2022, bull_2023_24); val = (choppy_2025,); test = 1 heldout.
    assert set(SAMPLES) == {"train", "val", "test"}
    assert len(SAMPLES["train"]) == 2
    assert len(SAMPLES["val"]) == 1
    assert len(SAMPLES["test"]) == 1


def test_train_val_mirror_default_candidates():
    by_name = {c["name"]: (c["start"], c["end"]) for c in DEFAULT_CANDIDATES}
    train_spans = [(w.start, w.end) for w in SAMPLES["train"]]
    val_spans = [(w.start, w.end) for w in SAMPLES["val"]]
    assert by_name["bear_2022"] in train_spans
    assert by_name["bull_2023_24"] in train_spans
    assert by_name["choppy_2025"] in val_spans


# ---------------------------------------------------------------------------
# window_of
# ---------------------------------------------------------------------------
def test_window_of_train_returns_both_spans():
    spans = window_of("train")
    assert spans == [("2022-01-03", "2022-10-14"), ("2023-10-27", "2024-07-16")]
    assert all(isinstance(s, tuple) and len(s) == 2 for s in spans)


def test_window_of_val_and_test():
    assert window_of("val") == [("2025-02-18", "2025-08-01")]
    assert window_of("test") == [("2025-09-01", "2026-06-01")]


def test_window_of_unknown_raises():
    with pytest.raises((KeyError, ValueError)):
        window_of("nope")


# ---------------------------------------------------------------------------
# sample_of
# ---------------------------------------------------------------------------
def test_sample_of_classifies_each_window():
    assert sample_of("2022-05-01") == "train"  # bear_2022
    assert sample_of("2024-01-15") == "train"  # bull_2023_24
    assert sample_of("2025-04-01") == "val"  # choppy_2025
    assert sample_of("2026-01-15") == "test"  # heldout


def test_sample_of_gap_date_returns_none():
    # 2025-08-15 falls after choppy (ends 2025-08-01) and before test (starts
    # 2025-09-01) — it belongs to no window.
    assert sample_of("2025-08-15") is None


def test_sample_of_inclusive_bounds():
    assert sample_of("2022-01-03") == "train"  # bear start
    assert sample_of("2025-09-01") == "test"  # heldout start
    assert sample_of("2026-06-01") == "test"  # heldout end


# ---------------------------------------------------------------------------
# Isolation invariant (load-bearing): test must not overlap train/val
# ---------------------------------------------------------------------------
def test_test_window_does_not_overlap_train_or_val():
    (test_start, test_end) = window_of("test")[0]
    train_val_ends = [end for s in ("train", "val") for (_start, end) in window_of(s)]
    # The held-out test window starts strictly after every train/val window ends.
    assert test_start > max(train_val_ends)
    # And its start classifies as "test", never as train/val.
    assert sample_of(test_start) == "test"
    assert sample_of(test_start) not in ("train", "val")
    assert sample_of(test_end) == "test"


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------
def test_samples_mapping_is_immutable():
    with pytest.raises(TypeError):
        SAMPLES["train"] = ()  # type: ignore[index]


def test_window_of_result_cannot_corrupt_samples():
    spans = window_of("train")
    spans.append(("1999-01-01", "1999-12-31"))
    # Mutating the returned list must not change SAMPLES.
    assert len(window_of("train")) == 2
    assert len(SAMPLES["train"]) == 2


def test_samples_module_exposes_constant():
    # scanner_fitness lazily imports window_of from here.
    assert hasattr(samples, "window_of")
    assert hasattr(samples, "SAMPLES")
