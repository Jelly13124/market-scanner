// Mirror of src/lab/spec/strategy.py — flat dict shape; rely on backend
// validation for blocks (frontend treats them as Record<string, unknown>).

export interface UniverseSpec {
  kind: 'watchlist' | 'sp500' | 'nasdaq100';
  watchlist_id?: number | null;
}

export interface EntryGroup {
  combiner: 'and' | 'or';
  signals: Record<string, unknown>[];
}

export interface BacktestConfig {
  start_date?: string | null;
  end_date?: string | null;
  is_oos_split?: number;
  starting_capital_usd?: number;
  commission_bps?: number;
  slippage_bps?: number;
  max_concurrent_positions?: number;
  benchmark?: 'spy' | 'none';
  reverse_signal_as_exit?: boolean;
  full_position_policy?: 'skip' | 'replace_weakest';
}

export interface StrategySpec {
  name: string;
  description: string;
  universe: UniverseSpec;
  entry: EntryGroup;
  exit: Record<string, unknown>[];
  filters: Record<string, unknown>[];
  sizing: Record<string, unknown>;
  backtest_config: BacktestConfig;
}

export interface StrategyResponse {
  id: number;
  name: string;
  description: string | null;
  spec_json: StrategySpec;
  version: number;
  created_at: string;
  updated_at: string | null;
}

export interface StrategyCreateRequest {
  name: string;
  description?: string;
  initial_spec_json?: StrategySpec | null;
}

export interface StrategyUpdateRequest {
  name?: string;
  description?: string;
  spec_json?: StrategySpec;
}

export interface CatalogEntry {
  category: 'entry' | 'exit' | 'sizing' | 'filter';
  description: string;
  schema: Record<string, unknown>;
}

export type Catalog = Record<string, CatalogEntry>;
