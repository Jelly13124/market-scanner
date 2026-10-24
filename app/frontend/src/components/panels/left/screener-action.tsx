// Small button in the left sidebar that opens / focuses the Screener tab.

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { Filter } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function ScreenerAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('screener', 'screener')) {
      setActiveTab('screener');
      return;
    }
    openTab({
      id: 'screener',
      ...TabService.createScreenerTab(),
    });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('sidebar.screener', 'Screener')}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('sidebar.screenerTooltip', 'Open Screener')}
        >
          <Filter size={14} />
        </Button>
      </div>
    </div>
  );
}
