// research-service.ts — REST wrapper for the /research/* backend endpoints.
// Mirrors the shape of services/pipeline-service.ts.

import type {
  ResearchReportDetail,
  ResearchReportSummary,
  ResearchRunRequest,
} from '@/types/research';

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

export interface ListReportsParams {
  ticker?: string;
  scan_date?: string;
  limit?: number;
}

export const researchService = {
  async runResearch(req: ResearchRunRequest): Promise<ResearchReportDetail> {
    const r = await fetch(`${API_BASE_URL}/research/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'runResearch');
    return r.json();
  },

  async listReports(params: ListReportsParams = {}): Promise<ResearchReportSummary[]> {
    const q = new URLSearchParams();
    if (params.ticker) q.set('ticker', params.ticker);
    if (params.scan_date) q.set('scan_date', params.scan_date);
    if (params.limit != null) q.set('limit', String(params.limit));
    const qs = q.toString();
    const r = await fetch(`${API_BASE_URL}/research/reports${qs ? '?' + qs : ''}`);
    if (!r.ok) throw await _toError(r, 'listReports');
    return r.json();
  },

  async getReport(reportId: number): Promise<ResearchReportDetail> {
    const r = await fetch(`${API_BASE_URL}/research/reports/${reportId}`);
    if (!r.ok) throw await _toError(r, 'getReport');
    return r.json();
  },

  /** Returns the URL string for the HTML payload; consumers embed in an iframe. */
  reportHtmlUrl(reportId: number): string {
    return `${API_BASE_URL}/research/reports/${reportId}/html`;
  },
};
