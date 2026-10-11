/**
 * X2 (§23, plan §5.3): the six operator journeys, completed keyboard-only in
 * real Chromium and recorded step by step.
 *
 *   node tools/web-visual-qa/journeys.mjs [--journeys a,b] [--viewports 1366x768] [--workers 3] [--shard i/n]
 *   node tools/web-visual-qa/journeys.mjs --aggregate --out DIR shard-0/journeys.json shard-1/journeys.json …
 *
 * A journey loads its declared starting route once, with its fixtures in
 * place, and from then on the application carries the operator: every action
 * is a key pressed through the browser's input pipeline (cdp.mjs `press`),
 * every target is found by Tab and named by Chromium's accessibility tree,
 * every step ends on an observable checkpoint, and the journey ends on a
 * terminal one. The runner never clicks, focuses, navigates, dispatches
 * events or writes application state: the operator object a journey is given
 * offers keys and observations only, the page records any pointer input,
 * scripted click or synthetic key event and any document load after the
 * start, and a test reads the registry's source for anything else
 * (test/journeys.test.mjs).
 *
 * The one place the operator cannot reach is the operating system's file
 * chooser (Journey 1): the browser is asked to report it rather than open it
 * (Page.setInterceptFileChooserDialog), the operator opens it with a key on the
 * focused file input, and only then is the fixture file supplied — to the node
 * the browser itself names as having opened the chooser.
 *
 * Exit status: 0 every planned journey passed; 1 a journey failed; 2 the
 * harness itself failed (a missing or duplicated execution, a fault).
 */
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { cpus } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { toExpression, zoomClipChain, zoomDescribe, zoomVisibility, zoomVisibleRect } from './assertions.mjs';
import { launch } from './cdp.mjs';
import { HarnessError } from './engine.mjs';
import { ensureFootage } from './footage.mjs';
import { JOURNEY_CONDITION } from './manifest.mjs';
import { startServer } from './server.mjs';
import { OBSERVERS, TRANSIENT } from './settle.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

/** A journey that did not complete: the step it stopped at, and why. */
export class JourneyFailure extends Error {}

// --- Planning ---------------------------------------------------------------------

/**
 * The executions: every journey at every frozen workstation composition
 * (JOURNEY_CONDITION). Tier C carries no workflow acceptance (§25, the
 * programme's non-claim): a Tier C viewport is refused, never run as a claim.
 */
export function planJourneys({ journeys, viewports = JOURNEY_CONDITION.viewports, onlyJourneys = null, onlyViewports = null }) {
  const ids = new Set();
  for (const journey of journeys) {
    if (ids.has(journey.id)) throw new HarnessError(`journey ${journey.id} is registered twice`);
    ids.add(journey.id);
  }
  for (const viewport of viewports) {
    if (viewport.tier === 'C') throw new HarnessError(`journeys are not run at ${viewport.width}x${viewport.height} (Tier C): ${JOURNEY_CONDITION.tierC}`);
  }
  const plan = [];
  for (const journey of journeys) {
    if (onlyJourneys && !onlyJourneys.includes(journey.id)) continue;
    for (const viewport of viewports) {
      const label = `${viewport.width}x${viewport.height}`;
      if (onlyViewports && !onlyViewports.includes(label)) continue;
      plan.push({ key: `${journey.id}@${label}`, journey, viewport: { ...viewport, label } });
    }
  }
  return plan;
}

/** A deterministic shard of the plan: the executions whose index is i modulo n. */
export function partitionJourneys(plan, shard) {
  if (!shard) return plan;
  const selected = plan.filter((_, i) => i % shard.count === shard.index);
  if (!selected.length) throw new HarnessError(`shard ${shard.index}/${shard.count} selects no journey of ${plan.length}`);
  return selected;
}

/**
 * The aggregate's verdict over every shard: one head, one plan, every planned
 * execution run exactly once and passed. A missing or duplicated execution is
 * a harness fault; a failed journey is a failure.
 */
