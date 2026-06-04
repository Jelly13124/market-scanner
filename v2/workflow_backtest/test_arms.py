from v2.workflow_backtest.arms import scanner_arm, random_arm


class _Entry:
    def __init__(self, ticker, rank):
        self.ticker = ticker; self.rank = rank
        self.composite_score = 80.0; self.direction = "bullish"
        self.event_severity = 1.0; self.triggers = []


def _fake_run_scan(*, tickers, end_date, top_n, provider_factory=None, **kw):
    return [_Entry("NVDA", 1), _Entry("AAPL", 2)][:top_n]


def test_scanner_arm_returns_tickers_and_context():
    tickers, ctx = scanner_arm(scan_date="2025-03-03", universe_tickers=["NVDA", "AAPL", "MSFT"],
                               top_n=2, provider_factory=None, run_scan_fn=_fake_run_scan)
    assert tickers == ["NVDA", "AAPL"]
    assert set(ctx) == {"NVDA", "AAPL"}
    assert ctx["NVDA"]["rank"] == 1


def test_random_arm_seeded_reproducible():
    a = random_arm(scan_date="2025-03-03", universe_tickers=["A", "B", "C", "D", "E"], n=2, seed=42)
    b = random_arm(scan_date="2025-03-03", universe_tickers=["A", "B", "C", "D", "E"], n=2, seed=42)
    assert a == b and len(a) == 2 and set(a) <= {"A", "B", "C", "D", "E"}
    diff = random_arm(scan_date="2025-03-04", universe_tickers=["A", "B", "C", "D", "E"], n=2, seed=42)
    assert isinstance(diff, list) and len(diff) == 2
