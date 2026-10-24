import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { ColumnMetadata } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface DateRangeChipProps {
  meta: ColumnMetadata;
  afterDate: string | null;
  beforeDate: string | null;
  onChange: (after: string | null, before: string | null) => void;
}

export function DateRangeChip({ meta, afterDate, beforeDate, onChange }: DateRangeChipProps) {
  const { i18n } = useTranslation();
  const label = i18n.language === 'zh' ? meta.label_zh : meta.label_en;
  const active = afterDate !== null || beforeDate !== null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className={cn('rounded-full px-3 h-8 text-xs', active && 'border-primary text-primary')}
        >
          {active ? `${label} ${afterDate ?? '...'} → ${beforeDate ?? '...'}` : label}
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-64 p-3 space-y-2">
        <div className="text-xs font-medium">{label}</div>
        <div className="flex gap-2 items-center">
          <Input
            type="date"
            value={afterDate ?? ''}
            onChange={(e) => onChange(e.target.value || null, beforeDate)}
            className="h-8 text-xs"
          />
          <span className="text-muted-foreground">→</span>
          <Input
            type="date"
            value={beforeDate ?? ''}
            onChange={(e) => onChange(afterDate, e.target.value || null)}
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
