// TypeScript types mirroring the backend Pydantic schemas in
// app/backend/models/scanner_schemas.py. Keep these in sync when the backend
// schema changes.

export type UniverseKind =
  | 'sp500'
  | 'nasdaq100'
  | 'nasdaq100_sp500'
  | 'russell3000'
  | 'all_us'
  | 'custom'
  | 'watchlist'
  // Phase 8 A-share universes
  | 'sse50'
  | 'csi300'
  | 'csi500'
  | 'csi1000'
  | 'hs300_ext';

export const UNIVERSE_KIND_OPTIONS: { value: UniverseKind; label: string; description: string }[] = [
  {
    value: 'nasdaq100_sp500',
    label: 'NASDAQ 100 + S&P 500',
    description: 'Recommended default — union of NDX 100 and S&P 500 (~530 tickers)',
  },
  { value: 'sp500', label: 'S&P 500', description: '~500 large-cap US stocks' },
  { value: 'nasdaq100', label: 'NASDAQ 100', description: '~100 NASDAQ blue-chips' },
  { value: 'russell3000', label: 'Russell 3000', description: '~3000 US-listed stocks' },
  { value: 'all_us', label: 'All US Listed', description: '~6000-8000 NYSE + NASDAQ + AMEX' },
  { value: 'custom', label: 'Custom Watchlist', description: 'Provide your own ticker list' },
  { value: 'watchlist', label: 'User watchlist', description: 'Pick a saved watchlist from the sidebar' },
  // Phase 8 A-share universes (sourced via mootdx)
  { value: 'sse50', label: 'SSE 50 / 上证 50', description: '~50 Shanghai blue-chips' },
  { value: 'csi300', label: 'CSI 300 / 沪深 300', description: '~300 A-share large-caps (SSE + SZSE)' },
  { value: 'csi500', label: 'CSI 500 / 中证 500', description: '~500 A-share mid-caps' },
  { value: 'csi1000', label: 'CSI 1000 / 中证 1000', description: '~1000 A-share small-caps' },
  { value: 'hs300_ext', label: 'HS300 + CSI500', description: '~800-ticker union of CSI 300 and CSI 500' },
];

export type ScanStatus = 'PENDING' | 'RUNNING' | 'COMPLETE' | 'ERROR';

export type Direction = 'bullish' | 'bearish' | 'neutral';

export interface TriggerPayload {
  detector: string;
  triggered: boolean;
  severity_z: number;
  direction: Direction;
  reason: string;
  components?: Record<string, number>;
  asof_date?: string | null;
}

export interface ScannerConfigResponse {
  id: number;
  name: string;
  universe_kind: UniverseKind;
  universe_tickers?: string[] | null;
  cron_expr: string;
  is_enabled: boolean;
  top_n: number;
  weights?: Record<string, unknown> | null;
  /** Phase 5C — set when universe_kind === 'watchlist'. */
  user_watchlist_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ScannerConfigCreateRequest {
  name: string;
  universe_kind: UniverseKind;
  universe_tickers?: string[] | null;
  cron_expr?: string;
  is_enabled?: boolean;
  top_n?: number;
  weights?: Record<string, unknown> | null;
  /** Required when universe_kind === 'watchlist'. */
  user_watchlist_id?: number | null;
}

export interface ScannerConfigUpdateRequest {
  name?: string;
  universe_kind?: UniverseKind;
  universe_tickers?: string[] | null;
  cron_expr?: string;
  is_enabled?: boolean;
  top_n?: number;
  weights?: Record<string, unknown> | null;
  user_watchlist_id?: number | null;
}

export interface ScanRunSummary {
  id: number;
  config_id: number;
  status: ScanStatus;
  started_at?: string | null;
  completed_at?: string | null;
  universe_size?: number | null;
  error_message?: string | null;
  created_at?: string | null;
}

export interface WatchlistEntryResponse {
  id: number;
  scan_run_id: number;
  ticker: string;
  composite_score: number;
  direction: Direction;
  event_score: number;
  quant_score?: number | null;
  /** Raw max |severity_z| across triggered detectors — tiebreaker for
   *  ties at composite_score = 100. */
  event_severity?: number;
  triggers: TriggerPayload[];
  rank: number;
}

export interface ScanRunDetailResponse extends ScanRunSummary {
  entries: WatchlistEntryResponse[];
}

// ---------------------------------------------------------------------------
// Live quote payload from GET /scanner/runs/{id}/quotes
// ---------------------------------------------------------------------------

export interface Quote {
  ticker: string;
  current_price: number | null;
  prev_close: number | null;
  /** Today's session % change (Finnhub's `dp` field) — already in
   *  percent units (e.g. 2.0 means +2%). */
  percent_change: number | null;
  asof_timestamp: number | null;
}

/** Backend returns dict[ticker, Quote | null] — null = quote fetch failed. */
export type QuotesByTicker = Record<string, Quote | null>;

// ---------------------------------------------------------------------------
// Detector metadata (GET /scanner/detectors)
// ---------------------------------------------------------------------------

export interface DetectorMetadata {
  name: string;
  label: string;
  default_mult: number;
  description: string;
}

/** Shape of the optional fields the dialog writes into ScannerConfig.weights. */
export interface ScannerWeightsExtension {
  enabled_detectors?: string[] | null;
  detector_severity_mult?: Record<string, number>;
  // Existing fields (kept for shape completeness):
  event_weight?: number;
  quant_weight?: number;
  factor_weights?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// SSE event payloads emitted by /scanner/runs/{run_id}/stream
// ---------------------------------------------------------------------------

export interface ScanStartEvent {
  event: 'start';
  run_id: number;
  universe_size?: number;
}

export interface ScanProgressEvent {
  event: 'progress';
  run_id: number;
  processed: number;
  total: number;
  triggered: number;
  skipped: number;
  errors: number;
  current_ticker?: string | null;
  elapsed_seconds: number;
  eta_seconds?: number | null;
}

export interface ScanCompleteEvent {
  event: 'complete';
  run_id: number;
  entries: number;
}

export interface ScanErrorEvent {
  event: 'error';
  run_id: number;
  message: string;
}

export type ScanStreamEvent =
  | ScanStartEvent
  | ScanProgressEvent
  | ScanCompleteEvent
  | ScanErrorEvent;

// ---------------------------------------------------------------------------
// Cron presets surfaced in the UI dropdown
// ---------------------------------------------------------------------------

export interface CronPreset {
  expr: string;
  label: string;
}

export const CRON_PRESETS: CronPreset[] = [
  { expr: '0 6 * * 1-5', label: 'Pre-market weekdays (06:00 ET)' },
  { expr: '30 16 * * 1-5', label: 'After close weekdays (16:30 ET)' },
  { expr: '0 21 * * 1-5', label: 'Late evening weekdays (21:00 ET)' },
];
