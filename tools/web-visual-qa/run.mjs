#!/usr/bin/env node
/**
 * MAVI visual-QA pass — Harness v2 (specification §26 as amended in v2.0;
 * acceptance register V1-V5, P1).
 *
 *   node tools/web-visual-qa/run.mjs [--states a,b] [--tiers A,B] [--widths 1366,2560]
 *                                    [--zoom only|none] [--workers 3] [--repeat 5] [--keep] [--build]
 *
 * Runs the real production bundle (build it first, or pass --build) in real
 * Chromium at every tier anchor each state applies to, plus each state's probe
 * widths. Every finding names a manifest rule and takes that rule's severity
 * at the tier of the width it was found at (manifest.mjs).
 *
 * T3 (§23): every state swept at Tier C is also captured on the 1366x768
 * anchor at 200% browser page zoom — the browser's own zoom, read back from
 * the browser and the page (cdp.mjs pageZoom, engine.zoomQualification) — and
 * judged at Tier C, where its effective 683x384 falls; states declare live
 * zoom transitions too. `--zoom only` runs just those cases, `--zoom none`
 * leaves them out; either is a partial run.
 *
 * Exit status:
 *   0  no blocking finding (measured/pending findings are reported, never fail);
 *   1  at least one blocking finding (unless --keep);
 *   2  the harness itself failed — a browser or server fault, a finding or an
 *      evaluation the manifest does not allow, or a blocking rule that the full
 *      sweep never evaluated. A harness failure is never reported as a finding.
 *
 * Captures are diagnostic working artefacts (`.captures/`, gitignored): §26
 * forbids committing them, and no pixel baseline exists (V5).
 */
import { execFileSync } from 'node:child_process';
import { appendFileSync, existsSync, mkdirSync, readdirSync, rmSync, writeFileSync, writeSync } from 'node:fs';
import { cpus } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

/** A harness fault before the run: said synchronously (an asynchronous write to
 *  a pipe can be lost when the process exits), then exit 2. */
function fatal(text) {
  try { writeSync(2, text.endsWith('\n') ? text : text + '\n'); } catch { /* stderr gone */ }
  process.exit(2);
}

// A fault outside the case loop is a harness failure (exit 2), never the
// blocking-finding status an uncaught error would otherwise produce.
process.on('uncaughtException', (error) => { fatal(`HARNESS ERROR: ${error.stack || error}\n`); });
process.on('unhandledRejection', (error) => { fatal(`HARNESS ERROR: ${error?.stack || error}\n`); });

// The harness's modules load after the handlers above, so one that fails to
// load is a harness fault (exit 2) too. The states are the registered ones or —
// for the harness's own tests only — a module that re-exports them with test
// states added (MAVI_VQA_STATES_MODULE).
const STATES_MODULE = process.env.MAVI_VQA_STATES_MODULE ? resolve(process.env.MAVI_VQA_STATES_MODULE) : null;
let modules;
try {
  modules = await Promise.all([
    import('./assertions.mjs'), import('./cdp.mjs'), import('./engine.mjs'), import('./footage.mjs'),
    import('./manifest.mjs'), import('./server.mjs'), import('./settle.mjs'),
    import(STATES_MODULE ? pathToFileURL(STATES_MODULE).href : './states.mjs'), import('./semantics.mjs'),
  ]);
} catch (error) {
  fatal(`HARNESS ERROR: a harness module did not load: ${error.stack || error}\n`);
}
const [
  {
    focusAssertions, overlayExitProbe, overlayFocusProbe, overlayOpened, overlayReady, pageAssertions, stickyProbe, toExpression, workspaceAssertions,
    zoomAssertions, zoomBeforeChange, zoomEnvironment, zoomTransitionProbe,
  },
  { launch },
  { createLedger, exitStatus, HarnessError, planCases, settle, unprovenPressedKinds, unreachedFaults, zoomCoverageFaults, zoomQualification },
  { CONDITIONS, ensureFootage },
  { manifestSummary, OPERATOR_SURFACES, RULES, TIERS, validateManifest, ZOOM_CONDITION },
  { startServer },
  { OBSERVERS, perfCollect, TRANSIENT },
  { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM },
  { tierCLedgerSemantics },
] = modules;

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, '..', '..', 'src', 'web', 'mavi-web');
// Captures and results; the harness's own tests point this elsewhere so they never
// overwrite a sweep's evidence.
const OUT = process.env.MAVI_VQA_OUT ? resolve(process.env.MAVI_VQA_OUT) : join(HERE, '.captures');

function arg(name, fallback) {
  const index = process.argv.indexOf(`--${name}`);
  return index === -1 ? fallback : process.argv[index + 1];
}
const flag = (name) => process.argv.includes(`--${name}`);
const list = (name) => arg(name, null)?.split(',').map((v) => v.trim()).filter(Boolean) ?? null;

/** Bounds every wait. A timeout refuses the capture; it never settles it. */
const SETTLE_TIMEOUT_MS = 20_000;
const OVERLAY_TIMEOUT_MS = 20_000;
/** Layout-shift pairs: a loading Ledger and the table that replaces it (S1e, D3). */
const LOADING_PAIRS = [['cameras-loading', 'cameras'], ['videos-loading', 'videos'], ['processing-queue-loading', 'processing-queue']];

// --- Plan the run ---------------------------------------------------------------

const onlyStates = list('states');
const onlyTiers = list('tiers');
const onlyWidths = list('widths')?.map(Number) ?? null;
const onlyZoom = arg('zoom', null);
if (onlyZoom !== null && onlyZoom !== 'only' && onlyZoom !== 'none') fatal(`--zoom takes "only" or "none", not "${onlyZoom}"`);
// A count that is not a positive integer is refused: NaN would plan cases and
// run none of them.
const positiveInt = (name, fallback) => {
  const raw = arg(name, String(fallback));
  if (!/^[1-9][0-9]*$/.test(String(raw))) fatal(`--${name} must be a positive integer, not "${raw}"`);
  return Number(raw);
};
const repeat = positiveInt('repeat', 1);
const fullSweep = !onlyStates && !onlyTiers && !onlyWidths && !onlyZoom && repeat === 1 && !STATES_MODULE;
const workers = positiveInt('workers', Math.min(4, Math.max(1, cpus().length - 1)));