export function journeyAggregate(shards) {
  const faults = [];
  if (!shards.length) return { faults: ['no journey results to aggregate'], executions: [], failed: [], planned: [] };
  const [first] = shards;
  for (const s of shards.slice(1)) {
    if (s.head !== first.head) faults.push(`${s.file}: head ${s.head} differs from ${first.file}'s ${first.head}`);
    if (JSON.stringify(s.planned) !== JSON.stringify(first.planned)) faults.push(`${s.file}: its plan differs from ${first.file}'s`);
  }
  const executions = shards.flatMap((s) => s.executions.map((e) => ({ ...e, shardFile: s.file })));
  const seen = new Map();
  for (const e of executions) seen.set(e.key, (seen.get(e.key) ?? 0) + 1);
  for (const key of first.planned) {
    const n = seen.get(key) ?? 0;
    if (n === 0) faults.push(`a11y.keyboard-journeys: ${key} was planned and never ran`);
    if (n > 1) faults.push(`a11y.keyboard-journeys: ${key} ran ${n} times`);
  }
  for (const key of seen.keys()) if (!first.planned.includes(key)) faults.push(`a11y.keyboard-journeys: ${key} ran but was not planned`);
  for (const e of executions) if (e.tier === 'C') faults.push(`a11y.keyboard-journeys: ${e.key} ran at Tier C, where no workflow acceptance is claimed`);
  for (const s of shards) faults.push(...(s.harnessErrors ?? []).map((h) => `${s.file}: ${h}`));
  const failed = executions.filter((e) => !e.passed);
  return { faults, executions, failed, planned: first.planned };
}

// --- The page's side --------------------------------------------------------------

/**
 * Installed before every document: what the journey's guards read. Trusted
 * pointer and touch input (none is ever sent; one means a pointer reached the
 * page), and scripted clicks and key events (the product makes none; one means
 * something other than the input pipeline acted). A keyboard-activated button
 * still fires its trusted `click` — that is keyboard input, and is not counted.
 * Each document numbers itself, so a load after the journey's start (a direct
 * navigation) shows as a new number.
 */
export const JOURNEY_GUARD = `(() => {
  const guard = window.__vqaJourneyGuard = { pointer: [], synthetic: [] };
  try { const n = Number(sessionStorage.getItem('__vqaDocuments') || 0) + 1; sessionStorage.setItem('__vqaDocuments', String(n)); guard.document = n; } catch { guard.document = -1; }
  const name = (t) => t && t.nodeType === 1 ? (t.tagName.toLowerCase() + (t.id ? '#' + t.id : '') + (t.getAttribute('aria-label') ? '[' + t.getAttribute('aria-label') + ']' : '')) : String(t);
  for (const type of ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'touchstart', 'touchend', 'wheel', 'contextmenu', 'dblclick']) {
    window.addEventListener(type, (e) => { if (e.isTrusted) guard.pointer.push(type + ' on ' + name(e.target)); }, true);
  }
  window.addEventListener('click', (e) => { if (!e.isTrusted) guard.synthetic.push('scripted click on ' + name(e.target)); }, true);
  for (const type of ['keydown', 'keyup', 'keypress', 'input', 'change']) {
    window.addEventListener(type, (e) => { if (!e.isTrusted && (type.startsWith('key'))) guard.synthetic.push('scripted ' + type + ' on ' + name(e.target)); }, true);
  }
})();`;

/**
 * Where focus is, and whether it is somewhere an operator can act from: not
 * the document itself, rendered, seen, not under another layer at its
 * middle, and inside the open modal overlay when there is one. The focused
 * element is tagged for its accessible name from the accessibility tree.
 */
