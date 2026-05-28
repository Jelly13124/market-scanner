import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ScrollArea } from '@/components/ui/scroll-area';
import { cn } from '@/lib/utils';
import { ChipOption, ColumnMetadata, Market } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface MultiSelectChipProps {
  meta: ColumnMetadata;
  selectedValues: string[];
  market: Market;
  onChange: (values: string[]) => void;
}

export function MultiSelectChip({ meta, selectedValues, market, onChange }: MultiSelectChipProps) {
  const { i18n } = useTranslation();
  const isZh = i18n.language === 'zh';
  const label = isZh ? meta.label_zh : meta.label_en;

  let options: ChipOption[] = [];
  if (meta.options) options = meta.options;
  else if (market === 'CN' && meta.options_cn) options = meta.options_cn;
  else if (meta.options_us) options = meta.options_us;

  const active = selectedValues.length > 0;
  const summary = active ? `${label} (${selectedValues.length})` : label;

  const toggle = (value: string) => {
    if (selectedValues.includes(value)) {
      onChange(selectedValues.filter((v) => v !== value));
    } else {
      onChange([...selectedValues, value]);
    }
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('rounded-full px-3 h-8 text-xs', active && 'border-primary text-primary')}
        >
          {summary}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-2">
        <ScrollArea className="h-56">
          <div className="space-y-1">
            {options.map((o) => (
              <label key={o.value} className="flex items-center gap-2 px-1 py-1 text-xs cursor-pointer hover:bg-muted">
                <Checkbox
                  checked={selectedValues.includes(o.value)}
                  onCheckedChange={() => toggle(o.value)}
                />
                {isZh ? o.label_zh : o.label_en}
              </label>
            ))}
          </div>
        </ScrollArea>
        {active && (
          <Button variant="ghost" size="sm" className="w-full h-7 text-xs mt-1"
                  onClick={() => onChange([])}>
            Clear
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}
