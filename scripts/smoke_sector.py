"""One-off smoke for sector_agent — verifies sector → ETF mapping after cache bust."""
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import load_dotenv
load_dotenv()

from src.agents.sector_agent import sector_agent, _SECTOR_CACHE, _ETF_PRICES
_SECTOR_CACHE.clear()
_ETF_PRICES.clear()

state = {
    "data": {
        "tickers": ["NVDA", "JPM", "XOM", "JNJ", "AAPL"],
        "end_date": "2026-04-17",
        "analyst_signals": {},
    },
    "metadata": {"show_reasoning": False},
    "messages": [],
}
sector_agent(state)
for t, s in state["data"]["analyst_signals"]["sector_agent"].items():
    m = s["metrics"]
    print(
        f"{t}: sector={m['sector']!r} ETF={m['sector_etf']} "
        f"RS={m['relative_strength_pp']} signal={s['signal']} conf={s['confidence']}"
    )
