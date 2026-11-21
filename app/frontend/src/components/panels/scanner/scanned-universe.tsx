import { getUniverseSnapshot } from '@/services/screener-service';
import type { UniverseSnapshot } from '@/types/screener';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

export function ScannedUniverse({ snapshotId }: { snapshotId: number }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [run, setRun] = useState<UniverseSnapshot | null>(null);
  const [selection, setSelection] = useState<UniverseSnapshot | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    let active = true;
    setError('');
    async function load() {
      const snapshot = await getUniverseSnapshot(snapshotId);
      if (!active) return;
      setRun(snapshot);
      if (snapshot.source_snapshot_id != null) {
        const source = await getUniverseSnapshot(snapshot.source_snapshot_id);
        if (active) setSelection(source);
      }
    }
    load().catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [open, snapshotId]);

  return (
    <details className="mb-3 text-sm" onToggle={e => setOpen(e.currentTarget.open)}>
      <summary className="cursor-pointer font-medium">{t('scanner.viewScannedUniverse')}</summary>
      <div className="mt-2 space-y-2 border-l pl-3">
        {error && <p role="alert">{error}</p>}
        {!run && !error && <p>{t('scanner.loadingUniverse')}</p>}
        {run && <p className="max-h-36 overflow-auto">{run.tickers.join(', ')}</p>}
        {selection && (
          <>
            <p className="font-medium">{t('scanner.sourceSelection')} · {selection.screener_snapshot_date}</p>
            <p className="max-h-28 overflow-auto">{selection.tickers.join(', ')}</p>
            {Object.entries(selection.filters ?? {}).map(([name, value]) =>
              <div key={name}><span className="text-muted-foreground">{name}</span> · {Array.isArray(value) ? value.join(', ') : value}</div>
            )}
          </>
        )}
      </div>
    </details>
  );
}
