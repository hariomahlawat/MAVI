/**
 * A real Chromium for the self-tests: the rules under test only mean anything
 * against a rendered page. Pages are served from a throwaway directory by the
 * harness's own fixture server, so settling is tested against the same
 * request accounting the sweep uses.
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { launch } from '../cdp.mjs';
import { startServer } from '../server.mjs';
import { OBSERVERS } from '../settle.mjs';

export async function openBrowser() {
  const dist = mkdtempSync(join(tmpdir(), 'mavi-vqa-test-'));
  mkdirSync(join(dist, 'fixtures'), { recursive: true });
  const lane = { scenario: {} };
  lane.server = await startServer({ distDir: dist, fixtureDir: join(dist, 'fixtures'), scenario: () => lane.scenario, footage: () => null });
  lane.browser = await launch();
  await lane.browser.addInitScript(OBSERVERS);
  lane.page = async (html, { width = 1366, height = 768, api = {} } = {}) => {
    lane.scenario = api;
    lane.server.resetSequences();
    writeFileSync(join(dist, 'index.html'), `<!doctype html><html><head><meta charset="utf-8"></head><body>${html}</body></html>`);
    await lane.browser.viewport(width, height);
    await lane.browser.goto('about:blank');
    await lane.browser.goto(lane.server.origin + '/case');
  };
  lane.close = async () => {
    await lane.browser.close();
    await lane.server.close();
    rmSync(dist, { recursive: true, force: true });
  };
  return lane;
}
