import {
  ColumnMetadataResponse,
  Market,
  ScreenerSnapshotResponse,
  ScreenerStatusResponse,
  ChipValues,
  ScreenerPreset,
  SectorSummaryRow,
  SnapshotRefreshResult,
  SnapshotRefreshState,
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

/** Per-sector aggregate performance for the Sectors board (latest snapshot). */
export async function getSectorSummary(market = 'US'): Promise<SectorSummaryRow[]> {
  const res = await fetch(`${API_BASE}/screener/sectors?market=${market}`);
  if (!res.ok) throw new Error(`screener sectors failed: ${res.status}`);
  return res.json();
}

/** Trigger a single-market snapshot rebuild (runs server-side in the background). */
export async function triggerSnapshotRefresh(market: 'US' | 'CN'): Promise<SnapshotRefreshResult> {
  const r = await fetch(`${API_BASE}/screener/snapshot/refresh?market=${market}`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`triggerSnapshotRefresh ${r.status}`);
  return r.json();
}

/** Poll the current refresh progress/state. */
export async function getSnapshotRefreshState(): Promise<SnapshotRefreshState> {
  const r = await fetch(`${API_BASE}/screener/snapshot/refresh`);
  if (!r.ok) throw new Error(`getSnapshotRefreshState ${r.status}`);
  return r.json();
}

export async function listPresets(): Promise<ScreenerPreset[]> {
  const r = await fetch(`${API_BASE}/screener/presets`);
  if (!r.ok) throw new Error(`listPresets ${r.status}`);
  return r.json();
}

export async function createPreset(body: {
  name: string;
  market: 'US' | 'CN' | null;
  filters: ChipValues;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  schedule_enabled?: boolean;
  notify_channels?: string[] | null;
}): Promise<ScreenerPreset> {
  const r = await fetch(`${API_BASE}/screener/presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`createPreset ${r.status}`);
  return r.json();
}

export async function patchPreset(
  id: number,
  patch: Partial<{
    name: string;
    schedule_enabled: boolean;
    notify_channels: string[] | null;
  }>
): Promise<ScreenerPreset> {
  const r = await fetch(`${API_BASE}/screener/presets/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`patchPreset ${r.status}`);
  return r.json();
}

export async function deletePreset(id: number): Promise<void> {
  const r = await fetch(`${API_BASE}/screener/presets/${id}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) throw new Error(`deletePreset ${r.status}`);
}
