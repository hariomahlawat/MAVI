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
export function planCases({ states, anchors, policies, stateKeys, tierOf, zoom = null, textSpacing = null, reducedMotion = null, onlyStates = null, onlyTiers = null, onlyWidths = null, onlyZoom = null, onlyTextSpacing = null, onlyReducedMotion = null, repeat = 1 }) {
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
    if (zoom) viewports.push(...zoomViewports(state, applies, zoom, tierOf));
    if (textSpacing) viewports.push(...textSpacingViewports(state, applies, textSpacing, tierOf));
    if (reducedMotion) viewports.push(...reducedMotionViewports(state, applies, reducedMotion, tierOf));
    for (const viewport of viewports) {
      if (onlyTiers && !onlyTiers.includes(viewport.tier)) continue;
      if (onlyWidths && !onlyWidths.includes(viewport.width)) continue;
      // `--zoom only` runs the zoom cases alone; `--zoom none` leaves them out.
      if (onlyZoom === 'only' && !viewport.zoom) continue;
      if (onlyZoom === 'none' && viewport.zoom) continue;
      if (onlyTextSpacing === 'only' && !viewport.textSpacing) continue;
      if (onlyTextSpacing === 'none' && viewport.textSpacing) continue;
      if (onlyReducedMotion === 'only' && !viewport.reducedMotion) continue;
      if (onlyReducedMotion === 'none' && viewport.reducedMotion) continue;
      // A zoom-only, spacing-only or reduced-motion-only run is of that lane alone.
      if (onlyZoom === 'only' && (viewport.textSpacing || viewport.reducedMotion)) continue;
      if (onlyTextSpacing === 'only' && (viewport.zoom || viewport.reducedMotion)) continue;
      if (onlyReducedMotion === 'only' && (viewport.zoom || viewport.textSpacing)) continue;
      for (let attempt = 1; attempt <= repeat; attempt += 1) cases.push({ state, viewport, attempt, surface });
    }
  }
  return { cases, applicability };
}

// Labels name capture files, so they stay filename-safe on every platform.
const zoomLabel = (path) => path.map((factor) => `${Math.round(factor * 100)}%`).join('-');

/**
 * T3 (§23): a state's zoom cases on the 1366x768 anchor. Loaded at 200% — for
 * every state swept at the tier 200% lands in (Tier C), or a breakpoint probe
 * that opts in — and each declared live transition. A case carries its zoom
 * `path` (the factors it is taken through: one for a load, more for a change)
 * and the tier its final factor's effective width falls in, which is the tier
 * it is judged at. A transition starts at a tier the state is swept at, so its
 * preparation is one the state already proves there.
 */
function zoomViewports(state, applies, zoom, tierOf) {
  const effective = (factor) => ({ width: zoom.width / factor, height: zoom.height / factor });
  const tierAt = (factor) => tierOf(effective(factor).width);
  const swept = new Set([...applies.tiers, ...(state.probeWidths ?? []).map(tierOf)]);
  const zoomTier = tierAt(zoom.factor);
  const viewport = (path, extra) => ({
    width: zoom.width, height: zoom.height, zoom: path, effective: effective(path[path.length - 1]),
    tier: tierAt(path[path.length - 1]), ...extra,
  });
  const out = [];
  if (state.zoomCapture !== undefined && state.zoomCapture !== true) throw new HarnessError(`state ${state.name}: zoomCapture must be true when given`);
  if (state.zoomCapture && !swept.has(zoomTier)) throw new HarnessError(`state ${state.name} opts into a ${zoom.factor * 100}% zoom capture but is not swept at Tier ${zoomTier}, where it lands`);
  if (swept.has(zoomTier) && (applies.tiers.includes(zoomTier) || state.zoomCapture)) {
    out.push(viewport([zoom.factor], { label: `${zoom.width}x${zoom.height}@${zoomLabel([zoom.factor])}`, kind: 'zoom' }));
  }
  const seen = new Set();
  const TRANSITION_KEYS = new Set(['id', 'path', 'before', 'checks', 'then', 'expectText', 'forbidText']);
  for (const transition of state.zoomTransitions ?? []) {
    const { path } = transition;
    for (const key of Object.keys(transition)) {
      if (!TRANSITION_KEYS.has(key)) throw new HarnessError(`state ${state.name}: a zoom transition carries unknown key "${key}"`);
    }
    if (!Array.isArray(path) || path.length < 2 || !path.every((f) => f === 1 || f === zoom.factor) || path.some((f, i) => i > 0 && f === path[i - 1])) {
      throw new HarnessError(`state ${state.name}: a zoom transition's path changes between 100% and ${zoom.factor * 100}% at every step, not ${JSON.stringify(path)}`);
    }
    if (!swept.has(tierAt(path[0]))) throw new HarnessError(`state ${state.name}: its zoom transition starts at Tier ${tierAt(path[0])}, where the state is not swept`);
    if ((transition.checks ?? []).length > path.length - 1) throw new HarnessError(`state ${state.name}: more zoom-transition checks than zoom changes`);
    const label = `${zoom.width}x${zoom.height}@${zoomLabel(path)}${transition.id ? `.${transition.id}` : ''}`;
    if (seen.has(label)) throw new HarnessError(`state ${state.name}: two zoom transitions share the label ${label}; give one an id`);
    seen.add(label);
    out.push(viewport(path, { label, kind: 'zoom-transition', transition, startTier: tierAt(path[0]) }));
  }
  return out;
}

