// Live-run summary: section status pills (done/excluded/failed) + a
// compact persona-assignments line. Extracted from analyze-panel.tsx
// to keep that file lean.

import { SECTION_LABELS, SECTION_ORDER } from '@/types/analyze';
import type { AnalyzeReportDetail, SectionPayloadAPI } from '@/types/analyze';

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

export function SectionStatusPanel({ detail }: { detail: AnalyzeReportDetail }) {
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

export function PersonaAssignmentsBox({ detail }: { detail: AnalyzeReportDetail }) {
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