const manifestProblems = validateManifest();
if (manifestProblems.length) {
  fatal('assertion manifest is invalid:\n  ' + manifestProblems.join('\n  ') + '\n');
}
for (const name of onlyStates ?? []) {
  if (!STATES.some((state) => state.name === name)) { fatal(`unknown state ${name}\n`); }
}

let plan;
try {
  plan = planCases({
    states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, zoom: ZOOM,
    onlyStates, onlyTiers, onlyWidths, onlyZoom, repeat,
  });
} catch (error) {
  fatal(String(error.message || error) + '\n');
}
const { cases, applicability } = plan;
if (!cases.length) { fatal('nothing to run\n'); }

if (flag('build')) {
  process.stdout.write('building frontend…\n');
  execFileSync('npm', ['run', 'build'], { cwd: WEB, stdio: 'inherit', shell: process.platform === 'win32' });
}

// The default output directory is the harness's own (and ignored by Git); one
// MAVI_VQA_OUT names is replaced only if it is missing, empty or one the
// harness wrote (its marker), since that variable can point anywhere.
const MARKER = '.mavi-visual-qa-output';
if (process.env.MAVI_VQA_OUT && existsSync(OUT) && readdirSync(OUT).length && !existsSync(join(OUT, MARKER))) {
  fatal(`HARNESS ERROR: ${OUT} is not empty and is not a visual-QA output directory; refusing to replace it\n`);
}
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, MARKER), 'Written by tools/web-visual-qa/run.mjs; replaced on every run.\n');
const MEDIA = join(OUT, 'media');
// Every clip before any browser starts: ffmpeg is synchronous, and encoding on
// first request would stall the server mid-load.
const needed = new Set(cases.map(({ state }) => state.footage ?? 'saturated'));
for (const condition of needed) {
  if (!CONDITIONS[condition]) throw new HarnessError(`unknown footage condition in states.mjs: ${condition}`);
  ensureFootage(MEDIA, condition);
}

// --- Lanes ----------------------------------------------------------------------
//
// A lane is one fixture server and one Chromium, each with its own scenario,
// sequence counters, profile and storage, so lanes share nothing a case could
// leak through. Cases are pulled from one queue; within a lane they run one at
// a time, each in a fresh document.

async function openLane(index) {
  // `zoom`: the page zoom the lane's browser is at — its fresh profile's 100%
  // until a zoom case sets it, and set back before any other case runs.
  const lane = { index, scenario: {}, footage: 'saturated', zoom: 1 };
  lane.server = await startServer({
    distDir: join(WEB, 'dist'),
    fixtureDir: join(HERE, 'fixtures'),
    scenario: () => lane.scenario,
    footage: () => ensureFootage(MEDIA, lane.footage),
  });
  // A lane that fails part-way closes what it opened: a listening server left
  // behind would keep the process alive past the harness fault it reports.
  try {
    lane.browser = await launch();
    await lane.browser.addInitScript(OBSERVERS);
    lane.environment = await lane.browser.environment();
  } catch (error) {
    await lane.browser?.close().catch(() => {});
    await lane.server.close().catch(() => {});
    throw error;
  }
  return lane;
}

const results = [];
const harnessErrors = [];
/** Cases that threw: no result, no capture — a harness fault with its cause. */
const errored = [];
const ledger = createLedger(RULES);
const { findings, coverage } = ledger;
const record = (c, rule, message, scope) => ledger.record(c, rule, message, scope);
const markEvaluated = (c, rules, scope) => ledger.markEvaluated(c, rules, scope);

