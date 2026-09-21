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
 * `fullWidth` records which surfaces declare `page--full`. The harness asserts
 * it in both directions, so a surface cannot be widened or capped by accident.
 * UI-3 moved Cameras, Videos and Processing onto it: a standard Ledger is full
 * width (section 4.1). Overview stays capped as the section 4.1.1 exception,
 * Records stay capped by definition, and Review stays capped until UI-5.
 *
 * `archetype` runs the section 4 conformance measurements on the rendered
 * page. It is declared on **every** state that renders one, error and loading
 * states included: an unavailable inventory is drawn inside the Ledger body
 * rather than instead of it, so those are exactly the states where a broken
 * scroll owner would go unnoticed. The measurements are: which element owns the scroll, whether the shell was told to contain
 * it, whether the sticky header sticks to the scroller the operator actually
 * uses, and — for a standard Ledger at 2560 — whether a sparse table was
 * stretched across the display instead of being left-aligned.
 */

const CAM = '11111111-1111-7111-8111-111111111111';
const VIDEO = '22222222-2222-7222-8222-222222222222';
const LONG_VIDEO = '44444444-4444-7444-8444-444444444444';
const FAILED_VIDEO = '55555555-5555-7555-8555-555555555555';

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

/**
 * Drive the Scene Editor into its densest *real* fixed-chrome state.
 *
 * The other Workbench states are realistic, which is the point of them; this
 * one is deliberately the worst arrangement the product can actually reach, so
 * that "the page does not scroll" is tested against a Workbench that has every
 * band it can have at once rather than against the geometry that happens to
 * ship in the fixtures. Nothing here is invented UI: the notices come from an
 * inactive camera, an unavailable video list and a revision that will not load,
 * and the footer comes from the revision strip the operator can open.
 */
const DENSE_WORKBENCH = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const byName = (name) => Array.from(document.querySelectorAll('button'))
    .find((b) => new RegExp(name).test((b.textContent || '').trim()));

  // Open the revision strip, which is a real footer band on this surface.
  const revisions = byName('^Revisions$');
  if (!revisions) return false;
  revisions.click();
  await wait(250);

  // Open a past revision whose fetch is answered 503, which is the third notice.
  const view = byName('^View revision');
  if (view) { view.click(); await wait(600); }

  return document.querySelectorAll('.workspace__notices .alert, .workspace__notices p').length >= 2;
})()`;


/** Open the Ledger's create region the way an operator does. */
const OPEN_CAMERA_FORM = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  await wait(300);
  return Boolean(document.querySelector('form[aria-label="Add camera"]'));
})()`;

/** Open it and submit nothing, which is three field-level refusals at once. */
const INVALID_CAMERA_FORM = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  await wait(300);
  const form = document.querySelector('form[aria-label="Add camera"]');
  if (!form) return false;
  const submit = form.querySelector('button[type="submit"]');
  if (!submit) return false;
  submit.click();
  await wait(300);
  return Boolean(document.querySelector('.field__error'));
})()`;

/**
 * Reach the duplicate-code conflict through the real form and the real 409,
 * so the state is the one the server produces rather than a simulation of it.
 */
const CONFLICTED_CAMERA_FORM = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const type = (input, value) => { setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); };

  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  await wait(300);
  const form = document.querySelector('form[aria-label="Add camera"]');
  if (!form) return false;
  const inputs = Array.from(form.querySelectorAll('input'));
  if (inputs.length < 2) return false;
  type(inputs[0], 'CAM-01');
  type(inputs[1], 'Duplicate of the north gate');
  await wait(200);
  form.querySelector('button[type="submit"]').click();
  await wait(600);
  return Boolean(document.querySelector('.field__error'));
})()`;

