// Phase 6F-2: left column of the Lab panel — lists user strategies +
// New / Delete affordances.

import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { strategyService } from '@/services/strategy-service';
import type { StrategyResponse } from '@/types/strategy';
import { Plus, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

interface Props {
  selectedId: number | null;
  onSelect: (id: number | null) => void;
}

export function StrategyList({ selectedId, onSelect }: Props) {
  const [items, setItems] = useState<StrategyResponse[]>([]);
  const [, setLoading] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const { t } = useTranslation();

  const reload = useCallback(() => {
    setLoading(true);
    strategyService.list()
      .then(setItems)
      .catch((e: Error) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  async function handleCreate() {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await strategyService.create({ name, description: '' });
      setCreateOpen(false);
      setNewName('');
      reload();
      onSelect(created.id);
    } catch (e) { toast.error((e as Error).message); }
  }

  async function handleDelete(id: number, name: string) {
    if (!confirm(t('lab.deleteConfirm', { name }))) return;
    try {
      await strategyService.delete(id);
      if (selectedId === id) onSelect(null);
      reload();
    } catch (e) { toast.error((e as Error).message); }
  }

  return (
    <div className="border-r h-full min-h-0 min-w-0 flex flex-col">
      <div className="px-3 py-2 border-b flex items-center justify-between">
        <span className="text-xs font-medium uppercase">{t('lab.strategies')}</span>
        <Button variant="ghost" size="sm" onClick={() => setCreateOpen(true)}>
          <Plus className="size-3" />
        </Button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto divide-y">
        {items.length === 0 ? (
          <div className="p-3 text-xs text-muted-foreground">
            {t('lab.noStrategies')}
          </div>
        ) : (
          items.map((s) => (
            <div
              key={s.id}
              className={cn(
                'px-3 py-2 flex items-center gap-2 text-sm cursor-pointer hover:bg-accent/40',
                s.id === selectedId && 'bg-accent/30',
              )}
              onClick={() => onSelect(s.id)}
            >
              <span className="flex-1 truncate">{s.name}</span>
              <span className="text-[10px] text-muted-foreground">v{s.version}</span>
              <Button
                variant="ghost" size="icon"
                className="h-5 w-5 text-muted-foreground hover:text-destructive"
                onClick={(e) => { e.stopPropagation(); handleDelete(s.id, s.name); }}
              >
                <Trash2 className="size-3" />
              </Button>
            </div>
          ))
        )}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>{t('lab.newStrategy')}</DialogTitle></DialogHeader>
          <Input
            value={newName} onChange={(e) => setNewName(e.target.value)}
            placeholder={t('lab.strategyName')}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
          />
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>{t('common.cancel')}</Button>
            <Button onClick={handleCreate}>{t('common.create')}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
