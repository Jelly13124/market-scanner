import { ScreenerStatusResponse } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface StatusBarProps {
  status: ScreenerStatusResponse | null;
  matchCount: number;
}

export function StatusBar({ status, matchCount }: StatusBarProps) {
  const { t } = useTranslation();
  if (!status || !status.snapshot_date) {
    return (
      <div className="text-xs text-muted-foreground py-1 px-2">
        {t('screener.status.no_data', 'No snapshot yet')}
      </div>
    );
  }
  const updatedLabel = status.last_updated
    ? new Date(status.last_updated).toLocaleString()
    : status.snapshot_date;
  return (
    <div className="text-xs text-muted-foreground py-1 px-2 flex justify-between">
      <span>
        {t('screener.status.matched', 'Matched')}: <b>{matchCount}</b>
      </span>
      <span>
        {t('screener.status.data_as_of', 'Data as of')} {updatedLabel}
        {' · '}
        US: {status.by_market.US ?? 0} · CN: {status.by_market.CN ?? 0}
      </span>
    </div>
  );
}