export function journeyFocusState() {
  for (const el of Array.from(document.querySelectorAll('[data-vqa-journey-focus]'))) el.removeAttribute('data-vqa-journey-focus');
  const el = document.activeElement;
  const route = location.pathname + location.search;
  if (!el || el === document.body || el === document.documentElement) return { route, description: '<body>', onBody: true, problems: ['focus is on the document, not on a control (lost)'] };
  el.setAttribute('data-vqa-journey-focus', '');
  const problems = [];
  const v = zoomVisibility(el);
  if (v.hidden) problems.push(zoomDescribe(el) + ' has focus but is not rendered (' + v.hidden + ')');
  else if (v.seen.width < 1 || v.seen.height < 1) problems.push(zoomDescribe(el) + ' has focus but no part of it is in view');
  else {
    const x = (v.seen.left + v.seen.right) / 2; const y = (v.seen.top + v.seen.bottom) / 2;
    const hit = document.elementFromPoint(x, y);
    const label = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
    if (hit && !(hit === el || el.contains(hit) || hit.contains(el) || (label && label.contains(hit)))) problems.push(zoomDescribe(el) + ' has focus but ' + zoomDescribe(hit) + ' is over its middle');
  }
  const modal = Array.from(document.querySelectorAll('[aria-modal="true"]')).find((m) => !zoomVisibility(m).hidden);
  if (modal && !modal.contains(el)) problems.push('a modal overlay is open and focus is outside it, on ' + zoomDescribe(el));
  if (el.closest('[inert]')) problems.push(zoomDescribe(el) + ' has focus inside an inert region');
  // The row the control acts on (a Ledger row, a list item, a result), by its
  // text: row actions share names ("Detail"), the row says which.
  const rowEl = el.closest('tr, li, [role="row"], [role="listitem"]');
  const row = rowEl ? (rowEl.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240) : '';
  return {
    route, row, description: zoomDescribe(el), tag: el.tagName.toLowerCase(), type: el.getAttribute('type'),
    inModal: Boolean(modal && modal.contains(el)), modalOpen: Boolean(modal), problems,
  };
}
journeyFocusState.helpers = [zoomDescribe, zoomClipChain, zoomVisibleRect, zoomVisibility];

// --- The operator ------------------------------------------------------------------

const CODES = { Enter: 'Enter', Tab: 'Tab', Escape: 'Escape', ' ': 'Space', ArrowUp: 'ArrowUp', ArrowDown: 'ArrowDown', ArrowLeft: 'ArrowLeft', ArrowRight: 'ArrowRight', Home: 'Home', End: 'End', Delete: 'Delete', '?': 'Slash', '/': 'Slash' };
const codeOf = (key) => CODES[key] ?? (/^[0-9]$/.test(key) ? 'Digit' + key : /^[a-z]$/i.test(key) ? 'Key' + key.toUpperCase() : key);
const tick = (ms) => new Promise((done) => setTimeout(done, ms));

/**
 * The operator a journey is given: keys and observations, nothing else. Every
 * key goes through the input pipeline; every wait polls a condition the page
 * states (no fixed sleep); every action is recorded with the focus and route
 * before and after; focus is judged after every action.
 */
