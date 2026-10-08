/**
 * Non-vacuity of the rendered assertions (register V1): each new rule is shown
 * to pass a conforming page, to fire on a deliberate violation, and to report
 * itself as evaluated — so a rule whose selector stops matching is caught, not
 * quietly passed.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { focusAssertions, overlayExitProbe, overlayOpened, pageAssertions, toExpression, workspaceAssertions } from '../assertions.mjs';
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
  <main class="main" data-scroll="contain" style="height:700px;overflow:hidden">
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
  it('fires on text that spills out of its box in an S1 region (blocking rule)', async () => {
    const result = await page('<div class="context-bar"><div style="width:80px;white-space:nowrap">averyveryveryverylongidentifier</div></div>');
    assert.match(fired(result, 'text.overflow')[0].message, /spills out/);
    assert.deepEqual(fired(result, 'text.overflow-surface'), []);
  });
  it('reports the same overflow on unmigrated surface content under the surface rule', async () => {
    const result = await page('<main><div style="width:80px;white-space:nowrap">averyveryveryverylongidentifier</div></main>');
    assert.match(fired(result, 'text.overflow-surface')[0].message, /spills out/);
    assert.deepEqual(fired(result, 'text.overflow'), []);
  });
  it('fires on text cut off without an ellipsis', async () => {
    const result = await page('<div class="workspace--ledger"><div style="width:80px;white-space:nowrap;overflow:hidden">averyveryveryverylongidentifier</div></div>');
    assert.match(fired(result, 'text.overflow')[0].message, /without an ellipsis/);
  });
  it('passes the sanctioned truncation, a scroll region and visually hidden text', async () => {
    const result = await page(`<main>
      <div style="width:80px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">averyveryveryverylongidentifier</div>
      <div style="width:80px;white-space:nowrap;overflow-x:auto">averyveryveryverylongidentifier</div>
      <div class="visually-hidden" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)">averyveryveryverylongidentifier</div>
      <p>An ordinary sentence that wraps where it needs to.</p></main>`);
    assert.deepEqual([...fired(result, 'text.overflow'), ...fired(result, 'text.overflow-surface')], []);
    assert.ok(result.evaluated.includes('text.overflow-surface'));
  });
});

describe('pressed.visible', () => {
  it('fires on a pressed control whose pressed state changes nothing visible', async () => {
    const result = await page('<main><button aria-pressed="true">Zones</button></main>');
    assert.match(fired(result, 'pressed.visible')[0].message, /looks the same as when it is not/);
  });
  it('fires on a group whose pressed member looks like its unpressed peer, class or not', async () => {
    const result = await page(`<main><div role="group" aria-label="Mode">
      <button class="seg is-active" aria-pressed="true">Activity</button><button class="seg" aria-pressed="false">Heatmap</button></div></main>`);
    assert.ok(fired(result, 'pressed.visible').some((f) => /unpressed peer/.test(f.message)));
  });
  it('passes a group whose pressed style comes from a class the product sets, and a selected row', async () => {
    const result = await page(`<style>.seg.is-active{background:#2563eb} li.is-selected{background:#1b2a45}</style><main>
      <div role="group" aria-label="Mode"><button class="seg is-active" aria-pressed="true">Activity</button><button class="seg" aria-pressed="false">Heatmap</button></div>
      <ul><li class="is-selected"><button aria-pressed="true">Loading bay</button></li><li><button aria-pressed="false">Forecourt</button></li></ul></main>`);
    assert.deepEqual(fired(result, 'pressed.visible'), []);
  });
  it('passes a fill, a descendant mark, and a fill behind a transition', async () => {
    const result = await page(`<style>
        .fill[aria-pressed="true"]{background:#123456}
        .chip .mark{display:inline-block;width:10px;height:10px;border:1px solid #fff}
        .chip[aria-pressed="true"] .mark{background:#2563eb}
        .slow{transition:background 2s} .slow[aria-pressed="true"]{background:#654321}
      </style><main>
        <button class="fill" aria-pressed="true">Fill</button>
        <button class="chip" aria-pressed="false"><span class="mark"></span>Chip</button>
        <button class="slow" aria-pressed="false">Slow</button></main>`);
    assert.deepEqual(fired(result, 'pressed.visible'), []);
    assert.ok(result.evaluated.includes('pressed.visible'));
  });
  it('leaves the control in the state it found it', async () => {
    await page('<main><button aria-pressed="false">Zones</button></main>');
    assert.equal(await lane.browser.evaluate('document.querySelector("button").getAttribute("aria-pressed")'), 'false');
  });
});

describe('containment.depth and state.placement', () => {
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
