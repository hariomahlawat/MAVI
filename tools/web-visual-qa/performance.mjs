/**
 * Stage 3.5 S6/X3 (§38): the performance budgets, judged.
 *
 * The raw measurements are the sweep's and the long-task lane's own
 * (settle.mjs `perfCollect`, unchanged from the P1 measurement code): navigation
 * CLS and preparation CLS per ordinary case, the long tasks of a declared
 * interaction on one lane, the resolved platform fonts and the font faces the
 * document holds. This module judges them against the one budget source
 * (performance-budgets.mjs) and keeps two things apart: a performance finding
 * (a valid measurement over its limit; a font that could swap) and a harness
 * fault (a measurement missing, failed or unsupported; a planned case missing
 * or twice; a case no budget class covers; long tasks measured anywhere but
 * the single-lane run; a malformed budget table).
 *
 * Every comparison is in integer units — CLS in 1e-4 (the measurement's own
 * rounding), long tasks in whole milliseconds — so a value at its limit
 * passes and one unit over fails, with no floating-point ambiguity.
 *
 *   node tools/web-visual-qa/performance.mjs --sweep <results.json> --long-tasks <results.json> [--out <dir>] [--qualification <file>]
 */
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { HarnessError, planCases } from './engine.mjs';
import { PERFORMANCE_BUDGETS } from './performance-budgets.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
export const TIERS = ['A', 'B', 'C'];

/** CLS in integer units of 1e-4 — the measurement's own precision. */
export const clsUnits = (value) => Math.round(value * 10000);
export const fromUnits = (units) => units / 10000;
export const caseKey = (c) => `${c.state}|${c.viewport}|${c.kind}`;
/** The ordinary product: anchors and probes, never a zoom, spacing or reduced-motion case. */
export const isOrdinary = (c) => c.kind === 'anchor' || c.kind === 'probe';
/** A class's effective limit: reference + tolerance, in units. */
export const limitUnits = (reference, tolerance) => clsUnits(reference) + clsUnits(tolerance);

/**
 * The budget table's own coherence: every class with a reference, a tolerance
 * and the case that defines it; membership unambiguous; the long-task classes
 * with their limits; nothing twice. A table that fails here cannot judge
 * anything: a harness fault.
 */
