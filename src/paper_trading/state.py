"""Reconstruct a per-sleeve broker from the DB (Task 8).

The in-memory :class:`~src.paper_trading.broker.FakeBroker` does NOT persist
across process runs, so the DB is the source of truth. Each live run rebuilds a
sleeve's broker purely from persisted state:

    cash      = derive_cash(sleeve.id, ..., starting_cash=sleeve.starting_cash)
    positions = open PaperPositions → {ticker: {shares, avg_price=entry_price}}

then installs both via :meth:`FakeBroker.load_state`. Rebuilding from cash + open
lots (rather than replaying historical fills) keeps cost basis intact and avoids
re-marking old fills at today's prices.

``prices`` is the live mark map the broker reads through — the same dict the
weekly engine values entries/exits against. Callers pass in fresh marks for the
union of (held + target) tickers before each run.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.backend.database.models import PaperPosition, PaperSleeve

from .broker import FakeBroker
from .marks import derive_cash

logger = logging.getLogger(__name__)


def _get_or_create_sleeve(session: Session, sleeve_name: str, *, starting_cash: float) -> PaperSleeve:
    """Fetch the sleeve row by name, creating it (with ``starting_cash``) on first sight."""
    sleeve = session.query(PaperSleeve).filter_by(name=sleeve_name).one_or_none()
    if sleeve is not None:
        return sleeve
    sleeve = PaperSleeve(name=sleeve_name, starting_cash=float(starting_cash))
    session.add(sleeve)
    session.flush()  # assign sleeve.id
    return sleeve


def reconstruct_broker(
    sleeve_name: str,
    session: Session,
    *,
    prices: dict[str, float],
    starting_cash: float = 100_000.0,
) -> FakeBroker:
    """Rebuild ``sleeve_name``'s :class:`FakeBroker` from persisted DB state.

    Get-or-create the :class:`PaperSleeve`, derive its cash from the filled-order
    log, gather its OPEN :class:`PaperPosition` rows into the broker's position
    shape (``avg_price`` taken from each lot's ``entry_price``), and seed a fresh
    ``FakeBroker`` (constructed with the sleeve's ``starting_cash`` and the live
    ``prices`` map) via :meth:`FakeBroker.load_state`.

    Args:
        sleeve_name: One of ``SLEEVE_NAMES``; created on first sight.
        session: SQLAlchemy session for the paper-trading tables.
        prices: Live ``symbol -> mark`` map the broker reads through. Held live
            (not copied) so callers can refresh marks in place.
        starting_cash: Opening cash used ONLY when the sleeve doesn't yet exist.

    Returns:
        A ``FakeBroker`` whose cash + open positions mirror the DB.
    """
    sleeve = _get_or_create_sleeve(session, sleeve_name, starting_cash=starting_cash)

    cash = derive_cash(sleeve.id, session, starting_cash=sleeve.starting_cash)

    open_positions = session.query(PaperPosition).filter_by(sleeve_id=sleeve.id, status="open").all()
    positions: dict[str, dict] = {pos.ticker: {"shares": float(pos.shares), "avg_price": float(pos.entry_price)} for pos in open_positions}

    broker = FakeBroker(starting_cash=float(sleeve.starting_cash), prices=prices)
    broker.load_state(cash, positions)

    logger.info(
        "reconstruct_broker: %s cash=%.2f open_positions=%d",
        sleeve_name,
        cash,
        len(positions),
    )
    return broker
