// Toolbar button + modal for "Analyze with agents".
// Sends the current watchlist (ticker list) to POST /pipeline/run, then
// opens the AgentRunDetail dialog which polls until completion.

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { pipelineService } from '@/services/pipeline-service';
import { AgentMetadata } from '@/types/pipeline';
import { Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AgentRunDetailDialog } from './agent-run-detail';

interface AnalyzeButtonProps {
  /** Tickers from the current watchlist that get sent to the agents.
   *  Disabled when empty. */
  tickers: string[];
  /** LLM model passed through. The pipeline_schedule row stores a default
   *  for daily cron; interactive runs pass per-invocation. */
  modelName?: string;
  modelProvider?: string;
}

export function AnalyzeButton({
  tickers,
  modelName = 'deepseek-chat',
  modelProvider = 'DeepSeek',
}: AnalyzeButtonProps) {
  const [modalOpen, setModalOpen] = useState(false);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);

  return (
    <>
      <Button
        size="sm"
        variant="default"
        disabled={tickers.length === 0}
        onClick={() => setModalOpen(true)}
      >
        <Sparkles className="size-4" />
        Analyze with agents
      </Button>

      {modalOpen && (
        <AnalyzePickerDialog
          tickers={tickers}
          modelName={modelName}
          modelProvider={modelProvider}
          open={modalOpen}
          onOpenChange={setModalOpen}
          onSubmitted={(runId) => {
            setModalOpen(false);
            setDetailRunId(runId);
          }}
        />
      )}

      {detailRunId && (
        <AgentRunDetailDialog
          runId={detailRunId}
          open={!!detailRunId}
          onOpenChange={(open) => !open && setDetailRunId(null)}
        />
      )}
    </>
  );
}


interface PickerProps {
  tickers: string[];
  modelName: string;
  modelProvider: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSubmitted: (runId: string) => void;
}

/** Modal: pick a template (or custom analyst list) and kick off the run. */
function AnalyzePickerDialog({
  tickers, modelName, modelProvider, open, onOpenChange, onSubmitted,
}: PickerProps) {
  const [templates, setTemplates] = useState<Record<string, string[]>>({});
  const [defaultTemplate, setDefaultTemplate] = useState<string>('balanced');
  const [agents, setAgents] = useState<AgentMetadata[]>([]);
  const [chosen, setChosen] = useState<string>('balanced');
  const [submitting, setSubmitting] = useState(false);
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);

  // Load templates + agent metadata on mount.
  useEffect(() => {
    pipelineService
      .listTemplates()
      .then((res) => {
        setTemplates(res.templates);
        setDefaultTemplate(res.default_template);
        setAgents(res.agents);
        setChosen(res.default_template);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const chosenAnalysts = templates[chosen] ?? [];
  // Rough cost estimate based on agent count + ticker count. ~$0.001-0.002
  // per agent call on DeepSeek (we calibrate higher for safety). The number
  // is intentionally fuzzy — just enough to flag "you're about to spend a
  // lot" vs "this is cheap".
  const llmCallsApprox = chosenAnalysts.length * tickers.length + 2; // +risk_mgmt+pm
  const costApprox = llmCallsApprox * 0.002;

  const onSubmit = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const r = await pipelineService.triggerRun({
        universe: 'custom',
        universe_tickers: tickers,
        top_n: tickers.length,
        template: chosen,
        model_name: modelName,
        model_provider: modelProvider,
      });
      onSubmitted(r.run_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('scanner.analyze.dialogTitle')}</DialogTitle>
          <DialogDescription>
            Send {tickers.length} {tickers.length === 1 ? 'ticker' : 'tickers'} to a multi-agent workflow.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <label className="text-sm font-medium mb-1 block">{t('scanner.analyze.template')}</label>
            <select
              className="w-full border rounded px-2 py-1.5 text-sm bg-background"
              value={chosen}
              onChange={(e) => setChosen(e.target.value)}
              disabled={submitting}
            >
              {Object.keys(templates).map((name) => (
                <option key={name} value={name}>
                  {name}{name === defaultTemplate ? ' (default)' : ''}
                </option>
              ))}
            </select>
          </div>

          <div className="border rounded p-2 text-xs">
            <div className="text-muted-foreground mb-1">
              {chosenAnalysts.length} agents in this template:
            </div>
            <div className="flex flex-wrap gap-1">
              {chosenAnalysts.map((key) => {
                const meta = agents.find((a) => a.key === key);
                return (
                  <span key={key}
                    className="inline-flex items-center rounded bg-accent px-1.5 py-0.5 text-[10px] font-mono">
                    {meta?.display_name ?? key}
                  </span>
                );
              })}
            </div>
          </div>

          <div className="text-xs text-muted-foreground">
            ~{llmCallsApprox} LLM calls · est. cost ${costApprox.toFixed(2)} (rough)
          </div>

          {error && (
            <div className="text-sm text-red-600 border border-red-200 rounded p-2 bg-red-50">
              {error}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={submitting || tickers.length === 0}>
            {submitting ? 'Starting…' : 'Run analysis'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
