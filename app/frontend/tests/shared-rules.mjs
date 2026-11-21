import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openTestApp } from './browser-fixture.mjs';

test('Scanner and Backtest save and reopen identical directed daily rules', async t => {
  const {page, url} = await openTestApp(t);
  const spec = {name: 'Parity', description: '', universe: {kind: 'sp500'},
    entry: {combiner: 'and', signals: [{type: 'rsi', period: 14, level: 30, direction: 'oversold_buy'}]},
    exit: [{type: 'time_stop', bars: 5}, {type: 'stop_loss', mode: 'atr', value: 2}], filters: [],
    sizing: {type: 'equal_weight'}, backtest_config: {start_date: '2025-01-01', end_date: '2026-01-01'}};
  const strategy = {id: 7, name: 'Parity strategy', spec_json: spec, version: 1};
  let config;
  await page.route('**/api/**', route => {
    const req = route.request();
    const path = new URL(req.url()).pathname.slice(4);
    if (path === '/auth/me') return route.fulfill({json: {id: 1, email: 'test@example.test', is_active: true, is_verified: true}});
    if (path === '/scanner/configs') {
      if (req.method() === 'POST') config = {...req.postDataJSON(), id: 3};
      return route.fulfill({json: req.method() === 'POST' ? config : config ? [config] : []});
    }
    if (path === '/lab/strategies') return route.fulfill({json: [strategy]});
    if (path === '/lab/strategies/7') {
      if (req.method() === 'PATCH') Object.assign(strategy, req.postDataJSON(), {version: 2});
      return route.fulfill({json: strategy});
    }
    return route.fulfill({json: []});
  });
  await page.addInitScript(() => localStorage.setItem('auth_token', 'test'));
  await page.goto(url);
  await page.getByTitle('Run universe-wide screening').first().click();
  await page.getByRole('button', {name: 'New', exact: true}).click();
  await page.getByLabel('Name', {exact: true}).fill('Parity scanner');
  const mode = page.getByLabel('Signal rules', {exact: true});
  assert.equal(await mode.count(), 1, 'Scanner should offer shared daily rules');
  await mode.selectOption('daily');

  async function chooseRules() {
    await page.getByLabel('Match conditions').selectOption('or');
    await page.getByRole('checkbox', {name: 'Relative volume', exact: true}).check();
    const volume = page.getByRole('group', {name: 'Relative volume', exact: true});
    await volume.getByLabel('Lookback sessions').fill('12');
    await volume.getByLabel('Volume multiple').fill('2.5');
    await volume.getByLabel('Signal direction').selectOption('neutral');
    await page.getByRole('checkbox', {name: 'Relative strength vs SPY', exact: true}).check();
    const strength = page.getByRole('group', {name: 'Relative strength vs SPY'});
    await strength.getByLabel('Spread (percentage points)').fill('7');
    await strength.getByLabel('Signal direction').selectOption('bearish');
  }
  await chooseRules();
  await Promise.all([page.waitForResponse(r => r.request().method() === 'POST' && r.url().endsWith('/scanner/configs')),
    page.getByRole('button', {name: 'Create config'}).click()]);
  const expected = {combiner: 'or', signals: [
    {type: 'relative_volume', version: '1', window: 12, threshold: 2.5, direction: 'neutral'},
    {type: 'relative_strength', version: '1', window: 20, threshold: 0.07, direction: 'bearish'},
  ]};
  assert.deepEqual(config.weights.rule_group, expected);
  await page.getByRole('button', {name: 'Edit', exact: true}).click();
  assert.equal(await mode.inputValue(), 'daily');
  assert.equal(await page.getByLabel('Volume multiple').inputValue(), '2.5');
  await page.getByRole('button', {name: 'Cancel'}).click();
  await page.getByTitle('Configure and run historical strategy backtests').first().click();
  await page.getByText('Parity strategy', {exact: true}).click();
  await page.getByLabel('Entry rule').selectOption('daily');
  const importGroup = page.getByLabel('Use rules from Scanner', {exact: true});
  assert.equal(await importGroup.count(), 1, 'Backtest should reuse a saved Scanner group');
  await importGroup.selectOption('3');
  assert.equal(await page.getByLabel('Volume multiple').inputValue(), '2.5');
  assert.equal(await page.getByLabel('Match conditions').inputValue(), 'or');
  await Promise.all([page.waitForResponse(r => r.request().method() === 'PATCH' && r.url().endsWith('/lab/strategies/7')),
    page.getByRole('button', {name: 'Save parameters'}).click()]);
  assert.deepEqual(strategy.spec_json.entry, expected);
  assert.deepEqual(strategy.spec_json.exit, spec.exit, 'Importing entry rules must preserve the existing exits');
  await page.getByRole('group', {name: 'Relative strength vs SPY'}).waitFor();
  assert.equal(await page.getByLabel('Spread (percentage points)').inputValue(), '7');
});
