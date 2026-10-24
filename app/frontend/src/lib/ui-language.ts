// Maps the current UI language to the report-output language used as the
// DEFAULT for new analyses (Phase 7 i18n): zh-* → 'zh', everything else → 'en'.
//
// Reads the app's i18n singleton directly so it works outside React components
// too (e.g. the analyze-runs store that fires bus-driven runs). React callers
// that also use useTranslation() re-render on language change, so the value
// stays current.

import i18n from '@/i18n';
import type { ReportLanguage } from '@/types/analyze';

export function uiReportLanguage(): ReportLanguage {
  const lang = i18n.resolvedLanguage || i18n.language || 'en';
  return lang.startsWith('zh') ? 'zh' : 'en';
}
