/**
 * The assertion manifest (register V1): every §26 rule is registered, every
 * rule the code can produce is registered, every registered rule has code
 * (or is a declared future rule), and the severity model rejects what it must.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { manifestSummary, ROUTES, RULES, severityOf, SURFACES, surfaceOf, TIERS, validateManifest } from '../manifest.mjs';

const source = (file) => readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');

/**
 * The rule ids the execution engine can produce, read from the code that
 * produces them: a finding (`fail(...)`, `add(...)`, `record(c, ...)`,
 * `rule: '...'`), an evaluation (`evaluated.add(...)`, `markEvaluated(...)`),
 * and the overlay exit probe's chosen rule.
 */
export function implementedRules() {
  const ids = new Set();
  const RULE = "'([a-z0-9]+(?:\\.[a-z0-9-]+)+)'";
  for (const file of ['assertions.mjs', 'run.mjs']) {
    const text = source(file);
    for (const pattern of [
      new RegExp(`(?:fail|add|evaluated\\.add)\\(\\s*${RULE}`, 'g'),
      new RegExp(`record\\(c,\\s*${RULE}`, 'g'),
      new RegExp(`rule:\\s*${RULE}`, 'g'),
      new RegExp(`\\?\\s*${RULE}\\s*:\\s*${RULE}`, 'g'),
      // A conditional evaluation: `...(measured ? ['perf.cls'] : [])`.
      new RegExp(`\\?\\s*\\[\\s*${RULE}\\s*\\]`, 'g'),
    ]) {
      for (const match of text.matchAll(pattern)) for (const id of match.slice(1)) if (id) ids.add(id);
    }
    for (const match of text.matchAll(/markEvaluated\(c,\s*\[([^\]]+)\]\)/g)) {
      for (const id of match[1].matchAll(new RegExp(RULE, 'g'))) ids.add(id[1]);
    }
  }
  return ids;
}

const clone = () => structuredClone(RULES);

