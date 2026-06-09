"""Institutional-positioning endpoint.

Returns a ticker's dealer-gamma exposure (GEX, options-implied snapshot) and
off-exchange short-volume (FINRA Reg-SHO proxy — NOT true dark-pool/ATS). Both
are best-effort live fetches; either may be ``null`` when data is unavailable.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from src.research.institutional_flow import fetch_gamma_exposure, fetch_short_volume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/institutional-flow")


@router.get("/{ticker}")
def get_institutional_flow(ticker: str) -> dict:
    """Best-effort dealer gamma + FINRA short-volume for one ticker.

    Never 500s on a data-source failure — a failed/empty fetch yields ``null``
    for that half so the panel can render a partial view.
    """
    t = ticker.strip().upper()
    gamma = None
    short_volume = None
    try:
        gamma = fetch_gamma_exposure(t)
    except Exception as e:  # noqa: BLE001 — best-effort, never break the request
        logger.warning("institutional_flow: gamma fetch failed for %s: %s", t, e)
    try:
        short_volume = fetch_short_volume(t)
    except Exception as e:  # noqa: BLE001
        logger.warning("institutional_flow: short_volume fetch failed for %s: %s", t, e)
    return {"ticker": t, "gamma": gamma, "short_volume": short_volume}
