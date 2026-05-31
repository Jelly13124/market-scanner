import { AnalyzePanel } from '@/components/panels/analyze/analyze-panel';
import { LabPanel } from '@/components/panels/lab/lab-panel';
import { ReportsPanel } from '@/components/panels/reports/reports-panel';
import { ScannerPanel } from '@/components/panels/scanner/scanner-panel';
import { ScreenerTab } from '@/components/panels/screener/screener-tab';
import { SectorsTab } from '@/components/panels/sectors/sectors-tab';
import { WatchlistTab } from '@/components/panels/watchlist/watchlist-tab';
import { Settings } from '@/components/settings/settings';
import { ReactNode, createElement } from 'react';

export interface TabData {
  type: 'settings' | 'scanner' | 'analyze' | 'lab' | 'screener' | 'reports' | 'watchlist' | 'sectors';
  title: string;
  metadata?: Record<string, any>;
}

export class TabService {
  static createTabContent(tabData: TabData): ReactNode {
    switch (tabData.type) {
      case 'settings':
        return createElement(Settings);

      case 'scanner':
        return createElement(ScannerPanel, {
          initialConfigId: tabData.metadata?.configId,
        });

      case 'analyze':
        return createElement(AnalyzePanel, {});

      case 'lab':
        return createElement(LabPanel, {});

      case 'screener':
        return createElement(ScreenerTab, {});

      case 'reports':
        return createElement(ReportsPanel, {});

      case 'watchlist':
        return createElement(WatchlistTab, {});

      case 'sectors':
        return createElement(SectorsTab, {});

      default:
        throw new Error(`Unsupported tab type: ${(tabData as any).type}`);
    }
  }

  static createSettingsTab(): TabData & { content: ReactNode } {
    return {
      type: 'settings',
      title: 'Settings',
      content: TabService.createTabContent({ type: 'settings', title: 'Settings' }),
    };
  }

  /** Open / focus the single Scanner tab. ``configId`` pre-selects a config. */
  static createScannerTab(configId?: number): TabData & { content: ReactNode } {
    const metadata = configId != null ? { configId } : undefined;
    return {
      type: 'scanner',
      title: 'Scanner',
      metadata,
      content: TabService.createTabContent({ type: 'scanner', title: 'Scanner', metadata }),
    };
  }

  /** Open / focus the single Analyze tab. */
  static createAnalyzeTab(): TabData & { content: ReactNode } {
    const metadata = {};
    return {
      type: 'analyze',
      title: 'Analyze',
      metadata,
      content: TabService.createTabContent({ type: 'analyze', title: 'Analyze', metadata }),
    };
  }

  /** Open / focus the single Lab tab. */
  static createLabTab(): TabData & { content: ReactNode } {
    const metadata = {};
    return {
      type: 'lab',
      title: 'Lab',
      metadata,
      content: TabService.createTabContent({ type: 'lab', title: 'Lab', metadata }),
    };
  }

  /** Open / focus the single Screener tab. */
  static createScreenerTab(): TabData & { content: ReactNode } {
    return {
      type: 'screener',
      title: 'Screener',
      content: TabService.createTabContent({ type: 'screener', title: 'Screener' }),
    };
  }

  /** Open / focus the single Reports tab. */
  static createReportsTab(): TabData & { content: ReactNode } {
    return {
      type: 'reports',
      title: 'Reports',
      content: TabService.createTabContent({ type: 'reports', title: 'Reports' }),
    };
  }

  /** Open / focus the single Watchlist tab. */
  static createWatchlistTab(): TabData & { content: ReactNode } {
    return {
      type: 'watchlist',
      title: 'Watchlist',
      content: TabService.createTabContent({ type: 'watchlist', title: 'Watchlist' }),
    };
  }

  /** Open / focus the single Sectors board tab. */
  static createSectorsTab(): TabData & { content: ReactNode } {
    return {
      type: 'sectors',
      title: 'Sectors',
      content: TabService.createTabContent({ type: 'sectors', title: 'Sectors' }),
    };
  }

  // Restore tab content for persisted tabs (used when loading from localStorage)
  static restoreTabContent(tabData: TabData): ReactNode {
    return TabService.createTabContent(tabData);
  }

  // Helper method to restore a complete tab from saved data
  static restoreTab(savedTab: TabData): TabData & { content: ReactNode } {
    switch (savedTab.type) {
      case 'settings':
        return TabService.createSettingsTab();

      case 'scanner':
        return TabService.createScannerTab(savedTab.metadata?.configId);

      case 'analyze':
        return TabService.createAnalyzeTab();

      case 'lab':
        return TabService.createLabTab();

      case 'screener':
        return TabService.createScreenerTab();

      case 'reports':
        return TabService.createReportsTab();

      case 'watchlist':
        return TabService.createWatchlistTab();

      case 'sectors':
        return TabService.createSectorsTab();

      default:
        throw new Error(`Cannot restore unsupported tab type: ${(savedTab as any).type}`);
    }
  }
}
