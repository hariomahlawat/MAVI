/**
 * The harness's decisions, apart from the browser plumbing: which cases run,
 * what a finding weighs, when a page has settled, and what the run exits with.
 * Kept separate from `run.mjs` so each decision is tested directly.
 */
import { RULES, severityOf, SURFACES, surfaceOf, TIERS } from './manifest.mjs';
import { settleProbe, TRANSIENT } from './settle.mjs';
import { toExpression } from './assertions.mjs';

/** A fault in the harness, never reported as a finding. */
export class HarnessError extends Error {}

/**
 * The cases a run executes, and every state's applicability per tier.
 * A state is swept at every anchor of every tier its policy applies to, plus
 * its probe widths; a tier is absent only through a policy that says why.
 */
export function planCases({ states, anchors, policies, stateKeys, tierOf, onlyStates = null, onlyTiers = null, onlyWidths = null, repeat = 1 }) {
  const applicability = states.map((state) => {
    for (const key of Object.keys(state)) {
      if (!stateKeys.has(key)) throw new HarnessError(`state ${state.name} carries unknown key "${key}"`);
    }
    const policyName = state.tierPolicy ?? 'all-tiers';
    const policy = policies[policyName];
    if (!policy) throw new HarnessError(`state ${state.name} names unknown tier policy "${policyName}"`);
    const excluded = {};
    for (const tier of TIERS) {
      if (policy.tiers.includes(tier)) continue;
      if (!policy.excluded?.[tier]) throw new HarnessError(`policy ${policyName} leaves out Tier ${tier} without a reason`);
      excluded[tier] = policy.excluded[tier];
    }
    return { state: state.name, policy: policyName, tiers: policy.tiers, excluded, probeWidths: state.probeWidths ?? [] };
  });

  const cases = [];
  for (const state of states) {
    if (onlyStates && !onlyStates.includes(state.name)) continue;
    let surface;
    try { surface = surfaceOf(state.path); } catch (error) { throw new HarnessError(`state ${state.name}: ${error.message}`); }
    const applies = applicability.find((entry) => entry.state === state.name);
    const viewports = anchors.filter((anchor) => applies.tiers.includes(anchor.tier)).map((anchor) => ({ ...anchor, kind: 'anchor' }));
    for (const width of state.probeWidths ?? []) {
      const label = `${width}x900`;
      if (viewports.some((viewport) => viewport.label === label)) continue;
      const tier = tierOf(width);
      if (!tier) throw new HarnessError(`state ${state.name} probes ${width}px, below every support tier`);
      viewports.push({ width, height: 900, label, tier, kind: 'probe' });
    }
    for (const viewport of viewports) {
      if (onlyTiers && !onlyTiers.includes(viewport.tier)) continue;
      if (onlyWidths && !onlyWidths.includes(viewport.width)) continue;
      for (let attempt = 1; attempt <= repeat; attempt += 1) cases.push({ state, viewport, attempt, surface });
    }
  }
  return { cases, applicability };
}

/**
 * Every finding and every evaluation goes through here, so its severity can
 * only come from the manifest. A finding or an evaluation the manifest does
 * not allow at that tier is a harness fault, not something to report.
 *
 * A surface-scoped rule is resolved on the surface it was found on: `scope`
 * `'foundation'` (an S1 region, wherever it is rendered) or, by default, the
 * case's own surface.
 */
export function createLedger(rules = RULES, surfaces = SURFACES) {
  const findings = [];
  const coverage = Object.fromEntries(Object.keys(rules).map((rule) => [rule, Object.fromEntries(TIERS.map((t) => [t, { evaluated: 0, blockingEvaluated: 0, findings: 0 }]))]));
  const tierOfCase = (c) => c.viewport.tier;
  const surfaceFor = (c, scope) => (scope === 'foundation' ? 'foundation' : c.surface ?? null);

  function resolve(rule, tier, surface, what) {
    if (!rules[rule]) throw new HarnessError(`unregistered rule "${rule}" ${what}: every assertion must have a manifest entry`);
    let at;
    try { at = severityOf(rule, tier, surface, { rules, surfaces }); } catch (error) { throw new HarnessError(`${rule} ${what}: ${error.message}`); }
    if (at.status === 'not-applicable') {
      throw new HarnessError(`${rule} ${what} at Tier ${tier}, where the manifest says it is not applicable (${at.reason})`);
    }
    return at;
  }

  return {
    findings,
    coverage,
    record(c, rule, message, scope = null) {
      const tier = tierOfCase(c);
      const surface = surfaceFor(c, scope);
      const at = resolve(rule, tier, surface, 'produced a finding');
      const finding = {
        state: c.state.name, viewport: c.viewport.label, tier, kind: c.viewport.kind, rule,
        ...(rules[rule].scope === 'surface' ? { surface } : {}),
        severity: at.status, owner: at.owner ?? null, message,
      };
      findings.push(finding);
      coverage[rule][tier].findings += 1;
      return finding;
    },
    markEvaluated(c, evaluated, scope = null) {
      const tier = tierOfCase(c);
      const surface = surfaceFor(c, scope);
      for (const rule of evaluated) {
        const at = resolve(rule, tier, surface, 'was evaluated');
        coverage[rule][tier].evaluated += 1;
        if (at.status === 'blocking') coverage[rule][tier].blockingEvaluated += 1;
      }
    },
    /**
     * Blocking assertions the sweep never evaluated where they block: a rule
     * that matched nothing has not passed, and a surface-scoped rule evaluated
     * only on surfaces where it is still pending has not passed either.
     */
    vacuous() {
      const missing = [];
      for (const [rule, entry] of Object.entries(rules)) {
        if (entry.kind !== 'assertion') continue;
        for (const tier of TIERS) {
          if (entry.tiers[tier].status === 'blocking' && coverage[rule][tier].blockingEvaluated === 0) missing.push(`${rule} @ Tier ${tier}`);
        }
      }
      return missing;
    },
    blocking: () => findings.filter((f) => f.severity === 'blocking'),
    pending: () => findings.filter((f) => f.severity === 'measured/pending'),
  };
}

