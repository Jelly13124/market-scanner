// Thin top toolbar for the Analyze panel — Phase 5 polish.
//
// Hosts: FlowList template controls + a Run button + a live elapsed
// indicator while a run is in flight. Everything else (form, canvas,
// reports) lives below.

import { Button } from '@/components/ui/button';
import { Loader2, Play } from 'lucide-react';
import { useEffect, useState } from 'react';

import { FlowList, type FlowListProps } from './flow-list';

interface AnalyzeToolbarProps extends FlowListProps {
  running: boolean;
  /** Disabled when canvas has no Input node. */
  canRun: boolean;
  onRun: () => void;
  /** Section count surfaced on the Run button label. */
  sectionCount: number;
}

function formatElapsed(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export function AnalyzeToolbar({
  running, canRun, onRun, sectionCount, ...flowListProps
}: AnalyzeToolbarProps) {
  const [elapsed, setElapsed] = useState(0);

  // Live elapsed counter — restarts when `running` flips true.
  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    setElapsed(0);
    const startedAt = Date.now();
    const id = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, [running]);

  return (
    <div className="border-b bg-background px-3 py-1.5 flex items-center gap-2 flex-wrap">
      <FlowList {...flowListProps} />
      <div className="flex-1" />
      {running && (
        <span className="text-xs text-muted-foreground tabular-nums px-2">
          elapsed: {formatElapsed(elapsed)}
        </span>
      )}
      <Button
        onClick={onRun}
        disabled={running || !canRun}
        size="sm"
        className="h-7"
        title={canRun ? 'Run SOP analysis' : 'Add an Input node first'}
      >
        {running ? (
          <>
            <Loader2 className="size-3 mr-1 animate-spin" />
            Running… ({sectionCount} sections)
          </>
        ) : (
          <>
            <Play className="size-3 mr-1" />
            Run ({sectionCount})
          </>
        )}
      </Button>
    </div>
  );
}