export function createOperator({ browser, server, record, journeyId, viewport, documentIndex, limits = {} }) {
  const timeout = limits.timeoutMs ?? 12_000;
  const steps = [];
  let terminal = null;
  const step = (entry) => {
    const s = { journey: journeyId, viewport: viewport.label, step: steps.length + 1, ...entry };
    steps.push(s);
    record?.(s);
    return s;
  };
  const fail = (entry, why) => {
    step({ ...entry, observed: why, pass: false });
    throw new JourneyFailure(`${journeyId} @ ${viewport.label} step ${steps.length} (${entry.action}${entry.target ? ' ' + JSON.stringify(entry.target) : ''}): ${why}`);
  };
  const focus = async () => {
    const state = await browser.evaluate(toExpression(journeyFocusState));
    if (!state.onBody) {
      const [ax] = await browser.axNames('[data-vqa-journey-focus]');
      state.name = ax?.name ?? ''; state.role = ax?.role ?? null;
    }
    return state;
  };
  const guards = async () => {
    const g = await browser.evaluate('(() => { const g = window.__vqaJourneyGuard || {}; return { pointer: (g.pointer || []).slice(), synthetic: (g.synthetic || []).slice(), document: g.document }; })()');
    const problems = [];
    if (g.document !== documentIndex) problems.push(`the document was reloaded or replaced after the journey started (document ${g.document}, started on ${documentIndex}): a direct navigation`);
    if (g.pointer.length) problems.push('pointer input reached the page: ' + g.pointer.join(', '));
    if (g.synthetic.length) problems.push('something other than the input pipeline acted: ' + g.synthetic.join(', '));
    return problems;
  };
  // The page has finished reacting: no request in flight, no loading
  // placeholder, twice in a row (each poll a condition, never a fixed wait).
  const quiet = async () => {
    const started = Date.now();
    let calm = 0;
    while (Date.now() - started < timeout) {
      const busy = server.network().inflight > 0 || await browser.evaluate(`Boolean(document.querySelector(${JSON.stringify(TRANSIENT)}))`);
      calm = busy ? 0 : calm + 1;
      if (calm >= 2) return true;
      await tick(40);
    }
    return false;
  };
  const named = (state, target) => {
    if (!state || state.onBody) return false;
    const nameOk = target.name === undefined || (target.name instanceof RegExp ? target.name.test(state.name) : state.name === target.name);
    const roleOk = target.role === undefined || state.role === target.role;
    const rowOk = target.row === undefined || (target.row instanceof RegExp ? target.row.test(state.row ?? '') : (state.row ?? '').includes(target.row));
    return nameOk && roleOk && rowOk;
  };
  const judge = async (entry, { expectFocus } = {}) => {
    const problems = await guards();
    if (problems.length) fail(entry, problems.join('; '));
    const after = await focus();
    entry.focusAfter = summary(after);
    entry.routeAfter = after.route;
    if (after.problems.length) fail(entry, after.problems.join('; '));
    if (expectFocus && !named(after, expectFocus)) fail(entry, `focus landed on ${summary(after)}, not on ${describeTarget(expectFocus)}`);
    return after;
  };

  const op = {
    /** One key, through the input pipeline. */
    async press(key, { shift = false, expectFocus, note } = {}) {
      const before = await focus();
      const entry = { action: 'press', key: (shift ? 'Shift+' : '') + (key === ' ' ? 'Space' : key), focusBefore: summary(before), routeBefore: before.route, note };
      await browser.press(key, codeOf(key), { shift });
      await quiet();
      await judge(entry, { expectFocus });
      step({ ...entry, observed: 'key delivered; focus valid', pass: true });
    },
    /** Characters, one key each. */
    async type(text, { note } = {}) {
      const before = await focus();
      const entry = { action: 'type', key: JSON.stringify(text), focusBefore: summary(before), routeBefore: before.route, note };
      for (const ch of text) await browser.press(ch, codeOf(ch));
      await quiet();
      await judge(entry);
      step({ ...entry, observed: 'typed; focus valid', pass: true });
    },
    /**
     * Tab (or Shift+Tab) until focus is on the named control — by its
     * accessible name and role — within a strict maximum, every stop recorded.
     * Never focuses the target itself.
     */
    async tabTo(target, { max = 60, reverse = false, note } = {}) {
      const before = await focus();
      const entry = { action: 'tab-to', key: reverse ? 'Shift+Tab' : 'Tab', target: describeTarget(target), focusBefore: summary(before), routeBefore: before.route, note, stops: [] };
      if (named(before, target)) {
        await judge(entry);
        step({ ...entry, observed: 'already focused', pass: true });
        return;
      }
      for (let i = 0; i < max; i += 1) {
        await browser.press('Tab', 'Tab', { shift: reverse });
        const state = await focus();
        entry.stops.push(summary(state));
        if (named(state, target)) {
          await quiet();
          await judge(entry, { expectFocus: target });
          step({ ...entry, observed: `reached in ${i + 1} press(es)`, pass: true });
          return;
        }
      }
      entry.focusAfter = entry.stops[entry.stops.length - 1];
      fail(entry, `${describeTarget(target)} was not reached within ${max} ${reverse ? 'Shift+Tab' : 'Tab'} presses`);
    },
    /** A condition the page must reach, polled until it does or the bound passes. */
    async until(description, expression, { timeoutMs = timeout, judgeFocus = true } = {}) {
      const started = Date.now();
      let last;
      while (Date.now() - started < timeoutMs) {
        last = await browser.evaluate(`(() => { try { return ${expression}; } catch (e) { return false; } })()`);
        if (last) break;
        await tick(50);
      }
      const entry = { action: 'checkpoint', expect: description };
      if (!last) fail(entry, `not reached within ${timeoutMs}ms`);
      await quiet();
      // Focus is judged from the operator's first action on: a page just
      // loaded has focus on the document, as every page does.
      if (judgeFocus) await judge(entry);
      else { const problems = await guards(); if (problems.length) fail(entry, problems.join('; ')); }
      step({ ...entry, observed: typeof last === 'string' ? last : 'reached', routeAfter: entry.routeAfter ?? null, pass: true });
      return last;
    },
    /** The route (path and query, matched by a regular expression), as a checkpoint. */
    async route(description, pattern) {
      if (!(pattern instanceof RegExp)) throw new HarnessError('op.route takes a regular expression');
      return op.until(description, `${pattern.toString()}.test(location.pathname + location.search) && (location.pathname + location.search)`);
    },
    /** The operator's action reached the backend: the request is in the server's log. */
    async requested(description, method, pathPattern, { query } = {}) {
      const started = Date.now();
      let found = null;
      while (Date.now() - started < timeout && !found) {
        found = server.requests().find((r) => r.method === method && pathPattern.test(r.path) && (!query || Object.entries(query).every(([k, v]) => new URLSearchParams(r.search).get(k) === String(v)))) ?? null;
        if (!found) await tick(50);
      }
      const entry = { action: 'checkpoint', expect: description };
      if (!found) fail(entry, `no ${method} ${pathPattern} request was made`);
      step({ ...entry, observed: `${found.method} ${found.path}${found.search}`, pass: true });
    },
    /**
     * The file-chooser boundary: focus must be on a file input; a key opens the
     * chooser; the browser reports which node opened it; only then is the
     * fixture file supplied, to that node.
     */
    async chooseFile(filePath, { key = 'Enter', note } = {}) {
      const before = await focus();
      const entry = { action: 'file-chooser', key, focusBefore: summary(before), routeBefore: before.route, note, boundary: 'the OS file chooser is outside the product: opened by the key, intercepted, answered with the fixture file' };
      if (before.tag !== 'input' || before.type !== 'file') fail(entry, `focus is on ${summary(before)}, not on a file input`);
      const { root } = await browser.cdp('DOM.getDocument', { depth: 0 });
      const { nodeId } = await browser.cdp('DOM.querySelector', { nodeId: root.nodeId, selector: '[data-vqa-journey-focus]' });
      const { node } = await browser.cdp('DOM.describeNode', { nodeId });
      let opened = null;
      const off = browser.onEvent('Page.fileChooserOpened', (params) => { opened = params; });
      try {
        await browser.press(key, codeOf(key));
        const started = Date.now();
        while (!opened && Date.now() - started < timeout) await tick(25);
      } finally { off(); }
      if (!opened) fail(entry, `pressing ${key} on the file input opened no file chooser`);
      if (opened.backendNodeId !== node.backendNodeId) fail(entry, 'the chooser the browser reported belongs to another element than the focused input');
      await browser.fileChooser.supply(opened.backendNodeId, [filePath]);
      await quiet();
      await judge(entry);
      step({ ...entry, observed: `chooser opened by ${key} on the focused input; supplied ${filePath.split(/[\\/]/).pop()}`, pass: true });
    },
    /** The journey's end: its terminal checkpoint, reached. */
    async done(description, expression) {
      const observed = await op.until(description, expression);
      terminal = { description, observed: typeof observed === 'string' ? observed : 'reached' };
      steps[steps.length - 1].terminal = true;
    },
    /** For the journey's own branching: the focused control's name and role, read, never changed. */
    focused: async () => { const s = await focus(); return { name: s.name, role: s.role, description: s.description, route: s.route }; },
    viewport,
  };
  return { op, steps, terminal: () => terminal };
}

