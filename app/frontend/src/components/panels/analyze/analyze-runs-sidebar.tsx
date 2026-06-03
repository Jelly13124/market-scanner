// Right-edge sidebar for the Analyze panel (Task 11).
//
// Lists the concurrent analyze runs from the hoisted store (AnalyzeRunsProvider,
// mounted above the tab switcher) with a live elapsed timer; click a completed
// run to open its report in the viewer modal. Because the state lives above the
// tabs, the list survives switching to another tab and back.

import { Button } from '@/components/ui/button';
import { useAnalyzeRuns } from '@/contexts/analyze-runs-context';
import { cn } from '@/lib/utils';
import { getOneClickUseCanvas, setOneClickUseCanvas } from '@/services/analyze-config-snapshot';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ReportViewerModal } from './report-viewer-modal';

function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  return `${m}:${(s % 60).toString().padStart(2, '0')}`;
}

export function AnalyzeRunsSidebar() {
  const { runs, clearFinished } = useAnalyzeRuns();
  const { t } = useTranslation();
  const [viewId, setViewId] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [useCanvas, setUseCanvas] = useState(() => getOneClickUseCanvas());

  // Tick once a second while anything is running, to advance elapsed timers.
  const anyRunning = runs.some((r) => r.status === 'running');
  useEffect(() => {
    if (!anyRunning) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [anyRunning]);

  const hasFinished = runs.some((r) => r.status !== 'running');

  return (
    <aside className="w-56 shrink-0 border-l bg-background flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b">
        <span className="text-xs uppercase font-medium tracking-wider text-muted-foreground">
          {t('analyze.runsSidebar.title')}
        </span>
        {hasFinished && (
          <Button
            size="sm"
            variant="ghost"
            className="h-6 text-[11px] px-2"
            onClick={clearFinished}
          >
            {t('analyze.runsSidebar.clearFinished')}
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-auto p-2 space-y-1">
        {runs.length === 0 ? (
          <div className="text-xs text-muted-foreground px-1 py-2">
            {t('analyze.runsSidebar.empty')}
          </div>
        ) : (
          runs.map((r) => {
            const elapsed = (r.finishedAt ?? now) - r.startedAt;
            const isDone = r.status === 'done';
            return (
              <button
                key={r.id}
                type="button"
                disabled={!isDone}
                onClick={() => {
                  if (isDone && r.reportId != null) setViewId(r.reportId);
                }}
                title={
                  isDone
                    ? t('analyze.runsSidebar.openReport')
                    : r.status === 'failed'
                      ? r.error
                      : t('analyze.runsSidebar.running')
                }
                className={cn(
                  'w-full flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs',
                  isDone ? 'hover:bg-accent/60 cursor-pointer' : 'cursor-default',
                )}
              >
                {r.status === 'running' && (
                  <Loader2 className="size-3 animate-spin text-muted-foreground shrink-0" />
                )}
                {r.status === 'done' && (
                  <CheckCircle2 className="size-3 text-green-600 shrink-0" />
                )}
                {r.status === 'failed' && (
                  <XCircle className="size-3 text-red-500 shrink-0" />
                )}
                <span className="font-medium truncate flex-1">{r.ticker}</span>
                <span className="tabular-nums text-muted-foreground shrink-0">
                  {r.status === 'failed' ? '—' : fmtElapsed(elapsed)}
                </span>
              </button>
            );
          })
        )}
      </div>

      <label
        className="flex items-center gap-2 border-t px-3 py-2 text-[11px] text-muted-foreground cursor-pointer"
        title={t('analyze.runsSidebar.useCanvasHint')}
      >
        <input
          type="checkbox"
          className="size-3"
          checked={useCanvas}
          onChange={(e) => { setOneClickUseCanvas(e.target.checked); setUseCanvas(e.target.checked); }}
        />
        {t('analyze.runsSidebar.useCanvas')}
      </label>

      <ReportViewerModal
        reportId={viewId}
        open={viewId != null}
        onOpenChange={(o) => {
          if (!o) setViewId(null);
        }}
      />
    </aside>
  );
}
