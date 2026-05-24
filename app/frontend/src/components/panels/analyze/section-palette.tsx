// Sidebar list of all 16 SOP sections. Click '+' to add a node to the
// canvas. We deliberately mirror the existing right-sidebar pattern
// (right-sidebar.tsx) — click-from-palette, not HTML5 drag-drop.

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { Plus } from 'lucide-react';

import {
  REQUIRED_SECTIONS, SECTION_LABELS, SECTION_ORDER,
} from '@/types/analyze';

export interface SectionPaletteProps {
  /** Which section names are currently on the canvas (disables their '+'). */
  presentSections: Set<string>;
  /** Add a section node by name. */
  onAdd: (sectionName: string) => void;
}

export function SectionPalette({ presentSections, onAdd }: SectionPaletteProps) {
  return (
    <div className="h-full overflow-auto p-2 space-y-1">
      <div className="text-xs font-medium uppercase text-muted-foreground px-2 pt-1 pb-2">
        SOP sections
      </div>
      {SECTION_ORDER.map((name) => {
        const label = SECTION_LABELS[name] ?? name;
        const isPresent = presentSections.has(name);
        const isRequired = REQUIRED_SECTIONS.includes(name);
        return (
          <div
            key={name}
            className={cn(
              'flex items-center justify-between gap-2 px-2 py-1 rounded',
              'hover:bg-accent/40 transition-colors',
              isPresent && 'opacity-50',
            )}
          >
            <div className="flex flex-col min-w-0 flex-1">
              <span className="text-sm truncate" title={label}>{label}</span>
              {isRequired && (
                <span className="text-[10px] uppercase text-muted-foreground">
                  required
                </span>
              )}
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              disabled={isPresent}
              onClick={() => onAdd(name)}
              aria-label={`Add ${label}`}
              title={isPresent ? 'Already on canvas' : `Add ${label}`}
            >
              <Plus className="size-3" />
            </Button>
          </div>
        );
      })}
    </div>
  );
}