/** Submit the import form empty: every field refuses, inline (§21). */
const SUBMIT_EMPTY_IMPORT = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const submit = Array.from(document.querySelectorAll('button')).find((b) => /Import and process/.test(b.textContent || ''));
  if (!submit) return false;
  submit.click();
  await wait(300);
  return document.querySelectorAll('.field__error').length >= 3;
})()`;

/**
 * Dense inventories, generated rather than committed: the density and
 * long-name states section 26 requires, without a third copy of the fixtures.
 */
const DENSE_CAMERAS = Array.from({ length: 24 }, (_, index) => ({
  id: `aaaaaaaa-0000-7000-8000-${String(index).padStart(12, '0')}`,
  code: index % 5 === 0 ? `NORTH-PERIMETER-GATE-CAM-${String(index).padStart(5, '0')}` : `CAM-${String(index + 1).padStart(2, '0')}`,
  name: index % 3 === 0
    ? 'Perimeter fence south-west sector, outer vehicle approach and pedestrian gate'
    : `Gate ${index + 1}`,
  description: null,
  locationName: null,
  timeZoneId: index % 4 === 0 ? 'America/Argentina/ComodRivadavia' : 'Asia/Kolkata',
  isActive: index % 7 !== 0,
  createdAtUtc: '2026-09-01T04:00:00Z',
  updatedAtUtc: '2026-09-01T04:00:00Z',
}));

const DENSE_STATUSES = ['Processed', 'Processing', 'Failed', 'NotQueued', 'Queued'];
const DENSE_VIDEOS = Array.from({ length: 30 }, (_, index) => ({
  id: `22222222-0000-7000-8000-${String(index).padStart(12, '0')}`,
  cameraId: CAM,
  originalFileName: index % 4 === 0
    ? `north-gate-${String(index).padStart(4, '0')}-very-long-original-file-name-for-truncation-checks.mp4`
    : `clip-${String(index).padStart(4, '0')}.mp4`,
  recordingStartUtc: `2026-09-${String((index % 28) + 1).padStart(2, '0')}T02:30:00Z`,
  recordingEndUtc: `2026-09-${String((index % 28) + 1).padStart(2, '0')}T02:40:00Z`,
  recordingTimeZoneId: 'Asia/Kolkata',
  recordingUtcOffsetMinutes: 330,
  durationMs: 600000 + index * 1000,
  width: 1920,
  height: 1080,
  frameRateNumerator: 25,
  frameRateDenominator: 1,
  codecName: 'h264',
  // Only the two videos with a processing fixture are given a state that makes
  // the queue poll for one; the rest stay out of it, so the dense states test
  // density rather than the fixture server.
  processingStatus: index < 2 ? DENSE_STATUSES[index] : 'NotQueued',
  importedAtUtc: '2026-09-14T03:00:00Z',
}));

export const WIDTHS = [
  { width: 1366, height: 768, label: '1366x768' },
  { width: 1440, height: 900, label: '1440x900' },
  { width: 1920, height: 1080, label: '1920x1080' },
  { width: 2560, height: 1080, label: '2560x1080' },
];

export const STATES = [
  // --- Ledger-summary: Overview, the one Ledger permitted to stay capped. ---
  { name: 'overview', path: '/', fullWidth: false, archetype: 'ledger-summary' },
  {
    name: 'overview-empty', path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: { '/api/videos': [], '/api/tracks': { items: [], nextCursor: null, totalCount: 0 } },
    expectText: 'No tracks yet',
  },
  {
    // One section's request failed; the other three must still answer.
    name: 'overview-partial-failure', path: '/', fullWidth: false, archetype: 'ledger-summary',
    settleMs: 4000, api: { '/api/videos': 'unavailable' },
    expectText: ['video inventory is unavailable', 'Media status unavailable'],
    forbidText: 'No tracks yet',
  },

  // --- Standard Ledgers: full width, column-capped, never stretched. --------
  { name: 'cameras', path: '/cameras', fullWidth: true, archetype: 'ledger' },
  {
    name: 'cameras-unavailable', path: '/cameras', fullWidth: true, archetype: 'ledger', settleMs: 4000,
    api: { '/api/cameras': 'unavailable' },
    expectText: 'unavailable', forbidText: 'No cameras registered',
  },
  {
    name: 'cameras-loading', path: '/cameras', fullWidth: true, archetype: 'ledger', settleMs: 500,
    api: { '/api/cameras': 'hang' }, expectText: 'Loading cameras',
  },
  {
    name: 'cameras-empty', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/cameras': [] }, expectText: 'No cameras registered',
  },
  {
    // The create region open and clean: §21's inline form, and the widest the
    // Context Bar gets on this surface.
    name: 'cameras-create', path: '/cameras', fullWidth: true, archetype: 'ledger',
    prepare: OPEN_CAMERA_FORM, expectText: 'Camera timezone',
    forbidText: 'Unsaved changes',
  },
  {
    // Submitted empty: three field-level refusals at once (§21).
    name: 'cameras-create-invalid', path: '/cameras', fullWidth: true, archetype: 'ledger',
    prepare: INVALID_CAMERA_FORM, expectText: 'A camera code is required.',
  },
  {
    // A duplicate-code 409 mapped onto the Code field, other drafts intact.
    name: 'cameras-create-conflict', path: '/cameras', fullWidth: true, archetype: 'ledger',
    prepare: CONFLICTED_CAMERA_FORM, settleMs: 900,
    api: {
      'POST /api/cameras': {
        status: 409,
        body: { title: 'Conflict', detail: 'A camera with this code already exists.', code: 'camera_code_duplicate' },
      },
    },
    expectText: ['A camera with this code already exists.', 'Unsaved changes'],
  },
  {
    // A long name and a dense inventory in one state: the column cap has to
    // truncate rather than widen, at every width.
    name: 'cameras-dense', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/cameras': DENSE_CAMERAS },
  },

  { name: 'videos', path: '/videos', fullWidth: true, archetype: 'ledger' },
  {
    name: 'videos-empty', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': [] }, expectText: 'No videos imported yet',
  },
  {
    name: 'videos-filtered-empty', path: '/videos?q=no-such-recording', fullWidth: true, archetype: 'ledger',
    expectText: 'No videos match these filters', forbidText: 'No videos imported yet',
  },
  {
    name: 'videos-unavailable', path: '/videos', fullWidth: true, archetype: 'ledger', settleMs: 4000,
    api: { '/api/videos': 'unavailable' },
    expectText: 'unavailable', forbidText: 'No videos imported yet',
  },
  {
    // Camera metadata gone: the list still lists, and says why the camera
    // column is thin.
    name: 'videos-cameras-unavailable', path: '/videos', fullWidth: true, archetype: 'ledger',
    settleMs: 4000, api: { '/api/cameras': 'unavailable' },
    expectText: 'Camera metadata is unavailable',
  },
  {
    name: 'videos-dense', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': DENSE_VIDEOS },
  },

  { name: 'processing-queue', path: '/processing', fullWidth: true, archetype: 'ledger', settleMs: 1200 },
  {
    name: 'processing-queue-empty', path: '/processing', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': [] }, expectText: 'Nothing has been queued',
  },
  {
    name: 'processing-queue-unavailable', path: '/processing', fullWidth: true, archetype: 'ledger', settleMs: 4000,
    api: { '/api/videos': 'unavailable' },
    expectText: 'unavailable', forbidText: 'Nothing has been queued',
  },
  {
    // The inventory answered and the per-row run lookups did not: each row
    // must say so and offer its retry, never sit on "Loading run…".
    name: 'processing-queue-row-unavailable', path: '/processing', fullWidth: true, archetype: 'ledger',
    settleMs: 4000,
    api: {
      '/api/videos/22222222-2222-7222-8222-222222222222/processing': 'unavailable',
      '/api/videos/44444444-4444-7444-8444-444444444444/processing': 'unavailable',
      '/api/videos/55555555-5555-7555-8555-555555555555/processing': 'unavailable',
    },
    expectText: 'Run status unavailable', forbidText: 'Loading run…',
  },
  {
    name: 'processing-queue-dense', path: '/processing', fullWidth: true, archetype: 'ledger',
    settleMs: 1400, api: { '/api/videos': DENSE_VIDEOS },
  },

  // --- Records: centred, the page scrolls. --------------------------------
  { name: 'import', path: '/import', fullWidth: false, archetype: 'record' },
  {
    name: 'import-no-active-cameras', path: '/import', fullWidth: false, archetype: 'record',
    api: { '/api/cameras': [{ ...DENSE_CAMERAS[0], isActive: false }] },
    expectText: 'No active camera to import against',
  },
  {
    name: 'import-cameras-unavailable', path: '/import', fullWidth: false, archetype: 'record', settleMs: 4000,
    api: { '/api/cameras': 'unavailable' },
    expectText: 'Camera inventory is unavailable',
    forbidText: 'No active camera to import against',
  },
  {
    name: 'import-invalid', path: '/import', fullWidth: false, archetype: 'record',
    prepare: SUBMIT_EMPTY_IMPORT, expectText: 'Enter the recording date and time.',
  },

  {
    // A completed run: final counts, the results action, diagnostics closed.
    name: 'processing-detail-completed', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 1200, expectText: 'north-gate-0800.mp4',
  },
  {
    // A running one: determinate progress, counts deliberately withheld.
    name: 'processing-detail-running', path: `/processing/${LONG_VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 1200, expectText: 'Final count after completion',
  },
  {
    name: 'processing-detail-failed', path: `/processing/${FAILED_VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 1200, expectText: 'worker_watchdog_timeout',
  },
  {
    name: 'processing-detail-unavailable', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 4000, api: { [`/api/videos/${VIDEO}/processing`]: 'unavailable' },
    expectText: 'Processing status is unavailable.',
  },

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
    // The worst identity the domain permits: `Camera.Create` allows a 32-character
    // code, and a long name beside it. A 44px band cannot grow, so this is where
    // the crumb trail either truncates or pushes the controls off the end.
    name: 'scene-editor-long-identity',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    settleMs: 1200,
    prepare: DIRTY_SCENE,
    api: {
      // The scene must keep its own fixture: a broader camera override would
      // otherwise answer this path too.
      [`/api/cameras/${CAM}/scene`]: 'fixture',
      [`/api/cameras/${CAM}`]: {
        id: CAM,
        code: 'NORTH-PERIMETER-GATE-CAM-00042',
        name: 'North perimeter vehicle entrance, outer gate',
        description: null,
        locationName: null,
        timeZoneId: 'Asia/Kolkata',
        isActive: true,
        createdAtUtc: '2026-09-01T04:00:00Z',
        updatedAtUtc: '2026-09-01T04:00:00Z',
      },
    },
    expectText: 'Unsaved changes',
  },
  {
    // The stress case for the frozen no-page-scroll rule (§4.3.2): every fixed
    // band this surface can have, at once, above and below the stage.
    name: 'scene-editor-dense',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    settleMs: 1400,
    prepare: DENSE_WORKBENCH,
    api: {
      // A revision the operator can ask for and the server will not give,
      // which is a real error notice rather than a contrived one.
      [`/api/cameras/${CAM}/scene/revisions`]: 'unavailable',
      [`/api/cameras/${CAM}/scene`]: 'fixture',
      [`/api/cameras/${CAM}`]: {
        id: CAM,
        code: 'CAM-01',
        name: 'North Gate',
        description: 'Main vehicle entrance',
        locationName: 'North perimeter',
        timeZoneId: 'Asia/Kolkata',
        // Inactive: a real warning notice, and the reason Save is refused.
        isActive: false,
        createdAtUtc: '2026-09-01T04:00:00Z',
        updatedAtUtc: '2026-09-01T04:00:00Z',
      },
      // Unavailable video list: a second real warning notice, with its own
      // retry control.
      '/api/videos': 'unavailable',
    },
    expectText: ['This camera is inactive', 'video list is unavailable'],
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
