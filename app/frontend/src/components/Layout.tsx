import { LeftSidebar } from '@/components/panels/left/left-sidebar';
import { TabBar } from '@/components/tabs/tab-bar';
import { TabContent } from '@/components/tabs/tab-content';
import { SidebarProvider } from '@/components/ui/sidebar';
import { LayoutProvider } from '@/contexts/layout-context';
import { TabsProvider, useTabsContext } from '@/contexts/tabs-context';
import { useLayoutKeyboardShortcuts } from '@/hooks/use-keyboard-shortcuts';
import { cn } from '@/lib/utils';
import { SidebarStorageService } from '@/services/sidebar-storage';
import { TabService } from '@/services/tab-service';
import { ReactNode, useEffect, useState } from 'react';
import { TopBar } from './layout/top-bar';

// Create a LayoutContent component to access TabsContext.
function LayoutContent({ children: _children }: { children?: ReactNode }) {
  const { openTab } = useTabsContext();

  // Initialize sidebar states from storage service
  const [isLeftCollapsed, setIsLeftCollapsed] = useState(() =>
    SidebarStorageService.loadLeftSidebarState(false)
  );

  // Track actual sidebar widths for dynamic positioning
  const [leftSidebarWidth, setLeftSidebarWidth] = useState(280);

  const handleSettingsClick = () => {
    const tabData = TabService.createSettingsTab();
    openTab(tabData);
  };

  // Add keyboard shortcuts for toggling sidebars and fit view
  useLayoutKeyboardShortcuts(
    () => {}, // Cmd+I (right sidebar) — no-op; right sidebar removed
    () => setIsLeftCollapsed(!isLeftCollapsed),   // Cmd+B for left sidebar
    () => {}, // Cmd+O (fit view) — no-op; no global flow canvas
    undefined, // undo
    undefined, // redo
    () => {}, // Cmd+J (bottom panel) — no-op; bottom panel removed
    handleSettingsClick, // Shift+Cmd+J for settings
  );

  // Save sidebar states whenever they change
  useEffect(() => {
    SidebarStorageService.saveLeftSidebarState(isLeftCollapsed);
  }, [isLeftCollapsed]);

  // Calculate tab bar positioning based on actual sidebar widths
  const getSidebarBasedStyle = () => {
    const left = !isLeftCollapsed ? leftSidebarWidth : 0;
    return {
      left: `${left}px`,
      right: '0px',
    };
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden relative bg-background">
      {/* VSCode-style Top Bar */}
      <TopBar onSettingsClick={handleSettingsClick} />

      {/* Tab Bar */}
      <div
        className="absolute top-0 z-10 transition-all duration-200"
        style={getSidebarBasedStyle()}
      >
        <TabBar />
      </div>

      {/* Main content area */}
      <main
        className="absolute inset-0 overflow-hidden"
        style={{
          left: !isLeftCollapsed ? `${leftSidebarWidth}px` : '0px',
          right: '0px',
          top: '40px', // Tab bar height
          bottom: '0px',
        }}
      >
        <TabContent className="h-full w-full" />
      </main>

      {/* Floating left sidebar */}
      <div className={cn(
        "absolute top-0 left-0 z-30 h-full transition-transform",
        isLeftCollapsed && "transform -translate-x-full opacity-0"
      )}>
        <LeftSidebar
          isCollapsed={isLeftCollapsed}
          onCollapse={() => setIsLeftCollapsed(true)}
          onExpand={() => setIsLeftCollapsed(false)}
          onWidthChange={setLeftSidebarWidth}
        />
      </div>
    </div>
  );
}

interface LayoutProps {
  children?: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <SidebarProvider defaultOpen={true}>
      <TabsProvider>
        <LayoutProvider>
          <LayoutContent>{children}</LayoutContent>
        </LayoutProvider>
      </TabsProvider>
    </SidebarProvider>
  );
}
