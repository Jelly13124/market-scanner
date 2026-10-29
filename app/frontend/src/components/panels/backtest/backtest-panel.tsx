import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { strategyService } from '@/services/strategy-service';
import { watchlistService } from '@/services/watchlist-service';
import type { StrategyResponse, StrategySpec } from '@/types/strategy';
import type { UserWatchlist } from '@/types/watchlist';
import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { StrategyList } from '../lab/strategy-list';
import { SpecViewer } from '../lab/spec-viewer';
import { BacktestHistory } from '../lab/backtest-history';
import { BacktestResult } from '../lab/backtest-result';
import { BacktestRunner } from '../lab/backtest-runner';

export function BacktestPanel() {
  const { t } = useTranslation();
  const [id, setId] = useState<number | null>(null);
  const [strategy, setStrategy] = useState<StrategyResponse | null>(null);
  const [resultId, setResultId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [dirty, setDirty] = useState(false);
  const reload = async () => {
    if (id == null) { setStrategy(null); return; }
    setLoading(true); setError('');
    try {
      const loaded = await strategyService.get(id);
      setStrategy(loaded);
      setDirty(!loaded.spec_json.backtest_config.start_date || !loaded.spec_json.backtest_config.end_date);
    }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  };
  useEffect(() => { setStrategy(null); setResultId(null); void reload(); }, [id]);
  return <div className="h-full flex flex-col overflow-hidden">
    <header className="border-b px-5 py-3"><h2 className="font-semibold">{t('backtest.title')} <span className="ml-2 rounded border px-2 py-0.5 text-xs font-normal text-muted-foreground">{t('backtest.status')}</span></h2><p className="text-sm text-muted-foreground">{t('backtest.subtitle')}</p><p className="mt-1 text-xs text-muted-foreground">{t('backtest.limitations')}</p></header>
    <div className="flex flex-1 min-h-0">
      <aside className="w-52 shrink-0"><StrategyList selectedId={id} onSelect={setId} /></aside>
      <main className="flex-1 min-w-0 overflow-auto p-4 space-y-4">
        {error && <p role="alert" className="text-red-600">{error}</p>}
        {loading ? <p>{t('common.loading')}</p> : strategy ? <>
          <BacktestSetup key={strategy.id + ':' + strategy.version} strategy={strategy} onSaved={reload} onDirty={() => setDirty(true)} />
          <details className="border rounded"><summary className="px-4 py-2 cursor-pointer">{t('backtest.advanced')}</summary><div className="max-h-96 overflow-auto"><SpecViewer strategy={strategy} onSpecUpdated={reload} /></div></details>
          <BacktestRunner disabled={dirty} strategyId={strategy.id} onComplete={setResultId} />
          {resultId != null && <BacktestResult key={resultId} backtestId={resultId} />}
          <BacktestHistory strategyId={strategy.id} selectedBacktestId={resultId} onSelectBacktest={setResultId} />
        </> : <p className="p-8 text-muted-foreground">{t('backtest.empty')}</p>}
      </main>
    </div>
  </div>;
}

function BacktestSetup({ strategy, onSaved, onDirty }: { strategy: StrategyResponse; onSaved: () => Promise<void>; onDirty: () => void }) {
  const { t } = useTranslation();
  const spec = strategy.spec_json;
  const [lists, setLists] = useState<UserWatchlist[]>([]);
  const [universe, setUniverse] = useState(spec.universe.kind === 'watchlist' ? `watchlist:${spec.universe.watchlist_id}` : spec.universe.kind);
  const first = spec.entry.signals[0];
  const [rule, setRule] = useState(spec.entry.signals.length === 1 && ['ma_cross', 'rsi'].includes(String(first?.type)) ? String(first.type) : 'custom');
  const [fast, setFast] = useState(String(first?.fast ?? 20));
  const [slow, setSlow] = useState(String(first?.slow ?? 50));
  const [level, setLevel] = useState(String(first?.level ?? 30));
  const [start, setStart] = useState(spec.backtest_config.start_date ?? '2024-01-01');
  const [end, setEnd] = useState(spec.backtest_config.end_date ?? localToday());
  const [cash, setCash] = useState(String(spec.backtest_config.starting_capital_usd ?? 100000));
  const [commission, setCommission] = useState(String(spec.backtest_config.commission_bps ?? 5));
  const [slippage, setSlippage] = useState(String(spec.backtest_config.slippage_bps ?? 5));
  const [stop, setStop] = useState(String(Number(spec.exit.find((e) => e.type === 'stop_loss' && e.mode === 'pct')?.value ?? 0.05) * 100));
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { watchlistService.list().then(setLists).catch((e) => setError((e as Error).message)); }, []);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    if (start >= end) { setError(t('backtest.dateError')); return; }
    if (rule === 'ma_cross' && Number(fast) >= Number(slow)) { setError(t('backtest.maError')); return; }
    setBusy(true);
    try {
      const next: StrategySpec = { ...spec,
        universe: universe.startsWith('watchlist:') ? { kind: 'watchlist', watchlist_id: Number(universe.split(':')[1]) } : { kind: universe as 'sp500' | 'nasdaq100' },
        entry: rule === 'custom' ? spec.entry : { combiner: 'and', signals: [rule === 'ma_cross'
          ? { type: 'ma_cross', fast: Number(fast), slow: Number(slow), direction: 'golden' }
          : { type: 'rsi', period: 14, level: Number(level), direction: 'oversold_buy' }] },
        exit: [{ type: 'stop_loss', mode: 'pct', value: Number(stop) / 100 }, ...spec.exit.filter((e) => e.type !== 'stop_loss')],
        backtest_config: { ...spec.backtest_config, start_date: start, end_date: end, starting_capital_usd: Number(cash), commission_bps: Number(commission), slippage_bps: Number(slippage) },
      };
      await strategyService.update(strategy.id, { spec_json: next }); await onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const field = (key: string, value: string, set: (v: string) => void, type = 'number', min = '0', max?: string) =>
    <label className="text-xs space-y-1" key={key}><span className="block">{t(`backtest.${key}`)}</span><Input aria-label={t(`backtest.${key}`)} type={type} value={value} min={min} max={max} step={type === 'number' ? (['fast', 'slow'].includes(key) ? '1' : 'any') : undefined} required onChange={(e) => set(e.target.value)} /></label>;
  return <form onSubmit={save} onChange={onDirty} className="border rounded p-4 space-y-3">
    <h3 className="font-medium">{strategy.name}</h3>
    <p className="text-xs text-muted-foreground">{t('backtest.saveHint')}</p>
    <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
      <label className="text-xs space-y-1"><span className="block">{t('backtest.universe')}</span><select aria-label={t('backtest.universe')} className="w-full border rounded h-9 bg-background px-2" value={universe} onChange={(e) => setUniverse(e.target.value)}>
        <option value="sp500">S&amp;P 500</option><option value="nasdaq100">Nasdaq 100</option>
        {lists.map((list) => <option key={list.id} value={`watchlist:${list.id}`}>{list.name} ({list.tickers.length})</option>)}
      </select></label>
      <label className="text-xs space-y-1"><span className="block">{t('backtest.rule')}</span><select aria-label={t('backtest.rule')} className="w-full border rounded h-9 bg-background px-2" value={rule} onChange={(e) => setRule(e.target.value)}><option value="ma_cross">{t('backtest.maRule')}</option><option value="rsi">{t('backtest.rsiRule')}</option><option value="custom">{t('backtest.keepAdvanced')}</option></select></label>
      {rule === 'ma_cross' && <>{field('fast', fast, setFast, 'number', '2', '500')}{field('slow', slow, setSlow, 'number', '2', '500')}</>}
      {rule === 'rsi' && field('rsiLevel', level, setLevel, 'number', '0', '100')}
      {field('start', start, setStart, 'date')}{field('end', end, setEnd, 'date')}{field('cash', cash, setCash, 'number', '1')}
      {field('commission', commission, setCommission, 'number', '0', '100')}{field('slippage', slippage, setSlippage, 'number', '0', '100')}{field('stop', stop, setStop, 'number', '0.01', '100')}
    </div>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <Button type="submit" disabled={busy}>{t('backtest.save')}</Button>
    <p className="text-xs text-muted-foreground">{t('backtest.dataHint')}</p>
  </form>;
}

function localToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}
