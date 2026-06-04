// Home — shown in the main area when no tab is open (tab-content's !activeTab
// branch). Hero + getting-started checklist + feature cards. Reuses the tab
// system to open features.

import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { useTranslation } from 'react-i18next';

import { GettingStartedChecklist } from './getting-started-checklist';

export function HomeScreen() {
  const { t } = useTranslation();
  const { openTab } = useTabsContext();

  const cards = [
    { id: 'analyze' as const, make: () => TabService.createAnalyzeTab() },
    { id: 'scanner' as const, make: () => TabService.createScannerTab() },
    { id: 'screener' as const, make: () => TabService.createScreenerTab() },
    { id: 'lab' as const, make: () => TabService.createLabTab() },
  ];

  return (
    <div className="h-full w-full overflow-auto bg-background">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        <div>
          <h1 className="text-2xl font-semibold text-primary">{t('onboarding.home.title')}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t('onboarding.home.subtitle')}</p>
        </div>

        <GettingStartedChecklist />

        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
            {t('onboarding.home.exploreLabel')}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {cards.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => openTab({ id: c.id, ...c.make() })}
                className="rounded-lg border p-3 text-left hover:bg-accent/60 transition-colors"
              >
                <div className="text-sm font-medium">{t(`onboarding.home.cards.${c.id}.title`)}</div>
                <div className="text-xs text-muted-foreground mt-1">{t(`onboarding.home.cards.${c.id}.desc`)}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