/**
 * X1 (§23, WCAG 1.4.12): a state's text-spacing cases — the state loaded with
 * the user's spacing overrides in force, at one canonical anchor of every
 * distinct responsive composition it is swept at (the lane's frozen anchors:
 * the narrowest acceptance anchor of each tier range and each orientation
 * Tier B distinguishes) and at each of its declared probe widths (the
 * compositions the sweep itself declares distinct). Wider anchors that
 * render the same composition are not duplicated. Judged at the tier the
 * width falls in, by every rule of that tier plus a11y.text-spacing.
 */
function textSpacingViewports(state, applies, textSpacing, tierOf) {
  const out = [];
  for (const anchor of textSpacing.anchors) {
    if (!applies.tiers.includes(anchor.tier)) continue;
    out.push({ ...anchor, label: `${anchor.width}x${anchor.height}@spacing`, kind: 'text-spacing', textSpacing: true });
  }
  for (const width of state.probeWidths ?? []) {
    const label = `${width}x900@spacing`;
    if (out.some((viewport) => viewport.label === label)) continue;
    out.push({ width, height: 900, label, tier: tierOf(width), kind: 'text-spacing', textSpacing: true });
  }
  return out;
}

/**
 * X4 (§13, §23): a state's reduced-motion cases — the state loaded with
 * Chromium emulating `prefers-reduced-motion: reduce` from before its first
 * document, at the same canonical anchors as the text-spacing lane (one per
 * distinct responsive composition the state is swept at) and at each of its
 * declared probe widths. Judged at the tier the width falls in, by every rule
 * of that tier plus a11y.reduced-motion: the preference changes no layout, but
 * a zero duration is behaviour too (a transitionend that never fires).
 */
function reducedMotionViewports(state, applies, reducedMotion, tierOf) {
  const out = [];
  for (const anchor of reducedMotion.anchors) {
    if (!applies.tiers.includes(anchor.tier)) continue;
    out.push({ width: anchor.width, height: anchor.height, tier: anchor.tier, label: `${anchor.width}x${anchor.height}@reduced-motion`, kind: 'reduced-motion', reducedMotion: true });
  }
  for (const width of state.probeWidths ?? []) {
    const label = `${width}x900@reduced-motion`;
    if (out.some((viewport) => viewport.label === label)) continue;
    out.push({ width, height: 900, label, tier: tierOf(width), kind: 'reduced-motion', reducedMotion: true });
  }
  return out;
}

/**
 * The reduced-motion lane's coverage (X4): on the full sweep every planned
 * reduced-motion case produced a valid capture with the preference proven in
 * force and the rule judging at least one element — a state the lane never
 * judged at one of its compositions is a fault, never a pass.
 */
