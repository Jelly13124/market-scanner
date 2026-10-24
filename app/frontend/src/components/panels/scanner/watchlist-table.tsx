// Top-N ranked watchlist table for a completed scan run.
// Sortable by rank, ticker, score, direction. Triggers rendered as badges.

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { scannerService } from '@/services/scanner-service';
import type {
  Direction,
  QuotesByTicker,
  TriggerPayload,
  WatchlistEntryResponse,
} from '@/types/scanner';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Minus } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

const PAGE_SIZE = 20;

interface WatchlistTableProps {
  entries: WatchlistEntryResponse[];
  /** Run id to fetch live quotes for. When omitted the price/today columns
   *  stay as em-dashes (e.g. while a scan is still streaming). */
  runId?: number | null;
  /** Invoked when a row is clicked. The scanner panel uses this to open a
   *  Stage-2 flow tab pre-seeded with the clicked ticker. */
  onTickerClick?: (ticker: string) => void;
}

type SortKey = 'rank' | 'ticker' | 'score' | 'direction' | 'price' | 'today';

const DIRECTION_ORDER: Record<Direction, number> = {
  bullish: 0,
  neutral: 1,
  bearish: 2,
};

const DETECTOR_LABELS: Record<string, string> = {
  earnings_event: 'EARN',
  // Legacy keys retained so previously persisted scan rows still render as EARN.
  earnings_surprise: 'EARN',
  earnings_upcoming: 'EARN',
  insider_cluster: 'INSDR',
  price_volume_anomaly: 'VOL',
  news_sentiment_shift: 'NEWS',
  intraday_move: 'IDAY',
  analyst_rating: 'ANLY',
  target_price_change: 'TGT',
  bollinger_squeeze: 'SQZ',
  obv_divergence: 'OBV',
};

