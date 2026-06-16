// Paper tab — read-only forward-test performance panel. Mirrors the load/then/
// catch/loading pattern of reports-panel.tsx. Shows a per-sleeve metrics table,
// the graduation verdict, and the 3-sleeve equity-curve chart. No write controls.

import { Button } from '@/components/ui/button';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { paperService } from '@/services/paper-service';
import type { PaperPerformance, SleeveMetrics } from '@/types/paper';
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

// Canonical sleeve order (A/B order), mirrors the report module.
const SLEEVE_ORDER = ['scanner_agent', 'scanner_only', 'spy_benchmark'];

function orderedSleeves(sleeves: Record<string, SleeveMetrics>): string[] {
  const known = SLEEVE_ORDER.filter((n) => n in sleeves);
  const extra = Object.keys(sleeves).filter((n) => !SLEEVE_ORDER.includes(n));
  return [...known, ...extra];
}

function fmtPct(v: number | null): string {
  return v == null ? 'n/a' : `${(v * 100).toFixed(2)}%`;
}

function fmtDrawdown(v: number | null): string {
  // Already a ×100 percent — show with % directly, do NOT scale.
  return v == null ? 'n/a' : `${v.toFixed(2)}%`;
}

function fmtNum(v: number | null): string {
  return v == null ? 'n/a' : v.toFixed(2);
}

function fmtMoney(v: number | null): string {
  return v == null ? 'n/a' : `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function PaperPanel() {
  const { t } = useTranslation();
  const [data, setData] = useState<PaperPerformance | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    paperService.getPerformance()
      .then((d) => setData(d))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const sleeves = data?.sleeves ?? {};
  const names = orderedSleeves(sleeves);
  const verdict = data?.graduation;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-2 border-b">
        <div className="text-sm font-semibold">{t('paper.title', 'Paper Trading')}</div>
        <span className="text-xs text-muted-foreground">{names.length}</span>
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="icon" variant="ghost" className="h-7 w-7"
            disabled={loading} onClick={reload} title={t('common.refresh', 'Refresh')}
          >
            <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-3 space-y-6">
        {error && (
          <div className="text-xs text-red-600">{error}</div>
        )}

        {/* Per-sleeve metrics table */}
        <div>
          <Table className="text-xs">
            <TableHeader>
              <TableRow>
                <TableHead>{t('paper.colSleeve', 'Sleeve')}</TableHead>
                <TableHead className="text-right">{t('paper.colFinalEquity', 'Final equity')}</TableHead>
                <TableHead className="text-right">{t('paper.colTotalReturn', 'Total return')}</TableHead>
                <TableHead className="text-right">{t('paper.colSharpe', 'Sharpe')}</TableHead>
                <TableHead className="text-right">{t('paper.colMaxDrawdown', 'Max drawdown')}</TableHead>
                <TableHead className="text-right">{t('paper.colNTrades', '# Trades')}</TableHead>
                <TableHead className="text-right">{t('paper.colNMarks', '# Marks')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {names.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                    {t('paper.empty', 'No paper-trading data yet.')}
                  </TableCell>
                </TableRow>
              )}
              {names.map((name) => {
                const m = sleeves[name];
                const isBaseline = name === 'spy_benchmark';
                return (
                  <TableRow key={name} className={cn(isBaseline && 'bg-accent/30')}>
                    <TableCell className="font-mono font-bold">
                      {name}
                      {isBaseline && (
                        <span className="ml-2 text-[10px] uppercase text-muted-foreground">
                          {t('paper.baseline', 'baseline')}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{fmtMoney(m.final_equity)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtPct(m.total_return)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtNum(m.sharpe)}</TableCell>
                    <TableCell className="text-right tabular-nums">{fmtDrawdown(m.max_drawdown)}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.n_trades ?? 0}</TableCell>
                    <TableCell className="text-right tabular-nums">{m.n_marks ?? 0}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        {/* Graduation verdict */}
        {verdict && (
          <div>
            <div className="text-sm font-semibold mb-2">{t('paper.graduation', 'Graduation verdict')}</div>
            <div className={cn('text-sm font-bold mb-2', verdict.passed ? 'text-green-600' : 'text-red-600')}>
              {verdict.passed
                ? t('paper.pass', 'PASS')
                : t('paper.fail', 'FAIL')}
            </div>
            <ul className="list-disc pl-5 space-y-1 text-xs text-muted-foreground">
              {verdict.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
              {verdict.reasons.length === 0 && (
                <li>{t('paper.noClauses', 'No clauses evaluated.')}</li>
              )}
            </ul>
          </div>
        )}

        {/* Equity curve */}
        <div>
          <div className="text-sm font-semibold mb-2">{t('paper.equityCurve', 'Equity curve')}</div>
          <img
            src={paperService.equityChartUrl()}
            alt={t('paper.equityCurveAlt', 'Paper sleeves equity curve')}
            className="max-w-full h-auto border rounded"
          />
        </div>
      </div>
    </div>
  );
}
