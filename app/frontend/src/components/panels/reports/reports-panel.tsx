// Reports tab — full-area list of all saved SOP reports. Replaces the small
// sidebar list. Supports batch-select delete; clicking a row pops the report
// in a viewer modal.

import { ReportViewerModal } from '@/components/panels/analyze/report-viewer-modal';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { analyzeBus } from '@/services/analyze-bus';
import { analyzeService } from '@/services/analyze-service';
import type { ResearchReportSummary } from '@/types/research';
import { RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

export function ReportsPanel() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ResearchReportSummary[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [loading, setLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [viewingId, setViewingId] = useState<number | null>(null);
  const [modalOpen, setModalOpen] = useState(false);

  const reload = useCallback(() => {
    setLoading(true);
    analyzeService.listReports(undefined, 200)
      .then((r) => {
        setRows(r);
        // Drop selections that no longer exist.
        setSelected((prev) => new Set([...prev].filter((id) => r.some((x) => x.id === id))));
      })
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);
  useEffect(() => analyzeBus.subscribeReportsChanged(reload), [reload]);

  const allSelected = rows.length > 0 && selected.size === rows.length;
  const toggleAll = () =>
    setSelected(allSelected ? new Set() : new Set(rows.map((r) => r.id)));
  const toggleOne = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const openReport = (id: number) => {
    setViewingId(id);
    setModalOpen(true);
  };

  const deleteSelected = async () => {
    const ids = [...selected];
    if (ids.length === 0) return;
    if (!window.confirm(t('reports.deleteSelectedConfirm', {
      count: ids.length,
      defaultValue: 'Delete {{count}} selected report(s)?',
    }))) return;
    setDeleting(true);
    try {
      await Promise.all(ids.map((id) => analyzeService.deleteReport(id)));
      setSelected(new Set());
      if (viewingId != null && ids.includes(viewingId)) {
        setModalOpen(false);
        setViewingId(null);
      }
      toast.success(t('reports.deletedN', {
        count: ids.length, defaultValue: '{{count}} report(s) deleted',
      }));
      reload();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-3 py-2 border-b">
        <div className="text-sm font-semibold">{t('analyze.reports.title')}</div>
        <span className="text-xs text-muted-foreground">{rows.length}</span>
        <div className="ml-auto flex items-center gap-2">
          {selected.size > 0 && (
            <Button
              size="sm"
              variant="destructive"
              className="h-7 text-xs"
              disabled={deleting}
              onClick={deleteSelected}
            >
              <Trash2 className="size-3 mr-1" />
              {t('reports.deleteSelected', {
                count: selected.size,
                defaultValue: 'Delete selected ({{count}})',
              })}
            </Button>
          )}
          <Button
            size="icon" variant="ghost" className="h-7 w-7"
            disabled={loading} onClick={reload} title={t('common.refresh')}
          >
            <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">
                <Checkbox checked={allSelected} onCheckedChange={toggleAll}
                          aria-label="select all" />
              </TableHead>
              <TableHead className="w-14">{t('reports.colId', 'ID')}</TableHead>
              <TableHead>{t('reports.colTicker', 'Ticker')}</TableHead>
              <TableHead>{t('reports.colDate', 'Date')}</TableHead>
              <TableHead className="text-right">⏱</TableHead>
              <TableHead></TableHead>
              <TableHead className="w-10"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  {t('analyze.reports.noReports', 'No reports yet')}
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => (
              <TableRow
                key={r.id}
                className={cn('cursor-pointer', selected.has(r.id) && 'bg-accent/30')}
                onClick={() => openReport(r.id)}
              >
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selected.has(r.id)}
                    onCheckedChange={() => toggleOne(r.id)}
                    aria-label={`select ${r.id}`}
                  />
                </TableCell>
                <TableCell className="font-mono text-muted-foreground">#{r.id}</TableCell>
                <TableCell className="font-mono font-bold">{r.ticker}</TableCell>
                <TableCell className="text-muted-foreground">{r.scan_date}</TableCell>
                <TableCell className="text-right tabular-nums text-muted-foreground">
                  {r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '—'}
                </TableCell>
                <TableCell>
                  {r.use_personas && (
                    <span className="text-purple-600 text-[10px] uppercase">personas</span>
                  )}
                </TableCell>
                <TableCell onClick={(e) => e.stopPropagation()}>
                  <Button
                    size="icon" variant="ghost"
                    className="h-6 w-6 text-muted-foreground hover:text-red-600"
                    title={t('common.delete')}
                    onClick={() => {
                      if (window.confirm(t('analyze.reports.deleteConfirm', {
                        id: r.id, ticker: r.ticker,
                        defaultValue: 'Delete report #{{id}} ({{ticker}})?',
                      }))) {
                        analyzeService.deleteReport(r.id)
                          .then(() => { analyzeBus.notifyReportsChanged(); })
                          .catch((e: Error) => toast.error(e.message));
                      }
                    }}
                  >
                    <Trash2 className="size-3" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <ReportViewerModal reportId={viewingId} open={modalOpen} onOpenChange={setModalOpen} />
    </div>
  );
}
