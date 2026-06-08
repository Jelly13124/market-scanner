"""Daily mark-to-market for the paper-trading forward test (Task 5).

The in-memory broker does NOT persist across process runs, so the DB is the
source of truth. The daily mark therefore reconstructs each sleeve's equity
purely from persisted state — never from a live broker object:

    cash   = derive_cash(...)                  # from filled PaperOrder rows
    equity = cash + Σ(open shares × price_fn(ticker))

``derive_cash`` is the same canonical reconstruction the live runner uses to
rebuild a broker's cash from the order log, so it is kept deliberately small
and exhaustively tested.

Robustness contract (mirrors the rest of the harness): nothing here raises on
a bad ticker, a missing price, or an unknown sleeve. A name whose price is
unavailable is simply skipped (its value excluded from equity); an unknown
sleeve logs and returns ``None``. ``mark_sleeve`` upserts exactly one
:class:`PaperEquityMark` per ``(sleeve_id, date)`` so the daily write is
idempotent — re-marking the same day overwrites that day's equity rather than
duplicating the row.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.backend.database.models import (
    PaperEquityMark,
    PaperOrder,
    PaperPosition,
    PaperSleeve,
)

logger = logging.getLogger(__name__)

PriceFn = Callable[[str], "Optional[float]"]


def derive_cash(sleeve_id: int, session: Session, *, starting_cash: float) -> float:
    """Reconstruct a sleeve's cash from its filled-order log.

    Cash = ``starting_cash`` − Σ(filled BUY qty×price) + Σ(filled SELL qty×price)
    over this sleeve's :class:`PaperOrder` rows with ``status == "filled"``.
    Rejected orders never moved cash, so they are ignored.

    This is the canonical DB-derived cash the live runner also uses to
    reconstruct a broker, so it must stay exact.

    Args:
        sleeve_id: The sleeve whose orders to sum.
        session: SQLAlchemy session for the paper-trading tables.
        starting_cash: The sleeve's opening cash balance.

    Returns:
        The current cash balance implied by the filled orders.
    """
    cash = float(starting_cash)
    filled = session.query(PaperOrder).filter_by(sleeve_id=sleeve_id, status="filled").all()
    for order in filled:
        notional = float(order.qty) * float(order.price)
        if order.side == "buy":
            cash -= notional
        elif order.side == "sell":
            cash += notional
        else:
            # Unknown side: not buy/sell. Don't guess its cash impact.
            logger.warning(
                "derive_cash: order id=%s has unknown side %r; ignoring",
                order.id,
                order.side,
            )
    return cash


def mark_sleeve(
    sleeve_name: str,
    date: str,
    *,
    session: Session,
    price_fn: PriceFn,
) -> float | None:
    """Mark one sleeve to market for ``date`` and upsert its equity row.

    Equity is computed entirely from the DB plus current prices:
    ``derive_cash`` for cash, then each OPEN :class:`PaperPosition` valued at
    ``shares × price_fn(ticker)``. A ticker whose price is ``None`` is skipped
    (excluded from equity) rather than counted at zero or raising.

    The resulting equity is written to :class:`PaperEquityMark` as an upsert on
    ``(sleeve_id, date)``: an existing row for that day is updated in place,
    otherwise a new row is inserted. Exactly one row per sleeve per date.

    Args:
        sleeve_name: The sleeve to mark (resolved by unique ``name``).
        date: As-of date (``YYYY-MM-DD``) for the mark.
        session: SQLAlchemy session for the paper-trading tables.
        price_fn: ``ticker -> price`` (``None`` when the price is unavailable).

    Returns:
        The marked equity, or ``None`` if the sleeve does not exist. Never raises.
    """
    sleeve = session.query(PaperSleeve).filter_by(name=sleeve_name).one_or_none()
    if sleeve is None:
        logger.warning("mark_sleeve: no sleeve named %r; skipping", sleeve_name)
        return None

    cash = derive_cash(sleeve.id, session, starting_cash=sleeve.starting_cash)

    positions_value = 0.0
    open_positions = session.query(PaperPosition).filter_by(sleeve_id=sleeve.id, status="open").all()
    for pos in open_positions:
        try:
            px = price_fn(pos.ticker)
        except Exception:
            logger.exception(
                "mark_sleeve: price_fn raised for %s; skipping from equity",
                pos.ticker,
            )
            continue
        if px is None:
            logger.debug(
                "mark_sleeve: no price for %s; excluding from %s equity",
                pos.ticker,
                sleeve_name,
            )
            continue
        positions_value += float(pos.shares) * float(px)

    equity = cash + positions_value

    # Upsert one PaperEquityMark per (sleeve_id, date).
    mark = session.query(PaperEquityMark).filter_by(sleeve_id=sleeve.id, date=date).one_or_none()
    if mark is None:
        session.add(PaperEquityMark(sleeve_id=sleeve.id, date=date, equity=equity))
    else:
        mark.equity = equity
    session.commit()

    logger.info(
        "mark_sleeve: %s @ %s equity=%.2f (cash=%.2f positions=%.2f)",
        sleeve_name,
        date,
        equity,
        cash,
        positions_value,
    )
    return equity


def mark_all(
    date: str,
    *,
    session: Session,
    price_fn: PriceFn,
) -> dict[str, float]:
    """Mark every sleeve to market for ``date``.

    Iterates all :class:`PaperSleeve` rows, calling :func:`mark_sleeve` for
    each. A sleeve that fails (returns ``None`` or raises) is logged and
    skipped; it does not abort the others.

    Args:
        date: As-of date (``YYYY-MM-DD``) for the marks.
        session: SQLAlchemy session for the paper-trading tables.
        price_fn: ``ticker -> price`` (``None`` when the price is unavailable).

    Returns:
        ``{sleeve_name: equity}`` for every sleeve marked successfully.
    """
    results: dict[str, float] = {}
    sleeves = session.query(PaperSleeve).all()
    for sleeve in sleeves:
        try:
            equity = mark_sleeve(sleeve.name, date, session=session, price_fn=price_fn)
        except Exception:
            logger.exception("mark_all: mark_sleeve raised for %s; skipping", sleeve.name)
            continue
        if equity is not None:
            results[sleeve.name] = equity
    return results
