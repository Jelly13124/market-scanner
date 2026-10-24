import { Database } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function EmptyState() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center text-muted-foreground">
      <Database className="w-10 h-10 mb-3 opacity-40" />
      <div className="text-sm">
        {t('screener.empty.title', 'No snapshot yet')}
      </div>
      <div className="text-xs mt-1">
        {t('screener.empty.body', 'Snapshot runs nightly at 22:00 ET. Check back tomorrow.')}
      </div>
    </div>
  );
}
