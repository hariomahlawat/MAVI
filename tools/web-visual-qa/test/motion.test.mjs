/**
 * X4 (§13, §23): reduced motion, proven in real Chromium — the preference
 * emulated by the browser itself (Emulation.setEmulatedMedia), read back from
 * the page two ways, never assumed; every element and pseudo-element's
 * computed durations judged; running browser animations judged; the lane
 * planned, isolated between cases and covered on the full sweep.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { toExpression } from '../assertions.mjs';
import { a11yMotionEnvironment, a11yReducedMotion, motionDurations, motionEnvironmentProblem } from '../a11y.mjs';
import { caseKey, createLedger, HarnessError, normalMotionControlFaults, planCases, reducedMotionCoverageFaults, sweepChecks } from '../engine.mjs';
import { REDUCED_MOTION_CONDITION, RULES, TEXT_SPACING_CONDITION } from '../manifest.mjs';
import { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM } from '../states.mjs';
import { e2eIt, openBrowser, unitBlock } from './browser.mjs';

// The product's own reduced-motion contract, read from the stylesheet that
// ships it: the unit tests judge fixtures with and without exactly this rule.
const BASE_CSS = readFileSync(fileURLToPath(new URL('../../../src/web/mavi-web/src/styles/base.css', import.meta.url)), 'utf8');
const PRODUCT_RULE = /@media \(prefers-reduced-motion: reduce\) \{[\s\S]*?\n\}/.exec(BASE_CSS)?.[0];
const KEYFRAMES = '@keyframes spin { to { transform: rotate(360deg); } } @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }';

let lane;
before(async () => { lane = await openBrowser(); });
after(async () => { await lane.close(); });

/** The page under the emulated preference (or not), then the rule's verdict. */
async function judge(html, { reduce = true, judge: judging = true } = {}) {
  await lane.browser.reducedMotion(reduce);
  await lane.page(html);
  return lane.browser.evaluate(toExpression(a11yReducedMotion, { judge: judging }));
}
const messages = (r) => r.findings.map((f) => f.message).join('\n');

