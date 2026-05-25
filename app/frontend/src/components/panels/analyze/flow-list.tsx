// Top bar of the Analyze panel — list/load/save/new for AnalyzeFlow
// templates. Hands off all canvas work to the parent via the supplied
// callbacks; this component only owns its own form state + REST calls.

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { analyzeFlowService } from '@/services/analyze-flow-service';
import type { AnalyzeFlowResponse } from '@/types/analyze-flow';
import { FileX, FolderOpen, Plus, Save, Trash2 } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

export interface FlowListProps {
  /** Current canvas serialized — what `Save current as...` posts. */
  getCurrentConfig: () => {
    included_sections: string[];
    persona_overrides: Record<string, string>;
  };
  /** Called when user picks a saved flow to load. */
  onLoad: (flow: AnalyzeFlowResponse) => void;
  /** Called when user picks New blank → clear canvas. */
  onNewBlank: () => void;
  /** When set, save updates this id instead of creating new. */
  loadedFlowId: number | null;
  onLoadedFlowIdChange: (id: number | null) => void;
}

export function FlowList({
  getCurrentConfig, onLoad, onNewBlank,
  loadedFlowId, onLoadedFlowIdChange,
}: FlowListProps) {
  const [flows, setFlows] = useState<AnalyzeFlowResponse[]>([]);
  const [selectedId, setSelectedId] = useState<number | ''>('');
  const [savingName, setSavingName] = useState<string>('');
  const [showSave, setShowSave] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const rows = await analyzeFlowService.list();
      setFlows(rows);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  // Keep dropdown in sync when parent loads a flow programmatically
  useEffect(() => {
    if (loadedFlowId != null) setSelectedId(loadedFlowId);
  }, [loadedFlowId]);

  const handleLoad = useCallback(async () => {
    if (selectedId === '') return;
    try {
      const flow = await analyzeFlowService.get(Number(selectedId));
      onLoad(flow);
      onLoadedFlowIdChange(flow.id);
      toast.success(`Loaded "${flow.name}"`);
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [selectedId, onLoad, onLoadedFlowIdChange]);

  const handleSaveNew = useCallback(async () => {
    const name = savingName.trim();
    if (!name) {
      toast.error('Enter a name');
      return;
    }
    const cfg = getCurrentConfig();
    try {
      const created = await analyzeFlowService.create({
        name,
        included_sections: cfg.included_sections,
        persona_overrides: Object.keys(cfg.persona_overrides).length
          ? cfg.persona_overrides
          : null,
        use_personas: Object.keys(cfg.persona_overrides).length > 0,
      });
      toast.success(`Saved "${created.name}"`);
      setSavingName('');
      setShowSave(false);
      onLoadedFlowIdChange(created.id);
      setSelectedId(created.id);
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [savingName, getCurrentConfig, onLoadedFlowIdChange, refresh]);

  const handleUpdateCurrent = useCallback(async () => {
    if (loadedFlowId == null) return;
    const cfg = getCurrentConfig();
    try {
      await analyzeFlowService.update(loadedFlowId, {
        included_sections: cfg.included_sections,
        persona_overrides: Object.keys(cfg.persona_overrides).length
          ? cfg.persona_overrides
          : null,
      });
      toast.success('Saved');
      await refresh();
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [loadedFlowId, getCurrentConfig, refresh]);

  const handleDelete = useCallback(async () => {
    if (selectedId === '') return;
    if (!confirm('Delete this saved flow?')) return;
    try {
      await analyzeFlowService.delete(Number(selectedId));
      if (loadedFlowId === Number(selectedId)) onLoadedFlowIdChange(null);
      setSelectedId('');
      await refresh();
      toast.success('Deleted');
    } catch (e) {
      toast.error((e as Error).message);
    }
  }, [selectedId, loadedFlowId, onLoadedFlowIdChange, refresh]);

  const handleNewBlank = useCallback(() => {
    onNewBlank();
    onLoadedFlowIdChange(null);
    setSelectedId('');
  }, [onNewBlank, onLoadedFlowIdChange]);

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <select
        value={selectedId === '' ? '' : String(selectedId)}
        onChange={(e) =>
          setSelectedId(e.target.value === '' ? '' : Number(e.target.value))
        }
        className="h-7 text-xs border rounded bg-background px-1 min-w-[180px]"
        title="Saved AnalyzeFlow templates"
      >
        <option value="">— Saved templates —</option>
        {flows.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name} ({f.included_sections.length})
          </option>
        ))}
      </select>
      <Button
        variant="outline" size="sm" className="h-7 px-2"
        disabled={selectedId === ''}
        onClick={handleLoad}
        title="Load selected"
      >
        <FolderOpen className="size-3" />
      </Button>
      <Button
        variant="outline" size="sm" className="h-7 px-2"
        disabled={selectedId === ''}
        onClick={handleDelete}
        title="Delete selected"
      >
        <Trash2 className="size-3" />
      </Button>
      {loadedFlowId != null && (
        <Button
          variant="outline" size="sm" className="h-7 px-2"
          onClick={handleUpdateCurrent}
          title={`Update saved flow #${loadedFlowId}`}
        >
          <Save className="size-3 mr-1" />
          Save
        </Button>
      )}
      <Button
        variant="outline" size="sm" className="h-7 px-2"
        onClick={() => setShowSave((s) => !s)}
        title="Save current canvas as new template"
      >
        <Save className="size-3 mr-1" />
        Save as…
      </Button>
      <Button
        variant="outline" size="sm" className="h-7 px-2"
        onClick={handleNewBlank}
        title="Reset to default template"
      >
        <FileX className="size-3 mr-1" />
        New
      </Button>

      {showSave && (
        <div className="flex gap-1 items-center">
          <Input
            value={savingName}
            onChange={(e) => setSavingName(e.target.value)}
            placeholder="Template name"
            className="h-7 text-xs w-48"
            onKeyDown={(e) => { if (e.key === 'Enter') handleSaveNew(); }}
            autoFocus
          />
          <Button size="sm" className="h-7" onClick={handleSaveNew}>
            <Plus className="size-3 mr-1" />
            Create
          </Button>
        </div>
      )}
    </div>
  );
}
