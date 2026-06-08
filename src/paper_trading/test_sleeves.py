"""Offline tests for per-sleeve long-only target-position logic.

These tests must run with no network and no LLM. They use trivial in-process
stubs for the injected ``run_scan_fn`` / ``agent_fn`` seams (the real scanner
and agent are wired in a later task) and pin the ``compute_targets`` contract
every later paper-trading task depends on.
"""

from __future__ import annotations

from src.paper_trading.sleeves import SLEEVE_NAMES, compute_targets


# -- stub seams ---------------------------------------------------------------


def _scan(tickers: list[str]):
    """Build a ``run_scan_fn`` stub returning ``tickers`` capped at ``top_n``."""

    def run_scan_fn(scan_date: str, top_n: int) -> list[str]:
        return list(tickers)[:top_n]

    return run_scan_fn


def _agent(decisions: dict[str, dict]):
    """Build an ``agent_fn`` stub returning a fixed decisions dict."""

    def agent_fn(tickers: list[str], scan_date: str) -> dict[str, dict]:
        return {t: decisions[t] for t in tickers if t in decisions}

    return agent_fn


# -- scanner_agent ------------------------------------------------------------


def test_scanner_agent_keeps_only_buys_in_rank_order() -> None:
    targets = compute_targets(
        "scanner_agent",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB", "CCC"]),
        agent_fn=_agent(
            {
                "AAA": {"action": "buy"},
                "BBB": {"action": "short"},
                "CCC": {"action": "buy"},
            }
        ),
    )
    # Only the buys, scan rank order preserved (AAA before CCC).
    assert targets == ["AAA", "CCC"]


def test_scanner_agent_missing_action_is_not_a_buy() -> None:
    targets = compute_targets(
        "scanner_agent",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB"]),
        agent_fn=_agent({"AAA": {"action": "buy"}, "BBB": {}}),
    )
    assert targets == ["AAA"]


def test_scanner_agent_agent_fn_raising_returns_empty() -> None:
    def boom(tickers: list[str], scan_date: str) -> dict[str, dict]:
        raise RuntimeError("agent exploded")

    targets = compute_targets(
        "scanner_agent",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB"]),
        agent_fn=boom,
    )
    # No conviction this week — falls back to empty, never raises.
    assert targets == []


def test_scanner_agent_missing_agent_fn_returns_empty() -> None:
    targets = compute_targets(
        "scanner_agent",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB"]),
        agent_fn=None,
    )
    assert targets == []


def test_scanner_agent_empty_scan_returns_empty() -> None:
    targets = compute_targets(
        "scanner_agent",
        "2026-06-01",
        run_scan_fn=_scan([]),
        agent_fn=_agent({"AAA": {"action": "buy"}}),
    )
    assert targets == []


# -- scanner_only -------------------------------------------------------------


def test_scanner_only_returns_all_picks_capped_at_top_n() -> None:
    targets = compute_targets(
        "scanner_only",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB", "CCC", "DDD"]),
        top_n=3,
    )
    assert targets == ["AAA", "BBB", "CCC"]


def test_scanner_only_dedupes_preserving_order() -> None:
    targets = compute_targets(
        "scanner_only",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "AAA", "BBB"]),
        top_n=5,
    )
    assert targets == ["AAA", "BBB"]


def test_scanner_only_empty_scan_returns_empty() -> None:
    targets = compute_targets(
        "scanner_only",
        "2026-06-01",
        run_scan_fn=_scan([]),
    )
    assert targets == []


# -- spy_benchmark ------------------------------------------------------------


def test_spy_benchmark_returns_spy_ignoring_scan() -> None:
    targets = compute_targets(
        "spy_benchmark",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB"]),
    )
    assert targets == ["SPY"]


def test_spy_benchmark_returns_spy_even_with_empty_scan() -> None:
    targets = compute_targets(
        "spy_benchmark",
        "2026-06-01",
        run_scan_fn=_scan([]),
    )
    assert targets == ["SPY"]


# -- robustness ---------------------------------------------------------------


def test_scan_returning_none_is_treated_as_empty() -> None:
    def run_scan_fn(scan_date: str, top_n: int):
        return None

    assert compute_targets("scanner_only", "2026-06-01", run_scan_fn=run_scan_fn) == []
    assert (
        compute_targets(
            "scanner_agent",
            "2026-06-01",
            run_scan_fn=run_scan_fn,
            agent_fn=_agent({}),
        )
        == []
    )


def test_run_scan_fn_raising_returns_empty() -> None:
    def boom(scan_date: str, top_n: int) -> list[str]:
        raise RuntimeError("scan exploded")

    assert compute_targets("scanner_only", "2026-06-01", run_scan_fn=boom) == []


def test_unknown_sleeve_returns_empty() -> None:
    targets = compute_targets(
        "mystery_sleeve",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB"]),
    )
    assert targets == []


def test_sleeve_names_constant() -> None:
    assert SLEEVE_NAMES == ("scanner_agent", "scanner_only", "spy_benchmark", "scanner_agent_flow")


# -- scanner_agent_flow -------------------------------------------------------


def test_scanner_agent_flow_matches_scanner_agent_same_stubs() -> None:
    """scanner_agent_flow is identical to scanner_agent in compute_targets.

    The ONLY difference between the two sleeves is the flow flag the runner sets
    around the agent call — NOT the target logic here. So given the same stubs,
    both must produce the exact same buys (in scan rank order).
    """
    run_scan_fn = _scan(["AAA", "BBB", "CCC"])
    agent_fn = _agent(
        {
            "AAA": {"action": "buy"},
            "BBB": {"action": "short"},
            "CCC": {"action": "buy"},
        }
    )

    agent_targets = compute_targets("scanner_agent", "2026-06-01", run_scan_fn=run_scan_fn, agent_fn=agent_fn)
    flow_targets = compute_targets("scanner_agent_flow", "2026-06-01", run_scan_fn=run_scan_fn, agent_fn=agent_fn)

    assert flow_targets == ["AAA", "CCC"]
    assert flow_targets == agent_targets


def test_scanner_agent_flow_missing_agent_fn_returns_empty() -> None:
    targets = compute_targets(
        "scanner_agent_flow",
        "2026-06-01",
        run_scan_fn=_scan(["AAA", "BBB"]),
        agent_fn=None,
    )
    assert targets == []