export function validateBudgets(budgets = PERFORMANCE_BUDGETS) {
  const problems = [];
  const number = (v, where) => { if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) problems.push(`${where}: not a non-negative number (${v})`); };
  if (!budgets?.schema) problems.push('no schema');
  if (!budgets?.baseline?.file || !budgets?.baseline?.sha) problems.push('no P1 baseline file and SHA');
  const tol = budgets?.cls?.tolerance ?? {};
  for (const t of TIERS) number(tol[t], `cls.tolerance.${t}`);
  number(tol.preparation, 'cls.tolerance.preparation');
  const names = new Set();
  const named = (cls, family) => {
    if (!cls?.name) { problems.push(`cls.${family}: a class without a name`); return false; }
    if (names.has(cls.name)) problems.push(`cls: class "${cls.name}" is defined twice`);
    names.add(cls.name);
    number(cls.reference, `"${cls.name}".reference`);
    if (cls.tolerance !== undefined) number(cls.tolerance, `"${cls.name}".tolerance`);
    if (!cls.definedBy) problems.push(`"${cls.name}": no defining case`);
    if (!['mapped', 'inherited-new', 'explicit-new'].includes(cls.kind)) problems.push(`"${cls.name}": kind "${cls.kind}" is not mapped, inherited-new or explicit-new`);
    if (cls.kind === 'explicit-new' && !cls.why) problems.push(`"${cls.name}": an explicit class states why it is qualified`);
    if (cls.environment && (!cls.environment.rationale || !Array.isArray(cls.environment.linux))) problems.push(`"${cls.name}": an environment-calibrated class states its Linux evidence and why`);
    return true;
  };
  const navigation = budgets?.cls?.navigation ?? [];
  if (!navigation.length) problems.push('cls.navigation: no class');
  const navKeys = new Map();
  for (const cls of navigation) {
    if (!named(cls, 'navigation')) continue;
    if (!cls.surface || !TIERS.includes(cls.tier)) problems.push(`"${cls.name}": a navigation class names one surface and one tier`);
    if (cls.states !== undefined && (!Array.isArray(cls.states) || !cls.states.length)) problems.push(`"${cls.name}": its named states are a non-empty list`);
    for (const key of (cls.states ?? ['*']).map((s) => `${cls.surface}|${cls.tier}|${s}`)) {
      if (navKeys.has(key)) problems.push(`cls.navigation: ${key} belongs to "${navKeys.get(key)}" and "${cls.name}"`);
      navKeys.set(key, cls.name);
    }
  }
  const prepKeys = new Map();
  for (const cls of budgets?.cls?.preparation ?? []) {
    if (!named(cls, 'preparation')) continue;
    const byLabel = Array.isArray(cls.by) && cls.by.length > 0;
    const byState = Array.isArray(cls.states) && cls.states.length > 0;
    if (!cls.surface || byLabel === byState) problems.push(`"${cls.name}": a preparation class's membership is either transitions (by) or named states, exactly one`);
    for (const key of [...(cls.by ?? []), ...(cls.states ?? []).map((s) => `state:${s}`)].map((m) => `${cls.surface}|${m}`)) {
      if (prepKeys.has(key)) problems.push(`cls.preparation: ${key} belongs to "${prepKeys.get(key)}" and "${cls.name}"`);
      prepKeys.set(key, cls.name);
    }
  }
  const lt = budgets?.longTasks;
  if (!lt?.default?.name) problems.push('longTasks: no default class');
  else { number(lt.default.count, 'longTasks.default.count'); number(lt.default.maxMs, 'longTasks.default.maxMs'); }
  const interactions = new Map();
  for (const cls of lt?.classes ?? []) {
    if (!cls.name || !Array.isArray(cls.interactions) || !cls.interactions.length) problems.push(`longTasks: class "${cls.name}" names no interaction`);
    number(cls.count, `longTasks."${cls.name}".count`); number(cls.maxMs, `longTasks."${cls.name}".maxMs`);
    for (const i of cls.interactions ?? []) {
      if (interactions.has(i)) problems.push(`longTasks: interaction "${i}" belongs to "${interactions.get(i)}" and "${cls.name}"`);
      interactions.set(i, cls.name);
    }
  }
  if (!Number.isInteger(budgets?.fonts?.documentFaces) || budgets.fonts.documentFaces < 0) problems.push('fonts.documentFaces: not a non-negative integer');
  for (const family of ['navigation', 'preparation', 'longTasks']) {
    if (!Array.isArray(budgets?.measured?.[family]) || !budgets.measured[family].length) problems.push(`measured.${family}: the calibration's measured cases are the floor of what is judged`);
  }
  return problems;
}

const limitOf = (family, cls, tolerance) => ({
  family, class: cls.name, kind: cls.kind, reference: cls.reference, tolerance,
  limit: fromUnits(limitUnits(cls.reference, tolerance)), definedBy: cls.definedBy,
  environmentCalibrated: Boolean(cls.environment),
});

/**
 * A case's navigation class: an explicit class naming its state first (a
 * failure path qualified on its own evidence), else its surface and tier.
 * Null when neither exists — a new surface has no inherited budget.
 */
export function navigationLimit(c, budgets = PERFORMANCE_BUDGETS) {
  const classes = budgets.cls.navigation.filter((k) => k.surface === c.surface && k.tier === c.tier);
  const cls = classes.find((k) => k.states?.includes(c.state)) ?? classes.find((k) => !k.states);
  if (!cls) return null;
  return limitOf('navigation', cls, cls.tolerance ?? budgets.cls.tolerance[c.tier]);
}

/**
 * A case's preparation class, never inherited from navigation: an explicit
 * class naming its state first, else the class of its surface and transition.
 * Null when neither exists: a new transition needs a class, with evidence.
 */
export function preparationLimit(c, budgets = PERFORMANCE_BUDGETS) {
  const by = c.perf?.clsPreparation?.by;
  const classes = budgets.cls.preparation.filter((k) => k.surface === c.surface);
  const cls = classes.find((k) => k.states?.includes(c.state)) ?? classes.find((k) => k.by?.includes(by));
  if (!cls) return null;
  return limitOf('preparation', cls, cls.tolerance ?? budgets.cls.tolerance.preparation);
}

