#!/usr/bin/env node
/**
 * MAVI visual-QA pass — Harness v2 (specification §26 as amended in v2.0;
 * acceptance register V1-V5, P1).
 *
 *   node tools/web-visual-qa/run.mjs [--states a,b] [--tiers A,B] [--widths 1366,2560]
 *                                    [--zoom only|none] [--workers 3] [--repeat 5] [--keep] [--build]
 *                                    [--shard i/n]
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
 * `--shard i/n` (CI) runs the i-th of n deterministic shards of the same plan
 * (engine.partitionCases: a state and its loading-pair partner in one shard)
 * and records the whole plan beside its own cases, so aggregate.mjs can prove
 * every planned case ran exactly once and apply the sweep-wide checks that a
 * shard cannot judge alone. A shard's own exit status covers only what it ran.
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
    import(STATES_MODULE ? pathToFileURL(STATES_MODULE).href : './states.mjs'), import('./semantics.mjs'), import('./a11y.mjs'), import('./probes.mjs'),
  ]);
} catch (error) {
  fatal(`HARNESS ERROR: a harness module did not load: ${error.stack || error}\n`);
}
const [
  {
    focusAssertions, overlayExitProbe, overlayFocusProbe, overlayOpened, overlayReady, pageAssertions, stickyProbe, toExpression, workspaceAssertions,
    zoomAssertions, zoomBeforeChange, zoomEnvironment, zoomTextBaseline, zoomTextCompare, zoomTransitionProbe,
  },
  { launch },
  { caseKey, createLedger, exitStatus, HarnessError, partitionCases, planCases, settle, sweepChecks, zoomQualification },
  { CONDITIONS, ensureFootage },
  { manifestSummary, OPERATOR_SURFACES, RULES, TEXT_SPACING_CONDITION, TIERS, validateManifest, ZOOM_CONDITION },
  { startServer },
  { OBSERVERS, perfCollect, TRANSIENT },
  { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM },
  { tierCLedgerSemantics },
  { a11yAssertions, a11yLiveCheck, a11yLiveMark, a11yNamesJudge, a11yTextSpacingEnvironment },
  { probeHoverContent, probeShortcuts },
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
// X1: the text-spacing lane (WCAG 1.4.12), `--text-spacing only|none` as `--zoom`.
const onlyTextSpacing = arg('text-spacing', null);
if (onlyTextSpacing !== null && onlyTextSpacing !== 'only' && onlyTextSpacing !== 'none') fatal(`--text-spacing takes "only" or "none", not "${onlyTextSpacing}"`);
// A count that is not a positive integer is refused: NaN would plan cases and
// run none of them.
const positiveInt = (name, fallback) => {
  const raw = arg(name, String(fallback));
  if (!/^[1-9][0-9]*$/.test(String(raw))) fatal(`--${name} must be a positive integer, not "${raw}"`);
  return Number(raw);
};
const repeat = positiveInt('repeat', 1);
// `--shard i/n`: refused unless it names one of n shards.
const shardArg = arg('shard', null);
let shard = null;
if (shardArg !== null) {
  const m = /^([0-9]+)\/([1-9][0-9]*)$/.exec(String(shardArg));
  if (!m || Number(m[1]) >= Number(m[2])) fatal(`--shard takes i/n with 0 <= i < n, not "${shardArg}"`);
  shard = { index: Number(m[1]), count: Number(m[2]) };
}
// The whole plan, with nothing left out: the sweep-wide obligations hold here.
const completeSelection = !onlyStates && !onlyTiers && !onlyWidths && !onlyZoom && !onlyTextSpacing && repeat === 1 && !STATES_MODULE;
// A shard is never the full sweep by itself; aggregate.mjs is, over every shard.
const fullSweep = completeSelection && !shard;
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
    textSpacing: TEXT_SPACING_CONDITION, onlyStates, onlyTiers, onlyWidths, onlyZoom, onlyTextSpacing, repeat,
  });
} catch (error) {
  fatal(String(error.message || error) + '\n');
}
const { applicability } = plan;
if (!plan.cases.length) { fatal('nothing to run\n'); }
const partition = shard ? partitionCases(plan.cases, { ...shard, pairs: LOADING_PAIRS }) : null;
const cases = partition ? partition.selected : plan.cases;
if (partition && !cases.length) { fatal(`shard ${shard.index}/${shard.count} selects no case of ${plan.cases.length}\n`); }

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
  // `textSpacing`: whether the lane's server serves the WCAG 1.4.12 overrides
  // in the document head — set per case, before its document is requested.
  const lane = { index, scenario: {}, footage: 'saturated', zoom: 1, textSpacing: false };
  lane.server = await startServer({
    distDir: join(WEB, 'dist'),
    fixtureDir: join(HERE, 'fixtures'),
    scenario: () => lane.scenario,
    footage: () => ensureFootage(MEDIA, lane.footage),
    textSpacing: () => lane.textSpacing,
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
  const browser = lane.browser;

  // The previous document goes first, then its held requests: a page whose
  // held request is destroyed while it is still alive retries it, and that
  // retry would land on this case's scenario and consume the first answer of
  // its sequenced fixtures (a loading Ledger followed by a degraded one, in a
  // sharded sweep, showed the failed refresh where the retained one was due).
  // A blank document has nothing to retry.
  await browser.goto('about:blank');
  lane.server.releaseHung();
  lane.scenario = state.api ?? {};
  lane.server.resetSequences();
  lane.textSpacing = Boolean(viewport.textSpacing);
  lane.footage = state.footage ?? 'saturated';
  await browser.viewport(viewport.width, viewport.height);
  // A fresh document for a load: a blank document first (Chromium holds
  // media decoders across same-origin navigations), then storage cleared
  // from a same-origin page that boots nothing, so a stored preference
  // cannot leak between cases, and the state's own preference written
  // there before the surface boots.
  const freshDocument = async () => {
    await browser.goto('about:blank');
    await browser.goto(lane.server.origin + '/__blank');
    await browser.evaluate('(() => { try { window.localStorage.clear(); } catch { /* blocked */ } return true; })()');
    if (state.storage) {
      await browser.evaluate(`(() => { try { for (const [key, value] of Object.entries(${JSON.stringify(state.storage)})) window.localStorage.setItem(key, value); } catch { /* blocked */ } return true; })()`);
    }
  };
  // T3: the browser's page zoom for this case — 100% unless it is a zoom case
  // — set before the page loads and read back from the browser. A zoom that
  // cannot be set fails the case (a harness fault), never runs it at another.
  const startZoom = viewport.zoom?.[0] ?? 1;
  // T3: a case that begins at 200% — a load, or a transition that starts
  // there — is compared with the same state at 100% (WCAG 1.4.4): the state
  // the page reaches at 100% on the same viewport, with the same fixtures and
  // its Tier A preparation (a probe's base state), its text recorded as the
  // baseline. A baseline that cannot be reached is a harness fault: the 200%
  // capture is then not judged at all, never passed.
  let textBaseline = null;
  let unreached = null;
  const unreach = (stage, reason) => { if (!unreached) unreached = { stage, reason }; };
  // Every zoom case takes the baseline: a load and a 200% start compare
  // with it at once, a change back to 200% after its action compares with
  // it at the end.
  if (viewport.zoom) {
    const baseName = c.state.probeOf ?? c.state.name;
    const baseState = STATES.find((s) => s.name === baseName) ?? c.state;
    const baseView = baseState.atTier?.A ? { ...baseState, ...baseState.atTier.A } : baseState;
    if (lane.zoom !== 1) { lane.zoom = null; lane.zoom = await browser.pageZoom(1); }
    // The baseline begins as the case will.
    await freshDocument();
    await browser.goto(lane.server.origin + baseView.path);
    const baseLoaded = await settle(lane, baseView, { timeoutMs: SETTLE_TIMEOUT_MS, beforePreparation: Boolean(baseView.prepare) });
    if (!baseLoaded.ok) unreach('zoom text baseline', `the state at 100% did not settle within ${SETTLE_TIMEOUT_MS}ms: ${baseLoaded.why.join('; ')}`);
    else if (baseView.prepare) {
      let prepared = false;
      try { prepared = Boolean(await browser.evaluate(`(async () => await ${baseView.prepare})()`)); } catch (error) { unreach('zoom text baseline', `its preparation at 100% failed: ${String(error.message || error).split('\n')[0]}`); }
      if (prepared) {
        const ready = await settle(lane, baseView, { timeoutMs: SETTLE_TIMEOUT_MS });
        if (!ready.ok) unreach('zoom text baseline', `did not settle after its preparation at 100% within ${SETTLE_TIMEOUT_MS}ms: ${ready.why.join('; ')}`);
      } else if (!unreached) unreach('zoom text baseline', 'its preparation at 100% reported that the state was not reached');
    }
    if (!unreached) {
      const metrics = await browser.layoutMetrics();
      if (Math.abs(metrics.pageZoom - 1) > 1e-3) unreach('zoom text baseline', `the baseline was taken at page zoom ${metrics.pageZoom}, not 100%`);
      else {
        textBaseline = await browser.evaluate(toExpression(zoomTextBaseline));
        if (!textBaseline.holders) unreach('zoom text baseline', 'the state at 100% holds no text to be the baseline');
      }
    }
    // The baseline's page is left behind as any other case's would be: the
    // document gone first (so nothing of it retries), then held requests
    // released and sequenced fixtures rewound, and the stored preferences it
    // may have written cleared with the state's own put back, so the 200%
    // load begins as it would alone.
    await browser.goto('about:blank');
    lane.server.releaseHung();
    lane.server.resetSequences();
  }
  if (lane.zoom !== startZoom) {
    lane.zoom = null;
    lane.zoom = await browser.pageZoom(startZoom);
  }
  await freshDocument();
  await browser.goto(lane.server.origin + state.path);

  // V3: the state is reached when the page and the server say so.
  const loaded = await settle(lane, start, { timeoutMs: SETTLE_TIMEOUT_MS, beforePreparation: Boolean(start.prepare) });
  const settledAt = await browser.evaluate('performance.now()');
  // An overlay already open when the page settles was opened by its URL, not
  // by an action: §20 restoration to an invoking control does not apply to it.
  const openOnLoad = await browser.evaluate(`Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'))`);
  if (!loaded.ok) unreach('navigation settle', `did not settle within ${SETTLE_TIMEOUT_MS}ms: ${loaded.why.join('; ')}`);
  let reached = !unreached;

  let prepareStart = null;
  let preparedAt = null;
  let afterPrepare = null;
  if (start.prepare && reached) {
    prepareStart = await browser.evaluate('window.__vqa.mark("prepare-start")');
    // X1 (a11y.live-regions): the live regions the page has before its
    // preparation, so a region that appears already populated is caught.
    await browser.evaluate(toExpression(a11yLiveMark));
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
      if (afterPrepare.ok) {
        preparedAt = await browser.evaluate('performance.now()');
        const live = await browser.evaluate(toExpression(a11yLiveCheck));
        if (live.judged) markEvaluated(c, ['a11y.live-regions']);
        for (const finding of live.findings) add(finding.rule, finding.message);
      } else unreach('settle after preparation', `did not settle after its preparation within ${SETTLE_TIMEOUT_MS}ms: ${afterPrepare.why.join('; ')}`);
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
    // The text comparison (WCAG 1.4.4): the page's text against its baseline,
    // the smallest matched ratio turned into a physical size by the browser's
    // own zoom factors. Every zoom case makes exactly one such comparison —
    // a load or a 200% start against the 100% baseline, a change that zooms
    // in against the step before it — or it is a fault, never a pass.
    let comparisons = 0;
    const compareText = async (baseline, from, to, live, zoomFrom, zoomTo, where) => {
      const text = await browser.evaluate(toExpression(zoomTextCompare, { baseline, from, to, live }));
      if (text.fault) { unreach('zoom text comparison', text.fault); reached = false; return; }
      // Nothing matched: the physical size is unproven, which is a fault
      // (the comparison could not be made), not a pass.
      if (!text.matched) { unreach('zoom text comparison', `none of the ${text.compared} pieces of text at ${to} could be matched to the ${from} baseline, so their size is unproven`); reached = false; return; }
      comparisons += 1;
      for (const message of text.changed) zoomFail(`${where}${message}`);
      // Against the frozen condition's factor, by the browser's own zoom
      // factors at each side: a "200%" that the browser applies as 100%
      // draws its text at 1x, and fails here as well as in the environment.
      const physical = text.minRatio === null ? null : text.minRatio * (zoomTo / zoomFrom);
      const expected = ZOOM_CONDITION.factor;
      if (physical !== null && physical < expected - 0.02) zoomFail(`${where}text is drawn at only ${Math.round(physical * 100) / 100}x its ${from} size at ${to}, not the ${expected}x the browser's zoom gives`);
      zoom.text = { baselineHolders: baseline.holders, compared: text.compared, matched: text.matched, unmatched: text.unmatched, physical, expected, findings: text.changed.length, comparisons };
      zoom.textComparisons = [...(zoom.textComparisons ?? []), { from, to, ...zoom.text }];
    };
    let previous = reached ? await qualify(viewport.zoom[0]) : null;
    if (previous) {
      zoom.steps.push({ factor: previous.factor, focus: null, environment: previous });
      if (viewport.zoom.length > 1) for (const problem of previous.problems) zoomFail(`at the start (${previous.factor * 100}%): ${problem}`);
      // A transition that starts at 200% judges the state it prepared there
      // before it leaves it (a drawer opened at 200%), as a load would — its
      // text against the 100% baseline included.
      if (viewport.zoom.length > 1 && viewport.zoom[0] !== 1) {
        const atStart = await browser.evaluate(toExpression(zoomAssertions, { tier: viewport.startTier }));
        for (const finding of atStart.findings) zoomFail(`at the start (${previous.factor * 100}%): ${finding.message}`);
        await compareText(textBaseline, '100%', `${previous.factor * 100}%`, false, 1, previous.metrics.pageZoom, `at the start (${previous.factor * 100}%): `);
      }
    }
    // What every piece of text measures at this step, for the next change.
    let liveBaseline = reached && viewport.zoom.length > 1 ? await browser.evaluate(toExpression(zoomTextBaseline)) : null;
    for (let index = 1; reached && index < viewport.zoom.length; index += 1) {
      const factor = viewport.zoom[index];
      const focusBefore = await browser.evaluate(toExpression(zoomBeforeChange));
      lane.zoom = null;
      lane.zoom = await browser.pageZoom(factor);
      const last = index === viewport.zoom.length - 1;
      // Each step settles on the declared state at the tier it lands in —
      // the state's view there, as a load's; the transition's own at its
      // last step — and only before a final action on loading alone, the
      // action producing what the transition declares (Codex P1).
      const stepView = last ? end : view(tierOf(ZOOM_CONDITION.width / factor));
      const after = await settle(lane, stepView, { timeoutMs: SETTLE_TIMEOUT_MS, beforePreparation: last && Boolean(transition?.then) });
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
      // Text grows with the zoom (WCAG 1.4.4): on a step that zooms in, the
      // page's text against the step before it — words matched, the live
      // elements too — and its physical size by the browser's factors. A
      // step back out to 100% returns to the desktop composition and its own
      // type scale, which 1.4.4 does not judge.
      if (factor > previous.factor) {
        await compareText(liveBaseline, `${previous.factor * 100}%`, `${factor * 100}%`, true, previous.metrics.pageZoom, environment.metrics.pageZoom, `at ${factor * 100}%: `);
        if (!reached) break;
      }
      liveBaseline = await browser.evaluate(toExpression(zoomTextBaseline));
      if (!last) for (const problem of environment.problems) zoomFail(`at ${factor * 100}%: ${problem}`);
      // A step the transition passes through is judged as a load would be —
      // every zoom check at the composition it shows — before it leaves it;
      // the last step is judged below, with the rest of the capture.
      if (!last) {
        const atStep = await browser.evaluate(toExpression(zoomAssertions, { tier: tierOf(ZOOM_CONDITION.width / factor) }));
        for (const finding of atStep.findings) zoomFail(`at ${factor * 100}%: ${finding.message}`);
      }
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
      // A case that ends at 200% — a load, or a transition with its final
      // action done — has its text compared with the 100% baseline as it
      // will be captured.
      if (viewport.zoom[viewport.zoom.length - 1] !== 1) await compareText(textBaseline, '100%', '200%', false, 1, final.metrics.pageZoom, '');
    }
  }

  // X1 (a11y.text-spacing): a spacing case proves the overrides are in force
  // from computed style, or it is not reached — never judged as if they were.
  let textSpacing = null;
  if (viewport.textSpacing && reached) {
    const env = await browser.evaluate(toExpression(a11yTextSpacingEnvironment));
    textSpacing = { ...env, inForce: env.problems.length === 0, overrides: TEXT_SPACING_CONDITION.overrides };
    if (env.problems.length) { unreach('text-spacing environment', `the overrides are not in force: ${env.problems.join('; ')}`); reached = false; }
    else markEvaluated(c, ['a11y.text-spacing']);
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
  let a11y = null;
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
    // X1 (§23): the page rules of a11y.mjs, then the names Chromium computes
    // for the controls they tagged (cdp.axNames) and the verdicts that need them.
    const x1 = await browser.evaluate(toExpression(a11yAssertions, input));
    markEvaluated(c, x1.evaluated);
    for (const finding of x1.findings) add(finding.rule, finding.message);
    // Chromium names the tagged controls. A control the page replaced in
    // between (a re-render) carries no tag: the pass is taken once more for
    // those, and what is still unresolved is counted, never judged.
    let names = await browser.axNames('[data-vqa-ax]');
    if (names.length < x1.controls.length) {
      await browser.evaluate(`(() => { for (const el of document.querySelectorAll('[data-vqa-ax]')) el.removeAttribute('data-vqa-ax'); return true; })()`);
      const again = await browser.evaluate(toExpression(a11yAssertions, { ...input, namesOnly: true }));
      x1.controls = again.controls; x1.measured.tooltipList = again.measured.tooltipList;
      names = await browser.axNames('[data-vqa-ax]');
    }
    const judged = await browser.evaluate(toExpression(a11yNamesJudge, { controls: x1.controls, names, tooltips: x1.measured.tooltipList }));
    // Controls still unnamed after the second pass were replaced again: the
    // names rules did not run on them — a fault of the case, never a pass.
    if (judged.measured.unresolved > 0) {
      unreach('accessible names', `${judged.measured.unresolved} control(s) re-rendered between tagging and the accessibility-tree read, twice`);
      reached = false;
    }
    markEvaluated(c, judged.evaluated);
    for (const finding of judged.findings) add(finding.rule, finding.message);
    a11y = { ...x1.measured, tooltipList: undefined, names: judged.measured };
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
      // Controls the page offers — not disabled, not behind an open overlay,
      // not taken out of the tab order while hidden — of which the harness
      // judged none: the rule did not run on them, a fault, not a pass.
      const offered = zoomed.measured.candidates - ['disabled', 'a hidden input', 'inside an inert region', 'hidden and out of the tab order', 'not rendered']
        .reduce((sum, reason) => sum + (zoomed.measured.skipped[reason] ?? 0), 0);
      if (offered > 0 && zoomed.measured.controls === 0) {
        unreach('zoom controls', `${offered} control(s) offered and none judged (${JSON.stringify(zoomed.measured.skipped)})`);
        reached = false;
      }
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
  // X1 (probes.mjs): the page's custom tooltips driven through the input
  // pipeline (a11y.hover-content, WCAG 1.4.13), then a shortcut typed into
  // the first text field (a11y.shortcuts-in-text-entry, WCAG 2.1.4) — before
  // the overlay exit, which closes what the tooltips may live in.
  let hover = null;
  let shortcuts = null;
  if (reached) {
    const h = await probeHoverContent(browser);
    for (const message of h.findings) add('a11y.hover-content', message);
    if (h.judged) markEvaluated(c, ['a11y.hover-content']);
    hover = h.measured;
    const s = await probeShortcuts(browser);
    markEvaluated(c, s.evaluated);
    for (const finding of s.findings) add(finding.rule, finding.message);
    shortcuts = s.measured;
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
  // Held requests are released at the start of the next case, after its
  // document is gone (above); releasing them here, with this page alive,
  // would make it retry into the next case's scenario.

  const result = {
    state: state.name, viewport: viewport.label, tier: viewport.tier, kind: viewport.kind, attempt: c.attempt, lane: lane.index,
    settled: { ok: loaded.ok, ms: loaded.ms, probes: loaded.probes, why: loaded.ok ? undefined : loaded.why },
    prepared: state.prepare ? { ok: Boolean(afterPrepare?.ok), ms: afterPrepare?.ms ?? null, interaction: state.interaction ?? null } : null,
    reached,
    valid: reached,
    unreached,
    surface: c.surface,
    ...(zoom ? { zoom: { path: zoom.path, effective: zoom.effective, qualified: zoom.qualified ?? false, evaluated: zoom.evaluated, steps: zoom.steps, environment: zoom.environment ?? null, measured: zoom.measured ?? null, text: zoom.text ?? null, textComparisons: zoom.textComparisons ?? [] } } : {}),
    ...(textSpacing ? { textSpacing } : {}),
    a11y, hover, shortcuts,
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
        errored.push({ state: c.state.name, viewport: c.viewport.label, tier: c.viewport.tier, attempt: c.attempt, stage: 'exception', reason: String(error.message || error).split('\n')[0] });
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

// The checks that read across cases (engine.sweepChecks): a loading Ledger
// against its table, pressed treatments proven somewhere, every scheduled case
// run and reached, and — on the full sweep — every surface judged at 200%, no
// blocking rule unevaluated, overlay restoration judged at Tier A. A shard
// runs only what is its own to judge (every case ran and reached); the rest
// is the aggregate's, over every shard.
const sweep = sweepChecks({
  results, cases, errored, ledger, surfaces: OPERATOR_SURFACES,
  loadingPairs: shard ? [] : LOADING_PAIRS, fullSweep, plannedKeys: cases.map(caseKey),
});
harnessErrors.push(...sweep.faults);
const pressedUnproven = sweep.pressedUnproven;

// --- Report -----------------------------------------------------------------------

const count = (items, key) => items.reduce((acc, item) => { acc[item[key]] = (acc[item[key]] ?? 0) + 1; return acc; }, {});
const valid = results.filter((r) => r.valid);
const byTier = Object.fromEntries(TIERS.map((tier) => [tier, {
  anchorCaptures: valid.filter((r) => r.tier === tier && r.kind === 'anchor').length,
  probeCaptures: valid.filter((r) => r.tier === tier && r.kind === 'probe').length,
  spacingCaptures: valid.filter((r) => r.tier === tier && r.kind === 'text-spacing').length,
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
  // A shard says which of how many it is and lists the whole plan beside its
  // own selection, so the aggregate can prove the plan ran exactly once.
  shard: shard ? { ...shard, completeSelection, planned: partition.planned, selected: partition.selectedKeys } : null,
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
  // X1: the text-spacing lane by composition, and the rules driven through the input pipeline.
  textSpacing: (() => {
    const spacing = results.filter((r) => r.kind === 'text-spacing');
    const by = {};
    for (const r of spacing) { (by[r.viewport] ??= { scheduled: 0, valid: 0, inForce: 0 }).scheduled += 1; if (r.valid) by[r.viewport].valid += 1; if (r.textSpacing?.inForce) by[r.viewport].inForce += 1; }
    return { condition: TEXT_SPACING_CONDITION, scheduled: cases.filter((c) => c.viewport.textSpacing).length, valid: spacing.filter((r) => r.valid).length, inForce: spacing.filter((r) => r.textSpacing?.inForce).length, byViewport: by };
  })(),
  a11y: {
    hover: { cases: results.filter((r) => r.hover?.judged).length, tooltips: results.reduce((n, r) => n + (r.hover?.judged ?? 0), 0), escapeSkipped: results.reduce((n, r) => n + (r.hover?.escapeSkipped ?? 0), 0), escapeClosedOverlay: results.reduce((n, r) => n + (r.hover?.escapeClosedOverlay ?? 0), 0) },
    shortcuts: { cases: results.filter((r) => r.shortcuts?.field).length },
    names: { controls: results.reduce((n, r) => n + (r.a11y?.names?.controls ?? 0), 0), fields: results.reduce((n, r) => n + (r.a11y?.names?.fields ?? 0), 0), tooltips: results.reduce((n, r) => n + (r.a11y?.names?.tooltips ?? 0), 0) },
    targets: results.reduce((n, r) => n + (r.a11y?.targets?.judged ?? 0), 0),
    readingOrder: results.filter((r) => r.a11y?.readingOrder?.containers).length,
  },
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
line(`${valid.length} valid captures of ${cases.length} scheduled (${STATES.length} registered states, ${report.states.selected} selected) in ${Math.round(durationMs / 1000)}s on ${lanes.length} lane(s)`
  + (shard ? ` — shard ${shard.index}/${shard.count} of ${plan.cases.length} planned case(s); the sweep-wide checks are aggregate.mjs's` : ''));
for (const tier of TIERS) {
  const t = byTier[tier];
  line(`  Tier ${tier}: ${t.anchorCaptures} anchor + ${t.probeCaptures} probe${t.zoomCaptures ? ` + ${t.zoomCaptures} zoom` : ''}${t.spacingCaptures ? ` + ${t.spacingCaptures} text-spacing` : ''} valid captures, ${t.invalid} invalid; ${t.blocking} blocking, ${t.pending} measured/pending finding(s)`);
}
if (report.textSpacing.scheduled) {
  const ts = report.textSpacing;
  line(`  text spacing (WCAG 1.4.12): ${ts.valid}/${ts.scheduled} valid with the overrides proven in force on ${ts.inForce}; ${Object.entries(ts.byViewport).map(([v, n]) => `${v} ${n.valid}/${n.scheduled}`).join(', ')}`);
}
line(`  a11y (X1): ${report.a11y.names.controls} controls named, ${report.a11y.names.fields} fields, ${report.a11y.names.tooltips} tooltips classed, ${report.a11y.targets} pointer targets, ${report.a11y.hover.tooltips} tooltips driven in ${report.a11y.hover.cases} case(s), shortcuts typed in ${report.a11y.shortcuts.cases} case(s), reading order in ${report.a11y.readingOrder} case(s)`);
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
