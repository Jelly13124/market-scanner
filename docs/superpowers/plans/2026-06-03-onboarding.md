# New-User Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a brand-new user understand the app, be forced to add their LLM API key first, and run a first analysis in one click — via a Home screen, a getting-started checklist, a hard key-gate, and a first-visit Analyze hint.

**Architecture:** Frontend-only (`app/frontend/`, React+TS+Vite). A new `ApiKeysStatusProvider` exposes `hasKeys` (≥1 active LLM-provider key); Run actions disable until then. A new `HomeScreen` renders in `tab-content.tsx`'s existing `!activeTab` branch (Home = the no-tabs state, reached via `closeAllTabs()`). Everything reuses existing services + the `screener/empty-state.tsx` styling idiom. No backend/DB changes.

**Tech Stack:** React 18, TypeScript, Vite, react-i18next, lucide-react, Tailwind. Spec: `docs/superpowers/specs/2026-06-03-onboarding-design.md`.

**Constraints (bake into every task):**
- Branch: `main`.
- Typecheck from `app/frontend/`: `node node_modules/typescript/bin/tsc --noEmit` (npm is NOT on the non-interactive PATH). **Zero NEW tsc errors** per task.
- **No jest harness** for frontend → each task's "test" = tsc clean + a concrete manual-smoke assertion (start `npm run dev` from `app/frontend/`, open `http://localhost:5173`; backend on `:8001`).
- Commit per task; conventional message; **NO Co-Authored-By trailer**; never `--no-verify`.
- Explicit `git add <paths>` (never `-A`; never stage `.claude/settings.local.json`).
- Every new user-facing string gets keys in BOTH `app/frontend/src/i18n/locales/en.json` and `zh.json`.
- Reuse: `analyzeBus`/`useRequestAnalyze` (Try-NVDA), `useTabsContext().openTab`/`closeAllTabs` + `TabService` (cards/sidebar), `apiKeysService`/`analyzeService`/`watchlistService`/`reportSchedulesService` (probes), `screener/empty-state.tsx` styling.

---

## File Structure

**New files**
- `app/frontend/src/contexts/api-keys-status-context.tsx` — `ApiKeysStatusProvider` + `useApiKeysStatus()`. One job: hold `{hasKeys, loading, refresh}`.
- `app/frontend/src/components/home/home-screen.tsx` — Home view: hero + checklist mount + feature cards.
- `app/frontend/src/components/home/getting-started-checklist.tsx` — the 4-step checklist (status probes + actions).
- `app/frontend/src/components/panels/left/home-action.tsx` — sidebar "Home" entry (`closeAllTabs`).

**Modified files**
- `app/frontend/src/components/Layout.tsx` — mount `ApiKeysStatusProvider`.
- `app/frontend/src/components/tabs/tab-content.tsx` — render `<HomeScreen/>` in the `!activeTab` branch.
- `app/frontend/src/components/panels/analyze/analyze-toolbar.tsx` — `hasKeys`/`onAddKey` props; gate Run + Schedule.
- `app/frontend/src/components/panels/analyze/analyze-panel.tsx` — consume `useApiKeysStatus`, thread props, open Settings.
- `app/frontend/src/components/panels/scanner/scanner-panel.tsx` — gate Run-now on `hasKeys` + add-key affordance.
- `app/frontend/src/components/settings/api-keys.tsx` — `refresh()` after save/clear.
- `app/frontend/src/components/panels/left/left-sidebar.tsx` — add `<HomeAction/>`.
- `app/frontend/src/i18n/locales/en.json` + `zh.json` — `onboarding` namespace + `sidebar.home`.

---

### Task 1: `ApiKeysStatusProvider` + `useApiKeysStatus` (foundation)

**Files:**
- Create: `app/frontend/src/contexts/api-keys-status-context.tsx`
- Modify: `app/frontend/src/components/Layout.tsx`

- [ ] **Step 1: Create the context**

