import type { EntryGroup } from '@/types/strategy';

export const ruleNames = ['relative_volume', 'range_breakout', 'relative_strength'] as const;
export type RuleName = typeof ruleNames[number];
export type SignalDirection = 'bullish' | 'bearish' | 'neutral' | 'any';
export type Condition = {
  type: RuleName;
  version: '1';
  window: number;
  direction: SignalDirection;
  threshold?: number;
};

export type DailyRuleGroup = {combiner: 'and' | 'or'; signals: Condition[]};

export function defaultCondition(type: RuleName): Condition {
  const base: Condition = {type, version: '1', window: 20, direction: 'bullish'};
  if (type === 'relative_volume') base.threshold = 2;
  if (type === 'relative_strength') base.threshold = 0.05;
  return base;
}

export function defaultDailyGroup(): DailyRuleGroup {
  return {combiner: 'and', signals: [defaultCondition('relative_volume')]};
}

export function editableDailyGroup(group: EntryGroup): group is DailyRuleGroup {
  const types = group.signals.map(signal => signal.type);
  return types.length > 0 && new Set(types).size === types.length &&
    group.signals.every(s => ruleNames.some(name => name === s.type) && s.version === '1');
}
