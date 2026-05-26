// Custom React Flow node holding the run-request form (ticker / objective /
// budget / holds / risk). One instance per canvas. The canvas serializer
// reads this node's `data` to build the AnalyzeRunRequest at run-time.
//
// NOTE: `use_personas` is no longer surfaced as a checkbox here — it lives
// in the Debate node. The field is still in InputNodeData for backwards
// compat (saved templates / serializer fallback), but is never user-set
// from this UI. The flow-canvas serializer reads it from the Debate node.

import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { Market, Objective, ReportLanguage, RiskBand } from '@/types/analyze';
import { Handle, NodeProps, Position } from '@xyflow/react';
import { X } from 'lucide-react';
import { useContext } from 'react';
import { useTranslation } from 'react-i18next';

import { FlowCanvasContext } from './flow-canvas-context';

/** Shape of the InputNode's `data` payload. Mirrors AnalyzeRunRequest
 * fields the user can control from the canvas.
 *
 * `use_personas` is retained as a fallback for the serializer — its
 * authoritative value now lives on the Debate node. When Debate is on
 * canvas, the flow-canvas serializer ignores this field. */
export interface InputNodeData {
  ticker: string;
  objective: Objective;
  budget_usd: string;          // string so the input field can be empty
  already_holds: boolean;
  cost_basis_usd: string;
  risk_tolerance: RiskBand;
  use_personas: boolean;       // fallback only — see Debate node for source of truth
  // Phase 7 i18n — language of the generated report. Defaults to 'en'.
  report_language?: ReportLanguage;
  // Phase 8 — A-share data integration. Defaults to 'us'.
  market?: Market;
  [key: string]: unknown;
}

export const DEFAULT_INPUT_NODE_DATA: InputNodeData = {
  ticker: 'NVDA',
  objective: 'general_research',
  budget_usd: '',
  already_holds: false,
  cost_basis_usd: '',
  risk_tolerance: 'balanced',
  use_personas: false,
  report_language: 'en',
  market: 'us',
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
  const { t, i18n } = useTranslation();

  // Default report_language tracks the current UI language unless the
  // user has explicitly set it on this node. Read-only check — does not
  // mutate stored data.
  const effectiveReportLang: ReportLanguage = (d.report_language
    ?? ((i18n.resolvedLanguage || i18n.language || 'en').startsWith('zh') ? 'zh' : 'en')
  ) as ReportLanguage;

  const update = (patch: Partial<InputNodeData>) => {
    ctx?.updateNodeData(id, patch as Record<string, unknown>);
  };

  return (
    <div
      className={cn(
        'group relative rounded-lg border-2 bg-card text-card-foreground shadow-md',
        'min-w-[400px] max-w-[440px] p-5',
        selected ? 'border-primary ring-2 ring-primary/30' : 'border-primary/60',
      )}
    >
      {/* Delete button — visible on hover. nodrag so it doesn't start a drag. */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          ctx?.deleteNode(id);
        }}
        aria-label={t('analyze.input.deleteNode')}
        title={t('analyze.input.deleteNode')}
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

      <div className="text-sm uppercase font-bold tracking-wider text-primary mb-4">
        {t('analyze.input.label')}
      </div>

      <div className="space-y-4">
        {/* Market (Phase 8) — pick market first so the ticker convention is clear */}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">
            {t('analyze.input.market')}
          </label>
          <select
            value={(d.market ?? 'us') as Market}
            onChange={(e) => update({ market: e.target.value as Market })}
            className="nodrag h-9 px-2 text-sm border rounded bg-background"
          >
            <option value="us">{t('analyze.markets.us')}</option>
            <option value="cn">{t('analyze.markets.cn')}</option>
          </select>
        </div>

        {/* Ticker */}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">{t('analyze.input.ticker')}</label>
          <Input
            value={d.ticker}
            onChange={(e) => update({ ticker: e.target.value.toUpperCase() })}
            className="nodrag h-9 text-sm font-mono uppercase"
            placeholder="NVDA"
          />
        </div>

        {/* Objective */}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">{t('analyze.input.objective')}</label>
          <select
            value={d.objective}
            onChange={(e) => update({ objective: e.target.value as Objective })}
            className="nodrag h-9 px-2 text-sm border rounded bg-background"
          >
            {OBJECTIVES.map((o) => (
              <option key={o.value} value={o.value}>{t(`analyze.objectives.${o.value}`)}</option>
            ))}
          </select>
        </div>

        {/* Budget */}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">{t('analyze.input.budget')}</label>
          <Input
            type="number" min="0" step="100"
            value={d.budget_usd}
            onChange={(e) => update({ budget_usd: e.target.value })}
            placeholder="10000"
            className="nodrag h-9 text-sm"
          />
        </div>

        {/* Risk */}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">{t('analyze.input.risk')}</label>
          <select
            value={d.risk_tolerance}
            onChange={(e) => update({ risk_tolerance: e.target.value as RiskBand })}
            className="nodrag h-9 px-2 text-sm border rounded bg-background"
          >
            {RISKS.map((r) => (
              <option key={r.value} value={r.value}>{t(`analyze.risks.${r.value}`)}</option>
            ))}
          </select>
        </div>

        {/* Report language (Phase 7 i18n) */}
        <div className="flex flex-col gap-1">
          <label className="text-xs uppercase text-muted-foreground tracking-wide">
            {t('analyze.input.reportLanguage')}
          </label>
          <select
            value={effectiveReportLang}
            onChange={(e) => update({ report_language: e.target.value as ReportLanguage })}
            className="nodrag h-9 px-2 text-sm border rounded bg-background"
            title={t('analyze.input.reportLanguageHint')}
          >
            <option value="en">English</option>
            <option value="zh">简体中文</option>
          </select>
        </div>

        {/* Holds */}
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <Checkbox
            checked={d.already_holds}
            onCheckedChange={(v) => update({ already_holds: !!v })}
          />
          <span>{t('analyze.input.holds')}</span>
        </label>
        {d.already_holds && (
          <div className="flex flex-col gap-1 pl-6">
            <label className="text-xs uppercase text-muted-foreground tracking-wide">
              {t('analyze.input.costBasis')}
            </label>
            <Input
              type="number" min="0" step="0.01"
              value={d.cost_basis_usd}
              onChange={(e) => update({ cost_basis_usd: e.target.value })}
              placeholder="120.50"
              className="nodrag h-9 text-sm"
            />
          </div>
        )}
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
