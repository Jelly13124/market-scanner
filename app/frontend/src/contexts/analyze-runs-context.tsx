// Analyze concurrent-run store (Task 11).
//
// Hoisted ABOVE the tab switcher (mounted in Layout) so in-flight analyses and
// their results survive tab switches AND tab close — the Analyze panel only
// renders a sidebar that READS this store. `startRun` fires runAnalyze
// non-blocking, so several analyses run at once (the backend serves independent
// /research/analyze requests concurrently). Each run is tracked
// running → done | failed with timestamps for a live elapsed timer.

import { uiReportLanguage } from '@/lib/ui-language';
import { analyzeBus } from '@/services/analyze-bus';
import { getAnalyzeConfigSnapshot, getOneClickUseCanvas } from '@/services/analyze-config-snapshot';
import { analyzeService } from '@/services/analyze-service';
import { SECTION_ORDER } from '@/types/analyze';
import type { AnalyzeReportDetail, AnalyzeRunRequest } from '@/types/analyze';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

export interface AnalyzeRun {
  /** Local id (ticker + timestamp + seq) — NOT the report id. */
  id: string;
  ticker: string;
  status: 'running' | 'done' | 'failed';
  startedAt: number;            // epoch ms
  finishedAt?: number;          // epoch ms (done | failed)
  reportId?: number;            // set when done
  detail?: AnalyzeReportDetail; // set when done (drives the panel's inline view)
  error?: string;               // set when failed
}

interface AnalyzeRunsContextValue {
  runs: AnalyzeRun[];
  /** Fire an analysis non-blocking; it appears in the sidebar immediately. */
  startRun: (req: AnalyzeRunRequest) => void;
  /** Drop all finished (done/failed) runs; keep the still-running ones. */
  clearFinished: () => void;
  /** Most-recently-FINISHED done run (or null) — the panel mirrors it inline. */
  latestDone: AnalyzeRun | null;
}

const AnalyzeRunsContext = createContext<AnalyzeRunsContextValue | null>(null);

export function useAnalyzeRuns() {
  const ctx = useContext(AnalyzeRunsContext);
  if (!ctx) throw new Error('useAnalyzeRuns must be used within an AnalyzeRunsProvider');
  return ctx;
}

// Module-level monotonic counter so two runs started in the same millisecond
// still get distinct ids.
let _seq = 0;

export function AnalyzeRunsProvider({ children }: { children: ReactNode }) {
  const [runs, setRuns] = useState<AnalyzeRun[]>([]);

  const startRun = useCallback((req: AnalyzeRunRequest) => {
    const id = `${req.ticker}-${Date.now()}-${_seq++}`;
    setRuns((prev) => [
      { id, ticker: req.ticker, status: 'running', startedAt: Date.now() },
      ...prev,
    ]);
    analyzeService
      .runAnalyze(req)
      .then((detail) => {
        setRuns((prev) =>
          prev.map((r) =>
            r.id === id
              ? { ...r, status: 'done', finishedAt: Date.now(), reportId: detail.id, detail }
              : r,
          ),
        );
        // Refresh the sidebar Recent Reports list.
        analyzeBus.notifyReportsChanged();
      })
      .catch((e: unknown) => {
        setRuns((prev) =>
          prev.map((r) =>
            r.id === id
              ? {
                  ...r,
                  status: 'failed',
                  finishedAt: Date.now(),
                  error: e instanceof Error ? e.message : String(e),
                }
              : r,
          ),
        );
      });
  }, []);

  // Track bus-driven one-click analyses (Screener / Scanner / Watchlist
  // "Analyze this ticker") in the SAME sidebar. The provider is mounted above
  // the tab switcher, so the run starts + tracks immediately — independent of
  // whether the Analyze tab/canvas has mounted yet (the panel only prefills its
  // canvas). Bus runs use a standard full-report config.
  useEffect(() => {
    return analyzeBus.subscribe((busReq) => {
      // Opt-in: reuse the Analyze canvas's sections + persona overrides for the
      // one-click run; otherwise a standard full report.
      const snap = getOneClickUseCanvas() ? getAnalyzeConfigSnapshot() : null;
      startRun({
        ticker: busReq.ticker,
        objective: 'general_research',
        risk_tolerance: 'balanced',
        use_personas: false,
        included_sections: snap?.included_sections?.length ? snap.included_sections : SECTION_ORDER,
        persona_overrides:
          snap && Object.keys(snap.persona_overrides ?? {}).length ? snap.persona_overrides : null,
        report_language: uiReportLanguage(),
        market: busReq.market,
      });
    });
  }, [startRun]);

  const clearFinished = useCallback(() => {
    setRuns((prev) => prev.filter((r) => r.status === 'running'));
  }, []);

  const latestDone = runs
    .filter((r) => r.status === 'done')
    .reduce<AnalyzeRun | null>(
      (best, r) => (!best || (r.finishedAt ?? 0) > (best.finishedAt ?? 0) ? r : best),
      null,
    );

  return (
    <AnalyzeRunsContext.Provider value={{ runs, startRun, clearFinished, latestDone }}>
      {children}
    </AnalyzeRunsContext.Provider>
  );
}
