export interface BacktestMetrics {
  total_return: number | null;
  cagr: number | null;
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  calmar: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  n_trades: number | null;
  avg_holding_days: number | null;
}

export interface BacktestResponse {
  id: number;
  strategy_id: number;
  created_at: string;
  spec_snapshot_json: Record<string, unknown>;
  start_date: string;
  end_date: string;
  midpoint_date: string;
  universe_size: number;

  is_total_return: number | null;
  is_cagr: number | null;
  is_sharpe: number | null;
  is_sortino: number | null;
  is_max_drawdown: number | null;
  is_calmar: number | null;
  is_win_rate: number | null;
  is_profit_factor: number | null;
  is_n_trades: number | null;
  is_avg_holding_days: number | null;

  oos_total_return: number | null;
  oos_cagr: number | null;
  oos_sharpe: number | null;
  oos_sortino: number | null;
  oos_max_drawdown: number | null;
  oos_calmar: number | null;
  oos_win_rate: number | null;
  oos_profit_factor: number | null;
  oos_n_trades: number | null;
  oos_avg_holding_days: number | null;

  degradation_ratio: number | null;
  benchmark_cagr: number | null;
  verdict_label: string;
  verdict_text: string;

  trades_json: unknown[];
  equity_curve_is: number[];
  equity_curve_oos: number[];
  benchmark_curve: number[] | null;
  duration_seconds: number | null;
  error_message: string | null;
}
