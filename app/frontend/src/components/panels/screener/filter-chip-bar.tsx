import { ColumnMetadata, Market, ChipValues } from '@/types/screener';
import { RangeChip } from './chips/range-chip';
import { MultiSelectChip } from './chips/multi-select-chip';
import { DateRangeChip } from './chips/date-range-chip';

interface FilterChipBarProps {
  columns: ColumnMetadata[];
  values: ChipValues;
  market: Market;
  onChange: (next: ChipValues) => void;
}

export function FilterChipBar({ columns, values, market, onChange }: FilterChipBarProps) {
  const updateOne = (patch: ChipValues) => onChange({ ...values, ...patch });

  return (
    <div className="flex flex-wrap gap-2 py-2 px-2">
      {columns.map((meta) => {
        if (meta.kind === 'range' && meta.filter_min && meta.filter_max) {
          const minKey = meta.filter_min;
          const maxKey = meta.filter_max;
          return (
            <RangeChip
              key={meta.slug}
              meta={meta}
              minValue={(values[minKey] as number | null) ?? null}
              maxValue={(values[maxKey] as number | null) ?? null}
              onChange={(min, max) => updateOne({ [minKey]: min, [maxKey]: max })}
            />
          );
        }
        if (meta.kind === 'multi_select' && meta.filter_key) {
          const key = meta.filter_key;
          return (
            <MultiSelectChip
              key={meta.slug}
              meta={meta}
              market={market}
              selectedValues={(values[key] as string[]) ?? []}
              onChange={(vals) => updateOne({ [key]: vals })}
            />
          );
        }
        if (meta.kind === 'date_range' && meta.filter_after && meta.filter_before) {
          const a = meta.filter_after;
          const b = meta.filter_before;
          return (
            <DateRangeChip
              key={meta.slug}
              meta={meta}
              afterDate={(values[a] as string | null) ?? null}
              beforeDate={(values[b] as string | null) ?? null}
              onChange={(after, before) => updateOne({ [a]: after, [b]: before })}
            />
          );
        }
        return null;
      })}
    </div>
  );
}
