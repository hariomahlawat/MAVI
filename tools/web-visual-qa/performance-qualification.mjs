/**
 * Stage 3.5 S6/X3 (§38): the qualification artifact, generated — never typed.
 *
 * From the exact implementation head's CI evidence (the full sweep's
 * aggregate and the single-lane long-task run: the enforcement environment)
 * and, for continuity, an uncontended Windows sweep and long-task run of the
 * same head (P1's environment), this writes
 * docs/qualification/stage3-5/s6-x3-performance-qualification.json: the
 * budgets, the gate's verdict on the head, the mapping of P1 states (mapped,
 * new, retired), P1 against the current product, and Windows against P1.
 *
 *   node tools/web-visual-qa/performance-qualification.mjs \
 *     --sweep <ci aggregate results.json> --long-tasks <ci long-task results.json> \
 *     --windows-sweep <results.json> --windows-long-tasks <results.json> \
 *     --ci-run <run id/attempt> [--out <file>]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { HarnessError } from './engine.mjs';
import { surfaceOf } from './manifest.mjs';
import { PERFORMANCE_BUDGETS } from './performance-budgets.mjs';
import { clsUnits, distribution, evaluatePerformance, fromUnits, isOrdinary, navigationLimit, ordinaryPlan, preparationLimit, TIERS } from './performance.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
const OUT = 'docs/qualification/stage3-5/s6-x3-performance-qualification.json';
const where = (c) => `${c.state}@${c.viewport}`;
const num = (v) => (typeof v === 'number' ? v : null);

/** P1's states against today's: mapped (still registered), new, retired. */
export function stateMapping(p1, states) {
  const before = new Set(p1.cases.map((c) => c.state));
  const now = new Set(states.map((s) => s.name));
  return {
    mapped: [...before].filter((s) => now.has(s)).length,
    new: [...now].filter((s) => !before.has(s)).sort(),
    retired: [...before].filter((s) => !now.has(s)).sort(),
  };
}

/**
 * P1 against the current product, case by case: only case keys both measured
 * are compared (a distribution over different case sets would read a de-planned
 * or newly not-applicable case as an improvement). P1 cases no longer planned,
 * P1 cases now not-applicable, and current cases P1 never had are their own
 * categories.
 */
export function p1ToCurrent(p1, sweep, longTasks, plannedKeys = null) {
  const cur = sweep.cases.filter(isOrdinary);
  const keyOf = (c) => `${c.state}|${c.viewport}|${c.kind}`;
  const curBy = new Map(cur.map((c) => [keyOf(c), c]));
  const planned = plannedKeys ?? new Set(curBy.keys());
  const p1nav = (c) => num(c.cls);
  const p1prep = (c) => num(c.clsPreparation?.value);
  const curnav = (c) => (c?.perf?.cls?.status === 'measured' ? c.perf.cls.value : null);
  const curprep = (c) => (c?.perf?.clsPreparation?.status === 'measured' ? c.perf.clsPreparation.value : null);
  const family = (p1f, curf) => {
    const matched = []; const dePlanned = []; const nowNotApplicable = [];
    for (const c of p1.cases) {
      const before = p1f(c); if (before === null) continue;
      const k = keyOf(c);
      if (!planned.has(k)) { dePlanned.push({ at: where(c), p1: before }); continue; }
      const now = curf(curBy.get(k));
      if (now === null) { nowNotApplicable.push({ at: where(c), p1: before, status: curBy.get(k)?.perf ? 'not-applicable' : 'missing' }); continue; }
      matched.push({ at: where(c), tier: c.tier, p1: before, current: now });
    }
    const p1Keys = new Set(p1.cases.filter((c) => p1f(c) !== null).map(keyOf));
    const newlyMeasured = cur.filter((c) => curf(c) !== null && !p1Keys.has(keyOf(c))).length;
    const byTier = Object.fromEntries(TIERS.map((t) => {
      const m = matched.filter((x) => x.tier === t);
      return [t, { matched: m.length, p1: distribution(m.map((x) => x.p1)), current: distribution(m.map((x) => x.current)), worse: m.filter((x) => clsUnits(x.current) > clsUnits(x.p1)).length }];
    }));
    return {
      byTier,
      largestP1Outliers: [...matched].sort((a, b) => b.p1 - a.p1).slice(0, 15),
      largestRegressions: matched.filter((x) => clsUnits(x.current) > clsUnits(x.p1)).sort((a, b) => (b.current - b.p1) - (a.current - a.p1)).slice(0, 15).map((x) => ({ ...x, delta: fromUnits(clsUnits(x.current) - clsUnits(x.p1)) })),
      dePlannedP1Cases: dePlanned,
      p1MeasuredNowNotApplicable: nowNotApplicable,
      currentCasesWithoutP1: newlyMeasured,
    };
  };
  const p1Tasks = p1.cases.filter((c) => c.longTasks && typeof c.longTasks === 'object' && c.longTasks.count > 0).map((c) => ({ at: where(c), interaction: c.interaction, count: c.longTasks.count, maxMs: c.longTasks.maxMs }));
  const curTasks = longTasks.cases.filter((c) => isOrdinary(c) && c.perf?.longTasks?.status === 'measured' && c.perf.longTasks.count > 0).map((c) => ({ at: where(c), interaction: c.perf.longTasks.interaction, count: c.perf.longTasks.count, maxMs: c.perf.longTasks.maxMs }));
  return {
    navigation: family(p1nav, curnav),
    preparation: family(p1prep, curprep),
    longTasks: {
      p1: { measured: p1.cases.filter((c) => c.longTasks && typeof c.longTasks === 'object').length, withTasks: p1Tasks },
      current: { measured: longTasks.cases.filter((c) => isOrdinary(c) && c.perf?.longTasks?.status === 'measured').length, withTasks: curTasks },
    },
  };
}

