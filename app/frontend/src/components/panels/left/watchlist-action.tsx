// Small button in the left sidebar that opens / focuses the Watchlist tab,
// where all watchlist management (create / search-add / rename / delete) and
// live per-ticker market data now live.

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { ListChecks } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function WatchlistAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('watchlist', 'watchlist')) {
      setActiveTab('watchlist');
      return;
    }
    openTab({
      id: 'watchlist',
      ...TabService.createWatchlistTab(),
    });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('watchlist.tab.title', 'Watchlist')}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('watchlist.openTooltip', 'Open live watchlist')}
        >
          <ListChecks size={14} />
        </Button>
      </div>
    </div>
  );
}
