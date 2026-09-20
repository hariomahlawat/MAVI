/**
 * The states and viewports the section 26 pass covers.
 *
 * `api` overrides a fixture for one state: a literal value is served as the
 * response, `'unavailable'` answers 503, and `'hang'` never answers, which is
 * how the loading state is held still long enough to look at.
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
const TRACK = '55555550-5555-7555-8555-555555555550';

/**
 * Drive the player to the representative frame using the product's own
 * control, so the overlay is drawn where it actually gets drawn. Setting
 * currentTime directly races the player's own seek handling.
 */
const SEEK = `(() => {
  const jump = Array.from(document.querySelectorAll('button')).find((b) => /Evidence/.test(b.textContent || ''));
  if (jump) jump.click();
  const v = document.querySelector('.player video');
  if (v) v.pause();
  return Boolean(jump);
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

  // --- Workbench: declares full width, and must actually use it. ---
  { name: 'scene-editor', path: `/cameras/${CAM}/scene`, fullWidth: true, settleMs: 1200 },
  {
    name: 'scene-editor-unconfigured',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    settleMs: 1200,
    api: { [`/api/cameras/${CAM}/scene`]: { cameraId: CAM, configured: false, activeRevision: null, history: [] } },
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
  { name: 'search', path: '/search', fullWidth: true, settleMs: 900 },
  {
    name: 'search-empty', path: '/search', fullWidth: true,
    api: { '/api/tracks': { items: [], nextCursor: null, totalCount: 0 } },
  },
  {
    name: 'search-unavailable', path: '/search', fullWidth: true, settleMs: 4000,
    api: { '/api/tracks': 'unavailable' }, expectText: 'unavailable',
  },

  // --- Review: capped today; its archetype migration is UI-5, not UI-1. ---
  // The evidence overlay: where the bounding-box and trajectory hues have to
  // survive footage the product does not control (section 26).
  { name: 'review', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, expectText: 'North Gate' },
  { name: 'review-bright', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'bright', prepare: SEEK },
  { name: 'review-dark', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'dark', prepare: SEEK },
  { name: 'review-saturated', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'saturated', prepare: SEEK },
  { name: 'review-lowcontrast', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'lowcontrast', prepare: SEEK },
  { name: 'review-letterbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, settleMs: 2000, footage: 'letterbox', prepare: SEEK },
];
