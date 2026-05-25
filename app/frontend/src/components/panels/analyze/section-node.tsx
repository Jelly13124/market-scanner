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
import { cn } from '@/lib/utils';
import { Handle, NodeProps, Position } from '@xyflow/react';
import { X } from 'lucide-react';
import { useContext } from 'react';

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
        'group relative rounded-md border bg-card text-card-foreground shadow-sm',
        'min-w-[300px] max-w-[340px] px-4 py-3',
        selected ? 'border-primary ring-1 ring-primary/30' : 'border-border',
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
        aria-label={`Delete ${d.label}`}
        title="Delete node"
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

      <div className="flex items-center gap-2">
        <Checkbox
          checked={d.enabled}
          onCheckedChange={(v) => onToggleEnabled(!!v)}
          aria-label={`Enable ${d.label}`}
        />
        <div className="text-base font-semibold truncate flex-1" title={d.label}>
          {d.label}
        </div>
      </div>

      {supports.length > 0 && (
        <div className="mt-3">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">
            Persona
          </label>
          <select
            value={d.persona ?? '__objective__'}
            onChange={onPickPersona}
            disabled={!d.enabled}
            className="nodrag w-full h-8 px-2 mt-1 text-sm border rounded bg-background"
          >
            <option value="__objective__">objective</option>
            {supports.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
      )}

      {isDebate && (
        <div className="mt-3 space-y-2 border-t pt-2">
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <Checkbox
              checked={debateUsePersonas}
              onCheckedChange={(v) =>
                ctx?.updateNodeData(id, { usePersonas: !!v })
              }
              disabled={!d.enabled}
              aria-label="Use investor personas"
            />
            <span>Use investor personas</span>
          </label>
          <div className="flex flex-col gap-1">
            <label className="text-xs uppercase text-muted-foreground tracking-wide">
              Rounds <span className="normal-case text-[10px]">(max 5, recommended 3)</span>
            </label>
            <select
              value={debateRounds}
              onChange={(e) =>
                ctx?.updateNodeData(id, { debateRounds: parseInt(e.target.value, 10) })
              }
              disabled={!d.enabled}
              className="nodrag w-full h-8 px-2 text-sm border rounded bg-background"
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
