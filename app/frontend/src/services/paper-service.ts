import type { PaperAccount } from '@/types/paper';
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8001';
async function request(path: string, body?: object): Promise<PaperAccount | null> {
  const r = await fetch(`${BASE}/paper/${path}`, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  } : undefined);
  if (!r.ok) {
    const payload = await r.json().catch(() => ({}));
    throw new Error(typeof payload.detail === 'string' ? payload.detail : `Paper request failed (${r.status})`);
  }
  return r.json();
}
export const paperService = {
  getAccount: () => request('account'),
  createAccount: (initial_cash: string) => request('account', { initial_cash }),
  order: (ticker: string, side: 'buy' | 'sell', quantity: string, price: string) => request('orders', { ticker, side, quantity, price }),
  mark: (ticker: string, price: string) => request('marks', { ticker, price }),
};
