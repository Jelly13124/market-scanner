# Scanner detector & signal usefulness — evaluation report

Regime-segmented usefulness study over `nasdaq100_sp500 (80-ticker subset)`. Primary axis is **interestingness vs random** (does it flag bigger movers than random); directional alpha / IC is secondary colour. Generated at: 2026-05-31 (Phase 1+2+3).

## Headline

**Useful detectors:** intraday_move
**Useless (consider cutting):** analyst_rating, bollinger_squeeze, earnings_event, gap, high_breakout, insider_cluster, ma_cross, news_sentiment_shift, obv_divergence, price_volume_anomaly, rsi_divergence
**Data-limited:** target_price_change

**Useful signals:** —
**Inverted:** —
**Useless:** —
**Data-limited:** earnings_quality, quality, value

## Detector scorecard

Per-regime cell: `n / Δinterestingness (t) / dir-α`. Interestingness-vs-random is primary; dir-α is secondary colour.

| Detector | Verdict | BEAR (bear_2022) | BULL (bull_2023_24) | CHOPPY (choppy_2025) |
|---|---|---|---|---|
| intraday_move | KEEP | 2974 / +1.45pp (t=8.2) / -0.29% | 786 / +1.39pp (t=4.3) / +0.20% | 865 / +1.67pp (t=8.3) / -0.11% |
| analyst_rating | CUT | 59 / -2.03pp (t=-5.3) / +0.71% | 99 / +0.16pp (t=0.3) / -0.09% | 46 / +1.21pp (t=2.2) / -0.88% |
| bollinger_squeeze | CUT | 198 / -0.35pp (t=-1.0) / -0.08% | 277 / +0.25pp (t=0.6) / +0.34% | 151 / -0.67pp (t=-2.2) / -0.19% |
| earnings_event | CUT | 1146 / +0.09pp (t=0.4) / +0.43% | 1071 / +0.17pp (t=1.0) / +0.13% | 676 / +0.29pp (t=1.5) / -0.27% |
| gap | CUT | 8738 / -1.13pp (t=-8.2) / +0.07% | 6354 / -0.52pp (t=-4.2) / +0.07% | 1897 / -1.17pp (t=-9.6) / -0.06% |
| high_breakout | CUT | 97 / -1.63pp (t=-4.2) / +0.27% | 721 / -0.02pp (t=-0.1) / -0.06% | 201 / -1.22pp (t=-4.4) / -0.27% |
| insider_cluster | CUT | 523 / -0.74pp (t=-3.5) / +0.30% | 1060 / +0.07pp (t=0.2) / -0.75% | 755 / +0.16pp (t=0.8) / -0.36% |
| ma_cross | CUT | 104 / -1.23pp (t=-3.1) / +0.37% | 60 / +1.39pp (t=0.7) / -1.98% | 81 / +0.04pp (t=0.1) / -0.44% |
| news_sentiment_shift | CUT | 177 / -1.32pp (t=-5.0) / -0.28% | 205 / -0.35pp (t=-1.6) / -0.16% | 185 / -0.35pp (t=-1.2) / +0.06% |
| obv_divergence | CUT | 346 / -1.02pp (t=-4.3) / +0.29% | 309 / -0.45pp (t=-2.4) / -0.05% | 265 / +0.14pp (t=0.5) / -0.35% |
| price_volume_anomaly | CUT | 248 / -0.64pp (t=-1.9) / -0.23% | 314 / -0.02pp (t=-0.1) / -0.06% | 173 / -0.03pp (t=-0.1) / +0.04% |
| rsi_divergence | CUT | 3793 / -0.11pp (t=-0.7) / +0.40% | 4203 / -0.03pp (t=-0.2) / +0.05% | 2167 / -0.08pp (t=-0.6) / +0.19% |
| target_price_change | DATA-LIMITED | 0 / -5.24pp (t=0.0) / +0.00% | 0 / -3.53pp (t=0.0) / +0.00% | 0 / -4.07pp (t=0.0) / +0.00% |

## Signal scorecard

Per-regime cell: `mean rank-IC (t) / n_dates`.

| Signal | Verdict | BEAR (bear_2022) | BULL (bull_2023_24) | CHOPPY (choppy_2025) |
|---|---|---|---|---|
| momentum | WATCH | +0.017 (t=0.4) / 40 | +0.043 (t=0.8) / 36 | -0.004 (t=-0.1) / 23 |
| technical | WATCH | -0.050 (t=-1.7) / 40 | -0.017 (t=-0.6) / 36 | -0.029 (t=-0.6) / 23 |
| earnings_quality | DATA-LIMITED | +0.000 (t=0.0) / 0 | +0.000 (t=0.0) / 0 | +0.000 (t=0.0) / 0 |
| quality | DATA-LIMITED | +0.000 (t=0.0) / 0 | +0.000 (t=0.0) / 0 | +0.076 (t=1.0) / 17 |
| value | DATA-LIMITED | +0.000 (t=0.0) / 0 | +0.000 (t=0.0) / 0 | +0.000 (t=0.0) / 0 |

## Phase 3 — full-replay confirmation

Bounded full-replay over each regime: mean 5d alpha, and the quant overlay ON vs OFF delta.

| Regime | mean alpha 5d | quant ON | quant OFF | ON − OFF |
|---|---|---|---|---|
| bear_2022 | -0.79% | -0.79% | +1.04% | -1.83% |
| bull_2023_24 | +0.48% | +0.48% | +0.79% | -0.31% |
| choppy_2025 | +1.93% | +1.93% | +1.93% | -0.00% |

## Regime windows

| Regime | Label | Dates | SPY return | Max drawdown | Trend R² |
|---|---|---|---|---|---|
| bear_2022 | BEAR | 2022-01-03 → 2022-10-14 | -24.27% | -24.50% | 0.63 |
| bull_2023_24 | BULL | 2023-10-27 → 2024-07-16 | +38.98% | -5.35% | 0.91 |
| choppy_2025 | CHOPPY | 2025-02-18 → 2025-08-01 | +2.28% | -18.76% | 0.42 |

## Methodology & caveats

- **No lookahead.** Detectors/signals decide through `CachedAsOfClient`, which clamps every read to `<= asof`; forward returns are measured from the full (post-asof) series only at scoring time.
- **Adjusted close** preferred everywhere, so ex-div / split days don't manufacture fake moves.
- **Fundamental availability lag (~60d).** Point-in-time fundamentals are treated as available only after a reporting lag, so value/quality factors aren't credited with data they couldn't have had.
- **Survivorship bias.** The universe is a *current* snapshot (delisted names absent), which flatters long-only stats — read directional alpha with that caveat.
- **Interestingness is primary.** The scanner is an LLM-cost pre-filter; a detector earns its budget by flagging bigger movers than random. Directional alpha is secondary colour and never the sole basis for a CUT.
- **Low-n / low-coverage → DATA-LIMITED.** Detectors/signals that barely fired or covered little of the universe are flagged, not judged.
- **Seeded baselines.** Random interestingness baselines use a fixed seed, so the report is deterministic and reproducible.
