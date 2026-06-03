import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useAuth } from '@/contexts/auth-context';
import { Clock } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

// Common IANA zones offered in the dropdown. The backend validates against the
// full host tz database, so this list is just a convenience shortlist.
const ZONES = [
  'America/New_York',
  'America/Los_Angeles',
  'America/Chicago',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Australia/Sydney',
  'UTC',
];

export function TimezoneSettings() {
  const { user, updateTimezone } = useAuth();
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const current = user?.timezone ?? 'America/New_York';

  const onChange = async (tz: string) => {
    if (tz === current) return;
    setBusy(true);
    setError(null);
    try {
      await updateTimezone(tz);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-primary mb-2">{t('settings.timezone')}</h2>
        <p className="text-sm text-muted-foreground">{t('settings.timezoneDesc')}</p>
      </div>

      {error && (
        <Card className="bg-red-500/5 border-red-500/20">
          <CardContent className="p-4 text-xs text-red-500">{error}</CardContent>
        </Card>
      )}

      <Card className="bg-panel border-gray-700 dark:border-gray-700">
        <CardHeader>
          <CardTitle className="text-lg font-medium text-primary flex items-center gap-2">
            <Clock className="h-4 w-4" /> {t('settings.timezone')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">{t('settings.timezoneHint')}</p>
          <select
            className="rounded-md border bg-background px-2 py-1.5 text-sm"
            value={ZONES.includes(current) ? current : 'America/New_York'}
            disabled={busy}
            onChange={(e) => onChange(e.target.value)}
          >
            {ZONES.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </CardContent>
      </Card>
    </div>
  );
}
