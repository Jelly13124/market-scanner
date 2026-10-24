import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  buildCron,
  describeCron,
  reportSchedulesService,
  type Frequency,
  type ReportSchedule,
} from '@/services/report-schedules-api';
import { CalendarClock, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

export function ReportSchedulesSettings() {
  const [schedules, setSchedules] = useState<ReportSchedule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // create form
  const [tickers, setTickers] = useState('');
  const [freq, setFreq] = useState<Frequency>('weekdays');
  const [time, setTime] = useState('09:30');
  const [lang, setLang] = useState('en');

  const load = async () => {
    setLoading(true);
    try {
      setSchedules(await reportSchedulesService.list());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const create = async () => {
    const list = tickers
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!list.length) {
      setError('Enter at least one ticker');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await reportSchedulesService.create({
        tickers: list,
        cron_expr: buildCron(freq, time),
        report_language: lang,
      });
      setTickers('');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (s: ReportSchedule) => {
    setError(null);
    try {
      await reportSchedulesService.update(s.id, { is_enabled: !s.is_enabled });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async (id: number) => {
    setError(null);
    try {
      await reportSchedulesService.remove(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-primary mb-2">Scheduled reports</h2>
        <p className="text-sm text-muted-foreground">
          Auto-run analysis for a set of tickers on a schedule and email each report to your
          verified addresses (Settings → Report emails). Times are US Eastern. Needs an LLM API key
          and at least one verified email.
        </p>
      </div>

      {error && (
        <Card className="bg-red-500/5 border-red-500/20">
          <CardContent className="p-4 text-xs text-red-500">{error}</CardContent>
        </Card>
      )}

      <Card className="bg-panel border-gray-700 dark:border-gray-700">
        <CardHeader>
          <CardTitle className="text-lg font-medium text-primary flex items-center gap-2">
            <CalendarClock className="h-4 w-4" /> Your schedules
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : schedules.length === 0 ? (
            <div className="text-sm text-muted-foreground">No schedules yet.</div>
          ) : (
            schedules.map((s) => (
              <div key={s.id} className="flex items-center gap-3 border-b pb-2 last:border-0">
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{s.tickers.join(', ')}</div>
                  <div className="text-xs text-muted-foreground">
                    {describeCron(s.cron_expr)} · {s.report_language === 'zh' ? '中文' : 'EN'}
                    {s.last_run_at && ` · last ${new Date(s.last_run_at).toLocaleString()}`}
                  </div>
                </div>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => toggle(s)}>
                  {s.is_enabled ? 'Enabled' : 'Paused'}
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 hover:bg-red-500/10 hover:text-red-500"
                  onClick={() => remove(s.id)}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))
          )}
        </CardContent>
      </Card>

      <Card className="bg-panel border-gray-700 dark:border-gray-700">
        <CardHeader>
          <CardTitle className="text-lg font-medium text-primary">New schedule</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <label className="text-xs text-muted-foreground">Tickers (comma or space separated)</label>
            <Input
              placeholder="NVDA, AAPL, MSFT"
              value={tickers}
              onChange={(e) => setTickers(e.target.value)}
            />
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
              value={freq}
              onChange={(e) => setFreq(e.target.value as Frequency)}
            >
              <option value="daily">Daily</option>
              <option value="weekdays">Weekdays</option>
              <option value="weekly">Weekly (Mon)</option>
            </select>
            <Input type="time" className="w-32" value={time} onChange={(e) => setTime(e.target.value)} />
            <select
              className="rounded-md border bg-background px-2 py-1.5 text-sm"
              value={lang}
              onChange={(e) => setLang(e.target.value)}
            >
              <option value="en">EN report</option>
              <option value="zh">中文报告</option>
            </select>
            <span className="text-xs text-muted-foreground">→ {describeCron(buildCron(freq, time))}</span>
          </div>
          <Button size="sm" disabled={busy || !tickers.trim()} onClick={create}>
            {busy ? 'Creating…' : 'Create schedule'}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
