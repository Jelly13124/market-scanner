// REST wrapper for /institutional-flow/{ticker} — dealer gamma (GEX, options-implied
// snapshot) + FINRA short-volume (off-exchange-pressure PROXY, not true dark-pool).

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface GammaWall {
  strike: number;
  gamma_dollars: number;
}

export interface GammaExposure {
  spot: number;
  total_gex: number;
  regime: string; // "positive" | "negative" | "flat"
  call_gex: number;
  put_gex: number;
  walls: GammaWall[];
  gamma_flip: number | null;
}

export interface ShortVolume {
  short_pct: number;
  date: string;
  avg_short_pct: number;
  trend: string; // "rising" | "falling" | "flat"
  n_days: number;
}

export interface InstitutionalFlow {
  ticker: string;
  gamma: GammaExposure | null;
  short_volume: ShortVolume | null;
}

export const institutionalFlowService = {
  async get(ticker: string): Promise<InstitutionalFlow> {
    const r = await fetch(`${API_BASE_URL}/institutional-flow/${encodeURIComponent(ticker.trim())}`);
    if (!r.ok) {
      let detail = '';
      try {
        const body = await r.json();
        detail = typeof body?.detail === 'string' ? body.detail : '';
      } catch {
        /* swallow */
      }
      throw new Error(`institutional-flow failed (HTTP ${r.status})${detail ? ': ' + detail : ''}`);
    }
    return r.json();
  },
};
