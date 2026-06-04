from v2.workflow_backtest.types import Decision, ArmResult

def test_decision_defaults():
    d = Decision(ticker="NVDA", action="buy", quantity=10)
    assert d.ticker == "NVDA" and d.action == "buy" and d.quantity == 10
    assert d.confidence is None  # not guaranteed by all agent paths

def test_arm_result_holds_decisions():
    ar = ArmResult(arm="scanner", scan_date="2025-03-03", tickers=["NVDA"],
                   decisions={"NVDA": Decision(ticker="NVDA", action="buy", quantity=10, confidence=80)})
    assert ar.decisions["NVDA"].confidence == 80
