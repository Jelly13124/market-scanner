// Phase 6F-3: modal textarea for manual JSON edit of a StrategySpec.
// Client-side parse for syntax; backend validates the rest.

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import type { StrategySpec } from '@/types/strategy';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

interface Props {
  open: boolean;
  initialSpec: StrategySpec;
  onCancel: () => void;
  onSave: (newSpec: StrategySpec) => Promise<void>;
}

export function SpecJsonEditor({ open, initialSpec, onCancel, onSave }: Props) {
  const [text, setText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const { t } = useTranslation();

  useEffect(() => {
    if (open) {
      setText(JSON.stringify(initialSpec, null, 2));
      setError(null);
    }
  }, [open, initialSpec]);

  async function handleSave() {
    let parsed: StrategySpec;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      setError(`Invalid JSON: ${(e as Error).message}`);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(parsed);
    } catch (e) {
      setError((e as Error).message);
    } finally { setSaving(false); }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t('lab.specJson.title')}</DialogTitle>
          <DialogDescription>
            {t('lab.specJson.description')}
          </DialogDescription>
        </DialogHeader>
        <textarea
          value={text} onChange={(e) => setText(e.target.value)}
          className="w-full h-96 font-mono text-xs p-2 border rounded"
          spellCheck={false}
        />
        {error && <div className="text-xs text-red-600 mt-2">{error}</div>}
        <DialogFooter>
          <Button variant="ghost" onClick={onCancel} disabled={saving}>{t('common.cancel')}</Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? t('lab.specJson.saving') : t('common.save')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
