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
import { toExpression, zoomAssertions, zoomBeforeChange, zoomEnvironment, zoomTextBaseline, zoomTextCompare, zoomTransitionProbe } from '../assertions.mjs';
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
    const results = OPERATOR_SURFACES.map((surface) => ({ valid: true, kind: 'zoom', surface, zoom: { evaluated: true, text: { compared: 1 } } }));
    assert.deepEqual(zoomCoverageFaults(results, OPERATOR_SURFACES), []);
    const missing = results.filter((r) => r.surface !== 'review');
    assert.deepEqual(zoomCoverageFaults(missing, OPERATOR_SURFACES), ['a11y.zoom-200: the full sweep has no valid 200% zoom capture of review that evaluated it']);
    const unevaluated = [...results, { valid: false, kind: 'zoom-transition', state: 'videos', viewport: '1366x768@100%-200%', zoom: { evaluated: false, text: { compared: 1 } } }];
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

  it('treats a control collapsed in either dimension, or to nothing, as unseen (Codex P1-A)', async () => {
    const LINE = (w, h) => `<button style="display:block;width:${w};height:${h};padding:0;border:0;overflow:hidden">Delete zone</button>`;
    for (const [w, h] of [['1px', '32px'], ['32px', '1px'], ['1px', '1px'], ['0', '0']]) {
      assert.match(messages(await at200(LINE(w, h))), /"Delete zone" can be focused but is not shown, even when focused/, `${w} x ${h}`);
    }
    // Adversarial: collapsed by its box rather than by its own size.
    assert.match(messages(await at200('<div style="width:1px;height:40px;overflow:hidden"><button style="width:200px;height:40px">Delete zone</button></div>')), /"Delete zone"/);
    assert.equal(messages(await at200(LINE('120px', '32px'))), '');
  });

  it('includes the root in the clip chain (Codex P1-B)', async () => {
    assert.match(messages(await at200('<style>html{clip-path:inset(0 0 0 15%)}</style><button style="width:200px;height:40px">Retry processing</button>')), /"Retry processing" is cut off even when focused \(\d+px of its width/);
    assert.match(messages(await at200('<style>html{clip-path:circle(40%)}</style><button style="width:200px;height:40px">Retry processing</button>')), /clip-path circle\(40%\), which the harness cannot measure/);
    // A fixed control is clipped by the root's clip-path too: it covers the
    // whole page (whose box must have height: a root with no in-flow content
    // is 0px tall, and its clip-path then clips everything — as Chrome does).
    assert.match(messages(await at200('<style>html{clip-path:inset(0 0 0 15%)}</style><div style="height:400px"></div><button style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button>')), /"Retry processing" is cut off even when focused \(\d+px of its width/);
    assert.equal(messages(await at200('<style>html{clip-path:inset(0)}</style><button style="width:200px;height:40px">Retry processing</button>')), '');
  });

  it('measures the Evidence Player by its intrinsic size and box, not by an object-fit whitelist (Codex P1-C)', async () => {
    // Footage from a canvas stream, so the video has intrinsic dimensions.
    const PLAYER = (w, h, fit, cw = 640, ch = 360) => `<canvas id="c" width="${cw}" height="${ch}"></canvas><video class="evidence-player__video" style="display:block;width:${w};height:${h};object-fit:${fit}" muted autoplay playsinline></video>
      <script>const c = document.getElementById('c'); const x = c.getContext('2d'); x.fillStyle = '#4af'; x.fillRect(0, 0, c.width, c.height); document.querySelector('video').srcObject = c.captureStream(5);</script>`;
    const player = async (html) => {
      await lane.page(TOKENS + html, { width: 1366, height: 768, zoom: 2 });
      for (let i = 0; i < 100 && !(await lane.browser.evaluate('document.querySelector("video").videoWidth > 0')); i += 1) await lane.browser.evaluate('new Promise((r) => setTimeout(r, 50))');
      assert.ok(await lane.browser.evaluate('document.querySelector("video").videoWidth > 0'), 'the footage decoded');
      return messages(await lane.browser.evaluate(toExpression(zoomAssertions, { tier: 'C' })));
    };
    // none: natural size; cropped when the footage is larger than its box.
    assert.match(await player(PLAYER('300px', '200px', 'none')), /640x360 footage in a 300x200 box with object-fit none: .*cropped/);
    assert.equal(await player(PLAYER('660px', '380px', 'none')), '');
    // scale-down and contain never crop; cover crops a different aspect; fill distorts it.
    assert.equal(await player(PLAYER('300px', '200px', 'scale-down')), '');
    assert.equal(await player(PLAYER('300px', '200px', 'contain')), '');
    assert.match(await player(PLAYER('300px', '300px', 'cover')), /object-fit cover: .*cropped/);
    assert.match(await player(PLAYER('300px', '300px', 'fill')), /object-fit fill: the picture is distorted/);
    assert.equal(await player(PLAYER('320px', '180px', 'cover')), '');
  });

  it('models overflow per axis: a box or page that scrolls only vertically still hides what lies past its right edge (cold review 2)', async () => {
    // Focus scrolls the box sideways, which no pointer can; the capture shows nothing.
    assert.match(messages(await at200('<div style="width:200px;height:120px;overflow-x:hidden;overflow-y:auto"><div style="width:600px;height:300px"><button style="margin-left:300px;width:150px;height:40px">Retry processing</button></div></div>')),
      /"Retry processing" is shown only by focus scrolling <div>.*, which clips without scrolling on that axis/);
    // The root's overflow is the viewport's (propagated); on the body as well
    // it would clip the body itself, which the chain names instead.
    assert.match(messages(await at200('<style>html{overflow-x:hidden}</style><div style="width:2000px;height:50px"><button style="margin-left:900px;width:150px;height:40px">Retry processing</button></div>')),
      /"Retry processing" is shown only by focus scrolling the page, which hides its overflow on that axis/);
    assert.match(messages(await at200('<style>html,body{overflow-x:hidden}</style><div style="width:2000px;height:50px"><button style="margin-left:900px;width:150px;height:40px">Retry processing</button></div>')),
      /"Retry processing" is shown only by focus scrolling <body>.*, which clips without scrolling on that axis/);
    assert.equal(messages(await at200('<div style="width:200px;height:120px;overflow:auto"><div style="width:600px;height:300px"><button style="margin-left:300px;width:150px;height:40px">Retry processing</button></div></div>')), '');
  });

  it('counts every layer that paints at the point — a backdrop filter, a border ring, an inset shadow, a static pseudo-element (cold review 2)', async () => {
    const UNDER = '<div style="height:200px"></div><button style="display:block;width:160px;height:40px">Detail</button><div style="height:10px"></div>';
    for (const [name, css] of [
      ['a backdrop-filter', 'position:fixed;inset:0;backdrop-filter:blur(40px);pointer-events:none'],
      ['a border ring', 'position:fixed;inset:0;border:400px solid #000;pointer-events:none'],
      ['an inset shadow', 'position:fixed;inset:0;box-shadow:inset 0 0 0 400px #000;pointer-events:none'],
    ]) {
      assert.match(messages(await at200(UNDER + `<div style="${css}">layer</div>`)), /"Detail" is hidden under <div>/, name);
    }
    // An ancestor's static ::after pulled over the control by a negative margin.
    assert.match(messages(await at200('<style>.w{pointer-events:none}.w::after{content:"";display:block;height:60px;margin-top:-60px;background:#000;position:relative}</style><div class="w"><button style="display:block;width:160px;height:40px;pointer-events:auto">Detail</button></div>')), /"Detail" is hidden under <div.w>/);
    // A transparent, borderless, shadowless layer with no text of its own hides nothing.
    assert.equal(messages(await at200(UNDER + '<div style="position:fixed;inset:0;pointer-events:none"></div>')), '');
  });

  it('judges visibility by the computed value: a visible control inside a hidden parent is still judged (cold review 2)', async () => {
    assert.match(messages(await at200('<div style="visibility:hidden"><div style="width:100px;height:20px;overflow:hidden"><button style="visibility:visible;width:200px;height:40px">Retry processing</button></div></div>')), /"Retry processing" is (cut off|shown only by focus scrolling)/);
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

  it('measures a clip-path: an inset() like a box, any other shape as an unmeasured loss (Codex P1)', async () => {
    assert.match(messages(await at200('<div style="clip-path:inset(0 0 0 15%)"><button style="width:200px">Retry processing</button></div>')), /"Retry processing" is cut off even when focused \(\d+px of its width/);
    assert.match(messages(await at200('<div style="clip-path:circle(40%)"><button style="width:200px">Retry processing</button></div>')), /clipped by <div> .*clip-path circle\(40%\), which the harness cannot measure/);
    assert.equal(messages(await at200('<div style="clip-path:inset(0)"><button style="width:200px">Retry processing</button></div>')), '');
  });

  it('clips a fixed control by the ancestors that form its containing block, and no others (Codex P1, containing blocks)', async () => {
    // A transformed ancestor is a fixed descendant's containing block: its
    // overflow clips the control. 200px of button in a 180px box: 20px lost.
    assert.match(messages(await at200('<div style="transform:translateZ(0);width:180px;height:60px;overflow:hidden"><button style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button></div>')),
      /"Retry processing" is cut off even when focused \(20px of its width/);
    // Clipped vertically, through a filter ancestor.
    assert.match(messages(await at200('<div style="filter:blur(0);width:300px;height:24px;overflow:hidden"><button style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button></div>')),
      /"Retry processing" is cut off even when focused \(0px of its width, 16px of its height/);
    // Nested: a static box between the control and its containing block does
    // not clip it (fixed escapes it), but the containing block's own parent does.
    assert.equal(messages(await at200('<div style="transform:translateZ(0);width:300px;height:60px"><div style="width:100px;height:20px;overflow:hidden"><button style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button></div></div>')), '');
    assert.match(messages(await at200('<div style="width:120px;height:60px;overflow:hidden"><div style="transform:translateZ(0);width:300px;height:60px"><div style="width:100px;height:20px;overflow:hidden"><button style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button></div></div></div>')),
      /"Retry processing" is cut off even when focused \(80px of its width/);
    // A fixed control with no such ancestor escapes every overflow box: no false positive.
    assert.equal(messages(await at200('<div style="width:100px;height:20px;overflow:hidden"><button style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button></div>')), '');
    // An absolute control escapes the overflow of static ancestors between it
    // and its positioned containing block, and is clipped by that block.
    assert.equal(messages(await at200('<div style="position:relative;width:300px;height:60px"><div style="width:100px;height:20px;overflow:hidden"><button style="position:absolute;left:0;top:0;width:200px;height:40px">Retry processing</button></div></div>')), '');
    assert.match(messages(await at200('<div style="position:relative;width:180px;height:60px;overflow:hidden"><div style="width:100px;height:20px"><button style="position:absolute;left:0;top:0;width:200px;height:40px">Retry processing</button></div></div>')),
      /"Retry processing" is cut off even when focused \(20px of its width/);
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
    // Over a stretched control, only its own composition is its face (Codex P1).
    assert.match(messages(await at200(`<div style="position:relative;width:300px;height:220px">
      <article style="position:relative;width:300px;height:160px"><button aria-label="Select Person" style="position:absolute;inset:0;background:transparent;border:0"></button>
        <span style="position:relative;display:block;height:120px;background:#333;pointer-events:none">No image</span></article>
      <span style="position:absolute;left:0;top:0;width:300px;height:160px;background:#900;pointer-events:none">alert band</span></div>`)), /"Select Person" is hidden under <span> "alert band"/);
    // A pass-through layer placed by a negative margin covers it too (Codex P1).
    assert.match(messages(await at200(`<button style="display:block;width:200px;height:40px">Retry</button>
      <span style="position:relative;z-index:2;display:block;margin-top:-40px;width:200px;height:40px;background:#000;pointer-events:none">shade</span>`)), /"Retry" is hidden under <span> "shade"/);
    // An absolutely placed pass-through layer over an ordinary control covers it (Codex P1).
    assert.match(messages(await at200(`<div style="position:relative;width:300px;height:120px"><button style="width:200px;height:40px">Retry</button>
      <span style="position:absolute;inset:0;background:#000;pointer-events:none">badge</span></div>`)), /"Retry" is hidden under <span> "badge"/);
  });

  it('takes a control\'s own tooltip as part of it, and another control\'s as a cover (Codex P1)', async () => {
    const TIPS = (own) => `<div style="height:250px"></div><span class="tooltip-anchor"><button ${own ? 'aria-describedby="tip"' : ''} style="width:160px;height:40px">Detail</button></span>
      <span class="tooltip" role="tooltip" id="tip" style="position:fixed;left:0;top:240px;width:200px;height:60px;background:#222">${own ? 'Open the run detail' : 'Another control\'s hint'}</span><div style="height:10px"></div>`;
    assert.equal(messages(await at200(TIPS(true))), '');
    assert.match(messages(await at200(TIPS(false))), /"Detail" is (covered by|hidden under) <span.tooltip>/);
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

  it('compares text with its baseline by words, then by the page floor, and element by element in a live change (Codex P1)', async () => {
    const SHRINKS = (size) => `<style>body{margin:0;font:14px sans-serif} @media (width < 768px) { .label { font-size: ${size} } }</style>
      <main id="main"><p>Videos</p><span class="label">north-gate-0800.mp4</span></main>`;
    // A live change: the baseline taken at 100%, the comparison after the zoom.
    const change = async (html) => {
      await lane.page(html, { width: 1366, height: 768, zoom: 1 });
      const baseline = await lane.browser.evaluate(toExpression(zoomTextBaseline));
      lane.zoom = await lane.browser.pageZoom(2);
      return lane.browser.evaluate(toExpression(zoomTextCompare, { baseline, from: '100%', to: '200%', live: true }));
    };
    const shrunk = await change(SHRINKS('7px'));
    assert.deepEqual(shrunk.changed, ['"north-gate-0800.mp4" changed from 14px to 7px with the zoom change']);
    assert.equal(shrunk.matched, 2);
    const kept = await change(SHRINKS('14px'));
    assert.ok(kept.compared >= 2);
    assert.deepEqual(kept.changed, []);
    assert.equal(kept.minRatio, 1);
    // Text the new composition mounts in place of another is held to the same
    // words before, else to the page's smallest text.
    const REPLACED = (size) => `<style>body{margin:0;font:14px sans-serif} .summary{display:none;font-size:${size}} @media (width < 768px) { .editor { display: none } .summary { display: block } }</style>
      <main id="main"><div class="editor"><span style="font-size:12px">Zone A</span></div><div class="summary">Editing a scene needs a display at least 768px wide.</div></main>`;
    assert.match((await change(REPLACED('7px'))).changed.join('\n'), /"Editing a scene needs a displa" is drawn at 7px at 200%, below the 12px smallest text at 100% \(it has no counterpart there\)/);
    assert.deepEqual((await change(REPLACED('14px'))).changed, []);
    // Words drawn before are held to their own size, never to a smaller
    // record's or field's — the baseline matched to the wrong text is caught.
    const RELABEL = `<style>body{margin:0;font:14px sans-serif} .tiny{font-size:10px} .narrow{display:none;font-size:10px} @media (width < 768px) { .wide { display: none } .narrow { display: block } }</style>
      <main id="main"><small class="tiny">south-dock-2200.mp4</small><h2 class="wide" style="font-size:16px">north-gate-0800.mp4</h2><p class="narrow">north-gate-0800.mp4</p></main>`;
    assert.match((await change(RELABEL)).changed.join('\n'), /"north-gate-0800.mp4" is drawn at 10px at 200%, where the same words were drawn no smaller than 16px at 100%/);
    // Words a page draws at two sizes are held to the smaller: a status badge
    // "Processing" (11px) beside a 13px rail link is not a shrink.
    const ROLES = `<style>body{margin:0;font:14px sans-serif} .badge{font-size:11px} .nav{font-size:13px} @media (width < 768px) { .nav { display: none } }</style>
      <main id="main"><a class="nav" href="/processing">Processing</a><span class="badge">Processed</span><span class="badge narrow-only">Processing</span></main>`;
    assert.deepEqual((await change(ROLES)).changed, []);
    // A component drawn smaller than it was, in the same document, is caught by its identity whatever its words.
    const ROLE_SHRUNK = `<style>body{margin:0;font:14px sans-serif} .badge{font-size:11px} @media (width < 768px) { .badge.late { font-size: 8px } }</style>
      <main id="main"><span class="badge">Processed</span><span class="badge late">Queued</span></main>`;
    assert.match((await change(ROLE_SHRUNK)).changed.join('\n'), /"Queued" changed from 11px to 8px with the zoom change/);
    // Across two documents, new words are held to the page's smallest text.
    await lane.page(ROLE_SHRUNK.replace('@media (width < 768px) { .badge.late { font-size: 8px } }', ''), { width: 1366, height: 768, zoom: 1 });
    const floorBaseline = await lane.browser.evaluate(toExpression(zoomTextBaseline));
    await lane.page('<style>body{margin:0;font:14px sans-serif} .badge{font-size:8px}</style><main id="main"><span class="badge">Stale</span></main>', { width: 1366, height: 768, zoom: 2 });
    assert.match((await lane.browser.evaluate(toExpression(zoomTextCompare, { baseline: floorBaseline, from: '100%', to: '200%', live: false }))).changed.join('\n'), /"Stale" is drawn at 8px at 200%, below the 11px smallest text at 100%/);
    // Text the operator cannot view is not a baseline (Codex P1-D): a 7px
    // element far off-screen does not lower the floor; text below the fold,
    // reachable by scrolling, is one; text in an inert region or outside a
    // clipped box is not; a hidden heading is not.
    const OFFSCREEN = `<style>body{margin:0;font:14px sans-serif} .away{position:absolute;left:-9999px;font-size:7px} .narrow{display:none;font-size:9px} @media (width < 768px) { .narrow { display: block } }</style>
      <main id="main"><p>Videos</p><p class="away">far away</p><p class="narrow">Shown only on a narrow display</p></main>`;
    assert.match((await change(OFFSCREEN)).changed.join('\n'), /"Shown only on a narrow display" is drawn at 9px at 200%, below the 14px smallest text at 100%/);
    const BELOW = `<style>body{margin:0;font:14px sans-serif} .fold{margin-top:2000px;font-size:9px} .narrow{display:none;font-size:9px} @media (width < 768px) { .narrow { display: block } }</style>
      <main id="main"><p>Videos</p><p class="fold">below the fold</p><p class="narrow">Shown only on a narrow display</p></main>`;
    assert.deepEqual((await change(BELOW)).changed, []);
    const CLIPPED = `<style>body{margin:0;font:14px sans-serif} .box{width:200px;height:20px;overflow:hidden} .cut{margin-top:60px;font-size:7px} .narrow{display:none;font-size:9px} @media (width < 768px) { .narrow { display: block } }</style>
      <main id="main"><p>Videos</p><div class="box"><p class="cut">clipped away</p></div><p class="narrow">Shown only on a narrow display</p></main>`;
    assert.match((await change(CLIPPED)).changed.join('\n'), /"Shown only on a narrow display" is drawn at 9px at 200%, below the 14px smallest text at 100%/);
    // Text behind an open overlay — inert, under a translucent scrim — is
    // still drawn and read: it stays a baseline (a Dialog over a Scene
    // Editor does not shrink the page's text to the Dialog's).
    const SCRIM = `<style>body{margin:0;font:14px sans-serif} .scrim{position:fixed;inset:0;background:rgba(0,0,0,.5)} .narrow{display:none;font-size:11px} @media (width < 768px) { .narrow { display: block } .scrim { display: none } }</style>
      <main id="main" inert><p>Videos</p><p style="font-size:11px">4 of 4 videos</p></main><div class="scrim"></div><p class="narrow">Shown only on a narrow display</p>`;
    assert.deepEqual((await change(SCRIM)).changed, []);
    // ...but under an opaque cover it is hidden: with every text covered the
    // comparison is a fault, and with the 11px text alone covered the floor is 14px.
    assert.match((await change(SCRIM.replace('rgba(0,0,0,.5)', '#000'))).fault, /no text baseline at 100%/);
    const COVERED = `<style>body{margin:0;font:14px sans-serif} .cover{position:absolute;left:0;right:0;top:30px;height:30px;background:#000} .narrow{display:none;font-size:11px} @media (width < 768px) { .narrow { display: block } .cover { display: none } }</style>
      <main id="main" style="position:relative"><p style="margin:0;height:30px">Videos</p><p style="margin:0;height:30px;font-size:11px">4 of 4 videos</p><div class="cover"></div></main><p class="narrow">Shown only on a narrow display</p>`;
    assert.match((await change(COVERED)).changed.join('\n'), /"Shown only on a narrow display" is drawn at 11px at 200%, below the 14px smallest text at 100%/);
    // A size is the drawn size: text scaled down by a transform or the CSS
    // zoom of an ancestor at the narrow tier is drawn smaller, whatever its
    // font-size says (cold review 2).
    const SCALED = (how) => `<style>body{margin:0;font:14px sans-serif} @media (width < 768px) { .box { ${how} } }</style><main id="main"><div class="box"><p>north-gate-0800.mp4</p></div></main>`;
    assert.match((await change(SCALED('transform:scale(.5);transform-origin:0 0'))).changed.join('\n'), /"north-gate-0800.mp4" changed from 14px to 7px with the zoom change/);
    assert.match((await change(SCALED('zoom:0.5'))).changed.join('\n'), /"north-gate-0800.mp4" changed from 14px to 7px with the zoom change/);
    // A form control's value and a select's chosen option are text too.
    const FORM = `<style>body{margin:0;font:14px sans-serif} input,select{font-size:14px} @media (width < 768px) { input,select { font-size: 6px } }</style>
      <main id="main"><p>Videos</p><label>Camera <select><option>CAM-01 North Gate</option></select></label><label>Filter <input value="south dock"></label></main>`;
    const form = (await change(FORM)).changed.join('\n');
    assert.match(form, /"CAM-01 North Gate" changed from 14px to 6px/);
    assert.match(form, /"south dock" changed from 14px to 6px/);
    // Hidden text is neither baseline nor subject: a visually-hidden 20px
    // heading does not hold a 13px crumb with the same words to it.
    const HIDDEN = `<style>body{margin:0;font:14px sans-serif} .vh{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)} h1{font-size:20px} .crumb{display:none;font-size:13px} @media (width < 768px) { .crumb { display: inline } }</style>
      <main id="main"><h1 class="vh">Videos</h1><span class="crumb">Videos</span><p>rows</p><small style="font-size:12px">4 of 4 videos</small></main>`;
    assert.deepEqual((await change(HIDDEN)).changed, []);
    // The same element changing its own size in a live change, whatever its words elsewhere.
    const SELF = `<style>body{margin:0;font:14px sans-serif} @media (width < 768px) { .a { font-size: 10px } }</style>
      <main id="main"><p class="a">Cameras</p><p style="font-size:10px">Cameras</p></main>`;
    const self = await change(SELF);
    assert.deepEqual(self.changed, ['"Cameras" changed from 14px to 10px with the zoom change']);
    // No baseline, or no text: a fault, never a pass.
    await lane.page('<main id="main"><p>Videos</p></main>', { width: 1366, height: 768, zoom: 2 });
    assert.match((await lane.browser.evaluate(toExpression(zoomTextCompare, { baseline: { holders: 0, floor: null, words: {} }, from: '100%', to: '200%', live: false }))).fault, /no text baseline at 100%/);
    await lane.page('<main id="main"><button aria-label="Play"></button></main>', { width: 1366, height: 768, zoom: 2 });
    assert.match((await lane.browser.evaluate(toExpression(zoomTextCompare, { baseline: { holders: 3, floor: 12, words: { videos: 14 } }, from: '100%', to: '200%', live: false }))).fault, /holds no text to compare/);
    // Every word replaced: nothing matched, the physical size unproven — the
    // run makes that a fault (minRatio null, matched 0).
    await lane.page('<main id="main"><p>Imported videos</p></main>', { width: 1366, height: 768, zoom: 2 });
    const none = await lane.browser.evaluate(toExpression(zoomTextCompare, { baseline: { holders: 3, floor: 12, words: { videos: 14 } }, from: '100%', to: '200%', live: false }));
    assert.equal(none.matched, 0);
    assert.equal(none.minRatio, null);
  });

  it('fails a focused fixed control that a transformed ancestor clips only after the zoom change', async () => {
    // At 100% the box is wide; the Tier C rule narrows it to 180px, and the
    // 200px fixed button inside the transformed box is cut by 20px.
    const CLIPS = `<style>body{margin:0} .box{transform:translateZ(0);width:300px;height:60px;overflow:hidden} @media (width < 768px) { .box { width: 180px } }</style>
      <main id="main"><div class="box"><button class="target" style="position:fixed;left:0;top:0;width:200px;height:40px">Retry processing</button></div></main>`;
    const probe = await across(CLIPS, '(() => { document.querySelector(".target").focus(); return true; })()');
    assert.deepEqual(probe.findings, [], 'the probe sees the control still partly on screen');
    const step = await lane.browser.evaluate(toExpression(zoomAssertions, { tier: 'C' }));
    assert.match(step.findings.map((f) => f.message).join('\n'), /"Retry processing" is cut off even when focused \(20px of its width/);
  });

  it('fails focus the zoom change leaves on a transparent control (Codex P1)', async () => {
    const FADED = `<style>body{margin:0} @media (width < 768px) { .fades { opacity: 0 } }</style>
      <main id="main"><button class="fades">Detail</button></main>`;
    assert.match(messages(await across(FADED, '(() => { document.querySelector(".fades").focus(); return true; })()')), /focus is left on <button.fades> "Detail", which the zoom change has left transparent/);
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
    // Every zoom case first reaches the state at 100% for its text baseline,
    // so the undeclared start is a fault there already.
    assert.ok(results.harnessErrors.some((e) => /videos @ 1366x768@100%-200% \(Tier C\): the declared state was not reached at (navigation settle|zoom text baseline)/.test(e)), results.harnessErrors.join('\n'));
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
    const { status, output, results } = run('prepared', `export const STATES = [...REGISTERED.filter((s) => s.name === "videos"), ...REGISTERED.filter((s) => s.name === "videos-filters-drawer").map(({ zoomCapture, ...s }) => ({ ...s, zoomTransitions: [{ path: [2, 1], before: ${JSON.stringify(WIDE)} }] }))];`, ['--states', 'videos-filters-drawer']);
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@200%-100%');
    assert.ok(zoom.some((f) => /^at the start \(200%\): .* does not fit the 683x384 viewport/.test(f.message) && f.severity === 'blocking'), JSON.stringify(zoom));
  });

  it('compares every 200% load with the same state at 100%: a label a Tier C rule shrinks fails (Codex P1, text scaling)', () => {
    const SHRINK = (selector, size) => `(() => { const s = document.createElement('style'); s.textContent = '@media (width < 768px) { ${selector} { font-size: ${size} !important } }'; document.head.appendChild(s); return true; })()`;
    // One label shrunk to 7px at the Tier C breakpoint; the body font untouched.
    let { status, output, results } = run('shrunk-label', `${VIDEOS.replace('=> s)', '=> ({ ...s, prepare: ' + JSON.stringify(SHRINK('main tbody td .faint', '7px')) + ' }))')}`, ['--states', 'videos']);
    assert.equal(status, 1, output);
    let zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@200%');
    assert.ok(zoom.some((f) => /"North Gate" .*7px at 200%, where .* 1[0-9]px at 100%/.test(f.message) && f.severity === 'blocking'), JSON.stringify(zoom));
    // A secondary field (the recorded time) reduced while everything else keeps its size.
    ({ status, output, results } = run('shrunk-field', `${VIDEOS.replace('=> s)', '=> ({ ...s, prepare: ' + JSON.stringify(SHRINK('main tbody td .ledger-folded__value', '9px')) + ' }))')}`, ['--states', 'videos']));
    assert.equal(status, 1, output);
    zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@200%');
    // The folded value's holder exists only at Tier C: caught by the floor.
    assert.ok(zoom.some((f) => /"Recorded 14 Sept, 09:00" is drawn at 9px at 200%, (where|below) .*1[0-9]px/.test(f.message)), JSON.stringify(zoom));
    // Text only the narrow composition draws, with no counterpart at 100%,
    // is held to the smallest text the page drew at 100%.
    const NARROW_ONLY = `(() => { if (matchMedia('(width < 768px)').matches) { const p = document.createElement('p'); p.style.fontSize = '7px'; p.textContent = 'Shown only on a narrow display'; document.querySelector('main').appendChild(p); } return true; })()`;
    ({ status, output, results } = run('narrow-only', `${VIDEOS.replace('=> s)', '=> ({ ...s, prepare: ' + JSON.stringify(NARROW_ONLY) + ' }))')}`, ['--states', 'videos']));
    assert.equal(status, 1, output);
    zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@200%');
    assert.ok(zoom.some((f) => /"Shown only on a narrow display" .*7px at 200%, below the 1[0-9]px smallest text at 100%/.test(f.message)), JSON.stringify(zoom));
  });

  it('is a harness fault when a 200% load\'s 100% baseline cannot be established, and when a zoom case never compares its text (Codex P1)', () => {
    // The state's Tier A view (its baseline) waits for text the page never shows.
    const { status, output, results } = run('no-baseline', `export const STATES = REGISTERED.filter((s) => s.name === "videos").map(({ zoomTransitions, ...s }) => ({ ...s, expectText: 'Text this page never shows', atTier: { C: { expectText: '4 of 4 videos' } } }));`, ['--states', 'videos']);
    assert.equal(status, 2, output);
    assert.ok(results.harnessErrors.some((e) => /videos @ 1366x768@200% \(Tier C\): the declared state was not reached at zoom text baseline/.test(e)), results.harnessErrors.join('\n'));
    // A valid zoom capture with no text comparison is a fault on the full sweep.
    assert.match(zoomCoverageFaults([{ valid: true, kind: 'zoom', surface: 'videos', state: 'videos', viewport: '1366x768@200%', zoom: { evaluated: true, text: null } }], ['videos']).join('\n'),
      /a11y.zoom-200: videos @ 1366x768@200% never compared its text with a 100% baseline/);
  });

  it('judges every step a transition passes through, as a load (Codex P1)', () => {
    // A band drawn only at 200%, letting the pointer through: it hides the
    // focused row action there, and is gone again by the 100% capture.
    const BAND = `(() => { const s = document.createElement('style'); s.textContent = '@media (width < 768px) { body::after { content: ""; position: fixed; inset: 0; background: #000; pointer-events: none; z-index: 9 } }'; document.head.appendChild(s); const a = document.querySelector('main tbody tr a[href], main tbody tr button'); a.focus(); return document.activeElement === a; })()`;
    const { status, output, results } = run('step', `export const STATES = REGISTERED.filter((s) => s.name === "videos").map((s) => ({ ...s, zoomTransitions: [{ path: [1, 2, 1], before: ${JSON.stringify(BAND)} }] }));`, ['--states', 'videos']);
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@100%-200%-100%');
    assert.ok(zoom.some((f) => /^at 200%: .*(hidden under|covered by)/.test(f.message) && f.severity === 'blocking'), JSON.stringify(zoom));
  });

  it('compares the text a transition\'s final action draws at 200%, and takes each baseline with the state\'s own storage, not the previous case\'s (cold review 2)', () => {
    // search-grid stores the grid choice; a case after it must not inherit it
    // into its 100% baseline: search-filtered's baseline matches its words
    // as it does alone (every holder but the Tier C-only ones).
    let { status, output, results } = run('storage-order', `export const STATES = REGISTERED.filter((s) => s.name === "search-grid" || s.name === "search-filtered").map(({ zoomTransitions, ...s }) => s);`, ['--states', 'search-grid,search-filtered']);
    assert.equal(status, 0, output);
    const filtered = results.cases.find((c) => c.state === 'search-filtered');
    assert.ok(filtered.zoom.text.unmatched <= 3, JSON.stringify(filtered.zoom.text));
    // A transition whose final action mounts tiny text at 200% is caught by
    // the comparison after the action.
    const TINY = `(() => { const p = document.createElement('p'); p.style.fontSize = '6px'; p.textContent = 'Mounted by the action'; document.querySelector('main').appendChild(p); return true; })()`;
    ({ status, output, results } = run('then-text', `export const STATES = REGISTERED.filter((s) => s.name === "videos").map(({ zoomTransitions, ...s }) => ({ ...s, zoomTransitions: [{ path: [1, 2], then: ${JSON.stringify(TINY)} }] }));`, ['--states', 'videos']));
    assert.equal(status, 1, output);
    const zoom = results.findingsList.filter((f) => f.rule === 'a11y.zoom-200' && f.viewport === '1366x768@100%-200%');
    assert.ok(zoom.some((f) => /"Mounted by the action" is drawn at 6px at 200%, below the 1[0-9]px smallest text at 100%/.test(f.message)), JSON.stringify(zoom));
  });

  it('is a harness fault when a required zoom state is never reached', () => {
    const { status, output, results } = run('unreached', `export const STATES = REGISTERED.filter((s) => s.name === "videos").map((s) => ({ ...s, zoomTransitions: [{ path: [1, 2], before: '(() => false)()' }] }));`, ['--states', 'videos']);
    assert.equal(status, 2, output);
    assert.ok(results.harnessErrors.some((e) => /videos @ 1366x768@100%-200% \(Tier C\): the declared state was not reached at zoom transition set-up/.test(e)), results.harnessErrors.join('\n'));
  });
});
