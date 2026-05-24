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
