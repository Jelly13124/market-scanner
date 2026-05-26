// Phase 6G: previous backtest runs for this strategy.

import { backtestService } from '@/services/backtest-service';
import { cn } from '@/lib/utils';
import type { BacktestResponse } from '@/types/backtest';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

interface Props {
  strategyId: number;
  selectedBacktestId: number | null;
  onSelectBacktest: (id: number) => void;
}

export function BacktestHistory({
  strategyId,
  selectedBacktestId,
  onSelectBacktest,
}: Props) {
  const [items, setItems] = useState<BacktestResponse[]>([]);
  const { t } = useTranslation();

  const reload = useCallback(() => {
    backtestService
      .list(strategyId)
      .then(setItems)
      .catch((e: Error) => toast.error(e.message));
  }, [strategyId]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (items.length === 0) return null;

  return (
    <div className="border-t p-3">
      <div className="text-xs font-medium uppercase mb-2">
        {t('lab.backtest.history', { count: items.length })}
      </div>
      <div className="space-y-1">
        {items.map((b) => (
          <button
            key={b.id}
            onClick={() => onSelectBacktest(b.id)}
            className={cn(
              'w-full text-left px-2 py-1 text-xs rounded hover:bg-accent/40',
              b.id === selectedBacktestId && 'bg-accent/30',
            )}
          >
            <span className="font-mono">#{b.id}</span>
            <span className="ml-2">{b.created_at.slice(0, 10)}</span>
            <span className="ml-2 font-medium">{b.verdict_label}</span>
            {b.oos_cagr != null && (
              <span className="ml-2 text-muted-foreground">
                OOS CAGR {(b.oos_cagr * 100).toFixed(1)}%
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