/** An interaction's long-task class: its own when it has one, else the zero class. */
export function longTaskLimit(interaction, budgets = PERFORMANCE_BUDGETS) {
  const cls = budgets.longTasks.classes.find((k) => k.interactions.includes(interaction)) ?? budgets.longTasks.default;
  return { class: cls.name, count: cls.count, maxMs: cls.maxMs };
}

/**
 * The ordinary plan X3 is judged on: every state at its anchors and probes,
 * no zoom, spacing or reduced-motion case; and the long-task plan, the states
 * that declare an interaction. Derived from the states module, never from the
 * results being judged.
 */
export function ordinaryPlan(statesModule) {
  const { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf, ZOOM } = statesModule;
  const plan = (onlyStates) => planCases({ states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, zoom: ZOOM, onlyStates, onlyZoom: 'none', onlyTextSpacing: 'none', onlyReducedMotion: 'none' })
    .cases.filter((c) => isOrdinary(c.viewport)).map((c) => caseKey({ state: c.state.name, viewport: c.viewport.label, kind: c.viewport.kind }));
  return { sweep: new Set(plan(null)), longTasks: new Set(plan(STATES.filter((s) => s.interaction).map((s) => s.name))) };
}

/**
 * The budgets as the register states them: one line per class, its limit
 * spelled as reference + tolerance = limit, and the long-task classes. The
 * register carries this block verbatim (between its markers), so a register
 * that disagrees with the budget source is caught by comparison, not by
 * reading prose.
 */
export const REGISTER_MARKERS = Object.freeze({ begin: '<!-- x3-budgets:begin -->', end: '<!-- x3-budgets:end -->' });
export function registerBlock(budgets = PERFORMANCE_BUDGETS) {
  const f = (v) => fromUnits(clsUnits(v)).toFixed(4);
  const lines = [`schema ${budgets.schema}; P1 ${budgets.baseline.sha}`];
  for (const cls of budgets.cls.navigation) {
    const tol = cls.tolerance ?? budgets.cls.tolerance[cls.tier];
    lines.push(`navigation | ${cls.name} | ${f(cls.reference)} + ${f(tol)} = ${f(fromUnits(limitUnits(cls.reference, tol)))}${cls.environment ? ' | environment-calibrated' : ''}`);
  }
  for (const cls of budgets.cls.preparation) {
    const tol = cls.tolerance ?? budgets.cls.tolerance.preparation;
    lines.push(`preparation | ${cls.name} | ${f(cls.reference)} + ${f(tol)} = ${f(fromUnits(limitUnits(cls.reference, tol)))}`);
  }
  lines.push(`long tasks | ${budgets.longTasks.default.name} | ${budgets.longTasks.default.count} x <= ${budgets.longTasks.default.maxMs}ms`);
  for (const cls of budgets.longTasks.classes) lines.push(`long tasks | ${cls.name} | ${cls.count} x <= ${cls.maxMs}ms`);
  lines.push(`fonts | document font faces <= ${budgets.fonts.documentFaces}`);
  return lines.join('\n');
}

