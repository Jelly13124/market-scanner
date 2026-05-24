// AnalyzePanel — Phase 5D rewrite. The right column is now a React Flow
// canvas (SectionNodes + SectionPalette) instead of a checkbox list.
//
// Layout:
//   1. FlowList — load/save AnalyzeFlow templates
//   2. Form + canvas grid (form left, palette + canvas right)
//   3. Section status pills + persona summary (live runs only)
//   4. iframe with rendered report
//   5. ReportList history

import { Button } from '@/components/ui/button';
import { analyzeService } from '@/services/analyze-service';
import type {
  AnalyzeReportDetail, AnalyzeRunRequest, SectionPayloadAPI,
} from '@/types/analyze';
import { SECTION_LABELS, SECTION_ORDER } from '@/types/analyze';
import { ExternalLink } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';

import { AnalyzeForm } from './analyze-form';
import { FlowCanvas, type FlowCanvasHandle } from './flow-canvas';
import { FlowList } from './flow-list';
import { ReportList } from './report-list';
import { SectionPalette } from './section-palette';

type PillKind = 'done' | 'excluded' | 'failed';

function classifySection(s: SectionPayloadAPI): PillKind {
  if (!s.skipped) return 'done';
  const reason = (s.skip_reason || '').toLowerCase();
  if (reason.includes('user excluded')) return 'excluded';
  return 'failed';
}

const PILL_GLYPH: Record<PillKind, string> = {
  done: '✓',
  excluded: '⊘',
  failed: '×',
};

const PILL_CLASS: Record<PillKind, string> = {
  done: 'bg-green-500/15 text-green-700 border-green-500/40 dark:text-green-400',
  excluded: 'bg-yellow-500/15 text-yellow-700 border-yellow-500/40 dark:text-yellow-400',
  failed: 'bg-red-500/15 text-red-700 border-red-500/40 dark:text-red-400',
};