`app/frontend/src/contexts/api-keys-status-context.tsx`:
```tsx
// Global "does the user have a usable LLM key?" status. Drives the hard
// onboarding gate (Run actions disable until true) + the Home checklist's
// first step. Fetches once on mount; `refresh()` re-checks after the user
// saves/clears a key in Settings.

import { apiKeysService } from '@/services/api-keys-api';
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';

// LLM-provider keys — the UPPERCASE env-var names from LLM_API_KEYS in
// settings/api-keys.tsx. Analysis needs one of these; a data-only key
// (FINANCIAL_DATASETS_API_KEY) does NOT satisfy the gate.
const LLM_PROVIDERS = new Set<string>([
  'ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY', 'GROQ_API_KEY', 'GOOGLE_API_KEY',
  'OPENAI_API_KEY', 'MOONSHOT_API_KEY', 'OPENROUTER_API_KEY', 'GIGACHAT_API_KEY',
]);

interface ApiKeysStatusValue {
  /** true when ≥1 active LLM-provider key is saved. */
  hasKeys: boolean;
  loading: boolean;
  refresh: () => Promise<void>;
}

const ApiKeysStatusContext = createContext<ApiKeysStatusValue | null>(null);

export function useApiKeysStatus(): ApiKeysStatusValue {
  const ctx = useContext(ApiKeysStatusContext);
  if (!ctx) throw new Error('useApiKeysStatus must be used within an ApiKeysStatusProvider');
  return ctx;
}

export function ApiKeysStatusProvider({ children }: { children: ReactNode }) {
  const [hasKeys, setHasKeys] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const keys = await apiKeysService.getAllApiKeys();
      setHasKeys(keys.some((k) => k.is_active && k.has_key && LLM_PROVIDERS.has(k.provider)));
    } catch {
      // Conservative: a failed probe keeps the gate ON (hasKeys=false). The
      // user always has a visible route to add a key, so they're never trapped.
      setHasKeys(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  return (
    <ApiKeysStatusContext.Provider value={{ hasKeys, loading, refresh }}>
      {children}
    </ApiKeysStatusContext.Provider>
  );
}
```

- [ ] **Step 2: Mount it in `Layout.tsx`**

Add the import after the `AnalyzeRunsProvider` import (line 5 area):
```tsx
import { AnalyzeRunsProvider } from '@/contexts/analyze-runs-context';
import { ApiKeysStatusProvider } from '@/contexts/api-keys-status-context';
```
Wrap `LayoutContent` (inside `TabsProvider`, so the provider/Home can use tabs). Replace the `Layout()` body:
```tsx
export function Layout({ children }: LayoutProps) {
  return (
    <AnalyzeRunsProvider>
      <SidebarProvider defaultOpen={true}>
        <TabsProvider>
          <ApiKeysStatusProvider>
            <LayoutProvider>
              <LayoutContent>{children}</LayoutContent>
            </LayoutProvider>
          </ApiKeysStatusProvider>
        </TabsProvider>
      </SidebarProvider>
    </AnalyzeRunsProvider>
  );
}
```

- [ ] **Step 3: Verify** — `cd app/frontend && node node_modules/typescript/bin/tsc --noEmit` → zero new errors. Manual: app still loads (the provider fetches `/api-keys` on mount); no console error; nothing visibly changes yet.

- [ ] **Step 4: Commit**
```bash
git add app/frontend/src/contexts/api-keys-status-context.tsx app/frontend/src/components/Layout.tsx
git commit -m "feat(onboarding): global API-keys status provider (hasKeys gate)"
```

---

### Task 2: Hard gate — Analyze Run button

**Files:**
- Modify: `app/frontend/src/components/panels/analyze/analyze-toolbar.tsx`
- Modify: `app/frontend/src/components/panels/analyze/analyze-panel.tsx`
- Modify: `app/frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] **Step 1: i18n — add the `onboarding.gate` keys**

In `en.json`, add a top-level `"onboarding"` object (place it after the `"analyze"` block's closing `},` — pick any valid spot at the root level):
```json
  "onboarding": {
    "gate": {
      "tooltip": "Add an API key first",
      "addKey": "Add API key"
    }
  },
```
In `zh.json`, the mirror:
```json
  "onboarding": {
    "gate": {
      "tooltip": "请先添加 API Key",
      "addKey": "添加 API Key"
    }
  },
