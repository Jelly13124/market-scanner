// AgentRunDetail dialog — polls /pipeline/runs/{id} until COMPLETE/ERROR,
// renders per-ticker scanner badge + grid of agent signals + portfolio_manager
// decisions.

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { pipelineService } from '@/services/pipeline-service';
import type {
  AgentDecision,
  AnalystSignal,
  PipelineRunDetail,
} from '@/types/pipeline';
import type { Direction } from '@/types/scanner';
import { ArrowDown, ArrowUp, Loader2, Minus, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

interface AgentRunDetailDialogProps {
  runId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function AgentRunDetailDialog({
  runId,
  open,
  onOpenChange,
}: AgentRunDetailDialogProps) {
  const [detail, setDetail] = useState<PipelineRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    setError(null);
    const ctrl = new AbortController();
    pipelineService
      .pollUntilDone(runId, { intervalMs: 2000, signal: ctrl.signal })
      .then((d) => { if (!cancelled) setDetail(d); })
      .catch((e: Error) => { if (!cancelled) setError(e.message); });
    // Also fetch once immediately so users see RUNNING state without waiting
    // for the first poll interval.
    pipelineService.getRun(runId)
      .then((d) => { if (!cancelled) setDetail((prev) => prev ?? d); })
      .catch(() => { /* swallow — pollUntilDone owns retries */ });
    return () => { cancelled = true; ctrl.abort(); };
  }, [runId]);

  const status = detail?.status ?? 'PENDING';
  const isDone = status === 'COMPLETE' || status === 'ERROR';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Pipeline run <span className="font-mono text-xs">{runId.slice(0, 12)}…</span>
            <StatusBadge status={status} />
          </DialogTitle>
          <DialogDescription className="flex items-center gap-3 text-xs">
            {detail?.template && <span>template: <span className="font-medium">{detail.template}</span></span>}
            {detail?.top_n != null && <span>top_n: {detail.top_n}</span>}
            {detail?.duration_seconds != null && (
              <span>duration: {detail.duration_seconds.toFixed(1)}s</span>
            )}
          </DialogDescription>
        </DialogHeader>

        {!isDone && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-8 justify-center">
            <Loader2 className="size-4 animate-spin" />
            {status === 'PENDING' ? 'Queued…' : 'Running scanner + agent workflow…'}
          </div>
        )}

        {status === 'ERROR' && detail?.error && (
          <div className="text-sm border border-red-200 bg-red-50 dark:bg-red-950 dark:border-red-800 rounded p-3">
            <div className="font-medium text-red-700 dark:text-red-300 flex items-center gap-1 mb-1">
              <XCircle className="size-4" /> Run failed
            </div>
            <pre className="text-xs overflow-x-auto whitespace-pre-wrap">{detail.error}</pre>
          </div>
        )}

        {error && (
          <div className="text-sm text-red-600 border border-red-200 rounded p-2 bg-red-50">
            Polling error: {error}
          </div>
        )}

        {status === 'COMPLETE' && detail && (
          <RunResults detail={detail} />
        )}

        <div className="flex justify-end mt-4">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}


function StatusBadge({ status }: { status: string }) {
  const color = status === 'COMPLETE' ? 'bg-green-100 text-green-800'
    : status === 'ERROR' ? 'bg-red-100 text-red-800'
    : status === 'RUNNING' ? 'bg-blue-100 text-blue-800'
    : 'bg-gray-100 text-gray-800';
  return (
    <span className={cn('inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium', color)}>
      {status}
    </span>
  );
}


function DirectionPill({ direction }: { direction: Direction }) {
  if (direction === 'bullish') {
    return (
      <span className="inline-flex items-center gap-0.5 text-green-600 text-xs font-medium">
        <ArrowUp size={10} />bull
      </span>
    );
  }
  if (direction === 'bearish') {
    return (
      <span className="inline-flex items-center gap-0.5 text-red-600 text-xs font-medium">
        <ArrowDown size={10} />bear
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-0.5 text-muted-foreground text-xs">
      <Minus size={10} />neut
    </span>
  );
}


function RunResults({ detail }: { detail: PipelineRunDetail }) {
  const tickers = Object.keys(detail.agent_decisions ?? {});
  if (tickers.length === 0) {
    return (
      <div className="text-sm text-muted-foreground py-6 text-center">
        No tickers in this run (scanner didn't fire on any).
      </div>
    );
  }

  const analystKeys = Object.keys(detail.analyst_signals ?? {});

  return (
    <div className="space-y-6">
      {tickers.map((ticker) => (
        <TickerResultCard
          key={ticker}
          ticker={ticker}
          decision={detail.agent_decisions![ticker]}
          analystKeys={analystKeys}
          signals={Object.fromEntries(
            analystKeys
              .map((k) => [k, detail.analyst_signals![k]?.[ticker]])
              .filter(([, v]) => v != null),
          ) as Record<string, AnalystSignal>}
        />
      ))}
    </div>
  );
}


interface TickerCardProps {
  ticker: string;
  decision: AgentDecision;
  analystKeys: string[];
  signals: Record<string, AnalystSignal>;
}

function TickerResultCard({ ticker, decision, signals, analystKeys }: TickerCardProps) {
  return (
    <div className="border rounded-lg overflow-hidden">
      {/* Final decision header */}
      <div className="bg-accent/50 px-4 py-2 flex items-center justify-between border-b">
        <div className="flex items-center gap-3">
          <span className="font-mono font-bold text-base">{ticker}</span>
          <ActionPill action={decision.action} />
          <span className="text-xs text-muted-foreground">
            qty {decision.quantity}{decision.confidence != null && ` · conf ${decision.confidence}`}
          </span>
        </div>
      </div>

      {decision.reasoning && (
        <div className="px-4 py-2 text-xs text-muted-foreground border-b">
          <span className="font-medium">PM:</span> {decision.reasoning}
        </div>
      )}

      {/* Per-analyst signals */}
      <div className="divide-y">
        {analystKeys.map((key) => {
          const sig = signals[key];
          if (!sig) return null;
          return (
            <div key={key} className="px-4 py-2 flex items-start gap-3 text-xs">
              <div className="font-mono text-muted-foreground w-44 shrink-0">
                {key.replace(/_agent$/, '').replace(/_/g, ' ')}
              </div>
              <div className="shrink-0 w-16">
                <DirectionPill direction={sig.signal} />
              </div>
              <div className="shrink-0 w-14 text-right tabular-nums text-muted-foreground">
                {typeof sig.confidence === 'number'
                  ? `conf ${sig.confidence.toFixed(0)}`
                  : ''}
              </div>
              <div className="flex-1 text-muted-foreground">
                {typeof sig.reasoning === 'string'
                  ? sig.reasoning
                  : <pre className="whitespace-pre-wrap text-[10px]">{JSON.stringify(sig.reasoning, null, 2)}</pre>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}


function ActionPill({ action }: { action: AgentDecision['action'] }) {
  const colors: Record<AgentDecision['action'], string> = {
    buy: 'bg-green-100 text-green-800',
    cover: 'bg-green-100 text-green-800',
    sell: 'bg-red-100 text-red-800',
    short: 'bg-red-100 text-red-800',
    hold: 'bg-gray-100 text-gray-800',
  };
  return (
    <span className={cn('inline-flex items-center rounded px-2 py-0.5 text-xs font-bold uppercase',
      colors[action] ?? 'bg-gray-100 text-gray-800')}>
      {action}
    </span>
  );
}
