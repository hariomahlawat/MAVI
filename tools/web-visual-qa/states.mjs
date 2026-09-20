/**
 * The states and viewports the section 26 pass covers.
 *
 * `api` overrides a fixture for one state: a literal value is served as the
 * response, `'unavailable'` answers 503, and `'hang'` never answers, which is
 * how the loading state is held still long enough to look at.
 *
 * `requireOverlay` makes a footage-condition state prove the overlay is drawn
 * over a decoded frame before its capture counts.
 *
 * `knownIssues` lists regexes for defects that exist at this baseline and
 * belong to a later UI PR (section 34.1). They are reported separately rather
 * than failing the pass, so the harness stays honest about them without
 * blocking work that does not own them. Anything not listed is a finding.
 *
 * `expectText` / `forbidText` make a state prove it rendered what it claims.
 * Unavailable states need a long settle because the query client retries once
 * before failing terminally; without the assertion a slow retry would quietly
 * turn an "unavailable" check into a second loading check.
 *
 * `fullWidth` records which surfaces declare `page--full` at this baseline.
 * The harness asserts it in both directions, because UI-1 must fix the cap on
 * the two surfaces that declare full width *and* must not widen any of the
 * others — those belong to UI-3 and UI-5.
 */

const CAM = '11111111-1111-7111-8111-111111111111';
const VIDEO = '22222222-2222-7222-8222-222222222222';

/**
 * The Investigation filter rail's section headings land on the labels beneath
 * them at 1366. Verified identical on main at the UI-1 baseline, so this is not
 * a UI-1 regression; the rail's layout is UI-4's, and section 34.1 leaves it
 * non-conformant until then rather than pulling that work forward.
 */
const RAIL_OVERLAP = ['overlapping text: .*(THRESHOLDS|Thresholds|Display timezone|Minimum duration)'];
const TRACK = '55555550-5555-7555-8555-555555555550';

/**
 * Drive the player to the representative frame using the product's own
 * control, so the overlay is drawn where it actually gets drawn. Setting
 * currentTime directly races the player's own seek handling.
 */
const SEEK = `(() => {
  const v = document.querySelector('.player video');
  if (!v) return false;
  // A paused element with only metadata will sit at readyState 1 forever, and
  // the larger letterbox source hits that at the wide viewports. Nudge it into
  // buffering, then put it back where the overlay is drawn.
  if (v.readyState < 2) { try { v.load(); v.play().then(() => v.pause()).catch(() => {}); } catch { /* ignore */ } }
  const jump = Array.from(document.querySelectorAll('button')).find((b) => /Evidence/.test(b.textContent || ''));
  if (jump) jump.click();
  v.pause();
  return Boolean(jump);
})()`;

/**
 * Dirty the scene, which is what fills the Context Bar.
 *
 * A clean Scene Editor shows crumbs, three badges and two buttons. Editing adds
 * the revision note field and the unsaved-changes state, and that is the bar's
 * busiest arrangement — so it is the one where controls collide at 1366 if they
 * are going to. Renaming through the real field goes through the real reducer,
 * so the state is reached rather than simulated.
 */
