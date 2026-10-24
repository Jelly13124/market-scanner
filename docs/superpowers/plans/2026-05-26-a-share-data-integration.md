# Phase 8 — A-Share Data Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Wire `simonlin1212/a-stock-data` (China A-share data source) into the existing v2/data layer so the SOP analyze pipeline, scanner, and Lab backtest engine all work on A-shares (SSE/SZSE/STAR/ChiNext/BSE) end-to-end.

**Architecture:** A new `AShareClient` class implements the existing `DataClient` Protocol — no protocol change. CompositeClient gains symbol-aware dispatch (A-share tickers → AShareClient; US → existing hybrid). 5 new universe CSVs (CSI 300/500/1000, SSE 50, HS 300+CSI 500). A-share benchmark = 沪深300, sector ETFs swap to 申万一级 (SW1) indices. Frontend gets a Market dropdown + universe options. Spec: `docs/superpowers/specs/2026-05-26-a-share-data-integration.md`.

**Tech Stack:** Python 3.12, mootdx (TDX market data), Eastmoney/Tencent/CLS HTTP scraping, pytest with mocked HTTP, React + react-i18next, Pydantic v2.

## Execution model (wave parallelism for overnight subagent dispatch)

```
Wave 1 (single agent, ~30min) — Foundation
  Task 1-3: deps + symbol normalization + Protocol conformance test stub

Wave 2 (3 agents parallel, ~1.5h) — Independent data fetchers
  Wave 2A: Task 4 mootdx_prices
  Wave 2B: Task 5-7 Eastmoney (fundamentals + earnings + market_cap)
  Wave 2C: Task 8-9 CLS news + SW sector map

Wave 3 (single agent, ~45min) — Compose AShareClient + universes
  Task 10-11: AShareClient main class + protocol conformance
  Task 12: 5 universe CSVs + loader extension

Wave 4 (single agent, ~30min) — CompositeClient routing + factory
  Task 13-14: symbol-aware dispatch + make_hybrid_client(include_ashare=True)

Wave 5 (single agent, ~45min) — SOP pipeline integration
  Task 15-17: shared_data benchmark/sector swap + AnalyzeRequest.market field + route wiring

Wave 6 (single agent, ~30min) — Frontend
  Task 18-20: market dropdown + universe options + i18n keys

Wave 7 (single agent, ~30min) — Smoke + progress.md
  Task 21-22: live data smoke + progress block

Total: ~4.5-5 hours wall clock with parallelization
```

---

## Task 1: Add mootdx + stockstats as optional [ashare] extra

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the extra group**

Edit `pyproject.toml` — find `[tool.poetry.dependencies]` and add (or add an optional-deps section):

```toml
[tool.poetry.dependencies]
# ... existing ...
mootdx = { version = "^2.1.6", optional = true }
stockstats = { version = "^0.6.2", optional = true }

[tool.poetry.extras]
ashare = ["mootdx", "stockstats"]
```

(If pyproject.toml uses PEP 621 `[project.optional-dependencies]` instead of poetry sections, use that idiom — check the existing file first.)

- [ ] **Step 2: Install the extra**

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m pip install mootdx stockstats
```

(Pip-install directly rather than `poetry install --extras ashare` since the user reported Poetry isn't on PATH in this environment.)

- [ ] **Step 3: Confirm import works**

```powershell
C:\Users\Jerry\anaconda3\python.exe -c "import mootdx; import stockstats; print('ok')"
```

Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
deps: add mootdx + stockstats as optional [ashare] extra

Phase 8 prep. Used for A-share OHLCV (mootdx) and indicator helpers
(stockstats). Optional so US-only deployments don't pull them.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Symbol normalization module

**Files:**
- Create: `v2/data/ashare/__init__.py` (empty)
- Create: `v2/data/ashare/symbol.py`
- Create: `tests/v2/data/ashare/__init__.py` (empty)
- Create: `tests/v2/data/ashare/test_symbol.py`

- [ ] **Step 1: Write the test first**

`tests/v2/data/ashare/test_symbol.py`:

```python
"""Phase 8: A-share symbol detection + canonical form normalization."""
from __future__ import annotations

import pytest
from v2.data.ashare.symbol import is_ashare, normalize, infer_exchange


class TestIsAshare:
    @pytest.mark.parametrize("ticker,expected", [
        ("600519", True),         # bare 6 digits
        ("600519.SH", True),
        ("000001.SZ", True),
        ("300750.SZ", True),
        ("688981.SH", True),
        ("830799.BJ", True),
        ("sh600519", True),       # prefix form
        ("SZ.000001", True),
        ("NVDA", False),
        ("BRK.B", False),
        ("AAPL.US", False),
        ("", False),
        ("00519", False),         # 5 digits is not A-share
        ("6005191", False),       # 7 digits is not A-share
    ])
    def test_detection(self, ticker, expected):
        assert is_ashare(ticker) is expected


