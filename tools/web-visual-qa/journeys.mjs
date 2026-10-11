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
import { createHash } from 'node:crypto';
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
  for (const e of executions) if (e.harnessError) faults.push(`a11y.keyboard-journeys: ${e.key} ended on a harness error, not a journey finding: ${String(e.harnessError).split('\n')[0]}`);
  for (const e of executions) if (e.tier === 'C') faults.push(`a11y.keyboard-journeys: ${e.key} ran at Tier C, where no workflow acceptance is claimed`);
  // A pass is its evidence: keys alone (no pointer, nothing scripted), one
  // document from the start, and the terminal checkpoint reached.
  for (const e of executions.filter((x) => x.passed)) {
    const missing = [
      e.pointerEvents !== 0 && 'pointer events',
      e.syntheticEvents !== 0 && 'scripted events',
      e.documentLoadsAfterStart !== 0 && 'document loads after the start',
      !e.terminal && 'a terminal checkpoint',
      !(e.steps?.length) && 'steps',
    ].filter(Boolean);
    if (missing.length) faults.push(`a11y.keyboard-journeys: ${e.key} claims a pass without its evidence (${missing.join(', ')})`);
  }
  for (const s of shards) faults.push(...(s.harnessErrors ?? []).map((h) => `${s.file}: ${h}`));
  const failed = executions.filter((e) => !e.passed);
  return { faults, executions, failed, planned: first.planned };
}

// --- The page's side --------------------------------------------------------------

/**
 * Installed before every document: what the journey's guards read. Trusted
 * pointer and touch input (none is ever sent; one means a pointer reached the
 * page), and scripted clicks, key, input, change and submit events (the
 * product dispatches none; one means something other than the input pipeline
 * acted). A keyboard-activated button
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
  for (const type of ['keydown', 'keyup', 'keypress', 'beforeinput', 'input', 'change', 'submit']) {
    window.addEventListener(type, (e) => { if (!e.isTrusted) guard.synthetic.push('scripted ' + type + ' on ' + name(e.target)); }, true);
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
  // The last control focus stood on: where a Tab that leaves the page left from.
  window.__vqaJourneyLastFocus = el;
  const problems = [];
  // X1's rule, here confined to the one control that needs it: a file input
  // not itself drawn (the FileInput's transparent native input, dressed by its
  // label and framed by its :focus-within ring) is shown by a visible label of
  // its own, judged in its place. Any other hidden control with focus fails.
  let face = el;
  let facedBy = null;
  if (zoomVisibility(el).hidden && el.matches('input[type="file"]') && el.labels) {
    const label = Array.from(el.labels).find((candidate) => !zoomVisibility(candidate).hidden);
    if (label) { face = label; facedBy = 'its label ' + zoomDescribe(label); }
  }
  const v = zoomVisibility(face);
  if (v.hidden) problems.push(zoomDescribe(el) + ' has focus but is not rendered (' + v.hidden + ')');
  else if (v.seen.width < 1 || v.seen.height < 1) problems.push(zoomDescribe(el) + ' has focus but no part of it is in view');
  else {
    const x = (v.seen.left + v.seen.right) / 2; const y = (v.seen.top + v.seen.bottom) / 2;
    const hit = document.elementFromPoint(x, y);
    const label = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null;
    if (hit && !(hit === el || el.contains(hit) || hit.contains(el) || face.contains(hit) || (label && label.contains(hit)))) problems.push(zoomDescribe(el) + ' has focus but ' + zoomDescribe(hit) + ' is over its middle');
  }
  const modal = Array.from(document.querySelectorAll('[aria-modal="true"]')).find((m) => !zoomVisibility(m).hidden);
  if (modal && !modal.contains(el)) problems.push('a modal overlay is open and focus is outside it, on ' + zoomDescribe(el));
  if (el.closest('[inert]')) problems.push(zoomDescribe(el) + ' has focus inside an inert region');
  // The row the control acts on (a Ledger row, a list item, a result), by its
  // text: row actions share names ("Detail"), the row says which.
  const rowEl = el.closest('tr, li, [role="row"], [role="listitem"]');
  const row = rowEl ? (rowEl.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 240) : '';
  // The labelled landmark or group it sits in: two controls may share a name
  // ("Search" in the rail and in a breadcrumb; "Zone" the tool and the
  // filter), the landmark or group says which.
  const landmarkEl = el.closest('nav[aria-label], aside[aria-label], section[aria-label], [role="navigation"][aria-label], [role="region"][aria-label], [role="dialog"][aria-label], [role="group"][aria-label]');
  const within = landmarkEl ? landmarkEl.getAttribute('aria-label') : '';
  return {
    route, row, within, description: zoomDescribe(el) + (facedBy ? ' (shown by ' + facedBy + ')' : ''), tag: el.tagName.toLowerCase(), type: el.getAttribute('type'),
    inModal: Boolean(modal && modal.contains(el)), modalOpen: Boolean(modal), problems,
  };
}
journeyFocusState.helpers = [zoomDescribe, zoomClipChain, zoomVisibleRect, zoomVisibility];

/**
 * Whether a Tab that put focus on the document left the page from its edge:
 * the control it left was the last tabbable one in the document (the first,
 * for Shift+Tab). Focus then returns to the page on the next press — the
 * browser's own cycle, not focus lost.
 */
