// ResearchPanel — minimal UI for the per-stock research pipeline.
// Lets a user type a ticker, optionally enable personas, run research,
// and view the resulting HTML report inline. History list shows recent
// reports across all tickers — click one to load it back into the iframe.

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { researchService } from '@/services/research-service';
import type {
  ResearchReportDetail,
  ResearchReportSummary,
  RiskTolerance,
} from '@/types/research';
import { Loader2, Play, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

export function ResearchPanel() {
  const [ticker, setTicker] = useState('NVDA');
  const [usePersonas, setUsePersonas] = useState(true);
  const [risk, setRisk] = useState<RiskTolerance>('moderate');
  const { t } = useTranslation();

  const [running, setRunning] = useState(false);
  const [detail, setDetail] = useState<ResearchReportDetail | null>(null);
  const [iframeReportId, setIframeReportId] = useState<number | null>(null);

  const [recent, setRecent] = useState<ResearchReportSummary[]>([]);
  const [listLoading, setListLoading] = useState(false);

  const reloadList = useCallback(() => {
    setListLoading(true);
    researchService
      .listReports({ limit: 20 })
      .then(setRecent)
      .catch((e: Error) => toast.error(`list: ${e.message}`))
      .finally(() => setListLoading(false));
  }, []);

  useEffect(() => { reloadList(); }, [reloadList]);

  const run = useCallback(async () => {
    const t = ticker.trim().toUpperCase();
    if (!t) {
      toast.error('Enter a ticker first');
      return;
    }
    setRunning(true);
    setDetail(null);
    try {
      const result = await researchService.runResearch({
        ticker: t,
        use_personas: usePersonas,
        risk_tolerance: risk,
        report_goal: 'general_research',
      });
      setDetail(result);
      setIframeReportId(result.id);
      toast.success(`Research complete: ${result.ticker} (id ${result.id})`);
      reloadList();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRunning(false);
    }
  }, [ticker, usePersonas, risk, reloadList]);

  const loadPast = useCallback(async (id: number) => {
    try {
      const r = await researchService.getReport(id);
      setDetail(r);
      setIframeReportId(id);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, []);

  return (
    <div className="space-y-3">
      {/* ---- Run form ---- */}
      <div className="border rounded p-3 space-y-2 bg-accent/20">
        <div className="text-xs font-medium uppercase text-muted-foreground">
          Per-stock research
        </div>
        <div className="flex items-end gap-2 flex-wrap">
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">{t('scanner.research.ticker')}</label>
            <Input
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !running) run();
              }}
              className="w-28 h-8 text-sm uppercase font-mono"
              placeholder="NVDA"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Risk</label>
            <select
              value={risk}
              onChange={(e) => setRisk(e.target.value as RiskTolerance)}
              className="h-8 px-2 text-sm border rounded bg-background"
            >
              <option value="conservative">conservative</option>
              <option value="moderate">moderate</option>
              <option value="aggressive">aggressive</option>
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm h-8 cursor-pointer">
            <Checkbox
              checked={usePersonas}
              onCheckedChange={(v) => setUsePersonas(!!v)}
            />
            <span>{t('scanner.research.usePersonas')}</span>
          </label>
          <Button
            size="sm"
            onClick={run}
            disabled={running}
            className="ml-auto"
          >
            {running ? (
              <>
                <Loader2 className="size-3 mr-1 animate-spin" />
                Running… (30–90s)
              </>
            ) : (
              <>
                <Play className="size-3 mr-1" />
                Run research
              </>
            )}
          </Button>
        </div>
      </div>

      {/* ---- Current report summary ---- */}
      {detail && (
        <div className="border rounded p-3 space-y-2">
          <div className="flex items-baseline gap-2">
            <div className="text-base font-bold">{detail.ticker}</div>
            <div className="text-xs text-muted-foreground">
              id {detail.id} · {detail.scan_date} ·{' '}
              {detail.duration_seconds != null
                ? `${detail.duration_seconds.toFixed(1)}s`
                : '—'}
              {detail.use_personas ? ' · personas' : ''}
            </div>
          </div>

          <PlanBox plan={detail.plan} />
          <BacktestBox backtest={detail.backtest} />
          {detail.use_personas && detail.persona_assignments && (
            <PersonaBox assignments={detail.persona_assignments} />
          )}
        </div>
      )}

      {/* ---- HTML iframe ---- */}
      {iframeReportId != null && (
        <div className="border rounded overflow-hidden">
          <iframe
            key={iframeReportId}
            src={researchService.reportHtmlUrl(iframeReportId)}
            title={`Research report ${iframeReportId}`}
            className="w-full"
            style={{ height: 700, border: 0 }}
          />
        </div>
      )}

      {/* ---- History list ---- */}
      <div className="border rounded">
        <div className="flex items-center justify-between px-3 py-1.5 border-b bg-accent/30">
          <span className="text-xs font-medium">{t('scanner.research.recent')}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={reloadList}
            disabled={listLoading}
            title={t('common.refresh')}
          >
            <RefreshCw className={cn('size-3', listLoading && 'animate-spin')} />
          </Button>
        </div>
        {recent.length === 0 ? (
          <div className="px-3 py-2 text-xs text-muted-foreground">
            No research reports yet. Run one above.
          </div>
        ) : (
          <div className="divide-y">
            {recent.map((r) => (
              <button
                key={r.id}
                onClick={() => loadPast(r.id)}
                className={cn(
                  'w-full text-left px-3 py-1.5 hover:bg-accent/40 flex items-center gap-2 text-xs',
                  r.id === iframeReportId && 'bg-accent/30',
                )}
              >
                <span className="font-mono text-muted-foreground w-10 shrink-0">
                  #{r.id}
                </span>
                <span className="font-mono font-bold w-16 shrink-0">
                  {r.ticker}
                </span>
                <span className="w-24 shrink-0 text-muted-foreground">
                  {r.scan_date}
                </span>
                <span className="text-muted-foreground tabular-nums">
                  {r.duration_seconds != null
                    ? `${r.duration_seconds.toFixed(1)}s`
                    : '—'}
                </span>
                {r.use_personas && (
                  <span className="ml-auto text-purple-600 text-[10px] uppercase">
                    personas
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ---- Sub-blocks ----

function PlanBox({ plan }: { plan: ResearchReportDetail['plan'] }) {
  const isStandAside = plan.direction === 'stand_aside';
  return (
    <div
      className={cn(
        'rounded p-2 text-xs',
        isStandAside
          ? 'bg-yellow-50 border border-yellow-300'
          : 'bg-green-50 border border-green-300',
      )}
    >
      <div className="font-bold uppercase mb-1">
        Trade Plan: {plan.direction}
      </div>
      {isStandAside ? (
        <div>
          No actionable trade. Confidence: {plan.confidence}/100
        </div>
      ) : (
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <KV label="Entry" value={fmt$(plan.entry_price)} />
          <KV label="Target" value={fmt$(plan.target_price)} />
          <KV label="Stop" value={fmt$(plan.stop_price)} />
          <KV label="Horizon" value={`${plan.horizon_days}d`} />
          <KV label="Sizing" value={`${(plan.sizing_pct * 100).toFixed(2)}%`} />
          <KV label="Conf" value={`${plan.confidence}/100`} />
        </div>
      )}
      <div className="mt-2 text-muted-foreground">{plan.rationale}</div>
    </div>
  );
}

function BacktestBox({ backtest }: { backtest: ResearchReportDetail['backtest'] }) {
  return (
    <div className="rounded p-2 text-xs bg-blue-50 border border-blue-300">
      <div className="font-bold uppercase mb-1">
        Detector backtest ({backtest.sample_quality})
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <KV label="Matches" value={String(backtest.matches_found)} />
        {backtest.win_rate != null && (
          <>
            <KV label="Win rate" value={`${(backtest.win_rate * 100).toFixed(1)}%`} />
            <KV label="Avg PnL" value={fmtPct(backtest.avg_pnl_pct)} />
            <KV label="Max DD" value={fmtPct(backtest.max_drawdown_pct)} />
          </>
        )}
      </div>
      {backtest.caveat && (
        <div className="mt-1 text-orange-700">⚠ {backtest.caveat}</div>
      )}
    </div>
  );
}

function PersonaBox({ assignments }: { assignments: Record<string, unknown> }) {
  const { t } = useTranslation();
  const rows: { module: string; persona: string }[] = [];
  for (const mod of ['fundamentals', 'valuation', 'risk_position']) {
    const v = assignments[mod];
    rows.push({ module: mod, persona: typeof v === 'string' ? v : 'objective' });
  }
  const debate = assignments.debate;
  const debateLabel =
    Array.isArray(debate) && debate.length === 2
      ? `${debate[0]} vs ${debate[1]}`
      : '(none)';
  const rationale = (assignments._rationale as string | undefined) || '';
  return (
    <div className="rounded p-2 text-xs bg-purple-50 border border-purple-300">
      <div className="font-bold uppercase mb-1">{t('scanner.research.personaAssignments')}</div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {rows.map((r) => (
          <KV key={r.module} label={r.module} value={r.persona} />
        ))}
        <KV label="debate" value={debateLabel} />
      </div>
      {rationale && (
        <div className="mt-1 text-muted-foreground">{rationale}</div>
      )}
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex flex-col">
      <span className="text-[10px] uppercase text-muted-foreground">
        {label}
      </span>
      <span className="font-medium">{value}</span>
    </span>
  );
}

function fmt$(v: number | null): string {
  return v == null ? '—' : `$${v.toFixed(2)}`;
}
function fmtPct(v: number | null): string {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`;
}
