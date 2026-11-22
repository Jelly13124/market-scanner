import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openTestApp } from './browser-fixture.mjs';

test('review a saved Analyze draft, edit it, cancel and explicitly confirm its saved version', async t => {
  const {page, url} = await openTestApp(t);
  const entry = {combiner: 'or', signals: [
    {type: 'relative_volume', window: 12, threshold: 2.5, direction: 'bullish', version: '1'},
  ]};
  const draft = {id: 7, name: 'AAPL draft', version: 1, source_report_id: 18,
    source_scan_result_id: 79, universe_snapshot_id: 11, spec_json: {
      name: 'AAPL draft', description: '', universe: {kind: 'snapshot', snapshot_id: 11}, entry,
      exit: [{type: 'stop_loss', mode: 'pct', value: 0.05}], filters: [],
      sizing: {type: 'fixed_pct', pct: 0.1}, backtest_config: {
        start_date: '2024-01-01', end_date: '2025-01-01', starting_capital_usd: 100000,
        max_concurrent_positions: 3, is_oos_split: 0.7, benchmark: 'spy', reverse_signal_as_exit: false,
        commission_bps: 5, slippage_bps: 5, full_position_policy: 'skip',
      },
    }};
  const runs = [];
  const result = {id: 50, confirmed_revision_id: 9, confirmed_version: 3, source_report_id: 18,
    source_scan_result_id: 79, created_at: '2026-11-17', verdict_label: 'insufficient', trades_json: []};
  let drafts = 0;
  await page.route('**/api/**', route => {
    const req = route.request();
    const path = new URL(req.url()).pathname.slice(4);
    if (path === '/auth/me') return route.fulfill({json: {id: 1, email: 'test@example.test', is_active: true, is_verified: true}});
    if (path === '/research/reports') return route.fulfill({json: [
      {id: 18, ticker: 'AAPL', scan_date: '2026-11-16', can_draft_strategy: true},
      {id: 19, ticker: 'IBM', scan_date: '2026-11-17', can_draft_strategy: false},
    ]});
    if (path.endsWith('/html')) return route.fulfill({body: '<p>Analysis</p>'});
    if (path === '/lab/reports/18/strategy-draft' && req.method() === 'POST') {
      drafts++; return route.fulfill({json: draft});
    }
    if (path === '/lab/strategies') return route.fulfill({json: drafts ? [draft] : []});
    if (path === '/lab/strategies/7') {
      if (req.method() === 'PATCH') {
        assert.equal(req.postDataJSON().expected_version, 1);
        Object.assign(draft, {spec_json: req.postDataJSON().spec_json, version: 2});
      }
      return route.fulfill({json: draft});
    }
    if (path === '/lab/strategies/7/backtest') {
      runs.push(req.postDataJSON());
      if (runs.length === 1) {
        draft.version = 3;
        return route.fulfill({status: 409, json: {detail: 'Draft changed. Review the latest version.'}});
      }
      return route.fulfill({json: result});
    }
    if (path === '/lab/backtests/50') return route.fulfill({json: result});
    if (path === '/lab/strategies/7/backtests') return route.fulfill({json: runs.length === 2 ? [result] : []});
    if (path === '/screener/universe-snapshots/11') return route.fulfill({json: {id: 11, tickers: ['AAPL', 'IBM']}});
    return route.fulfill({json: []});
  });
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test');
    localStorage.setItem('ai-hedge-fund-tabs', JSON.stringify([{id:'reports', type:'reports', title:'Reports'}]));
    localStorage.setItem('ai-hedge-fund-active-tab', 'reports');
  });
  await page.goto(url);
  await page.getByRole('cell', {name: 'IBM'}).click();
  const create = page.getByRole('button', {name: 'Create strategy draft'});
  assert.equal(await create.count(), 0);
  await page.keyboard.press('Escape');
  await page.getByRole('cell', {name: 'AAPL'}).click();
  assert.equal(await create.count(), 1, 'a report with frozen rules should offer a strategy draft');
  await create.click();
  const review = page.getByRole('button', {name: 'Review backtest'});
  await review.waitFor();
  assert.equal(drafts, 1);
  assert.deepEqual(runs, []);
  assert.equal(await page.getByLabel('Volume multiple').inputValue(), '2.5');
  assert.equal(await page.getByLabel('Entry rule', {exact: true}).locator('option[value="ma_cross"]').count(), 0);
  const allocation = page.getByLabel('Equity per position (%)');
  assert.equal(await allocation.inputValue(), '10');
  await allocation.fill('8');
  await page.getByLabel('Maximum positions', {exact: true}).fill('4');
  await page.getByLabel('Commission (bps)').fill('0');
  assert.equal(await review.isDisabled(), true);
  await page.getByRole('button', {name: 'Save parameters'}).click();
  await review.click();
  const dialog = page.getByRole('dialog');
  await dialog.getByText('AAPL, IBM', {exact: true}).waitFor();
  assert.ok((await dialog.innerText()).includes('2025-01-01'));
  assert.ok((await dialog.innerText()).includes('0 bps'));
  await dialog.getByRole('button', {name: 'Cancel'}).click();
  assert.deepEqual(runs, []);
  assert.deepEqual(draft.spec_json.universe, {kind:'snapshot', snapshot_id:11});
  assert.deepEqual(draft.spec_json.entry, entry);
  assert.equal(draft.spec_json.sizing.pct, 0.08);
  assert.equal(draft.spec_json.backtest_config.max_concurrent_positions, 4);
  await review.click();
  await page.getByRole('button', {name: 'Confirm and run backtest'}).click();
  await page.getByText(/Draft changed. Review the latest version/).first().waitFor();
  assert.deepEqual(runs, [{confirm_version: 2}]);
  await review.click();
  await dialog.getByRole('heading', {name: /v3$/}).waitFor();
  await dialog.getByRole('button', {name: 'Confirm and run backtest'}).click();
  await page.getByText(/Confirmed revision #9/).waitFor();
  assert.deepEqual(runs, [{confirm_version: 2}, {confirm_version: 3}]);
  await page.getByText('Backtest history (1)', {exact: true}).waitFor();
});
