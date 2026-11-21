"""Versioned rule definitions, daily evidence and condition semantics."""

import pytest
from pydantic import ValidationError


def test_group_round_trips_explicit_rule_identity_and_defaults():
    from v2.rules.spec import DailyRule, RuleGroup

    group = RuleGroup.model_validate({
        "combiner": "or",
        "signals": [{"type": name} for name in
                    ("relative_volume", "range_breakout", "relative_strength")],
    })
    assert all(isinstance(rule, DailyRule) for rule in group.signals)
    assert group.signals[0].threshold == 2
    assert group.signals[2].threshold == .05
    assert group.model_dump()["signals"][1] == {
        "type": "range_breakout", "version": "1", "window": 20, "direction": "bullish",
    }
    assert RuleGroup.model_validate_json(group.model_dump_json()) == group


@pytest.mark.parametrize("signals", [
    [], [{"type": "retired"}], [{"type": "range_breakout", "version": "2"}],
    [{"type": "range_breakout", "window": 0}], [{"type": "range_breakout", "threshold": 2}],
    [{"type": "relative_volume", "threshold": 1}],
    [{"type": "relative_strength", "threshold": float("inf")}],
    [{"type": "relative_strength", "threshold": 0}],
    [{"type": "relative_volume", "direction": "up"}],
    [{"combiner": "or", "signals": [{"type": "range_breakout"}]}],
])
def test_group_rejects_unsupported_definitions(signals):
    from v2.rules.spec import RuleGroup

    with pytest.raises(ValidationError):
        RuleGroup(combiner="and", signals=signals)


def bars(closes, volumes=None):
    from v2.data.models import Price

    if volumes is None:
        volumes = [100] * len(closes)
    return [
        Price(time=f"2026-10-{day:02}", open=close, high=close, low=close,
              close=close, volume=volume)
        for day, (close, volume) in enumerate(zip(closes, volumes, strict=True), start=1)
    ]


@pytest.mark.parametrize("name", ["relative_volume", "range_breakout", "relative_strength"])
def test_window_needs_n_prior_sessions(name):
    from v2.rules.daily import evaluate_rule
    from v2.rules.spec import RuleGroup

    rule = RuleGroup(combiner="and", signals=[{"type": name, "window": 2}]).signals[0]
    stock = bars([100, 120], [100, 300])
    assert evaluate_rule(rule, stock, bars([100, 100])) is None


def test_volume_hit_has_raw_neutral_evidence_even_for_bullish_condition():
    from v2.rules.daily import evaluate_rule, match_condition
    from v2.rules.spec import RelativeVolumeRule

    stock = bars([100, 110, 55], [50, 150, 200])
    stock[1].adjusted_close = 55
    rule = RelativeVolumeRule(window=2)
    hit = evaluate_rule(rule, stock)
    assert hit.triggered and hit.direction == "neutral" and hit.severity_z == 0
    assert hit.asof_date == hit.signal_session == "2026-10-03"
    assert hit.components == {"relative_volume": 2, "baseline_volume": 100,
                              "today_volume": 200, "daily_return": 0}
    assert match_condition(rule, hit) is False
    for direction in ("neutral", "any"):
        assert match_condition(rule.model_copy(update={"direction": direction}), hit) is True
    stock[-1].volume = 199
    miss = evaluate_rule(rule, stock)
    assert miss.triggered is False
    assert match_condition(RelativeVolumeRule(direction="neutral"), miss) is False
    assert match_condition(rule, None) is None


def test_breakout_equality_uses_preceding_adjusted_closes():
    from v2.rules.daily import evaluate_rule
    from v2.rules.spec import RangeBreakoutRule

    stock = bars([1000, 90, 95, 100])
    stock[-2].adjusted_close = 100
    rule = RangeBreakoutRule(window=2)
    result = evaluate_rule(rule, stock)
    assert result.triggered is False
    assert result.components == {"prior_high_close": 100, "prior_low_close": 90,
                                 "window": 2, "close": 100}
    stock[-1].adjusted_close = 89
    hit = evaluate_rule(rule, stock)
    assert hit.triggered and hit.direction == "bearish" and hit.severity_z == -2


@pytest.mark.parametrize("last_stock,last_spy,triggered,direction", [
    (115, 110, True, "bullish"), (110, 115, True, "bearish"),
    (114.99999999999999, 110, False, "neutral"),
])
def test_strength_includes_exact_five_point_spread(last_stock, last_spy, triggered, direction):
    from v2.rules.daily import evaluate_rule
    from v2.rules.spec import RelativeStrengthRule

    stock = bars([100, last_stock])
    spy = bars([100, last_spy])
    result = evaluate_rule(RelativeStrengthRule(window=1), stock, spy)
    assert result.triggered is triggered
    assert result.direction == direction
    assert result.components["return_spread"] == pytest.approx(.05 if last_stock > last_spy else -.05)


def test_scanner_strength_applies_same_inclusive_five_point_boundary():
    from v2.scanner.detectors.daily_momentum import RelativeStrengthDetector

    class PriceFeed:
        def get_prices(self, ticker, start, end):
            return bars([100, 110 if ticker == "SPY" else 115])

    result = RelativeStrengthDetector(window=1).detect("XYZ", "2026-10-02", PriceFeed())
    assert result.triggered and result.direction == "bullish"


def test_strength_requires_every_benchmark_session_including_latest():
    from v2.rules.daily import evaluate_rule
    from v2.rules.spec import RelativeStrengthRule

    stock = bars([100, 100, 110, 120])
    spy = bars([100, 100, 100])
    rule = RelativeStrengthRule(window=2)
    assert evaluate_rule(rule, stock, spy) is None
    assert evaluate_rule(rule, [stock[0], stock[2]], spy) is None
    assert evaluate_rule(rule, stock[:3], spy).triggered


@pytest.mark.parametrize("window,days", [(1, 90), (40, 120)])
def test_lookback_keeps_scanner_calendar_window(window, days):
    from v2.rules.daily import lookback_days

    assert lookback_days(window) == days


@pytest.mark.parametrize("combiner, operands, expected", [
    ("and", [True, True], True), ("and", [False, None], False),
    ("and", [True, None], None), ("and", [None, None], None),
    ("or", [False, False], False), ("or", [True, None], True),
    ("or", [False, None], None), ("or", [None, None], None),
])
def test_group_combines_incomplete_evidence(combiner, operands, expected):
    from v2.rules.daily import combine_matches

    assert combine_matches(combiner, operands) is expected
