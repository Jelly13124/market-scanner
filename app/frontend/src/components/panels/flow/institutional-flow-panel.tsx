// Institutional Positioning panel: dealer gamma (GEX, options-implied snapshot)
// + off-exchange short volume (FINRA Reg-SHO proxy, NOT true dark-pool/ATS).

import { Button } from '@/components/ui/button';
import { institutionalFlowService, type InstitutionalFlow } from '@/services/institutional-flow-service';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

function fmtUsd(n: number): string {
  const a = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(0)}M`;
  return `${sign}$${a.toFixed(0)}`;
}

export function InstitutionalFlowPanel() {
  const { t } = useTranslation();
  const [ticker, setTicker] = useState('');
  const [data, setData] = useState<InstitutionalFlow | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    const sym = ticker.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setError(null);
    setData(null);
    try {
      setData(await institutionalFlowService.get(sym));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  const g = data?.gamma ?? null;
  const sv = data?.short_volume ?? null;
  const negative = g?.regime === 'negative';

  return (
    <div className="h-full w-full overflow-auto p-4 bg-background text-foreground">
      <div className="mb-1 text-lg font-medium">{t('flow.title', 'Institutional Positioning')}</div>
      <div className="mb-4 text-xs text-muted-foreground max-w-2xl">
        {t('flow.subtitle', 'Dealer gamma (options-implied snapshot) + off-exchange short volume (FINRA proxy, NOT true dark-pool). Context, not a trade signal.')}
      </div>

      <div className="flex gap-2 mb-4 max-w-md">
        <input
          className="flex-1 border rounded px-2 py-1 bg-background text-sm"
          placeholder={t('flow.tickerPlaceholder', 'Ticker (e.g. NVDA)')}
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void load();
          }}
        />
        <Button onClick={() => void load()} disabled={loading || !ticker.trim()}>
          {loading ? t('common.loading', 'Loading...') : t('flow.load', 'Load')}
        </Button>
      </div>

      {error && <div className="text-sm text-red-500 mb-4">{error}</div>}
      {!data && !loading && !error && (
        <div className="text-sm text-muted-foreground">{t('flow.empty', 'Enter a ticker to see its institutional positioning.')}</div>
      )}

      {data && (
        <div className="space-y-4 max-w-2xl">
          <section className="border rounded p-3">
            <div className="font-medium mb-2">{t('flow.gamma.title', 'Dealer Gamma (GEX)')}</div>
            {g ? (
              <div className="space-y-1 text-sm">
                <div>
                  <span className="text-muted-foreground">{t('flow.gamma.regime', 'Regime')}: </span>
                  <span className={negative ? 'text-red-500 font-medium' : 'text-green-500 font-medium'}>
                    {g.regime.toUpperCase()}{' '}
                    {negative ? t('flow.gamma.neg', '(short gamma -> squeeze-prone)') : t('flow.gamma.pos', '(long gamma -> pinned)')}
                  </span>
                </div>
                <div>
                  <span className="text-muted-foreground">{t('flow.gamma.netGex', 'Net GEX')}: </span>
                  {fmtUsd(g.total_gex)} {t('flow.gamma.perMove', 'per 1% move')}
                </div>
                {g.gamma_flip != null && (
                  <div>
                    <span className="text-muted-foreground">{t('flow.gamma.flip', 'Gamma flip')}: </span>${g.gamma_flip.toFixed(2)}
                  </div>
                )}
                <div>
                  <span className="text-muted-foreground">{t('flow.gamma.spot', 'Spot')}: </span>${g.spot.toFixed(2)}
                </div>
                {g.walls && g.walls.length > 0 && (
                  <table className="mt-2 text-xs w-full max-w-xs">
                    <thead>
                      <tr className="text-muted-foreground text-left">
                        <th className="font-normal">{t('flow.gamma.strike', 'Strike')}</th>
                        <th className="font-normal">{t('flow.gamma.wall', '$-gamma (wall)')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.walls.slice(0, 5).map((w) => (
                        <tr key={w.strike}>
                          <td>{w.strike}</td>
                          <td>{fmtUsd(w.gamma_dollars)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">{t('flow.gamma.none', 'No options / gamma data.')}</div>
            )}
          </section>

          <section className="border rounded p-3">
            <div className="font-medium mb-1">{t('flow.short.title', 'Off-Exchange Short Pressure')}</div>
            <div className="text-xs text-muted-foreground mb-2">
              {t('flow.short.note', 'FINRA Reg-SHO daily short volume — a proxy, NOT true dark-pool/ATS.')}
            </div>
            {sv ? (
              <div className="text-sm">
                {t('flow.short.latest', 'Latest short volume')}: <span className="font-medium">{(sv.short_pct * 100).toFixed(1)}%</span> ({sv.date}),{' '}
                {sv.n_days}
                {t('flow.short.dayAvg', '-day avg')} {(sv.avg_short_pct * 100).toFixed(1)}%, {t('flow.short.trend', 'trend')} {sv.trend.toUpperCase()}
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">{t('flow.short.none', 'No short-volume data.')}</div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
