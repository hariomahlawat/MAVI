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

export async function openBrowser({ responseOrder = 'natural' } = {}) {
  const dist = mkdtempSync(join(tmpdir(), 'mavi-vqa-test-'));
  mkdirSync(join(dist, 'fixtures'), { recursive: true });
  const lane = { scenario: {} };
  lane.server = await startServer({ distDir: dist, fixtureDir: join(dist, 'fixtures'), scenario: () => lane.scenario, footage: () => null, responseOrder });
  // A browser that fails to start must not leave the server listening (it
  // would hold the test run open) or the temporary directory behind.
  try {
    lane.browser = await launch();
    await lane.browser.addInitScript(OBSERVERS);
  } catch (error) {
    await lane.browser?.close().catch(() => {});
    await lane.server.close().catch(() => {});
    rmSync(dist, { recursive: true, force: true });
    throw error;
  }
  // The browser's page zoom (T3): 100% unless a test asks for another.
  lane.zoom = 1;
  lane.page = async (html, { width = 1366, height = 768, api = {}, zoom = 1 } = {}) => {
    lane.scenario = api;
    lane.server.resetSequences();
    writeFileSync(join(dist, 'index.html'), `<!doctype html><html><head><meta charset="utf-8"></head><body>${html}</body></html>`);
    await lane.browser.viewport(width, height);
    if (lane.zoom !== zoom) lane.zoom = await lane.browser.pageZoom(zoom);
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

/**
 * Which tests this process runs (CI partitions the harness's self-tests):
 * MAVI_VQA_TEST_GROUP unset — everything; `unit` — everything but the
 * end-to-end runs of run.mjs; `e2e-i/n` — the i-th of n deterministic groups
 * of the end-to-end runs, by their order in the file, and nothing else. Each
 * end-to-end test is in exactly one group by construction: `e2e()` numbers
 * them as they are declared and keeps index % n === i.
 */
export function testGroup() {
  const raw = process.env.MAVI_VQA_TEST_GROUP;
  if (!raw) return { kind: 'all', unit: true, e2e: () => true, label: 'all' };
  if (raw === 'unit') return { kind: 'unit', unit: true, e2e: () => false, label: 'unit' };
  const m = /^e2e-([0-9]+)\/([1-9][0-9]*)$/.exec(raw);
  if (!m || Number(m[1]) >= Number(m[2])) throw new Error(`MAVI_VQA_TEST_GROUP must be unset, "unit" or "e2e-i/n" with 0 <= i < n, not "${raw}"`);
  const index = Number(m[1]); const count = Number(m[2]);
  return { kind: 'e2e', unit: false, e2e: (ordinal) => ordinal % count === index, label: raw, index, count };
}

/** `it` for an end-to-end run of run.mjs: declared in order, run in its group only. */
export function e2eIt(it) {
  const group = testGroup();
  let ordinal = 0;
  return (name, fn) => {
    const mine = group.e2e(ordinal);
    ordinal += 1;
    return mine ? it(name, fn) : it(name, { skip: `end-to-end test of another group (MAVI_VQA_TEST_GROUP=${group.label})` }, fn);
  };
}

/** `describe` options for a block of unit tests: skipped in an e2e group. */
export function unitBlock() {
  const group = testGroup();
  return group.unit ? {} : { skip: `unit tests are the unit group's (MAVI_VQA_TEST_GROUP=${group.label})` };
}
