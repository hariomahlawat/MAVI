/**
 * X2 (§23, plan §5.3): the keyboard-journey runner refuses what is not a
 * keyboard-only journey. Each negative drives the real runner — real Chromium,
 * real keys through CDP, the real page guard and focus judgement — against a
 * small page with one defect, and must fail for that defect's reason; a
 * positive control on the same pages passes, so a negative cannot pass by the
 * runner failing everything. The plan, shard and aggregate refusals are pure.
 * The registry's own source is held to the operator's vocabulary.
 */
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, before, describe, it } from 'node:test';
import { HarnessError } from '../engine.mjs';
import { JOURNEYS } from '../journey-registry.mjs';
import { journeyAggregate, openJourneyLane, partitionJourneys, planJourneys, runJourney } from '../journeys.mjs';
import { JOURNEY_CONDITION } from '../manifest.mjs';

const HERE = new URL('.', import.meta.url);
const FIXTURES = new URL('../fixtures/', HERE);

/**
 * One page per path, each with one behaviour. Written as a static app the
 * fixture server serves like the product's build (every path answers
 * index.html).
 */
const APP = String.raw`<!doctype html><html lang="en"><head><meta charset="utf-8"><title>journey negatives</title>
<style>body{font:16px sans-serif;margin:0} main{padding:16px} button{margin:4px;padding:8px 12px} [role=dialog]{position:fixed;inset:20% 30%;background:#fff;border:2px solid #000;padding:16px}</style></head>
<body><div id="root"></div><script>
const root = document.getElementById('root');
const path = location.pathname;
const say = (text) => { const p = document.createElement('p'); p.textContent = text; document.querySelector('main').append(p); };
const button = (name, onClick) => { const b = document.createElement('button'); b.textContent = name; b.addEventListener('click', onClick); document.querySelector('main').append(b); return b; };
root.innerHTML = '<main tabindex="-1"><h1>Journey page</h1></main>';
if (path === '/plain' || path === '/pointer') {
  button('Alpha', () => say('Alpha pressed'));
  button('Beta', () => say('Beta pressed'));
}
if (path === '/ghost') {
  button('Alpha', () => {});
  const ghost = button('Ghost', () => {}); ghost.style.opacity = '0';
  button('Beta', () => {});
}
if (path === '/vanish') {
  const b = button('Remove me', () => { b.remove(); say('removed'); });
}
if (path === '/never') button('Go', () => {});
if (path === '/overlay' || path === '/escape') {
  const opener = button('Open dialog', () => {
    const d = document.createElement('div');
    d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'true'); d.setAttribute('aria-label', 'Dialog');
    const close = document.createElement('button'); close.textContent = 'Close';
    const shut = () => { d.remove(); /* focus is not returned to the opener */ };
    close.addEventListener('click', shut);
    d.addEventListener('keydown', (e) => { if (e.key === 'Escape') shut(); });
    d.append(close); document.body.append(d);
    if (path === '/escape') close.focus(); // focus enters; Escape will not bring it back
  });
}
if (path === '/reload') button('Reload', () => location.assign('/plain'));
if (path === '/retry') {
  const go = () => fetch('/api/thing').then((r) => { say(r.ok ? 'Recovered' : 'Failed'); });
  button('Retry', go);
}
if (path === '/save') {
  button('Save', () => { /* the defect: saving sends nothing */ });
  fetch('/api/state').then((r) => r.ok ? r.json() : null).then((s) => { if (s && s.saved) say('Saved'); });
}
</script></body></html>`;

const VIEWPORT = Object.freeze({ width: 1366, height: 768, tier: 'A' });

let dir;
let lane;
async function run(journey) {
  const [item] = planJourneys({ journeys: [journey], viewports: [VIEWPORT] });
  return runJourney(lane, item, { outDir: dir });
}

