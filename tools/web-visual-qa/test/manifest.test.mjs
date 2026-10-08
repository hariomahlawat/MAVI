/**
 * The assertion manifest (register V1): every §26 rule is registered, every
 * rule the code can produce is registered, every registered rule has code
 * (or is a declared future rule), and the severity model rejects what it must.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { describe, it } from 'node:test';
import { manifestSummary, RULES, severityOf, TIERS, validateManifest } from '../manifest.mjs';

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
      'a11y.skip-link', 'a11y.landmarks', 'overlay.drawer', 'overlay.dialog', 'text.overflow', 'text.overflow-surface', 'pressed.visible',
      'tier.b-shell', 'tier.c-shell', 'tier.c-workbench-unsupported',
      // owned by later slices, measured now
      'review.sticky-rendered', 'perf.cls', 'perf.long-tasks', 'typography.resolved-font',
    ];
    for (const rule of SECTION_26) {
      assert.ok(RULES[rule], `${rule} is not registered`);
      for (const tier of TIERS) assert.ok(RULES[rule].tiers[tier], `${rule} has no status at Tier ${tier}`);
    }
  });

  it('makes the S1-implemented rules blocking at Tier A', () => {
    for (const rule of ['ledger.row-pitch', 'surface.one-primary', 'ledger.containment', 'state.placement', 'a11y.skip-link',
      'a11y.landmarks', 'overlay.dialog', 'overlay.drawer', 'text.overflow', 'pressed.visible', 'page.horizontal-overflow',
      'page.uncaught-error', 'page.control-overlap', 'page.token-resolution', 'a11y.focus-visible']) {
      assert.equal(severityOf(rule, 'A').status, 'blocking', rule);
    }
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
    assert.match(severityOf('review.sticky-rendered', 'A').owner, /R6/);
    assert.match(severityOf('perf.cls', 'A').owner, /X3/);
    assert.match(severityOf('a11y.zoom-200', 'A').owner, /T3/);
    assert.match(severityOf('containment.depth', 'A').owner, /S3|S4/);
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
    for (const rule of ['ledger.row-pitch', 'surface.one-primary', 'pressed.visible', 'overlay.dialog', 'harness.state-reached', 'perf.cls']) {
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
