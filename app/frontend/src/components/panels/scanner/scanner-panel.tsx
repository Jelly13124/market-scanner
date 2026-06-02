// ScannerPanel — main view rendered when the 'scanner' tab is active.
//
// Layout:
//   header        config dropdown + run-now + edit/new buttons
//   progress      live SSE progress (only while a run is in flight)
//   results       sortable Top-N watchlist table

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { scannerService } from '@/services/scanner-service';
import { useRequestAnalyze } from '@/hooks/use-request-analyze';
import { toast } from 'sonner';
import type {
  ScanProgressEvent,
  ScanRunSummary,
  ScannerConfigResponse,
  WatchlistEntryResponse,
} from '@/types/scanner';
import { Pencil, Play, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AgentRunsList } from './agent-runs-list';
import { AnalyzeButton } from './analyze-button';
import { NotificationSettings } from './notification-settings';
import { ScannerConfigDialog } from './scanner-config-dialog';
import { WatchlistTable } from './watchlist-table';

interface ScannerPanelProps {
  /** Optional initial config selection (e.g. from metadata when opening tab). */
  initialConfigId?: number;
}

export function ScannerPanel({ initialConfigId }: ScannerPanelProps) {
  const { t } = useTranslation();
  const requestAnalyze = useRequestAnalyze();
  // ---- config state -------------------------------------------------------
  const [configs, setConfigs] = useState<ScannerConfigResponse[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(initialConfigId ?? null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ScannerConfigResponse | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Phase 9: data tier badge — auto-detected from EODHD_API_KEY presence.
  const [tier, setTier] = useState<'paid' | 'free' | null>(null);

  // Load /tier once on mount; re-load when sidebar saves a new key.
  useEffect(() => {
    const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    fetch(`${API_BASE}/tier`)
      .then((r) => r.json())
      .then((data) => setTier(data.tier))
      .catch(() => setTier(null));
  }, []);

  // ---- run state ----------------------------------------------------------
  const [runId, setRunId] = useState<number | null>(null);
  const [run, setRun] = useState<ScanRunSummary | null>(null);
  const [progress, setProgress] = useState<ScanProgressEvent | null>(null);
  const [entries, setEntries] = useState<WatchlistEntryResponse[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  // ---- effects ------------------------------------------------------------

  const loadConfigs = useCallback(async () => {
    try {
      const list = await scannerService.listConfigs();
      setConfigs(list);
      // Default selection: keep current if still present, otherwise first.
      setSelectedId((prev) => {
        if (prev != null && list.some((c) => c.id === prev)) return prev;
        return list[0]?.id ?? null;
      });
    } catch (err) {
      setConfigError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  // Cleanup the SSE subscription if the panel unmounts mid-stream.
  useEffect(() => {
    return () => {
      abortRef.current?.();
    };
  }, []);

  const selectedConfig = useMemo(
    () => configs.find((c) => c.id === selectedId) ?? null,
    [configs, selectedId],
  );

  // ---- handlers -----------------------------------------------------------

  function handleNewConfig() {
    setEditing(null);
    setDialogOpen(true);
  }

  function handleEditConfig() {
    if (!selectedConfig) return;
    setEditing(selectedConfig);
    setDialogOpen(true);
  }

  function handleConfigSaved(saved: ScannerConfigResponse) {
    setConfigs((prev) => {
      const next = prev.some((c) => c.id === saved.id)
        ? prev.map((c) => (c.id === saved.id ? saved : c))
        : [...prev, saved];
      return next;
    });
    setSelectedId(saved.id);
  }

  async function handleConfirmDelete() {
    if (!selectedConfig) return;
    const targetId = selectedConfig.id;
    const targetName = selectedConfig.name;
    setDeleting(true);
    try {
      await scannerService.deleteConfig(targetId);
      // Drop any in-flight scan view tied to this config — its rows are gone.
      abortRef.current?.();
      setRunId(null);
      setRun(null);
      setProgress(null);
      setEntries([]);
      setStreamError(null);
      // Drop the config locally + pick a new selection (or null if empty).
      setConfigs((prev) => {
        const next = prev.filter((c) => c.id !== targetId);
        setSelectedId(next[0]?.id ?? null);
        return next;
      });
      toast.success(`Deleted "${targetName}"`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
      setDeleteConfirmOpen(false);
    }
  }

  // Subscribe to a run's live SSE stream. Extracted so both a fresh "Run now"
  // and an on-mount re-attach (after a tab switch) share the same wiring.
  const subscribeToRun = useCallback((run_id: number) => {
    abortRef.current?.();
    abortRef.current = scannerService.streamRun(run_id, {
      onStart: () => {
        /* no-op — we already have the run_id */
      },
      onProgress: (e) => setProgress(e),
      onComplete: async () => {
        // Fetch the full entries list when the scan finishes.
        try {
          const detail = await scannerService.getRunEntries(run_id);
          setEntries(detail.entries);
          setRun({
            id: detail.id,
            config_id: detail.config_id,
            status: detail.status,
            started_at: detail.started_at,
            completed_at: detail.completed_at,
            universe_size: detail.universe_size,
            error_message: detail.error_message,
            created_at: detail.created_at,
          });
        } catch (err) {
          setStreamError(err instanceof Error ? err.message : String(err));
        }
      },
      onError: (e) => setStreamError(e.message),
      onFatal: (err) => setStreamError(err.message),
    });
  }, []);

  async function handleRunNow() {
    if (!selectedConfig) return;
    setRunId(null);
    setRun(null);
    setProgress(null);
    setEntries([]);
    setStreamError(null);

    try {
      // runNow is idempotent: if a scan is already running for this config the
      // backend returns that run (already_running=true) instead of 500'ing, so
      // we simply re-attach to its stream below.
      const { run_id } = await scannerService.runNow(selectedConfig.id);
      setRunId(run_id);
      subscribeToRun(run_id);
    } catch (err) {
      setStreamError(err instanceof Error ? err.message : String(err));
    }
  }

  // Re-attach to the selected config's latest run on (re)mount or config switch.
  // A tab switch unmounts this panel and aborts the SSE, but the scan keeps
  // running server-side — RUNNING => resubscribe to live progress, COMPLETE =>
  // restore the results, otherwise show the empty state.
  useEffect(() => {
    if (selectedId == null) return;
    let cancelled = false;
    (async () => {
      try {
        const latest = await scannerService.getLatestRun(selectedId);
        if (cancelled) return;
        if (latest && latest.status === 'RUNNING') {
          setRunId(latest.id);
          setRun(latest);
          setProgress(null);
          setEntries([]);
          setStreamError(null);
          subscribeToRun(latest.id);
        } else if (latest && latest.status === 'COMPLETE') {
          const detail = await scannerService.getRunEntries(latest.id);
          if (cancelled) return;
          setRunId(latest.id);
          setRun(latest);
          setEntries(detail.entries);
          setProgress(null);
          setStreamError(null);
        } else {
          // No restorable run for this config — clean slate.
          abortRef.current?.();
          setRunId(null);
          setRun(null);
          setProgress(null);
          setEntries([]);
          setStreamError(null);
        }
      } catch {
        /* latest-run unavailable — leave whatever is showing */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, subscribeToRun]);

  function handleTickerClick(ticker: string) {
    // One-click → open/focus the Analyze tab, pre-fill this ticker, auto-run
    // the SOP deep-research report. Scanner universes are US.
    requestAnalyze(ticker, 'us');
  }

  // ---- render -------------------------------------------------------------

  const isRunning =
    run?.status === 'RUNNING' ||
    (runId !== null &&
      progress != null &&
      progress.processed < progress.total &&
      entries.length === 0);

  return (
    <div className="h-full w-full flex flex-col bg-background">
      {/* Header */}
      <div className="flex items-center gap-2 p-4 border-b">
        <h2 className="text-lg font-semibold mr-2">{t('scanner.title')}</h2>

        {/* Phase 9: data tier badge (paid = EODHD wired, free = Finnhub only) */}
        {tier && (
          <span
            className={
              tier === 'paid'
                ? 'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400 border border-emerald-300/40'
                : 'inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400 border border-amber-300/40'
            }
            title={tier === 'paid' ? t('scanner.tierPaidHint') : t('scanner.tierFreeHint')}
          >
            {tier === 'paid' ? t('scanner.tierPaid') : t('scanner.tierFree')}
          </span>
        )}

        <select
          value={selectedId ?? ''}
          onChange={(e) => setSelectedId(e.target.value ? Number(e.target.value) : null)}
          className="rounded-md border bg-background px-3 py-1.5 text-sm min-w-[220px]"
          disabled={configs.length === 0}
        >
          {configs.length === 0 && <option value="">{t('scanner.noConfigs')}</option>}
          {configs.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.universe_kind}, top {c.top_n}
              {c.is_enabled ? '' : ', disabled'})
            </option>
          ))}
        </select>

        <Button variant="outline" size="sm" onClick={handleEditConfig} disabled={!selectedConfig}>
          <Pencil size={14} className="mr-1" />
          Edit
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDeleteConfirmOpen(true)}
          disabled={!selectedConfig}
          title={t('scanner.deleteThisConfig')}
        >
          <Trash2 size={14} className="text-red-600 dark:text-red-400" />
        </Button>
        <Button variant="outline" size="sm" onClick={handleNewConfig}>
          <Plus size={14} className="mr-1" />
          New
        </Button>

        <div className="flex-1" />

        <Button variant="outline" size="sm" onClick={loadConfigs} title={t('scanner.reloadConfigs')}>
          <RefreshCw size={14} />
        </Button>
        <Button onClick={handleRunNow} disabled={!selectedConfig || isRunning} size="sm">
          <Play size={14} className="mr-1" />
          {isRunning ? 'Running…' : 'Run now'}
        </Button>
      </div>

      {/* Error banners */}
      {configError && (
        <div className="bg-red-50 dark:bg-red-950 border-b border-red-200 dark:border-red-800 px-4 py-2 text-sm text-red-700 dark:text-red-300">
          {configError}
        </div>
      )}
      {streamError && (
        <div className="bg-red-50 dark:bg-red-950 border-b border-red-200 dark:border-red-800 px-4 py-2 text-sm text-red-700 dark:text-red-300">
          {streamError}
        </div>
      )}

      {/* Progress (live SSE) */}
      {progress && (
        <div className="border-b px-4 py-3 bg-muted/40">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-mono tabular-nums">
              {progress.processed} / {progress.total}
            </span>
            <span className="text-muted-foreground">
              triggered={progress.triggered} skipped={progress.skipped} errors={progress.errors}
            </span>
            {progress.eta_seconds != null && progress.eta_seconds > 0 && (
              <span className="text-muted-foreground">ETA {Math.ceil(progress.eta_seconds)}s</span>
            )}
            <div className="flex-1" />
            {progress.current_ticker && (
              <span className="font-mono text-xs text-muted-foreground">
                {progress.current_ticker}
              </span>
            )}
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className="h-full bg-primary transition-all"
              style={{
                width: `${Math.min(100, (progress.processed / Math.max(progress.total, 1)) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* Results / empty state */}
      <div className="flex-1 overflow-auto p-4">
        {!runId && (
          <div className="text-center text-sm text-muted-foreground py-8">
            {configs.length === 0
              ? 'Create a scanner config to get started.'
              : 'Pick a config and click "Run now" to generate today\'s watchlist.'}
          </div>
        )}
        {runId && entries.length > 0 && (
          <>
            <div className="mb-3 flex items-center justify-between gap-3">
              {run && (
                <div className="text-xs text-muted-foreground">
                  Run #{run.id} · {run.status} · {run.universe_size} tickers scanned
                  {run.completed_at && ` · completed ${new Date(run.completed_at).toLocaleString()}`}
                </div>
              )}
              <AnalyzeButton tickers={entries.map((e) => e.ticker)} />
            </div>
            <WatchlistTable entries={entries} runId={runId} onTickerClick={handleTickerClick} />
            <div className="mt-6">
              <AgentRunsList />
            </div>
          </>
        )}
        {runId && entries.length > 0 && (
          <div className="mt-4">
            <NotificationSettings />
          </div>
        )}
        {runId && entries.length === 0 && !isRunning && !streamError && (
          <div className="text-center text-sm text-muted-foreground py-12">
            Waiting for the scan to finish…
          </div>
        )}
      </div>

      <ScannerConfigDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        editing={editing}
        onSaved={handleConfigSaved}
      />

      {/* Confirm delete modal */}
      <Dialog open={deleteConfirmOpen} onOpenChange={setDeleteConfirmOpen}>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>Delete scanner config?</DialogTitle>
            <DialogDescription>
              {selectedConfig ? (
                <>
                  Permanently delete <span className="font-semibold">{selectedConfig.name}</span>?
                  This also removes all past scan runs and watchlist entries created by
                  this config. This action cannot be undone.
                </>
              ) : (
                'No config selected.'
              )}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setDeleteConfirmOpen(false)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={handleConfirmDelete}
              disabled={!selectedConfig || deleting}
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
