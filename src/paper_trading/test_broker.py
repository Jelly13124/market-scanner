"""Offline tests for the deterministic in-memory FakeBroker.

These tests must run with no network and no LLM. They pin the order-result
dict shape and FakeBroker semantics that every later paper-trading task
depends on.
"""

from __future__ import annotations

import pytest

from src.paper_trading.broker import BrokerClient, FakeBroker


def test_buy_fills_and_decrements_cash() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})

    result = broker.submit_market_order("AAPL", "buy", 10)

    assert result["status"] == "filled"
    assert result["symbol"] == "AAPL"
    assert result["side"] == "buy"
    assert result["qty"] == 10
    assert result["price"] == 100.0

    account = broker.get_account()
    assert account["cash"] == 9_000.0  # 10_000 - 10 * 100

    positions = broker.get_positions()
    assert positions == {"AAPL": {"shares": 10.0, "avg_price": 100.0}}


def test_buy_beyond_cash_is_rejected_and_leaves_state_unchanged() -> None:
    broker = FakeBroker(starting_cash=500.0, prices={"AAPL": 100.0})

    result = broker.submit_market_order("AAPL", "buy", 10)  # needs 1_000

    assert result["status"] == "rejected"
    assert broker.get_account()["cash"] == 500.0
    assert broker.get_positions() == {}


def test_two_buys_average_price_is_share_weighted() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})

    broker.submit_market_order("AAPL", "buy", 10)  # 10 @ 100
    broker.prices["AAPL"] = 200.0
    broker.submit_market_order("AAPL", "buy", 30)  # 30 @ 200

    positions = broker.get_positions()
    # weighted avg = (10*100 + 30*200) / 40 = 7000 / 40 = 175
    assert positions["AAPL"]["shares"] == 40.0
    assert positions["AAPL"]["avg_price"] == 175.0
    # cash = 10_000 - 1_000 - 6_000 = 3_000
    assert broker.get_account()["cash"] == 3_000.0


def test_sell_increments_cash_and_reduces_position() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})
    broker.submit_market_order("AAPL", "buy", 10)  # cash 9_000, 10 shares

    broker.prices["AAPL"] = 150.0
    result = broker.submit_market_order("AAPL", "sell", 4)

    assert result["status"] == "filled"
    assert result["qty"] == 4
    assert result["price"] == 150.0

    # cash = 9_000 + 4 * 150 = 9_600
    assert broker.get_account()["cash"] == 9_600.0
    # 6 shares left, avg_price unchanged by a sell
    assert broker.get_positions() == {"AAPL": {"shares": 6.0, "avg_price": 100.0}}


def test_close_position_sells_all_and_removes_it() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})
    broker.submit_market_order("AAPL", "buy", 10)

    broker.prices["AAPL"] = 120.0
    result = broker.close_position("AAPL")

    assert result["status"] == "filled"
    assert result["qty"] == 10
    # cash = 9_000 + 10 * 120 = 10_200
    assert broker.get_account()["cash"] == 10_200.0
    assert broker.get_positions() == {}


def test_oversell_clamps_to_held_and_does_not_raise() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})
    broker.submit_market_order("AAPL", "buy", 10)  # cash 9_000

    result = broker.submit_market_order("AAPL", "sell", 999)  # only 10 held

    assert result["status"] == "filled"
    assert result["qty"] == 10  # clamped to held
    # cash = 9_000 + 10 * 100 = 10_000 (back to start)
    assert broker.get_account()["cash"] == 10_000.0
    assert broker.get_positions() == {}


def test_sell_unknown_symbol_is_noop_and_does_not_raise() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})

    sell_result = broker.submit_market_order("MSFT", "sell", 5)
    close_result = broker.close_position("TSLA")

    assert sell_result["status"] == "noop"
    assert close_result["status"] == "noop"
    assert broker.get_account()["cash"] == 10_000.0
    assert broker.get_positions() == {}


