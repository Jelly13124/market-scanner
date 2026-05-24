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
import { useContext } from 'react';

import { FlowCanvasContext } from './flow-canvas-context';

export interface SectionNodeData {
  name: string;
  label: string;
  enabled: boolean;
  persona: string | null;
  supportsPersonas: string[];
  [key: string]: unknown;
}

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

  return (
    <div
      className={cn(
        'rounded border bg-card text-card-foreground shadow-sm',
        'min-w-[180px] max-w-[240px] px-3 py-2',
        selected ? 'border-primary ring-1 ring-primary/30' : 'border-border',
        !d.enabled && 'opacity-60',
      )}
    >
      {/* Top handle for incoming edges */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2 !h-2 !bg-muted-foreground/40"
      />

      <div className="flex items-center gap-2">
        <Checkbox
          checked={d.enabled}
          onCheckedChange={(v) => onToggleEnabled(!!v)}
          aria-label={`Enable ${d.label}`}
        />
        <div className="text-sm font-medium truncate flex-1" title={d.label}>
          {d.label}
        </div>
      </div>

      {supports.length > 0 && (
        <div className="mt-2">
          <label className="text-[10px] uppercase text-muted-foreground">
            Persona
          </label>
          <select
            value={d.persona ?? '__objective__'}
            onChange={onPickPersona}
            disabled={!d.enabled}
            className="nodrag w-full h-7 px-1 text-xs border rounded bg-background"
          >
            <option value="__objective__">objective</option>
            {supports.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
      )}

      {/* Bottom handle for outgoing edges */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2 !h-2 !bg-muted-foreground/40"
      />
    </div>
  );
}
