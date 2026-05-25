// Phase 6G: verdict badge + IS/OOS metrics + 3 chart imgs + collapsible trade log.

import { backtestService } from '@/services/backtest-service';
import type { BacktestResponse } from '@/types/backtest';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { TradeLogTable } from './trade-log-table';

interface Props {
  backtestId: number;
}

const VERDICT_COLORS: Record<string, string> = {
  positive_edge: 'bg-green-100 text-green-900 border-green-300',
  weak: 'bg-yellow-100 text-yellow-900 border-yellow-300',
  underperform_bench: 'bg-orange-100 text-orange-900 border-orange-300',
  overfit: 'bg-red-100 text-red-900 border-red-300',
  reject: 'bg-red-100 text-red-900 border-red-400',
  insufficient: 'bg-gray-100 text-gray-700 border-gray-300',
};

export function BacktestResult({ backtestId }: Props) {
  const [bt, setBt] = useState<BacktestResponse | null>(null);

  const reload = useCallback(() => {
    backtestService
      .get(backtestId)
      .then(setBt)
      .catch((e: Error) => toast.error(e.message));
  }, [backtestId]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (!bt) return <div className="p-3 text-xs text-muted-foreground">Loading...</div>;

  const verdictColor = VERDICT_COLORS[bt.verdict_label] || 'bg-muted';

  return (
    <div className="border-t p-3 space-y-3">
      <div className={`border rounded p-2 text-sm ${verdictColor}`}>
        <div className="font-bold uppercase">Verdict: {bt.verdict_label}</div>
        <div className="text-xs mt-1">{bt.verdict_text}</div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="border rounded overflow-hidden">
          <img
            src={backtestService.chartUrl(bt.id, 'equity_curve')}
            alt="Equity curve"
            className="w-full"
          />
        </div>
        <div className="space-y-1 text-xs">
          <table className="w-full">
            <thead>
              <tr className="text-muted-foreground">
                <td></td>
                <td className="text-right">IS</td>
                <td className="text-right">OOS</td>
                <td className="text-right">Benchmark</td>
              </tr>
            </thead>
            <tbody>
              <MetricRow
                label="CAGR"
                is={bt.is_cagr}
                oos={bt.oos_cagr}
                bench={bt.benchmark_cagr}
                pct
              />
              <MetricRow label="Sharpe" is={bt.is_sharpe} oos={bt.oos_sharpe} />
              <MetricRow label="Sortino" is={bt.is_sortino} oos={bt.oos_sortino} />
              <MetricRow
                label="Max DD"
                is={bt.is_max_drawdown}
                oos={bt.oos_max_drawdown}
                pct
              />
              <MetricRow
                label="Win rate"
                is={bt.is_win_rate}
                oos={bt.oos_win_rate}
                pct
              />
              <MetricRow
                label="Profit factor"
                is={bt.is_profit_factor}
                oos={bt.oos_profit_factor}
              />
              <MetricRow label="Trades" is={bt.is_n_trades} oos={bt.oos_n_trades} />
            </tbody>
          </table>
          {bt.degradation_ratio != null && (
            <div className="text-xs text-muted-foreground">
              Degradation ratio (OOS/IS CAGR): {bt.degradation_ratio.toFixed(2)}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="border rounded overflow-hidden">
          <img
            src={backtestService.chartUrl(bt.id, 'drawdown')}
            alt="Drawdown"
            className="w-full"
          />
        </div>
        <div className="border rounded overflow-hidden">
          <img
            src={backtestService.chartUrl(bt.id, 'monthly_heatmap')}
            alt="Monthly heatmap"
            className="w-full"
          />
        </div>
      </div>

      <TradeLogTable trades={(bt.trades_json as any[]) ?? []} />
    </div>
  );
}

interface MetricRowProps {
  label: string;
  is: number | null;
  oos: number | null;
  bench?: number | null;
  pct?: boolean;
}

function MetricRow({ label, is, oos, bench, pct }: MetricRowProps) {
  const fmt = (v: number | null | undefined) => {
    if (v == null) return '-';
    return pct ? `${(v * 100).toFixed(1)}%` : v.toFixed(2);
  };
  return (
    <tr>
      <td className="text-muted-foreground">{label}</td>
      <td className="text-right font-mono">{fmt(is)}</td>
      <td className="text-right font-mono">{fmt(oos)}</td>
      {bench !== undefined && <td className="text-right font-mono">{fmt(bench)}</td>}
    </tr>
  );
}
