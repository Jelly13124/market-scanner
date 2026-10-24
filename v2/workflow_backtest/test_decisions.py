from v2.workflow_backtest.decisions import run_arm_decisions

def _stub_ok(**kwargs):
    tickers = kwargs["tickers"]
    return {"decisions": {t: {"action": "buy", "quantity": 5, "confidence": 70} for t in tickers},
            "analyst_signals": {}}

def _stub_raises(**kwargs):
    raise RuntimeError("boom")

def test_run_arm_decisions_maps_decisions():
    ar = run_arm_decisions(arm="random", scan_date="2025-03-03", tickers=["NVDA"], scanner_context=None,
                           model_name="deepseek-v4-pro", model_provider="DeepSeek", run_hedge_fund_fn=_stub_ok)
    assert ar.error is None
    assert ar.decisions["NVDA"].action == "buy"
    assert ar.decisions["NVDA"].quantity == 5
    assert ar.decisions["NVDA"].confidence == 70

def test_run_arm_decisions_handles_failure():
    ar = run_arm_decisions(arm="scanner", scan_date="2025-03-03", tickers=["NVDA"], scanner_context={},
                           model_name="deepseek-v4-pro", model_provider="DeepSeek", run_hedge_fund_fn=_stub_raises)
    assert ar.error is not None
    assert ar.decisions == {}
