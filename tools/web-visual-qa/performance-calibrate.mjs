/**
 * Stage 3.5 S6/X3 (§38): the budgets, derived — never typed.
 *
 * From the P1 baseline and a same-head calibration (two Linux CI samples, the
 * enforcement environment; one uncontended Windows sweep, continuity with P1,
 * which was measured on Windows; the single-lane long-task runs of both), this
 * writes performance-budgets.mjs: every class with the case that defines its
 * reference, its P1 reference, the calibration's own values, its tolerance and
 * its kind. The owner's decisions (which classes are explicit, which one is
 * environment-calibrated, the tolerances) are DECISIONS below, each with the
 * evidence that justified it; everything else follows from the data.
 *
 * The derivation:
 *  - navigation classes: surface x tier; preparation classes: surface x
 *    transition (`by`). An explicit class names its states and takes them out
 *    of their surface's class.
 *  - reference = min(P1 class maximum, the larger Linux sample's class maximum):
 *    the ratchet. P1 is a Windows measurement, so it bounds Linux only through
 *    this min. A class P1 never measured has its Linux maximum.
 *  - an environment-calibrated class (named in DECISIONS, and only where
 *    Linux exceeds P1 while Windows stays within tolerance of P1) has its
 *    Linux maximum as reference instead.
 *  - an explicit preparation class approved above P1 has its Linux maximum.
 *  - comparison in integer units of 1e-4.
 *
 *   node tools/web-visual-qa/performance-calibrate.mjs \
 *     --linux a/results.json,b/results.json --windows w/results.json \
 *     --linux-long-tasks x.json,y.json --windows-long-tasks p.json,q.json \
 *     [--write] [--table out.md]
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { HarnessError } from './engine.mjs';
import { surfaceOf } from './manifest.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '..', '..');
const TIERS = ['A', 'B', 'C'];
const U = (v) => Math.round(v * 10000);
const F = (u) => u / 10000;

/** The owner's decisions on the 5363c673 / db619129 calibration review (2026-10-12). */
export const DECISIONS = Object.freeze({
  baseline: {
    file: 'docs/qualification/stage3-5/s2-p1-performance-baseline.json',
    sha: 'db20f3e7',
  },
  tolerance: {
    // About 1.2x the largest same-head difference (Linux pairs 2bb486ca,
    // 40e0c3e5, 5363c673; Windows sweeps), rounded up to 0.0005: above every
    // observed noise, not materially larger.
    A: 0.004, B: 0.002, C: 0.0075, preparation: 0.0035,
    why: 'Same-head per-case differences: Tier A max 0.0033 (Linux) / 0.0004 (Windows); Tier B 0.0013 / 0.0012; Tier C 0.0060 / 0 (excluding search-analytics-inspecting@390x844, a two-mode arrival-order race reported, not budgeted); preparation 0.0027 / 0.0022.',
  },
  explicitNavigation: [{
    name: 'search: filter names unresolved',
    surface: 'search',
    states: ['search-filtered-unresolved'],
    // The highest demonstrated legitimate value per tier across the 12-run
    // Linux evidence set (961ff8eb x2, f9ef6a4f x2, 2bb486ca x2, 40e0c3e5 x2,
    // 5363c673 x2, db619129 x2): the systematic arrival modes belong in the
    // reference; the tier tolerance stays for repeatability alone.
    references: { A: 0.0876, B: 0.0971, C: 0.2538 },
    referenceEvidence: {
      A: '0.0876 = search-filtered-unresolved@1920x1080 in two consecutive frames (0.0282 + 0.0585), identically on 961ff8eb (both samples) and db619129 (sample 1); the same viewport measures 0.0512 or 0.0637 when the two statements land in one frame. P1 measured 0.0637 there (0.0646 at 1366x768).',
      B: '0.0971 = search-filtered-unresolved@1024x768 (two-frame mode; 0.0901 in one), below P1 0.1513.',
      C: '0.2538 = search-filtered-unresolved@390x844 (one-frame mode; 0.2347 in two), below P1 0.2661.',
    },
    why: [
      'The cameras-list and videos-list failures are independent requests.',
      'Their failure statements can legitimately render in the same frame or in consecutive frames; each moves the investigation grid.',
      'The 0.0876 Tier A mode has occurred identically on three runs across three commits.',
      'Synchronising the requests merely to lower CLS would delay known failure information and violate the §37.1 independence of each request’s state.',
      'A larger tolerance to absorb the mode was rejected: the mode is systematic, not repeatability noise (the 0.0225 class tolerance once proposed is retired).',
      'So this is an explicit failure-path class with an evidence-derived reference above the P1 Tier A observation, split out of ordinary Search; not a relaxation of Search or of Tier A.',
    ].join(' '),
  }, {
    name: 'review: scene geometry unavailable',
    surface: 'review',
    states: ['review-geometry-unavailable'],
    // The highest demonstrated legitimate value per tier. At Tiers A and B the
    // rail moves in two or three consecutive frames (a <=0.011 shift of the
    // layers row, then the facts); on a faster runner they can land in one,
    // which scores higher: 1440x900 measured 0.0450 in eleven Linux samples
    // across seven commits and 0.0605 once (06e16ec8, one frame).
    references: { A: 0.0605, B: 0.1247, C: 0.1205 },
    referenceEvidence: {
      A: '0.0605 = review-geometry-unavailable@1440x900 with its two movements in one frame (Linux, MAVI Quality Gate run 38202495528, 06e16ec8); 0.0450 when they land in consecutive frames (eleven samples). Below P1 (0.127-0.1295 at Tier A).',
      B: '0.1247 = review-geometry-unavailable@768x1024 (consecutive frames; every sample), below P1 0.3087.',
      C: '0.1205 = review-geometry-unavailable@430x932 (one movement; every sample), below P1 0.1476.',
    },
    why: 'The pinned scene revision cannot be loaded, so the zones, trip-line and crossing layer chips each state why beside the control and their row wraps (0.1247 at 768x1024, identical across samples). The normal path is the one kept still: X3 says loading quietly, so a review whose geometry arrives moves nothing (review@1024x768 0.0565-0.0748 to 0.0050); reserving three failure sentences on every load would undo that, and moving the reason off its chip would separate a statement from its control. A P1-ratcheted failure-path class (Linux 0.0559/0.1247/0.1205 against P1 0.1295/0.3087/0.1476), split out so it no longer sets the ordinary Review ceilings.',
  }],
  // Every preparation transition P1 never measured is qualified here, by
  // state, with its reason; the calibration refuses one that is not.
  explicitPreparation: [{
    name: 'search: scene refresh failure (names withdrawn)',
    surface: 'search',
    states: ['search-analytics-scene-degraded'],
    aboveP1: true,
    why: 'After a failed scene refresh the zone and line names are withdrawn (raw ids shown, correctly) and the rail states the failure with its Retry: an actionable alert that cannot be reserved while the scene is healthy. The coverage strip keeps its geometry through it (db619129). Approved as an explicit failure-path class.',
  }, {
    name: 'review: refresh failure on returning to a stale Review',
    surface: 'review',
    states: ['review-refresh-degraded'],
    why: 'New since P1. Returning to a stale Review, its refresh fails and the failure is stated with its Retry above the evidence: the review grid moves once as the statement arrives (0.0827 at 390x844, identical in every Linux and Windows sample). The statement arrives with the failure; there is nothing to reserve while the refresh may still succeed.',
  }, {
    name: 'scene-editor: stacked failure notices (dense workbench)',
    surface: 'scene-editor',
    states: ['scene-editor-dense'],
    why: 'New since P1 as a preparation (P1 measured this state’s navigation only). The dense-workbench fixture stacks genuine failures: the revision the operator asks for is refused and the video list is unavailable after its retry; each notice arrives when its request fails (about 1.25s and 2.27s) and moves the inspector and the footer (0.0911 at 768x1024, identical across samples). X3 removed the avoidable part, the two-reason note (0.30/0.47 to 0.09); what remains is failure statements arriving. Keyed by this state, never by the shared label "fixture preparation".',
  }, {
    name: 'review: open the runtime attestation and the record detail',
    surface: 'review',
    states: ['review-provenance-open'],
    why: 'New since P1. Opening the attestation disclosure expands it in place: at most 0.0005 (2560x1440), 0 elsewhere.',
  }],
  environmentCalibrated: [{
    name: 'processing-queue @ B',
    why: 'P1 0.0078 (Windows); current Windows 0.0079; Linux 0.0099 in both samples. The residual column reflow as "Run status unavailable" arrives is wider in DejaVu Sans; it is not absorbed into Tier B\'s tolerance.',
  }],
  longTasks: {
    default: { name: 'no long task', count: 0, maxMs: 0, why: 'P1: every declared interaction but Search selection raised none; the final head raised none on Linux or Windows.' },
    classes: [{
      name: 'Search result selection', interactions: ['select a result to inspect it'], count: 1, maxMs: 65,
      why: 'P1: one sporadic task in the 50-65ms band. Kept at the P1 envelope (not tightened to the latest 50-58ms): it has historical support.',
    }],
  },
  fonts: { documentFaces: 0, why: '§38 "fonts do not swap": the document holds no font face (no @font-face, no FontFace), so the platform stack resolves at layout and nothing can arrive late.' },
});

