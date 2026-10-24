"""Tenant-safety tests for run_sop per-user api_keys threading (A3).

These prove run_sop puts the caller's `api_keys` dict onto EVERY
SectionContext it builds — including the sections dispatched across the
ThreadPoolExecutor fan-out — and that two concurrent run_sop calls with
different keys NEVER cross-contaminate. A bug here leaks one user's
provider keys/credits to another tenant.

Strategy: patch the section-execution seam (SECTION_REGISTRY stub
sections whose .run(ctx) records ctx.api_keys). No real LLM/data — both
fetch_shared_data and run_signal_backtest are mocked. Offline +
deterministic.
"""

from __future__ import annotations

import threading
from unittest.mock import patch

from src.research.models import (
    AnalyzeRequest,
    BacktestVerdict,
    SECTION_ORDER,
    SectionPayload,
)
from src.research.sop_orchestrator import run_sop


def _minimal_request(included=None, objective="medium_term"):
    return AnalyzeRequest(
        ticker="NVDA",
        objective=objective,
        position_budget_usd=10000,
        already_holds=False,
        cost_basis_usd=None,
        risk_tolerance="balanced",
        use_personas=False,
        included_sections=included if included is not None else set(SECTION_ORDER),
    )


def _empty_shared():
    from src.research.shared_data import SharedData
    return SharedData(
        ticker="NVDA", scan_date="2026-05-22",
        prices=[], financials=[], insider_trades=[], news=[],
        analyst_actions=[], analyst_targets=None, earnings_history=[],
        company_facts={}, sector_etf_prices=[], spy_prices=[],
    )


def _null_backtest():
    return BacktestVerdict(
        signal="x", window_start="x", window_end="x", n_signals=0,
        win_rate_20d=None, avg_return_20d=None, t_stat=None,
        significant=False, verdict="x",
    )


def _payload(name):
    return SectionPayload(
        name=name, markdown=f"## {name}\n\nbody.",
        structured=None, skipped=False, persona_used=None,
    )


class _RecordingStub:
    """Section stub that records the api_keys it observed via ctx."""

    def __init__(self, name, sink, lock):
        self.name = name
        self.supports_personas = []
        self._sink = sink
        self._lock = lock

    def run(self, ctx):
        with self._lock:
            self._sink.append(ctx.api_keys)
        return _payload(self.name)


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_run_sop_threads_api_keys_to_all_sections(mock_bt, mock_registry, mock_fetch):
    """Every SectionContext built by run_sop — sequential AND the parallel
    ThreadPoolExecutor batch — carries the exact api_keys dict passed in."""
    mock_fetch.return_value = _empty_shared()
    mock_bt.return_value = _null_backtest()

    seen: list[dict | None] = []
    lock = threading.Lock()
    for n in SECTION_ORDER:
        mock_registry[n] = _RecordingStub(n, seen, lock)

    keys = {"DEEPSEEK_API_KEY": "userA"}
    run_sop(_minimal_request(), api_keys=keys)

    # Stub ran for every registered section (sequential + parallel batch).
    assert len(seen) == len(SECTION_ORDER)
    # Each context saw EXACTLY the dict we passed: identity-equal (so no
    # copy silently replaced it) and value-equal.
    assert all(k is keys for k in seen)
    assert all(k == {"DEEPSEEK_API_KEY": "userA"} for k in seen)


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_run_sop_default_none(mock_bt, mock_registry, mock_fetch):
    """run_sop(request) with no api_keys => every ctx.api_keys is None
    (host-env / cron path stays single-tenant). The default must not break
    callers that invoke run_sop(request) positionally with no keys."""
    mock_fetch.return_value = _empty_shared()
    mock_bt.return_value = _null_backtest()

    seen: list[dict | None] = []
    lock = threading.Lock()
    for n in SECTION_ORDER:
        mock_registry[n] = _RecordingStub(n, seen, lock)

    run_sop(_minimal_request())

    assert len(seen) == len(SECTION_ORDER)
    assert all(k is None for k in seen)


