// TypeScript types mirroring the backend Pydantic schemas in
// app/backend/models/pipeline_schemas.py. Keep in sync when backend changes.

import type { Direction, TriggerPayload } from '@/types/scanner';

export type PipelineStatus = 'PENDING' | 'RUNNING' | 'COMPLETE' | 'ERROR';

// ---------------------------------------------------------------------------
// POST /pipeline/run
// ---------------------------------------------------------------------------

export interface RunPipelineRequest {
  scan_date?: string | null;
  universe?: string;
  universe_tickers?: string[] | null;
  top_n?: number;
  template?: string | null;
  custom_analysts?: string[] | null;
  model_name?: string;
  model_provider?: string;
  portfolio?: Record<string, unknown> | null;
}

export interface RunPipelineResponse {
  run_id: string;
  status: PipelineStatus;
}

// ---------------------------------------------------------------------------
// GET /pipeline/runs[/{id}]
// ---------------------------------------------------------------------------

export interface PipelineRunSummary {
  id: string;
  created_at?: string | null;
  completed_at?: string | null;
  scan_date: string;
  template: string;
  top_n: number;
  universe: string;
  status: PipelineStatus;
  duration_seconds?: number | null;
  error?: string | null;
}

/** One ScoredEntry from the pipeline watchlist — mirrors v2.scanner.models.ScoredEntry */
export interface PipelineWatchlistEntry {
  ticker: string;
  composite_score: number;
  direction: Direction;
  event_score: number;
  quant_score?: number | null;
  event_severity?: number;
  triggers: TriggerPayload[];
  rank: number;
}

/** Per-ticker signal output by ONE analyst agent. */
export interface AnalystSignal {
  signal: Direction;
  /** 0-100. */
  confidence: number | string;
  /** Free-form text OR structured dict (depends on the agent). */
  reasoning: unknown;
}

/** Output of portfolio_manager_agent — top-level decision per ticker. */
export interface AgentDecision {
  action: 'buy' | 'sell' | 'short' | 'cover' | 'hold';
  quantity: number;
  confidence?: number;
  reasoning?: string;
}

export interface PipelineRunDetail extends PipelineRunSummary {
  selected_analysts: string[];
  watchlist?: PipelineWatchlistEntry[] | null;
  agent_decisions?: Record<string, AgentDecision> | null;
  /** analyst_signals[agent_id][ticker] = AnalystSignal */
  analyst_signals?: Record<string, Record<string, AnalystSignal>> | null;
}

// ---------------------------------------------------------------------------
// GET /pipeline/templates
// ---------------------------------------------------------------------------

export interface AgentMetadata {
  key: string;
  display_name: string;
  description: string;
  investing_style: string;
  order: number;
}

export interface TemplatesResponse {
  templates: Record<string, string[]>;
  default_template: string;
  agents: AgentMetadata[];
}

// ---------------------------------------------------------------------------
// GET/PATCH /pipeline/schedule
// ---------------------------------------------------------------------------

export interface PipelineScheduleResponse {
  enabled: boolean;
  top_n: number;
  template: string;
  universe: string;
  model_name: string;
  model_provider: string;
  updated_at?: string | null;
}

export interface PipelineScheduleUpdateRequest {
  enabled?: boolean;
  top_n?: number;
  template?: string;
  universe?: string;
  model_name?: string;
  model_provider?: string;
}
