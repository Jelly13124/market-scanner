// analyze-bus — cross-tab "send this ticker to Analyze" channel.
//
// The Screener and Scanner live in different tabs from the Analyze panel
// (separate React trees, kept mounted via display:none). There is no global
// store, so this module-level singleton is the lightest way to hand a ticker
// from one tab to the Analyze panel and trigger an auto-run.
//
// Flow:
//   - Screener/Scanner call requestAnalyze({ticker, market}) then open/focus
//     the Analyze tab.
//   - If the Analyze panel is already mounted, its subscriber fires immediately.
//   - If the tab is opening fresh, the panel reads takePending() on mount.
// Either path runs exactly once (see analyze-panel.tsx).

export interface AnalyzeRequest {
  ticker: string;
  /** Backend market convention is lowercase. */
  market: 'us' | 'cn';
}

type Listener = (req: AnalyzeRequest) => void;
type VoidListener = () => void;

let pending: AnalyzeRequest | null = null;
const listeners = new Set<Listener>();
const createdListeners = new Set<VoidListener>();

export const analyzeBus = {
  /** Queue a ticker for analysis and notify any mounted Analyze panel. */
  requestAnalyze(req: AnalyzeRequest): void {
    pending = req;
    listeners.forEach((l) => l(req));
  },

  /** Read + clear the queued request (used by the panel on fresh mount). */
  takePending(): AnalyzeRequest | null {
    const r = pending;
    pending = null;
    return r;
  },

  /** Subscribe a mounted Analyze panel. Returns an unsubscribe fn. */
  subscribe(l: Listener): () => void {
    listeners.add(l);
    return () => listeners.delete(l);
  },

  // --- "the report set changed" channel (refreshes the sidebar list) ---
  // Fired after a run persists a new report, or after a delete.

  notifyReportsChanged(): void {
    createdListeners.forEach((l) => l());
  },

  subscribeReportsChanged(l: VoidListener): () => void {
    createdListeners.add(l);
    return () => createdListeners.delete(l);
  },
};
