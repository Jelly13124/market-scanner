// AnalyzePanel — main view for the per-stock SOP analyzer tab.
//
// Top: gate form + flow-style module picker (left column) and the
// rendered iframe (right column, when a report exists).
// Bottom: recent reports list.

import { analyzeService } from '@/services/analyze-service';
import type { AnalyzeRunRequest } from '@/types/analyze';
import { REQUIRED_SECTIONS, SECTION_ORDER } from '@/types/analyze';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import { AnalyzeForm } from './analyze-form';
import { ModulePicker } from './module-picker';
import { ReportList } from './report-list';

export function AnalyzePanel() {
  const [included, setIncluded] = useState<Set<string>>(
    () => new Set(SECTION_ORDER),  // default = full SOP
  );
  const [running, setRunning] = useState(false);
  const [currentReportId, setCurrentReportId] = useState<number | null>(null);
  const [tickerFilter, setTickerFilter] = useState<string | undefined>(undefined);

  const toggle = useCallback((name: string) => {
    setIncluded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }, []);

  const applyPreset = useCallback((preset: 'all' | 'required') => {
    setIncluded(
      preset === 'all' ? new Set(SECTION_ORDER) : new Set(REQUIRED_SECTIONS),
    );
  }, []);

  const handleRun = useCallback(
    async (req: AnalyzeRunRequest) => {
      setRunning(true);
      try {
        const detail = await analyzeService.runAnalyze(req);
        setCurrentReportId(detail.id);
        setTickerFilter(detail.ticker);
        toast.success(`Analyze complete: ${detail.ticker} (id ${detail.id})`);
      } catch (e) {
        toast.error((e as Error).message);
      } finally {
        setRunning(false);
      }
    },
    [],
  );

  const iframeSrc =
    currentReportId != null
      ? analyzeService.reportHtmlUrl(currentReportId)
      : null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* Top: form + picker, side-by-side */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="border rounded p-3 bg-accent/20">
            <AnalyzeForm
              running={running}
              onRun={(req) => handleRun(req)}
              included={included}
            />
          </div>
          <div className="border rounded p-3 bg-accent/20">
            <ModulePicker
              included={included}
              onToggle={toggle}
              onPreset={applyPreset}
            />
          </div>
        </div>

        {/* Middle: iframe with the rendered report */}
        {iframeSrc && (
          <div className="border rounded overflow-hidden">
            <iframe
              key={currentReportId}
              src={iframeSrc}
              title={`Analyze report ${currentReportId}`}
              className="w-full"
              style={{ height: 800, border: 0 }}
            />
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
