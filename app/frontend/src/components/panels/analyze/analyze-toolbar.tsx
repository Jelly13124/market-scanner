// Thin top toolbar for the Analyze panel — Phase 5 polish.
//
// Hosts: FlowList template controls + an "Add" dropdown (sections / input /
// reset-to-default) + a Run button + a live elapsed indicator while a run
// is in flight. Everything else (canvas, reports) lives below.

import { Button } from '@/components/ui/button';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { useSectionLabels } from '@/hooks/use-section-labels';
import { cn } from '@/lib/utils';
import {
  REQUIRED_SECTIONS,
  SECTION_ORDER,
} from '@/types/analyze';
import { CalendarClock, KeyRound, Loader2, Play, Plus, RotateCcw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { FlowList, type FlowListProps } from './flow-list';

interface AnalyzeToolbarProps extends FlowListProps {
  running: boolean;
  /** Disabled when canvas has no Input node. */
  canRun: boolean;
  onRun: () => void;
  /** Section count surfaced on the Run button label. */
  sectionCount: number;
  /** Which section names are currently on the canvas (used to disable items). */
  presentSections: Set<string>;
  /** Whether the singleton Input node is already on the canvas. */
  hasInputNode: boolean;
  /** Add a section node by canonical name. */
  onAddSection: (sectionName: string) => void;
  /** Add (or focus) the Input node. */
  onAddInput: () => void;
  /** Re-seed the canvas with the default full-pipeline template. */
  onResetToDefault: () => void;
  /** Open the "schedule this ticker" dialog (Task 10). Hidden when omitted. */
  onSchedule?: () => void;
  /** When false, Run is disabled + an "Add API key" button appears. Defaults true. */
  hasKeys?: boolean;
  /** Open Settings → API Keys. Shown only when hasKeys is false. */
  onAddKey?: () => void;
}

function formatElapsed(s: number): string {
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export function AnalyzeToolbar({
  running, canRun, onRun, sectionCount,
  presentSections, hasInputNode, onAddSection, onAddInput, onResetToDefault,
  onSchedule,
  hasKeys = true,
  onAddKey,
  ...flowListProps
}: AnalyzeToolbarProps) {
  const [elapsed, setElapsed] = useState(0);
  const [addOpen, setAddOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const { t } = useTranslation();
  const sectionLabels = useSectionLabels();

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

  // Reset the confirm-reset state when the popover closes so it always
  // takes two clicks the next time it's opened.
  useEffect(() => {
    if (!addOpen) setConfirmReset(false);
  }, [addOpen]);

  const missingSections = SECTION_ORDER.filter((s) => !presentSections.has(s));
  const allSectionsPresent = missingSections.length === 0;

  return (
    <div className="border-b bg-background px-3 py-1.5 flex items-center gap-2 flex-wrap">
      <FlowList {...flowListProps} />

      <Popover open={addOpen} onOpenChange={setAddOpen}>
        <PopoverTrigger asChild>
          <Button size="sm" variant="outline" className="h-7" title={t('analyze.toolbar.addSection')}>
            <Plus className="size-3 mr-1" />
            {t('common.add')}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-64 p-0 max-h-[60vh] overflow-auto">
          {/* Sections */}
          <div className="px-2 pt-2 pb-1 text-[10px] uppercase tracking-wider text-muted-foreground">
            {t('analyze.palette.title')}
          </div>
          {allSectionsPresent ? (
            <div className="px-3 py-2 text-xs text-muted-foreground italic">
              {t('analyze.palette.alreadyOnCanvas')}
            </div>
          ) : (
            <div className="pb-1">
              {missingSections.map((name) => {
                const label = sectionLabels[name] ?? name;
                const isRequired = REQUIRED_SECTIONS.includes(name);
                return (
                  <button
                    key={name}
                    type="button"
                    onClick={() => {
                      onAddSection(name);
                      setAddOpen(false);
                    }}
                    className={cn(
                      'w-full flex items-center justify-between gap-2 px-3 py-1.5',
                      'text-left text-sm hover:bg-accent/60 transition-colors',
                    )}
                  >
                    <span className="truncate" title={label}>{label}</span>
                    {isRequired && (
                      <span className="text-[10px] uppercase text-muted-foreground shrink-0">
                        {t('common.confirm')}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          )}

          {/* Divider */}
          <div className="border-t" />

          {/* Input */}
          <button
            type="button"
            disabled={hasInputNode}
            onClick={() => {
              onAddInput();
              setAddOpen(false);
            }}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm',
              'hover:bg-accent/60 transition-colors',
              hasInputNode && 'opacity-50 cursor-not-allowed hover:bg-transparent',
            )}
            title={hasInputNode ? t('analyze.palette.alreadyOnCanvas') : t('analyze.toolbar.addInput')}
          >
            <Plus className="size-3" />
            <span>{t('analyze.toolbar.addInput')}</span>
          </button>

          {/* Divider */}
          <div className="border-t" />

          {/* Reset to default template — two-click confirm */}
          <button
            type="button"
            onClick={() => {
              if (!confirmReset) {
                setConfirmReset(true);
                return;
              }
              onResetToDefault();
              setAddOpen(false);
              toast.success(t('analyze.toasts.canvasReset'));
            }}
            className={cn(
              'w-full flex items-center gap-2 px-3 py-1.5 text-left text-sm',
              'hover:bg-accent/60 transition-colors',
              confirmReset && 'bg-destructive/10 text-destructive hover:bg-destructive/15',
            )}
          >
            <RotateCcw className="size-3" />
            <span>
              {confirmReset
                ? t('common.confirm')
                : t('analyze.toolbar.resetToDefault')}
            </span>
          </button>
        </PopoverContent>
      </Popover>

      <div className="flex-1" />
      {running && (
        <span className="text-xs text-muted-foreground tabular-nums px-2">
          {t('analyze.toolbar.elapsed')}: {formatElapsed(elapsed)}
        </span>
      )}
      {onSchedule && (
        <Button
          onClick={onSchedule}
          disabled={!canRun}
          size="sm"
          variant="outline"
          className="h-7"
          title={t('analyze.toolbar.schedule')}
        >
          <CalendarClock className="size-3 mr-1" />
          {t('analyze.toolbar.schedule')}
        </Button>
      )}
      {!hasKeys && onAddKey && (
        <Button
          onClick={onAddKey}
          size="sm"
          variant="outline"
          className="h-7 border-amber-500/60 text-amber-600"
          title={t('onboarding.gate.tooltip')}
        >
          <KeyRound className="size-3 mr-1" />
          {t('onboarding.gate.addKey')}
        </Button>
      )}
      <Button
        onClick={onRun}
        disabled={running || !canRun || !hasKeys}
        size="sm"
        className="h-7"
        title={!hasKeys ? t('onboarding.gate.tooltip') : (canRun ? t('analyze.toolbar.run') : t('analyze.errors.noInput'))}
      >
        {running ? (
          <>
            <Loader2 className="size-3 mr-1 animate-spin" />
            {t('analyze.toolbar.running')}… ({sectionCount})
          </>
        ) : (
          <>
            <Play className="size-3 mr-1" />
            {t('common.run')} ({sectionCount})
          </>
        )}
      </Button>
    </div>
  );
}