async function runCase(lane, c) {
  const { viewport } = c;
  // A state may say how it is reached, and what it shows, at one tier
  // (`atTier`): a Tier C Workbench state asserts the unsupported state, not
  // the canvas its Tier A preparation drives (§26). Everything below reads
  // the tier's view of the state.
  const view = (tier) => (c.state.atTier?.[tier] ? { ...c.state, ...c.state.atTier[tier] } : c.state);
  const state = view(viewport.tier);
  // A live zoom transition (T3) is reached at the tier it starts at, and
  // judged at the tier it ends at: its preparation is the start tier's.
  const transition = viewport.kind === 'zoom-transition' ? viewport.transition : null;
  const start = transition ? view(viewport.startTier) : state;
  // What the transition settles on at its final zoom: its own expectations
  // where the zoom changes what the state shows (a Dialog the narrower tier
  // drops), else the state's at that tier.
  const end = transition && (transition.expectText || transition.forbidText)
    ? { ...state, expectText: transition.expectText ?? state.expectText, forbidText: transition.forbidText ?? state.forbidText }
    : state;
  const where = `${state.name} @ ${viewport.label}${c.attempt > 1 ? ` #${c.attempt}` : ''}`;
  const name = `${state.name}--${viewport.label}${repeat > 1 ? `--${c.attempt}` : ''}`;
  const caseFindings = [];
  const add = (rule, message, scope = null) => caseFindings.push(record(c, rule, message, scope));
  // The harness could not establish the declared state. Not a finding: a
  // fault at every tier (engine.unreachedFaults), first cause kept.
  let unreached = null;
  const unreach = (stage, reason) => { if (!unreached) unreached = { stage, reason }; };
  const browser = lane.browser;

  lane.server.releaseHung();
  lane.scenario = state.api ?? {};
  lane.server.resetSequences();
  lane.footage = state.footage ?? 'saturated';
  await browser.viewport(viewport.width, viewport.height);
  // T3: the browser's page zoom for this case — 100% unless it is a zoom case
  // — set before the page loads and read back from the browser. A zoom that
  // cannot be set fails the case (a harness fault), never runs it at another.
  const startZoom = viewport.zoom?.[0] ?? 1;
  if (lane.zoom !== startZoom) {
    lane.zoom = null;
    lane.zoom = await browser.pageZoom(startZoom);
  }
  // A blank document first: Chromium holds media decoders across same-origin
  // navigations. Then storage is cleared from a same-origin page that boots
  // nothing, so a stored preference cannot leak between cases and a sequenced
  // fixture is not consumed before the case begins.
  await browser.goto('about:blank');
  await browser.goto(lane.server.origin + '/__blank');
  await browser.evaluate('(() => { try { window.localStorage.clear(); } catch { /* blocked */ } return true; })()');
  // A state that arrives with a stored preference (Search's grid view) has it
  // written here, on the same blank page, before the surface boots.
  if (state.storage) {
    await browser.evaluate(`(() => { try { for (const [key, value] of Object.entries(${JSON.stringify(state.storage)})) window.localStorage.setItem(key, value); } catch { /* blocked */ } return true; })()`);
  }
  await browser.goto(lane.server.origin + state.path);

  // V3: the state is reached when the page and the server say so.
  const loaded = await settle(lane, start, { timeoutMs: SETTLE_TIMEOUT_MS, beforePreparation: Boolean(start.prepare) });
  const settledAt = await browser.evaluate('performance.now()');
  // An overlay already open when the page settles was opened by its URL, not
  // by an action: §20 restoration to an invoking control does not apply to it.
  const openOnLoad = await browser.evaluate(`Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'))`);
  let reached = loaded.ok;
  if (!loaded.ok) unreach('navigation settle', `did not settle within ${SETTLE_TIMEOUT_MS}ms: ${loaded.why.join('; ')}`);

  let prepareStart = null;
  let preparedAt = null;
  let afterPrepare = null;
  if (start.prepare && reached) {
    prepareStart = await browser.evaluate('window.__vqa.mark("prepare-start")');
    let prepared = false;
    try {
      // An interaction's long tasks are read from the action (its
      // `interaction-start` mark, else here) until the settle probe that
      // confirmed its outcome; a long task that ran one of the settle probes is the harness's and
      // is excluded (settle.mjs, perfCollect).
      prepared = Boolean(await browser.evaluate(`(async () => await ${start.prepare})()`));
    } catch (error) {
      unreach('preparation', `preparation failed: ${String(error.message || error).split('\n')[0]}`);
    }
    if (prepared) {
      afterPrepare = await settle(lane, start, { timeoutMs: SETTLE_TIMEOUT_MS });
      if (afterPrepare.ok) preparedAt = await browser.evaluate('performance.now()');
      else unreach('settle after preparation', `did not settle after its preparation within ${SETTLE_TIMEOUT_MS}ms: ${afterPrepare.why.join('; ')}`);
    } else {
      unreach('preparation', 'preparation reported that the state was not reached');
    }
    reached = prepared && Boolean(afterPrepare?.ok);
  }

  // A footage state proves its overlay is drawn over a decoded frame. Media
  // decoding and seeking have no completion event this page exposes, so the
  // seek is re-issued at a bounded interval until the overlay is there — the
  // one deliberate re-trigger in the harness — and the condition, not the
  // interval, decides.
  if (state.requireOverlay && reached) {
    const started = Date.now();
    let overlay = { ok: false, why: 'not checked' };
    let lastSeek = Date.now();
    while (Date.now() - started < OVERLAY_TIMEOUT_MS) {
      overlay = await browser.evaluate(`new Promise((r) => requestAnimationFrame(() => r(${toExpression(overlayReady)})))`);
      if (overlay.ok) break;
      if (start.prepare && Date.now() - lastSeek > 1500) { await browser.evaluate(start.prepare).catch(() => false); lastSeek = Date.now(); }
    }
    if (!overlay.ok) { unreach('footage overlay', `overlay not ready for capture: ${overlay.why}`); reached = false; }
  }

  // T3: the zoom itself. A transition is taken through its zoom changes here,
  // live, each change judged as it happens (focus, overlays, inertness, the
  // state's own check, text growing with the zoom); every zoom case then
  // proves its final environment is the zoom it claims.
  let zoom = null;
  if (viewport.zoom && reached) {
    // Judged against §23's frozen condition (manifest ZOOM_CONDITION): the
    // 1366x768 viewport, and the 200% factor for a load or a transition's
    // zoomed step — never the condition the states happen to declare. A
    // transition's other steps are 100%.
    const qualify = async (factor) => {
      const page = await browser.evaluate(toExpression(zoomEnvironment));
      const metrics = await browser.layoutMetrics();
      const reported = lane.zoom;
      const expected = viewport.kind === 'zoom' || factor !== 1 ? ZOOM_CONDITION.factor : 1;
      const problems = zoomQualification({ factor: expected, viewport: ZOOM_CONDITION, reported, metrics, page });
      return { factor, reported, metrics, page, problems };
    };
    zoom = { path: viewport.zoom, effective: viewport.effective, steps: [], findings: [], evaluated: false };
    const zoomFail = (message) => zoom.findings.push(message);
    const firstLine = (error) => String(error.message || error).split('\n')[0];
    if (transition?.before) {
      let ok = false;
      try { ok = Boolean(await browser.evaluate(`(async () => await ${transition.before})()`)); } catch (error) { unreach('zoom transition set-up', firstLine(error)); }
      if (!ok) unreach('zoom transition set-up', 'its set-up reported that the state was not reached');
      else {
        // The state the change must survive, as the start tier declares it.
        const ready = await settle(lane, start, { timeoutMs: SETTLE_TIMEOUT_MS });
        if (!ready.ok) unreach('zoom transition set-up', `did not settle within ${SETTLE_TIMEOUT_MS}ms: ${ready.why.join('; ')}`);
      }
      reached = !unreached;
    }
    let previous = reached ? await qualify(viewport.zoom[0]) : null;
    if (previous) {
      zoom.steps.push({ factor: previous.factor, focus: null, environment: previous });
      if (viewport.zoom.length > 1) for (const problem of previous.problems) zoomFail(`at the start (${previous.factor * 100}%): ${problem}`);
    }
    for (let index = 1; reached && index < viewport.zoom.length; index += 1) {
      const factor = viewport.zoom[index];
      const focusBefore = await browser.evaluate(toExpression(zoomBeforeChange));
      lane.zoom = null;
      lane.zoom = await browser.pageZoom(factor);
      const last = index === viewport.zoom.length - 1;
      const after = await settle(lane, end, { timeoutMs: SETTLE_TIMEOUT_MS, beforePreparation: !last || Boolean(transition?.then) });
      if (!after.ok) { unreach('zoom change', `did not settle at ${factor * 100}% within ${SETTLE_TIMEOUT_MS}ms: ${after.why.join('; ')}`); reached = false; break; }
      const probe = await browser.evaluate(toExpression(zoomTransitionProbe));
      for (const finding of probe.findings) zoomFail(`at ${factor * 100}%: ${finding.message}`);
      const check = transition.checks?.[index - 1];
      if (check) {
        let verdict;
        try { verdict = await browser.evaluate(`(async () => await ${check})()`); } catch (error) { verdict = { ok: false, why: `its check threw: ${firstLine(error)}` }; }
        if (!verdict?.ok) zoomFail(`at ${factor * 100}%: ${verdict?.why ?? 'its check failed'}`);
      }
      const environment = await qualify(factor);
      // Text grows with the zoom: its device-independent size follows the
      // factor (WCAG 1.4.4), for the page's text and the Context Bar's.
      for (const key of ['bodyFontPx', 'barTextPx']) {
        const a = previous.page[key] * previous.metrics.pageZoom;
        const b = environment.page[key] * environment.metrics.pageZoom;
        if (a > 0 && b > 0 && Math.abs(b / a - factor / previous.factor) > 0.02) {
          zoomFail(`at ${factor * 100}%: ${key === 'bodyFontPx' ? 'the page text' : 'the Context Bar text'} is drawn ${Math.round(b * 10) / 10}px against ${Math.round(a * 10) / 10}px at ${previous.factor * 100}%: it did not scale with the zoom`);
        }
      }
      if (!last) for (const problem of environment.problems) zoomFail(`at ${factor * 100}%: ${problem}`);
      zoom.steps.push({ factor, focus: { before: focusBefore, after: probe.focus }, modals: probe.modals, environment });
      previous = environment;
    }
    if (reached && transition?.then) {
      let ok = false;
      try { ok = Boolean(await browser.evaluate(`(async () => await ${transition.then})()`)); } catch (error) { unreach('zoom transition action', firstLine(error)); }
      if (!ok && !unreached) unreach('zoom transition action', 'its action reported that the state was not reached');
      if (ok) {
        const done = await settle(lane, end, { timeoutMs: SETTLE_TIMEOUT_MS });
        if (!done.ok) unreach('zoom transition action', `did not settle within ${SETTLE_TIMEOUT_MS}ms: ${done.why.join('; ')}`);
      }
      reached = !unreached;
    }
    if (reached) {
      const final = await qualify(viewport.zoom[viewport.zoom.length - 1]);
      for (const problem of final.problems) zoomFail(problem);
      zoom.environment = final;
      zoom.qualified = final.problems.length === 0;
    }
  }

  const input = {
    tier: viewport.tier, width: viewport.effective?.width ?? viewport.width, fullWidth: state.fullWidth ?? null,
    archetype: state.archetype ?? null, holds: state.holds ?? null,
    // For the few rules a surface's own acceptance scopes to it (cameras.*).
    surface: c.surface ?? null,
  };
  let page = null;
  let focus = null;
  let workspace = null;
  if (reached) {
    // Order matters: the page rules read the resting state; the focus pass
    // then moves focus through every control and puts focus and scroll back.
    page = await browser.evaluate(toExpression(pageAssertions, input));
    focus = await browser.evaluate(toExpression(focusAssertions));
    workspace = state.archetype ? await browser.evaluate(toExpression(workspaceAssertions, input)) : null;
    for (const part of [page, focus, workspace].filter(Boolean)) {
      markEvaluated(c, part.evaluated);
      // Surface-scoped rules also evaluated inside S1 regions, where they block.
      if (part.foundationEvaluated) markEvaluated(c, part.foundationEvaluated, 'foundation');
      for (const finding of part.findings) add(finding.rule, finding.message, finding.scope ?? null);
    }
    // §25 Tier C Ledger: the list is still a table to assistive technology.
    if (viewport.tier === 'C' && state.archetype === 'ledger') {
      const semantics = await tierCLedgerSemantics(browser);
      if (semantics) {
        markEvaluated(c, ['tier.c-composition']);
        for (const message of semantics.findings) add('tier.c-composition', message);
      }
    }
    // T3: the zoom rule — the environment proven above, the transition's own
    // judgements, and what the 384px height can take from the composition.
    if (zoom) {
      const zoomed = await browser.evaluate(toExpression(zoomAssertions, input));
      zoom.measured = zoomed.measured;
      markEvaluated(c, zoomed.evaluated);
      zoom.evaluated = true;
      for (const message of zoom.findings) add('a11y.zoom-200', message);
      for (const finding of zoomed.findings) add(finding.rule, finding.message);
    }
    markEvaluated(c, ['harness.focus-coverage']);
    const skippedTotal = Object.values(focus.skipped).reduce((sum, count) => sum + count, 0);
    if (focus.discovered !== focus.checked + skippedTotal) {
      add('harness.focus-coverage', `${focus.discovered} discovered, ${focus.checked} checked, ${skippedTotal} skipped`);
    }
  }
  if (reached) markEvaluated(c, ['page.uncaught-error', 'page.resource-error']);

  // P1 and V5 measurements: recorded, never pass/fail — and only of a state
  // the harness reached: an unreached page is not the state's evidence.
  const notReached = { status: 'failed', why: 'the declared state was not reached' };
  const perf = reached
    ? await browser.evaluate(toExpression(perfCollect, {
      holds: state.holds ?? null, settledAt, prepareStart, preparedAt,
      confirmedAt: afterPrepare?.confirmedAt ?? null, interaction: state.interaction ?? null,
    }))
    : { cls: notReached, clsPreparation: notReached, longTasks: notReached };
  // The platform fonts are read per text-bearing element: Chromium reports the
  // fonts of a node's own text, so the probe is the first element that holds
  // text in the Context Bar and in the surface.
  const probes = await browser.evaluate(`(() => {
    const path = (el) => { const parts = []; for (let n = el; n && n !== document.body; n = n.parentElement) parts.unshift(n.tagName.toLowerCase() + ':nth-child(' + (Array.from(n.parentElement.children).indexOf(n) + 1) + ')'); return 'body > ' + parts.join(' > '); };
    const first = (root) => root && Array.from(root.querySelectorAll('*')).find((el) => Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim()) && el.getBoundingClientRect().width > 1 && !el.closest('.visually-hidden, [aria-hidden="true"], svg, select, option, script, style, noscript, template, video, audio, canvas, iframe, object'));
    const bar = first(document.querySelector('.context-bar'));
    const surface = first(document.querySelector('main .workspace') || document.querySelector('main .page') || document.querySelector('main'));
    return { contextBar: bar ? path(bar) : null, content: surface ? path(surface) : null, declared: getComputedStyle(document.body).fontFamily };
  })()`);
  const fonts = { declared: probes.declared, contextBar: null, content: null, status: 'measured', why: undefined };
  if (!reached) { fonts.status = 'failed'; fonts.why = 'the declared state was not reached'; } else try {
    if (probes.contextBar) fonts.contextBar = await browser.platformFonts(probes.contextBar);
    if (probes.content) fonts.content = await browser.platformFonts(probes.content);
    if (!fonts.content?.length && !fonts.contextBar?.length) { fonts.status = 'failed'; fonts.why = `no platform font reported for ${probes.content ?? 'any text on the page'}`; }
    else if (!fonts.content?.length) fonts.why = 'the surface lays out no text of its own here; the font of the Context Bar was read';
  } catch (error) {
    fonts.status = 'failed';
    fonts.why = String(error.message || error).split('\n')[0];
  }
  // A measurement is "evaluated" only when it measured something.
  markEvaluated(c, [
    ...(perf.cls.status === 'measured' ? ['perf.cls'] : []),
    ...(perf.longTasks.status === 'measured' ? ['perf.long-tasks'] : []),
    ...(fonts.status === 'measured' ? ['typography.resolved-font'] : []),
  ]);

  // A capture of a state not reached is kept for diagnosis and named so.
  const capture = reached ? `${name}.png` : `${name}--UNREACHED.png`;
  writeFileSync(join(OUT, capture), await browser.screenshot());
  // What the capture shows, read before the probes below act on the page.
  const signature = await browser.evaluate(`(() => {
    const main = document.querySelector('main');
    const text = main ? main.innerText.replace(/\\s+/g, ' ').trim() : '';
    return { rows: document.querySelectorAll('main tbody tr').length, loading: document.querySelectorAll(${JSON.stringify(TRANSIENT)}).length, text: text.slice(0, 2000) };
  })()`);

  // After the capture, the probes that act on the page.
  let sticky = null;
  if (reached && workspace?.measured?.archetype === 'review') {
    sticky = await browser.evaluate(toExpression(stickyProbe));
    if (sticky.evaluated) {
      markEvaluated(c, ['review.sticky-rendered']);
      if (!sticky.pinned) {
        add('review.sticky-rendered', `after a ${sticky.scrolled}px page scroll only ${Math.round(sticky.visibleFraction * 100)}% of the Evidence Player is on screen`);
      } else if (sticky.underBar > 0) {
        add('review.sticky-rendered', `the pinned Evidence Player sits ${sticky.underBar}px under the Context Bar`);
      }
    }
  }
  let overlayExit = null;
  if (reached && page?.shell?.modals) {
    // §15, §20: Escape leaves the overlay and focus goes back to the control
    // that opened it — the invoker the observers recorded as focus entered it.
    overlayExit = await browser.evaluate(toExpression(overlayOpened));
    if (overlayExit) {
      // §20, §23: the keyboard stays inside the open overlay. With real keys,
      // from the focus the overlay itself established (its heading, as a rule):
      // Shift+Tab, then Tab, each must leave focus inside the topmost modal —
      // a reverse step from a heading before the first control is where a trap
      // that only watches its first and last controls lets focus out.
      const start = await browser.evaluate(toExpression(overlayFocusProbe));
      if (start.inside) {
        let escaped = null;
        let from = start.focus;
        for (const [label, shift] of [['Shift+Tab', true], ['Tab', false]]) {
          await browser.press('Tab', 'Tab', { shift });
          const after = await browser.evaluate(toExpression(overlayFocusProbe));
          if (!after.inside && !escaped) {
            escaped = `${label} from ${from} left the open overlay: focus is on ${after.focus ?? 'nothing'}`
              + (after.documentFocused ? '' : ' and the document has lost focus');
          }
          from = after.focus;
        }
        if (escaped) add(overlayExit, escaped);
      }
      await browser.press('Escape');
      const exit = await browser.evaluate(toExpression(overlayExitProbe));
      if (!exit.closed) add(overlayExit, 'Escape did not close the open overlay');
      else if (exit.inertLeft) add(overlayExit, `${exit.inertLeft} region(s) left inert after the overlay closed`);
      // Restoration (§20) is owed to the control that opened the overlay. One
      // the URL opened has none; one an action opened must have been recorded.
      let restoration;
      if (openOnLoad && !exit.invoker) restoration = 'not-applicable (opened by its URL)';
      else if (!exit.invoker) {
        restoration = 'unverifiable';
        add(overlayExit, 'no focused invoker was recorded before the overlay took focus, so restoration to it cannot be shown');
      } else if (!exit.restored) {
        restoration = 'failed';
        if (exit.closed) add(overlayExit, `focus was not restored to the invoker ${exit.invoker} after Escape (it is on ${exit.focus ?? 'nothing'})`);
      } else restoration = 'restored';
      overlayExit = { rule: overlayExit, openOnLoad, restoration, ...exit };
    }
  }

  // A page the harness did not reach is not the state's evidence: its errors
  // are kept with the case for diagnosis, not recorded as its findings.
  const diagnostics = [];
  const pageProblem = (rule, problem) => (reached ? add(rule, problem) : diagnostics.push({ rule, message: problem }));
  for (const problem of browser.problems()) pageProblem('page.uncaught-error', problem);
  const failing = (value) => value === 'unavailable' || (value !== null && typeof value === 'object' && typeof value.status === 'number');
  const expectedPaths = Object.entries(state.api ?? {})
    .filter(([, value]) => failing(value) || (value !== null && typeof value === 'object' && Array.isArray(value.sequence) && value.sequence.some(failing)))
    .map(([key]) => (key.includes(' ') ? key.slice(key.indexOf(' ') + 1) : key));
  for (const problem of browser.resourceErrors()) {
    if (!expectedPaths.some((path) => problem.includes(path))) pageProblem('page.resource-error', problem);
  }
  lane.server.releaseHung();

  const result = {
    state: state.name, viewport: viewport.label, tier: viewport.tier, kind: viewport.kind, attempt: c.attempt, lane: lane.index,
    settled: { ok: loaded.ok, ms: loaded.ms, probes: loaded.probes, why: loaded.ok ? undefined : loaded.why },
    prepared: state.prepare ? { ok: Boolean(afterPrepare?.ok), ms: afterPrepare?.ms ?? null, interaction: state.interaction ?? null } : null,
    reached,
    valid: reached,
    unreached,
    surface: c.surface,
    ...(zoom ? { zoom: { path: zoom.path, effective: zoom.effective, qualified: zoom.qualified ?? false, evaluated: zoom.evaluated, steps: zoom.steps, environment: zoom.environment ?? null, measured: zoom.measured ?? null } } : {}),
    capture,
    pageWidth: page?.pageWidth ?? null,
    shell: page?.shell ?? null,
    focus: focus ? { discovered: focus.discovered, checked: focus.checked, skipped: focus.skipped } : null,
    workspace: workspace?.measured ?? null,
    perf, fonts, sticky, overlayExit, signature,
    findings: caseFindings.map(({ rule, severity, message }) => ({ rule, severity, message })),
    ...(diagnostics.length ? { diagnostics } : {}),
    pressed: page?.pressed ?? null,
  };
  writeFileSync(join(OUT, `${name}.json`), JSON.stringify(result, null, 2));
  results.push(result);
  const blocking = caseFindings.filter((f) => f.severity === 'blocking').length;
  process.stdout.write(`  ${!reached ? 'UNRCH' : blocking ? 'FAIL ' : caseFindings.length ? 'diag ' : ' ok  '} ${where}${reached ? '' : `  (not reached at ${unreached?.stage}: ${unreached?.reason})`}\n`);
}

