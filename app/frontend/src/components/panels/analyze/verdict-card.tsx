// VerdictCard — the buy/sell/hold + confidence takeaway, shown above the
// report in the Analyze panel so impatient readers get the call at a glance.
// Mirrors the banner rendered at the top of the HTML report.

import { cn } from '@/lib/utils';
import { Recommendation, VerdictPayload } from '@/types/analyze';
import { useTranslation } from 'react-i18next';

const STYLE: Record<Recommendation, { color: string; bg: string; bar: string }> = {
  strong_buy:  { color: 'text-green-700',  bg: 'bg-green-50 border-green-600',   bar: 'bg-green-700' },
  buy:         { color: 'text-green-600',  bg: 'bg-green-50 border-green-500',   bar: 'bg-green-600' },
  hold:        { color: 'text-gray-600',   bg: 'bg-gray-50 border-gray-400',     bar: 'bg-gray-500' },
  sell:        { color: 'text-orange-600', bg: 'bg-orange-50 border-orange-500', bar: 'bg-orange-600' },
  strong_sell: { color: 'text-red-600',    bg: 'bg-red-50 border-red-600',       bar: 'bg-red-600' },
};

const LABEL_EN: Record<Recommendation, string> = {
  strong_buy: 'STRONG BUY', buy: 'BUY', hold: 'HOLD', sell: 'SELL', strong_sell: 'STRONG SELL',
};
const LABEL_ZH: Record<Recommendation, string> = {
  strong_buy: '强力买入', buy: '买入', hold: '持有 / 观望', sell: '卖出', strong_sell: '强力卖出',
};

export function VerdictCard({ verdict }: { verdict: VerdictPayload }) {
  const { i18n } = useTranslation();
  const isZh = i18n.language === 'zh';
  const s = STYLE[verdict.recommendation] ?? STYLE.hold;
  const label = (isZh ? LABEL_ZH : LABEL_EN)[verdict.recommendation] ?? verdict.recommendation;
  const conf = Math.max(0, Math.min(100, Math.round(verdict.confidence_score)));

  return (
    <div className={cn('border-2 rounded-xl px-4 py-3 mb-3', s.bg)}>
      <div className="flex items-center gap-4 flex-wrap">
        <div>
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {isZh ? '投资建议' : 'Recommendation'}
          </div>
          <div className={cn('text-2xl font-extrabold leading-none', s.color)}>{label}</div>
        </div>
        <div className="flex-1 min-w-[160px]">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            {isZh ? '置信度' : 'Confidence'}
          </div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
              <div className={cn('h-full', s.bar)} style={{ width: `${conf}%` }} />
            </div>
            <strong className={s.color}>{conf}/100</strong>
          </div>
        </div>
      </div>
      {verdict.one_liner && (
        <div className="mt-2 text-sm text-foreground/80">{verdict.one_liner}</div>
      )}
    </div>
  );
}
