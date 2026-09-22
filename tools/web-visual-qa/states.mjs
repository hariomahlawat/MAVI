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

const TRACK = '55555550-5555-7555-8555-555555555550';
const CAM2 = '33333333-3333-7333-8333-333333333333';

/**
 * Proof that the inspector has the Track's evidence, not just its shell.
 *
 * Deliberately not the heading: §26 reads `innerText`, which reflects
 * `text-transform`, and the inspector's title is uppercased by the shared shell
 * — so a state asserting "Person · Track" would fail for a reason that has
 * nothing to do with the state it is checking.
 */
const INSPECTOR_LOADED = ['Track duration', 'Max confidence'];

/** One Track, restated with the long camera and video names of the fixtures. */
const LONG_NAME_TRACKS = {
  items: [{
    id: TRACK,
    videoAssetId: LONG_VIDEO,
    cameraId: CAM2,
    cameraCode: 'CAM-02',
    cameraName: 'Perimeter fence south-west sector, long descriptive name for truncation',
    objectClass: 'Person',
    startTimestampUtc: '2026-09-14T02:31:00Z',
    endTimestampUtc: '2026-09-14T02:31:10Z',
    startOffsetMs: 60000,
    endOffsetMs: 68000,
    durationMs: 8000,
    detectionCount: 40,
    meanConfidence: 0.91,
    maxConfidence: 0.98,
    reviewStatus: 'Unreviewed',
    thumbnailContentUrl: null,
  }],
  nextCursor: null,
  totalCount: 1,
};

/** A first page that has a continuation, so there is something to load more of. */
const PAGE_ONE = { ...LONG_NAME_TRACKS, nextCursor: 'opaque-cursor', totalCount: 48 };

/** Page one, then a transient failure: the results survive, continuation stops. */
const PAGE_ONE_THEN_503 = { sequence: [PAGE_ONE, 'unavailable'] };

/** Page one, then the snapshot the cursor belonged to is gone. */
const PAGE_ONE_THEN_EXPIRED = {
  sequence: [PAGE_ONE, {
    status: 400,
    body: { status: 400, code: 'track_search_invalid', detail: 'The result snapshot has expired.' },
  }],
};

// --- Slice 4: analytic search ------------------------------------------------

const ZONE = '77777777-7777-7777-8777-777777777777';
const REVISION = '66666666-6666-7666-8666-666666666666';

/** The §H coverage block for a partially analysed scope. */
const PARTIAL_COVERAGE = {
  sceneRevisionId: REVISION, algorithmVersion: 'scene-analytics-v1',
  evaluatedRuns: 2, pendingRuns: 1, failedRuns: 0, notConfiguredRuns: 0, disabledRuns: 1, staleRuns: 1,
  analysedTracks: 17, unavailableTracks: 2, complete: false,
};

const COMPLETE_COVERAGE = {
  ...PARTIAL_COVERAGE, evaluatedRuns: 4, pendingRuns: 0, disabledRuns: 0, staleRuns: 0, unavailableTracks: 0, complete: true,
};

/** An analytic first page: the fixture rows, each explained against the pinned identity. */
const ANALYTIC_PAGE = (coverage) => ({
  items: LONG_NAME_TRACKS.items.map((item) => ({
    ...item,
    cameraId: CAM, cameraCode: 'CAM-01', cameraName: 'North Gate', videoAssetId: VIDEO,
    analytics: {
      sceneRevisionId: REVISION, algorithmVersion: 'scene-analytics-v1',
      zones: [{ zoneId: ZONE, visitCount: 2, totalDwellMs: 14000, loitering: true }],
      lines: [], motion: null,
    },
  })),
  nextCursor: null,
  analyticsCoverage: coverage,
});

/** Nothing evaluated yet: an analytic zero result that must not read as "no matches". */
const NOT_ANALYSED_PAGE = {
  items: [], nextCursor: null,
  analyticsCoverage: { ...PARTIAL_COVERAGE, evaluatedRuns: 0, pendingRuns: 3, disabledRuns: 0, staleRuns: 0, analysedTracks: 0, unavailableTracks: 0 },
};

/** Pick the fixture camera in the rail so the Analytics group resolves its scene. */
const PICK_CAMERA = `(() => {
  const select = Array.from(document.querySelectorAll('select'))
    .find((element) => element.labels?.[0]?.textContent.trim() === 'Camera');
  if (!select || !Array.from(select.options).some((option) => option.value === '${CAM}')) return false;
  const set = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  set.call(select, '${CAM}');
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()`;

/** Switch the results column to the Grid; the choice is a stored preference. */
const PICK_GRID = `(() => {
  const control = document.querySelector('[aria-label="Grid view"]');
  if (!control) return false;
  control.click();
  return true;
})()`;

/** Ask for the next page of the snapshot. */
const LOAD_MORE = `(() => {
  const control = Array.from(document.querySelectorAll('button'))
    .find((element) => element.textContent.trim() === 'Load more');
  if (!control) return false;
  control.click();
  return true;
})()`;