/** The run's exit status: 2 for a harness fault, 1 for a blocking finding, else 0. */
/**
 * A case whose declared state was not reached is a harness fault at every
 * tier: whatever it measured is not the state it claims to be evidence of.
 * Tier severity applies to what a reached state shows, never to whether the
 * harness reached it, so no manifest entry is consulted here.
 *
 * @param {Array<{ state: string, viewport: string, tier: string, reached: boolean, unreached?: { stage: string, reason: string } | null }>} results
 * @returns {string[]}
 */
export function unreachedFaults(results) {
  return results.filter((r) => !r.reached).map((r) => (
    `${r.state} @ ${r.viewport} (Tier ${r.tier}): the declared state was not reached`
    + (r.unreached ? ` at ${r.unreached.stage}: ${r.unreached.reason}` : '')
  ));
}

/**
 * pressed.visible across a sweep: the control kinds some capture left unproven
 * (its pressed form never on that page) that no capture proved distinct in the
 * same rendering context — the same surface at the same tier, so a pressed look
 * shown on another surface or at a narrower tier never stands in for this one —
 * each with the first valid case it was seen in.
 */
export function unprovenPressedKinds(results) {
  const context = (kind, r) => `${kind} @ ${r.surface ?? '?'} / Tier ${r.tier}`;
  const proven = new Set(results.filter((r) => r.valid).flatMap((r) => (r.pressed?.proven ?? []).map((kind) => context(kind, r))));
  const firstSeen = new Map();
  for (const r of results.filter((x) => x.valid)) {
    for (const u of r.pressed?.unproven ?? []) {
      const key = context(u.kind, r);
      if (!proven.has(key) && !firstSeen.has(key)) firstSeen.set(key, { kind: u.kind, result: r, control: u.control });
    }
  }
  return Array.from(firstSeen.values());
}

export function exitStatus({ harnessErrors, blocking, keep = false }) {
  if (harnessErrors.length) return 2;
  if (blocking.length && !keep) return 1;
  return 0;
}

/**
 * Waits until the page and the fixture server agree the declared state is
 * reached: the page probe finds nothing pending, no request is in flight,
 * none started and nothing in the DOM changed since the previous probe — on
 * `stable` consecutive probes. Bounded: on timeout it says what was still
 * pending, and the caller refuses the capture.
 */
export async function settle(lane, state, { timeoutMs = 20_000, stable = 2, beforePreparation = false } = {}) {
  const started = Date.now();
  let previous = null;
  let run = 0;
  let probes = 0;
  let last = [];
  // The page clock at the probe that began the final quiet run: by then the
  // outcome being waited for had rendered and nothing changed after it.
  let quietAt = null;
  // Before a preparation the page has only to finish loading: the state's
  // expected and forbidden text describe what the preparation produces.
  const input = {
    expectText: beforePreparation ? [] : [].concat(state.expectText ?? []),
    forbidText: beforePreparation ? [] : [].concat(state.forbidText ?? []),
    holds: state.holds ?? null, transient: TRANSIENT,
  };
  while (Date.now() - started < timeoutMs) {
    const probe = await lane.browser.evaluate(toExpression(settleProbe, input));
    probes += 1;
    const net = lane.server.network();
    const why = [...probe.why];
    if (net.inflight > 0) why.push(net.inflight + ' request(s) in flight');
    if (previous && net.started !== previous.started) why.push('new requests started');
    if (previous && probe.mutations !== previous.mutations) why.push('the DOM is still changing');
    run = previous && why.length === 0 ? run + 1 : 0;
    // The quiet run begins at the first probe that found nothing pending.
    if (run === 0) quietAt = why.length === 0 ? probe.at ?? null : null;
    else if (quietAt === null) quietAt = probe.at ?? null;
    if (run >= stable) return { ok: true, ms: Date.now() - started, probes, quietAt };
    previous = { started: net.started, mutations: probe.mutations };
    last = why;
  }
  return { ok: false, ms: Date.now() - started, probes, why: last.length ? last : ['no probe completed'] };
}
