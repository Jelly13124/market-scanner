import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { paperService } from '@/services/paper-service';
import type { PaperAccount, PaperNumber } from '@/types/paper';
import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

const money = (value: PaperNumber) => Number(value).toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 4 });
const quantity = (value: PaperNumber) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 6 });

export function PaperPanel() {
  const { t } = useTranslation();
  return <div className="p-5 space-y-2">
    <h2 className="text-lg font-semibold">{t('paper.title')} · {t('paper.status')}</h2>
    <p className="text-sm text-muted-foreground">{t('paper.unavailable')}</p>
  </div>;
}

// Retained for development; the application only renders the placeholder above.
export function ManualPaperPanel() {
  const { t } = useTranslation();
  const [account, setAccount] = useState<PaperAccount | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [initialCash, setInitialCash] = useState('100000');
  const [ticker, setTicker] = useState('AAPL');
  const [action, setAction] = useState<'buy' | 'sell' | 'mark'>('buy');
  const [qty, setQty] = useState('1');
  const [price, setPrice] = useState('');
  const refresh = async () => {
    setLoading(true); setError('');
    try { setAccount(await paperService.getAccount()); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  };
  useEffect(() => { void refresh(); }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const updated = !account ? await paperService.createAccount(initialCash)
        : action === 'mark' ? await paperService.mark(ticker.trim().toUpperCase(), price)
        : await paperService.order(ticker.trim().toUpperCase(), action, qty, price);
      setAccount(updated);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  return <div className="h-full overflow-auto p-5 space-y-5">
    <div className="flex items-center justify-between">
      <div><h2 className="text-lg font-semibold">{t('paper.title')} <span className="ml-2 rounded border px-2 py-0.5 text-xs font-normal text-muted-foreground">{t('paper.status')}</span></h2><p className="text-sm text-muted-foreground">{t('paper.subtitle')}</p></div>
      <Button variant="outline" disabled={loading || busy} onClick={() => void refresh()}>{t('common.refresh', 'Refresh')}</Button>
    </div>
    <div className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-sm"><p>{t('paper.manualNote')}</p><p className="mt-1">{t('paper.limitations')}</p></div>
    {error && <div role="alert" className="text-sm text-red-600">{error}</div>}
    {loading ? <p>{t('common.loading')}</p> : !account ?
      <form onSubmit={submit} className="max-w-md border rounded p-4 space-y-3">
        <label htmlFor="paper-initial-cash">{t('paper.initialCash')}</label>
        <Input id="paper-initial-cash" type="number" min="1" max="1000000000" step="0.000001" required value={initialCash} onChange={(e) => setInitialCash(e.target.value)} />
        <Button disabled={busy} type="submit">{t('paper.createAccount')}</Button>
      </form> : <>
        <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
          {(['cash', 'equity', 'total_pnl', 'realized_pnl', 'unrealized_pnl'] as const).map((field) =>
            <div className="border rounded p-3" key={field}><div className="text-xs text-muted-foreground">{t(`paper.${field}`)}</div><div className="text-lg font-semibold mt-1">{money(account[field])}</div></div>)}
        </div>
        <form onSubmit={submit} className="border rounded p-4 flex flex-wrap items-end gap-3">
          <div><label htmlFor="paper-action" className="block text-xs mb-1">{t('paper.action')}</label>
            <select id="paper-action" value={action} onChange={(e) => setAction(e.target.value as typeof action)} className="h-9 rounded border bg-background px-3">
              <option value="buy">{t('paper.buy')}</option><option value="sell">{t('paper.sell')}</option><option value="mark">{t('paper.mark')}</option>
            </select></div>
          <div><label htmlFor="paper-ticker" className="block text-xs mb-1">{t('paper.ticker')}</label><Input id="paper-ticker" required maxLength={20} pattern="[A-Za-z][A-Za-z0-9.\-]*" value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())} className="w-28" /></div>
          {action !== 'mark' && <div><label htmlFor="paper-qty" className="block text-xs mb-1">{t('paper.quantity')}</label><Input id="paper-qty" type="number" min="0.000001" max="1000000" step="0.000001" required value={qty} onChange={(e) => setQty(e.target.value)} className="w-28" /></div>}
          <div><label htmlFor="paper-price" className="block text-xs mb-1">{t('paper.price')}</label><Input id="paper-price" type="number" min="0.000001" max="1000000000" step="0.000001" required value={price} onChange={(e) => setPrice(e.target.value)} className="w-36" /></div>
          <Button type="submit" disabled={busy}>{t(action === 'mark' ? 'paper.updateMark' : 'paper.submitOrder')}</Button>
        </form>
        <section><h3 className="font-medium mb-2">{t('paper.positions')}</h3><div className="overflow-auto border rounded"><table className="w-full text-sm text-left">
          <thead className="bg-muted"><tr>{['ticker','quantity','averageCost','lastPrice','marketValue','unrealized_pnl'].map((key) => <th key={key} className="p-2">{t(`paper.${key}`)}</th>)}</tr></thead>
          <tbody>{account.positions.map((p) => <tr key={p.ticker} className="border-t"><td className="p-2 font-mono">{p.ticker}</td><td className="p-2">{quantity(p.quantity)}</td><td className="p-2">{money(p.average_cost)}</td><td className="p-2" title={new Date(p.updated_at).toLocaleString()}>{money(p.last_price)}</td><td className="p-2">{money(p.market_value)}</td><td className="p-2">{money(p.unrealized_pnl)}</td></tr>)}</tbody>
        </table>{!account.positions.length && <p className="p-4 text-sm text-muted-foreground">{t('paper.noPositions')}</p>}</div></section>
        <section><h3 className="font-medium mb-2">{t('paper.trades')}</h3><div className="overflow-auto border rounded"><table className="w-full text-sm text-left">
          <thead className="bg-muted"><tr>{['time','ticker','action','quantity','price','realized_pnl','cashAfter'].map((key) => <th key={key} className="p-2">{t(`paper.${key}`)}</th>)}</tr></thead>
          <tbody>{account.trades.map((trade) => <tr key={trade.id} className="border-t"><td className="p-2 whitespace-nowrap">{new Date(trade.created_at).toLocaleString()}</td><td className="p-2 font-mono">{trade.ticker}</td><td className="p-2">{t(`paper.${trade.side}`)}</td><td className="p-2">{quantity(trade.quantity)}</td><td className="p-2">{money(trade.price)}</td><td className="p-2">{money(trade.realized_pnl)}</td><td className="p-2">{money(trade.cash_after)}</td></tr>)}</tbody>
        </table>{!account.trades.length && <p className="p-4 text-sm text-muted-foreground">{t('paper.noTrades')}</p>}</div></section>
      </>}
  </div>;
}
