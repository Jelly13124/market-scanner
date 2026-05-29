// Recent reports for the current ticker (or all tickers if blank).
// Click a row → load that report's HTML into the iframe.

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { analyzeBus } from '@/services/analyze-bus';
import { analyzeService } from '@/services/analyze-service';
import type { ResearchReportSummary } from '@/types/research';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

interface ReportListProps {
  tickerFilter?: string;
  currentReportId: number | null;
  onSelect: (reportId: number) => void;
  onDelete?: (reportId: number) => void;
}

export function ReportList({ tickerFilter, currentReportId, onSelect, onDelete }: ReportListProps) {
  const [rows, setRows] = useState<ResearchReportSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const { t } = useTranslation();

  const reload = useCallback(() => {
    setLoading(true);
    analyzeService.listReports(tickerFilter)
      .then(setRows)
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, [tickerFilter]);

  useEffect(() => { reload(); }, [reload]);
  // Refresh when the report set changes (new run lands, or a delete).
  useEffect(() => analyzeBus.subscribeReportsChanged(reload), [reload]);

  return (
    <div className="border rounded">
      <div className="flex items-center justify-between px-3 py-1.5 border-b bg-accent/30">
        <span className="text-xs font-medium">
          {tickerFilter ? t('analyze.reports.titleFor', { ticker: tickerFilter }) : t('analyze.reports.title')}
        </span>
        <Button
          variant="ghost" size="sm"
          onClick={reload} disabled={loading} title={t('common.refresh')}
        >
          <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
        </Button>
      </div>
      {rows.length === 0 ? (
        <div className="px-3 py-2 text-xs text-muted-foreground">
          {t('analyze.reports.noReports')}
        </div>
      ) : (
        <div className="divide-y max-h-60 overflow-y-auto">
          {rows.map((r) => (
            <div
              key={r.id}
              className={cn(
                'group flex items-center gap-2 text-xs pr-1 hover:bg-accent/40',
                r.id === currentReportId && 'bg-accent/30',
              )}
            >
              <button
                onClick={() => onSelect(r.id)}
                className="flex-1 min-w-0 text-left px-3 py-1.5 flex items-center gap-2"
              >
                <span className="font-mono text-muted-foreground w-9 shrink-0">#{r.id}</span>
                <span className="font-mono font-bold w-14 shrink-0 truncate">{r.ticker}</span>
                <span className="w-20 shrink-0 text-muted-foreground">{r.scan_date}</span>
                <span className="text-muted-foreground tabular-nums">
                  {r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '—'}
                </span>
                {r.use_personas && (
                  <span className="ml-auto text-purple-600 text-[10px] uppercase">personas</span>
                )}
              </button>
              {onDelete && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 shrink-0 text-muted-foreground hover:text-red-600 opacity-0 group-hover:opacity-100"
                  title={t('common.delete')}
                  onClick={() => {
                    if (window.confirm(t('analyze.reports.deleteConfirm', {
                      id: r.id, ticker: r.ticker,
                      defaultValue: 'Delete report #{{id}} ({{ticker}})?',
                    }))) {
                      onDelete(r.id);
                    }
                  }}
                >
                  <Trash2 className="size-3" />
                </Button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
