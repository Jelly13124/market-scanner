// Types for the read-only paper-trading performance panel (/paper/* backend).

export interface SleeveMetrics {
  total_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null; // ALREADY a ×100 percent — do NOT scale again
  n_trades: number | null;
  final_equity: number | null;
  n_marks: number | null;
}

export interface GraduationVerdict {
  passed: boolean;
  reasons: string[];
  checked_clauses: Record<string, boolean>;
}

export interface PaperPerformance {
  sleeves: Record<string, SleeveMetrics>;
  graduation: GraduationVerdict;
}