def test_get_account_equity_tracks_mutated_prices() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})
    broker.submit_market_order("AAPL", "buy", 10)  # cash 9_000, 10 shares

    # equity = cash + shares * price = 9_000 + 10 * 100 = 10_000
    assert broker.get_account()["equity"] == 10_000.0

    broker.prices["AAPL"] = 150.0
    # equity = 9_000 + 10 * 150 = 10_500
    assert broker.get_account()["equity"] == 10_500.0


def test_get_last_price_returns_mark_or_none() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})

    assert broker.get_last_price("AAPL") == 100.0
    assert broker.get_last_price("NOPE") is None


def test_buy_unknown_symbol_has_no_mark_and_is_rejected() -> None:
    broker = FakeBroker(starting_cash=10_000.0, prices={"AAPL": 100.0})

    result = broker.submit_market_order("MSFT", "buy", 5)  # no price for MSFT

    assert result["status"] == "rejected"
    assert broker.get_account()["cash"] == 10_000.0
    assert broker.get_positions() == {}


def test_fakebroker_satisfies_broker_client_protocol() -> None:
    broker = FakeBroker(starting_cash=1_000.0, prices={})
    assert isinstance(broker, BrokerClient)


def test_load_state_seeds_cash_and_positions_without_replaying_fills() -> None:
    # Reconstruct a broker as the live runner does: starting_cash is the
    # sleeve's deposit, but load_state installs the DB-derived cash + open lots.
    broker = FakeBroker(starting_cash=100_000.0, prices={"AAPL": 250.0, "MSFT": 400.0})

    broker.load_state(
        cash=12_345.67,
        positions={
            "AAPL": {"shares": 100.0, "avg_price": 180.0},  # cost basis preserved
            "MSFT": {"shares": 50.0, "avg_price": 300.0},
        },
    )

    assert broker.get_account()["cash"] == 12_345.67
    assert broker.get_positions() == {
        "AAPL": {"shares": 100.0, "avg_price": 180.0},
        "MSFT": {"shares": 50.0, "avg_price": 300.0},
    }
    # equity = cash + shares * CURRENT price (not avg): 12_345.67 + 100*250 + 50*400
    assert broker.get_account()["equity"] == 12_345.67 + 100 * 250.0 + 50 * 400.0


def test_load_state_copies_positions_and_can_sell_after_seed() -> None:
    broker = FakeBroker(starting_cash=100_000.0, prices={"AAPL": 250.0})
    seed = {"AAPL": {"shares": 10.0, "avg_price": 180.0}}
    broker.load_state(cash=0.0, positions=seed)

    # Mutating the caller's dict must not leak into the broker.
    seed["AAPL"]["shares"] = 999.0
    assert broker.get_positions()["AAPL"]["shares"] == 10.0

    # The seeded lot is sellable through the normal fill engine.
    result = broker.submit_market_order("AAPL", "sell", 4)
    assert result["status"] == "filled"
    assert result["qty"] == 4
    assert broker.get_account()["cash"] == 4 * 250.0
    assert broker.get_positions()["AAPL"]["shares"] == 6.0


def test_alpaca_broker_requires_keys() -> None:
    # With no env keys, AlpacaBroker should raise a clear error — but only AFTER
    # the lazy alpaca import. If alpaca-py isn't installed, the import itself
    # raises ImportError; either way construction fails (never silently succeeds).
    import os

    saved = (os.environ.pop("ALPACA_API_KEY", None), os.environ.pop("ALPACA_SECRET_KEY", None))
    try:
        with pytest.raises((ValueError, ImportError, ModuleNotFoundError)):
            from src.paper_trading.broker import AlpacaBroker

            AlpacaBroker()
    finally:
        if saved[0] is not None:
            os.environ["ALPACA_API_KEY"] = saved[0]
        if saved[1] is not None:
            os.environ["ALPACA_SECRET_KEY"] = saved[1]
