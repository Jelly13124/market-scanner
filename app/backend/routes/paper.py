"""Read-only paper-trading performance panel for the host.

The forward-test book (``src/paper_trading``) persists one daily equity mark per
``(sleeve, date)`` and derives the comparable A/B numbers + graduation verdict.
This router exposes that state to the in-app "Paper" tab — read-only, no write
controls.

The paper tables carry no ``user_id`` (they are the host's single forward-test
book), so both routes are SUPERUSER-ONLY, mirroring the legacy
``/research/run`` gate. Metrics are not reinvented here — they reuse the
already-debugged (never-raise) ``performance``/``report`` helpers.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.backend.auth.dependencies import get_current_user
from app.backend.database import get_db
from app.backend.database.models import User
from src.paper_trading.performance import compute_performance, evaluate_graduation
from src.paper_trading.report import (
    _load_equity_by_sleeve,
    render_sleeves_equity_png,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/paper")


@router.get("/performance")
def get_performance(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-sleeve metrics + graduation verdict for the forward-test book.

    Superuser-only (the paper book is the host's, with no per-user scoping).
    Never 500s on an empty book: ``compute_performance`` returns ``{}`` and
    ``evaluate_graduation`` returns a FAILed verdict gracefully.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The paper-trading panel is host-only.",
        )
    perf = compute_performance(db)
    return {"sleeves": perf, "graduation": evaluate_graduation(perf)}


@router.get("/equity-chart.png")
def get_equity_chart(
    db: Session = Depends(get_db),
):
    """The 3-sleeve equity-curve overlay as a PNG.

    Open-read (NOT superuser-gated) by design: an ``<img src>`` cannot carry the
    Bearer header, and the chart alone is not sensitive (the numeric metrics stay
    behind the superuser gate on ``/paper/performance``). The render helper
    returns a placeholder PNG on empty input, so this never 500s.
    """
    png = render_sleeves_equity_png(_load_equity_by_sleeve(db))
    return Response(content=png, media_type="image/png")
