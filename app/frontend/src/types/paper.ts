export type PaperNumber = number | string;
export interface PaperPosition {
  ticker: string; quantity: PaperNumber; average_cost: PaperNumber;
  last_price: PaperNumber; market_value: PaperNumber; unrealized_pnl: PaperNumber; updated_at: string;
}
export interface PaperTrade {
  id: number; ticker: string; side: 'buy' | 'sell'; quantity: PaperNumber; price: PaperNumber;
  notional: PaperNumber; realized_pnl: PaperNumber; cash_after: PaperNumber; created_at: string;
}
export interface PaperAccount {
  currency: 'USD'; pricing_mode: 'manual_simulation'; initial_cash: PaperNumber; cash: PaperNumber;
  market_value: PaperNumber; equity: PaperNumber; total_pnl: PaperNumber;
  realized_pnl: PaperNumber; unrealized_pnl: PaperNumber; positions: PaperPosition[]; trades: PaperTrade[];
}
