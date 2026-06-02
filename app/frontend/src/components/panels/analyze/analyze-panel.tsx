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
import { useReportHtml } from '@/hooks/use-report-html';
import { analyzeService } from '@/services/analyze-service';
import { analyzeBus, type AnalyzeRequest as AnalyzeBusRequest } from '@/services/analyze-bus';
import type { AnalyzeReportDetail, AnalyzeRunRequest } from '@/types/analyze';
import { ExternalLink, Mail } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

import { AnalyzeToolbar } from './analyze-toolbar';
import { FlowCanvas, type FlowCanvasHandle } from './flow-canvas';
import {
  PersonaAssignmentsBox,
  SectionStatusPanel,
} from './section-status-panel';
import { VerdictCard } from './verdict-card';

export function AnalyzePanel() {
  const canvasRef = useRef<FlowCanvasHandle | null>(null);
  const { t } = useTranslation();

  // Trigger re-render so the palette knows when '+' buttons should be disabled.
  const [canvasTick, setCanvasTick] = useState(0);
  const onCanvasChange = useCallback(() => setCanvasTick((t) => t + 1), []);

  const [running, setRunning] = useState(false);
  const [currentReportId, setCurrentReportId] = useState<number | null>(null);
  const [currentDetail, setCurrentDetail] = useState<AnalyzeReportDetail | null>(null);
  const [loadedFlowId, setLoadedFlowId] = useState<number | null>(null);

  const getConfig = useCallback(
    () =>
      canvasRef.current?.getConfig() ?? {
        included_sections: [],
        persona_overrides: {},
      },
    [],
  );

  const handleRun = useCallback(async (override?: AnalyzeBusRequest) => {
    // When invoked from a DOM onClick the event object leaks in as `override`;
    // only honor it when it actually carries a ticker (bus-driven auto-run).
    const ov = override && typeof override === 'object' && 'ticker' in override
      ? override
      : undefined;
    const cfg = getConfig();
    const input = canvasRef.current?.getInputData();
    if (!input) {
      toast.error(t('analyze.errors.noInput'));
      return;
    }
    const ticker = (ov?.ticker ?? input.ticker).trim().toUpperCase();
    if (!ticker) {
      toast.error(t('analyze.errors.noTicker'));
      return;
    }
    // Debate settings now live on the Debate node, not the Input node.
    // If the Debate node is on canvas, its values win; otherwise we send
    // safe defaults (no personas, rounds=3).
    const debate = canvasRef.current?.getDebateSettings()
      ?? { use_personas: false, debate_rounds: 3 };
    const req: AnalyzeRunRequest = {
      ticker,
      objective: input.objective,
      position_budget_usd: input.budget_usd ? parseFloat(input.budget_usd) : null,
      already_holds: input.already_holds,
      cost_basis_usd: input.already_holds && input.cost_basis_usd
        ? parseFloat(input.cost_basis_usd)
        : null,
      risk_tolerance: input.risk_tolerance,
      use_personas: debate.use_personas,
      debate_rounds: debate.debate_rounds,
      included_sections: cfg.included_sections,
      persona_overrides: Object.keys(cfg.persona_overrides).length
        ? cfg.persona_overrides
        : null,
      // Phase 7 i18n — defaults to 'en' if user hasn't picked anything
      // on the Input node (fallback covers older saved canvases).
      report_language: input.report_language ?? 'en',
      // Phase 8 — defaults to 'us'. Older saved canvases lack this field.
      market: ov?.market ?? input.market ?? 'us',
    };
    setRunning(true);
    try {
      const detail = await analyzeService.runAnalyze(req);
      setCurrentReportId(detail.id);
      setCurrentDetail(detail);
      // Tell the sidebar Recent Reports list to refresh + nudge the user there.
      analyzeBus.notifyReportsChanged();
      toast.success(
        t('analyze.toasts.completeInReports', {
          ticker: detail.ticker,
          id: detail.id,
          defaultValue: 'Report #{{id}} for {{ticker}} is ready — open it from Recent Reports in the sidebar.',
        }),
      );
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setRunning(false);
    }
  }, [getConfig, t]);

  // Bus-driven one-click analyze (from Screener / Scanner). Pre-fills the
  // Input node with the requested ticker + market, then auto-runs. Handles
  // both "tab already open" (subscribe fires) and "tab opening fresh"
  // (takePending on mount); the 60ms delay lets patchInput's setNodes apply.
  useEffect(() => {
    const runFor = (req: AnalyzeBusRequest) => {
      canvasRef.current?.patchInput({ ticker: req.ticker, market: req.market });
      window.setTimeout(() => { void handleRun(req); }, 60);
    };
    const queued = analyzeBus.takePending();
    if (queued) runFor(queued);
    return analyzeBus.subscribe((req) => {
      analyzeBus.takePending(); // clear so a later remount won't re-run it
      runFor(req);
    });
  }, [handleRun]);

  // Re-read canvas state every render (tick triggers a refresh).
  void canvasTick;
  const cfg = getConfig();
  const presentSet = canvasRef.current?.getPresentSections() ?? new Set<string>();
  const hasInput = canvasRef.current?.hasInputNode() ?? false;
  const sectionCount = cfg.included_sections.length;

  // Fetch the report HTML with auth (via the global fetch interceptor) and
  // open it from a blob URL — a window.open navigation wouldn't carry the token.
  const { url: iframeSrc } = useReportHtml(currentReportId);

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
        presentSections={presentSet}
        hasInputNode={hasInput}
        onAddSection={(name) => canvasRef.current?.addSection(name)}
        onAddInput={() => {
          if (canvasRef.current?.hasInputNode()) {
            canvasRef.current.focusInput();
          } else {
            canvasRef.current?.addInputNode();
          }
        }}
        onResetToDefault={() => canvasRef.current?.resetToDefault()}
      />

      {/* 2. Canvas dominates the viewport — full width */}
      <div className="flex-1 min-h-0 border-b overflow-hidden">
        <FlowCanvas ref={canvasRef} onChange={onCanvasChange} />
      </div>

      {/* 3. Collapsible bottom — verdict card, status pills, report iframe, history */}
      <div className="flex-shrink-0 max-h-[40vh] overflow-auto bg-background">
        {showLiveDetail && currentDetail?.verdict && (
          <div className="px-3 pt-3">
            <VerdictCard verdict={currentDetail.verdict} />
          </div>
        )}
        <Accordion
          type="multiple"
          defaultValue={['report']}
          className="px-3"
        >
          {showLiveDetail && currentDetail && (
            <AccordionItem value="status">
              <AccordionTrigger className="py-2 text-xs uppercase font-medium">
                {t('analyze.status.title')}
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
                {t('analyze.reports.reportN', { id: currentReportId })}
              </AccordionTrigger>
              <AccordionContent className="pb-3">
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7"
                    onClick={() => window.open(iframeSrc, '_blank', 'noopener')}
                  >
                    <ExternalLink className="size-3 mr-1" />
                    {t('analyze.reports.openInNewTab')}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7"
                    onClick={async () => {
                      if (!currentReportId) return;
                      try {
                        const res = await analyzeService.emailReport(currentReportId);
                        if (res.sent.length) {
                          toast.success(
                            t('analyze.reports.emailSent', { count: res.sent.length }),
                          );
                        }
                        if (res.failed.length) {
                          toast.error(
                            t('analyze.reports.emailFailed', { count: res.failed.length }),
                          );
                        }
                      } catch (e) {
                        toast.error(e instanceof Error ? e.message : 'Failed to email report');
                      }
                    }}
                  >
                    <Mail className="size-3 mr-1" />
                    {t('analyze.reports.emailReport')}
                  </Button>
                </div>
              </AccordionContent>
            </AccordionItem>
          )}
        </Accordion>
      </div>
    </div>
  );
}
