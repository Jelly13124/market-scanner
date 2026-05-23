// REST wrapper for the Phase 4 /research/analyze endpoint.
// Reuses the existing Phase 3 GET endpoints (list + html) where possible.

import type {
  AnalyzeReportDetail, AnalyzeRunRequest,
} from '@/types/analyze';
import type { ResearchReportSummary } from '@/types/research';

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
    `${op} failed (HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''})${detail ? ': ' + detail : ''}`,
  );
}

export const analyzeService = {
  /** POST /research/analyze — sync, takes 60-120s. */
  async runAnalyze(req: AnalyzeRunRequest): Promise<AnalyzeReportDetail> {
    const r = await fetch(`${API_BASE_URL}/research/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'runAnalyze');
    return r.json();
  },

  /** Reuse Phase 3 list endpoint. Returns summaries (analyze rows
   *  show up too — same table). */
  async listReports(ticker?: string, limit = 20): Promise<ResearchReportSummary[]> {
    const q = new URLSearchParams();
    if (ticker) q.set('ticker', ticker);
    q.set('limit', String(limit));
    const r = await fetch(`${API_BASE_URL}/research/reports?${q}`);
    if (!r.ok) throw await _toError(r, 'listReports');
    return r.json();
  },

  /** Direct URL to the rendered HTML (iframe src). */
  reportHtmlUrl(reportId: number): string {
    return `${API_BASE_URL}/research/reports/${reportId}/html`;
  },
};
