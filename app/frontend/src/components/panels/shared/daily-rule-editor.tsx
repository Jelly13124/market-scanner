import { useTranslation } from 'react-i18next';
import { ruleNames, defaultCondition, type DailyRuleGroup, type RuleName, type SignalDirection, type Condition } from '@/types/daily-rule';

const selectStyle = 'w-full rounded border bg-background px-2 py-1.5';
const directions: SignalDirection[] = ['bullish', 'bearish', 'neutral', 'any'];

export function DailyRuleEditor({group, onChange}: {
  group: DailyRuleGroup;
  onChange: (group: DailyRuleGroup) => void;
}) {
  const { t } = useTranslation();
  function update(type: RuleName, values: Partial<Condition>) {
    onChange({...group, signals: group.signals.map(s => s.type === type ? {...s, ...values} : s)});
  }
  return <div className="space-y-2 rounded border p-3 text-sm">
    <label className="block">{t('dailyRules.combiner')}
      <select aria-label={t('dailyRules.combiner')} className={selectStyle} value={group.combiner}
        onChange={e => onChange({...group, combiner: e.target.value as DailyRuleGroup['combiner']})}>
        <option value="and">{t('dailyRules.and')}</option>
        <option value="or">{t('dailyRules.or')}</option>
      </select>
    </label>
    {ruleNames.map(type => {
      const rule = group.signals.find(s => s.type === type);
      const isStrength = type === 'relative_strength';
      return <fieldset key={type} className="border-t pt-2">
        <legend className="sr-only">{t(`dailyRules.${type}`)}</legend>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={!!rule} onChange={e => {
            const signals = e.target.checked ? [...group.signals, defaultCondition(type)] : group.signals.filter(s => s.type !== type);
            onChange({...group, signals});
          }} />{t(`dailyRules.${type}`)}
        </label>
        {rule && <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <label>{t('dailyRules.window')}
            <input className={selectStyle} type="number" required min="1" step="1" value={rule.window || ''}
              onChange={e => update(type, {window: Number(e.target.value)})} />
          </label>
          {type !== 'range_breakout' && <label>{t(isStrength ? 'dailyRules.spread' : 'dailyRules.volumeMultiple')}
            <input className={selectStyle} type="number" required step="any" min={isStrength ? 0 : 1}
              value={rule.threshold ? Number((rule.threshold * (isStrength ? 100 : 1)).toPrecision(14)) : ''}
              onChange={e => update(type, {threshold: Number(e.target.value) / (isStrength ? 100 : 1)})} />
          </label>}
          <label>{t('dailyRules.direction')}
            <select aria-label={t('dailyRules.direction')} className={selectStyle} value={rule.direction}
              onChange={e => update(type, {direction: e.target.value as SignalDirection})}>
              {directions.map(dir => <option key={dir} value={dir}>{t(`dailyRules.${dir}`)}</option>)}
            </select>
          </label>
        </div>}
      </fieldset>;
    })}
    {!group.signals.length && <p role="alert">{t('dailyRules.selectOne')}</p>}
  </div>;
}