```
(Later tasks extend this same `onboarding` object with `home`, `checklist`, `analyzeHint`.)

- [ ] **Step 2: Toolbar — add `hasKeys`/`onAddKey` props + gate**

In `analyze-toolbar.tsx`: add `KeyRound` to the lucide import:
```tsx
import { CalendarClock, KeyRound, Loader2, Play, Plus, RotateCcw } from 'lucide-react';
```
Add to `AnalyzeToolbarProps` (after `onSchedule?`):
```tsx
  /** When false, Run is disabled + an "Add API key" button appears. Defaults true. */
  hasKeys?: boolean;
  /** Open Settings → API Keys. Shown only when hasKeys is false. */
  onAddKey?: () => void;
```
Destructure with a default in the component signature:
```tsx
  onSchedule,
  hasKeys = true,
  onAddKey,
  ...flowListProps
```
Replace the Run `<Button>` block (the one with `onClick={onRun}`) — add the add-key affordance before it and extend `disabled`:
```tsx
      {!hasKeys && onAddKey && (
        <Button
          onClick={onAddKey}
          size="sm"
          variant="outline"
          className="h-7 border-amber-500/60 text-amber-600"
          title={t('onboarding.gate.tooltip')}
        >
          <KeyRound className="size-3 mr-1" />
          {t('onboarding.gate.addKey')}
        </Button>
      )}
      <Button
        onClick={onRun}
        disabled={running || !canRun || !hasKeys}
        size="sm"
        className="h-7"
        title={!hasKeys ? t('onboarding.gate.tooltip') : (canRun ? t('analyze.toolbar.run') : t('analyze.errors.noInput'))}
      >
```
(Leave the Run button's inner `{running ? ... : ...}` content unchanged.)

- [ ] **Step 3: Panel — consume status + provide `onAddKey`**

In `analyze-panel.tsx`: add imports (with the other `@/contexts` / `@/services` imports):
```tsx
import { useApiKeysStatus } from '@/contexts/api-keys-status-context';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
```
Inside `AnalyzePanel`, near the other hooks (after `const { t } = useTranslation();`):
```tsx
  const { hasKeys } = useApiKeysStatus();
  const { openTab } = useTabsContext();
  const openApiKeys = useCallback(() => {
    openTab({ id: 'settings', ...TabService.createSettingsTab() });
  }, [openTab]);
```
Thread the props into `<AnalyzeToolbar .../>` (add to its prop list):
```tsx
        onSchedule={handleSchedule}
        hasKeys={hasKeys}
        onAddKey={openApiKeys}
```

- [ ] **Step 4: Verify** — tsc clean. Manual: with NO LLM key saved → open Analyze → **Run is disabled**, hovering shows "Add an API key first", and an amber **"Add API key"** button appears that opens the Settings tab (lands on API Keys).

- [ ] **Step 5: Commit**
```bash
git add app/frontend/src/components/panels/analyze/analyze-toolbar.tsx app/frontend/src/components/panels/analyze/analyze-panel.tsx app/frontend/src/i18n/locales/en.json app/frontend/src/i18n/locales/zh.json
git commit -m "feat(onboarding): gate Analyze Run on having an LLM key"
```

---

### Task 3: Hard gate — Scanner Run + unlock on key save

**Files:**
- Modify: `app/frontend/src/components/panels/scanner/scanner-panel.tsx`
- Modify: `app/frontend/src/components/settings/api-keys.tsx`

- [ ] **Step 1: Scanner — gate Run-now + add-key affordance**

In `scanner-panel.tsx`: add imports:
```tsx
import { useApiKeysStatus } from '@/contexts/api-keys-status-context';
import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { KeyRound } from 'lucide-react';
```
Inside `ScannerPanel`, near `const requestAnalyze = useRequestAnalyze();`:
```tsx
  const { hasKeys } = useApiKeysStatus();
  const { openTab } = useTabsContext();
  const openApiKeys = () => openTab({ id: 'settings', ...TabService.createSettingsTab() });
