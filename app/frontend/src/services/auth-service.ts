// auth-service.ts — thin REST wrappers for the /auth/* endpoints.
//
// These intentionally use the RAW fetch and never depend on the global
// interceptor installed by AuthProvider: registration/login must work
// before any token exists, and the interceptor skips /auth/* anyway.

import { User } from '@/types/auth';

export const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

async function _toError(res: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail || body?.message || JSON.stringify(body);
  } catch {
    try {
      detail = await res.text();
    } catch {
      /* swallow */
    }
  }
  const err = new Error(
    `${op} failed (HTTP ${res.status})${detail ? `: ${detail}` : ''}`,
  );
  // Attach status so callers can branch on 401/409/422 for friendly messages.
  (err as Error & { status?: number }).status = res.status;
  return err;
}

export const authService = {
  async register(
    email: string,
    password: string,
    full_name?: string,
  ): Promise<TokenResponse> {
    const r = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, full_name: full_name || null }),
    });
    if (!r.ok) throw await _toError(r, 'register');
    return r.json();
  },

  async login(email: string, password: string): Promise<TokenResponse> {
    const r = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!r.ok) throw await _toError(r, 'login');
    return r.json();
  },

  async me(token: string): Promise<User> {
    const r = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!r.ok) throw await _toError(r, 'me');
    return r.json();
  },

  // PATCH /auth/me — update the user's timezone. /auth/* is skipped by the
  // global interceptor, so set the Authorization header explicitly here.
  async updateTimezone(token: string, timezone: string): Promise<User> {
    const r = await fetch(`${API_BASE}/auth/me`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ timezone }),
    });
    if (!r.ok) throw await _toError(r, 'updateTimezone');
    return r.json();
  },

  async logout(token: string): Promise<void> {
    // Best-effort; ignore failures (the client clears its token regardless).
    try {
      await fetch(`${API_BASE}/auth/logout`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
    } catch {
      /* swallow */
    }
  },

  oauthUrl(provider: 'google' | 'github'): string {
    return `${API_BASE}/auth/oauth/${provider}`;
  },
};
