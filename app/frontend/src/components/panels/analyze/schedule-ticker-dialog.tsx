// Schedule dialog (Task 10) — create a ReportSchedule for the Analyze panel's
// current ticker. Reuses the report-schedules service + the frequency↔cron
// helpers that power Settings → Scheduled reports, so a schedule made here
// shows up there and is managed in one place.

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  buildCron,
  describeCron,
  reportSchedulesService,
  type Frequency,
} from '@/services/report-schedules-api';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

export interface ScheduleTickerContext {
  ticker: string;
  /** 'en' | 'zh' — seeds the dialog's language select. */
  reportLanguage: string;
}

interface ScheduleTickerDialogProps {
  /** Non-null opens the dialog (for that ticker); null closes it. */
  ctx: ScheduleTickerContext | null;
  onClose: () => void;
}

export function ScheduleTickerDialog({ ctx, onClose }: ScheduleTickerDialogProps) {
  const { t } = useTranslation();
  const [freq, setFreq] = useState<Frequency>('weekdays');
  const [time, setTime] = useState('09:30');
  const [lang, setLang] = useState('en');
  const [busy, setBusy] = useState(false);

  const ticker = ctx?.ticker ?? '';

  // Re-seed the language from the Input node each time the dialog opens.
  useEffect(() => {
    if (ctx) setLang(ctx.reportLanguage || 'en');
  }, [ctx]);

  const submit = async () => {
    if (!ticker) return;
    setBusy(true);
    try {
      await reportSchedulesService.create({
        tickers: [ticker],
        cron_expr: buildCron(freq, time),
        report_language: lang,
      });
      toast.success(t('analyze.scheduleDialog.created', { ticker }));
      onClose();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={ctx != null} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('analyze.scheduleDialog.title', { ticker })}</DialogTitle>
        </DialogHeader>
        <p className="text-sm text-muted-foreground">
          {t('analyze.scheduleDialog.description')}
        </p>
        <div className="space-y-3 pt-1">
          <div className="flex items-center gap-2 flex-wrap">
            <select
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
              value={freq}
              onChange={(e) => setFreq(e.target.value as Frequency)}
            >
              <option value="daily">{t('analyze.scheduleDialog.daily')}</option>
              <option value="weekdays">{t('analyze.scheduleDialog.weekdays')}</option>
              <option value="weekly">{t('analyze.scheduleDialog.weekly')}</option>
            </select>
            <Input
              type="time"
              className="w-32"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
            <select
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
              value={lang}
              onChange={(e) => setLang(e.target.value)}
            >
              <option value="en">EN</option>
              <option value="zh">中文</option>
            </select>
          </div>
          <div className="text-xs text-muted-foreground">
            → {describeCron(buildCron(freq, time))}
          </div>
          <Button size="sm" disabled={busy || !ticker} onClick={submit}>
            {t('analyze.scheduleDialog.create')}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
