"""Tests for v2.scanner.runner.run_scan.

Uses stub detectors and a no-op FDClient so nothing hits the wire.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from v2.scanner.detectors.base import EventDetector, EventTrigger
from v2.scanner.models import ScannerWeights
from v2.scanner.runner import ScanProgress, run_scan


class _StubDetector(EventDetector):
    """Returns a configurable EventTrigger for each ticker."""

    name = "stub"

    def __init__(self, *, mapping: dict[str, EventTrigger | None]) -> None:
        self._mapping = mapping

    def detect(self, ticker, end_date, fd, *, ctx=None):
        return self._mapping.get(ticker)


class _BoomDetector(EventDetector):
    """Always raises — used to verify failure isolation."""

    name = "boom"

    def detect(self, ticker, end_date, fd, *, ctx=None):
        raise RuntimeError("synthetic detector failure")


def _make_trigger(z: float, direction: str) -> EventTrigger:
    return EventTrigger(
        detector="stub",
        triggered=True,
        severity_z=z,
        direction=direction,
        reason=f"z={z}",
    )


def _fd_factory():
    """Each worker gets its own MagicMock — no real HTTP."""
    return MagicMock()


# ---------------------------------------------------------------------------


class TestRunScan:
    def test_empty_universe_returns_empty(self):
        result = run_scan(
            tickers=[],
            end_date="2026-05-13",
            detectors=[_StubDetector(mapping={})],
            fd_factory=_fd_factory,
        )
        assert result == []

    def test_sorts_by_composite_and_ranks(self):
        mapping = {
            "AAA": _make_trigger(2.0, "bullish"),
            "BBB": _make_trigger(4.0, "bullish"),  # highest severity
            "CCC": _make_trigger(1.0, "bearish"),
        }
        result = run_scan(
            tickers=["AAA", "BBB", "CCC"],
            end_date="2026-05-13",
            top_n=10,
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=_fd_factory,
            max_workers=2,
        )
        assert [e.ticker for e in result] == ["BBB", "AAA", "CCC"]
        assert [e.rank for e in result] == [1, 2, 3]
        assert result[0].composite_score >= result[1].composite_score

    def test_drops_tickers_without_triggers(self):
        mapping = {
            "GOOD": _make_trigger(3.0, "bullish"),
            "MEH": None,  # detector returns None -> "no data", excluded
        }
        result = run_scan(
            tickers=["GOOD", "MEH", "ALSO_GONE"],  # ALSO_GONE not in mapping -> None
            end_date="2026-05-13",
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=_fd_factory,
        )
        assert [e.ticker for e in result] == ["GOOD"]

    def test_top_n_truncates(self):
        # Scale severities so they stay below the 5σ clip in scoring,
        # ensuring composite scores are distinct and sort order is deterministic.
        mapping = {f"T{i}": _make_trigger(float(i + 1) * 0.1, "bullish") for i in range(50)}
        result = run_scan(
            tickers=list(mapping),
            end_date="2026-05-13",
            top_n=5,
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=_fd_factory,
            max_workers=4,
        )
        assert len(result) == 5
        # Highest severity wins; T49 (z=5.0) is rank 1, then T48..T45.
        assert [e.ticker for e in result] == ["T49", "T48", "T47", "T46", "T45"]
        assert [e.rank for e in result] == [1, 2, 3, 4, 5]

    def test_detector_exception_does_not_abort_run(self):
        mapping = {
            "OK": _make_trigger(2.0, "bullish"),
            "BAD": _make_trigger(3.0, "bearish"),
        }
        result = run_scan(
            tickers=["OK", "BAD"],
            end_date="2026-05-13",
            # Stub + boom; OK and BAD still produce triggers via the stub.
            detectors=[_BoomDetector(), _StubDetector(mapping=mapping)],
            fd_factory=_fd_factory,
        )
        assert {e.ticker for e in result} == {"OK", "BAD"}

    def test_progress_callback_emitted(self):
        mapping = {f"T{i}": _make_trigger(2.0, "bullish") for i in range(20)}
        events: list[ScanProgress] = []
        run_scan(
            tickers=list(mapping),
            end_date="2026-05-13",
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=_fd_factory,
            progress_cb=events.append,
            progress_every=5,
            max_workers=2,
        )
        # At minimum: initial (force) + at least one mid-run + final (force).
        assert len(events) >= 2
        last = events[-1]
        assert last.processed == 20
        assert last.total == 20
        assert last.triggered == 20

    def test_fd_factory_called_once_per_worker(self):
        mapping = {f"T{i}": _make_trigger(2.0, "bullish") for i in range(8)}
        calls = []

        def factory():
            calls.append(1)
            return MagicMock()

        run_scan(
            tickers=list(mapping),
            end_date="2026-05-13",
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=factory,
            max_workers=4,
        )
        # 8 tickers, 4 workers -> exactly 4 FDClients should have been created
        assert len(calls) == 4

    def test_max_workers_capped_at_total(self):
        mapping = {"ONE": _make_trigger(2.0, "bullish")}
        calls = []

        def factory():
            calls.append(1)
            return MagicMock()

        run_scan(
            tickers=["ONE"],
            end_date="2026-05-13",
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=factory,
            max_workers=16,
        )
        # Only 1 ticker -> 1 client max.
        assert len(calls) == 1

    def test_provider_factory_kwarg_works(self):
        """The post-M3.5 preferred kwarg name."""
        mapping = {"AAA": _make_trigger(2.0, "bullish")}
        result = run_scan(
            tickers=["AAA"],
            end_date="2026-05-13",
            detectors=[_StubDetector(mapping=mapping)],
            provider_factory=_fd_factory,
        )
        assert len(result) == 1

    def test_fd_factory_emits_deprecation_warning(self):
        mapping = {"AAA": _make_trigger(2.0, "bullish")}
        with pytest.warns(DeprecationWarning, match="fd_factory is deprecated"):
            run_scan(
                tickers=["AAA"],
                end_date="2026-05-13",
                detectors=[_StubDetector(mapping=mapping)],
                fd_factory=_fd_factory,
            )

    def test_tiebreaker_uses_raw_severity_when_composite_ties(self):
        """When two tickers both clip to composite_score=100, the one with
        the larger raw |severity_z| ranks first. Regression for the M6.c
        fix — without this, four tickers all stuck at 100 would sort
        arbitrarily by thread-completion order."""
        # All four exceed the 5σ clip → composite = 100 for each.
        mapping = {
            "LOW": _make_trigger(5.5, "bullish"),     # mild
            "MID": _make_trigger(10.0, "bullish"),
            "HIGH": _make_trigger(20.0, "bullish"),
            "EXTREME": _make_trigger(43.0, "bearish"),
        }
        result = run_scan(
            tickers=list(mapping),
            end_date="2026-05-13",
            top_n=4,
            detectors=[_StubDetector(mapping=mapping)],
            fd_factory=_fd_factory,
            max_workers=2,
        )
        # All four scored 100, ordering depends entirely on event_severity.
        assert all(e.composite_score == pytest.approx(100.0) for e in result)
        assert [e.ticker for e in result] == ["EXTREME", "HIGH", "MID", "LOW"]
        # event_severity should be the raw max |z|, not the clipped score.
        assert result[0].event_severity == pytest.approx(43.0)
        assert result[1].event_severity == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Benchmark prefetch (SPY/QQQ-relative IDAY plumbing)
# ---------------------------------------------------------------------------


def _make_price_bars(count: int = 60):
    """Synthetic flat OHLC series for benchmark fetch responses."""
    from datetime import date, timedelta
    from v2.data.models import Price
    end = date.fromisoformat("2026-05-13")
    return [
        Price(
            open=100.0, close=100.0, high=101.0, low=99.0,
            volume=1_000_000, time=(end - timedelta(days=count - i)).isoformat(),
        )
        for i in range(count)
    ]


class _CaptureCtxDetector(EventDetector):
    """Records every ScanContext seen so tests can inspect benchmark_prices."""

    name = "capture"

    def __init__(self, mapping: dict[str, EventTrigger | None]) -> None:
        self._mapping = mapping
        self.captured: list = []
        self._lock = threading.Lock()

    def detect(self, ticker, end_date, fd, *, ctx=None):
        with self._lock:
            self.captured.append(ctx)
        return self._mapping.get(ticker)


class TestBenchmarkPlumbing:
    def test_benchmark_ticker_prefetched_once_and_injected(self):
        mapping = {"AAA": _make_trigger(2.0, "bullish"),
                   "BBB": _make_trigger(2.0, "bullish")}
        det = _CaptureCtxDetector(mapping)
        bench_calls = {"n": 0}

        def _factory():
            client = MagicMock()

            def get_prices_side_effect(t, *a, **kw):
                if t == "QQQ":
                    bench_calls["n"] += 1
                    return _make_price_bars(60)
                return []

            client.get_prices = MagicMock(side_effect=get_prices_side_effect)
            return client

        run_scan(
            tickers=["AAA", "BBB"],
            end_date="2026-05-13",
            detectors=[det],
            provider_factory=_factory,
            benchmark_ticker="QQQ",
            max_workers=2,
        )

        assert bench_calls["n"] == 1, "benchmark should be fetched exactly once"
        assert len(det.captured) == 2
        for ctx in det.captured:
            assert ctx.benchmark_prices is not None
            assert len(ctx.benchmark_prices) == 60

    def test_benchmark_fetch_failure_does_not_abort_scan(self):
        mapping = {"AAA": _make_trigger(2.0, "bullish")}
        det = _CaptureCtxDetector(mapping)

        def _factory():
            client = MagicMock()

            def get_prices_side_effect(t, *a, **kw):
                if t == "QQQ":
                    raise RuntimeError("synthetic benchmark fetch failure")
                return []

            client.get_prices = MagicMock(side_effect=get_prices_side_effect)
            return client

        result = run_scan(
            tickers=["AAA"],
            end_date="2026-05-13",
            detectors=[det],
            provider_factory=_factory,
            benchmark_ticker="QQQ",
        )

        assert len(result) == 1
        assert det.captured[0].benchmark_prices is None

    def test_benchmark_too_few_bars_disables_adjustment(self):
        mapping = {"AAA": _make_trigger(2.0, "bullish")}
        det = _CaptureCtxDetector(mapping)

        def _factory():
            client = MagicMock()

            def get_prices_side_effect(t, *a, **kw):
                if t == "QQQ":
                    return _make_price_bars(5)  # below 30-bar minimum
                return []

            client.get_prices = MagicMock(side_effect=get_prices_side_effect)
            return client

        run_scan(
            tickers=["AAA"],
            end_date="2026-05-13",
            detectors=[det],
            provider_factory=_factory,
            benchmark_ticker="QQQ",
        )
        assert det.captured[0].benchmark_prices is None

    def test_benchmark_ticker_none_preserves_current_behavior(self):
        mapping = {"AAA": _make_trigger(2.0, "bullish")}
        det = _CaptureCtxDetector(mapping)

        run_scan(
            tickers=["AAA"],
            end_date="2026-05-13",
            detectors=[det],
            fd_factory=_fd_factory,
        )

        assert det.captured[0].benchmark_prices is None
