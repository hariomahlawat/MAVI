/**
 * The assertion manifest (specification §26 as amended in v2.0, §34.2;
 * acceptance register V1).
 *
 * One entry per rule, and per support tier the rule's status there:
 *
 * - `blocking`         a finding fails the run;
 * - `measured/pending` the rule is evaluated and its findings are reported,
 *                      never failing the run, until the named owner slice
 *                      flips it — `owner` is that slice and register row;
 * - `not-applicable`   the rule is not evaluated at that tier, for `reason`.
 *
 * Every finding the harness produces names a rule here, and its severity is
 * resolved here and nowhere else: a state can say which tiers it is swept at,
 * but it cannot say how severe anything is. A finding that names no rule is a
 * harness error, not a finding, so an assertion cannot run unregistered.
 *
 * `kind` says how a rule is executed:
 *
 * - `assertion`   evaluated by the browser assertions (`assertions.mjs`) or by
 *                 the run itself (`run.mjs`), which must name the rule;
 * - `measurement` recorded per capture, never a pass/fail on its own (P1, V5);
 * - `future`      known to the specification and owned by a later slice, not
 *                 yet evaluated by any code — its `execution` says so and its
 *                 tiers are `measured/pending` against that owner. It becomes
 *                 an `assertion` in the slice that implements it.
 *
 * Tier policy (§26, §34.2): until S5 flips them, every rule evaluated at a
 * Tier B or C anchor is `measured/pending` — generic or tier-specific — so S2
 * never blocks on S5 behaviour. `validateManifest` enforces that.
 *
 * Surface scope (§34.2 staged conformance). A rule with `scope: 'surface'` is
 * `blocking` at Tier A, and a finding of it carries where it was found: in a
 * region S1 owns (`foundation` — the shell, Context Bar, Ledgers, Dialog,
 * shortcut sheet, StateRegion) it always blocks; on a surface it blocks once
 * that surface's register row is accepted (`SURFACES`), and until then it is
 * `measured/pending` against that row. Each surface is promoted on its own by
 * its slice — never by a global switch — and no surface status can soften a
 * finding in an S1 region.
 *
 * Whether the harness reached the declared state is not a rule here: a state
 * not reached is a harness fault at every tier (`engine.unreachedFaults`),
 * which no severity can soften.
 */

export const TIERS = ['A', 'B', 'C'];
export const STATUSES = ['blocking', 'measured/pending', 'not-applicable'];
export const KINDS = ['assertion', 'measurement', 'future'];

const blocking = () => ({ status: 'blocking' });
const pending = (owner) => ({ status: 'measured/pending', owner });
const na = (reason) => ({ status: 'not-applicable', reason });

/** Tier B and C stay non-blocking until S5 (T1, T2) flips them. */
const B = pending('S5 / T1 (Tier B compositions)');
const C = pending('S5 / T2 (Tier C degradation)');

/** An S1-implemented rule: blocking at the accepted tier, pending below it. */
const s1 = () => ({ A: blocking(), B, C });

/**
 * The surfaces a `scope: 'surface'` finding can belong to, with the register
 * row that finishes each (plan §4, S3a–S3e and S4). `accepted` flips to true in
 * the PR that closes the row, and promotes that surface alone.
 */
export const SURFACES = {
  foundation: { owner: 'S1 foundation (D1-D9)', accepted: true },
  'not-found': { owner: 'S1d shell (D4)', accepted: true },
  overview: { owner: 'S3a / R1', accepted: false },
  videos: { owner: 'S3a / R2', accepted: false },
  'processing-detail': { owner: 'S3b / R3', accepted: false },
  'scene-editor': { owner: 'S3c / R4', accepted: false },
  search: { owner: 'S3d / R5', accepted: false },
  review: { owner: 'S3e / R6', accepted: false },
  cameras: { owner: 'S4 / M1', accepted: false },
  'processing-queue': { owner: 'S4 / M2', accepted: false },
  import: { owner: 'S4 / M3', accepted: false },
  'camera-analytics': { owner: 'S4 / M4', accepted: false },
};