// --- Run --------------------------------------------------------------------------

const started = Date.now();
const lanes = [];
let next = 0;
try {
  for (let index = 0; index < Math.min(workers, cases.length); index += 1) lanes.push(await openLane(index));
  await Promise.all(lanes.map(async (lane) => {
    while (next < cases.length) {
      const c = cases[next];
      next += 1;
      try {
        await runCase(lane, c);
      } catch (error) {
        if (error instanceof HarnessError) throw error;
        harnessErrors.push(`${c.state.name} @ ${c.viewport.label}: ${String(error.stack || error).split('\n').slice(0, 3).join(' | ')}`);
        errored.push({ state: c.state.name, viewport: c.viewport.label, tier: c.viewport.tier, stage: 'exception', reason: String(error.message || error).split('\n')[0] });
        process.stdout.write(`  ERR   ${c.state.name} @ ${c.viewport.label}: ${String(error.message || error).split('\n')[0]}\n`);
      }
    }
  }));
} catch (error) {
  harnessErrors.push(String(error.message || error));
} finally {
  await Promise.all(lanes.map(async (lane) => { await lane.browser.close(); await lane.server.close(); }));
}
const durationMs = Date.now() - started;

// A loading Ledger's first skeleton row is where the first table row arrives.
for (const [loading, ready] of LOADING_PAIRS) {
  for (const result of results.filter((r) => r.state === loading)) {
    const settled = results.find((r) => r.state === ready && r.viewport === result.viewport);
    const a = result.workspace?.firstRowTop;
    const b = settled?.workspace?.firstRowTop;
    if (typeof a !== 'number' || typeof b !== 'number') continue;
    const c = { state: { name: loading }, viewport: { label: result.viewport, tier: result.tier, kind: result.kind } };
    markEvaluated(c, ['ledger.loading-geometry']);
    if (Math.abs(a - b) > 0.5) record(c, 'ledger.loading-geometry', `first skeleton row at ${a}px, first ${ready} row at ${b}px: the rows move when the table arrives`);
  }
}

