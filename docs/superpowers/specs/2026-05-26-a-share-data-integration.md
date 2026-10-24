# Phase 8 — A-Share (China Stock) Data Integration

**Spec date:** 2026-05-26
**Reference:** [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data) (Apache 2.0, v3.1.0)

## Context

The ai-hedge-fund pipeline today only ingests US equities (NYSE / NASDAQ / AMEX) via three providers: EODHD (prices + news), Finnhub (insider + earnings), Yahoo Finance (analyst). The user works the US session at home but lives in Asia; they want the same SOP analyze + scanner + lab tooling to work on A-shares (Shanghai SSE + Shenzhen SZSE + Beijing BSE + STAR Board + ChiNext).

The chosen data source is `simonlin1212/a-stock-data` — a Claude Code Skill (not a pip package) that documents how to call 13 free A-share HTTP APIs (mootdx, Eastmoney, Tencent Finance, Sina, 财联社, 巨潮, 同花顺, Baidu, Iwencai). It is **prompt + code recipe form** — we will write our own `AShareClient` Python class that implements the `DataClient` Protocol, using the SKILL.md recipes as reference. License compatible (Apache 2.0).

## Approach

Three architecture pillars:

1. **`AShareClient` implements the existing `DataClient` Protocol** in `v2/data/ashare/`. No protocol change. Single class with `requests.Session` per worker thread, returns project-native typed models (`Price`, `FinancialMetrics`, etc.). Backed by `mootdx` for OHLCV + raw HTTP calls for fundamentals / news.
2. **Symbol-based composite routing** — extend `CompositeClient` with a per-method symbol dispatch: `_is_ashare(ticker)` returns True for 6-digit codes ± `.SH/.SZ/.BJ` suffixes; routes to AShareClient. US-format tickers continue to route through the existing hybrid (EODHD/Finnhub/yfinance).
3. **Universe + benchmark + sector mapping extensions** — `csi300 / csi500 / csi1000 / sse50 / hs300_ext` universe CSVs; A-share benchmark = 沪深300 (000300.SH) instead of SPY; sector ETFs swap to 申万一级 (SW1) ETF proxies.

The SOP analyze pipeline and Lab backtest engine work **as-is** once the data layer + composite routing handle A-share tickers — they consume typed models, not raw API responses.

## Scope per design decisions

I made the following decisions autonomously because the user is asleep. Each has a one-line rationale; reverse any in the morning if you disagree.

### Decision 1: scope of data fields covered in v1

**In:**
- `get_prices` (daily OHLCV) — mootdx
- `get_financial_metrics` (37-field quarterly) — Eastmoney F10
- `get_news` (per-stock + flash) — 财联社 CLS
- `get_company_facts` (sector / industry / name) — Eastmoney F10
- `get_earnings_history` (quarterly reports) — Eastmoney
- `get_market_cap` (TTM) — Tencent quote

**Out (v2):**
- `get_insider_trades` — China filings format differs significantly from US 13F; punt to v2
- `get_analyst_targets` / `get_analyst_actions` — Eastmoney has consensus data but parser is fragile; punt to v2
- `get_estimate_revisions` — same
- `get_earnings_calendar` (universe-wide) — punt to v2
- Level-2 / tick / order book — only useful for HFT, not SOP

**Why:** v1 should make SOP analyze + scanner + Lab backtest work end-to-end on A-shares. Analyst sub-protocol is optional in the existing pipeline (`AnalystDataClient` is a separate Protocol). v1 ships without it; sections that depend on analyst data emit "n/a" gracefully (existing fallback).

### Decision 2: symbol convention

**Canonical internal format:** `<6-digit-code>.<exchange>` where exchange ∈ `SH | SZ | BJ`.
- `600519` → `600519.SH` (Kweichow Moutai, SSE)
- `000001` → `000001.SZ` (Ping An Bank, SZSE)
- `300750` → `300750.SZ` (CATL, ChiNext)
- `688981` → `688981.SH` (SMIC, STAR)
- `830799` → `830799.BJ` (BSE)

**Exchange inference from prefix:**
- `60xxxx`, `68xxxx`, `90xxxx` → SH
- `00xxxx`, `30xxxx`, `20xxxx` → SZ
- `4xxxxx`, `8xxxxx`, `92xxxx` → BJ

**User-facing input:** accept all forms (`600519`, `600519.SH`, `sh.600519`, `SH600519`). The AShareClient internally normalizes.

**Conflict with US tickers:** none — US tickers are alphabetic; A-share are 6 digits. The `_is_ashare(ticker)` regex is `^[0-9]{6}(\.(SH|SZ|BJ))?$|^(sh|sz|bj)\.?[0-9]{6}$`.

### Decision 3: composite client extension

