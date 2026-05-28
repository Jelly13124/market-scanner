import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { ColumnMetadata } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface RangeChipProps {
  meta: ColumnMetadata;
  minValue: number | null;
  maxValue: number | null;
  onChange: (min: number | null, max: number | null) => void;
}

export function RangeChip({ meta, minValue, maxValue, onChange }: RangeChipProps) {
  const { i18n } = useTranslation();
  const label = i18n.language === 'zh' ? meta.label_zh : meta.label_en;
  const active = minValue !== null || maxValue !== null;

  const labelSummary = active
    ? `${label} ${minValue ?? '...'}-${maxValue ?? '...'}`
    : label;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('rounded-full px-3 h-8 text-xs', active && 'border-primary text-primary')}
        >
          {labelSummary}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3 space-y-2">
        <div className="text-xs font-medium">{label}</div>
        <div className="flex gap-2 items-center">
          <Input
            type="number"
            step={meta.step ?? 1}
            value={minValue ?? ''}
            placeholder="Min"
            onChange={(e) =>
              onChange(e.target.value === '' ? null : Number(e.target.value), maxValue)
            }
            className="h-8 text-xs"
          />
          <span className="text-muted-foreground">—</span>
          <Input
            type="number"
            step={meta.step ?? 1}
            value={maxValue ?? ''}
            placeholder="Max"
            onChange={(e) =>
              onChange(minValue, e.target.value === '' ? null : Number(e.target.value))
            }
            className="h-8 text-xs"
          />
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full h-7 text-xs"
          onClick={() => onChange(null, null)}
        >
          Clear
        </Button>
      </PopoverContent>
    </Popover>
  );
}