function SectionStatusPanel({ detail }: { detail: AnalyzeReportDetail }) {
  const ordered: string[] = [
    ...SECTION_ORDER.filter((n) => n in detail.sections),
    ...Object.keys(detail.sections).filter((n) => !SECTION_ORDER.includes(n)),
  ];

  const counts = { done: 0, excluded: 0, failed: 0 };
  for (const name of ordered) {
    counts[classifySection(detail.sections[name])]++;
  }

  return (
    <div className="border rounded p-3 bg-accent/10 space-y-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>
          Sections: <span className="text-green-600 dark:text-green-400">{counts.done} done</span>
          {counts.excluded > 0 && (
            <> · <span className="text-yellow-600 dark:text-yellow-400">{counts.excluded} excluded</span></>
          )}
          {counts.failed > 0 && (
            <> · <span className="text-red-600 dark:text-red-400">{counts.failed} failed</span></>
          )}
        </span>
        {detail.duration_seconds != null && (
          <span>Run took {detail.duration_seconds.toFixed(1)}s</span>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {ordered.map((name) => {
          const s = detail.sections[name];
          const kind = classifySection(s);
          const label = SECTION_LABELS[name] ?? name;
          const tip = s.skip_reason ? `${label} — ${s.skip_reason}` : label;
          return (
            <span
              key={name}
              title={tip}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-xs ${PILL_CLASS[kind]}`}
            >
              <span className="font-mono">{PILL_GLYPH[kind]}</span>
              <span>{label}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function PersonaAssignmentsBox({ detail }: { detail: AnalyzeReportDetail }) {
  if (!detail.persona_assignments) return null;
  const entries = Object.entries(detail.persona_assignments)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}: ${String(v)}`);
  if (entries.length === 0) return null;
  return (
    <div className="border rounded px-3 py-2 bg-accent/10 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">Personas</span> → {entries.join(' · ')}
    </div>
  );
}

export function AnalyzePanel() {
  const canvasRef = useRef<FlowCanvasHandle | null>(null);

  // Trigger re-render of the palette when canvas content changes (so
  // already-present section '+' buttons disable correctly).
  const [canvasTick, setCanvasTick] = useState(0);
  const onCanvasChange = useCallback(() => setCanvasTick((t) => t + 1), []);

  const [running, setRunning] = useState(false);
  const [currentReportId, setCurrentReportId] = useState<number | null>(null);
  const [currentDetail, setCurrentDetail] = useState<AnalyzeReportDetail | null>(null);
  const [tickerFilter, setTickerFilter] = useState<string | undefined>(undefined);
  const [loadedFlowId, setLoadedFlowId] = useState<number | null>(null);

  const getConfig = useCallback(
    () =>
      canvasRef.current?.getConfig() ?? {
        included_sections: [],
        persona_overrides: {},
      },
    [],
  );

  const handleRun = useCallback(
    async (formReq: AnalyzeRunRequest) => {
      const cfg = getConfig();
      const req: AnalyzeRunRequest = {
        ...formReq,
        included_sections: cfg.included_sections,
        persona_overrides: Object.keys(cfg.persona_overrides).length
          ? cfg.persona_overrides
          : null,
      };
      setRunning(true);
      try {
        const detail = await analyzeService.runAnalyze(req);
        setCurrentReportId(detail.id);
        setCurrentDetail(detail);
        setTickerFilter(detail.ticker);
        toast.success(`Analyze complete: ${detail.ticker} (id ${detail.id})`);
      } catch (e) {
        toast.error((e as Error).message);
      } finally {
        setRunning(false);
      }
    },
    [getConfig],
  );

  const iframeSrc =
    currentReportId != null
      ? analyzeService.reportHtmlUrl(currentReportId)
      : null;

  const showLiveDetail = currentDetail != null && currentDetail.id === currentReportId;

  // Recompute the included-sections set for the AnalyzeForm submit label
  // (so the form's "Run SOP analysis (N sections)" stays in sync with
  // the canvas without prop-drilling state). Reads canvas each render
  // via the tick trigger.
  void canvasTick;  // silence unused-var while binding the dep
  const includedSet = new Set(getConfig().included_sections);
  const presentSet = canvasRef.current?.getPresentSections() ?? new Set<string>();

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-1 overflow-auto p-4 space-y-4">
        <div className="text-xs text-muted-foreground">
          Full SOP analysis: 16 sections + technical-signal backtest. 60-120s per run.
        </div>

        {/* FlowList — saved templates */}
        <FlowList
          getCurrentConfig={getConfig}
          onLoad={(flow) => canvasRef.current?.loadFlow(flow)}
          onNewBlank={() => canvasRef.current?.clear()}
          loadedFlowId={loadedFlowId}
          onLoadedFlowIdChange={setLoadedFlowId}
        />

        {/* Form + canvas grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="border rounded p-3 bg-accent/20">
            <AnalyzeForm
              running={running}
              onRun={(req) => handleRun(req)}
              included={includedSet}
            />
          </div>
          <div className="border rounded bg-accent/20 grid grid-cols-[180px_1fr] h-[420px] overflow-hidden">
            <div className="border-r overflow-hidden">
              <SectionPalette
                presentSections={presentSet}
                onAdd={(name) => canvasRef.current?.addSection(name)}
              />
            </div>
            <div className="overflow-hidden">
              <FlowCanvas ref={canvasRef} onChange={onCanvasChange} />
            </div>
          </div>
        </div>

        {/* Live run summary */}
        {showLiveDetail && currentDetail && (
          <>
            <SectionStatusPanel detail={currentDetail} />
            <PersonaAssignmentsBox detail={currentDetail} />
          </>
        )}

        {/* Iframe */}
        {iframeSrc && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="text-xs text-muted-foreground">
                Report #{currentReportId}
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={() => window.open(iframeSrc, '_blank', 'noopener')}
              >
                <ExternalLink className="size-3 mr-1" />
                Open in new tab
              </Button>
            </div>
            <div className="border rounded overflow-hidden">
              <iframe
                key={currentReportId}
                src={iframeSrc}
                title={`Analyze report ${currentReportId}`}
                className="w-full h-[70vh]"
                style={{ border: 0 }}
              />
            </div>
          </div>
        )}

        {/* Bottom: history */}
        <ReportList
          tickerFilter={tickerFilter}
          currentReportId={currentReportId}
          onSelect={(id) => setCurrentReportId(id)}
        />
      </div>
    </div>
  );
}
