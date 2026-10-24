// Settings → "My schedules" — one place to see every scheduled job.
//
// Read-only aggregation of the three independent scheduling surfaces — Scanner
// configs, Screener presets, and Report schedules — each with a quick
// enable/pause toggle. Editing/creating still lives in the respective panels
// (Scanner config dialog, Screener preset manager, the Report-schedules
// section); this view is the at-a-glance "what runs when" + fast pause.

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  describeCron,
  reportSchedulesService,
  type ReportSchedule,
} from '@/services/report-schedules-api';
import { scannerService } from '@/services/scanner-service';
import { listPresets, patchPreset } from '@/services/screener-service';
import type { ScannerConfigResponse } from '@/types/scanner';
import type { ScreenerPreset } from '@/types/screener';
import { CalendarClock, FileText, Filter, Radar } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

type Kind = 'scanner' | 'screener' | 'report';

interface Row {
  key: string;
  kind: Kind;
  title: string;
  cron: string;
  enabled: boolean;
  lastRun?: string | null;
  toggle: (on: boolean) => Promise<void>;
}

export function SchedulesOverview() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = async () => {
    setLoading(true);
    try {
      // Each source is independent — a failure in one shouldn't blank the view.
      const [configs, presets, schedules] = await Promise.all([
        scannerService.listConfigs().catch(() => [] as ScannerConfigResponse[]),
        listPresets().catch(() => [] as ScreenerPreset[]),
        reportSchedulesService.list().catch(() => [] as ReportSchedule[]),
      ]);
      const next: Row[] = [];
      for (const c of configs) {
        next.push({
          key: `scanner-${c.id}`, kind: 'scanner', title: c.name,
          cron: c.cron_expr, enabled: c.is_enabled,
          toggle: async (on) => { await scannerService.updateConfig(c.id, { is_enabled: on }); },
        });
      }
      for (const p of presets) {
        next.push({
          key: `screener-${p.id}`, kind: 'screener', title: p.name,
          cron: p.cron_expr, enabled: p.schedule_enabled,
          toggle: async (on) => { await patchPreset(p.id, { schedule_enabled: on }); },
        });
      }
      for (const s of schedules) {
        next.push({
          key: `report-${s.id}`, kind: 'report', title: s.tickers.join(', '),
          cron: s.cron_expr, enabled: s.is_enabled, lastRun: s.last_run_at,
          toggle: async (on) => { await reportSchedulesService.update(s.id, { is_enabled: on }); },
        });
      }
      setRows(next);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const onToggle = async (row: Row, on: boolean) => {
    setBusy((b) => ({ ...b, [row.key]: true }));
    try {
      await row.toggle(on);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy((b) => ({ ...b, [row.key]: false }));
    }
  };

  const KIND_META: Record<Kind, { icon: typeof Radar; label: string }> = {
    scanner: { icon: Radar, label: t('settings.plans.scanner', 'Scanner scans') },
    screener: { icon: Filter, label: t('settings.plans.screener', 'Screener presets') },
    report: { icon: FileText, label: t('settings.plans.reports', 'Report deliveries') },
  };
  const groups: Kind[] = ['scanner', 'screener', 'report'];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-primary mb-2 flex items-center gap-2">
          <CalendarClock className="h-5 w-5" /> {t('settings.plans.title', 'My schedules')}
        </h2>
        <p className="text-sm text-muted-foreground">
          {t('settings.plans.desc', 'Everything that runs on a schedule, in one place. Edit the details in the Scanner / Screener / Report-schedule panels; pause or resume here. Times are US Eastern.')}
        </p>
      </div>

      {error && (
        <Card className="bg-red-500/5 border-red-500/20">
          <CardContent className="p-4 text-xs text-red-500">{error}</CardContent>
        </Card>
      )}

      {loading ? (
        <div className="text-sm text-muted-foreground">{t('common.loading')}</div>
      ) : rows.length === 0 ? (
        <div className="text-sm text-muted-foreground">{t('settings.plans.empty', 'Nothing scheduled yet.')}</div>
      ) : (
        groups.map((kind) => {
          const groupRows = rows.filter((r) => r.kind === kind);
          if (!groupRows.length) return null;
          const Meta = KIND_META[kind];
          const Icon = Meta.icon;
          return (
            <Card key={kind} className="bg-panel border-gray-700 dark:border-gray-700">
              <CardHeader>
                <CardTitle className="text-lg font-medium text-primary flex items-center gap-2">
                  <Icon className="h-4 w-4" /> {Meta.label}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {groupRows.map((row) => (
                  <div key={row.key} className="flex items-center gap-3 border-b pb-2 last:border-0">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">{row.title}</div>
                      <div className="text-xs text-muted-foreground">
                        {describeCron(row.cron)}
                        {row.lastRun && ` · ${t('settings.plans.last', 'last')} ${new Date(row.lastRun).toLocaleString()}`}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant={row.enabled ? 'outline' : 'ghost'}
                      className="h-7 text-xs"
                      disabled={busy[row.key]}
                      onClick={() => onToggle(row, !row.enabled)}
                    >
                      {row.enabled
                        ? t('settings.plans.enabled', 'Enabled')
                        : t('settings.plans.paused', 'Paused')}
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          );
        })
      )}
    </div>
  );
}
