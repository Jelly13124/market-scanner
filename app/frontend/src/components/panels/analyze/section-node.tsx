// Custom React Flow node for one SOP section.
//
// Each node carries:
//   * name           — canonical section id (matches SECTION_ORDER)
//   * label          — human-readable title
//   * enabled        — whether to include in the run
//   * persona        — pinned persona name, or null for objective/router
//   * supportsPersonas — list of valid persona ids for the dropdown
//
// The node mutates its own data via the FlowCanvasContext setter so the
// parent FlowCanvas can serialize state without each node owning DB I/O.

import { Checkbox } from '@/components/ui/checkbox';
import { useSectionLabels } from '@/hooks/use-section-labels';
import { cn } from '@/lib/utils';
import { Handle, NodeProps, Position } from '@xyflow/react';
import { X } from 'lucide-react';
import { useContext } from 'react';
import { useTranslation } from 'react-i18next';

import { FlowCanvasContext } from './flow-canvas-context';

export interface SectionNodeData {
  name: string;
  label: string;
  enabled: boolean;
  persona: string | null;
  supportsPersonas: string[];
  // Debate-only fields (read by flow-canvas serializer when name==='debate').
  // Defaulted lazily so older saved canvases load cleanly.
  usePersonas?: boolean;     // default true
  debateRounds?: number;     // default 3 (1..5)
  [key: string]: unknown;
}

const DEBATE_ROUND_CHOICES = [1, 2, 3, 4, 5] as const;

export function SectionNode({ id, data, selected }: NodeProps) {
  const ctx = useContext(FlowCanvasContext);
  const d = data as unknown as SectionNodeData;
  const { t } = useTranslation();
  const sectionLabels = useSectionLabels();
  const displayLabel = sectionLabels[d.name] ?? d.label;

  const onToggleEnabled = (next: boolean) => {
    ctx?.updateNodeData(id, { enabled: next });
  };

  const onPickPersona = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    ctx?.updateNodeData(id, { persona: v === '__objective__' ? null : v });
  };

  const supports = d.supportsPersonas ?? [];
  const isDebate = d.name === 'debate';
  const debateUsePersonas = d.usePersonas ?? true;
  const debateRounds = d.debateRounds ?? 3;

  return (
    <div
      className={cn(
        'group relative rounded-lg border-2 bg-card text-card-foreground shadow-md',
        'min-w-[380px] max-w-[440px] px-5 py-4',
        selected ? 'border-primary ring-2 ring-primary/30' : 'border-border',
        !d.enabled && 'opacity-60',
      )}
    >
      {/* Top handle for incoming edges */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-muted-foreground/40"
      />

      {/* Delete button — visible on hover. nodrag so it doesn't start a drag. */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          ctx?.deleteNode(id);
        }}
        aria-label={`${t('common.delete')} ${displayLabel}`}
        title={t('analyze.section.deleteNode')}
        className={cn(
          'nodrag absolute -top-2 -right-2 z-10 size-5 rounded-full',
          'bg-destructive text-destructive-foreground border border-background',
          'flex items-center justify-center',
          'opacity-0 group-hover:opacity-100 transition-opacity',
          'hover:bg-destructive/90',
        )}
      >
        <X className="size-3" strokeWidth={3} />
      </button>

      <div className="flex items-center gap-3">
        <Checkbox
          checked={d.enabled}
          onCheckedChange={(v) => onToggleEnabled(!!v)}
          aria-label={`${t('common.apply')} ${displayLabel}`}
          className="size-5"
        />
        <div className="text-lg font-semibold truncate flex-1" title={displayLabel}>
          {displayLabel}
        </div>
      </div>

      {supports.length > 0 && (
        <div className="mt-4">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">
            {t('analyze.section.persona')}
          </label>
          <select
            value={d.persona ?? '__objective__'}
            onChange={onPickPersona}
            disabled={!d.enabled}
            className="nodrag w-full h-9 px-2 mt-1 text-sm border rounded bg-background"
          >
            <option value="__objective__">{t('analyze.section.objective_persona')}</option>
            {supports.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
      )}

      {isDebate && (
        <div className="mt-4 space-y-3 border-t pt-3">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <Checkbox
              checked={debateUsePersonas}
              onCheckedChange={(v) =>
                ctx?.updateNodeData(id, { usePersonas: !!v })
              }
              disabled={!d.enabled}
              aria-label={t('analyze.section.usePersonas')}
            />
            <span>{t('analyze.section.usePersonas')}</span>
          </label>
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase text-muted-foreground tracking-wide">
              {t('analyze.section.rounds')} <span className="normal-case text-[10px]">{t('analyze.section.roundsHint')}</span>
            </label>
            <select
              value={debateRounds}
              onChange={(e) =>
                ctx?.updateNodeData(id, { debateRounds: parseInt(e.target.value, 10) })
              }
              disabled={!d.enabled}
              className="nodrag w-full h-9 px-2 text-sm border rounded bg-background"
            >
              {DEBATE_ROUND_CHOICES.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Bottom handle for outgoing edges */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-muted-foreground/40"
      />
    </div>
  );
}
