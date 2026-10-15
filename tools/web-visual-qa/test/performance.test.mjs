// S6/X3: the performance gate's enforcement, adversarially. Each test feeds
// the real evaluator a small, explicit budget table and synthetic results, so
// what is proven is the mechanism — a finding where a valid measurement is
// over its limit, a harness fault where the evidence itself is wrong — not
// the frozen values, which have their own test against the real table.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { PERFORMANCE_BUDGETS } from '../performance-budgets.mjs';
import { DECISIONS, deriveBudgets } from '../performance-calibrate.mjs';
import {
  caseKey, clsUnits, evaluatePerformance, GATE_REQUEST_ADMISSION, GATE_RESPONSE_ORDER, longTaskLimit, navigationLimit, ordinaryPlan, preparationLimit,
  registerBlock, registerDisagreements, REGISTER_MARKERS, validateBudgets,
} from '../performance.mjs';

const BUDGETS = Object.freeze({
  schema: 'test.budgets.v1',
  baseline: { file: 'p1.json', sha: 'p1sha' },
  cls: {
    tolerance: { A: 0.004, B: 0.002, C: 0.0075, preparation: 0.0035 },
    navigation: [
      { name: 'search @ A', surface: 'search', tier: 'A', reference: 0.0359, definedBy: 'search-no-timezone@1366x768', kind: 'mapped' },
      { name: 'search @ B', surface: 'search', tier: 'B', reference: 0.052, definedBy: 'search-no-timezone@1024x768', kind: 'mapped' },
      { name: 'search: filter names unresolved @ A', surface: 'search', tier: 'A', states: ['search-filtered-unresolved'], reference: 0.0876, definedBy: 'evidence: the two-frame mode', kind: 'explicit-new', why: 'test' },
      { name: 'processing-queue @ B', surface: 'processing-queue', tier: 'B', reference: 0.0099, definedBy: 'processing-queue-row-unavailable@1024x768', kind: 'mapped', environment: { p1: 0.0078, windows: 0.0079, linux: [0.0099, 0.0099], rationale: 'test' } },
    ],
    preparation: [
      { name: 'search: select a result to inspect it', surface: 'search', by: ['select a result to inspect it'], reference: 0.0124, definedBy: 'search-inspector-opened-narrow-band@600x900', kind: 'mapped' },
      { name: 'search: scene refresh failure', surface: 'search', states: ['search-analytics-scene-degraded'], reference: 0.017, definedBy: 'search-analytics-scene-degraded@430x932', kind: 'explicit-new', why: 'test' },
    ],
  },
  longTasks: {
    default: { name: 'no long task', count: 0, maxMs: 0 },
    classes: [{ name: 'Search result selection', interactions: ['select a result to inspect it'], count: 1, maxMs: 65 }],
  },
  fonts: { documentFaces: 0 },
  // What the calibration measured: the floor of what is judged.
  measured: {
    navigation: ['search|1024x768|anchor'],
    preparation: ['search-inspector-opened|1024x768|anchor'],
    longTasks: ['search-inspector-opened|1024x768|anchor'],
  },
});

const measured = (value, extra = {}) => ({ status: 'measured', value, ...extra });
const NA = { status: 'not-applicable' };
const FONTS = { status: 'measured', faces: 0, contextBar: [{ family: 'DejaVu Sans', custom: false, glyphs: 10 }], content: [{ family: 'DejaVu Sans', custom: false, glyphs: 40 }] };
function sweepCase({ state = 'search', viewport = '1366x768', tier = 'A', kind = 'anchor', surface = 'search', cls = measured(0), prep = NA, fonts = FONTS, valid = true } = {}) {
  return { state, viewport, tier, kind, surface, valid, reached: valid, perf: { cls, clsPreparation: prep, longTasks: NA }, fonts };
}
function ltCase({ state = 'search-inspector-opened', viewport = '1366x768', tier = 'A', interaction = 'select a result to inspect it', count = 0, maxMs = 0, status = 'measured' } = {}) {
  return { state, viewport, tier, kind: 'anchor', surface: 'search', valid: true, reached: true, perf: { longTasks: { status, interaction, count, maxMs, totalMs: count * maxMs } } };
}
const sweepOf = (cases, extra = {}) => ({ head: 'h', fullSweep: true, responseOrder: 'forward', requestAdmission: 'page-identity+cdp-pre-transport', cases, ...extra });
const lanesOf = (cases, extra = {}) => ({ head: 'h', longTaskLane: true, workers: 1, responseOrder: 'forward', requestAdmission: 'page-identity+cdp-pre-transport', cases, ...extra });
const judge = ({ sweep = [sweepCase()], lt = [ltCase()], sweepExtra, ltExtra, plan = null, budgets = BUDGETS } = {}) =>
  evaluatePerformance({ sweep: sweepOf(sweep, sweepExtra), longTasks: lanesOf(lt, ltExtra), plan, budgets });
