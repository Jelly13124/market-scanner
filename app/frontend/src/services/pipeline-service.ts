// pipeline-service.ts — REST wrapper for the /pipeline/* backend endpoints.
// Mirrors the shape of services/scanner-service.ts.

import {
  PipelineRunDetail,
  PipelineRunSummary,
  PipelineScheduleResponse,
  PipelineScheduleUpdateRequest,
  RunPipelineRequest,
  RunPipelineResponse,
  TemplatesResponse,
} from '@/types/pipeline';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

async function _toError(res: Response, op: string): Promise<Error> {
  let detail = '';
  try {
    const body = await res.json();
    detail = body?.detail || body?.message || JSON.stringify(body);
  } catch {
    try { detail = await res.text(); } catch { /* swallow */ }
  }
  return new Error(
    `${op} failed (HTTP ${res.status}${res.statusText ? ' ' + res.statusText : ''})${detail ? `: ${detail}` : ''}`,
  );
}

export interface ListRunsParams {
  limit?: number;
  template?: string;
  status?: 'PENDING' | 'RUNNING' | 'COMPLETE' | 'ERROR';
  since?: string;
}

export const pipelineService = {
  // -- read endpoints --------------------------------------------------------

  async listTemplates(): Promise<TemplatesResponse> {
    const r = await fetch(`${API_BASE_URL}/pipeline/templates`);
    if (!r.ok) throw await _toError(r, 'listTemplates');
    return r.json();
  },

  async listRuns(params: ListRunsParams = {}): Promise<PipelineRunSummary[]> {
    const q = new URLSearchParams();
    if (params.limit != null) q.set('limit', String(params.limit));
    if (params.template) q.set('template', params.template);
    if (params.status) q.set('status', params.status);
    if (params.since) q.set('since', params.since);
    const qs = q.toString();
    const url = `${API_BASE_URL}/pipeline/runs${qs ? `?${qs}` : ''}`;
    const r = await fetch(url);
    if (!r.ok) throw await _toError(r, 'listRuns');
    return r.json();
  },

  async getRun(runId: string): Promise<PipelineRunDetail> {
    const r = await fetch(`${API_BASE_URL}/pipeline/runs/${runId}`);
    if (!r.ok) throw await _toError(r, 'getRun');
    return r.json();
  },

  // -- triggering ------------------------------------------------------------

  async triggerRun(body: RunPipelineRequest): Promise<RunPipelineResponse> {
    const r = await fetch(`${API_BASE_URL}/pipeline/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw await _toError(r, 'triggerRun');
    return r.json();
  },

  // -- schedule (singleton config) ------------------------------------------

  async getSchedule(): Promise<PipelineScheduleResponse> {
    const r = await fetch(`${API_BASE_URL}/pipeline/schedule`);
    if (!r.ok) throw await _toError(r, 'getSchedule');
    return r.json();
  },

  async updateSchedule(patch: PipelineScheduleUpdateRequest): Promise<PipelineScheduleResponse> {
    const r = await fetch(`${API_BASE_URL}/pipeline/schedule`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw await _toError(r, 'updateSchedule');
    return r.json();
  },

  // -- helpers --------------------------------------------------------------

  /** Polls getRun until status is COMPLETE/ERROR or timeout. Resolves with
   *  the final detail; rejects on timeout / network failure. */
  async pollUntilDone(
    runId: string,
    opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
  ): Promise<PipelineRunDetail> {
    const interval = opts.intervalMs ?? 1500;
    const timeout = opts.timeoutMs ?? 10 * 60 * 1000; // 10 min
    const start = Date.now();
    while (true) {
      if (opts.signal?.aborted) throw new Error('aborted');
      const detail = await this.getRun(runId);
      if (detail.status === 'COMPLETE' || detail.status === 'ERROR') return detail;
      if (Date.now() - start > timeout) throw new Error('pollUntilDone: timeout');
      await new Promise((r) => setTimeout(r, interval));
    }
  },
};