describe('the keyboard-journey runner', { timeout: 300_000 }, () => {
  before(async () => {
    dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-journeys-'));
    writeFileSync(join(dir, 'index.html'), APP);
    lane = await openJourneyLane({ distDir: dir, fixtureDir: fileURLToPath(FIXTURES), mediaDir: join(dir, 'media') });
  });
  after(async () => {
    await lane?.browser.close().catch(() => {});
    await lane?.server.close().catch(() => {});
    if (dir) rmSync(dir, { recursive: true, force: true });
  });

  it('passes a journey taken by the keyboard alone (the control the negatives rest on)', async () => {
    const result = await run({
      id: 'control', title: 'control', start: '/plain', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await op.tabTo({ name: 'Beta', role: 'button' });
        await op.press('Enter');
        await op.done('Beta answered its key', '/Beta pressed/.test(document.body.innerText) && "Beta pressed"');
      },
    });
    assert.equal(result.failure, null);
    assert.equal(result.passed, true);
    assert.equal(result.rule, 'a11y.keyboard-journeys');
    assert.equal(result.pointerEvents, 0);
    assert.equal(result.syntheticEvents, 0);
    assert.equal(result.documentLoadsAfterStart, 0);
    assert.ok(result.steps.at(-1).terminal);
    // Structured evidence on every step.
    for (const step of result.steps.slice(1)) {
      for (const field of ['journey', 'viewport', 'step', 'action', 'pass']) assert.ok(field in step, `${field} on step ${step.step}`);
    }
    const tab = result.steps.find((s) => s.action === 'tab-to');
    assert.equal(tab.focusAfter, 'button "Beta"');
    assert.ok(tab.stops.length >= 2, 'the Tab stops are recorded');
  });

  it('fails a target the keyboard cannot reach, within its bound', async () => {
    const result = await run({
      id: 'unreachable', title: 'unreachable', start: '/plain', ready: 'Boolean(document.querySelector("button"))',
      async run(op) { await op.tabTo({ name: 'Gamma', role: 'button' }, { max: 8 }); await op.done('never', 'false'); },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /button named "Gamma" was not reached within 8 Tab presses/);
    assert.equal(result.steps.at(-1).stops.length, 8);
  });

  it('fails when the focused control disappears and focus falls to the document', async () => {
    const result = await run({
      id: 'vanish', title: 'vanish', start: '/vanish', ready: 'Boolean(document.querySelector("button"))',
      async run(op) { await op.tabTo({ name: 'Remove me', role: 'button' }); await op.press('Enter'); await op.done('never', 'true'); },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /step \d+ \(press\): focus is on the document, not on a control \(lost\)/);
  });

  it('fails when pointer input reaches the page, even once', async () => {
    const result = await run({
      id: 'pointer', title: 'pointer', start: '/pointer', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        // What the runner never does: a mouse press, sent here to prove the guard sees it.
        await lane.browser.cdp('Input.dispatchMouseEvent', { type: 'mousePressed', x: 30, y: 80, button: 'left', clickCount: 1 });
        await lane.browser.cdp('Input.dispatchMouseEvent', { type: 'mouseReleased', x: 30, y: 80, button: 'left', clickCount: 1 });
        await op.tabTo({ name: 'Beta', role: 'button' });
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /pointer input reached the page: pointerdown/);
    assert.ok(result.pointerEvents > 0);
  });

  it('fails a scripted click: something other than the input pipeline acted', async () => {
    const result = await run({
      id: 'scripted', title: 'scripted', start: '/plain', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await lane.browser.evaluate('document.querySelectorAll("button")[1].click()');
        await op.tabTo({ name: 'Alpha', role: 'button' });
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /something other than the input pipeline acted: scripted click/);
  });

  it('fails a scripted input event, as it fails a scripted click', async () => {
    const result = await run({
      id: 'scripted-input', title: 'scripted input', start: '/plain', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await lane.browser.evaluate('document.body.dispatchEvent(new Event("input", { bubbles: true }))');
        await op.tabTo({ name: 'Alpha', role: 'button' });
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /something other than the input pipeline acted: scripted input/);
  });

  it('fails a checkpoint that acts on the page instead of observing it', async () => {
    const result = await run({
      id: 'acting-checkpoint', title: 'acting checkpoint', start: '/plain', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await op.tabTo({ name: 'Alpha', role: 'button' });
        await op.until('Beta pressed', '(document.querySelectorAll("button")[1].click(), /Beta pressed/.test(document.body.innerText))');
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /the checkpoint expression acts on the page .*: a checkpoint may only observe/);
    assert.doesNotMatch(result.snapshot.text, /Beta pressed/, 'the side effect was refused before it ran');
  });

  it('fails a Tab stop where focus is not valid, before the target is reached', async () => {
    const result = await run({
      id: 'ghost', title: 'ghost', start: '/ghost', ready: 'Boolean(document.querySelector("button"))',
      async run(op) { await op.tabTo({ name: 'Beta', role: 'button' }); await op.done('never', 'true'); },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /Tab stop 2: <button> "Ghost" has focus but is not rendered \(transparent\)/);
  });

  it('counts only requests made after the operator\'s last key', async () => {
    // /save asks for /api/state as it loads, before any key: that request is
    // not the effect of the Save the operator then presses.
    const result = await run({
      id: 'early-request', title: 'early request', start: '/save', ready: 'Boolean(document.querySelector("button"))',
      api: { '/api/state': { saved: false } },
      async run(op) {
        await op.tabTo({ name: 'Save', role: 'button' });
        await op.press('Enter');
        await op.requested('the state was read', 'GET', /^\/api\/state$/);
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /no GET .* request was made after the operator's last key/);
  });

  it('fails a direct route jump: a document load after the start', async () => {
    const result = await run({
      id: 'reload', title: 'reload', start: '/reload', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await op.tabTo({ name: 'Reload', role: 'button' });
        await op.press('Enter');
        await op.done('the next page', '/^\\/plain$/.test(location.pathname) && "on /plain"');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /the document was reloaded or replaced after the journey started/);
    assert.ok(result.documentLoadsAfterStart > 0);
  });

  it('fails a checkpoint the page never reaches, naming it', async () => {
    const result = await run({
      id: 'never', title: 'never', start: '/never', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await op.tabTo({ name: 'Go', role: 'button' });
        await op.press('Enter');
        await op.until('the work is done', '/Done/.test(document.body.innerText)', { timeoutMs: 1500 });
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /step \d+ \(checkpoint\): not reached within 1500ms/);
    assert.equal(result.steps.at(-1).expect, 'the work is done');
  });

  it('fails a modal overlay that opens without taking focus', async () => {
    const result = await run({
      id: 'overlay', title: 'overlay', start: '/overlay', ready: 'Boolean(document.querySelector("button"))',
      async run(op) { await op.tabTo({ name: 'Open dialog', role: 'button' }); await op.press('Enter'); await op.done('never', 'true'); },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /a modal overlay is open and focus is outside it/);
  });

  it('fails an Escape that closes an overlay without returning focus', async () => {
    const result = await run({
      id: 'escape', title: 'escape', start: '/escape', ready: 'Boolean(document.querySelector("button"))',
      async run(op) {
        await op.tabTo({ name: 'Open dialog', role: 'button' });
        await op.press('Enter', { expectFocus: { name: 'Close', role: 'button' } });
        await op.press('Escape', { expectFocus: { name: 'Open dialog', role: 'button' } });
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    // The dialog took focus (the first press passed); Escape lost it.
    assert.equal(result.steps.find((s) => s.key === 'Enter')?.pass, true);
    assert.match(result.failure, /\(press\): focus is on the document, not on a control \(lost\)/);
  });

  it('fails a retry that does not recover', async () => {
    lane.scenario = {};
    const result = await run({
      id: 'retry', title: 'retry', start: '/retry', ready: 'Boolean(document.querySelector("button"))',
      api: { '/api/thing': 'unavailable' },
      async run(op) {
        await op.tabTo({ name: 'Retry', role: 'button' });
        await op.press('Enter');
        await op.requested('the retry was requested', 'GET', /^\/api\/thing$/);
        await op.until('the retry recovered', '/Recovered/.test(document.body.innerText) && "recovered"', { timeoutMs: 2000 });
        await op.done('never', 'true');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /\(checkpoint\): not reached within 2000ms/);
    assert.match(result.snapshot.text, /Failed/);
  });

  it('refuses a success the fixture would show without the operator\'s action', async () => {
    // The backend's "saved" exists only after a POST the operator's Save
    // must send; this Save sends nothing, so neither the request nor the
    // success can be observed.
    const result = await run({
      id: 'save', title: 'save', start: '/save', ready: 'Boolean(document.querySelector("button"))',
      api: { '/api/state': { after: 'POST /api/save', before: { saved: false }, then: { saved: true } } },
      async run(op) {
        await op.tabTo({ name: 'Save', role: 'button' });
        await op.press('Enter');
        await op.requested('the save reached the backend', 'POST', /^\/api\/save$/);
        await op.done('saved', '/Saved/.test(document.body.innerText) && "saved"');
      },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /no POST \/\^\\\/api\\\/save\$\/ request was made/);
    assert.doesNotMatch(result.snapshot.text, /Saved/);
  });

  it('fails a journey that ends without its terminal checkpoint', async () => {
    const result = await run({
      id: 'unfinished', title: 'unfinished', start: '/plain', ready: 'Boolean(document.querySelector("button"))',
      async run(op) { await op.tabTo({ name: 'Alpha', role: 'button' }); },
    });
    assert.equal(result.passed, false);
    assert.match(result.failure, /ended without its terminal checkpoint/);
  });
});

describe('the journey plan, its shards and their aggregate', () => {
  const journeys = [{ id: 'one' }, { id: 'two' }, { id: 'three' }];

  it('plans every journey at every workstation viewport, and refuses Tier C', () => {
    const plan = planJourneys({ journeys });
    assert.equal(plan.length, 9);
    assert.deepEqual([...new Set(plan.map((p) => p.viewport.tier))].sort(), ['A', 'B']);
    assert.throws(() => planJourneys({ journeys, viewports: [...JOURNEY_CONDITION.viewports, { width: 390, height: 844, tier: 'C' }] }), (e) => e instanceof HarnessError && /Tier C/.test(e.message));
    assert.throws(() => planJourneys({ journeys: [...journeys, { id: 'one' }] }), /registered twice/);
  });

  it('plans the six frozen journeys, 18 executions', () => {
    assert.equal(JOURNEYS.length, 6);
    assert.equal(planJourneys({ journeys: JOURNEYS }).length, 18);
  });

  it('partitions the plan deterministically: each execution in exactly one shard', () => {
    const plan = planJourneys({ journeys });
    const shards = [0, 1, 2, 3].map((index) => partitionJourneys(plan, { index, count: 4 }).map((p) => p.key));
    const all = shards.flat();
    assert.equal(all.length, plan.length);
    assert.equal(new Set(all).size, plan.length);
    assert.deepEqual(partitionJourneys(plan, { index: 1, count: 4 }).map((p) => p.key), shards[1]);
    assert.throws(() => partitionJourneys(plan.slice(0, 2), { index: 3, count: 4 }), /selects no journey/);
  });

  const planned = ['one@1366x768', 'two@1366x768'];
  const exec = (key, extra = {}) => ({ key, tier: 'A', passed: true, pointerEvents: 0, syntheticEvents: 0, documentLoadsAfterStart: 0, terminal: { description: 'end' }, steps: [{}], ...extra });
  const shard = (file, executions, extra = {}) => ({ file, head: 'abc', planned, executions, harnessErrors: [], ...extra });

  it('accepts every planned execution exactly once', () => {
    const agg = journeyAggregate([shard('a', [exec('one@1366x768')]), shard('b', [exec('two@1366x768')])]);
    assert.deepEqual(agg.faults, []);
    assert.equal(agg.executions.length, 2);
  });

  it('faults a duplicate execution', () => {
    const agg = journeyAggregate([shard('a', [exec('one@1366x768'), exec('two@1366x768')]), shard('b', [exec('two@1366x768')])]);
    assert.ok(agg.faults.some((f) => /two@1366x768 ran 2 times/.test(f)));
  });

  it('faults a missing execution, and a missing shard file', () => {
    const agg = journeyAggregate([shard('a', [exec('one@1366x768')])]);
    assert.ok(agg.faults.some((f) => /two@1366x768 was planned and never ran/.test(f)));
    assert.deepEqual(journeyAggregate([]).faults, ['no journey results to aggregate']);
  });

  it('faults an execution claimed at Tier C, one not planned, and shards of different heads', () => {
    const agg = journeyAggregate([
      shard('a', [exec('one@1366x768'), exec('two@1366x768', { tier: 'C' }), exec('stray@1366x768')]),
      shard('b', [], { head: 'def' }),
    ]);
    assert.ok(agg.faults.some((f) => /two@1366x768 ran at Tier C, where no workflow acceptance is claimed/.test(f)));
    assert.ok(agg.faults.some((f) => /stray@1366x768 ran but was not planned/.test(f)));
    assert.ok(agg.faults.some((f) => /head def differs/.test(f)));
  });

  it('faults a pass that does not carry its evidence', () => {
    const agg = journeyAggregate([shard('a', [
      exec('one@1366x768', { pointerEvents: 1 }),
      exec('two@1366x768', { terminal: null, syntheticEvents: null }),
    ])]);
    assert.ok(agg.faults.some((f) => /one@1366x768 claims a pass without its evidence \(pointer events\)/.test(f)));
    assert.ok(agg.faults.some((f) => /two@1366x768 claims a pass without its evidence \(scripted events, a terminal checkpoint\)/.test(f)));
  });

  it('faults, from the command line, an aggregate of a subset or of a missing shard file (exit 2)', () => {
    const work = mkdtempSync(join(tmpdir(), 'mavi-vqa-journey-agg-'));
    try {
      const file = join(work, 'shard.json');
      writeFileSync(file, JSON.stringify(shard('a', [exec('one@1366x768'), exec('two@1366x768')])));
      const cli = (...args) => spawnSync(process.execPath, [fileURLToPath(new URL('../journeys.mjs', import.meta.url)), '--aggregate', '--out', join(work, 'out'), ...args], { encoding: 'utf8', timeout: 60_000 });
      const subset = cli(file);
      assert.equal(subset.status, 2, subset.stdout + subset.stderr);
      assert.match(subset.stdout, /planned 2 executions, not the registry's 18/);
      const missing = cli(file, join(work, 'absent.json'));
      assert.equal(missing.status, 2);
    } finally { rmSync(work, { recursive: true, force: true }); }
  });

  it('refuses a substitute registry in a shard, and an aggregate of shards that ran another registry', () => {
    const work = mkdtempSync(join(tmpdir(), 'mavi-vqa-journey-reg-'));
    try {
      const script = fileURLToPath(new URL('../journeys.mjs', import.meta.url));
      const substitute = join(work, 'other.mjs');
      writeFileSync(substitute, 'export const JOURNEYS = [];\n');
      const refused = spawnSync(process.execPath, [script, '--shard', '0/3', '--out', join(work, 'shard')], { encoding: 'utf8', timeout: 60_000, env: { ...process.env, MAVI_VQA_JOURNEYS_MODULE: substitute } });
      assert.equal(refused.status, 2);
      assert.match(refused.stderr, /a shard \(X2 evidence\) refuses it/);
      const file = join(work, 'shard.json');
      const full = planJourneys({ journeys: JOURNEYS }).map((p) => p.key);
      writeFileSync(file, JSON.stringify({ head: 'abc', registry: 'not-this-registry', planned: full, executions: full.map((key) => exec(key)), harnessErrors: [] }));
      const agg = spawnSync(process.execPath, [script, '--aggregate', '--out', join(work, 'out'), file], { encoding: 'utf8', timeout: 60_000 });
      assert.equal(agg.status, 2, agg.stdout + agg.stderr);
      assert.match(agg.stdout, /ran registry not-this-registry, not this head's [0-9a-f]{64}/);
    } finally { rmSync(work, { recursive: true, force: true }); }
  });

  it('keeps a failed execution failed, apart from the faults', () => {
    const agg = journeyAggregate([shard('a', [exec('one@1366x768'), exec('two@1366x768', { passed: false, failure: 'x' })])]);
    assert.deepEqual(agg.faults, []);
    assert.deepEqual(agg.failed.map((e) => e.key), ['two@1366x768']);
  });
});

describe('the journey registry', () => {
  const source = readFileSync(new URL('../journey-registry.mjs', import.meta.url), 'utf8')
    // Comments may describe what the journeys never do.
    .replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');

  it('drives the product through the operator alone: no click, focus, navigation, event or browser call', () => {
    for (const forbidden of [
      /\.click\(/, /\.focus\(/, /\.blur\(/, /\.select\(/, /requestSubmit|\.submit\(/, /showPicker/, /dispatchEvent/,
      /pushState|replaceState|history\./, /location\s*=|location\.(assign|replace|reload|href\s*=)/, /\.value\s*=[^=]/, /\.checked\s*=[^=]/,
      /localStorage|sessionStorage|indexedDB|document\.cookie/, /setAttribute|removeAttribute|\.remove\(|innerHTML\s*=|\.append\(/,
      /dispatchMouseEvent|dispatchTouchEvent|mouseMove/, /\bgoto\(/, /\bbrowser\./, /\.cdp\(/, /\.evaluate\(/, /setInputFiles|setFileInputFiles/,
    ]) {
      assert.doesNotMatch(source, forbidden, `the registry uses ${forbidden}`);
    }
  });

  it('registers the six frozen journeys of plan §5.3, by their names', () => {
    assert.deepEqual(JOURNEYS.map((j) => j.title), [
      'Import → Process → Status → Results',
      'Search → filter → scan → inspect → evidence → return',
      'Vehicle search → Car refinement → inspect → Review',
      'Configure scene → analyse → search analytic → why matched → inspect',
      'Cameras / Videos / Processing monitoring',
      'Error / retry / recovery',
    ]);
    for (const journey of JOURNEYS) {
      assert.ok(journey.start.startsWith('/'), `${journey.id} declares its one direct load`);
      assert.match(journey.run.toString(), /op\.done\(/, `${journey.id} ends on a terminal checkpoint`);
    }
  });
});
