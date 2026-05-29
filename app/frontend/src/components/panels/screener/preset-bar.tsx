import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { createPreset, listPresets } from '@/services/screener-service';
import { ChipValues, Market, ScreenerPreset } from '@/types/screener';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { PresetManager } from './preset-manager';

interface PresetBarProps {
  market: Market;
  filters: ChipValues;
  sortBy: string;
  sortDir: 'asc' | 'desc';
  onLoad: (p: ScreenerPreset) => void;
  onManage?: () => void;
}

export function PresetBar({ market, filters, sortBy, sortDir, onLoad, onManage }: PresetBarProps) {
  const { t } = useTranslation();
  const [presets, setPresets] = useState<ScreenerPreset[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);
  const [mgrOpen, setMgrOpen] = useState(false);

  const loadList = () => {
    listPresets()
      .then(setPresets)
      .catch(console.error);
  };

  useEffect(() => {
    loadList();
  }, []);

  const handleSelect = (val: string) => {
    setSelectedId(val);
    const preset = presets.find((p) => String(p.id) === val);
    if (preset) onLoad(preset);
  };

  const handleSave = async () => {
    const name = saveName.trim();
    if (!name) return;
    setSaving(true);
    try {
      await createPreset({
        name,
        market: market === 'ALL' ? null : market,
        filters,
        sort_by: sortBy,
        sort_dir: sortDir,
      });
      toast.success(t('screener.presets.saved', 'Preset saved'));
      setSaveName('');
      setSaveOpen(false);
      loadList();
    } catch (err) {
      toast.error(t('screener.presets.save_error', 'Failed to save preset'));
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <Select value={selectedId} onValueChange={handleSelect}>
        <SelectTrigger className="h-7 w-44 text-xs">
          <SelectValue placeholder={t('screener.presets.select_placeholder', 'Load preset…')} />
        </SelectTrigger>
        <SelectContent>
          {presets.length === 0 && (
            <SelectItem value="__none__" disabled>
              {t('screener.presets.empty', 'No presets')}
            </SelectItem>
          )}
          {presets.map((p) => (
            <SelectItem key={p.id} value={String(p.id)}>
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Popover open={saveOpen} onOpenChange={setSaveOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" size="sm" className="h-7 text-xs px-2">
            {t('screener.presets.save', 'Save preset')}
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-56 p-3 space-y-2">
          <div className="text-xs font-medium">
            {t('screener.presets.save_title', 'Save current filters as preset')}
          </div>
          <Input
            className="h-7 text-xs"
            placeholder={t('screener.presets.name_placeholder', 'Preset name')}
            value={saveName}
            onChange={(e) => setSaveName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
          />
          <Button
            size="sm"
            className="w-full h-7 text-xs"
            disabled={!saveName.trim() || saving}
            onClick={handleSave}
          >
            {saving
              ? t('screener.presets.saving', 'Saving…')
              : t('screener.presets.save_confirm', 'Save')}
          </Button>
        </PopoverContent>
      </Popover>

      <Button
        variant="ghost"
        size="sm"
        className="h-7 text-xs px-2"
        onClick={() => { setMgrOpen(true); onManage?.(); }}
      >
        {t('screener.presets.manage', 'Manage')}
      </Button>

      <PresetManager
        open={mgrOpen}
        onOpenChange={setMgrOpen}
        onChanged={loadList}
      />
    </div>
  );
}
