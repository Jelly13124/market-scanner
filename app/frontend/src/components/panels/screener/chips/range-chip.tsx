import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';
import { ColumnMetadata } from '@/types/screener';
import { useTranslation } from 'react-i18next';

interface RangeChipProps {
  meta: ColumnMetadata;
  // Stored as the RAW query value: fractions for percent columns
  // (0.03 = 3%), raw dollars for market cap (3.2e12).
  minValue: number | null;
  maxValue: number | null;
  onChange: (min: number | null, max: number | null) => void;
}

// The DB/API stores percent metrics as fractions (change_pct 0.0384 = 3.84%)
// and market cap in raw currency (5.19e12). Users think in percent (3.84) and
// billions (5190). These helpers translate between what the user types and the
// raw query value so a "Chg % 1–10" filter actually matches 1%–10%.
function unitScale(format: string | undefined): number {
  if (format === 'percent') return 100; // raw * 100 = percent shown to user
  if (format === 'abbreviated_currency') return 1 / 1e9; // raw / 1e9 = billions
  return 1;
}

function toDisplay(raw: number | null, format: string | undefined): number | '' {
  if (raw === null) return '';
  const scaled = raw * unitScale(format);
  // Trim float noise (0.0384 * 100 = 3.8400000000000003).
  return Math.round(scaled * 1e6) / 1e6;
}

function fromInput(s: string, format: string | undefined): number | null {
  if (s === '') return null;
  const n = Number(s);
  if (!isFinite(n)) return null;
  return n / unitScale(format);
}

function unitSuffix(format: string | undefined): string {
  if (format === 'percent') return '%';
  if (format === 'abbreviated_currency') return 'B';
  return '';
}

export function RangeChip({ meta, minValue, maxValue, onChange }: RangeChipProps) {
  const { i18n } = useTranslation();
  const label = i18n.language === 'zh' ? meta.label_zh : meta.label_en;
  const active = minValue !== null || maxValue !== null;
  const suffix = unitSuffix(meta.format);

  const dispMin = toDisplay(minValue, meta.format);
  const dispMax = toDisplay(maxValue, meta.format);

  const labelSummary = active
    ? `${label} ${dispMin === '' ? '...' : dispMin}-${dispMax === '' ? '...' : dispMax}${suffix}`
    : label;

  // Step is expressed in user units (percent/billions), not raw units.
  const step = meta.format === 'percent' ? 0.5
    : meta.format === 'abbreviated_currency' ? 1
    : meta.step ?? 1;

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
        <div className="text-xs font-medium">
          {label}{suffix ? ` (${suffix})` : ''}
        </div>
        <div className="flex gap-2 items-center">
          <Input
            type="number"
            step={step}
            value={dispMin}
            placeholder="Min"
            onChange={(e) => onChange(fromInput(e.target.value, meta.format), maxValue)}
            className="h-8 text-xs"
          />
          <span className="text-muted-foreground">—</span>
          <Input
            type="number"
            step={step}
            value={dispMax}
            placeholder="Max"
            onChange={(e) => onChange(minValue, fromInput(e.target.value, meta.format))}
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
