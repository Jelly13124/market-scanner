// Global "does the user have a usable LLM key?" status. Drives the hard
// onboarding gate (Run actions disable until true) + the Home checklist's
// first step. Fetches once on mount; `refresh()` re-checks after the user
// saves/clears a key in Settings.

import { apiKeysService } from '@/services/api-keys-api';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

// LLM-provider keys — the UPPERCASE env-var names from LLM_API_KEYS in
// settings/api-keys.tsx. Analysis needs one of these; a data-only key
// (FINANCIAL_DATASETS_API_KEY) does NOT satisfy the gate.
const LLM_PROVIDERS = new Set<string>([
  'ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY', 'GROQ_API_KEY', 'GOOGLE_API_KEY',
  'OPENAI_API_KEY', 'MOONSHOT_API_KEY', 'OPENROUTER_API_KEY', 'GIGACHAT_API_KEY',
]);

interface ApiKeysStatusValue {
  /** true when ≥1 active LLM-provider key is saved. */
  hasKeys: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
}

const ApiKeysStatusContext = createContext<ApiKeysStatusValue | null>(null);

export function useApiKeysStatus(): ApiKeysStatusValue {
  const ctx = useContext(ApiKeysStatusContext);
  if (!ctx) throw new Error('useApiKeysStatus must be used within an ApiKeysStatusProvider');
  return ctx;
}

export function ApiKeysStatusProvider({ children }: { children: ReactNode }) {
  const [hasKeys, setHasKeys] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const keys = await apiKeysService.getAllApiKeys();
      setHasKeys(keys.some((k) => k.is_active && k.has_key && LLM_PROVIDERS.has(k.provider)));
    } catch {
      // Conservative: a failed probe keeps the gate ON (hasKeys=false). The
      // user always has a visible route to add a key, so they're never trapped.
      setHasKeys(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <ApiKeysStatusContext.Provider value={{ hasKeys, loading, refresh }}>
      {children}
    </ApiKeysStatusContext.Provider>
  );
}
