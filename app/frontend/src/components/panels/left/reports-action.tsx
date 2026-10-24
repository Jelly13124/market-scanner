// Left-sidebar button that opens / focuses the Reports tab (full list of
// saved SOP reports with batch delete + pop-out viewer).

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { FileText } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function ReportsAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('reports', 'reports')) {
      setActiveTab('reports');
      return;
    }
    openTab({ id: 'reports', ...TabService.createReportsTab() });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">
        {t('analyze.reports.title')}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('analyze.reports.title')}
        >
          <FileText size={14} />
        </Button>
      </div>
    </div>
  );
}
