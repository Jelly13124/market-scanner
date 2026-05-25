import { useTabsContext } from '@/contexts/tabs-context';
import { cn } from '@/lib/utils';
import { TabService } from '@/services/tab-service';
import { FileText, FolderOpen } from 'lucide-react';
import { useEffect } from 'react';

interface TabContentProps {
  className?: string;
}

export function TabContent({ className }: TabContentProps) {
  const { tabs, activeTabId, openTab } = useTabsContext();

  const activeTab = tabs.find(tab => tab.id === activeTabId);

  // Restore content for tabs that don't have it (from localStorage restoration)
  useEffect(() => {
    if (activeTab && !activeTab.content) {
      try {
        const restoredTab = TabService.restoreTab({
          type: activeTab.type,
          title: activeTab.title,
          metadata: activeTab.metadata,
        });

        // Update the tab with restored content
        openTab({
          id: activeTab.id,
          type: restoredTab.type,
          title: restoredTab.title,
          content: restoredTab.content,
          metadata: restoredTab.metadata,
        });
      } catch (error) {
        console.error('Failed to restore tab content:', error);
      }
    }
  }, [activeTab, openTab]);

  if (!activeTab) {
    return (
      <div className={cn(
        "h-full w-full flex items-center justify-center bg-background text-muted-foreground",
        className
      )}>
        <div className="text-center space-y-4">
          <FolderOpen size={48} className="mx-auto text-muted-foreground/50" />
          <div>
            <div className="text-xl font-medium mb-2">Welcome to the AI Hedge Fund</div>
            <div className="text-sm max-w-md">
              Create a flow from the left sidebar (⌘B) to open it in a tab, or open settings (⌘,) to configure your preferences.
            </div>
          </div>
          <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground/70">
            <FileText size={14} />
            <span>Flows now open in tabs</span>
          </div>
        </div>
      </div>
    );
  }

  // Show loading state if content is being restored
  if (!activeTab.content) {
    return (
      <div className={cn(
        "h-full w-full flex items-center justify-center bg-background text-muted-foreground",
        className
      )}>
        <div className="text-center">
          <div className="text-lg font-medium mb-2">Loading {activeTab.title}...</div>
        </div>
      </div>
    );
  }

  // Render ALL tabs simultaneously and toggle visibility via display:none.
  // This preserves React state (and any in-flight work like SOP runs / SSE
  // streams) when the user switches between tabs. Tabs whose content has
  // not yet been restored from localStorage are skipped.
  return (
    <div className={cn("h-full w-full bg-background overflow-hidden relative", className)}>
      {tabs.map((tab) =>
        tab.content ? (
          <div
            key={tab.id}
            className="absolute inset-0 h-full w-full"
            style={{ display: tab.id === activeTabId ? undefined : 'none' }}
          >
            {tab.content}
          </div>
        ) : null,
      )}
    </div>
  );
} 