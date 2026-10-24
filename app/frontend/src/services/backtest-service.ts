// REST wrapper for the Phase 6E /lab/backtests + /lab/strategies/{id}/backtest endpoints.

import type { BacktestResponse } from '@/types/backtest';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json();
    const d = body?.detail ?? body?.message;
    if (typeof d === 'string') {
      detail = d;
    } else if (Array.isArray(d)) {
      detail = d
        .map((e) => {
          const loc = Array.isArray(e?.loc) ? e.loc.filter((x: unknown) => x !== 'body').join('.') : '';
          const msg = e?.msg ?? JSON.stringify(e);
          return loc ? `${loc}: ${msg}` : String(msg);
        })
        .join('; ');
    } else if (d != null) {
      detail = JSON.stringify(d);
    } else {
      detail = JSON.stringify(body);
    }
  } catch {
    try { detail = await res.text(); } catch { /* swallow */ }
  }
  return new Error(
    `${op} failed (HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''})${detail ? ': ' + detail : ''}`,
  );
}

export const backtestService = {
  async run(strategyId: number): Promise<BacktestResponse> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${strategyId}/backtest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    if (!r.ok) throw await _toError(r, 'runBacktest');
    return r.json();
  },
  async list(strategyId: number): Promise<BacktestResponse[]> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${strategyId}/backtests`);
    if (!r.ok) throw await _toError(r, 'listBacktests');
    return r.json();
  },
  async get(id: number): Promise<BacktestResponse> {
    const r = await fetch(`${API_BASE_URL}/lab/backtests/${id}`);
    if (!r.ok) throw await _toError(r, 'getBacktest');
    return r.json();
  },
  chartUrl(id: number, type: 'equity_curve' | 'drawdown' | 'monthly_heatmap'): string {
    return `${API_BASE_URL}/lab/backtests/${id}/chart/${type}.png`;
  },
};