const DIRTY_SCENE = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const object = document.querySelector('.scene-navigator__name');
  if (!object) return false;
  object.click();
  await wait(300);
  const field = Array.from(document.querySelectorAll('input')).find((i) => {
    const label = i.labels && i.labels[0];
    return label && label.textContent.trim() === 'Name';
  });
  if (!field) return false;
  // Through the native setter, so React sees a real change rather than a
  // value assignment it never hears about.
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(field, 'A considerably longer zone name');
  field.dispatchEvent(new Event('input', { bubbles: true }));
  await wait(300);
  return Boolean(document.querySelector('.scene-context__note input'));
})()`;

export const WIDTHS = [
  { width: 1366, height: 768, label: '1366x768' },
  { width: 1440, height: 900, label: '1440x900' },
  { width: 1920, height: 1080, label: '1920x1080' },
  { width: 2560, height: 1080, label: '2560x1080' },
];

export const STATES = [
  // --- Ledger and Record surfaces: capped, and must stay capped until UI-3. ---
  { name: 'overview', path: '/', fullWidth: false },
  { name: 'cameras', path: '/cameras', fullWidth: false },
  {
    name: 'cameras-unavailable', path: '/cameras', fullWidth: false, settleMs: 4000,
    api: { '/api/cameras': 'unavailable' },
    expectText: 'unavailable', forbidText: 'No cameras registered',
  },
  {
    name: 'cameras-loading', path: '/cameras', fullWidth: false, settleMs: 500,
    api: { '/api/cameras': 'hang' }, expectText: 'Loading cameras',
  },
  {
    name: 'cameras-empty', path: '/cameras', fullWidth: false,
    api: { '/api/cameras': [] }, expectText: 'No cameras registered',
  },
  { name: 'videos', path: '/videos', fullWidth: false },
  {
    name: 'videos-empty', path: '/videos', fullWidth: false,
    api: { '/api/videos': [] }, expectText: 'No videos imported yet',
  },
  {
    name: 'videos-unavailable', path: '/videos', fullWidth: false, settleMs: 4000,
    api: { '/api/videos': 'unavailable' },
    expectText: 'unavailable', forbidText: 'No videos imported yet',
  },
  { name: 'import', path: '/import', fullWidth: false },
  { name: 'processing-queue', path: '/processing', fullWidth: false },

  // --- Workbench: declares full width, and must actually use it. `archetype`
  //     additionally measures it against the frozen section 4.3 rules. ---
  { name: 'scene-editor', path: `/cameras/${CAM}/scene`, fullWidth: true, settleMs: 1200, archetype: 'workbench' },
  {
    name: 'scene-editor-unconfigured',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    settleMs: 1200,
    api: { [`/api/cameras/${CAM}/scene`]: { cameraId: CAM, configured: false, activeRevision: null, history: [] } },
  },
  {
    // The bar at its fullest: identity, three badges, the note field, Reset and
    // Save, all in 44px.
    name: 'scene-editor-dirty',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    settleMs: 1200,
    prepare: DIRTY_SCENE,
    // A placeholder is not page text, so the note field is proven by the
    // preparation's own return value instead — a failed prepare is a finding.
    expectText: 'Unsaved changes',
  },
  {
    name: 'scene-editor-unavailable',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    settleMs: 4000,
    api: { [`/api/cameras/${CAM}/scene`]: 'unavailable' },
    expectText: 'unavailable',
  },

  // --- Investigation: declares full width, and must actually use it. ---
  {
    name: 'search', path: '/search', fullWidth: true, settleMs: 900,
    // Pre-existing at the UI-1 baseline and verified identical on main: the
    // THRESHOLDS heading lands on the timezone hint and the duration label.
    // The Investigation filter rail is UI-4's to lay out; section 34.1 leaves
    // it non-conformant until then rather than pulling that work forward.
    knownIssues: RAIL_OVERLAP,
  },
  {
    name: 'search-empty', path: '/search', fullWidth: true,
    api: { '/api/tracks': { items: [], nextCursor: null, totalCount: 0 } },
    knownIssues: RAIL_OVERLAP,
  },
  {
    name: 'search-unavailable', path: '/search', fullWidth: true, settleMs: 4000,
    api: { '/api/tracks': 'unavailable' }, expectText: 'unavailable',
    knownIssues: RAIL_OVERLAP,
  },

  // --- Review: capped today; its archetype migration is UI-5, not UI-1. ---
  // The evidence overlay: where the bounding-box and trajectory hues have to
  // survive footage the product does not control (section 26).
  { name: 'review', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, expectText: 'North Gate' },
  { name: 'review-bright', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'bright', prepare: SEEK, requireOverlay: true },
  { name: 'review-dark', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'dark', prepare: SEEK, requireOverlay: true },
  { name: 'review-saturated', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'saturated', prepare: SEEK, requireOverlay: true },
  { name: 'review-lowcontrast', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'lowcontrast', prepare: SEEK, requireOverlay: true },
  { name: 'review-letterbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'letterbox', prepare: SEEK, requireOverlay: true },
];