```
Gate the Run-now button — change its `disabled`:
```tsx
        <Button onClick={handleRunNow} disabled={!selectedConfig || isRunning || !hasKeys} size="sm">
          <Play size={14} className="mr-1" />
          {isRunning ? 'Running…' : 'Run now'}
        </Button>
```
Immediately AFTER that Run-now `<Button>`, add the affordance:
```tsx
        {!hasKeys && (
          <Button
            onClick={openApiKeys}
            size="sm"
            variant="outline"
            className="h-8 border-amber-500/60 text-amber-600"
            title={t('onboarding.gate.tooltip')}
          >
            <KeyRound size={14} className="mr-1" />
            {t('onboarding.gate.addKey')}
          </Button>
        )}
```
(`t` is already in scope — `scanner-panel.tsx` uses `const { t } = useTranslation();`.)

- [ ] **Step 2: Settings — refresh status after save/clear**

In `settings/api-keys.tsx`: add the hook import:
```tsx
import { useApiKeysStatus } from '@/contexts/api-keys-status-context';
```
Inside `ApiKeysSettings()`, near the top with the other hooks:
```tsx
  const { refresh: refreshKeyStatus } = useApiKeysStatus();
```
In `saveKey`, after `setSaveStatus(prev => ({ ...prev, [key]: 'saved' }));` add:
```tsx
      void refreshKeyStatus();
```
In `clearKey`, after its successful `apiKeysService.deleteApiKey(key)` await (before/after the local state reset), add:
```tsx
      void refreshKeyStatus();
```

- [ ] **Step 3: Verify** — tsc clean. Manual: with NO key → Scanner "Run now" disabled + amber "Add API key" button. Then Settings → save a DeepSeek/OpenAI key → **without reloading**, return to Analyze + Scanner → Run buttons are now **enabled** (the gate lifted via `refresh()`).

- [ ] **Step 4: Commit**
```bash
git add app/frontend/src/components/panels/scanner/scanner-panel.tsx app/frontend/src/components/settings/api-keys.tsx
git commit -m "feat(onboarding): gate Scanner Run + lift gate on key save"
```

---

### Task 4: Home screen — hero + feature cards + render-when-no-tabs

**Files:**
- Create: `app/frontend/src/components/home/home-screen.tsx`
- Modify: `app/frontend/src/components/tabs/tab-content.tsx`
- Modify: `app/frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] **Step 1: i18n — add `onboarding.home`**

Extend the `onboarding` object in `en.json`:
```json
    "home": {
      "title": "Welcome to Quant Lab",
      "subtitle": "AI deep-dive research · market scanning · backtesting — with your own API key.",
      "exploreLabel": "Or jump into a tool",
      "cards": {
        "analyze": { "title": "Analyze", "desc": "Deep-dive one stock into a full report" },
        "scanner": { "title": "Scanner", "desc": "Batch-scan a universe + auto-analyze" },
        "screener": { "title": "Screener", "desc": "Filter stocks by your criteria" },
        "lab": { "title": "Strategy Lab", "desc": "Build + backtest a strategy" }
      }
    },
```
Mirror in `zh.json`:
```json
    "home": {
      "title": "欢迎使用 Quant Lab",
      "subtitle": "AI 股票深度研究 · 市场扫描 · 策略回测 —— 用你自己的 API Key。",
      "exploreLabel": "或直接进入某个功能",
      "cards": {
        "analyze": { "title": "Analyze", "desc": "深挖一只股，生成完整报告" },
        "scanner": { "title": "Scanner", "desc": "批量扫描一个股票池 + 自动分析" },
        "screener": { "title": "Screener", "desc": "按你的条件筛选股票" },
        "lab": { "title": "策略实验室", "desc": "搭建 + 回测策略" }
      }
    },
```

- [ ] **Step 2: Create `home-screen.tsx`**

