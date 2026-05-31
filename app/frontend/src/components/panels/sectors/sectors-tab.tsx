// Sectors board — a heatmap grid of GICS sector cards with live aggregate
// performance for the latest US snapshot. Clicking a sector opens / focuses
// the Screener tab pre-filtered to that sector (via the screener-filter bus).
//
// US only: CN snapshots carry no sector data, so GET /screener/sectors?market=CN
// returns []. The data is the latest daily snapshot (not intraday).

import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { cn } from '@/lib/utils';
import { requestScreenerSectorFilter } from '@/services/analyze-bus';
import { getSectorSummary } from '@/services/screener-service';
import { TabService } from '@/services/tab-service';
import { SectorSummaryRow } from '@/types/screener';
import { Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

/** Parse a fraction string (e.g. "0.0263") → "+2.63%". "—" when absent. */
function fmtPct(fracString: string | null): string {
  if (fracString === null) return '—';
  const n = Number(fracString);
  if (!isFinite(n)) return '—';
  const pct = n * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

export function SectorsTab() {
  const { t } = useTranslation();
  const { openTab, isTabOpen, setActiveTab } = useTabsContext();

  const [rows, setRows] = useState<SectorSummaryRow[]>([]);
  const [loading, setLoading] = useState(false);

  function load() {
    let alive = true;
    setLoading(true);
    getSectorSummary('US')
      .then((r) => {
        if (alive) setRows(r);
      })
      .catch((e) => {
        console.error('getSectorSummary failed', e);
        if (alive) setRows([]);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }

  useEffect(() => load(), []);

  function handleSectorClick(sector: string) {
    // Open / focus the Screener tab (same wiring as screener-action.tsx), then
    // ask it to apply the sector filter. If the Screener is mounting fresh it
    // picks up the pending sector on mount; if already mounted, its subscriber
    // fires immediately.
    if (isTabOpen('screener', 'screener')) {
      setActiveTab('screener');
    } else {
      openTab({ id: 'screener', ...TabService.createScreenerTab() });
    }
    requestScreenerSectorFilter(sector);
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-2 pt-2">
        <div className="text-sm font-semibold">{t('sectors.tab.title', 'Sectors')}</div>
        <span className="text-xs text-muted-foreground">
          {t('sectors.asOf', 'as of latest snapshot · US')}
        </span>
        <Button
          variant="outline"
          size="sm"
          className="ml-auto h-8 gap-1 text-xs"
          onClick={() => load()}
          disabled={loading}
          title={t('sectors.refresh.tooltip', 'Re-fetch sector performance')}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
          {t('sectors.refresh.button', 'Refresh')}
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto px-2 py-2">
        {loading ? (
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-12">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('common.loading', 'Loading...')}
          </div>
        ) : rows.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-12">
            {t('sectors.empty', '暂无板块数据（需先有快照）')}
          </div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
            {rows.map((row) => {
              const avg = row.avg_change_pct === null ? null : Number(row.avg_change_pct);
              const up = avg !== null && isFinite(avg) && avg > 0;
              const down = avg !== null && isFinite(avg) && avg < 0;
              return (
                <button
                  key={row.sector}
                  type="button"
                  onClick={() => handleSectorClick(row.sector)}
                  title={t('sectors.cardTooltip', 'Open Screener filtered to {{sector}}', {
                    sector: row.sector,
                  })}
                  className={cn(
                    'flex flex-col items-start gap-1.5 rounded-md border p-3 text-left transition-colors hover-bg',
                    up && 'bg-green-500/5 border-green-500/30',
                    down && 'bg-red-500/5 border-red-500/30',
                  )}
                >
                  <div className="text-xs font-medium text-foreground truncate w-full">
                    {row.sector}
                  </div>
                  <div
                    className={cn(
                      'text-2xl font-bold tabular-nums',
                      up && 'text-green-500',
                      down && 'text-red-500',
                    )}
                  >
                    {fmtPct(row.avg_change_pct)}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {t('sectors.stats', '{{count}} 只 · {{gainers}}↑ {{losers}}↓', {
                      count: row.count,
                      gainers: row.gainers,
                      losers: row.losers,
                    })}
                  </div>
                  {row.top_gainer && (
                    <div className="text-[11px] text-green-500 truncate w-full">
                      ▲ {row.top_gainer.ticker} {fmtPct(row.top_gainer.change_pct)}
                    </div>
                  )}
                  {row.top_loser && (
                    <div className="text-[11px] text-red-500 truncate w-full">
                      ▼ {row.top_loser.ticker} {fmtPct(row.top_loser.change_pct)}
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
