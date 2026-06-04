import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { Home } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function HomeAction() {
  const { closeAllTabs } = useTabsContext();
  const { t } = useTranslation();

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('sidebar.home')}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={closeAllTabs}
          className="h-6 w-6 text-primary hover-bg"
          title={t('sidebar.homeTooltip')}
        >
          <Home size={14} />
        </Button>
      </div>
    </div>
  );
}
