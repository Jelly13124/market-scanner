// REST wrapper for the Phase 6E /lab/strategies endpoints + /lab/catalog.

import type {
  Catalog, StrategyCreateRequest, StrategyResponse, StrategyUpdateRequest,
} from '@/types/strategy';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
  // FastAPI returns `detail` as a string for HTTPException(...) but as an
  // array of {loc, msg, type, ...} for Pydantic 422 validation errors.
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

export const strategyService = {
  async list(): Promise<StrategyResponse[]> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies`);
    if (!r.ok) throw await _toError(r, 'listStrategies');
    return r.json();
  },
  async create(req: StrategyCreateRequest): Promise<StrategyResponse> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'createStrategy');
    return r.json();
  },
  async get(id: number): Promise<StrategyResponse> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${id}`);
    if (!r.ok) throw await _toError(r, 'getStrategy');
    return r.json();
  },
  async update(id: number, req: StrategyUpdateRequest): Promise<StrategyResponse> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'updateStrategy');
    return r.json();
  },
  async delete(id: number): Promise<void> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${id}`, { method: 'DELETE' });
    if (!r.ok && r.status !== 204) throw await _toError(r, 'deleteStrategy');
  },
  async catalog(): Promise<Catalog> {
    const r = await fetch(`${API_BASE_URL}/lab/catalog`);
    if (!r.ok) throw await _toError(r, 'getCatalog');
    return r.json();
  },
};
