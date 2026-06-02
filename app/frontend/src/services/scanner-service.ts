// scanner-service.ts — REST + SSE wrapper for the /scanner/* backend.
// Mirrors the patterns established in services/api.ts (fetch + AbortController +
// manual SSE parsing via getReader/TextDecoder).

import {
  DetectorMetadata,
  QuotesByTicker,
  ScanRunDetailResponse,
  ScanRunSummary,
  ScanStreamEvent,
  ScannerConfigCreateRequest,
  ScannerConfigResponse,
  ScannerConfigUpdateRequest,
} from '@/types/scanner';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

/** Throws a friendly Error built from a non-2xx fetch Response. */
async function _toError(res: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail || body?.message || JSON.stringify(body);
  } catch {
    try {
      detail = await res.text();
    } catch {
      detail = '';
    }
  }
  return new Error(
    `${op} failed (HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''})${detail ? `: ${detail}` : ''}`,
  );
}

export interface ScanStreamHandlers {
  onStart?: (e: Extract<ScanStreamEvent, { event: 'start' }>) => void;
  onProgress?: (e: Extract<ScanStreamEvent, { event: 'progress' }>) => void;
  onComplete?: (e: Extract<ScanStreamEvent, { event: 'complete' }>) => void;
  onError?: (e: Extract<ScanStreamEvent, { event: 'error' }>) => void;
  /** Invoked when the underlying fetch or stream fails for non-business reasons. */
  onFatal?: (err: Error) => void;
}

export const scannerService = {
  // ===================================================================
  // ScannerConfig CRUD
  // ===================================================================

  /** Registered detectors and their UI metadata, used to render the per-config picker. */
  async listDetectors(): Promise<DetectorMetadata[]> {
    const r = await fetch(`${API_BASE_URL}/scanner/detectors`);
    if (!r.ok) throw await _toError(r, 'listDetectors');
    return r.json();
  },

  async listConfigs(): Promise<ScannerConfigResponse[]> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs`);
    if (!r.ok) throw await _toError(r, 'listConfigs');
    return r.json();
  },

  async getConfig(id: number): Promise<ScannerConfigResponse> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs/${id}`);
    if (!r.ok) throw await _toError(r, 'getConfig');
    return r.json();
  },

  async createConfig(body: ScannerConfigCreateRequest): Promise<ScannerConfigResponse> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _toError(r, 'createConfig');
    return r.json();
  },

  async updateConfig(id: number, body: ScannerConfigUpdateRequest): Promise<ScannerConfigResponse> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _toError(r, 'updateConfig');
    return r.json();
  },

  async deleteConfig(id: number): Promise<void> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs/${id}`, { method: 'DELETE' });
    if (!r.ok) throw await _toError(r, 'deleteConfig');
  },

  // ===================================================================
  // Run lifecycle
  // ===================================================================

  /** Trigger a manual scan; resolves with the run_id. When a run is already in
   *  flight for this config the backend returns that run with already_running=true
   *  (instead of erroring), so the caller just re-attaches to its stream. */
  async runNow(configId: number): Promise<{ run_id: number; status: string; already_running?: boolean }> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs/${configId}/run`, {
      method: 'POST',
    });
    if (!r.ok) throw await _toError(r, 'runNow');
    return r.json();
  },

  /** Most recent run for a config (any status), or null. The panel calls this on
   *  mount / config-switch to re-attach to a run still RUNNING server-side (the
   *  panel unmounts + aborts its SSE on a tab switch) or restore the last results. */
  async getLatestRun(configId: number): Promise<ScanRunSummary | null> {
    const r = await fetch(`${API_BASE_URL}/scanner/configs/${configId}/latest-run`);
    if (!r.ok) throw await _toError(r, 'getLatestRun');
    return r.json();
  },

  async getRun(runId: number): Promise<ScanRunSummary> {
    const r = await fetch(`${API_BASE_URL}/scanner/runs/${runId}`);
    if (!r.ok) throw await _toError(r, 'getRun');
    return r.json();
  },

  async getRunEntries(runId: number): Promise<ScanRunDetailResponse> {
    const r = await fetch(`${API_BASE_URL}/scanner/runs/${runId}/entries`);
    if (!r.ok) throw await _toError(r, 'getRunEntries');
    return r.json();
  },

  /** Batch-fetch live quotes for all tickers in a completed run.
   *  Returns dict[ticker, Quote | null]. Null entries mean the quote
   *  fetch failed for that ticker — UI should show em-dash. The whole
   *  call may take ~20s for Top-N=20 (Finnhub rate-limit serialization). */
  async getRunQuotes(runId: number): Promise<QuotesByTicker> {
    const r = await fetch(`${API_BASE_URL}/scanner/runs/${runId}/quotes`);
    if (!r.ok) throw await _toError(r, 'getRunQuotes');
    return r.json();
  },

  /**
   * Subscribe to an in-progress run via SSE.
   *
   * Returns an abort callback. The handlers fire as ``event:``/``data:`` pairs
   * arrive over the stream. The stream ends naturally when the backend sends
   * the `complete` or `error` event (the server closes the connection after
   * those). The caller may also abort early — useful when the user navigates
   * away from the panel.
   */
  streamRun(runId: number, handlers: ScanStreamHandlers): () => void {
    const controller = new AbortController();

    (async () => {
      try {
        const response = await fetch(
          `${API_BASE_URL}/scanner/runs/${runId}/stream`,
          { signal: controller.signal, headers: { Accept: 'text/event-stream' } },
        );
        if (!response.ok) {
          handlers.onFatal?.(await _toError(response, 'streamRun'));
          return;
        }
        const reader = response.body?.getReader();
        if (!reader) {
          handlers.onFatal?.(new Error('streamRun: response body has no reader'));
          return;
        }

        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          // Each SSE event is terminated by a blank line.
          const events = buffer.split('\n\n');
          buffer = events.pop() || '';

          for (const text of events) {
            if (!text.trim()) continue;
            const eventTypeMatch = text.match(/^event: (.+)$/m);
            const dataMatch = text.match(/^data: (.+)$/m);
            if (!eventTypeMatch || !dataMatch) continue;
            const eventType = eventTypeMatch[1].trim();
            let data: any;
            try {
              data = JSON.parse(dataMatch[1]);
            } catch (e) {
              console.warn('scanner streamRun: malformed JSON in SSE data', e, dataMatch[1]);
              continue;
            }
            switch (eventType) {
              case 'start':
                handlers.onStart?.(data);
                break;
              case 'progress':
                handlers.onProgress?.(data);
                break;
              case 'complete':
                handlers.onComplete?.(data);
                break;
              case 'error':
                handlers.onError?.(data);
                break;
              default:
                // Unknown event types are ignored — forward-compatible.
                console.debug('scanner streamRun: unhandled SSE event type', eventType, data);
            }
          }
        }
      } catch (err) {
        if (controller.signal.aborted) return; // caller-initiated, not fatal
        handlers.onFatal?.(err instanceof Error ? err : new Error(String(err)));
      }
    })();

    return () => controller.abort();
  },
};

export type ScannerService = typeof scannerService;