`app/frontend/src/components/home/home-screen.tsx`:
```tsx
// Home — shown in the main area when no tab is open (tab-content's !activeTab
// branch). Hero + getting-started checklist + feature cards. Reuses the tab
// system to open features.

import { useTabsContext } from '@/contexts/tabs-context';
import { TabService } from '@/services/tab-service';
import { useTranslation } from 'react-i18next';

import { GettingStartedChecklist } from './getting-started-checklist';

export function HomeScreen() {
  const { t } = useTranslation();
  const { openTab } = useTabsContext();

  const cards = [
    { id: 'analyze' as const, make: () => TabService.createAnalyzeTab() },
    { id: 'scanner' as const, make: () => TabService.createScannerTab() },
    { id: 'screener' as const, make: () => TabService.createScreenerTab() },
    { id: 'lab' as const, make: () => TabService.createLabTab() },
  ];

  return (
    <div className="h-full w-full overflow-auto bg-background">
      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        <div>
          <h1 className="text-2xl font-semibold text-primary">{t('onboarding.home.title')}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t('onboarding.home.subtitle')}</p>
        </div>

        <GettingStartedChecklist />

        <div>
          <div className="text-xs uppercase tracking-wider text-muted-foreground mb-2">
            {t('onboarding.home.exploreLabel')}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {cards.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => openTab({ id: c.id, ...c.make() })}
                className="rounded-lg border p-3 text-left hover:bg-accent/60 transition-colors"
              >
                <div className="text-sm font-medium">{t(`onboarding.home.cards.${c.id}.title`)}</div>
                <div className="text-xs text-muted-foreground mt-1">{t(`onboarding.home.cards.${c.id}.desc`)}</div>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```
> NOTE: this imports `./getting-started-checklist`, created in Task 5. To keep Task 4 independently compilable, FIRST create a 1-line stub `app/frontend/src/components/home/getting-started-checklist.tsx`:
> ```tsx
> export function GettingStartedChecklist() { return null; }
> ```
> Task 5 replaces the stub with the real component.

- [ ] **Step 3: Render Home in `tab-content.tsx`**

Add the import:
```tsx
import { HomeScreen } from '@/components/home/home-screen';
```
Replace the entire `if (!activeTab) { return (...) }` block (the welcome-placeholder branch) with:
```tsx
  if (!activeTab) {
    return (
      <div className={cn('h-full w-full', className)}>
        <HomeScreen />
      </div>
    );
  }
```
(The old `FolderOpen`/`FileText`/`t('tabBar.welcome')` markup is removed. If `FolderOpen`/`FileText` become unused imports, drop them from the lucide import to keep tsc/lint clean.)

- [ ] **Step 4: Verify** — tsc clean. Manual: close all tabs (or fresh login) → Home shows: hero + (empty checklist stub) + 4 feature cards. Clicking **Analyze** card opens the Analyze tab; same for Scanner/Screener/Lab.

- [ ] **Step 5: Commit**
```bash
git add app/frontend/src/components/home/home-screen.tsx app/frontend/src/components/home/getting-started-checklist.tsx app/frontend/src/components/tabs/tab-content.tsx app/frontend/src/i18n/locales/en.json app/frontend/src/i18n/locales/zh.json
git commit -m "feat(onboarding): Home screen (hero + feature cards) when no tab is open"
```

---

### Task 5: Home screen — getting-started checklist

**Files:**
- Modify (replace stub): `app/frontend/src/components/home/getting-started-checklist.tsx`
- Modify: `app/frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] **Step 1: i18n — add `onboarding.checklist`**

Extend `onboarding` in `en.json`:
```json
    "checklist": {
      "title": "Getting started",
      "allSet": "✓ You're all set",
      "dismiss": "Dismiss",
      "steps": {
        "key": "Add your API key (nothing runs without it)",
        "analyze": "Run your first analysis",
        "watch": "Save a watchlist",
        "schedule": "Set up a scheduled report"
      },
      "actions": {
        "addKey": "Add key →",
        "tryNvda": "Try NVDA →",
        "openWatchlist": "Open Watchlist →",
        "openSchedules": "Open Settings →"
      }
    },
```
Mirror in `zh.json`:
```json
    "checklist": {
      "title": "上手清单",
      "allSet": "✓ 都搞定了",
      "dismiss": "收起",
      "steps": {
        "key": "添加你的 API Key（没它什么都跑不了）",
        "analyze": "跑第一份分析",
        "watch": "保存一个自选股",
        "schedule": "设置定时报告"
      },
      "actions": {
        "addKey": "去添加 →",
        "tryNvda": "试试 NVDA →",
        "openWatchlist": "打开自选 →",
        "openSchedules": "打开设置 →"
      }
    },
