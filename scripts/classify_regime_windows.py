"""Classify recent candidate 10-day A/B windows by SPY regime.

Picks end-dates that leave full 20d forward returns available (end ≤
today−30 cal days). For each, prints the macro_agent regime + VIX so
we can pick one up / one down / one chop for a 3×10d regime-robustness
A/B suite.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv
load_dotenv()

from src.agents.macro_agent import _macro_snapshot, _CACHE

# Today is 2026-05-20. Need end ≤ 2026-04-20 for full 20d forward.
candidate_ends = [
    "2026-04-17",   # 10d back = 2026-04-06 — last week of complete data
    "2026-04-03",   # 10d back = 2026-03-23 — late March
    "2026-03-20",   # 10d back = 2026-03-09 — early-mid March
    "2026-03-06",   # 10d back = 2026-02-23 — late Feb
    "2026-02-20",   # 10d back = 2026-02-09 — early-mid Feb
    "2026-02-06",   # 10d back = 2026-01-26 — late Jan
    "2026-01-23",   # 10d back = 2026-01-12 — mid Jan
]

print(f"{'end_date':<12s}  {'window':<27s}  {'SPY 20d':>10s}  {'VIX':>6s}  "
      f"{'regime':<8s}  {'vol':<7s}")
print("-" * 90)
for end_date in candidate_ends:
    _CACHE.clear()
    snap = _macro_snapshot(end_date)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
    start_dt = end_dt - timedelta(days=14)  # rough 10 trading days backwards
    window = f"{start_dt.isoformat()} → {end_date}"
    ret_pct = (snap["spy_return_20d"] or 0) * 100
    vix = snap["vix_level"] or 0
    print(
        f"{end_date:<12s}  {window:<27s}  {ret_pct:>+9.2f}%  {vix:>6.2f}  "
        f"{snap['regime']:<8s}  {snap['vol_regime']:<7s}"
    )
