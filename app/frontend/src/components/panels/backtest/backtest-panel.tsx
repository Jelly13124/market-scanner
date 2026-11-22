import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TabService } from '@/services/tab-service';
import { useTabsContext } from '@/contexts/tabs-context';
import { scannerService } from '@/services/scanner-service';
import { strategyService } from '@/services/strategy-service';
import { watchlistService } from '@/services/watchlist-service';
import type { StrategyResponse, StrategySpec } from '@/types/strategy';
import type { UserWatchlist } from '@/types/watchlist';
import { useEffect, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { StrategyList } from '../lab/strategy-list';
import { SpecViewer } from '../lab/spec-viewer';
import { DailyRuleEditor } from '../shared/daily-rule-editor';
import { defaultDailyGroup, editableDailyGroup, type DailyRuleGroup } from '@/types/daily-rule';
import { BacktestHistory } from '../lab/backtest-history';
import { BacktestResult } from '../lab/backtest-result';
import { BacktestRunner } from '../lab/backtest-runner';

export function BacktestPanel({strategyId: id}: {strategyId?: number}) {
  const { t } = useTranslation();
  const { openTab } = useTabsContext();
  const setId = (selected: number | null) => openTab({id: 'backtest', ...TabService.createBacktestTab(selected ?? undefined)});
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
      <aside className="w-52 shrink-0"><StrategyList selectedId={id ?? null} onSelect={setId} /></aside>
      <main className="flex-1 min-w-0 overflow-auto p-4 space-y-4">
        {error && <p role="alert" className="text-red-600">{error}</p>}
        {loading ? <p>{t('common.loading')}</p> : strategy ? <>
          <BacktestSetup key={strategy.id + ':' + strategy.version} strategy={strategy} onSaved={reload} onDirty={() => setDirty(true)} />
          <details className="border rounded"><summary className="px-4 py-2 cursor-pointer">{t('backtest.advanced')}</summary><div className="max-h-96 overflow-auto"><SpecViewer strategy={strategy} onSpecUpdated={reload} /></div></details>
          <BacktestRunner disabled={dirty} strategy={strategy} onReload={reload} onComplete={setResultId} />
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
  const fromReport = strategy.source_report_id != null;
  const [lists, setLists] = useState<UserWatchlist[]>([]);
  const [universe, setUniverse] = useState(spec.universe.kind === 'watchlist' ? `watchlist:${spec.universe.watchlist_id}` : spec.universe.kind);
  const first = spec.entry.signals[0];
  const savedDaily = editableDailyGroup(spec.entry) ? spec.entry : null;
  const [dailyGroup, setDailyGroup] = useState(savedDaily ?? defaultDailyGroup());
  const [rule, setRule] = useState(savedDaily ? 'daily' : spec.entry.signals.length === 1 && ['ma_cross', 'rsi'].includes(String(first?.type)) ? String(first.type) : 'custom');
  const [fast, setFast] = useState(String(first?.fast ?? 20));
  const [slow, setSlow] = useState(String(first?.slow ?? 50));
  const [level, setLevel] = useState(String(first?.level ?? 30));
  const [start, setStart] = useState(spec.backtest_config.start_date ?? '2024-01-01');
  const [end, setEnd] = useState(spec.backtest_config.end_date ?? localToday());
  const [cash, setCash] = useState(String(spec.backtest_config.starting_capital_usd ?? 100000));
  const [allocation, setAllocation] = useState(String(Number(spec.sizing.pct ?? 0.05) * 100));
  const [maxPositions, setMaxPositions] = useState(String(spec.backtest_config.max_concurrent_positions ?? 10));
  const [commission, setCommission] = useState(String(spec.backtest_config.commission_bps ?? 5));
  const [slippage, setSlippage] = useState(String(spec.backtest_config.slippage_bps ?? 5));
  const pctStopIndex = spec.exit.findIndex(e => e.type === 'stop_loss' && e.mode === 'pct');
  const savedStop = pctStopIndex < 0 ? '' : String(Number(spec.exit[pctStopIndex].value) * 100);
  const [stop, setStop] = useState(savedStop);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!fromReport) watchlistService.list().then(setLists).catch((e: Error) => setError(e.message));
  }, [fromReport]);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('');
    if (start >= end) { setError(t('backtest.dateError')); return; }
    if (rule === 'ma_cross' && Number(fast) >= Number(slow)) { setError(t('backtest.maError')); return; }
    setBusy(true);
    try {
      const exits = [...spec.exit];
      if (stop !== savedStop) {
        const replacement = stop ? [{type: 'stop_loss', mode: 'pct', value: Number(stop) / 100}] : [];
        if (pctStopIndex < 0) exits.push(...replacement);
        else exits.splice(pctStopIndex, 1, ...replacement);
      }
      const next: StrategySpec = { ...spec,
        universe: universe === 'snapshot' ? spec.universe : universe.startsWith('watchlist:') ? { kind: 'watchlist', watchlist_id: Number(universe.split(':')[1]) } : { kind: universe as 'sp500' | 'nasdaq100' },
        entry: rule === 'custom' ? spec.entry : rule === 'daily' ? dailyGroup : { combiner: 'and', signals: [rule === 'ma_cross'
          ? { type: 'ma_cross', fast: Number(fast), slow: Number(slow), direction: 'golden' }
          : { type: 'rsi', period: 14, level: Number(level), direction: 'oversold_buy' }] },
        exit: exits,
        sizing: fromReport ? {type: 'fixed_pct', pct: Number(allocation) / 100} : spec.sizing,
        backtest_config: { ...spec.backtest_config,
          ...(fromReport ? {max_concurrent_positions: Number(maxPositions)} : {}), start_date: start, end_date: end, starting_capital_usd: Number(cash), commission_bps: Number(commission), slippage_bps: Number(slippage) },
      };
      await strategyService.update(strategy.id, { spec_json: next, expected_version: strategy.version }); await onSaved();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const field = (key: string, value: string, set: (v: string) => void, type = 'number', min = '0', max?: string, required = true) =>
    <label className="text-xs space-y-1" key={key}><span className="block">{t(`backtest.${key}`)}</span><Input aria-label={t(`backtest.${key}`)} type={type} value={value} min={min} max={max} step={type === 'number' ? (['fast', 'slow', 'maxPositions'].includes(key) ? '1' : 'any') : undefined} required={required} onChange={(e) => set(e.target.value)} /></label>;
  return <form onSubmit={save} onChange={onDirty} className="border rounded p-4 space-y-3">
    <h3 className="font-medium">{strategy.name}</h3>
    {strategy.source_report_id != null && <p className="text-sm">{t('draft.source', {report: strategy.source_report_id, signal: strategy.source_scan_result_id})}</p>}
    <p className="text-xs text-muted-foreground">{t('backtest.saveHint')}</p>
    <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
      <label className="text-xs space-y-1"><span className="block">{t('backtest.universe')}</span><select aria-label={t('backtest.universe')} className="w-full border rounded h-9 bg-background px-2" disabled={spec.universe.kind === 'snapshot'} value={universe} onChange={(e) => setUniverse(e.target.value)}>
        {spec.universe.kind === 'snapshot' && <option value="snapshot">{t('draft.snapshot', {id: spec.universe.snapshot_id})}</option>}
        <option value="sp500">S&amp;P 500</option><option value="nasdaq100">Nasdaq 100</option>
        {lists.map((list) => <option key={list.id} value={`watchlist:${list.id}`}>{list.name} ({list.tickers.length})</option>)}
      </select></label>
      <label className="text-xs space-y-1"><span className="block">{t('backtest.rule')}</span><select aria-label={t('backtest.rule')} className="w-full border rounded h-9 bg-background px-2" value={rule} onChange={(e) => setRule(e.target.value)}>{!fromReport && <><option value="ma_cross">{t('backtest.maRule')}</option><option value="rsi">{t('backtest.rsiRule')}</option></>}<option value="daily">{t('dailyRules.title')}</option><option value="custom">{t('backtest.keepAdvanced')}</option></select></label>
      {rule === 'daily' && <div className="col-span-full space-y-2">
        {!fromReport && <ScannerRulePicker onSelect={setDailyGroup} />}
        <DailyRuleEditor group={dailyGroup} onChange={setDailyGroup} />
      </div>}
      {rule === 'ma_cross' && <>{field('fast', fast, setFast, 'number', '2', '500')}{field('slow', slow, setSlow, 'number', '2', '500')}</>}
      {rule === 'rsi' && field('rsiLevel', level, setLevel, 'number', '0', '100')}
      {field('start', start, setStart, 'date')}{field('end', end, setEnd, 'date')}{field('cash', cash, setCash, 'number', '1')}
      {fromReport && <>
        {field('allocation', allocation, setAllocation, 'number', '0.5', '100')}
        {field('maxPositions', maxPositions, setMaxPositions, 'number', '1', '100')}
      </>}
      {field('commission', commission, setCommission, 'number', '0', '100')}{field('slippage', slippage, setSlippage, 'number', '0', '100')}{field('stop', stop, setStop, 'number', '0.01', '100', pctStopIndex >= 0 && spec.exit.length === 1)}
    </div>
    {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
    <Button type="submit" disabled={busy || (rule === 'daily' && dailyGroup.signals.length === 0)}>{t('backtest.save')}</Button>
    <p className="text-xs text-muted-foreground">{t('backtest.dataHint')}</p>
  </form>;
}

function ScannerRulePicker({ onSelect }: {onSelect: (group: DailyRuleGroup) => void}) {
  const { t } = useTranslation();
  const [choices, setChoices] = useState<{id: number; name: string; group: DailyRuleGroup}[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    scannerService.listConfigs().then(configs => {
      if (active) setChoices(configs.flatMap(config => {
        const group = config.weights?.rule_group as DailyRuleGroup | undefined;
        return group ? [{id: config.id, name: config.name, group}] : [];
      }));
    }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, []);
  return <label className="block text-xs">{t('dailyRules.import')}
    <select aria-label={t('dailyRules.import')} className="w-full rounded border bg-background p-2"
      value="" onChange={e => {
        const source = choices.find(c => c.id === Number(e.target.value));
        if (source) onSelect(source.group);
      }}>
      <option value="">{t('dailyRules.chooseConfig')}</option>
      {choices.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
    </select>
    {error && <span role="alert">{error}</span>}
  </label>;
}

function localToday(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}
