/**
 * X1 (§23): every named rule passes a conforming page, fires on a deliberate
 * violation, and reports itself evaluated — in real Chromium, with names from
 * its accessibility tree and the probes driven through its input pipeline.
 */
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';
import { toExpression } from '../assertions.mjs';
import { a11yAssertions, a11yLiveCheck, a11yLiveMark, a11yNamesJudge, a11yTextSpacingEnvironment } from '../a11y.mjs';
import { createLedger, planCases, sweepChecks, textSpacingCoverageFaults } from '../engine.mjs';
import { RULES, TEXT_SPACING_CONDITION } from '../manifest.mjs';
import { probeHoverContent, probeShortcuts } from '../probes.mjs';
import { TEXT_SPACING_CSS } from '../server.mjs';
import { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM } from '../states.mjs';
import { e2eIt, openBrowser, unitBlock } from './browser.mjs';

const TOKENS = '<style>:root{--dur:20ms} body{margin:0;font:14px sans-serif} button,a{font:inherit}</style>';
const INPUT = { tier: 'A', width: 1366, fullWidth: null, archetype: null, holds: null, surface: 'videos' };
let lane;
before(async () => { lane = await openBrowser(); });
after(async () => { await lane.close(); });

/** The DOM rules alone. */
async function rules(html, input = INPUT) {
  await lane.page(TOKENS + html);
  return lane.browser.evaluate(toExpression(a11yAssertions, input));
}
/** The DOM rules, then Chromium's names and the verdicts that need them. */
async function judge(html, input = INPUT) {
  await lane.page(TOKENS + html);
  const x1 = await lane.browser.evaluate(toExpression(a11yAssertions, input));
  const names = await lane.browser.axNames('[data-vqa-ax]');
  const judged = await lane.browser.evaluate(toExpression(a11yNamesJudge, { controls: x1.controls, names, tooltips: x1.measured.tooltipList }));
  return { findings: [...x1.findings, ...judged.findings], evaluated: [...x1.evaluated, ...judged.evaluated], measured: { ...x1.measured, names: judged.measured } };
}
const of = (result, rule) => result.findings.filter((f) => f.rule === rule).map((f) => f.message).join('\n');

