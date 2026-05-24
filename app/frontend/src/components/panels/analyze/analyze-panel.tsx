// AnalyzePanel — main view for the per-stock SOP analyzer tab.
//
// Top: gate form + flow-style module picker (left column) and the
// rendered iframe (right column, when a report exists).
// Bottom: recent reports list.

import { Button } from '@/components/ui/button';
import { analyzeService } from '@/services/analyze-service';
import type { AnalyzeReportDetail, AnalyzeRunRequest, SectionPayloadAPI } from '@/types/analyze';
import { REQUIRED_SECTIONS, SECTION_LABELS, SECTION_ORDER } from '@/types/analyze';
import { ExternalLink } from 'lucide-react';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import { AnalyzeForm } from './analyze-form';
import { ModulePicker } from './module-picker';
import { ReportList } from './report-list';

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
  // Render pills in canonical SECTION_ORDER, then any extras.
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
  const [included, setIncluded] = useState<Set<string>>(
    () => new Set(SECTION_ORDER),  // default = full SOP
  );
  const [running, setRunning] = useState(false);
  const [currentReportId, setCurrentReportId] = useState<number | null>(null);
  const [currentDetail, setCurrentDetail] = useState<AnalyzeReportDetail | null>(null);
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
        setCurrentDetail(detail);
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

  // Section status + persona box only apply to the most recent live run
  // (currentDetail). Selecting an older report from the list switches the
  // iframe but we don't refetch the full detail, so hide these for that case.
  const showLiveDetail = currentDetail != null && currentDetail.id === currentReportId;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {/* How-this-works caption */}
        <div className="text-xs text-muted-foreground">
          Full SOP analysis: 16 sections + technical-signal backtest. 60-120s per run.
        </div>

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

        {/* Status pills + persona summary (live run only) */}
        {showLiveDetail && currentDetail && (
          <>
            <SectionStatusPanel detail={currentDetail} />
            <PersonaAssignmentsBox detail={currentDetail} />
          </>
        )}

        {/* Middle: iframe with the rendered report */}
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
