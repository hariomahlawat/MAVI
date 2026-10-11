#!/usr/bin/env node
/**
 * The full sweep from its shards (CI).
 *
 *   node tools/web-visual-qa/aggregate.mjs --out DIR shard0/results.json shard1/results.json …
 *
 * `run.mjs --shard i/n` judges each case it runs; what no shard can judge alone
 * is judged here, over every shard, and the result is the one a single full
 * run would have produced:
 *
 *  - every shard is a shard of the same plan: same head, same manifest, same
 *    shard count, the same planned case list, and shard indices 0..n-1 each
 *    present exactly once;
 *  - every planned case ran in exactly one shard — none missing, none twice —
 *    and every one reached its state and produced a valid capture;
 *  - no shard reported a harness error;
 *  - the sweep-wide checks (engine.sweepChecks, the ones run.mjs applies to an
 *    unsharded full sweep): a loading Ledger against its table, pressed
 *    treatments proven somewhere, every operator surface judged at 200%, no
 *    blocking rule left unevaluated, overlay restoration judged at Tier A;
 *  - no blocking finding.
 *
 * Exit status as run.mjs: 0 clean, 1 a blocking finding, 2 a harness fault —
 * a shard missing or doubled, a plan disagreement, a case never run.
 */
import { appendFileSync, mkdirSync, readFileSync, writeFileSync, writeSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { caseKey, createLedger, exitStatus, sweepChecks } from './engine.mjs';
import { manifestSummary, OPERATOR_SURFACES, RULES, TIERS } from './manifest.mjs';

function fatal(text) {
  try { writeSync(2, text.endsWith('\n') ? text : text + '\n'); } catch { /* stderr gone */ }
  process.exit(2);
}

const argv = process.argv.slice(2);
const outIndex = argv.indexOf('--out');
if (outIndex === -1 || !argv[outIndex + 1]) fatal('usage: aggregate.mjs --out DIR shard/results.json …');
const OUT = resolve(argv[outIndex + 1]);
const files = argv.filter((_, i) => i !== outIndex && i !== outIndex + 1);
if (!files.length) fatal('no shard results given');

/** Layout-shift pairs, as run.mjs declares them. */
const LOADING_PAIRS = [['cameras-loading', 'cameras'], ['videos-loading', 'videos'], ['processing-queue-loading', 'processing-queue']];

const faults = [];
const shards = [];
for (const file of files) {
  let data;
  try { data = JSON.parse(readFileSync(file, 'utf8')); } catch (error) { fatal(`cannot read ${file}: ${error.message}`); }
  if (!data.shard) fatal(`${file} is not a shard result (run.mjs --shard i/n writes one)`);
  shards.push({ file, ...data });
}

// One plan: head, manifest, count and the planned case list agree everywhere.
const first = shards[0];
const sameJson = (a, b) => JSON.stringify(a) === JSON.stringify(b);
for (const s of shards.slice(1)) {
  if (s.head !== first.head) faults.push(`${s.file}: head ${s.head} differs from ${first.file}'s ${first.head}`);
  if (s.shard.count !== first.shard.count) faults.push(`${s.file}: shard count ${s.shard.count} differs from ${first.shard.count}`);
  if (!sameJson(s.manifest, first.manifest)) faults.push(`${s.file}: manifest summary differs from ${first.file}'s`);
  if (!sameJson(s.shard.planned, first.shard.planned)) faults.push(`${s.file}: planned case list differs from ${first.file}'s`);
  if (s.statesModule !== first.statesModule) faults.push(`${s.file}: states module differs from ${first.file}'s`);
}
const count = first.shard.count;
const indices = shards.map((s) => s.shard.index).sort((a, b) => a - b);
if (!sameJson(indices, Array.from({ length: count }, (_, i) => i))) {
  faults.push(`shard indices ${JSON.stringify(indices)} are not 0..${count - 1} each exactly once`);
}

// Every planned case exactly once, across the selections and across the results.
const planned = first.shard.planned;
const plannedSet = new Set(planned);
if (plannedSet.size !== planned.length) faults.push('the plan lists a case twice');
const seenSelected = new Map();
const seenResults = new Map();
const results = [];
const errored = [];
const findings = [];
const harnessErrors = [];
for (const s of shards) {
  for (const key of s.shard.selected) seenSelected.set(key, (seenSelected.get(key) ?? 0) + 1);
  for (const r of s.cases ?? []) {
    const key = caseKey(r);
    seenResults.set(key, (seenResults.get(key) ?? 0) + 1);
    results.push(r);
  }
  for (const e of s.executions?.errored ?? []) { errored.push(e); const key = caseKey(e); seenResults.set(key, (seenResults.get(key) ?? 0) + 1); }
  findings.push(...(s.findingsList ?? []));
  harnessErrors.push(...(s.harnessErrors ?? []).map((e) => `shard ${s.shard.index}: ${e}`));
}
for (const key of planned) {
  const sel = seenSelected.get(key) ?? 0;
  const ran = seenResults.get(key) ?? 0;
  if (sel !== 1) faults.push(`${key}: selected by ${sel} shard(s), not exactly one`);
  if (ran !== 1) faults.push(`${key}: ran ${ran} time(s), not exactly once`);
}
for (const key of seenSelected.keys()) if (!plannedSet.has(key)) faults.push(`${key}: selected by a shard but not in the plan`);
for (const key of seenResults.keys()) if (!plannedSet.has(key)) faults.push(`${key}: ran but is not in the plan`);
// Up to here the faults are structural: shards that disagree or a plan not
// covered. Only those make the union meaningless; a shard's own harness
// errors (a state not reached, a case that threw) are faults too, but the
// sweep-wide checks still run over what did run, as they do in an unsharded
// run — and they report the unreached cases themselves, so a shard's copy of
// that message is kept only where the checks do not say it.
const structural = faults.length;

// The sweep-wide checks, over the union: the aggregate's ledger carries every
// shard's coverage, so vacuity is judged as one full run would judge it.
const ledger = createLedger(RULES);
for (const s of shards) {
  for (const [rule, tiers] of Object.entries(s.coverage ?? {})) {
    for (const [tier, c] of Object.entries(tiers)) {
      if (!ledger.coverage[rule]?.[tier]) { faults.push(`shard ${s.shard.index}: coverage names ${rule} @ Tier ${tier}, which the manifest does not`); continue; }
      ledger.coverage[rule][tier].evaluated += c.evaluated;
      ledger.coverage[rule][tier].blockingEvaluated += c.blockingEvaluated;
      ledger.coverage[rule][tier].findings += c.findings;
    }
  }
}
const fullSweep = shards.every((s) => s.shard.completeSelection) && !first.statesModule;
const cases = planned.map((key) => ({ key }));
let sweep = { faults: [], pressedUnproven: [] };
if (!structural) {
  try {
    sweep = sweepChecks({ results, cases, errored, ledger, surfaces: OPERATOR_SURFACES, loadingPairs: LOADING_PAIRS, fullSweep, plannedKeys: planned });
  } catch (error) { faults.push(String(error.message || error)); }
  faults.push(...sweep.faults);
}
const said = new Set(faults);
for (const e of harnessErrors) {
  const own = e.replace(/^shard \d+: /, '');
  if (!said.has(own)) faults.push(e);
}
findings.push(...ledger.findings);

const valid = results.filter((r) => r.valid);
const byTier = Object.fromEntries(TIERS.map((tier) => [tier, {
  anchorCaptures: valid.filter((r) => r.tier === tier && r.kind === 'anchor').length,
  probeCaptures: valid.filter((r) => r.tier === tier && r.kind === 'probe').length,
  zoomCaptures: valid.filter((r) => r.tier === tier && (r.kind === 'zoom' || r.kind === 'zoom-transition')).length,
  spacingCaptures: valid.filter((r) => r.tier === tier && r.kind === 'text-spacing').length,
  motionCaptures: valid.filter((r) => r.tier === tier && r.kind === 'reduced-motion').length,
  invalid: results.filter((r) => r.tier === tier && !r.valid).length + errored.filter((e) => e.tier === tier).length,
  blocking: findings.filter((f) => f.tier === tier && f.severity === 'blocking').length,
  pending: findings.filter((f) => f.tier === tier && f.severity === 'measured/pending').length,
}]));
const blocking = findings.filter((f) => f.severity === 'blocking');
const pending = findings.filter((f) => f.severity === 'measured/pending');
const zoomResults = results.filter((r) => r.zoom);
// X4: the reduced-motion lane over the union of the shards — its coverage
// fault is sweepChecks' (engine.reducedMotionCoverageFaults, by planned key).
const motionResults = results.filter((r) => r.kind === 'reduced-motion');
const motionSum = (key) => motionResults.reduce((n, r) => n + (r.reducedMotion?.measured?.[key] ?? 0), 0);
const report = {
  harness: 'web-visual-qa v2 (aggregate of shards)',
  head: first.head,
  statesModule: first.statesModule,
  fullSweep,
  manifest: manifestSummary(),
  shards: shards.map((s) => ({ index: s.shard.index, count: s.shard.count, file: s.file, cases: s.cases?.length ?? 0, durationMs: s.durationMs, workers: s.workers })),
  executions: {
    planned: planned.length,
    scheduled: planned.length,
    validCaptures: valid.length,
    byTier,
    notReached: results.filter((r) => !r.reached).map((r) => ({ state: r.state, viewport: r.viewport, tier: r.tier, ...r.unreached })),
    errored,
    zoom: {
      valid: { loads: zoomResults.filter((r) => r.valid && r.kind === 'zoom').length, transitions: zoomResults.filter((r) => r.valid && r.kind === 'zoom-transition').length },
      qualified: zoomResults.filter((r) => r.valid && r.zoom.qualified).length,
      workbenchException: Object.entries(zoomResults.filter((r) => r.valid && r.zoom.measured?.workbenchException && r.tier === 'C')
        .reduce((acc, r) => { (acc[r.surface] ??= { captures: 0, statement: r.zoom.measured.workbenchException }).captures += 1; return acc; }, {}))
        .map(([surface, entry]) => ({ surface, ...entry })),
    },
  },
  reducedMotion: {
    planned: planned.filter((k) => /@reduced-motion#\d+$/.test(k)).length,
    valid: motionResults.filter((r) => r.valid).length,
    active: motionResults.filter((r) => r.reducedMotion?.active).length,
    byViewport: motionResults.reduce((acc, r) => { const v = (acc[r.viewport] ??= { valid: 0, active: 0, cases: 0 }); v.cases += 1; if (r.valid) v.valid += 1; if (r.reducedMotion?.active) v.active += 1; return acc; }, {}),
    elements: motionSum('elements'), pseudos: motionSum('pseudos'), transitionValues: motionSum('transitionValues'), animationValues: motionSum('animationValues'),
    positiveTransitions: motionSum('positiveTransitions'), positiveAnimations: motionSum('positiveAnimations'), unparseable: motionSum('unparseable'),
    browserAnimations: motionSum('browserAnimations'), browserRunning: motionSum('browserRunning'), browserRunningPositive: motionSum('browserRunningPositive'),
    otherCasesUnderReduce: results.filter((r) => r.kind !== 'reduced-motion' && r.motionMedia?.matchMedia === true).length,
    // The normal-preference control over the union: per site, the ordinary cases it ran in and its longest duration.
    normalSites: results.reduce((sites, r) => { for (const [key, s] of Object.entries(r.normalMotion ?? {})) { const e = (sites[key] ??= { cases: 0, maxMs: 0 }); e.cases += 1; e.maxMs = Math.max(e.maxMs, s.maxMs); } return sites; }, {}),
  },
  findings: { blocking: blocking.length, pending: pending.length },
  coverage: ledger.coverage,
  pressedUnproven: sweep.pressedUnproven,
  harnessErrors: faults,
};
mkdirSync(OUT, { recursive: true });
writeFileSync(join(OUT, 'results.json'), JSON.stringify({ ...report, findingsList: findings, cases: results }, null, 2));

const line = (text = '') => process.stdout.write(text + '\n');
line(`${valid.length} valid captures of ${planned.length} planned across ${shards.length} shard(s)${fullSweep ? ' (the full sweep)' : ' (a partial selection)'}`);
for (const tier of TIERS) {
  const t = byTier[tier];
  line(`  Tier ${tier}: ${t.anchorCaptures} anchor + ${t.probeCaptures} probe${t.zoomCaptures ? ` + ${t.zoomCaptures} zoom` : ''}${t.spacingCaptures ? ` + ${t.spacingCaptures} text-spacing` : ''}${t.motionCaptures ? ` + ${t.motionCaptures} reduced-motion` : ''} valid captures, ${t.invalid} invalid; ${t.blocking} blocking, ${t.pending} measured/pending finding(s)`);
}
{
  const rm = report.reducedMotion;
  if (rm.planned) {
    line(`  reduced motion (§13): ${rm.valid}/${rm.planned} valid with prefers-reduced-motion: reduce proven in force on ${rm.active}; ${Object.entries(rm.byViewport).map(([v, n]) => `${v} ${n.valid}/${n.cases}`).join(', ')}`);
    const ns = Object.entries(rm.normalSites).filter(([k]) => /^animation /.test(k)).map(([k, s]) => `${k.replace('animation ', '')} ${s.maxMs}ms in ${s.cases}`).join(', ');
    if (ns) line(`  normal preference (control): ${ns} ordinary case(s)`);
    line(`  reduced motion judged: ${rm.elements} elements and ${rm.pseudos} pseudo-elements, ${rm.transitionValues} transition and ${rm.animationValues} animation durations; positive: ${rm.positiveTransitions} transition, ${rm.positiveAnimations} animation, ${rm.browserRunningPositive} running browser animation(s) of ${rm.browserAnimations}; ordinary cases under reduce: ${rm.otherCasesUnderReduce}`);
  }
}
const z = report.executions.zoom;
line(`  200% zoom: ${z.valid.loads} loads and ${z.valid.transitions} transitions valid, ${z.qualified} with the zoom proven`);
for (const e of z.workbenchException) line(`  200% zoom, §23 WCAG 1.4.4 Workbench exception: ${e.surface} (${e.captures} capture(s)) — "${e.statement}"`);
if (pending.length) {
  const grouped = {};
  for (const f of pending) { const k = `${f.rule} @ Tier ${f.tier} [${f.owner}]`; grouped[k] = (grouped[k] ?? 0) + 1; }
  line(`\n${pending.length} measured/pending finding(s) — reported, never failing (owner in brackets):`);
  for (const [k, n] of Object.entries(grouped).sort()) line(`  - ${k}: ${n}`);
}
if (blocking.length) {
  line(`\n${blocking.length} BLOCKING finding(s):`);
  for (const f of blocking) line(`  - ${f.state} @ ${f.viewport} [${f.rule}]: ${f.message}`);
}
if (faults.length) {
  line('\nHARNESS ERROR(S):');
  for (const e of faults) line(`  - ${e}`);
} else if (!blocking.length) {
  line('\nNo blocking findings. Section 26 still requires a person to read the captures.');
}
process.exitCode = exitStatus({ harnessErrors: faults, blocking });
if (process.env.GITHUB_STEP_SUMMARY) {
  const md = [
    `## Visual QA (aggregate of ${shards.length} shards) — ${faults.length ? 'harness error' : blocking.length ? `${blocking.length} blocking finding(s)` : 'no blocking findings'}`,
    '',
    `${valid.length} valid captures of ${planned.length} planned${fullSweep ? ' (full sweep)' : ' (partial selection)'}; head ${first.head}.`,
    '',
    '| Tier | Valid anchor | Valid probe | Valid 200% zoom | Valid text spacing | Valid reduced motion | Invalid | Blocking | Measured/pending |',
    '|---|---|---|---|---|---|---|---|---|',
    ...TIERS.map((tier) => `| ${tier} | ${byTier[tier].anchorCaptures} | ${byTier[tier].probeCaptures} | ${byTier[tier].zoomCaptures} | ${byTier[tier].spacingCaptures} | ${byTier[tier].motionCaptures} | ${byTier[tier].invalid} | ${byTier[tier].blocking} | ${byTier[tier].pending} |`),
    '',
    ...(faults.length ? ['### Harness errors', ...faults.map((e) => `- ${e}`), ''] : []),
    ...(blocking.length ? ['### Blocking findings', ...blocking.slice(0, 100).map((f) => `- \`${f.state} @ ${f.viewport}\` [${f.rule}] ${f.message}`), ''] : []),
  ];
  try { appendFileSync(process.env.GITHUB_STEP_SUMMARY, md.join('\n') + '\n'); } catch { /* summary is a convenience */ }
}
line(`results: ${join(OUT, 'results.json')}`);