const ord = (r) => r.cases.filter((c) => c.kind === 'anchor' || c.kind === 'probe');
const key = (c) => `${c.state}|${c.viewport}|${c.kind}`;
const where = (c) => `${c.state}@${c.viewport}`;
const nav = (c) => (c?.perf?.cls?.status === 'measured' ? c.perf.cls.value : null);
const prep = (c) => (c?.perf?.clsPreparation?.status === 'measured' ? c.perf.clsPreparation.value : null);
const p1nav = (c) => (typeof c.cls === 'number' ? c.cls : null);
const p1prep = (c) => (c.clsPreparation && typeof c.clsPreparation === 'object' && typeof c.clsPreparation.value === 'number' ? c.clsPreparation.value : null);
const maxBy = (rows, f) => rows.reduce((b, c) => (f(c) !== null && (!b || f(c) > f(b)) ? c : b), null);

/**
 * The classes and their references, from the data and DECISIONS.
 * @returns {{ navigation: object[], preparation: object[], longTasks: object, problems: string[] }}
 */
export function deriveBudgets({ linux, windows, p1, stateSurface, linuxLongTasks = [], windowsLongTasks = [], decisions = DECISIONS }) {
  if (linux.length !== 2) throw new HarnessError('the calibration is two Linux samples of one head');
  // One head throughout: every sweep and every long-task run is of the head
  // being calibrated, or nothing is derived (the budgets and their metadata
  // would mix implementation revisions).
  const inputs = [
    ...linux.map((r, i) => [`Linux sample ${i + 1}`, r]), ['the Windows sweep', windows],
    ...linuxLongTasks.map((r, i) => [`Linux long-task run ${i + 1}`, r]), ...windowsLongTasks.map((r, i) => [`Windows long-task run ${i + 1}`, r]),
  ];
  for (const [what, r] of inputs) if (!r?.head) throw new HarnessError(`${what} names no head`);
  const heads = new Set(inputs.map(([, r]) => r.head));
  if (heads.size !== 1) throw new HarnessError(`the calibration mixes heads: ${inputs.map(([what, r]) => `${what} ${r.head.slice(0, 8)}`).join(', ')}`);
  const [L1, L2] = linux.map(ord);
  const W = ord(windows);
  const problems = [];
  const explicitNav = new Map(decisions.explicitNavigation.flatMap((d) => d.states.map((s) => [s, d])));
  const explicitPrep = new Map(decisions.explicitPreparation.flatMap((d) => d.states.map((s) => [s, d])));
  const envNames = new Set(decisions.environmentCalibrated.map((d) => d.name));
  const M2 = new Map(L2.map((c) => [key(c), c]));

  const build = ({ name, family, tier, f, p1f, inClass, p1In, tolerance, explicit, decision, states, by, surface }) => {
    const pick = (rows) => rows.filter((c) => inClass(c) && f(c) !== null);
    const l1 = pick(L1); const l2 = pick(L2); const w = pick(W);
    const l1m = maxBy(l1, f); const l2m = maxBy(l2, f); const wm = maxBy(w, f);
    if (!l1m && !l2m) return null;
    const definer = !l2m || (l1m && f(l1m) >= f(l2m)) ? l1m : l2m;
    const linuxMax = f(definer);
    const p1m = maxBy(p1.cases.filter((c) => p1In(c)), p1f);
    const p1v = p1m ? p1f(p1m) : null;
    const wMax = wm ? f(wm) : null;
    const environment = envNames.has(name);
    if (environment && !(p1v !== null && U(linuxMax) > U(p1v) && wMax !== null && U(wMax) <= U(p1v) + U(tolerance))) {
      problems.push(`"${name}" is named for environment calibration, but the evidence does not support it (P1 ${p1v}, Windows ${wMax}, Linux ${linuxMax})`);
    }
    const aboveP1 = explicit && family === 'preparation' && decision?.aboveP1;
    const decided = explicit && family === 'navigation' && decision?.references ? decision.references[tier] : undefined;
    if (decided !== undefined && U(linuxMax) > U(decided)) problems.push(`"${name}": the calibration's Linux ${linuxMax} (${where(definer)}) is above its evidence-derived reference ${decided}`);
    const reference = decided !== undefined ? decided : p1v === null || environment || aboveP1 ? linuxMax : F(Math.min(U(p1v), U(linuxMax)));
    const spread = Math.max(0, ...l1.map((c) => Math.abs(f(c) - (f(M2.get(key(c))) ?? 0))));
    const perCase = new Map();
    for (const c of [...l1, ...l2]) perCase.set(where(c), Math.max(perCase.get(where(c)) ?? 0, f(c)));
    const limit = F(U(reference) + U(tolerance));
    const nearest = [...perCase].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 3).map(([at, value]) => ({ at, value, headroom: F(U(limit) - U(value)) }));
    const kind = explicit ? 'explicit-new' : p1v !== null ? 'mapped' : family === 'preparation' ? 'explicit-new' : 'inherited-new';
    const definedBy = decided !== undefined ? `evidence: ${decision.referenceEvidence[tier]}`
      : environment || aboveP1 || p1v === null || U(linuxMax) <= U(p1v) ? `Linux ${where(definer)}` : `P1 ${where(p1m)}`;
    if (U(linuxMax) > U(limit)) problems.push(`"${name}": Linux ${linuxMax} (${where(definer)}) is over its own limit ${limit}`);
    const cls = {
      name, surface, ...(tier ? { tier } : {}), ...(states ? { states } : {}), ...(by ? { by } : {}),
      reference, definedBy, kind,
      ...(environment ? { environment: { p1: p1v, windows: wMax, linux: [l1m ? f(l1m) : null, l2m ? f(l2m) : null], rationale: decisions.environmentCalibrated.find((d) => d.name === name).why } } : {}),
      evidence: { p1: p1v === null ? null : { value: p1v, at: where(p1m) }, windows: wMax, linux: [l1m ? f(l1m) : null, l2m ? f(l2m) : null], spread: F(U(spread)), nearest },
      ...(decision?.why ? { why: decision.why } : {}),
    };
    return cls;
  };

  const navigation = [];
  const surfaces = [...new Set([...L1, ...L2].map((c) => c.surface))].sort();
  for (const s of surfaces) for (const t of TIERS) {
    const cls = build({
      name: `${s} @ ${t}`, family: 'navigation', tier: t, surface: s, f: nav, p1f: p1nav, tolerance: decisions.tolerance[t],
      inClass: (c) => c.surface === s && c.tier === t && !explicitNav.has(c.state),
      p1In: (c) => stateSurface[c.state] === s && c.tier === t && !explicitNav.has(c.state) && p1nav(c) !== null,
    });
    if (cls) navigation.push(cls);
  }
  for (const d of decisions.explicitNavigation) for (const t of TIERS) {
    const cls = build({
      name: `${d.name} @ ${t}`, family: 'navigation', tier: t, surface: d.surface, states: d.states, f: nav, p1f: p1nav, tolerance: decisions.tolerance[t], explicit: true, decision: d,
      inClass: (c) => d.states.includes(c.state) && c.tier === t,
      p1In: (c) => d.states.includes(c.state) && c.tier === t && p1nav(c) !== null,
    });
    if (cls) navigation.push(cls);
  }

  const preparation = [];
  const labels = new Map();
  for (const c of [...L1, ...L2]) if (prep(c) !== null && !explicitPrep.has(c.state)) labels.set(`${c.surface}: ${c.perf.clsPreparation.by}`, { surface: c.surface, by: c.perf.clsPreparation.by });
  for (const [name, { surface, by }] of [...labels].sort()) {
    if (!p1.cases.some((c) => stateSurface[c.state] === surface && p1prep(c) !== null && c.clsPreparation.by === by)) {
      problems.push(`the preparation transition "${by}" on ${surface} has no P1 measurement and no decision: qualify it in DECISIONS.explicitPreparation (by state, with its reason)`);
    }
    const cls = build({
      name, family: 'preparation', surface, by: [by], f: prep, p1f: p1prep, tolerance: decisions.tolerance.preparation,
      inClass: (c) => c.surface === surface && c.perf?.clsPreparation?.by === by && !explicitPrep.has(c.state),
      p1In: (c) => stateSurface[c.state] === surface && p1prep(c) !== null && c.clsPreparation.by === by && !explicitPrep.has(c.state),
    });
    if (cls) preparation.push(cls);
  }
  for (const d of decisions.explicitPreparation) {
    const cls = build({
      name: d.name, family: 'preparation', surface: d.surface, states: d.states, f: prep, p1f: p1prep, tolerance: decisions.tolerance.preparation, explicit: true, decision: d,
      inClass: (c) => d.states.includes(c.state), p1In: (c) => d.states.includes(c.state) && p1prep(c) !== null,
    });
    if (cls) preparation.push(cls);
  }

  // Long tasks: what the runs raised, against the decided classes.
  const lt = (runs, env) => runs.map((r) => {
    if (r.workers !== 1 || r.longTaskLane !== true) problems.push(`a ${env} long-task run is not the single-lane run`);
    const tasks = ord(r).filter((c) => c.perf?.longTasks?.status === 'measured' && c.perf.longTasks.count > 0);
    for (const c of tasks) {
      const own = decisions.longTasks.classes.find((k) => k.interactions.includes(c.perf.longTasks.interaction)) ?? decisions.longTasks.default;
      if (c.perf.longTasks.count > own.count || c.perf.longTasks.maxMs > own.maxMs) problems.push(`${env} ${where(c)}: "${c.perf.longTasks.interaction}" raised ${c.perf.longTasks.count} x ${c.perf.longTasks.maxMs}ms, over "${own.name}" — a finding to investigate, not a budget input`);
    }
    return { head: r.head, measured: ord(r).filter((c) => c.perf?.longTasks?.status === 'measured').length, tasks: tasks.map((c) => ({ at: where(c), interaction: c.perf.longTasks.interaction, count: c.perf.longTasks.count, maxMs: c.perf.longTasks.maxMs })) };
  });
  const longTasks = { linux: lt(linuxLongTasks, 'Linux'), windows: lt(windowsLongTasks, 'Windows') };
  // What the calibration measured, in both Linux samples: a case that stops
  // being measured (a loading presentation renamed or removed, an interaction
  // that no longer applies) is a fault at the gate, never a silent pass. Both
  // samples agree on this set exactly (and six samples across three heads did).
  const both = (rows1, rows2, f) => {
    const second = new Set(rows2.filter((c) => f(c) !== null).map(key));
    const firstSet = new Set(rows1.filter((c) => f(c) !== null).map(key));
    for (const k of second) if (!firstSet.has(k)) problems.push(`${k}: measured in one Linux sample and not the other`);
    return [...firstSet].filter((k) => second.has(k)).sort();
  };
  const ltMeasured = (c) => (c?.perf?.longTasks?.status === 'measured' ? c.perf.longTasks.count : null);
  const measured = {
    navigation: both(L1, L2, nav),
    preparation: both(L1, L2, prep),
    longTasks: linuxLongTasks.length === 2 ? both(ord(linuxLongTasks[0]), ord(linuxLongTasks[1]), ltMeasured) : [],
  };
  if (!measured.longTasks.length) problems.push('the calibration has no two single-lane Linux long-task runs');
  return { head: linux[0].head, navigation, preparation, longTasks, measured, problems };
}