/** Route to surface. A route no entry owns is refused, never defaulted. */
export const ROUTES = [
  [/^\/$/, 'overview'],
  [/^\/videos$/, 'videos'],
  [/^\/processing$/, 'processing-queue'],
  [/^\/processing\/[^/]+$/, 'processing-detail'],
  [/^\/cameras$/, 'cameras'],
  [/^\/cameras\/[^/]+\/scene$/, 'scene-editor'],
  [/^\/cameras\/[^/]+\/analytics$/, 'camera-analytics'],
  [/^\/search$/, 'search'],
  [/^\/review\/video\/[^/]+$/, 'review'],
  [/^\/import$/, 'import'],
  [/^\/no-such-page$/, 'not-found'],
];

export function surfaceOf(path) {
  const route = path.split('?')[0];
  const hit = ROUTES.find(([pattern]) => pattern.test(route));
  if (!hit) throw new Error(`no surface owns route ${route}: add it to ROUTES in manifest.mjs`);
  return hit[1];
}

const TIER_A_ONLY = 'evaluated only at the ultra-wide Tier A anchors, where the §25 width rule bites';

/** @type {Record<string, { section: string, kind: string, summary: string, tiers: Record<string, object>, execution?: string }>} */
export const RULES = {
  // --- Page-wide (§26 generic, all existing) ---------------------------------
  'page.horizontal-overflow': { section: '§26, §25', kind: 'assertion', summary: 'No horizontal page overflow.', tiers: s1() },
  'page.uncaught-error': { section: '§26', kind: 'assertion', summary: 'No uncaught page error or console error.', tiers: s1() },
  'page.resource-error': { section: '§26', kind: 'assertion', summary: 'No failed request other than the one the state asks to fail.', tiers: s1() },
  'page.control-overlap': { section: '§26', kind: 'assertion', summary: 'No two visible interactive controls overlap (a deliberate overlay excepted).', tiers: s1() },
  'page.text-overlap': { section: '§26', kind: 'assertion', summary: 'No two visible text leaves collide.', tiers: s1() },
  'page.token-resolution': { section: '§26, §7', kind: 'assertion', summary: 'Every referenced custom property resolves.', tiers: s1() },
  'page.width-discipline': {
    section: '§25, §4.1', kind: 'assertion',
    summary: 'A page--full surface uses the ultra-wide viewport; a capped surface stays capped.',
    tiers: { A: blocking(), B: na(TIER_A_ONLY), C: na(TIER_A_ONLY) },
  },
  'text.overflow': {
    section: '§26, §36.2, §16', kind: 'assertion', scope: 'surface',
    summary: 'No visible text extends outside its box without sanctioned wrapping or truncation. Blocks in every S1 region; on a surface, once its row is accepted.',
    tiers: s1(),
  },
  'pressed.visible': { section: '§12, §26', kind: 'assertion', summary: 'Every visible enabled aria-pressed control has a visible pressed treatment.', tiers: s1() },

  // --- Shell, landmarks, primaries (S1d, S1a) ---------------------------------
  'shell.context-bar': { section: '§5', kind: 'assertion', summary: 'Exactly one Context Bar, 44px tall.', tiers: s1() },
  'shell.rail': {
    section: '§5, §25', kind: 'assertion', summary: 'Rail 216/56px with a 32px labelled collapse control announcing its state.',
    tiers: { A: blocking(), B, C: na('below 760px the rail is the §25 Tier C top-of-page menu, measured by tier.c-shell (S5 / T2)') },
  },
  'a11y.skip-link': { section: '§5, §23', kind: 'assertion', summary: 'The skip link is the first focusable element outside a modal, and its target resolves to the main landmark.', tiers: s1() },
  'a11y.landmarks': { section: '§5, §23', kind: 'assertion', summary: 'Exactly one main and one banner landmark; a named primary navigation.', tiers: s1() },
  'surface.one-primary': { section: '§8.1, §16', kind: 'assertion', summary: 'At most one visible, enabled, non-inert accent-filled action on the surface.', tiers: s1() },
  'a11y.focus-visible': { section: '§23, §12', kind: 'assertion', summary: 'Every focusable control shows a focus ring when focused.', tiers: s1() },
  'harness.focus-coverage': { section: '§26', kind: 'assertion', summary: 'Every discovered control is focus-checked or skipped for a named reason.', tiers: s1() },

  // --- Overlays (S1c, §15, §20) ------------------------------------------------
  'overlay.dialog': { section: '§15, §23', kind: 'assertion', summary: 'An open Dialog is a named modal dialog holding focus, with everything else inert and nothing outside it focusable.', tiers: s1() },
  'overlay.drawer': { section: '§20, §23', kind: 'assertion', summary: 'An overlay drawer is a named modal dialog holding focus over an inert workspace; an in-place inspector claims no modality.', tiers: s1() },

  // --- Archetypes (§4; UI-2..UI-5 and S1d) -----------------------------------
  'archetype.rendered': { section: '§4', kind: 'assertion', summary: 'The state renders the archetype it declares.', tiers: s1() },
  'archetype.contained-clipping': { section: '§26, §4', kind: 'assertion', summary: 'A contained column clips in neither direction.', tiers: s1() },
  'ledger.scroll-ownership': { section: '§4.1', kind: 'assertion', summary: 'The Ledger table frame is the single scroll owner, its header sticks to it, and the page does not scroll.', tiers: s1() },
  'ledger.containment': { section: '§4.1, §11', kind: 'assertion', summary: 'The containment frame bounds the table: no frame without a table, no viewport-high frame around a sparse table, no frame inside the frame.', tiers: s1() },
  'state.placement': {
    section: '§37.1, §14.1', kind: 'assertion',
    summary: 'A state presentation is content-sized at the top of the region it replaces; a Ledger one is a direct, uncontained child of the body region.',
    tiers: s1(),
  },
  'ledger.loading-geometry': { section: '§36.3, §38', kind: 'assertion', summary: 'A loading Ledger reserves the table header and its first skeleton row lands where the first body row arrives.', tiers: s1() },
  'ledger.row-pitch': { section: '§16, §10', kind: 'assertion', summary: 'Every visible Ledger data row measures 36-40px.', tiers: s1() },
  'ledger.row-primary': { section: '§8.1, §16', kind: 'assertion', summary: 'No Ledger row carries an accent-filled primary.', tiers: s1() },
  'ledger.ultrawide-alignment': {
    section: '§4.1, §25', kind: 'assertion', summary: 'At ultra-wide a sparse Ledger is left-aligned, not stretched.',
    tiers: { A: blocking(), B: na(TIER_A_ONLY), C: na(TIER_A_ONLY) },
  },
  'record.scroll-ownership': { section: '§4.2', kind: 'assertion', summary: 'A Record gives the page the scroll and has its primary/facts grid.', tiers: s1() },
  'investigation.geometry': { section: '§4.4', kind: 'assertion', summary: 'Rail 252px, results 560-900px, inspector in place or drawer as the layout declares.', tiers: s1() },
  'investigation.scroll-ownership': { section: '§4.4', kind: 'assertion', summary: 'Rail and results scroll independently; the page does not.', tiers: s1() },
  'workbench.geometry': { section: '§4.3.1', kind: 'assertion', summary: 'Stage at least 65% of the working width; inspector 300-360px.', tiers: s1() },
  'workbench.scroll-ownership': { section: '§4.3.2', kind: 'assertion', summary: 'No page scroll; only the inspector body scrolls.', tiers: s1() },
  'review.composition': { section: '§4.5, §25', kind: 'assertion', summary: 'Player at least 65% (70% ultra-wide) and the player and summary start in the initial viewport.', tiers: s1() },
  'review.sticky-declared': { section: '§4.5.1', kind: 'assertion', summary: 'The player column is declared sticky side by side and released when stacked.', tiers: s1() },
  'review.timeline': { section: '§18', kind: 'assertion', summary: 'One timeline; its evidence visible to assistive technology; zone and overflow lanes within their caps; fixed dense controls; usable, non-overlapping markers.', tiers: s1() },
  'review.analytical-geometry': { section: '§18', kind: 'assertion', summary: 'Analytical shapes inside the content rectangle; direction cues perpendicular, arrowed and labelled; no native controls.', tiers: s1() },

  // --- Rules evaluated now, owned by a later slice ---------------------------
  'containment.depth': {
    section: '§11', kind: 'assertion', scope: 'surface',
    summary: 'At most one contained surface: no bordered panel inside a bordered panel (card-inside-card); a frame holding only media is an object, not a container. Blocks in every S1 region; on a surface, once its row is accepted.',
    tiers: s1(),
  },
  'review.sticky-rendered': {
    section: '§4.5.1, §36.3', kind: 'assertion',
    summary: 'After the page scrolls, the Evidence Player is still in the viewport (rendered, not only declared).',
    tiers: { A: pending('S3e / R6'), B, C },
  },
  'a11y.target-size': { section: '§10.1, §23', kind: 'assertion', summary: 'Pointer targets at least 24x24 wherever practical.', tiers: { A: pending('S6 / X1'), B, C } },
  'tier.b-shell': {
    section: '§25 (Tier B shell)', kind: 'assertion', summary: 'At Tier B the rail is collapsed by default and its control stays visible and labelled.',
    tiers: { A: na('a Tier B composition rule'), B, C: na('a Tier B composition rule') },
  },
  'tier.c-shell': {
    section: '§25 (Tier C shell)', kind: 'assertion', summary: 'At Tier C the rail is not a column beside the content: the content takes the viewport width.',
    tiers: { A: na('a Tier C composition rule'), B: na('a Tier C composition rule'), C },
  },
  'tier.c-workbench-unsupported': {
    section: '§25 (Tier C Workbench)', kind: 'assertion',
    summary: 'At Tier C a Workbench renders no editing canvas and states that editing needs at least 768px.',
    tiers: { A: na('a Tier C composition rule'), B: na('a Tier C composition rule'), C },
  },

  // --- Measurements (P1, V5) ---------------------------------------------------
  'perf.cls': {
    section: '§38', kind: 'measurement',
    summary: 'Cumulative layout shift during the loading-to-content transition (Layout Instability API).',
    tiers: { A: pending('S6 / X3 (budget set from the P1 baseline)'), B: pending('S6 / X3'), C: pending('S6 / X3') },
  },
  'perf.long-tasks': {
    section: '§38', kind: 'measurement',
    summary: 'Long tasks during the state’s first interaction (Long Tasks API).',
    tiers: { A: pending('S6 / X3 (budget set from the P1 baseline)'), B: pending('S6 / X3'), C: pending('S6 / X3') },
  },
  'typography.resolved-font': {
    section: '§26, §32', kind: 'measurement',
    summary: 'The rendered font family per state and anchor, recorded (never a pixel baseline).',
    tiers: { A: pending('S6 / X3 (§38: fonts do not swap)'), B: pending('S6 / X3'), C: pending('S6 / X3') },
  },

  // --- Known rules not yet evaluated by any code ------------------------------
  'a11y.zoom-200': {
    section: '§23, §25', kind: 'future', execution: 'not evaluated until S5 adds the 200% zoom sweep at 1366x768',
    summary: '200% zoom at 1366x768 reflows under the Tier C rules.',
    tiers: { A: pending('S5 / T3'), B: pending('S5 / T3'), C: pending('S5 / T3') },
  },
  'a11y.reduced-motion': {
    section: '§13, §23', kind: 'future', execution: 'not evaluated until S6 adds the reduced-motion emulation pass',
    summary: 'Under prefers-reduced-motion no transition or animation runs.',
    tiers: { A: pending('S6 / X4'), B: pending('S6 / X4'), C: pending('S6 / X4') },
  },
  'a11y.keyboard-journeys': {
    section: '§23', kind: 'future', execution: 'not evaluated until S6 scripts the six keyboard-only operator journeys',
    summary: 'The six operator journeys complete keyboard-only.',
    tiers: { A: pending('S6 / X2'), B: pending('S6 / X2'), C: pending('S6 / X2') },
  },
  'a11y.section23-remaining': {
    section: '§23', kind: 'future', execution: 'not evaluated until S6 asserts the remaining §23 rows (harness or contrast.test.ts)',
    summary: 'Every remaining §23 obligation asserted on every surface.',
    tiers: { A: pending('S6 / X1'), B: pending('S6 / X1'), C: pending('S6 / X1') },
  },
};

