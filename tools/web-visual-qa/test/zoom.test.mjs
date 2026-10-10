/**
 * T3 (§23): 200% browser page zoom on a 1366x768 viewport. The zoom is the
 * browser's own (cdp.mjs pageZoom) and is proven, not assumed: these tests
 * show the gate tells it apart from every impostor — 100%, a shrunk viewport,
 * device-pixel-ratio emulation, pinch scale — in real Chromium, that what the
 * 384px height can take from a page fails the zoom rule, that a live zoom
 * change is judged as it happens, and that a run fails, end to end, when the
 * zoom is not genuine or a zoom state is never reached.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { toExpression, zoomAssertions, zoomBeforeChange, zoomEnvironment, zoomTextSizes, zoomTransitionProbe } from '../assertions.mjs';
import { createLedger, HarnessError, planCases, zoomCoverageFaults, zoomQualification } from '../engine.mjs';
import { OPERATOR_SURFACES, ZOOM_CONDITION } from '../manifest.mjs';
import { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM } from '../states.mjs';
import { openBrowser } from './browser.mjs';

const plan = (states = STATES, extra = {}) => planCases({ states, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, zoom: ZOOM, ...extra });

describe('the zoom condition (§23, frozen)', () => {
  it('is 200% page zoom on the 1366x768 anchor, an effective 683x384 that is Tier C', () => {
    assert.deepEqual({ ...ZOOM_CONDITION }, { width: 1366, height: 768, factor: 2 });
    assert.ok(Object.isFrozen(ZOOM_CONDITION));
    assert.equal(ZOOM, ZOOM_CONDITION, 'the states sweep the frozen condition');
    assert.equal(tierOf(ZOOM.width / ZOOM.factor), 'C');
  });
});

describe('planning the zoom cases', () => {
  const { cases } = plan();
  const loads = cases.filter((c) => c.viewport.kind === 'zoom');
  const transitions = cases.filter((c) => c.viewport.kind === 'zoom-transition');

  it('captures every state swept at Tier C at 200%, plus the opted-in Tier C overlay probes, and no other', () => {
    const expected = STATES.filter((s) => TIER_POLICIES[s.tierPolicy ?? 'all-tiers'].tiers.includes('C') || s.zoomCapture).map((s) => s.name).sort();
    assert.deepEqual(loads.map((c) => c.state.name).sort(), expected);
    assert.ok(expected.includes('shell-menu-overlay') && expected.includes('videos-filters-drawer'));
    // A Workbench editing variant is not captured loaded at 200%: there is no
    // editor at Tier C to put in that state (its transitions carry it there).
    assert.ok(!expected.includes('scene-editor-dirty'));
    for (const c of loads) {
      assert.deepEqual([c.viewport.width, c.viewport.height, c.viewport.zoom, c.viewport.tier, c.viewport.label], [1366, 768, [2], 'C', '1366x768@200%']);
      assert.deepEqual(c.viewport.effective, { width: 683, height: 384 });
    }
  });

  it('reaches all ten operator surfaces at 200%', () => {
    const reached = new Set(loads.map((c) => c.surface));
    assert.equal(OPERATOR_SURFACES.length, 10);
    for (const surface of OPERATOR_SURFACES) assert.ok(reached.has(surface), `${surface} has no 200% capture`);
  });

  it('takes each declared transition from the tier it starts at to the tier it ends at', () => {
    const find = (name, label) => transitions.find((c) => c.state.name === name && c.viewport.label === label);
    const there = find('videos', '1366x768@100%-200%-100%');
    assert.deepEqual([there.viewport.startTier, there.viewport.tier], ['A', 'A']);
    const into = find('overview', '1366x768@100%-200%.rail-link-focused');
    assert.deepEqual([into.viewport.startTier, into.viewport.tier, into.viewport.effective], ['A', 'C', { width: 683, height: 384 }]);
    const out = find('shell-menu-overlay', '1366x768@200%-100%');
    assert.deepEqual([out.viewport.startTier, out.viewport.tier], ['C', 'A']);
    // The brief's ten transitions, each present.
    for (const [name, label] of [
      ['videos', '1366x768@100%-200%-100%'], ['shell-menu-overlay', '1366x768@200%-100%'], ['search', '1366x768@200%-100%.filters-open'],
      ['search-inspector-opened', '1366x768@100%-200%-100%'], ['videos-filters-drawer', '1366x768@200%-100%'], ['search', '1366x768@100%-200%-100%.result-focused'],
      ['scene-editor-dirty', '1366x768@100%-200%-100%'], ['scene-editor-discard-dialog', '1366x768@100%-200%'], ['review-transport', '1366x768@100%-200%-100%'],
      ['import-invalid', '1366x768@100%-200%-100%'], ['search-grid', '1366x768@100%-200%-100%'], ['scene-editor-dirty', '1366x768@100%-200%.leave-guard'],
    ]) assert.ok(find(name, label), `${name} @ ${label}`);
  });

  it('runs the zoom cases alone, or leaves them out, on request', () => {
    assert.ok(plan(STATES, { onlyZoom: 'only' }).cases.every((c) => c.viewport.zoom));
    assert.ok(plan(STATES, { onlyZoom: 'none' }).cases.every((c) => !c.viewport.zoom));
    assert.equal(plan(STATES, { zoom: null }).cases.filter((c) => c.viewport.zoom).length, 0);
  });

  it('refuses a malformed transition or zoom capture instead of running it', () => {
    const base = STATES.find((s) => s.name === 'videos');
    const refuse = (state, pattern) => assert.throws(() => plan([{ ...base, ...state }]), (error) => error instanceof HarnessError && pattern.test(error.message));
    refuse({ zoomTransitions: [{ path: [2] }] }, /changes between 100% and 200% at every step/);
    refuse({ zoomTransitions: [{ path: [1, 1] }] }, /changes between 100% and 200% at every step/);
    refuse({ zoomTransitions: [{ path: [1, 3] }] }, /changes between 100% and 200% at every step/);
    refuse({ zoomTransitions: [{ path: [1, 2], checks: ['a', 'b'] }] }, /more zoom-transition checks than zoom changes/);
    refuse({ zoomTransitions: [{ path: [1, 2], wait: 500 }] }, /unknown key "wait"/);
    refuse({ zoomTransitions: [{ path: [1, 2] }, { path: [1, 2] }] }, /share the label/);
    refuse({ zoomCapture: 'yes' }, /zoomCapture must be true/);
    const scene = STATES.find((s) => s.name === 'scene-editor-dirty');
    // A Workbench variant is not swept at Tier C: no transition may start there.
    assert.throws(() => plan([{ ...scene, zoomTransitions: [{ path: [2, 1] }] }]), /starts at Tier C, where the state is not swept/);
    assert.throws(() => plan([{ ...scene, zoomCapture: true }]), /not swept at Tier C, where it lands/);
  });
});

describe('the zoom rule is a zoom case\'s alone', () => {
  it('is refused, as a harness fault, in a case with no page zoom — a shrunk viewport cannot stand in', () => {
    const ledger = createLedger();
    const shrunk = { state: { name: 's' }, viewport: { tier: 'C', label: '683x384', kind: 'probe' } };
    assert.throws(() => ledger.record(shrunk, 'a11y.zoom-200', 'x'), (error) => error instanceof HarnessError && /not a zoom case/.test(error.message));
    assert.throws(() => ledger.markEvaluated(shrunk, ['a11y.zoom-200']), /not a zoom case/);
    const zoomed = { state: { name: 's' }, viewport: { tier: 'C', label: '1366x768@200%', kind: 'zoom', zoom: [2] } };
    assert.equal(ledger.record(zoomed, 'a11y.zoom-200', 'x').severity, 'blocking');
    const back = { state: { name: 's' }, viewport: { tier: 'A', label: '1366x768@200%-100%', kind: 'zoom-transition', zoom: [2, 1] } };
    assert.equal(ledger.record(back, 'a11y.zoom-200', 'x').severity, 'blocking');
    assert.throws(() => ledger.record({ ...zoomed, viewport: { ...zoomed.viewport, tier: 'B' } }, 'a11y.zoom-200', 'x'), /not applicable/);
  });

  it('makes a full sweep a harness fault where a surface was never judged at 200%, or a transition never evaluated', () => {
    const results = OPERATOR_SURFACES.map((surface) => ({ valid: true, kind: 'zoom', surface, zoom: { evaluated: true } }));
    assert.deepEqual(zoomCoverageFaults(results, OPERATOR_SURFACES), []);
    const missing = results.filter((r) => r.surface !== 'review');
    assert.deepEqual(zoomCoverageFaults(missing, OPERATOR_SURFACES), ['a11y.zoom-200: the full sweep has no valid 200% zoom capture of review that evaluated it']);
    const unevaluated = [...results, { valid: false, kind: 'zoom-transition', state: 'videos', viewport: '1366x768@100%-200%', zoom: { evaluated: false } }];
    assert.match(zoomCoverageFaults(unevaluated, OPERATOR_SURFACES)[0], /zoom transition videos @ 1366x768@100%-200% was never evaluated/);
  });
});

describe('in Chromium: genuine 200% page zoom, and the impostors the gate refuses', () => {
  let lane;
  before(async () => { lane = await openBrowser(); });
  after(async () => { await lane.close(); });
  const PAGE = '<style>body{margin:0;font:14px sans-serif}</style><div class="context-bar"><span>Videos</span></div><p>text</p>';
  const measure = async () => ({
    reported: lane.zoom,
    metrics: await lane.browser.layoutMetrics(),
    page: await lane.browser.evaluate(toExpression(zoomEnvironment)),
  });
  const qualify = (m) => zoomQualification({ factor: ZOOM_CONDITION.factor, viewport: ZOOM_CONDITION, ...m });

  it('qualifies the browser\'s own 200% page zoom on a 1366x768 viewport', async () => {
    await lane.page(PAGE, { width: 1366, height: 768, zoom: 2 });
    const m = await measure();
    assert.deepEqual(qualify(m), []);
    assert.equal(m.metrics.pageZoom, 2);
    assert.deepEqual(m.metrics.dipViewport, { width: 1366, height: 768 });
    assert.deepEqual([m.page.innerWidth, m.page.innerHeight, m.page.dpr, m.page.media.narrow], [683, 384, 2, true]);
    // Text grows with the page: the same CSS size, drawn at twice the device-independent size.
    await lane.page(PAGE, { width: 1366, height: 768, zoom: 1 });
    const at100 = await measure();
    assert.equal(m.page.bodyFontPx * m.metrics.pageZoom, 2 * at100.page.bodyFontPx * at100.metrics.pageZoom);
  });

  it('refuses the zoom left at 100%', async () => {
    await lane.page(PAGE, { width: 1366, height: 768, zoom: 1 });
    const problems = qualify(await measure());
    assert.ok(problems.some((p) => /page-zoom setting is 100%, not 200%/.test(p)), problems.join('\n'));
    assert.ok(problems.some((p) => /applies a page zoom of 1, not 2/.test(p)));
    assert.ok(problems.some((p) => /media queries see Tier A/.test(p)));
  });

  it('refuses a viewport merely shrunk to 683x384', async () => {
    await lane.page(PAGE, { width: 683, height: 384, zoom: 1 });
    const m = await measure();
    // The page alone cannot tell: it is 683x384 and Tier C either way.
    assert.deepEqual([m.page.innerWidth, m.page.innerHeight, m.page.media.narrow], [683, 384, true]);
    const problems = qualify(m);
    assert.ok(problems.some((p) => /viewport is 683x384 device-independent px, not 1366x768/.test(p)), problems.join('\n'));
    assert.ok(problems.some((p) => /applies a page zoom of 1, not 2/.test(p)));
    assert.ok(problems.some((p) => /devicePixelRatio is 1/.test(p)));
  });

  it('refuses device-pixel-ratio emulation at 683x384, which gives devicePixelRatio 2 without zoom', async () => {
    await lane.page(PAGE, { width: 683, height: 384, zoom: 1 });
    await lane.browser.cdp('Emulation.setDeviceMetricsOverride', { width: 683, height: 384, deviceScaleFactor: 2, mobile: false });
    const m = await measure();
    assert.equal(m.page.dpr, 2);
    const problems = qualify(m);
    assert.ok(problems.some((p) => /applies a page zoom of 1, not 2/.test(p)), problems.join('\n'));
    assert.ok(problems.some((p) => /viewport is 683x384 device-independent px/.test(p)));
  });

  it('refuses pinch scale, which magnifies without reflowing', async () => {
    await lane.page(PAGE, { width: 1366, height: 768, zoom: 1 });
    await lane.browser.cdp('Emulation.setPageScaleFactor', { pageScaleFactor: 2 });
    const m = await measure();
    await lane.browser.cdp('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
    const problems = qualify(m);
    assert.ok(problems.some((p) => /pinch-scaled/.test(p)), problems.join('\n'));
    assert.ok(problems.some((p) => /page sees 1366x768/.test(p)));
  });
});

describe('what the 384px height can take from a page at 200% (zoomAssertions)', () => {
  let lane;
  before(async () => { lane = await openBrowser(); });
  after(async () => { await lane.close(); });
  const TOKENS = '<style>body{margin:0;font:14px sans-serif} button:focus{outline:2px solid #fff}</style>';
  const at200 = async (html) => {
    await lane.page(TOKENS + html, { width: 1366, height: 768, zoom: 2 });
    return lane.browser.evaluate(toExpression(zoomAssertions, { tier: 'C' }));
  };
  const messages = (result) => result.findings.map((f) => f.message).join('\n');

  it('fails a control a fixed region cuts off below the viewport, and passes it once the region scrolls', async () => {
    const PANEL = (overflow) => `<div style="position:fixed;inset:0 auto 0 0;width:300px;overflow:${overflow}">
      <div style="height:420px">brand and links</div><button>Close navigation</button></div>`;
    const clipped = await at200(PANEL('hidden'));
    assert.match(messages(clipped), /"Close navigation".*(cannot be brought into the 683x384 view|cut off|shown only by focus scrolling)/);
    assert.ok(clipped.evaluated.includes('a11y.zoom-200'));
    assert.ok(clipped.measured.controls >= 1);
    assert.equal(messages(await at200(PANEL('auto'))), '');
  });

  it('fails a control partly cut off, or partly covered away from its middle (Codex P1)', async () => {
    // 40% of the button outside a box that clips and cannot scroll it into view.
    const CUT = (width) => `<div style="width:${width}px;overflow:hidden;white-space:nowrap"><button style="width:200px">Retry processing</button></div>`;
    assert.match(messages(await at200(CUT(120))), /"Retry processing" is cut off even when focused \(80px of its width, 0px of its height\)/);
    assert.equal(messages(await at200(CUT(220))), '');
    // Larger than the viewport, it is not let off by the viewport's size (Codex P1).
    assert.match(messages(await at200('<button style="width:1000px">Load more results</button>')), /"Load more results" is cut off even when focused \(\d+px of its width/);
    // A band covering the button's lower edge, clear of its middle.
    const EDGE = (paint) => `<div style="height:250px">top</div><button style="display:block;height:60px">Detail</button>
      <div style="position:fixed;left:0;right:0;bottom:${384 - 250 - 60}px;height:16px;background:${paint}"></div>`;
    assert.match(messages(await at200(EDGE('#000'))), /"Detail" is covered by <div>/);
  });

  it('fails a focusable control that stays 1px even when focused, and passes the skip link and a labelled native input (Codex P1)', async () => {
    const HIDDEN = 'position:absolute;width:1px;height:1px;padding:0;border:0;overflow:hidden;clip-path:inset(50%)';
    assert.match(messages(await at200(`<button style="${HIDDEN}">Delete zone</button>`)), /"Delete zone" can be focused but is not shown, even when focused/);
    assert.equal(messages(await at200(`<style>.skip{${HIDDEN}} .skip:focus{width:auto;height:auto;clip-path:none}</style><a class="skip" href="#main">Skip to workspace</a><main id="main"></main>`)), '');
    assert.equal(messages(await at200(`<input id="c" type="checkbox" style="${HIDDEN}"><label for="c">Trajectory</label>`)), '');
    // Transparent counts as unseen too (Codex P1): its own opacity or an ancestor's.
    assert.match(messages(await at200('<div style="opacity:0"><button>Delete zone</button></div>')), /"Delete zone" can be focused but is not shown, even when focused/);
    // The page faded as a whole counts as well (Codex P1).
    assert.match(messages(await at200('<style>html{opacity:0}</style><button>Delete zone</button>')), /"Delete zone" can be focused but is not shown, even when focused/);
    assert.equal(messages(await at200('<label><input type="checkbox" style="opacity:0;position:absolute"> Trajectory</label>')), '');
    // The label standing for it must itself be seen: not transparent, not covered (Codex P1).
    assert.match(messages(await at200(`<input id="t" type="checkbox" style="${HIDDEN}"><label for="t" style="opacity:0">Trajectory</label>`)), /can be focused but is not shown, even when focused/);
    assert.match(messages(await at200(`<div style="height:250px"></div><input id="u" type="checkbox" style="${HIDDEN}"><label for="u" style="display:block;height:40px">Trajectory</label><div style="height:10px"></div>
      <div style="position:fixed;inset:auto 0 0 0;height:200px;background:#000">band</div>`)), /is covered by <div> "band" when focused/);
  });

  it('fails a step back up a column, and keeps side-by-side columns read one after the other (Codex P1)', async () => {
    const PAGE = (body) => `<main><section class="page">${body}</section></main>`;
    // Down one column, the keyboard reaches the lower control first.
    assert.match(messages(await at200(PAGE('<div style="display:flex;flex-direction:column-reverse"><button>Second</button><button>First</button></div>'))),
      /the keyboard reaches <button> "First" after <button> "Second", but it is drawn above it in the same column/);
    assert.equal(messages(await at200(PAGE('<div style="display:flex;flex-direction:column"><button>First</button><button>Second</button></div>'))), '');
    // Two columns, each read down before the next (a Tier C Ledger row: its
    // identity, then the action column beside it) — the composition's order.
    assert.equal(messages(await at200(PAGE(`<div style="display:grid;grid-template-columns:1fr 1fr;grid-auto-flow:column;grid-template-rows:auto auto">
      <button>Top left</button><button>Bottom left</button><button>Top right</button><button>Bottom right</button></div>`))), '');
  });

  it('fails a control only focus can scroll into a box that clips', async () => {
    const BOX = (overflow) => `<div style="height:120px;overflow:${overflow}"><div style="height:200px">facts</div><button>Retry</button></div>`;
    assert.match(messages(await at200(BOX('hidden'))), /"Retry" is shown only by focus scrolling .*which clips without scrolling/);
    assert.equal(messages(await at200(BOX('auto'))), '');
  });

  it('fails a control hidden under a painted layer the pointer passes through, and passes a card face over its own select button (T3 cold review)', async () => {
    // A fixed band with pointer-events: none hides what is under it all the same.
    const BAND = (paint) => `<style>body::after{content:"";position:fixed;left:0;right:0;bottom:0;height:200px;background:${paint};pointer-events:none}</style>
      <div style="height:250px">top</div><button>Detail</button><div style="height:10px"></div>`;
    assert.match(messages(await at200(BAND('#000'))), /"Detail" is hidden under <body>.*a layer the pointer passes through still covers it/);
    assert.equal(messages(await at200(BAND('transparent'))), '');
    // A grid card: a transparent select button under its own drawn face.
    const CARD = `<article style="position:relative;width:300px;height:160px">
      <button aria-label="Select Person" style="position:absolute;inset:0;background:transparent;border:0"></button>
      <span style="position:relative;display:block;height:120px;background:#333;pointer-events:none">No image</span></article>`;
    assert.equal(messages(await at200(CARD)), '');
    // An absolutely placed pass-through layer over an ordinary control covers it (Codex P1).
    assert.match(messages(await at200(`<div style="position:relative;width:300px;height:120px"><button style="width:200px;height:40px">Retry</button>
      <span style="position:absolute;inset:0;background:#000;pointer-events:none">badge</span></div>`)), /"Retry" is hidden under <span> "badge"/);
  });

  it('fails a control only focus can bring into a page that hides its overflow (T3 cold review)', async () => {
    const PAGE = (overflow) => `<style>html{overflow:${overflow}}</style><div style="height:500px">facts</div><button>Retry</button>`;
    assert.match(messages(await at200(PAGE('hidden'))), /"Retry" is shown only by focus scrolling the page, which hides its overflow/);
    assert.equal(messages(await at200(PAGE('auto'))), '');
  });

  it('fails a focused control covered by a fixed band', async () => {
    const PAGE = (cover) => `<div style="height:300px">top</div><button style="display:block;margin-bottom:${cover ? 0 : 80}px">Play</button>
      ${cover ? '<div style="position:fixed;left:0;right:0;bottom:0;height:120px;background:#222">transport bar</div>' : ''}<div style="height:10px"></div>`;
    assert.match(messages(await at200(PAGE(true))), /"Play" is covered by <div> "transport bar" when focused/);
    assert.equal(messages(await at200(PAGE(false))), '');
  });

  it('fails a drawer or dialog that does not fit the viewport', async () => {
    const DRAWER = (width) => `<div role="dialog" aria-modal="true" aria-label="Filters" style="position:fixed;top:0;right:0;bottom:0;width:${width}"><button>Apply</button></div>`;
    assert.match(messages(await at200(DRAWER('800px'))), /<div> "Filters" is 800x384 at \(-117, 0\) and does not fit the 683x384 viewport/);
    assert.equal(messages(await at200(DRAWER('100%'))), '');
  });

  it('fails text sized in viewport units, which does not grow with the zoom', async () => {
    assert.match(messages(await at200('<style>.title{font-size:2.5vw}</style><p class="title">Videos</p>')), /"\.title" sets its font size in viewport units/);
    assert.match(messages(await at200('<p style="font-size:3vmin">Videos</p>')), /<p> "Videos" \(inline\) sets its font size in viewport units \(3vmin\)/);
    assert.equal(messages(await at200('<style>.title{font-size:1.25rem}</style><p class="title">Videos</p>')), '');
    // Through custom properties, to any depth (T3 cold review).
    assert.match(messages(await at200('<style>:root{--size:3vw;--title:var(--size)}.title{font-size:var(--title)}</style><p class="title">Videos</p>')), /"\.title" sets its font size in viewport units \(var\(--title\)\)/);
    assert.match(messages(await at200('<style>:root{--title:calc(1rem + 2vw)}.title{font:600 var(--title)/1.2 sans-serif}</style><p class="title">Videos</p>')), /"\.title" sets its font size in viewport units/);
    assert.equal(messages(await at200('<style>:root{--title:1.25rem}.title{font-size:var(--title)}</style><p class="title">Videos</p>')), '');
  });

  it('fails truncated text whose full value the keyboard cannot reach (§16)', async () => {
    const NAME = 'north-gate-0900-very-long-original-file-name.mp4';
    const CUT = 'display:block;width:120px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis';
    assert.match(messages(await at200(`<span style="${CUT}">${NAME}</span>`)), /truncated text "north-gate-0900.*cannot be focused to show its full value/);
    // Focusable only to be read, it must describe itself with the whole value (the Tooltip).
    assert.match(messages(await at200(`<span tabindex="0" style="${CUT}">${NAME}</span>`)), /can be focused, but focus does not show its full value/);
    assert.equal(messages(await at200(`<span tabindex="0" aria-describedby="tip" style="${CUT}">${NAME}</span><span role="tooltip" id="tip" hidden>${NAME}</span>`)), '');
    // The drawn value may set a code apart where the tooltip joins it with a separator.
    assert.equal(messages(await at200(`<span tabindex="0" aria-describedby="cam" style="${CUT}"><strong>CAM-02</strong> Perimeter fence south-west sector</span><span role="tooltip" id="cam" hidden>CAM-02 · Perimeter fence south-west sector</span>`)), '');
    assert.match(messages(await at200(`<span tabindex="0" aria-describedby="cam" style="${CUT}"><strong>CAM-02</strong> Perimeter fence south-west sector</span><span role="tooltip" id="cam" hidden>CAM-02</span>`)), /can be focused, but focus does not show its full value/);
    // A link to the row's detail leads to the full-value home (§16), and so
    // does a row's own selection button, to its inspector.
    assert.equal(messages(await at200(`<a href="/processing/1" style="${CUT}">${NAME}</a>`)), '');
    // Any other button acts in place: its truncated label must say the whole on focus (Codex P1),
    // in a row too — only the row's selection control leads to its inspector.
    assert.match(messages(await at200(`<button style="${CUT}">${NAME}</button>`)), /can be focused, but focus does not show its full value/);
    assert.match(messages(await at200(`<ul><li><button style="${CUT}">Retry ${NAME}</button></li></ul>`)), /can be focused, but focus does not show its full value/);
    assert.equal(messages(await at200(`<ul><li><button class="scene-navigator__name" aria-pressed="false" style="${CUT}">${NAME}</button></li></ul>`)), '');
    assert.equal(messages(await at200(`<ul><li><button class="result-select" style="${CUT}">${NAME}</button></li></ul>`)), '');
    // aria-pressed alone is a toggle's state too: no lead to the full value (Codex P1).
    assert.match(messages(await at200(`<ul><li><button aria-pressed="false" style="${CUT}">Favourite ${NAME}</button></li></ul>`)), /can be focused, but focus does not show its full value/);
  });

  it('fails a Context Bar whose keyboard order is not its visual order — the menu drawn first but reached last', async () => {
    const BAR = (moved) => `<div class="context-bar" style="display:flex;gap:8px;height:44px">
      ${moved ? '' : '<button class="shell__menu" aria-label="Open navigation">M</button>'}<a href="/cameras">Cameras</a><button>Import video</button>
      ${moved ? '<button class="shell__menu" aria-label="Open navigation" style="order:-1">M</button>' : ''}</div>`;
    assert.match(messages(await at200(BAR(true))), /in the Context Bar the keyboard reaches <button.shell__menu> "Open navigation" after <button> "Import video", but it is drawn before it/);
    assert.equal(messages(await at200(BAR(false))), '');
    // The order Tab visits, not the document's (Codex P1): a positive tabindex goes first.
    assert.match(messages(await at200(`<div class="context-bar" style="display:flex;gap:8px;height:44px">
      <button class="shell__menu" aria-label="Open navigation">M</button><a href="/cameras">Cameras</a><button tabindex="1">Import video</button></div>`)),
      /keyboard reaches <button.shell__menu> "Open navigation" after <button> "Import video", but it is drawn before it/);
  });
});

describe('a live zoom change (zoomTransitionProbe)', () => {
  let lane;
  before(async () => { lane = await openBrowser(); });
  after(async () => { await lane.close(); });
  // A page whose composition changes at 768px CSS, as the product's does.
  const PAGE = `<style>@media (width < 768px) { .wide { display: none } } body{margin:0}</style>
    <main id="main" tabindex="-1"><button class="wide">Collapse navigation</button><button class="always">Detail</button></main>`;
  const across = async (html, setup) => {
    await lane.page(html, { width: 1366, height: 768, zoom: 1 });
    await lane.browser.evaluate(setup);
    await lane.browser.evaluate(toExpression(zoomBeforeChange));
    lane.zoom = await lane.browser.pageZoom(2);
    return lane.browser.evaluate(toExpression(zoomTransitionProbe));
  };
  const messages = (result) => result.findings.map((f) => f.message).join('\n');

  it('fails focus that the zoom drops to the document, and passes focus that stays on a shown control', async () => {
    assert.match(messages(await across(PAGE, '(() => { document.querySelector(".wide").focus(); return true; })()')), /focus fell to the document when the zoom changed \(it was on <button.wide> "Collapse navigation"\)/);
    assert.equal(messages(await across(PAGE, '(() => { document.querySelector(".always").focus(); return true; })()')), '');
  });

  it('fails focus left out of view or under a layer by the zoom change, at every step (Codex P1)', async () => {
    const MOVED = `<style>body{margin:0} @media (width < 768px) { .push { height: 900px } .band { display: block !important } }</style>
      <main id="main"><div class="push"></div><button class="target">Detail</button><div style="height:10px"></div></main>
      <div class="band" style="display:none;position:fixed;inset:0;background:#000">overlay band</div>`;
    assert.match(messages(await across(MOVED, '(() => { document.querySelector(".target").focus(); return true; })()')), /focus is left on <button.target> "Detail", (out of view|covered by .*) after the zoom change/);
  });

  it('names text whose CSS size changes with the zoom, which does not grow by it (Codex P1)', async () => {
    const SHRINKS = (size) => `<style>body{margin:0;font:14px sans-serif} @media (width < 768px) { .label { font-size: ${size} } }</style>
      <main id="main"><p>Videos</p><span class="label">north-gate-0800.mp4</span></main>`;
    const change = async (html) => {
      await lane.page(html, { width: 1366, height: 768, zoom: 1 });
      await lane.browser.evaluate(toExpression(zoomTextSizes));
      lane.zoom = await lane.browser.pageZoom(2);
      return lane.browser.evaluate(toExpression(zoomTextSizes));
    };
    const shrunk = await change(SHRINKS('7px'));
    assert.deepEqual(shrunk.changed, ['"north-gate-0800.mp4" (14px -> 7px)']);
    const kept = await change(SHRINKS('14px'));
    assert.ok(kept.compared >= 2);
    assert.deepEqual(kept.changed, []);
  });

  it('fails focus the zoom change leaves on a transparent control (Codex P1)', async () => {
    const FADED = `<style>body{margin:0} @media (width < 768px) { .fades { opacity: 0 } }</style>
      <main id="main"><button class="fades">Detail</button></main>`;
    assert.match(messages(await across(FADED, '(() => { document.querySelector(".fades").focus(); return true; })()')), /focus is left on <button.fades> "Detail", which the zoom change has made transparent/);
  });

  it('fails an overlay left open with focus outside it, and a region left inert with no overlay open', async () => {
    const OPEN = `<main id="main"><button id="out">Outside</button></main><div role="dialog" aria-modal="true" aria-label="Filters"><button>In</button></div>`;
    assert.match(messages(await across(OPEN, '(() => { document.getElementById("out").focus(); return true; })()')), /"Filters" is still open after the zoom change, but focus is on <button> "Outside", outside it/);
    const INERT = '<main id="main"><button id="b">Detail</button></main><aside inert><button>Nav</button></aside>';
    assert.match(messages(await across(INERT, '(() => { document.getElementById("b").focus(); return true; })()')), /1 region\(s\) are left inert after the zoom change with no overlay open/);
  });
});

describe('the run, end to end, at 200% zoom', () => {
  const RUN = fileURLToPath(new URL('../run.mjs', import.meta.url));
  const REGISTERED = new URL('../states.mjs', import.meta.url).href;
  let dir;
  before(() => { dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-zoom-')); });
  after(() => { rmSync(dir, { recursive: true, force: true }); });
  const run = (name, body, args) => {
    const module = join(dir, `${name}.mjs`);
    writeFileSync(module, `export * from ${JSON.stringify(REGISTERED)};
import { STATES as REGISTERED } from ${JSON.stringify(REGISTERED)};
${body}
`);
    const out = join(dir, name);
    const result = spawnSync(process.execPath, [RUN, '--zoom', 'only', '--workers', '1', ...args], {
      env: { ...process.env, MAVI_VQA_STATES_MODULE: module, MAVI_VQA_OUT: out }, encoding: 'utf8', timeout: 180_000,
    });
    assert.equal(result.error, undefined, 'the run hung');
    const output = result.stdout + result.stderr;
    assert.ok(existsSync(join(out, 'results.json')), `the run wrote no results (exit ${result.status}):
${output}`);
    return { status: result.status, output, results: JSON.parse(readFileSync(join(out, 'results.json'), 'utf8')) };
  };
  const VIDEOS = 'export const STATES = REGISTERED.filter((s) => s.name === "videos").map(({ zoomTransitions, ...s }) => s);';

  it('fails, blocking, when the zoom is left at 100%', () => {
    const { status, output, results } = run('at-100', `${VIDEOS}\nexport const ZOOM = { width: 1366, height: 768, factor: 1 };`, ['--states', 'videos']);
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200');
    assert.ok(zoom.length && zoom.every((f) => f.severity === 'blocking'));
    assert.ok(zoom.some((f) => /applies a page zoom of 1, not 2/.test(f.message)), JSON.stringify(zoom));
  });

  it('fails, blocking, when the viewport is merely shrunk to 683x384', () => {
    const { status, output, results } = run('shrunk', `${VIDEOS}\nexport const ZOOM = { width: 683, height: 384, factor: 1 };`, ['--states', 'videos']);
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.tier === 'C');
    assert.ok(zoom.some((f) => /viewport is 683x384 device-independent px, not 1366x768/.test(f.message)), JSON.stringify(zoom));
    assert.ok(zoom.every((f) => f.severity === 'blocking'));
  });

  it('passes the genuine zoom of the same state, its zoom proven', () => {
    const { status, output, results } = run('genuine', VIDEOS, ['--states', 'videos']);
    assert.equal(status, 0, output);
    assert.equal(results.executions.zoom.qualified, 1);
    assert.equal(results.executions.zoom.sample.metrics.pageZoom, 2);
  });

  it('is a harness fault when a transition\'s starting state is not the one it declares (T3 cold review)', () => {
    const { status, output, results } = run('start', `export const STATES = REGISTERED.filter((s) => s.name === "videos").map((s) => ({ ...s, expectText: 'Text this page never shows', zoomTransitions: [{ path: [1, 2], expectText: '4 of 4 videos' }] }));`, ['--states', 'videos']);
    assert.equal(status, 2, output);
    assert.ok(results.harnessErrors.some((e) => /videos @ 1366x768@100%-200% \(Tier C\): the declared state was not reached at navigation settle/.test(e)), results.harnessErrors.join('\n'));
  });

  it('judges a transition against the frozen 200%, whatever factor the states declare (T3 cold review)', () => {
    const { status, output, results } = run('factor', `export const ZOOM = { width: 1366, height: 768, factor: 1.8 };
export const STATES = REGISTERED.filter((s) => s.name === "videos").map((s) => ({ ...s, zoomTransitions: [{ path: [1, 1.8] }] }));`, ['--states', 'videos']);
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && /1366x768@100%-180%/.test(f.viewport));
    assert.ok(zoom.some((f) => /applies a page zoom of 1\.(8|79\d*), not 2/.test(f.message) && f.severity === 'blocking'), JSON.stringify(zoom));
  });

  it('judges a transition\'s prepared starting state at 200% before leaving it (Codex P1)', () => {
    const WIDE = `(() => { const s = document.createElement('style'); s.textContent = '.toolbar-band__controls[aria-modal="true"]{width:900px!important;max-width:none!important}'; document.head.appendChild(s); return true; })()`;
    const { status, output, results } = run('prepared', `export const STATES = REGISTERED.filter((s) => s.name === "videos-filters-drawer").map(({ zoomCapture, ...s }) => ({ ...s, zoomTransitions: [{ path: [2, 1], before: ${JSON.stringify(WIDE)} }] }));`, ['--states', 'videos-filters-drawer']);
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@200%-100%');
    assert.ok(zoom.some((f) => /^at the start \(200%\): .* does not fit the 683x384 viewport/.test(f.message) && f.severity === 'blocking'), JSON.stringify(zoom));
  });

  it('is a harness fault when a required zoom state is never reached', () => {
    const { status, output, results } = run('unreached', `export const STATES = REGISTERED.filter((s) => s.name === "videos").map((s) => ({ ...s, zoomTransitions: [{ path: [1, 2], before: '(() => false)()' }] }));`, ['--states', 'videos']);
    assert.equal(status, 2, output);
    assert.ok(results.harnessErrors.some((e) => /videos @ 1366x768@100%-200% \(Tier C\): the declared state was not reached at zoom transition set-up/.test(e)), results.harnessErrors.join('\n'));
  });
});