// Repeated preparations must confirm the same settled state (V3).
const determinism = [];
if (repeat > 1) {
  const groups = new Map();
  for (const result of results) {
    const key = `${result.state}@${result.viewport}`;
    groups.set(key, [...(groups.get(key) ?? []), result]);
  }
  for (const [key, group] of groups) {
    const signatures = new Set(group.map((r) => JSON.stringify(r.signature)));
    determinism.push({ case: key, runs: group.length, reached: group.filter((r) => r.reached).length, distinctStates: signatures.size, rows: group.map((r) => r.signature.rows), loading: group.map((r) => r.signature.loading) });
    if (signatures.size !== 1) harnessErrors.push(`${key}: ${group.length} independent preparations confirmed ${signatures.size} different states`);
  }
}

// pressed.visible: a control whose pressed form a capture never shows is
// unproven there, not passed. On the full sweep every such kind must be shown
// distinct in some capture; one never proven is a finding where first seen.
const pressedUnproven = [];
if (fullSweep) {
  for (const { kind, result: r, control } of unprovenPressedKinds(results)) {
    const c = { state: { name: r.state }, viewport: { label: r.viewport, tier: r.tier, kind: r.kind }, surface: r.surface };
    record(c, 'pressed.visible', `${control} (${kind}): its pressed treatment is never shown in any capture of the sweep, so it is unproven`);
    pressedUnproven.push(kind);
  }
}

