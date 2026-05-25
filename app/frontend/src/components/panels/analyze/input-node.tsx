// Custom React Flow node holding the run-request form (ticker / objective /
// budget / holds / risk / personas). One instance per canvas. The canvas
// serializer reads this node's `data` to build the AnalyzeRunRequest at
// run-time.
//
// Kept compact (≤280px) so it sits comfortably alongside SectionNodes.

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { Objective, RiskBand } from '@/types/analyze';
import { Handle, NodeProps, Position } from '@xyflow/react';
import { useContext } from 'react';

import { FlowCanvasContext } from './flow-canvas-context';

/** Shape of the InputNode's `data` payload. Mirrors AnalyzeRunRequest
 * fields the user can control from the canvas. */
export interface InputNodeData {
  ticker: string;
  objective: Objective;
  budget_usd: string;          // string so the input field can be empty
  already_holds: boolean;
  cost_basis_usd: string;
  risk_tolerance: RiskBand;
  use_personas: boolean;
  [key: string]: unknown;
}

export const DEFAULT_INPUT_NODE_DATA: InputNodeData = {
  ticker: 'NVDA',
  objective: 'general_research',
  budget_usd: '',
  already_holds: false,
  cost_basis_usd: '',
  risk_tolerance: 'balanced',
  use_personas: true,
};

const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: 'general_research', label: 'General research' },
  { value: 'target_price',     label: 'Target price' },
  { value: 'short_term',       label: 'Short-term trade' },
  { value: 'medium_term',      label: 'Medium-term' },
  { value: 'long_term',        label: 'Long-term invest' },
  { value: 'earnings_review',  label: 'Earnings review' },
];

const RISKS: { value: RiskBand; label: string }[] = [
  { value: 'conservative', label: 'Conservative' },
  { value: 'balanced',     label: 'Balanced' },
  { value: 'aggressive',   label: 'Aggressive' },
];

export function InputNode({ id, data, selected }: NodeProps) {
  const ctx = useContext(FlowCanvasContext);
  const d = data as unknown as InputNodeData;

  const update = (patch: Partial<InputNodeData>) => {
    ctx?.updateNodeData(id, patch as Record<string, unknown>);
  };

  return (
    <div
      className={cn(
        'rounded border bg-card text-card-foreground shadow-sm',
        'min-w-[260px] max-w-[280px] p-3',
        selected ? 'border-primary ring-1 ring-primary/30' : 'border-primary/50',
      )}
    >
      <div className="text-[10px] uppercase font-bold tracking-wider text-primary mb-2">
        Run Input
      </div>

      <div className="space-y-2">
        {/* Ticker */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase text-muted-foreground">Ticker</label>
          <Input
            value={d.ticker}
            onChange={(e) => update({ ticker: e.target.value.toUpperCase() })}
            className="nodrag h-7 text-xs font-mono uppercase"
            placeholder="NVDA"
          />
        </div>

        {/* Objective */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase text-muted-foreground">Objective</label>
          <select
            value={d.objective}
            onChange={(e) => update({ objective: e.target.value as Objective })}
            className="nodrag h-7 px-1 text-xs border rounded bg-background"
          >
            {OBJECTIVES.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Budget */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase text-muted-foreground">Budget (USD)</label>
          <Input
            type="number" min="0" step="100"
            value={d.budget_usd}
            onChange={(e) => update({ budget_usd: e.target.value })}
            placeholder="10000"
            className="nodrag h-7 text-xs"
          />
        </div>

        {/* Risk */}
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase text-muted-foreground">Risk tolerance</label>
          <select
            value={d.risk_tolerance}
            onChange={(e) => update({ risk_tolerance: e.target.value as RiskBand })}
            className="nodrag h-7 px-1 text-xs border rounded bg-background"
          >
            {RISKS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </div>

        {/* Holds */}
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <Checkbox
            checked={d.already_holds}
            onCheckedChange={(v) => update({ already_holds: !!v })}
          />
          <span>I already hold this</span>
        </label>
        {d.already_holds && (
          <div className="flex flex-col gap-1 pl-5">
            <label className="text-[10px] uppercase text-muted-foreground">
              Cost basis ($/share)
            </label>
            <Input
              type="number" min="0" step="0.01"
              value={d.cost_basis_usd}
              onChange={(e) => update({ cost_basis_usd: e.target.value })}
              placeholder="120.50"
              className="nodrag h-7 text-xs"
            />
          </div>
        )}

        {/* Personas */}
        <label className="flex items-center gap-2 text-xs cursor-pointer">
          <Checkbox
            checked={d.use_personas}
            onCheckedChange={(v) => update({ use_personas: !!v })}
          />
          <span>Use personas + debate</span>
        </label>
      </div>

      {/* Output handle (right) — feeds into section nodes */}
      <Handle
        type="source"
        position={Position.Right}
        className="!w-2.5 !h-2.5 !bg-primary"
      />
    </div>
  );
}
