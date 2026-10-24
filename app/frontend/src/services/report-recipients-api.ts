// report-recipients-api.ts — REST wrapper for /report-recipients/*.
// Auth header is injected by the global fetch interceptor (auth-context.tsx).
// Collection routes use a trailing slash so they don't 307-redirect (which can
// drop the Authorization header behind the proxy — see api-keys-api.ts).

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export interface ReportRecipient {
  id: number;
  email: string;
  is_verified: boolean;
}

async function _err(r: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    detail = (await r.json())?.detail || '';
  } catch {
    /* non-JSON body */
  }
  return new Error(detail || `Failed to ${op} report email (HTTP ${r.status})`);
}

class ReportRecipientsService {
  private baseUrl = `${API_BASE_URL}/report-recipients`;

  async list(): Promise<ReportRecipient[]> {
    const r = await fetch(`${this.baseUrl}/`);
    if (!r.ok) throw await _err(r, 'load');
    return r.json();
  }

  async add(email: string): Promise<ReportRecipient> {
    const r = await fetch(`${this.baseUrl}/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    if (!r.ok) throw await _err(r, 'add');
    return r.json();
  }

  async resend(id: number): Promise<ReportRecipient> {
    const r = await fetch(`${this.baseUrl}/${id}/resend`, { method: 'POST' });
    if (!r.ok) throw await _err(r, 'resend verification for');
    return r.json();
  }

  async remove(id: number): Promise<void> {
    const r = await fetch(`${this.baseUrl}/${id}`, { method: 'DELETE' });
    if (!r.ok) throw await _err(r, 'remove');
  }
}

export const reportRecipientsService = new ReportRecipientsService();