const summary = (state) => (state.onBody ? '<body>' : `${state.role ?? state.tag} "${state.name ?? ''}"`);
const describeTarget = (t) => `${t.role ?? 'control'} named ${t.name instanceof RegExp ? t.name.toString() : JSON.stringify(t.name)}${t.row ? ` in the row of ${t.row instanceof RegExp ? t.row.toString() : JSON.stringify(t.row)}` : ''}`;

// --- Running ----------------------------------------------------------------------

/** The head and dirty count of the exact tree being judged. */
function gitHead() {
  try { return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(); } catch { return 'unknown'; }
}

export async function openJourneyLane({ distDir, fixtureDir, mediaDir }) {
  const lane = { scenario: {} };
  lane.server = await startServer({ distDir, fixtureDir, scenario: () => lane.scenario, footage: () => ensureFootage(mediaDir, 'saturated') });
  try {
    lane.browser = await launch();
    await lane.browser.addInitScript(OBSERVERS);
    await lane.browser.addInitScript(JOURNEY_GUARD);
    // The locale the journeys' segmented fields read (a datetime-local's day,
    // month and year order), the same on every host.
    await lane.browser.cdp('Emulation.setLocaleOverride', { locale: JOURNEY_CONDITION.locale });
    await lane.browser.fileChooser.intercept(true);
  } catch (error) {
    await lane.browser?.close().catch(() => {});
    await lane.server.close().catch(() => {});
    throw error;
  }
  return lane;
}