/** Where the register's block and the budget source disagree (a harness fault). */
export function registerDisagreements(markdown, budgets = PERFORMANCE_BUDGETS) {
  const begin = markdown.indexOf(REGISTER_MARKERS.begin);
  const end = markdown.indexOf(REGISTER_MARKERS.end);
  if (begin === -1 || end === -1 || end < begin) return ['the register carries no X3 budget block'];
  const stated = markdown.slice(begin + REGISTER_MARKERS.begin.length, end).replace(/```[a-z]*/g, '').split('\n').map((l) => l.trim()).filter(Boolean);
  const source = registerBlock(budgets).split('\n');
  const problems = [];
  for (const line of source) if (!stated.includes(line)) problems.push(`the register does not state: ${line}`);
  for (const line of stated) if (!source.includes(line)) problems.push(`the register states what the budget source does not: ${line}`);
  return problems;
}

const measurementFault = (key, what, m) => `${key}: ${what} ${m?.status ?? 'missing'}${m?.why ? ` (${m.why})` : ''}`;

/**
 * Judge one full sweep (its ordinary cases: CLS and fonts) and one
 * single-lane long-task run against the budgets.
 *
 * @param {{ sweep: object, longTasks: object, plan?: { sweep: Set<string>, longTasks: Set<string> }, budgets?: object }} input
 */
export function evaluatePerformance({ sweep, longTasks, plan = null, budgets = PERFORMANCE_BUDGETS }) {
  const faults = [];
  const findings = [];
  const rows = [];
  const ltRows = [];
  const budgetProblems = validateBudgets(budgets);
  if (budgetProblems.length) return { faults: budgetProblems.map((p) => `the budget table is malformed: ${p}`), findings, rows, longTaskRows: ltRows, summary: null };

  // What the calibration measured: such a case answering not-applicable has
  // stopped being judged (its loading presentation renamed or removed, its
  // interaction gone) — a fault until it is requalified, never a silent pass.
  const wasMeasured = {
    navigation: new Set(budgets.measured.navigation),
    preparation: new Set(budgets.measured.preparation),
    longTasks: new Set(budgets.measured.longTasks),
  };
  const stopped = (key, what) => `${key}: ${what} was measured at calibration and is now not-applicable — what it measured no longer happens or is no longer seen; requalify it`;
  // The sweep: the full sweep, each planned ordinary case exactly once.
  if (!sweep) faults.push('no sweep results to judge');
  else if (sweep.fullSweep !== true) faults.push('the sweep results are not the full sweep: X3 is judged on the whole product');
  if (sweep && !sweep.head) faults.push('the sweep results name no head');
  const ordinary = (sweep?.cases ?? []).filter(isOrdinary);
  const seen = new Map();
  for (const c of ordinary) seen.set(caseKey(c), (seen.get(caseKey(c)) ?? 0) + 1);
  for (const [key, n] of seen) if (n > 1) faults.push(`${key}: in the sweep ${n} times`);
  if (sweep && !ordinary.length) faults.push('the sweep has no ordinary case');
  if (plan) {
    for (const key of plan.sweep) if (!seen.has(key)) faults.push(`${key}: planned but missing from the sweep`);
    for (const key of seen.keys()) if (!plan.sweep.has(key)) faults.push(`${key}: in the sweep but not in the plan`);
  }

  for (const c of ordinary) {
    const key = caseKey(c);
    if (!c.valid || !c.reached) { faults.push(`${key}: not a valid capture, so its measurements are not the state's`); continue; }
    const row = { key, state: c.state, viewport: c.viewport, tier: c.tier, kind: c.kind, surface: c.surface };
    // Navigation CLS.
    const nav = c.perf?.cls;
    if (!nav || nav.status !== 'measured' && nav.status !== 'not-applicable') faults.push(measurementFault(key, 'navigation CLS', nav));
    else if (nav.status === 'not-applicable' && wasMeasured.navigation.has(key)) faults.push(stopped(key, 'navigation CLS'));
    else if (nav.status === 'measured') {
      const limit = navigationLimit(c, budgets);
      if (!limit) faults.push(`${key}: no navigation budget class for ${c.surface} @ ${c.tier}, and nothing to inherit one from`);
      else {
        const pass = clsUnits(nav.value) <= clsUnits(limit.limit);
        row.navigation = { value: nav.value, ...limit, pass };
        if (!pass) findings.push({ rule: 'perf.cls', key, tier: c.tier, message: `navigation CLS ${nav.value} over its limit ${limit.limit} (${limit.class}: reference ${limit.reference}, defined by ${limit.definedBy}, + tolerance ${limit.tolerance})` });
      }
    }
    // Preparation CLS — its own family: a good navigation never excuses it.
    const prep = c.perf?.clsPreparation;
    if (!prep || prep.status !== 'measured' && prep.status !== 'not-applicable') faults.push(measurementFault(key, 'preparation CLS', prep));
    else if (prep.status === 'not-applicable' && wasMeasured.preparation.has(key)) faults.push(stopped(key, 'preparation CLS'));
    else if (prep.status === 'measured') {
      const limit = preparationLimit(c, budgets);
      if (!limit) faults.push(`${key}: the preparation transition "${prep.by}" on ${c.surface} belongs to no preparation budget class; it needs one, with its evidence (a navigation budget is never inherited)`);
      else {
        const pass = clsUnits(prep.value) <= clsUnits(limit.limit);
        row.preparation = { value: prep.value, by: prep.by, ...limit, pass };
        if (!pass) findings.push({ rule: 'perf.cls', key, tier: c.tier, message: `preparation CLS ${prep.value} ("${prep.by}") over its limit ${limit.limit} (${limit.class}: reference ${limit.reference}, defined by ${limit.definedBy}, + tolerance ${limit.tolerance})` });
      }
    }
    // Fonts: the platform's, and nothing the document could load and swap.
    const fonts = c.fonts;
    if (!fonts || fonts.status !== 'measured') faults.push(measurementFault(key, 'resolved font', fonts));
    else if (!Number.isInteger(fonts.faces)) faults.push(`${key}: the font record does not say how many font faces the document holds`);
    else {
      const faces = [...(fonts.contextBar ?? []), ...(fonts.content ?? [])];
      const custom = faces.filter((f) => f.custom);
      row.font = { families: [...new Set(faces.map((f) => f.family))], custom: custom.length, faces: fonts.faces };
      if (custom.length || fonts.faces > budgets.fonts.documentFaces) {
        findings.push({ rule: 'typography.resolved-font', key, tier: c.tier, message: `a font that is not the platform's (${[...custom.map((f) => f.family), ...(fonts.faces > budgets.fonts.documentFaces ? [`${fonts.faces} font face(s) in the document`] : [])].join('; ')}): it can arrive late and swap (§38)` });
      }
    }
    rows.push(row);
  }

  // Long tasks: the single-lane run, whole — never the sweep's lanes.
  if (!longTasks) faults.push('no long-task results to judge');
  else {
    if (longTasks.longTaskLane !== true) faults.push('the long-task results are not the long-task lane (run.mjs --long-tasks)');
    if (longTasks.workers !== 1) faults.push(`the long-task results were measured on ${longTasks.workers} lanes: only a single-lane run is evidence (lanes contend for the CPU)`);
    if (!longTasks.head) faults.push('the long-task results name no head');
    else if (sweep?.head && longTasks.head !== sweep.head) faults.push(`the long-task run (${longTasks.head}) and the sweep (${sweep.head}) are of different heads`);
    const lt = (longTasks.cases ?? []).filter(isOrdinary);
    const ltSeen = new Map();
    for (const c of lt) ltSeen.set(caseKey(c), (ltSeen.get(caseKey(c)) ?? 0) + 1);
    for (const [key, n] of ltSeen) if (n > 1) faults.push(`${key}: in the long-task run ${n} times`);
    if (plan) {
      for (const key of plan.longTasks) if (!ltSeen.has(key)) faults.push(`${key}: declares an interaction but the long-task run did not measure it`);
      for (const key of ltSeen.keys()) if (!plan.longTasks.has(key)) faults.push(`${key}: in the long-task run but not in its plan`);
    }
    for (const c of lt) {
      const key = caseKey(c);
      const m = c.perf?.longTasks;
      if (!c.valid || !c.reached) { faults.push(`${key}: not a valid capture in the long-task run`); continue; }
      // A case of an interaction state where the interaction does not apply
      // (a rendered composition, said so with its reason) measures nothing,
      // as in P1; missing, failed or unsupported is a fault.
      if (m?.status === 'not-applicable' && m.why) {
        if (wasMeasured.longTasks.has(key)) faults.push(stopped(key, 'its interaction’s long tasks'));
        continue;
      }
      if (!m || m.status !== 'measured') { faults.push(measurementFault(key, 'long tasks', m)); continue; }
      const limit = longTaskLimit(m.interaction, budgets);
      const pass = m.count <= limit.count && m.maxMs <= limit.maxMs;
      // The measurement and what its class permits, apart: a permitted value
      // never stands in for a measured one in the evidence.
      ltRows.push({ key, tier: c.tier, interaction: m.interaction, count: m.count, maxMs: m.maxMs, totalMs: m.totalMs, class: limit.class, permitted: { count: limit.count, maxMs: limit.maxMs }, pass });
      if (!pass) findings.push({ rule: 'perf.long-tasks', key, tier: c.tier, message: `"${m.interaction}": ${m.count} long task(s), longest ${m.maxMs}ms, total ${m.totalMs}ms; its class "${limit.class}" permits ${limit.count}, each at most ${limit.maxMs}ms` });
    }
  }
  return { faults, findings, rows, longTaskRows: ltRows, summary: summarise(rows, ltRows) };
}