/**
 * The status of a rule at a tier — for a surface-scoped rule, on the surface
 * the finding belongs to — or a thrown error for anything unregistered.
 */
export function severityOf(rule, tier, surface = null, { rules = RULES, surfaces = SURFACES } = {}) {
  const entry = rules[rule];
  if (!entry) throw new Error(`unregistered rule "${rule}": every finding must name a manifest rule`);
  const at = entry.tiers[tier];
  if (!at) throw new Error(`rule "${rule}" has no status at tier ${tier}`);
  if (entry.scope !== 'surface' || at.status !== 'blocking') return at;
  if (!surface) throw new Error(`rule "${rule}" is surface-scoped: its finding must name the surface it belongs to`);
  const owner = surfaces[surface];
  if (!owner) throw new Error(`rule "${rule}": unknown surface "${surface}"`);
  return owner.accepted ? at : { status: 'measured/pending', owner: `${owner.owner} (surface not yet accepted)` };
}

/**
 * The manifest's own integrity. Returns a list of problems; empty means valid.
 * `implemented` is the set of rule ids the execution engine can produce, read
 * from the assertion and run sources, so a rule with no code and a finding
 * with no rule are both caught.
 */
export function validateManifest(rules = RULES, implemented = null, { surfaces = SURFACES, routes = ROUTES } = {}) {
  const problems = [];
  for (const [id, entry] of Object.entries(rules)) {
    if (!/^[a-z0-9]+(\.[a-z0-9-]+)+$/.test(id)) problems.push(`${id}: malformed rule id`);
    if (!KINDS.includes(entry.kind)) problems.push(`${id}: unknown kind "${entry.kind}"`);
    if (!entry.section || !entry.summary) problems.push(`${id}: missing section or summary`);
    for (const tier of TIERS) {
      const at = entry.tiers?.[tier];
      if (!at) { problems.push(`${id}: no status at tier ${tier}`); continue; }
      if (!STATUSES.includes(at.status)) problems.push(`${id} @ ${tier}: invalid status "${at.status}"`);
      if (at.status === 'measured/pending' && !at.owner) problems.push(`${id} @ ${tier}: measured/pending without an owning slice`);
      if (at.status === 'not-applicable' && !at.reason) problems.push(`${id} @ ${tier}: not-applicable without a reason`);
      // §26 / §34.2: nothing below Tier A blocks until S5 flips it.
      if (tier !== 'A' && at.status === 'blocking') problems.push(`${id} @ ${tier}: blocking below Tier A before S5`);
    }
    if (entry.kind !== 'assertion' && Object.values(entry.tiers ?? {}).some((at) => at.status === 'blocking')) {
      problems.push(`${id}: a ${entry.kind} rule cannot block`);
    }
    if (entry.kind === 'future' && !entry.execution) problems.push(`${id}: future rule without an execution policy`);
    if (entry.scope !== undefined && entry.scope !== 'surface') problems.push(`${id}: unknown scope "${entry.scope}"`);
    if (entry.scope === 'surface' && entry.tiers?.A?.status !== 'blocking') problems.push(`${id}: a surface-scoped rule must block at Tier A, where S1 owns it`);
    if (implemented) {
      const isImplemented = implemented.has(id);
      if (entry.kind !== 'future' && !isImplemented) problems.push(`${id}: registered as ${entry.kind} but no code produces it`);
      if (entry.kind === 'future' && isImplemented) problems.push(`${id}: registered as future but code already produces it`);
    }
  }
  if (implemented) {
    for (const id of implemented) if (!rules[id]) problems.push(`${id}: produced by code but not registered`);
  }
  for (const [name, surface] of Object.entries(surfaces)) {
    if (typeof surface.accepted !== 'boolean') problems.push(`surface ${name}: accepted must be true or false`);
    if (!/S[1-7]/.test(surface.owner ?? '')) problems.push(`surface ${name}: no owning slice`);
  }
  if (surfaces.foundation?.accepted !== true) problems.push('surface foundation: S1 regions must always block');
  for (const [, name] of routes) if (!surfaces[name]) problems.push(`route to unknown surface ${name}`);
  return problems;
}

/** Counts by tier and status, for the report and the register. */
export function manifestSummary(rules = RULES) {
  const summary = {
    rules: Object.keys(rules).length, byKind: {}, byTier: {},
    surfaceScoped: Object.keys(rules).filter((id) => rules[id].scope === 'surface'),
    surfaces: Object.fromEntries(Object.entries(SURFACES).map(([name, s]) => [name, s.accepted ? 'accepted' : `pending: ${s.owner}`])),
  };
  for (const entry of Object.values(rules)) summary.byKind[entry.kind] = (summary.byKind[entry.kind] ?? 0) + 1;
  for (const tier of TIERS) {
    summary.byTier[tier] = Object.fromEntries(STATUSES.map((s) => [s, 0]));
    for (const entry of Object.values(rules)) summary.byTier[tier][entry.tiers[tier].status] += 1;
  }
  return summary;
}
