// BatchReportDialog + runBatchReports — "batch run reports" for multi-selected
// tickers. Shared by the Screener table and the Watchlist tab so the two stay
// DRY.
//
// Each report is a SYNCHRONOUS ~60-120s call to POST /research/analyze (via
// analyzeService.runAnalyze) — reusing the existing endpoint, no backend route
// added. The dialog only collects the shared run options (objective + market)
// once; on confirm we close, clear the caller's selection, and drive a
// client-side concurrency pool (limit 2) that streams reports into Recent
// Reports as each finishes. Progress is surfaced via a single floating sonner
// toast updated in place (Promise.allSettled semantics — one ticker failing
// never stops the rest).

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { analyzeBus } from '@/services/analyze-bus';
import { analyzeService } from '@/services/analyze-service';
import type { Market, Objective, ReportLanguage } from '@/types/analyze';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

/** Hard cap — never run more than this many reports per batch. */
export const BATCH_REPORT_CAP = 20;

/** Client-side concurrency limit for the batch pool. Each run is ~1-2 min, so
 * 2 in flight balances throughput against hammering the (synchronous) backend. */
const POOL_LIMIT = 2;

const OBJECTIVES: Objective[] = [
  'general_research', 'target_price', 'short_term',
  'medium_term', 'long_term', 'earnings_review',
];

export interface BatchReportProgress {
  done: number;
  total: number;
  failed: number;
}

/**
 * Run an analysis report for each ticker via a concurrency pool (limit 2).
 * Resolves once every ticker has settled. `onProgress` fires after each
 * settle (success or failure). Each success calls notifyReportsChanged() so
 * the report streams into the Reports tab. One ticker failing does not stop
 * the rest (Promise.allSettled semantics, implemented manually for the pool).
 */
export async function runBatchReports(
  tickers: string[],
  opts: { objective: Objective; market: Market; reportLanguage: ReportLanguage },
  onProgress: (p: BatchReportProgress) => void,
): Promise<BatchReportProgress> {
  const total = tickers.length;
  let done = 0;
  let failed = 0;
  let cursor = 0;

  async function worker(): Promise<void> {
    for (;;) {
      const i = cursor;
      cursor += 1;
      if (i >= tickers.length) return;
      const ticker = tickers[i];
      try {
        await analyzeService.runAnalyze({
          ticker,
          objective: opts.objective,
          market: opts.market,
          // null => backend runs the full default section set (all 16).
          included_sections: null,
          use_personas: false,
          report_language: opts.reportLanguage,
        });
        // Stream into Recent Reports as soon as this one lands.
        analyzeBus.notifyReportsChanged();
      } catch {
        failed += 1;
      } finally {
        done += 1;
        onProgress({ done, total, failed });
      }
    }
  }

  const workers = Array.from({ length: Math.min(POOL_LIMIT, total) }, () => worker());
  await Promise.all(workers);
  return { done, total, failed };
}

interface BatchReportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Selected tickers (already de-duped). Capped to BATCH_REPORT_CAP on run. */
  tickers: string[];
  /** Default market — Screener rows know per-row market; Watchlist is US. */
  defaultMarket?: Market;
  /** Called after the batch is kicked off so the caller can clear its selection. */
  onStarted?: () => void;
}

/**
 * Small dialog: pick Objective + Market once, confirm to run N reports.
 * On confirm it closes the dialog, kicks off the pool, and drives a floating
 * progress toast — so the slow (minutes-long) batch never blocks the UI.
 */
export function BatchReportDialog({
  open,
  onOpenChange,
  tickers,
  defaultMarket = 'us',
  onStarted,
}: BatchReportDialogProps) {
  const { t, i18n } = useTranslation();
  const [objective, setObjective] = useState<Objective>('general_research');
  const [market, setMarket] = useState<Market>(defaultMarket);

  const capped = tickers.slice(0, BATCH_REPORT_CAP);
  const n = capped.length;
  const overCap = tickers.length > BATCH_REPORT_CAP;

  const reportLanguage: ReportLanguage =
    (i18n.resolvedLanguage || i18n.language || 'en').startsWith('zh') ? 'zh' : 'en';

  function handleConfirm() {
    if (n === 0) return;
    const toRun = capped;
    onOpenChange(false);
    onStarted?.();

    const toastId = `batch-report-${Date.now()}`;
    toast.loading(
      t('analyze.batch.progress', {
        done: 0, total: toRun.length, failed: 0,
        defaultValue: 'Batch analysis {{done}}/{{total}} (failed {{failed}})',
      }),
      { id: toastId },
    );

    void runBatchReports(
      toRun,
      { objective, market, reportLanguage },
      (p) => {
        toast.loading(
          t('analyze.batch.progress', {
            done: p.done, total: p.total, failed: p.failed,
            defaultValue: 'Batch analysis {{done}}/{{total}} (failed {{failed}})',
          }),
          { id: toastId },
        );
      },
    ).then((final) => {
      const msg = t('analyze.batch.done', {
        done: final.done - final.failed, total: final.total, failed: final.failed,
        defaultValue: 'Batch done — {{done}}/{{total}} reports ready (failed {{failed}})',
      });
      if (final.failed > 0) {
        toast.warning(msg, { id: toastId, duration: 8000 });
      } else {
        toast.success(msg, { id: toastId, duration: 8000 });
      }
    });
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t('analyze.batch.dialogTitle', 'Batch report')}</DialogTitle>
          <DialogDescription>
            {t('analyze.batch.dialogDesc', 'Run a deep analysis report for each selected ticker. Each takes ~1-2 min and streams into Recent Reports.')}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-1">
          {/* Objective */}
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase text-muted-foreground tracking-wide">
              {t('analyze.input.objective', 'Objective')}
            </label>
            <Select value={objective} onValueChange={(v) => setObjective(v as Objective)}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {OBJECTIVES.map((o) => (
                  <SelectItem key={o} value={o} className="text-sm">
                    {t(`analyze.objectives.${o}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Market */}
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase text-muted-foreground tracking-wide">
              {t('analyze.input.market', 'Market')}
            </label>
            <Select value={market} onValueChange={(v) => setMarket(v as Market)}>
              <SelectTrigger className="h-9 text-sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="us" className="text-sm">{t('analyze.markets.us', 'US')}</SelectItem>
                <SelectItem value="cn" className="text-sm">{t('analyze.markets.cn', 'A股')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {overCap && (
            <p className="text-xs text-amber-500">
              {t('analyze.batch.capNote', 'At most {{cap}} at a time — only the first {{cap}} will run.', { cap: BATCH_REPORT_CAP })}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button onClick={handleConfirm} disabled={n === 0}>
            {t('analyze.batch.run', 'Run {{count}} reports', { count: n })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
