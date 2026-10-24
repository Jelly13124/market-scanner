// Flow-style module picker for the SOP sections. Vertical pipeline
// metaphor — each section is a card with a checkbox; thin vertical
// line connects them. NOT React Flow nodes (overkill for this scope).

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { cn } from '@/lib/utils';
import {
  SECTION_LABELS, SECTION_ORDER, REQUIRED_SECTIONS,
} from '@/types/analyze';

interface ModulePickerProps {
  included: Set<string>;
  onToggle: (sectionName: string) => void;
  onPreset: (preset: 'all' | 'required') => void;
}

export function ModulePicker({ included, onToggle, onPreset }: ModulePickerProps) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase text-muted-foreground">
          SOP sections to include
        </span>
        <div className="flex gap-1">
          <Button
            variant="ghost" size="sm"
            onClick={() => onPreset('all')}
            className="text-xs h-6 px-2"
          >
            All on
          </Button>
          <Button
            variant="ghost" size="sm"
            onClick={() => onPreset('required')}
            className="text-xs h-6 px-2"
          >
            Required only
          </Button>
        </div>
      </div>

      <div className="relative pl-4">
        {/* Vertical pipeline line */}
        <div className="absolute left-1.5 top-2 bottom-2 w-px bg-border" />

        {SECTION_ORDER.map((name, idx) => {
          const checked = included.has(name);
          const isRequired = REQUIRED_SECTIONS.includes(name);
          return (
            <div
              key={name}
              className={cn(
                'relative flex items-center gap-2 py-1.5 pl-3',
                idx > 0 && 'mt-0.5',
              )}
            >
              {/* Node dot */}
              <div
                className={cn(
                  'absolute left-[-10px] top-1/2 -translate-y-1/2',
                  'w-2 h-2 rounded-full border',
                  checked ? 'bg-primary border-primary' : 'bg-background border-muted-foreground',
                )}
              />
              <Checkbox
                id={`sec-${name}`}
                checked={checked}
                onCheckedChange={() => onToggle(name)}
              />
              <label
                htmlFor={`sec-${name}`}
                className="text-sm cursor-pointer flex-1 select-none"
              >
                {SECTION_LABELS[name] || name}
                {isRequired && (
                  <span className="ml-2 text-[10px] uppercase text-muted-foreground">
                    required
                  </span>
                )}
              </label>
            </div>
          );
        })}
      </div>
    </div>
  );
}