// Non-vacuity: on the full sweep every blocking assertion must have run.
harnessErrors.push(...unreachedFaults(results));
// Every scheduled case produced a result or a recorded error: a case the run
// never reached is not a passed one.
if (results.length + errored.length !== cases.length) {
  harnessErrors.push(`${cases.length - results.length - errored.length} of ${cases.length} scheduled case(s) never ran`);
}
// T3: every operator surface judged at 200% zoom, every transition evaluated.
if (fullSweep) harnessErrors.push(...zoomCoverageFaults(results, OPERATOR_SURFACES));
const vacuous = fullSweep && !harnessErrors.length ? ledger.vacuous() : [];
if (vacuous.length) harnessErrors.push('blocking rules the full sweep never evaluated: ' + vacuous.join(', '));
// §15/§20 restoration is part of each overlay rule: a full sweep must have
// judged it at Tier A for an overlay an action opened, not only for ones the
// URL opened.
if (fullSweep && !harnessErrors.length) {
  for (const rule of ['overlay.dialog', 'overlay.drawer']) {
    const judged = results.some((r) => r.tier === 'A' && r.overlayExit?.rule === rule && ['restored', 'failed', 'unverifiable'].includes(r.overlayExit.restoration));
    if (!judged) harnessErrors.push(`${rule}: the full sweep never judged focus restoration at Tier A for an overlay an action opened`);
  }
}