/** The budget module's source: the one canonical table. */
export function budgetModule(derived, { decisions = DECISIONS, calibration }) {
  const strip = ({ evidence, why, ...cls }) => ({ ...cls, ...(why ? { why } : {}), evidence });
  const table = {
    schema: 'mavi.stage3-5.x3-performance-budgets.v1',
    baseline: decisions.baseline,
    calibration,
    comparison: 'integer units: CLS in 1e-4, long tasks in whole milliseconds; a value at its limit passes',
    cls: {
      tolerance: { A: decisions.tolerance.A, B: decisions.tolerance.B, C: decisions.tolerance.C, preparation: decisions.tolerance.preparation },
      toleranceWhy: decisions.tolerance.why,
      navigation: derived.navigation.map(strip),
      preparation: derived.preparation.map(strip),
    },
    longTasks: {
      default: decisions.longTasks.default,
      classes: decisions.longTasks.classes,
      evidence: derived.longTasks,
    },
    fonts: decisions.fonts,
    measured: derived.measured,
  };
  return `/**
 * Stage 3.5 S6/X3 (§38): the performance budgets — the one canonical source.
 *
 * GENERATED by performance-calibrate.mjs from the P1 baseline and the
 * calibration named below; never edited by hand. Tests, the gate
 * (performance.mjs), the qualification artifact and the register read these
 * values; none holds a second copy (the register's block is checked against
 * this table). Each class carries the case that defines its reference, its P1
 * reference, the calibration's values and, where the owner decided it, why.
 */
export const PERFORMANCE_BUDGETS = Object.freeze(${JSON.stringify(table, null, 2)});
`;
}

