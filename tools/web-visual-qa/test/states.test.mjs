/**
 * The tier-aware state model (register V2) and the no-fixed-delay rule for
 * preparations (V3), checked against the registered states.
 */
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { HarnessError, planCases } from '../engine.mjs';
import { SURFACES, surfaceOf } from '../manifest.mjs';
import { ANCHORS, STATE_KEYS, STATES, TIER_POLICIES, tierOf } from '../states.mjs';

const plan = (overrides = {}) => planCases({ states: STATES, anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf, ...overrides });

describe('anchors and tiers', () => {
  it('sweeps exactly the frozen nine anchors (§26 as amended)', () => {
    assert.deepEqual(ANCHORS.map((a) => `${a.tier}:${a.width}x${a.height}`), [
      'A:1366x768', 'A:1440x900', 'A:1920x1080', 'A:2560x1080', 'A:2560x1440',
      'B:1024x768', 'B:768x1024', 'C:430x932', 'C:390x844',
    ]);
  });

  it('classifies widths by the §25 ranges', () => {
    assert.equal(tierOf(1366), 'A');
    assert.equal(tierOf(1365), 'B');
    assert.equal(tierOf(1120), 'B');
    assert.equal(tierOf(768), 'B');
    assert.equal(tierOf(767), 'C');
    assert.equal(tierOf(390), 'C');
    assert.equal(tierOf(389), null);
  });
});

