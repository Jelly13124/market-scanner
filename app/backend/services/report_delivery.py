"""Deliver a rendered report to a user's verified recipient emails.

Shared by the on-demand "email this report" endpoint (Stage 2) and the scheduled
push job (Stage 3). Never raises on a per-recipient mail failure — it logs and
counts the address as failed so one bad address can't sink the batch.
"""
import logging

from sqlalchemy.orm import Session

from app.backend.database.models import ReportRecipient
from app.backend.services.notifications.email_handler import EmailHandler

logger = logging.getLogger(__name__)


def verified_recipients(db: Session, user_id: int) -> list[ReportRecipient]:
    """The user's report-recipient rows that have been email-verified."""
    return (
        db.query(ReportRecipient)
        .filter(ReportRecipient.user_id == user_id, ReportRecipient.is_verified.is_(True))
        .order_by(ReportRecipient.id)
        .all()
    )


def email_report_html(db: Session, user_id: int, *, ticker: str, html: str) -> dict:
    """Email a rendered report to every verified recipient of ``user_id``.

    Returns ``{"sent": [emails...], "failed": [emails...]}``. With no verified
    recipients both lists are empty — the caller decides whether that's an error
    (on-demand) or a quiet no-op (scheduled)."""
    recipients = verified_recipients(db, user_id)
    subject = f"Quant Lab report — {ticker}"
    text = f"Your Quant Lab report for {ticker}. Open the HTML version to read it."
    handler = EmailHandler()
    sent: list[str] = []
    failed: list[str] = []
    for r in recipients:
        try:
            res = handler.send(to=r.email, subject=subject, html=html or "", text=text)
            (sent if res.get("status") == "ok" else failed).append(r.email)
        except Exception:
            logger.exception("emailing report (%s) to %s failed", ticker, r.email)
            failed.append(r.email)
    return {"sent": sent, "failed": failed}


def email_watchlist(db: Session, user_id: int, *, config_name: str, entries) -> dict:
    """Email a scanner watchlist (ranked tickers) to every verified recipient.

    ``entries`` are watchlist rows (``WatchlistEntry`` or any object exposing
    ``ticker``, ``composite_score``/``score``, ``direction``, ``rank``). Builds a
    compact Rank|Ticker|Score|Direction table (plus a plain-text fallback) and
    sends one message per verified recipient. Returns
    ``{"sent": [emails...], "failed": [emails...]}``; with no verified recipients
    both lists are empty. Never raises on a per-recipient mail failure."""
    rows = sorted(entries, key=lambda e: getattr(e, "rank", 0))
    html = _watchlist_html(config_name, rows)
    text = _watchlist_text(rows)
    subject = f"Quant Lab watchlist — {config_name}"

    recipients = verified_recipients(db, user_id)
    handler = EmailHandler()
    sent: list[str] = []
    failed: list[str] = []
    for r in recipients:
        try:
            res = handler.send(to=r.email, subject=subject, html=html, text=text)
            (sent if res.get("status") == "ok" else failed).append(r.email)
        except Exception:
            logger.exception("emailing watchlist (%s) to %s failed", config_name, r.email)
            failed.append(r.email)
    return {"sent": sent, "failed": failed}


def _entry_score(entry) -> float:
    """Read an entry's score, preferring ``composite_score`` then ``score``."""
    score = getattr(entry, "composite_score", None)
    if score is None:
        score = getattr(entry, "score", 0.0)
    return score or 0.0


def _watchlist_html(config_name: str, rows) -> str:
    """Compact HTML table: Rank | Ticker | Score | Direction."""
    body = "".join(
        "<tr>"
        f"<td>{getattr(e, 'rank', '')}</td>"
        f"<td>{getattr(e, 'ticker', '')}</td>"
        f"<td>{_entry_score(e):.1f}</td>"
        f"<td>{getattr(e, 'direction', '')}</td>"
        "</tr>"
        for e in rows
    )
    return (
        f"<h2>Quant Lab watchlist — {config_name}</h2>"
        '<table border="1" cellpadding="6" cellspacing="0">'
        "<thead><tr><th>Rank</th><th>Ticker</th><th>Score</th><th>Direction</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def _watchlist_text(rows) -> str:
    """Plain-text fallback, e.g. ``#1 NVDA  92.0  bullish``."""
    return "\n".join(
        f"#{getattr(e, 'rank', '')} {getattr(e, 'ticker', '')}  "
        f"{_entry_score(e):.1f}  {getattr(e, 'direction', '')}"
        for e in rows
    )