const q = (xs, p) => { if (!xs.length) return null; const s = [...xs].sort((a, b) => a - b); return s[Math.min(s.length - 1, Math.ceil(p * s.length) - 1)]; };
const r4 = (n) => (n == null ? n : Math.round(n * 10000) / 10000);
export const distribution = (xs) => ({ n: xs.length, median: r4(q(xs, 0.5)), p90: r4(q(xs, 0.9)), max: r4(xs.length ? Math.max(...xs) : null) });

/** Per tier and surface, each family apart; the cases nearest their limits. */
function summarise(rows, ltRows) {
  const headroom = (r, f) => clsUnits(r[f].limit) - clsUnits(r[f].value);
  const family = (f) => {
    const measured = rows.filter((r) => r[f]?.value !== undefined);
    return {
      byTier: Object.fromEntries(TIERS.map((t) => [t, distribution(measured.filter((r) => r.tier === t).map((r) => r[f].value))])),
      bySurface: Object.fromEntries([...new Set(measured.map((r) => r.surface))].sort().map((s) => [s, distribution(measured.filter((r) => r.surface === s).map((r) => r[f].value))])),
      nearest: [...measured].sort((a, b) => headroom(a, f) - headroom(b, f) || a.key.localeCompare(b.key)).slice(0, 10)
        .map((r) => ({ key: r.key, value: r[f].value, limit: r[f].limit, class: r[f].class, headroom: fromUnits(headroom(r, f)) })),
    };
  };
  return {
    navigation: family('navigation'),
    preparation: family('preparation'),
    longTasks: { measured: ltRows.length, withTasks: ltRows.filter((r) => r.count > 0).map((r) => ({ key: r.key, interaction: r.interaction, count: r.count, maxMs: r.maxMs, class: r.class })) },
    fonts: { families: rows.reduce((m, r) => { for (const f of r.font?.families ?? []) m[f] = (m[f] ?? 0) + 1; return m; }, {}), documentFaces: Math.max(0, ...rows.map((r) => r.font?.faces ?? 0)) },
  };
}

