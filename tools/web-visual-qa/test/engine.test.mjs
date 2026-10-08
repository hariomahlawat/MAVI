/**
 * Severity routing, exit status and deterministic settling (register V1, V3).
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, before, describe, it } from 'node:test';
import { createLedger, exitStatus, HarnessError, settle, unprovenPressedKinds, unreachedFaults } from '../engine.mjs';
import { RULES } from '../manifest.mjs';
import { openBrowser } from './browser.mjs';

const at = (tier, width = 1366) => ({ state: { name: 's' }, viewport: { tier, label: `${width}`, kind: 'anchor' } });

describe('severity routing', () => {
  it('resolves a finding from the manifest at the tier it was found at', () => {
    const ledger = createLedger();
    assert.equal(ledger.record(at('A'), 'ledger.row-pitch', 'x').severity, 'blocking');
    assert.equal(ledger.record(at('B', 1024), 'ledger.row-pitch', 'x').severity, 'measured/pending');
    assert.equal(ledger.record(at('C', 390), 'page.horizontal-overflow', 'x').severity, 'measured/pending');
    assert.equal(ledger.record(at('A'), 'review.sticky-rendered', 'x').severity, 'measured/pending');
    assert.match(ledger.record(at('A'), 'review.sticky-rendered', 'x').owner, /R6/);
  });

  it('refuses an unregistered rule rather than reporting it', () => {
    const ledger = createLedger();
    assert.throws(() => ledger.record(at('A'), 'page.invented-rule', 'x'), HarnessError);
    assert.throws(() => ledger.markEvaluated(at('A'), ['page.invented-rule']), HarnessError);
  });

  it('refuses a finding or an evaluation at a tier where the rule is not applicable', () => {
    const ledger = createLedger();
    assert.throws(() => ledger.record(at('C', 390), 'shell.rail', 'x'), /not applicable/);
    assert.throws(() => ledger.markEvaluated(at('B', 1024), ['page.width-discipline']), /not applicable/);
  });

  it('fails the run on a blocking finding and never on a measured/pending one', () => {
    const ledger = createLedger();
    ledger.record(at('B', 1024), 'page.horizontal-overflow', 'x');
    ledger.record({ ...at('A'), surface: 'review' }, 'containment.depth', 'x');
    assert.equal(exitStatus({ harnessErrors: [], blocking: ledger.blocking() }), 0);
    assert.equal(ledger.pending().length, 2);
    ledger.record(at('A'), 'surface.one-primary', 'two primaries');
    assert.equal(exitStatus({ harnessErrors: [], blocking: ledger.blocking() }), 1);
    assert.equal(exitStatus({ harnessErrors: [], blocking: ledger.blocking(), keep: true }), 0);
  });

  it('reports a harness fault as a fault, never as a finding', () => {
    assert.equal(exitStatus({ harnessErrors: ['browser crashed'], blocking: [] }), 2);
    assert.equal(exitStatus({ harnessErrors: ['browser crashed'], blocking: [{}], keep: true }), 2);
  });

  it('names every blocking assertion the sweep never evaluated', () => {
    const ledger = createLedger();
    const vacuous = ledger.vacuous();
    assert.ok(vacuous.includes('ledger.row-pitch @ Tier A'));
    ledger.markEvaluated(at('A'), ['ledger.row-pitch']);
    assert.ok(!ledger.vacuous().includes('ledger.row-pitch @ Tier A'));
    // A rule that is only measured can never be "vacuous blocking".
    assert.ok(!vacuous.some((entry) => entry.startsWith('perf.')));
    assert.equal(Object.keys(ledger.coverage).length, Object.keys(RULES).length);
  });
});

describe('deterministic settling', () => {
  let lane;
  before(async () => { lane = await openBrowser(); });
  after(async () => { await lane.close(); });

  // A page that loads like the product: a loading presentation, then content
  // from the fixture server after the request answers.
  const LOADING_PAGE = `
    <div id="region"><div class="skeleton"><div style="height:40px">.</div></div></div>
    <script>
      fetch('/api/thing').then((r) => r.ok ? r.json() : Promise.reject(r.status)).then((data) => {
        document.getElementById('region').innerHTML = '<p>' + data.label + '</p>';
      }).catch(() => {});
    </script>`;

  it('settles once the content has replaced the loading presentation', async () => {
    await lane.page(LOADING_PAGE, { api: { '/api/thing': { label: 'Ready content' } } });
    const result = await settle(lane, { expectText: 'Ready content' }, { timeoutMs: 8000 });
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.match(await lane.browser.evaluate('document.body.innerText'), /Ready content/);
  });

  it('refuses a state whose expected content never arrives, saying what was missing', async () => {
    await lane.page(LOADING_PAGE, { api: { '/api/thing': { label: 'Something else' } } });
    const result = await settle(lane, { expectText: 'Ready content' }, { timeoutMs: 1500 });
    assert.equal(result.ok, false);
    assert.ok(result.why.some((why) => why.includes('expected text "Ready content"')), JSON.stringify(result.why));
  });

  it('settles a held loading state on its loading presentation, not on a response that never comes', async () => {
    await lane.page(LOADING_PAGE, { api: { '/api/thing': 'hang' } });
    const result = await settle(lane, { holds: 'loading' }, { timeoutMs: 8000 });
    assert.equal(result.ok, true, JSON.stringify(result));
    lane.server.releaseHung();
  });

  it('does not mistake an accidental, unfinished load for a settled state', async () => {
    await lane.page(LOADING_PAGE, { api: { '/api/thing': 'hang' } });
    const result = await settle(lane, {}, { timeoutMs: 1500 });
    assert.equal(result.ok, false);
    assert.ok(result.why.some((why) => why.includes('loading presentation')), JSON.stringify(result.why));
    lane.server.releaseHung();
  });

  it('waits out a running transition instead of capturing it mid-way', async () => {
    await lane.page(`<div id="box" style="width:10px;height:10px;transition:width 600ms linear"></div>
      <script>requestAnimationFrame(() => requestAnimationFrame(() => { document.getElementById('box').style.width = '300px'; }));</script>`);
    const result = await settle(lane, {}, { timeoutMs: 5000 });
    assert.equal(result.ok, true, JSON.stringify(result));
    assert.ok(result.ms >= 400, `settled after ${result.ms}ms, before the 600ms transition ended`);
    assert.equal(await lane.browser.evaluate("document.getElementById('box').getBoundingClientRect().width"), 300);
  });
});

describe('harness faults', () => {
  it('makes an unreached state a fault at every tier, whatever the severity there', () => {
    const results = [
      { state: 'a', viewport: '1366x768', tier: 'A', reached: true, findings: [] },
      { state: 'b', viewport: '390x844', tier: 'C', reached: false, unreached: { stage: 'preparation', reason: 'preparation failed: no control' } },
      { state: 'c', viewport: '1024x768', tier: 'B', reached: false, unreached: null },
    ];
    const faults = unreachedFaults(results);
    assert.equal(faults.length, 2);
    assert.match(faults[0], /^b @ 390x844 \(Tier C\): the declared state was not reached at preparation: preparation failed/);
    assert.match(faults[1], /^c @ 1024x768 \(Tier B\)/);
    assert.equal(exitStatus({ harnessErrors: faults, blocking: [] }), 2);
  });

  it('exits 2 promptly when the browser process starts but never offers DevTools, leaving no process behind', () => {
    // Node standing in for a browser: it starts, rejects Chromium's flags and
    // exits without an endpoint — launch() must clean up after itself.
    const run = spawnSync(process.execPath, [fileURLToPath(new URL('../run.mjs', import.meta.url)), '--states', 'search', '--widths', '1366'], {
      env: { ...process.env, MAVI_CHROMIUM: process.execPath, MAVI_VQA_OUT: mkdtempSync(join(tmpdir(), 'mavi-vqa-launch-failure-')) },
      encoding: 'utf8',
      timeout: 60_000,
    });
    assert.equal(run.error, undefined, 'the run hung');
    assert.equal(run.status, 2, run.stdout + run.stderr);
    assert.match(run.stdout + run.stderr, /Chromium exited|DevTools/);
  });

  it('exits 2 promptly, without hanging on an open server, when a lane cannot start its browser', () => {
    const run = spawnSync(process.execPath, [fileURLToPath(new URL('../run.mjs', import.meta.url)), '--states', 'search', '--widths', '1366'], {
      env: { ...process.env, MAVI_CHROMIUM: join(tmpdir(), 'mavi-vqa-no-such-browser'), MAVI_VQA_OUT: mkdtempSync(join(tmpdir(), 'mavi-vqa-lane-failure-')) },
      encoding: 'utf8',
      timeout: 60_000,
    });
    assert.equal(run.error, undefined, 'the run hung');
    assert.equal(run.status, 2, run.stdout + run.stderr);
    assert.match(run.stdout + run.stderr, /MAVI_CHROMIUM is set to .* which does not exist|ffmpeg/);
  });
});

describe('surface-scoped findings in the ledger', () => {
  const on = (surface, tier = 'A') => ({ state: { name: 's' }, viewport: { tier, label: tier === 'A' ? '1366x768' : '390x844', kind: 'anchor' }, surface });
  it('weighs a finding by where it was found: an S1 region blocks, an unmigrated surface is pending on its row', () => {
    const ledger = createLedger();
    const foundation = ledger.record(on('search'), 'containment.depth', 'x', 'foundation');
    assert.equal(foundation.severity, 'blocking');
    assert.equal(foundation.surface, 'foundation');
    const surface = ledger.record(on('search'), 'containment.depth', 'x');
    assert.equal(surface.severity, 'measured/pending');
    assert.match(surface.owner, /R5/);
    assert.equal(ledger.record(on('search', 'C'), 'containment.depth', 'x', 'foundation').severity, 'measured/pending');
  });
  it('does not count a blocking rule as evaluated where it was only ever pending', () => {
    const ledger = createLedger();
    ledger.markEvaluated(on('search'), ['containment.depth']);
    assert.ok(ledger.vacuous().includes('containment.depth @ Tier A'));
    ledger.markEvaluated(on('search'), ['containment.depth'], 'foundation');
    assert.ok(!ledger.vacuous().includes('containment.depth @ Tier A'));
  });
});

describe('pressed.visible across a sweep', () => {
  it('leaves no kind unproven once any capture shows it distinct, and names the first case of one never shown', () => {
    const results = [
      { state: 'a', valid: true, pressed: { proven: [], unproven: [{ kind: 'button.chip in div', control: 'R3' }, { kind: 'button in li.nav', control: 'Forecourt' }] } },
      { state: 'b', valid: false, pressed: { proven: [], unproven: [{ kind: 'button.seg in div', control: 'x' }] } },
      { state: 'c', valid: true, pressed: { proven: ['button in li.nav'], unproven: [{ kind: 'button.chip in div', control: 'R4' }] } },
    ];
    const unproven = unprovenPressedKinds(results);
    assert.deepEqual(unproven.map((u) => [u.kind, u.result.state, u.control]), [['button.chip in div', 'a', 'R3']]);
  });
});