// --- Report -----------------------------------------------------------------------

const count = (items, key) => items.reduce((acc, item) => { acc[item[key]] = (acc[item[key]] ?? 0) + 1; return acc; }, {});
const valid = results.filter((r) => r.valid);
const byTier = Object.fromEntries(TIERS.map((tier) => [tier, {
  anchorCaptures: valid.filter((r) => r.tier === tier && r.kind === 'anchor').length,
  probeCaptures: valid.filter((r) => r.tier === tier && r.kind === 'probe').length,
  zoomCaptures: valid.filter((r) => r.tier === tier && (r.kind === 'zoom' || r.kind === 'zoom-transition')).length,
  invalid: results.filter((r) => r.tier === tier && !r.valid).length + errored.filter((e) => e.tier === tier).length,
  blocking: findings.filter((f) => f.tier === tier && f.severity === 'blocking').length,
  pending: findings.filter((f) => f.tier === tier && f.severity === 'measured/pending').length,
}]));
const measure = (key) => count(results.map((r) => ({ status: r.perf?.[key]?.status ?? 'failed' })), 'status');
const clsValues = results.filter((r) => r.perf?.cls?.status === 'measured').map((r) => r.perf.cls.value);
const report = {
  harness: 'web-visual-qa v2',
  statesModule: STATES_MODULE,
  head: (() => { try { return execFileSync('git', ['rev-parse', 'HEAD'], { cwd: HERE }).toString().trim(); } catch { return null; } })(),
  startedAt: new Date(started).toISOString(),
  durationMs,
  workers: lanes.length,
  fullSweep,
  manifest: manifestSummary(),
  states: { registered: STATES.length, selected: new Set(cases.map((c) => c.state.name)).size, applicability },
  executions: {
    scheduled: cases.length,
    validCaptures: valid.length,
    byTier,
    notReached: results.filter((r) => !r.reached).map((r) => ({ state: r.state, viewport: r.viewport, tier: r.tier, ...r.unreached })),
    errored,
    zoom: (() => {
      const zoomCases = cases.filter((c) => c.viewport.zoom);
      const zoomResults = results.filter((r) => r.zoom);
      const sample = zoomResults.find((r) => r.valid && r.kind === 'zoom')?.zoom?.environment ?? null;
      return {
        condition: { ...ZOOM, effective: { width: ZOOM.width / ZOOM.factor, height: ZOOM.height / ZOOM.factor }, method: 'Chrome Settings page zoom (chrome.settingsPrivate.setDefaultZoom), read back from the browser and the page' },
        browser: lanes[0]?.environment ?? null,
        scheduled: { loads: zoomCases.filter((c) => c.viewport.kind === 'zoom').length, transitions: zoomCases.filter((c) => c.viewport.kind === 'zoom-transition').length },
        valid: { loads: zoomResults.filter((r) => r.valid && r.kind === 'zoom').length, transitions: zoomResults.filter((r) => r.valid && r.kind === 'zoom-transition').length },
        qualified: zoomResults.filter((r) => r.valid && r.zoom.qualified).length,
        // §23's WCAG 1.4.4 exception, where it applied: a Workbench at 200%
        // is its unsupported state. Reported, never passed silently.
        workbenchException: Object.entries(zoomResults.filter((r) => r.valid && r.zoom.measured?.workbenchException && r.tier === 'C')
          .reduce((acc, r) => { (acc[r.surface] ??= { captures: 0, statement: r.zoom.measured.workbenchException }).captures += 1; return acc; }, {}))
          .map(([surface, entry]) => ({ surface, ...entry })),
        bySurface: count(zoomResults.filter((r) => r.valid), 'surface'),
        sample: sample && { reported: sample.reported, metrics: sample.metrics, page: sample.page },
      };
    })(),
  },
  findings: { blocking: findings.filter((f) => f.severity === 'blocking').length, pending: findings.filter((f) => f.severity === 'measured/pending').length, byRule: count(findings, 'rule') },
  coverage,
  perf: {
    cls: { statuses: measure('cls'), measured: clsValues.length, min: clsValues.length ? Math.min(...clsValues) : null, max: clsValues.length ? Math.max(...clsValues) : null, nonZero: clsValues.filter((v) => v > 0).length },
    clsPreparation: { statuses: measure('clsPreparation') },
    longTasks: { statuses: measure('longTasks') },
    fonts: count(results.map((r) => ({ fonts: r.fonts?.status === 'measured' ? (r.fonts.content?.length ? r.fonts.content : r.fonts.contextBar).map((f) => f.family).join(' + ') : `failed: ${r.fonts?.why}` })), 'fonts'),
  },
  determinism,
  pressedUnproven,
  harnessErrors,
};
writeFileSync(join(OUT, 'results.json'), JSON.stringify({ ...report, findingsList: findings, cases: results }, null, 2));

