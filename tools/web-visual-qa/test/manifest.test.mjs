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

/** The real surfaces with the named ones not accepted: the mechanism's subject now that every real one is. */
const notAccepted = (...names) => Object.fromEntries(Object.entries(SURFACES).map(([name, s]) => [name, { ...s, accepted: names.includes(name) ? false : s.accepted }]));

/** The register rows R1-R6 and M1-M4, each by the surface it owns. */
const ACCEPTED_ROWS = {
  overview: /R1/, videos: /R2/, 'processing-detail': /R3/, 'scene-editor': /R4/, search: /R5/, review: /R6/,
  cameras: /M1/, 'processing-queue': /M2/, import: /M3/, 'camera-analytics': /M4/,
};


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

  it('blocks Tier B from T1 and Tier C from T2, and names the owner of what it measures', () => {
    // T1 (S5) promoted every rule that judges a Tier B composition, and T2 every
    // rule that judges a Tier C one; a rule a later slice owns at Tier A stays
    // measured against that owner at Tiers B and C.
    const laterOwned = new Set(['a11y.target-size', 'perf.cls', 'perf.long-tasks', 'typography.resolved-font',
      'a11y.reduced-motion', 'a11y.keyboard-journeys', 'a11y.section23-remaining']);
    for (const [rule, entry] of Object.entries(RULES)) {
      const atB = entry.tiers.B;
      if (laterOwned.has(rule)) {
        assert.equal(atB.status, 'measured/pending', `${rule} @ B`);
        assert.doesNotMatch(atB.owner, /T1/, `${rule} @ B is not T1's`);
      } else if (atB.status !== 'not-applicable') {
        assert.equal(atB.status, 'blocking', `${rule} @ B is T1's and blocks`);
      }
      // No rule is left owned by T1 or T2: each is done or it is not.
      for (const tier of ['B', 'C']) assert.doesNotMatch(entry.tiers[tier].owner ?? '', /T1|T2/, `${rule} @ ${tier} still owned by T1 or T2`);
      const atC = entry.tiers.C;
      if (laterOwned.has(rule)) {
        assert.equal(atC.status, 'measured/pending', `${rule} @ C stays its owner's`);
        assert.match(atC.owner, /S6/, `${rule} @ C owner`);
      } else if (atC.status !== 'not-applicable') {
        assert.equal(atC.status, 'blocking', `${rule} @ C is T2's and blocks`);
      } else {
        assert.ok(atC.reason, `${rule} @ C not-applicable without a reason`);
      }
    }
    // The Tier B composition rules exist, block at B and only apply there.
    for (const rule of ['tier.b-shell', 'tier.b-composition']) {
      assert.equal(RULES[rule].tiers.B.status, 'blocking', rule);
      for (const tier of ['A', 'C']) assert.equal(RULES[rule].tiers[tier].status, 'not-applicable', `${rule} @ ${tier}`);
    }
    // The Tier C composition rules exist, block at C and only apply there.
    for (const rule of ['tier.c-shell', 'tier.c-composition', 'tier.c-workbench-unsupported']) {
      assert.equal(RULES[rule].tiers.C.status, 'blocking', rule);
      for (const tier of ['A', 'B']) assert.equal(RULES[rule].tiers[tier].status, 'not-applicable', `${rule} @ ${tier}`);
    }
    // The Ledger fold (Codex P1 on #199): blocks at every tier.
    for (const tier of ['A', 'B', 'C']) assert.equal(RULES['ledger.column-fold'].tiers[tier].status, 'blocking', tier);
  });

  it('blocks the 200% zoom rule (T3) where a zoom case lands — Tier C at 200%, Tier A zoomed back out — and nowhere else', () => {
    const zoom = RULES['a11y.zoom-200'];
    assert.equal(zoom.kind, 'assertion');
    assert.equal(zoom.lane, 'zoom');
    assert.equal(zoom.tiers.A.status, 'blocking');
    assert.equal(zoom.tiers.C.status, 'blocking');
    assert.equal(zoom.tiers.B.status, 'not-applicable');
    assert.match(zoom.tiers.B.reason, /683px \(Tier C\)/);
    // No entry is left owned by T3: it is done or it is not.
    for (const [rule, entry] of Object.entries(RULES)) {
      for (const tier of TIERS) assert.doesNotMatch(entry.tiers[tier].owner ?? '', /T3/, `${rule} @ ${tier} still owned by T3`);
    }
    // The leave guard reached at Tier C by a live zoom change makes a Dialog
    // reachable there: overlay.dialog blocks at every tier.
    for (const tier of TIERS) assert.equal(RULES['overlay.dialog'].tiers[tier].status, 'blocking', tier);
  });

  it('rejects an entry still owned by T3 after T3, and an unknown lane', () => {
    const rules = clone();
    rules['a11y.zoom-200'].tiers.C = { status: 'measured/pending', owner: 'S5 / T3' };
    rules['page.text-overlap'].lane = 'magnifier';
    const problems = validateManifest(rules);
    assert.ok(problems.some((p) => p.includes('a11y.zoom-200 @ C: still owned by T3 after T3')));
    assert.ok(problems.some((p) => p.includes('page.text-overlap: unknown lane "magnifier"')));
  });

  it('keeps the later-slice rules measured with their owners named', () => {
    assert.match(severityOf('perf.cls', 'A').owner, /X3/);
    assert.match(severityOf('a11y.reduced-motion', 'A').owner, /X4/);
    assert.match(severityOf('containment.depth', 'A', 'overview', { surfaces: notAccepted('overview') }).owner, /R1/);
  });

  it('blocks the rendered Review pin at Tier A (R6) and Tier B (T1); at Tier C the pin is released and tier.c-composition says so', () => {
    for (const tier of ['A', 'B']) assert.equal(severityOf('review.sticky-rendered', tier).status, 'blocking', tier);
    assert.equal(severityOf('review.sticky-rendered', 'C').status, 'not-applicable');
    assert.match(severityOf('review.sticky-rendered', 'C').reason, /tier\.c-composition/);
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

  it('rejects a Tier C entry still owned by T2, and a measurement that blocks', () => {
    const rules = clone();
    rules['page.text-overlap'].tiers.C = { status: 'measured/pending', owner: 'S5 / T2 (Tier C degradation)' };
    rules['perf.cls'].tiers.A = { status: 'blocking' };
    const problems = validateManifest(rules);
    assert.ok(problems.some((p) => p.includes('page.text-overlap @ C: still owned by T2 after T2')));
    assert.ok(problems.some((p) => p.includes('perf.cls: a measurement rule cannot block')));
    // Tier B blocking (T1) and Tier C blocking (T2) are the policy now, and valid.
    assert.deepEqual(validateManifest(RULES), []);
  });

  it('rejects a future rule without an execution policy', () => {
    const rules = clone();
    delete rules['a11y.reduced-motion'].execution;
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
    assert.ok(implemented.has('a11y.zoom-200'), 'the T3 zoom rule is not found in the code');
    assert.ok(!implemented.has('a11y.reduced-motion'), 'a future rule appears in the code');
  });

  it('summarises by tier and status', () => {
    const summary = manifestSummary();
    assert.equal(summary.rules, Object.keys(RULES).length);
    for (const tier of TIERS) {
      const total = Object.values(summary.byTier[tier]).reduce((a, b) => a + b, 0);
      assert.equal(total, summary.rules);
    }
    // T1: Tier B blocks on every composition rule; T2: so does Tier C.
    assert.ok(summary.byTier.B.blocking >= 30, `only ${summary.byTier.B.blocking} rules block at Tier B`);
    assert.ok(summary.byTier.C.blocking >= 30, `only ${summary.byTier.C.blocking} rules block at Tier C`);
  });
});