/** The review table: one row per class, every column the owner asked for. */
export function reviewTable(derived, decisions = DECISIONS) {
  const f = (x) => (x == null ? '—' : x.toFixed(4));
  const rows = [...derived.navigation.map((c) => ({ ...c, family: 'navigation' })), ...derived.preparation.map((c) => ({ ...c, family: 'preparation' }))];
  const out = ['| Class | Family | Tier | Reference defined by | P1 (Windows) | Windows | Linux 1 | Linux 2 | Same-head spread | Reference | Tol | **Limit** | Nearest three (value, headroom) | Kind | Env-calibrated |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|'];
  for (const c of rows) {
    const tol = c.tolerance ?? (c.family === 'navigation' ? decisions.tolerance[c.tier] : decisions.tolerance.preparation);
    out.push(`| ${c.name} | ${c.family} | ${c.tier ?? 'A/B/C'} | ${c.definedBy} | ${c.evidence.p1 ? `${f(c.evidence.p1.value)} (${c.evidence.p1.at})` : '—'} | ${f(c.evidence.windows)} | ${f(c.evidence.linux[0])} | ${f(c.evidence.linux[1])} | ${f(c.evidence.spread)} | ${f(c.reference)} | ${f(tol)} | **${f(F(U(c.reference) + U(tol)))}** | ${c.evidence.nearest.map((n) => `${n.at} ${f(n.value)} (+${f(n.headroom)})`).join('<br>')} | ${c.kind} | ${c.environment ? 'yes' : 'no'} |`);
  }
  return out.join('\n');
}

