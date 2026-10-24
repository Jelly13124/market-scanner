// REST wrapper for the Phase 6E /lab/strategies/{id}/chat endpoints.

import type {
  ChatApplyRequest, ChatMessage, ChatResponse, ChatSendRequest,
} from '@/types/chat';
import type { StrategyResponse } from '@/types/strategy';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
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

export const labChatService = {
  async list(strategyId: number): Promise<ChatMessage[]> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${strategyId}/chat`);
    if (!r.ok) throw await _toError(r, 'listChat');
    return r.json();
  },
  async send(strategyId: number, req: ChatSendRequest): Promise<ChatResponse> {
    const r = await fetch(`${API_BASE_URL}/lab/strategies/${strategyId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw await _toError(r, 'sendChat');
    return r.json();
  },
  async applyPatch(strategyId: number, req: ChatApplyRequest): Promise<StrategyResponse> {
    const r = await fetch(
      `${API_BASE_URL}/lab/strategies/${strategyId}/chat/apply`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(req),
      },
    );
    if (!r.ok) throw await _toError(r, 'applyChatPatch');
    return r.json();
  },
};
