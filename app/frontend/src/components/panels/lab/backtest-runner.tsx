// Phase 6G: Run-backtest button with live elapsed timer.

import { Button } from '@/components/ui/button';
import { backtestService } from '@/services/backtest-service';
import { Loader2, Play } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';

interface Props {
  strategyId: number;
  onComplete: (backtestId: number) => void;
}

export function BacktestRunner({ strategyId, onComplete }: Props) {
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const { t } = useTranslation();

  async function handleRun() {
    setRunning(true);
    setElapsed(0);
    const t0 = Date.now();
    const interval = setInterval(
      () => setElapsed(Math.floor((Date.now() - t0) / 1000)),
      1000,
    );
    try {
      const result = await backtestService.run(strategyId);
      onComplete(result.id);
      toast.success(t('lab.backtest.done', { label: result.verdict_label }));
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      clearInterval(interval);
      setRunning(false);
    }
  }

  const mm = Math.floor(elapsed / 60);
  const ss = String(elapsed % 60).padStart(2, '0');

  return (
    <div className="p-3 flex items-center gap-3 border-b">
      <Button onClick={handleRun} disabled={running}>
        {running ? (
          <>
            <Loader2 className="size-3 mr-1 animate-spin" />
            {t('lab.backtest.running')} {mm}:{ss}
          </>
        ) : (
          <>
            <Play className="size-3 mr-1" /> {t('lab.backtest.run')}
          </>
        )}
      </Button>
      <span className="text-xs text-muted-foreground">
        {t('lab.backtest.expectedDuration')}
      </span>
    </div>
  );
}
