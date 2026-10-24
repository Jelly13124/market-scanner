// report-schedules-api.ts — REST wrapper for /report-schedules/* (Stage 3).
// Auth header injected by the global fetch interceptor. Trailing-slash collection
// URLs avoid the proxy 307-redirect that can drop auth (see api-keys-api.ts).

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface ReportSchedule {
  id: number;
  tickers: string[];
  cron_expr: string;
  report_language: string;
  is_enabled: boolean;
  last_run_at: string | null;
  created_at: string;
}

export interface ScheduleCreate {
  tickers: string[];
  cron_expr: string;
  report_language?: string;
  is_enabled?: boolean;
}

export interface ScheduleUpdate {
  tickers?: string[];
  cron_expr?: string;
  report_language?: string;
  is_enabled?: boolean;
}

async function _err(r: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    detail = (await r.json())?.detail || '';
  } catch {
    /* non-JSON */
  }
  return new Error(detail || `Failed to ${op} schedule (HTTP ${r.status})`);
}

class ReportSchedulesService {
  private baseUrl = `${API_BASE_URL}/report-schedules`;

  async list(): Promise<ReportSchedule[]> {
    const r = await fetch(`${this.baseUrl}/`);
    if (!r.ok) throw await _err(r, 'load');
    return r.json();
  }

  async create(body: ScheduleCreate): Promise<ReportSchedule> {
    const r = await fetch(`${this.baseUrl}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _err(r, 'create');
    return r.json();
  }

  async update(id: number, body: ScheduleUpdate): Promise<ReportSchedule> {
    const r = await fetch(`${this.baseUrl}/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _err(r, 'update');
    return r.json();
  }

  async remove(id: number): Promise<void> {
    const r = await fetch(`${this.baseUrl}/${id}`, { method: 'DELETE' });
    if (!r.ok && r.status !== 204) throw await _err(r, 'delete');
  }
}

export const reportSchedulesService = new ReportSchedulesService();

// --- cron helpers (frequency preset <-> cron, all America/New_York) ---------

export type Frequency = 'daily' | 'weekdays' | 'weekly';

export function buildCron(freq: Frequency, time: string): string {
  const [hh, mm] = (time || '09:30').split(':');
  const h = Math.max(0, Math.min(23, parseInt(hh, 10) || 9));
  const m = Math.max(0, Math.min(59, parseInt(mm, 10) || 30));
  const dow = freq === 'weekdays' ? '1-5' : freq === 'weekly' ? '1' : '*';
  return `${m} ${h} * * ${dow}`;
}

export function describeCron(cron: string): string {
  const parts = (cron || '').trim().split(/\s+/);
  if (parts.length !== 5) return cron;
  const [m, h, , , dow] = parts;
  const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  const freq = dow === '1-5' ? 'Weekdays' : dow === '1' ? 'Weekly (Mon)' : dow === '*' ? 'Daily' : `dow ${dow}`;
  return `${freq} ${time} ET`;
}
