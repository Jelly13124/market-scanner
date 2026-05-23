// TypeScript mirrors of AnalyzeRunRequest + AnalyzeReportDetail from
// app/backend/models/research_schemas.py.

export type Objective =
  | 'target_price' | 'short_term' | 'medium_term'
  | 'long_term' | 'earnings_review' | 'general_research';
export type RiskBand = 'conservative' | 'balanced' | 'aggressive';

export interface AnalyzeRunRequest {
  ticker: string;
  objective?: Objective;
  position_budget_usd?: number | null;
  already_holds?: boolean;
  cost_basis_usd?: number | null;
  risk_tolerance?: RiskBand;
  use_personas?: boolean;
  included_sections?: string[] | null;
}

export interface SectionPayloadAPI {
  name: string;
  markdown: string;
  structured: Record<string, unknown> | unknown[] | null;
  skipped: boolean;
  persona_used: string | null;
  skip_reason: string | null;
}

export interface BacktestVerdictAPI {
  signal: string;
  window_start: string;
  window_end: string;
  n_signals: number;
  win_rate_20d: number | null;
  avg_return_20d: number | null;
  t_stat: number | null;
  significant: boolean;
  verdict: string;
}

export interface AnalyzeReportDetail {
  id: number;
  ticker: string;
  scan_date: string;
  created_at: string;
  duration_seconds: number | null;
  objective: Objective;
  position_budget_usd: number | null;
  already_holds: boolean;
  cost_basis_usd: number | null;
  risk_tolerance: RiskBand;
  use_personas: boolean;
  persona_assignments: Record<string, unknown> | null;
  sections: Record<string, SectionPayloadAPI>;
  backtest: BacktestVerdictAPI | null;
}

// Default section order — keep in sync with src/research/models.py:SECTION_ORDER
export const SECTION_ORDER: string[] = [
  'data_health', 'executive_summary', 'evidence_ledger',
  'macro', 'sector', 'company_fundamentals', 'financial_statements',
  'valuation', 'technical', 'risk_position', 'scenarios',
  'conviction', 'event_risk', 'debate', 'final_strategy',
  'missing_data',
];

// Human-readable labels for each section
export const SECTION_LABELS: Record<string, string> = {
  data_health:          'Data Health',
  executive_summary:    'Executive Summary',
  evidence_ledger:      'Evidence Ledger',
  macro:                'Macro Regime',
  sector:               'Sector & Peer',
  company_fundamentals: 'Company Fundamentals',
  financial_statements: 'Financial Statements',
  valuation:            'Valuation',
  technical:            'Technical (incl. backtest)',
  risk_position:        'Risk & Position',
  scenarios:            'Bear/Base/Bull Scenarios',
  conviction:           'Conviction Score',
  event_risk:           'Event Risk',
  debate:               'Debate (personas only)',
  final_strategy:       'Final Strategy',
  missing_data:         'Missing Data',
};

// Subset that's always-on for the "Required only" preset
export const REQUIRED_SECTIONS: string[] = [
  'data_health', 'executive_summary', 'evidence_ledger',
  'conviction', 'final_strategy',
];
