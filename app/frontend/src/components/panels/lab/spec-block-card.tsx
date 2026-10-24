// Phase 6F-3: one strategy block rendered as a labeled card with
// color-coded category badge + key=value param chips.

import { Badge } from '@/components/ui/badge';

interface Props {
  block: Record<string, unknown>;
  category: 'entry' | 'exit' | 'sizing' | 'filter';
}

export function SpecBlockCard({ block, category }: Props) {
  const type = (block.type as string) || 'unknown';
  const params = Object.entries(block).filter(([k]) => k !== 'type');
  const catColor = {
    entry: 'bg-green-50 text-green-800 border-green-200',
    exit: 'bg-red-50 text-red-800 border-red-200',
    sizing: 'bg-blue-50 text-blue-800 border-blue-200',
    filter: 'bg-purple-50 text-purple-800 border-purple-200',
  }[category];

  return (
    <div className={`border rounded p-2 text-xs ${catColor}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="font-bold uppercase">{type}</span>
        <Badge variant="outline" className="text-[10px]">{category}</Badge>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        {params.map(([k, v]) => (
          <span key={k}>
            <span className="text-muted-foreground">{k}=</span>
            <span className="font-mono">{String(v)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