export function reducedMotionCoverageFaults(results, plannedKeys) {
  const faults = [];
  for (const key of plannedKeys.filter((k) => /@reduced-motion#\d+$/.test(k))) {
    const r = results.find((x) => caseKey(x) === key);
    const where = key.replace(/#\d+$/, '').replace('@', ' @ ');
    if (!r || !r.valid) faults.push(`a11y.reduced-motion: ${where} has no valid capture`);
    else if (!r.reducedMotion?.active) faults.push(`a11y.reduced-motion: ${where} ran without prefers-reduced-motion: reduce proven in force`);
    else if (!(r.reducedMotion.measured?.elements > 0)) faults.push(`a11y.reduced-motion: ${where} judged no element`);
  }
  return faults;
}

/**
 * The text-spacing lane's coverage (X1): on the full sweep every planned
 * spacing case produced a valid capture with the overrides proven in force
 * and the rule evaluated — a state the lane never judged at one of its
 * anchors is a fault, never a pass.
 */
export function textSpacingCoverageFaults(results, plannedKeys) {
  const faults = [];
  for (const key of plannedKeys.filter((k) => /@spacing#\d+$/.test(k))) {
    const r = results.find((x) => caseKey(x) === key);
    const where = key.replace(/#\d+$/, '').replace('@', ' @ ');
    if (!r || !r.valid) faults.push(`a11y.text-spacing: ${where} has no valid capture`);
    else if (!r.textSpacing?.inForce) faults.push(`a11y.text-spacing: ${where} ran without the overrides proven in force`);
  }
  return faults;
}

/**
 * Whether a zoom case's environment is the zoom it claims (T3, §23), from the
 * browser's own report and the page's: the factor the browser's setting holds,
 * the zoom factor the browser applies, the 1366x768 viewport behind it (device-
 * independent px), the CSS viewport it yields, no pinch scale, the
 * devicePixelRatio the zoom implies and the media queries it drives. Each
 * mismatch is one problem; an empty list is a qualified environment. A shrunk
 * viewport without zoom fails it (zoom 1, a 683px device-independent viewport).
 */
export function zoomQualification({ factor, viewport, reported, metrics, page }) {
  const problems = [];
  const near = (a, b, tolerance = 1) => typeof a === 'number' && Math.abs(a - b) <= tolerance;
  const css = { width: viewport.width / factor, height: viewport.height / factor };
  if (!near(reported, factor, 1e-6)) problems.push(`the browser's page-zoom setting is ${reported * 100}%, not ${factor * 100}%`);
  if (!near(metrics?.pageZoom, factor, 1e-3)) problems.push(`the browser applies a page zoom of ${metrics?.pageZoom}, not ${factor}`);
  if (!near(metrics?.dipViewport?.width, viewport.width) || !near(metrics?.dipViewport?.height, viewport.height)) {
    problems.push(`the viewport is ${metrics?.dipViewport?.width}x${metrics?.dipViewport?.height} device-independent px, not ${viewport.width}x${viewport.height}`);
  }
  if (!near(metrics?.cssLayoutViewport?.width, css.width) || !near(metrics?.cssLayoutViewport?.height, css.height)) {
    problems.push(`the CSS layout viewport is ${metrics?.cssLayoutViewport?.width}x${metrics?.cssLayoutViewport?.height}, not ${css.width}x${css.height}`);
  }
  if (!near(metrics?.cssVisualViewport?.scale, 1, 1e-3) || !near(page?.visual?.scale, 1, 1e-3)) problems.push(`the visual viewport is pinch-scaled (${page?.visual?.scale}), which is not page zoom`);
  if (!near(page?.innerWidth, css.width) || !near(page?.innerHeight, css.height) || !near(page?.clientWidth, css.width)) {
    problems.push(`the page sees ${page?.innerWidth}x${page?.innerHeight} (documentElement ${page?.clientWidth} wide), not ${css.width}x${css.height}`);
  }
  if (!near(page?.dpr, factor, 1e-3)) problems.push(`devicePixelRatio is ${page?.dpr}, not the ${factor} a ${factor * 100}% zoom gives at device scale 1`);
  if (page?.media?.narrow !== (css.width < 768) || page?.media?.compact !== (css.width < 1366)) {
    problems.push(`the media queries see ${page?.media?.narrow ? 'Tier C' : page?.media?.compact ? 'Tier B' : 'Tier A'}, not the tier of ${css.width}px`);
  }
  return problems;
}

/**
 * The full sweep's zoom coverage (T3): every operator surface has a valid
 * capture loaded at the zoom that evaluated the zoom rule, and every declared
 * transition ran. A surface the zoom never judged has not passed it.
 */
export function zoomCoverageFaults(results, surfaces) {
  const faults = [];
  for (const surface of surfaces) {
    const judged = results.some((r) => r.valid && r.kind === 'zoom' && r.surface === surface && r.zoom?.evaluated);
    if (!judged) faults.push(`a11y.zoom-200: the full sweep has no valid 200% zoom capture of ${surface} that evaluated it`);
  }
  for (const r of results.filter((x) => x.kind === 'zoom-transition' && !x.zoom?.evaluated)) {
    faults.push(`a11y.zoom-200: the zoom transition ${r.state} @ ${r.viewport} was never evaluated`);
  }
  // WCAG 1.4.4 is judged by comparison: a valid zoom case that compared no
  // text with a 100% baseline has not judged it.
  for (const r of results.filter((x) => x.valid && x.zoom && !x.zoom.text)) {
    faults.push(`a11y.zoom-200: ${r.state} @ ${r.viewport} never compared its text with a 100% baseline`);
  }
  return faults;
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

  function resolve(rule, tier, surface, what, c) {
    if (!rules[rule]) throw new HarnessError(`unregistered rule "${rule}" ${what}: every assertion must have a manifest entry`);
    // T3: a zoom rule is judged only where the browser's page zoom is set.
    if (rules[rule].lane === 'zoom' && !c?.viewport?.zoom) throw new HarnessError(`${rule} ${what} in ${c?.state?.name} @ ${c?.viewport?.label}, which is not a zoom case`);
    if (rules[rule].lane === 'text-spacing' && !c?.viewport?.textSpacing) throw new HarnessError(`${rule} ${what} in ${c?.state?.name} @ ${c?.viewport?.label}, which is not a text-spacing case`);
    if (rules[rule].lane === 'reduced-motion' && !c?.viewport?.reducedMotion) throw new HarnessError(`${rule} ${what} in ${c?.state?.name} @ ${c?.viewport?.label}, which is not a reduced-motion case`);
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
      const at = resolve(rule, tier, surface, 'produced a finding', c);
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
        const at = resolve(rule, tier, surface, 'was evaluated', c);
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
    // `confirmedAt`: the page clock at the probe that confirmed the state —
    // the end of everything the page did to reach it, work that changes no DOM
    // (a canvas drawn, a deferred computation) included.
    if (run >= stable) return { ok: true, ms: Date.now() - started, probes, confirmedAt: probe.at ?? null };
    previous = { started: net.started, mutations: probe.mutations };
    last = why;
  }
  return { ok: false, ms: Date.now() - started, probes, why: last.length ? last : ['no probe completed'] };
}

// --- Sharding (CI) ----------------------------------------------------------------

/** One case's identity across a run and across shards: state, viewport, attempt. */
export function caseKey(c) {
  const state = c.state?.name ?? c.state;
  const viewport = c.viewport?.label ?? c.viewport;
  return `${state}@${viewport}#${c.attempt ?? 1}`;
}

/**
 * The shard a state belongs to: the unit of partition is a state (every anchor,
 * probe and zoom case of a state runs in one shard), with the two states of a
 * loading pair kept together so a shard can compare them. Round-robin over the
 * states in their registered order — deterministic, and even enough: a state
 * has 3 to 12 cases, so 228 states give shards within a few per cent of each
 * other.
 */
export function partitionCases(cases, { index, count, pairs = [] }) {
  if (!Number.isInteger(count) || count < 1) throw new HarnessError(`shard count must be a positive integer, not ${count}`);
  if (!Number.isInteger(index) || index < 0 || index >= count) throw new HarnessError(`shard index must be 0..${count - 1}, not ${index}`);
  const partner = new Map(pairs.flatMap(([a, b]) => [[a, b], [b, a]]));
  const keyOf = (name) => {
    const other = partner.get(name);
    // The pair's partition key is the lexically first of the two names, so both
    // states resolve to the same key whichever is registered first.
    return other && other < name ? other : name;
  };
  const order = [];
  const seen = new Set();
  for (const c of cases) {
    const key = keyOf(c.state.name);
    if (!seen.has(key)) { seen.add(key); order.push(key); }
  }
  const shardOfKey = new Map(order.map((key, i) => [key, i % count]));
  const assignment = cases.map((c) => shardOfKey.get(keyOf(c.state.name)));
  const selected = cases.filter((_, i) => assignment[i] === index);
  return { selected, planned: cases.map(caseKey), selectedKeys: selected.map(caseKey), assignment };
}

/**
 * The checks that read across cases — what a shard cannot judge alone and the
 * aggregate must: a loading Ledger's first row against its table's (S1e, D3);
 * pressed treatments never proven in any capture (pressed.visible); every
 * scheduled case ran and reached its state; every operator surface judged at
 * 200% (T3); no blocking rule left unevaluated; overlay restoration judged at
 * Tier A. `fullSweep` enables the sweep-wide obligations. Returns the harness
 * faults; findings go through the ledger, so their severity is the manifest's.
 */
export function sweepChecks({ results, cases, errored, ledger, surfaces, loadingPairs = [], fullSweep, plannedKeys = null }) {
  const faults = [];
  const pressedUnproven = [];
  for (const [loading, ready] of loadingPairs) {
    for (const result of results.filter((r) => r.state === loading)) {
      const settled = results.find((r) => r.state === ready && r.viewport === result.viewport);
      const a = result.workspace?.firstRowTop;
      const b = settled?.workspace?.firstRowTop;
      if (typeof a !== 'number' || typeof b !== 'number') continue;
      const c = { state: { name: loading }, viewport: { label: result.viewport, tier: result.tier, kind: result.kind } };
      ledger.markEvaluated(c, ['ledger.loading-geometry']);
      if (Math.abs(a - b) > 0.5) ledger.record(c, 'ledger.loading-geometry', `first skeleton row at ${a}px, first ${ready} row at ${b}px: the rows move when the table arrives`);
    }
  }
  if (fullSweep) {
    for (const { kind, result: r, control } of unprovenPressedKinds(results)) {
      const c = { state: { name: r.state }, viewport: { label: r.viewport, tier: r.tier, kind: r.kind }, surface: r.surface };
      ledger.record(c, 'pressed.visible', `${control} (${kind}): its pressed treatment is never shown in any capture of the sweep, so it is unproven`);
      pressedUnproven.push(kind);
    }
  }
  faults.push(...unreachedFaults(results));
  if (results.length + errored.length !== cases.length) {
    faults.push(`${cases.length - results.length - errored.length} of ${cases.length} scheduled case(s) never ran`);
  }
  if (fullSweep) faults.push(...zoomCoverageFaults(results, surfaces));
  if (fullSweep && plannedKeys) faults.push(...textSpacingCoverageFaults(results, plannedKeys));
  if (fullSweep && plannedKeys) faults.push(...reducedMotionCoverageFaults(results, plannedKeys));
  const vacuous = fullSweep && !faults.length ? ledger.vacuous() : [];
  if (vacuous.length) faults.push('blocking rules the full sweep never evaluated: ' + vacuous.join(', '));
  if (fullSweep && !faults.length) {
    for (const rule of ['overlay.dialog', 'overlay.drawer']) {
      const judged = results.some((r) => r.tier === 'A' && r.overlayExit?.rule === rule && ['restored', 'failed', 'unverifiable'].includes(r.overlayExit.restoration));
      if (!judged) faults.push(`${rule}: the full sweep never judged focus restoration at Tier A for an overlay an action opened`);
    }
  }
  return { faults, pressedUnproven };
}
