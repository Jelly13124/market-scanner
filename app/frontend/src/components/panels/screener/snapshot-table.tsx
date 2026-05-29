import React, { useState } from 'react';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription,
} from '@/components/ui/dialog';
import { useRequestAnalyze } from '@/hooks/use-request-analyze';
import { useToastManager } from '@/hooks/use-toast-manager';
import { cn } from '@/lib/utils';
import { SnapshotRow } from '@/types/screener';
import { UserWatchlist } from '@/types/watchlist';
import { watchlistService } from '@/services/watchlist-service';
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react';
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

type ColKey =
  | 'ticker' | 'market' | 'price' | 'change_pct' | 'volume' | 'market_cap'
  | 'pe_ttm' | 'eps_growth_yoy' | 'dividend_yield_pct' | 'sector'
  | 'analyst_rating' | 'perf_1m' | 'perf_ytd' | 'perf_1y' | 'analyze';

type GroupKey = 'overview' | 'valuation' | 'performance';

const GROUPS: Record<GroupKey, ColKey[]> = {
  overview:    ['ticker', 'market', 'price', 'change_pct', 'volume', 'market_cap', 'sector', 'analyst_rating', 'analyze'],
  valuation:   ['ticker', 'price', 'market_cap', 'pe_ttm', 'eps_growth_yoy', 'dividend_yield_pct', 'sector', 'analyst_rating', 'analyze'],
  performance: ['ticker', 'price', 'change_pct', 'perf_1m', 'perf_ytd', 'perf_1y', 'sector', 'analyst_rating', 'analyze'],
};

interface ColDescriptor {
  key: ColKey;
  sortKey: string | null;
  align: 'left' | 'right' | 'center';
  header: string;
  cell: (r: SnapshotRow, requestAnalyze: (ticker: string, market: 'us' | 'cn') => void, t: (k: string, d: string) => string) => React.ReactNode;
}

const COL_DESCRIPTORS: ColDescriptor[] = [
  {
    key: 'ticker',
    sortKey: 'ticker',
    align: 'left',
    header: 'screener.col.ticker',
    cell: (r) => (
      <TableCell className="font-mono font-semibold">{r.ticker}</TableCell>
    ),
  },
  {
    key: 'market',
    sortKey: null,
    align: 'left',
    header: 'screener.col.market',
    cell: (r) => (
      <TableCell>
        <Badge variant="outline" className="h-5 text-[10px]">{r.market}</Badge>
      </TableCell>
    ),
  },
  {
    key: 'price',
    sortKey: 'price',
    align: 'right',
    header: 'screener.col.price',
    cell: (r) => (
      <TableCell className="text-right">{fmtNum(r.price, 2)}</TableCell>
    ),
  },
  {
    key: 'change_pct',
    sortKey: 'change_pct',
    align: 'right',
    header: 'screener.col.chg',
    cell: (r) => {
      const chgN = r.change_pct === null ? 0 : Number(r.change_pct);
      return (
        <TableCell className={cn('text-right',
          chgN > 0 && 'text-green-500',
          chgN < 0 && 'text-red-500')}>{fmtPct(r.change_pct)}</TableCell>
      );
    },
  },
  {
    key: 'volume',
    sortKey: 'volume',
    align: 'right',
    header: 'screener.col.vol',
    cell: (r) => (
      <TableCell className="text-right">{fmtVol(r.volume)}</TableCell>
    ),
  },
  {
    key: 'market_cap',
    sortKey: 'market_cap',
    align: 'right',
    header: 'screener.col.mcap',
    cell: (r) => (
      <TableCell className="text-right">{fmtMcap(r.market_cap)}</TableCell>
    ),
  },
  {
    key: 'pe_ttm',
    sortKey: 'pe_ttm',
    align: 'right',
    header: 'screener.col.pe',
    cell: (r) => (
      <TableCell className="text-right">{fmtNum(r.pe_ttm, 1)}</TableCell>
    ),
  },
  {
    key: 'eps_growth_yoy',
    sortKey: 'eps_growth_yoy',
    align: 'right',
    header: 'screener.col.eps_g',
    cell: (r) => (
      <TableCell className="text-right">{fmtPct(r.eps_growth_yoy)}</TableCell>
    ),
  },
  {
    key: 'dividend_yield_pct',
    sortKey: 'dividend_yield_pct',
    align: 'right',
    header: 'screener.col.div',
    cell: (r) => (
      <TableCell className="text-right">{fmtPct(r.dividend_yield_pct)}</TableCell>
    ),
  },
  {
    key: 'sector',
    sortKey: null,
    align: 'left',
    header: 'screener.col.sector',
    cell: (r) => (
      <TableCell className="text-left truncate max-w-[120px]">{r.sector ?? '—'}</TableCell>
    ),
  },
  {
    key: 'analyst_rating',
    sortKey: null,
    align: 'left',
    header: 'screener.col.rating',
    cell: (r) => (
      <TableCell className="text-left">
        {r.analyst_rating
          ? <Badge className={cn('h-5 text-[10px]', RATING_COLOR[r.analyst_rating])}>
              {r.analyst_rating.replace('_', ' ')}
            </Badge>
          : '—'}
      </TableCell>
    ),
  },
  {
    key: 'perf_1m',
    sortKey: 'perf_1m',
    align: 'right',
    header: 'screener.col.perf_1m',
    cell: (r) => (
      <TableCell className={cn('text-right',
        Number(r.perf_1m) > 0 && 'text-green-500',
        Number(r.perf_1m) < 0 && 'text-red-500')}>{fmtPct(r.perf_1m)}</TableCell>
    ),
  },
  {
    key: 'perf_ytd',
    sortKey: 'perf_ytd',
    align: 'right',
    header: 'screener.col.perf_ytd',
    cell: (r) => (
      <TableCell className={cn('text-right',
        Number(r.perf_ytd) > 0 && 'text-green-500',
        Number(r.perf_ytd) < 0 && 'text-red-500')}>{fmtPct(r.perf_ytd)}</TableCell>
    ),
  },
  {
    key: 'perf_1y',
    sortKey: 'perf_1y',
    align: 'right',
    header: 'screener.col.perf_1y',
    cell: (r) => (
      <TableCell className={cn('text-right',
        Number(r.perf_1y) > 0 && 'text-green-500',
        Number(r.perf_1y) < 0 && 'text-red-500')}>{fmtPct(r.perf_1y)}</TableCell>
    ),
  },
  {
    key: 'analyze',
    sortKey: null,
    align: 'center',
    header: 'screener.col.analyze',
    cell: (r, requestAnalyze, t) => (
      <TableCell className="text-center">
        <Button
          size="sm"
          variant="ghost"
          className="h-6 px-2 text-primary"
          title={t('screener.analyze.tooltip', 'Analyze this stock')}
          onClick={() =>
            requestAnalyze(r.ticker, r.market === 'CN' ? 'cn' : 'us')
          }
        >
          <Sparkles className="w-3 h-3 mr-1" />
          {t('screener.analyze.button', 'Analyze')}
        </Button>
      </TableCell>
    ),
  },
];

