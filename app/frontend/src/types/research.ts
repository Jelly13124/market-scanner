// TypeScript types mirroring app/backend/models/research_schemas.py.
// Keep in sync when the backend schemas change.

export type HoldingStatus =
  | 'holding'
  | 'watching'
  | 'considering_buy'
  | 'considering_short';
export type RiskTolerance = 'conservative' | 'moderate' | 'aggressive';
export type ReportGoal =
  | 'new_entry'
  | 'hold_review'
  | 'exit_decision'
  | 'general_research';
export type Direction = 'long' | 'short' | 'stand_aside';
export type SampleQuality = 'strong' | 'moderate' | 'weak' | 'insufficient';

// POST /research/run body
export interface ResearchRunRequest {
  ticker: string;
  holding_status?: HoldingStatus;
  target_position_pct?: number;
  risk_tolerance?: RiskTolerance;
  report_goal?: ReportGoal;
  use_personas?: boolean;
}

export interface TradePlanPayload {
  direction: Direction;
  entry_price: number | null;
  target_price: number | null;
  stop_price: number | null;
  horizon_days: number;
  sizing_pct: number;
  confidence: number;
  rationale: string;
}

export interface BacktestSummaryPayload {
  matches_found: number;
  win_rate: number | null;
  avg_pnl_pct: number | null;
  max_drawdown_pct: number | null;
  avg_holding_days: number | null;
  sample_quality: SampleQuality;
  caveat: string | null;
}

// GET /research/reports — list row
export interface ResearchReportSummary {
  id: number;
  ticker: string;
  scan_date: string;
  created_at: string;
  use_personas: boolean;
  duration_seconds: number | null;
}

// GET /research/reports/{id} — full body (HTML fetched separately)
export interface ResearchReportDetail {
  id: number;
  ticker: string;
  scan_date: string;
  created_at: string;
  use_personas: boolean;
  persona_assignments: Record<string, unknown> | null;
  report_markdown: string;
  duration_seconds: number | null;
  plan: TradePlanPayload;
  backtest: BacktestSummaryPayload;
}
