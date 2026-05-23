// Gate form — collects ticker, objective, budget, holding info, risk,
// personas. Submit triggers the parent's onRun callback.

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import type { AnalyzeRunRequest, Objective, RiskBand } from '@/types/analyze';
import { Loader2, Play } from 'lucide-react';
import { useState } from 'react';

interface AnalyzeFormProps {
  defaultTicker?: string;
  running: boolean;
  onRun: (req: AnalyzeRunRequest, included: Set<string>) => void;
  included: Set<string>;
}

const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: 'general_research', label: 'General research' },
  { value: 'target_price',     label: 'Target price' },
  { value: 'short_term',       label: 'Short-term trade (< 1 week)' },
  { value: 'medium_term',      label: 'Medium-term (1-3 months)' },
  { value: 'long_term',        label: 'Long-term investment (> 1 year)' },
  { value: 'earnings_review',  label: 'Earnings review' },
];

const RISKS: { value: RiskBand; label: string }[] = [
  { value: 'conservative', label: 'Conservative (~≤10% drawdown)' },
  { value: 'balanced',     label: 'Balanced (~10-20%)' },
  { value: 'aggressive',   label: 'Aggressive (~25%+)' },
];

export function AnalyzeForm({ defaultTicker = 'NVDA', running, onRun, included }: AnalyzeFormProps) {
  const [ticker, setTicker] = useState(defaultTicker);
  const [objective, setObjective] = useState<Objective>('general_research');
  const [budget, setBudget] = useState<string>('');
  const [holds, setHolds] = useState(false);
  const [costBasis, setCostBasis] = useState<string>('');
  const [risk, setRisk] = useState<RiskBand>('balanced');
  const [usePersonas, setUsePersonas] = useState(true);

  function submit() {
    const req: AnalyzeRunRequest = {
      ticker: ticker.trim().toUpperCase(),
      objective,
      position_budget_usd: budget ? parseFloat(budget) : null,
      already_holds: holds,
      cost_basis_usd: holds && costBasis ? parseFloat(costBasis) : null,
      risk_tolerance: risk,
      use_personas: usePersonas,
      included_sections: Array.from(included),
    };
    onRun(req, included);
  }

  return (
    <div className="space-y-3">
      {/* Row 1 — ticker + objective */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Ticker</label>
          <Input
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !running) submit(); }}
            className="w-28 h-8 font-mono uppercase"
            placeholder="NVDA"
          />
        </div>
        <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
          <label className="text-xs text-muted-foreground">Objective</label>
          <select
            value={objective}
            onChange={(e) => setObjective(e.target.value as Objective)}
            className="h-8 px-2 text-sm border rounded bg-background"
          >
            {OBJECTIVES.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Row 2 — budget + holds */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground">Budget (USD)</label>
          <Input
            type="number" min="0" step="100"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="10000"
            className="w-28 h-8"
          />
        </div>
        <label className="flex items-center gap-2 text-sm h-8 cursor-pointer">
          <Checkbox checked={holds} onCheckedChange={(v) => setHolds(!!v)} />
          <span>I already hold this</span>
        </label>
        {holds && (
          <div className="flex flex-col gap-1">
            <label className="text-xs text-muted-foreground">Cost basis ($/share)</label>
            <Input
              type="number" min="0" step="0.01"
              value={costBasis}
              onChange={(e) => setCostBasis(e.target.value)}
              placeholder="120.50"
              className="w-32 h-8"
            />
          </div>
        )}
      </div>

      {/* Row 3 — risk + personas */}
      <div className="flex flex-wrap gap-3 items-end">
        <div className="flex flex-col gap-1 flex-1 min-w-[200px]">
          <label className="text-xs text-muted-foreground">Risk tolerance</label>
          <select
            value={risk}
            onChange={(e) => setRisk(e.target.value as RiskBand)}
            className="h-8 px-2 text-sm border rounded bg-background"
          >
            {RISKS.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm h-8 cursor-pointer">
          <Checkbox
            checked={usePersonas}
            onCheckedChange={(v) => setUsePersonas(!!v)}
          />
          <span>Use personas + debate</span>
        </label>
      </div>

      {/* Submit */}
      <div className="pt-2">
        <Button onClick={submit} disabled={running || !ticker} size="sm">
          {running ? (
            <>
              <Loader2 className="size-3 mr-1 animate-spin" />
              Running SOP… (60-120s, {included.size} sections)
            </>
          ) : (
            <>
              <Play className="size-3 mr-1" />
              Run SOP analysis ({included.size} sections)
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
