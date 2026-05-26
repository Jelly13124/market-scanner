// Phase 9: collapsible API Keys panel in the left sidebar.
// Compact alternative to the full Settings → API Keys page.
// Auto-saves on blur (not on every keystroke) and uses the existing
// apiKeysService backend (which writes to .env via the FastAPI route).

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { apiKeysService } from '@/services/api-keys-api';
import {
  ChevronDown, ChevronRight, Eye, EyeOff, ExternalLink, Key,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

/** The 6 keys we surface in the sidebar quick-panel. Same shape as the
 * full Settings page uses, kept narrow for sidebar density. */
interface QuickKey {
  provider: string;   // env var name (e.g. DEEPSEEK_API_KEY)
  label: string;      // short display name
  url: string;        // where to register
  group: 'llm' | 'data';
}

const QUICK_KEYS: QuickKey[] = [
  { provider: 'DEEPSEEK_API_KEY',           label: 'DeepSeek',  url: 'https://platform.deepseek.com/',   group: 'llm' },
  { provider: 'OPENAI_API_KEY',             label: 'OpenAI',    url: 'https://platform.openai.com/',     group: 'llm' },
  { provider: 'ANTHROPIC_API_KEY',          label: 'Anthropic', url: 'https://console.anthropic.com/',   group: 'llm' },
  { provider: 'FINNHUB_API_KEY',            label: 'Finnhub',   url: 'https://finnhub.io/',              group: 'data' },
  { provider: 'EODHD_API_KEY',              label: 'EODHD',     url: 'https://eodhd.com/',               group: 'data' },
  { provider: 'FINANCIAL_DATASETS_API_KEY', label: 'FinDataset', url: 'https://financialdatasets.ai/',   group: 'data' },
];

export function ApiKeysSection() {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [savingProvider, setSavingProvider] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const summary = await apiKeysService.getAllApiKeys();
      const next: Record<string, string> = {};
      // Use Promise.all so the 6 GETs run in parallel
      await Promise.all(summary.map(async (s) => {
        try {
          const full = await apiKeysService.getApiKey(s.provider);
          next[s.provider] = full.key_value;
        } catch { /* ignore — key may be unset */ }
      }));
      setValues(next);
    } catch (e) {
      console.warn('Failed to load API keys for sidebar panel', e);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    // Lazy-load on first expand to avoid the 6 GETs on every page mount
    if (expanded && !loaded) {
      load();
    }
  }, [expanded, loaded, load]);

  async function saveKey(provider: string, value: string) {
    setSavingProvider(provider);
    try {
      const trimmed = value.trim();
      if (trimmed) {
        await apiKeysService.createOrUpdateApiKey({
          provider, key_value: trimmed, is_active: true,
        });
      } else {
        try { await apiKeysService.deleteApiKey(provider); } catch { /* expected if absent */ }
      }
    } catch (e) {
      toast.error(`${provider}: ${(e as Error).message}`);
    } finally {
      setSavingProvider(null);
    }
  }

  function onChange(provider: string, value: string) {
    setValues((prev) => ({ ...prev, [provider]: value }));
  }

  function onBlur(provider: string) {
    saveKey(provider, values[provider] || '');
  }

  function toggleVisible(provider: string) {
    setVisible((prev) => ({ ...prev, [provider]: !prev[provider] }));
  }

  // "N/6 set" badge text — count keys that have any non-empty value
  const setCount = Object.values(values).filter((v) => v && v.trim()).length;

  return (
    <div className="border-b flex-shrink-0">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className={cn(
          'w-full p-2 flex items-center gap-2 hover:bg-accent/40 transition-colors',
          'text-primary text-sm font-medium',
        )}
      >
        {expanded
          ? <ChevronDown className="size-3 ml-2" />
          : <ChevronRight className="size-3 ml-2" />}
        <Key className="size-3" />
        <span className="flex-1 text-left">{t('sidebar.apiKeys')}</span>
        <span className="text-[10px] text-muted-foreground mr-2">
          {loaded ? `${setCount}/${QUICK_KEYS.length}` : '...'}
        </span>
      </button>

      {expanded && (
        <div className="px-2 pb-2 space-y-1">
          {QUICK_KEYS.map((k) => {
            const isVisible = !!visible[k.provider];
            const isSaving = savingProvider === k.provider;
            return (
              <div key={k.provider} className="flex flex-col gap-1 py-1">
                <div className="flex items-center gap-1 px-1">
                  <span className="text-[11px] font-medium flex-1 truncate" title={k.provider}>
                    {k.label}
                    <span className="text-[9px] uppercase text-muted-foreground ml-1">
                      {k.group}
                    </span>
                  </span>
                  <a
                    href={k.url} target="_blank" rel="noopener noreferrer"
                    className="text-muted-foreground hover:text-primary"
                    title={t('sidebar.apiKeysGetKey')}
                  >
                    <ExternalLink className="size-3" />
                  </a>
                </div>
                <div className="flex items-center gap-1">
                  <Input
                    type={isVisible ? 'text' : 'password'}
                    value={values[k.provider] || ''}
                    onChange={(e) => onChange(k.provider, e.target.value)}
                    onBlur={() => onBlur(k.provider)}
                    placeholder={isSaving ? t('common.loading') : '...'}
                    disabled={isSaving}
                    className="h-7 text-xs font-mono"
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={() => toggleVisible(k.provider)}
                    title={t(isVisible ? 'sidebar.apiKeysHide' : 'sidebar.apiKeysShow')}
                  >
                    {isVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
                  </Button>
                </div>
              </div>
            );
          })}
          <div className="text-[10px] text-muted-foreground px-1 pt-1">
            {t('sidebar.apiKeysHint')}
          </div>
        </div>
      )}
    </div>
  );
}