const COL_MAP = Object.fromEntries(COL_DESCRIPTORS.map((d) => [d.key, d])) as Record<ColKey, ColDescriptor>;

const HEADER_DEFAULTS: Record<string, string> = {
  'screener.col.ticker':   'Ticker',
  'screener.col.market':   'Mkt',
  'screener.col.price':    'Price',
  'screener.col.chg':      'Chg %',
  'screener.col.vol':      'Vol',
  'screener.col.mcap':     'Mkt cap',
  'screener.col.pe':       'P/E',
  'screener.col.eps_g':    'EPS gro',
  'screener.col.div':      'Div %',
  'screener.col.sector':   'Sector',
  'screener.col.rating':   'Rating',
  'screener.col.perf_1m':  '1M',
  'screener.col.perf_ytd': 'YTD',
  'screener.col.perf_1y':  '1Y',
  'screener.col.analyze':  'Analyze',
};

export function SnapshotTable({ rows, sortBy, sortDir, onSort }: SnapshotTableProps) {
  const requestAnalyze = useRequestAnalyze();
  const { t } = useTranslation();
  const { success, error } = useToastManager();
  const [group, setGroup] = useState<GroupKey>('overview');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [dialogOpen, setDialogOpen] = useState(false);
  const [watchlists, setWatchlists] = useState<UserWatchlist[]>([]);
  const [loadingWl, setLoadingWl] = useState(false);

  const activeCols = GROUPS[group].map((k) => COL_MAP[k]);

  const allSelected = rows.length > 0 && rows.every((r) => selected.has(r.ticker));

  function toggleAll(checked: boolean) {
    if (checked) {
      setSelected(new Set(rows.map((r) => r.ticker)));
    } else {
      setSelected(new Set());
    }
  }

  function toggleOne(ticker: string, checked: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(ticker);
      else next.delete(ticker);
      return next;
    });
  }

  async function openDialog() {
    setDialogOpen(true);
    setLoadingWl(true);
    try {
      const wls = await watchlistService.list();
      setWatchlists(wls);
    } catch {
      setWatchlists([]);
    } finally {
      setLoadingWl(false);
    }
  }

  async function handlePickWatchlist(wl: UserWatchlist) {
    const tickers = Array.from(selected).filter((tk) => !wl.tickers.includes(tk));
    const results = await Promise.allSettled(
      tickers.map((tk) => watchlistService.addTicker(wl.id, tk)),
    );
    const added = results.filter((r) => r.status === 'fulfilled').length;
    const failed = results.filter((r) => r.status === 'rejected').length;
    if (added > 0) {
      success(t('screener.bulk.added', 'Added {{n}} to {{name}}', { n: added, name: wl.name }));
    }
    if (failed > 0) {
      error(t('screener.bulk.addFailed', '{{n}} ticker(s) failed to add', { n: failed }));
    }
    setSelected(new Set());
    setDialogOpen(false);
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center">
        <Tabs value={group} onValueChange={(v) => setGroup(v as GroupKey)}>
          <TabsList className="h-8">
            <TabsTrigger value="overview" className="text-xs">
              {t('screener.group.overview', 'Overview')}
            </TabsTrigger>
            <TabsTrigger value="valuation" className="text-xs">
              {t('screener.group.valuation', 'Valuation')}
            </TabsTrigger>
            <TabsTrigger value="performance" className="text-xs">
              {t('screener.group.performance', 'Performance')}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {selected.size > 0 && (
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto h-8 text-xs"
            onClick={openDialog}
          >
            {t('screener.bulk.add', 'Add {{count}} to watchlist', { count: selected.size })}
          </Button>
        )}
      </div>
      <div className="border rounded-md overflow-x-auto">
        <Table className="text-xs">
          <TableHeader>
            <TableRow>
              <TableHead className="w-8">
                <Checkbox
                  checked={allSelected}
                  onCheckedChange={(v) => toggleAll(!!v)}
                />
              </TableHead>
              {activeCols.map((col) => {
                const label = t(col.header, HEADER_DEFAULTS[col.header] ?? col.key);
                if (col.sortKey !== null) {
                  const isActive = sortBy === col.sortKey;
                  const alignClass = col.align === 'left' ? 'text-left' : 'text-right';
                  return (
                    <TableHead
                      key={col.key}
                      className={cn('cursor-pointer select-none whitespace-nowrap', alignClass, isActive && 'text-primary')}
                      onClick={() => onSort(col.sortKey!)}
                    >
                      <span className="inline-flex items-center gap-1">
                        {label}
                        {isActive && (sortDir === 'desc'
                          ? <ChevronDown className="w-3 h-3" />
                          : <ChevronUp className="w-3 h-3" />)}
                      </span>
                    </TableHead>
                  );
                }
                const alignClass = col.align === 'right' ? 'text-right'
                  : col.align === 'center' ? 'text-center'
                  : 'text-left';
                return (
                  <TableHead key={col.key} className={cn('whitespace-nowrap', alignClass)}>
                    {label}
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={activeCols.length + 1} className="text-center text-muted-foreground py-6">
                  {t('screener.table.no_results', 'No tickers match the current filters.')}
                </TableCell>
              </TableRow>
            )}
            {rows.map((r) => (
              <TableRow key={r.ticker}>
                <TableCell className="w-8" onClick={(e) => e.stopPropagation()}>
                  <Checkbox
                    checked={selected.has(r.ticker)}
                    onCheckedChange={(v) => toggleOne(r.ticker, !!v)}
                    onClick={(e) => e.stopPropagation()}
                  />
                </TableCell>
                {activeCols.map((col) => (
                  <React.Fragment key={col.key}>
                    {col.cell(r, requestAnalyze, t)}
                  </React.Fragment>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{t('screener.bulk.dialogTitle', 'Add to watchlist')}</DialogTitle>
            <DialogDescription>
              {t('screener.bulk.dialogDesc', 'Select a watchlist to add the {{count}} selected ticker(s).', { count: selected.size })}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-1 max-h-64 overflow-y-auto">
            {loadingWl && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t('screener.bulk.loading', 'Loading…')}
              </p>
            )}
            {!loadingWl && watchlists.length === 0 && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                {t('screener.bulk.noLists', 'No watchlists yet. Create one in the sidebar.')}
              </p>
            )}
            {!loadingWl && watchlists.map((wl) => (
              <button
                key={wl.id}
                className="w-full flex items-center justify-between px-3 py-2 rounded-md text-sm hover:bg-accent text-left"
                onClick={() => handlePickWatchlist(wl)}
              >
                <span>{wl.name}</span>
                <Badge variant="outline" className="h-5 text-[10px]">{wl.tickers.length}</Badge>
              </button>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
