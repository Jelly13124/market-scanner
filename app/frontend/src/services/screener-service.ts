import {
  ColumnMetadataResponse,
  Market,
  ScreenerSnapshotResponse,
  ScreenerStatusResponse,
  ChipValues,
} from '@/types/screener';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

function chipValuesToQuery(values: ChipValues): URLSearchParams {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) {
    if (v === null || v === '' || v === undefined) continue;
    if (Array.isArray(v)) {
      if (v.length > 0) sp.append(k, v.join(','));
    } else {
      sp.append(k, String(v));
    }
  }
  return sp;
}

export interface SnapshotQuery {
  market?: Market;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  limit?: number;
  offset?: number;
  filters?: ChipValues;
}

export async function getLatestSnapshot(q: SnapshotQuery = {}): Promise<ScreenerSnapshotResponse> {
  const sp = chipValuesToQuery(q.filters || {});
  if (q.market) sp.set('market', q.market);
  if (q.sort_by) sp.set('sort_by', q.sort_by);
  if (q.sort_dir) sp.set('sort_dir', q.sort_dir);
  if (q.limit !== undefined) sp.set('limit', String(q.limit));
  if (q.offset !== undefined) sp.set('offset', String(q.offset));

  const url = `${API_BASE}/screener/snapshot/latest?${sp.toString()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`screener snapshot failed: ${res.status}`);
  return res.json();
}

export async function getColumnMetadata(): Promise<ColumnMetadataResponse> {
  const res = await fetch(`${API_BASE}/screener/snapshot/columns`);
  if (!res.ok) throw new Error(`screener columns failed: ${res.status}`);
  return res.json();
}

export async function getSnapshotStatus(): Promise<ScreenerStatusResponse> {
  const res = await fetch(`${API_BASE}/screener/snapshot/status`);
  if (!res.ok) throw new Error(`screener status failed: ${res.status}`);
  return res.json();
}
