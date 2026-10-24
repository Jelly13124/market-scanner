"""Unit tests for YFinanceClient — mocked yfinance, no network."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from v2.data.yfinance_client import YFinanceClient, _normalize_action


# ---------------------------------------------------------------------------
# _normalize_action
# ---------------------------------------------------------------------------


class TestNormalizeAction:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("up", "up"),
            ("UP", "up"),
            ("upgrade", "up"),
            ("down", "down"),
            ("Downgrade", "down"),
            ("main", "main"),
            ("maintain", "main"),
            ("Reiterated", "reit"),
            ("reit", "reit"),
            ("init", "init"),
            ("Initiated", "init"),
            (None, "main"),
            ("something weird", "main"),
        ],
    )
    def test_maps_known_variants(self, raw, expected):
        assert _normalize_action(raw) == expected


# ---------------------------------------------------------------------------
# get_analyst_targets
# ---------------------------------------------------------------------------


class TestGetAnalystTargets:
    def test_happy_path(self):
        mock_ticker = MagicMock()
        mock_ticker.analyst_price_targets = {
            "current": 200.0,
            "high": 280.0,
            "low": 160.0,
            "mean": 220.5,
            "median": 215.0,
        }
        with patch("yfinance.Ticker", return_value=mock_ticker):
            client = YFinanceClient()
            target = client.get_analyst_targets("AAPL", asof_date="2026-05-15")
        assert target is not None
        assert target.ticker == "AAPL"
        assert target.current_price == 200.0
        assert target.target_mean == 220.5
        assert target.target_median == 215.0
        assert target.target_high == 280.0
        assert target.target_low == 160.0
        assert target.asof_date == "2026-05-15"

    def test_returns_none_when_empty(self):
        mock_ticker = MagicMock()
        mock_ticker.analyst_price_targets = {}
        with patch("yfinance.Ticker", return_value=mock_ticker):
            assert YFinanceClient().get_analyst_targets("AAPL") is None

    def test_returns_none_on_yfinance_exception(self):
        mock_ticker = MagicMock()
        type(mock_ticker).analyst_price_targets = property(lambda self: (_ for _ in ()).throw(RuntimeError("scraper broke")))
        with patch("yfinance.Ticker", return_value=mock_ticker):
            assert YFinanceClient().get_analyst_targets("AAPL") is None

    def test_fills_asof_date_when_omitted(self):
        mock_ticker = MagicMock()
        mock_ticker.analyst_price_targets = {"mean": 100.0, "current": 90.0}
        with patch("yfinance.Ticker", return_value=mock_ticker):
            target = YFinanceClient().get_analyst_targets("AAPL")
        assert target is not None
        # Today's ISO date — just sanity-check the format.
        assert target.asof_date == date.today().isoformat()


# ---------------------------------------------------------------------------
# get_analyst_actions
# ---------------------------------------------------------------------------


def _mock_upgrades_df():
    """Build a 4-row mock DataFrame mimicking yfinance.Ticker.upgrades_downgrades."""
    import pandas as pd

    rows = [
        {"GradeDate": "2026-05-10", "Firm": "Morgan Stanley", "ToGrade": "Overweight", "FromGrade": "Equal-Weight", "Action": "up"},
        {"GradeDate": "2026-05-05", "Firm": "Goldman", "ToGrade": "Buy", "FromGrade": "Hold", "Action": "up"},
        {"GradeDate": "2026-04-20", "Firm": "JPM", "ToGrade": "Underweight", "FromGrade": "Neutral", "Action": "down"},
        {"GradeDate": "2026-01-15", "Firm": "Wells", "ToGrade": "Equal-Weight", "FromGrade": "Equal-Weight", "Action": "main"},
    ]
    df = pd.DataFrame(rows)
    df.set_index(pd.to_datetime(df["GradeDate"]), inplace=True)
    df.drop(columns=["GradeDate"], inplace=True)
    return df


class TestGetAnalystActions:
    def test_filters_by_date_range(self):
        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = _mock_upgrades_df()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            actions = YFinanceClient().get_analyst_actions(
                "AAPL",
                end_date="2026-05-15",
                start_date="2026-05-01",
            )
        # Only 2 rows in the May 1-15 window.
        assert len(actions) == 2
        assert actions[0].action_date == "2026-05-10"
        assert actions[1].action_date == "2026-05-05"
        assert actions[0].firm == "Morgan Stanley"
        assert actions[0].action == "up"

    def test_normalizes_action_field(self):
        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = _mock_upgrades_df()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            actions = YFinanceClient().get_analyst_actions(
                "AAPL",
                end_date="2026-05-15",
                start_date="2026-01-01",
            )
        actions_by_date = {a.action_date: a.action for a in actions}
        assert actions_by_date["2026-05-10"] == "up"
        assert actions_by_date["2026-04-20"] == "down"
        assert actions_by_date["2026-01-15"] == "main"

    def test_empty_when_no_data(self):
        import pandas as pd

        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = pd.DataFrame()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            assert (
                YFinanceClient().get_analyst_actions(
                    "AAPL",
                    end_date="2026-05-15",
                    start_date="2026-01-01",
                )
                == []
            )

    def test_empty_on_yfinance_exception(self):
        mock_ticker = MagicMock()
        type(mock_ticker).upgrades_downgrades = property(lambda self: (_ for _ in ()).throw(RuntimeError("scraper broke")))
        with patch("yfinance.Ticker", return_value=mock_ticker):
            assert (
                YFinanceClient().get_analyst_actions(
                    "AAPL",
                    end_date="2026-05-15",
                    start_date="2026-01-01",
                )
                == []
            )

    def test_respects_limit(self):
        mock_ticker = MagicMock()
        mock_ticker.upgrades_downgrades = _mock_upgrades_df()
        with patch("yfinance.Ticker", return_value=mock_ticker):
            actions = YFinanceClient().get_analyst_actions(
                "AAPL",
                end_date="2026-05-15",
                start_date="2026-01-01",
                limit=2,
            )
        assert len(actions) == 2


# ---------------------------------------------------------------------------
# Unimplemented DataClient methods
# ---------------------------------------------------------------------------


class TestUnimplementedMethods:
    @pytest.mark.parametrize(
        "method,args",
        [
            ("get_prices", ("AAPL", "2026-01-01", "2026-05-15")),
            ("get_financial_metrics", ("AAPL", "2026-05-15")),
            ("get_news", ("AAPL", "2026-05-15")),
            ("get_insider_trades", ("AAPL", "2026-05-15")),
            ("get_company_facts", ("AAPL",)),
            ("get_earnings", ("AAPL",)),
            # get_earnings_history is now implemented (earnings route to yfinance).
            ("get_market_cap", ("AAPL", "2026-05-15")),
        ],
    )
    def test_raises_not_implemented(self, method, args):
        client = YFinanceClient()
        with pytest.raises(NotImplementedError, match="analyst data only"):
            getattr(client, method)(*args)


# ---------------------------------------------------------------------------
# get_estimate_revisions — load-bearing case-insensitive column lookup
# ---------------------------------------------------------------------------


def _make_eps_revisions_df(*, periods=("0q", "+1q", "0y", "+1y"), up7=None, down7=None, up30=None, down30=None, down7_camel=False):
    """Build a fake yfinance eps_revisions DataFrame.

    yfinance's column casing is inconsistent: observed live as
    ``upLast7days`` (lowercase d) but ``downLast7Days`` (uppercase D).
    ``down7_camel=True`` mimics that real-world casing; ``False`` uses
    all-lowercase. Detector must handle both."""
    import pandas as pd

    down7_col = "downLast7Days" if down7_camel else "downLast7days"
    rows = []
    for p in periods:
        rows.append(
            {
                "upLast7days": (up7 if p == "0q" else 0),
                "upLast30days": (up30 if p == "0q" else 0),
                "downLast30days": (down30 if p == "0q" else 0),
                down7_col: (down7 if p == "0q" else 0),
            }
        )
    return pd.DataFrame(rows, index=list(periods))


class TestGetEstimateRevisions:
    def test_reads_lowercase_columns(self):
        """Baseline: all-lowercase column names work (legacy yfinance casing)."""
        df = _make_eps_revisions_df(up7=10, down7=2, up30=15, down30=5, down7_camel=False)
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value.eps_revisions = df
            client = YFinanceClient()
            r = client.get_estimate_revisions("AAPL")
        assert r is not None
        assert r.up_last_7d == 10
        assert r.down_last_7d == 2
        assert r.up_last_30d == 15
        assert r.down_last_30d == 5

    def test_reads_camelcase_downlast7days(self):
        """Regression: yfinance live data uses ``downLast7Days`` (uppercase D)
        which previously was silently dropped → down_7d=0 → every covered
        ticker triggered as 100% bullish consensus. Lookup must be
        case-insensitive."""
        df = _make_eps_revisions_df(up7=10, down7=8, up30=15, down30=12, down7_camel=True)
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value.eps_revisions = df
            client = YFinanceClient()
            r = client.get_estimate_revisions("AAPL")
        assert r is not None
        assert r.up_last_7d == 10
        assert r.down_last_7d == 8, "downLast7Days column was not read — case-sensitive lookup bug"

    def test_returns_none_on_empty_dataframe(self):
        import pandas as pd

        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value.eps_revisions = pd.DataFrame()
            client = YFinanceClient()
            assert client.get_estimate_revisions("AAPL") is None

    def test_returns_none_on_missing_period(self):
        df = _make_eps_revisions_df(periods=("+1q", "0y"), up7=5)
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value.eps_revisions = df
            client = YFinanceClient()
            # Asking for "0q" but DataFrame doesn't have it.
            assert client.get_estimate_revisions("AAPL", period="0q") is None

    def test_period_arg_selects_correct_row(self):
        df = _make_eps_revisions_df(up7=99, down7=99, down7_camel=True)
        # Add a "+1q" row with different values (note the casing mismatch
        # between row dicts isn't realistic for yfinance — they apply uniform
        # cols — but pandas will tolerate it for the test).
        import pandas as pd

        df.loc["+1q"] = {"upLast7days": 3, "upLast30days": 4, "downLast30days": 0, "downLast7Days": 1}
        with patch("yfinance.Ticker") as MockTicker:
            MockTicker.return_value.eps_revisions = df
            client = YFinanceClient()
            r = client.get_estimate_revisions("AAPL", period="+1q")
        assert r is not None
        assert r.period == "+1q"
        assert r.up_last_7d == 3
        assert r.down_last_7d == 1

    def test_returns_none_when_ticker_throws(self):
        with patch("yfinance.Ticker", side_effect=RuntimeError("network")):
            client = YFinanceClient()
            assert client.get_estimate_revisions("AAPL") is None