export function journeyTabEdge(reverse) {
  const from = window.__vqaJourneyLastFocus;
  if (!from || !from.isConnected) return false;
  const tabbable = Array.from(document.querySelectorAll('a[href], button, input, select, textarea, summary, iframe, [tabindex], [contenteditable="true"]'))
    .filter((el) => el.tabIndex >= 0 && !el.disabled && !el.closest('[inert]') && !(el.type === 'hidden') && !zoomVisibility(el).hidden);
  const index = tabbable.indexOf(from);
  return index !== -1 && index === (reverse ? 0 : tabbable.length - 1);
}
journeyTabEdge.helpers = journeyFocusState.helpers;

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
export function createOperator({ browser, server, record, journeyId, viewport, documentIndex, uploads = {}, limits = {} }) {
  const timeout = limits.timeoutMs ?? 12_000;
  const steps = [];
  let terminal = null;
  // Where the request log stood at the operator's last key: `requested`
  // looks only after it, so a request is proven to follow the action.
  let requestMark = 0;
  const markRequests = () => { requestMark = server.requests().length; };
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
  // Focus is read in two steps (the page tags it, the accessibility tree
  // names it); a control the product re-renders between the two — a button
  // turning into its own busy label — is gone by the second, which is the
  // read's race, not the journey's finding: the whole read is retried, a
  // bounded few times, then the CDP error stands as a harness fault.
  const focus = async () => {
    for (let attempt = 1; ; attempt += 1) {
      const state = await browser.evaluate(toExpression(journeyFocusState));
      if (state.onBody) return state;
      try {
        const [ax] = await browser.axNames('[data-vqa-journey-focus]');
        state.name = ax?.name ?? ''; state.role = ax?.role ?? null;
        return state;
      } catch (error) {
        if (attempt >= 4 || !/Could not find node|No node with given id|Node with given id does not/i.test(String(error?.message ?? error))) throw error;
        await tick(25);
      }
    }
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
    const withinOk = target.within === undefined || state.within === target.within;
    return nameOk && roleOk && rowOk && withinOk;
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
      markRequests();
      await browser.press(key, codeOf(key), { shift });
      await quiet();
      await judge(entry, { expectFocus });
      step({ ...entry, observed: 'key delivered; focus valid', pass: true });
    },
    /** Characters, one key each. */
    async type(text, { note } = {}) {
      const before = await focus();
      const entry = { action: 'type', key: JSON.stringify(text), focusBefore: summary(before), routeBefore: before.route, note };
      markRequests();
      for (const ch of text) await browser.press(ch, codeOf(ch));
      await quiet();
      await judge(entry);
      step({ ...entry, observed: 'typed; focus valid', pass: true });
    },
    /**
     * A `datetime-local`'s value, typed into its segments as an operator
     * reads them: the segment order (day, month, year, hour, minute, and a
     * 12-hour clock's AM/PM) is the browser's own, by its locale, and is read
     * from the focused control's rendering — observed, never set — then each
     * segment is typed with keys (Tab after a year, which does not advance by
     * itself). The value is then checked as the field holds it.
     */
    async enterDateTime(value, { note } = {}) {
      const before = await focus();
      const entry = { action: 'type', key: JSON.stringify(value), focusBefore: summary(before), routeBefore: before.route, note };
      if (before.tag !== 'input' || before.type !== 'datetime-local') fail(entry, `focus is on ${summary(before)}, not on a date and time field`);
      const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(value);
      if (!m) throw new HarnessError(`enterDateTime takes YYYY-MM-DDTHH:MM, not ${value}`);
      const [, year, month, day, hour, minute] = m;
      const { root } = await browser.cdp('DOM.getDocument', { depth: 0 });
      const { nodeId } = await browser.cdp('DOM.querySelector', { nodeId: root.nodeId, selector: '[data-vqa-journey-focus]' });
      const { node } = await browser.cdp('DOM.describeNode', { nodeId, depth: -1, pierce: true });
      const order = [];
      const walk = (n) => {
        const a = n.attributes ?? []; const i = a.indexOf('pseudo');
        const f = i === -1 ? null : /^-webkit-datetime-edit-(day|month|year|hour|minute|ampm)-field$/.exec(a[i + 1]);
        if (f) order.push(f[1]);
        for (const c of [...(n.shadowRoots ?? []), ...(n.children ?? [])]) walk(c);
      };
      walk(node);
      if (order.length < 5) fail(entry, `the field's segments could not be read (${order.join(', ') || 'none'})`);
      const twelve = order.includes('ampm');
      const h = Number(hour);
      const keys = { day, month, year, minute, hour: twelve ? String(h % 12 === 0 ? 12 : h % 12).padStart(2, '0') : hour, ampm: h < 12 ? 'A' : 'P' };
      markRequests();
      entry.presses = 0;
      for (const [index, segment] of order.entries()) {
        for (const ch of keys[segment]) { await browser.press(ch, codeOf(ch)); entry.presses += 1; }
        if (segment === 'year' && index < order.length - 1) { await browser.press('Tab', 'Tab'); entry.presses += 1; }
      }
      await quiet();
      entry.segments = order.join(' ');
      const held = await browser.evaluate('document.activeElement && document.activeElement.value');
      if (held !== value) fail(entry, `the field holds ${JSON.stringify(held)}, not ${value} (segments ${entry.segments})`);
      await judge(entry);
      step({ ...entry, observed: `typed by segment (${entry.segments}); the field holds ${held}`, pass: true });
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
      let previousStop = before;
      for (let i = 0; i < max; i += 1) {
        await browser.press('Tab', 'Tab', { shift: reverse });
        const state = await focus();
        entry.stops.push(summary(state));
        // Every stop is somewhere the operator stands: lost, hidden or covered
        // focus on the way fails as it would at the end.
        if (state.problems.length) {
          // The document itself is a stop only at the page's edge, the
          // browser's cycle; anywhere else focus was lost on the way.
          const edge = state.onBody && !previousStop.onBody && await browser.evaluate(toExpression(journeyTabEdge, reverse)).catch(() => false);
          if (!edge) { entry.focusAfter = summary(state); fail(entry, `Tab stop ${i + 1}: ${state.problems.join('; ')}`); }
        }
        previousStop = state;
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
      const entry = { action: 'checkpoint', expect: description };
      while (Date.now() - started < timeoutMs) {
        // Evaluated with V8's side-effect check: a checkpoint that would click,
        // focus, write a value, navigate or store anything throws before it
        // does, and fails the journey — it observes; only keys act. An
        // ordinary error (an element not there yet) is "not yet".
        const r = await browser.cdp('Runtime.evaluate', {
          expression: `(() => { try { return ${expression}; } catch (e) { if (e instanceof EvalError) throw e; return false; } })()`,
          returnByValue: true, throwOnSideEffect: true,
        });
        if (r.exceptionDetails) fail(entry, `the checkpoint expression acts on the page (${(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text).split('\n')[0]}): a checkpoint may only observe`);
        last = r.result?.value;
        if (last) break;
        await tick(50);
      }
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
    async requested(description, method, pathPattern, { query, body } = {}) {
      const started = Date.now();
      let found = null;
      while (Date.now() - started < timeout && !found) {
        found = server.requests().slice(requestMark).find((r) => r.method === method && pathPattern.test(r.path)
          && (!query || Object.entries(query).every(([k, v]) => new URLSearchParams(r.search).get(k) === String(v)))
          // `body`: a predicate over the parsed JSON the application sent.
          && (!body || (() => { try { return r.body !== undefined && body(JSON.parse(r.body)); } catch { return false; } })())) ?? null;
        if (!found) await tick(50);
      }
      const entry = { action: 'checkpoint', expect: description };
      if (!found) fail(entry, `no ${method} ${pathPattern} request was made after the operator's last key`);
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
      markRequests();
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
    /** A file the operator will pick in the chooser: one the lane wrote before the journey started. */
    upload(name) {
      if (!uploads[name]) throw new HarnessError(`no upload fixture named ${name}`);
      return uploads[name];
    },
    /** For the journey's own branching: the focused control's name and role, read, never changed. */
    focused: async () => { const s = await focus(); return { name: s.name, role: s.role, description: s.description, route: s.route }; },
    viewport,
  };
  return { op, steps, terminal: () => terminal };
}

const summary = (state) => (state.onBody ? '<body>' : `${state.role ?? state.tag} "${state.name ?? ''}"${state.within ? ` within "${state.within}"` : ''}`);
const describeTarget = (t) => `${t.role ?? 'control'} named ${t.name instanceof RegExp ? t.name.toString() : JSON.stringify(t.name)}${t.row ? ` in the row of ${t.row instanceof RegExp ? t.row.toString() : JSON.stringify(t.row)}` : ''}${t.within ? ` within "${t.within}"` : ''}`;

// --- Running ----------------------------------------------------------------------

/** The head and dirty count of the exact tree being judged. */
/** The registry a run executed, by the hash of its source. */
function registryHash(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

function gitHead() {
  try { return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(); } catch { return 'unknown'; }
}

export async function openJourneyLane({ distDir, fixtureDir, mediaDir }) {
  const lane = { scenario: {}, uploads: writeUploads(join(mediaDir, 'uploads')) };
  lane.server = await startServer({ distDir, fixtureDir, scenario: () => lane.scenario, footage: () => ensureFootage(mediaDir, 'saturated') });
  try {
    lane.browser = await launch({ lang: JOURNEY_CONDITION.locale });
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

/**
 * The files an operator picks in a chooser (journey 1's import). The fixture
 * server never reads an upload, so its bytes need not decode — only its name
 * meets the form's own check (an `.mp4`).
 */
export const UPLOADS = Object.freeze({ 'north-gate-0800.mp4': 'MAVI keyboard-journey upload fixture; the fixture server does not decode it.\n' });
function writeUploads(dir) {
  mkdirSync(dir, { recursive: true });
  return Object.fromEntries(Object.entries(UPLOADS).map(([name, body]) => {
    const path = join(dir, name);
    writeFileSync(path, body);
    return [name, resolve(path)];
  }));
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
  const { op, steps, terminal } = createOperator({ browser, server, record, journeyId: journey.id, viewport, documentIndex, uploads: lane.uploads });
  let failure = null;
  let harnessError = null;
  try {
    await op.until(`the start, ${journey.start}, has rendered`, journey.ready ?? 'Boolean(document.querySelector("main"))', { judgeFocus: false });
    await journey.run(op, { viewport });
    if (!terminal()) throw new JourneyFailure(`${journey.id} @ ${viewport.label}: the journey ended without its terminal checkpoint`);
  } catch (error) {
    failure = error instanceof JourneyFailure ? error.message : `${journey.id} @ ${viewport.label}: harness error: ${String(error.stack || error)}`;
    // A CDP call, the runner or a registry entry that throws is not a
    // keyboard finding: it is kept apart as a harness fault (exit 2).
    if (!(error instanceof JourneyFailure)) harnessError = String(error.stack || error);
  }
  // A failed journey keeps what the operator was looking at: the page's text
  // and a capture (diagnostic artefacts, never committed — §26).
  let snapshot = null;
  if (failure) {
    snapshot = await browser.evaluate(String.raw`({ route: location.pathname + location.search, text: document.body.innerText.replace(/\s+/g, ' ').slice(0, 1500) })`).catch(() => null);
    // What the application asked the backend, last first (the request log).
    if (snapshot) snapshot.requests = server.requests().slice(-25).map((r) => `${r.method} ${r.path}${r.search}`);
    if (outDir) {
      try { writeFileSync(join(outDir, `${item.key.replace(/[^a-z0-9@-]+/gi, '_')}.png`), Buffer.from(await browser.screenshot(), 'base64')); } catch { /* a capture is a convenience */ }
    }
  }
  const guard = await browser.evaluate('(() => { const g = window.__vqaJourneyGuard || {}; return { pointer: (g.pointer || []).length, synthetic: (g.synthetic || []).length, document: g.document }; })()').catch(() => ({}));
  return {
    // Every execution is the evidence of one rule (§23, plan §5.3).
    rule: 'a11y.keyboard-journeys',
    key: item.key, journey: journey.id, title: journey.title, viewport: viewport.label, tier: viewport.tier,
    passed: !failure && Boolean(terminal()), failure, harnessError, terminal: terminal(),
    steps, keyPresses: steps.reduce((n, s) => n + (s.action === 'tab-to' ? s.stops.length : s.presses ?? (s.action === 'type' ? JSON.parse(s.key).length : s.action === 'checkpoint' ? 0 : 1)), 0),
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
    const expected = registryHash(join(HERE, 'journey-registry.mjs'));
    for (const s of shards) if (s.registry !== expected) verdict.faults.push(`${s.file}: ran registry ${s.registry ?? '(none recorded)'}, not this head's ${expected}`);
    // The aggregate is of the whole registry: a subset is not X2's evidence.
    const { JOURNEYS: registered } = await import('./journey-registry.mjs');
    const full = planJourneys({ journeys: registered }).map((p) => p.key);
    if (JSON.stringify(verdict.planned) !== JSON.stringify(full)) verdict.faults.push(`the shards planned ${verdict.planned?.length ?? 0} executions, not the registry's ${full.length}`);
    mkdirSync(OUT, { recursive: true });
    writeFileSync(join(OUT, 'journeys.json'), JSON.stringify({ aggregate: true, head: shards[0]?.head, planned: verdict.planned, faults: verdict.faults, executions: verdict.executions }, null, 2));
    report(verdict.executions, verdict.planned, verdict.faults, `${shards.length} shard(s)`);
    process.exitCode = verdict.faults.length ? 2 : verdict.failed.length ? 1 : 0;
    return;
  }
  const shardArg = arg('shard');
  // A shard is X2's evidence: it runs the registry, never a substitute.
  if (process.env.MAVI_VQA_JOURNEYS_MODULE && shardArg) throw new HarnessError('MAVI_VQA_JOURNEYS_MODULE replaces the registry, so a shard (X2 evidence) refuses it');
  const registryFile = process.env.MAVI_VQA_JOURNEYS_MODULE ? resolve(process.env.MAVI_VQA_JOURNEYS_MODULE) : join(HERE, 'journey-registry.mjs');
  const { JOURNEYS } = await import(new URL('file:///' + registryFile.replaceAll('\\', '/')).href);
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
  for (const e of executions) if (e.harnessError) harnessErrors.push(`${e.key}: ${e.harnessError.split('\n')[0]}`);
  const result = { head: gitHead(), registry: registryHash(registryFile), shard, planned: plan.map((p) => p.key), selected: selected.map((p) => p.key), executions, harnessErrors };
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