Add a new constructor slot to `CompositeClient`: `ashare_backend: DataClient | None = None`. When a method is called with an A-share ticker AND `ashare_backend is not None`, dispatch to `ashare_backend`; otherwise fall through to the existing per-method backend.

This is a **per-call symbol-aware dispatcher** layered on top of the existing per-method-slot architecture. Existing US flows are unchanged.

`make_hybrid_client(include_ashare=True)` becomes the new default factory; A-share users get it free, US-only users opt out via `include_ashare=False` (or just don't pass A-share tickers).

### Decision 4: universes

Bundle 5 new universe CSVs under `v2/scanner/universes/data/`:
- `csi300.csv` — 沪深300 (~300 large caps)
- `csi500.csv` — 中证500 (~500 mid caps)
- `csi1000.csv` — 中证1000 (~1000 small caps)
- `sse50.csv` — 上证50 (~50 mega caps)
- `hs300_ext.csv` — 沪深300 + 中证500 union (~800)

Snapshot script: `v2/scanner/universes/refresh_ashare_universes.py` fetches the constituent lists from Eastmoney once and writes CSVs (run by hand, like the existing US universes script).

Loader (`v2/scanner/universes/loader.py`) extends to recognize these names — no symbol-format branching needed because all 5 CSVs ship A-share codes in canonical form.

### Decision 5: benchmark + sector

**Benchmark:** when `request.market == "cn"` (new field, default "us"), `shared_data` fetches 000300.SH ("hs300") as the benchmark series instead of SPY. Lab backtest's benchmark config already supports a string identifier — add `benchmark: "hs300"` enum value.

**Sector ETFs:** A-share doesn't have liquid sector ETFs in the SPDR sense. Use 申万一级 (SW1) sector indices via Eastmoney:
- Banks: 801780.SH
- Tech: 801770.SH (通信 SW1)
- Healthcare: 801150.SH (医药生物 SW1)
- ... 31 SW1 sectors total

`SectorEtfMapper` (new helper) returns the SW1 index code for a given A-share ticker's sector. Falls back to "no sector data" if Eastmoney doesn't return a sector.

### Decision 6: SOP report content for A-shares

When `report_language="zh"` and ticker is A-share, the LLM is naturally most fluent. No additional prompt changes needed — the existing Phase 7 i18n `language_instruction("zh")` covers it.

When `report_language="en"` and ticker is A-share, the LLM translates company name + sector to English in narrative but keeps the ticker as `600519.SH`. Acceptable v1 behavior.

### Decision 7: frontend

Minimal changes — most surfaces already accept arbitrary tickers:
- **Scanner config dialog:** universe dropdown gains 5 new options (CSI 300 / CSI 500 / CSI 1000 / SSE 50 / 沪深 + 中证). Translations in `scanner.universe.*`.
- **Lab strategy spec:** `universe.kind` enum adds same 5 options.
- **Watchlist:** accept A-share tickers; ticker autocomplete remains US-only for now (free Eastmoney search planned for v2).
- **InputNode (Analyze):** accept A-share tickers; ticker uppercase logic stays (no harm — A-share codes are digits, uppercase is no-op).

### Decision 8: dependencies

Add to `pyproject.toml` under `[tool.poetry.dependencies]`:
- `mootdx = "^2.1.6"` — pure Python TDX market data client
- `stockstats = "^0.6.2"` — TA indicators on pandas DataFrame (optional; we already have indicator code, but stockstats's `KDJ` etc. may simplify some signals)

Or under `[project.optional-dependencies]` as `[ashare]` extra so US-only deployments don't pull mootdx. (Recommended.)

## Files

### New

```
v2/data/ashare/
├── __init__.py
├── client.py                        # AShareClient — main class implementing DataClient Protocol
├── symbol.py                        # is_ashare(), normalize(), infer_exchange()
├── mootdx_prices.py                 # OHLCV via mootdx Quotes API
├── eastmoney_fundamentals.py        # F10 financials, sector/industry
├── eastmoney_earnings.py            # quarterly earnings history
├── eastmoney_market_cap.py          # TTM market cap
├── cls_news.py                      # 财联社 stock-specific news
└── sw_sector_map.py                 # 申万一级 sector → SW1 index code mapper

v2/scanner/universes/data/
├── csi300.csv
├── csi500.csv
├── csi1000.csv
├── sse50.csv
└── hs300_ext.csv

v2/scanner/universes/refresh_ashare_universes.py   # one-off snapshot script

tests/v2/data/ashare/
├── __init__.py
├── test_symbol.py
├── test_client_protocol.py          # protocol conformance
├── test_mootdx_prices.py            # mocked HTTP
├── test_eastmoney_fundamentals.py   # mocked HTTP
└── test_cls_news.py                 # mocked HTTP

tests/v2/data/test_composite_ashare_routing.py
tests/v2/scanner/test_universes_ashare.py
```

### Modified (additive only)

```
v2/data/protocol.py                  # NO CHANGE — A-share fits existing Protocol
v2/data/composite_client.py          # add ashare_backend slot + symbol-aware dispatch
v2/data/factory.py                   # make_hybrid_client(include_ashare=True) default
v2/scanner/universes/loader.py       # recognize 5 new universe names
src/research/shared_data.py          # benchmark = "hs300" when market=cn; SW1 sector etf
src/research/models.py               # AnalyzeRequest.market: str = "us"
app/backend/models/research_schemas.py  # mirror market field
app/backend/routes/research.py       # pass market through
app/frontend/src/types/analyze.ts    # market field on AnalyzeRunRequest
app/frontend/src/components/panels/analyze/input-node.tsx  # market dropdown ("US" / "A股")
app/frontend/src/types/scanner.ts    # UNIVERSE_KIND_OPTIONS adds 5
app/frontend/src/i18n/locales/{en,zh}.json  # scanner.universe.* keys for 5
pyproject.toml                       # mootdx + stockstats optional [ashare] extra
```

## Verification

### Backend

```powershell
$env:PYTHONIOENCODING="utf-8"
C:\Users\Jerry\anaconda3\python.exe -m pytest tests/v2/data/ashare/ tests/v2/scanner/test_universes_ashare.py -q
```

All new tests green. Existing v2/data tests green (no protocol change, additive only).

### Live smoke (requires internet, no API key)

```powershell
C:\Users\Jerry\anaconda3\python.exe -c "
from v2.data.ashare.client import AShareClient
c = AShareClient()
prices = c.get_prices('600519', '2025-01-01', '2026-05-26')
print(f'600519 (Moutai): {len(prices)} bars, last close={prices[-1].close}')
metrics = c.get_financial_metrics('600519', '2026-05-26', limit=4)
print(f'600519 metrics: {len(metrics)} quarters')
"
```

Expected: ~330 trading bars, last close ~1500-1700 RMB. 4 quarters of financial metrics.

### End-to-end smoke (Lab strategy backtest on A-share universe)

1. Restart backend
2. Open Lab → new strategy "A-share momentum"
3. Chat: "用沪深300股票池，RSI<30入场，5%止损"
4. Apply patch → universe should be `kind: csi300`
5. Run backtest → completes in ~60s (vs sp500 ~5min — fewer tickers, but mootdx is slower than EODHD)
6. Verdict appears, charts render

### End-to-end smoke (SOP analyze on A-share)

1. Restart frontend
2. Open Analyze → InputNode → set ticker `600519`, Market `A股`, Report language `简体中文`
3. Run → ~1-2 min → 中文 report on Moutai with sections macro / sector / fundamentals / valuation / technical / etc.

## Risks / unknowns

1. **mootdx server availability.** mootdx uses TDX servers which occasionally drop connections in China-mainland-only IPs. From outside China (e.g., AWS US-East), some servers may be unreachable. Mitigation: AShareClient retries across mootdx's bundled server list (the library already has this fallback); if all fail, `get_prices` returns `[]` and the section emits "n/a — data unavailable" (existing graceful path).
2. **Eastmoney HTML scraping fragility.** Eastmoney F10 pages are unstable; field names change occasionally. Mitigation: per-field try/except; partial data is acceptable. The a-stock-data repo's last 5 commits include endpoint-replacement fixes — adopt their post-V3.0 push2 endpoints.
3. **No `requirements.txt` for mootdx in install.** We add `mootdx` as an optional `[ashare]` extra. If a user runs `poetry install` without `--extras ashare`, A-share imports fail. Mitigation: import mootdx lazily inside `mootdx_prices.py` and raise a clear "install with [ashare]" error if missing. AShareClient construction itself doesn't import mootdx until first `get_prices` call.
4. **Universe CSVs are static snapshots.** CSI 300 constituents rebalance semi-annually. Mitigation: ship a refresh script and document that universes age out. Users re-run script as needed.
5. **Backtest engine assumes calendar.US.** The Lab backtest engine currently uses business-day calendar via pandas. A-share trading calendar has different holidays (Spring Festival, National Day, etc.). For v1 we accept some misalignment — engine uses pandas `B` frequency (Mon-Fri excluding US federal holidays). True fidelity needs `pandas_market_calendars["SSE"]` — v2.
6. **News volume for A-share.** 财联社 has 100x volume vs EODHD news for the same window. Section `news` may hit token limits in the SOP prompt. Mitigation: cap `limit=50` in shared_data fetch for A-share news (vs `limit=200` for US).
7. **LLM persona system for A-share.** Buffett/Graham/Munger personas trained on US market; their "lens" prompts may misfire on A-share regulatory / SOE context. Acceptable v1 — personas remain optional. v2 could add domestic personas (李录, 段永平, etc.) but not in scope.
