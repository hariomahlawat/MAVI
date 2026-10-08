/**
 * The harness's decisions, apart from the browser plumbing: which cases run,
 * what a finding weighs, when a page has settled, and what the run exits with.
 * Kept separate from `run.mjs` so each decision is tested directly.
 */
import { RULES, severityOf, TIERS } from './manifest.mjs';
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
      for (let attempt = 1; attempt <= repeat; attempt += 1) cases.push({ state, viewport, attempt });
    }
  }
  return { cases, applicability };
}

/**
 * Every finding and every evaluation goes through here, so its severity can
 * only come from the manifest. A finding or an evaluation the manifest does
 * not allow at that tier is a harness fault, not something to report.
 */
export function createLedger(rules = RULES) {
  const findings = [];
  const coverage = Object.fromEntries(Object.keys(rules).map((rule) => [rule, Object.fromEntries(TIERS.map((t) => [t, { evaluated: 0, findings: 0 }]))]));
  const tierOfCase = (c) => c.viewport.tier;

  function resolve(rule, tier, what) {
    if (!rules[rule]) throw new HarnessError(`unregistered rule "${rule}" ${what}: every assertion must have a manifest entry`);
    const at = severityOf(rule, tier);
    if (at.status === 'not-applicable') {
      throw new HarnessError(`${rule} ${what} at Tier ${tier}, where the manifest says it is not applicable (${at.reason})`);
    }
    return at;
  }

  return {
    findings,
    coverage,
    record(c, rule, message) {
      const tier = tierOfCase(c);
      const at = resolve(rule, tier, 'produced a finding');
      const finding = { state: c.state.name, viewport: c.viewport.label, tier, kind: c.viewport.kind, rule, severity: at.status, owner: at.owner ?? null, message };
      findings.push(finding);
      coverage[rule][tier].findings += 1;
      return finding;
    },
    markEvaluated(c, evaluated) {
      const tier = tierOfCase(c);
      for (const rule of evaluated) {
        resolve(rule, tier, 'was evaluated');
        coverage[rule][tier].evaluated += 1;
      }
    },
    /** Blocking assertions the sweep never evaluated: a rule that matched nothing has not passed. */
    vacuous() {
      const missing = [];
      for (const [rule, entry] of Object.entries(rules)) {
        if (entry.kind !== 'assertion') continue;
        for (const tier of TIERS) {
          if (entry.tiers[tier].status === 'blocking' && coverage[rule][tier].evaluated === 0) missing.push(`${rule} @ Tier ${tier}`);
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
 * harness reached it.
 *
 * @param {Array<{ state: string, viewport: string, tier: string, reached: boolean, findings: Array<{ rule: string, message: string }> }>} results
 * @returns {string[]}
 */
export function unreachedFaults(results) {
  return results.filter((r) => !r.reached).map((r) => {
    const why = r.findings.filter((f) => f.rule === 'harness.state-reached').map((f) => f.message);
    return `${r.state} @ ${r.viewport} (Tier ${r.tier}): the declared state was not reached${why.length ? ': ' + why.join('; ') : ''}`;
  });
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
    if (run >= stable) return { ok: true, ms: Date.now() - started, probes };
    previous = { started: net.started, mutations: probe.mutations };
    last = why;
  }
  return { ok: false, ms: Date.now() - started, probes, why: last.length ? last : ['no probe completed'] };
}
