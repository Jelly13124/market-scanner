// Phase 6G: collapsible trade log table.

import { Button } from '@/components/ui/button';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

interface Trade {
  ticker: string;
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  shares: number;
  pnl: number;
  exit_reason: string;
}

interface Props {
  trades: Trade[];
}

export function TradeLogTable({ trades }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <div className="border rounded">
      <Button
        variant="ghost"
        size="sm"
        className="w-full justify-start text-xs"
        onClick={() => setOpen(!open)}
      >
        {open ? (
          <ChevronDown className="size-3 mr-1" />
        ) : (
          <ChevronRight className="size-3 mr-1" />
        )}
        Trade log ({trades.length} trades)
      </Button>
      {open && (
        <div className="max-h-64 overflow-auto border-t">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr>
                <th className="px-2 py-1 text-left">Ticker</th>
                <th className="px-2 py-1 text-left">Entry</th>
                <th className="px-2 py-1 text-left">Exit</th>
                <th className="px-2 py-1 text-right">$ in</th>
                <th className="px-2 py-1 text-right">$ out</th>
                <th className="px-2 py-1 text-right">PnL</th>
                <th className="px-2 py-1 text-left">Reason</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t, i) => (
                <tr key={i} className="border-t">
                  <td className="px-2 py-1 font-mono">{t.ticker}</td>
                  <td className="px-2 py-1">{t.entry_date?.slice(0, 10)}</td>
                  <td className="px-2 py-1">{t.exit_date?.slice(0, 10)}</td>
                  <td className="px-2 py-1 text-right font-mono">
                    ${Number(t.entry_price ?? 0).toFixed(2)}
                  </td>
                  <td className="px-2 py-1 text-right font-mono">
                    ${Number(t.exit_price ?? 0).toFixed(2)}
                  </td>
                  <td
                    className={`px-2 py-1 text-right font-mono ${
                      Number(t.pnl ?? 0) >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {Number(t.pnl ?? 0) >= 0 ? '+' : ''}
                    {Number(t.pnl ?? 0).toFixed(2)}
                  </td>
                  <td className="px-2 py-1 text-muted-foreground">{t.exit_reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
