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
 * Tier policy (§26, §34.2): S5 flips the tiers below A as it implements them.
 * T1 (Tier B compositions) made every rule that judges a Tier B composition
 * `blocking` at Tier B, and T2 (Tier C degradation) every rule that judges a
 * Tier C composition `blocking` at Tier C, and T3 (200% zoom) made the zoom
 * rule `blocking` where a zoom case lands; a rule owned by a later slice (S6's
 * target size, journeys, motion and measurements) stays measured against that
 * owner. `validateManifest` refuses a Tier C entry still owned by T2, and any
 * entry still owned by T3: each is done or it is not.
 *
 * Lane (T3). A rule with `lane: 'zoom'` is evaluated only in a zoom case —
 * the 1366x768 anchor at a browser page zoom — and the engine refuses it
 * anywhere else, so a shrunk viewport can never stand in for zoom.
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
/** The runners other than the sweep that prove a rule by their own aggregate. */
export const PRODUCERS = Object.freeze(['journeys', 'performance']);
/** S6/X3: the rules the performance gate proves (performance.mjs). */
export const PERFORMANCE_RULES = Object.freeze(['perf.cls', 'perf.long-tasks', 'typography.resolved-font']);
export const KINDS = ['assertion', 'measurement', 'future'];

const blocking = () => ({ status: 'blocking' });
const pending = (owner) => ({ status: 'measured/pending', owner });
const na = (reason) => ({ status: 'not-applicable', reason });

/** T1 (S5) promoted Tier B; T2 (S5) promoted Tier C. */
const B = blocking();
const C = blocking();

/** An S1-implemented rule: blocking at the accepted tiers (A, and B from T1), pending at C. */
const s1 = () => ({ A: blocking(), B, C });

/**
 * The surfaces a `scope: 'surface'` finding can belong to, with the register
 * row that finishes each (plan §4, S3a–S3e and S4). `accepted` flips to true in
 * the PR that closes the row, and promotes that surface alone.
 */
export const SURFACES = {
  foundation: { owner: 'S1 foundation (D1-D9)', accepted: true },
  'not-found': { owner: 'S1d shell (D4)', accepted: true },
  // R1-R3 accepted (retrospective correction, S5 preliminary): the register
  // recorded R1 (PR #189), R2 (PR #190) and R3 (PR #191) PASS, but their flags
  // stayed false, so their surface findings were measured, never blocking.
  // Corrected on its own, before any Tier B promotion, so no accepted surface
  // is exempt from surface-scoped enforcement.
  overview: { owner: 'S3a / R1', accepted: true },
  videos: { owner: 'S3a / R2', accepted: true },
  'processing-detail': { owner: 'S3b / R3', accepted: true },
  // R4 accepted (S3c): the Scene Editor's surface findings block at Tier A.
  'scene-editor': { owner: 'S3c / R4', accepted: true },
  // R5 accepted (S3d): Search's surface findings block at Tier A.
  search: { owner: 'S3d / R5', accepted: true },
  // R6 accepted (S3e): Review's surface findings block at Tier A.
  review: { owner: 'S3e / R6', accepted: true },
  // M1 accepted (S4): Cameras' surface findings block at Tier A.
  cameras: { owner: 'S4 / M1', accepted: true },
  // M2 accepted (S4): the Processing queue's surface findings block at Tier A,
  // ledger.actions-reachable among them.
  'processing-queue': { owner: 'S4 / M2', accepted: true },
  // M3 accepted (S4): Import's surface findings block at Tier A.
  import: { owner: 'S4 / M3', accepted: true },
  // M4 accepted (S4): Camera Analytics' surface findings block at Tier A. With
  // it, and the R1-R3 correction above, every reference and migrated surface is
  // accepted.
  'camera-analytics': { owner: 'S4 / M4', accepted: true },
};

/**
 * §23 (frozen): the condition a11y.zoom-200 qualifies — 200% browser page zoom
 * on a 1366x768 viewport. A zoom case is judged against this, not against
 * whatever condition the states declare, so no states module can shrink the
 * viewport, or leave the zoom at 100%, and still pass the rule.
 */
export const ZOOM_CONDITION = Object.freeze({ width: 1366, height: 768, factor: 2 });
/** The lanes a rule may be confined to: a case of that lane alone evaluates it. */
export const LANES = Object.freeze(['zoom', 'text-spacing', 'reduced-motion']);