function DirectionPill({ direction }: { direction: Direction }) {
  if (direction === 'bullish') {
    return (
      <span className="inline-flex items-center gap-1 text-green-600 text-xs font-medium">
        <ArrowUp size={12} />
        bull
      </span>
    );
  }
  if (direction === 'bearish') {
    return (
      <span className="inline-flex items-center gap-1 text-red-600 text-xs font-medium">
        <ArrowDown size={12} />
        bear
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 text-muted-foreground text-xs">
      <Minus size={12} />
      neut
    </span>
  );
}

function TriggerBadge({ trigger }: { trigger: TriggerPayload }) {
  const label = DETECTOR_LABELS[trigger.detector] || trigger.detector.slice(0, 4).toUpperCase();
  const isPositive = trigger.severity_z > 0;
  // Tailwind doesn't ship bg-green-100 via shadcn default themes here, so we
  // inline the colors. Numbers are clipped to 1 decimal for compactness.
  return (
    <span
      title={trigger.reason}
      className={cn(
        'inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-mono font-medium border',
        isPositive
          ? 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950 dark:text-green-300 dark:border-green-800'
          : 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950 dark:text-red-300 dark:border-red-800',
      )}
    >
      {label}({trigger.severity_z >= 0 ? '+' : ''}
      {trigger.severity_z.toFixed(1)})
    </span>
  );
}

function SortHeader({
  label,
  active,
  desc,
  onClick,
  align = 'left',
}: {
  label: string;
  active: boolean;
  desc: boolean;
  onClick: () => void;
  align?: 'left' | 'right';
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'inline-flex w-full items-center gap-1 text-xs font-medium',
        align === 'right' ? 'justify-end' : 'justify-start',
        active ? 'text-foreground' : 'text-muted-foreground',
      )}
    >
      {label}
      {active && (desc ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
    </button>
  );
}

export function WatchlistTable({ entries, runId, onTickerClick }: WatchlistTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [desc, setDesc] = useState(false);
  const [quotes, setQuotes] = useState<QuotesByTicker | null>(null);
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [page, setPage] = useState(0);
  const { t } = useTranslation();

  // Switching to a different scan run (or a re-run that changes the row count)
  // should start back at page 1 — and guarantees we never sit on a now
  // out-of-range page.
  useEffect(() => {
    setPage(0);
  }, [runId, entries.length]);

  // Fetch live quotes once entries land and we have a runId. Reset when
  // either changes (new run → discard old prices).
  useEffect(() => {
    if (!runId || entries.length === 0) {
      setQuotes(null);
      return;
    }
    let cancelled = false;
    setQuotesLoading(true);
    setQuotes(null);
    scannerService
      .getRunQuotes(runId)
      .then((q) => {
        if (!cancelled) setQuotes(q);
      })
      .catch((err) => {
        console.warn('getRunQuotes failed', err);
        if (!cancelled) setQuotes({});
      })
      .finally(() => {
        if (!cancelled) setQuotesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, entries]);

  function toggleSort(k: SortKey) {
    if (k === sortKey) {
      setDesc(!desc);
    } else {
      setSortKey(k);
      // Defaults: rank/ticker ascending; score/price/today descending
      // (most interesting first).
      setDesc(k === 'score' || k === 'price' || k === 'today');
    }
  }

  const sorted = [...entries].sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case 'rank':
        cmp = a.rank - b.rank;
        break;
      case 'ticker':
        cmp = a.ticker.localeCompare(b.ticker);
        break;
      case 'score':
        cmp = a.composite_score - b.composite_score;
        break;
      case 'direction':
        cmp = DIRECTION_ORDER[a.direction] - DIRECTION_ORDER[b.direction];
        break;
      case 'price': {
        // Nulls sort to the bottom (regardless of asc/desc) — they're
        // missing data, not zero.
        const pa = quotes?.[a.ticker]?.current_price;
        const pb = quotes?.[b.ticker]?.current_price;
        if (pa == null && pb == null) cmp = 0;
        else if (pa == null) return 1;
        else if (pb == null) return -1;
        else cmp = pa - pb;
        break;
      }
      case 'today': {
        const pa = quotes?.[a.ticker]?.percent_change;
        const pb = quotes?.[b.ticker]?.percent_change;
        if (pa == null && pb == null) cmp = 0;
        else if (pa == null) return 1;
        else if (pb == null) return -1;
        else cmp = pa - pb;
        break;
      }
    }
    return desc ? -cmp : cmp;
  });

  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paged = sorted.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  if (entries.length === 0) {
    return (
      <div className="text-center text-sm text-muted-foreground py-12">
        {t('scanner.watchlistTable.noEntries')}
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-12">
              <SortHeader label={t('scanner.watchlistTable.rank')} active={sortKey === 'rank'} desc={desc} onClick={() => toggleSort('rank')} />
            </TableHead>
            <TableHead className="w-20">
              <SortHeader label={t('scanner.watchlistTable.ticker')} active={sortKey === 'ticker'} desc={desc} onClick={() => toggleSort('ticker')} />
            </TableHead>
            <TableHead className="w-20 text-right">
              <SortHeader label={t('scanner.watchlistTable.score')} align="right" active={sortKey === 'score'} desc={desc} onClick={() => toggleSort('score')} />
            </TableHead>
            <TableHead className="w-24 text-right">
              <SortHeader label={t('scanner.watchlistTable.price')} align="right" active={sortKey === 'price'} desc={desc} onClick={() => toggleSort('price')} />
            </TableHead>
            <TableHead className="w-20 text-right">
              <SortHeader label={t('scanner.watchlistTable.today')} align="right" active={sortKey === 'today'} desc={desc} onClick={() => toggleSort('today')} />
            </TableHead>
            <TableHead className="w-20">
              <SortHeader label={t('scanner.watchlistTable.dir')} active={sortKey === 'direction'} desc={desc} onClick={() => toggleSort('direction')} />
            </TableHead>
            <TableHead>{t('scanner.watchlistTable.triggers')}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {paged.map((entry) => {
            const quote = quotes?.[entry.ticker];
            const price = quote?.current_price;
            const pct = quote?.percent_change;
            return (
            <TableRow
              key={entry.id}
              className={cn(
                onTickerClick && 'cursor-pointer hover:bg-accent/50',
              )}
              onClick={() => onTickerClick?.(entry.ticker)}
            >
              <TableCell className="text-muted-foreground text-xs tabular-nums">
                {entry.rank}
              </TableCell>
              <TableCell className="font-mono font-semibold text-cyan-700 dark:text-cyan-300">
                {entry.ticker}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                <Badge variant="outline" className="font-mono">
                  {entry.composite_score.toFixed(1)}
                </Badge>
              </TableCell>
              <TableCell className="text-right tabular-nums font-mono text-xs">
                {price != null
                  ? `$${price.toFixed(2)}`
                  : quotes === null && quotesLoading
                    ? <span className="text-muted-foreground">…</span>
                    : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell className="text-right tabular-nums font-mono text-xs">
                {pct != null ? (
                  <span className={cn(
                    'font-medium',
                    pct > 0 ? 'text-green-600 dark:text-green-400'
                            : pct < 0 ? 'text-red-600 dark:text-red-400'
                                      : 'text-muted-foreground',
                  )}>
                    {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                  </span>
                ) : quotes === null && quotesLoading
                    ? <span className="text-muted-foreground">…</span>
                    : <span className="text-muted-foreground">—</span>}
              </TableCell>
              <TableCell>
                <DirectionPill direction={entry.direction} />
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap gap-1">
                  {entry.triggers.map((t, idx) => (
                    <TriggerBadge key={idx} trigger={t} />
                  ))}
                </div>
              </TableCell>
            </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {sorted.length > PAGE_SIZE && (
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
              page: page + 1, pages: totalPages, total: sorted.length,
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
