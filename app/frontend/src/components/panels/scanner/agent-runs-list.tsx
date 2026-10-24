// Compact list of recent pipeline runs. Sits alongside the scanner watchlist
// rather than on its own route — keeps the user's mental model of "scan +
// agent analysis live in one panel".
//
// Click a row → open the AgentRunDetail dialog for that run.

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { pipelineService } from '@/services/pipeline-service';
import type { PipelineRunSummary, PipelineStatus } from '@/types/pipeline';
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AgentRunDetailDialog } from './agent-run-detail';

interface AgentRunsListProps {
  limit?: number;
}

export function AgentRunsList({ limit = 10 }: AgentRunsListProps) {
  const [runs, setRuns] = useState<PipelineRunSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openDetail, setOpenDetail] = useState<string | null>(null);
  const { t } = useTranslation();

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    pipelineService
      .listRuns({ limit })
      .then(setRuns)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [limit]);

  useEffect(() => { reload(); }, [reload]);

  if (error) {
    return (
      <div className="text-xs text-red-600 border border-red-200 rounded p-2 bg-red-50">
        Failed to load runs: {error}
      </div>
    );
  }

  if (!loading && runs.length === 0) return null;  // Don't clutter UI on empty.

  return (
    <div className="border rounded">
      <div className="flex items-center justify-between px-3 py-1.5 border-b bg-accent/30">
        <span className="text-xs font-medium">{t('scanner.agentRuns.title')}</span>
        <Button
          variant="ghost"
          size="sm"
          onClick={reload}
          disabled={loading}
          title={t('common.refresh')}
        >
          <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
        </Button>
      </div>

      <div className="divide-y">
        {runs.map((r) => (
          <button
            key={r.id}
            onClick={() => setOpenDetail(r.id)}
            className="w-full text-left px-3 py-1.5 hover:bg-accent/40 flex items-center gap-2 text-xs"
          >
            <span className="font-mono text-muted-foreground w-20 shrink-0">
              {r.id.slice(0, 10)}…
            </span>
            <span className="w-20 shrink-0">{r.template}</span>
            <span className="w-20 shrink-0 text-muted-foreground">
              top {r.top_n}
            </span>
            <StatusBadge status={r.status} />
            <span className="text-muted-foreground tabular-nums">
              {r.duration_seconds != null ? `${r.duration_seconds.toFixed(1)}s` : '—'}
            </span>
            <span className="ml-auto text-muted-foreground">
              {r.completed_at
                ? new Date(r.completed_at).toLocaleString()
                : r.created_at
                  ? new Date(r.created_at).toLocaleString()
                  : ''}
            </span>
          </button>
        ))}
      </div>

      {openDetail && (
        <AgentRunDetailDialog
          runId={openDetail}
          open={!!openDetail}
          onOpenChange={(o) => !o && setOpenDetail(null)}
        />
      )}
    </div>
  );
}


function StatusBadge({ status }: { status: PipelineStatus }) {
  const colors: Record<PipelineStatus, string> = {
    PENDING: 'bg-gray-100 text-gray-700',
    RUNNING: 'bg-blue-100 text-blue-700',
    COMPLETE: 'bg-green-100 text-green-700',
    ERROR: 'bg-red-100 text-red-700',
  };
  return (
    <span className={cn('inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium shrink-0',
      colors[status] ?? 'bg-gray-100')}>
      {status}
    </span>
  );
}
