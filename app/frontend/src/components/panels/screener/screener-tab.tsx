import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useToastManager } from '@/hooks/use-toast-manager';
import { cn } from '@/lib/utils';
import {
  subscribeScreenerSectorFilter, takePendingScreenerSectorFilter,
} from '@/services/analyze-bus';
import {
  getColumnMetadata, getLatestSnapshot, getSnapshotStatus,
  getSnapshotRefreshState, triggerSnapshotRefresh,
} from '@/services/screener-service';
import {
  ChipValues, ColumnMetadata, Market,
  ScreenerPreset, ScreenerSnapshotResponse, ScreenerStatusResponse, SnapshotRow,
} from '@/types/screener';
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState } from './empty-state';
import { FilterChipBar } from './filter-chip-bar';
import { PresetBar } from './preset-bar';
import { SnapshotTable } from './snapshot-table';
import { StatusBar } from './status-bar';

const PAGE_SIZE = 20;

export function ScreenerTab() {
  const { t } = useTranslation();
  // CN is under development (akshare/Eastmoney fundamentals are geo-blocked),
  // so default to US and disable CN selection for now.
  const [market, setMarket] = useState<Market>('US');
  const [columns, setColumns] = useState<ColumnMetadata[]>([]);
  const [filterValues, setFilterValues] = useState<ChipValues>({});
  const [sortBy, setSortBy] = useState('market_cap');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(0);
  const [response, setResponse] = useState<ScreenerSnapshotResponse | null>(null);
  const [status, setStatus] = useState<ScreenerStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshProgress, setRefreshProgress] =
    useState<{ done: number; total: number } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const pollRef = useRef<number | null>(null);
  const { success, error } = useToastManager();

  useEffect(() => {
    let alive = true;
    getColumnMetadata()
      .then((r) => { if (alive) setColumns(r.columns); })
      .catch(console.error);
    getSnapshotStatus()
      .then((s) => { if (alive) setStatus(s); })
      .catch(console.error);
    return () => { alive = false; };
  }, []);

  // Cross-tab "filter to this sector" requests from the Sectors board. The
  // sector chip's filter_key is `sector_in`, and the backend sector strings
  // (e.g. "Technology") ARE the chip option values, so they match 1:1.
  useEffect(() => {
    const applySector = (sector: string) => {
      setMarket('US');
      setFilterValues((prev) => ({ ...prev, sector_in: [sector] }));
    };
    // Picks up a sector requested before this tab mounted.
    const queued = takePendingScreenerSectorFilter();
    if (queued) applySector(queued);
    return subscribeScreenerSectorFilter(applySector);
  }, []);

  // A new query (market/sort/filter) should start back at page 1.
  // Note: `page` is intentionally NOT a dep — that would defeat paging.
  useEffect(() => { setPage(0); }, [market, sortBy, sortDir, filterValues]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getLatestSnapshot({
      market, sort_by: sortBy, sort_dir: sortDir,
      limit: PAGE_SIZE, offset: page * PAGE_SIZE,
      filters: filterValues,
    })
      .then((r) => { if (alive) setResponse(r); })
      .catch(console.error)
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [market, sortBy, sortDir, filterValues, page, reloadKey]);

  const rows: SnapshotRow[] = response?.rows ?? [];
  const totalCount = response?.total_count ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const hasAnySnapshot = useMemo(
    () => (status?.row_count ?? 0) > 0, [status]);

  const handleLoadPreset = (p: ScreenerPreset) => {
    setMarket(p.market ?? 'US');
    setFilterValues(p.filters);
    setSortBy(p.sort_by);
    setSortDir(p.sort_dir);
  };

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(column);
      setSortDir('desc');
    }
  };

  // Stop polling if the tab unmounts mid-refresh.
  useEffect(() => () => {
    if (pollRef.current !== null) window.clearInterval(pollRef.current);
  }, []);

  const handleRefresh = async () => {
    // CN is disabled in the selector today; map anything non-CN to US.
    const refreshMarket: 'US' | 'CN' = market === 'CN' ? 'CN' : 'US';
    setRefreshing(true);
    setRefreshProgress(null);
    try {
      await triggerSnapshotRefresh(refreshMarket);
    } catch (e) {
      console.error(e);
      setRefreshing(false);
      error(t('screener.refresh.failed', 'Data update failed'));
      return;
    }
    // Poll progress until the server reports the build finished.
    pollRef.current = window.setInterval(async () => {
      let st;
      try {
        st = await getSnapshotRefreshState();
      } catch (e) {
        console.error(e);
        return;
      }
      setRefreshProgress({ done: st.done, total: st.total });
      if (st.running) return;
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
      setRefreshing(false);
      setRefreshProgress(null);
      if (st.error) {
        error(`${t('screener.refresh.failed', 'Data update failed')}: ${st.error}`);
        return;
      }
      success(
        t('screener.refresh.done', 'Data updated')
        + (st.inserted != null ? ` (${st.inserted})` : ''),
      );
      getSnapshotStatus().then(setStatus).catch(console.error);
      setReloadKey((k) => k + 1);
    }, 2000);
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 px-2 pt-2">
        <div className="text-sm font-semibold">{t('screener.tab.title', 'Screener')}</div>
        <Select value={market} onValueChange={(v) => setMarket(v as Market)}>
          <SelectTrigger className="h-8 w-32 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="US">{t('screener.market.us', 'US')}</SelectItem>
            <SelectItem value="CN" disabled>
              {t('screener.market.cn_dev', 'CN / A股 (开发中)')}
            </SelectItem>
          </SelectContent>
        </Select>
        {loading && <span className="text-xs text-muted-foreground">…</span>}
        <Button
          variant="outline"
          size="sm"
          className="ml-auto h-8 gap-1 text-xs"
          onClick={handleRefresh}
          disabled={refreshing}
          title={t('screener.refresh.tooltip', 'Fetch the latest market data')}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
          {refreshing
            ? (refreshProgress && refreshProgress.total > 0
                ? `${t('screener.refresh.running', 'Updating')} ${refreshProgress.done}/${refreshProgress.total}`
                : t('screener.refresh.starting', 'Starting…'))
            : t('screener.refresh.button', 'Update data')}
        </Button>
      </div>

      <PresetBar
        market={market}
        filters={filterValues}
        sortBy={sortBy}
        sortDir={sortDir}
        onLoad={handleLoadPreset}
      />

      {columns.length > 0 && (
        <FilterChipBar
          columns={columns}
          values={filterValues}
          market={market}
          onChange={setFilterValues}
        />
      )}

      <StatusBar status={status} matchCount={totalCount} />

      <div className="flex-1 overflow-auto px-2 pb-2">
        {!hasAnySnapshot
          ? <EmptyState />
          : <SnapshotTable rows={rows} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
        }
      </div>

      {hasAnySnapshot && totalCount > 0 && (
        <div className="flex items-center justify-center gap-2 border-t px-2 py-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={() => setPage((p) => p - 1)}
            disabled={page === 0}
            aria-label={t('screener.page.prev', 'Previous page')}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </Button>
          <span className="text-xs text-muted-foreground tabular-nums">
            {t('screener.page.label', 'Page {{page}} / {{pages}} · {{total}} total', {
              page: page + 1, pages: totalPages, total: totalCount,
            })}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={() => setPage((p) => p + 1)}
            disabled={page >= totalPages - 1}
            aria-label={t('screener.page.next', 'Next page')}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </div>
  );
}