@patch("src.research.sop_orchestrator.fetch_shared_data")
@patch("src.research.sop_orchestrator.SECTION_REGISTRY", new_callable=dict)
@patch("src.research.sop_orchestrator.run_signal_backtest")
def test_run_sop_concurrent_runs_do_not_cross(mock_bt, mock_registry, mock_fetch):
    """Two run_sop calls executing concurrently, each with a DIFFERENT
    api_keys dict, must never let a section in run A observe run B's keys.

    We force genuine temporal overlap: the first section of each run blocks
    on a 2-party barrier, so both runs are provably in-flight at the same
    instant before any section records. A single shared registry of
    router-stubs serves both runs; each stub routes its observation into
    the A or B bucket by the *identity* of the api_keys dict run_sop
    threaded through the SectionContext. We then assert each bucket is pure.

    Because api_keys flows ONLY through run_sop's local var + the _run_one
    closure + SectionContext (no module global / env / thread-local), the
    overlap cannot mix them — this test would fail loudly if any of those
    forbidden carriers were introduced.
    """
    mock_fetch.return_value = _empty_shared()
    mock_bt.return_value = _null_backtest()

    keys_a = {"DEEPSEEK_API_KEY": "userA"}
    keys_b = {"DEEPSEEK_API_KEY": "userB"}

    observed: dict[str, list[dict | None]] = {"A": [], "B": [], "?": []}
    obs_lock = threading.Lock()

    # Rendezvous: first section of EACH run must meet before either records,
    # guaranteeing the two runs overlap in time. Later sections skip it.
    rendezvous = threading.Barrier(2, timeout=15)
    rdv_state = {"done": False}
    rdv_lock = threading.Lock()

    class _RouterStub:
        def __init__(self, name):
            self.name = name
            self.supports_personas = []

        def run(self, ctx):
            do_wait = False
            with rdv_lock:
                if not rdv_state["done"]:
                    do_wait = True
            if do_wait:
                try:
                    rendezvous.wait()
                except threading.BrokenBarrierError:
                    pass
                with rdv_lock:
                    rdv_state["done"] = True
            if ctx.api_keys is keys_a:
                bucket = "A"
            elif ctx.api_keys is keys_b:
                bucket = "B"
            else:
                bucket = "?"
            with obs_lock:
                observed[bucket].append(ctx.api_keys)
            return _payload(self.name)

    for n in SECTION_ORDER:
        mock_registry[n] = _RouterStub(n)

    errors: list[BaseException] = []

    def _safe_run(keys):
        try:
            run_sop(_minimal_request(), api_keys=keys)
        except BaseException as e:  # noqa: BLE001 - surface to main thread
            errors.append(e)

    ta = threading.Thread(target=_safe_run, args=(keys_a,), name="run-A")
    tb = threading.Thread(target=_safe_run, args=(keys_b,), name="run-B")
    ta.start()
    tb.start()
    ta.join(timeout=30)
    tb.join(timeout=30)

    assert not errors, f"run_sop raised in a worker thread: {errors!r}"
    assert not ta.is_alive() and not tb.is_alive(), "run_sop deadlocked"

    # Both runs executed all their sections, and none misrouted.
    assert len(observed["A"]) == len(SECTION_ORDER), observed
    assert len(observed["B"]) == len(SECTION_ORDER), observed
    assert observed["?"] == [], "a section saw foreign/None api_keys"

    # THE tenant-isolation guarantee: run A's sections only ever saw A's
    # dict; run B's only ever saw B's. No cross-contamination under overlap.
    assert all(k is keys_a for k in observed["A"])
    assert all(k is keys_b for k in observed["B"])
    assert all(k == {"DEEPSEEK_API_KEY": "userA"} for k in observed["A"])
    assert all(k == {"DEEPSEEK_API_KEY": "userB"} for k in observed["B"])
