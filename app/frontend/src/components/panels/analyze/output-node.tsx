// Visual aggregator node for the Analyze canvas. Single canvas node that
// the flow-canvas serializer expands to the 4 backend SECTION_ORDER
// entries listed in OUTPUT_BACKEND_SECTIONS (evidence_ledger /
// final_strategy / executive_summary / missing_data). User toggles all
// four with one checkbox; persona-overrides are not supported here in v1.

import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import { Handle, NodeProps, Position } from '@xyflow/react';
import { FileText, X } from 'lucide-react';
import { useContext } from 'react';
import { useTranslation } from 'react-i18next';

import { FlowCanvasContext } from './flow-canvas-context';

export interface OutputNodeData {
  enabled: boolean;
  [key: string]: unknown;
}

// Sub-sections are the 4 backend SECTION_ORDER entries Output represents.
// Labels are looked up from sections.* i18n keys at render time.
const SUBSECTION_KEYS = [
  'executive_summary',
  'evidence_ledger',
  'final_strategy',
  'missing_data',
];

export function OutputNode({ id, data, selected }: NodeProps) {
  const ctx = useContext(FlowCanvasContext);
  const d = data as unknown as OutputNodeData;
  const enabled = d.enabled !== false;
  const { t } = useTranslation();

  const onToggle = (next: boolean) => {
    ctx?.updateNodeData(id, { enabled: next });
  };

  return (
    <div
      className={cn(
        'group relative rounded-lg border-2 bg-card text-card-foreground shadow-md',
        'min-w-[400px] max-w-[440px] px-5 py-4',
        selected ? 'border-primary ring-2 ring-primary/30' : 'border-emerald-500/60',
        !enabled && 'opacity-60',
      )}
    >
      {/* Incoming handle (left) — receives 10 analyses + Debate */}
      <Handle
        type="target"
        position={Position.Left}
        className="!w-2.5 !h-2.5 !bg-emerald-500/60"
      />

      {/* Delete */}
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          ctx?.deleteNode(id);
        }}
        aria-label={t('analyze.output.deleteNode')}
        title={t('analyze.output.deleteNode')}
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
          checked={enabled}
          onCheckedChange={(v) => onToggle(!!v)}
          aria-label={t('analyze.output.title')}
          className="size-5"
        />
        <FileText className="size-5 text-emerald-600" />
        <div className="text-lg font-semibold flex-1">{t('analyze.output.title')}</div>
      </div>

      <div className="text-xs text-muted-foreground mt-1">
        {t('analyze.output.description')}
      </div>

      <ul className="mt-3 space-y-1 text-xs">
        {SUBSECTION_KEYS.map((key) => (
          <li key={key} className="flex items-baseline gap-2">
            <span className="text-emerald-600 font-mono">·</span>
            <span className="font-medium">{t(`sections.${key}`)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
