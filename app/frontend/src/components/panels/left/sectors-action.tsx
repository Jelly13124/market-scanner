// Small button in the left sidebar that opens / focuses the Sectors board tab
// (a heatmap grid of GICS sectors with live aggregate performance).

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { LayoutGrid } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function SectorsAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('sectors', 'sectors')) {
      setActiveTab('sectors');
      return;
    }
    openTab({
      id: 'sectors',
      ...TabService.createSectorsTab(),
    });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('sectors.tab.title', 'Sectors')}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('sectors.openTooltip', 'Open sector board')}
        >
          <LayoutGrid size={14} />
        </Button>
      </div>
    </div>
  );
}