// --- The command line ---------------------------------------------------------------

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}
const readJson = (file) => JSON.parse(readFileSync(resolve(file), 'utf8'));

async function main() {
  const out = resolve(arg('out', join(HERE, '.performance')));
  const sweep = arg('sweep') ? readJson(arg('sweep')) : null;
  const longTasks = arg('long-tasks') ? readJson(arg('long-tasks')) : null;
  const plan = ordinaryPlan(await import('./states.mjs'));
  const verdict = evaluatePerformance({ sweep, longTasks, plan });
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, 'performance.json'), JSON.stringify({ schema: 'mavi.stage3-5.x3-performance-run.v1', head: sweep?.head ?? null, budgets: PERFORMANCE_BUDGETS.schema, ...verdict }, null, 2));
  const s = verdict.summary;
  if (s) {
    process.stdout.write(`performance budgets (${PERFORMANCE_BUDGETS.schema}) on ${sweep?.head ?? '?'}:\n`);
    for (const t of TIERS) process.stdout.write(`  Tier ${t}: navigation CLS ${JSON.stringify(s.navigation.byTier[t])}; preparation CLS ${JSON.stringify(s.preparation.byTier[t])}\n`);
    process.stdout.write(`  long tasks: ${s.longTasks.measured} interaction cases, ${s.longTasks.withTasks.length} with a long task\n  fonts: ${JSON.stringify(s.fonts)}\n`);
    process.stdout.write(`  nearest: ${s.navigation.nearest.slice(0, 3).map((n) => `${n.key} ${n.value}/${n.limit}`).join('; ')}\n`);
  }
  for (const f of verdict.findings) process.stdout.write(`  BLOCKING ${f.rule} ${f.key}: ${f.message}\n`);
  if (verdict.faults.length) { process.stdout.write('\nHARNESS ERROR(S):\n'); for (const f of verdict.faults) process.stdout.write(`  - ${f}\n`); }
  process.exitCode = verdict.faults.length ? 2 : verdict.findings.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => { process.stderr.write(`HARNESS ERROR: ${error instanceof HarnessError ? error.message : error.stack || error}\n`); process.exitCode = 2; });
}

export { REPO };