/**
 * Windows (P1's environment) against P1, class by class: where the current
 * Windows maximum stands against P1's, and whether it is within the class's
 * tolerance of it. Continuity evidence; never the blocking gate.
 */
export function windowsContinuity(windows, windowsLongTasks, budgets = PERFORMANCE_BUDGETS) {
  const cur = windows.cases.filter(isOrdinary);
  const rows = [];
  const family = (list, f, limitOf) => {
    for (const cls of list) {
      const members = cur.filter((c) => f(c) !== null && limitOf(c)?.class === cls.name);
      const top = members.reduce((b, c) => (!b || f(c) > f(b) ? c : b), null);
      const p1 = cls.evidence?.p1?.value ?? null;
      const tol = cls.tolerance ?? (cls.tier ? budgets.cls.tolerance[cls.tier] : budgets.cls.tolerance.preparation);
      const value = top ? f(top) : null;
      rows.push({
        class: cls.name, p1, windows: value, at: top ? where(top) : null,
        withinP1: p1 === null || value === null ? null : clsUnits(value) <= clsUnits(p1) + clsUnits(tol),
        ...(cls.kind === 'explicit-new' && p1 !== null ? { note: 'explicit class qualified above P1' } : {}),
      });
    }
  };
  family(budgets.cls.navigation, (c) => (c.perf?.cls?.status === 'measured' ? c.perf.cls.value : null), (c) => navigationLimit(c, budgets));
  family(budgets.cls.preparation, (c) => (c.perf?.clsPreparation?.status === 'measured' ? c.perf.clsPreparation.value : null), (c) => preparationLimit(c, budgets));
  const tasks = windowsLongTasks ? windowsLongTasks.cases.filter((c) => isOrdinary(c) && c.perf?.longTasks?.count > 0).map((c) => ({ at: where(c), interaction: c.perf.longTasks.interaction, count: c.perf.longTasks.count, maxMs: c.perf.longTasks.maxMs })) : null;
  return { head: windows.head, classes: rows, outsideP1: rows.filter((r) => r.withinP1 === false && !r.note).map((r) => r.class), longTasks: tasks };
}

