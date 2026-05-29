// useRequestAnalyze — one-click "send this ticker to the Analyze tab".
//
// Queues the ticker on the analyze-bus (which the Analyze panel consumes to
// pre-fill its Input node and auto-run), then opens or focuses the Analyze
// tab. Used by the Screener table and the Scanner watchlist.

import { useCallback } from 'react';

import { useTabsContext } from '@/contexts/tabs-context';
import { analyzeBus } from '@/services/analyze-bus';
import { TabService } from '@/services/tab-service';

export function useRequestAnalyze() {
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();

  return useCallback(
    (ticker: string, market: 'us' | 'cn' = 'us') => {
      const clean = ticker.trim().toUpperCase();
      if (!clean) return;
      // Queue first so an already-mounted Analyze panel runs immediately;
      // a fresh tab will read the pending request on mount.
      analyzeBus.requestAnalyze({ ticker: clean, market });
      if (isTabOpen('analyze', 'analyze')) {
        setActiveTab('analyze');
      } else {
        openTab({ id: 'analyze', ...TabService.createAnalyzeTab() });
      }
    },
    [openTab, isTabOpen, setActiveTab],
  );
}