describe('the assertion manifest', () => {
  it('is valid against the code that executes it', () => {
    assert.deepEqual(validateManifest(RULES, implementedRules()), []);
  });

  it('registers every rule §26 names, at every tier', () => {
    const SECTION_26 = [
      // existing, kept
      'page.horizontal-overflow', 'page.uncaught-error', 'page.control-overlap', 'page.token-resolution',
      'a11y.focus-visible', 'archetype.contained-clipping', 'ledger.scroll-ownership', 'record.scroll-ownership',
      'investigation.geometry', 'investigation.scroll-ownership', 'workbench.geometry', 'workbench.scroll-ownership',
      'review.composition',
      // added in Stage 3.5
      'ledger.row-pitch', 'surface.one-primary', 'containment.depth', 'ledger.containment', 'state.placement',
      'a11y.skip-link', 'a11y.landmarks', 'overlay.drawer', 'overlay.dialog', 'text.overflow', 'pressed.visible',
      'tier.b-shell', 'tier.c-shell', 'tier.c-workbench-unsupported',
      // owned by later slices (review.sticky-rendered: R6, now blocking at Tier A)
      'review.sticky-rendered', 'perf.cls', 'perf.long-tasks', 'typography.resolved-font',
    ];
    for (const rule of SECTION_26) {
      assert.ok(RULES[rule], `${rule} is not registered`);
      for (const tier of TIERS) assert.ok(RULES[rule].tiers[tier], `${rule} has no status at Tier ${tier}`);
    }
  });

  it('makes the S1-implemented rules blocking at Tier A', () => {
    for (const rule of ['ledger.row-pitch', 'surface.one-primary', 'ledger.containment', 'state.placement', 'a11y.skip-link',
      'a11y.landmarks', 'overlay.dialog', 'overlay.drawer', 'pressed.visible', 'page.horizontal-overflow',
      'page.uncaught-error', 'page.control-overlap', 'page.token-resolution', 'a11y.focus-visible']) {
      assert.equal(severityOf(rule, 'A').status, 'blocking', rule);
    }
    // The surface-scoped S1 rules block in every S1 region, on any surface.
    for (const rule of ['text.overflow', 'containment.depth']) assert.equal(severityOf(rule, 'A', 'foundation').status, 'blocking', rule);
  });

  it('blocks nothing at Tier B or C before S5, and names the owner of what it measures', () => {
    for (const [rule, entry] of Object.entries(RULES)) {
      for (const tier of ['B', 'C']) {
        const at = entry.tiers[tier];
        assert.notEqual(at.status, 'blocking', `${rule} blocks at Tier ${tier}`);
        if (at.status === 'measured/pending') assert.match(at.owner, /S[1-7]/, `${rule} @ ${tier} owner`);
      }
    }
  });

  it('keeps the later-slice rules measured with their owners named', () => {
    assert.match(severityOf('perf.cls', 'A').owner, /X3/);
    assert.match(severityOf('a11y.zoom-200', 'A').owner, /T3/);
    assert.match(severityOf('containment.depth', 'A', 'camera-analytics').owner, /M4/);
  });

  it('blocks the rendered Review pin at Tier A once R6 made it hold, and nowhere below it', () => {
    assert.equal(severityOf('review.sticky-rendered', 'A').status, 'blocking');
    for (const tier of ['B', 'C']) assert.equal(severityOf('review.sticky-rendered', tier).status, 'measured/pending', tier);
  });

  it('rejects an invalid severity', () => {
    const rules = clone();
    rules['page.horizontal-overflow'].tiers.A = { status: 'warning' };
    assert.ok(validateManifest(rules).some((p) => p.includes('invalid status "warning"')));
  });

  it('rejects an unknown rule identifier', () => {
    assert.throws(() => severityOf('page.no-such-rule', 'A'), /unregistered rule/);
  });

  it('rejects a not-applicable entry without a reason, and a pending one without an owner', () => {
    const rules = clone();
    rules['page.width-discipline'].tiers.B = { status: 'not-applicable' };
    rules['perf.cls'].tiers.A = { status: 'measured/pending' };
    const problems = validateManifest(rules);
    assert.ok(problems.some((p) => p.includes('not-applicable without a reason')));
    assert.ok(problems.some((p) => p.includes('without an owning slice')));
  });

  it('rejects a blocking rule below Tier A, and a measurement that blocks', () => {
    const rules = clone();
    rules['ledger.row-pitch'].tiers.B = { status: 'blocking' };
    rules['perf.cls'].tiers.A = { status: 'blocking' };
    const problems = validateManifest(rules);
    assert.ok(problems.some((p) => p.includes('ledger.row-pitch @ B: blocking below Tier A')));
    assert.ok(problems.some((p) => p.includes('perf.cls: a measurement rule cannot block')));
  });

  it('rejects a future rule without an execution policy', () => {
    const rules = clone();
    delete rules['a11y.zoom-200'].execution;
    assert.ok(validateManifest(rules).some((p) => p.includes('future rule without an execution policy')));
  });

  it('fails when a registered rule loses its implementation', () => {
    const implemented = implementedRules();
    implemented.delete('pressed.visible');
    assert.ok(validateManifest(RULES, implemented).some((p) => p.includes('pressed.visible: registered as assertion but no code produces it')));
  });

  it('fails when code produces a rule the manifest does not register', () => {
    const rules = clone();
    delete rules['text.overflow'];
    assert.ok(validateManifest(rules, implementedRules()).some((p) => p.includes('text.overflow: produced by code but not registered')));
  });

  it('reads the implemented rules from the code, not from the manifest', () => {
    const implemented = implementedRules();
    for (const rule of ['ledger.row-pitch', 'surface.one-primary', 'pressed.visible', 'overlay.dialog', 'containment.depth', 'perf.cls']) {
      assert.ok(implemented.has(rule), `${rule} not found in the code`);
    }
    assert.ok(!implemented.has('a11y.zoom-200'), 'a future rule appears in the code');
  });

  it('summarises by tier and status', () => {
    const summary = manifestSummary();
    assert.equal(summary.rules, Object.keys(RULES).length);
    for (const tier of TIERS) {
      const total = Object.values(summary.byTier[tier]).reduce((a, b) => a + b, 0);
      assert.equal(total, summary.rules);
    }
    assert.equal(summary.byTier.B.blocking, 0);
    assert.equal(summary.byTier.C.blocking, 0);
  });
});