const rules = (v) => v.findings.map((f) => f.rule);

describe('the performance gate (X3)', () => {
  it('passes a clean sweep and long-task run: no finding, no fault (the control the negatives rest on)', () => {
    const v = judge();
    assert.deepEqual(v.faults, []);
    assert.deepEqual(v.findings, []);
  });

  describe('boundaries: integer units of 1e-4, a value at its limit passes', () => {
    it('passes exactly at the reference', () => {
      assert.deepEqual(judge({ sweep: [sweepCase({ cls: measured(0.0359) })] }).findings, []);
    });
    it('passes exactly at reference + tolerance', () => {
      // 0.0359 + 0.004 = 0.0399, a sum binary floating point does not hold exactly.
      assert.notEqual(0.0359 + 0.004, 0.0399);
      assert.deepEqual(judge({ sweep: [sweepCase({ cls: measured(0.0399) })] }).findings, []);
    });
    it('fails one unit above it', () => {
      assert.deepEqual(rules(judge({ sweep: [sweepCase({ cls: measured(0.04) })] })), ['perf.cls']);
    });
    it('holds the same boundary for preparation CLS and for long tasks', () => {
      const at = sweepCase({ state: 'search-inspector-opened', prep: measured(0.0159, { by: 'select a result to inspect it' }) });
      const over = sweepCase({ state: 'search-inspector-opened', viewport: '1440x900', prep: measured(0.016, { by: 'select a result to inspect it' }) });
      assert.deepEqual(judge({ sweep: [at, over] }).findings.map((f) => f.key), ['search-inspector-opened|1440x900|anchor']);
      assert.deepEqual(judge({ lt: [ltCase({ count: 1, maxMs: 65 })] }).findings, []);
      assert.deepEqual(rules(judge({ lt: [ltCase({ count: 1, maxMs: 66 })] })), ['perf.long-tasks']);
    });
  });

  it('faults a case the calibration measured that now answers not-applicable: nothing stops being judged silently', () => {
    const navGone = sweepCase({ viewport: '1024x768', tier: 'B', cls: { status: 'not-applicable', why: 'no loading presentation was observed' } });
    const prepGone = sweepCase({ state: 'search-inspector-opened', viewport: '1024x768', tier: 'B', prep: { status: 'not-applicable', why: 'no preparation' } });
    const ltGone = { ...ltCase({ viewport: '1024x768', tier: 'B' }), perf: { longTasks: { status: 'not-applicable', why: 'the state has no interaction' } } };
    const v = judge({ sweep: [navGone, prepGone], lt: [ltGone] });
    assert.deepEqual(v.findings, []);
    assert.ok(v.faults.some((f) => f.startsWith('search|1024x768|anchor: navigation CLS was measured at calibration and is now not-applicable')));
    assert.ok(v.faults.some((f) => f.startsWith('search-inspector-opened|1024x768|anchor: preparation CLS was measured at calibration')));
    assert.ok(v.faults.some((f) => f.includes('long tasks was measured at calibration')));
    // A case the calibration never measured may be not-applicable.
    assert.deepEqual(judge({ sweep: [sweepCase({ viewport: '1440x900', cls: { status: 'not-applicable', why: 'none shown' } })] }).faults, []);
  });

  it('faults an unreached or invalid capture, and results that name no head', () => {
    const unreached = { ...sweepCase(), valid: false, reached: false };
    assert.ok(judge({ sweep: [unreached] }).faults.some((f) => f.includes('not a valid capture')));
    const ltUnreached = { ...ltCase(), valid: false };
    assert.ok(judge({ lt: [ltUnreached] }).faults.some((f) => f.includes('not a valid capture in the long-task run')));
    assert.ok(judge({ sweepExtra: { head: null } }).faults.includes('the sweep results name no head'));
    assert.ok(judge({ ltExtra: { head: undefined } }).faults.includes('the long-task results name no head'));
  });

  it('1. fails navigation CLS above its budget, naming the class and the case that defines it', () => {
    const v = judge({ sweep: [sweepCase({ cls: measured(0.0521) })] });
    assert.deepEqual(rules(v), ['perf.cls']);
    assert.match(v.findings[0].message, /navigation CLS 0\.0521 over its limit 0\.0399 \(search @ A: reference 0\.0359, defined by search-no-timezone@1366x768/);
    assert.deepEqual(v.faults, []);
  });

  it('2. fails preparation CLS above its own class, not a navigation limit', () => {
    const v = judge({ sweep: [sweepCase({ state: 'search-inspector-opened', prep: measured(0.03, { by: 'select a result to inspect it' }) })] });
    assert.deepEqual(rules(v), ['perf.cls']);
    assert.match(v.findings[0].message, /preparation CLS 0\.03 \("select a result to inspect it"\) over its limit 0\.0159 \(search: select a result to inspect it/);
  });

  it('3. never lets a good navigation CLS hide a bad preparation CLS', () => {
    const v = judge({ sweep: [sweepCase({ state: 'search-inspector-opened', cls: measured(0), prep: measured(0.2, { by: 'select a result to inspect it' }) })] });
    assert.equal(v.rows[0].navigation.pass, true);
    assert.equal(v.rows[0].preparation.pass, false);
    assert.deepEqual(rules(v), ['perf.cls']);
  });

  it('records the measured long tasks, and what the class permits, apart', () => {
    const v = judge({ lt: [ltCase({ count: 0, maxMs: 0 }), ltCase({ viewport: '1440x900', count: 1, maxMs: 52 })] });
    assert.deepEqual(v.longTaskRows.map((r) => [r.count, r.maxMs, r.permitted.count, r.permitted.maxMs]), [[0, 0, 1, 65], [1, 52, 1, 65]]);
    assert.deepEqual(v.summary.longTasks.withTasks.map((r) => [r.key, r.count, r.maxMs]), [['search-inspector-opened|1440x900|anchor', 1, 52]]);
  });

  it('4. fails a long task on an interaction whose baseline is zero', () => {
    const v = judge({ lt: [ltCase({ state: 'analytics-line-crossings', interaction: 'switch to line crossings', count: 1, maxMs: 51 })] });
    assert.deepEqual(rules(v), ['perf.long-tasks']);
    assert.match(v.findings[0].message, /its class "no long task" permits 0, each at most 0ms/);
  });

  it('5. fails Search selection over its permitted count or duration', () => {
    assert.deepEqual(rules(judge({ lt: [ltCase({ count: 2, maxMs: 52 })] })), ['perf.long-tasks']);
    assert.deepEqual(rules(judge({ lt: [ltCase({ count: 1, maxMs: 80 })] })), ['perf.long-tasks']);
  });

  it('6. faults a missing measurement, never a finding or a pass', () => {
    const noCls = sweepCase(); delete noCls.perf.cls;
    const noFont = sweepCase({ viewport: '1440x900', fonts: null });
    const noFaces = sweepCase({ viewport: '1920x1080', fonts: { ...FONTS, faces: undefined } });
    const noLt = ltCase(); delete noLt.perf.longTasks;
    const v = judge({ sweep: [noCls, noFont, noFaces], lt: [noLt] });
    assert.deepEqual(v.findings, []);
    assert.ok(v.faults.some((f) => f.includes('search|1366x768|anchor: navigation CLS missing')));
    assert.ok(v.faults.some((f) => f.includes('search|1440x900|anchor: resolved font missing')));
    assert.ok(v.faults.some((f) => f.includes('does not say how many font faces')));
    assert.ok(v.faults.some((f) => f.includes('long tasks missing')));
  });

  it('accepts a long-task case where the interaction does not apply, said with its reason — and faults one without a reason', () => {
    const rendered = { ...ltCase({ viewport: '390x844', tier: 'C' }), perf: { longTasks: { status: 'not-applicable', why: 'the state has no interaction: it is a rendered state' } } };
    assert.deepEqual(judge({ lt: [ltCase(), rendered] }).faults, []);
    const silent = { ...ltCase({ viewport: '390x844', tier: 'C' }), perf: { longTasks: { status: 'not-applicable' } } };
    assert.ok(judge({ lt: [ltCase(), silent] }).faults.some((f) => f.includes('390x844|anchor: long tasks not-applicable')));
  });

  it('7. faults "unsupported" and "failed" where the qualification browser supports the API', () => {
    const v = judge({
      sweep: [sweepCase({ cls: { status: 'unsupported', why: 'no layout-shift entries' } }), sweepCase({ viewport: '1440x900', prep: { status: 'failed', why: 'prepare threw' } })],
      lt: [ltCase({ status: 'unsupported' })],
    });
    assert.deepEqual(v.findings, []);
    assert.ok(v.faults.some((f) => /navigation CLS unsupported \(no layout-shift entries\)/.test(f)));
    assert.ok(v.faults.some((f) => /preparation CLS failed \(prepare threw\)/.test(f)));
    assert.ok(v.faults.some((f) => /long tasks unsupported/.test(f)));
  });

  it('8. faults a case with no budget class and nothing to inherit one from — and never lends it navigation\'s', () => {
    const newSurface = sweepCase({ state: 'reports', surface: 'reports', cls: measured(0) });
    const newTransition = sweepCase({ state: 'search-new', prep: measured(0.001, { by: 'a transition nobody qualified' }) });
    const v = judge({ sweep: [newSurface, newTransition] });
    assert.deepEqual(v.findings, []);
    assert.ok(v.faults.some((f) => f.includes('no navigation budget class for reports @ A')));
    assert.ok(v.faults.some((f) => f.includes('"a transition nobody qualified" on search belongs to no preparation budget class') && f.includes('never inherited')));
    // A new state on a known surface and tier inherits that class.
    assert.equal(navigationLimit({ state: 'search-new', surface: 'search', tier: 'A' }, BUDGETS).class, 'search @ A');
  });

  it('9. refuses a malformed or duplicated budget table before judging anything', () => {
    const twice = structuredClone(BUDGETS); twice.cls.navigation.push({ ...twice.cls.navigation[0] });
    assert.ok(validateBudgets(twice).some((p) => p.includes('"search @ A" is defined twice')));
    assert.ok(validateBudgets(twice).some((p) => p.includes('search|A|* belongs to "search @ A" and "search @ A"')));
    const negative = structuredClone(BUDGETS); negative.cls.tolerance.B = -0.002;
    assert.ok(validateBudgets(negative).some((p) => p.includes('cls.tolerance.B: not a non-negative number')));
    const both = structuredClone(BUDGETS); both.cls.preparation[0].states = ['x'];
    assert.ok(validateBudgets(both).some((p) => p.includes('either transitions (by) or named states, exactly one')));
    const shared = structuredClone(BUDGETS); shared.longTasks.classes.push({ name: 'again', interactions: ['select a result to inspect it'], count: 1, maxMs: 65 });
    assert.ok(validateBudgets(shared).some((p) => p.includes('belongs to "Search result selection" and "again"')));
    const unexplained = structuredClone(BUDGETS); delete unexplained.cls.preparation[1].why;
    assert.ok(validateBudgets(unexplained).some((p) => p.includes('"search: scene refresh failure": an explicit class states why')));
    const floorless = structuredClone(BUDGETS); floorless.measured.navigation = [];
    assert.ok(validateBudgets(floorless).some((p) => p.includes('measured.navigation')));
    const undefined_ = structuredClone(BUDGETS); delete undefined_.cls.navigation[0].definedBy;
    assert.ok(validateBudgets(undefined_).some((p) => p.includes('"search @ A": no defining case')));
    const env = structuredClone(BUDGETS); env.cls.navigation[3].environment = { linux: [0.0099] };
    assert.ok(validateBudgets(env).some((p) => p.includes('environment-calibrated class states its Linux evidence and why')));
    const v = judge({ budgets: twice, sweep: [sweepCase({ cls: measured(0.9) })] });
    assert.deepEqual(v.findings, [], 'a malformed table judges nothing');
    assert.ok(v.faults.every((f) => f.startsWith('the budget table is malformed')));
  });

  it('10. catches the register disagreeing with the budget source', () => {
    const register = (block) => `# Register\n\n${REGISTER_MARKERS.begin}\n\`\`\`\n${block}\n\`\`\`\n${REGISTER_MARKERS.end}\n`;
    assert.deepEqual(registerDisagreements(register(registerBlock(BUDGETS)), BUDGETS), []);
    const drifted = registerBlock(BUDGETS).replace('0.0359 + 0.0040 = 0.0399', '0.0359 + 0.0040 = 0.0450');
    const problems = registerDisagreements(register(drifted), BUDGETS);
    assert.ok(problems.some((p) => p.includes('does not state: navigation | search @ A | 0.0359 + 0.0040 = 0.0399')));
    assert.ok(problems.some((p) => p.includes('states what the budget source does not: navigation | search @ A | 0.0359 + 0.0040 = 0.0450')));
    assert.deepEqual(registerDisagreements('# no block', BUDGETS), ['the register carries no X3 budget block']);
  });

  it('12. fails a font that could swap: a non-platform face, or any font face in the document', () => {
    const custom = sweepCase({ fonts: { ...FONTS, content: [{ family: 'Inter', custom: true, glyphs: 40 }] } });
    const loaded = sweepCase({ viewport: '1440x900', fonts: { ...FONTS, faces: 1 } });
    const v = judge({ sweep: [custom, loaded] });
    assert.deepEqual(rules(v), ['typography.resolved-font', 'typography.resolved-font']);
    assert.match(v.findings[0].message, /Inter/);
    assert.match(v.findings[1].message, /1 font face\(s\) in the document/);
    // A different platform family is not a finding: no face is required across systems.
    assert.deepEqual(judge({ sweep: [sweepCase({ fonts: { ...FONTS, content: [{ family: 'Segoe UI Variable', custom: false, glyphs: 40 }] } })] }).findings, []);
  });

  it('13. refuses long tasks measured on more than one lane, or outside the long-task lane', () => {
    assert.ok(judge({ ltExtra: { workers: 3 } }).faults.some((f) => f.includes('measured on 3 lanes')));
    assert.ok(judge({ ltExtra: { longTaskLane: false } }).faults.some((f) => f.includes('not the long-task lane')));
    assert.ok(judge({ ltExtra: { head: 'other' } }).faults.some((f) => f.includes('different heads')));
  });

  it('judges only a forward run ordered by page-issued identity with pre-transport admission, free of harness faults', () => {
    assert.equal(GATE_RESPONSE_ORDER, 'forward');
    assert.equal(GATE_REQUEST_ADMISSION, 'page-identity+cdp-pre-transport');
    assert.ok(judge({ sweepExtra: { responseOrder: 'natural' } }).faults.some((f) => f.includes('the sweep answered its data requests in natural order')));
    assert.ok(judge({ ltExtra: { responseOrder: undefined } }).faults.some((f) => f.includes('the long-task run answered its data requests in natural order')));
    // `reverse` is no order the gate knows (rejected: generic reverse ordering).
    assert.ok(judge({ sweepExtra: { responseOrder: 'reverse' } }).faults.some((f) => f.includes('in reverse order')));
    // Forward without admission is server-arrival order: not evidence.
    assert.ok(judge({ sweepExtra: { requestAdmission: undefined } }).faults.some((f) => f.includes('the sweep was not ordered by page-issued identity with pre-transport admission')));
    assert.ok(judge({ ltExtra: { requestAdmission: 'none' } }).faults.some((f) => f.includes('the long-task run was not ordered by page-issued identity')));
    // A missing or duplicate identity is a harness fault in the run: the run is not evidence.
    assert.ok(judge({ sweepExtra: { harnessErrors: ['videos @ 1366x768: duplicate request identity d.3 (GET /api/videos) in epoch 4: refused before the fixtures'] } }).faults.some((f) => f.includes('the sweep reported a harness error: videos @ 1366x768: duplicate request identity')));
    assert.ok(judge({ ltExtra: { harnessErrors: ['x @ 1366x768: admission: a schedulable Fetch request without a page-issued identity: GET /api/x (failed, not admitted)'] } }).faults.some((f) => f.includes('without a page-issued identity')));
    assert.deepEqual(judge().faults, []);
  });

  it('14. faults a planned case missing from the sweep or the long-task run, and an unplanned one present', () => {
    const plan = { sweep: new Set(['search|1366x768|anchor', 'search|1024x768|anchor']), longTasks: new Set(['search-inspector-opened|1366x768|anchor', 'search-inspector-opened|390x844|anchor']) };
    const v = judge({ plan, sweep: [sweepCase(), sweepCase({ viewport: '2560x1440' })] });
    assert.ok(v.faults.includes('search|1024x768|anchor: planned but missing from the sweep'));
    assert.ok(v.faults.includes('search|2560x1440|anchor: in the sweep but not in the plan'));
    assert.ok(v.faults.includes('search-inspector-opened|390x844|anchor: declares an interaction but the long-task run did not measure it'));
    const extra = judge({ plan, sweep: [sweepCase(), sweepCase({ viewport: '1024x768' })], lt: [ltCase(), ltCase({ viewport: '390x844' }), ltCase({ viewport: '2560x1440' })] });
    assert.ok(extra.faults.includes('search-inspector-opened|2560x1440|anchor: in the long-task run but not in its plan'));
    assert.ok(judge({ sweepExtra: { fullSweep: false } }).faults.some((f) => f.includes('not the full sweep')));
  });

  it('15. faults a case present twice, in the sweep or the long-task run', () => {
    const v = judge({ sweep: [sweepCase(), sweepCase()], lt: [ltCase(), ltCase()] });
    assert.ok(v.faults.includes('search|1366x768|anchor: in the sweep 2 times'));
    assert.ok(v.faults.includes('search-inspector-opened|1366x768|anchor: in the long-task run 2 times'));
  });

  it('judges an explicit class before its surface class, at the tier tolerance', () => {
    assert.equal(navigationLimit({ state: 'search-filtered-unresolved', surface: 'search', tier: 'A' }, BUDGETS).limit, 0.0916);
    assert.equal(navigationLimit({ state: 'search', surface: 'search', tier: 'A' }, BUDGETS).limit, 0.0399);
    assert.equal(preparationLimit({ state: 'search-analytics-scene-degraded', surface: 'search', perf: { clsPreparation: { by: 'select a result to inspect it' } } }, BUDGETS).class, 'search: scene refresh failure');
    assert.equal(navigationLimit({ state: 'processing-queue', surface: 'processing-queue', tier: 'B' }, BUDGETS).environmentCalibrated, true);
    assert.equal(longTaskLimit('anything else', BUDGETS).class, 'no long task');
  });

  it('compares in units: no limit is a floating-point accident', () => {
    for (const [a, b] of [[0.0359, 0.004], [0.0876, 0.004], [0.0099, 0.002], [0.1681, 0.0075], [0.0162, 0.0035]]) {
      assert.equal(clsUnits(a) + clsUnits(b), Math.round((a + b) * 10000), `${a} + ${b}`);
    }
  });
});

describe('the calibration (performance-calibrate.mjs)', () => {
  it('refuses inputs of more than one head, or of none: budgets never mix implementation revisions', () => {
    const run = (head) => ({ head, cases: [], workers: 1, longTaskLane: true });
    const p1 = { cases: [] };
    const args = (over = {}) => ({ linux: [run('h'), run('h')], windows: run('h'), p1, stateSurface: {}, linuxLongTasks: [run('h'), run('h')], windowsLongTasks: [run('h')], ...over });
    assert.throws(() => deriveBudgets(args({ windows: run('other') })), /mixes heads: .*the Windows sweep other/);
    assert.throws(() => deriveBudgets(args({ linuxLongTasks: [run('h'), run('old')] })), /Linux long-task run 2 old/);
    assert.throws(() => deriveBudgets(args({ windowsLongTasks: [run(null)] })), /Windows long-task run 1 names no head/);
    assert.doesNotThrow(() => deriveBudgets(args()));
  });
});

describe('the frozen budget table (performance-budgets.mjs)', () => {
  it('is well formed', () => {
    assert.deepEqual(validateBudgets(PERFORMANCE_BUDGETS), []);
  });

  it('covers every surface at every tier the ordinary plan reaches with a navigation class', async () => {
    const states = await import('../states.mjs');
    const { STATES } = states;
    const plan = ordinaryPlan(states);
    assert.ok(plan.sweep.size > 1000, 'the ordinary plan is the whole product');
    const bySurface = new Map(STATES.map((s) => [s.name, s]));
    const { surfaceOf } = await import('../manifest.mjs');
    const tierOfLabel = new Map();
    for (const c of (await import('../engine.mjs')).planCases({ states: STATES, anchors: states.ANCHORS, policies: states.TIER_POLICIES, stateKeys: states.STATE_KEYS, tierOf: states.tierOf, zoom: states.ZOOM, onlyZoom: 'none', onlyTextSpacing: 'none', onlyReducedMotion: 'none' }).cases) {
      tierOfLabel.set(caseKey({ state: c.state.name, viewport: c.viewport.label, kind: c.viewport.kind }), c.viewport.tier);
    }
    const missing = new Set();
    for (const key of plan.sweep) {
      const [state] = key.split('|');
      const surface = surfaceOf(bySurface.get(state).path);
      if (!navigationLimit({ state, surface, tier: tierOfLabel.get(key) })) missing.add(`${surface} @ ${tierOfLabel.get(key)}`);
    }
    // A surface without a navigation class must say why: the not-found page
    // shows no loading presentation, so its navigation CLS is not applicable
    // in every case; were it to start measuring one, the gate faults (no
    // class, nothing to inherit) until that transition is qualified.
    const unmeasured = { 'not-found @ A': 'no loading presentation', 'not-found @ B': 'no loading presentation', 'not-found @ C': 'no loading presentation' };
    assert.deepEqual([...missing].filter((m) => !unmeasured[m]), []);
  });

  it('is the owner’s decisions, exactly: no value DECISIONS did not set or the calibration derive', () => {
    const b = PERFORMANCE_BUDGETS;
    const { tolerance } = DECISIONS;
    assert.deepEqual(b.cls.tolerance, { A: tolerance.A, B: tolerance.B, C: tolerance.C, preparation: tolerance.preparation });
    assert.deepEqual(b.baseline, DECISIONS.baseline);
    assert.deepEqual(b.longTasks.default, DECISIONS.longTasks.default);
    assert.deepEqual(b.longTasks.classes, DECISIONS.longTasks.classes);
    assert.deepEqual(b.fonts, DECISIONS.fonts);
    // No class carries a tolerance of its own: the tiers' are the only ones.
    for (const c of [...b.cls.navigation, ...b.cls.preparation]) assert.equal(c.tolerance, undefined, c.name);
    // Environment calibration only where decided.
    assert.deepEqual(b.cls.navigation.filter((c) => c.environment).map((c) => c.name), DECISIONS.environmentCalibrated.map((d) => d.name));
    // Every explicit class is a decision, with its reason; its references as decided.
    for (const d of DECISIONS.explicitNavigation) {
      for (const t of ['A', 'B', 'C']) {
        const c = b.cls.navigation.find((k) => k.name === `${d.name} @ ${t}`);
        assert.ok(c, `${d.name} @ ${t}`);
        assert.deepEqual(c.states, d.states);
        assert.equal(c.why, d.why);
        if (d.references) assert.equal(c.reference, d.references[t], `${d.name} @ ${t}`);
      }
    }
    const explicitPrep = new Map(DECISIONS.explicitPreparation.map((d) => [d.name, d]));
    for (const c of [...b.cls.navigation, ...b.cls.preparation].filter((k) => k.kind === 'explicit-new')) {
      const d = explicitPrep.get(c.name) ?? DECISIONS.explicitNavigation.find((n) => c.name.startsWith(`${n.name} @ `));
      assert.ok(d, `${c.name} is explicit but no decision qualifies it`);
      assert.deepEqual(c.states, d.states, c.name);
    }
    // A preparation class keyed by a shared label is P1-measured; anything new
    // is keyed by its state.
    for (const c of b.cls.preparation.filter((k) => k.by)) assert.equal(c.kind, 'mapped', c.name);
  });

  it('agrees with the register', () => {
    const register = readFileSync(new URL('../../../docs/reviews/2026-10-07-stage3-5-ui-ux-professionalisation-acceptance.md', import.meta.url), 'utf8');
    assert.deepEqual(registerDisagreements(register), []);
  });
});
