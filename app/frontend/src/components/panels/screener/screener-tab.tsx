import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import {
  getColumnMetadata, getLatestSnapshot, getSnapshotStatus,
} from '@/services/screener-service';
import {
  ChipValues, ColumnMetadata, Market,
  ScreenerSnapshotResponse, ScreenerStatusResponse, SnapshotRow,
} from '@/types/screener';
import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { EmptyState } from './empty-state';
import { FilterChipBar } from './filter-chip-bar';
import { SnapshotTable } from './snapshot-table';
import { StatusBar } from './status-bar';

export function ScreenerTab() {
  const { t } = useTranslation();
  const [market, setMarket] = useState<Market>('ALL');
  const [columns, setColumns] = useState<ColumnMetadata[]>([]);
  const [filterValues, setFilterValues] = useState<ChipValues>({});
  const [sortBy, setSortBy] = useState('market_cap');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [response, setResponse] = useState<ScreenerSnapshotResponse | null>(null);
  const [status, setStatus] = useState<ScreenerStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);

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

  useEffect(() => {
    let alive = true;
    setLoading(true);
    getLatestSnapshot({
      market, sort_by: sortBy, sort_dir: sortDir, limit: 200,
      filters: filterValues,
    })
      .then((r) => { if (alive) setResponse(r); })
      .catch(console.error)
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [market, sortBy, sortDir, filterValues]);

  const rows: SnapshotRow[] = response?.rows ?? [];
  const totalCount = response?.total_count ?? 0;
  const hasAnySnapshot = useMemo(
    () => (status?.row_count ?? 0) > 0, [status]);

  const handleSort = (column: string) => {
    if (sortBy === column) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(column);
      setSortDir('desc');
    }
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
            <SelectItem value="ALL">{t('screener.market.all', 'US + CN')}</SelectItem>
            <SelectItem value="US">{t('screener.market.us', 'US')}</SelectItem>
            <SelectItem value="CN">{t('screener.market.cn', 'CN (A股)')}</SelectItem>
          </SelectContent>
        </Select>
        {loading && <span className="text-xs text-muted-foreground">…</span>}
      </div>

      {columns.length > 0 && (
        <FilterChipBar
          columns={columns}
          values={filterValues}
          market={market}
          onChange={setFilterValues}
        />
      )}

      <StatusBar status={status} matchCount={rows.length} totalCount={totalCount} />

      <div className="flex-1 overflow-auto px-2 pb-2">
        {!hasAnySnapshot
          ? <EmptyState />
          : <SnapshotTable rows={rows} sortBy={sortBy} sortDir={sortDir} onSort={handleSort} />
        }
      </div>
    </div>
  );
}