/** The ten operator surfaces (§23 "every other surface keeps its function"). */
export const OPERATOR_SURFACES = Object.keys(SURFACES).filter((name) => name !== 'foundation' && name !== 'not-found');

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
    tiers: { A: blocking(), B, C: na('below 768px the rail is the §25 Tier C top-of-page menu, judged by tier.c-shell') },
  },
  'a11y.skip-link': { section: '§5, §23', kind: 'assertion', summary: 'The skip link is the first focusable element outside a modal, and its target resolves to the main landmark.', tiers: s1() },
  'a11y.landmarks': { section: '§5, §23', kind: 'assertion', summary: 'Exactly one main and one banner landmark; a named primary navigation.', tiers: s1() },
  'surface.one-primary': { section: '§8.1, §16', kind: 'assertion', summary: 'At most one visible, enabled, non-inert accent-filled action on the surface.', tiers: s1() },
  'a11y.focus-visible': { section: '§23, §12', kind: 'assertion', summary: 'Every focusable control shows a focus ring when focused.', tiers: s1() },
  'harness.focus-coverage': { section: '§26', kind: 'assertion', summary: 'Every discovered control is focus-checked or skipped for a named reason.', tiers: s1() },

  // --- Overlays (S1c, §15, §20) ------------------------------------------------
  // T3: a dirty draft carried across 768px by a live zoom change reaches the
  // Scene Editor's leave guard at Tier C (scene-editor-dirty's leave-guard
  // transition): a Dialog at Tier C is reachable, so it is judged, and blocks.
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
  'ledger.row-pitch': {
    section: '§16, §10', kind: 'assertion', summary: 'Every visible Ledger data row measures 36-40px.',
    tiers: { A: blocking(), B, C: na('a Tier C Ledger is the §25 single-column list, whose item is several lines by design; tier.c-composition judges it') },
  },
  'ledger.row-primary': { section: '§8.1, §16', kind: 'assertion', summary: 'No Ledger row carries an accent-filled primary.', tiers: s1() },
  // M1 (S4): §25's "no clipped or unreachable control" for Ledger rows. The
  // body may scroll sideways (§4.1); an action is unreachable only where no
  // scrolling reveals it. Surface-scoped: it blocks at Tier A on an accepted
  // surface (Cameras from M1, the Processing queue from M2) and is measured
  // against the owning row on one not yet migrated. Under CI's wider fallback
  // font it found the queue's degraded-row Retry clipped 6px by the run cell's
  // cap; M2 corrected that (processing-queue-row-degraded-wide-font).
  'ledger.actions-reachable': {
    section: '§25, §4.1', kind: 'assertion', scope: 'surface',
    summary: 'No Ledger row action is clipped where no scrolling reaches it; an action reachable by the permitted sideways scroll is not a finding. Blocks on a surface once its row is accepted.',
    tiers: { A: blocking(), B, C },
  },
  // M1's own acceptance (§4.1 "1366: all columns visible"): the Camera columns
  // fit at Tier A, both row actions in view at rest. Cameras only; §25 governs
  // the narrower tiers, where a Ledger may scroll.
  'cameras.actions-in-view': {
    section: '§4.1', kind: 'assertion', summary: 'On Cameras every row action is within the frame\'s visible width at rest at Tier A: its supported columns fit.',
    tiers: { A: blocking(), B: na('Tier A only: §4.1 "1366: all columns visible"; below it §25 lets a Ledger scroll'), C: na('Tier A only: §4.1 "1366: all columns visible"; below it §25 lets a Ledger scroll') },
  },
  'ledger.ultrawide-alignment': {
    section: '§4.1, §25', kind: 'assertion', summary: 'At ultra-wide a sparse Ledger is left-aligned, not stretched.',
    tiers: { A: blocking(), B: na(TIER_A_ONLY), C: na(TIER_A_ONLY) },
  },
  'record.scroll-ownership': { section: '§4.2', kind: 'assertion', summary: 'A Record gives the page the scroll and has its primary/facts grid.', tiers: s1() },
  'investigation.geometry': { section: '§4.4', kind: 'assertion', summary: 'Rail 252px, results 560-900px, inspector in place or drawer as the layout declares.', tiers: { A: blocking(), B, C: na('the 252px rail beside the results is the composition above 1100px; at Tier C tier.c-composition judges the full-width list and its full-width drawers') } },
  'investigation.scroll-ownership': { section: '§4.4', kind: 'assertion', summary: 'Rail and results scroll independently; the page does not.', tiers: s1() },
  'workbench.geometry': {
    section: '§4.3.1', kind: 'assertion', summary: 'Stage at least 65% of the working width; inspector 300-360px.',
    tiers: { A: blocking(), B, C: na('below 768px the Workbench renders no stage or inspector (§25), which tier.c-workbench-unsupported judges') },
  },
  'workbench.scroll-ownership': {
    section: '§4.3.2', kind: 'assertion', summary: 'No page scroll; only the inspector body scrolls.',
    tiers: { A: blocking(), B, C: na('below 768px the Workbench is its unsupported state, read down the page like a Record (§25)') },
  },
  'review.composition': { section: '§4.5, §25', kind: 'assertion', summary: 'Player at least 65% (70% ultra-wide) and the player and summary start in the initial viewport.', tiers: { A: blocking(), B, C: na('the player share and the summary in view are the side-by-side composition above 1100px (§4.5.1); at Tier C tier.c-composition judges the full-width player, then the summary, then provenance') } },
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
    summary: 'After the page scrolls, the Evidence Player is still in the viewport and clear of the Context Bar (rendered, not only declared).',
    // R6 (S3e) fixed the rendered pin and flipped this to blocking at Tier A.
    tiers: { A: blocking(), B, C: na('the pin is released at 1100px and below (§4.5.1); at Tier C tier.c-composition asserts the player is not sticky') },
  },
  // X1 (S6): every pointer target measured by its effective hit area through
  // one discovery (a11y.mjs a11yPointerTargets): a checkbox by the label that
  // toggles it, a canvas handle by its invisible hit circle, a disclosure by
  // its summary. The four root causes of the T3 sweep's 87 findings are fixed
  // in the product; the rule blocks at every tier.
  'a11y.target-size': { section: '§10.1, §23', kind: 'assertion', summary: 'Every pointer-operated control offers an effective target of at least 24x24 CSS px (its own box; a checkbox or radio by its label; a canvas handle by its hit circle).', tiers: s1() },
  'tier.b-shell': {
    section: '§25 (Tier B shell)', kind: 'assertion',
    summary: 'At Tier B the rail never takes the workspace\'s width (collapsed by default, expanded only as the modal overlay), its control stays visible and labelled, and the Context Bar\'s actions stay inside it with the primary keeping its label.',
    tiers: { A: na('a Tier B composition rule'), B, C: na('a Tier B composition rule') },
  },
  // T1: the §25 Tier B transitions themselves, judged from where the regions
  // render — Workbench stacked at 768-1100 and side by side above it;
  // Investigation rail a drawer opened from the results header at 768-1100 and
  // in place above it; Record facts below the primary at 768-1100 and beside it
  // (280px minimum) above it; Review rail below the player at 768-1100 and
  // beside it above it.
  // T1 (Codex P1 on #199): the Ledger fold, stated per Ledger and judged from
  // the rendered table. Tier A blocks too (§4.1: every column at 1366);
  // Tier C is T2's.
  'ledger.column-fold': {
    section: '§25 (Tier B Ledger), §4.1', kind: 'assertion',
    summary: 'Each operational Ledger folds exactly its stated columns at its stated width (and back where its table fits), into each row’s primary cell with their names, keeping identity, status, analytics and the action, with a Sort select for a folded sort key; nothing folds at Tier A.',
    tiers: { A: blocking(), B, C },
  },
  'tier.b-composition': {
    section: '§25 (Tier B compositions), §4.3.1, §4.4', kind: 'assertion',
    summary: 'At Tier B each archetype renders its designed composition on each side of the stacking threshold.',
    tiers: { A: na('a Tier B composition rule'), B, C: na('a Tier B composition rule') },
  },
  'tier.c-shell': {
    section: '§25 (Tier C shell), §5', kind: 'assertion',
    summary: 'At Tier C the content takes the viewport width, the rail exists only as the overlay, a visible, named 32px control at the top of the page opens the navigation, and the Context Bar keeps a readable identity and every action inside it with the primary labelled.',
    tiers: { A: na('a Tier C composition rule'), B: na('a Tier C composition rule'), C },
  },
  'tier.c-composition': {
    section: '§25 (Tier C compositions), §4.2, §20', kind: 'assertion',
    summary: 'At Tier C each archetype renders its narrow composition: a Ledger is a single-column list with identity, status and a reachable action, its filters in a drawer; the Overview is attention then counts; a Record stacks its facts in the stated order; Search is the full-width list with full-width drawers and no grid; Review is the full-width player, then the summary, then provenance, its transport at 24px.',
    tiers: { A: na('a Tier C composition rule'), B: na('a Tier C composition rule'), C },
  },
  'tier.c-workbench-unsupported': {
    section: '§25 (Tier C Workbench)', kind: 'assertion',
    summary: 'At Tier C a Workbench renders no canvas, stage, inspector or mode strip, states that it needs at least 768px, and shows a read-only summary.',
    tiers: { A: na('a Tier C composition rule'), B: na('a Tier C composition rule'), C },
  },

  // --- Measurements (P1, V5) ---------------------------------------------------
  // S6/X3 (§38): the performance budgets. Each case keeps its raw
  // measurement (navigation and preparation CLS, the interaction's long tasks,
  // the resolved fonts and the font faces the document holds); these rules
  // are what that measurement must satisfy, judged by the performance gate
  // (performance.mjs against performance-budgets.mjs: the full sweep's
  // ordinary cases, the single-lane long-task run) — never by a sweep case,
  // whose lanes contend for the CPU. Nothing here is owned by X3 any more.
  'perf.cls': {
    section: '§38', kind: 'assertion', producer: 'performance',
    summary: 'Navigation CLS (loading to content) and preparation CLS (a declared state change), each judged on its own, stay within their frozen X3 budget class and tolerance (Layout Instability API).',
    tiers: { A: blocking(), B: blocking(), C: blocking() },
  },
  'perf.long-tasks': {
    section: '§38', kind: 'assertion', producer: 'performance',
    summary: 'A declared operator interaction, measured on one lane, raises no more long tasks, and none longer, than its frozen X3 class permits (Long Tasks API).',
    tiers: { A: blocking(), B: blocking(), C: blocking() },
  },
  'typography.resolved-font': {
    section: '§26, §32, §38', kind: 'assertion', producer: 'performance',
    summary: 'The text renders in a platform font, and the document holds no font face that could arrive late and swap (§38 "fonts do not swap"); the resolved family is recorded as a diagnostic, never required to be one face across systems.',
    tiers: { A: blocking(), B: blocking(), C: blocking() },
  },

  // T3 (S5): 200% browser page zoom at 1366x768 (§23). A zoom case is the
  // 1366x768 anchor with the browser's page zoom set (cdp.mjs pageZoom): its
  // effective 683x384 CSS viewport is Tier C, so every Tier C rule judges it
  // as well. This rule is what only a zoom case can settle — that the zoom is
  // real (the browser's zoom factor, the 1366x768 viewport behind it, the
  // devicePixelRatio and the media queries it drives), that no offered control
  // is lost to the 384px height (reachable, unclipped and unobscured when
  // focused), that drawers and dialogs fit, that text grows with the page, and
  // that a zoom change keeps focus, overlays, drafts and preferences sound. It
  // is evaluated only in zoom cases (`lane`), and the full sweep must evaluate
  // it on every operator surface (engine.zoomCoverageFaults).
  'a11y.zoom-200': {
    section: '§23, §25', kind: 'assertion', lane: 'zoom',
    summary: 'At 200% browser page zoom on a 1366x768 viewport the page lays out at 683x384 CSS px under the Tier C rules with no offered control lost, hidden, clipped or obscured; drawers and dialogs fit; text grows with the page; and a zoom change in either direction keeps focus visible, overlays valid, drafts and preferences intact.',
    tiers: {
      A: blocking(),
      B: na('200% of the 1366x768 anchor is an effective 683px (Tier C), and zooming back out returns to 1366 (Tier A): no zoom case lands at Tier B'),
      C: blocking(),
    },
  },
  // The reduced-motion lane (X4, §13): a case of the lane loads the state
  // with Chromium emulating `prefers-reduced-motion: reduce` from before its
  // first document (cdp.mjs reducedMotion, Emulation.setEmulatedMedia) at one
  // canonical anchor per distinct composition (REDUCED_MOTION_CONDITION) and
  // its probe widths, and is judged by every rule of its tier; this rule holds
  // that the preference is in force (matchMedia and a CSS media probe agree)
  // and that no element or ::before/::after has a positive transition or
  // animation duration, and no running browser animation a positive one
  // (a11y.mjs a11yReducedMotion; engine.reducedMotionCoverageFaults on the
  // full sweep). Evaluated only in a reduced-motion case (`lane`).
  'a11y.reduced-motion': {
    section: '§13, §23', kind: 'assertion', lane: 'reduced-motion',
    summary: 'With prefers-reduced-motion: reduce emulated before first paint, every element and pseudo-element computes a zero transition and animation duration, and no running animation has a positive duration.',
    tiers: s1(),
  },
  // --- Known rules not yet evaluated by any code ------------------------------
  // X2 (§23, plan §5.3): the six operator journeys, completed keyboard-only.
  // Not a per-state rule: a journey crosses routes, so its producer is the
  // journey runner (journeys.mjs, JOURNEY_CONDITION), never the sweep — the
  // sweep neither evaluates it nor faults for not having done so; the journey
  // aggregate proves every planned execution ran once and passed.
  'a11y.keyboard-journeys': {
    section: '§23 (plan §5.3)', kind: 'assertion', producer: 'journeys',
    summary: 'Each of the six frozen operator journeys completes keyboard-only — every action a key through the input pipeline, every target reached by Tab and named by the accessibility tree, focus valid after every action, every step on an observable checkpoint, the journey on a terminal one — at every workstation composition.',
    tiers: {
      A: blocking(),
      B: blocking(),
      C: na('§25 / T2: Tier C is the designed reading and degraded composition, and no workflow acceptance is claimed below Tier A — the programme\'s non-claim; the journeys are not run there'),
    },
  },

  // --- X1 (S6): the §23 obligations, each a named rule (a11y.mjs) ------------
  // Names and roles are read from Chromium's accessibility tree (cdp.mjs
  // axNames); seeing is zoomVisibility's account; nothing here is an engine.
  'a11y.names': {
    section: '§23', kind: 'assertion',
    summary: 'Every control has a computed accessible name; where it shows a label the name contains it (WCAG 2.5.3); a title is never the only name, except the collapsed rail item.',
    tiers: s1(),
  },
  'a11y.form-fields': {
    section: '§23', kind: 'assertion',
    summary: 'Every form field is labelled (not by its placeholder alone); an invalid field has its rendered error message associated and announced, or focused.',
    tiers: s1(),
  },
  'a11y.role-contract': {
    section: '§23', kind: 'assertion',
    summary: "A role's contract is honoured or not claimed: aria-expanded names a rendered region, referenced ids resolve, an option holds nothing focusable, a listbox holds options, native semantics are not re-roled or re-invented on generic elements.",
    tiers: s1(),
  },
  'a11y.live-regions': {
    section: '§23', kind: 'assertion',
    summary: 'Every live region is rendered, and a status region is mounted before it is populated: across a state\'s preparation no region appears already holding its message (one inserted passes only if its text arrived in a later task).',
    tiers: s1(),
  },
  'a11y.tooltips': {
    section: '§23', kind: 'assertion',
    summary: "A tooltip or title carries no information required to operate the product: its text is its control's name (with a key hint at most), a truncated value, a timestamp's full form, or stated elsewhere on the page.",
    tiers: s1(),
  },
  'a11y.shortcuts-in-text-entry': {
    section: '§23', kind: 'assertion',
    summary: 'Keyboard shortcuts (the shell\'s "?", the Scene Editor\'s Delete) do not fire while a text field is being typed in; the key reaches the field.',
    tiers: s1(),
  },
  'a11y.tab-order': {
    section: '§23', kind: 'assertion',
    summary: 'The keyboard reaches the controls of the Context Bar, the workspace and an open overlay in their reading order, per container; a control placed by its data follows the data.',
    tiers: s1(),
  },
  'a11y.state-cues': {
    section: '§23', kind: 'assertion',
    summary: 'Every state carries a cue that is not colour alone: a selected or current item differs from its peers in border, bar, shadow, weight, glyph or a 3:1 luminance step; invalid geometry is dashed; a status badge has text; timeline marker kinds differ in shape.',
    tiers: s1(),
  },
  'a11y.focus-not-obscured': {
    section: '§23 (WCAG 2.4.11)', kind: 'assertion',
    summary: 'A focused control is not hidden under a fixed or sticky layer at its middle.',
    tiers: s1(),
  },
  'a11y.spatial-twin': {
    section: '§23', kind: 'assertion',
    summary: 'Every drawn scene object has its entry in the object list, naming it, its state and its actual coordinates, through the control the pointer uses; every timeline interval and marker has its named entry.',
    tiers: { A: blocking(), B, C: blocking() },
  },
  'a11y.reading-order': {
    section: '§23 (WCAG 1.3.2)', kind: 'assertion',
    summary: 'In every sequential region — a table body, a list, a definition list, the page\'s regions, a state region, the Context Bar — the document order of the content is the visual order.',
    tiers: s1(),
  },
  // The text-spacing lane (WCAG 1.4.12): a case of the lane loads the state
  // with the user\'s spacing overrides in force (server.mjs TEXT_SPACING_CSS)
  // at one canonical anchor per distinct composition (TEXT_SPACING_CONDITION)
  // and is judged by every rule of its tier; this rule holds that the
  // overrides were in force (engine.textSpacingCoverageFaults on the full
  // sweep). Evaluated only in a spacing case (`lane`).
  'a11y.text-spacing': {
    section: '§23 (WCAG 1.4.12)', kind: 'assertion', lane: 'text-spacing',
    summary: 'With line height 1.5×, paragraph spacing 2×, letter spacing 0.12em and word spacing 0.16em in force before first paint, every composition keeps its content and controls: no clipped or overlapping text, no overflow, every control reachable and unobscured.',
    tiers: s1(),
  },
  'a11y.hover-content': {
    section: '§23 (WCAG 1.4.13)', kind: 'assertion',
    summary: 'The custom tooltip is shown on focus and on hover, stays while either holds, can be hovered itself, is dismissed by Escape without moving focus, and hides when both leave.',
    tiers: s1(),
  },
};

