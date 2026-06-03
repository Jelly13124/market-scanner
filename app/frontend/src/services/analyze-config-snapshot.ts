// analyze-config-snapshot — bridges the Analyze panel's canvas config to the
// always-mounted AnalyzeRunsProvider for bus-driven one-click runs.
//
// By default a one-click "Analyze this ticker" (from Scanner/Screener/Watchlist)
// runs a STANDARD full report. When the user opts in (the toggle below), it
// instead reuses the sections + persona overrides from their Analyze canvas.
// The panel writes its config here on every canvas change; the provider reads
// it. localStorage-backed so it survives reloads + is readable before the panel
// mounts.

export interface AnalyzeConfigSnapshot {
  included_sections: string[];
  persona_overrides: Record<string, string>;
}

const SNAPSHOT_KEY = 'analyze-config-snapshot';
const TOGGLE_KEY = 'analyze-oneclick-use-canvas';

let _mem: AnalyzeConfigSnapshot | null = null;

export function setAnalyzeConfigSnapshot(cfg: AnalyzeConfigSnapshot): void {
  _mem = cfg;
  try {
    localStorage.setItem(SNAPSHOT_KEY, JSON.stringify(cfg));
  } catch {
    /* private mode / quota — in-memory copy still works this session */
  }
}

export function getAnalyzeConfigSnapshot(): AnalyzeConfigSnapshot | null {
  if (_mem) return _mem;
  try {
    const raw = localStorage.getItem(SNAPSHOT_KEY);
    if (raw) {
      _mem = JSON.parse(raw) as AnalyzeConfigSnapshot;
      return _mem;
    }
  } catch {
    /* ignore */
  }
  return null;
}

/** Whether one-click runs should reuse the canvas config (default false). */
export function getOneClickUseCanvas(): boolean {
  try {
    return localStorage.getItem(TOGGLE_KEY) === '1';
  } catch {
    return false;
  }
}

export function setOneClickUseCanvas(on: boolean): void {
  try {
    localStorage.setItem(TOGGLE_KEY, on ? '1' : '0');
  } catch {
    /* ignore */
  }
}
