/**
 * The P1 measurements' boundaries (cold review, items 4 and 5), against a real
 * browser: CLS of the navigation's loading-to-content transition and of one a
 * preparation starts, kept apart, with harness activity between them in
 * neither; long tasks measured only for a declared operator interaction, from
 * the action to the page going quiet; and missing instrumentation reported as
 * such, never as zero.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { toExpression } from '../assertions.mjs';
import { settle } from '../engine.mjs';
import { perfCollect } from '../settle.mjs';
import { openBrowser } from './browser.mjs';

let lane;
before(async () => { lane = await openBrowser(); });
after(async () => { await lane.close(); });

// A page whose content arrives after a request and pushes a box down (a
// layout shift), with a `reload()` that does the same again — the shape of a
// preparation that starts its own loading — and a `nudge()` that shifts the
// box with no loading at all, standing for unrelated harness activity.
const PAGE = `
  <div id="region"><div class="skeleton" style="height:20px">.</div></div>
  <div id="box" style="width:300px;height:60px;background:#345">box</div>
  <script>
    const load = () => fetch('/api/thing').then((r) => r.json()).then((data) => {
      document.getElementById('region').innerHTML = '<p style="height:' + data.height + 'px;margin:0">' + data.label + '</p>';
    });
    // After first paint, as a real request would: shifts before it are not reported.
    setTimeout(load, 300);
    window.reload = () => {
      document.getElementById('region').innerHTML = '<div class="skeleton" style="height:20px">.</div>';
      requestAnimationFrame(() => requestAnimationFrame(load));
    };
    window.nudge = () => { const b = document.getElementById('box'); b.style.marginTop = (parseInt(b.style.marginTop || '0', 10) + 150) + 'px'; };
  </script>`;

async function sequence({ interaction = null, busyMs = 0, reloadInPreparation = true, markAfterBusy = false } = {}) {
  await lane.page(PAGE, { api: { '/api/thing': { label: 'Ready', height: 200 } } });
  const navigated = await settle(lane, { expectText: 'Ready' }, { timeoutMs: 8000 });
  assert.equal(navigated.ok, true, JSON.stringify(navigated));
  const settledAt = await lane.browser.evaluate('performance.now()');
  // Harness activity between the navigation and the preparation.
  await lane.browser.evaluate('window.nudge()');
  await lane.browser.evaluate('new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))');
  const prepareStart = await lane.browser.evaluate('window.__vqa.mark("prepare-start")');
  await lane.browser.evaluate(`(() => {
    ${busyMs ? `const end = performance.now() + ${busyMs}; while (performance.now() < end) { /* a long task */ }` : ''}
    ${markAfterBusy ? "window.__vqa.mark('interaction-start');" : ''}
    ${reloadInPreparation ? 'window.reload();' : ''}
    return true;
  })()`);
  const prepared = await settle(lane, { expectText: 'Ready' }, { timeoutMs: 8000 });
  assert.equal(prepared.ok, true, JSON.stringify(prepared));
  const preparedAt = await lane.browser.evaluate('performance.now()');
  return lane.browser.evaluate(toExpression(perfCollect, { holds: null, settledAt, prepareStart, preparedAt, confirmedAt: prepared.confirmedAt, interaction }));
}