describe('surface scope (V1: S1 blocking, unmigrated surfaces measured against their own row)', () => {
  const accepted = (...names) => Object.fromEntries(Object.entries(SURFACES).map(([name, s]) => [name, { ...s, accepted: s.accepted || names.includes(name) }]));

  it('names the owning row of every unmigrated surface', () => {
    const owners = { 'camera-analytics': /M4/, overview: /R1/, videos: /R2/, 'processing-detail': /R3/, 'processing-queue': /M2/, import: /M3/ };
    for (const [surface, owner] of Object.entries(owners)) {
      const at = severityOf('containment.depth', 'A', surface);
      assert.equal(at.status, 'measured/pending', surface);
      assert.match(at.owner, owner, surface);
    }
  });

  it('blocks the accepted Scene Editor at Tier A on its own, and nowhere below it (R4)', () => {
    assert.equal(SURFACES['scene-editor'].accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'scene-editor').status, 'blocking', rule);
      for (const tier of ['B', 'C']) assert.equal(severityOf(rule, tier, 'scene-editor').status, 'measured/pending', `${rule} @ ${tier}`);
    }
    // Its acceptance promotes nothing else.
    assert.equal(severityOf('containment.depth', 'A', 'processing-queue').status, 'measured/pending');
    assert.equal(surfaceOf('/cameras/abc/scene'), 'scene-editor');
  });

  it('blocks the accepted Search at Tier A on its own, and nowhere below it (R5)', () => {
    assert.equal(SURFACES.search.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'search').status, 'blocking', rule);
      for (const tier of ['B', 'C']) assert.equal(severityOf(rule, tier, 'search').status, 'measured/pending', `${rule} @ ${tier}`);
    }
    // Its acceptance promotes nothing else.
    assert.equal(severityOf('containment.depth', 'A', 'camera-analytics').status, 'measured/pending');
    assert.equal(surfaceOf('/search'), 'search');
  });

  it('blocks the accepted Review at Tier A on its own, and nowhere below it (R6)', () => {
    assert.equal(SURFACES.review.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'review').status, 'blocking', rule);
      for (const tier of ['B', 'C']) assert.equal(severityOf(rule, tier, 'review').status, 'measured/pending', `${rule} @ ${tier}`);
    }
    // Its acceptance promotes nothing else: not the R1-R3 rows, whose
    // promotion is the separate governance change recorded under R4.
    for (const other of ['overview', 'videos', 'processing-detail', 'processing-queue', 'camera-analytics']) {
      assert.equal(severityOf('containment.depth', 'A', other).status, 'measured/pending', other);
    }
  });

  it('blocks the accepted Cameras Ledger at Tier A on its own, and nowhere below it (M1)', () => {
    assert.equal(SURFACES.cameras.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'cameras').status, 'blocking', rule);
      for (const tier of ['B', 'C']) assert.equal(severityOf(rule, tier, 'cameras').status, 'measured/pending', `${rule} @ ${tier}`);
    }
    // Its acceptance promotes nothing else: not the other S4 rows, not Camera
    // Analytics beneath the same /cameras path, and not the R1-R3 rows, whose
    // promotion is the separate governance change recorded under R4.
    for (const other of ['overview', 'videos', 'processing-detail', 'processing-queue', 'import', 'camera-analytics']) {
      assert.equal(severityOf('containment.depth', 'A', other).status, 'measured/pending', other);
    }
    assert.equal(surfaceOf('/cameras'), 'cameras');
    assert.equal(surfaceOf('/cameras/abc/analytics'), 'camera-analytics');
  });

  it('blocks a Ledger table that does not fit its frame at Tier A on every Ledger, and only measures it below (M1)', () => {
    assert.equal(severityOf('ledger.columns-fit', 'A').status, 'blocking');
    for (const tier of ['B', 'C']) assert.match(severityOf('ledger.columns-fit', tier).owner, /S5/);
  });

  it('promotes one surface at a time, never all together', () => {
    const surfaces = accepted('processing-queue');
    assert.equal(severityOf('containment.depth', 'A', 'processing-queue', { surfaces }).status, 'blocking');
    assert.equal(severityOf('text.overflow', 'A', 'processing-queue', { surfaces }).status, 'blocking');
    assert.equal(severityOf('containment.depth', 'A', 'import', { surfaces }).status, 'measured/pending');
    assert.equal(severityOf('containment.depth', 'A', 'camera-analytics', { surfaces }).status, 'measured/pending');
  });

  it('never lets a surface status soften a finding in an S1 region, nor promote anything below Tier A', () => {
    for (const surfaces of [SURFACES, accepted('search', 'review')]) {
      assert.equal(severityOf('containment.depth', 'A', 'foundation', { surfaces }).status, 'blocking');
      for (const tier of ['B', 'C']) assert.equal(severityOf('containment.depth', tier, 'search', { surfaces }).status, 'measured/pending');
    }
  });

  it('refuses a surface-scoped finding that names no surface or an unknown one', () => {
    assert.throws(() => severityOf('text.overflow', 'A'), /surface-scoped/);
    assert.throws(() => severityOf('text.overflow', 'A', 'invented'), /unknown surface/);
  });

  it('maps every route a state uses to a surface, and refuses one it does not know', () => {
    assert.equal(surfaceOf('/'), 'overview');
    assert.equal(surfaceOf('/processing/abc?tab=x'), 'processing-detail');
    assert.equal(surfaceOf('/processing'), 'processing-queue');
    assert.equal(surfaceOf('/cameras/abc/analytics'), 'camera-analytics');
    assert.throws(() => surfaceOf('/settings'), /no surface owns route/);
    for (const [, name] of ROUTES) assert.ok(SURFACES[name], name);
  });

  it('rejects a surface-scoped rule that does not block at Tier A, and a foundation that does not block', () => {
    const rules = clone();
    rules['containment.depth'].tiers.A = { status: 'measured/pending', owner: 'S3' };
    assert.ok(validateManifest(rules).some((p) => p.includes('a surface-scoped rule must block at Tier A')));
    const surfaces = { ...SURFACES, foundation: { owner: 'S1', accepted: false } };
    assert.ok(validateManifest(RULES, null, { surfaces }).some((p) => p.includes('S1 regions must always block')));
  });
});
