// The Home "getting started" checklist. Each step's done-state comes from a
// real backend probe (key/report/watchlist/schedule); actions reuse the tab
// system + the analyze bus. Dismissable; auto-condenses once all done.

import { useApiKeysStatus } from '@/contexts/api-keys-status-context';
import { useTabsContext } from '@/contexts/tabs-context';
import { useRequestAnalyze } from '@/hooks/use-request-analyze';
import { analyzeService } from '@/services/analyze-service';
import { reportSchedulesService } from '@/services/report-schedules-api';
import { TabService } from '@/services/tab-service';
import { watchlistService } from '@/services/watchlist-service';
import { Check, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

const DISMISS_KEY = 'onboarding-checklist-dismissed';

export function GettingStartedChecklist() {
  const { t } = useTranslation();
  const { hasKeys } = useApiKeysStatus();
  const { openTab, setActiveTab, isTabOpen } = useTabsContext();
  const requestAnalyze = useRequestAnalyze();

  const [hasReport, setHasReport] = useState(false);
  const [hasWatch, setHasWatch] = useState(false);
  const [hasSchedule, setHasSchedule] = useState(false);
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
  });

  useEffect(() => {
    analyzeService.listReports(undefined, 1).then((r) => setHasReport(r.length > 0)).catch(() => {});
    watchlistService.list().then((w) => setHasWatch(w.length > 0)).catch(() => {});
    reportSchedulesService.list().then((s) => setHasSchedule(s.length > 0)).catch(() => {});
  }, []);

  const openSettings = () => {
    if (isTabOpen('settings', 'settings')) setActiveTab('settings');
    else openTab({ id: 'settings', ...TabService.createSettingsTab() });
  };
  const openWatchlist = () => {
    if (isTabOpen('watchlist', 'watchlist')) setActiveTab('watchlist');
    else openTab({ id: 'watchlist', ...TabService.createWatchlistTab() });
  };

  const steps = [
    { id: 'key', done: hasKeys, action: openSettings, actionKey: 'addKey' },
    { id: 'analyze', done: hasReport, action: () => requestAnalyze('NVDA', 'us'), actionKey: 'tryNvda' },
    { id: 'watch', done: hasWatch, action: openWatchlist, actionKey: 'openWatchlist' },
    { id: 'schedule', done: hasSchedule, action: openSettings, actionKey: 'openSchedules' },
  ] as const;

  const doneCount = steps.filter((s) => s.done).length;

  if (dismissed) return null;

  if (doneCount === steps.length) {
    return (
      <div className="rounded-lg border px-4 py-3 text-sm text-green-600">
        {t('onboarding.checklist.allSet')}
      </div>
    );
  }

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* ignore */ }
    setDismissed(true);
  };

  return (
    <div className="rounded-lg border p-4 bg-accent/20">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold">
          🚀 {t('onboarding.checklist.title')} · {doneCount}/{steps.length}
        </div>
        <button
          type="button"
          onClick={dismiss}
          title={t('onboarding.checklist.dismiss')}
          className="text-muted-foreground hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </div>
      <ul className="space-y-2">
        {steps.map((s) => (
          <li key={s.id} className="flex items-center gap-3 text-sm">
            <span
              className={`grid place-items-center size-5 rounded-full border shrink-0 ${
                s.done ? 'bg-green-600 border-green-600 text-white' : 'text-muted-foreground'
              }`}
            >
              {s.done ? <Check className="size-3" /> : null}
            </span>
            <span className={`flex-1 ${s.done ? 'line-through text-muted-foreground' : ''}`}>
              {t(`onboarding.checklist.steps.${s.id}`)}
            </span>
            {!s.done && (
              <button
                type="button"
                onClick={s.action}
                className="text-xs text-primary hover:underline shrink-0"
              >
                {t(`onboarding.checklist.actions.${s.actionKey}`)}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
