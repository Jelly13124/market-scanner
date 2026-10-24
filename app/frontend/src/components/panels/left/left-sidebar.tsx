import { useResizable } from '@/hooks/use-resizable';
import { cn } from '@/lib/utils';
import { ReactNode, useEffect } from 'react';
import { AnalyzeAction } from './analyze-action';
import { FlowAction } from './flow-action';
import { HomeAction } from './home-action';
import { LabAction } from './lab-action';
import { PaperAction } from './paper-action';
import { ReportsAction } from './reports-action';
import { ScannerAction } from './scanner-action';
import { ScreenerAction } from './screener-action';
import { SectorsAction } from './sectors-action';
import { WatchlistAction } from './watchlist-action';

interface LeftSidebarProps {
  children?: ReactNode;
  isCollapsed: boolean;
  onCollapse: () => void;
  onExpand: () => void;
  onWidthChange?: (width: number) => void;
}

export function LeftSidebar({
  isCollapsed,
  onWidthChange,
}: LeftSidebarProps) {
  // Use our custom hooks
  const { width, isDragging, elementRef, startResize } = useResizable({
    defaultWidth: 280,
    minWidth: 200,
    maxWidth: window.innerWidth * .90,
    side: 'left',
  });

  // Notify parent component of width changes
  useEffect(() => {
    onWidthChange?.(width);
  }, [width, onWidthChange]);

  return (
    <div
      ref={elementRef}
      className={cn(
        "h-full bg-panel flex flex-col relative pt-5 border overflow-y-auto",
        isCollapsed ? "shadow-lg" : "",
      )}
      style={{
        width: `${width}px`
      }}
    >
      <HomeAction />

      <WatchlistAction />

      <ScreenerAction />

      <SectorsAction />

      <ScannerAction />

      <AnalyzeAction />

      <FlowAction />

      <ReportsAction />

      <PaperAction />

      <LabAction />

      {/* Resize handle - on the right side for left sidebar */}
      {!isDragging && (
        <div
          className="absolute top-0 right-0 h-full w-1 cursor-ew-resize transition-all duration-150 z-10"
          onMouseDown={startResize}
        />
      )}
    </div>
  );
}
