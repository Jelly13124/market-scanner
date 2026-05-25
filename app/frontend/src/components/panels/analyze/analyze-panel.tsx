// AnalyzePanel — Phase 5 polish.
//
// Layout (top→bottom, full viewport):
//   1. Thin toolbar  (~40px) — FlowList controls + Run + elapsed indicator
//   2. Canvas        (~70% of remaining height) — palette + React Flow
//   3. Collapsible accordion — section pills, report iframe, history list
//
// The run-request payload is sourced from the Input node on the canvas
// (compact form inside a draggable node) instead of a separate form.

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Button } from '@/components/ui/button';
import { analyzeService } from '@/services/analyze-service';
import type { AnalyzeReportDetail, AnalyzeRunRequest } from '@/types/analyze';
import { ExternalLink } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { toast } from 'sonner';

import { AnalyzeToolbar } from './analyze-toolbar';
import { FlowCanvas, type FlowCanvasHandle } from './flow-canvas';
import { ReportList } from './report-list';
import { SectionPalette } from './section-palette';
import {
  PersonaAssignmentsBox,
  SectionStatusPanel,
} from './section-status-panel';

export function AnalyzePanel() {
  const canvasRef = useRef<FlowCanvasHandle | null>(null);

  // Trigger re-render so the palette knows when '+' buttons should be disabled.
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

  const handleRun = useCallback(async () => {
    const cfg = getConfig();
    const input = canvasRef.current?.getInputData();
    if (!input) {
      toast.error('Add an Input node to the canvas first.');
      return;
    }
    const ticker = input.ticker.trim().toUpperCase();
    if (!ticker) {
      toast.error('Enter a ticker in the Input node.');
      return;
    }
    const req: AnalyzeRunRequest = {
      ticker,
      objective: input.objective,
      position_budget_usd: input.budget_usd ? parseFloat(input.budget_usd) : null,
      already_holds: input.already_holds,
      cost_basis_usd: input.already_holds && input.cost_basis_usd
        ? parseFloat(input.cost_basis_usd)
        : null,
      risk_tolerance: input.risk_tolerance,
      use_personas: input.use_personas,
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
  }, [getConfig]);

  // Re-read canvas state every render (tick triggers a refresh).
  void canvasTick;
  const cfg = getConfig();
  const presentSet = canvasRef.current?.getPresentSections() ?? new Set<string>();
  const hasInput = canvasRef.current?.hasInputNode() ?? false;
  const sectionCount = cfg.included_sections.length;

  const iframeSrc =
    currentReportId != null
      ? analyzeService.reportHtmlUrl(currentReportId)
      : null;

  const showLiveDetail =
    currentDetail != null && currentDetail.id === currentReportId;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* 1. Toolbar */}
      <AnalyzeToolbar
        running={running}
        canRun={hasInput}
        onRun={handleRun}
        sectionCount={sectionCount}
        getCurrentConfig={getConfig}
        onLoad={(flow) => canvasRef.current?.loadFlow(flow)}
        onNewBlank={() => canvasRef.current?.clear()}
        loadedFlowId={loadedFlowId}
        onLoadedFlowIdChange={setLoadedFlowId}
      />

      {/* 2. Canvas dominates the viewport — palette + React Flow */}
      <div className="flex-1 min-h-0 grid grid-cols-[200px_1fr] border-b">
        <div className="border-r overflow-hidden">
          <SectionPalette
            presentSections={presentSet}
            hasInputNode={hasInput}
            onAdd={(name) => canvasRef.current?.addSection(name)}
            onAddInput={() => {
              if (canvasRef.current?.hasInputNode()) {
                canvasRef.current.focusInput();
              } else {
                canvasRef.current?.addInputNode();
              }
            }}
          />
        </div>
        <div className="overflow-hidden">
          <FlowCanvas ref={canvasRef} onChange={onCanvasChange} />
        </div>
      </div>

      {/* 3. Collapsible bottom — status pills, report iframe, history */}
      <div className="flex-shrink-0 max-h-[40vh] overflow-auto bg-background">
        <Accordion
          type="multiple"
          defaultValue={['report', 'history']}
          className="px-3"
        >
          {showLiveDetail && currentDetail && (
            <AccordionItem value="status">
              <AccordionTrigger className="py-2 text-xs uppercase font-medium">
                Section status
              </AccordionTrigger>
              <AccordionContent className="space-y-2 pb-3">
                <SectionStatusPanel detail={currentDetail} />
                <PersonaAssignmentsBox detail={currentDetail} />
              </AccordionContent>
            </AccordionItem>
          )}

          {iframeSrc && (
            <AccordionItem value="report">
              <AccordionTrigger className="py-2 text-xs uppercase font-medium">
                Report #{currentReportId}
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <div className="flex items-center justify-end mb-1">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7"
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
                    className="w-full h-[50vh]"
                    style={{ border: 0 }}
                  />
                </div>
              </AccordionContent>
            </AccordionItem>
          )}

          <AccordionItem value="history">
            <AccordionTrigger className="py-2 text-xs uppercase font-medium">
              Recent reports{tickerFilter ? ` for ${tickerFilter}` : ''}
            </AccordionTrigger>
            <AccordionContent className="pb-3">
              <ReportList
                tickerFilter={tickerFilter}
                currentReportId={currentReportId}
                onSelect={(id) => setCurrentReportId(id)}
              />
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </div>
    </div>
  );
}
