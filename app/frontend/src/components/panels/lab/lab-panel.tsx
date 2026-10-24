// Phase 6G: full Lab tab assembly - 3-col top (strategies / chat / spec)
// plus bottom result panel (runner / result / history).

import { strategyService } from '@/services/strategy-service';
import type { StrategyResponse } from '@/types/strategy';
import { useCallback, useEffect, useState } from 'react';
import { BacktestHistory } from './backtest-history';
import { BacktestResult } from './backtest-result';
import { BacktestRunner } from './backtest-runner';
import { ChatPanel } from './chat-panel';
import { SpecViewer } from './spec-viewer';
import { StrategyList } from './strategy-list';

export function LabPanel() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [strategy, setStrategy] = useState<StrategyResponse | null>(null);
  const [latestBacktestId, setLatestBacktestId] = useState<number | null>(null);

  const refetchStrategy = useCallback(() => {
    if (selectedId == null) {
      setStrategy(null);
      return;
    }
    strategyService
      .get(selectedId)
      .then(setStrategy)
      .catch(() => setStrategy(null));
  }, [selectedId]);

  useEffect(() => {
    refetchStrategy();
  }, [refetchStrategy]);

  // Reset the active backtest selection when the user switches strategies
  // so the bottom panel doesn't show a stale run from a different strategy.
  useEffect(() => {
    setLatestBacktestId(null);
  }, [selectedId]);

  return (
    <div className="h-full w-full flex flex-col bg-background overflow-hidden">
      <div className="grid grid-cols-[200px_1fr_400px] flex-1 min-h-0 overflow-hidden">
        <StrategyList selectedId={selectedId} onSelect={setSelectedId} />
        <ChatPanel strategyId={selectedId} onSpecUpdated={refetchStrategy} />
        <SpecViewer strategy={strategy} onSpecUpdated={refetchStrategy} />
      </div>
      {strategy && (
        <div className="border-t flex-shrink-0 max-h-[60%] overflow-auto">
          <BacktestRunner
            strategyId={strategy.id}
            onComplete={(id) => setLatestBacktestId(id)}
          />
          {latestBacktestId != null && (
            <BacktestResult backtestId={latestBacktestId} />
          )}
          <BacktestHistory
            strategyId={strategy.id}
            onSelectBacktest={setLatestBacktestId}
            selectedBacktestId={latestBacktestId}
          />
        </div>
      )}
    </div>
  );
}
