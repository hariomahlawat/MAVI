#!/usr/bin/env node
/**
 * MAVI visual-QA pass — Harness v2 (specification §26 as amended in v2.0;
 * acceptance register V1-V5, P1).
 *
 *   node tools/web-visual-qa/run.mjs [--states a,b] [--tiers A,B] [--widths 1366,2560]
 *                                    [--workers 3] [--repeat 5] [--keep] [--build]
 *
 * Runs the real production bundle (build it first, or pass --build) in real
 * Chromium at every tier anchor each state applies to, plus each state's probe
 * widths. Every finding names a manifest rule and takes that rule's severity
 * at the tier of the width it was found at (manifest.mjs).
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
import { appendFileSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { cpus } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { focusAssertions, overlayExitProbe, overlayOpened, overlayReady, pageAssertions, stickyProbe, toExpression, workspaceAssertions } from './assertions.mjs';
import { launch } from './cdp.mjs';
import { createLedger, exitStatus, HarnessError, planCases, settle } from './engine.mjs';
import { CONDITIONS, ensureFootage } from './footage.mjs';
import { manifestSummary, RULES, TIERS, validateManifest } from './manifest.mjs';
import { startServer } from './server.mjs';
import { OBSERVERS, perfCollect, TRANSIENT } from './settle.mjs';
import { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf } from './states.mjs';

// A fault outside the case loop is a harness failure (exit 2), never the
// blocking-finding status an uncaught error would otherwise produce.
process.on('uncaughtException', (error) => { process.stderr.write(`HARNESS ERROR: ${error.stack || error}\n`); process.exit(2); });
process.on('unhandledRejection', (error) => { process.stderr.write(`HARNESS ERROR: ${error?.stack || error}\n`); process.exit(2); });

const HERE = dirname(fileURLToPath(import.meta.url));
const WEB = join(HERE, '..', '..', 'src', 'web', 'mavi-web');
const OUT = join(HERE, '.captures');

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
const repeat = Math.max(1, Number(arg('repeat', 1)));
const fullSweep = !onlyStates && !onlyTiers && !onlyWidths && repeat === 1;
const workers = Math.max(1, Number(arg('workers', Math.min(4, Math.max(1, cpus().length - 1)))));

const manifestProblems = validateManifest();
if (manifestProblems.length) {
  process.stderr.write('assertion manifest is invalid:\n  ' + manifestProblems.join('\n  ') + '\n');
  process.exit(2);
}
for (const name of onlyStates ?? []) {
  if (!STATES.some((state) => state.name === name)) { process.stderr.write(`unknown state ${name}\n`); process.exit(2); }
}

let plan;
try {
  plan = planCases({
    states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf,
    onlyStates, onlyTiers, onlyWidths, repeat,
  });
} catch (error) {
  process.stderr.write(String(error.message || error) + '\n');
  process.exit(2);
}
const { cases, applicability } = plan;
if (!cases.length) { process.stderr.write('nothing to run\n'); process.exit(2); }

if (flag('build')) {
  process.stdout.write('building frontend…\n');
  execFileSync('npm', ['run', 'build'], { cwd: WEB, stdio: 'inherit', shell: process.platform === 'win32' });
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });
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
  const lane = { index, scenario: {}, footage: 'saturated' };
  lane.server = await startServer({
    distDir: join(WEB, 'dist'),
    fixtureDir: join(HERE, 'fixtures'),
    scenario: () => lane.scenario,
    footage: () => ensureFootage(MEDIA, lane.footage),
  });
  lane.browser = await launch();
  await lane.browser.addInitScript(OBSERVERS);
  return lane;
}

const results = [];
const harnessErrors = [];
const ledger = createLedger(RULES);
const { findings, coverage } = ledger;
const record = (c, rule, message) => ledger.record(c, rule, message);
const markEvaluated = (c, rules) => ledger.markEvaluated(c, rules);

async function runCase(lane, c) {
  const { state, viewport } = c;
  const where = `${state.name} @ ${viewport.label}${c.attempt > 1 ? ` #${c.attempt}` : ''}`;
  const name = `${state.name}--${viewport.label}${repeat > 1 ? `--${c.attempt}` : ''}`;
  const caseFindings = [];
  const add = (rule, message) => caseFindings.push(record(c, rule, message));
  const browser = lane.browser;

  lane.server.releaseHung();
  lane.scenario = state.api ?? {};
  lane.server.resetSequences();
  lane.footage = state.footage ?? 'saturated';
  await browser.viewport(viewport.width, viewport.height);
  // A blank document first: Chromium holds media decoders across same-origin
  // navigations. Then storage is cleared from a same-origin page that boots
  // nothing, so a stored preference cannot leak between cases and a sequenced
  // fixture is not consumed before the case begins.
  await browser.goto('about:blank');
  await browser.goto(lane.server.origin + '/__blank');
  await browser.evaluate('(() => { try { window.localStorage.clear(); } catch { /* blocked */ } return true; })()');
  await browser.goto(lane.server.origin + state.path);

  // V3: the state is reached when the page and the server say so.
  const loaded = await settle(lane, state, { timeoutMs: SETTLE_TIMEOUT_MS, beforePreparation: Boolean(state.prepare) });
  const settledAt = await browser.evaluate('performance.now()');
  // An overlay already open when the page settles was opened by its URL, not
  // by an action: §20 restoration to an invoking control does not apply to it.
  const openOnLoad = await browser.evaluate(`Boolean(document.querySelector('[role="dialog"][aria-modal="true"]'))`);
  let reached = loaded.ok;
  if (!loaded.ok) add('harness.state-reached', `did not settle within ${SETTLE_TIMEOUT_MS}ms: ${loaded.why.join('; ')}`);

  let prepareStart = null;
  let prepareEnd = null;
  let afterPrepare = null;
  if (state.prepare && reached) {
    prepareStart = await browser.evaluate('window.__vqa.mark("prepare-start")');
    let prepared = false;
    try {
      // The preparation resolves when the outcome of its action is on screen,
      // so its own span is the interaction's window; the settle probes that
      // follow are the harness's work and are kept out of it.
      prepared = Boolean(await browser.evaluate(`(async () => { const ok = await ${state.prepare}; window.__vqa.mark('prepare-end'); return ok; })()`));
    } catch (error) {
      add('harness.state-reached', `preparation failed: ${String(error.message || error).split('\n')[0]}`);
    }
    if (prepared) {
      afterPrepare = await settle(lane, state, { timeoutMs: SETTLE_TIMEOUT_MS });
      if (afterPrepare.ok) prepareEnd = await browser.evaluate('window.__vqa.marks["prepare-end"] ?? null');
      else add('harness.state-reached', `did not settle after its preparation within ${SETTLE_TIMEOUT_MS}ms: ${afterPrepare.why.join('; ')}`);
    } else if (!caseFindings.length) {
      add('harness.state-reached', 'preparation reported that the state was not reached');
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
      if (state.prepare && Date.now() - lastSeek > 1500) { await browser.evaluate(state.prepare).catch(() => false); lastSeek = Date.now(); }
    }
    if (!overlay.ok) { add('harness.state-reached', `overlay not ready for capture: ${overlay.why}`); reached = false; }
  }

  const input = {
    tier: viewport.tier, width: viewport.width, fullWidth: state.fullWidth ?? null,
    archetype: state.archetype ?? null, holds: state.holds ?? null,
  };
  let page = null;
  let focus = null;
  let workspace = null;
  if (reached) {
    // Order matters: the page rules read the resting state; the focus pass
    // then moves focus through every control and leaves it on the first.
    page = await browser.evaluate(toExpression(pageAssertions, input));
    focus = await browser.evaluate(toExpression(focusAssertions));
    workspace = state.archetype ? await browser.evaluate(toExpression(workspaceAssertions, input)) : null;
    for (const part of [page, focus, workspace].filter(Boolean)) {
      markEvaluated(c, part.evaluated);
      for (const finding of part.findings) add(finding.rule, finding.message);
    }
    markEvaluated(c, ['harness.focus-coverage']);
    const skippedTotal = Object.values(focus.skipped).reduce((sum, count) => sum + count, 0);
    if (focus.discovered !== focus.checked + skippedTotal) {
      add('harness.focus-coverage', `${focus.discovered} discovered, ${focus.checked} checked, ${skippedTotal} skipped`);
    }
  }
  markEvaluated(c, ['harness.state-reached', 'page.uncaught-error', 'page.resource-error']);

  // P1 and V5 measurements: recorded, never pass/fail.
  const perf = await browser.evaluate(toExpression(perfCollect, { holds: state.holds ?? null, settledAt, prepareStart, prepareEnd }));
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
  try {
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

  const capture = `${name}.png`;
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
      }
    }
  }
  let overlayExit = null;
  if (reached && page?.shell?.modals) {
    // §15, §20: Escape leaves the overlay and focus goes back to the control
    // that opened it — the invoker the observers recorded as focus entered it.
    overlayExit = await browser.evaluate(toExpression(overlayOpened));
    if (overlayExit) {
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

  for (const problem of browser.problems()) add('page.uncaught-error', problem);
  const failing = (value) => value === 'unavailable' || (value !== null && typeof value === 'object' && typeof value.status === 'number');
  const expectedPaths = Object.entries(state.api ?? {})
    .filter(([, value]) => failing(value) || (value !== null && typeof value === 'object' && Array.isArray(value.sequence) && value.sequence.some(failing)))
    .map(([key]) => (key.includes(' ') ? key.slice(key.indexOf(' ') + 1) : key));
  for (const problem of browser.resourceErrors()) {
    if (!expectedPaths.some((path) => problem.includes(path))) add('page.resource-error', problem);
  }
  lane.server.releaseHung();

  const result = {
    state: state.name, viewport: viewport.label, tier: viewport.tier, kind: viewport.kind, attempt: c.attempt, lane: lane.index,
    settled: { ok: loaded.ok, ms: loaded.ms, probes: loaded.probes, why: loaded.ok ? undefined : loaded.why },
    prepared: state.prepare ? { ok: Boolean(afterPrepare?.ok), ms: afterPrepare?.ms ?? null } : null,
    reached,
    capture,
    pageWidth: page?.pageWidth ?? null,
    shell: page?.shell ?? null,
    focus: focus ? { discovered: focus.discovered, checked: focus.checked, skipped: focus.skipped } : null,
    workspace: workspace?.measured ?? null,
    perf, fonts, sticky, overlayExit, signature,
    findings: caseFindings.map(({ rule, severity, message }) => ({ rule, severity, message })),
  };
  writeFileSync(join(OUT, `${name}.json`), JSON.stringify(result, null, 2));
  results.push(result);
  const blocking = caseFindings.filter((f) => f.severity === 'blocking').length;
  process.stdout.write(`  ${blocking ? 'FAIL' : caseFindings.length ? 'diag' : ' ok '}  ${where}${reached ? '' : '  (state not reached)'}\n`);
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

// Non-vacuity: on the full sweep every blocking assertion must have run.
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
const byTier = Object.fromEntries(TIERS.map((tier) => [tier, {
  anchorCaptures: results.filter((r) => r.tier === tier && r.kind === 'anchor').length,
  probeCaptures: results.filter((r) => r.tier === tier && r.kind === 'probe').length,
  blocking: findings.filter((f) => f.tier === tier && f.severity === 'blocking').length,
  pending: findings.filter((f) => f.tier === tier && f.severity === 'measured/pending').length,
}]));
const measure = (key) => count(results.map((r) => ({ status: r.perf?.[key]?.status ?? 'failed' })), 'status');
const clsValues = results.filter((r) => r.perf?.cls?.status === 'measured').map((r) => r.perf.cls.value);
const report = {
  harness: 'web-visual-qa v2',
  head: (() => { try { return execFileSync('git', ['rev-parse', 'HEAD'], { cwd: HERE }).toString().trim(); } catch { return null; } })(),
  startedAt: new Date(started).toISOString(),
  durationMs,
  workers: lanes.length,
  fullSweep,
  manifest: manifestSummary(),
  states: { registered: STATES.length, selected: new Set(cases.map((c) => c.state.name)).size, applicability },
  executions: { total: results.length, byTier, notReached: results.filter((r) => !r.reached).map((r) => `${r.state} @ ${r.viewport}`) },
  findings: { blocking: findings.filter((f) => f.severity === 'blocking').length, pending: findings.filter((f) => f.severity === 'measured/pending').length, byRule: count(findings, 'rule') },
  coverage,
  perf: {
    cls: { statuses: measure('cls'), measured: clsValues.length, min: clsValues.length ? Math.min(...clsValues) : null, max: clsValues.length ? Math.max(...clsValues) : null, nonZero: clsValues.filter((v) => v > 0).length },
    longTasks: { statuses: measure('longTasks') },
    fonts: count(results.map((r) => ({ fonts: r.fonts?.status === 'measured' ? (r.fonts.content?.length ? r.fonts.content : r.fonts.contextBar).map((f) => f.family).join(' + ') : `failed: ${r.fonts?.why}` })), 'fonts'),
  },
  determinism,
  harnessErrors,
};
writeFileSync(join(OUT, 'results.json'), JSON.stringify({ ...report, findingsList: findings, cases: results }, null, 2));

const line = (text = '') => process.stdout.write(text + '\n');
line();
line(`${results.length} captures (${STATES.length} registered states, ${report.states.selected} selected) in ${Math.round(durationMs / 1000)}s on ${lanes.length} lane(s)`);
for (const tier of TIERS) {
  const t = byTier[tier];
  line(`  Tier ${tier}: ${t.anchorCaptures} anchor + ${t.probeCaptures} probe captures; ${t.blocking} blocking, ${t.pending} measured/pending finding(s)`);
}
line(`  CLS: ${JSON.stringify(report.perf.cls.statuses)}; measured range ${report.perf.cls.min ?? '-'}..${report.perf.cls.max ?? '-'}`);
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
    `${results.length} captures of ${report.states.selected} states in ${Math.round(durationMs / 1000)}s on ${lanes.length} lanes.`,
    '',
    '| Tier | Anchor captures | Probe captures | Blocking | Measured/pending |',
    '|---|---|---|---|---|',
    ...TIERS.map((tier) => `| ${tier} | ${byTier[tier].anchorCaptures} | ${byTier[tier].probeCaptures} | ${byTier[tier].blocking} | ${byTier[tier].pending} |`),
    '',
    `CLS: ${JSON.stringify(report.perf.cls.statuses)}, measured range ${report.perf.cls.min ?? '-'}..${report.perf.cls.max ?? '-'}; long tasks: ${JSON.stringify(report.perf.longTasks.statuses)}.`,
    '',
    ...(harnessErrors.length ? ['### Harness errors', ...harnessErrors.map((e) => `- ${e}`), ''] : []),
    ...(blocking.length ? ['### Blocking findings', ...blocking.slice(0, 100).map((f) => `- \`${f.state} @ ${f.viewport}\` [${f.rule}] ${f.message}`), ''] : []),
    '### Measured/pending (never failing)',
    ...Object.entries(count(pending.map((f) => ({ key: `${f.rule} @ Tier ${f.tier} (${f.owner})` })), 'key')).sort().map(([key, n]) => `- ${key}: ${n}`),
  ];
  try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, md.join('\n') + '\n'); } catch { /* summary is a convenience */ }
}
line(`results: ${join(OUT, 'results.json')}`);