/**
 * Put two thresholds the product refuses into the rail and ask for the search,
 * so the field-level refusals of section 10 can be looked at.
 *
 * React owns the input's value, so assigning to `.value` is discarded on the
 * next render; the native setter plus a bubbled `input` event is what the
 * product's own change handler actually sees.
 */
const REFUSE_FIELDS = `(() => {
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const type = (label, value) => {
    const field = Array.from(document.querySelectorAll('.field'))
      .find((element) => element.querySelector('label')?.textContent.trim() === label);
    const input = field?.querySelector('input');
    if (!input) return false;
    set.call(input, value);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  };
  if (!type('Minimum duration (seconds)', '1.2345')) return false;
  if (!type('Minimum confidence (%)', '140')) return false;
  const search = Array.from(document.querySelectorAll('button[type="submit"]'))
    .find((element) => element.textContent.includes('Search'));
  if (!search) return false;
  search.click();
  return true;
})()`;

/**
 * Drive the player to the representative frame using the product's own
 * control, so the overlay is drawn where it actually gets drawn. Setting
 * currentTime directly races the player's own seek handling.
 */
const SEEK = `(() => {
  const v = document.querySelector('.evidence-player__video');
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

/*
 * Scene Analytics Slice 5 conditions.
 *
 * Each is the whole Track detail with its analytics block replaced, so the
 * rendered page reaches the state through the real contract rather than
 * through a prop a test set. The single-sample trajectory is served through
 * the same artefact route as the full one, which is what lets raw evidence
 * and analytics-unavailable be shown together rather than argued about.
 */
const REVIEW_OVERLAP_2 = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 2,
        "totalDwellMs": 2600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitCount": 2,
        "totalDwellMs": 2600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2600,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 1,
        "entryOffsetMs": 720,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2480,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

const REVIEW_OVERLAP_3 = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 3,
        "totalDwellMs": 2600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitCount": 3,
        "totalDwellMs": 2600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2600,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 1,
        "entryOffsetMs": 720,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2480,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 2,
        "entryOffsetMs": 840,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2360,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

const REVIEW_OVERLAP_5 = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 5,
        "totalDwellMs": 2600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitCount": 5,
        "totalDwellMs": 2600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2600,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 1,
        "entryOffsetMs": 720,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2480,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 2,
        "entryOffsetMs": 840,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2360,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 3,
        "entryOffsetMs": 960,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2240,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 4,
        "entryOffsetMs": 1080,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2120,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

const REVIEW_MULTI_VISIT = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 2,
        "totalDwellMs": 1600,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": true,
        "loiteringThresholdSeconds": 1,
        "loiteringDwellMs": 1600
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 1400,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 800,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 1,
        "entryOffsetMs": 1900,
        "exitOffsetMs": 2700,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 800,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": true,
        "entryHeading": "E",
        "exitHeading": "W"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

const REVIEW_CROSSING_BTOA = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 1,
        "totalDwellMs": 2100,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00.6Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:02.7Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 2700,
        "entryTimestampUtc": "2026-09-14T02:30:00.6Z",
        "exitTimestampUtc": "2026-09-14T02:30:02.7Z",
        "dwellMs": 2100,
        "beganInside": true,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "None",
        "exitHeading": "E"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "bToA",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

const REVIEW_DWELL_STATIONARY = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 1,
        "totalDwellMs": 2100,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 2700,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 2100,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 900,
      "totalStationaryMs": 1400,
      "stationaryIntervals": [
        {
          "startOffsetMs": 900,
          "endOffsetMs": 1800
        },
        {
          "startOffsetMs": 2200,
          "endOffsetMs": 2700
        }
      ],
      "stationaryZoneIds": [
        "77777777-7777-7777-8777-777777777777"
      ]
    },
    "otherIdentities": []
  }
};

const REVIEW_DENSE_MARKERS = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 1,
        "totalDwellMs": 2100,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00.6Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:02.7Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 2700,
        "entryTimestampUtc": "2026-09-14T02:30:00.6Z",
        "exitTimestampUtc": "2026-09-14T02:30:02.7Z",
        "dwellMs": 2100,
        "beganInside": true,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "None",
        "exitHeading": "E"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 1900,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.42,
        "pointY": 0.5
      },
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 1,
        "offsetMs": 1960,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "bToA",
        "pointX": 0.44,
        "pointY": 0.5
      },
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 2,
        "offsetMs": 2020,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.46,
        "pointY": 0.5
      },
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 3,
        "offsetMs": 2080,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "bToA",
        "pointX": 0.48,
        "pointY": 0.5
      },
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 4,
        "offsetMs": 2140,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.5,
        "pointY": 0.5
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

const REVIEW_ANALYTICS_UNAVAILABLE = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Unavailable",
    "unavailableReason": "trajectory_too_short",
    "referencePoint": "bbox-centre",
    "sampleCount": 1,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [],
    "zoneVisits": [],
    "lineCrossings": [],
    "motion": null,
    "otherIdentities": []
  }
};

const REVIEW_ANALYTICS_PENDING = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": null,
    "sceneRevisionNumber": null,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Pending",
    "unavailableReason": null,
    "referencePoint": null,
    "sampleCount": null,
    "gapCount": null,
    "gapTotalMs": null,
    "zoneSummaries": [],
    "zoneVisits": [],
    "lineCrossings": [],
    "motion": null,
    "otherIdentities": []
  }
};

const REVIEW_ANALYTICS_STALE = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Stale",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 1,
        "totalDwellMs": 2100,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00.6Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:02.7Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 600,
        "exitOffsetMs": 2700,
        "entryTimestampUtc": "2026-09-14T02:30:00.6Z",
        "exitTimestampUtc": "2026-09-14T02:30:02.7Z",
        "dwellMs": 2100,
        "beganInside": true,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "None",
        "exitHeading": "E"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};
const SINGLE_SAMPLE_TRACK = (() => {
  const detail = JSON.parse(JSON.stringify(REVIEW_ANALYTICS_UNAVAILABLE));
  detail.trajectoryContentUrl = '/api/artifacts/single/trajectory';
  return detail;
})();

const REVIEW_OVERFLOW_SPANS = {
  "id": "55555550-5555-7555-8555-555555555550",
  "processingRunId": "bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb",
  "videoAssetId": "22222222-2222-7222-8222-222222222222",
  "camera": {
    "id": "11111111-1111-7111-8111-111111111111",
    "code": "CAM-01",
    "name": "North Gate"
  },
  "objectClass": "Person",
  "localTrackNumber": 1,
  "startOffsetMs": 600,
  "endOffsetMs": 3400,
  "startTimestampUtc": "2026-09-14T02:30:00Z",
  "endTimestampUtc": "2026-09-14T02:30:03Z",
  "durationMs": 2800,
  "detectionCount": 42,
  "meanConfidence": 0.913,
  "maxConfidence": 0.981,
  "reviewStatus": "Unreviewed",
  "processing": {
    "pipelineVersion": "1.4.0",
    "detectorName": "RTMDet",
    "detectorVersion": "1.2.0",
    "trackerName": "ByteTrack",
    "trackerVersion": "0.9.1",
    "completedAtUtc": "2026-09-14T03:09:40Z"
  },
  "video": {
    "recordingStartUtc": "2026-09-14T02:30:00Z",
    "recordingEndUtc": "2026-09-14T02:40:00Z",
    "durationMs": 4000,
    "width": 1920,
    "height": 1080,
    "frameRateNumerator": 25,
    "frameRateDenominator": 1,
    "videoContentUrl": "/api/videos/22222222-2222-7222-8222-222222222222/content"
  },
  "representative": {
    "observationId": "dddddddd-dddd-7ddd-8ddd-dddddddddddd",
    "sourceFrameNumber": 40,
    "videoOffsetMs": 1600,
    "timestampUtc": "2026-09-14T02:30:01Z",
    "confidence": 0.962,
    "qualityScore": 0.88,
    "boundingBox": {
      "x": 0.34,
      "y": 0.3,
      "width": 0.16,
      "height": 0.34
    },
    "thumbnailArtifactId": null,
    "thumbnailContentUrl": null
  },
  "trajectoryArtifactId": "cccccccc-cccc-7ccc-8ccc-cccccccccccc",
  "trajectoryContentUrl": "/api/artifacts/track1/trajectory",
  "analytics": {
    "sceneRevisionId": "66666666-6666-7666-8666-666666666666",
    "sceneRevisionNumber": 4,
    "algorithmVersion": "scene-analytics-v1",
    "status": "Analysed",
    "unavailableReason": null,
    "referencePoint": "bbox-centre",
    "sampleCount": 42,
    "gapCount": 0,
    "gapTotalMs": 0,
    "zoneSummaries": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitCount": 5,
        "totalDwellMs": 4000,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitCount": 5,
        "totalDwellMs": 4000,
        "firstEntryTimestampUtc": "2026-09-14T02:30:00Z",
        "lastExitTimestampUtc": "2026-09-14T02:30:03Z",
        "loitering": false,
        "loiteringThresholdSeconds": 120,
        "loiteringDwellMs": 0
      }
    ],
    "zoneVisits": [
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 0,
        "entryOffsetMs": 400,
        "exitOffsetMs": 1400,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 1000,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 1,
        "entryOffsetMs": 460,
        "exitOffsetMs": 1400,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 940,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 2,
        "entryOffsetMs": 520,
        "exitOffsetMs": 1400,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 880,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 3,
        "entryOffsetMs": 580,
        "exitOffsetMs": 1400,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 820,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 4,
        "entryOffsetMs": 640,
        "exitOffsetMs": 1400,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 760,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 5,
        "entryOffsetMs": 2200,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 1000,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 6,
        "entryOffsetMs": 2260,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 940,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 7,
        "entryOffsetMs": 2320,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 880,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "88888888-8888-7888-8888-888888888888",
        "visitIndex": 8,
        "entryOffsetMs": 2380,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 820,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      },
      {
        "zoneId": "77777777-7777-7777-8777-777777777777",
        "visitIndex": 9,
        "entryOffsetMs": 2440,
        "exitOffsetMs": 3200,
        "entryTimestampUtc": "2026-09-14T02:30:00Z",
        "exitTimestampUtc": "2026-09-14T02:30:03Z",
        "dwellMs": 760,
        "beganInside": false,
        "endedInside": false,
        "closedByGap": false,
        "entryHeading": "E",
        "exitHeading": "W"
      }
    ],
    "lineCrossings": [
      {
        "lineId": "99999999-9999-7999-8999-999999999999",
        "crossingIndex": 0,
        "offsetMs": 2000,
        "timestampUtc": "2026-09-14T02:30:02Z",
        "direction": "aToB",
        "pointX": 0.487,
        "pointY": 0.523
      }
    ],
    "motion": {
      "heading": "E",
      "pathLengthNormalised": 0.31,
      "meanDisplacementRate": 0.11,
      "longestStationaryMs": 0,
      "totalStationaryMs": 0,
      "stationaryIntervals": [],
      "stationaryZoneIds": []
    },
    "otherIdentities": []
  }
};

/**
 * Same-instant density, derived rather than re-pasted.
 *
 * Five concurrent visits that all begin together, and five crossings that share
 * one exact millisecond. Both are the cases where a rail that positions by
 * offset alone puts controls on top of each other: the first fills the overflow
 * span with no stagger available, the second must collapse into one control
 * because there is one destination, while still naming all five facts.
 */
const REVIEW_OVERFLOW_SAME_START = {
  ...REVIEW_OVERLAP_5,
  analytics: {
    ...REVIEW_OVERLAP_5.analytics,
    zoneVisits: REVIEW_OVERLAP_5.analytics.zoneVisits.map((visit) => ({
      ...visit, entryOffsetMs: 700,
    })),
  },
};

const REVIEW_MARKERS_SAME_OFFSET = {
  ...REVIEW_DENSE_MARKERS,
  analytics: {
    ...REVIEW_DENSE_MARKERS.analytics,
    lineCrossings: REVIEW_DENSE_MARKERS.analytics.lineCrossings.map((crossing) => ({
      ...crossing, offsetMs: 1900,
    })),
  },
};

/**
 * Seek to the evidence, then single out one overflowed visit.
 *
 * The overflow disclosure is the only route to a visit the capped sub-rows
 * could not hold, so the captured state is the one an operator actually
 * reaches: disclosure open, one exact interval highlighted on the rail.
 */
const SHOW_OVERFLOWED = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const v = document.querySelector('.evidence-player__video');
  if (v) {
    if (v.readyState < 2) { try { v.load(); v.play().then(() => v.pause()).catch(() => {}); } catch { /* ignore */ } }
    const jump = Array.from(document.querySelectorAll('button')).find((b) => /Evidence/.test(b.textContent || ''));
    if (jump) jump.click();
    v.pause();
  }
  const disclosure = document.querySelector('.evidence-timeline__dense');
  if (!disclosure) return false;
  disclosure.open = true;
  await wait(120);
  const control = disclosure.querySelector('button');
  if (!control) return false;
  control.click();
  await wait(120);
  return Boolean(document.querySelector('.evidence-timeline__shown'));
})()`;

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

  // --- Investigation: Search, migrated in UI-4. -------------------------
  //
  // Twenty-one states, because this is the surface where the operator's whole
  // job happens and almost every §14 state is reachable on it. The breakpoint
  // states below carry their own viewports: a threshold is settled by the
  // widths either side of it and nowhere else.
  {
    name: 'search', path: '/search', fullWidth: true, settleMs: 900, archetype: 'investigation',
    expectText: 'Newest first',
  },
  {
    name: 'search-loading', path: '/search', fullWidth: true, settleMs: 400,
    archetype: 'investigation', api: { '/api/tracks': 'hang' },
    expectText: 'Searching visual intelligence',
  },
  {
    name: 'search-empty', path: '/search', fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': { items: [], nextCursor: null, totalCount: 0 } },
    expectText: 'No Tracks matched',
  },
  {
    name: 'search-unavailable', path: '/search', fullWidth: true, settleMs: 4000,
    archetype: 'investigation', api: { '/api/tracks': 'unavailable' },
    // §14.1: a failed first page is distinguishable from an empty one, and
    // offers the retry it did not have before UI-4.
    expectText: ['unavailable', 'Retry'], forbidText: 'No Tracks matched',
  },
  {
    name: 'search-invalid', path: '/search?objectClass=Person&objectClass=Vehicle',
    fullWidth: true, archetype: 'investigation',
    // A malformed committed URL is refused at page level, and no Track request
    // is issued for it — the results column stays empty rather than loading.
    expectText: 'must occur exactly once', forbidText: 'Searching visual intelligence',
  },
  {
    name: 'search-grid', path: '/search', fullWidth: true, settleMs: 900, archetype: 'investigation',
    prepare: PICK_GRID, expectText: 'Review evidence',
  },
  {
    name: 'search-filtered',
    path: `/search?cameraId=${CAM}&objectClass=Person&fromUtc=2026-09-14T02%3A00%3A00Z&toUtc=2026-09-14T04%3A00%3A00Z&minimumDurationMs=2500&minimumConfidence=0.8`,
    fullWidth: true, settleMs: 900, archetype: 'investigation',
    // Every committed criterion is a chip, and each resolves to what the
    // operator calls it rather than to the identifier in the URL.
    expectText: ['CAM-01', 'Minimum confidence', '2.5 s'],
  },
  {
    name: 'search-filtered-unresolved',
    path: `/search?cameraId=${CAM}&videoAssetId=${VIDEO}&processingRunId=77777777-7777-7777-8777-777777777777`,
    fullWidth: true, settleMs: 4000, archetype: 'investigation',
    api: { '/api/cameras': 'unavailable', '/api/videos': 'unavailable' },
    // The metadata that names them is gone; the chips shorten the identifier
    // rather than dropping a criterion that is still in force.
    expectText: ['Camera metadata is unavailable', 'Processing run', '11111111…'],
  },
  {
    name: 'search-no-timezone', path: '/search?fromUtc=2026-09-14T02%3A30%3A00Z',
    fullWidth: true, settleMs: 4000, archetype: 'investigation',
    api: { '/api/system/config': 'unavailable' },
    // ADR-004: without the configured zone the bound is stated explicitly in
    // UTC and time editing is refused rather than guessed at.
    expectText: ['Display timezone is unavailable', 'UTC'],
  },
  {
    name: 'search-videos-unavailable', path: '/search', fullWidth: true, settleMs: 4000,
    archetype: 'investigation', api: { '/api/videos': 'unavailable' },
    expectText: 'Video metadata is unavailable',
  },
  {
    // The tallest the rail gets: every field refused at once, on top of the
    // video-outage hint, at the shortest acceptance viewport. This is where a
    // rail that owns its own scroll, or whose actions are stuck to its bottom
    // edge, puts a control on top of a field — and where the containment border
    // has to stay inside the 252px column rather than widening it.
    name: 'search-rail-overflow', path: '/search', fullWidth: true, settleMs: 4000,
    archetype: 'investigation', widths: [1366, 1440],
    api: { '/api/videos': 'unavailable' },
    prepare: REFUSE_FIELDS, prepareSettleMs: 900,
    expectText: ['Video metadata is unavailable', 'decimal places', 'Reset'],
  },
  {
    name: 'search-field-errors', path: '/search', fullWidth: true, settleMs: 900,
    archetype: 'investigation', prepare: REFUSE_FIELDS,
    // §10: both refusals land on their own fields, at once.
    expectText: ['decimal places', 'between 0 and 100'],
  },
  {
    name: 'search-long-names', path: `/search?cameraId=${CAM2}`, fullWidth: true, settleMs: 900,
    archetype: 'investigation',
    // The second camera exists but has no scene, which the real API answers
    // with an unconfigured scene rather than a 404. Without the stub the
    // harness records a resource error for a request the product makes
    // correctly (the Analytics rail asks every committed camera scope for its
    // geometry).
    api: {
      '/api/tracks': LONG_NAME_TRACKS,
      [`/api/cameras/${CAM2}/scene`]: { cameraId: CAM2, configured: false, activeRevision: null, history: [] },
    },
    expectText: 'Perimeter fence',
  },
  {
    name: 'search-paged', path: '/search', fullWidth: true, settleMs: 900, archetype: 'investigation',
    api: { '/api/tracks': PAGE_ONE },
    expectText: ['Load more', 'more to load'],
  },
  {
    name: 'search-continuation-failed', path: '/search', fullWidth: true, settleMs: 5000,
    archetype: 'investigation', api: { '/api/tracks': PAGE_ONE_THEN_503 },
    // The query client retries a 5xx once before the failure is terminal.
    prepare: LOAD_MORE, prepareSettleMs: 3000,
    // The page that failed does not take the results with it, and continuation
    // stops being automatic until the operator asks again.
    expectText: ['next page could not be loaded', 'Retry load more'],
  },
  {
    name: 'search-snapshot-expired', path: '/search', fullWidth: true, settleMs: 5000,
    archetype: 'investigation', api: { '/api/tracks': PAGE_ONE_THEN_EXPIRED }, prepare: LOAD_MORE,
    expectText: ['snapshot can no longer continue', 'Refresh results'],
  },
  {
    name: 'search-end-of-snapshot', path: '/search', fullWidth: true, settleMs: 900,
    archetype: 'investigation', expectText: ['End of this result snapshot', 'all loaded'],
  },
  {
    name: 'search-inspecting', path: `/search?track=${TRACK}`, fullWidth: true, settleMs: 2000,
    archetype: 'investigation', expectText: INSPECTOR_LOADED,
  },
  {
    name: 'search-inspecting-grid', path: `/search?track=${TRACK}`, fullWidth: true, settleMs: 2000,
    archetype: 'investigation', prepare: PICK_GRID, expectText: INSPECTOR_LOADED,
  },
  {
    // The narrow host. Marker separation is measured from the rendered track,
    // not assumed from Review's wider column, so dense markers have to stay
    // individually clickable in the drawer too.
    name: 'search-inspecting-dense', path: `/search?track=${TRACK}`, fullWidth: true, settleMs: 2200,
    archetype: 'investigation',
    api: { [`/api/tracks/${TRACK}`]: REVIEW_DENSE_MARKERS },
    expectText: INSPECTOR_LOADED,
  },
  {
    name: 'search-inspector-unavailable', path: `/search?track=${TRACK}`, fullWidth: true,
    settleMs: 4000, archetype: 'investigation',
    api: { [`/api/tracks/${TRACK}`]: 'unavailable' },
    // The inspector states an ApiError by its detail and code; "could not be
    // loaded" is only the fallback for a failure that is not one.
    expectText: ['upstream_unavailable', 'Retry'],
  },
  {
    name: 'search-inspector-missing', path: `/search?track=${TRACK}`, fullWidth: true,
    settleMs: 2000, archetype: 'investigation',
    api: { [`/api/tracks/${TRACK}`]: { status: 404, body: { status: 404, code: 'track_not_found', detail: 'Track was not found.' } } },
    // The one failure retrying cannot mend, so it is stated without a control
    // that would only fail again.
    expectText: 'Track was not found', forbidText: 'Retry',
  },
  {
    // Open decision 3, closed in UI-4 at 1600px. The threshold is settled by the
    // widths either side of it: 1599 must be a drawer, 1600 an in-place column,
    // and 1500 — the frozen default UI-4 amended away — must still be a drawer
    // rather than the clipped three columns it produced before.
    name: 'search-threshold', path: `/search?track=${TRACK}`, fullWidth: true, settleMs: 2000,
    // The threshold is 1600, so the widths either side of it are what settle it.
    archetype: 'investigation', widths: [1440, 1500, 1550, 1599, 1600, 1700],
    expectText: INSPECTOR_LOADED,
  },
  {
    // Open decision 4. At 1920 and 2560 the results stay capped and the
    // inspector takes the surplus — asserted as geometry, not by eye.
    name: 'search-ultrawide', path: `/search?track=${TRACK}`, fullWidth: true, settleMs: 2000,
    archetype: 'investigation', widths: [1920, 2560], expectText: INSPECTOR_LOADED,
  },

  // --- Investigation: Slice 4 analytics on the UI-4 grammar. --------------
  {
    // Zone, relation and dwell committed; the chips name the geometry the scene
    // fixture owns, the coverage strip sits beneath the header and names every
    // non-zero bucket, and the rows carry no second status badge.
    name: 'search-analytics',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}&zoneRelation=entered&minDwellMs=2500&loitering=true`,
    fullWidth: true, settleMs: 1500, archetype: 'investigation',
    api: { '/api/tracks': ANALYTIC_PAGE(PARTIAL_COVERAGE) },
    expectText: ['Entered', 'Loading bay', '2 of 5 runs analysed', 'not yet analysed', 'could not be analysed', 'Revision 4'],
    forbidText: 'No Tracks matched',
  },
  {
    name: 'search-analytics-complete',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}`,
    fullWidth: true, settleMs: 1500, archetype: 'investigation',
    api: { '/api/tracks': ANALYTIC_PAGE(COMPLETE_COVERAGE) },
    // "Processing" is a navigation item, so the absence asserted is the link's
    // own words in the strip, not the word itself.
    expectText: ['All 4 runs analysed', 'Dwelled in'], forbidText: 'could not be analysed',
  },
  {
    // Incomplete analytics never render as ordinary zero matches (§14, §17).
    name: 'search-analytics-not-analysed',
    path: `/search?cameraId=${CAM}&loitering=true`,
    fullWidth: true, settleMs: 1500, archetype: 'investigation',
    api: { '/api/tracks': NOT_ANALYSED_PAGE },
    expectText: ['Not analysed yet.', '3 runs not yet analysed'], forbidText: 'No Tracks matched',
  },
  {
    // The scene that names the geometry is gone: the committed zone stays in
    // force by identifier and the rail says why its choices are unavailable.
    name: 'search-analytics-scene-unavailable',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}`,
    fullWidth: true, settleMs: 4000, archetype: 'investigation',
    api: { '/api/tracks': ANALYTIC_PAGE(PARTIAL_COVERAGE), [`/api/cameras/${CAM}/scene`]: 'unavailable' },
    expectText: ['Scene geometry is unavailable', '77777777…'],
  },
  {
    // The Analytics group with a camera chosen: zone and line choices resolved
    // from the active revision, dependents unlocked, the rail tall enough to
    // scroll at 1366 — which is what the overlap assertion is for.
    name: 'search-analytics-rail', path: '/search', fullWidth: true, settleMs: 2500, archetype: 'investigation',
    // The group heading is uppercased on screen; its field labels are not.
    prepare: PICK_CAMERA, expectText: ['Zone relation', 'Motion direction', 'Loitering', 'Loading bay'],
    forbidText: 'Choose a camera, video or processing run',
  },
  {
    // The inspector's analytics summary against the pinned identity.
    name: 'search-analytics-inspecting',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}&track=${TRACK}`,
    fullWidth: true, settleMs: 2500, archetype: 'investigation',
    // The page override is a prefix match, so the Track detail beneath it is
    // re-exposed as its fixture; otherwise the inspector would be handed a page.
    api: { '/api/tracks': ANALYTIC_PAGE(PARTIAL_COVERAGE), [`/api/tracks/${TRACK}`]: 'fixture' },
    // Slice 5 gives the shared Track detail a crossing, so the inspector's
    // explanation states it rather than "no line crossed", and it names the
    // revision in the fuller wording section 16 settles on.
    expectText: [...INSPECTOR_LOADED, 'Scene revision 4 · Engine v1', 'Loading bay', 'Gate A · 1 crossing'],
  },

  // --- Processing: Slice 4 readiness on the Ledger and the Record. ----------
  {
    // Readiness as text in its own column; one badge per row still.
    // The column header is uppercased by the Ledger, so the readiness word the
    // completed row carries is the text that proves the column rendered.
    name: 'processing-queue-analytics', path: '/processing', fullWidth: true, archetype: 'ledger', settleMs: 1400,
    expectText: ['Analysed'],
  },
  {
    name: 'processing-detail-analytics-ready', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 1400,
    expectText: ['Scene analytics', 'Revision 4 · scene-analytics-v1', 'Tracks unavailable'],
  },
  {
    // Stale: the current geometry is not applied; the camera-wide consequence is
    // stated before the action.
    name: 'processing-detail-analytics-stale', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 1400,
    api: {
      [`/api/videos/${VIDEO}/processing`]: {
        videoStatus: 'Processed',
        latestRun: {
          processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', status: 'Completed', pipeline: 'phase1-detection-tracking', pipelineVersion: 'phase1-v1',
          workerId: 'worker-a', queuedAtUtc: '2026-09-14T03:05:00Z', startedAtUtc: '2026-09-14T03:05:10Z', completedAtUtc: '2026-09-14T03:09:40Z',
          progressPercent: 100, attemptCount: 1, failureCode: null, framesProcessed: 15000, tracksCreated: 6, analyticsReadiness: 'Stale',
        },
      },
      '/api/processing/runs/bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb/analytics': {
        processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', readiness: 'Stale', activeSceneRevisionId: REVISION, algorithmVersion: 'scene-analytics-v1',
        analyses: [{
          analysisId: 'aaaaaaa1-aaaa-7aaa-8aaa-aaaaaaaaaaa1', processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb',
          sceneRevisionId: '66666666-6666-7666-8666-666666666665', sceneRevisionNumber: 3, algorithmVersion: 'scene-analytics-v1', status: 'Superseded',
          attemptCount: 1, queuedAtUtc: '2026-09-14T03:10:00Z', startedAtUtc: '2026-09-14T03:10:02Z', completedAtUtc: '2026-09-14T03:10:41Z',
          leaseExpiresAtUtc: null, analysedTrackCount: 5, unavailableTrackCount: 1, failureCode: null,
        }],
      },
    },
    expectText: ['Stale', 'Re-analyse camera', 'every video of'],
  },
  {
    name: 'processing-detail-analytics-failed', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', settleMs: 1400,
    api: {
      [`/api/videos/${VIDEO}/processing`]: {
        videoStatus: 'Processed',
        latestRun: {
          processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', status: 'Completed', pipeline: 'phase1-detection-tracking', pipelineVersion: 'phase1-v1',
          workerId: 'worker-a', queuedAtUtc: '2026-09-14T03:05:00Z', startedAtUtc: '2026-09-14T03:05:10Z', completedAtUtc: '2026-09-14T03:09:40Z',
          progressPercent: 100, attemptCount: 1, failureCode: null, framesProcessed: 15000, tracksCreated: 6, analyticsReadiness: 'Failed',
        },
      },
      '/api/processing/runs/bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb/analytics': {
        processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', readiness: 'Failed', activeSceneRevisionId: REVISION, algorithmVersion: 'scene-analytics-v1',
        analyses: [{
          analysisId: 'aaaaaaa1-aaaa-7aaa-8aaa-aaaaaaaaaaa1', processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb',
          sceneRevisionId: REVISION, sceneRevisionNumber: 4, algorithmVersion: 'scene-analytics-v1', status: 'Failed',
          attemptCount: 3, queuedAtUtc: '2026-09-14T03:10:00Z', startedAtUtc: '2026-09-14T03:10:02Z', completedAtUtc: '2026-09-14T03:12:41Z',
          leaseExpiresAtUtc: null, analysedTrackCount: 0, unavailableTrackCount: 0, failureCode: 'analytics_attempts_exhausted',
        }],
      },
    },
    expectText: ['Analysis failed', 'Retry analytics', 'analytics_attempts_exhausted'],
  },

  // --- Review: capped today; its archetype migration is UI-5, not UI-1. ---
  // The evidence overlay: where the bounding-box and trajectory hues have to
  // survive footage the product does not control (section 26).
  // UI-5: Review is on the Review archetype and uses the full width, so the
  // player takes the surplus on a wide display (section 25).
  { name: 'review', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, expectText: ['North Gate', 'Track summary'] },
  { name: 'review-bright', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'bright', prepare: SEEK, requireOverlay: true },
  { name: 'review-dark', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'dark', prepare: SEEK, requireOverlay: true },
  { name: 'review-saturated', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, requireOverlay: true },
  { name: 'review-lowcontrast', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'lowcontrast', prepare: SEEK, requireOverlay: true },
  { name: 'review-letterbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'letterbox', prepare: SEEK, requireOverlay: true },
  { name: 'review-pillarbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'pillarbox', prepare: SEEK, requireOverlay: true },
  // The custom transport and the layer toggles that replaced the native
  // controls, captured over real footage. Playback itself is not asserted here:
  // a headless browser refuses programmatic play without a user gesture, and
  // the play/pause transition is covered by the component tests.
  { name: 'review-transport', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, expectText: ['Play', 'Start', 'Evidence', 'End', 'Speed', 'Bounding box', 'Trajectory'] },
  { name: 'review-zone-visit', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, requireOverlay: true, expectText: ['Loading bay', 'Scene revision 4'] },
  { name: 'review-multi-visit', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_MULTI_VISIT }, expectText: ['2 visits', '2s dwell against a 1s threshold'] },
  { name: 'review-overlap-2', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERLAP_2 } },
  { name: 'review-overlap-3', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERLAP_3 } },
  // More concurrent visits than the capped sub-rows, so the overflow rail
  // and its count are exercised rather than only reasoned about.
  { name: 'review-overlap-overflow', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERLAP_5 } },
  { name: 'review-crossing-atob', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, requireOverlay: true, expectText: ['Gate A', 'Inbound'] },
  { name: 'review-crossing-btoa', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, requireOverlay: true, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_CROSSING_BTOA }, expectText: ['Outbound'] },
  { name: 'review-dwell-stationary', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_DWELL_STATIONARY }, expectText: ['2 intervals'] },
  { name: 'review-dense-markers', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_DENSE_MARKERS }, expectText: ['5 crossings'] },
  // Geometry that cannot be loaded must not fall back to the active revision.
  { name: 'review-geometry-unavailable', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2500, footage: 'saturated', prepare: SEEK, api: { '/api/cameras/11111111-1111-7111-8111-111111111111/scene/revisions': 'unavailable' }, expectText: ['could not be loaded'] },
  { name: 'review-analytics-unavailable', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': SINGLE_SAMPLE_TRACK }, expectText: ['trajectory_too_short'] },
  { name: 'review-analytics-pending', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_ANALYTICS_PENDING }, expectText: ['has not been analysed yet'] },
  { name: 'review-analytics-stale', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_ANALYTICS_STALE }, expectText: ['earlier revision or engine'] },
  // Two separate runs of concurrency: the rail must aggregate each span on
  // its own terms rather than stating one total for the whole timeline.
  { name: 'review-overflow-spans', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SPANS } },
  // Nothing separates visits that begin at the same instant, so the span is
  // the only honest unit: one band, its own count, and a route to each visit.
  { name: 'review-overflow-same-start', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SAME_START } },
  // One overflowed visit singled out through the disclosure: the recovery path
  // is captured in the state it leaves the rail in, not only asserted.
  { name: 'review-overflow-selected', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SHOW_OVERFLOWED, prepareSettleMs: 900, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SAME_START } },
  // Five crossings at one millisecond: one destination, so one control — which
  // has to carry all five names or four of them become unreachable.
  { name: 'review-markers-same-offset', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_MARKERS_SAME_OFFSET }, expectText: ['5 crossings'] },
  // The directed diagonal line over letterboxed and pillarboxed footage: the
  // perpendicular is measured in projected space, where the operator sees it.
  { name: 'review-direction-letterbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'letterbox', prepare: SEEK, requireOverlay: true, expectText: ['Inbound', 'Outbound'] },
  { name: 'review-direction-pillarbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', settleMs: 2000, footage: 'pillarbox', prepare: SEEK, requireOverlay: true, expectText: ['Inbound', 'Outbound'] },
];
