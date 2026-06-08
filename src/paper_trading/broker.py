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
            pos["avg_price"] = (
                prior_shares * pos["avg_price"] + qty * price
            ) / new_shares
            pos["shares"] = new_shares

        return _order_result(
            status="filled", symbol=symbol, side="buy", qty=qty, price=price
        )

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

        return _order_result(
            status="filled", symbol=symbol, side="sell", qty=fill_qty, price=price
        )

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
        return {
            symbol: {"shares": pos["shares"], "avg_price": pos["avg_price"]}
            for symbol, pos in self._positions.items()
            if pos["shares"] > 0
        }

    def get_account(self) -> dict:
        positions_value = sum(
            pos["shares"] * self.prices.get(symbol, 0.0)
            for symbol, pos in self._positions.items()
        )
        return {"cash": self.cash, "equity": self.cash + positions_value}

    def get_last_price(self, symbol: str) -> float | None:
        return self.prices.get(symbol)


class AlpacaBroker:
    """Live Alpaca-backed broker.

    Placeholder only. The real implementation (wrapping alpaca-py and the
    Alpaca paper-trading REST API) is filled in Task 8. Intentionally does not
    import alpaca-py so the offline test suite has zero live dependencies.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("AlpacaBroker is filled in Task 8")
