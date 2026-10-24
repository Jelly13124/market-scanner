// Phase 7 i18n — SECTION_LABELS as a hook so labels translate at render
// time. The constant in types/analyze.ts is still used as a fallback +
// canonical key list, but consumers should prefer this hook.

import { SECTION_LABELS, SECTION_ORDER } from '@/types/analyze';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

export function useSectionLabels(): Record<string, string> {
  const { t, i18n } = useTranslation();
  // useMemo so the returned dict identity is stable across renders with
  // the same language — avoids unnecessary downstream re-renders.
  return useMemo(() => {
    const out: Record<string, string> = {};
    for (const name of SECTION_ORDER) {
      const key = `sections.${name}`;
      // i18n.exists guards against missing keys (fall back to English const)
      out[name] = i18n.exists(key) ? t(key) : (SECTION_LABELS[name] ?? name);
    }
    return out;
  }, [t, i18n.language]);
}
