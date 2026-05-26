"""Shared filters used by the event-study engine and the scanner.

These guard against an extractor quirk: the FD API occasionally returns
prior-period comparison data anchored on a current-period filing date,
producing rows where filing_date is far past report_period. We drop those
because their event dates don't actually mark a market-moving moment.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Iterable

from v2.data.models import EarningsRecord

logger = logging.getLogger(__name__)

# Filings more than this many days after the reporting period are treated as
# retrospective (e.g. Q4 data parsed from a Q1 8-K).
RETROSPECTIVE_CUTOFF_DAYS = 45


def _parse_date(s: str) -> date:
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def filter_retrospective_earnings(
    records: Iterable[EarningsRecord],
    *,
    cutoff_days: int = RETROSPECTIVE_CUTOFF_DAYS,
) -> list[EarningsRecord]:
    """Drop records where filing_date is more than *cutoff_days* after report_period."""
    kept: list[EarningsRecord] = []
    for r in records:
        try:
            filing = _parse_date(r.filing_date)
            report = _parse_date(r.report_period)
        except (ValueError, TypeError):
            logger.debug("Unparseable dates on %s; dropping", r.ticker)
            continue
        if (filing - report).days < cutoff_days:
            kept.append(r)
        else:
            logger.debug(
                "Filtered retrospective: %s %s filed %s (report %s, %d days)",
                r.ticker, r.source_type, r.filing_date, r.report_period,
                (filing - report).days,
            )
    return kept
