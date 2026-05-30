// Dedicated Watchlist tab — live per-ticker market data for a saved list.
//
// Header: pick which of the user's watchlists to view + a Refresh button +
// the selected list's ticker count. Body: a Screener-style table of live
// quotes (price / change% / volume / day range) fetched on demand from
// GET /watchlists/{id}/quotes. The fetch is slow (yfinance batch), so we
// show a spinner while loading.

import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useRequestAnalyze } from '@/hooks/use-request-analyze';
import { useToastManager } from '@/hooks/use-toast-manager';
import { cn } from '@/lib/utils';
import { watchlistService } from '@/services/watchlist-service';
import { LiveQuoteRow, UserWatchlist } from '@/types/watchlist';
import { Loader2, RefreshCw, Sparkles, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

function fmtPrice(v: number | null): string {
  if (v === null || !isFinite(v)) return '—';
  return v.toFixed(2);
}

function fmtPct(v: number | null): string {
  if (v === null || !isFinite(v)) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
}

function fmtVol(v: number | null): string {
  if (v === null || !isFinite(v)) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(2)}K`;
  return `${v}`;
}

function fmtRange(low: number | null, high: number | null): string {
  if (low === null || high === null || !isFinite(low) || !isFinite(high)) return '—';
  return `${low.toFixed(2)}–${high.toFixed(2)}`;
}

export function WatchlistTab() {
  const { t } = useTranslation();
  const { error } = useToastManager();
  const requestAnalyze = useRequestAnalyze();

  const [lists, setLists] = useState<UserWatchlist[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [rows, setRows] = useState<LiveQuoteRow[]>([]);
  const [loadingLists, setLoadingLists] = useState(false);
  const [loadingQuotes, setLoadingQuotes] = useState(false);

  const selected = lists.find((w) => w.id === selectedId) ?? null;

  // Load the user's watchlists once on mount; default to the first.
  useEffect(() => {
    let alive = true;
    setLoadingLists(true);
    watchlistService
      .list()
      .then((wls) => {
        if (!alive) return;
        setLists(wls);
        if (wls.length > 0) setSelectedId((cur) => cur ?? wls[0].id);
      })
      .catch((e) => {
        console.error('listWatchlists failed', e);
        if (alive) error(t('watchlist.loadListsFailed', 'Failed to load watchlists'));
      })
      .finally(() => {
        if (alive) setLoadingLists(false);
      });
    return () => {
      alive = false;
    };
  }, [error, t]);

  // Fetch live quotes whenever the selected list changes.
  useEffect(() => {
    if (selectedId === null) {
      setRows([]);
      return;
    }
    let alive = true;
    setLoadingQuotes(true);
    setRows([]);
    watchlistService
      .getWatchlistQuotes(selectedId)
      .then((q) => {
        if (alive) setRows(q);
      })
      .catch((e) => {
        console.error('getWatchlistQuotes failed', e);
        if (alive) error(t('watchlist.quotesFailed', 'Failed to load live quotes'));
      })
      .finally(() => {
        if (alive) setLoadingQuotes(false);
      });
    return () => {
      alive = false;
    };
  }, [selectedId, error, t]);

  async function handleRefresh() {
    if (selectedId === null) return;
    setLoadingQuotes(true);
    try {
      const q = await watchlistService.getWatchlistQuotes(selectedId);
      setRows(q);
    } catch (e) {
      console.error('getWatchlistQuotes failed', e);
      error(t('watchlist.quotesFailed', 'Failed to load live quotes'));
    } finally {
      setLoadingQuotes(false);
    }
  }

  async function handleRemove(ticker: string) {
    if (selectedId === null) return;
    try {
      const updated = await watchlistService.removeTicker(selectedId, ticker);
      setLists((prev) => prev.map((w) => (w.id === selectedId ? updated : w)));
      // Drop the row immediately; the count comes from the updated list.
      setRows((prev) => prev.filter((r) => r.ticker !== ticker));
    } catch (e) {
      console.error('removeTicker failed', e);
      error(t('watchlist.removeFailed', 'Failed to remove {{ticker}}', { ticker }));
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-2 pt-2">
        <div className="text-sm font-semibold">{t('watchlist.tab.title', 'Watchlist')}</div>
        <Select
          value={selectedId !== null ? String(selectedId) : undefined}
          onValueChange={(v) => setSelectedId(Number(v))}
          disabled={loadingLists || lists.length === 0}
        >
          <SelectTrigger className="h-8 w-48 text-xs">
            <SelectValue
              placeholder={
                loadingLists
                  ? t('common.loading', 'Loading...')
                  : t('watchlist.pickList', 'Pick a watchlist')
              }
            />
          </SelectTrigger>
          <SelectContent>
            {lists.map((wl) => (
              <SelectItem key={wl.id} value={String(wl.id)} className="text-xs">
                {wl.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selected && (
          <Badge variant="outline" className="h-5 text-[10px]">
            {t('watchlist.tickerCount', '{{count}} tickers', { count: selected.tickers.length })}
          </Badge>
        )}
        <Button
          variant="outline"
          size="sm"
          className="ml-auto h-8 gap-1 text-xs"
          onClick={handleRefresh}
          disabled={loadingQuotes || selectedId === null}
          title={t('watchlist.refresh.tooltip', 'Re-fetch live quotes')}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loadingQuotes && 'animate-spin')} />
          {t('watchlist.refresh.button', 'Refresh')}
        </Button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-auto px-2 py-2">
        {loadingQuotes ? (
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-12">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('watchlist.loadingQuotes', '加载实时数据…')}
          </div>
        ) : selected && selected.tickers.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-12">
            {t('watchlist.empty', '此清单暂无股票，去 Screener 或侧边栏添加')}
          </div>
        ) : (
          <div className="border rounded-md overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  <TableHead className="text-left whitespace-nowrap">
                    {t('watchlist.col.ticker', '代码')}
                  </TableHead>
                  <TableHead className="text-right whitespace-nowrap">
                    {t('watchlist.col.price', '价格')}
                  </TableHead>
                  <TableHead className="text-right whitespace-nowrap">
                    {t('watchlist.col.change', '涨跌%')}
                  </TableHead>
                  <TableHead className="text-right whitespace-nowrap">
                    {t('watchlist.col.volume', '成交量')}
                  </TableHead>
                  <TableHead className="text-right whitespace-nowrap">
                    {t('watchlist.col.range', '日内区间')}
                  </TableHead>
                  <TableHead className="text-center whitespace-nowrap">
                    {t('watchlist.col.actions', '操作')}
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground py-6">
                      {t('watchlist.noQuotes', 'No live data yet.')}
                    </TableCell>
                  </TableRow>
                )}
                {rows.map((r) => {
                  const chg = r.change_pct;
                  return (
                    <TableRow key={r.ticker}>
                      <TableCell className="font-mono font-semibold">{r.ticker}</TableCell>
                      <TableCell className="text-right">{fmtPrice(r.price)}</TableCell>
                      <TableCell
                        className={cn(
                          'text-right',
                          chg !== null && chg > 0 && 'text-green-500',
                          chg !== null && chg < 0 && 'text-red-500',
                        )}
                      >
                        {fmtPct(chg)}
                      </TableCell>
                      <TableCell className="text-right">{fmtVol(r.volume)}</TableCell>
                      <TableCell className="text-right">{fmtRange(r.day_low, r.day_high)}</TableCell>
                      <TableCell className="text-center">
                        <div className="flex items-center justify-center gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 px-2 text-primary"
                            title={t('watchlist.analyze.tooltip', 'Analyze this stock')}
                            onClick={() => requestAnalyze(r.ticker, 'us')}
                          >
                            <Sparkles className="w-3 h-3 mr-1" />
                            {t('watchlist.analyze.button', '分析')}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-6 w-6 p-0 text-red-500 hover-bg"
                            title={t('watchlist.remove.tooltip', 'Remove from list')}
                            onClick={() => handleRemove(r.ticker)}
                          >
                            <X className="w-3 h-3" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
