/**
 * Severity routing, exit status and deterministic settling (register V1, V3).
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { createLedger, exitStatus, HarnessError, settle } from '../engine.mjs';
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
    ledger.record(at('A'), 'containment.depth', 'x');
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
