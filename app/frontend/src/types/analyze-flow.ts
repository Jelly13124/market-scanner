// TS mirror of app/backend/models/analyze_flow_schemas.py.
// AnalyzeFlow = saved canvas template the Analyze panel can load back.

export interface AnalyzeFlowCreate {
  name: string;
  included_sections: string[];
  use_personas?: boolean;
  persona_overrides?: Record<string, string> | null;
}

export interface AnalyzeFlowUpdate {
  name?: string;
  included_sections?: string[];
  use_personas?: boolean;
  persona_overrides?: Record<string, string> | null;
}

export interface AnalyzeFlowResponse {
  id: number;
  name: string;
  included_sections: string[];
  use_personas: boolean;
  persona_overrides: Record<string, string> | null;
  created_at: string;
  updated_at: string | null;
}