/**
 * X1 (§23, WCAG 1.4.12): the text-spacing lane's frozen anchors — one
 * canonical anchor of every distinct responsive composition (§25): the
 * narrowest Tier A anchor, both Tier B orientations, the narrowest Tier C
 * anchor. A state's probe widths are added by the plan.
 */
export const TEXT_SPACING_CONDITION = Object.freeze({
  anchors: Object.freeze([
    Object.freeze({ width: 1366, height: 768, tier: 'A' }),
    Object.freeze({ width: 1024, height: 768, tier: 'B' }),
    Object.freeze({ width: 768, height: 1024, tier: 'B' }),
    Object.freeze({ width: 390, height: 844, tier: 'C' }),
  ]),
  overrides: Object.freeze({ lineHeight: 1.5, paragraphSpacing: 2, letterSpacing: 0.12, wordSpacing: 0.16 }),
});

/**
 * X2 (§23, plan §5.3): where the keyboard journeys run — the workstation
 * compositions only (§25: Tier A and both Tier B orientations; Tier C claims
 * no workflow) — and the locale their segmented fields are read in.
 */
export const JOURNEY_CONDITION = Object.freeze({
  viewports: Object.freeze([
    Object.freeze({ width: 1366, height: 768, tier: 'A' }),
    Object.freeze({ width: 1024, height: 768, tier: 'B' }),
    Object.freeze({ width: 768, height: 1024, tier: 'B' }),
  ]),
  locale: 'en-GB',
  tierC: 'Tier C is the designed reading and degraded composition; no workflow acceptance is claimed below Tier A (§25, T2)',
});

