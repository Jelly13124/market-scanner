// Dedicated Watchlist tab — full management + live per-ticker market data.
//
// Header/toolbar: pick which of the user's watchlists to view, + New / Rename /
// Delete the selected list, a search-to-add bar, the selected list's ticker
// count, and a Refresh button. Body: a Screener-style table of live quotes
// (price / change% / volume / day range) fetched on demand from
// GET /watchlists/{id}/quotes. The fetch is slow (yfinance batch), so we show a
// spinner while loading. This tab is the single source of truth for watchlist
// management — the old left-sidebar section was removed.

import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table';
import { BatchReportDialog } from '@/components/panels/analyze/batch-report-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useRequestAnalyze } from '@/hooks/use-request-analyze';
import { useToastManager } from '@/hooks/use-toast-manager';
import { cn } from '@/lib/utils';
import { tickerService, watchlistService } from '@/services/watchlist-service';
import {
  LiveQuoteRow,
  TickerSearchResult,
  UserWatchlist,
} from '@/types/watchlist';
import {
  ChevronLeft, ChevronRight, Loader2, Pencil, Plus, RefreshCw, Sparkles, Trash2, X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

const DEBOUNCE_MS = 300;
const PAGE_SIZE = 20;

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
  const { success, error } = useToastManager();
  const requestAnalyze = useRequestAnalyze();

  const [lists, setLists] = useState<UserWatchlist[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [rows, setRows] = useState<LiveQuoteRow[]>([]);
  const [page, setPage] = useState(0);
  const [loadingLists, setLoadingLists] = useState(false);
  const [loadingQuotes, setLoadingQuotes] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<UserWatchlist | null>(null);
  const [deleting, setDeleting] = useState<UserWatchlist | null>(null);

  // Multi-select for batch reports (mirrors the Screener's selection pattern).
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [batchOpen, setBatchOpen] = useState(false);

  const selected = lists.find((w) => w.id === selectedId) ?? null;

  // (Re)load the user's watchlists; default the selection to the first list
  // when nothing is selected yet. Stable so window-focus can re-pull it.
  const reloadLists = useCallback(async () => {
    setLoadingLists(true);
    try {
      const wls = await watchlistService.list();
      setLists(wls);
      if (wls.length > 0) setSelectedId((cur) => cur ?? wls[0].id);
    } catch (e) {
      console.error('listWatchlists failed', e);
      error(t('watchlist.loadListsFailed', 'Failed to load watchlists'));
    } finally {
      setLoadingLists(false);
    }
  }, [error, t]);

  const reloadQuotes = useCallback(async (id: number) => {
    setLoadingQuotes(true);
    try {
      const q = await watchlistService.getWatchlistQuotes(id);
      setRows(q);
    } catch (e) {
      console.error('getWatchlistQuotes failed', e);
      error(t('watchlist.quotesFailed', 'Failed to load live quotes'));
    } finally {
      setLoadingQuotes(false);
    }
  }, [error, t]);

  // Load the user's watchlists once on mount.
  useEffect(() => {
    reloadLists();
  }, [reloadLists]);

  // Fetch live quotes whenever the selected list changes.
  useEffect(() => {
    if (selectedId === null) {
      setRows([]);
      return;
    }
    setRows([]);
    reloadQuotes(selectedId);
  }, [selectedId, reloadQuotes]);

  // Refresh on window focus: tickers added elsewhere (e.g. the Screener) while
  // this persistent tab was mounted won't show until we re-pull. Lightweight —
  // refresh-on-focus only, no polling.
  useEffect(() => {
    const onFocus = () => {
      reloadLists();
      if (selectedId !== null) reloadQuotes(selectedId);
    };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [selectedId, reloadLists, reloadQuotes]);

  // Switching lists or a refresh (row count changes) should start back at page 1
  // — and guarantees we never sit on a now-out-of-range page. Also clear any
  // multi-select so a stale pick can't leak into a different list.
  useEffect(() => { setPage(0); setPicked(new Set()); }, [selectedId, rows.length]);

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  // Select-all spans every row (all pages), mirroring the Screener.
  const allPicked = rows.length > 0 && rows.every((r) => picked.has(r.ticker));

  function togglePickAll(checked: boolean) {
    setPicked(checked ? new Set(rows.map((r) => r.ticker)) : new Set());
  }

  function togglePickOne(ticker: string, checked: boolean) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (checked) next.add(ticker);
      else next.delete(ticker);
      return next;
    });
  }

  async function handleRefresh() {
    if (selectedId === null) return;
    await Promise.all([reloadLists(), reloadQuotes(selectedId)]);
  }

  async function handleRemove(ticker: string) {
    if (selectedId === null) return;
    try {
      const updated = await watchlistService.removeTicker(selectedId, ticker);
      setLists((prev) => prev.map((w) => (w.id === selectedId ? updated : w)));
      // Drop the row immediately; the count comes from the updated list. If that
      // empties the current page, clamp back to the last page that still has rows.
      setRows((prev) => {
        const next = prev.filter((r) => r.ticker !== ticker);
        const lastPage = Math.max(0, Math.ceil(next.length / PAGE_SIZE) - 1);
        setPage((p) => Math.min(p, lastPage));
        return next;
      });
      setPicked((prev) => {
        if (!prev.has(ticker)) return prev;
        const next = new Set(prev);
        next.delete(ticker);
        return next;
      });
    } catch (e) {
      console.error('removeTicker failed', e);
      error(t('watchlist.removeFailed', 'Failed to remove {{ticker}}', { ticker }));
    }
  }

  // Add a ticker to the currently-selected list, then re-fetch quotes so the
  // new row shows up with live data.
  async function handleAddTicker(ticker: string) {
    if (selectedId === null) return;
    const updated = await watchlistService.addTicker(selectedId, ticker);
    setLists((prev) => prev.map((w) => (w.id === selectedId ? updated : w)));
    await reloadQuotes(selectedId);
  }

  async function handleCreate(name: string) {
    setCreating(true);
    try {
      const created = await watchlistService.create({ name });
      setLists((prev) => [...prev, created]);
      setSelectedId(created.id);
      success(t('watchlist.created', 'Created "{{name}}"', { name: created.name }));
      setCreateOpen(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      error(t('watchlist.createFailed', 'Failed to create: {{msg}}', { msg }));
    } finally {
      setCreating(false);
    }
  }

  async function handleRename(id: number, name: string) {
    try {
      const updated = await watchlistService.update(id, { name });
      setLists((prev) => prev.map((w) => (w.id === id ? updated : w)));
      success(t('watchlist.renamed', 'Renamed to "{{name}}"', { name: updated.name }));
      setRenaming(null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      error(t('watchlist.renameFailed', 'Rename failed: {{msg}}', { msg }));
    }
  }

  async function handleDelete(target: UserWatchlist) {
    try {
      await watchlistService.delete(target.id);
      const remaining = lists.filter((w) => w.id !== target.id);
      setLists(remaining);
      if (selectedId === target.id) {
        setSelectedId(remaining.length > 0 ? remaining[0].id : null);
      }
      success(t('watchlist.deleted', 'Deleted "{{name}}"', { name: target.name }));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      error(t('watchlist.deleteFailed', 'Delete failed: {{msg}}', { msg }));
    } finally {
      setDeleting(null);
    }
  }

  const noLists = !loadingLists && lists.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Header / toolbar */}
      <div className="flex flex-wrap items-center gap-2 px-2 pt-2">
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

        <Button
          variant="outline"
          size="sm"
          className="h-8 gap-1 text-xs"
          onClick={() => setCreateOpen(true)}
          title={t('watchlist.newTooltip', 'Create a new watchlist')}
        >
          <Plus className="h-3.5 w-3.5" />
          {t('watchlist.new', 'New')}
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-primary hover-bg"
          onClick={() => selected && setRenaming(selected)}
          disabled={!selected}
          title={t('watchlist.renameTooltip', 'Rename this watchlist')}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-red-500 hover-bg"
          onClick={() => selected && setDeleting(selected)}
          disabled={!selected}
          title={t('watchlist.deleteTooltip', 'Delete this watchlist')}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>

        {selected && (
          <Badge variant="outline" className="h-5 text-[10px]">
            {t('watchlist.tickerCount', '{{count}} tickers', { count: selected.tickers.length })}
          </Badge>
        )}

        {picked.size > 0 && (
          <Button
            variant="default"
            size="sm"
            className="ml-auto h-8 text-xs"
            onClick={() => setBatchOpen(true)}
          >
            {t('analyze.batch.button', 'Batch report ({{count}})', { count: picked.size })}
          </Button>
        )}

        <Button
          variant="outline"
          size="sm"
          className={cn('h-8 gap-1 text-xs', picked.size === 0 && 'ml-auto')}
          onClick={handleRefresh}
          disabled={loadingQuotes || selectedId === null}
          title={t('watchlist.refresh.tooltip', 'Re-fetch live quotes')}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', loadingQuotes && 'animate-spin')} />
          {t('watchlist.refresh.button', 'Refresh')}
        </Button>
      </div>

      {/* Search-to-add bar (only meaningful when a list is selected) */}
      {selected && (
        <div className="px-2 pt-2">
          <AddTickerAutocomplete
            existingTickers={selected.tickers}
            onAdd={handleAddTicker}
            onError={(msg) => error(msg)}
          />
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-auto px-2 py-2">
        {noLists ? (
          <div className="flex flex-col items-center justify-center gap-3 py-12 text-center">
            <div className="text-sm text-muted-foreground">
              {t('watchlist.noLists', 'No watchlists yet — click + New to create one.')}
            </div>
            <Button size="sm" className="gap-1" onClick={() => setCreateOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              {t('watchlist.new', 'New')}
            </Button>
          </div>
        ) : loadingQuotes ? (
          <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground py-12">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('watchlist.loadingQuotes', '加载实时数据…')}
          </div>
        ) : selected && selected.tickers.length === 0 ? (
          <div className="text-center text-sm text-muted-foreground py-12">
            {t('watchlist.empty', '此清单暂无股票，用上面的搜索添加')}
          </div>
        ) : (
          <div className="border rounded-md overflow-x-auto">
            <Table className="text-xs">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8">
                    <Checkbox
                      checked={allPicked}
                      onCheckedChange={(v) => togglePickAll(!!v)}
                    />
                  </TableHead>
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
                    <TableCell colSpan={7} className="text-center text-muted-foreground py-6">
                      {t('watchlist.noQuotes', 'No live data yet.')}
                    </TableCell>
                  </TableRow>
                )}
                {pageRows.map((r) => {
                  const chg = r.change_pct;
                  return (
                    <TableRow key={r.ticker}>
                      <TableCell className="w-8">
                        <Checkbox
                          checked={picked.has(r.ticker)}
                          onCheckedChange={(v) => togglePickOne(r.ticker, !!v)}
                        />
                      </TableCell>
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
            {rows.length > PAGE_SIZE && (
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
                    page: page + 1, pages: totalPages, total: rows.length,
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
        )}
      </div>

      {/* Batch report dialog — runs a report per selected ticker */}
      <BatchReportDialog
        open={batchOpen}
        onOpenChange={setBatchOpen}
        tickers={Array.from(picked)}
        defaultMarket="us"
        onStarted={() => setPicked(new Set())}
      />

      {/* Create dialog */}
      <WatchlistCreateDialog
        isOpen={createOpen}
        isLoading={creating}
        onClose={() => setCreateOpen(false)}
        onCreate={handleCreate}
      />

      {/* Rename dialog */}
      {renaming && (
        <WatchlistRenameDialog
          watchlist={renaming}
          onClose={() => setRenaming(null)}
          onRename={handleRename}
        />
      )}

      {/* Delete confirm */}
      {deleting && (
        <Dialog open onOpenChange={(open) => !open && setDeleting(null)}>
          <DialogContent className="sm:max-w-[400px]">
            <DialogHeader>
              <DialogTitle>
                {t('watchlist.deleteConfirm', 'Delete watchlist "{{name}}"?', { name: deleting.name })}
              </DialogTitle>
              <DialogDescription>
                {t('watchlist.tickerCount', '{{count}} tickers', { count: deleting.tickers.length })}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>
                {t('common.cancel', 'Cancel')}
              </Button>
              <Button variant="destructive" onClick={() => handleDelete(deleting)}>
                {t('common.delete', 'Delete')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AddTickerAutocomplete — debounced search + result dropdown.
// Picking a result adds the ticker to the currently-selected list.
// ---------------------------------------------------------------------------

interface AddTickerAutocompleteProps {
  existingTickers: string[];
  onAdd: (ticker: string) => Promise<void>;
  onError: (msg: string) => void;
}

function AddTickerAutocomplete({
  existingTickers,
  onAdd,
  onError,
}: AddTickerAutocompleteProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<TickerSearchResult[]>([]);
  const [showDropdown, setShowDropdown] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { t } = useTranslation();

  // Close dropdown on outside click
  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setShowDropdown(false);
      }
    }
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setIsSearching(true);
      try {
        const r = await tickerService.search(query);
        // Filter out already-added tickers so user can't double-add.
        const filtered = r.filter((x) => !existingTickers.includes(x.ticker));
        setResults(filtered);
      } catch (e) {
        console.error('ticker search failed', e);
        setResults([]);
      } finally {
        setIsSearching(false);
      }
    }, DEBOUNCE_MS);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, existingTickers]);

  const handleSelect = async (ticker: string) => {
    try {
      await onAdd(ticker);
      setQuery('');
      setShowDropdown(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      onError(t('watchlist.addFailed', 'Add {{ticker}} failed: {{msg}}', { ticker, msg }));
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <Input
        type="text"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setShowDropdown(true);
        }}
        onFocus={() => setShowDropdown(true)}
        placeholder={t('watchlist.searchPlaceholder', 'Search a stock to add to this list…')}
        className="h-8 text-xs"
      />
      {showDropdown && (
        <div className="absolute left-0 right-0 top-full mt-1 z-10 max-h-48 overflow-y-auto rounded-md border border-border bg-popover shadow-md">
          {isSearching && (
            <div className="px-2 py-1 text-xs text-muted-foreground">
              {t('watchlist.searching', 'Searching…')}
            </div>
          )}
          {!isSearching && results.length === 0 && (
            <div className="px-2 py-1 text-xs text-muted-foreground">
              {t('watchlist.noMatches', 'No matches.')}
            </div>
          )}
          {!isSearching &&
            results.map((r) => (
              <button
                key={r.ticker}
                onClick={() => handleSelect(r.ticker)}
                className="w-full px-2 py-1 text-left text-xs font-mono hover:bg-accent"
              >
                {r.ticker}
                {r.name && (
                  <span className="ml-2 text-muted-foreground">{r.name}</span>
                )}
              </button>
            ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create dialog
// ---------------------------------------------------------------------------

interface WatchlistCreateDialogProps {
  isOpen: boolean;
  isLoading: boolean;
  onClose: () => void;
  onCreate: (name: string) => Promise<void>;
}

function WatchlistCreateDialog({
  isOpen,
  isLoading,
  onClose,
  onCreate,
}: WatchlistCreateDialogProps) {
  const [name, setName] = useState('');
  const { t } = useTranslation();

  useEffect(() => {
    if (isOpen) setName('');
  }, [isOpen]);

  const submit = () => {
    if (!name.trim()) return;
    onCreate(name.trim());
  };

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t('sidebar.newWatchlist', 'New watchlist')}</DialogTitle>
          <DialogDescription>
            {t('watchlist.createDescription', 'Give the list a name. You can add tickers next.')}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 py-2">
          <label htmlFor="wl-name" className="text-sm font-medium">
            {t('common.name', 'Name')}
          </label>
          <Input
            id="wl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && name.trim()) submit();
            }}
            placeholder={t('sidebarDialogs.watchlistNamePlaceholder', 'My Mega-caps')}
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button onClick={submit} disabled={isLoading || !name.trim()}>
            {isLoading ? t('common.loading', 'Creating...') : t('common.create', 'Create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Rename dialog
// ---------------------------------------------------------------------------

interface WatchlistRenameDialogProps {
  watchlist: UserWatchlist;
  onClose: () => void;
  onRename: (id: number, name: string) => Promise<void>;
}

function WatchlistRenameDialog({
  watchlist,
  onClose,
  onRename,
}: WatchlistRenameDialogProps) {
  const [name, setName] = useState(watchlist.name);
  const [isLoading, setIsLoading] = useState(false);
  const { t } = useTranslation();

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === watchlist.name) {
      onClose();
      return;
    }
    setIsLoading(true);
    try {
      await onRename(watchlist.id, trimmed);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t('common.rename', 'Rename')} "{watchlist.name}"</DialogTitle>
        </DialogHeader>
        <div className="grid gap-2 py-2">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submit();
            }}
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel', 'Cancel')}
          </Button>
          <Button onClick={submit} disabled={isLoading || !name.trim()}>
            {isLoading ? t('lab.specJson.saving', 'Saving...') : t('common.save', 'Save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
