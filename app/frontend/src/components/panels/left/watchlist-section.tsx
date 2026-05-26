// Left-sidebar section listing user-curated watchlists. (Phase 5B)
//
// Each watchlist is a collapsible row showing ticker badges with × to
// remove. "+ Add ticker" opens a debounced autocomplete that calls
// tickerService.search(). "+ New" creates an empty watchlist via dialog.

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { useToastManager } from '@/hooks/use-toast-manager';
import {
  tickerService,
  watchlistService,
} from '@/services/watchlist-service';
import { TickerSearchResult, UserWatchlist } from '@/types/watchlist';
import {
  ChevronDown,
  ChevronRight,
  Pencil,
  Plus,
  Star,
  Trash2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

const DEBOUNCE_MS = 300;

export function WatchlistSection() {
  const [lists, setLists] = useState<UserWatchlist[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [createOpen, setCreateOpen] = useState(false);
  const [renaming, setRenaming] = useState<UserWatchlist | null>(null);
  const [deleting, setDeleting] = useState<UserWatchlist | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const { success, error } = useToastManager();
  const { t } = useTranslation();

  const refresh = useCallback(async () => {
    try {
      const rows = await watchlistService.list();
      setLists(rows);
    } catch (e) {
      console.error('listWatchlists failed', e);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleRemoveTicker = async (id: number, ticker: string) => {
    try {
      const updated = await watchlistService.removeTicker(id, ticker);
      setLists((prev) => prev.map((w) => (w.id === id ? updated : w)));
    } catch (e) {
      console.error('removeTicker failed', e);
      error(`Failed to remove ${ticker}`);
    }
  };

  const handleTickerAdded = (id: number, updated: UserWatchlist) => {
    setLists((prev) => prev.map((w) => (w.id === id ? updated : w)));
  };

  return (
    <div className="flex flex-col flex-shrink-0 border-b">
      {/* Section header */}
      <div className="p-2 flex justify-between items-center mt-4">
        <span className="text-primary text-sm font-medium ml-4 flex items-center gap-1.5">
          <Star size={12} className="text-yellow-500" />
          {t('sidebar.watchlists')}
        </span>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCreateOpen(true)}
          className="h-6 w-6 text-primary hover-bg"
          title={t('sidebar.newWatchlist')}
        >
          <Plus size={14} />
        </Button>
      </div>

      {/* List rows */}
      <div className="px-2 pb-2 flex flex-col gap-1">
        {lists.length === 0 && (
          <div className="text-muted-foreground text-xs px-4 py-1">
            No watchlists yet.
          </div>
        )}
        {lists.map((wl) => {
          const expanded = expandedIds.has(wl.id);
          return (
            <div
              key={wl.id}
              className="flex flex-col rounded-md hover:bg-accent/50"
            >
              <div className="flex items-center px-2 py-1 gap-1 group">
                <button
                  onClick={() => toggleExpand(wl.id)}
                  className="flex-1 flex items-center gap-1 text-left text-sm text-primary"
                  title={expanded ? 'Collapse' : 'Expand'}
                >
                  {expanded ? (
                    <ChevronDown size={12} />
                  ) : (
                    <ChevronRight size={12} />
                  )}
                  <span className="truncate">{wl.name}</span>
                  <Badge variant="outline" className="ml-auto px-1.5 py-0 text-[10px]">
                    {wl.tickers.length}
                  </Badge>
                </button>
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 text-primary hover-bg"
                    onClick={() => setRenaming(wl)}
                    title={t('common.rename')}
                  >
                    <Pencil size={11} />
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-5 w-5 text-red-500 hover-bg"
                    onClick={() => setDeleting(wl)}
                    title={t('common.delete')}
                  >
                    <Trash2 size={11} />
                  </Button>
                </div>
              </div>

              {expanded && (
                <div className="px-3 pb-2 flex flex-col gap-2">
                  <div className="flex flex-wrap gap-1">
                    {wl.tickers.map((t) => (
                      <span
                        key={t}
                        className="group/badge inline-flex items-center gap-0.5 rounded border border-border bg-background px-1.5 py-0.5 text-[10px] font-mono"
                      >
                        {t}
                        <button
                          onClick={() => handleRemoveTicker(wl.id, t)}
                          className="opacity-50 hover:opacity-100 hover:text-red-500"
                          title={`Remove ${t}`}
                        >
                          <X size={10} />
                        </button>
                      </span>
                    ))}
                    {wl.tickers.length === 0 && (
                      <span className="text-muted-foreground text-[11px]">
                        Empty list.
                      </span>
                    )}
                  </div>
                  <AddTickerAutocomplete
                    watchlistId={wl.id}
                    existingTickers={wl.tickers}
                    onAdded={(u) => handleTickerAdded(wl.id, u)}
                    onError={error}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Create dialog */}
      <WatchlistCreateDialog
        isOpen={createOpen}
        isLoading={isLoading}
        onClose={() => setCreateOpen(false)}
        onCreate={async (name) => {
          setIsLoading(true);
          try {
            const created = await watchlistService.create({ name });
            success(`Created "${created.name}"`);
            await refresh();
            setCreateOpen(false);
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e);
            error(`Failed to create: ${msg}`);
          } finally {
            setIsLoading(false);
          }
        }}
      />

      {/* Rename dialog */}
      {renaming && (
        <WatchlistRenameDialog
          watchlist={renaming}
          onClose={() => setRenaming(null)}
          onRename={async (id, name) => {
            try {
              const updated = await watchlistService.update(id, { name });
              setLists((prev) => prev.map((w) => (w.id === id ? updated : w)));
              success(`Renamed to "${updated.name}"`);
              setRenaming(null);
            } catch (e: unknown) {
              const msg = e instanceof Error ? e.message : String(e);
              error(`Rename failed: ${msg}`);
            }
          }}
        />
      )}

      {/* Delete confirm */}
      {deleting && (
        <Dialog open onOpenChange={(open) => !open && setDeleting(null)}>
          <DialogContent className="sm:max-w-[400px]">
            <DialogHeader>
              <DialogTitle>{t('sidebar.deleteWatchlist', { name: deleting.name })}</DialogTitle>
              <DialogDescription>
                {t('sidebar.tickerCount', { count: deleting.tickers.length })}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleting(null)}>
                {t('common.cancel')}
              </Button>
              <Button
                variant="destructive"
                onClick={async () => {
                  const target = deleting;
                  try {
                    await watchlistService.delete(target.id);
                    setLists((prev) => prev.filter((w) => w.id !== target.id));
                    success(`Deleted "${target.name}"`);
                  } catch (e: unknown) {
                    const msg = e instanceof Error ? e.message : String(e);
                    error(`Delete failed: ${msg}`);
                  } finally {
                    setDeleting(null);
                  }
                }}
              >
                {t('common.delete')}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// AddTickerAutocomplete — debounced search + result dropdown
// ---------------------------------------------------------------------------

interface AddTickerAutocompleteProps {
  watchlistId: number;
  existingTickers: string[];
  onAdded: (updated: UserWatchlist) => void;
  onError: (msg: string) => void;
}

function AddTickerAutocomplete({
  watchlistId,
  existingTickers,
  onAdded,
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
      const updated = await watchlistService.addTicker(watchlistId, ticker);
      onAdded(updated);
      setQuery('');
      setShowDropdown(false);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      onError(`Add ${ticker} failed: ${msg}`);
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
        placeholder={`+ ${t('sidebar.addTicker')}`}
        className="h-7 text-xs"
      />
      {showDropdown && (
        <div className="absolute left-0 right-0 top-full mt-1 z-10 max-h-48 overflow-y-auto rounded-md border border-border bg-popover shadow-md">
          {isSearching && (
            <div className="px-2 py-1 text-xs text-muted-foreground">
              Searching...
            </div>
          )}
          {!isSearching && results.length === 0 && (
            <div className="px-2 py-1 text-xs text-muted-foreground">
              No matches.
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
          <DialogTitle>{t('sidebar.newWatchlist')}</DialogTitle>
          <DialogDescription>
            Give the list a name. You can add tickers next.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-2 py-2">
          <label htmlFor="wl-name" className="text-sm font-medium">
            Name
          </label>
          <Input
            id="wl-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && name.trim()) submit();
            }}
            placeholder={t('sidebarDialogs.watchlistNamePlaceholder')}
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={isLoading || !name.trim()}>
            {isLoading ? 'Creating...' : 'Create'}
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
          <DialogTitle>{t('common.rename')} "{watchlist.name}"</DialogTitle>
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
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={isLoading || !name.trim()}>
            {isLoading ? t('lab.specJson.saving') : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