describe('state applicability', () => {
  it('lets no state carry a severity, a known-issue list or any key the model does not define', () => {
    for (const state of STATES) {
      for (const key of Object.keys(state)) assert.ok(STATE_KEYS.has(key), `${state.name}: ${key}`);
    }
    for (const key of ['knownIssues', 'severity', 'blocking', 'status']) assert.ok(!STATE_KEYS.has(key), key);
  });

  it('excludes a tier only through a policy that says why', () => {
    for (const [name, policy] of Object.entries(TIER_POLICIES)) {
      for (const tier of ['A', 'B', 'C']) {
        if (policy.tiers.includes(tier)) continue;
        assert.ok(policy.excluded[tier] && policy.excluded[tier].length > 40, `${name} leaves out ${tier} without a reason`);
      }
    }
    assert.deepEqual(TIER_POLICIES['all-tiers'].tiers, ['A', 'B', 'C']);
  });

  it('refuses a policy that drops a tier silently', () => {
    const policies = { ...TIER_POLICIES, sneaky: { tiers: ['A'], excluded: { B: 'not designed yet, at all, for the moment, honestly' } } };
    const states = [{ name: 'x', path: '/', fullWidth: false, tierPolicy: 'sneaky' }];
    assert.throws(() => planCases({ states, anchors: ANCHORS, policies, stateKeys: STATE_KEYS, tierOf }), HarnessError);
  });

  it('refuses an unknown policy and an unknown state key', () => {
    assert.throws(() => planCases({ states: [{ name: 'x', path: '/', tierPolicy: 'nope' }], anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf }), /unknown tier policy/);
    assert.throws(() => planCases({ states: [{ name: 'x', path: '/', knownIssues: ['.'] }], anchors: ANCHORS, policies: TIER_POLICIES, stateKeys: STATE_KEYS, tierOf }), /unknown key "knownIssues"/);
  });

  it('keeps Tier A out of the matrix only for breakpoint probes, which name their base state and widths', () => {
    for (const state of STATES) {
      const policy = state.tierPolicy ?? 'all-tiers';
      if (TIER_POLICIES[policy].tiers.includes('A')) continue;
      assert.equal(policy, 'breakpoint-probe', state.name);
      assert.ok(state.probeWidths?.length, `${state.name} probes no width`);
      const base = STATES.find((s) => s.name === state.probeOf);
      assert.ok(base, `${state.name} probes an unknown base state`);
      // A probe can leave the matrix only because its base state is in it at
      // every Tier A anchor: a probe is never a way out of a blocking tier.
      assert.ok(TIER_POLICIES[base.tierPolicy ?? 'all-tiers'].tiers.includes('A'), `${state.name}: its base state is not swept at Tier A`);
      assert.equal(base.path, state.path, `${state.name} probes a different route from its base state`);
    }
  });

  it('applies the footage-variant policy only to footage states', () => {
    for (const state of STATES.filter((s) => s.tierPolicy === 'footage-variant')) {
      assert.ok(state.footage, `${state.name} has no footage condition`);
      assert.equal(state.archetype, 'review', state.name);
    }
  });

  it('applies the typography-variant policy only to wide-font states that measure their pressure', () => {
    const variants = STATES.filter((s) => s.tierPolicy === 'typography-variant');
    assert.ok(variants.length > 0);
    for (const state of variants) {
      assert.match(state.name, /-wide-font$/, state.name);
      assert.match(state.prepare, /throw new Error\('the rendered typography is not wide enough/, state.name);
      // Its base state is swept at every tier.
      const base = STATES.find((s) => s.name === state.name.replace(/-wide-font$/, ''));
      assert.ok(base, `${state.name} has no base state`);
      assert.deepEqual(TIER_POLICIES[base.tierPolicy ?? 'all-tiers'].tiers, ['A', 'B', 'C'], state.name);
    }
  });

  it('pairs every held loading state with a request that never answers, and back', () => {
    for (const state of STATES) {
      const hangs = Object.values(state.api ?? {}).includes('hang');
      assert.equal(Boolean(state.holds === 'loading'), hangs, state.name);
    }
  });

  it('plans the default sweep from the policies and reports every exclusion', () => {
    const { cases, applicability } = plan();
    const anchorCases = cases.filter((c) => c.viewport.kind === 'anchor');
    const tierCount = (tier) => anchorCases.filter((c) => c.viewport.tier === tier).length;
    const applies = (tier) => applicability.filter((a) => a.tiers.includes(tier)).length;
    assert.equal(tierCount('A'), applies('A') * 5);
    assert.equal(tierCount('B'), applies('B') * 2);
    assert.equal(tierCount('C'), applies('C') * 2);
    for (const entry of applicability) {
      for (const tier of ['A', 'B', 'C'].filter((t) => !entry.tiers.includes(t))) assert.ok(entry.excluded[tier], `${entry.state} ${tier}`);
    }
    const probes = cases.filter((c) => c.viewport.kind === 'probe').map((c) => `${c.state.name}@${c.viewport.width}`);
    assert.ok(probes.includes('scene-editor-side-by-side-threshold@1120'));
    assert.ok(probes.includes('search-threshold@1599'));
    assert.ok(probes.includes('search-inspecting-evidence@1600'));
  });

  it('keeps every special-width probe the harness had before', () => {
    const probed = (name) => STATES.find((s) => s.name === name)?.probeWidths ?? [];
    // T1: the Workbench drawer probe became the measured side-by-side threshold probe.
    assert.deepEqual(probed('scene-editor-side-by-side-threshold'), [1101, 1120, 1149]);
    assert.deepEqual(probed('search-threshold'), [1440, 1500, 1550, 1599, 1600, 1700]);
    for (const name of ['search-inspecting-evidence', 'search-inspecting-evidence-unavailable', 'review-evidence-set',
      'review-evidence-selected', 'review-evidence-representative-only', 'review-evidence-crop-unavailable']) {
      assert.ok(probed(name).includes(1600), name);
    }
  });
});

describe('preparations', () => {
  it('establish wide-font pressure from rendered widths, never from the declared family list (M2, Codex P2)', () => {
    const state = STATES.find((s) => s.name === 'processing-queue-row-degraded-wide-font');
    // The serialised font-family names every family declared, installed or not.
    assert.doesNotMatch(state.prepare, /fontFamily\s*\)?\s*\.(startsWith|includes)|\/Verdana\/\.test/);
    // It measures what the original row needed against the cell's cap, and
    // refuses to report the state reached when the rendered font is narrower.
    assert.match(state.prepare, /getBoundingClientRect\(\)\.width/);
    assert.match(state.prepare, /maxWidth/);
    assert.match(state.prepare, /throw new Error\('the rendered typography is not wide enough/);
  });

  it('establish the bucket table heading pressure from rendered widths, never from the declared family list (M4, CI)', () => {
    const state = STATES.find((s) => s.name === 'analytics-line-crossings-wide-font');
    assert.doesNotMatch(state.prepare, /fontFamily\s*\)?\s*\.(startsWith|includes)|\/Verdana\/\.test/);
    // Scoped to the table under test, not the page.
    assert.match(state.prepare, /'\.analytics-table, \.analytics-table \* \{ font-family:/);
    assert.match(state.prepare, /getBoundingClientRect\(\)\.width/);
    assert.match(state.prepare, /throw new Error\('the rendered typography is not wide enough/);
  });

  it('never sleep for a guessed duration (V3)', () => {
    for (const state of STATES.filter((s) => s.prepare)) {
      assert.doesNotMatch(state.prepare, /setTimeout|\bwait\(/, `${state.name} sleeps`);
    }
  });

  it('name an operator interaction only where a preparation performs one (P1)', () => {
    const interactions = STATES.filter((s) => s.interaction);
    assert.ok(interactions.length >= 10, 'interactions are designated');
    for (const state of interactions) {
      assert.ok(state.prepare, `${state.name} names an interaction it never performs`);
      assert.ok(typeof state.interaction === 'string' && state.interaction.length > 8, state.name);
    }
    // Fixture setup and passive checks are not interactions.
    for (const name of ['not-found', 'review-saturated', 'search-analytics-scene-degraded', 'search-field-errors']) {
      assert.equal(STATES.find((s) => s.name === name).interaction, undefined, name);
    }
  });
});

describe('surfaces', () => {
  it('give every state a surface, so a surface-scoped finding always has an owner', () => {
    for (const state of STATES) assert.ok(SURFACES[surfaceOf(state.path)], state.name);
    assert.ok(plan().cases.every((c) => c.surface), 'every planned case carries its surface');
  });
});