describe('a11y.target-size: one discovery of what a pointer presses, measured by its effective target', unitBlock(), () => {
  it('passes a 14px checkbox whose label is 24px tall, and fails the bare mark or a short label', async () => {
    const LABEL = (h) => `<label class="checkbox" style="display:inline-flex;align-items:center;min-height:${h}px;gap:8px"><input type="checkbox" style="width:14px;height:14px;margin:0">Evaluate this zone</label>`;
    let r = await rules(LABEL(24));
    assert.equal(of(r, 'a11y.target-size'), '');
    assert.ok(r.evaluated.includes('a11y.target-size'));
    r = await rules(LABEL(0).replace('min-height:0px', 'min-height:0;height:16px'));
    assert.match(of(r, 'a11y.target-size'), /<input> \d+x16 \(its label, the hit area that toggles it\)/);
    r = await rules('<input type="checkbox" style="width:14px;height:14px">');
    assert.match(of(r, 'a11y.target-size'), /<input> 14x14 \(its own box\)/);
  });

  it('measures a canvas handle by its hit circle, a disclosure by its summary, a chip control by its own box', async () => {
    const HANDLE = (r) => `<svg width="200" height="200"><g class="scene-handle"><circle class="scene-handle__hit" cx="50" cy="50" r="${r}" fill="transparent"/><circle class="scene-handle__mark" cx="50" cy="50" r="3.5"/></g></svg>`;
    assert.match(of(await rules(HANDLE(11)), 'a11y.target-size'), /<circle.scene-handle__hit> 22x22 \(its invisible hit circle/);
    assert.equal(of(await rules(HANDLE(12)), 'a11y.target-size'), '');
    assert.match(of(await rules('<details><summary style="display:block;height:16px;line-height:16px">3 more</summary><p>x</p></details>'), 'a11y.target-size'), /<summary> "3 more" \d+x16/);
    assert.equal(of(await rules('<details><summary style="display:flex;align-items:center;min-height:24px">3 more</summary><p>x</p></details>'), 'a11y.target-size'), '');
    assert.match(of(await rules('<span class="chip" style="display:flex;width:120px"><span class="truncate" style="flex:1 1 auto">a very long committed filter value that squeezes</span><button style="width:24px;height:24px;flex:1 1 auto;min-width:0;padding:0">×</button></span>'), 'a11y.target-size'), /<button> "×" \d+x24/);
  });

  it('excludes what a pointer does not press: a programmatic focus target, a scrollable region, a hidden skip link, a disabled control', async () => {
    const r = await rules('<a class="skip-link" href="#main" style="position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%)">Skip</a><main id="main" tabindex="-1" style="height:20px"><div tabindex="0" style="height:10px;overflow:auto">scrolls</div><button disabled style="width:10px;height:10px">x</button><button style="width:30px;height:30px">ok</button></main>');
    assert.equal(of(r, 'a11y.target-size'), '');
    assert.equal(r.measured.targets.judged, 1);
    assert.equal(r.measured.targets.excluded.disabled, 1);
  });
});

describe('a11y.names and a11y.form-fields: names from the accessibility tree', unitBlock(), () => {
  it('requires a name, requires it to contain the visible label, and refuses a title as the only name', async () => {
    let r = await judge('<button aria-label="Save draft">Save</button><button aria-label="Save draft now">Save <b>draft</b></button><a href="/x">R<span>4</span> Active</a>');
    assert.equal(of(r, 'a11y.names'), '');
    assert.ok(r.evaluated.includes('a11y.names'));
    r = await judge('<button aria-label="Submit">Save</button>');
    assert.match(of(r, 'a11y.names'), /named "Submit" but shows "Save": the name does not contain the visible label/);
    // A name that is merely part of the visible label is not a name that contains it.
    r = await judge('<button aria-label="S">Save</button><button aria-label="Save">Save draft now</button>');
    assert.match(of(r, 'a11y.names'), /named "S" but shows "Save"/);
    assert.match(of(r, 'a11y.names'), /named "Save" but shows "Save draft now"/);
    r = await judge('<button><svg width="16" height="16"></svg></button>');
    assert.match(of(r, 'a11y.names'), /<button> has no accessible name/);
    r = await judge('<button title="Delete"><svg width="16" height="16"></svg></button>');
    assert.match(of(r, 'a11y.names'), /named by its title alone \("Delete"\)/);
  });

  it('keeps the one exception: a collapsed rail item named by its title', async () => {
    const RAIL = (expanded) => `<header><button aria-controls="rail" aria-expanded="${expanded}">Collapse navigation</button></header><aside class="sidebar" id="rail"><nav aria-label="Primary"><a href="/cameras" title="Cameras"><svg width="16" height="16"></svg></a></nav></aside>`;
    assert.equal(of(await judge(RAIL('false')), 'a11y.names'), '');
    assert.match(of(await judge(RAIL('true')), 'a11y.names'), /named by its title alone/);
  });

  it('labels every field, never by its placeholder alone, and associates and announces an error', async () => {
    let r = await judge('<label for="q">Filter</label><input id="q" placeholder="Type to filter"><input placeholder="Name" aria-label="Name">');
    assert.equal(of(r, 'a11y.form-fields'), '');
    assert.ok(r.evaluated.includes('a11y.form-fields'));
    r = await judge('<input placeholder="Filter by file">');
    assert.match(of(r, 'a11y.form-fields'), /labelled by its placeholder alone \("Filter by file"\)/);
    r = await judge('<label for="n">Name</label><input id="n" aria-invalid="true" aria-describedby="e"><p id="e" role="alert">Name is required.</p>');
    assert.equal(of(r, 'a11y.form-fields'), '');
    r = await judge('<label for="n">Name</label><input id="n" aria-invalid="true">');
    assert.match(of(r, 'a11y.form-fields'), /aria-invalid with no rendered error message associated/);
    r = await judge('<label for="n">Name</label><input id="n" aria-invalid="true" aria-describedby="e"><p id="e">Name is required.</p>');
    assert.match(of(r, 'a11y.form-fields'), /associated but neither announced .* nor focused/);
    r = await judge('<label for="n">Name</label><input id="n" aria-invalid="true" aria-describedby="e" autofocus><p id="e">Name is required.</p><script>document.getElementById("n").focus()</script>');
    assert.equal(of(r, 'a11y.form-fields'), '');
  });
});

describe('a11y.role-contract: real ARIA contracts and the two §23 examples', unitBlock(), () => {
  it('requires aria-expanded to name a rendered region, ids to resolve, options to hold nothing focusable', async () => {
    let r = await rules('<button aria-expanded="true" aria-controls="r">Filters</button><div id="r">filters</div><details><summary>More</summary>x</details><div role="listbox"><div role="option">A</div></div>');
    assert.equal(of(r, 'a11y.role-contract'), '');
    assert.ok(r.evaluated.includes('a11y.role-contract'));
    assert.match(of(await rules('<button aria-expanded="false">Filters</button>'), 'a11y.role-contract'), /aria-expanded="false" with no controlled region/);
    assert.match(of(await rules('<button aria-expanded="true" aria-controls="r">Filters</button><div id="r" hidden>filters</div>'), 'a11y.role-contract'), /aria-expanded="true" but its region <div> "filters" is not rendered/);
    assert.match(of(await rules('<button aria-labelledby="nope">x</button>'), 'a11y.role-contract'), /aria-labelledby="nope" names an id that does not resolve/);
    assert.match(of(await rules('<div role="listbox"><div role="option"><button>pick</button></div></div>'), 'a11y.role-contract'), /is an option holding a focusable <button>/);
  });

  it('refuses a native-equivalent role on a generic element and a native control re-roled', async () => {
    assert.match(of(await rules('<div role="button" tabindex="0">Go</div>'), 'a11y.role-contract'), /claims role="button" where the native button carries the semantics/);
    assert.match(of(await rules('<button role="presentation">x</button>'), 'a11y.role-contract'), /re-roles a native control as "presentation"/);
    assert.equal(of(await rules('<div role="status">ok</div><div role="group" aria-label="Filters"><div role="group">unnamed is fine</div></div><a href="/x" role="button">x</a>'), 'a11y.role-contract'), '');
  });
});

describe('a11y.live-regions: rendered, and mounted before populated', unitBlock(), () => {
  it('fails a live region that is not rendered or inside aria-hidden', async () => {
    assert.match(of(await rules('<p role="status" style="display:none">saved</p>'), 'a11y.live-regions'), /not rendered \(display none\)/);
    assert.match(of(await rules('<div aria-hidden="true"><p aria-live="polite">saved</p></div>'), 'a11y.live-regions'), /inside aria-hidden/);
    const r = await rules('<p role="status"></p>');
    assert.equal(of(r, 'a11y.live-regions'), '');
    assert.ok(r.evaluated.includes('a11y.live-regions'));
  });

  it('judges a preparation: a status region inserted with its message fails; one mounted empty and filled passes; an alert inserted is its contract', async () => {
    await lane.page(TOKENS + '<main><p id="s" role="status"></p><div id="host"></div></main>');
    await lane.browser.evaluate(toExpression(a11yLiveMark));
    await lane.browser.evaluate('(() => { document.getElementById("s").textContent = "Saved"; const p = document.createElement("p"); p.setAttribute("role", "status"); p.textContent = "Run status may be out of date"; document.getElementById("host").appendChild(p); const a = document.createElement("div"); a.setAttribute("role", "alert"); a.textContent = "The camera could not be created."; document.getElementById("host").appendChild(a); return true; })()');
    const r = await lane.browser.evaluate(toExpression(a11yLiveCheck));
    assert.equal(r.judged, 2);
    assert.equal(r.findings.length, 1);
    assert.match(r.findings[0].message, /<p> "Run status may be out of date" was inserted already holding "Run status may be out of date"/);
  });

  it('judges timing, not membership: a region inserted empty and given its text in a later frame is a change in an existing region; in the same frame — a later task or microtask included — it is an insertion', async () => {
    const SLOT = '<span class=\\"announcer\\" role=\\"status\\"></span><p class=\\"empty\\">No videos imported yet.</p>';
    const after = async (wait) => {
      await lane.page(TOKENS + '<main><div id="host"></div></main>');
      await lane.browser.evaluate(toExpression(a11yLiveMark));
      await lane.browser.evaluate('(async () => { const slot = document.createElement("div"); slot.innerHTML = "' + SLOT + '"; document.getElementById("host").appendChild(slot); await (' + wait + '); slot.querySelector(".announcer").textContent = "No videos imported yet."; await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0))); return true; })()');
      return lane.browser.evaluate(toExpression(a11yLiveCheck));
    };
    // The product's StatusSlot: the sentence lands after the next frame, one task on.
    let r = await after('new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)))');
    assert.equal(r.judged, 1);
    assert.deepEqual(r.findings, []);
    assert.ok(r.frames >= 1, String(r.frames));
    // A microtask later is the same frame: an insertion.
    r = await after('Promise.resolve()');
    assert.equal(r.judged, 1);
    assert.match(of(r, 'a11y.live-regions'), /<span.announcer> "No videos imported yet." was inserted already holding/);
    // So is the same task.
    r = await after('null');
    assert.match(of(r, 'a11y.live-regions'), /was inserted already holding/);
  });

  it('exempts only a region inside an overlay the preparation opened and put focus in', async () => {
    const OPEN = (focus) => '(() => { const d = document.createElement("div"); d.setAttribute("role", "dialog"); d.innerHTML = "<button>Keep</button><p role=\\"status\\">Draft kept</p>"; document.getElementById("host").appendChild(d); ' + (focus ? 'd.querySelector("button").focus();' : '') + ' return true; })()';
    await lane.page(TOKENS + '<main><div id="host"></div></main>');
    await lane.browser.evaluate(toExpression(a11yLiveMark));
    await lane.browser.evaluate(OPEN(true));
    let r = await lane.browser.evaluate(toExpression(a11yLiveCheck));
    assert.deepEqual(r.findings, []);
    assert.equal(r.judged, 0);
    await lane.page(TOKENS + '<main><div id="host"></div></main>');
    await lane.browser.evaluate(toExpression(a11yLiveMark));
    await lane.browser.evaluate(OPEN(false));
    r = await lane.browser.evaluate(toExpression(a11yLiveCheck));
    assert.match(of(r, 'a11y.live-regions'), /<p> "Draft kept" was inserted already holding/);
  });
});

describe('a11y.tooltips: no information required to operate the product', unitBlock(), () => {
  it('passes a name, a name with a key hint, a truncated value, a timestamp\'s full form and text stated elsewhere; fails an instruction only in a tooltip', async () => {
    let r = await judge(`
      <button title="Play (Space)">Play</button>
      <span class="tooltip-anchor"><button aria-describedby="t1">Next result</button><span role="tooltip" id="t1" hidden>Next result · j or ↓</span></span>
      <span class="truncate" style="display:inline-block;width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="north-gate-0900-very-long-original-file-name.mp4">north-gate-0900-very-long-original-file-name.mp4</span>
      <td class="num" title="14 Sept 2026, 09:00:00">14 Sept, 09:00</td>
      <time datetime="2026-09-14T09:00:00Z" title="14 September 2026 09:00">09:00</time>
      <p>Tracks is the final count, recorded when the run completed.</p><table><tr><th title="Final count, recorded when the run completed">Tracks</th></tr></table>
      <p>Adjust the window before refreshing.</p><button disabled title="Adjust the window before refreshing.">Refresh</button>`);
    assert.equal(of(r, 'a11y.tooltips'), '');
    assert.ok(r.evaluated.includes('a11y.tooltips'));
    r = await judge('<button title="Press to discard the draft and reload">Reload</button>');
    assert.match(of(r, 'a11y.tooltips'), /carries "Press to discard the draft and reload" only in a tooltip/);
    // A heading's definition is not stated by being a heading.
    r = await judge('<table><tr><th title="Final count, recorded when the run completed">Tracks</th></tr></table>');
    assert.match(of(r, 'a11y.tooltips'), /carries "Final count, recorded when the run completed" only in a tooltip/);
    // K is the name and one key: an instruction bracketed after the name is still an instruction.
    r = await judge('<button title="Delete (this cannot be undone; press twice to confirm)">Delete</button><button title="Save · you must adjust the window first">Save</button><button title="Open full review (Enter)">Open</button>');
    assert.match(of(r, 'a11y.tooltips'), /carries "Delete \(this cannot be undone; press twice to confirm\)" only in a tooltip/);
    assert.match(of(r, 'a11y.tooltips'), /carries "Save · you must adjust the window first" only in a tooltip/);
    assert.match(of(r, 'a11y.tooltips'), /carries "Open full review \(Enter\)" only in a tooltip/);
    // V is the truncated holder's own full value, not any truncated descendant's.
    r = await judge('<table><tr title="Retry from the queue page"><td><span class="truncate" style="display:inline-block;width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">north-gate-0900-very-long-original-file-name.mp4</span></td></tr></table>');
    assert.match(of(r, 'a11y.tooltips'), /carries "Retry from the queue page" only in a tooltip/);
  });
});

describe('a11y.tab-order and a11y.reading-order', unitBlock(), () => {
  const PAGE = (body) => `<main><section class="page">${body}</section></main>`;
  it('fails a reversed row, a reversed column at Tier C, and a wrapped grid whose order scatters its stops', async () => {
    assert.match(of(await rules(PAGE('<div style="display:flex;flex-direction:row-reverse"><button>First</button><button>Second</button></div>')), 'a11y.tab-order'), /reaches <button> "Second" after <button> "First", but it is drawn before it on the same line/);
    assert.match(of(await rules(PAGE('<div style="display:flex;flex-direction:column-reverse"><button>First</button><button>Second</button></div>'), { ...INPUT, tier: 'C' }), 'a11y.tab-order'), /drawn above it in the same column|reading order/);
    const GRID = `<div style="display:grid;grid-template-columns:repeat(3,100px);gap:4px">
      <button style="order:5">A</button><button style="order:1">B</button><button style="order:4">C</button><button style="order:2">D</button><button style="order:6">E</button><button style="order:3">F</button></div>`;
    assert.match(of(await rules(PAGE(GRID)), 'a11y.tab-order'), /visits <button> "A" where the reading order of <div>.* has <button> "B": focus order is not the reading order/);
  });

  it('passes side-by-side columns read one after another, a column-flow container, and controls placed by their data', async () => {
    const r = await rules(PAGE(`<div style="display:grid;grid-template-columns:1fr 1fr;grid-auto-flow:column;grid-template-rows:auto auto"><button>Top left</button><button>Bottom left</button><button>Top right</button><button>Bottom right</button></div>
      <div style="position:relative;height:60px"><div style="position:absolute;left:0;top:30px"><button>Second</button></div><div style="position:absolute;left:0;top:0"><button>First</button></div></div>
      <div style="display:flex"><div style="display:flex;flex-direction:column"><button>a1</button><button>a2</button></div><div style="display:flex;flex-direction:column"><button>b1</button><button>b2</button></div></div>`));
    assert.equal(of(r, 'a11y.tab-order'), '');
    assert.ok(r.evaluated.includes('a11y.tab-order'));
  });

  it('holds the document order of content to its visual order in a sequential region, non-focusable content included', async () => {
    let r = await rules(PAGE('<dl style="display:flex;flex-direction:column-reverse"><dt>Camera</dt><dd>North gate</dd><dt>Recorded</dt><dd>14 Sept</dd></dl>'));
    assert.match(of(r, 'a11y.reading-order'), /in <dl>.* the document reads <dt> "Camera" where the page shows <dd> "14 Sept"/);
    r = await rules('<main><div class="page"><section style="order:2">Summary of the track</section><section style="order:1">Provenance of the run</section></div></main>'.replace('<div class="page">', '<div class="page" style="display:flex;flex-direction:column">'));
    assert.match(of(r, 'a11y.reading-order'), /the document reads <section> "Summary of the track" where the page shows <section> "Provenance of the run"/);
    r = await rules(PAGE('<table><tbody><tr><td>one</td></tr><tr><td>two</td></tr></tbody></table><ul><li>a</li><li>b</li></ul><div class="context-bar"><span>Videos</span><span>4 of 4</span></div>'));
    assert.equal(of(r, 'a11y.reading-order'), '');
    assert.ok(r.evaluated.includes('a11y.reading-order'));
  });
});

describe('a11y.state-cues: a cue that is not colour alone', unitBlock(), () => {
  it('fails a selected item told from its peers by background colour alone, and passes a bar, a weight, a glyph or a luminance step', async () => {
    // A tint of the same lightness is colour alone; a dark highlight on a light page is a 3:1 luminance step (WCAG 1.4.1).
    const ITEM = (style) => `<ul><li class="row is-selected" style="${style}">North gate</li><li class="row">South dock</li></ul>`;
    assert.match(of(await rules(ITEM('background:#eef')), 'a11y.state-cues'), /is selected\/current, but nothing but colour tells it from <li.row>/);
    assert.equal(of(await rules(ITEM('background:#eef;box-shadow:inset 3px 0 0 #58f')), 'a11y.state-cues'), '');
    assert.equal(of(await rules(ITEM('font-weight:700')), 'a11y.state-cues'), '');
    assert.equal(of(await rules('<ul><li aria-current="true" class="row"><span class="icon" aria-hidden="true">✓</span>North gate</li><li class="row">South dock</li></ul>'), 'a11y.state-cues'), '');
    assert.equal(of(await rules(ITEM('background:#000;color:#fff')), 'a11y.state-cues'), '');
    // Alone in its row (a crumb's link, an evidence-set control): the same control in a sibling row is the peer.
    const ROWS = (style) => `<ol><li><a href="/a" aria-current="page" style="${style}">Search</a></li><li><a href="/b">Review</a></li></ol>`;
    let r = await rules(ROWS('color:#88f'));
    assert.match(of(r, 'a11y.state-cues'), /<a> "Search" is selected\/current, but nothing but colour tells it from <a> "Review"/);
    r = await rules(ROWS('font-weight:700'));
    assert.equal(of(r, 'a11y.state-cues'), '');
    assert.equal(r.measured.stateCues?.unjudged ?? 0, 0);
  });

  it('requires dashed invalid geometry, text in every badge, distinct tick shapes per marker kind, and a handle told by its mark', async () => {
    assert.match(of(await rules('<svg><g class="scene-zone is-invalid"><polygon points="0,0 10,0 10,10" style="stroke:#fa0"/></g></svg>'), 'a11y.state-cues'), /invalid geometry told by its stroke colour alone/);
    assert.equal(of(await rules('<svg><g class="scene-zone is-invalid"><polygon points="0,0 10,0 10,10" style="stroke:#fa0;stroke-dasharray:6 4"/></g></svg>'), 'a11y.state-cues'), '');
    assert.match(of(await rules('<span class="badge badge--ok" style="display:inline-block;width:40px;height:16px"></span>'), 'a11y.state-cues'), /status badge with no text/);
    assert.match(of(await rules('<span class="badge badge--ok">Ready</span><span class="badge badge--err">Ready</span>'), 'a11y.state-cues'), /two status badges read "Ready" with different tones/);
    const TICKS = (skew) => `<ul><li class="evidence-timeline__marker" data-kind="zone-entry"><span class="evidence-timeline__marker-tick" style="display:block;height:10px;${skew}"></span></li><li class="evidence-timeline__marker" data-kind="crossing"><span class="evidence-timeline__marker-tick" style="display:block;height:10px"></span></li></ul>`;
    assert.match(of(await rules(TICKS('')), 'a11y.state-cues'), /timeline marker kinds .* share one tick shape/);
    assert.equal(of(await rules(TICKS('transform:skewX(-20deg)')), 'a11y.state-cues'), '');
    // The product's handle: a transparent hit circle first, then the mark;
    // the state is told by the mark, whichever child it is.
    const HANDLES = (fill, stroke) => `<svg><g class="scene-handle is-selected"><circle class="scene-handle__hit" r="12" style="fill:transparent"/><circle class="scene-handle__mark" r="3.5" style="fill:${fill};stroke:${stroke}"/></g><g class="scene-handle"><circle class="scene-handle__hit" r="12" style="fill:transparent"/><circle class="scene-handle__mark" r="3.5" style="fill:#111;stroke:#58f"/></g></svg>`;
    assert.equal(of(await rules(HANDLES('#fff', '#58f')), 'a11y.state-cues'), '');
    assert.equal(of(await rules(HANDLES('#131313', '#fff')), 'a11y.state-cues'), '');
    assert.match(of(await rules(HANDLES('#131313', '#59f')), 'a11y.state-cues'), /nothing but colour tells it/);
  });
});

describe('a11y.focus-not-obscured and a11y.spatial-twin', unitBlock(), () => {
  it('fails a focused control under a fixed band at its middle, and passes one in the clear', async () => {
    const BAND = (top) => `<main style="height:2000px"><button style="position:absolute;top:${top}px;left:10px;width:120px;height:40px">Detail</button></main><div style="position:fixed;top:0;left:0;right:0;height:60px;background:#000"></div>`;
    let r = await rules(BAND(10));
    assert.match(of(r, 'a11y.focus-not-obscured'), /<button> "Detail", focused, is under <div> \(a fixed layer\) at its middle/);
    r = await rules(BAND(300));
    assert.equal(of(r, 'a11y.focus-not-obscured'), '');
    assert.ok(r.evaluated.includes('a11y.focus-not-obscured'));
  });

  it('holds the object list to the canvas: every drawn object, its state, its actual coordinates; every timeline entry named', async () => {
    const CANVAS = '<svg><g class="scene-zone" data-object-key="z1" data-points="0.100000,0.100000 0.500000,0.100000 0.500000,0.600000"><polygon points="10,10 50,10 50,60"/></g><g class="scene-line" data-object-key="l1" data-endpoints="0.100000,0.500000 0.900000,0.500000"><polygon class="hit" points="0,0 1,0 1,1"/><line class="scene-line__segment" x1="10" y1="50" x2="90" y2="50"/></g></svg>';
    const ROWS = (zonePoints, lineEnds) => `<ul aria-label="Zones"><li data-object-key="z1" data-object-kind="zone"><button aria-current="true">Gate, zone, 3 vertices, enabled</button><details class="scene-navigator__coordinates"><summary>Coordinates</summary><ol class="scene-navigator__points">${zonePoints}</ol></details></li></ul>
      <ul aria-label="Trip lines"><li data-object-key="l1" data-object-kind="line"><button>Door, directional, enabled</button>${lineEnds}</li></ul>`;
    const OK = ROWS('<li>0.100000, 0.100000</li><li>0.500000, 0.100000</li><li>0.500000, 0.600000</li>', '<span class="scene-navigator__endpoints">(0.100000, 0.500000) → (0.900000, 0.500000)</span>');
    let r = await rules(CANVAS + OK);
    assert.equal(of(r, 'a11y.spatial-twin'), '');
    assert.ok(r.evaluated.includes('a11y.spatial-twin'));
    r = await rules(CANVAS + OK.replace('<li data-object-key="z1"', '<li data-object-key="zX"'));
    assert.match(of(r, 'a11y.spatial-twin'), /<g.scene-zone> \(z1\) is drawn with no entry in the object list/);
    r = await rules(CANVAS + ROWS('', '<span class="scene-navigator__endpoints">(0.1, 0.5) → (0.9, 0.5)</span>'));
    assert.match(of(r, 'a11y.spatial-twin'), /the entry for z1 names no coordinates/);
    r = await rules(CANVAS + ROWS('<li>0.100000, 0.100000</li><li>0.500000, 0.100000</li>', '<span class="scene-navigator__endpoints">(0.100000, 0.500000) → (0.900000, 0.500000)</span>'));
    assert.match(of(r, 'a11y.spatial-twin'), /lists "0.100000,0.100000 0.500000,0.100000" where the drawing holds "0.100000,0.100000 0.500000,0.100000 0.500000,0.600000"/);
    // The right count of the wrong vertices, and a line's wrong endpoint, are findings; a drawing that states no coordinates cannot be held to.
    r = await rules(CANVAS + ROWS('<li>0.100000, 0.100000</li><li>0.500000, 0.100000</li><li>0.500000, 0.700000</li>', '<span class="scene-navigator__endpoints">(0.100000, 0.500000) → (0.900000, 0.400000)</span>'));
    assert.match(of(r, 'a11y.spatial-twin'), /lists "[^"]*0.500000,0.700000" where the drawing holds/);
    assert.match(of(r, 'a11y.spatial-twin'), /names endpoints "0.100000 0.500000 0.900000 0.400000" where the drawing holds "0.100000,0.500000 0.900000,0.500000"/);
    r = await rules(CANVAS.replace(/ data-points="[^"]*"/, '') + OK);
    assert.match(of(r, 'a11y.spatial-twin'), /does not state its stored coordinates \(data-points\)/);
    r = await rules(CANVAS + ROWS('<li>0.1, 0.1</li><li>0.5, 0.1</li><li>0.5, 0.6</li>', ''));
    assert.match(of(r, 'a11y.spatial-twin'), /the entry for l1 does not name both endpoints/);
    r = await rules('<ul><li class="evidence-timeline__interval"><button>Zone A, 00:01 to 00:04</button></li><li class="evidence-timeline__marker"><span>no control</span></li></ul>');
    assert.match(of(r, 'a11y.spatial-twin'), /is a timeline marker with no control/);
  });
});

describe('the probes: hover content and shortcuts in text entry', unitBlock(), () => {
  const TIP = (behaviour) => `<style>.tooltip-anchor{position:relative;display:inline-flex}.tooltip{position:absolute;top:100%;left:0;background:#000;color:#fff;padding:4px;white-space:nowrap}.tooltip[hidden]{display:none}</style>
    <main><span class="tooltip-anchor"><button aria-describedby="tip1">Save</button><span class="tooltip" role="tooltip" id="tip1" hidden>Save (S)</span></span></main>
    <script>(() => { const a = document.querySelector('.tooltip-anchor'); const trigger = a.querySelector('button'); const tip = a.querySelector('.tooltip'); let hovered = false, focused = false; const sync = () => { tip.hidden = !(hovered || focused); };
      ${behaviour}
      a.addEventListener('focusin', () => { focused = true; sync(); ${behaviour.includes('FADE') ? 'setTimeout(() => { focused = false; sync(); }, 60);' : ''} });
      a.addEventListener('focusout', (e) => { if (!a.contains(e.relatedTarget)) { focused = false; sync(); } });
      ${behaviour.includes('NOESC') ? '' : "a.addEventListener('keydown', (e) => { if (e.key === 'Escape') { hovered = false; focused = false; sync(); } });"}
    })();</script>`;
  const GOOD = "a.addEventListener('pointerenter', () => { hovered = true; sync(); }); a.addEventListener('pointerleave', () => { hovered = false; sync(); });";
  const TRIGGER_ONLY = "trigger.addEventListener('pointerenter', () => { hovered = true; sync(); }); trigger.addEventListener('pointerleave', () => { hovered = false; sync(); });";

  it('passes the product\'s pattern and fails one that is not hoverable, ignores Escape, or fades while focus stays', async () => {
    await lane.page(TOKENS + TIP(GOOD));
    let r = await probeHoverContent(lane.browser);
    assert.deepEqual(r.findings, []);
    assert.equal(r.judged, 1);
    await lane.page(TOKENS + TIP(TRIGGER_ONLY));
    r = await probeHoverContent(lane.browser);
    assert.match(r.findings.join('\n'), /hidden when the pointer moved onto it \(not hoverable\)/);
    await lane.page(TOKENS + TIP(GOOD + ' /* NOESC */'));
    r = await probeHoverContent(lane.browser);
    assert.match(r.findings.join('\n'), /Escape did not dismiss it/);
    await lane.page(TOKENS + TIP(GOOD + ' /* FADE */'));
    r = await probeHoverContent(lane.browser);
    assert.match(r.findings.join('\n'), /shown on focus, then hidden while focus stayed/);
  });

  it('types "?" into the first field and judges what a shortcut did', async () => {
    const PAGE = (handler) => `<main><input aria-label="Filter"><button>x</button></main><script>document.addEventListener('keydown', (e) => { ${handler} });</script>`;
    await lane.page(TOKENS + PAGE("if (e.key === '?' && !(e.target instanceof HTMLInputElement)) { const d = document.createElement('div'); d.setAttribute('role', 'dialog'); d.textContent = 'sheet'; document.body.appendChild(d); }"));
    let r = await probeShortcuts(lane.browser);
    assert.deepEqual(r.findings, []);
    assert.deepEqual(r.evaluated, ['a11y.shortcuts-in-text-entry']);
    await lane.page(TOKENS + PAGE("if (e.key === '?') { const d = document.createElement('div'); d.setAttribute('role', 'dialog'); d.textContent = 'sheet'; document.body.appendChild(d); }"));
    r = await probeShortcuts(lane.browser);
    assert.match(r.findings.map((f) => f.message).join('\n'), /the "\?" shortcut opened an overlay while <input> "Filter" was being typed in/);
    await lane.page(TOKENS + PAGE("if (e.key === '?') e.preventDefault();"));
    r = await probeShortcuts(lane.browser);
    assert.match(r.findings.map((f) => f.message).join('\n'), /did not reach it/);
  });
});

describe('a11y.text-spacing: the lane, planned and proven', unitBlock(), () => {
  it('plans one case per distinct composition the state is swept at, plus its probe widths, and only in the lane on request', () => {
    const plan = (extra = {}) => planCases({ states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, zoom: ZOOM, textSpacing: TEXT_SPACING_CONDITION, ...extra });
    const videos = plan({ onlyStates: ['videos'] }).cases.filter((c) => c.viewport.textSpacing).map((c) => c.viewport.label);
    assert.deepEqual(videos, ['1366x768@spacing', '1024x768@spacing', '768x1024@spacing', '390x844@spacing']);
    const probed = STATES.find((s) => (s.probeWidths ?? []).includes(1600));
    const labels = plan({ onlyStates: [probed.name] }).cases.filter((c) => c.viewport.textSpacing).map((c) => c.viewport.label);
    assert.ok(labels.includes('1600x900@spacing'), labels.join(','));
    const only = plan({ onlyTextSpacing: 'only' }).cases;
    assert.ok(only.length > 800 && only.every((c) => c.viewport.textSpacing && !c.viewport.zoom));
    const none = plan({ onlyTextSpacing: 'none' }).cases;
    assert.ok(none.length && none.every((c) => !c.viewport.textSpacing));
    // The workbench variants are not swept at Tier C: no 390 case for them.
    const wb = plan({ onlyStates: ['scene-editor-object-selected'] }).cases.filter((c) => c.viewport.textSpacing).map((c) => c.viewport.label);
    assert.deepEqual(wb, ['1366x768@spacing', '1024x768@spacing', '768x1024@spacing']);
  });

  it('reads the overrides from computed style and faults a plain page; a planned case missing or not in force is a coverage fault', async () => {
    await lane.page(TOKENS + '<main><p>Videos</p></main>');
    let env = await lane.browser.evaluate(toExpression(a11yTextSpacingEnvironment));
    assert.ok(env.problems.length >= 3, env.problems.join('; '));
    await lane.page(`<style>${TEXT_SPACING_CSS}</style>` + TOKENS + '<main><p>Videos</p></main>');
    env = await lane.browser.evaluate(toExpression(a11yTextSpacingEnvironment));
    assert.deepEqual(env.problems, []);
    assert.ok(env.lineHeight >= 1.5 && env.letterSpacing >= 0.12 && env.wordSpacing >= 0.16 && env.paragraphSpacing >= 2);
    const keys = ['videos@1366x768#1', 'videos@1366x768@spacing#1', 'videos@390x844@spacing#1'];
    const results = [{ state: 'videos', viewport: '1366x768@spacing', kind: 'text-spacing', attempt: 1, valid: true, reached: true, textSpacing: { inForce: true } }];
    assert.deepEqual(textSpacingCoverageFaults(results, keys), ['a11y.text-spacing: videos @ 390x844@spacing has no valid capture']);
    results[0].textSpacing.inForce = false;
    assert.match(textSpacingCoverageFaults(results, keys)[0], /ran without the overrides proven in force/);
    // sweepChecks carries it on the full sweep, by the planned keys.
    const ledger = createLedger(RULES);
    const { faults } = sweepChecks({ results, cases: keys.map((key) => ({ key })), errored: [], ledger, surfaces: [], fullSweep: true, plannedKeys: keys });
    assert.ok(faults.some((f) => /a11y.text-spacing: videos @ 1366x768@spacing ran without the overrides/.test(f)), faults.join('\n'));
  });
});

describe('the text-spacing lane, end to end', () => {
  const e2e = e2eIt(it);
  const RUN = fileURLToPath(new URL('../run.mjs', import.meta.url));
  const REGISTERED = new URL('../states.mjs', import.meta.url).href;
  let dir;
  before(() => { dir = mkdtempSync(join(tmpdir(), 'mavi-vqa-spacing-')); });
  after(() => { rmSync(dir, { recursive: true, force: true }); });
  const run = (name, body, args) => {
    const module = join(dir, `${name}.mjs`);
    writeFileSync(module, `export * from ${JSON.stringify(REGISTERED)};\nimport { STATES as REGISTERED } from ${JSON.stringify(REGISTERED)};\n${body}\n`);
    const out = join(dir, name);
    const result = spawnSync(process.execPath, [RUN, '--workers', '1', ...args], { env: { ...process.env, MAVI_VQA_STATES_MODULE: module, MAVI_VQA_OUT: out }, encoding: 'utf8', timeout: 240_000 });
    assert.equal(result.error, undefined, 'the run hung');
    return { status: result.status, output: result.stdout + result.stderr, results: JSON.parse(readFileSync(join(out, 'results.json'), 'utf8')) };
  };
  const VIDEOS = (prepare) => `export const STATES = REGISTERED.filter((s) => s.name === "videos").map(({ zoomTransitions, ...s }) => ({ ...s, prepare: ${JSON.stringify(prepare)} }));`;

  e2e('runs the videos state with the overrides in force at its four compositions, each judged by the tier\'s rules and the lane\'s', () => {
    const { status, output, results } = run('lane', VIDEOS('(() => true)()'), ['--states', 'videos', '--text-spacing', 'only', '--widths', '1366,390']);
    assert.equal(status, 0, output);
    const cases = results.cases.filter((c) => c.kind === 'text-spacing');
    assert.deepEqual(cases.map((c) => c.viewport), ['1366x768@spacing', '390x844@spacing']);
    for (const c of cases) {
      assert.ok(c.textSpacing.inForce, JSON.stringify(c.textSpacing));
      assert.ok(c.textSpacing.lineHeight >= 1.5 && c.textSpacing.letterSpacing >= 0.12);
    }
    assert.equal(results.coverage['a11y.text-spacing'].A.blockingEvaluated, 1);
    assert.equal(results.coverage['a11y.text-spacing'].C.blockingEvaluated, 1);
    assert.ok(results.coverage['text.overflow'].A.evaluated >= 1 && results.coverage['a11y.target-size'].C.evaluated >= 1);
  });

  e2e('catches content that fits at normal spacing and clips only under the overrides, and a spaced control pushed under a fixed band', () => {
    // A sentence in a box sized to its width at normal metrics (measured on a
    // clone that overrides the spacing with !important): under the overrides
    // the letter spacing widens it past the box, which cuts it off.
    const CLIP = `(() => {
      const p = document.createElement('p'); p.textContent = 'Latest run per video — earlier runs are not listed here.'; p.style.cssText = 'white-space:nowrap;overflow:hidden;margin:8px';
      const probe = p.cloneNode(true); probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap';
      for (const prop of [['letter-spacing', 'normal'], ['word-spacing', 'normal'], ['line-height', '1.45']]) probe.style.setProperty(prop[0], prop[1], 'important');
      document.body.appendChild(probe); const width = Math.ceil(probe.getBoundingClientRect().width) + 2; probe.remove();
      p.style.width = width + 'px'; document.querySelector('main').prepend(p); return true; })()`;
    let { status, output, results } = run('clip', VIDEOS(CLIP), ['--states', 'videos', '--text-spacing', 'only', '--widths', '1366']);
    assert.equal(status, 1, output);
    assert.ok(results.findingsList.some((f) => f.rule === 'text.overflow' && f.viewport === '1366x768@spacing' && f.severity === 'blocking'), JSON.stringify(results.findingsList.map((f) => [f.rule, f.message]).slice(0, 5)));
    ({ status, output, results } = run('clip-none', VIDEOS(CLIP), ['--states', 'videos', '--text-spacing', 'none', '--zoom', 'none', '--widths', '1366']));
    assert.equal(status, 0, output);
    assert.ok(!results.findingsList.some((f) => f.rule === 'text.overflow'));
    // A control after a paragraph, and a fixed band at the bottom whose top
    // edge sits just under where the control ends at normal metrics: the
    // paragraph spacing of the overrides pushes the control under the band.
    const BAND = `(() => {
      const wrap = document.createElement('div'); wrap.id = 'vqa-band-fixture';
      const p = document.createElement('p'); p.textContent = 'Earlier runs are not listed here.'; const b = document.createElement('button'); b.type = 'button'; b.textContent = 'Fixture action';
      wrap.append(p, b); document.querySelector('main').prepend(wrap);
      const probe = wrap.cloneNode(true); probe.id = ''; probe.style.cssText = 'position:absolute;left:0;top:0;visibility:hidden;width:' + wrap.offsetWidth + 'px';
      for (const el of [probe, ...probe.querySelectorAll('*')]) for (const prop of [['letter-spacing', 'normal'], ['word-spacing', 'normal'], ['line-height', '1.45'], ['margin-bottom', '0']]) el.style.setProperty(prop[0], prop[1], 'important');
      document.body.appendChild(probe); const normalBottom = probe.querySelector('button').offsetTop + probe.querySelector('button').offsetHeight; probe.remove();
      const top = wrap.getBoundingClientRect().top + normalBottom + 2;
      const band = document.createElement('div'); band.style.cssText = 'position:fixed;left:0;right:0;bottom:0;background:#000;z-index:100;top:' + top + 'px;height:auto;max-height:200px';
      document.body.appendChild(band); return true; })()`;
    ({ status, output, results } = run('band', VIDEOS(BAND), ['--states', 'videos', '--text-spacing', 'only', '--widths', '1366']));
    assert.ok(results.cases.every((c) => c.valid), output);
    assert.ok(results.findingsList.some((f) => f.rule === 'a11y.focus-not-obscured' && f.viewport === '1366x768@spacing' && /Fixture action/.test(f.message)), JSON.stringify(results.findingsList.map((f) => [f.rule, f.message]).slice(0, 8)));
    ({ status, output, results } = run('band-none', VIDEOS(BAND), ['--states', 'videos', '--text-spacing', 'none', '--zoom', 'none', '--widths', '1366']));
    assert.ok(results.cases.every((c) => c.valid), output);
    assert.ok(!results.findingsList.some((f) => f.rule === 'a11y.focus-not-obscured' && /Fixture action/.test(f.message)), JSON.stringify(results.findingsList.map((f) => [f.rule, f.message]).slice(0, 8)));
  });
});
