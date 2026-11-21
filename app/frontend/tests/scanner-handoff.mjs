// Run from app/frontend with npm run test:handoff. Uses a disposable Chrome profile.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { openTestApp } from './browser-fixture.mjs';

test('a Scanner row exposes its frozen universe and submits the owned result reference', async t => {
  const {page, url} = await openTestApp(t);
  const run = {id: 5, config_id: 1, status: 'COMPLETE', universe_size: 2, universe_snapshot_id: 11};
  const trigger = {detector: 'relative_volume', severity_z: 3, direction: 'bullish',
    reason: 'Volume exceeded baseline', signal_session: '2026-10-30', components: {ratio: 3}};
  const entry = {id: 79, scan_run_id: 5, ticker: 'AAPL', market: 'us', rank: 1,
    composite_score: 70, event_score: 70, direction: 'bullish', triggers: [trigger]};
  const fixtures = {
    '/auth/me': {id: 1, email: 'fixture@example.test', is_active: true, is_verified: true},
    '/research/model-status': {ready: true},
    '/scanner/configs': [{id: 1, name: 'Volume', universe_kind: 'watchlist', top_n: 10}],
    '/scanner/configs/1/latest-run': {...run, status: 'PENDING'},
    '/scanner/runs/5/entries': {...run, entries: [entry]},
    '/scanner/runs/5/quotes': {},
    '/screener/universe-snapshots/11': {id: 11, tickers: ['AAPL', 'IBM'], source_snapshot_id: 8},
    '/screener/universe-snapshots/8': {id: 8, tickers: ['AAPL'], filters: {sector_in: ['Technology']}, screener_snapshot_date: '2026-10-30'},
  };
  let analyzeCalls = 0;
  let terminalEvent = {event: 'complete', run_id: 5, entries: 1};
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.slice('/api'.length);
    if (path === '/scanner/runs/5/stream') {
      return route.fulfill({contentType: 'text/event-stream', body: `event: ${terminalEvent.event}\ndata: ${JSON.stringify(terminalEvent)}\n\n`});
    }
    if (path === '/research/analyze') {
      analyzeCalls++;
      return route.fulfill({status: 503, json: {detail: 'Test stops at model dispatch'}});
    }
    return route.fulfill({json: fixtures[path] ?? []});
  });
  await page.addInitScript(() => {
    localStorage.setItem('auth_token', 'test-session');
    localStorage.setItem('analyze-oneclick-use-canvas', '1');
    localStorage.setItem('analyze-config-snapshot', JSON.stringify({
      included_sections: ['valuation', 'debate'], persona_overrides: {valuation: 'burry'},
      use_personas: true, debate_rounds: 3,
    }));
  });
  await page.goto(url, {waitUntil: 'domcontentloaded'});
  const queuedRun = page.waitForResponse(r => r.url().endsWith('/scanner/configs/1/latest-run'));
  await page.getByTitle('Run universe-wide screening').first().click();
  await queuedRun;
  await page.getByText('View scanned universe', {exact: true}).click({timeout: 5000});
  await page.getByText('AAPL, IBM', {exact: true}).waitFor();
  await page.getByText(/sector_in.*Technology/).last().waitFor();
  await page.locator('summary').filter({hasText: 'RELA'}).click();
  await page.getByText('Signal session · 2026-10-30', {exact: true}).waitFor();
  await page.getByText('ratio = 3', {exact: true}).waitFor();
  assert.equal(analyzeCalls, 0);

  const [request] = await Promise.all([
    page.waitForRequest(r => r.url().endsWith('/api/research/analyze')),
    page.getByRole('cell', {name: 'AAPL', exact: true}).click(),
  ]);
  const body = request.postDataJSON();
  assert.equal(body.source_scan_result_id, entry.id);
  assert.equal(body.source_scan_evidence, undefined);
  assert.equal(body.ticker, 'AAPL');
  assert.equal(body.market, 'us');
  assert.equal(body.debate_rounds, 3);
  assert.equal(body.use_personas, true);
  assert.deepEqual(body.included_sections, ['valuation', 'debate']);
  assert.equal(analyzeCalls, 1);

  terminalEvent = {event: 'error', run_id: 5, message: 'Test feed unavailable'};
  await page.reload({waitUntil: 'domcontentloaded'});
  await page.getByTitle('Run universe-wide screening').first().click();
  await page.getByText(terminalEvent.message, {exact: true}).waitFor();
  assert.ok(await page.getByRole('button', {name: 'Run now', exact: true}).isEnabled());
});
