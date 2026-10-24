// notification-service.ts — REST wrapper for /notifications/* endpoints.
// Mirrors the pattern in services/pipeline-service.ts.

import type {
  DeliveryResponse,
  SubscriptionCreateRequest,
  SubscriptionPatchRequest,
  SubscriptionResponse,
} from '@/types/notification';

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

export const notificationService = {
  async list(): Promise<SubscriptionResponse[]> {
    const r = await fetch(`${API_BASE_URL}/notifications/subscriptions`);
    if (!r.ok) throw await _toError(r, 'listSubscriptions');
    return r.json();
  },

  async create(body: SubscriptionCreateRequest): Promise<SubscriptionResponse> {
    const r = await fetch(`${API_BASE_URL}/notifications/subscriptions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _toError(r, 'createSubscription');
    return r.json();
  },

  async update(id: number, patch: SubscriptionPatchRequest): Promise<SubscriptionResponse> {
    const r = await fetch(`${API_BASE_URL}/notifications/subscriptions/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw await _toError(r, 'updateSubscription');
    return r.json();
  },

  async remove(id: number): Promise<void> {
    const r = await fetch(`${API_BASE_URL}/notifications/subscriptions/${id}`, {
      method: 'DELETE',
    });
    if (!r.ok) throw await _toError(r, 'deleteSubscription');
  },

  async sendTest(id: number): Promise<DeliveryResponse> {
    const r = await fetch(`${API_BASE_URL}/notifications/subscriptions/${id}/test`, {
      method: 'POST',
    });
    if (!r.ok) throw await _toError(r, 'sendTest');
    return r.json();
  },

  async listDeliveries(id: number, limit = 20): Promise<DeliveryResponse[]> {
    const r = await fetch(
      `${API_BASE_URL}/notifications/subscriptions/${id}/deliveries?limit=${limit}`,
    );
    if (!r.ok) throw await _toError(r, 'listDeliveries');
    return r.json();
  },
};