/**
 * X4 (§13, §23): the reduced-motion lane's frozen condition — the media
 * feature Chromium emulates and the same canonical anchors as the
 * text-spacing lane (one per distinct composition, §25). A state's probe
 * widths are added by the plan.
 */
export const REDUCED_MOTION_CONDITION = Object.freeze({
  anchors: TEXT_SPACING_CONDITION.anchors,
  media: Object.freeze({ name: 'prefers-reduced-motion', value: 'reduce' }),
});

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
      // §26 / §34.2: Tier C blocks nothing until T2 flips it (T1 flipped B).
      // T2 merged: no Tier C entry may still wait on it.
      if (tier === 'C' && at.status === 'measured/pending' && /T2/.test(at.owner ?? '')) problems.push(`${id} @ ${tier}: still owned by T2 after T2`);
    }
    if (entry.kind !== 'assertion' && Object.values(entry.tiers ?? {}).some((at) => at.status === 'blocking')) {
      problems.push(`${id}: a ${entry.kind} rule cannot block`);
    }
    if (entry.kind === 'future' && !entry.execution) problems.push(`${id}: future rule without an execution policy`);
    if (entry.scope !== undefined && entry.scope !== 'surface') problems.push(`${id}: unknown scope "${entry.scope}"`);
    if (entry.lane !== undefined && !LANES.includes(entry.lane)) problems.push(`${id}: unknown lane "${entry.lane}"`);
    // T3: 200% zoom is §23 MUST, owned by T3 alone; T3 is done or it is not.
    // X1: every §23 obligation is asserted; nothing stays owned by X1.
    for (const tier of TIERS) {
      if (entry.tiers?.[tier]?.status === 'measured/pending' && /T3/.test(entry.tiers[tier].owner ?? '')) problems.push(`${id} @ ${tier}: still owned by T3 after T3`);
      if (entry.tiers?.[tier]?.status === 'measured/pending' && /X1/.test(entry.tiers[tier].owner ?? '')) problems.push(`${id} @ ${tier}: still owned by X1 after X1`);
      // X4: reduced motion is asserted; nothing stays owned by X4.
      if (/X4/.test(entry.tiers?.[tier]?.owner ?? '')) problems.push(`${id} @ ${tier}: still owned by X4 after X4`);
      // X2: the journeys are asserted; nothing stays owned by X2.
      if (/X2/.test(entry.tiers?.[tier]?.owner ?? '')) problems.push(`${id} @ ${tier}: still owned by X2 after X2`);
    }
    if (entry.producer !== undefined && !PRODUCERS.includes(entry.producer)) problems.push(`${id}: unknown producer "${entry.producer}"`);
    // X3: the performance budgets are asserted; nothing stays owned by X3.
    for (const tier of TIERS) if (/X3/.test(entry.tiers?.[tier]?.owner ?? '')) problems.push(`${id} @ ${tier}: still owned by X3 after X3`);
    if (PERFORMANCE_RULES.includes(id) && (entry.kind !== 'assertion' || entry.producer !== 'performance' || !TIERS.every((t) => entry.tiers?.[t]?.status === 'blocking'))) {
      problems.push(`${id}: X3 asserts it through the performance gate, blocking at every tier`);
    }
    if (id === 'a11y.keyboard-journeys' && (entry.kind !== 'assertion' || entry.producer !== 'journeys' || entry.tiers?.A?.status !== 'blocking' || entry.tiers?.B?.status !== 'blocking' || entry.tiers?.C?.status !== 'not-applicable')) {
      problems.push(`${id}: X2 asserts it through the journey runner, blocking at A and B, not applicable at C`);
    }
    if (id === 'a11y.reduced-motion' && (entry.kind !== 'assertion' || entry.lane !== 'reduced-motion' || !TIERS.every((t) => entry.tiers?.[t]?.status === 'blocking'))) problems.push(`${id}: X4 asserts it in the reduced-motion lane, blocking at every tier`);
    if (id === 'a11y.section23-remaining') problems.push(`${id}: the X1 placeholder is retired; every §23 obligation has its own rule`);
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
  // Stage 3.5 is closed (S7, C2): §34.2 staged conformance has expired and
  // §34 applies unqualified. Nothing may be measured/pending — on any rule, at
  // any tier, under any owner — and every surface is accepted; a new
  // obligation is blocking or not-applicable with its reason from the start.
  for (const [id, entry] of Object.entries(rules)) {
    for (const tier of TIERS) {
      if (entry.tiers?.[tier]?.status === 'measured/pending') problems.push(`${id} @ ${tier}: measured/pending after Stage 3.5 closure (§34.2 has expired)`);
    }
  }
  for (const [name, surface] of Object.entries(surfaces)) {
    if (surface.accepted === false) problems.push(`surface ${name}: not accepted after Stage 3.5 closure (§34.2 has expired)`);
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
