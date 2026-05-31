// TypeScript mirrors of AnalyzeRunRequest + AnalyzeReportDetail from
// app/backend/models/research_schemas.py.

export type Objective =
  | 'target_price' | 'short_term' | 'medium_term'
  | 'long_term' | 'earnings_review' | 'general_research';
export type RiskBand = 'conservative' | 'balanced' | 'aggressive';
export type ReportLanguage = 'en' | 'zh';
// Phase 8 — selects which data source / ticker convention the run targets.
// 'us' = US equities (Financial Datasets, Finnhub, etc.).
// 'cn' = A-shares (mootdx / a-stock-data toolkit).
export type Market = 'us' | 'cn';

export interface AnalyzeRunRequest {
  ticker: string;
  objective?: Objective;
  position_budget_usd?: number | null;
  already_holds?: boolean;
  cost_basis_usd?: number | null;
  risk_tolerance?: RiskBand;
  use_personas?: boolean;
  // Phase 5E — number of debate rounds the LLM simulates (1..5, default 3).
  // Sourced from the Debate node on the canvas; ignored by the backend's
  // debate section when use_personas=false.
  debate_rounds?: number;
  included_sections?: string[] | null;
  // Phase 5D — pin specific personas per section (canvas overrides).
  persona_overrides?: Record<string, string> | null;
  // Phase 7 i18n — output language for the generated report. Defaults to
  // 'en'. Sourced from the Input node on the canvas.
  report_language?: ReportLanguage;
  // Phase 8 A-share data integration — defaults to 'us'. Sourced from the
  // Input node on the canvas.
  market?: Market;
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

export type Recommendation =
  | 'strong_buy' | 'buy' | 'hold' | 'sell' | 'strong_sell';

export interface VerdictPayload {
  recommendation: Recommendation;
  confidence_score: number; // 0-100 — confidence in the recommendation
  // Conviction / setup-quality score (0-100). Shown as the headline metric
  // when present; null for old reports that predate the conviction section.
  stock_score?: number | null;
  one_liner: string;
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
  verdict: VerdictPayload | null;
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
  technical:            'Technical Analysis (含 Backtest)',
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

// Per-section persona support — mirrors `supports_personas` on each
// Section subclass in src/research/sections/. The dropdown on a
// SectionNode shows these (plus an "objective" entry meaning "no
// override / objective mode").
export const SECTION_PERSONAS: Record<string, string[]> = {
  company_fundamentals: ['buffett', 'munger', 'fisher'],
  valuation:            ['buffett', 'graham', 'munger', 'fisher'],
  risk_position:        ['druckenmiller', 'burry'],
  macro:                ['druckenmiller'],
};
