import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { getUniverseSnapshot } from '@/services/screener-service';
import type { StrategyResponse } from '@/types/strategy';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { StrategyDetails } from './spec-viewer';

export function ReviewBacktest({strategy, onCancel, onConfirm}: {
  strategy: StrategyResponse; onCancel: () => void; onConfirm: () => void;
}) {
  const { t } = useTranslation();
  const [tickers, setTickers] = useState<string[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    getUniverseSnapshot(strategy.universe_snapshot_id!).then(snapshot => {
      if (active) setTickers(snapshot.tickers);
    }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [strategy.universe_snapshot_id]);

  return <Dialog open onOpenChange={open => { if (!open) onCancel(); }}>
    <DialogContent className="flex max-h-[88vh] max-w-2xl flex-col">
      <DialogHeader>
        <DialogTitle>{t('draft.review')} · {strategy.name} v{strategy.version}</DialogTitle>
        <DialogDescription>{t('draft.source', {report: strategy.source_report_id, signal: strategy.source_scan_result_id})}</DialogDescription>
      </DialogHeader>
      <div className="overflow-y-auto text-sm">
        <p>{t('draft.engine')}</p>
        <p className="mt-2 font-medium">{t('draft.snapshot', {id: strategy.universe_snapshot_id})}</p>
        {error ? <p role="alert">{error}</p> : <p>{tickers.length ? tickers.join(', ') : t('scanner.loadingUniverse')}</p>}
        <StrategyDetails spec={strategy.spec_json} />
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>{t('common.cancel')}</Button>
        <Button disabled={!tickers.length} onClick={onConfirm}>{t('draft.confirm')}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
