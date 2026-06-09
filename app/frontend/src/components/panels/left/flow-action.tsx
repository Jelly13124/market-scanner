// Small button in the left sidebar that opens / focuses the Institutional
// Positioning tab (dealer gamma + off-exchange short volume for a ticker).

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { Activity } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function FlowAction() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();
  const { t } = useTranslation();

  function handleOpen() {
    if (isTabOpen('flow', 'flow')) {
      setActiveTab('flow');
      return;
    }
    openTab({
      id: 'flow',
      ...TabService.createInstitutionalFlowTab(),
    });
  }

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('flow.tab.title', 'Institutional')}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={handleOpen}
          className="h-6 w-6 text-primary hover-bg"
          title={t('flow.openTooltip', 'Open institutional positioning')}
        >
          <Activity size={14} />
        </Button>
      </div>
    </div>
  );
}
