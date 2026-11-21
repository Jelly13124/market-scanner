import { chromium } from 'playwright-core';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { build, preview } from 'vite';

export async function openTestApp(t) {
  process.env.VITE_API_URL = '/api';
  const outDir = await mkdtemp(join(tmpdir(), 'scanner-handoff-'));
  let server;
  let browser;
  t.after(async () => {
    await browser?.close();
    if (server) await new Promise(resolve => server.httpServer.close(resolve));
    await rm(outDir, {recursive: true, force: true});
  });
  const config = {build: {outDir}, logLevel: 'error'};
  await build(config);
  server = await preview({...config, preview: {host: '127.0.0.1', port: 0}});
  browser = await chromium.launch({channel: 'chrome'});
  const page = await browser.newPage({locale: 'en-US'});
  return {page, url: server.resolvedUrls.local[0]};
}
