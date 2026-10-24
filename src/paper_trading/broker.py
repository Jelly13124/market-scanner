"""Broker abstraction for the paper-trading harness.

This module defines the broker interface (``BrokerClient``) plus a
deterministic in-memory implementation (``FakeBroker``) used by all offline
tests, and a placeholder for the live Alpaca implementation.

Order-result dict shape (the contract every broker must return from
``submit_market_order`` / ``close_position``)::

    {
        "status": "filled" | "rejected" | "noop",
        "symbol": str,
        "side": "buy" | "sell",
        "qty": float,     # shares actually transacted (0 when not filled)
        "price": float,   # fill mark (0.0 when not filled)
        "reason": str,    # present only when status != "filled"
    }

Invariants:
- No method raises on unknown symbol, oversell, or insufficient cash.
- Cash never goes negative: a buy that cannot be fully funded is rejected
  and leaves cash + positions unchanged.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BrokerClient(Protocol):
    """Minimal broker interface the paper-trading engine depends on.

    Implementations are deterministic from the caller's perspective: the same
    sequence of calls against the same marks yields the same results.
    """

    def submit_market_order(self, symbol: str, side: str, qty: float) -> dict:
        """Submit a market order. ``side`` is ``"buy"`` or ``"sell"``.

        Returns an order-result dict (see module docstring). Never raises.
        """
        ...

    def get_positions(self) -> dict[str, dict]:
        """Return open positions as ``{symbol: {"shares", "avg_price"}}``."""
        ...

    def get_account(self) -> dict:
        """Return ``{"cash": float, "equity": float}``.

        ``equity`` is cash plus the marked-to-market value of all positions.
        """
        ...

    def get_last_price(self, symbol: str) -> float | None:
        """Return the last known mark for ``symbol``, or ``None`` if unknown."""
        ...

    def close_position(self, symbol: str) -> dict:
        """Sell the entire held position in ``symbol``.

        Returns an order-result dict. ``noop`` when nothing is held.
        """
        ...


def _order_result(
    *,
    status: str,
    symbol: str,
    side: str,
    qty: float = 0.0,
    price: float = 0.0,
    reason: str | None = None,
) -> dict:
    """Build a canonical order-result dict."""
    result: dict = {
        "status": status,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
    }
    if reason is not None:
        result["reason"] = reason
    return result


class FakeBroker:
    """Deterministic in-memory broker for offline tests.

    Args:
        starting_cash: Initial cash balance.
        prices: Mutable mapping of ``symbol -> mark``. Tests mutate this in
            place between calls to move marks; ``FakeBroker`` reads it live and
            does not copy it.
    """

    def __init__(self, starting_cash: float, prices: dict[str, float]) -> None:
        self.cash: float = float(starting_cash)
        # Keep the caller's reference so in-place mutations are observed.
        self.prices: dict[str, float] = prices
        # symbol -> {"shares": float, "avg_price": float}
        self._positions: dict[str, dict] = {}

    # -- orders ---------------------------------------------------------------

    def submit_market_order(self, symbol: str, side: str, qty: float) -> dict:
        side = side.lower()
        if side == "buy":
            return self._buy(symbol, float(qty))
        if side == "sell":
            return self._sell(symbol, float(qty))
        return _order_result(
            status="rejected",
            symbol=symbol,
            side=side,
            reason=f"unknown side: {side!r}",
        )

    def _buy(self, symbol: str, qty: float) -> dict:
        price = self.prices.get(symbol)
        if price is None:
            return _order_result(
                status="rejected",
                symbol=symbol,
                side="buy",
                reason="no mark for symbol",
            )
        if qty <= 0:
            return _order_result(
                status="rejected",
                symbol=symbol,
                side="buy",
                reason="qty must be positive",
            )

        cost = qty * price
        if cost > self.cash:
            return _order_result(
                status="rejected",
                symbol=symbol,
                side="buy",
                reason="insufficient cash",
            )

        self.cash -= cost
        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = {"shares": qty, "avg_price": price}
        else:
            prior_shares = pos["shares"]
            new_shares = prior_shares + qty
            # Share-weighted average entry price.
            pos["avg_price"] = (prior_shares * pos["avg_price"] + qty * price) / new_shares
            pos["shares"] = new_shares

        return _order_result(status="filled", symbol=symbol, side="buy", qty=qty, price=price)

    def _sell(self, symbol: str, qty: float) -> dict:
        pos = self._positions.get(symbol)
        if pos is None or pos["shares"] <= 0:
            return _order_result(
                status="noop",
                symbol=symbol,
                side="sell",
                reason="no position",
            )

        price = self.prices.get(symbol)
        if price is None:
            return _order_result(
                status="noop",
                symbol=symbol,
                side="sell",
                reason="no mark for symbol",
            )

        # Clamp oversell to held shares.
        fill_qty = min(float(qty), pos["shares"])
        if fill_qty <= 0:
            return _order_result(
                status="noop",
                symbol=symbol,
                side="sell",
                reason="qty must be positive",
            )

        self.cash += fill_qty * price
        remaining = pos["shares"] - fill_qty
        if remaining <= 0:
            del self._positions[symbol]
        else:
            pos["shares"] = remaining  # avg_price unchanged on a sell

        return _order_result(status="filled", symbol=symbol, side="sell", qty=fill_qty, price=price)

    def close_position(self, symbol: str) -> dict:
        pos = self._positions.get(symbol)
        if pos is None or pos["shares"] <= 0:
            return _order_result(
                status="noop",
                symbol=symbol,
                side="sell",
                reason="no position",
            )
        return self._sell(symbol, pos["shares"])

    # -- reads ----------------------------------------------------------------

    def get_positions(self) -> dict[str, dict]:
        # Return a fresh copy so callers can't mutate internal state.
        return {symbol: {"shares": pos["shares"], "avg_price": pos["avg_price"]} for symbol, pos in self._positions.items() if pos["shares"] > 0}

    def get_account(self) -> dict:
        positions_value = sum(pos["shares"] * self.prices.get(symbol, 0.0) for symbol, pos in self._positions.items())
        return {"cash": self.cash, "equity": self.cash + positions_value}

    def get_last_price(self, symbol: str) -> float | None:
        return self.prices.get(symbol)

    # -- seed (reconstruct from DB) ------------------------------------------

    def load_state(self, cash: float, positions: dict[str, dict]) -> None:
        """Seed cash + open positions directly, bypassing the fill engine.

        The DB is the source of truth across process runs; the live runner
        rebuilds a per-sleeve broker from the persisted cash + open lots rather
        than replaying historical fills (which would re-mark at today's prices
        and corrupt cost basis). This setter installs that reconstructed state.

        Args:
            cash: The sleeve's DB-derived cash balance.
            positions: ``{ticker: {"shares": float, "avg_price": float}}``. The
                mapping is copied (shares/avg_price coerced to float) so the
                caller's dict can't alias internal state.
        """
        self.cash = float(cash)
        self._positions = {symbol: {"shares": float(pos["shares"]), "avg_price": float(pos["avg_price"])} for symbol, pos in positions.items()}


class AlpacaBroker:
    """Live Alpaca-backed broker (paper endpoint).

    Wraps ``alpaca-py``'s ``TradingClient`` against the Alpaca PAPER trading
    REST API. ``alpaca-py`` is imported lazily INSIDE ``__init__`` so the
    offline test suite never imports it (and the dependency stays optional for
    anyone who only runs the default FakeBroker path).

    Keys come from ``ALPACA_API_KEY`` / ``ALPACA_SECRET_KEY`` (env). A missing
    key raises a clear error rather than letting the SDK fail opaquely.

    NOTE: this adapter is an OPTIONAL future-execution path. The default live
    harness reconstructs FakeBroker ledgers from the DB and marks at real
    prices (three sleeves can't share one Alpaca account, and that path needs
    no broker key). This class is not exercised by the offline tests beyond
    confirming it stays import-guarded.
    """

    def __init__(self, *, api_key: str | None = None, secret_key: str | None = None) -> None:
        import os

        # Lazy import — keep alpaca-py out of the offline suite's import graph.
        from alpaca.trading.client import TradingClient

        api_key = api_key or os.getenv("ALPACA_API_KEY")
        secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError("AlpacaBroker requires ALPACA_API_KEY and ALPACA_SECRET_KEY (paper keys) in the environment")

        # paper=True pins the paper-trading endpoint; no real money is at risk.
        self._client = TradingClient(api_key, secret_key, paper=True)

    def submit_market_order(self, symbol: str, side: str, qty: float) -> dict:
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest

        side = side.lower()
        if side not in ("buy", "sell"):
            return _order_result(status="rejected", symbol=symbol, side=side, reason=f"unknown side: {side!r}")
        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=float(qty),
                side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
        except Exception as exc:  # network / rejection / SDK error
            return _order_result(status="rejected", symbol=symbol, side=side, reason=str(exc))

        filled_qty = float(getattr(order, "filled_qty", 0) or 0)
        filled_avg = getattr(order, "filled_avg_price", None)
        price = float(filled_avg) if filled_avg is not None else 0.0
        # Market orders submitted async fill shortly after; report submission as
        # filled-pending using the requested qty when the SDK hasn't populated
        # fill fields yet, so the caller records the order.
        if filled_qty <= 0:
            filled_qty = float(qty)
        return _order_result(status="filled", symbol=symbol, side=side, qty=filled_qty, price=price)

    def get_positions(self) -> dict[str, dict]:
        try:
            positions = self._client.get_all_positions()
        except Exception:
            return {}
        out: dict[str, dict] = {}
        for pos in positions:
            shares = float(getattr(pos, "qty", 0) or 0)
            if shares <= 0:
                continue
            out[pos.symbol] = {"shares": shares, "avg_price": float(getattr(pos, "avg_entry_price", 0) or 0)}
        return out

    def get_account(self) -> dict:
        account = self._client.get_account()
        cash = float(getattr(account, "cash", 0) or 0)
        equity = float(getattr(account, "equity", 0) or 0)
        return {"cash": cash, "equity": equity}

    def get_last_price(self, symbol: str) -> float | None:
        # The trading client carries no market-data feed; the average entry
        # price of an open position is the only mark it can offer locally.
        positions = self.get_positions()
        pos = positions.get(symbol)
        return pos["avg_price"] if pos else None

    def close_position(self, symbol: str) -> dict:
        try:
            order = self._client.close_position(symbol)
        except Exception as exc:
            return _order_result(status="noop", symbol=symbol, side="sell", reason=str(exc))
        filled_qty = float(getattr(order, "filled_qty", 0) or 0)
        filled_avg = getattr(order, "filled_avg_price", None)
        price = float(filled_avg) if filled_avg is not None else 0.0
        return _order_result(status="filled", symbol=symbol, side="sell", qty=filled_qty, price=price)
