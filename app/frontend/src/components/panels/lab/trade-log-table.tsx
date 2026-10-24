// Phase 6G: collapsible trade log table.

import { Button } from '@/components/ui/button';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

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
  const { t } = useTranslation();

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
        {t('lab.backtest.tradeLog', { count: trades.length })}
      </Button>
      {open && (
        <div className="max-h-64 overflow-auto border-t">
          <table className="w-full text-xs">
            <thead className="bg-muted/30">
              <tr>
                <th className="px-2 py-1 text-left">{t('lab.backtest.ticker')}</th>
                <th className="px-2 py-1 text-left">{t('lab.backtest.entry')}</th>
                <th className="px-2 py-1 text-left">{t('lab.backtest.exit')}</th>
                <th className="px-2 py-1 text-right">{t('lab.backtest.in')}</th>
                <th className="px-2 py-1 text-right">{t('lab.backtest.out')}</th>
                <th className="px-2 py-1 text-right">{t('lab.backtest.pnl')}</th>
                <th className="px-2 py-1 text-left">{t('lab.backtest.reason')}</th>
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
