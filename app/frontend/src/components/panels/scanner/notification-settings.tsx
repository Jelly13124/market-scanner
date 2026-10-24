// NotificationSettings — manage who gets pinged when the daily pipeline
// finishes. Sits under the scanner panel alongside AgentRunsList.
//
// One row per subscription (email or webhook), each with:
//   * enable/disable toggle
//   * test-send button (works even when disabled — useful for "does my
//     Resend config work?" sanity checks before flipping the switch)
//   * delete
// + an "Add" button opening a dialog to create a new subscription.

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { notificationService } from '@/services/notification-service';
import type {
  NotificationChannel,
  SubscriptionResponse,
} from '@/types/notification';
import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  Mail,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Webhook,
} from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';


// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export function NotificationSettings() {
  const [subs, setSubs] = useState<SubscriptionResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const { t } = useTranslation();
  // Per-sub transient state (test-send result, delete confirmation).
  const [busyId, setBusyId] = useState<number | null>(null);
  const [lastTest, setLastTest] = useState<Record<number, { ok: boolean; message: string }>>({});

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    notificationService
      .list()
      .then(setSubs)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const onToggle = async (sub: SubscriptionResponse, enabled: boolean) => {
    setBusyId(sub.id);
    try {
      const updated = await notificationService.update(sub.id, { enabled });
      setSubs((prev) => prev.map((s) => (s.id === sub.id ? updated : s)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const onTest = async (sub: SubscriptionResponse) => {
    setBusyId(sub.id);
    try {
      const result = await notificationService.sendTest(sub.id);
      setLastTest((prev) => ({
        ...prev,
        [sub.id]: {
          ok: result.status === 'ok',
          message: result.status === 'ok'
            ? `delivered in ${result.latency_ms ?? '?'}ms (HTTP ${result.http_code ?? '?'})`
            : (result.error_text ?? 'unknown error'),
        },
      }));
    } catch (e) {
      setLastTest((prev) => ({
        ...prev,
        [sub.id]: { ok: false, message: (e as Error).message },
      }));
    } finally {
      setBusyId(null);
    }
  };

  const onDelete = async (sub: SubscriptionResponse) => {
    if (!confirm(`Delete notification "${sub.label || sub.target}"?`)) return;
    setBusyId(sub.id);
    try {
      await notificationService.remove(sub.id);
      setSubs((prev) => prev.filter((s) => s.id !== sub.id));
      setLastTest((prev) => {
        const next = { ...prev };
        delete next[sub.id];
        return next;
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="border rounded">
      <div className="flex items-center justify-between px-3 py-1.5 border-b bg-accent/30">
        <span className="text-xs font-medium">{t('scanner.notifications.title')}</span>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setAdding(true)}
            title={t('scanner.notifications.addSub')}
          >
            <Plus className="size-3" />
            <span className="text-xs">{t('common.add')}</span>
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={reload}
            disabled={loading}
            title={t('common.refresh')}
          >
            <RefreshCw className={cn('size-3', loading && 'animate-spin')} />
          </Button>
        </div>
      </div>

      {error && (
        <div className="text-xs text-red-600 border-b border-red-200 p-2 bg-red-50">
          {error}
        </div>
      )}

      {!loading && subs.length === 0 && (
        <div className="text-xs text-muted-foreground px-3 py-3 text-center">
          No subscriptions yet — add one to receive an email or webhook ping
          when the daily pipeline finishes.
        </div>
      )}

      <div className="divide-y">
        {subs.map((sub) => (
          <SubscriptionRow
            key={sub.id}
            sub={sub}
            busy={busyId === sub.id}
            lastTest={lastTest[sub.id]}
            onToggle={(enabled) => onToggle(sub, enabled)}
            onTest={() => onTest(sub)}
            onDelete={() => onDelete(sub)}
          />
        ))}
      </div>

      {adding && (
        <AddSubscriptionDialog
          open={adding}
          onOpenChange={setAdding}
          onCreated={(s) => {
            setSubs((prev) => [s, ...prev]);
            setAdding(false);
          }}
        />
      )}
    </div>
  );
}


// ---------------------------------------------------------------------------
// One subscription row
// ---------------------------------------------------------------------------

interface RowProps {
  sub: SubscriptionResponse;
  busy: boolean;
  lastTest?: { ok: boolean; message: string };
  onToggle: (enabled: boolean) => void;
  onTest: () => void;
  onDelete: () => void;
}

function SubscriptionRow({ sub, busy, lastTest, onToggle, onTest, onDelete }: RowProps) {
  const ChannelIcon = sub.channel === 'email' ? Mail : Webhook;
  const { t } = useTranslation();
  return (
    <div className="px-3 py-2 flex items-center gap-2 text-xs">
      <ChannelIcon className="size-4 shrink-0 text-muted-foreground" />

      {/* Enabled toggle (native checkbox — keeps deps slim) */}
      <input
        type="checkbox"
        checked={sub.enabled}
        onChange={(e) => onToggle(e.target.checked)}
        disabled={busy}
        title={sub.enabled ? 'enabled' : 'disabled'}
        className="size-3.5 shrink-0 cursor-pointer"
      />

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="font-medium truncate" title={sub.target}>
            {sub.label || sub.target}
          </span>
          {sub.label && (
            <span className="text-muted-foreground truncate text-[10px] font-mono">
              {sub.target}
            </span>
          )}
        </div>
        {lastTest && (
          <div className={cn(
            'flex items-center gap-1 mt-0.5 text-[10px]',
            lastTest.ok ? 'text-green-600' : 'text-red-600',
          )}>
            {lastTest.ok ? <CheckCircle2 className="size-3" /> : <AlertCircle className="size-3" />}
            {lastTest.message}
          </div>
        )}
      </div>

      <Button variant="ghost" size="sm" onClick={onTest} disabled={busy} title={t('scanner.notifications.sendTest')}>
        {busy ? <Loader2 className="size-3 animate-spin" /> : <Send className="size-3" />}
      </Button>
      <Button variant="ghost" size="sm" onClick={onDelete} disabled={busy} title={t('common.delete')}>
        <Trash2 className="size-3" />
      </Button>
    </div>
  );
}


// ---------------------------------------------------------------------------
// Add subscription dialog
// ---------------------------------------------------------------------------

interface AddDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (sub: SubscriptionResponse) => void;
}

function AddSubscriptionDialog({ open, onOpenChange, onCreated }: AddDialogProps) {
  const [channel, setChannel] = useState<NotificationChannel>('email');
  const [target, setTarget] = useState('');
  const [label, setLabel] = useState('');
  const [authHeader, setAuthHeader] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { t } = useTranslation();

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const created = await notificationService.create({
        channel,
        target: target.trim(),
        label: label.trim() || null,
        auth_header: channel === 'webhook' && authHeader.trim()
          ? authHeader.trim()
          : null,
        enabled: true,
      });
      onCreated(created);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('scanner.notifications.addDialog')}</DialogTitle>
          <DialogDescription>
            Send an HTML email (Resend) or POST a webhook when the daily
            pipeline completes.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium mb-1 block">{t('scanner.notifications.channel')}</label>
            <div className="flex gap-2">
              <label className="flex-1 border rounded p-2 cursor-pointer text-sm flex items-center gap-2">
                <input
                  type="radio"
                  value="email"
                  checked={channel === 'email'}
                  onChange={() => setChannel('email')}
                />
                <Mail className="size-4" /> Email
              </label>
              <label className="flex-1 border rounded p-2 cursor-pointer text-sm flex items-center gap-2">
                <input
                  type="radio"
                  value="webhook"
                  checked={channel === 'webhook'}
                  onChange={() => setChannel('webhook')}
                />
                <Webhook className="size-4" /> Webhook
              </label>
            </div>
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">
              {channel === 'email' ? 'Email address' : 'Webhook URL'}
            </label>
            <input
              className="w-full border rounded px-2 py-1.5 text-sm bg-background font-mono"
              placeholder={channel === 'email'
                ? 'you@example.com'
                : 'https://hooks.example.com/in/...'}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              disabled={submitting}
              autoFocus
            />
            {channel === 'email' && (
              <div className="text-[10px] text-muted-foreground mt-1">
                Sender goes through Resend. Without a verified domain, the
                sandbox sender can only deliver to the email registered on
                your Resend account.
              </div>
            )}
          </div>

          <div>
            <label className="text-sm font-medium mb-1 block">
              Label <span className="text-muted-foreground font-normal">(optional)</span>
            </label>
            <input
              className="w-full border rounded px-2 py-1.5 text-sm bg-background"
              placeholder="e.g. daily report, ops slack"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              disabled={submitting}
            />
          </div>

          {channel === 'webhook' && (
            <div>
              <label className="text-sm font-medium mb-1 block">
                Authorization header <span className="text-muted-foreground font-normal">(optional)</span>
              </label>
              <input
                className="w-full border rounded px-2 py-1.5 text-sm bg-background font-mono"
                placeholder="Bearer xxxxx"
                value={authHeader}
                onChange={(e) => setAuthHeader(e.target.value)}
                disabled={submitting}
              />
              <div className="text-[10px] text-muted-foreground mt-1">
                {t('scanner.notifications.headerValueHint')}
                Not shown back after save.
              </div>
            </div>
          )}

          {error && (
            <div className="text-sm text-red-600 border border-red-200 rounded p-2 bg-red-50">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting || !target.trim()}>
            {submitting ? 'Saving…' : 'Add'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
