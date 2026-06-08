"""Weekly rebalance engine for the paper-trading forward test (Task 4).

``run_week`` drives one weekly run for one sleeve against an injected broker
and DB session. Each run, in this order:

1. Resolve (get-or-create) the :class:`PaperSleeve` row by name and short-circuit
   to a no-op if this ``week_key`` already produced orders (idempotency).
2. Exit positions that have aged past ``hold_days`` calendar days.
3. Compute this week's target tickers via :func:`compute_targets`.
4. Enter the new targets (those not already held) equal-weight from cash.

It is deliberately decoupled from the live scanner/agent and the live broker:
the scanner/agent come in as the same seam functions :func:`compute_targets`
takes, and the broker is any :class:`~src.paper_trading.broker.BrokerClient`
(``FakeBroker`` offline, ``AlpacaBroker`` live). The function NEVER raises on a
single bad ticker or missing mark — per-ticker failures are isolated, logged,
and skipped so one bad name can't sink the whole weekly run.

Idempotency contract: re-running the same ``(sleeve, week_key)`` places ZERO
orders and leaves positions untouched, so the weekly scheduler can safely retry.
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.backend.database.models import PaperOrder, PaperPosition, PaperSleeve

from .sleeves import compute_targets

logger = logging.getLogger(__name__)

RunScanFn = Callable[[str, int], "Optional[list[str]]"]
AgentFn = Callable[[list[str], str], "Optional[dict[str, dict]]"]


def _calendar_days(d1: str, d2: str) -> int:
    """Return calendar days from ``d1`` to ``d2`` (both ``YYYY-MM-DD``).

    Positive when ``d2`` is after ``d1``. Used to age positions against the
    hold window; calendar (not trading) days keep the rule simple and stable.
    """
    return (date.fromisoformat(d2) - date.fromisoformat(d1)).days


def _get_or_create_sleeve(session: Session, sleeve_name: str, broker) -> PaperSleeve:
    """Fetch the sleeve row by name, creating it on first sight.

    On create, ``starting_cash`` is seeded from the broker's current cash so the
    persisted book starts equal to the broker's opening balance.
    """
    sleeve = session.query(PaperSleeve).filter_by(name=sleeve_name).one_or_none()
    if sleeve is not None:
        return sleeve
    starting_cash = float(broker.get_account()["cash"])
    sleeve = PaperSleeve(name=sleeve_name, starting_cash=starting_cash)
    session.add(sleeve)
    session.flush()  # assign sleeve.id
    return sleeve


def run_week(
    *,
    sleeve_name: str,
    scan_date: str,
    week_key: str,
    broker,
    session: Session,
    run_scan_fn: RunScanFn,
    agent_fn: AgentFn | None = None,
    top_n: int = 5,
    hold_days: int | None = 30,
    targets: list[str] | None = None,
) -> dict:
    """Run one weekly rebalance for ``sleeve_name`` and return a summary.

    Args:
        sleeve_name: One of ``SLEEVE_NAMES``.
        scan_date: As-of date (``YYYY-MM-DD``) for the scan and for stamping
            entry/exit dates on positions.
        week_key: ISO-week grouping key (e.g. ``"2026-W24"``). The idempotency key
            together with the sleeve.
        broker: A ``BrokerClient`` (``FakeBroker`` offline).
        session: SQLAlchemy session for the paper-trading tables.
        run_scan_fn: Injected scanner seam, passed through to ``compute_targets``.
        agent_fn: Injected agent seam (required only for ``scanner_agent``).
        top_n: Max ranked picks to request from the scan.
        hold_days: Calendar-day hold window. ``None`` disables age-exit entirely
            (buy-and-hold; this is how ``spy_benchmark`` holds SPY forever).

    Returns:
        Summary dict with keys ``sleeve_name``, ``week_key``, ``already_ran``,
        ``entered`` (list of tickers bought), ``exited`` (list of tickers sold),
        ``n_orders`` (orders recorded this run), and ``cash_after``.
    """
    sleeve = _get_or_create_sleeve(session, sleeve_name, broker)

    # --- 1. Idempotency: bail if this (sleeve, week_key) already ran. ---------
    already_ran = session.query(PaperOrder.id).filter_by(sleeve_id=sleeve.id, week_key=week_key).first() is not None
    if already_ran:
        logger.info(
            "run_week: sleeve=%s week_key=%s already ran; placing zero orders",
            sleeve_name,
            week_key,
        )
        return {
            "sleeve_name": sleeve_name,
            "week_key": week_key,
            "already_ran": True,
            "entered": [],
            "exited": [],
            "n_orders": 0,
            "cash_after": float(broker.get_account()["cash"]),
        }

    exited: list[str] = []
    entered: list[str] = []
    n_orders = 0

    # --- 2. Exit positions past the hold window. -----------------------------
    open_positions = session.query(PaperPosition).filter_by(sleeve_id=sleeve.id, status="open").all()
    for pos in open_positions:
        if hold_days is None:
            continue  # buy-and-hold: never age-exit
        try:
            age = _calendar_days(pos.entry_date, scan_date)
        except Exception:
            logger.exception(
                "run_week: bad entry_date %r on position id=%s; skipping exit",
                pos.entry_date,
                pos.id,
            )
            continue
        if age < hold_days:
            continue

        try:
            result = broker.close_position(pos.ticker)
        except Exception:
            logger.exception("run_week: close_position raised for %s; skipping", pos.ticker)
            continue

        if result.get("status") == "filled":
            fill = float(result["price"])
            session.add(
                PaperOrder(
                    sleeve_id=sleeve.id,
                    ticker=pos.ticker,
                    side="sell",
                    qty=float(result["qty"]),
                    price=fill,
                    status="filled",
                    week_key=week_key,
                )
            )
            n_orders += 1
            pos.status = "closed"
            pos.exit_date = scan_date
            pos.exit_price = fill
            exited.append(pos.ticker)
        else:
            # noop (nothing held broker-side) — leave the position as-is rather
            # than guessing; nothing was transacted so nothing to record.
            logger.warning(
                "run_week: close_position non-fill for %s (%s); position left open",
                pos.ticker,
                result.get("status"),
            )

    # Tickers still held after exits (avoid double-buying these).
    try:
        held = set(broker.get_positions().keys())
    except Exception:
        logger.exception("run_week: get_positions raised; assuming nothing held")
        held = set()

    # --- 3. Targets for this week. -------------------------------------------
    # Caller may pass precomputed targets (run_once does, so the scanner/agent
    # seam isn't run twice — otherwise scanner_agent's LLM analysis runs once
    # for the price-prefetch and again here).
    if targets is None:
        targets = compute_targets(
            sleeve_name,
            scan_date,
            run_scan_fn=run_scan_fn,
            agent_fn=agent_fn,
            top_n=top_n,
        )

    # --- 4. Enter new targets equal-weight from available cash. ---------------
    new = [t for t in targets if t not in held]
    if new:
        # Price every new target FIRST, then split cash only across the ones we
        # can actually price — otherwise an unpriceable name's share of capital
        # is left idle and the sleeve is under-invested vs its peers (A/B bias).
        priced: list[tuple[str, float]] = []
        for ticker in new:
            try:
                price = broker.get_last_price(ticker)
            except Exception:
                logger.exception("run_week: get_last_price raised for %s; skipping", ticker)
                continue
            if price is None or price <= 0:
                logger.warning("run_week: no valid price for %s; skipping entry", ticker)
                continue
            priced.append((ticker, price))

        cash = float(broker.get_account()["cash"])
        notional_each = cash / max(1, len(priced))
        for ticker, price in priced:
            qty = math.floor(notional_each / price)
            if qty < 1:
                logger.info(
                    "run_week: notional %.2f too small for %s @ %.2f; skipping",
                    notional_each,
                    ticker,
                    price,
                )
                continue

            try:
                result = broker.submit_market_order(ticker, "buy", qty)
            except Exception:
                logger.exception("run_week: submit_market_order raised for %s; skipping", ticker)
                continue

            status = result.get("status")
            if status == "filled":
                fill = float(result["price"])
                session.add(
                    PaperOrder(
                        sleeve_id=sleeve.id,
                        ticker=ticker,
                        side="buy",
                        qty=float(result["qty"]),
                        price=fill,
                        status="filled",
                        week_key=week_key,
                    )
                )
                session.add(
                    PaperPosition(
                        sleeve_id=sleeve.id,
                        ticker=ticker,
                        shares=float(result["qty"]),
                        entry_date=scan_date,
                        entry_price=fill,
                        status="open",
                    )
                )
                n_orders += 1
                entered.append(ticker)
            else:
                # Record the rejection for the audit log; no position opened.
                session.add(
                    PaperOrder(
                        sleeve_id=sleeve.id,
                        ticker=ticker,
                        side="buy",
                        qty=float(qty),
                        price=0.0,
                        status="rejected",
                        week_key=week_key,
                    )
                )
                n_orders += 1
                logger.warning(
                    "run_week: buy rejected for %s (%s)",
                    ticker,
                    result.get("reason"),
                )

    # --- 5. Commit and summarise. --------------------------------------------
    session.commit()

    return {
        "sleeve_name": sleeve_name,
        "week_key": week_key,
        "already_ran": False,
        "entered": entered,
        "exited": exited,
        "n_orders": n_orders,
        "cash_after": float(broker.get_account()["cash"]),
    }
