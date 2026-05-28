import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { useTabsContext } from '@/contexts/tabs-context';
import { cn } from '@/lib/utils';
import { SnapshotRow } from '@/types/screener';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface SnapshotTableProps {
  rows: SnapshotRow[];
  sortBy: string;
  sortDir: 'asc' | 'desc';
  onSort: (column: string) => void;
}

function fmtNum(v: string | null, digits = 2): string {
  if (v === null) return '—';
  const n = Number(v);
  if (!isFinite(n)) return '—';
  return n.toFixed(digits);
}

function fmtPct(v: string | null): string {
  if (v === null) return '—';
  const n = Number(v) * 100;
  if (!isFinite(n)) return '—';
  return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function fmtMcap(v: string | null): string {
  if (v === null) return '—';
  const n = Number(v);
  if (n >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (n >= 1e9)  return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6)  return `${(n / 1e6).toFixed(2)}M`;
  return `${n.toFixed(0)}`;
}

function fmtVol(v: number | null): string {
  if (v === null) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return `${v}`;
}

const RATING_COLOR: Record<string, string> = {
  strong_buy:  'bg-green-600 text-white',
  buy:         'bg-green-500 text-white',
  neutral:     'bg-gray-400 text-white',
  sell:        'bg-orange-500 text-white',
  strong_sell: 'bg-red-600 text-white',
};

export function SnapshotTable({ rows, sortBy, sortDir, onSort }: SnapshotTableProps) {
  const { openTab } = useTabsContext();
  const { t } = useTranslation();

  const headerCell = (column: string, label: string, align: 'left' | 'right' = 'right') => {
    const isActive = sortBy === column;
    return (
      <TableHead
        className={cn('cursor-pointer select-none whitespace-nowrap',
                      align === 'right' ? 'text-right' : 'text-left',
                      isActive && 'text-primary')}
        onClick={() => onSort(column)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {isActive && (sortDir === 'desc'
            ? <ChevronDown className="w-3 h-3" />
            : <ChevronUp className="w-3 h-3" />)}
        </span>
      </TableHead>
    );
  };

  return (
    <div className="border rounded-md overflow-x-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow>
            {headerCell('ticker', t('screener.col.ticker', 'Ticker'), 'left')}
            <TableHead className="text-left">{t('screener.col.market', 'Mkt')}</TableHead>
            {headerCell('price', t('screener.col.price', 'Price'))}
            {headerCell('change_pct', t('screener.col.chg', 'Chg %'))}
            {headerCell('volume', t('screener.col.vol', 'Vol'))}
            {headerCell('market_cap', t('screener.col.mcap', 'Mkt cap'))}
            {headerCell('pe_ttm', t('screener.col.pe', 'P/E'))}
            {headerCell('eps_growth_yoy', t('screener.col.eps_g', 'EPS gro'))}
            {headerCell('dividend_yield_pct', t('screener.col.div', 'Div %'))}
            <TableHead className="text-left">{t('screener.col.sector', 'Sector')}</TableHead>
            <TableHead className="text-left">{t('screener.col.rating', 'Rating')}</TableHead>
            {headerCell('perf_1m', t('screener.col.perf_1m', '1M'))}
            {headerCell('perf_ytd', t('screener.col.perf_ytd', 'YTD'))}
            {headerCell('perf_1y', t('screener.col.perf_1y', '1Y'))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={14} className="text-center text-muted-foreground py-6">
                {t('screener.table.no_results', 'No tickers match the current filters.')}
              </TableCell>
            </TableRow>
          )}
          {rows.map((r) => {
            const chgN = r.change_pct === null ? 0 : Number(r.change_pct);
            return (
              <TableRow
                key={r.ticker}
                className="cursor-pointer"
                onClick={() => openTab({
                  type: 'analyze',
                  title: r.ticker,
                  content: null,
                  metadata: { ticker: r.ticker },
                })}
              >
                <TableCell className="font-mono font-semibold">{r.ticker}</TableCell>
                <TableCell>
                  <Badge variant="outline" className="h-5 text-[10px]">{r.market}</Badge>
                </TableCell>
                <TableCell className="text-right">{fmtNum(r.price, 2)}</TableCell>
                <TableCell className={cn('text-right',
                  chgN > 0 && 'text-green-500',
                  chgN < 0 && 'text-red-500')}>{fmtPct(r.change_pct)}</TableCell>
                <TableCell className="text-right">{fmtVol(r.volume)}</TableCell>
                <TableCell className="text-right">{fmtMcap(r.market_cap)}</TableCell>
                <TableCell className="text-right">{fmtNum(r.pe_ttm, 1)}</TableCell>
                <TableCell className="text-right">{fmtPct(r.eps_growth_yoy)}</TableCell>
                <TableCell className="text-right">{fmtPct(r.dividend_yield_pct)}</TableCell>
                <TableCell className="text-left truncate max-w-[120px]">{r.sector ?? '—'}</TableCell>
                <TableCell className="text-left">
                  {r.analyst_rating
                    ? <Badge className={cn('h-5 text-[10px]', RATING_COLOR[r.analyst_rating])}>
                        {r.analyst_rating.replace('_', ' ')}
                      </Badge>
                    : '—'}
                </TableCell>
                <TableCell className={cn('text-right',
                  Number(r.perf_1m) > 0 && 'text-green-500',
                  Number(r.perf_1m) < 0 && 'text-red-500')}>{fmtPct(r.perf_1m)}</TableCell>
                <TableCell className={cn('text-right',
                  Number(r.perf_ytd) > 0 && 'text-green-500',
                  Number(r.perf_ytd) < 0 && 'text-red-500')}>{fmtPct(r.perf_ytd)}</TableCell>
                <TableCell className={cn('text-right',
                  Number(r.perf_1y) > 0 && 'text-green-500',
                  Number(r.perf_1y) < 0 && 'text-red-500')}>{fmtPct(r.perf_1y)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
