import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { reportRecipientsService, type ReportRecipient } from '@/services/report-recipients-api';
import { CheckCircle2, Clock, Mail, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

const MAX = 3;

export function ReportRecipientsSettings() {
  const [recipients, setRecipients] = useState<ReportRecipient[]>([]);
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      setRecipients(await reportRecipientsService.list());
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

  const add = async () => {
    const v = email.trim();
    if (!v) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await reportRecipientsService.add(v);
      setEmail('');
      setNotice(`Verification email sent to ${v}. Click the link in that inbox to confirm.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const resend = async (id: number, addr: string) => {
    setError(null);
    setNotice(null);
    try {
      await reportRecipientsService.resend(id);
      setNotice(`Verification email re-sent to ${addr}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const remove = async (id: number) => {
    setError(null);
    setNotice(null);
    try {
      await reportRecipientsService.remove(id);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const atMax = recipients.length >= MAX;

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-primary mb-2">Report emails</h2>
        <p className="text-sm text-muted-foreground">
          Bind up to {MAX} email addresses to receive your reports. Each must be verified — we
          email a confirmation link, and only verified addresses receive reports.
        </p>
      </div>

      {error && (
        <Card className="bg-red-500/5 border-red-500/20">
          <CardContent className="p-4 text-xs text-red-500">{error}</CardContent>
        </Card>
      )}
      {notice && (
        <Card className="bg-emerald-500/5 border-emerald-500/20">
          <CardContent className="p-4 text-xs text-emerald-600 dark:text-emerald-400">{notice}</CardContent>
        </Card>
      )}

      <Card className="bg-panel border-gray-700 dark:border-gray-700">
        <CardHeader>
          <CardTitle className="text-lg font-medium text-primary flex items-center gap-2">
            <Mail className="h-4 w-4" /> Recipient addresses
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {loading ? (
            <div className="text-sm text-muted-foreground">Loading…</div>
          ) : recipients.length === 0 ? (
            <div className="text-sm text-muted-foreground">No report emails yet.</div>
          ) : (
            <div className="space-y-2">
              {recipients.map((r) => (
                <div key={r.id} className="flex items-center gap-2">
                  <span className="text-sm flex-1 truncate">{r.email}</span>
                  {r.is_verified ? (
                    <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Verified
                    </span>
                  ) : (
                    <>
                      <span className="inline-flex items-center gap-1 text-xs text-amber-500">
                        <Clock className="h-3.5 w-3.5" /> Pending
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-7 text-xs"
                        onClick={() => resend(r.id, r.email)}
                      >
                        Resend
                      </Button>
                    </>
                  )}
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 hover:bg-red-500/10 hover:text-red-500"
                    onClick={() => remove(r.id)}
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {!atMax ? (
            <div className="flex items-center gap-2 pt-2">
              <Input
                type="email"
                placeholder="friend@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') add();
                }}
              />
              <Button size="sm" disabled={busy || !email.trim()} onClick={add}>
                {busy ? 'Adding…' : 'Add + verify'}
              </Button>
            </div>
          ) : (
            <div className="text-xs text-muted-foreground">Maximum of {MAX} report emails reached.</div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
