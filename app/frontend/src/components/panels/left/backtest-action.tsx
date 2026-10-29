// Small button in the left sidebar that opens / focuses the Backtest tab.

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { History } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function BacktestAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('backtest', 'backtest')) {
      setActiveTab('backtest');
      return;
    }
    openTab({
      id: 'backtest',
      ...TabService.createBacktestTab(),
    });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('sidebar.backtest')}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('sidebar.backtestTooltip')}
        >
          <History size={14} />
        </Button>
      </div>
    </div>
  );
}
