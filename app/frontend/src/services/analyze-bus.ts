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
type SectorListener = (sector: string) => void;

let pending: AnalyzeRequest | null = null;
const listeners = new Set<Listener>();
const createdListeners = new Set<VoidListener>();

// --- "filter the Screener to this sector" channel (Sectors board → Screener) ---
let pendingSector: string | null = null;
const sectorListeners = new Set<SectorListener>();

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

/**
 * Queue a sector and notify any mounted Screener tab to filter to it.
 * Mirrors requestAnalyze: if the Screener is already mounted its subscriber
 * fires immediately; if it's opening fresh it reads takePendingScreenerSectorFilter().
 */
export function requestScreenerSectorFilter(sector: string): void {
  pendingSector = sector;
  sectorListeners.forEach((l) => l(sector));
}

/** Read + clear the queued sector (used by the Screener tab on fresh mount). */
export function takePendingScreenerSectorFilter(): string | null {
  const s = pendingSector;
  pendingSector = null;
  return s;
}

/** Subscribe a mounted Screener tab. Returns an unsubscribe fn. */
export function subscribeScreenerSectorFilter(cb: SectorListener): () => void {
  sectorListeners.add(cb);
  return () => sectorListeners.delete(cb);
}