const line = (text = '') => process.stdout.write(text + '\n');
line();
line(`${valid.length} valid captures of ${cases.length} scheduled (${STATES.length} registered states, ${report.states.selected} selected) in ${Math.round(durationMs / 1000)}s on ${lanes.length} lane(s)`);
for (const tier of TIERS) {
  const t = byTier[tier];
  line(`  Tier ${tier}: ${t.anchorCaptures} anchor + ${t.probeCaptures} probe${t.zoomCaptures ? ` + ${t.zoomCaptures} zoom` : ''} valid captures, ${t.invalid} invalid; ${t.blocking} blocking, ${t.pending} measured/pending finding(s)`);
}
{
  const z = report.executions.zoom;
  if (z.scheduled.loads + z.scheduled.transitions) {
    const s = z.sample;
    line(`  200% zoom (${z.browser?.product ?? 'browser ?'}): ${z.valid.loads}/${z.scheduled.loads} loads and ${z.valid.transitions}/${z.scheduled.transitions} transitions valid, ${z.qualified} with the zoom proven`
      + (s ? `; ${ZOOM.width}x${ZOOM.height} at page zoom ${s.metrics.pageZoom} -> ${s.page.innerWidth}x${s.page.innerHeight} CSS px, devicePixelRatio ${s.page.dpr}` : ''));
    for (const e of z.workbenchException) line(`  200% zoom, §23 WCAG 1.4.4 Workbench exception: ${e.surface} (${e.captures} capture(s)) — "${e.statement}"`);
  }
}
line(`  CLS (navigation): ${JSON.stringify(report.perf.cls.statuses)}; measured range ${report.perf.cls.min ?? '-'}..${report.perf.cls.max ?? '-'}`);
line(`  CLS (preparation): ${JSON.stringify(report.perf.clsPreparation.statuses)}`);
line(`  long tasks: ${JSON.stringify(report.perf.longTasks.statuses)}`);
line(`  fonts: ${Object.entries(report.perf.fonts).map(([k, v]) => `${k} (${v})`).join('; ')}`);
for (const d of determinism) line(`  determinism ${d.case}: ${d.runs} runs, ${d.reached} reached, ${d.distinctStates} distinct state(s), rows ${d.rows.join('/')}`);
const pending = findings.filter((f) => f.severity === 'measured/pending');
if (pending.length) {
  line(`\n${pending.length} measured/pending finding(s) — reported, never failing (owner in brackets):`);
  const grouped = count(pending.map((f) => ({ key: `${f.rule} @ Tier ${f.tier} [${f.owner}]` })), 'key');
  for (const [key, n] of Object.entries(grouped).sort()) line(`  - ${key}: ${n}`);
}
const blocking = findings.filter((f) => f.severity === 'blocking');
if (blocking.length) {
  line(`\n${blocking.length} BLOCKING finding(s):`);
  for (const f of blocking) line(`  - ${f.state} @ ${f.viewport} [${f.rule}]: ${f.message}`);
}
if (harnessErrors.length) {
  line(`\nHARNESS ERROR(S):`);
  for (const error of harnessErrors) line(`  - ${error}`);
} else if (!blocking.length) {
  line('\nNo blocking findings. Section 26 still requires a person to read the captures.');
}
process.exitCode = exitStatus({ harnessErrors, blocking, keep: flag('keep') });

// The CI job summary: what ran, what blocked, what is measured for later slices.
if (process.env.GITHUB_STEP_SUMMARY) {
  const md = [
    `## Visual QA (harness v2) — ${harnessErrors.length ? 'harness error' : blocking.length ? `${blocking.length} blocking finding(s)` : 'no blocking findings'}`,
    '',
    `${valid.length} valid captures of ${cases.length} scheduled, ${report.states.selected} states, in ${Math.round(durationMs / 1000)}s on ${lanes.length} lanes.`,
    '',
    '| Tier | Valid anchor captures | Valid probe captures | Valid 200% zoom captures | Invalid | Blocking | Measured/pending |',
    '|---|---|---|---|---|---|---|',
    ...TIERS.map((tier) => `| ${tier} | ${byTier[tier].anchorCaptures} | ${byTier[tier].probeCaptures} | ${byTier[tier].zoomCaptures} | ${byTier[tier].invalid} | ${byTier[tier].blocking} | ${byTier[tier].pending} |`),
    '',
    `CLS (navigation): ${JSON.stringify(report.perf.cls.statuses)}, measured range ${report.perf.cls.min ?? '-'}..${report.perf.cls.max ?? '-'}; CLS (preparation): ${JSON.stringify(report.perf.clsPreparation.statuses)}; long tasks: ${JSON.stringify(report.perf.longTasks.statuses)}.`,
    '',
    ...(harnessErrors.length ? ['### Harness errors', ...harnessErrors.map((e) => `- ${e}`), ''] : []),
    ...(blocking.length ? ['### Blocking findings', ...blocking.slice(0, 100).map((f) => `- \`${f.state} @ ${f.viewport}\` [${f.rule}] ${f.message}`), ''] : []),
    '### Measured/pending (never failing)',
    ...Object.entries(count(pending.map((f) => ({ key: `${f.rule} @ Tier ${f.tier} (${f.owner})` })), 'key')).sort().map(([key, n]) => `- ${key}: ${n}`),
  ];
  try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, md.join('\n') + '\n'); } catch { /* summary is a convenience */ }
}
line(`results: ${join(OUT, 'results.json')}`);
