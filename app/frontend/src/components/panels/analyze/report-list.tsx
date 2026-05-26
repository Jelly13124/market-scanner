// Recent reports for the current ticker (or all tickers if blank).
// Click a row → load that report's HTML into the iframe.

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { analyzeService } from '@/services/analyze-service';
import type { ResearchReportSummary } from '@/types/research';
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

interface ReportListProps {
  tickerFilter?: string;
  currentReportId: number | null;
  onSelect: (reportId: number) => void;
}

export function ReportList({ tickerFilter, currentReportId, onSelect }: ReportListProps) {
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
            <button
              key={r.id}
              onClick={() => onSelect(r.id)}
              className={cn(
                'w-full text-left px-3 py-1.5 hover:bg-accent/40',
                'flex items-center gap-2 text-xs',
                r.id === currentReportId && 'bg-accent/30',
              )}
            >
              <span className="font-mono text-muted-foreground w-10 shrink-0">
                #{r.id}
              </span>
              <span className="font-mono font-bold w-16 shrink-0">{r.ticker}</span>
              <span className="w-24 shrink-0 text-muted-foreground">{r.scan_date}</span>
              <span className="text-muted-foreground tabular-nums">
                {r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '—'}
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
  );
}
