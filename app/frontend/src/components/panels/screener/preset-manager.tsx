import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { buildCron, type Frequency } from '@/services/report-schedules-api';
import { deletePreset, listPresets, patchPreset } from '@/services/screener-service';
import { ScreenerPreset } from '@/types/screener';
import { Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

interface PresetManagerProps {
  open: boolean;
  onOpenChange: (b: boolean) => void;
  onChanged?: () => void;
}

/** Inverse of buildCron — split a "m h * * dow" cron into freq + HH:MM for the
 *  per-preset schedule editor. Falls back to daily 22:05 on anything odd. */
function parseCron(expr: string): { freq: Frequency; time: string } {
  const parts = (expr || '').trim().split(/\s+/);
  if (parts.length !== 5) return { freq: 'daily', time: '22:05' };
  const [m, h, , , dow] = parts;
  const time = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  const freq: Frequency = dow === '1-5' ? 'weekdays' : dow === '1' ? 'weekly' : 'daily';
  return { freq, time };
}

export function PresetManager({ open, onOpenChange, onChanged }: PresetManagerProps) {
  const { t } = useTranslation();
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [busy, setBusy] = useState<Record<number, boolean>>({});

  const reload = () => {
    listPresets()
      .then(setPresets)
      .catch(console.error);
  };

  useEffect(() => {
    if (open) reload();
  }, [open]);

  const setBusyFor = (id: number, val: boolean) =>
    setBusy((prev) => ({ ...prev, [id]: val }));

  const handleSchedule = async (p: ScreenerPreset, enabled: boolean) => {
    setBusyFor(p.id, true);
    try {
      await patchPreset(p.id, { schedule_enabled: enabled });
      reload();
      onChanged?.();
    } catch {
      toast.error(t('screener.presets.patch_error', 'Failed to update preset'));
    } finally {
      setBusyFor(p.id, false);
    }
  };

  const handleChannel = async (p: ScreenerPreset, channel: string, on: boolean) => {
    setBusyFor(p.id, true);
    try {
      const next = new Set(p.notify_channels ?? []);
      if (on) next.add(channel); else next.delete(channel);
      await patchPreset(p.id, { notify_channels: [...next] });
      reload();
      onChanged?.();
    } catch {
      toast.error(t('screener.presets.patch_error', 'Failed to update preset'));
    } finally {
      setBusyFor(p.id, false);
    }
  };

  const handleCron = async (p: ScreenerPreset, cron_expr: string) => {
    setBusyFor(p.id, true);
    try {
      await patchPreset(p.id, { cron_expr });
      reload();
      onChanged?.();
    } catch {
      toast.error(t('screener.presets.patch_error', 'Failed to update preset'));
    } finally {
      setBusyFor(p.id, false);
    }
  };

  const handleDelete = async (p: ScreenerPreset) => {
    if (!window.confirm(t('screener.presets.delete_confirm', `Delete preset "${p.name}"?`))) return;
    setBusyFor(p.id, true);
    try {
      await deletePreset(p.id);
      toast.success(t('screener.presets.deleted', 'Preset deleted'));
      reload();
      onChanged?.();
    } catch {
      toast.error(t('screener.presets.delete_error', 'Failed to delete preset'));
    } finally {
      setBusyFor(p.id, false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('screener.presets.manage_title', 'Manage Presets')}</DialogTitle>
        </DialogHeader>

        {presets.length === 0 ? (
          <div className="text-sm text-muted-foreground py-4 text-center">
            {t('screener.presets.empty', 'No presets')}
          </div>
        ) : (
          <div className="space-y-2 max-h-96 overflow-y-auto pr-1">
            {presets.map((p) => {
              const channels = p.notify_channels ?? [];
              const isDisabled = busy[p.id] ?? false;
              return (
                <div
                  key={p.id}
                  className="rounded-md border px-3 py-2 text-sm"
                >
                  <div className="flex items-center gap-3">
                  {/* Name + match count */}
                  <div className="flex-1 min-w-0">
                    <span className="font-medium truncate block">{p.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {t('screener.presets.last_match', 'last match: {{count}}', {
                        count: p.last_match_count ?? 0,
                      })}
                    </span>
                  </div>

                  {/* Schedule checkbox */}
                  <label className="flex items-center gap-1 text-xs cursor-pointer shrink-0">
                    <Checkbox
                      checked={p.schedule_enabled}
                      disabled={isDisabled}
                      onCheckedChange={(val) => handleSchedule(p, val === true)}
                    />
                    {t('screener.presets.schedule', 'Schedule')}
                  </label>

                  {/* Email channel checkbox */}
                  <label className="flex items-center gap-1 text-xs cursor-pointer shrink-0">
                    <Checkbox
                      checked={channels.includes('email')}
                      disabled={isDisabled}
                      onCheckedChange={(val) => handleChannel(p, 'email', val === true)}
                    />
                    {t('screener.presets.channel_email', 'Email')}
                  </label>

                  {/* Webhook channel checkbox */}
                  <label className="flex items-center gap-1 text-xs cursor-pointer shrink-0">
                    <Checkbox
                      checked={channels.includes('webhook')}
                      disabled={isDisabled}
                      onCheckedChange={(val) => handleChannel(p, 'webhook', val === true)}
                    />
                    {t('screener.presets.channel_webhook', 'Webhook')}
                  </label>

                  {/* Delete */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0 text-muted-foreground hover:text-destructive"
                    disabled={isDisabled}
                    onClick={() => handleDelete(p)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                  </div>

                  {/* Per-preset schedule cadence — shown only when scheduled */}
                  {p.schedule_enabled && (() => {
                    const { freq, time } = parseCron(p.cron_expr);
                    return (
                      <div className="mt-2 flex items-center gap-2 pl-1">
                        <span className="text-xs text-muted-foreground">
                          {t('screener.presets.runs_at', 'Runs')}:
                        </span>
                        <select
                          className="rounded border bg-background px-1.5 py-1 text-xs"
                          value={freq}
                          disabled={isDisabled}
                          onChange={(e) => handleCron(p, buildCron(e.target.value as Frequency, time))}
                        >
                          <option value="daily">{t('analyze.scheduleDialog.daily')}</option>
                          <option value="weekdays">{t('analyze.scheduleDialog.weekdays')}</option>
                          <option value="weekly">{t('analyze.scheduleDialog.weekly')}</option>
                        </select>
                        <input
                          type="time"
                          className="rounded border bg-background px-1.5 py-1 text-xs w-24"
                          value={time}
                          disabled={isDisabled}
                          onChange={(e) => handleCron(p, buildCron(freq, e.target.value))}
                        />
                        <span className="text-xs text-muted-foreground">ET</span>
                      </div>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
