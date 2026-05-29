export type Market = 'US' | 'CN' | 'ALL';

export type AnalystRating =
  | 'strong_buy' | 'buy' | 'neutral' | 'sell' | 'strong_sell';

export interface SnapshotRow {
  ticker: string;
  market: 'US' | 'CN';
  snapshot_date: string;

  price: string | null;
  prev_close: string | null;
  change_pct: string | null;
  volume: number | null;
  avg_volume_10d: number | null;
  rel_volume: string | null;

  market_cap: string | null;
  pe_ttm: string | null;
  pe_forward: string | null;
  pb: string | null;
  ps: string | null;
  peg: string | null;

  eps_growth_yoy: string | null;
  revenue_growth_yoy: string | null;
  roe: string | null;
  profit_margin: string | null;
  dividend_yield_pct: string | null;
  beta: string | null;

  sector: string | null;
  industry: string | null;
  exchange: string | null;

  analyst_rating: AnalystRating | null;
  analyst_count: number | null;
  target_mean_price: string | null;

  recent_earnings_date: string | null;
  upcoming_earnings_date: string | null;

  perf_1d: string | null;
  perf_5d: string | null;
  perf_1m: string | null;
  perf_3m: string | null;
  perf_ytd: string | null;
  perf_1y: string | null;

  data_source: string | null;
}

export interface ScreenerSnapshotResponse {
  rows: SnapshotRow[];
  total_count: number;
  snapshot_date: string;
  last_updated: string;
}

export interface ScreenerStatusResponse {
  snapshot_date: string | null;
  last_updated: string | null;
  row_count: number;
  by_market: Record<string, number>;
}

export interface SnapshotRefreshState {
  running: boolean;
  market: string | null;
  done: number;
  total: number;
  started_at: string | null;
  finished_at: string | null;
  inserted: number | null;
  error: string | null;
}

export interface SnapshotRefreshResult {
  started: boolean;
  state: SnapshotRefreshState;
}

export type ChipKind = 'range' | 'multi_select' | 'date_range';

export interface ChipOption {
  value: string;
  label_en: string;
  label_zh: string;
}

export interface ColumnMetadata {
  slug: string;
  label_en: string;
  label_zh: string;
  kind: ChipKind;
  format?: 'currency' | 'percent' | 'multiplier' | 'abbreviated_currency';
  step?: number;
  filter_min?: string;
  filter_max?: string;
  filter_key?: string;       // multi_select
  filter_after?: string;     // date_range
  filter_before?: string;    // date_range
  options?: ChipOption[];
  options_us?: ChipOption[];
  options_cn?: ChipOption[];
}

export interface ColumnMetadataResponse {
  columns: ColumnMetadata[];
}

/** Local filter state per chip slug. Sent to the API as flat query params. */
export type ChipValues = Record<string, string | number | string[] | null>;

export interface ScreenerPreset {
  id: number;
  name: string;
  market: 'US' | 'CN' | null;
  filters: ChipValues;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  schedule_enabled: boolean;
  notify_channels: string[] | null;
  last_run_at: string | null;
  last_match_count: number | null;
}