describe('surface scope (V1: S1 blocking, unmigrated surfaces measured against their own row)', () => {
  const accepted = (...names) => Object.fromEntries(Object.entries(SURFACES).map(([name, s]) => [name, { ...s, accepted: s.accepted || names.includes(name) }]));

  it('accepts every R1-R6 and M1-M4 surface, as the register records (retrospective R1-R3 correction)', () => {
    // The register recorded R1-R3 PASS while their flags stayed false, so their
    // surface findings never blocked. No accepted row may be exempt.
    for (const [surface, row] of Object.entries(ACCEPTED_ROWS)) {
      assert.equal(SURFACES[surface].accepted, true, surface);
      assert.match(SURFACES[surface].owner, row, surface);
    }
    const unaccepted = Object.entries(SURFACES).filter(([, s]) => !s.accepted).map(([name]) => name);
    assert.deepEqual(unaccepted, []);
  });

  it('blocks every surface-scoped rule at Tier A on every accepted surface', () => {
    const scoped = Object.keys(RULES).filter((id) => RULES[id].scope === 'surface');
    assert.deepEqual(scoped.sort(), ['containment.depth', 'ledger.actions-reachable', 'text.overflow']);
    for (const surface of Object.keys(ACCEPTED_ROWS)) {
      for (const rule of scoped) assert.equal(severityOf(rule, 'A', surface).status, 'blocking', `${rule} on ${surface}`);
    }
  });

  it('still names the owning row of a surface that is not accepted', () => {
    // The mechanism the correction relies on, on a hypothetical unaccepted surface.
    for (const [surface, row] of Object.entries({ overview: /R1/, videos: /R2/, 'processing-detail': /R3/ })) {
      const at = severityOf('containment.depth', 'A', surface, { surfaces: notAccepted(surface) });
      assert.equal(at.status, 'measured/pending', surface);
      assert.match(at.owner, row, surface);
    }
  });

  it('blocks the accepted Scene Editor at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (R4)', () => {
    assert.equal(SURFACES['scene-editor'].accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'scene-editor').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'scene-editor').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'scene-editor').status, 'blocking', `${rule} @ C`);
    }
    // A surface that is not accepted is still measured against its own row.
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces: notAccepted('overview') }).status, 'measured/pending');
    assert.equal(surfaceOf('/cameras/abc/scene'), 'scene-editor');
  });

  it('blocks the accepted Search at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (R5)', () => {
    assert.equal(SURFACES.search.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'search').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'search').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'search').status, 'blocking', `${rule} @ C`);
    }
    // A surface that is not accepted is still measured against its own row.
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces: notAccepted('overview') }).status, 'measured/pending');
    assert.equal(surfaceOf('/search'), 'search');
  });

  it('blocks the accepted Review at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (R6)', () => {
    assert.equal(SURFACES.review.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'review').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'review').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'review').status, 'blocking', `${rule} @ C`);
    }
    // Its acceptance promotes nothing else: not the R1-R3 rows, whose
    // promotion is the separate governance change recorded under R4.
    // A surface that is not accepted is still measured against its own row.
    const surfaces = notAccepted('overview');
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces }).status, 'measured/pending');
  });

  it('blocks the accepted Cameras Ledger at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (M1)', () => {
    assert.equal(SURFACES.cameras.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'cameras').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'cameras').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'cameras').status, 'blocking', `${rule} @ C`);
    }
    // Its acceptance promotes nothing else: not the R1-R3 rows, whose
    // promotion is the separate governance change recorded under R4. Camera
    // Analytics beneath the same /cameras path is its own surface (M4).
    // A surface that is not accepted is still measured against its own row.
    const surfaces = notAccepted('overview');
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces }).status, 'measured/pending');
    assert.equal(surfaceOf('/cameras'), 'cameras');
    assert.equal(surfaceOf('/cameras/abc/analytics'), 'camera-analytics');
  });

  it('blocks unreachable Ledger row actions on an accepted surface, and measures them against the owning row elsewhere (M1)', () => {
    assert.equal(RULES['ledger.actions-reachable'].scope, 'surface');
    assert.equal(severityOf('ledger.actions-reachable', 'A', 'cameras').status, 'blocking');
    // A surface not accepted: its own row owns what the rule finds there.
    const overview = severityOf('ledger.actions-reachable', 'A', 'overview', { surfaces: notAccepted('overview') });
    assert.equal(overview.status, 'measured/pending');
    assert.match(overview.owner, /R1/);
    assert.equal(severityOf('ledger.actions-reachable', 'B', 'cameras').status, 'blocking');
    assert.equal(severityOf('ledger.actions-reachable', 'C', 'cameras').status, 'blocking');
  });

  it('scopes "the Camera columns fit" to Cameras at Tier A, not to every Ledger (M1, §4.1)', () => {
    assert.equal(severityOf('cameras.actions-in-view', 'A').status, 'blocking');
    for (const tier of ['B', 'C']) assert.equal(severityOf('cameras.actions-in-view', tier).status, 'not-applicable');
    // No rule forbids a Ledger body from scrolling sideways (§4.1).
    assert.equal(RULES['ledger.columns-fit'], undefined);
    assert.equal(RULES['ledger.actions-in-view'], undefined);
  });

  it('blocks the accepted Processing queue at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (M2)', () => {
    assert.equal(SURFACES['processing-queue'].accepted, true);
    for (const rule of ['containment.depth', 'text.overflow', 'ledger.actions-reachable']) {
      assert.equal(severityOf(rule, 'A', 'processing-queue').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'processing-queue').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'processing-queue').status, 'blocking', `${rule} @ C`);
    }
    // Its acceptance promotes nothing else, and adds no Queue column-fit rule:
    // the Queue fits its frame by construction, and §4.1 lets a Ledger scroll.
    // A surface that is not accepted is still measured against its own row.
    const surfaces = notAccepted('overview');
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces }).status, 'measured/pending');
    assert.equal(Object.keys(RULES).filter((id) => id.startsWith('processing-queue.')).length, 0);
    assert.equal(surfaceOf('/processing'), 'processing-queue');
  });

  it('blocks the accepted Import Record at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (M3)', () => {
    assert.equal(SURFACES.import.accepted, true);
    for (const rule of ['containment.depth', 'text.overflow']) {
      assert.equal(severityOf(rule, 'A', 'import').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'import').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'import').status, 'blocking', `${rule} @ C`);
    }
    // Its acceptance promotes nothing else: not the R1–R3 rows, whose
    // promotion is the separate governance change.
    // A surface that is not accepted is still measured against its own row.
    const surfaces = notAccepted('overview');
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces }).status, 'measured/pending');
    assert.equal(surfaceOf('/import'), 'import');
  });

  it('blocks the accepted Camera Analytics Workbench at Tier A on its own, and at Tier B from T1, and at Tier C from T2 (M4)', () => {
    assert.equal(SURFACES['camera-analytics'].accepted, true);
    for (const rule of ['containment.depth', 'text.overflow', 'ledger.actions-reachable']) {
      assert.equal(severityOf(rule, 'A', 'camera-analytics').status, 'blocking', rule);
      assert.equal(severityOf(rule, 'B', 'camera-analytics').status, 'blocking', `${rule} @ B (T1)`);
      assert.equal(severityOf(rule, 'C', 'camera-analytics').status, 'blocking', `${rule} @ C`);
    }
    // With M4 every S4 surface migration is accepted ...
    for (const s4 of ['cameras', 'processing-queue', 'import', 'camera-analytics']) assert.equal(SURFACES[s4].accepted, true, s4);
    // ... and its acceptance promotes nothing else: not the R1–R3 rows, whose
    // promotion is the separate governance change.
    // A surface that is not accepted is still measured against its own row.
    const surfaces = notAccepted('overview');
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces }).status, 'measured/pending');
    assert.equal(surfaceOf('/cameras/abc/analytics'), 'camera-analytics');
  });

  it('promotes one surface at a time, never all together', () => {
    const surfaces = notAccepted('overview', 'videos', 'processing-detail');
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces }).status, 'measured/pending');
    const promoted = { ...surfaces, overview: { ...surfaces.overview, accepted: true } };
    assert.equal(severityOf('containment.depth', 'A', 'overview', { surfaces: promoted }).status, 'blocking');
    assert.equal(severityOf('text.overflow', 'A', 'overview', { surfaces: promoted }).status, 'blocking');
    assert.equal(severityOf('containment.depth', 'A', 'videos', { surfaces: promoted }).status, 'measured/pending');
    assert.equal(severityOf('containment.depth', 'A', 'processing-detail', { surfaces: promoted }).status, 'measured/pending');
  });

  it('never lets a surface status soften a finding in an S1 region, and blocks at Tier C only where the surface is accepted', () => {
    for (const surfaces of [SURFACES, accepted('search', 'review')]) {
      assert.equal(severityOf('containment.depth', 'A', 'foundation', { surfaces }).status, 'blocking');
      assert.equal(severityOf('containment.depth', 'C', 'search', { surfaces }).status, 'blocking');
    }
    // T2: an unaccepted surface's finding is still measured against its row at Tier C.
    assert.equal(severityOf('containment.depth', 'C', 'search', { surfaces: notAccepted('search') }).status, 'measured/pending');
    // At Tier B a surface-scoped finding blocks on an accepted surface (T1) and
    // is still measured against its row on one that is not.
    assert.equal(severityOf('containment.depth', 'B', 'search').status, 'blocking');
    assert.equal(severityOf('containment.depth', 'B', 'overview', { surfaces: notAccepted('overview') }).status, 'measured/pending');
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
