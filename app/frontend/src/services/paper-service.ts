// paper-service.ts — REST wrapper for the read-only /paper/* backend endpoints.
// Mirrors services/research-service.ts. Auth is attached automatically by the
// global fetch interceptor (auth-context.tsx) for any URL under VITE_API_URL,
// so these are plain fetch calls with no manual Authorization header.

import type { PaperPerformance } from '@/types/paper';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail || body?.message || JSON.stringify(body);
  } catch {
    try { detail = await res.text(); } catch { /* swallow */ }
  }
  return new Error(
    `${op} failed (HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''})${detail ? `: ${detail}` : ''}`,
  );
}

export const paperService = {
  async getPerformance(): Promise<PaperPerformance> {
    const r = await fetch(`${API_BASE_URL}/paper/performance`);
    if (!r.ok) throw await _toError(r, 'getPerformance');
    return r.json();
  },

  // The equity-chart PNG endpoint is open-read (an <img src> cannot carry the
  // Bearer header, and the chart alone is not sensitive — the numbers stay
  // behind the superuser gate on /paper/performance). Return a plain URL string.
  equityChartUrl(): string {
    return `${API_BASE_URL}/paper/equity-chart.png`;
  },
};
