// Phase 6F-3: right column of the Lab panel — renders the current spec
// grouped into Universe / Entry / Exit / Filters / Sizing / Backtest
// Config sections, plus a modal manual-edit button.

import { Button } from '@/components/ui/button';
import { strategyService } from '@/services/strategy-service';
import type { StrategyResponse, StrategySpec } from '@/types/strategy';
import { Pencil } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { SpecBlockCard } from './spec-block-card';
import { SpecJsonEditor } from './spec-json-editor';

interface Props {
  strategy: StrategyResponse | null;
  onSpecUpdated: () => void;
}

export function SpecViewer({ strategy, onSpecUpdated }: Props) {
  const [editing, setEditing] = useState(false);
  const { t } = useTranslation();

  if (!strategy) {
    return (
      <div className="border-l h-full flex items-center justify-center text-sm text-muted-foreground">
        {t('lab.spec.noStrategy')}
      </div>
    );
  }
  const spec: StrategySpec = strategy.spec_json;

  async function handleManualSave(newSpec: StrategySpec) {
    if (!strategy) return;
    try {
      await strategyService.update(strategy.id, { spec_json: newSpec });
      setEditing(false);
      onSpecUpdated();
      toast.success(t('lab.backtest.specUpdated'));
    } catch (e) {
      throw e;  // surface to editor dialog
    }
  }

  return (
    <div className="border-l h-full min-h-0 min-w-0 flex flex-col">
      <div className="px-3 py-2 border-b flex items-center justify-between">
        <div className="text-xs font-medium uppercase">{t('lab.spec.title')} {t('lab.version', { version: strategy.version })}</div>
        <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
          <Pencil className="size-3 mr-1" /> {t('lab.spec.editJson')}
        </Button>
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3 text-xs">
        <Section title={t('lab.spec.universe')}>
          <div className="border rounded p-2 bg-muted/30">
            <span className="font-bold">{spec.universe.kind}</span>
            {spec.universe.watchlist_id != null && (
              <span className="ml-2 text-muted-foreground">id={spec.universe.watchlist_id}</span>
            )}
          </div>
        </Section>
        <Section title={t('lab.spec.entry', { combiner: spec.entry.combiner })}>
          {spec.entry.signals.map((b, i) => (
            <SpecBlockCard key={i} block={b} category="entry" />
          ))}
        </Section>
        <Section title={t('lab.spec.exit')}>
          {spec.exit.map((b, i) => (
            <SpecBlockCard key={i} block={b} category="exit" />
          ))}
        </Section>
        {spec.filters.length > 0 && (
          <Section title={t('lab.spec.filters')}>
            {spec.filters.map((b, i) => (
              <SpecBlockCard key={i} block={b} category="filter" />
            ))}
          </Section>
        )}
        <Section title={t('lab.spec.sizing')}>
          <SpecBlockCard block={spec.sizing} category="sizing" />
        </Section>
        <Section title={t('lab.spec.backtestConfig')}>
          <div className="border rounded p-2 bg-muted/30 space-y-1">
            <KV k={t('lab.spec.starting')} v={`$${(spec.backtest_config.starting_capital_usd || 100000).toLocaleString()}`} />
            <KV k={t('lab.spec.costs')} v={`${spec.backtest_config.commission_bps || 5}bps + ${spec.backtest_config.slippage_bps || 5}bps`} />
            <KV k={t('lab.spec.maxPositions')} v={String(spec.backtest_config.max_concurrent_positions || 10)} />
            <KV k={t('lab.spec.isOosSplit')} v={`${((spec.backtest_config.is_oos_split || 0.7) * 100).toFixed(0)}/${((1 - (spec.backtest_config.is_oos_split || 0.7)) * 100).toFixed(0)}`} />
            <KV k={t('lab.spec.benchmark')} v={spec.backtest_config.benchmark || 'spy'} />
          </div>
        </Section>
      </div>

      <SpecJsonEditor
        open={editing} initialSpec={spec}
        onCancel={() => setEditing(false)}
        onSave={handleManualSave}
      />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-muted-foreground mb-1">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex gap-2">
      <span className="text-muted-foreground w-24">{k}</span>
      <span className="font-mono">{v}</span>
    </div>
  );
}
