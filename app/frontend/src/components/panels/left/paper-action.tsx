import { useTranslation } from 'react-i18next';

export function PaperAction() {
  const { t } = useTranslation();
  return (
    <div className="p-2 flex justify-between items-center border-b mt-4 text-muted-foreground">
      <span className="text-sm ml-4">{t('paper.tab.title', 'Paper')}</span>
      <span className="text-xs rounded border px-2 py-1">{t('paper.status')}</span>
    </div>
  );
}