```

- [ ] **Step 2: Replace the stub with the real checklist**

`app/frontend/src/components/home/getting-started-checklist.tsx`:
```tsx
// The Home "getting started" checklist. Each step's done-state comes from a
// real backend probe (key/report/watchlist/schedule); actions reuse the tab
// system + the analyze bus. Dismissable; auto-condenses once all done.

import { useApiKeysStatus } from '@/contexts/api-keys-status-context';
import { useTabsContext } from '@/contexts/tabs-context';
import { useRequestAnalyze } from '@/hooks/use-request-analyze';
import { analyzeService } from '@/services/analyze-service';
import { reportSchedulesService } from '@/services/report-schedules-api';
import { TabService } from '@/services/tab-service';
import { watchlistService } from '@/services/watchlist-service';
import { Check, X } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';

const DISMISS_KEY = 'onboarding-checklist-dismissed';

export function GettingStartedChecklist() {
  const { t } = useTranslation();
  const { hasKeys } = useApiKeysStatus();
  const { openTab, setActiveTab, isTabOpen } = useTabsContext();
  const requestAnalyze = useRequestAnalyze();

  const [hasReport, setHasReport] = useState(false);
  const [hasWatch, setHasWatch] = useState(false);
  const [hasSchedule, setHasSchedule] = useState(false);
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DISMISS_KEY) === '1'; } catch { return false; }
  });

  useEffect(() => {
    analyzeService.listReports(undefined, 1).then((r) => setHasReport(r.length > 0)).catch(() => {});
    watchlistService.list().then((w) => setHasWatch(w.length > 0)).catch(() => {});
    reportSchedulesService.list().then((s) => setHasSchedule(s.length > 0)).catch(() => {});
  }, []);

  const openTabOnce = (id: 'settings' | 'watchlist', make: () => Parameters<typeof openTab>[0]) => {
    if (isTabOpen(id, id)) setActiveTab(id);
    else openTab({ id, ...make() });
  };
  const openSettings = () => openTabOnce('settings', () => TabService.createSettingsTab());
  const openWatchlist = () => openTabOnce('watchlist', () => TabService.createWatchlistTab());

  const steps = [
    { id: 'key', done: hasKeys, action: openSettings, actionKey: 'addKey' },
    { id: 'analyze', done: hasReport, action: () => requestAnalyze('NVDA', 'us'), actionKey: 'tryNvda' },
    { id: 'watch', done: hasWatch, action: openWatchlist, actionKey: 'openWatchlist' },
    { id: 'schedule', done: hasSchedule, action: openSettings, actionKey: 'openSchedules' },
  ] as const;

  const doneCount = steps.filter((s) => s.done).length;

  if (dismissed) return null;

  if (doneCount === steps.length) {
    return (
      <div className="rounded-lg border px-4 py-3 text-sm text-green-600">
        {t('onboarding.checklist.allSet')}
      </div>
    );
  }

  const dismiss = () => {
    try { localStorage.setItem(DISMISS_KEY, '1'); } catch { /* ignore */ }
    setDismissed(true);
  };

  return (
    <div className="rounded-lg border p-4 bg-accent/20">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold">
          🚀 {t('onboarding.checklist.title')} · {doneCount}/{steps.length}
        </div>
        <button type="button" onClick={dismiss} title={t('onboarding.checklist.dismiss')}
          className="text-muted-foreground hover:text-foreground">
          <X className="size-4" />
        </button>
      </div>
      <ul className="space-y-2">
        {steps.map((s) => (
          <li key={s.id} className="flex items-center gap-3 text-sm">
            <span className={`grid place-items-center size-5 rounded-full border shrink-0 ${s.done ? 'bg-green-600 border-green-600 text-white' : 'text-muted-foreground'}`}>
              {s.done ? <Check className="size-3" /> : null}
            </span>
            <span className={`flex-1 ${s.done ? 'line-through text-muted-foreground' : ''}`}>
              {t(`onboarding.checklist.steps.${s.id}`)}
            </span>
            {!s.done && (
              <button type="button" onClick={s.action}
                className="text-xs text-primary hover:underline shrink-0">
                {t(`onboarding.checklist.actions.${s.actionKey}`)}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Verify** — tsc clean. Manual: Home shows the checklist `0/4`→ counts up as states are true. With a key saved, step ① is ticked + struck-through. Click **"Try NVDA →"** → Analyze tab opens + the run fires + shows in the runs sidebar. Click ✕ → checklist hides (persists across reload). Clearing `localStorage.onboarding-checklist-dismissed` brings it back.

- [ ] **Step 4: Commit**
```bash
git add app/frontend/src/components/home/getting-started-checklist.tsx app/frontend/src/i18n/locales/en.json app/frontend/src/i18n/locales/zh.json
git commit -m "feat(onboarding): getting-started checklist with live status probes"
```

---

### Task 6: Sidebar "Home" entry

**Files:**
- Create: `app/frontend/src/components/panels/left/home-action.tsx`
- Modify: `app/frontend/src/components/panels/left/left-sidebar.tsx`
- Modify: `app/frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] **Step 1: i18n — add `sidebar.home` + tooltip**

In `en.json`, inside the existing `"sidebar"` object add:
```json
    "home": "Home",
    "homeTooltip": "Back to the welcome / getting-started screen"
```
In `zh.json`, inside `"sidebar"`:
```json
    "home": "主页",
    "homeTooltip": "回到欢迎 / 上手页"
```

- [ ] **Step 2: Create `home-action.tsx`** (mirrors `analyze-action.tsx`, but uses `closeAllTabs` since Home is the no-tabs state)

`app/frontend/src/components/panels/left/home-action.tsx`:
```tsx
import { Button } from '@/components/ui/button';
import { useTabsContext } from '@/contexts/tabs-context';
import { Home } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export function HomeAction() {
  const { closeAllTabs } = useTabsContext();
  const { t } = useTranslation();

  return (
    <div className="p-2 flex justify-between flex-shrink-0 items-center border-b mt-4">
      <span className="text-primary text-sm font-medium ml-4">{t('sidebar.home')}</span>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" onClick={closeAllTabs}
          className="h-6 w-6 text-primary hover-bg" title={t('sidebar.homeTooltip')}>
          <Home size={14} />
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Add `<HomeAction/>` to `left-sidebar.tsx`**

Add the import alongside the other `*Action` imports, then put `<HomeAction />` FIRST in the action list:
```tsx
import { HomeAction } from './home-action';
```
```tsx
        <HomeAction />
        <WatchlistAction />
        <ScreenerAction />
        <SectorsAction />
        <ScannerAction />
        <AnalyzeAction />
        <ReportsAction />
        <LabAction />
```

- [ ] **Step 4: Verify** — tsc clean. Manual: the left sidebar shows a **Home** entry at the top; clicking its icon closes all tabs → returns to the Home screen.

- [ ] **Step 5: Commit**
```bash
git add app/frontend/src/components/panels/left/home-action.tsx app/frontend/src/components/panels/left/left-sidebar.tsx app/frontend/src/i18n/locales/en.json app/frontend/src/i18n/locales/zh.json
git commit -m "feat(onboarding): Home entry in the left sidebar"
```

---

### Task 7: Analyze first-visit hint banner

**Files:**
- Modify: `app/frontend/src/components/panels/analyze/analyze-panel.tsx`
- Modify: `app/frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] **Step 1: i18n — add `onboarding.analyzeHint`**

Extend `onboarding` in `en.json`:
```json
    "analyzeHint": {
      "text": "👋 This is the analysis canvas — type a ticker in the Input node, then click Run (top-right) to generate a deep report.",
      "dismiss": "Got it"
    },
```
Mirror in `zh.json`:
```json
    "analyzeHint": {
      "text": "👋 这是分析画布 —— 在 Input 节点里输入股票代码，然后点右上角的 Run 生成深度报告。",
      "dismiss": "知道了"
    },
```

- [ ] **Step 2: Add the dismissable banner to `analyze-panel.tsx`**

Add `Info`/`X` to the lucide import on the existing line (it currently imports `{ ExternalLink, Mail }`):
```tsx
import { ExternalLink, Info, Mail, X } from 'lucide-react';
```
Add the dismiss state near the other `useState`s in `AnalyzePanel`:
```tsx
  const [hintDismissed, setHintDismissed] = useState(() => {
    try { return localStorage.getItem('analyze-hint-dismissed') === '1'; } catch { return false; }
  });
  const dismissHint = () => {
    try { localStorage.setItem('analyze-hint-dismissed', '1'); } catch { /* ignore */ }
    setHintDismissed(true);
  };
```
Render the banner as the FIRST child inside the left-column wrapper, immediately before the `{/* 1. Toolbar */}` comment / `<AnalyzeToolbar .../>`:
```tsx
      {!hintDismissed && (
        <div className="flex items-start gap-2 border-b bg-amber-500/10 px-3 py-2 text-xs">
          <Info className="size-3.5 mt-0.5 shrink-0 text-amber-600" />
          <span className="flex-1">{t('onboarding.analyzeHint.text')}</span>
          <button type="button" onClick={dismissHint}
            className="shrink-0 text-muted-foreground hover:text-foreground" title={t('onboarding.analyzeHint.dismiss')}>
            <X className="size-3.5" />
          </button>
        </div>
      )}
```

- [ ] **Step 3: Verify** — tsc clean. Manual: first time on Analyze → an amber hint banner shows above the toolbar; click ✕ → it disappears + stays gone after reload (localStorage). Clearing `localStorage.analyze-hint-dismissed` brings it back.

- [ ] **Step 4: Commit**
```bash
git add app/frontend/src/components/panels/analyze/analyze-panel.tsx app/frontend/src/i18n/locales/en.json app/frontend/src/i18n/locales/zh.json
git commit -m "feat(onboarding): first-visit hint banner on the Analyze canvas"
```

---

## Self-Review

**Spec coverage:**
- Home screen (hero + checklist + feature cards) → Tasks 4 + 5. ✓
- Shown when no tabs open → Task 4 (tab-content `!activeTab`). ✓
- Sidebar Home entry → Task 6. ✓
- Hard key-gate (Analyze + Scanner Run disabled; route to add key; unlock on save) → Tasks 1–3. ✓
- `hasKeys` = LLM-provider key (not data-only) → Task 1 `LLM_PROVIDERS`. ✓
- Checklist steps (key/analysis/watchlist/schedule) auto-tick from real status → Task 5. ✓
- "Try NVDA" one-click → Task 5 (`requestAnalyze('NVDA','us')`). ✓
- Analyze first-visit hint → Task 7. ✓
- i18n en+zh for every string → Tasks 2,4,5,6,7. ✓
- Frontend-only, reuse existing services → confirmed (no backend tasks). ✓
- Tour (B) out of scope → not in plan. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases". Task 4 explicitly stubs `getting-started-checklist.tsx` so it compiles before Task 5 replaces it (intentional ordering, not a placeholder). ✓

**Type/name consistency:**
- `useApiKeysStatus()` → `{ hasKeys, loading, refresh }` defined Task 1; consumed Tasks 2,3,5 with those exact names. ✓
- `apiKeysService.getAllApiKeys()` → `ApiKeySummary[]` with `is_active`/`has_key`/`provider` (Task 1) — matches the real service. ✓
- Toolbar props `hasKeys`/`onAddKey` defined Task 2 toolbar, passed Task 2 panel. ✓
- `requestAnalyze('NVDA','us')` — matches `useRequestAnalyze` signature `(ticker, market)`. ✓
- `TabService.create{Settings,Analyze,Scanner,Screener,Lab,Watchlist}Tab()` — all confirmed to exist. ✓
- `closeAllTabs` (Task 6), `isTabOpen`/`setActiveTab`/`openTab` (Tasks 4,5) — all on `useTabsContext()`. ✓
- `watchlistService.list()`, `reportSchedulesService.list()`, `analyzeService.listReports()` — all confirmed. ✓