// --- The command line ---------------------------------------------------------------

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}
const list = (name) => (arg(name) ?? '').split(',').filter(Boolean).map((f) => JSON.parse(readFileSync(resolve(f), 'utf8')));

async function main() {
  const { STATES } = await import('./states.mjs');
  const stateSurface = Object.fromEntries(STATES.map((s) => [s.name, surfaceOf(s.path)]));
  const p1 = JSON.parse(readFileSync(join(REPO, DECISIONS.baseline.file), 'utf8'));
  const linux = list('linux');
  const [windows] = list('windows');
  if (!windows) throw new HarnessError('--windows: the uncontended Windows sweep (continuity with P1) is part of the calibration');
  const derived = deriveBudgets({ linux, windows, p1, stateSurface, linuxLongTasks: list('linux-long-tasks'), windowsLongTasks: list('windows-long-tasks') });
  const table = reviewTable(derived);
  if (arg('table')) writeFileSync(resolve(arg('table')), table + '\n');
  else process.stdout.write(table + '\n');
  for (const p of derived.problems) process.stdout.write(`PROBLEM: ${p}\n`);
  if (process.argv.includes('--write')) {
    if (derived.problems.length) throw new HarnessError('the calibration has problems; nothing written');
    const calibration = { head: derived.head, linux: arg('linux-runs') ?? 'two CI samples of the head', windows: 'one uncontended sweep and two single-lane long-task runs of the head' };
    writeFileSync(join(HERE, 'performance-budgets.mjs'), budgetModule(derived, { calibration }));
    process.stdout.write(`wrote performance-budgets.mjs (${derived.navigation.length} navigation and ${derived.preparation.length} preparation classes, calibrated on ${derived.head})\n`);
  }
  process.exitCode = derived.problems.length ? 1 : 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => { process.stderr.write(`HARNESS ERROR: ${error instanceof HarnessError ? error.message : error.stack || error}\n`); process.exitCode = 2; });
}