/** One execution: the declared start, then the journey's own keyboard steps. */
export async function runJourney(lane, item, { record, outDir } = {}) {
  const { journey, viewport } = item;
  const { browser, server } = lane;
  const startedAt = Date.now();
  await browser.goto('about:blank');
  server.releaseHung();
  lane.scenario = journey.api ?? {};
  server.resetSequences();
  await browser.viewport(viewport.width, viewport.height);
  await browser.reducedMotion(false);
  await browser.goto(server.origin + '/__blank');
  await browser.evaluate(`(() => { try { localStorage.clear(); sessionStorage.clear(); for (const [k, v] of Object.entries(${JSON.stringify(journey.storage ?? {})})) localStorage.setItem(k, v); } catch {} return true; })()`);
  // The journey's one direct load: its declared starting route.
  await browser.goto(server.origin + journey.start);
  const documentIndex = await browser.evaluate('window.__vqaJourneyGuard ? window.__vqaJourneyGuard.document : null');
  const { op, steps, terminal } = createOperator({ browser, server, record, journeyId: journey.id, viewport, documentIndex });
  let failure = null;
  try {
    await op.until(`the start, ${journey.start}, has rendered`, journey.ready ?? 'Boolean(document.querySelector("main"))', { judgeFocus: false });
    await journey.run(op, { viewport });
    if (!terminal()) throw new JourneyFailure(`${journey.id} @ ${viewport.label}: the journey ended without its terminal checkpoint`);
  } catch (error) {
    failure = error instanceof JourneyFailure ? error.message : `${journey.id} @ ${viewport.label}: harness error: ${String(error.stack || error)}`;
  }
  // A failed journey keeps what the operator was looking at: the page's text
  // and a capture (diagnostic artefacts, never committed — §26).
  let snapshot = null;
  if (failure) {
    snapshot = await browser.evaluate(String.raw`({ route: location.pathname + location.search, text: document.body.innerText.replace(/\s+/g, ' ').slice(0, 1500) })`).catch(() => null);
    if (outDir) {
      try { writeFileSync(join(outDir, `${item.key.replace(/[^a-z0-9@-]+/gi, '_')}.png`), Buffer.from(await browser.screenshot(), 'base64')); } catch { /* a capture is a convenience */ }
    }
  }
  const guard = await browser.evaluate('(() => { const g = window.__vqaJourneyGuard || {}; return { pointer: (g.pointer || []).length, synthetic: (g.synthetic || []).length, document: g.document }; })()').catch(() => ({}));
  return {
    key: item.key, journey: journey.id, title: journey.title, viewport: viewport.label, tier: viewport.tier,
    passed: !failure && Boolean(terminal()), failure, terminal: terminal(),
    steps, keyPresses: steps.reduce((n, s) => n + (s.action === 'tab-to' ? s.stops.length : s.action === 'type' ? JSON.parse(s.key).length : s.action === 'checkpoint' ? 0 : 1), 0),
    pointerEvents: guard.pointer ?? null, syntheticEvents: guard.synthetic ?? null, documentLoadsAfterStart: guard.document != null && documentIndex != null ? guard.document - documentIndex : null,
    pageProblems: browser.problems(), durationMs: Date.now() - startedAt, snapshot,
  };
}

// --- CLI --------------------------------------------------------------------------

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}

