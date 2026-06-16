// Left-sidebar button that opens / focuses the Paper tab (read-only forward-test
// performance: per-sleeve metrics, graduation verdict, equity curve).

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { TrendingUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function PaperAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('paper', 'paper')) {
      setActiveTab('paper');
      return;
    }
    openTab({ id: 'paper', ...TabService.createPaperTab() });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">
        {t('paper.tab.title', 'Paper')}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('paper.openTooltip', 'Open paper-trading panel')}
        >
          <TrendingUp size={14} />
        </Button>
      </div>
    </div>
  );
}
