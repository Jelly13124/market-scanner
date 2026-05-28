import { AnalyzePanel } from '@/components/panels/analyze/analyze-panel';
import { LabPanel } from '@/components/panels/lab/lab-panel';
import { ScannerPanel } from '@/components/panels/scanner/scanner-panel';
import { ScreenerTab } from '@/components/panels/screener/screener-tab';
import { Settings } from '@/components/settings/settings';
import { ReactNode, createElement } from 'react';

export interface TabData {
  type: 'settings' | 'scanner' | 'analyze' | 'lab' | 'screener';
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

      default:
        throw new Error(`Cannot restore unsupported tab type: ${(savedTab as any).type}`);
    }
  }
}