async function main() {
  const OUT = resolve(arg('out', process.env.MAVI_VQA_OUT ? join(process.env.MAVI_VQA_OUT) : join(HERE, '.journeys')));
  if (process.argv.includes('--aggregate')) {
    const files = process.argv.slice(2).filter((a, i, all) => !a.startsWith('--') && all[i - 1] !== '--out');
    const shards = files.map((file) => ({ file, ...JSON.parse(readFileSync(file, 'utf8')) }));
    const verdict = journeyAggregate(shards);
    mkdirSync(OUT, { recursive: true });
    writeFileSync(join(OUT, 'journeys.json'), JSON.stringify({ aggregate: true, head: shards[0]?.head, planned: verdict.planned, faults: verdict.faults, executions: verdict.executions }, null, 2));
    report(verdict.executions, verdict.planned, verdict.faults, `${shards.length} shard(s)`);
    process.exitCode = verdict.faults.length ? 2 : verdict.failed.length ? 1 : 0;
    return;
  }
  const { JOURNEYS } = await import(process.env.MAVI_VQA_JOURNEYS_MODULE ? new URL('file:///' + resolve(process.env.MAVI_VQA_JOURNEYS_MODULE).replaceAll('\\', '/')).href : './journey-registry.mjs');
  const shardArg = arg('shard');
  const shard = shardArg ? (() => { const m = /^(\d+)\/(\d+)$/.exec(shardArg); if (!m || Number(m[1]) >= Number(m[2])) throw new HarnessError(`--shard takes i/n with 0 <= i < n, not ${shardArg}`); return { index: Number(m[1]), count: Number(m[2]) }; })() : null;
  const plan = planJourneys({ journeys: JOURNEYS, onlyJourneys: arg('journeys')?.split(','), onlyViewports: arg('viewports')?.split(',') });
  const selected = partitionJourneys(plan, shard);
  const workers = Math.max(1, Math.min(Number(arg('workers', String(Math.min(3, Math.max(1, cpus().length - 1))))), selected.length));
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  const distDir = join(HERE, '..', '..', 'src', 'web', 'mavi-web', 'dist');
  if (!existsSync(join(distDir, 'index.html'))) throw new HarnessError('no production build: run npm run build in src/web/mavi-web first');
  const queue = selected.slice();
  const executions = [];
  const harnessErrors = [];
  const lanes = [];
  for (let i = 0; i < workers; i += 1) lanes.push(await openJourneyLane({ distDir, fixtureDir: join(HERE, 'fixtures'), mediaDir: join(OUT, 'media') }));
  try {
    await Promise.all(lanes.map(async (lane) => {
      while (queue.length) {
        const item = queue.shift();
        const result = await runJourney(lane, item, { outDir: OUT });
        executions.push(result);
        process.stdout.write(`  ${result.passed ? ' ok ' : 'FAIL'}  ${item.key}  (${result.steps.length} steps, ${result.keyPresses} keys)${result.failure ? '\n        ' + result.failure.split('\n')[0] : ''}\n`);
      }
    }));
  } catch (error) {
    harnessErrors.push(String(error.stack || error));
  } finally {
    for (const lane of lanes) { await lane.browser.close().catch(() => {}); await lane.server.close().catch(() => {}); }
  }
  executions.sort((a, b) => a.key.localeCompare(b.key));
  const result = { head: gitHead(), shard, planned: plan.map((p) => p.key), selected: selected.map((p) => p.key), executions, harnessErrors };
  writeFileSync(join(OUT, 'journeys.json'), JSON.stringify(result, null, 2));
  const faults = [...harnessErrors];
  if (!shard) faults.push(...journeyAggregate([{ file: 'this run', ...result }]).faults.filter((f) => !(arg('journeys') || arg('viewports')) || !/never ran/.test(f)));
  report(executions, shard ? result.selected : result.planned, faults, shard ? `shard ${shard.index}/${shard.count}` : 'one run');
  process.exitCode = faults.length ? 2 : executions.some((e) => !e.passed) ? 1 : 0;
}

function report(executions, planned, faults, scope) {
  const passed = executions.filter((e) => e.passed);
  process.stdout.write(`\nkeyboard journeys (${scope}): ${passed.length}/${planned.length} passed, ${executions.reduce((n, e) => n + e.steps.length, 0)} steps, ${executions.reduce((n, e) => n + e.keyPresses, 0)} key presses, ${executions.reduce((n, e) => n + (e.pointerEvents ?? 0), 0)} pointer events, ${executions.reduce((n, e) => n + (e.syntheticEvents ?? 0), 0)} scripted events\n`);
  for (const e of executions.filter((x) => !x.passed)) process.stdout.write(`  FAIL ${e.key}: ${e.failure}\n`);
  if (faults.length) { process.stdout.write('\nHARNESS ERROR(S):\n'); for (const f of faults) process.stdout.write(`  - ${f}\n`); }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => { process.stderr.write(`HARNESS ERROR: ${error.stack || error}\n`); process.exitCode = 2; });
}