class TestNormalize:
    @pytest.mark.parametrize("input,expected", [
        ("600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("SH.600519", "600519.SH"),
        ("000001", "000001.SZ"),
        ("300750", "300750.SZ"),
        ("688981", "688981.SH"),
        ("830799", "830799.BJ"),
    ])
    def test_canonical(self, input, expected):
        assert normalize(input) == expected

    def test_raises_on_non_ashare(self):
        with pytest.raises(ValueError):
            normalize("NVDA")


class TestInferExchange:
    @pytest.mark.parametrize("code,exchange", [
        ("600519", "SH"),
        ("601318", "SH"),
        ("688981", "SH"),
        ("900957", "SH"),     # B-share
        ("000001", "SZ"),
        ("002594", "SZ"),
        ("300750", "SZ"),
        ("200002", "SZ"),     # B-share
        ("830799", "BJ"),
        ("872925", "BJ"),
    ])
    def test_inference(self, code, exchange):
        assert infer_exchange(code) == exchange
```

- [ ] **Step 2: Run, expect ImportError**

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/v2/data/ashare/test_symbol.py -v
```

Expected: `ModuleNotFoundError: v2.data.ashare`

- [ ] **Step 3: Implement**

`v2/data/ashare/__init__.py`:
```python
"""A-share (China stock) data source — see docs/superpowers/specs/
2026-05-26-a-share-data-integration.md."""
```

`v2/data/ashare/symbol.py`:

```python
"""A-share symbol detection + canonical-form normalization.

Canonical form: '<6-digit-code>.<SH|SZ|BJ>'
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"^[0-9]{6}$")
_WITH_SUFFIX = re.compile(r"^([0-9]{6})\.(SH|SZ|BJ)$", re.IGNORECASE)
_WITH_PREFIX = re.compile(r"^(SH|SZ|BJ)\.?([0-9]{6})$", re.IGNORECASE)


def is_ashare(ticker: str) -> bool:
    """Return True iff ticker matches any accepted A-share form."""
    if not ticker:
        return False
    t = ticker.strip()
    return bool(
        _DIGITS.match(t)
        or _WITH_SUFFIX.match(t)
        or _WITH_PREFIX.match(t)
    )


def infer_exchange(code: str) -> str:
    """From a 6-digit code, infer the exchange. Returns 'SH' | 'SZ' | 'BJ'.

    Prefix rules (per exchange's listed code allocation):
      SH: 6xxxxx (A), 9xxxxx (B-share)
      SZ: 0xxxxx (A), 3xxxxx (ChiNext), 2xxxxx (B-share)
      BJ: 4xxxxx, 8xxxxx, 9[2-9]xxxx
    """
    if not _DIGITS.match(code):
        raise ValueError(f"not a 6-digit code: {code!r}")
    p = code[0]
    if p == "6" or p == "9":
        # 92-99 belongs to BJ; 90-91 belongs to SH B-share
        if p == "9" and code[1] in ("2", "3", "4", "5", "6", "7", "8", "9"):
            return "BJ"
        return "SH"
    if p in ("0", "3", "2"):
        return "SZ"
    if p in ("4", "8"):
        return "BJ"
    raise ValueError(f"unrecognized A-share code prefix: {code!r}")


def normalize(ticker: str) -> str:
    """Convert any accepted A-share form to canonical '<code>.<exchange>'.

    Raises ValueError on non-A-share input.
    """
    if not is_ashare(ticker):
        raise ValueError(f"not an A-share ticker: {ticker!r}")
    t = ticker.strip()
    if m := _WITH_SUFFIX.match(t):
        return f"{m.group(1)}.{m.group(2).upper()}"
    if m := _WITH_PREFIX.match(t):
        return f"{m.group(2)}.{m.group(1).upper()}"
    # bare 6 digits — infer
    return f"{t}.{infer_exchange(t)}"
```

- [ ] **Step 4: Run, all pass**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/v2/data/ashare/test_symbol.py -v
```

Expected: all pass (~20 tests).

- [ ] **Step 5: Commit**

```bash
git add v2/data/ashare/__init__.py v2/data/ashare/symbol.py \
        tests/v2/data/ashare/__init__.py tests/v2/data/ashare/test_symbol.py
git commit -m "$(cat <<'EOF'
feat(ashare): symbol detection + canonical normalization

Accepts bare 6-digit codes, .SH/.SZ/.BJ suffixed forms, and SH./SZ./BJ.
prefixed forms. Normalizes to '<code>.<exchange>' canonical form.
Exchange inferred from code prefix per SSE/SZSE/BSE allocation rules.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: AShareClient skeleton + Protocol conformance test

**Files:**
- Create: `v2/data/ashare/client.py` (skeleton — returns empty lists for now)
- Create: `tests/v2/data/ashare/test_client_protocol.py`

- [ ] **Step 1: Write the failing conformance test**

`tests/v2/data/ashare/test_client_protocol.py`:

```python
"""Phase 8: AShareClient implements the DataClient Protocol."""
from __future__ import annotations

import pytest
from v2.data.protocol import DataClient
from v2.data.ashare.client import AShareClient


def test_implements_protocol():
    c = AShareClient()
    # Pydantic Protocol — duck-type check
    assert hasattr(c, "get_prices")
    assert hasattr(c, "get_financial_metrics")
    assert hasattr(c, "get_news")
    assert hasattr(c, "get_company_facts")
    assert hasattr(c, "get_earnings_history")
    assert hasattr(c, "get_market_cap")
    assert callable(c.get_prices)


def test_returns_empty_on_unknown_ticker():
    """Per Protocol invariant — never raise; return empty list on missing data."""
    c = AShareClient()
    prices = c.get_prices("999999", "2025-01-01", "2026-05-26")
    assert prices == []
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement skeleton**

`v2/data/ashare/client.py`:

```python
"""AShareClient — implements DataClient Protocol for China A-shares.

Backed by mootdx (OHLCV) + Eastmoney (fundamentals/earnings/market_cap)
+ 财联社 (news) HTTP APIs. All free, no auth required.

Per the Protocol invariant, no method raises — failures degrade to
empty list / None. Per-instance requests.Session; not thread-safe
across threads — instantiate one per worker.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import requests

from v2.data.ashare.symbol import is_ashare, normalize
from v2.data.models import (
    CompanyFacts,
    CompanyNews,
    EarningsRecord,
    FinancialMetrics,
    Price,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AShareClient:
    """DataClient for SSE/SZSE/BSE/STAR/ChiNext A-shares."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_news_per_call: int = 50,
    ):
        self.timeout = timeout
        self.max_news = max_news_per_call
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        })

    def close(self) -> None:
        self._session.close()

    # -----------------------------------------------------------------
    # Protocol methods — skeletons. Real impls in subsequent tasks.
    # -----------------------------------------------------------------

    def get_prices(self, ticker, start_date, end_date, **kwargs) -> list[Price]:
        if not is_ashare(ticker):
            return []
        from v2.data.ashare.mootdx_prices import fetch_daily_ohlcv
        try:
            return fetch_daily_ohlcv(normalize(ticker), start_date, end_date)
        except Exception as e:
            logger.warning("get_prices(%s) failed: %s", ticker, e)
            return []

    def get_financial_metrics(
        self, ticker, end_date, period="ttm", limit=10,
    ) -> list[FinancialMetrics]:
        if not is_ashare(ticker):
            return []
        from v2.data.ashare.eastmoney_fundamentals import fetch_financial_metrics
        try:
            return fetch_financial_metrics(
                normalize(ticker), end_date, period=period, limit=limit,
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_financial_metrics(%s) failed: %s", ticker, e)
            return []

    def get_news(
        self, ticker, end_date, start_date=None, limit=1000,
    ) -> list[CompanyNews]:
        if not is_ashare(ticker):
            return []
        from v2.data.ashare.cls_news import fetch_stock_news
        try:
            return fetch_stock_news(
                normalize(ticker), end_date,
                start_date=start_date, limit=min(limit, self.max_news),
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_news(%s) failed: %s", ticker, e)
            return []

    def get_company_facts(self, ticker) -> CompanyFacts | None:
        if not is_ashare(ticker):
            return None
        from v2.data.ashare.eastmoney_fundamentals import fetch_company_facts
        try:
            return fetch_company_facts(
                normalize(ticker),
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_company_facts(%s) failed: %s", ticker, e)
            return None

    def get_earnings_history(self, ticker, limit=12) -> list[EarningsRecord]:
        if not is_ashare(ticker):
            return []
        from v2.data.ashare.eastmoney_earnings import fetch_earnings_history
        try:
            return fetch_earnings_history(
                normalize(ticker), limit=limit,
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_earnings_history(%s) failed: %s", ticker, e)
            return []

    def get_market_cap(self, ticker, end_date) -> float | None:
        if not is_ashare(ticker):
            return None
        from v2.data.ashare.eastmoney_market_cap import fetch_market_cap
        try:
            return fetch_market_cap(
                normalize(ticker), end_date,
                session=self._session, timeout=self.timeout,
            )
        except Exception as e:
            logger.warning("get_market_cap(%s) failed: %s", ticker, e)
            return None

    # Optional protocol methods — v1 returns empty / None (analyst data
    # and earnings calendar are v2 scope per spec).

    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        return []

    def get_earnings(self, ticker):
        return None

    def get_earnings_calendar(self, start_date, end_date):
        return []
```

- [ ] **Step 4: Run, expect 2 pass + ModuleNotFoundError on the helpers (acceptable — helpers ship in Wave 2)**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/v2/data/ashare/test_client_protocol.py -v
```

For `test_returns_empty_on_unknown_ticker`: the import of `mootdx_prices` fails because Wave 2A hasn't created it yet. That's OK — the try/except catches the exception and returns `[]`. Both tests should pass.

If both pass: ✓ proceed. If `test_returns_empty_on_unknown_ticker` fails because mootdx_prices import raises out of the try block, that means the lazy import failed at import-time rather than call-time. Re-read the client code and confirm imports are inside method bodies.

- [ ] **Step 5: Commit**

```bash
git add v2/data/ashare/client.py tests/v2/data/ashare/test_client_protocol.py
git commit -m "$(cat <<'EOF'
feat(ashare): AShareClient skeleton implementing DataClient Protocol

All 6 v1 methods route by is_ashare(ticker) — non-A-share input returns
empty/None. Real implementations live in lazy-imported helper modules
(Wave 2). Per-instance requests.Session; not thread-safe across threads.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: mootdx_prices — daily OHLCV (Wave 2A)

**Files:**
- Create: `v2/data/ashare/mootdx_prices.py`
- Create: `tests/v2/data/ashare/test_mootdx_prices.py`

- [ ] **Step 1: Failing test**

`tests/v2/data/ashare/test_mootdx_prices.py`:

```python
"""Phase 8: mootdx-backed OHLCV fetcher."""
from __future__ import annotations

from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from v2.data.ashare.mootdx_prices import fetch_daily_ohlcv, _split_canonical


def test_split_canonical():
    code, exch = _split_canonical("600519.SH")
    assert code == "600519"
    assert exch == "SH"


@patch("v2.data.ashare.mootdx_prices.Quotes")
def test_fetch_daily_returns_typed_prices(MockQuotes):
    # mootdx returns a DataFrame with columns:
    # ['open', 'high', 'low', 'close', 'vol', 'amount', 'date']
    fake_df = pd.DataFrame({
        'open':   [100.0, 101.0, 102.0],
        'high':   [101.0, 103.0, 104.0],
        'low':    [99.0,  100.0, 101.0],
        'close':  [100.5, 102.0, 103.5],
        'vol':    [1e7,   1.2e7, 1.5e7],
        'amount': [1e9,   1.2e9, 1.5e9],
        'date':   pd.to_datetime(['2025-01-02', '2025-01-03', '2025-01-06']),
    })
    instance = MagicMock()
    instance.bars.return_value = fake_df
    MockQuotes.factory.return_value = instance

    prices = fetch_daily_ohlcv('600519.SH', '2025-01-01', '2025-01-10')

    assert len(prices) == 3
    assert prices[0].close == 100.5
    assert prices[0].open == 100.0
    assert prices[0].high == 101.0
    assert prices[0].low == 99.0
    assert prices[0].volume == 1e7
    # canonicalize date as ISO string in 'time' field
    assert prices[0].time == '2025-01-02'


@patch("v2.data.ashare.mootdx_prices.Quotes")
def test_fetch_daily_empty_when_mootdx_returns_none(MockQuotes):
    instance = MagicMock()
    instance.bars.return_value = None
    MockQuotes.factory.return_value = instance

    prices = fetch_daily_ohlcv('600519.SH', '2025-01-01', '2025-01-10')
    assert prices == []


@patch("v2.data.ashare.mootdx_prices.Quotes")
def test_fetch_daily_filters_to_window(MockQuotes):
    fake_df = pd.DataFrame({
        'open': [1.0] * 5, 'high': [1.0] * 5, 'low': [1.0] * 5,
        'close': [1.0] * 5, 'vol': [0] * 5, 'amount': [0] * 5,
        'date': pd.to_datetime([
            '2024-12-30', '2024-12-31', '2025-01-02', '2025-01-03', '2025-01-06',
        ]),
    })
    instance = MagicMock()
    instance.bars.return_value = fake_df
    MockQuotes.factory.return_value = instance

    prices = fetch_daily_ohlcv('600519.SH', '2025-01-01', '2025-01-31')
    # First 2 rows out of window
    assert len(prices) == 3
    assert prices[0].time == '2025-01-02'
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`v2/data/ashare/mootdx_prices.py`:

```python
"""Daily OHLCV via mootdx (TDX market data).

mootdx is a pure-Python TDX client that connects to TCP servers maintained
by 通达信. No API key required; servers are free. The library bundles a
fallback list and rotates on connection failure — we surface the final
exception to the caller (AShareClient catches and returns []).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

import pandas as pd

from v2.data.models import Price

# Lazy import inside functions so non-A-share workflows don't pay the
# mootdx import cost (and don't break when the [ashare] extra is absent).
try:
    from mootdx.quotes import Quotes
except ImportError as e:
    Quotes = None  # type: ignore
    _IMPORT_ERROR = e
else:
    _IMPORT_ERROR = None


def _split_canonical(ticker: str) -> tuple[str, str]:
    """'600519.SH' -> ('600519', 'SH')."""
    code, exch = ticker.split('.', 1)
    return code, exch.upper()


def _mootdx_market(exch: str) -> int:
    """mootdx uses 0=SZ, 1=SH for market parameter. BSE not yet supported
    by mootdx core — return -1 to signal caller to skip."""
    return {'SZ': 0, 'SH': 1}.get(exch, -1)


def fetch_daily_ohlcv(
    canonical_ticker: str,
    start_date: str,
    end_date: str,
    *,
    n_bars: int = 800,
) -> list[Price]:
    """Fetch daily OHLCV for a canonical A-share ticker.

    Returns list[Price] sorted ascending by date, restricted to
    [start_date, end_date] inclusive.
    """
    if Quotes is None:
        raise RuntimeError(
            "mootdx not installed — `pip install mootdx` or "
            "`poetry install --extras ashare`"
        ) from _IMPORT_ERROR

    code, exch = _split_canonical(canonical_ticker)
    market = _mootdx_market(exch)
    if market == -1:
        # BSE not supported by mootdx core in v3.1.0; v2 will use Eastmoney
        return []

    client = Quotes.factory(market='std')  # 'std' = standard, no extended
    # mootdx `bars` signature: (symbol, frequency, market, start, n)
    # frequency 9 = daily. mootdx returns latest N bars; we filter.
    df = client.bars(symbol=code, frequency=9, market=market, n=n_bars)
    if df is None or len(df) == 0:
        return []
    return _df_to_prices(df, start_date, end_date)


def _df_to_prices(df: pd.DataFrame, start_date: str, end_date: str) -> list[Price]:
    """Convert mootdx DataFrame to list[Price], filtered to date window."""
    if 'date' not in df.columns:
        # some mootdx versions use 'datetime' or set index — normalize
        if 'datetime' in df.columns:
            df = df.rename(columns={'datetime': 'date'})
        elif df.index.name in ('date', 'datetime'):
            df = df.reset_index().rename(columns={df.index.name: 'date'})
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    df = df[(df['date'] >= start_ts) & (df['date'] <= end_ts)]

    out: list[Price] = []
    for _, row in df.iterrows():
        out.append(Price(
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row.get('vol', row.get('volume', 0))),
            time=row['date'].strftime('%Y-%m-%d'),
            adjusted_close=float(row['close']),  # mootdx daily already adjusted
        ))
    return out
```

- [ ] **Step 4: Run tests, all pass**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/v2/data/ashare/test_mootdx_prices.py -v
```

- [ ] **Step 5: Commit**

```bash
git add v2/data/ashare/mootdx_prices.py tests/v2/data/ashare/test_mootdx_prices.py
git commit -m "$(cat <<'EOF'
feat(ashare): mootdx-backed daily OHLCV fetcher

fetch_daily_ohlcv normalizes mootdx DataFrame to list[Price], filters
to the requested date window, sorts ascending. Lazy import keeps non-
ashare workflows from paying the mootdx cost. BSE returns [] for now
(mootdx core doesn't yet support market=2; v2 will use Eastmoney).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Eastmoney fundamentals (financial_metrics + company_facts) (Wave 2B-1)

**Files:**
- Create: `v2/data/ashare/eastmoney_fundamentals.py`
- Create: `tests/v2/data/ashare/test_eastmoney_fundamentals.py`

- [ ] **Step 1: Failing test**

`tests/v2/data/ashare/test_eastmoney_fundamentals.py`:

```python
"""Phase 8: Eastmoney F10 fundamentals fetcher (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from v2.data.ashare.eastmoney_fundamentals import (
    fetch_financial_metrics, fetch_company_facts,
)


def _mock_session(json_payload):
    """Build a fake session whose .get(...).json() returns the payload."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_payload
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_fetch_financial_metrics_parses_eastmoney_shape():
    # Eastmoney F10 financial-indicators endpoint returns:
    # {"result": {"data": [{"REPORT_DATE": "2024-09-30",
    #   "BASIC_EPS": 12.34, "TOTAL_OPERATE_INCOME": 1.2e11, ...}]}}
    payload = {
        "result": {
            "data": [
                {
                    "REPORT_DATE": "2024-09-30",
                    "BASIC_EPS": 50.12,
                    "TOTAL_OPERATE_INCOME": 1.2e11,
                    "NETPROFIT": 4.5e10,
                    "ROE_AVG": 25.6,
                    "GROSSPROFIT_MARGIN": 92.0,
                    "DEBT_ASSET_RATIO": 15.3,
                },
                {
                    "REPORT_DATE": "2024-06-30",
                    "BASIC_EPS": 32.10,
                    "TOTAL_OPERATE_INCOME": 8.0e10,
                    "NETPROFIT": 3.2e10,
                    "ROE_AVG": 18.2,
                    "GROSSPROFIT_MARGIN": 91.5,
                    "DEBT_ASSET_RATIO": 16.0,
                },
            ]
        }
    }
    sess = _mock_session(payload)
    metrics = fetch_financial_metrics(
        "600519.SH", "2026-05-26", period="ttm", limit=4, session=sess,
    )
    assert len(metrics) == 2
    assert metrics[0].report_period == "2024-09-30"
    assert metrics[0].earnings_per_share == 50.12
    assert metrics[0].return_on_equity == 0.256
    assert metrics[0].gross_margin == 0.92
    assert metrics[0].debt_to_assets == 0.153


def test_fetch_company_facts_parses_eastmoney_shape():
    payload = {
        "jbzl": {
            "SECURITY_NAME_ABBR": "贵州茅台",
            "INDUSTRYNAME": "白酒",
            "SECTOR_NAME": "食品饮料",
            "AREA_NAME": "贵州",
            "EMP_NUM": 30000,
            "LISTING_DATE": "2001-08-27",
        }
    }
    sess = _mock_session(payload)
    facts = fetch_company_facts("600519.SH", session=sess)
    assert facts is not None
    assert facts.name == "贵州茅台"
    assert facts.industry == "白酒"
    assert facts.sector == "食品饮料"
    assert facts.employee_count == 30000


def test_fetch_financial_metrics_returns_empty_on_empty_payload():
    sess = _mock_session({"result": {"data": []}})
    metrics = fetch_financial_metrics(
        "600519.SH", "2026-05-26", session=sess,
    )
    assert metrics == []


def test_fetch_company_facts_returns_none_on_missing_jbzl():
    sess = _mock_session({})
    facts = fetch_company_facts("600519.SH", session=sess)
    assert facts is None
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`v2/data/ashare/eastmoney_fundamentals.py`:

```python
"""Eastmoney F10 fundamentals — financial metrics + company facts.

Eastmoney exposes F10 (the 'Form 10' equivalent — Chinese listed-company
profile pages) as a series of JSON endpoints under emweb.securities.
eastmoney.com. No auth, no API key. Endpoints occasionally change names;
when this module starts returning empty data, check the latest URLs in
the reference repo (simonlin1212/a-stock-data) README.

Fields mapped to our project-native FinancialMetrics use ratios as
fractions (0.25 = 25%) per the existing convention.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from v2.data.models import CompanyFacts, FinancialMetrics

logger = logging.getLogger(__name__)

_FIN_INDICATORS_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
    "reportName=RPT_LICO_FN_CPD&columns=ALL"
    "&filter=(SECURITY_CODE=\"{code}\")"
    "&pageNumber=1&pageSize={page_size}"
    "&sortColumns=REPORT_DATE&sortTypes=-1"
)

_F10_PROFILE_URL = (
    "https://emweb.securities.eastmoney.com/PC_HSF10/CompanyInfo/"
    "PageAjaxJBZL?code={pre_code}"
)


def _code_only(canonical: str) -> str:
    return canonical.split('.', 1)[0]


def _pre_code(canonical: str) -> str:
    """Eastmoney expects e.g. 'SH600519' for the profile endpoint."""
    code, exch = canonical.split('.', 1)
    return f"{exch.upper()}{code}"


def _pct_to_frac(v: Any) -> float | None:
    """Eastmoney returns percentages as numbers (25.6 = 25.6%). Convert
    to fraction (0.256). None passes through; non-numeric → None."""
    if v is None:
        return None
    try:
        return float(v) / 100.0
    except (TypeError, ValueError):
        return None


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_financial_metrics(
    canonical_ticker: str,
    end_date: str,
    *,
    period: str = "ttm",
    limit: int = 10,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[FinancialMetrics]:
    """Fetch recent quarterly FinancialMetrics from Eastmoney F10.

    `period` is accepted for protocol parity but Eastmoney only ships
    quarterly snapshots. Caller picks the latest `limit` quarters.
    """
    sess = session or requests.Session()
    url = _FIN_INDICATORS_URL.format(
        code=_code_only(canonical_ticker), page_size=max(limit, 1),
    )
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    rows = (payload.get("result") or {}).get("data") or []
    if not rows:
        return []

    out: list[FinancialMetrics] = []
    for row in rows[:limit]:
        out.append(FinancialMetrics(
            ticker=canonical_ticker,
            report_period=row.get("REPORT_DATE", "").split(" ")[0],
            period=period,
            currency="CNY",
            earnings_per_share=_f(row.get("BASIC_EPS")),
            revenue=_f(row.get("TOTAL_OPERATE_INCOME")),
            net_income=_f(row.get("NETPROFIT")),
            return_on_equity=_pct_to_frac(row.get("ROE_AVG")),
            gross_margin=_pct_to_frac(row.get("GROSSPROFIT_MARGIN")),
            debt_to_assets=_pct_to_frac(row.get("DEBT_ASSET_RATIO")),
            # The rest of FinancialMetrics's ~50 fields stay None — v2
            # mapping work picks them up as Eastmoney coverage allows.
        ))
    return out


def fetch_company_facts(
    canonical_ticker: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> CompanyFacts | None:
    """Fetch sector / industry / name from Eastmoney F10 'JBZL'
    (基本资料 — basic info) page."""
    sess = session or requests.Session()
    url = _F10_PROFILE_URL.format(pre_code=_pre_code(canonical_ticker))
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    jbzl = payload.get("jbzl")
    if not jbzl:
        return None
    return CompanyFacts(
        ticker=canonical_ticker,
        name=jbzl.get("SECURITY_NAME_ABBR"),
        sector=jbzl.get("SECTOR_NAME"),
        industry=jbzl.get("INDUSTRYNAME"),
        cik=None,
        market_cap=None,  # fetched separately via market_cap module
        employee_count=int(jbzl["EMP_NUM"]) if jbzl.get("EMP_NUM") else None,
    )
```

- [ ] **Step 4: Run, all pass**

- [ ] **Step 5: Commit**

```bash
git add v2/data/ashare/eastmoney_fundamentals.py \
        tests/v2/data/ashare/test_eastmoney_fundamentals.py
git commit -m "$(cat <<'EOF'
feat(ashare): Eastmoney F10 fundamentals + company facts

fetch_financial_metrics pulls quarterly ROE/margin/debt/EPS from
emweb financial-indicators endpoint. fetch_company_facts grabs
sector/industry/name from F10 JBZL profile page. Percent-to-fraction
conversion (25.6 -> 0.256) follows project convention. ~50 unmapped
FinancialMetrics fields stay None for v1; v2 picks them up as
Eastmoney coverage expands.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Eastmoney earnings history (Wave 2B-2)

**Files:**
- Create: `v2/data/ashare/eastmoney_earnings.py`
- Create: `tests/v2/data/ashare/test_eastmoney_earnings.py`

- [ ] **Step 1: Failing test**

```python
"""Phase 8: Eastmoney quarterly earnings history (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.ashare.eastmoney_earnings import fetch_earnings_history


def _mock_session(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_parses_quarterly_earnings():
    # Eastmoney earnings preview/actual endpoint shape:
    # {"result": {"data": [
    #   {"REPORT_DATE": "2024-12-31", "BASIC_EPS": 60.5,
    #    "DEDUCT_BASIC_EPS": 59.8, "TOTAL_OPERATE_INCOME": 1.7e11,
    #    "NETPROFIT": 8.6e10, "YOY_NETPROFIT": 18.5}, ...]}}
    payload = {
        "result": {
            "data": [
                {
                    "REPORT_DATE": "2024-12-31",
                    "BASIC_EPS": 60.5,
                    "TOTAL_OPERATE_INCOME": 1.7e11,
                    "NETPROFIT": 8.6e10,
                    "YOY_NETPROFIT": 18.5,
                },
                {
                    "REPORT_DATE": "2024-09-30",
                    "BASIC_EPS": 50.12,
                    "TOTAL_OPERATE_INCOME": 1.2e11,
                    "NETPROFIT": 4.5e10,
                    "YOY_NETPROFIT": 15.2,
                },
            ]
        }
    }
    sess = _mock_session(payload)
    records = fetch_earnings_history("600519.SH", limit=4, session=sess)
    assert len(records) == 2
    assert records[0].report_period == "2024-12-31"
    assert records[0].eps == 60.5
    assert records[0].revenue == 1.7e11


def test_returns_empty_on_empty():
    sess = _mock_session({"result": {"data": []}})
    assert fetch_earnings_history("600519.SH", session=sess) == []
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`v2/data/ashare/eastmoney_earnings.py`:

```python
"""Eastmoney quarterly earnings history for A-shares.

Reuses the same financial-indicators endpoint as fundamentals but
parses through the EarningsRecord shape (flat per-period). The actual
SOP analyze pipeline cares about period-level EPS + revenue + YoY,
which all live in REPORT_DATE / BASIC_EPS / TOTAL_OPERATE_INCOME /
NETPROFIT / YOY_NETPROFIT.
"""

from __future__ import annotations

from typing import Any

import requests

from v2.data.models import EarningsRecord

_URL = (
    "https://datacenter-web.eastmoney.com/api/data/v1/get?"
    "reportName=RPT_LICO_FN_CPD&columns=ALL"
    "&filter=(SECURITY_CODE=\"{code}\")"
    "&pageNumber=1&pageSize={page_size}"
    "&sortColumns=REPORT_DATE&sortTypes=-1"
)


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_earnings_history(
    canonical_ticker: str,
    *,
    limit: int = 12,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[EarningsRecord]:
    sess = session or requests.Session()
    code = canonical_ticker.split('.', 1)[0]
    url = _URL.format(code=code, page_size=max(limit, 1))
    resp = sess.get(url, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    rows = (payload.get("result") or {}).get("data") or []
    out: list[EarningsRecord] = []
    for row in rows[:limit]:
        out.append(EarningsRecord(
            ticker=canonical_ticker,
            report_period=row.get("REPORT_DATE", "").split(" ")[0],
            fiscal_period="quarterly",
            currency="CNY",
            eps=_f(row.get("BASIC_EPS")),
            revenue=_f(row.get("TOTAL_OPERATE_INCOME")),
            net_income=_f(row.get("NETPROFIT")),
            source_type="eastmoney_f10",
        ))
    return out
```

(Note: if `EarningsRecord` doesn't have all these fields, drop the unsupported ones — open the dataclass file and check.)

- [ ] **Step 4: Run, all pass**

- [ ] **Step 5: Commit**

```bash
git add v2/data/ashare/eastmoney_earnings.py \
        tests/v2/data/ashare/test_eastmoney_earnings.py
git commit -m "feat(ashare): Eastmoney earnings history parser

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Eastmoney market_cap (Wave 2B-3)

**Files:**
- Create: `v2/data/ashare/eastmoney_market_cap.py`
- Create: `tests/v2/data/ashare/test_eastmoney_market_cap.py`

- [ ] **Step 1: Failing test**

```python
"""Phase 8: market cap fetcher (Tencent quote endpoint, mocked)."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.ashare.eastmoney_market_cap import fetch_market_cap


def test_parses_market_cap():
    # Tencent quote endpoint returns plain-text v_sz000001="50~ping_an_bank~000001~..."
    # Field 45 is total market cap in 亿元 (100m). We convert to RMB.
    txt = 'v_sh600519="1~贵州茅台~600519~1700.00~1690.00~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~21354.00~21354.00~~~~~~~~~~~~~"'
    resp = MagicMock()
    resp.status_code = 200
    resp.text = txt
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp

    cap = fetch_market_cap("600519.SH", "2026-05-26", session=sess)
    # 21354.00 亿元 == 21354 * 100_000_000 RMB
    assert cap == 21354.00 * 100_000_000


def test_returns_none_on_unparseable():
    resp = MagicMock()
    resp.status_code = 200
    resp.text = "garbage"
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    assert fetch_market_cap("600519.SH", "2026-05-26", session=sess) is None
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`v2/data/ashare/eastmoney_market_cap.py`:

```python
"""A-share market cap via Tencent's qt.gtimg.cn snapshot endpoint.

Returns total market cap in RMB (not 万元 or 亿元). end_date arg is
accepted for protocol parity but Tencent's endpoint serves real-time
only — caller gets 'current' market cap, not historical-at-date.
For SOP analyze on the latest scan_date this is fine.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

_URL = "https://qt.gtimg.cn/q={pre_code}"


def _pre_code(canonical: str) -> str:
    code, exch = canonical.split('.', 1)
    return f"{exch.lower()}{code}"


def fetch_market_cap(
    canonical_ticker: str,
    end_date: str,
    *,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> float | None:
    sess = session or requests.Session()
    resp = sess.get(_URL.format(pre_code=_pre_code(canonical_ticker)), timeout=timeout)
    resp.raise_for_status()
    # Format: v_sh600519="1~name~code~...~CAP_YI~..."
    txt = resp.text
    if '="' not in txt:
        return None
    body = txt.split('="', 1)[1].rstrip('";\n ')
    fields = body.split('~')
    # Field 45 (0-indexed) is total market cap in 亿元. Index can drift
    # between Tencent revisions — check len() and validate numeric.
    if len(fields) < 46:
        return None
    try:
        cap_yi = float(fields[45])
    except ValueError:
        return None
    if cap_yi <= 0:
        return None
    return cap_yi * 100_000_000  # 1 亿 = 100,000,000
```

- [ ] **Step 4-5: Test + commit (as previous)**

---

## Task 8: 财联社 news (Wave 2C-1)

**Files:**
- Create: `v2/data/ashare/cls_news.py`
- Create: `tests/v2/data/ashare/test_cls_news.py`

- [ ] **Step 1: Failing test**

```python
"""Phase 8: 财联社 (cls.cn) news fetcher (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.ashare.cls_news import fetch_stock_news


def _mock(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


def test_parses_news_list():
    payload = {
        "data": {
            "depth_list": [
                {
                    "id": 100,
                    "title": "贵州茅台2024年净利润同比增长15%",
                    "brief": "...",
                    "ctime": 1716700000,
                    "share_url": "https://www.cls.cn/detail/100",
                    "subjects": [{"subject_name": "白酒"}],
                },
                {
                    "id": 101,
                    "title": "茅台股东大会通过分红方案",
                    "ctime": 1716800000,
                    "share_url": "https://www.cls.cn/detail/101",
                    "subjects": [],
                },
            ]
        }
    }
    sess = _mock(payload)
    news = fetch_stock_news("600519.SH", "2026-05-26", limit=20, session=sess)
    assert len(news) == 2
    assert news[0].title.startswith("贵州茅台")
    assert news[0].source == "财联社"
    assert news[0].url == "https://www.cls.cn/detail/100"


def test_empty_on_no_data():
    sess = _mock({"data": {"depth_list": []}})
    assert fetch_stock_news("600519.SH", "2026-05-26", session=sess) == []
```

- [ ] **Step 2: Implement**

`v2/data/ashare/cls_news.py`:

```python
"""财联社 (Caixinglian / CLS) per-stock news scraper.

CLS exposes a depth-feed endpoint at www.cls.cn/v3/cms that returns
per-stock news in JSON. No auth, no API key. Per the spec, A-share
news is capped at 50 articles per fetch (vs 200 for US) to keep SOP
section prompts under token budget.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests

from v2.data.models import CompanyNews

_URL = "https://www.cls.cn/v3/cms/article/depth-list/v1?app=CailianpressWeb"


def _code_only(canonical: str) -> str:
    return canonical.split('.', 1)[0]


def fetch_stock_news(
    canonical_ticker: str,
    end_date: str,
    *,
    start_date: str | None = None,
    limit: int = 50,
    session: requests.Session | None = None,
    timeout: float = 10.0,
) -> list[CompanyNews]:
    sess = session or requests.Session()
    params = {
        "secu_code": f"{canonical_ticker.split('.', 1)[1].lower()}{_code_only(canonical_ticker)}",
        "rn": min(limit, 50),
    }
    resp = sess.get(_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    payload = resp.json()
    rows = ((payload.get("data") or {}).get("depth_list")) or []
    if not rows:
        return []

    end_ts = datetime.fromisoformat(end_date).timestamp()
    start_ts = (
        datetime.fromisoformat(start_date).timestamp() if start_date else 0
    )

    out: list[CompanyNews] = []
    for row in rows[:limit]:
        ctime = row.get("ctime") or 0
        if not (start_ts <= ctime <= end_ts + 86400):  # +1d slack
            continue
        out.append(CompanyNews(
            ticker=canonical_ticker,
            title=row.get("title", ""),
            source="财联社",
            date=datetime.fromtimestamp(ctime).strftime("%Y-%m-%d"),
            url=row.get("share_url", ""),
            sentiment=None,        # CLS doesn't ship sentiment
            sentiment_score=None,
        ))
    return out
```

- [ ] **Step 3-5: Run + commit**

---

## Task 9: SW1 sector → index code mapper (Wave 2C-2)

**Files:**
- Create: `v2/data/ashare/sw_sector_map.py`
- Create: `tests/v2/data/ashare/test_sw_sector_map.py`

- [ ] **Step 1: Failing test**

```python
"""Phase 8: 申万一级 (SW1) sector name -> index code mapping."""
from v2.data.ashare.sw_sector_map import sw1_index_code, SW1_SECTORS


def test_maps_known_sector():
    # 食品饮料 -> SW1 food & beverage index
    assert sw1_index_code("食品饮料") == "801120.SH"


def test_returns_none_for_unknown():
    assert sw1_index_code("not a sector") is None


def test_registry_has_31_sectors():
    # SW1 has 31 first-level sectors as of 2024
    assert len(SW1_SECTORS) == 31
```

- [ ] **Step 2: Implement**

`v2/data/ashare/sw_sector_map.py`:

```python
"""申万一级 (SW1) sector index codes — used as A-share sector ETF
benchmarks in the SOP analyze pipeline.

A-share doesn't have liquid sector ETFs in the SPDR sense. SW1 indices
are the standard reference — published by 申银万国 since 1999. 31
first-level sectors as of 2024 reclassification.

We map Eastmoney's SECTOR_NAME strings (returned by F10 JBZL) to SW1
index ticker codes. Loaders can then call get_prices() on the index
ticker just like SPY for US flow.
"""

from __future__ import annotations

SW1_SECTORS: dict[str, str] = {
    "农林牧渔": "801010.SH",
    "采掘": "801020.SH",
    "化工": "801030.SH",
    "钢铁": "801040.SH",
    "有色金属": "801050.SH",
    "电子": "801080.SH",
    "家用电器": "801110.SH",
    "食品饮料": "801120.SH",
    "纺织服装": "801130.SH",
    "轻工制造": "801140.SH",
    "医药生物": "801150.SH",
    "公用事业": "801160.SH",
    "交通运输": "801170.SH",
    "房地产": "801180.SH",
    "商业贸易": "801200.SH",
    "休闲服务": "801210.SH",
    "综合": "801230.SH",
    "建筑材料": "801710.SH",
    "建筑装饰": "801720.SH",
    "电气设备": "801730.SH",
    "国防军工": "801740.SH",
    "计算机": "801750.SH",
    "传媒": "801760.SH",
    "通信": "801770.SH",
    "银行": "801780.SH",
    "非银金融": "801790.SH",
    "汽车": "801880.SH",
    "机械设备": "801890.SH",
    "煤炭": "801950.SH",
    "石油石化": "801960.SH",
    "环保": "801970.SH",
}


def sw1_index_code(sector_name: str) -> str | None:
    """Map an Eastmoney F10 SECTOR_NAME to a SW1 index code.
    Returns None for unknown sector. Case-sensitive (Chinese chars)."""
    return SW1_SECTORS.get(sector_name.strip()) if sector_name else None
```

- [ ] **Step 3-5: Run + commit**

---

## Task 10: AShareClient full integration test (Wave 3)

**Files:**
- Modify: `tests/v2/data/ashare/test_client_protocol.py` (extend with smoke tests)

- [ ] **Step 1: Add tests that exercise the full Wave 2 surface (mocked at the helper level)**

Append to `test_client_protocol.py`:

```python
from unittest.mock import patch
from v2.data.models import Price, CompanyFacts


@patch("v2.data.ashare.mootdx_prices.fetch_daily_ohlcv")
def test_get_prices_delegates(mock_fetch):
    mock_fetch.return_value = [
        Price(open=1, high=1, low=1, close=1, volume=1, time="2025-01-02", adjusted_close=1),
    ]
    c = AShareClient()
    prices = c.get_prices("600519", "2025-01-01", "2025-12-31")
    assert len(prices) == 1
    # Confirms canonical normalization happened before delegation
    mock_fetch.assert_called_once_with("600519.SH", "2025-01-01", "2025-12-31")


@patch("v2.data.ashare.eastmoney_fundamentals.fetch_company_facts")
def test_get_company_facts_delegates(mock_fetch):
    mock_fetch.return_value = CompanyFacts(
        ticker="600519.SH", name="贵州茅台",
        sector="食品饮料", industry="白酒",
        cik=None, market_cap=None, employee_count=30000,
    )
    c = AShareClient()
    facts = c.get_company_facts("sh600519")
    assert facts is not None
    assert facts.name == "贵州茅台"


def test_us_ticker_returns_empty():
    c = AShareClient()
    assert c.get_prices("NVDA", "2025-01-01", "2025-12-31") == []
    assert c.get_company_facts("AAPL") is None
    assert c.get_market_cap("NVDA", "2025-12-31") is None
```

- [ ] **Step 2-3: Run, fix any wiring**

- [ ] **Step 4-5: Commit**

---

## Task 11: 5 A-share universe CSVs (Wave 3)

**Files:**
- Create: `v2/scanner/universes/data/sse50.csv`
- Create: `v2/scanner/universes/data/csi300.csv`
- Create: `v2/scanner/universes/data/csi500.csv`
- Create: `v2/scanner/universes/data/csi1000.csv`
- Create: `v2/scanner/universes/data/hs300_ext.csv`
- Create: `v2/scanner/universes/refresh_ashare_universes.py`
- Modify: `v2/scanner/universes/loader.py`

- [ ] **Step 1: Build the refresh script and run it once**

`v2/scanner/universes/refresh_ashare_universes.py`:

```python
"""One-off snapshot script: fetch SSE 50 / CSI 300 / CSI 500 / CSI 1000
constituents from Eastmoney and write CSVs alongside the US universes.

Run manually when you want to refresh; not invoked by the running app.
"""

from __future__ import annotations

import csv
from pathlib import Path

import requests

_BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"

_INDEX_CODES = {
    "sse50":   "000016",
    "csi300":  "000300",
    "csi500":  "000905",
    "csi1000": "000852",
}

_HERE = Path(__file__).parent / "data"


def fetch(index_code: str) -> list[tuple[str, str, str]]:
    """Return [(ticker_canonical, name, sector)] for an index's constituents."""
    out: list[tuple[str, str, str]] = []
    page = 1
    while True:
        params = {
            "reportName": "RPT_INDEX_TS_COMPONENT",
            "columns": "ALL",
            "filter": f'(TYPE="2")(BASE_CODE="{index_code}")',
            "pageNumber": page,
            "pageSize": 500,
            "sortColumns": "WEIGHT",
            "sortTypes": "-1",
        }
        r = requests.get(_BASE, params=params, timeout=15)
        r.raise_for_status()
        data = (r.json().get("result") or {}).get("data") or []
        if not data:
            break
        for row in data:
            code = row.get("SECURITY_CODE", "").strip()
            exch_raw = row.get("MARKET", "").strip().upper()
            exch = "SH" if exch_raw in ("SH", "SHA", "1") else "SZ"
            name = row.get("SECURITY_NAME_ABBR", "")
            sector = row.get("INDUSTRY", "")
            if code:
                out.append((f"{code}.{exch}", name, sector))
        if len(data) < 500:
            break
        page += 1
    return out


def write_csv(name: str, rows: list[tuple[str, str, str]]) -> None:
    _HERE.mkdir(parents=True, exist_ok=True)
    p = _HERE / f"{name}.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "name", "sector"])
        w.writerows(rows)
    print(f"wrote {p} ({len(rows)} rows)")


def main():
    snapshots = {}
    for name, code in _INDEX_CODES.items():
        snapshots[name] = fetch(code)
        write_csv(name, snapshots[name])
    # Composite hs300_ext = csi300 + csi500 (union, dedup by ticker)
    seen = set()
    ext = []
    for row in snapshots["csi300"] + snapshots["csi500"]:
        if row[0] not in seen:
            ext.append(row)
            seen.add(row[0])
    write_csv("hs300_ext", ext)


if __name__ == "__main__":
    main()
```

Run it:

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe v2/scanner/universes/refresh_ashare_universes.py
```

Expected output: 5 CSV files written. ~50 / ~300 / ~500 / ~1000 / ~800 rows.

If the script fails (Eastmoney endpoint moved, etc.), commit the script anyway and create empty CSV stubs with just headers so loader can read them; document the failure in the smoke step.

- [ ] **Step 2: Loader extension**

Modify `v2/scanner/universes/loader.py` to recognize the 5 new kinds. The exact change depends on the loader's current shape — open the file and find the dispatch (likely a dict / switch on `kind`). Add 5 entries that map kind names to the new CSV files in `data/`.

- [ ] **Step 3: Test the loader**

`tests/v2/scanner/test_universes_ashare.py`:

```python
"""Phase 8: A-share universe loader extension."""
from __future__ import annotations

import pytest
from v2.scanner.universes.loader import load_universe


@pytest.mark.parametrize("kind", ["sse50", "csi300", "csi500", "csi1000", "hs300_ext"])
def test_loads_nonempty(kind):
    tickers = load_universe(kind)
    assert isinstance(tickers, list)
    assert len(tickers) > 0
    # All tickers should be A-share canonical
    from v2.data.ashare.symbol import is_ashare
    for t in tickers[:10]:
        assert is_ashare(t), f"expected A-share canonical: {t}"
```

- [ ] **Step 4-5: Run + commit**

---

## Task 12: CompositeClient symbol-aware routing (Wave 4)

**Files:**
- Modify: `v2/data/composite_client.py`
- Modify: `v2/data/factory.py`
- Create: `tests/v2/data/test_composite_ashare_routing.py`

- [ ] **Step 1: Failing test**

```python
"""Phase 8: CompositeClient dispatches A-share tickers to ashare_backend."""
from __future__ import annotations

from unittest.mock import MagicMock
from v2.data.composite_client import CompositeClient
from v2.data.models import Price


def test_a_share_ticker_routes_to_ashare_backend():
    ashare = MagicMock()
    ashare.get_prices.return_value = [
        Price(open=1, high=1, low=1, close=1, volume=1, time="2025-01-02", adjusted_close=1)
    ]
    us = MagicMock()
    us.get_prices.return_value = []

    c = CompositeClient(prices_backend=us, ashare_backend=ashare)
    out = c.get_prices("600519.SH", "2025-01-01", "2025-12-31")

    assert len(out) == 1
    ashare.get_prices.assert_called_once()
    us.get_prices.assert_not_called()


def test_us_ticker_routes_to_us_backend():
    ashare = MagicMock()
    us = MagicMock()
    us.get_prices.return_value = []

    c = CompositeClient(prices_backend=us, ashare_backend=ashare)
    c.get_prices("NVDA", "2025-01-01", "2025-12-31")

    us.get_prices.assert_called_once()
    ashare.get_prices.assert_not_called()


def test_no_ashare_backend_falls_back_to_us():
    """If ashare_backend is None, even A-share tickers go through US
    backend (which will return empty)."""
    us = MagicMock()
    us.get_prices.return_value = []
    c = CompositeClient(prices_backend=us, ashare_backend=None)
    c.get_prices("600519.SH", "2025-01-01", "2025-12-31")
    us.get_prices.assert_called_once()
```

- [ ] **Step 2: Implement**

In `v2/data/composite_client.py`:
1. Add `ashare_backend: DataClient | None = None` to `__init__`.
2. Add module-level helper `_is_ashare(ticker)` re-exporting from `v2.data.ashare.symbol`.
3. Wrap each protocol method with a dispatcher that checks the ticker first arg:

```python
def get_prices(self, ticker, *args, **kwargs):
    if self.ashare_backend is not None and _is_ashare(ticker):
        return self.ashare_backend.get_prices(ticker, *args, **kwargs)
    return self.prices_backend.get_prices(ticker, *args, **kwargs)
```

Repeat for: `get_financial_metrics`, `get_news`, `get_insider_trades`, `get_company_facts`, `get_earnings_history`, `get_earnings`, `get_earnings_calendar`, `get_market_cap`. For methods where the first arg is NOT a ticker (e.g. `get_earnings_calendar(start_date, end_date)`), leave routing as-is.

- [ ] **Step 3: Factory update**

In `v2/data/factory.py`, find `make_hybrid_client(...)`. Add a kwarg `include_ashare: bool = True`. When True, construct an `AShareClient` and pass it as `ashare_backend`. When False or A-share extras aren't installed, leave `ashare_backend=None`.

```python
def make_hybrid_client(*, include_ashare: bool = True, ...) -> CompositeClient:
    # ... existing US backend construction ...
    ashare = None
    if include_ashare:
        try:
            from v2.data.ashare.client import AShareClient
            ashare = AShareClient()
        except ImportError:
            ashare = None  # extras not installed; degrade gracefully
    return CompositeClient(
        # ... existing backends ...
        ashare_backend=ashare,
    )
```

- [ ] **Step 4: Run all tests including this and pre-existing composite tests**

```powershell
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/v2/data/test_composite_ashare_routing.py tests/v2/data/test_composite_client.py -v
```

Pre-existing composite tests should still pass — `ashare_backend` defaults to None so existing constructor calls are unchanged.

- [ ] **Step 5: Commit**

---

## Task 13: AnalyzeRequest.market + benchmark/sector swap in shared_data (Wave 5)

**Files:**
- Modify: `src/research/models.py` — add `market: str = "us"` to `AnalyzeRequest`
- Modify: `app/backend/models/research_schemas.py` — mirror it on `AnalyzeRunRequest` as `Literal["us","cn"]`
- Modify: `app/backend/routes/research.py` — pass through
- Modify: `src/research/shared_data.py` — when `market == "cn"`, fetch 000300.SH instead of SPY; SW1 sector ETF instead of SPDR

- [ ] **Step 1: Failing test for shared_data benchmark swap**

`tests/research/test_shared_data_market.py`:

```python
"""Phase 8: shared_data uses 沪深300 + SW1 sector ETF for cn market."""
from unittest.mock import patch, MagicMock
from src.research.shared_data import fetch_shared_data
from src.research.models import AnalyzeRequest


@patch("src.research.shared_data._client")
def test_cn_market_uses_hs300_benchmark(mock_client_getter):
    client = MagicMock()
    client.get_prices.return_value = []
    client.get_financial_metrics.return_value = []
    client.get_company_facts.return_value = None
    client.get_news.return_value = []
    client.get_insider_trades.return_value = []
    client.get_earnings_history.return_value = []
    mock_client_getter.return_value = client

    shared = fetch_shared_data("600519.SH", "2026-05-26", market="cn")
    # Confirm 000300.SH was queried (some call somewhere in fetch_shared_data
    # asks the benchmark)
    benchmark_calls = [
        call for call in client.get_prices.call_args_list
        if call.args and "000300" in str(call.args[0])
    ]
    assert len(benchmark_calls) >= 1


@patch("src.research.shared_data._client")
def test_us_market_still_uses_spy(mock_client_getter):
    client = MagicMock()
    client.get_prices.return_value = []
    client.get_financial_metrics.return_value = []
    client.get_company_facts.return_value = None
    client.get_news.return_value = []
    client.get_insider_trades.return_value = []
    client.get_earnings_history.return_value = []
    mock_client_getter.return_value = client

    fetch_shared_data("NVDA", "2026-05-26")  # default market="us"
    spy_calls = [
        call for call in client.get_prices.call_args_list
        if call.args and call.args[0] == "SPY"
    ]
    assert len(spy_calls) >= 1
```

(Adjust the patch target depending on how shared_data actually gets its client — may need to patch `fetch_shared_data` differently. Read the file first.)

- [ ] **Step 2: Implementation**

- Add `market: str = "us"` to `AnalyzeRequest` dataclass.
- Mirror as `Literal["us", "cn"]` Pydantic field on `AnalyzeRunRequest`.
- Pass through in route handler.
- In `shared_data.py`:
  ```python
  def fetch_shared_data(ticker, scan_date, *, market: str = "us"):
      benchmark = "SPY" if market == "us" else "000300.SH"
      # ... use `benchmark` instead of hardcoded "SPY"
      # For sector_etf: look up facts.sector via sw_sector_map.sw1_index_code()
      # when market=="cn"
  ```

- [ ] **Step 3-5: Run + commit**

---

## Task 14: Frontend market selector + universe options (Wave 6)

**Files:**
- Modify: `app/frontend/src/types/analyze.ts` — add `Market = 'us' | 'cn'`, `market?: Market` on AnalyzeRunRequest
- Modify: `app/frontend/src/components/panels/analyze/input-node.tsx` — add market dropdown
- Modify: `app/frontend/src/components/panels/analyze/analyze-panel.tsx:handleRun` — pass market
- Modify: `app/frontend/src/types/scanner.ts` — add 5 universe options
- Modify: `app/frontend/src/types/strategy.ts` — add 5 to UniverseSpec.kind
- Modify: `app/frontend/src/i18n/locales/en.json` + `zh.json` — keys

- [ ] **Step 1: Locale keys**

Add to both `en.json` and `zh.json` under `scanner.universe`:
```json
"sse50":    "SSE 50 / 上证 50",
"csi300":   "CSI 300 / 沪深 300",
"csi500":   "CSI 500 / 中证 500",
"csi1000":  "CSI 1000 / 中证 1000",
"hs300_ext": "HS300 + CSI500 (union)"
```

And under `analyze.input`:
```json
"market": "Market"   // en
"market": "市场"      // zh
```

And under `analyze.markets`:
```json
"us": "US"           // en
"cn": "A股"           // zh
```

- [ ] **Step 2: Types + UI**

`types/analyze.ts`:
```ts
export type Market = 'us' | 'cn';
// On AnalyzeRunRequest add:
market?: Market;
```

`input-node.tsx`: add a Market dropdown immediately above the ticker field (so the user picks market first, then knows what ticker format to type):

```tsx
{/* Market */}
<div className="flex flex-col gap-1">
  <label className="text-xs uppercase text-muted-foreground tracking-wide">
    {t('analyze.input.market')}
  </label>
  <select
    value={d.market ?? 'us'}
    onChange={(e) => update({ market: e.target.value as Market })}
    className="nodrag h-9 px-2 text-sm border rounded bg-background"
  >
    <option value="us">{t('analyze.markets.us')}</option>
    <option value="cn">{t('analyze.markets.cn')}</option>
  </select>
</div>
```

And add `market: Market;` to `InputNodeData`, default to `'us'` in `DEFAULT_INPUT_NODE_DATA`.

In `analyze-panel.tsx:handleRun`, add `market: input.market ?? 'us',` to the POST payload.

- [ ] **Step 3: Universe options**

In `types/scanner.ts` find `UNIVERSE_KIND_OPTIONS` and append 5 entries:
```ts
{ value: 'sse50',    label: 'SSE 50',     description: '上证 50 mega-caps' },
{ value: 'csi300',   label: 'CSI 300',    description: '沪深 300 large-caps' },
{ value: 'csi500',   label: 'CSI 500',    description: '中证 500 mid-caps' },
{ value: 'csi1000',  label: 'CSI 1000',   description: '中证 1000 small-caps' },
{ value: 'hs300_ext', label: 'HS300+CSI500', description: '~800 A-share universe' },
```

Lab strategy spec: in `types/strategy.ts` find `UniverseSpec.kind` Literal/union and add the 5 strings.

- [ ] **Step 4: tsc check**

```powershell
cd app/frontend
npx tsc --noEmit 2>&1 | grep -iE "market|ashare|csi|sse" | head
```

Expected: 0 new errors.

- [ ] **Step 5: Commit**

---

## Task 15: Full pytest + live smoke + progress.md (Wave 7)

**Files:**
- Modify: `progress.md`

- [ ] **Step 1: Full backend pytest — confirm no regression**

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m pytest -q --tb=no 2>&1 | tail -15
```

Expected: All A-share tests green. Pre-existing v2/data live-API failures and the 1 known scanner_service test (earnings_event alias) remain — those are not Phase 8's job.

- [ ] **Step 2: Live data smoke (no API key needed, requires internet)**

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -c "
from v2.data.ashare.client import AShareClient
c = AShareClient()
prices = c.get_prices('600519', '2025-01-01', '2026-05-26')
print(f'600519 (Moutai): {len(prices)} bars')
if prices:
    print(f'  first: {prices[0].time} close={prices[0].close}')
    print(f'  last:  {prices[-1].time} close={prices[-1].close}')
facts = c.get_company_facts('600519.SH')
print(f'facts: {facts}')
metrics = c.get_financial_metrics('600519', '2026-05-26', limit=4)
print(f'metrics: {len(metrics)} quarters; latest EPS={metrics[0].earnings_per_share if metrics else None}')
"
```

Expected: ~300+ bars; Moutai close ~1500-1700 RMB; sector "食品饮料", industry "白酒"; 4 quarters of metrics.

If mootdx connection fails from your network (common outside China), document the failure and the AShareClient gracefully returns `[]` — the rest of the pipeline degrades to "n/a — data unavailable".

- [ ] **Step 3: Frontend tsc check**

```powershell
cd app/frontend
npx tsc --noEmit 2>&1 | tail -10
```

Expected: no new errors.

- [ ] **Step 4: progress.md session block**

Prepend to `progress.md` under `# Progress Log`:

```markdown
## Session — 2026-05-26/27 (Phase 8 landed — A-share data source)

### What shipped

- `AShareClient` (`v2/data/ashare/client.py`) implementing the existing
  `DataClient` Protocol — no protocol change. Backed by mootdx (daily
  OHLCV), Eastmoney F10 (fundamentals + earnings + market cap), and
  财联社 (per-stock news). No API keys required.
- Symbol normalization (`v2/data/ashare/symbol.py`) — accepts bare
  6-digit codes, .SH/.SZ/.BJ suffixed forms, SH./SZ./BJ. prefixed
  forms. Canonical form: '<code>.<exchange>'.
- `CompositeClient` gains symbol-aware dispatch: per-call check on
  ticker format routes A-share tickers to `ashare_backend`, US tickers
  to the existing prices/news/insider backends. Zero impact on
  existing US flows.
- 5 A-share universe CSVs (SSE 50, CSI 300/500/1000, HS300+CSI500
  union) snapshotted from Eastmoney; refresh script committed.
- 31-sector 申万一级 (SW1) index map for sector-benchmark lookup.
- SOP analyze pipeline: `AnalyzeRequest.market` field defaults "us";
  when "cn", benchmark swaps from SPY → 000300.SH and sector ETF
  uses SW1 instead of SPDR.
- Frontend: Input node gains Market dropdown (US / A股); Scanner +
  Lab universe options gain 5 A-share entries; i18n keys added.

### Commits

[fill in from `git log --oneline c3e7f9d2b8a4..HEAD --reverse`]

### Tests
- ~20 new backend tests under tests/v2/data/ashare/ — mocked HTTP
- Full pytest: no Phase 8 regressions; pre-existing v2/data live-API
  failures and the earnings_event alias test remain unchanged

### Live smoke
[fill in: how many bars Moutai returned; whether mootdx servers
reached from this machine; etc.]

### Notes for next session
- BSE (.BJ) tickers return [] for now (mootdx core doesn't yet
  support market=2; Eastmoney fallback is v2 work)
- Analyst data (target / actions / revisions) returns empty for
  A-share v1; SOP sections gracefully emit "n/a"
- Insider trades return empty for A-share v1 (filing format differs
  from US 13F)
- Universe CSVs are snapshots — re-run refresh_ashare_universes.py
  semi-annually to track CSI rebalances
```

- [ ] **Step 5: Final commit**

```bash
git add progress.md
git commit -m "$(cat <<'EOF'
docs: progress.md — Phase 8 A-share data integration landing

15 tasks; AShareClient + Eastmoney/mootdx/CLS helpers + composite
routing + universes + SOP integration + frontend market selector.
All additive; no Phase 1-7 regressions.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review

**Spec coverage:**
- AShareClient implements Protocol (no Protocol change) → Tasks 3, 10 ✓
- Symbol normalization with prefix inference → Task 2 ✓
- mootdx prices → Task 4 ✓
- Eastmoney fundamentals + earnings + market_cap → Tasks 5, 6, 7 ✓
- CLS news → Task 8 ✓
- SW1 sector mapper → Task 9 ✓
- 5 universe CSVs + loader extension → Task 11 ✓
- CompositeClient symbol-aware routing + factory → Task 12 ✓
- AnalyzeRequest.market + shared_data benchmark/sector swap → Task 13 ✓
- Frontend market selector + 5 universe options + i18n → Task 14 ✓
- Smoke + progress.md → Task 15 ✓

**Placeholder scan:** none. All code blocks are concrete and would compile/run as written modulo the noted "open the file and adjust" caveats for two integration points (loader.py dispatch shape; shared_data._client patching pattern). Those are flagged inline.

**Type consistency:**
- `Price`, `FinancialMetrics`, `CompanyNews`, `CompanyFacts`, `EarningsRecord` all imported from `v2.data.models` (existing types) — no new model classes.
- Canonical ticker format `<code>.<exchange>` used consistently across symbol.py / client.py / universes / composite routing.
- `market: str` on `AnalyzeRequest`, `Literal["us","cn"]` on Pydantic schema, `Market = 'us' | 'cn'` on TS — all aligned.

**Risks acknowledged:**
- mootdx server unreachability outside China — caught & returns []
- Eastmoney HTML/JSON field renames — per-field try/except, partial data OK
- BSE coverage gap — documented, v2
- News volume token limit — `max_news_per_call=50` default

**Subagent dispatch notes for the parent agent:**
- Waves 2A/2B/2C touch only their own files (`mootdx_prices.py`, `eastmoney_*.py`, `cls_news.py`) — fully parallel-safe
- Wave 3 has a sequential dep (CSVs must exist before loader tests can pass) — single agent
- Wave 4 modifies shared `composite_client.py` + `factory.py` — single agent
- Wave 5 modifies the SOP pipeline + DB-schema-adjacent files — single agent for safety
- Wave 6 frontend is independent of Waves 3-5 — could fork off after Wave 4, but for simplicity single agent after Wave 5
- Wave 7 needs everything green — sequential
