// TypeScript types mirroring the backend Pydantic schemas in
// app/backend/models/watchlist_schemas.py. Keep in sync.

export interface UserWatchlist {
  id: number;
  name: string;
  tickers: string[];
  created_at: string;
  updated_at?: string | null;
}

export interface UserWatchlistCreate {
  name: string;
}

export interface UserWatchlistUpdate {
  name?: string | null;
  tickers?: string[] | null;
}

export interface TickerAddRequest {
  ticker: string;
}

export interface TickerSearchResult {
  ticker: string;
  name?: string | null;
}

/** One row from GET /watchlists/{id}/quotes — live per-ticker market data
 *  fetched on demand via yfinance. `error` is set (and price/etc null) when
 *  the quote fetch failed for that ticker. */
export interface LiveQuoteRow {
  ticker: string;
  price: number | null;
  prev_close: number | null;
  change_pct: number | null;
  volume: number | null;
  day_open: number | null;
  day_high: number | null;
  day_low: number | null;
  error: string | null;
}
