import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { strategyService } from '@/services/strategy-service';
import { TabService } from '@/services/tab-service';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

export function CreateStrategyDraft({ reportId, onOpen }: {reportId: number; onOpen?: () => void}) {
  const { t } = useTranslation();
  const { openTab } = useTabsContext();
  const [busy, setBusy] = useState(false);

  async function openDraft() {
    setBusy(true);
    try {
      const strategy = await strategyService.fromReport(reportId);
      onOpen?.();
      openTab({id: 'backtest', ...TabService.createBacktestTab(strategy.id)});
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return <Button size="sm" variant="outline" disabled={busy} onClick={openDraft}>{t('draft.create')}</Button>;
}
