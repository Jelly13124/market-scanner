"""Compare the Scanner's public detector API to Lab's dated signal evaluations."""
from datetime import date, timedelta

import pytest

from v2.data.models import Price
from v2.scanner.detectors.daily_momentum import (
    RangeBreakoutDetector, RelativeStrengthDetector, RelativeVolumeDetector,
)
from src.lab.engine.data import _bars_to_dataframe
from src.lab.spec.strategy import EntryGroup


def history(closes, *, volumes=None, adjusted=None):
    return [
        Price(time=(date(2026, 1, 5) + timedelta(days=i)).isoformat(),
              open=c, high=c + 1, low=c - 1, close=c,
              adjusted_close=adjusted[i] if adjusted else None,
              volume=volumes[i] if volumes else 100)
        for i, c in enumerate(closes)
    ]


class Feed:
    def __init__(self, stock, benchmark):
        self.series = {"ABC": stock, "SPY": benchmark}

    def get_prices(self, ticker, start_date, end_date):
        return [p for p in self.series[ticker] if start_date <= p.time <= end_date]


@pytest.mark.parametrize("detector, stock, benchmark, expected", [
    (RelativeVolumeDetector, history([10, 10, 10, 11], volumes=[100, 100, 200, 199]), [],
     [None, None, (True, 'neutral'), (False, 'neutral')]),
    (RangeBreakoutDetector, history([20, 20, 10, 11, 9], adjusted=[10, 10, 10, 11, 9]), [],
     [None, None, (False, 'neutral'), (True, 'bullish'), (True, 'bearish')]),
    (RelativeStrengthDetector, history([100, 100, 110, 111]), history([100, 100, 100, 111]),
     [None, None, (True, 'bullish'), (False, 'neutral')]),
    (RelativeStrengthDetector, history([100, 100, 115, 120]), history([100, 100, 100, 100])[::2],
     [None, None, None, None]),
])
def test_same_daily_evidence_for_scanner_and_backtest(detector, stock, benchmark, expected):
    spec = EntryGroup.model_validate({'signals': [{'type': detector.name, 'window': 2, 'direction': 'any'}]})
    from src.lab.engine.signal_eval import iter_daily_rule_evidence

    lab = list(iter_daily_rule_evidence(spec.signals[0], _bars_to_dataframe(stock),
                                         _bars_to_dataframe(benchmark) if benchmark else None))
    feed = Feed(stock, benchmark)
    assert len(stock) == len(lab)
    for bar, (session, verdict), want in zip(stock, lab, expected, strict=True):
        scanner = detector(window=2).detect('ABC', bar.time, feed)
        assert session.date().isoformat() == bar.time
        assert scanner == verdict
        assert (None if verdict is None else (verdict.triggered, verdict.direction)) == want
        if verdict is not None:
            assert verdict.signal_session == bar.time


@pytest.mark.parametrize('lang, labels', [
    ('en', ['OR', 'matched', 'unavailable']),
    ('zh', ['OR', '已满足', '未记录']),
])
def test_analyze_explains_incomplete_or_group_that_selected_ticker(lang, labels):
    from src.research.scan_provenance import evidence_markdown
    from v2.rules.spec import RuleGroup

    group = RuleGroup.model_validate({'combiner': 'or', 'signals': [
        {'type': 'relative_volume', 'direction': 'neutral', 'threshold': 2.5},
        {'type': 'relative_strength', 'direction': 'bullish', 'threshold': 0.07},
    ]})
    source = {
        'ticker': 'ABC', 'detector_config': {'weights': {'rule_group': group.model_dump()}},
        'triggers': [{'detector': 'relative_volume', 'components': {'relative_volume': 3.0}}],
        'outcome': {'quality': {'rule_group': {'match': True, 'incomplete': True,
                    'matches': {'relative_volume': True, 'relative_strength': None}}}},
    }
    text = evidence_markdown(source, None, lang)
    for value in [*labels, 'relative_volume', 'relative_strength', '0.07', 'bullish', 'neutral']:
        assert value in text


def test_insufficient_history_for_long_window_does_not_overflow_calendar():
    stock = history([100, 101])
    detector = RangeBreakoutDetector(window=1_000_000)
    # Callers accept positive session counts, even when only a few quotes exist.
    assert detector.detect("ABC", stock[-1].time, Feed(stock, [])) is None


def test_backtest_reports_insufficient_history_for_long_window(monkeypatch):
    from src.lab.backtest_runner import run_backtest
    from src.lab.spec.strategy import StrategySpec

    spec = StrategySpec.model_validate({
        'name': 'Unavailable history', 'universe': {'kind': 'sp500'},
        'entry': {'signals': [{'type': 'range_breakout', 'window': 1_000_000}]},
        'exit': [{'type': 'time_stop', 'bars': 5}], 'sizing': {'type': 'fixed_pct', 'pct': 0.1},
        'backtest_config': {'start_date': '2026-01-05', 'end_date': '2026-01-07', 'benchmark': 'none'},
    })
    monkeypatch.setattr('src.lab.backtest_runner.load_universe_tickers', lambda *a, **kw: ['ABC'])
    monkeypatch.setattr('v2.data.factory.make_data_client', lambda: Feed(history([100, 101]), []))
    result = run_backtest(spec, None)
    assert result.verdict.label == 'insufficient'
    assert result.is_metrics is None and result.oos_metrics is None
