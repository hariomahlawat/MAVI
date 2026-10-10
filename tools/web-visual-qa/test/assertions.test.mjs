/**
 * Non-vacuity of the rendered assertions (register V1): each new rule is shown
 * to pass a conforming page, to fire on a deliberate violation, and to report
 * itself as evaluated — so a rule whose selector stops matching is caught, not
 * quietly passed.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { focusAssertions, overlayExitProbe, overlayOpened, pageAssertions, stickyProbe, toExpression, workspaceAssertions } from '../assertions.mjs';
import { openBrowser } from './browser.mjs';

const TOKENS = '<style>:root{--accent-strong:#2563eb;--accent-hover:#1d4ed8} body{margin:0;font:14px sans-serif}</style>';
const PAGE_INPUT = { tier: 'A', width: 1366, fullWidth: null, archetype: null, holds: null };

let lane;
before(async () => { lane = await openBrowser(); });
after(async () => { await lane.close(); });

async function page(html, input = PAGE_INPUT) {
  await lane.page(TOKENS + html);
  return lane.browser.evaluate(toExpression(pageAssertions, input));
}
async function workspace(html, input = { tier: 'A', width: 1366, archetype: 'ledger' }) {
  await lane.page(TOKENS + html);
  return lane.browser.evaluate(toExpression(workspaceAssertions, input));
}
const fired = (result, rule) => result.findings.filter((f) => f.rule === rule);

const LEDGER = (body, frameStyle = '') => `
  <main class="main" data-scroll="body" style="height:700px;overflow:hidden">
    <section class="workspace workspace--ledger" style="height:100%">
      <div class="workspace__body workspace__body--ledger">
        ${body.includes('<table') ? `<div class="ledger-table" style="border:1px solid #444;overflow:auto;width:max-content;max-height:600px;${frameStyle}">${body}</div>` : body}
      </div>
    </section>
  </main>`;
const TABLE = (rows) => `<table style="border-collapse:separate;border-spacing:0">
  <thead><tr><th style="position:sticky;top:0;height:32px">Name</th></tr></thead>
  <tbody>${rows}</tbody></table>`;

describe('ledger.row-pitch', () => {
  it('passes 40px rows and reports itself evaluated', async () => {
    const result = await workspace(LEDGER(TABLE('<tr style="height:40px"><td>one</td></tr><tr style="height:40px"><td>two</td></tr>')));
    assert.deepEqual(fired(result, 'ledger.row-pitch'), []);
    assert.ok(result.evaluated.includes('ledger.row-pitch'));
    assert.equal(result.measured.rowCount, 2);
  });
  it('fires on a 56px row', async () => {
    const result = await workspace(LEDGER(TABLE('<tr style="height:40px"><td>one</td></tr><tr style="height:56px"><td>two</td></tr>')));
    assert.match(fired(result, 'ledger.row-pitch')[0].message, /outside 36-40px/);
  });
  it('does not pass a table it could not measure', async () => {
    const result = await workspace(LEDGER(TABLE('')));
    assert.match(fired(result, 'ledger.row-pitch')[0].message, /no body rows/);
  });
});

describe('Ledger row actions: reachable everywhere, in view on Cameras (M1)', () => {
  // A frame at the width the workspace gives it, around a table whose last
  // column holds the row's action — or, with `actionFirst`, whose first does.
  // `frameOverflow` sets the frame's sideways behaviour; `cellClip` wraps the
  // action in a narrow box that clips rather than scrolls.
  const FRAMED = (frameWidth, codeWidth, { actionFirst = false, frameOverflow = 'auto', cellClip = false } = {}) => {
    const action = cellClip
      ? '<td><div style="width:24px;overflow:hidden;white-space:nowrap"><a href="#x" style="display:inline-block;width:80px">Scene</a></div></td>'
      : '<td><a href="#x">Scene</a></td>';
    const code = `<td><div style="width:${codeWidth}px">CAM</div></td>`;
    return `
    <main class="main" data-scroll="body" style="height:700px;overflow:hidden">
      <section class="workspace workspace--ledger" style="height:100%">
        <div class="workspace__body workspace__body--ledger">
          <div class="ledger-table" style="border:1px solid #444;overflow-x:${frameOverflow};overflow-y:auto;max-width:${frameWidth}px;max-height:600px">
            <table style="border-collapse:separate;border-spacing:0">
              <thead><tr><th style="position:sticky;top:0;height:32px">Code</th><th>Actions</th></tr></thead>
              <tbody><tr style="height:40px">${actionFirst ? action + code : code + action}</tr></tbody>
            </table>
          </div>
        </div>
      </section>
    </main>`;
  };
  const ON = (surface) => ({ tier: 'A', width: 1366, archetype: 'ledger', surface });

  it('accepts a compliant Ledger that scrolls sideways to its action (§4.1), and reports itself evaluated', async () => {
    const result = await workspace(FRAMED(600, 900), ON('videos'));
    assert.ok(result.measured.frameScrollWidth > result.measured.frameClientWidth, 'the table does scroll sideways');
    assert.deepEqual(fired(result, 'ledger.actions-reachable'), []);
    assert.ok(result.evaluated.includes('ledger.actions-reachable'));
    // And the Cameras-only requirement is not applied to another Ledger.
    assert.ok(!result.evaluated.includes('cameras.actions-in-view'));
  });
  it('fails an action past an edge the frame cannot scroll to', async () => {
    const result = await workspace(FRAMED(600, 900, { frameOverflow: 'hidden' }), ON('videos'));
    assert.match(fired(result, 'ledger.actions-reachable')[0].message, /^1 row action\(s\) are clipped where no scrolling of the frame reaches them/);
  });
  it('fails an action cut by a non-scrolling box inside the frame, even with the frame in view', async () => {
    const result = await workspace(FRAMED(600, 100, { cellClip: true }), ON('videos'));
    assert.equal(fired(result, 'ledger.actions-reachable').length, 1);
  });
  it('fails a Cameras layout whose identity cell pushes the actions out of view at Tier A', async () => {
    const result = await workspace(FRAMED(600, 900), ON('cameras'));
    // Reachable by the permitted scroll, so the generic rule is silent ...
    assert.deepEqual(fired(result, 'ledger.actions-reachable'), []);
    // ... but the Camera columns do not fit, which M1 accepts as a defect.
    assert.match(fired(result, 'cameras.actions-in-view')[0].message, /^1 row action\(s\) lie outside the frame's visible width at rest/);
  });
  it('applies the Cameras requirement at Tier A only, where the manifest declares it', async () => {
    const result = await workspace(FRAMED(600, 900), { tier: 'B', width: 1024, archetype: 'ledger', surface: 'cameras' });
    assert.ok(!result.evaluated.includes('cameras.actions-in-view'));
    assert.deepEqual(fired(result, 'cameras.actions-in-view'), []);
  });
  it('passes a conformant Cameras layout, its columns within the frame', async () => {
    const result = await workspace(FRAMED(600, 200), ON('cameras'));
    assert.ok(result.evaluated.includes('cameras.actions-in-view'));
    assert.deepEqual(fired(result, 'cameras.actions-in-view'), []);
    assert.deepEqual(fired(result, 'ledger.actions-reachable'), []);
  });
});

describe('ledger.containment and state.placement in a Ledger', () => {
  it('fires on a bordered frame inside the table frame', async () => {
    const result = await workspace(LEDGER(TABLE('<tr style="height:40px"><td><div style="border:1px solid #888;height:60px;width:200px">card</div></td></tr>')));
    assert.ok(fired(result, 'ledger.containment').some((f) => /bordered frame inside the Ledger frame/.test(f.message)));
  });
  it('fires on a state presentation drawn inside a frame', async () => {
    const result = await workspace(LEDGER('<div class="state-region" style="border:1px solid #888;padding:8px;height:80px"><p>No cameras</p></div>'));
    assert.ok(fired(result, 'state.placement').length > 0);
  });
  it('passes an uncontained state presentation in the body region', async () => {
    const result = await workspace(LEDGER('<div class="state-region"><p>No cameras</p></div>'));
    assert.deepEqual(fired(result, 'state.placement'), []);
    assert.ok(result.evaluated.includes('state.placement'));
  });
});

describe('surface.one-primary', () => {
  const ACCENT = 'style="background:var(--accent-strong);color:#fff;border:0;padding:6px"';
  it('fires on two visible accent-filled actions, judged by paint rather than class', async () => {
    const result = await page(`<main><button ${ACCENT}>Save</button><a href="#" ${ACCENT}>Import</a></main>`);
    assert.match(fired(result, 'surface.one-primary')[0].message, /2 accent-filled actions/);
  });
  it('passes one primary beside a disabled one, a pressed state indicator and a hidden one', async () => {
    const result = await page(`<main><button ${ACCENT}>Save</button><button ${ACCENT} disabled>Later</button>
      <button ${ACCENT} aria-pressed="true">Activity</button><button ${ACCENT} hidden>Hidden</button></main>`);
    assert.deepEqual(fired(result, 'surface.one-primary'), []);
    assert.ok(result.evaluated.includes('surface.one-primary'));
  });
  it('counts a control that carries the shared primary class even if its paint changed', async () => {
    const result = await page('<main><button class="btn--primary">One</button><button class="btn--primary">Two</button></main>');
    assert.equal(fired(result, 'surface.one-primary').length, 1);
  });
  it('does not count an action parked outside the page, as the skip link is until focused', async () => {
    const result = await page(`<main><a href="#main" ${ACCENT.replace('style="', 'style="position:absolute;top:-80px;')}>Skip</a><button ${ACCENT}>Save</button></main>`);
    assert.deepEqual(fired(result, 'surface.one-primary'), []);
  });
  it('counts a second primary below the fold of a scrolling page', async () => {
    const result = await page(`<main><button ${ACCENT}>Save</button><div style="height:2400px"></div><button ${ACCENT}>Also save</button></main>`);
    assert.match(fired(result, 'surface.one-primary')[0].message, /2 accent-filled actions/);
  });
});

describe('text.overflow', () => {
  const scoped = (result, scope) => fired(result, 'text.overflow').filter((f) => (f.scope ?? null) === scope);
  it('fires on text that spills out of its box in an S1 region, scoped to the foundation', async () => {
    const result = await page('<div class="context-bar"><div style="width:80px;white-space:nowrap">averyveryveryverylongidentifier</div></div>');
    assert.match(scoped(result, 'foundation')[0].message, /spills out/);
    assert.ok(result.foundationEvaluated.includes('text.overflow'));
  });
  it('scopes every S1 region to the foundation: Ledger, Dialog host, shortcut sheet and StateRegion', async () => {
    for (const region of ['workspace--ledger', 'dialog-host', 'shortcut-sheet', 'state-region']) {
      const result = await page(`<main><div class="${region}"><div style="width:80px;white-space:nowrap">averyveryveryverylongidentifier</div></div></main>`);
      assert.equal(scoped(result, 'foundation').length, 1, region);
    }
  });
  it('leaves the same overflow on surface content unscoped, for the manifest to weigh by surface', async () => {
    const result = await page('<main><div style="width:80px;white-space:nowrap">averyveryveryverylongidentifier</div></main>');
    assert.match(scoped(result, null)[0].message, /spills out/);
    assert.deepEqual(scoped(result, 'foundation'), []);
    assert.ok(result.evaluated.includes('text.overflow'));
  });
  it('fires on text cut off without an ellipsis', async () => {
    const result = await page('<div class="workspace--ledger"><div style="width:80px;white-space:nowrap;overflow:hidden">averyveryveryverylongidentifier</div></div>');
    assert.match(fired(result, 'text.overflow')[0].message, /without an ellipsis/);
  });
  it('fires on text that wrapped past a fixed-height box, clipped or spilling', async () => {
    const clipped = await page('<div class="context-bar"><button style="width:90px;height:24px;overflow:hidden;white-space:normal;font:14px/20px sans-serif">Save the active revision</button></div>');
    assert.match(fired(clipped, 'text.overflow')[0].message, /cut off below/);
    const spill = await page('<main><div style="width:90px;height:20px;font:14px/20px sans-serif">Save the active revision now</div></main>');
    assert.match(fired(spill, 'text.overflow')[0].message, /spills below/);
  });
  it('passes a line clamp and a vertical scroll region', async () => {
    const result = await page(`<main>
      <p style="width:90px;font:14px/20px sans-serif;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden">A long description that is clamped to two lines with an ellipsis</p>
      <div style="width:90px;height:40px;overflow-y:auto;font:14px/20px sans-serif">A long description that scrolls inside its own region</div></main>`);
    assert.deepEqual(fired(result, 'text.overflow'), []);
  });
  it('passes the sanctioned truncation, a scroll region and visually hidden text', async () => {
    const result = await page(`<main>
      <div style="width:80px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">averyveryveryverylongidentifier</div>
      <div style="width:80px;white-space:nowrap;overflow-x:auto">averyveryveryverylongidentifier</div>
      <div class="visually-hidden" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">averyveryveryverylongidentifier</div>
      <p>An ordinary sentence that wraps where it needs to.</p></main>`);
    assert.deepEqual(fired(result, 'text.overflow'), []);
    assert.ok(result.evaluated.includes('text.overflow'));
  });
});

describe('pressed.visible', () => {
  const pressed = (result) => fired(result, 'pressed.visible');
  // Negative cases (cold review, item 3).
  it('fires on an isolated, unstyled aria-pressed="false" control', async () => {
    assert.match(pressed(await page('<main><button aria-pressed="false">Zones</button></main>'))[0].message, /looks the same pressed and unpressed/);
  });
  it('fires on an isolated, unstyled aria-pressed="true" control', async () => {
    assert.match(pressed(await page('<main><button aria-pressed="true">Zones</button></main>'))[0].message, /looks the same pressed and unpressed/);
  });
  it('fires on an is-active class that gives the pressed state nothing visible', async () => {
    assert.equal(pressed(await page('<main><button class="seg is-active" aria-pressed="true">Activity</button></main>')).length, 1);
    assert.equal(pressed(await page('<main><ul><li class="is-selected"><button aria-pressed="true">Loading bay</button></li></ul></main>')).length, 1);
  });
  it('fires on a group whose pressed and unpressed members look identical', async () => {
    const result = await page(`<main><div role="group" aria-label="Mode">
      <button class="seg is-active" aria-pressed="true">Activity</button><button class="seg" aria-pressed="false">Heatmap</button></div></main>`);
    assert.equal(pressed(result).length, 2);
  });
  it('is not satisfied by a peer that differs for an unrelated reason', async () => {
    // The unpressed peer is the "active revision" (styled); the pressed chip's
    // own state class changes nothing — the difference is not its pressed state.
    const result = await page(`<style>.chip.is-active{border:2px solid #2563eb}</style><main><div role="group" aria-label="Revisions">
      <button class="chip is-viewing" aria-pressed="true">R3</button><button class="chip is-active" aria-pressed="false">R4</button>
      <button class="chip" aria-pressed="false">R2</button></div></main>`);
    assert.ok(pressed(result).some((f) => /"R3"/.test(f.message)));
  });
  // Positive cases: every way the product draws a pressed state.
  it('passes class-driven pressed states the product sets, on the control and on its row', async () => {
    const result = await page(`<style>.seg.is-active{background:#2563eb} .nav-item.is-selected{background:#1b2a45} .chip.is-viewing{background:#333}</style><main>
      <div role="group" aria-label="Mode"><button class="seg is-active" aria-pressed="true">Activity</button><button class="seg" aria-pressed="false">Heatmap</button></div>
      <ul><li class="nav-item is-selected"><button aria-pressed="true">Loading bay</button></li><li class="nav-item"><button aria-pressed="false">Forecourt</button></li></ul>
      <div role="group" aria-label="Revisions"><button class="chip is-viewing" aria-pressed="true">R3</button><button class="chip" aria-pressed="false">R4</button></div></main>`);
    assert.deepEqual(pressed(result), []);
  });
  it('leaves an isolated unpressed control unproven — not passed — when only its stylesheet speaks for it', async () => {
    // The stylesheet's state class could be anything (here an unrelated
    // "active revision" look): it is not evidence of a pressed treatment.
    const result = await page(`<style>.chip.is-active{background:#2563eb} .nav-item.is-selected{background:#1b2a45}</style><main>
      <div><button class="chip" aria-pressed="false">R3</button></div>
      <ul><li class="nav-item"><button aria-pressed="false">Forecourt</button></li></ul></main>`);
    assert.deepEqual(pressed(result), []);
    assert.equal(result.pressed.unproven.length, 2);
    assert.deepEqual(result.pressed.proven, []);
  });
  it('proves an isolated control from a pressed one of the same kind elsewhere on the page', async () => {
    const result = await page(`<style>.nav-item.is-selected{background:#1b2a45}</style><main>
      <ul><li class="nav-item"><button aria-pressed="false">Forecourt</button></li></ul>
      <ul><li class="nav-item is-selected"><button aria-pressed="true">Loading bay</button></li></ul></main>`);
    assert.deepEqual(pressed(result), []);
    assert.deepEqual(result.pressed.unproven, []);
    assert.equal(result.pressed.proven.length, 1);
  });
  it('reads a state class on a wrapping element that is not a list row', async () => {
    const result = await page(`<style>.opt.is-on{background:#2563eb}</style><main><div role="group" aria-label="Options">
      <div class="opt is-on"><button aria-pressed="true">On</button></div><div class="opt"><button aria-pressed="false">Off</button></div></div></main>`);
    assert.deepEqual(pressed(result), []);
  });
  it('passes a fill, a border, a shape, a descendant mark, a checkmark and a fill behind a transition', async () => {
    const result = await page(`<style>
        .fill[aria-pressed="true"]{background:#123456}
        .edge[aria-pressed="true"]{border:2px solid #2563eb}
        .shape[aria-pressed="true"]{border-radius:12px}
        .chip .mark{display:inline-block;width:10px;height:10px;border:1px solid #fff}
        .chip[aria-pressed="true"] .mark{background:#2563eb}
        .tick[aria-pressed="true"]::before{content:"✓"}
        .slow{transition:background 2s} .slow[aria-pressed="true"]{background:#654321}
      </style><main>
        <button class="fill" aria-pressed="true">Fill</button>
        <button class="edge" aria-pressed="false">Edge</button>
        <button class="shape" aria-pressed="false">Shape</button>
        <button class="chip" aria-pressed="false"><span class="mark"></span>Chip</button>
        <button class="tick" aria-pressed="false">Tick</button>
        <button class="slow" aria-pressed="false">Slow</button></main>`);
    assert.deepEqual(pressed(result), []);
    assert.ok(result.evaluated.includes('pressed.visible'));
  });
  it('leaves the page exactly as it found it: attributes, classes, styles, no transition running', async () => {
    const html = `<style>.slow{transition:background 2s} .slow[aria-pressed="true"]{background:#654321} .seg.is-active{background:#2563eb}</style><main>
      <div role="group" aria-label="Mode"><button class="seg is-active" aria-pressed="true">A</button><button class="seg" aria-pressed="false">B</button></div>
      <ul><li class="row"><button class="slow" aria-pressed="false">Slow</button></li></ul></main>`;
    await page(html);
    const before = await lane.browser.evaluate('document.querySelector("main").outerHTML');
    await lane.browser.evaluate(toExpression(pageAssertions, PAGE_INPUT));
    assert.equal(await lane.browser.evaluate('document.querySelector("main").outerHTML'), before);
    assert.equal(await lane.browser.evaluate('document.getAnimations().length'), 0);
    // Chromium serialises inline style lazily: no element gains an empty style.
    assert.equal(await lane.browser.evaluate('document.querySelectorAll("main [style]").length'), 0);
  });
});

describe('containment.depth and state.placement', () => {
  it('scopes a nested frame inside an S1 region to the foundation, and one on a surface to nothing', async () => {
    const nest = '<div style="border:1px solid #444;width:400px;height:200px"><div style="border:1px solid #444;width:300px;height:100px">card</div></div>';
    const ledger = await page(`<main><div class="workspace--ledger">${nest}</div></main>`);
    assert.equal(fired(ledger, 'containment.depth')[0].scope, 'foundation');
    assert.ok(ledger.foundationEvaluated.includes('containment.depth'));
    const surface = await page(`<main>${nest}</main>`);
    assert.equal(fired(surface, 'containment.depth')[0].scope, undefined);
  });
  it('checks the Dialog host and the shortcut sheet wherever they are mounted', async () => {
    const result = await page('<main></main><div class="dialog-host"><div style="border:1px solid #444;width:400px;height:200px"><div style="border:1px solid #444;width:300px;height:100px">card</div></div></div>');
    assert.equal(fired(result, 'containment.depth')[0].scope, 'foundation');
  });
  it('treats a frame round nothing but media as the object, not a containment level', async () => {
    const result = await page(`<main><div style="border:1px solid #444;width:400px;height:300px">
      <div style="border:1px solid #333;width:200px;height:184px"><img alt="crop" style="width:100px;height:100px"></div>
      <div style="border:1px solid #333;width:200px;height:184px"><div class="evidence-placeholder">No image</div></div></div></main>`);
    assert.deepEqual(fired(result, 'containment.depth'), []);
  });
  it('does not take an icon, or a frame with its own text, for media', async () => {
    const outer = (inner) => `<main><div style="border:1px solid #444;width:400px;height:300px">${inner}</div></main>`;
    const icon = '<svg width="16" height="16"><rect width="16" height="16"/></svg>';
    const card = await page(outer(`<div style="border:1px solid #333;width:200px;height:120px">Status ${icon}</div>`));
    assert.equal(fired(card, 'containment.depth').length, 1);
    const chart = await page(outer(`<div style="border:1px solid #333;width:200px;height:120px"><svg width="180" height="100"><rect width="180" height="100"/></svg></div>`));
    assert.equal(fired(chart, 'containment.depth').length, 1);
  });
  it('takes a FileInput frame for the control it is, however tall a wrapped file name makes it (M3)', async () => {
    const outer = (inner) => `<main><div style="border:1px solid #444;width:400px;height:300px">${inner}</div></main>`;
    const control = await page(outer('<div class="file-input" style="border:1px solid #333;width:300px;height:64px"><input type="file"><span>a-file-name-long-enough-to-wrap-onto-a-second-line.mp4</span></div>'));
    assert.deepEqual(fired(control, 'containment.depth'), []);
    // The same frame without the control's class is still a container.
    const card = await page(outer('<div style="border:1px solid #333;width:300px;height:64px"><span>a-file-name-long-enough-to-wrap-onto-a-second-line.mp4</span></div>'));
    assert.equal(fired(card, 'containment.depth').length, 1);
  });
  it('scopes a nesting by the frame doing the containing: a surface panel round an S1 presentation is the surface', async () => {
    const result = await page(`<main><div style="border:1px solid #444;width:400px;height:300px">
      <div class="state-region"><div style="border:1px solid #333;width:300px;height:100px">Nothing here yet.</div></div></div></main>`);
    assert.equal(fired(result, 'containment.depth')[0].scope, undefined);
  });
  it('still fires on a frame holding media and anything else', async () => {
    const result = await page(`<main><div style="border:1px solid #444;width:400px;height:300px">
      <div style="border:1px solid #333;width:200px;height:184px"><img alt="crop" style="width:100px;height:100px"><p>Caption and controls</p></div></div></main>`);
    assert.equal(fired(result, 'containment.depth').length, 1);
  });
  it('fires on a bordered card inside a bordered panel', async () => {
    const result = await page('<main><div style="border:1px solid #444;width:400px;height:200px"><div style="border:1px solid #444;width:300px;height:100px">card</div></div></main>');
    assert.equal(fired(result, 'containment.depth').length, 1);
  });
  it('passes one contained surface holding an alert and a control', async () => {
    const result = await page('<main><div style="border:1px solid #444;width:400px;height:200px"><div class="alert" style="border:1px solid red;width:300px;height:60px">!</div><button>Go</button></div></main>');
    assert.deepEqual(fired(result, 'containment.depth'), []);
  });
  it('fires on a state presentation that paints a box stretched to fill its region', async () => {
    const result = await page('<main><div style="height:600px;display:flex;flex-direction:column"><div class="state-region" style="flex:1;display:flex;flex-direction:column"><div class="empty-state" style="flex:1;border:1px dashed #555"><p>Nothing here yet.</p></div></div></div></main>');
    assert.match(fired(result, 'state.placement')[0].message, /fills its region/);
  });
  it('fires on a presentation pushed down its region, whether or not it is the first child', async () => {
    const centred = (before) => `<main><div style="height:600px;display:flex;flex-direction:column;justify-content:center;gap:8px">${before}<div class="state-region"><div class="alert" style="border:1px solid red">Nothing here yet.</div></div></div></main>`;
    assert.match(fired(await page(centred('')), 'state.placement')[0].message, /below the top of the region it replaces/);
    const apart = '<main><div style="height:600px;display:flex;flex-direction:column;justify-content:space-between;gap:8px"><div style="height:40px">Filters</div><div class="state-region"><div class="alert" style="border:1px solid red">None match.</div></div></div></main>';
    assert.match(fired(await page(apart), 'state.placement')[0].message, /below the content above it/);
  });
  it('fires on a presentation centred inside a stretched transparent region', async () => {
    const result = await page('<main><div style="height:600px;display:flex;flex-direction:column"><div class="state-region" style="flex:1;display:flex;flex-direction:column;justify-content:center"><div class="alert" style="border:1px solid red">Nothing here yet.</div></div></div></main>');
    assert.match(fired(result, 'state.placement')[0].message, /below the top of its own region/);
  });
  it('passes a presentation that follows the content above it at the layout gap', async () => {
    const result = await page('<main><div style="height:600px;display:flex;flex-direction:column;gap:12px"><div style="height:40px">Filters</div><div class="state-region"><div class="alert" style="border:1px solid red;margin-top:4px">None match.</div></div></div></main>');
    assert.deepEqual(fired(result, 'state.placement'), []);
    const block = await page('<main><div><h2 style="margin:0 0 16px">Results</h2><div class="state-region" style="margin-top:8px"><div class="alert" style="border:1px solid red">None match.</div></div></div></main>');
    assert.deepEqual(fired(block, 'state.placement'), []);
  });
  it('measures a presentation beside its sibling from the top of the region', async () => {
    const result = await page('<main><div style="display:flex;align-items:flex-end;height:300px"><div style="width:200px;height:300px">Rail</div><div class="state-region"><div class="alert" style="border:1px solid red">Nothing selected.</div></div></div></main>');
    assert.match(fired(result, 'state.placement')[0].message, /below the top of the region it replaces/);
  });
  it('passes a transparent container a layout stretched around a content-sized presentation', async () => {
    const result = await page('<main><div style="height:600px;display:flex;flex-direction:column"><div class="state-region" style="flex:1"><div class="alert" style="border:1px solid red">Camera is unavailable.</div></div></div></main>');
    assert.deepEqual(fired(result, 'state.placement'), []);
  });
});

describe('overlays, skip link and landmarks', () => {
  const SHELL = (inner) => `<header>MAVI</header><a class="skip-link" href="#main">Skip to workspace</a>
    <nav aria-label="Primary"><a href="/">Overview</a></nav><main id="main" tabindex="-1">${inner}</main>`;
  it('passes the shell contract', async () => {
    const result = await page(SHELL('<p>Content</p>'));
    assert.deepEqual([...fired(result, 'a11y.skip-link'), ...fired(result, 'a11y.landmarks')], []);
    assert.ok(result.evaluated.includes('a11y.skip-link'));
  });
  it('fires when the skip link is not first, or its target is not the main landmark', async () => {
    const late = await page('<header>MAVI</header><button>First</button><a class="skip-link" href="#main">Skip</a><main id="main" tabindex="-1"></main>');
    assert.match(fired(late, 'a11y.skip-link')[0].message, /not the first focusable/);
    const astray = await page('<header>MAVI</header><a class="skip-link" href="#nowhere">Skip</a><main id="main" tabindex="-1"></main>');
    assert.match(fired(astray, 'a11y.skip-link')[0].message, /does not exist/);
  });
  it('fires when there are two mains or no named primary navigation', async () => {
    const result = await page('<header>MAVI</header><a class="skip-link" href="#main">Skip</a><main id="main" tabindex="-1"></main><main></main>');
    const messages = fired(result, 'a11y.landmarks').map((f) => f.message).join(' | ');
    assert.match(messages, /one main landmark, found 2/);
    assert.match(messages, /no navigation landmark named Primary/);
  });
  const DIALOG = (outside, attrs = 'aria-labelledby="t"') => `<div id="behind" ${outside}><button>Behind</button></div>
    <div class="dialog-host"><div class="dialog" role="dialog" aria-modal="true" ${attrs}><h2 id="t">Discard your changes?</h2><button id="cancel">Cancel</button></div></div>
    <script>document.getElementById('cancel').focus()</script>`;
  it('passes a named Dialog holding focus over an inert page', async () => {
    const result = await page(DIALOG('inert'));
    assert.deepEqual(fired(result, 'overlay.dialog'), []);
    assert.ok(result.evaluated.includes('overlay.dialog'));
  });
  it('fires on a Dialog with a live page behind it, without a name, or without focus', async () => {
    const live = await page(DIALOG(''));
    assert.match(fired(live, 'overlay.dialog')[0].message, /outside the open Dialog are not inert/);
    const unnamed = await page(DIALOG('inert', ''));
    assert.ok(fired(unnamed, 'overlay.dialog').some((f) => /no accessible name/.test(f.message)));
    const unfocused = await page(DIALOG('inert').replace("document.getElementById('cancel').focus()", 'document.activeElement.blur()'));
    assert.ok(fired(unfocused, 'overlay.dialog').some((f) => /focus is outside/.test(f.message)));
  });
  it('treats a modal drawer by the drawer contract', async () => {
    const result = await page(`<div inert><button>Behind</button></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="Inspector" tabindex="-1">
      <button id="close">Close</button></aside><script>document.getElementById('close').focus()</script>`);
    assert.deepEqual(fired(result, 'overlay.drawer'), []);
    assert.ok(result.evaluated.includes('overlay.drawer'));
    assert.ok(!result.evaluated.includes('a11y.skip-link'), 'the skip link is not judged behind a modal');
  });
});

describe('tier composition rules', () => {
  it('evaluates the Tier C rules only at Tier C', async () => {
    const atA = await page('<main><p>x</p></main>');
    assert.ok(!atA.evaluated.some((rule) => rule.startsWith('tier.')));
    const atC = await page('<main><p>x</p></main>', { ...PAGE_INPUT, tier: 'C', width: 390 });
    assert.ok(atC.evaluated.includes('tier.c-shell'));
    assert.ok(!atC.evaluated.includes('shell.rail'), 'the Tier A rail rule is not applicable at Tier C');
  });
});

describe('overlay exit (Escape)', () => {
  // A Dialog opened from a button; on Escape it closes and sends focus to
  // `restoreTo` (the invoker when correct).
  const DIALOG = (restoreTo) => `<main><button id="open">Discard changes</button><button id="other">Elsewhere</button></main>
    <script>
      const open = document.getElementById('open');
      open.addEventListener('click', () => {
        const d = document.createElement('div');
        d.className = 'dialog'; d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'true'); d.setAttribute('aria-label', 'Discard');
        d.innerHTML = '<button>Keep editing</button>';
        document.body.appendChild(d);
        d.querySelector('button').focus();
        document.addEventListener('keydown', function esc(e) {
          if (e.key !== 'Escape') return;
          document.removeEventListener('keydown', esc); d.remove();
          document.getElementById('${restoreTo}').focus();
        });
      });
    </script>`;
  const exitAfter = async (html, { focusInvoker = true } = {}) => {
    await lane.page(html);
    await lane.browser.evaluate(`(() => { const b = document.getElementById('open'); ${focusInvoker ? 'b.focus();' : ''} b.click(); })()`);
    const rule = await lane.browser.evaluate(toExpression(overlayOpened));
    await lane.browser.press('Escape');
    return { rule, ...(await lane.browser.evaluate(toExpression(overlayExitProbe))) };
  };
  it('passes focus restored to the invoker', async () => {
    const exit = await exitAfter(DIALOG('open'));
    assert.equal(exit.rule, 'overlay.dialog');
    assert.equal(exit.closed, true);
    assert.match(exit.invoker, /Discard changes/);
    assert.equal(exit.restored, true);
  });
  it('fails focus sent to an unrelated control, connected and outside the overlay though it is', async () => {
    const exit = await exitAfter(DIALOG('other'));
    assert.equal(exit.closed, true);
    assert.equal(exit.restored, false);
    assert.match(exit.focus, /Elsewhere/);
  });
  it('records no invoker when nothing outside had focus, so restoration cannot pass', async () => {
    const exit = await exitAfter(DIALOG('open'), { focusInvoker: false });
    assert.equal(exit.invoker, null);
    assert.equal(exit.restored, false);
  });
});

describe('the focus pass', () => {
  it('leaves focus where the state put it, inside an open overlay', async () => {
    await lane.page(`<a class="skip-link" href="#main">Skip to workspace</a><main id="main"><button>Behind</button></main>
      <div role="dialog" aria-modal="true" aria-label="Sheet"><button id="inside">Close</button></div>`);
    await lane.browser.evaluate('document.getElementById("inside").focus()');
    const result = await lane.browser.evaluate(toExpression(focusAssertions));
    assert.ok(result.checked >= 3, 'the pass walked the page');
    assert.equal(await lane.browser.evaluate('document.activeElement.id'), 'inside');
  });
});

describe('native dialogs', () => {
  it('dismisses a native confirm, never answering yes, and reports it as a page problem', async () => {
    await lane.page('<main><p id="out">pending</p></main><script>document.getElementById("out").textContent = String(window.confirm("Discard your changes?"));</script>');
    assert.equal(await lane.browser.evaluate('document.getElementById("out").textContent'), 'false');
    assert.ok(lane.browser.problems().some((p) => /native confirm dialog opened \("Discard your changes\?"\)/.test(p)), JSON.stringify(lane.browser.problems()));
  });
});

describe('the rendered Review pin (review.sticky-rendered, R6)', () => {
  // Review's geometry in miniature: the Context Bar in the shell's band above
  // the page scroller, and a two-column grid whose rail is far longer than the
  // player. `barInside` puts a sticky bar in the scroller instead.
  const REVIEW = ({ align = 'stretch', top = 12, barInside = false } = {}) => `
    ${barInside ? '' : '<header class="context-bar" style="height:44px;background:#111">bar</header>'}
    <main class="main" style="height:${barInside ? 768 : 724}px;overflow:auto">
      ${barInside ? '<header class="context-bar" style="position:sticky;top:0;height:44px;background:#111;z-index:2">bar</header>' : ''}
      <section class="workspace workspace--review" style="padding:20px">
        <div style="display:grid;grid-template-columns:1fr 400px;gap:16px;align-items:${align}">
          <div class="workspace__review-main" style="display:grid;align-content:start">
            <div class="workspace__player" style="position:sticky;top:${top}px;height:420px;background:#333">player</div>
          </div>
          <div class="workspace__review-rail" style="height:2400px">rail</div>
        </div>
      </section>
    </main>`;
  const probe = async (html, width = 1366) => {
    await lane.page(TOKENS + html, { width });
    return lane.browser.evaluate(toExpression(stickyProbe));
  };

  it('fails the original layout: a column only as tall as its player has no room to pin it', async () => {
    const result = await probe(REVIEW({ align: 'start' }));
    assert.equal(result.evaluated, true);
    assert.equal(result.pinned, false, JSON.stringify(result));
  });

  it('passes the stretched column: pinned clear of the Context Bar', async () => {
    const result = await probe(REVIEW());
    assert.equal(result.pinned, true, JSON.stringify(result));
    assert.equal(result.underBar, 0, JSON.stringify(result));
    assert.equal(result.topAfter, result.topBefore - 8, 'pinned at the bar plus its inset, not where it started');
  });

  it('catches a player that stays on screen only by sliding under the Context Bar', async () => {
    const result = await probe(REVIEW({ barInside: true }));
    assert.equal(result.pinned, true);
    assert.ok(result.underBar > 0, JSON.stringify(result));
  });

  it('does not evaluate the stacked Review, which releases the pin at 1100', async () => {
    const result = await probe(REVIEW(), 1100);
    assert.equal(result.evaluated, false);
  });
});

describe('Tier B (T1): rules that reject the pre-T1 compositions and pass the designed ones', () => {
  const render = async (html, width, fn, input) => {
    await lane.page(TOKENS + html, { width, height: 768 });
    return lane.browser.evaluate(toExpression(fn, input));
  };
  const pageAt = (html, width) => render(html, width, pageAssertions, { tier: 'B', width, fullWidth: null, archetype: null, holds: null });
  const workspaceAt = (html, width, archetype) => render(html, width, workspaceAssertions, { tier: 'B', width, archetype });
  const SHELL = ({ rail = 56, overlay = false, main = 56 } = {}) => `
    <div class="sidebar" ${overlay ? 'role="dialog" aria-modal="true"' : ''} style="position:${overlay ? 'fixed' : 'absolute'};left:0;top:0;bottom:0;width:${rail}px">
      <button class="sidebar__toggle" aria-expanded="${overlay}" aria-label="Open navigation" style="width:32px;height:32px">N</button>
    </div>
    <main id="main" style="position:absolute;left:${main}px;right:0;top:0;bottom:0"><p>workspace</p></main>`;

  it('tier.b-shell: fires on the pre-T1 expanded rail column; passes the collapsed rail and its modal overlay', async () => {
    const before = await pageAt(SHELL({ rail: 216, main: 216 }), 1024);
    assert.ok(before.evaluated.includes('tier.b-shell'));
    const messages = fired(before, 'tier.b-shell').map((f) => f.message).join('\n');
    assert.match(messages, /takes 216px of width beside the workspace/);
    assert.match(messages, /drawn expanded \(216px\) without being the modal overlay/);
    assert.deepEqual(fired(await pageAt(SHELL(), 1024), 'tier.b-shell'), []);
    assert.deepEqual(fired(await pageAt(SHELL({ rail: 216, overlay: true }), 1024), 'tier.b-shell'), []);
  });

  it('tier.b-shell: fires when a Context Bar action is pushed past the bar or its primary loses its label', async () => {
    const bar = (actions) => SHELL() + `<div class="context-bar" style="position:absolute;left:56px;top:0;width:600px;height:44px;display:flex">
      <div class="context-bar__actions" style="display:flex;flex:none">${actions}</div></div>`;
    const pushed = await pageAt(bar('<button class="btn btn--primary" style="margin-left:560px;width:120px">Save revision</button>'), 1024);
    assert.match(fired(pushed, 'tier.b-shell')[0].message, /extends past the bar/);
    const iconOnly = await pageAt(bar('<button class="btn btn--primary"><svg width="16" height="16"></svg><span class="visually-hidden">Save revision</span></button>'), 1024);
    assert.match(fired(iconOnly, 'tier.b-shell')[0].message, /has lost its visible label/);
    assert.deepEqual(fired(await pageAt(bar('<button class="btn btn--primary"><svg width="16" height="16"></svg>Save revision</button>'), 1024), 'tier.b-shell'), []);
  });

  const WORKBENCH = (columns) => `<div class="main" data-scroll="contain" style="overflow:auto;height:760px">
    <section class="workspace workspace--workbench" style="display:grid;grid-template-columns:${columns};gap:12px">
      <div class="workspace__stage" style="height:240px"></div><div class="workspace__inspector" style="height:200px"></div>
    </section></div>`;
  it('tier.b-composition: fires on a side-by-side Workbench at 1024 (stacked by §25) and on a stacked one at 1200', async () => {
    const compressed = await workspaceAt(WORKBENCH('1fr 300px'), 1024, 'workbench');
    assert.ok(compressed.evaluated.includes('tier.b-composition'));
    assert.match(fired(compressed, 'tier.b-composition')[0].message, /not stacked at 1024px/);
    assert.deepEqual(fired(await workspaceAt(WORKBENCH('1fr'), 1024, 'workbench'), 'tier.b-composition'), []);
    assert.match(fired(await workspaceAt(WORKBENCH('1fr'), 1200, 'workbench'), 'tier.b-composition')[0].message, /not beside the stage at 1200px/);
    assert.deepEqual(fired(await workspaceAt(WORKBENCH('1fr 300px'), 1200, 'workbench'), 'tier.b-composition'), []);
  });

  // The frozen 1101-1149 drawer band (§4.3.1, §25 Tier B): a shut drawer with
  // its toggle and the stage at full width, or not.
  const BAND = ({ drawer, toggle = true, stage = '1fr', inspectorShown = false }) => `<div class="main" data-scroll="contain" style="overflow:hidden;height:760px">
    <section class="workspace workspace--workbench${drawer ? ' is-drawer' : ''}">
      <div class="workspace__band">${toggle ? '<button class="workspace__drawer-toggle">Scene inspector</button>' : ''}</div>
      <div style="display:grid;grid-template-columns:${stage};gap:12px">
        <div class="workspace__stage" style="height:240px"></div>
        <div class="workspace__inspector" style="height:200px;${inspectorShown ? '' : 'display:none'}"></div>
      </div>
    </section></div>`;
  it('workbench.geometry and tier.b-composition: hold the frozen 1101-1149 drawer band and side by side from 1150, from rendered geometry', async () => {
    // Pre-remediation T1: side by side at 1120, where §25 freezes a drawer.
    const beside = await workspaceAt(BAND({ drawer: false, toggle: false, stage: '1fr 300px', inspectorShown: true }), 1120, 'workbench');
    assert.match(fired(beside, 'workbench.geometry')[0].message, /side by side at 1120px .* the frozen 1101-1149 band makes it a drawer/);
    assert.match(fired(beside, 'tier.b-composition')[0].message, /column beside the stage at 1120px, inside the frozen 1101-1149 drawer band/);
    // The class alone is not the composition: a drawer whose inspector is
    // still a column, and a shut drawer nobody can open.
    const parked = await workspaceAt(BAND({ drawer: true, stage: '1fr 300px', inspectorShown: true }), 1120, 'workbench');
    assert.match(fired(parked, 'workbench.geometry').map((f) => f.message).join('\n'), /neither shut nor the open modal drawer/);
    const noToggle = await workspaceAt(BAND({ drawer: true, toggle: false }), 1101, 'workbench');
    assert.match(fired(noToggle, 'workbench.geometry')[0].message, /no visible control to open it/);
    // The designed band at both edges, and side by side above it.
    for (const width of [1101, 1149]) {
      const designed = await workspaceAt(BAND({ drawer: true }), width, 'workbench');
      assert.deepEqual(fired(designed, 'workbench.geometry'), [], String(width));
      assert.deepEqual(fired(designed, 'tier.b-composition'), [], String(width));
    }
    assert.match(fired(await workspaceAt(BAND({ drawer: true }), 1150, 'workbench'), 'workbench.geometry')[0].message, /a drawer at 1150px/);
    assert.deepEqual(fired(await workspaceAt(BAND({ drawer: false, toggle: false, stage: '1fr 300px', inspectorShown: true }), 1150, 'workbench'), 'workbench.geometry'), []);
  });

  const INVESTIGATION = ({ railShown, toggle }) => `<div class="main" data-scroll="contain" style="overflow:auto;height:760px">
    <section class="workspace workspace--investigation">
      <div class="workspace__investigation-grid" style="display:grid;grid-template-columns:${railShown ? '252px 1fr' : '1fr'}">
        <div class="workspace__rail" style="${railShown ? '' : 'display:none'}">filters</div>
        <div class="workspace__results">${toggle ? '<button class="workspace__rail-toggle">Filters</button>' : ''}<div class="results__list" style="overflow:auto">results</div></div>
      </div></section></div>`;
  it('tier.b-composition: fires on the pre-T1 in-flow filter rail at 1024 and on a drawer with no way to open it', async () => {
    const inFlow = await workspaceAt(INVESTIGATION({ railShown: true, toggle: false }), 1024, 'investigation');
    assert.match(fired(inFlow, 'tier.b-composition').map((f) => f.message).join('\n'), /filter rail is in flow at 1024px/);
    const noToggle = await workspaceAt(INVESTIGATION({ railShown: false, toggle: false }), 1024, 'investigation');
    assert.match(fired(noToggle, 'tier.b-composition')[0].message, /no control in the results header/);
    assert.deepEqual(fired(await workspaceAt(INVESTIGATION({ railShown: false, toggle: true }), 1024, 'investigation'), 'tier.b-composition'), []);
  });

  // The Videos Ledger as the harness sees it: its stated columns, a region of
  // `region` px holding a `table` px table, folded or not, with the folded
  // values carried (and named), the Sort select, and the measured-fold mark.
  const FOLDING_LEDGER = ({ region, table, folded = false, carried = true, named = true, statusHidden = false, sort = true, mark = false }) => {
    // A measured fold (`mark`) hides the columns through the stylesheet, as
    // the product does, so setting the mark aside really unfolds them.
    const hide = (on) => (on && !mark ? 'display:none' : '');
    const value = (name, v) => `<span class="ledger-folded__value">${named ? `<span class="visually-hidden" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">${name} </span>` : ''}${v}</span>`;
    return `<style>.workspace--ledger[data-fold] .ledger-fold { display: none; }</style><div class="main" data-scroll="body" style="overflow:hidden;height:760px">
    <section class="workspace workspace--ledger"${mark ? ' data-fold="overflow"' : ''} style="width:${region}px">
      <div class="workspace__band"><div class="toolbar-band">${sort ? `<label class="ledger-sort" style="${hide(!folded)}">Sort <select><option>Recorded, newest first</option><option>Duration, longest first</option><option>File, A to Z</option></select></label>` : ''}</div></div>
      <div class="workspace__body workspace__body--ledger">
      <div class="ledger-table" style="overflow:auto;max-width:100%"><table style="width:${table}px;border-collapse:collapse">
        <thead><tr><th aria-sort="none">File</th><th aria-sort="none">Camera</th><th class="ledger-fold" aria-sort="descending" style="${hide(folded)}">Recorded<span aria-hidden="true">▼</span></th>
          <th class="ledger-fold" aria-sort="none" style="${hide(folded)}">Duration<span aria-hidden="true">↕</span></th><th style="${hide(statusHidden)}">Status</th><th><span class="visually-hidden">Actions</span><span>Actions</span></th></tr></thead>
        <tbody><tr>
          <td><div class="ledger-primary">clip.mp4<span class="ledger-folded" style="${hide(!folded)}">${carried ? value('Recorded', '14 Sept') : ''}${value('Duration', '10m')}</span></div></td>
          <td>GATE-4</td><td class="ledger-fold" style="${hide(folded)}">14 Sept</td><td class="ledger-fold" style="${hide(folded)}">10m</td>
          <td style="${hide(statusHidden)}">Ready</td><td><button>Review</button></td>
        </tr></tbody>
      </table></div></div></section></div>`;
  };
  const ledgerAt = (html, width, tier = 'B') => render(html, width, workspaceAssertions, { tier, width, archetype: 'ledger', surface: 'videos' });
  it('ledger.column-fold: blocks each Ledger fold defect and passes the designed compositions', async () => {
    const messages = (result) => fired(result, 'ledger.column-fold').map((f) => f.message).join('\n');
    // Folding disabled: at a region under Videos' stated 969px, and scrolling sideways.
    const unfolded = await ledgerAt(FOLDING_LEDGER({ region: 900, table: 1200 }), 1024);
    assert.ok(unfolded.evaluated.includes('ledger.column-fold'));
    assert.match(messages(unfolded), /at or under its stated 969px, and Recorded, Duration have not folded/);
    assert.match(messages(unfolded), /scrolls sideways .* while its stated fold column\(s\) Recorded, Duration are still shown/);
    // A transferred value removed.
    assert.match(messages(await ledgerAt(FOLDING_LEDGER({ region: 900, table: 800, folded: true, carried: false }), 1024)),
      /\(Recorded\) are hidden with their column but not shown in the row's primary cell/);
    // A transferred value without its header name: nothing to match it by.
    assert.match(messages(await ledgerAt(FOLDING_LEDGER({ region: 900, table: 800, folded: true, named: false }), 1024)),
      /\(Recorded, Duration\) are hidden with their column/);
    // A required column folded.
    assert.match(messages(await ledgerAt(FOLDING_LEDGER({ region: 900, table: 800, folded: true, statusHidden: true }), 1024)),
      /hides Status, which never fold/);
    // The replacement sort control removed.
    assert.match(messages(await ledgerAt(FOLDING_LEDGER({ region: 900, table: 800, folded: true, sort: false }), 1024)),
      /folded sort key\(s\) Recorded, Duration have no visible, enabled Sort select/);
    // The columns not returning where the unfolded table fits (the measured
    // mark left behind), and any fold at Tier A.
    assert.match(messages(await ledgerAt(FOLDING_LEDGER({ region: 1200, table: 1000, folded: true, mark: true }), 1365)),
      /keeps Recorded, Duration folded in a 1200px region where its unfolded table fits/);
    assert.match(messages(await ledgerAt(FOLDING_LEDGER({ region: 1200, table: 1000, folded: true }), 1366, 'A')), /folds Recorded, Duration at Tier A/);
    // An unstated Ledger is not silently passed.
    const unstated = await render(FOLDING_LEDGER({ region: 900, table: 800 }), 1024, workspaceAssertions, { tier: 'B', width: 1024, archetype: 'ledger', surface: 'import' });
    assert.match(messages(unstated), /no stated fold priority/);
    // The designed compositions: folded under the stated width, every value
    // carried and named, the Sort select offered; unfolded where the table
    // fits; and every column at Tier A.
    assert.deepEqual(fired(await ledgerAt(FOLDING_LEDGER({ region: 900, table: 800, folded: true }), 1024), 'ledger.column-fold'), []);
    assert.deepEqual(fired(await ledgerAt(FOLDING_LEDGER({ region: 1200, table: 1000 }), 1365), 'ledger.column-fold'), []);
    assert.deepEqual(fired(await ledgerAt(FOLDING_LEDGER({ region: 1200, table: 1000 }), 1366, 'A'), 'ledger.column-fold'), []);
  });

  const RECORD = (columns) => `<div class="main" data-scroll="page"><section class="workspace workspace--record">
    <div class="workspace__record-grid" style="display:grid;grid-template-columns:${columns};gap:16px;align-items:start">
      <div class="workspace__record-primary" style="height:300px"></div><div class="workspace__record-facts" style="height:200px"></div>
    </div></section></div>`;
  it('tier.b-composition: holds the Record facts rail beside the primary at 1101-1365 at 280px or more, and below it at 1100', async () => {
    assert.match(fired(await workspaceAt(RECORD('1fr 250px'), 1200, 'record'), 'tier.b-composition')[0].message, /below its 280px minimum/);
    assert.deepEqual(fired(await workspaceAt(RECORD('7fr 3fr'), 1200, 'record'), 'tier.b-composition'), []);
    assert.match(fired(await workspaceAt(RECORD('7fr 3fr'), 1024, 'record'), 'tier.b-composition')[0].message, /not stacked below the primary column/);
    assert.deepEqual(fired(await workspaceAt(RECORD('1fr'), 1024, 'record'), 'tier.b-composition'), []);
  });

  it('archetype.contained-clipping judges the column the stylesheet renders, not the policy it declared', async () => {
    const tall = (overflow) => `<div class="main" data-scroll="contain" style="height:400px;overflow:${overflow}">
      <section class="workspace workspace--workbench" style="display:grid"><div class="workspace__stage" style="height:900px"></div><div class="workspace__inspector" style="height:100px"></div></section></div>`;
    // Lifted at 1100 and below (§25): the column scrolls, so the content is reachable.
    assert.deepEqual(fired(await workspaceAt(tall('auto'), 1024, 'workbench'), 'archetype.contained-clipping'), []);
    // Contained, the same content is unreachable.
    assert.match(fired(await workspaceAt(tall('hidden'), 1024, 'workbench'), 'archetype.contained-clipping')[0].message, /cannot be reached/);
  });

  it('ledger.scroll-ownership requires the Ledger body to own the scroll at every width (pre-T1 lifted it at 1100)', async () => {
    const ledger = (policy) => LEDGER(TABLE('<tr style="height:40px"><td>one</td></tr>')).replace('data-scroll="body"', `data-scroll="${policy}"`);
    const lifted = await render(ledger('contain'), 1024, workspaceAssertions, { tier: 'B', width: 1024, archetype: 'ledger' });
    assert.match(fired(lifted, 'ledger.scroll-ownership')[0].message, /did not declare its body the scroll owner/);
    const owned = await render(ledger('body'), 1024, workspaceAssertions, { tier: 'B', width: 1024, archetype: 'ledger' });
    assert.deepEqual(fired(owned, 'ledger.scroll-ownership'), []);
  });
});

describe('Tier C (T2): rules that reject the pre-T2 compositions and pass the designed ones', () => {
  const render = async (html, width, fn, input) => {
    await lane.page(TOKENS + html, { width, height: 844 });
    return lane.browser.evaluate(toExpression(fn, input));
  };
  const pageAt = (html, archetype = null) => render(html, 390, pageAssertions, { tier: 'C', width: 390, fullWidth: null, archetype, holds: null });
  const workspaceAt = (html, archetype, surface = null) => render(html, 390, workspaceAssertions, { tier: 'C', width: 390, archetype, surface });
  const messages = (result, rule) => fired(result, rule).map((f) => f.message).join('\n');

  // The shell: a navigation landmark inside a rail that is a column (pre-T2)
  // or absent, and a top-of-page control naming it (T2).
  const SHELL = ({ railColumn = false, menu = true, menuName = 'Open navigation', actions = '', back = null, zone = null } = {}) => `
    <div class="sidebar" style="position:absolute;left:0;top:0;bottom:0;width:56px;${railColumn ? '' : 'display:none'}">
      <nav id="primary-nav" aria-label="Primary"><a href="#">O</a></nav>
    </div>
    <main id="main" style="position:absolute;left:${railColumn ? 56 : 0}px;right:0;top:0;bottom:0">
      <div class="context-bar" style="display:flex;align-items:center;gap:8px;height:44px;padding:0 12px">
        ${menu ? `<button class="shell__menu" aria-controls="primary-nav" aria-expanded="false" ${menuName ? `aria-label="${menuName}"` : ''} style="width:32px;height:32px;flex:none"><svg width="16" height="16"></svg></button>` : ''}
        <nav class="context-bar__crumbs" aria-label="Breadcrumb"><ol style="display:flex;margin:0;padding:0">${back ? `<li style="list-style:none;${back === 'hidden' ? 'display:none' : ''}"><a href="/search?cameraId=1">Search</a></li>` : ''}<li style="list-style:none">Videos</li></ol></nav>
        ${zone ? `<span class="context-bar__status"><span class="zone-note"><code class="${zone === 'hidden' ? 'visually-hidden' : ''}">Asia/Kolkata</code></span></span>` : ''}
        <div class="context-bar__actions" style="display:flex;flex:none">${actions}</div>
      </div>
      <p>workspace</p>
    </main>`;

  it('tier.c-shell: fires on the pre-T2 rail column, a missing or unnamed menu control, and a Context Bar action pushed off or unlabelled', async () => {
    const pre = messages(await pageAt(SHELL({ railColumn: true, menu: false })), 'tier.c-shell');
    assert.match(pre, /beside a \d+px rail column/);
    assert.match(pre, /rail is drawn \(56px\) without being the navigation overlay/);
    assert.match(pre, /no visible control opens the navigation/);
    assert.match(messages(await pageAt(SHELL({ menuName: '' })), 'tier.c-shell'), /menu control is unnamed/);
    assert.match(messages(await pageAt(SHELL({ actions: '<button class="btn btn--primary" style="margin-left:400px;width:120px">Import video</button>' })), 'tier.c-shell'),
      /action <button> "Import video" extends past the bar/);
    assert.match(messages(await pageAt(SHELL({ actions: '<button class="btn btn--primary"><svg width="16" height="16"></svg><span class="visually-hidden">Import video</span></button>' })), 'tier.c-shell'),
      /primary action .* has lost its visible label at Tier C/);
    // The way back to a filtered Investigation, and the stated zone, stay drawn.
    assert.match(messages(await pageAt(SHELL({ back: 'hidden' })), 'tier.c-shell'), /way back \(Search, to \/search\?cameraId=1\) is not drawn/);
    assert.match(messages(await pageAt(SHELL({ zone: 'hidden' })), 'tier.c-shell'), /states its time zone only invisibly/);
    assert.deepEqual(fired(await pageAt(SHELL({ back: 'shown', zone: 'shown' })), 'tier.c-shell'), []);
    // The designed bar: the menu control, the identity, the primary with its label.
    assert.deepEqual(fired(await pageAt(SHELL({ actions: '<button class="btn btn--primary"><svg width="16" height="16"></svg>Import video</button>' })), 'tier.c-shell'), []);
  });

  const UNSUPPORTED = ({ canvas = false, statement = true, summary = true, band = false } = {}) => `<main id="main"><div class="context-bar" style="height:44px"></div>
    <section class="workspace workspace--workbench workspace--unsupported">
      ${band ? '<div class="workspace__notices"><label>From <input value="2026-10-09 04:45:00"></label></div>' : ''}
      ${canvas ? '<div class="workspace__stage"><canvas width="300" height="200"></canvas></div><div class="workspace__inspector">inspector</div>' : ''}
      <div class="workspace__unsupported">
        ${statement ? '<p class="workspace__unsupported-statement">Editing a scene needs a display at least 768px wide.</p>' : ''}
        ${summary ? '<div class="panel"><dl class="kv"><dt>Camera</dt><dd>CAM-01</dd></dl></div>' : ''}
      </div>
    </section></main>`;
  it('tier.c-workbench-unsupported: fires on a canvas, stage or inspector, a missing statement and a missing summary', async () => {
    const pre = messages(await pageAt(UNSUPPORTED({ canvas: true }), 'workbench'), 'tier.c-workbench-unsupported');
    assert.match(pre, /the editing canvas renders at Tier C/);
    assert.match(pre, /still renders workspace__stage, workspace__inspector/);
    assert.match(messages(await pageAt(UNSUPPORTED({ statement: false }), 'workbench'), 'tier.c-workbench-unsupported'), /no statement that the operation needs a display of at least 768px/);
    assert.match(messages(await pageAt(UNSUPPORTED({ summary: false }), 'workbench'), 'tier.c-workbench-unsupported'), /has its statement but no read-only summary/);
    assert.match(messages(await pageAt(UNSUPPORTED({ band: true }), 'workbench'), 'tier.c-workbench-unsupported'), /still offers 1 form control\(s\)/);
    assert.deepEqual(fired(await pageAt(UNSUPPORTED(), 'workbench'), 'tier.c-workbench-unsupported'), []);
  });

  // A Videos-like Ledger row: identity, a secondary line, status, action.
  const LIST = ({ list = true, badge = true, action = true, filters = 'drawer', drawerWidth = '100%', sortable = false } = {}) => `
    <style>.list tbody tr{display:grid;grid-template-columns:minmax(0,1fr) auto}.list tbody td{display:block;grid-column:1}.list tbody td:last-child{grid-column:2;grid-row:1/span 4}
      .list thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}</style>
    <div class="main" data-scroll="body" style="height:800px;overflow:auto">
    <section class="workspace workspace--ledger">
      <div class="workspace__band"><div class="toolbar-band"><div class="toolbar-band__row">
        ${filters === 'drawer' ? '<button aria-controls="filters" aria-expanded="false">Filters</button>' : ''}
        <div id="filters" class="toolbar-band__controls"
          ${filters === 'open' ? `role="dialog" aria-modal="true" style="position:fixed;top:0;right:0;bottom:0;width:${drawerWidth}"` : filters === 'drawer' || filters === 'orphan' ? 'style="display:none"' : ''}>
          <input aria-label="Filter"><select aria-label="Camera"><option>All</option></select>
        </div>
      </div></div></div>
      <div class="workspace__body workspace__body--ledger"><div class="ledger-table">
        <table class="table table--ledger ${list ? 'list' : ''}" style="width:100%">
          <thead><tr><th>${sortable ? '<button>File</button>' : 'File'}</th><th>Camera</th><th>Status</th><th>Actions</th></tr></thead>
          <tbody><tr>
            <td>clip.mp4</td><td>CAM-01</td><td>${badge ? '<span class="badge">Processed</span>' : 'Processed'}</td>
            <td>${action ? '<button>Results</button>' : ''}</td>
          </tr></tbody>
        </table>
      </div></div>
    </section></div>`;
  it('tier.c-composition (Ledger): fires on a multi-column table, a row without status or action, inline filters, an orphaned drawer and a narrow open drawer', async () => {
    const table = messages(await workspaceAt(LIST({ list: false }), 'ledger'), 'tier.c-composition');
    assert.match(table, /draws a \d+px column header at Tier C/);
    assert.match(table, /row 1 lays its values out side by side/);
    assert.match(messages(await workspaceAt(LIST({ badge: false }), 'ledger'), 'tier.c-composition'), /row 1 shows no status/);
    assert.match(messages(await workspaceAt(LIST({ sortable: true }), 'ledger'), 'tier.c-composition'), /header is not drawn but holds 1 tab stop\(s\): File/);
    assert.match(messages(await workspaceAt(LIST({ action: false }), 'ledger'), 'tier.c-composition'), /row 1 has no reachable action/);
    assert.match(messages(await workspaceAt(LIST({ filters: 'inline' }), 'ledger'), 'tier.c-composition'), /filters are in the band at Tier C/);
    assert.match(messages(await workspaceAt(LIST({ filters: 'orphan' }), 'ledger'), 'tier.c-composition'), /in a drawer with no visible control to open it/);
    assert.match(messages(await workspaceAt(LIST({ filters: 'open', drawerWidth: '300px' }), 'ledger'), 'tier.c-composition'), /open Ledger filter drawer is 300px, not the full width/);
    assert.deepEqual(fired(await workspaceAt(LIST(), 'ledger'), 'tier.c-composition'), []);
    assert.deepEqual(fired(await workspaceAt(LIST({ filters: 'open' }), 'ledger'), 'tier.c-composition'), []);
  });

  const OVERVIEW = ({ extra = false, countsFirst = false } = {}) => {
    const attention = '<div class="panel attention"><div class="panel__title">Needs attention</div><ul><li>south-dock</li></ul></div>';
    const counts = '<div class="summary-band"><a href="#">Cameras 2</a></div>';
    return `<section class="workspace workspace--ledger-summary"><div class="workspace__body workspace__body--scroll">
      ${countsFirst ? counts + attention : attention + counts}
      ${extra ? '<div class="panel"><div class="panel__title">Recent tracks</div><p>rows</p></div>' : ''}
    </div></section>`;
  };
  it('tier.c-composition (Overview): fires on a secondary panel and on counts before the attention list', async () => {
    assert.match(messages(await workspaceAt(OVERVIEW({ extra: true }), 'ledger-summary'), 'tier.c-composition'), /draws 1 panel\(s\) besides the attention list at Tier C: Recent tracks/);
    assert.match(messages(await workspaceAt(OVERVIEW({ countsFirst: true }), 'ledger-summary'), 'tier.c-composition'), /counts come before the attention list/);
    assert.deepEqual(fired(await workspaceAt(OVERVIEW(), 'ledger-summary'), 'tier.c-composition'), []);
  });

  const RECORD = ({ order = 'primary-first', beside = false, visual = null } = {}) => {
    const primary = '<div class="workspace__record-primary" style="height:200px">run</div>';
    const facts = '<div class="workspace__record-facts" style="height:120px">video</div>';
    const grid = beside ? 'display:grid;grid-template-columns:1fr 1fr' : 'display:grid;grid-template-columns:1fr';
    // `visual` draws the regions in an order other than the document's.
    const style = visual ? '<style>.workspace__record-facts{order:' + (visual === 'facts-first' ? -1 : 1) + '}</style>' : '';
    return style + `<div class="main" data-scroll="page"><section class="workspace workspace--record"><div class="workspace__record-grid" style="${grid}">
      ${order === 'facts-first' ? facts + primary : primary + facts}</div></section></div>`;
  };
  it('tier.c-composition (Record): fires on a rail beside the primary, the stated order not kept, and a visual order unlike the reading order', async () => {
    assert.match(messages(await workspaceAt(RECORD({ beside: true }), 'record', 'import'), 'tier.c-composition'), /beside the primary column at Tier C/);
    assert.match(messages(await workspaceAt(RECORD(), 'record', 'processing-detail'), 'tier.c-composition'), /carries the identity but is below the primary column/);
    assert.match(messages(await workspaceAt(RECORD({ order: 'facts-first' }), 'record', 'import'), 'tier.c-composition'), /above the primary column, though it does not carry the identity/);
    assert.match(messages(await workspaceAt(RECORD({ visual: 'facts-first' }), 'record', 'processing-detail'), 'tier.c-composition'), /shown in a different order from the one they are read in/);
    assert.deepEqual(fired(await workspaceAt(RECORD({ order: 'facts-first' }), 'record', 'processing-detail'), 'tier.c-composition'), []);
    assert.deepEqual(fired(await workspaceAt(RECORD(), 'record', 'import'), 'tier.c-composition'), []);
  });

  const SEARCH = ({ grid = false, rail = 'shut', inspectorWidth = null, results = '100%' } = {}) => `<div class="main" data-scroll="contain" style="height:800px;overflow:auto">
    <section class="workspace workspace--investigation is-stacked">
      <div class="workspace__investigation-grid" style="display:grid;grid-template-columns:${rail === 'flow' ? '252px 1fr' : '1fr'}">
        <div class="workspace__rail" ${rail === 'flow' ? '' : 'style="display:none"'}>filters</div>
        <div class="workspace__results" style="width:${results}">
          ${grid ? '<button aria-label="Grid view">G</button><div class="track-grid">cards</div>' : '<ul><li>Track 1</li></ul>'}
        </div>
        ${inspectorWidth ? `<div class="workspace__inspector" role="dialog" aria-modal="true" style="position:fixed;top:0;right:0;bottom:0;width:${inspectorWidth}">inspector</div>` : ''}
      </div></section></div>`;
  it('tier.c-composition (Investigation): fires on grid view, partial-width results, an in-flow rail and a narrow inspector drawer', async () => {
    const grid = messages(await workspaceAt(SEARCH({ grid: true }), 'investigation'), 'tier.c-composition');
    assert.match(grid, /grid view is offered at Tier C/);
    assert.match(grid, /drawn as the grid at Tier C/);
    assert.match(messages(await workspaceAt(SEARCH({ results: '60%' }), 'investigation'), 'tier.c-composition'), /the results are \d+(\.\d)?px of a \d+(\.\d)?px working width/);
    assert.match(messages(await workspaceAt(SEARCH({ rail: 'flow' }), 'investigation'), 'tier.c-composition'), /filter rail is in flow at Tier C/);
    assert.match(messages(await workspaceAt(SEARCH({ inspectorWidth: '300px' }), 'investigation'), 'tier.c-composition'), /inspector drawer is 300px, not the full width/);
    assert.deepEqual(fired(await workspaceAt(SEARCH({ inspectorWidth: '100%' }), 'investigation'), 'tier.c-composition'), []);
  });

  const REVIEW = ({ player = '100%', sticky = false, order = ['player', 'summary', 'provenance'], control = 32 } = {}) => {
    const parts = {
      player: `<div class="workspace__player" style="width:${player};position:${sticky ? 'sticky' : 'static'};top:0"><div style="height:200px">video</div><button style="width:${control}px;height:${control}px">Play</button></div>`,
      summary: '<div class="panel"><div class="panel__title">Track summary</div><p>Person</p></div>',
      provenance: '<div class="panel"><div class="panel__title">Processing provenance</div><p>run</p></div>',
    };
    return `<div class="main" data-scroll="page"><section class="workspace workspace--review"><div class="workspace__review-grid" style="display:grid;grid-template-columns:1fr">
      ${order.map((part) => parts[part]).join('')}</div></section></div>`;
  };
  it('tier.c-composition (Review): fires on a narrow or sticky player, summary or provenance out of order, and an undersized transport control', async () => {
    assert.match(messages(await workspaceAt(REVIEW({ player: '70%' }), 'review'), 'tier.c-composition'), /Evidence Player is \d+(\.\d)?px of a \d+(\.\d)?px working width/);
    assert.match(messages(await workspaceAt(REVIEW({ sticky: true }), 'review'), 'tier.c-composition'), /still sticky at Tier C/);
    assert.match(messages(await workspaceAt(REVIEW({ order: ['summary', 'player', 'provenance'] }), 'review'), 'tier.c-composition'), /Track summary is not below the Evidence Player/);
    assert.match(messages(await workspaceAt(REVIEW({ order: ['player', 'provenance', 'summary'] }), 'review'), 'tier.c-composition'), /provenance comes before the Track summary/);
    assert.match(messages(await workspaceAt(REVIEW({ control: 18 }), 'review'), 'tier.c-composition'), /1 Evidence Player control\(s\) under the 24px effective target/);
    assert.deepEqual(fired(await workspaceAt(REVIEW(), 'review'), 'tier.c-composition'), []);
  });
});

describe('Tier C Ledger semantics (T2): the list composition is still a table to assistive technology', () => {
  it('passes a table composed as a list by CSS, and fires when the composition strips its table roles', async () => {
    const { tierCLedgerSemantics } = await import('../semantics.mjs');
    const table = (attrs) => `<style>.l tbody tr{display:grid}.l tbody td{display:block}.l thead{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)}</style>
      <table class="table table--ledger l" ${attrs}><caption>Videos</caption><thead><tr><th>File</th><th>Status</th></tr></thead>
      <tbody><tr><td>clip.mp4</td><td>Processed</td></tr></tbody></table>`;
    await lane.page(TOKENS + table(''), { width: 390, height: 844 });
    const kept = await tierCLedgerSemantics(lane.browser);
    assert.deepEqual(kept.findings, [], JSON.stringify(kept.roles));
    await lane.page(TOKENS + table('role="presentation"'), { width: 390, height: 844 });
    const stripped = await tierCLedgerSemantics(lane.browser);
    assert.ok(stripped.findings.some((f) => /exposes its table as/.test(f)), JSON.stringify(stripped.roles));
    await lane.page(TOKENS + '<p>no ledger</p>', { width: 390, height: 844 });
    assert.equal(await tierCLedgerSemantics(lane.browser), null);
  });
});
