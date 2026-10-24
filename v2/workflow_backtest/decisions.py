from __future__ import annotations
from v2.pipeline.orchestrator import run_agents_only
from v2.workflow_backtest.types import ArmResult, Decision

def run_arm_decisions(*, arm, scan_date, tickers, scanner_context, model_name, model_provider,
                      run_hedge_fund_fn=None):
    try:
        out = run_agents_only(
            tickers=tickers, scan_date=scan_date, scanner_context=scanner_context,
            model_name=model_name, model_provider=model_provider,
            run_hedge_fund_fn=run_hedge_fund_fn,
        )
    except Exception as e:
        return ArmResult(arm=arm, scan_date=scan_date, tickers=tickers, error=f"{type(e).__name__}: {e}")
    raw = out.get("decisions") or {}
    decisions = {}
    for t, d in raw.items():
        if not isinstance(d, dict):
            continue
        decisions[t] = Decision(ticker=t, action=d.get("action", "hold"),
                                quantity=int(d.get("quantity") or 0),
                                confidence=d.get("confidence"), reasoning=d.get("reasoning"))
    return ArmResult(arm=arm, scan_date=scan_date, tickers=tickers, decisions=decisions)