describe('CLS boundaries', () => {
  it('captures the navigation transition, and a preparation transition apart from it', async () => {
    const perf = await sequence({ interaction: 'reload the region' });
    assert.equal(perf.cls.status, 'measured');
    assert.ok(perf.cls.value > 0, 'the navigation transition shifted the box');
    assert.equal(perf.clsPreparation.status, 'measured');
    assert.ok(perf.clsPreparation.value > 0, 'the preparation transition shifted the box again');
    assert.equal(perf.clsPreparation.by, 'reload the region');
    assert.ok(perf.clsPreparation.window.from >= perf.cls.window.to, 'the two windows do not overlap');
  });

  it('counts neither the harness activity between them nor anything after settling', async () => {
    const perf = await sequence({ interaction: 'reload the region' });
    const counted = [...perf.cls.entries, ...perf.clsPreparation.entries].map((entry) => entry.at);
    const nudge = await lane.browser.evaluate('window.__vqa.shifts.map((s) => Math.round(s.startTime))');
    const outside = nudge.filter((at) => !counted.includes(at));
    assert.ok(outside.length >= 1, 'the nudge between the transitions is a shift outside both windows');
    assert.ok(perf.cls.outsideWindow >= 1 && perf.clsPreparation.outsideWindow >= 1);
  });

  it('reports a preparation that starts no loading as not-applicable, not as zero', async () => {
    const perf = await sequence({ reloadInPreparation: false });
    assert.equal(perf.clsPreparation.status, 'not-applicable');
    assert.equal(perf.clsPreparation.value, undefined);
  });

  it('reports missing instrumentation as unsupported, never as zero', async () => {
    await lane.page(PAGE, { api: { '/api/thing': { label: 'Ready', height: 200 } } });
    await settle(lane, { expectText: 'Ready' }, { timeoutMs: 8000 });
    const perf = await lane.browser.evaluate(`(() => {
      window.__vqa.supports.layoutShift = false; window.__vqa.supports.longTask = false;
      return ${toExpression(perfCollect, { holds: null, settledAt: 1e9, prepareStart: 0, preparedAt: 1e9, confirmedAt: 1e9, interaction: 'x' })};
    })()`);
    assert.equal(perf.cls.status, 'unsupported');
    assert.equal(perf.clsPreparation.status, 'unsupported');
    assert.equal(perf.longTasks.status, 'unsupported');
    for (const m of [perf.cls, perf.clsPreparation, perf.longTasks]) assert.equal(m.value ?? m.count, undefined);
  });
});

describe('first-interaction long tasks', () => {
  it('measures a declared interaction from the action to the page going quiet, with its identity', async () => {
    const perf = await sequence({ interaction: 'reload the region', busyMs: 120 });
    assert.equal(perf.longTasks.status, 'measured');
    assert.equal(perf.longTasks.interaction, 'reload the region');
    assert.ok(perf.longTasks.count >= 1 && perf.longTasks.maxMs >= 100, JSON.stringify(perf.longTasks));
    assert.ok(perf.longTasks.window.to > perf.longTasks.window.from);
  });

  it('starts at the action a multi-step preparation marks, so its setup is not attributed to it', async () => {
    const perf = await sequence({ interaction: 'reload the region', busyMs: 120, markAfterBusy: true });
    assert.equal(perf.longTasks.status, 'measured');
    assert.equal(perf.longTasks.startsAt, 'the marked action');
    assert.equal(perf.longTasks.count, 0, JSON.stringify(perf.longTasks));
  });

  it('counts work the interaction causes after its last DOM change, up to the probe that confirmed settling', async () => {
    // A canvas-like long task with no DOM mutation and no request, a frame
    // after the action: settling cannot see it, the measurement must.
    await lane.page(PAGE, { api: { '/api/thing': { label: 'Ready', height: 200 } } });
    await settle(lane, { expectText: 'Ready' }, { timeoutMs: 8000 });
    const settledAt = await lane.browser.evaluate('performance.now()');
    const prepareStart = await lane.browser.evaluate('window.__vqa.mark("prepare-start")');
    await lane.browser.evaluate(`(() => { requestAnimationFrame(() => { const end = performance.now() + 120; while (performance.now() < end) { /* draw */ } }); return true; })()`);
    const prepared = await settle(lane, { expectText: 'Ready' }, { timeoutMs: 8000 });
    const preparedAt = await lane.browser.evaluate('performance.now()');
    const perf = await lane.browser.evaluate(toExpression(perfCollect, { holds: null, settledAt, prepareStart, preparedAt, confirmedAt: prepared.confirmedAt, interaction: 'draw' }));
    assert.equal(perf.longTasks.status, 'measured');
    assert.ok(perf.longTasks.count >= 1 && perf.longTasks.maxMs >= 100, JSON.stringify(perf.longTasks));
  });

  it('does not measure a preparation that is fixture setup as an interaction', async () => {
    const perf = await sequence({ interaction: null, busyMs: 120 });
    assert.equal(perf.longTasks.status, 'not-applicable');
    assert.match(perf.longTasks.why, /fixture setup or verification/);
  });
});
