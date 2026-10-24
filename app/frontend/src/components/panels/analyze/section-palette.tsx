// Sidebar list of all 16 SOP sections plus the Input node + a visual
// Manager Check terminator. Click '+' to add a node to the canvas. We
// deliberately mirror the existing right-sidebar pattern (right-sidebar.tsx)
// — click-from-palette, not HTML5 drag-drop.

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { GripVertical, Plus } from 'lucide-react';

import {
  REQUIRED_SECTIONS, SECTION_LABELS, SECTION_ORDER,
} from '@/types/analyze';

export interface SectionPaletteProps {
  /** Which section names are currently on the canvas (disables their '+'). */
  presentSections: Set<string>;
  /** Whether the singleton Input node is already on canvas. */
  hasInputNode: boolean;
  /** Add a section node by name. */
  onAdd: (sectionName: string) => void;
  /** Add (or focus) the Input node. */
  onAddInput: () => void;
}

export function SectionPalette({
  presentSections, hasInputNode, onAdd, onAddInput,
}: SectionPaletteProps) {
  return (
    <div className="h-full overflow-auto p-2 space-y-1">
      <div className="text-xs font-medium uppercase text-muted-foreground px-2 pt-1 pb-1">
        Canvas Nodes
      </div>

      {/* Input node (top) */}
      <div
        className={cn(
          'flex items-center justify-between gap-2 px-2 py-1 rounded',
          'hover:bg-accent/40 transition-colors',
        )}
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          <GripVertical className="size-3 text-primary" />
          <span className="text-sm truncate font-medium" title="Run Input">
            Input
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          onClick={onAddInput}
          aria-label="Add Input node"
          title={hasInputNode ? 'Focus existing Input node' : 'Add Input node'}
        >
          <Plus className="size-3" />
        </Button>
      </div>

      <div className="text-xs font-medium uppercase text-muted-foreground px-2 pt-2 pb-1">
        SOP Sections
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

      {/* Manager Check (bottom, visual only) */}
      <div className="text-xs font-medium uppercase text-muted-foreground px-2 pt-2 pb-1">
        Terminal
      </div>
      <div
        className={cn(
          'flex items-center justify-between gap-2 px-2 py-1 rounded',
          'hover:bg-accent/40 transition-colors',
          presentSections.has('manager_check') && 'opacity-50',
        )}
      >
        <div className="flex flex-col min-w-0 flex-1">
          <span className="text-sm truncate" title="Manager Check">
            Manager Check
          </span>
          <span className="text-[10px] uppercase text-muted-foreground">
            visual only
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-6 p-0"
          disabled={presentSections.has('manager_check')}
          onClick={() => onAdd('manager_check')}
          aria-label="Add Manager Check"
          title={
            presentSections.has('manager_check')
              ? 'Already on canvas'
              : 'Add Manager Check (visual terminator)'
          }
        >
          <Plus className="size-3" />
        </Button>
      </div>
    </div>
  );
}
