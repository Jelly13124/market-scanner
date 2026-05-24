// watchlist-service.ts — REST wrappers for /watchlists/* and /tickers/*.
// Mirrors the shape of services/pipeline-service.ts.

import {
  TickerSearchResult,
  UserWatchlist,
  UserWatchlistCreate,
  UserWatchlistUpdate,
} from '@/types/watchlist';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail || body?.message || JSON.stringify(body);
  } catch {
    try {
      detail = await res.text();
    } catch {
      /* swallow */
    }
  }
  return new Error(
    `${op} failed (HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''})${
      detail ? `: ${detail}` : ''
    }`,
  );
}

export const watchlistService = {
  async list(): Promise<UserWatchlist[]> {
    const r = await fetch(`${API_BASE_URL}/watchlists`);
    if (!r.ok) throw await _toError(r, 'listWatchlists');
    return r.json();
  },

  async create(body: UserWatchlistCreate): Promise<UserWatchlist> {
    const r = await fetch(`${API_BASE_URL}/watchlists`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _toError(r, 'createWatchlist');
    return r.json();
  },

  async get(id: number): Promise<UserWatchlist> {
    const r = await fetch(`${API_BASE_URL}/watchlists/${id}`);
    if (!r.ok) throw await _toError(r, 'getWatchlist');
    return r.json();
  },

  async update(id: number, body: UserWatchlistUpdate): Promise<UserWatchlist> {
    const r = await fetch(`${API_BASE_URL}/watchlists/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _toError(r, 'updateWatchlist');
    return r.json();
  },

  async delete(id: number): Promise<void> {
    const r = await fetch(`${API_BASE_URL}/watchlists/${id}`, {
      method: 'DELETE',
    });
    if (!r.ok && r.status !== 204) throw await _toError(r, 'deleteWatchlist');
  },

  async addTicker(id: number, ticker: string): Promise<UserWatchlist> {
    const r = await fetch(`${API_BASE_URL}/watchlists/${id}/tickers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    });
    if (!r.ok) throw await _toError(r, 'addTicker');
    return r.json();
  },

  async removeTicker(id: number, ticker: string): Promise<UserWatchlist> {
    const r = await fetch(
      `${API_BASE_URL}/watchlists/${id}/tickers/${encodeURIComponent(ticker)}`,
      { method: 'DELETE' },
    );
    if (!r.ok) throw await _toError(r, 'removeTicker');
    return r.json();
  },
};

export const tickerService = {
  /** Search tickers; empty query returns top-20 popular. */
  async search(q: string): Promise<TickerSearchResult[]> {
    const url = `${API_BASE_URL}/tickers/search?q=${encodeURIComponent(q)}`;
    const r = await fetch(url);
    if (!r.ok) throw await _toError(r, 'searchTickers');
    return r.json();
  },
};
