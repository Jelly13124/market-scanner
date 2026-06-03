// Create / edit a ScannerConfig.
// Fields: name, universe_kind, custom tickers (when kind=custom),
// cron_expr (preset dropdown + custom), top_n, is_enabled.

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
import { scannerService } from '@/services/scanner-service';
import { watchlistService } from '@/services/watchlist-service';
import {
  CRON_PRESETS,
  DetectorMetadata,
  ScannerConfigCreateRequest,
  ScannerConfigResponse,
  ScannerWeightsExtension,
  UNIVERSE_KIND_OPTIONS,
  UniverseKind,
} from '@/types/scanner';
import { UserWatchlist } from '@/types/watchlist';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

interface ScannerConfigDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** When set, dialog edits this config instead of creating new. */
  editing?: ScannerConfigResponse | null;
  onSaved: (config: ScannerConfigResponse) => void;
}

const DEFAULT_FORM: ScannerConfigCreateRequest = {
  name: '',
  universe_kind: 'nasdaq100_sp500',
  cron_expr: '0 21 * * 1-5',
  is_enabled: true,
  top_n: 20,
  auto_sop_top_n: 0,
  auto_sop_use_personas: false,
  email_watchlist: false,
  email_reports: false,
};

export function ScannerConfigDialog({
  open,
  onOpenChange,
  editing,
  onSaved,
}: ScannerConfigDialogProps) {
  const [form, setForm] = useState<ScannerConfigCreateRequest>(DEFAULT_FORM);
  const { t } = useTranslation();
  const [cronPreset, setCronPreset] = useState<string>('0 21 * * 1-5');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detector picker: loaded once when dialog opens. detectorEnabled tracks
  // checkbox state (Set of names that are ON), detectorMult tracks slider
  // values (Map name -> float). Both are seeded from editing.weights when
  // editing, or "all enabled, mult=1.0" for new configs.
  const [detectorMeta, setDetectorMeta] = useState<DetectorMetadata[]>([]);
  const [detectorEnabled, setDetectorEnabled] = useState<Set<string>>(new Set());
  const [detectorMult, setDetectorMult] = useState<Record<string, number>>({});

  // Phase 5C — user watchlists for the universe_kind='watchlist' picker.
  // Loaded lazily when the dialog opens; null = still loading / failed.
  const [userWatchlists, setUserWatchlists] = useState<UserWatchlist[] | null>(null);

  // Sync form state when opening for edit / new.
  useEffect(() => {
    if (!open) return;
    if (editing) {
      setForm({
        name: editing.name,
        universe_kind: editing.universe_kind,
        universe_tickers: editing.universe_tickers ?? undefined,
        cron_expr: editing.cron_expr,
        is_enabled: editing.is_enabled,
        top_n: editing.top_n,
        weights: editing.weights ?? undefined,
        user_watchlist_id: editing.user_watchlist_id ?? undefined,
        auto_sop_top_n: editing.auto_sop_top_n ?? 0,
        auto_sop_use_personas: editing.auto_sop_use_personas ?? false,
        email_watchlist: editing.email_watchlist ?? false,
        email_reports: editing.email_reports ?? false,
      });
      const preset = CRON_PRESETS.find((p) => p.expr === editing.cron_expr);
      setCronPreset(preset ? editing.cron_expr : 'custom');
    } else {
      setForm(DEFAULT_FORM);
      setCronPreset(DEFAULT_FORM.cron_expr!);
    }
    setError(null);
  }, [open, editing]);

  // Fetch user watchlists once when the dialog opens — needed for the
  // 'watchlist' universe-kind picker. Failure is non-fatal: the dropdown
  // just renders empty and the form falls back to a server-side error.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    watchlistService
      .list()
      .then((rows) => {
        if (!cancelled) setUserWatchlists(rows);
      })
      .catch((err) => {
        if (!cancelled) {
          setUserWatchlists([]);
          console.warn('Failed to load user watchlists:', err);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  // Load detector metadata + seed picker state when dialog opens.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    scannerService
      .listDetectors()
      .then((list) => {
        if (cancelled) return;
        setDetectorMeta(list);
        const w = (editing?.weights ?? {}) as ScannerWeightsExtension;
        // null/undefined enabled_detectors = "all enabled" per the model.
        const enabledList = w.enabled_detectors;
        const enabledSet =
          enabledList === undefined || enabledList === null
            ? new Set(list.map((d) => d.name))
            : new Set(enabledList);
        setDetectorEnabled(enabledSet);
        // Mult: any name missing from the saved dict defaults to 1.0.
        const savedMult = w.detector_severity_mult ?? {};
        const fullMult: Record<string, number> = {};
        for (const d of list) {
          fullMult[d.name] = savedMult[d.name] ?? 1.0;
        }
        setDetectorMult(fullMult);
      })
      .catch((err) => {
        // Non-fatal — picker just won't render. User can still save the config.
        console.warn('Failed to load detector metadata:', err);
      });
    return () => {
      cancelled = true;
    };
  }, [open, editing]);

  function handleSelectAllDetectors() {
    setDetectorEnabled(new Set(detectorMeta.map((d) => d.name)));
  }
  function handleClearAllDetectors() {
    setDetectorEnabled(new Set());
  }
  function handleRecommendedDefaults() {
    setDetectorEnabled(new Set(detectorMeta.map((d) => d.name)));
    const next: Record<string, number> = {};
    for (const d of detectorMeta) {
      next[d.name] = d.default_mult;
    }
    setDetectorMult(next);
  }
  function toggleDetector(name: string, on: boolean) {
    setDetectorEnabled((prev) => {
      const next = new Set(prev);
      if (on) next.add(name);
      else next.delete(name);
      return next;
    });
  }
  function setMult(name: string, value: number) {
    setDetectorMult((prev) => ({ ...prev, [name]: value }));
  }

  function handleCronChange(value: string) {
    setCronPreset(value);
    if (value !== 'custom') {
      setForm((f) => ({ ...f, cron_expr: value }));
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      // Frontend guard mirroring the backend validator — empty selection is
      // rejected because a config that runs no detectors produces no triggers.
      if (detectorMeta.length > 0 && detectorEnabled.size === 0) {
        setError('Pick at least one detector.');
        setSubmitting(false);
        return;
      }

      const payload: ScannerConfigCreateRequest = { ...form };
      // Manual ticker entry was removed from the UI; never send custom tickers.
      delete payload.universe_tickers;

      // Auto-SOP off => the persona + report-email toggles are hidden; force
      // them false so a stale `true` from a prior edit can't leak through.
      if (!payload.auto_sop_top_n || payload.auto_sop_top_n <= 0) {
        payload.auto_sop_top_n = 0;
        payload.auto_sop_use_personas = false;
        payload.email_reports = false;
      }

      // Phase 5C — watchlist kind requires a chosen UserWatchlist id. Mirror
      // the backend model_validator so the user sees the error inline rather
      // than as a server 422.
      if (form.universe_kind === 'watchlist') {
        if (!form.user_watchlist_id) {
          setError('Pick a watchlist for universe_kind=watchlist.');
          setSubmitting(false);
          return;
        }
        payload.user_watchlist_id = form.user_watchlist_id;
      } else {
        // Clear FK when switching away from watchlist — explicit null tells
        // the PATCH route to drop the value rather than ignore the field.
        payload.user_watchlist_id = null;
      }

      // Merge picker state into weights JSON. We persist enabled_detectors
      // only when a strict subset is selected (otherwise null = "all" keeps
      // the JSON small + lets the backend default kick in). detector_severity_mult
      // persists only the entries that diverge from 1.0 for the same reason.
      if (detectorMeta.length > 0) {
        const allNames = detectorMeta.map((d) => d.name);
        const isAllEnabled = allNames.every((n) => detectorEnabled.has(n));
        const enabledList = isAllEnabled
          ? null
          : allNames.filter((n) => detectorEnabled.has(n));
        const multSubset: Record<string, number> = {};
        for (const [name, value] of Object.entries(detectorMult)) {
          if (Math.abs(value - 1.0) > 1e-9) multSubset[name] = value;
        }
        const w: ScannerWeightsExtension = {
          ...((payload.weights ?? {}) as ScannerWeightsExtension),
          enabled_detectors: enabledList,
          detector_severity_mult: multSubset,
        };
        payload.weights = w as Record<string, unknown>;
      }

      const saved = editing
        ? await scannerService.updateConfig(editing.id, payload)
        : await scannerService.createConfig(payload);
      onSaved(saved);
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[640px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit scanner config' : 'New scanner config'}</DialogTitle>
          <DialogDescription>
            Scanner runs on a cron schedule and produces a ranked watchlist of stocks
            that triggered any of the enabled detectors.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div className="space-y-1.5">
            <label htmlFor="cfg-name" className="text-sm font-medium">Name</label>
            <Input
              id="cfg-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="e.g. nightly nasdaq+sp500"
            />
          </div>

          {/* Universe */}
          <div className="space-y-1.5">
            <label htmlFor="cfg-universe" className="text-sm font-medium">{t('scanner.config.universe')}</label>
            <select
              id="cfg-universe"
              value={form.universe_kind}
              onChange={(e) =>
                setForm({ ...form, universe_kind: e.target.value as UniverseKind })
              }
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              {UNIVERSE_KIND_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label} — {opt.description}
                </option>
              ))}
            </select>
          </div>

          {/* User watchlist picker (Phase 5C — only when kind=watchlist) */}
          {form.universe_kind === 'watchlist' && (
            <div className="space-y-1.5">
              <label htmlFor="cfg-watchlist" className="text-sm font-medium">{t('scanner.config.userWatchlist')}</label>
              {userWatchlists === null ? (
                <div className="text-sm text-muted-foreground">Loading watchlists…</div>
              ) : userWatchlists.length === 0 ? (
                <div className="text-sm text-muted-foreground">
                  No saved watchlists. Create one in the Watchlist tab first.
                </div>
              ) : (
                <select
                  id="cfg-watchlist"
                  value={form.user_watchlist_id ?? ''}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      user_watchlist_id: e.target.value ? Number(e.target.value) : undefined,
                    })
                  }
                  className="w-full rounded-md border bg-background px-3 py-2 text-sm"
                >
                  <option value="">— pick a watchlist —</option>
                  {userWatchlists.map((wl) => (
                    <option key={wl.id} value={wl.id}>
                      {wl.name} ({wl.tickers.length} ticker{wl.tickers.length === 1 ? '' : 's'})
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Cron */}
          <div className="space-y-1.5">
            <label htmlFor="cfg-cron-preset" className="text-sm font-medium">Schedule (America/New_York)</label>
            <select
              id="cfg-cron-preset"
              value={cronPreset}
              onChange={(e) => handleCronChange(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm"
            >
              {CRON_PRESETS.map((p) => (
                <option key={p.expr} value={p.expr}>
                  {p.label}
                </option>
              ))}
              <option value="custom">Custom cron expression…</option>
            </select>
            {cronPreset === 'custom' && (
              <Input
                value={form.cron_expr}
                onChange={(e) => setForm({ ...form, cron_expr: e.target.value })}
                placeholder="0 21 * * 1-5"
                className="font-mono"
              />
            )}
          </div>

          {/* Schedule & delivery — email + auto-analyze after each scheduled scan. */}
          <div className="space-y-3 rounded-md border bg-muted/20 px-3 py-3">
            <div className="text-sm font-medium">{t('scanner.config.deliveryTitle')}</div>

            {/* Email the watchlist after each scheduled scan */}
            <div className="flex items-start gap-2">
              <Checkbox
                id="cfg-email-watchlist"
                checked={form.email_watchlist ?? false}
                onCheckedChange={(v) =>
                  setForm({ ...form, email_watchlist: v === true })
                }
              />
              <label htmlFor="cfg-email-watchlist" className="text-sm font-normal cursor-pointer">
                {t('scanner.config.emailWatchlist')}
              </label>
            </div>

            {/* Auto-SOP top-N */}
            <div className="space-y-1.5">
              <label htmlFor="cfg-auto-sop-topn" className="text-sm font-medium">
                {t('scanner.config.autoSop')}
              </label>
              <Input
                id="cfg-auto-sop-topn"
                type="number"
                min={0}
                max={20}
                value={form.auto_sop_top_n ?? 0}
                onChange={(e) =>
                  setForm({ ...form, auto_sop_top_n: Number(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">{t('scanner.config.autoSopHint')}</p>
            </div>

            {/* Persona + report-email toggles — only relevant when auto-SOP is on. */}
            {(form.auto_sop_top_n ?? 0) > 0 && (
              <div className="space-y-2 pl-1">
                <div className="flex items-start gap-2">
                  <Checkbox
                    id="cfg-auto-sop-personas"
                    checked={form.auto_sop_use_personas ?? false}
                    onCheckedChange={(v) =>
                      setForm({ ...form, auto_sop_use_personas: v === true })
                    }
                  />
                  <label htmlFor="cfg-auto-sop-personas" className="text-sm font-normal cursor-pointer">
                    {t('scanner.config.autoSopUsePersonas')}
                  </label>
                </div>
                <div className="flex items-start gap-2">
                  <Checkbox
                    id="cfg-email-reports"
                    checked={form.email_reports ?? false}
                    onCheckedChange={(v) =>
                      setForm({ ...form, email_reports: v === true })
                    }
                  />
                  <label htmlFor="cfg-email-reports" className="text-sm font-normal cursor-pointer">
                    {t('scanner.config.emailReports')}
                  </label>
                </div>
              </div>
            )}

            <p className="text-xs text-muted-foreground">{t('scanner.config.emailDeliveryHelp')}</p>
          </div>

          {/* Top-N + Enabled */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label htmlFor="cfg-topn" className="text-sm font-medium">Top-N watchlist size</label>
              <Input
                id="cfg-topn"
                type="number"
                min={1}
                max={200}
                value={form.top_n ?? 20}
                onChange={(e) => setForm({ ...form, top_n: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="cfg-enabled" className="text-sm font-medium">{t('scanner.config.enabled')}</label>
              <div className="flex items-center h-9 gap-2">
                <Checkbox
                  id="cfg-enabled"
                  checked={form.is_enabled ?? true}
                  onCheckedChange={(v) =>
                    setForm({ ...form, is_enabled: v === true })
                  }
                />
                <label htmlFor="cfg-enabled" className="text-sm font-normal">
                  Run on schedule
                </label>
              </div>
            </div>
          </div>

          {/* Detectors picker */}
          {detectorMeta.length > 0 && (
            <details open className="rounded-md border bg-muted/20">
              <summary className="cursor-pointer select-none px-3 py-2 text-sm font-medium flex items-center justify-between">
                <span>
                  Detectors
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    {detectorEnabled.size} / {detectorMeta.length} enabled
                  </span>
                </span>
              </summary>
              <div className="space-y-2 px-3 pb-3">
                <div className="flex flex-wrap gap-2 pt-1">
                  <Button type="button" variant="outline" size="sm" onClick={handleSelectAllDetectors}>
                    Select all
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={handleClearAllDetectors}>
                    Clear all
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={handleRecommendedDefaults}>
                    Recommended defaults
                  </Button>
                </div>
                <div className="divide-y">
                  {detectorMeta.map((d) => {
                    const on = detectorEnabled.has(d.name);
                    const mult = detectorMult[d.name] ?? 1.0;
                    return (
                      <div
                        key={d.name}
                        className="grid grid-cols-[auto_1fr_120px_40px] items-center gap-2 py-2"
                      >
                        <Checkbox
                          id={`det-${d.name}`}
                          checked={on}
                          onCheckedChange={(v) => toggleDetector(d.name, v === true)}
                        />
                        <label
                          htmlFor={`det-${d.name}`}
                          className="text-sm cursor-pointer"
                          title={d.description}
                        >
                          <span className="font-medium">{d.label}</span>
                          <span className="ml-2 text-xs text-muted-foreground">
                            {d.description}
                          </span>
                        </label>
                        <input
                          type="range"
                          min={0}
                          max={2}
                          step={0.05}
                          value={mult}
                          disabled={!on}
                          onChange={(e) => setMult(d.name, Number(e.target.value))}
                          className="w-full accent-primary disabled:opacity-40"
                          title={`Severity multiplier (default ${d.default_mult.toFixed(2)})`}
                        />
                        <span className={`text-xs font-mono tabular-nums text-right ${on ? '' : 'text-muted-foreground'}`}>
                          {mult.toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </details>
          )}

          {error && (
            <div className="text-sm text-red-600 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded p-2">
              {error}
            </div>
          )}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? 'Saving…' : editing ? 'Save changes' : 'Create config'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