describe('a11y.reduced-motion: the preference, emulated and proven', unitBlock(), () => {
  it('finds the product rule in base.css (the contract the lane proves)', () => {
    assert.ok(PRODUCT_RULE, 'base.css has no prefers-reduced-motion block');
    assert.match(PRODUCT_RULE, /transition-duration: 0ms !important/);
    assert.match(PRODUCT_RULE, /animation-duration: 0ms !important/);
  });

  it('reads the preference from the page and its stylesheet, and the emulation clears between cases', async () => {
    await lane.browser.reducedMotion(true);
    await lane.page('<main>a</main>');
    assert.deepEqual(await lane.browser.evaluate(toExpression(a11yMotionEnvironment)), { matchMedia: true, css: true });
    // The next case on the same browser, pinned to the normal preference: nothing leaks.
    await lane.browser.reducedMotion(false);
    await lane.page('<main>b</main>');
    assert.deepEqual(await lane.browser.evaluate(toExpression(a11yMotionEnvironment)), { matchMedia: false, css: false });
    // Pinned means `no-preference`, not whatever the host says.
    assert.equal(await lane.browser.evaluate("matchMedia('(prefers-reduced-motion: no-preference)').matches"), true);
    // And the emulation clears (back to the browser's default) on request.
    await lane.browser.reducedMotion(true);
    await lane.browser.reducedMotion(null);
    await lane.page('<main>c</main>');
    assert.equal(await lane.browser.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"), false);
  });

  it('decides what the preference reading of a case means: the lane needs both readings reduce, every other case neither', () => {
    assert.equal(motionEnvironmentProblem({ matchMedia: true, css: true }, true), null);
    assert.match(motionEnvironmentProblem({ matchMedia: false, css: true }, true), /prefers-reduced-motion: reduce is not in force \(matchMedia false, CSS media true\)/);
    assert.match(motionEnvironmentProblem({ matchMedia: true, css: false }, true), /not in force/);
    assert.equal(motionEnvironmentProblem({ matchMedia: false, css: false }, false), null);
    // An ordinary case under a reduced preference it did not ask for — a
    // host setting, a leaked emulation — is not reached, never judged.
    assert.match(motionEnvironmentProblem({ matchMedia: true, css: true }, false), /an ordinary case ran under prefers-reduced-motion: reduce it did not ask for/);
    assert.match(motionEnvironmentProblem({ matchMedia: true, css: false }, false), /disagree/);
    assert.match(motionEnvironmentProblem(null, false), /not read/);
  });

  it('cannot be fooled by a page that replaces matchMedia: the CSS media evaluation disagrees', async () => {
    await lane.browser.reducedMotion(false);
    await lane.page('<main>c</main><script>window.matchMedia = (q) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} });</script>');
    assert.deepEqual(await lane.browser.evaluate(toExpression(a11yMotionEnvironment)), { matchMedia: true, css: false });
    await lane.browser.reducedMotion(true);
    await lane.page('<main>d</main><script>window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} });</script>');
    assert.deepEqual(await lane.browser.evaluate(toExpression(a11yMotionEnvironment)), { matchMedia: false, css: true });
  });
});

describe('a11y.reduced-motion: every duration, every element and pseudo-element', unitBlock(), () => {
  it('parses every entry of a computed time list, in s and ms, and refuses what is not a time', () => {
    assert.deepEqual(motionDurations('0s'), [0]);
    assert.deepEqual(motionDurations('0ms'), [0]);
    assert.deepEqual(motionDurations('1.2s'), [1200]);
    assert.deepEqual(motionDurations('0s, 0.12s, 120ms'), [0, 120, 120]);
    assert.deepEqual(motionDurations('.5s'), [500]);
    assert.ok(Math.abs(motionDurations('1e-08s')[0] - 1e-5) < 1e-12);
    assert.deepEqual(motionDurations('-1s'), [-1000]);
    assert.ok(Number.isNaN(motionDurations('auto')[0]));
    assert.ok(Number.isNaN(motionDurations('0s, fast')[1]));
    assert.deepEqual(motionDurations(''), []);
  });

  it('finds a transition left at 600ms, and passes it under the product rule', async () => {
    const BOX = '<style>.box { width: 40px; height: 20px; transition: width 600ms linear; }</style><main><div class="box">x</div></main>';
    let r = await judge(BOX);
    assert.match(messages(r), /<div\.box> "x" has animation-duration 0s and transition-duration 0\.6s \(width\) under prefers-reduced-motion: reduce/);
    assert.equal(r.measured.positiveTransitions, 1);
    assert.deepEqual(r.evaluated, ['a11y.reduced-motion']);
    r = await judge(`<style>${PRODUCT_RULE}</style>` + BOX);
    assert.deepEqual(r.findings, []);
    assert.equal(r.measured.positiveTransitions, 0);
  });

  it('finds a CSS animation, as a computed duration and as a running browser animation', async () => {
    const SPINNER = `<style>${KEYFRAMES} .spinner { width: 14px; height: 14px; animation: spin 1s linear infinite; }</style><main><span class="spinner" style="display:inline-block"></span></main>`;
    const r = await judge(SPINNER);
    assert.match(messages(r), /<span\.spinner> has animation-duration 1s \(spin\)/);
    assert.match(messages(r), /<span\.spinner>: a running CSS animation spin with a 1000ms duration/);
    assert.equal(r.measured.positiveAnimations, 1);
    assert.equal(r.measured.browserRunningPositive, 1);
  });

  it('counts elements at fault, not the ways each faults: one element with a transition and an animation is one entry, and the summary counts the rest', async () => {
    const BOTH = `<style>${KEYFRAMES} .both { display: inline-block; width: 10px; height: 10px; transition: opacity 600ms; animation: spin 1s linear infinite; }</style><main><span class="both"></span></main>`;
    let r = await judge(BOTH);
    assert.equal(r.measured.affected, 1);
    assert.equal(r.measured.positiveTransitions, 1);
    assert.equal(r.measured.positiveAnimations, 1);
    assert.doesNotMatch(messages(r), /more element/);
    // Beyond the 30 reported in full, the summary counts elements, once each.
    const MANY = `<style>${KEYFRAMES} .m { display: inline-block; width: 4px; height: 4px; transition: opacity 600ms; animation: spin 1s linear infinite; }</style><main>${'<span class="m"></span>'.repeat(35)}</main>`;
    r = await judge(MANY);
    assert.equal(r.measured.affected, 35);
    assert.match(messages(r), /^5 more element\(s\) or pseudo-element\(s\) with a positive or unreadable duration/m);
  });

  it('finds an animated ::before, naming the pseudo-element, and judges only pseudo-elements that render', async () => {
    const THING = `<style>${KEYFRAMES} .thing::before { content: ""; display: inline-block; width: 6px; height: 6px; animation: pulse 1.2s ease-in-out infinite; } .bare::after { animation: pulse 1.2s infinite; }</style><main><span class="thing">Running</span><span class="bare">idle</span></main>`;
    const r = await judge(THING);
    assert.match(messages(r), /<span\.thing> "Running"::before has animation-duration 1\.2s \(pulse\)/);
    // `.bare::after` has no content: no box, nothing to judge.
    assert.doesNotMatch(messages(r), /bare/);
    assert.ok(r.measured.pseudos >= 1);
  });

  it('parses every entry of a duration list: one non-zero entry among zeros fails', async () => {
    const LIST = '<style>.chip { transition-property: opacity, color; transition-duration: 0ms, 120ms; }</style><main><span class="chip">a</span></main>';
    const r = await judge(LIST);
    assert.match(messages(r), /<span\.chip> "a" has animation-duration 0s and transition-duration 0s, 0\.12s \(opacity, color\)/);
    const ZERO = '<style>.chip { transition-property: opacity, color; transition-duration: 0s, 0ms; }</style><main><span class="chip">a</span></main>';
    assert.deepEqual((await judge(ZERO)).findings, []);
  });

  it('finds a script animation the stylesheet cannot reach, and lets a zero-duration or paused one be', async () => {
    const SCRIPT = (timing, then = '') => `<style>${PRODUCT_RULE}</style><main><div id="m" style="width:20px;height:20px">m</div></main><script>window.__a = document.getElementById('m').animate([{ opacity: 0 }, { opacity: 1 }], ${timing}); ${then}</script>`;
    let r = await judge(SCRIPT('{ duration: 1000, iterations: Infinity }'));
    assert.match(messages(r), /<div> "m": a running script animation with a 1000ms duration/);
    r = await judge(SCRIPT('{ duration: 0, iterations: 1 }'));
    assert.deepEqual(r.findings, []);
    r = await judge(SCRIPT('{ duration: 1000, iterations: Infinity }', 'window.__a.pause();'));
    assert.deepEqual(r.findings, []);
    assert.ok(r.measured.browserAnimations >= 1);
  });

  it('under the product rule, the pulse, the spinner and the ordinary transitions all compute to zero — and keep their durations without the preference', async () => {
    const SITES = `<style>${KEYFRAMES} .badge--active::before { content: ""; display: inline-block; width: 6px; height: 6px; animation: pulse 1.2s ease-in-out infinite; } .spinner { display: inline-block; width: 14px; height: 14px; animation: spin 0.8s linear infinite; } .btn { transition: background 120ms, border-color 120ms; } ${PRODUCT_RULE}</style>
      <main><span class="badge--active">Processing</span><span class="spinner"></span><button class="btn">Retry</button></main>`;
    const reduced = await judge(SITES, { reduce: true });
    assert.deepEqual(reduced.findings, []);
    assert.equal(reduced.measured.positiveTransitions + reduced.measured.positiveAnimations + reduced.measured.browserRunningPositive, 0);
    assert.deepEqual(reduced.measured.sites, {});
    // The control: the same page under the normal preference, measured not judged.
    const normal = await judge(SITES, { reduce: false, judge: false });
    assert.deepEqual(normal.findings, []);
    assert.equal(normal.measured.sites['animation pulse']?.maxMs, 1200);
    assert.equal(normal.measured.sites['animation spin']?.maxMs, 800);
    assert.equal(normal.measured.sites['transition background']?.maxMs, 120);
    // A shorter duration list repeats to the property list (CSS Transitions):
    // both properties are sited.
    const CYCLE = await judge('<style>.c { transition-property: opacity, color; transition-duration: 0.12s; }</style><main><span class="c">c</span></main>', { reduce: false, judge: false });
    assert.equal(CYCLE.measured.sites['transition opacity']?.maxMs, 120);
    assert.equal(CYCLE.measured.sites['transition color']?.maxMs, 120);
  });
});

describe('a11y.reduced-motion: the lane, planned, scoped and covered', unitBlock(), () => {
  const plan = (extra = {}) => planCases({ states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, zoom: ZOOM, textSpacing: TEXT_SPACING_CONDITION, reducedMotion: REDUCED_MOTION_CONDITION, ...extra });

  it('plans one case per distinct composition the state is swept at, plus its probe widths, and only in the lane on request', () => {
    const videos = plan({ onlyStates: ['videos'] }).cases.filter((c) => c.viewport.reducedMotion).map((c) => c.viewport.label);
    assert.deepEqual(videos, ['1366x768@reduced-motion', '1024x768@reduced-motion', '768x1024@reduced-motion', '390x844@reduced-motion']);
    assert.deepEqual(REDUCED_MOTION_CONDITION.anchors.map((a) => `${a.width}x${a.height}`), ['1366x768', '1024x768', '768x1024', '390x844']);
    const probed = STATES.find((s) => (s.probeWidths ?? []).includes(1600));
    const labels = plan({ onlyStates: [probed.name] }).cases.filter((c) => c.viewport.reducedMotion).map((c) => c.viewport.label);
    assert.ok(labels.includes('1600x900@reduced-motion'), labels.join(','));
    // Not every anchor: 1440, 1920 and 2560 render Tier A's composition again.
    // A case is a lane anchor or one of its own state's declared probe widths.
    const lane = new Set(REDUCED_MOTION_CONDITION.anchors.map((a) => `${a.width}x${a.height}`));
    for (const c of plan().cases.filter((x) => x.viewport.reducedMotion)) {
      const size = `${c.viewport.width}x${c.viewport.height}`;
      assert.ok(lane.has(size) || (c.state.probeWidths ?? []).includes(c.viewport.width), `${c.state.name} @ ${c.viewport.label}`);
    }
    const only = plan({ onlyReducedMotion: 'only' }).cases;
    assert.ok(only.length > 800 && only.every((c) => c.viewport.reducedMotion && !c.viewport.zoom && !c.viewport.textSpacing));
    const none = plan({ onlyReducedMotion: 'none' }).cases;
    assert.ok(none.length && none.every((c) => !c.viewport.reducedMotion));
    // A zoom-only or spacing-only run is of that lane alone.
    assert.ok(plan({ onlyZoom: 'only' }).cases.every((c) => !c.viewport.reducedMotion));
    assert.ok(plan({ onlyTextSpacing: 'only' }).cases.every((c) => !c.viewport.reducedMotion));
    // The workbench variants are not swept at Tier C: no 390 case for them.
    const wb = plan({ onlyStates: ['scene-editor-object-selected'] }).cases.filter((c) => c.viewport.reducedMotion).map((c) => c.viewport.label);
    assert.deepEqual(wb, ['1366x768@reduced-motion', '1024x768@reduced-motion', '768x1024@reduced-motion']);
  });

  it('gates the normal-preference control on the full sweep: the pulse, the spinner and a transition must be seen running', () => {
    const control = (sites) => [{ state: 's', viewport: '1366x768', kind: 'anchor', valid: true, normalMotion: sites }];
    const ALL = { 'animation pulse': { count: 1, maxMs: 1200 }, 'animation spin': { count: 1, maxMs: 800 }, 'transition background': { count: 3, maxMs: 120 } };
    assert.deepEqual(normalMotionControlFaults(control(ALL)), []);
    const { 'animation spin': _spin, ...noSpin } = ALL;
    assert.match(normalMotionControlFaults(control(noSpin))[0], /never saw the spin animation run/);
    const { 'transition background': _t, ...noTransition } = ALL;
    assert.match(normalMotionControlFaults(control(noTransition))[0], /never saw a transition run/);
    // A site seen only at zero (an ordinary case under a reduced preference) is not seen.
    assert.equal(normalMotionControlFaults(control({ ...ALL, 'animation pulse': { count: 1, maxMs: 0 } })).length, 1);
    // Wired into the full sweep when the plan holds the lane.
    const ledger = createLedger(RULES);
    const key = 'videos@1366x768@reduced-motion#1';
    const lanes = [{ state: 'videos', viewport: '1366x768@reduced-motion', attempt: 1, valid: true, reducedMotion: { active: true, measured: { elements: 9 } } }];
    let { faults } = sweepChecks({ results: [...lanes, ...control(noSpin)], cases: [{ key }, { key: 's@1366x768#1' }], errored: [], ledger, surfaces: [], fullSweep: true, plannedKeys: [key, 's@1366x768#1'] });
    assert.ok(faults.some((f) => /never saw the spin animation run/.test(f)), faults.join(' | '));
  });

  it('refuses the rule outside a reduced-motion case', () => {
    const ledger = createLedger(RULES);
    const normal = { state: { name: 'videos' }, viewport: { label: '1366x768', tier: 'A', kind: 'anchor' } };
    assert.throws(() => ledger.markEvaluated(normal, ['a11y.reduced-motion']), HarnessError);
    assert.throws(() => ledger.record(normal, 'a11y.reduced-motion', 'x'), HarnessError);
    const motion = { state: { name: 'videos' }, viewport: { label: '1366x768@reduced-motion', tier: 'A', kind: 'reduced-motion', reducedMotion: true } };
    ledger.markEvaluated(motion, ['a11y.reduced-motion']);
    assert.equal(ledger.coverage['a11y.reduced-motion'].A.evaluated, 1);
  });

  it('faults a planned composition missing, not reached, not proven under the preference, or judging nothing — over the sweep', () => {
    const keys = plan({ onlyStates: ['videos'] }).cases.filter((c) => c.viewport.reducedMotion).map((c) => caseKey({ state: c.state.name, viewport: c.viewport.label, attempt: c.attempt }));
    const good = (key) => { const [state, rest] = key.split('@'); const [w] = rest.split('#'); return { state, viewport: `${w.replace('@', '')}@reduced-motion`.replace('reduced-motion@reduced-motion', 'reduced-motion'), attempt: 1, valid: true, reducedMotion: { active: true, measured: { elements: 120 } } }; };
    const results = keys.map((k) => ({ ...good(k), viewport: k.replace(/^[^@]+@/, '').replace(/#\d+$/, '') }));
    assert.deepEqual(reducedMotionCoverageFaults(results, keys), []);
    // A required composition missing.
    assert.match(reducedMotionCoverageFaults(results.slice(1), keys)[0], /a11y\.reduced-motion: videos @ 1366x768@reduced-motion has no valid capture/);
    // Not reached.
    assert.match(reducedMotionCoverageFaults([{ ...results[0], valid: false }, ...results.slice(1)], keys)[0], /has no valid capture/);
    // Not proven under the preference.
    assert.match(reducedMotionCoverageFaults([{ ...results[0], reducedMotion: { active: false } }, ...results.slice(1)], keys)[0], /ran without prefers-reduced-motion: reduce proven in force/);
    // Judged nothing.
    assert.match(reducedMotionCoverageFaults([{ ...results[0], reducedMotion: { active: true, measured: { elements: 0 } } }, ...results.slice(1)], keys)[0], /judged no element/);
    // sweepChecks carries it on the full sweep, by the planned keys.
    const ledger = createLedger(RULES);
    const { faults } = sweepChecks({ results: results.slice(1), cases: keys.map((key) => ({ key })), errored: [], ledger, surfaces: [], fullSweep: true, plannedKeys: keys });
    assert.ok(faults.some((f) => /a11y\.reduced-motion: videos @ 1366x768@reduced-motion has no valid capture/.test(f)), faults.join('\n'));
  });
});

describe('the reduced-motion lane, end to end', () => {
  const e2e = e2eIt(it);
  const RUN = fileURLToPath(new URL('../run.mjs', import.meta.url));
  const REGISTERED = new URL('../states.mjs', import.meta.url).href;
  let dir;
  before(() => { dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-motion-')); });
  after(() => { rmSync(dir, { recursive: true, force: true }); });
  const run = (name, body, args) => {
    const module = join(dir, `${name}.mjs`);
    writeFileSync(module, `export * from ${JSON.stringify(REGISTERED)};\nimport { STATES as REGISTERED } from ${JSON.stringify(REGISTERED)};\n${body}\n`);
    const out = join(dir, name);
    const result = spawnSync(process.execPath, [RUN, '--workers', '1', ...args], { env: { ...process.env, MAVI_VQA_STATES_MODULE: module, MAVI_VQA_OUT: out }, encoding: 'utf8', timeout: 300_000 });
    assert.equal(result.error, undefined, 'the run hung');
    return { status: result.status, output: result.stdout + result.stderr, results: JSON.parse(readFileSync(join(out, 'results.json'), 'utf8')) };
  };
  const ONLY = (names, prepare = null) => `export const STATES = REGISTERED.filter((s) => ${JSON.stringify(names)}.includes(s.name)).map(({ zoomTransitions, ...s }) => (${prepare ? `{ ...s, prepare: ${JSON.stringify(prepare)} }` : 's'}));`;

  e2e('suppresses the product\'s real pulse, spinner and transitions under the preference, keeps them without it, and isolates the lane', () => {
    const { status, output, results } = run('product', ONLY(['processing-detail-running', 'import-loading']), ['--states', 'processing-detail-running,import-loading', '--widths', '1366', '--zoom', 'none', '--text-spacing', 'none']);
    assert.equal(status, 0, output);
    const motion = results.cases.filter((c) => c.kind === 'reduced-motion');
    const normal = results.cases.filter((c) => c.kind === 'anchor');
    assert.deepEqual(motion.map((c) => c.viewport), ['1366x768@reduced-motion', '1366x768@reduced-motion']);
    for (const c of motion) {
      assert.ok(c.valid && c.reducedMotion.active, JSON.stringify(c.reducedMotion));
      assert.deepEqual(c.reducedMotion.media, { matchMedia: true, css: true });
      const m = c.reducedMotion.measured;
      assert.ok(m.elements > 50 && m.transitionValues > 0 && m.animationValues > 0, JSON.stringify(m));
      assert.equal(m.positiveTransitions + m.positiveAnimations + m.unparseable + m.browserRunningPositive, 0, JSON.stringify(m));
      assert.deepEqual(m.sites, {});
    }
    // The control: the same states under the normal preference run the pulse,
    // the spinner and the --dur transitions at their design-system durations.
    const site = (state, key) => normal.find((c) => c.state === state)?.normalMotion?.[key]?.maxMs;
    assert.equal(site('processing-detail-running', 'animation pulse'), 1200);
    assert.equal(site('import-loading', 'animation spin'), 800);
    assert.ok(normal.some((c) => Object.entries(c.normalMotion ?? {}).some(([k, s]) => k.startsWith('transition ') && s.maxMs === 120)));
    // Isolation: the ordinary case run after a reduced-motion case on the same
    // lane (one worker) sees no reduced preference.
    for (const c of normal) assert.deepEqual(c.motionMedia, { matchMedia: false, css: false }, `${c.state} @ ${c.viewport}`);
    assert.equal(results.reducedMotion.otherCasesUnderReduce, 0);
  });

  e2e('faults a case whose page claims a preference the browser is not applying, and finds motion that escapes the product rule', () => {
    // The page replaces matchMedia: the lane's two readings disagree, the case
    // is not reached, and the run is a harness fault — never a pass.
    const SPOOF = `(() => { window.matchMedia = (q) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }); return true; })()`;
    let { status, output, results } = run('spoof', ONLY(['videos'], SPOOF), ['--states', 'videos', '--widths', '1366', '--zoom', 'none', '--text-spacing', 'none', '--reduced-motion', 'only']);
    assert.equal(status, 2, output);
    const c = results.cases.find((x) => x.kind === 'reduced-motion');
    assert.equal(c.valid, false);
    assert.match(c.unreached.reason, /prefers-reduced-motion: reduce is not in force \(matchMedia false, CSS media true\)/);
    // A rule more specific than the global `*` one, with !important, escapes
    // it: the lane finds the transition and the animation, and the run blocks.
    const ESCAPE = `(() => { const s = document.createElement('style'); s.textContent = '@keyframes vqa-spin { to { transform: rotate(360deg); } } main .vqa-escape { transition: opacity 600ms !important; transition-duration: 600ms !important; animation: vqa-spin 1s linear infinite !important; animation-duration: 1s !important; display: inline-block; width: 10px; height: 10px; }'; document.head.appendChild(s); const e = document.createElement('span'); e.className = 'vqa-escape'; document.querySelector('main').appendChild(e); return true; })()`;
    ({ status, output, results } = run('escape', ONLY(['videos'], ESCAPE), ['--states', 'videos', '--widths', '1366', '--zoom', 'none', '--text-spacing', 'none', '--reduced-motion', 'only']));
    assert.equal(status, 1, output);
    const found = results.findingsList.filter((f) => f.rule === 'a11y.reduced-motion' && f.severity === 'blocking').map((f) => f.message).join('\n');
    assert.match(found, /<span\.vqa-escape> has animation-duration 1s \(vqa-spin\) and transition-duration 0\.6s \(opacity\) under prefers-reduced-motion: reduce/);
    assert.match(found, /a running CSS animation vqa-spin with a 1000ms duration/);
  });
});