export function qualification({ sweep, longTasks, windows, windowsLongTasks, p1, states, plan, ciRun }) {
  const verdict = evaluatePerformance({ sweep, longTasks, plan });
  const continuity = windows ? windowsContinuity(windows, windowsLongTasks) : null;
  if (continuity && continuity.head !== sweep.head) verdict.faults.push(`the Windows continuity sweep (${continuity.head}) is not of the implementation head (${sweep.head})`);
  const surfaces = [...new Set(states.map((s) => surfaceOf(s.path)))].sort();
  const pass = verdict.faults.length === 0 && verdict.findings.length === 0;
  const b = PERFORMANCE_BUDGETS;
  const limit = (cls, tol) => fromUnits(clsUnits(cls.reference) + clsUnits(tol));
  return {
    schema: 'mavi.stage3-5.x3-performance-qualification.v1',
    generatedBy: 'tools/web-visual-qa/performance-qualification.mjs',
    implementationHead: sweep.head,
    p1: { file: b.baseline.file, schema: p1.schema, sha: p1.implementationHead, measurementCode: p1.implementationHead, environment: p1.environment },
    environment: {
      enforcement: { where: 'GitHub Actions ubuntu-latest, the Quality Gate (visual sweep aggregate + performance long tasks)', ciRun, sweep: { fullSweep: sweep.fullSweep, executions: sweep.executions ?? null }, longTasks: { workers: longTasks.workers, longTaskLane: longTasks.longTaskLane } },
      continuity: windows ? { where: 'Windows 11, uncontended local run (P1\'s environment)', sweepWorkers: windows.workers ?? null, longTaskWorkers: windowsLongTasks?.workers ?? null } : null,
      measurementCode: 'settle.mjs perfCollect, unchanged in method from the P1 measurement code',
    },
    budgets: {
      schema: b.schema, source: 'tools/web-visual-qa/performance-budgets.mjs', calibration: b.calibration, comparison: b.comparison,
      tolerance: b.cls.tolerance, toleranceDerivation: b.cls.toleranceWhy,
      navigation: b.cls.navigation.map((c) => ({ class: c.name, surface: c.surface, tier: c.tier, ...(c.states ? { states: c.states } : {}), reference: c.reference, tolerance: c.tolerance ?? b.cls.tolerance[c.tier], limit: limit(c, c.tolerance ?? b.cls.tolerance[c.tier]), definedBy: c.definedBy, kind: c.kind, environmentCalibrated: Boolean(c.environment), p1: c.evidence?.p1 ?? null })),
      preparation: b.cls.preparation.map((c) => ({ class: c.name, surface: c.surface, ...(c.by ? { by: c.by } : { states: c.states }), reference: c.reference, tolerance: c.tolerance ?? b.cls.tolerance.preparation, limit: limit(c, c.tolerance ?? b.cls.tolerance.preparation), definedBy: c.definedBy, kind: c.kind, p1: c.evidence?.p1 ?? null })),
      longTasks: { default: b.longTasks.default, classes: b.longTasks.classes },
      fonts: b.fonts,
    },
    mapping: { ...stateMapping(p1, states), surfaces },
    results: {
      faults: verdict.faults,
      findings: verdict.findings,
      cases: { sweep: verdict.rows.length, longTasks: verdict.longTaskRows.length },
      navigation: { byTier: verdict.summary.navigation.byTier, bySurface: verdict.summary.navigation.bySurface, nearest: verdict.summary.navigation.nearest },
      preparation: { byTier: verdict.summary.preparation.byTier, bySurface: verdict.summary.preparation.bySurface, nearest: verdict.summary.preparation.nearest },
      longTasks: { measured: verdict.summary.longTasks.measured, withTasks: verdict.summary.longTasks.withTasks, nearest: verdict.longTaskRows.filter((r) => r.count > 0) },
      fonts: { families: verdict.summary.fonts.families, documentFaces: verdict.summary.fonts.documentFaces, custom: verdict.rows.filter((r) => r.font?.custom).length },
    },
    // Case by case against P1 in P1's own environment (Windows) where the
    // continuity run is given — a Linux value against a Windows one mixes the
    // product with the platform's font metrics — and on Linux, labelled so.
    p1ToCurrent: {
      ...(windows ? { windows: { environment: 'Windows 11, the environment P1 was measured in: the like-for-like comparison', ...p1ToCurrent(p1, windows, windowsLongTasks ?? longTasks, plan?.sweep ?? null) } } : {}),
      linux: { environment: 'Linux CI, the enforcement environment: against P1’s Windows values, so platform font metrics are part of every difference', ...p1ToCurrent(p1, sweep, longTasks, plan?.sweep ?? null) },
    },
    windowsContinuity: continuity,
    verdict: pass ? 'PASS' : 'FAIL',
  };
}

// --- The command line ---------------------------------------------------------------

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}
const readJson = (file) => JSON.parse(readFileSync(resolve(file), 'utf8'));

async function main() {
  if (!arg('sweep') || !arg('long-tasks')) throw new HarnessError('--sweep and --long-tasks (the implementation head\'s CI evidence) are required');
  const statesModule = await import('./states.mjs');
  const doc = qualification({
    sweep: readJson(arg('sweep')), longTasks: readJson(arg('long-tasks')),
    windows: arg('windows-sweep') ? readJson(arg('windows-sweep')) : null,
    windowsLongTasks: arg('windows-long-tasks') ? readJson(arg('windows-long-tasks')) : null,
    p1: readJson(join(REPO, PERFORMANCE_BUDGETS.baseline.file)),
    states: statesModule.STATES, plan: ordinaryPlan(statesModule), ciRun: arg('ci-run'),
  });
  const out = resolve(REPO, arg('out', OUT));
  writeFileSync(out, JSON.stringify(doc, null, 2) + '\n');
  process.stdout.write(`${doc.verdict}: ${doc.results.cases.sweep} sweep cases, ${doc.results.cases.longTasks} long-task cases on ${doc.implementationHead}; ${doc.results.findings.length} finding(s), ${doc.results.faults.length} fault(s); Windows outside P1: ${doc.windowsContinuity?.outsideP1.join(', ') || 'none'}\nwrote ${out}\n`);
  process.exitCode = doc.verdict === 'PASS' ? 0 : 1;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => { process.stderr.write(`HARNESS ERROR: ${error instanceof HarnessError ? error.message : error.stack || error}\n`); process.exitCode = 2; });
}
