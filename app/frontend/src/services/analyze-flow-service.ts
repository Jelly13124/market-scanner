// REST wrapper for the Phase 5D /analyze-flows endpoints (saved canvas
// templates for the Analyze panel).

import type {
  AnalyzeFlowCreate, AnalyzeFlowResponse, AnalyzeFlowUpdate,
} from '@/types/analyze-flow';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
  // FastAPI returns `detail` as a string for HTTPException(...) but as an
  // array of {loc, msg, type, ...} for Pydantic 422 validation errors.
  // Stringify the array case so users see "name: String should have at
  // least 1 character" instead of "[object Object]".
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

export const analyzeFlowService = {
  async list(): Promise<AnalyzeFlowResponse[]> {
    const r = await fetch(`${API_BASE_URL}/analyze-flows`);
    if (!r.ok) throw await _toError(r, 'listAnalyzeFlows');
    return r.json();
  },

  async get(id: number): Promise<AnalyzeFlowResponse> {
    const r = await fetch(`${API_BASE_URL}/analyze-flows/${id}`);
    if (!r.ok) throw await _toError(r, 'getAnalyzeFlow');
    return r.json();
  },

  async create(req: AnalyzeFlowCreate): Promise<AnalyzeFlowResponse> {
    const r = await fetch(`${API_BASE_URL}/analyze-flows`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'createAnalyzeFlow');
    return r.json();
  },

  async update(id: number, req: AnalyzeFlowUpdate): Promise<AnalyzeFlowResponse> {
    const r = await fetch(`${API_BASE_URL}/analyze-flows/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'updateAnalyzeFlow');
    return r.json();
  },

  async delete(id: number): Promise<void> {
    const r = await fetch(`${API_BASE_URL}/analyze-flows/${id}`, {
      method: 'DELETE',
    });
    if (!r.ok && r.status !== 204) throw await _toError(r, 'deleteAnalyzeFlow');
  },
};
