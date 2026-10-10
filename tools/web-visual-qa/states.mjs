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
 * A state cannot weigh a finding: what a finding at a tier weighs is the
 * assertion manifest's to say (`manifest.mjs`). The pre-v2 `knownIssues`
 * downgrade list is gone for that reason. `tierPolicy` says at which support
 * tiers the state is swept, and a policy that leaves a tier out says why;
 * `probeWidths` adds special non-anchor widths; `holds: 'loading'` marks a state
 * whose loading presentation is the state.
 *
 * `interaction` names the operator action a state's `prepare` performs, where
 * it is one — a click, a submit, a key press — and only then is the
 * preparation measured as the state's first interaction (P1 long tasks) — from
 * `window.__vqa.mark('interaction-start')`, which a preparation of several
 * steps sets immediately before the one action it names, or else from the
 * preparation's start. A
 * loading presentation any preparation starts is measured for CLS either way,
 * apart from the navigation's, and labelled with it. A preparation without it is fixture
 * setup or verification (a programmatic seek, a page-clock advance, scripted
 * field values, a condition check) and its long tasks are not-applicable.
 *
 * `expectText` / `forbidText` make a state prove it rendered what it claims,
 * and are part of what it settles on (V3): an unavailable state is reached when
 * its unavailable text is shown — after the query client's one retry — not
 * after a guessed delay, so a slow retry can never turn an "unavailable" check
 * into a second loading check.
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

import { readFileSync } from 'node:fs';

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

/**
 * A full first page, as real data returns it: 24 rows and a continuation. Seven
 * rows fit on screen, and the list scrolls past the rest. Every row carries a
 * `.visually-hidden` label (`position: absolute`), so the list must be their
 * containing block. Otherwise each label resolves against the page, escapes the
 * list's clip and makes the *page* scroll: on the Development machine the
 * document grew to about twice the viewport, with the shell scrolling away
 * beneath empty space. One Track never showed it.
 */
const FULL_PAGE = {
  items: Array.from({ length: 24 }, (_, index) => ({
    ...LONG_NAME_TRACKS.items[0],
    id: `70000000-0000-7000-8000-${String(index).padStart(12, '0')}`,
  })),
  nextCursor: 'opaque-cursor',
  totalCount: 48,
};

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
/**
 * T1 (§25 Tier B, 768-1100): the Investigation's filter rail is a drawer the
 * results header opens. A preparation that works in the rail opens it first;
 * where the rail is in place (no toggle) this is nothing. Waits on the drawer's
 * own modal state, never on a guessed duration (V3).
 */
const OPEN_FILTERS = `(async () => {
  const toggle = document.querySelector('.workspace__rail-toggle');
  if (!toggle || toggle.getAttribute('aria-expanded') === 'true') return true;
  toggle.focus();
  toggle.click();
  const end = performance.now() + 8000;
  while (performance.now() < end) {
    if (document.querySelector('.workspace__rail[role="dialog"][aria-modal="true"]')) return true;
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
  }
  throw new Error('preparation timed out after 8000ms waiting for the filters drawer to open');
})()`;

const PICK_CAMERA_IN_RAIL = `(() => {
  const select = Array.from(document.querySelectorAll('select'))
    .find((element) => element.labels?.[0]?.textContent.trim() === 'Camera');
  if (!select || !Array.from(select.options).some((option) => option.value === '${CAM}')) return false;
  const set = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  set.call(select, '${CAM}');
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()`;
const PICK_CAMERA = `(async () => { await ${OPEN_FILTERS}; return ${PICK_CAMERA_IN_RAIL}; })()`;

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
const REFUSE_FIELDS_IN_RAIL = `(() => {
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
const REFUSE_FIELDS = `(async () => { await ${OPEN_FILTERS}; return ${REFUSE_FIELDS_IN_RAIL}; })()`;

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
 * The wait a preparation uses between an action and its consequence (V3).
 *
 * A preparation never sleeps for a guessed duration: after each action it
 * waits for the observable result of that action, polled once per animation
 * frame, and fails with what it was waiting for if that never arrives. A
 * timeout is a failure, not a settle — the harness then refuses the capture.
 */
const UNTIL = `const until = async (predicate, what, timeout = 8000) => {
    const end = performance.now() + timeout;
    while (performance.now() < end) {
      try { const value = await predicate(); if (value) return value; } catch { /* not yet */ }
      await new Promise((resolve) => requestAnimationFrame(() => resolve()));
    }
    throw new Error('preparation timed out after ' + timeout + 'ms waiting for ' + what);
  };`;

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
  ${UNTIL}
  const object = document.querySelector('.scene-navigator__name');
  if (!object) return false;
  object.click();
  const field = await until(() => Array.from(document.querySelectorAll('input')).find((i) => {
    const label = i.labels && i.labels[0];
    return label && label.textContent.trim() === 'Name';
  }), 'the Name field of the selected object');
  // Through the native setter, so React sees a real change rather than a
  // value assignment it never hears about.
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  // The measured interaction is the rename; selecting the object sets it up.
  window.__vqa.mark('interaction-start');
  setter.call(field, 'A considerably longer zone name');
  field.dispatchEvent(new Event('input', { bubbles: true }));
  return Boolean(await until(() => document.querySelector('.scene-context__note input'), 'the revision note field of a dirty draft'));
})()`;

/**
 * S1c: the Scene Editor's two consequential decisions, reached through the real
 * controls. Each is the product's Dialog (§15) over a dirty draft; the prepare
 * step fails unless the dialog is actually open.
 */
const clickButton = (label) => `Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === ${JSON.stringify(label)})`;
const DISCARD_DIALOG = `(async () => {
  ${UNTIL}
  if (!(await ${DIRTY_SCENE})) return false;
  const reset = ${clickButton('Reset')};
  if (!reset) return false;
  // An operator's click focuses the button, which is the Dialog's invoker.
  reset.focus();
  window.__vqa.mark('interaction-start');
  reset.click();
  return Boolean(await until(() => document.querySelector('[role="dialog"][aria-modal="true"]'), 'the discard Dialog'));
})()`;
const RELOAD_DIALOG = `(async () => {
  ${UNTIL}
  if (!(await ${DIRTY_SCENE})) return false;
  const save = ${clickButton('Save revision')};
  if (!save) return false;
  save.click();
  // The fixture answers the save with a 409; the conflict offers the reload.
  const reload = await until(() => ${clickButton('Reload active revision')}, 'the Reload active revision action of the conflict');
  reload.focus();
  window.__vqa.mark('interaction-start');
  reload.click();
  return Boolean(await until(() => document.querySelector('[role="dialog"][aria-modal="true"]'), 'the reload Dialog'));
})()`;

/** The Workbench inspector opened as the 1101-1149 overlay drawer (§4.3.1, §20). */
const OPEN_WORKBENCH_DRAWER = `(async () => {
  ${UNTIL}
  const toggle = document.querySelector('.workspace__drawer-toggle');
  if (!toggle) return false;
  toggle.focus();
  toggle.click();
  return Boolean(await until(() => {
    const drawer = document.querySelector('.workspace__inspector[role="dialog"][aria-modal="true"]');
    return drawer && drawer.contains(document.activeElement) && document.querySelector('.workspace__stage[inert]') && document.querySelector('.workspace__band[inert]')
      // Every region beside the drawer, the revision footer included (Codex P2 on #184).
      && Array.from(document.querySelectorAll('.workspace__footer, .workspace__notices')).every((region) => region.hasAttribute('inert'));
  }, 'the drawer open, holding focus, over an inert workspace'));
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
  ${UNTIL}
  const byName = (name) => Array.from(document.querySelectorAll('button'))
    .find((b) => new RegExp(name).test((b.textContent || '').trim()));

  // Open the revision strip, which is a real footer band on this surface.
  const revisions = byName('^Revisions$');
  if (!revisions) return false;
  revisions.click();

  await until(() => document.querySelector('.workspace__footer'), 'the open revision strip');
  // Open a past revision whose fetch is answered 503. R4: its failure is said
  // on the stage it would have filled, with its retry, not as a third notice
  // stacked above the workspace.
  // (Until R4 this looked for a button whose text began "View revision", which
  // no chip's does — its number leads — so no past revision was ever opened.)
  const view = await until(() => document.querySelector('.scene-revisions__chip:not(.is-active)'), 'a past revision in the open strip');
  view.click();
  return Boolean(await until(() => document.querySelector('.scene-stage__state .alert button'),
    'the unavailable past revision, with its retry, on the stage'));
})()`;


/** Open the Ledger's create region the way an operator does. */
const OPEN_CAMERA_FORM = `(async () => {
  ${UNTIL}
  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  return Boolean(await until(() => document.querySelector('form[aria-label="Add camera"]'), 'the create region'));
})()`;

/** Open it and submit nothing, which is three field-level refusals at once. */
const INVALID_CAMERA_FORM = `(async () => {
  ${UNTIL}
  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  const form = await until(() => document.querySelector('form[aria-label="Add camera"]'), 'the create region');
  const submit = form.querySelector('button[type="submit"]');
  if (!submit) return false;
  window.__vqa.mark('interaction-start');
  submit.click();
  return Boolean(await until(() => document.querySelector('.field__error'), 'the field-level refusals'));
})()`;

/**
 * Reach the duplicate-code conflict through the real form and the real 409,
 * so the state is the one the server produces rather than a simulation of it.
 */
const CONFLICTED_CAMERA_FORM = `(async () => {
  ${UNTIL}
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const type = (input, value) => { setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); };

  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  const form = await until(() => document.querySelector('form[aria-label="Add camera"]'), 'the create region');
  const inputs = Array.from(form.querySelectorAll('input'));
  if (inputs.length < 2) return false;
  type(inputs[0], 'CAM-01');
  type(inputs[1], 'Duplicate of the north gate');
  // The timezone too: it defaults from the system configuration, and a submit
  // before that arrives is refused locally (no zone) and never reaches the 409.
  await until(() => inputs[0].value === 'CAM-01' && inputs[1].value === 'Duplicate of the north gate' && inputs[2] && inputs[2].value, 'the typed draft and the default timezone');
  window.__vqa.mark('interaction-start');
  form.querySelector('button[type="submit"]').click();
  return Boolean(await until(() => document.querySelector('.field__error'), 'the 409 conflict on the Code field'));
})()`;

/** Submit the import form empty: every field refuses, inline (§21). */
const SUBMIT_EMPTY_IMPORT = `(async () => {
  ${UNTIL}
  const submit = Array.from(document.querySelectorAll('button')).find((b) => /Import and process/.test(b.textContent || ''));
  if (!submit) return false;
  submit.click();
  return Boolean(await until(() => document.querySelectorAll('.field__error').length >= 3, 'three field-level refusals'));
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

/**
 * M1: Cameras at its longest *valid* identities (Camera.Create: code 32, name
 * 128; the zone a recognised IANA id) — the widest 32-character code, a
 * realistic one, a 128-character name in two scripts, the longest IANA zones —
 * with a short row and an inactive one. Uncapped, the widest valid code clipped
 * the row actions out of view at 1366 (cameras.actions-in-view).
 */
const camerasRow = (index, code, name, timeZoneId, isActive = true) => ({
  id: `cccccccc-0000-7000-8000-${String(index).padStart(12, '0')}`, code, name, description: null, locationName: null,
  timeZoneId, isActive, createdAtUtc: '2026-09-01T04:00:00Z', updatedAtUtc: '2026-09-01T04:00:00Z',
});
const LONG_CAMERAS = [
  camerasRow(1, 'C1', 'Gate', 'UTC'),
  camerasRow(2, 'W'.repeat(32), 'Widest valid code', 'Asia/Kolkata'),
  camerasRow(5, 'SOUTH-DOCK-LOADING-BAY-EAST-0007', 'Short', 'Asia/Kolkata'),
  camerasRow(3, 'CAM-03', 'Périmètre sud-ouest — clôture extérieure, accès véhicules et piétons, caméra thermique nº 3 près du poste de garde principal Est'.slice(0, 128), 'America/Argentina/ComodRivadavia', false),
  camerasRow(4, 'CAM-04', '北门 车辆入口 主通道 摄像机 第四号 长名称测试 用于截断检查 北门 车辆入口 主通道', 'America/North_Dakota/New_Salem'),
];
const CAMERAS = JSON.parse(readFileSync(new URL('./fixtures/cameras.json', import.meta.url), 'utf8'));

/**
 * Open the Add camera form, type a code and a name, and submit — once the
 * timezone holds its deployment default (or, with `withoutZone`, once the
 * configuration has visibly failed), so the submit is the one the state means.
 */
const SUBMIT_CAMERA = (code, name, until, { withoutZone = false } = {}) => `(async () => {
  ${UNTIL}
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  const type = (input, value) => { setter.call(input, value); input.dispatchEvent(new Event('input', { bubbles: true })); };
  const add = Array.from(document.querySelectorAll('button')).find((b) => /^Add camera$/.test((b.textContent || '').trim()));
  if (!add) return false;
  add.click();
  const form = await until(() => document.querySelector('form[aria-label="Add camera"]'), 'the create region');
  const inputs = Array.from(form.querySelectorAll('input'));
  type(inputs[0], ${JSON.stringify(code)});
  type(inputs[1], ${JSON.stringify(name)});
  await until(() => inputs[0].value === ${JSON.stringify(code)} && inputs[1].value === ${JSON.stringify(name)}
    && (${withoutZone} ? /deployment timezone could not be read/.test(form.innerText) : inputs[2].value), 'the typed draft');
  window.__vqa.mark('interaction-start');
  form.querySelector('button[type="submit"]').click();
  return Boolean(await until(() => ${until}, 'the answer to the submit'));
})()`;

/**
 * M3: fill the Import form as an operator does — a camera, a wall time and an
 * MP4 (through the native file input, by a DataTransfer) — then optionally
 * submit, and wait for what the state names.
 */
const FILL_IMPORT = ({ cameraValue, fileName, submit = false, until }) => `(async () => {
  ${UNTIL}
  const select = await until(() => {
    const s = document.querySelector('form select');
    return s && s.querySelector('option[value="${cameraValue}"]') ? s : null;
  }, 'the active camera option');
  const set = (element, value) => {
    const proto = Object.getPrototypeOf(element);
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(element, value);
    element.dispatchEvent(new Event(element.tagName === 'SELECT' ? 'change' : 'input', { bubbles: true }));
  };
  set(select, ${JSON.stringify(cameraValue)});
  set(document.querySelector('input[type="datetime-local"]'), '2026-09-14T08:30');
  const file = document.querySelector('input[type="file"]');
  const transfer = new DataTransfer();
  transfer.items.add(new File(['mp4'], ${JSON.stringify(fileName)}, { type: 'video/mp4' }));
  file.files = transfer.files;
  file.dispatchEvent(new Event('change', { bubbles: true }));
  await until(() => document.querySelector('.file-input__name:not([data-empty])'), 'the chosen file named');
  ${submit ? "window.__vqa.mark('interaction-start'); document.querySelector('form button[type=submit]').click();" : ''}
  return Boolean(await until(() => ${until}, 'the state'));
})()`;

/** M2: the wide stack processing-queue-row-degraded-wide-font applies (test pressure, not product CSS). */
const QUEUE_WIDE_FONT = 'Verdana, "DejaVu Sans", sans-serif';

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

/**
 * The default sweep: every tier anchor of §25, exactly as frozen (§26 as
 * amended, register V2). A state is swept at every anchor of every tier its
 * policy applies to.
 */
export const ANCHORS = [
  { width: 1366, height: 768, tier: 'A' },
  { width: 1440, height: 900, tier: 'A' },
  { width: 1920, height: 1080, tier: 'A' },
  { width: 2560, height: 1080, tier: 'A' },
  { width: 2560, height: 1440, tier: 'A' },
  { width: 1024, height: 768, tier: 'B' },
  { width: 768, height: 1024, tier: 'B' },
  { width: 430, height: 932, tier: 'C' },
  { width: 390, height: 844, tier: 'C' },
].map((anchor) => ({ ...anchor, label: `${anchor.width}x${anchor.height}` }));

/** The support tier a width falls in (§25); below 390 nothing is asserted. */
export function tierOf(width) {
  if (width >= 1366) return 'A';
  if (width >= 768) return 'B';
  if (width >= 390) return 'C';
  return null;
}

/**
 * Tier applicability, by policy (V2). A state applies at every tier unless it
 * names one of these policies, and a policy that leaves a tier out says why —
 * so a tier can be absent from a state only for a stated, reviewable reason,
 * never because the state happens to render badly there. Applicability is
 * not severity: what a finding at an applicable tier weighs is the manifest's
 * to say, and no state can change it.
 */
export const TIER_POLICIES = {
  'all-tiers': {
    tiers: ['A', 'B', 'C'],
    excluded: {},
  },
  'footage-variant': {
    // T2: swept at Tier C too — the narrow Review is for reading evidence, and
    // bright, dark, letterboxed and pillarboxed footage is what it reads.
    tiers: ['A', 'C'],
    excluded: {
      B: 'a footage-condition variant (§26 media conditions): it differs from the canonical review state only in the video\'s pixels, '
        + 'so its Tier B geometry is the review state\'s, which is swept there',
    },
  },
  'workbench-variant': {
    tiers: ['A', 'B'],
    excluded: {
      C: 'a Workbench editing or analytical variant: below 768px the Workbench is its §25 unsupported state — no canvas, chart, '
        + 'inspector or analytical question exists to put in this state — and §26 has the base state assert that state at Tier C',
    },
  },
  'grid-variant': {
    tiers: ['A', 'B'],
    excluded: {
      C: 'a grid-view variant: grid view is unavailable at Tier C (§25); search-grid proves there that a stored grid choice is shown as the list',
    },
  },
  'typography-variant': {
    tiers: ['A'],
    excluded: {
      B: 'a typography variant: it exists where a wide platform font pressures a measured Tier A width, which its preparation proves '
        + 'from rendered widths and refuses to fake; at Tier B the same element has the room (the bucket table heading: 76px of text '
        + 'in 199px and 122px), and its Tier B geometry is its base state\'s, which is swept there',
      C: 'a typography variant: its Tier C geometry is its base state\'s, which is swept there',
    },
  },
  'workstation-interaction': {
    tiers: ['A'],
    excluded: {
      B: 'a workstation interaction: the rail\'s collapse choice exists at Tier A only — at Tier B (§25) the rail is collapsed by default and the same control opens it as an overlay, which shell-rail-overlay probes',
      C: 'a workstation interaction: at Tier C the rail is the §25 top-of-page menu (S5 / T2)',
    },
  },
  'breakpoint-probe': {
    tiers: [],
    excluded: {
      A: 'a breakpoint probe: it exists to settle a measured transition at its own probe widths, and its anchor geometry is its base state\'s',
      B: 'a breakpoint probe: swept only at its probe widths',
      C: 'a breakpoint probe: swept only at its probe widths',
    },
  },
};

/**
 * A video inventory for the Overview (R1) and the Videos Ledger (R2): the
 * video list and, for every video either surface looks up (failed, processed
 * and active ones), its processing status. Overrides match by path prefix, so
 * each looked-up video's `/processing` path must be answered here, or the
 * inventory's own override would answer it with the list. An entry may give
 * its own `lookup` (`'unavailable'`, a status), its run `phase` and `progress`,
 * and a `refresh` answer for every request after the first.
 */
const OVERVIEW_VIDEO = JSON.parse(readFileSync(new URL('./fixtures/videos.json', import.meta.url), 'utf8'))[0];
const OVERVIEW_CAM_2 = '33333333-3333-7333-8333-333333333333';
function inventoryFixture(entries) {
  const api = { '/api/videos': [] };
  entries.forEach((entry, index) => {
    const id = `0${(index + 1).toString(16).padStart(7, '0')}-0000-7000-8000-${String(index + 1).padStart(12, '0')}`;
    const importedAtUtc = new Date(Date.UTC(2026, 8, 14, 12) - index * 3_600_000).toISOString().replace('.000', '');
    api['/api/videos'].push({
      ...OVERVIEW_VIDEO, id, originalFileName: entry.name, cameraId: entry.camera ?? OVERVIEW_VIDEO.cameraId,
      processingStatus: entry.status, importedAtUtc,
    });
    if (entry.status !== 'NotQueued') {
      const failed = entry.status === 'Failed';
      const active = entry.status === 'Queued' || entry.status === 'Processing';
      const lookup = entry.lookup ?? {
        videoStatus: entry.status,
        latestRun: {
          processingRunId: id.replace(/^0/, 'a'), status: failed ? 'Failed' : active ? (entry.status === 'Queued' ? 'Queued' : 'Running') : 'Completed',
          pipeline: 'deepstream-yolo-bytetrack', pipelineVersion: '1.0.0', workerId: entry.status === 'Queued' ? null : 'worker-01',
          queuedAtUtc: importedAtUtc, startedAtUtc: entry.status === 'Queued' ? null : importedAtUtc, completedAtUtc: active ? null : importedAtUtc,
          progressPercent: entry.progress ?? (failed ? 42 : active ? 0 : 100), attemptCount: failed ? 3 : 1,
          failureCode: failed ? (entry.code ?? 'vision_job_attempts_exhausted') : null,
          framesProcessed: 15000, tracksCreated: failed || active ? 0 : 6, analyticsReadiness: entry.readiness ?? (failed ? 'NotConfigured' : 'Ready'),
          phase: entry.phase ?? (failed ? 'failed' : active ? (entry.status === 'Queued' ? 'queued' : 'processing') : 'completed'),
        },
      };
      // `refresh`: what every later request answers — a refresh that fails
      // after the first answer leaves the row with retained, degraded detail.
      api[`/api/videos/${id}/processing`] = entry.refresh ? { sequence: [lookup, entry.refresh] } : lookup;
    }
  });
  return api;
}

/** The keys a state may carry. Nothing here can name or change a severity. */
export const STATE_KEYS = new Set([
  'name', 'path', 'fullWidth', 'archetype', 'api', 'prepare', 'expectText', 'forbidText',
  'footage', 'requireOverlay', 'holds', 'tierPolicy', 'probeWidths', 'probeOf', 'interaction',
  // T2: how a state is reached, and what it shows, at one tier; and a stored
  // preference it arrives with.
  'atTier', 'storage',
]);

/**
 * The visual-QA Track's Evidence Set and its compatibility Representative, as
 * the base Track-detail fixture carries them (S1.3b). The analytics fixtures
 * below restate the same Track, so they carry the same evidence.
 */
const TRACK_EVIDENCE = (() => {
  const { representative, observations } = JSON.parse(
    readFileSync(new URL('./fixtures/tracks_55555550-5555-7555-8555-555555555550.json', import.meta.url), 'utf8'),
  );
  return { representative, observations };
})();

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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
  "representative": TRACK_EVIDENCE.representative,
  "observations": TRACK_EVIDENCE.observations,
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
/**
 * Seek to the evidence, then step the dense-evidence navigator.
 *
 * The navigator is the only route to a visit the capped sub-rows could not
 * hold, and it exposes one member at a time, so the captured state is reached
 * the way an operator reaches it: open the disclosure, then step.
 */
function stepDenseEvidence(steps) {
  return `(async () => {
  ${UNTIL}
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
  const next = await until(() => Array.from(disclosure.querySelectorAll('button'))
    .find((b) => (b.textContent || '').trim() === 'Next'), 'the dense-evidence navigator');
  const status = () => (disclosure.querySelector('.evidence-timeline__navigator-status')?.textContent || '').trim();
  for (let step = 0; step < ${steps}; step += 1) {
    if (next.disabled) break;
    const before = status();
    next.click();
    await until(() => status() !== before, 'the navigator to announce the next member');
  }
  return Boolean(await until(() => document.querySelector('[data-shown="true"]'), 'a singled-out overflowed visit'));
})()`;
}

const SHOW_OVERFLOWED = stepDenseEvidence(1);
const SHOW_OVERFLOWED_LATER = stepDenseEvidence(3);

/**
 * A bridging chain of overflowed visits, where grouping by transitive overlap
 * would claim a concurrency that never happened.
 *
 * Three long visits fill the capped sub-rows; A, B and C then overflow with
 * A overlapping B, B overlapping C and A never meeting C. The rail must show
 * the density rising and falling across the run rather than one flat "+3".
 */
const REVIEW_OVERFLOW_BRIDGING = {
  ...REVIEW_OVERLAP_5,
  analytics: {
    ...REVIEW_OVERLAP_5.analytics,
    zoneVisits: [
      ...[0, 1, 2].map((n) => ({
        ...REVIEW_OVERLAP_5.analytics.zoneVisits[n],
        visitIndex: n, entryOffsetMs: 600, exitOffsetMs: 3_400,
      })),
      { ...REVIEW_OVERLAP_5.analytics.zoneVisits[0], visitIndex: 3, entryOffsetMs: 700, exitOffsetMs: 1_700 },
      { ...REVIEW_OVERLAP_5.analytics.zoneVisits[1], visitIndex: 4, entryOffsetMs: 1_200, exitOffsetMs: 2_200 },
      { ...REVIEW_OVERLAP_5.analytics.zoneVisits[0], visitIndex: 5, entryOffsetMs: 2_100, exitOffsetMs: 3_000 },
    ],
  },
};

/** A hundred concurrent visits: the control count must not notice. */
const REVIEW_OVERFLOW_CROWD = {
  ...REVIEW_OVERLAP_5,
  analytics: {
    ...REVIEW_OVERLAP_5.analytics,
    zoneVisits: Array.from({ length: 100 }, (_, n) => ({
      ...REVIEW_OVERLAP_5.analytics.zoneVisits[n % 2],
      visitIndex: n,
      entryOffsetMs: 600 + n * 10,
      exitOffsetMs: 3_400,
    })),
  },
};

/*
 * Slice 7 acceptance: the two states the Stage-1 matrix still lacked. Both are
 * derived from served fixtures, so each changes exactly one thing.
 */
const BASE_HEATMAP = JSON.parse(
  readFileSync(new URL(`./fixtures/cameras_${CAM}_analytics_heatmap.json`, import.meta.url), 'utf8'),
);

/**
 * One Track's worth of samples in a 64 × 36 grid: three lit cells in a dark
 * matrix. The sparse end of the scale is where a relative colour ramp is most
 * likely to over-state a handful of samples, so its legend and summary must
 * still read as counts.
 */
const SPARSE_HEATMAP = (() => {
  const values = BASE_HEATMAP.values.map(() => 0);
  values[10 * 64 + 12] = 3;
  values[10 * 64 + 13] = 7;
  values[11 * 64 + 13] = 1;
  return {
    ...BASE_HEATMAP,
    coverage: { ...BASE_HEATMAP.coverage, evaluatedRuns: 1, analysedTracks: 1 },
    sampleCount: 11,
    trackCount: 1,
    maxCellValue: 7,
    values,
  };
})();

const BASE_TRACK_DETAIL = JSON.parse(
  readFileSync(new URL(`./fixtures/tracks_${TRACK}.json`, import.meta.url), 'utf8'),
);
/*
 * S1.3b Evidence Set variants of the one visual-QA Track. The base fixture
 * carries the full four-role v3 set; these reduce it to the other shapes the
 * strip must hold without an error or a layout shift.
 */
const EVIDENCE_REPRESENTATIVE_ONLY = {
  ...BASE_TRACK_DETAIL,
  observations: BASE_TRACK_DETAIL.observations.slice(0, 1),
};

/** Near view's crop names an artifact the harness cannot serve: a 404 in the browser. */
const EVIDENCE_CROP_UNAVAILABLE = {
  ...BASE_TRACK_DETAIL,
  observations: BASE_TRACK_DETAIL.observations.map((observation) => (observation.evidenceRole === 'NearView'
    ? {
      ...observation,
      evidenceArtifactId: 'eeeeeee9-eeee-7eee-8eee-eeeeeeeeeee9',
      evidenceContentUrl: '/api/artifacts/eeeeeee9-eeee-7eee-8eee-eeeeeeeeeee9/content',
    }
    : observation)),
};

/**
 * The crop request the unavailable state asks to fail, declared as an override
 * so the harness reports it as the requested failure and nothing else.
 */
const UNAVAILABLE_CROP = {
  '/api/artifacts/eeeeeee9-eeee-7eee-8eee-eeeeeeeeeee9/content':
    { status: 404, body: { status: 404, code: 'artifact_not_found', detail: 'Artifact content was not found.' } },
};

/** The legacy shape: no Representative relation, no Evidence Set. */
const EVIDENCE_LEGACY = { ...BASE_TRACK_DETAIL, representative: null, observations: [] };

/** Inspect a supplemental crop through its own control, as an operator would. */
const INSPECT_LATE_DIVERSE = `(() => {
  const control = Array.from(document.querySelectorAll('.evidence-set__control'))
    .find((button) => (button.getAttribute('aria-label') || '').startsWith('Late diverse'));
  if (!control) return false;
  control.click();
  return true;
})()`;


const BASE_REVISION = JSON.parse(
  readFileSync(new URL(`./fixtures/cameras_${CAM}_scene_revisions_4.json`, import.meta.url), 'utf8'),
);
const HISTORICAL_REVISION_ID = '66666666-6666-7666-8666-666666666663';

/** Revision 3, the one the historical facts were measured against. */
const HISTORICAL_REVISION = {
  ...BASE_REVISION,
  revisionId: HISTORICAL_REVISION_ID,
  revisionNumber: 3,
};

/**
 * The same Track read against revision 3 while revision 4 is active — the
 * detail an operator reaches from a historical search. It must be named as
 * revision 3's facts and must name revision 4 as the other identity, never
 * present revision 3's facts under revision 4's name.
 */
const HISTORICAL_TRACK_DETAIL = {
  ...BASE_TRACK_DETAIL,
  analytics: {
    ...BASE_TRACK_DETAIL.analytics,
    sceneRevisionId: HISTORICAL_REVISION_ID,
    sceneRevisionNumber: 3,
    otherIdentities: [{
      sceneRevisionId: BASE_TRACK_DETAIL.analytics.sceneRevisionId,
      sceneRevisionNumber: 4,
      algorithmVersion: BASE_TRACK_DETAIL.analytics.algorithmVersion,
      unitStatus: 'Completed',
      outcome: 'Analysed',
    }],
  },
};

/*
 * The three aggregate answers that are not "here are the figures". They are
 * derived from the served fixture so they cannot drift from it, and each
 * changes exactly one thing about it.
 */
const BASE_AGGREGATES = JSON.parse(
  readFileSync(new URL(`./fixtures/cameras_${CAM}_analytics_aggregates.json`, import.meta.url), 'utf8'),
);

/** Runs still queued: the surface must withhold the figures, not show zeros. */
const INCOMPLETE_AGGREGATES = {
  ...BASE_AGGREGATES,
  coverage: { ...BASE_AGGREGATES.coverage, evaluatedRuns: 4, pendingRuns: 2, complete: false },
};

/** Everything analysed, and nothing happened. A real observation. */
const ZERO_AGGREGATES = {
  ...BASE_AGGREGATES,
  coverage: { ...BASE_AGGREGATES.coverage, analysedTracks: 0 },
  zones: [],
  lines: [],
  classes: [{
    objectClass: 'Person',
    counts: BASE_AGGREGATES.buckets.map(() => 0),
    windowDistinctTrackCount: 0,
  }],
};

/** No geometry to count against at all. */
const NO_SCENE_AGGREGATES = {
  ...BASE_AGGREGATES,
  sceneRevisionId: null,
  sceneRevisionNumber: null,
  coverage: {
    ...BASE_AGGREGATES.coverage,
    sceneRevisionId: null,
    evaluatedRuns: 0,
    notConfiguredRuns: 6,
    analysedTracks: 0,
    complete: false,
  },
  zones: [],
  lines: [],
  classes: [],
};

/** M4 (F25): every run's analytics disabled by the scene revision in force. */
const DISABLED_AGGREGATES = {
  ...BASE_AGGREGATES,
  coverage: { ...BASE_AGGREGATES.coverage, evaluatedRuns: 0, disabledRuns: 6, analysedTracks: 0, complete: false },
  zones: [],
  lines: [],
  classes: [],
};

/**
 * M4 (Codex P1): a window with no runs under a revision that disables
 * analytics. The server then counts no disabled run and the coverage reads
 * complete; only the scene says the revision is disabled, so the scene answer
 * names the aggregate's resolved revision with analytics off.
 */
const EMPTY_WINDOW_AGGREGATES = {
  ...ZERO_AGGREGATES,
  coverage: { ...ZERO_AGGREGATES.coverage, evaluatedRuns: 0, pendingRuns: 0, failedRuns: 0, notConfiguredRuns: 0, disabledRuns: 0, staleRuns: 0, analysedTracks: 0, unavailableTracks: 0, complete: true },
};
const DISABLED_SCENE = (() => {
  const scene = JSON.parse(readFileSync(new URL(`./fixtures/cameras_${CAM}_scene.json`, import.meta.url), 'utf8'));
  return {
    ...scene,
    history: [
      { ...scene.history[0], revisionId: BASE_AGGREGATES.sceneRevisionId, analyticsEnabled: false, zoneCount: 0, tripLineCount: 0 },
      ...scene.history.slice(1),
    ],
  };
})();

/** Cold review F1: the same empty window, its revision listed as enabling analytics. */
const ENABLED_SCENE = {
  ...DISABLED_SCENE,
  history: DISABLED_SCENE.history.map((revision, index) => (index === 0 ? { ...revision, analyticsEnabled: true, zoneCount: 1 } : revision)),
};

/** Cold review F1: the heatmap's empty window, whose revision only the scene can confirm. */
const EMPTY_WINDOW_HEATMAP = {
  ...BASE_HEATMAP,
  sceneRevisionId: BASE_AGGREGATES.sceneRevisionId,
  coverage: { ...BASE_HEATMAP.coverage, sceneRevisionId: BASE_AGGREGATES.sceneRevisionId, evaluatedRuns: 0, pendingRuns: 0, failedRuns: 0, notConfiguredRuns: 0, disabledRuns: 0, staleRuns: 0, analysedTracks: 0, unavailableTracks: 0, complete: true },
  sampleCount: 0,
  trackCount: 0,
  maxCellValue: 0,
  values: BASE_HEATMAP.values.map(() => 0),
};

/**
 * Cold review F2: From emptied over a valid window. The committed window still
 * stands behind it, and must be neither shown as the answer nor asked again.
 */
const EMPTY_FROM = `(async () => {
  ${UNTIL}
  const field = await until(() => Array.from(document.querySelectorAll('input')).find((input) => input.labels && Array.from(input.labels).some((label) => label.textContent.trim() === 'From')), 'the From field');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(field, '');
  field.dispatchEvent(new Event('input', { bubbles: true }));
  await until(() => field.getAttribute('aria-invalid') === 'true', 'From marked invalid');
  const refresh = Array.from(document.querySelectorAll('button')).find((button) => /Refresh/.test(button.textContent));
  return Boolean(refresh && refresh.disabled);
})()`;

/** M4 (F25): the heatmap's answer for a camera with no scene. */
const NO_SCENE_HEATMAP = {
  ...BASE_HEATMAP,
  sceneRevisionId: null,
  sceneRevisionNumber: null,
  coverage: {
    ...BASE_HEATMAP.coverage, sceneRevisionId: null, evaluatedRuns: 0, notConfiguredRuns: 6, analysedTracks: 0, complete: false,
  },
  sampleCount: 0,
  trackCount: 0,
  maxCellValue: 0,
  values: BASE_HEATMAP.values.map(() => 0),
};

/**
 * M4 (F24): the bucket table scrolled under its own header, and the geometry
 * that says it is read correctly there — measured, not inferred from a
 * declared `position`.
 *
 * The 96 buckets of the served day are scrolled until a dozen rows have
 * passed under the header. Then every body row's header must sit on its own
 * row (a row label pinned to the top of the scroller names a different row
 * from the figures beside it), and the hit test at the column header's centre
 * and at the first row clear of it must land on that header and on that row's
 * own label — nothing painted over either.
 */
const SCROLL_BUCKET_TABLE = `(async () => {
  ${UNTIL}
  const table = await until(() => document.querySelector('.analytics-table'), 'the bucket table');
  const rows = Array.from(table.querySelectorAll('tbody tr'));
  if (rows.length < 40) return false;
  let scroller = table.parentElement;
  while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 1 && /(auto|scroll)/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
  scroller = scroller || document.scrollingElement;
  const top = () => (scroller === document.scrollingElement ? 0 : scroller.getBoundingClientRect().top);
  scroller.scrollTop += rows[12].getBoundingClientRect().top - top();
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  if (rows[0].getBoundingClientRect().bottom > top()) return false;
  for (const row of rows) {
    const label = row.querySelector('th').getBoundingClientRect();
    const figure = row.querySelector('td').getBoundingClientRect();
    if (Math.abs(label.top - figure.top) > 1) return false;
  }
  const head = table.querySelector('thead th').getBoundingClientRect();
  const atHead = document.elementFromPoint(head.left + head.width / 2, head.top + head.height / 2);
  if (!atHead || atHead.closest('thead') !== table.tHead) return false;
  const clear = rows.find((row) => row.getBoundingClientRect().top >= head.bottom);
  if (!clear) return false;
  const label = clear.querySelector('th');
  const box = label.getBoundingClientRect();
  const atRow = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
  return Boolean(atRow && label.contains(atRow));
})()`;

/**
 * M4 (F22): a one-minute interval over the served day — 1,440 buckets against
 * a bound of 512. The refusal must be on the Interval field (invalid, and
 * described by the message), and Refresh disabled with its reason.
 */
const REFUSE_WINDOW = `(async () => {
  ${UNTIL}
  const select = await until(() => Array.from(document.querySelectorAll('select'))
    .find((candidate) => Array.from(candidate.options).some((option) => option.value === '60')), 'the interval field');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(select, '60');
  select.dispatchEvent(new Event('change', { bubbles: true }));
  await until(() => select.getAttribute('aria-invalid') === 'true', 'the interval marked invalid');
  const described = document.getElementById(select.getAttribute('aria-describedby') || '');
  if (!described || !/the most that can be shown is 512/.test(described.textContent)) return false;
  const refresh = Array.from(document.querySelectorAll('button')).find((button) => /Refresh/.test(button.textContent));
  return Boolean(refresh && refresh.disabled && refresh.title);
})()`;

/** Arms the Heatmap mode, which is a click rather than a route. */
const HEATMAP_MODE = `(() => {
  const strip = document.querySelector('[aria-label="Analytics mode"]');
  const button = strip && Array.from(strip.querySelectorAll('button'))
    .find((candidate) => candidate.textContent.trim() === 'Heatmap');
  if (!button) return false;
  button.click();
  return true;
})()`;

/** Picks the zone occupancy metric, the one with a peak instant beside it. */
const LINE_METRIC = `(() => {
  const select = Array.from(document.querySelectorAll('select'))
    .find((candidate) => Array.from(candidate.options).some((option) => option.value === 'lineCrossings'));
  if (!select) return false;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(select, 'lineCrossings');
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()`;

const OCCUPANCY_METRIC = `(() => {
  const select = Array.from(document.querySelectorAll('select'))
    .find((candidate) => Array.from(candidate.options).some((option) => option.value === 'zoneOccupancy'));
  if (!select) return false;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
  setter.call(select, 'zoneOccupancy');
  select.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})()`;

/**
 * S1.4 B3 F4 plan §15.3: the asynchronous completion's operator states, as fixture data in
 * the shapes `GET /api/videos/{id}/processing` returns. `phase` is the truthful API field;
 * `status` stays `Running` while the platform finalizes (ProcessingRunStatus has no
 * Finalizing), which is why a UI that renders `status` alone shows Finalizing as Running.
 */
const FINALIZING_STATUS = {
  videoStatus: 'Processing',
  latestRun: {
    processingRunId: 'eeeeeeee-eeee-7eee-8eee-eeeeeeeeeeee',
    status: 'Running',
    pipeline: 'phase1-detection-tracking',
    pipelineVersion: 'phase1-v1',
    workerId: 'worker-a',
    queuedAtUtc: '2026-09-14T04:05:00Z',
    startedAtUtc: '2026-09-14T04:05:10Z',
    completedAtUtc: null,
    progressPercent: 100,
    attemptCount: 1,
    failureCode: null,
    framesProcessed: 0,
    tracksCreated: 0,
    analyticsReadiness: 'NotConfigured',
    phase: 'finalizing',
  },
};
const FAILED_FINALIZATION_STATUS = {
  videoStatus: 'Failed',
  latestRun: {
    ...FINALIZING_STATUS.latestRun,
    status: 'Failed',
    completedAtUtc: '2026-09-14T04:21:00Z',
    failureCode: 'vision_finalization_staging_missing',
    phase: 'failed',
  },
};

/** R3: the completed run of `VIDEO` and the running run of `LONG_VIDEO` (fixtures), for states that vary one thing. */
const R3_COMPLETED_STATUS = JSON.parse(readFileSync(new URL(`./fixtures/videos_${VIDEO}_processing.json`, import.meta.url), 'utf8'));
const R3_COMPLETED_RUN = R3_COMPLETED_STATUS.latestRun;
const R3_RUNNING_STATUS = JSON.parse(readFileSync(new URL(`./fixtures/videos_${LONG_VIDEO}_processing.json`, import.meta.url), 'utf8'));

/** R3: a completed run with the given analytics readiness, both endpoints agreeing. */
function r3Analytics(readiness, activeSceneRevisionId, units) {
  return {
    [`/api/videos/${VIDEO}/processing`]: { ...R3_COMPLETED_STATUS, latestRun: { ...R3_COMPLETED_RUN, analyticsReadiness: readiness } },
    [`/api/processing/runs/${R3_COMPLETED_RUN.processingRunId}/analytics`]: {
      processingRunId: R3_COMPLETED_RUN.processingRunId, readiness, activeSceneRevisionId, algorithmVersion: 'scene-analytics-v1',
      analyses: units.map((unit, index) => ({
        analysisId: `aaaaaaa${index + 1}-aaaa-7aaa-8aaa-aaaaaaaaaaa${index + 1}`, processingRunId: R3_COMPLETED_RUN.processingRunId,
        sceneRevisionId: REVISION, sceneRevisionNumber: 4, algorithmVersion: 'scene-analytics-v1', status: 'Completed', attemptCount: 1,
        queuedAtUtc: '2026-09-14T03:10:00Z', startedAtUtc: '2026-09-14T03:10:02Z', completedAtUtc: '2026-09-14T03:12:41Z',
        leaseExpiresAtUtc: null, analysedTrackCount: 5, unavailableTrackCount: 1, failureCode: null, ...unit,
      })),
    },
  };
}

/**
 * R3: the failed video under a long file name, on a camera with a long name,
 * run by a worker with a long identity — the values that stress the Context
 * Bar, the facts rail and the Diagnostics disclosure at once.
 */
const R3_FAILED_VIDEO_RECORD = JSON.parse(readFileSync(new URL(`./fixtures/videos_${FAILED_VIDEO}.json`, import.meta.url), 'utf8'));
const R3_FAILED_STATUS = JSON.parse(readFileSync(new URL(`./fixtures/videos_${FAILED_VIDEO}_processing.json`, import.meta.url), 'utf8'));
const R3_CAMERA = JSON.parse(readFileSync(new URL(`./fixtures/cameras_${CAM}.json`, import.meta.url), 'utf8'));
const R3_LONG_IDENTITY = {
  [`/api/videos/${FAILED_VIDEO}/processing`]: {
    ...R3_FAILED_STATUS,
    latestRun: { ...R3_FAILED_STATUS.latestRun, workerId: 'worker-gpu-node-17.site-recorder.local' },
  },
  [`/api/videos/${FAILED_VIDEO}`]: { ...R3_FAILED_VIDEO_RECORD, originalFileName: 'south-dock-2200-overnight-perimeter-recording-exported-from-site-recorder-channel-02.mp4' },
  [`/api/cameras/${CAM}`]: { ...R3_CAMERA, name: 'North Gate perimeter fence south-east approach (vehicle lane 2)' },
};

/** R4: the scene under the longest camera identity the domain permits (32-character code). */
const R4_LONG_CAMERA = {
  [`/api/cameras/${CAM}/scene`]: 'fixture',
  [`/api/cameras/${CAM}`]: {
    id: CAM, code: 'NORTH-PERIMETER-GATE-CAM-00042', name: 'North perimeter vehicle entrance, outer gate',
    description: null, locationName: null, timeZoneId: 'Asia/Kolkata', isActive: true,
    createdAtUtc: '2026-09-01T04:00:00Z', updatedAtUtc: '2026-09-01T04:00:00Z',
  },
};

/** R4: disable every object, then Save — the in-band confirmation, with the note field shown. */
const R4_CONFIRM_DISABLE = `(async () => {
  ${UNTIL}
  const objects = await until(() => {
    const found = Array.from(document.querySelectorAll('[aria-label="Scene objects"] .scene-navigator__name'));
    return found.length ? found : null;
  }, 'the scene objects');
  for (let index = 0; index < objects.length; index += 1) {
    const object = document.querySelectorAll('[aria-label="Scene objects"] .scene-navigator__name')[index];
    const name = object.querySelector('.truncate').textContent.trim();
    object.click();
    // The inspector names the object just selected before its control is used.
    await until(() => Array.from(document.querySelectorAll('.scene-inspector__head h3')).some((h) => h.textContent.trim() === name), 'the inspector showing ' + name);
    const box = await until(() => Array.from(document.querySelectorAll('label.checkbox')).find((l) => /^Evaluate this (zone|line)$/.test(l.textContent.trim())), 'the Enabled control of the selected object');
    const input = box.querySelector('input');
    if (input.checked) input.click();
  }
  const save = await until(() => Array.from(document.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Save revision' && !b.disabled), 'an enabled Save revision');
  save.focus();
  window.__vqa.mark('interaction-start');
  save.click();
  return Boolean(await until(() => Array.from(document.querySelectorAll('button')).some((b) => b.textContent.trim() === 'Save and disable analytics'), 'the in-band confirmation'));
})()`;

/** R4: the scene's camera (fixture), for states that vary one thing about it. */
const R4_CAMERA = JSON.parse(readFileSync(new URL(`./fixtures/cameras_${CAM}.json`, import.meta.url), 'utf8'));

/**
 * R6: more crossings and visits than Review lists inline (§37.1 large data,
 * N = 5), so the bounded lists and their closed "more" disclosures are
 * captured, and the sticky player is probed across a longer rail.
 */
const REVIEW_DENSE_FACTS = (() => {
  const analytics = REVIEW_MULTI_VISIT.analytics;
  const visit = analytics.zoneVisits[0];
  const crossing = analytics.lineCrossings[0];
  return {
    ...REVIEW_MULTI_VISIT,
    analytics: {
      ...analytics,
      zoneSummaries: [{ ...analytics.zoneSummaries[0], visitCount: 8, totalDwellMs: 1200, loitering: false, loiteringDwellMs: 0 }],
      zoneVisits: Array.from({ length: 8 }, (_, index) => ({
        ...visit, visitIndex: index, entryOffsetMs: 600 + index * 300, exitOffsetMs: 750 + index * 300, dwellMs: 150,
      })),
      lineCrossings: Array.from({ length: 9 }, (_, index) => ({
        ...crossing, crossingIndex: index, offsetMs: 700 + index * 300, direction: index % 2 ? 'bToA' : 'aToB',
      })),
    },
  };
})();

/** R6: identities at their longest — the crumb, the subject and the rail's camera row. */
const REVIEW_LONG_IDENTITY = {
  ...REVIEW_MULTI_VISIT,
  videoAssetId: LONG_VIDEO,
  objectClass: 'Motorcycle',
  localTrackNumber: 1248,
  camera: { ...REVIEW_MULTI_VISIT.camera, code: 'CAM-SOUTH-DOCK-LOADING-07', name: 'South Dock loading bay, east approach (service road)' },
};

/** R6: the run attestation behind Review's provenance disclosure, at its longest values. */
const RUN_ATTESTATION = {
  processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', videoAssetId: VIDEO, completedAtUtc: '2026-09-14T03:09:40Z',
  pipelineVersion: '1.4.0', modelId: 'rtmdet-m-coco', modelVersion: '1.2.0',
  modelManifestSha256: 'a'.repeat(64), checkpointSha256: '3f6c0e1b9a8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a291807f6e5d4c3b2a19087',
  resolvedConfigSha256: 'b'.repeat(64), pipelineProfileId: 'default-gpu', pipelineProfileVersion: '3', pipelineProfileSha256: 'c'.repeat(64),
  qualificationId: null, qualificationSha256: null, verificationStatus: 'verified',
  runtimeProfileId: 'cuda12-ort-1.19', runtimeProfileSha256: 'd'.repeat(64), runtimeVariant: 'win-x64-cuda12.4-cudnn9-onnxruntime-gpu-1.19.2',
  platformLockSha256: null, maviBuild: '0.1.0-dev', maviCommit: 'e9276a4790e1415131ed9fe3b1812d8aa2ff8632',
  configuredDevicePolicy: 'prefer-gpu', configuredDeviceIndex: 0, deviceResolutionReason: null, actualDevice: 'cuda:0',
  platform: { system: 'Windows', release: '11', version: '10.0.26200', machine: 'AMD64', processor: 'Intel64 Family 6', pythonVersion: '3.12.7', pythonImplementation: 'CPython', pythonBuild: ['main', 'Oct 1 2024'] },
  gpu: { name: 'NVIDIA RTX A4000 Laptop GPU', index: 0, vramBytes: 8589934592, driverVersion: '561.09', cudaRuntimeVersion: '12.4', uuid: 'GPU-00000000-0000-0000-0000-000000000000', pciBusId: '00000000:01:00.0', computeCapability: '8.6' },
  dependencyVersions: {}, detectorName: 'RTMDet', detectorVersion: '1.2.0', trackerName: 'ByteTrack', trackerVersion: '0.9.1',
  framesProcessed: 100, tracksCreated: 3, processingDurationMs: 41_000,
};

/** Open Review's two provenance disclosures, as an operator tracing the record would. */
const OPEN_PROVENANCE = `(async () => {
  ${UNTIL}
  const summaries = await until(() => {
    const found = ['Runtime attestation', 'Record detail'].map((label) => Array.from(document.querySelectorAll('summary')).find((s) => s.textContent.trim() === label));
    return found.every(Boolean) ? found : null;
  }, 'the provenance disclosures');
  window.__vqa.mark('interaction-start');
  for (const summary of summaries) summary.click();
  return Boolean(await until(() => /Verification/.test(document.body.innerText) && document.querySelectorAll('details[open]').length >= 2, 'the attestation loaded'));
})()`;

export const STATES = [
  // --- The shell (S1d, §5). The shell is on every state below; these three
  //     put it into the conditions no surface fixture reaches on its own. ---
  {
    // The rail collapsed by the operator: 56px, icon-only items named, the
    // 32x32 collapse control still labelled and announcing its state.
    name: 'shell-rail-collapsed', interaction: 'collapse the navigation rail', path: '/cameras', fullWidth: true, archetype: 'ledger',
    tierPolicy: 'workstation-interaction',
    prepare: `(async () => {
      ${UNTIL}
      const toggle = document.querySelector('.sidebar__toggle');
      if (!toggle) return false;
      toggle.click();
      return Boolean(await until(() => document.querySelector('.shell--collapsed') && toggle.getAttribute('aria-expanded') === 'false',
        'the rail collapsed and announcing it'));
    })()`,
  },
  {
    // T1 (§25 Tier B shell): the rail, collapsed by default, opened as an
    // overlay — the shared Drawer over the whole viewport: focus on its
    // heading, the workspace and Context Bar inert beneath its scrim. Probed at
    // the Tier B edges and the anchor between them.
    name: 'shell-rail-overlay', interaction: 'open the navigation overlay', path: '/cameras', fullWidth: true, archetype: 'ledger',
    tierPolicy: 'breakpoint-probe', probeOf: 'shell-rail-collapsed', probeWidths: [768, 1024, 1365],
    prepare: `(async () => {
      ${UNTIL}
      const toggle = await until(() => document.querySelector('.shell--compact .sidebar__toggle'), 'the compact rail toggle');
      if (toggle.getAttribute('aria-expanded') !== 'false') return false;
      toggle.focus();
      window.__vqa.mark('interaction-start');
      toggle.click();
      return Boolean(await until(() => {
        const overlay = document.querySelector('.sidebar[role="dialog"][aria-modal="true"]');
        return overlay && overlay.contains(document.activeElement) && document.getElementById('main')?.hasAttribute('inert')
          && overlay.getBoundingClientRect().width >= 200;
      }, 'the rail open as a modal overlay over an inert workspace'));
    })()`,
  },
  {
    // §25 Tier C (T2): the navigation behind the top-of-page menu control,
    // opened from it — the same overlay as Tier B, its invoker the menu. The
    // harness's overlay exit then presses real Shift+Tab, Tab and Escape, and
    // proves focus returns to the menu with nothing left inert. Probed across
    // the tier, the old 760px narrow shell's edge included.
    name: 'shell-menu-overlay', interaction: 'open the navigation from the top-of-page menu', path: '/videos', fullWidth: true, archetype: 'ledger',
    tierPolicy: 'breakpoint-probe', probeOf: 'videos', probeWidths: [390, 430, 600, 760, 761, 767],
    prepare: `(async () => {
      ${UNTIL}
      const menu = await until(() => document.querySelector('.shell__menu'), 'the top-of-page menu control');
      if (menu.getAttribute('aria-expanded') !== 'false') return false;
      menu.focus();
      window.__vqa.mark('interaction-start');
      menu.click();
      return Boolean(await until(() => {
        const overlay = document.querySelector('.sidebar[role="dialog"][aria-modal="true"]');
        return overlay && overlay.contains(document.activeElement) && document.getElementById('main')?.hasAttribute('inert')
          && overlay.querySelector('nav[aria-label="Primary"] a span')?.getBoundingClientRect().width > 0;
      }, 'the navigation open from the menu as a modal overlay over an inert workspace, its labels shown'));
    })()`,
  },
  {
    // The ? shortcut sheet open over a Ledger: the shared Drawer, focus on its
    // heading, the rail and workspace inert beneath its scrim.
    name: 'shell-shortcut-sheet', interaction: 'press ? to open the shortcut sheet', path: '/videos', fullWidth: true, archetype: 'ledger',
    prepare: `(async () => {
      ${UNTIL}
      // From a focused control, as an operator would press it: the sheet must
      // give focus back to that control when it closes (§20).
      // At Tier C the rail is not drawn: the navigation's own control, the
      // top-of-page menu, is the operator's focused control there.
      const menu = document.querySelector('.shell__menu');
      const from = menu && menu.getBoundingClientRect().width > 0 ? menu : document.querySelector('nav[aria-label="Primary"] a');
      from.focus();
      window.__vqa.mark('interaction-start');
      from.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
      return Boolean(await until(() => {
        const sheet = document.querySelector('.shortcut-sheet[role="dialog"][aria-modal="true"]');
        return sheet && sheet.contains(document.activeElement) && document.querySelector('main[inert]');
      }, 'the shortcut sheet holding focus over an inert main'));
    })()`,
    expectText: ['Keyboard shortcuts', 'Overview', 'Processing'],
  },
  {
    // §5: rendered inside the shell, with a Context Bar, and no rail item
    // highlighted.
    name: 'not-found', path: '/no-such-page', fullWidth: false,
    prepare: `(() => !document.querySelector('.sidebar__nav a.active') && document.title === 'Not found — MAVI')()`,
    expectText: ['Not found', 'This page does not exist.'],
  },
  // --- Ledger-summary: Overview, the one Ledger permitted to stay capped. ---
  // R1: attention-first. The base fixture has one failed and one not-queued
  // video, so its first region is a two-row attention list.
  { name: 'overview', path: '/', fullWidth: false, archetype: 'ledger-summary', expectText: ['Needs attention', 'south-dock-2200.mp4', '1 video'] },
  {
    // Every check answered and nothing needs attention: one line, no frame.
    name: 'overview-clear', path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: inventoryFixture([
      { name: 'north-gate-0800.mp4', status: 'Processed' },
      { name: 'north-gate-0900.mp4', status: 'Processed' },
      { name: 'south-dock-2200.mp4', status: 'Processed', readiness: 'Disabled' },
      { name: 'yard-sweep-0615.mp4', status: 'Processing' },
    ]),
    expectText: 'No items need attention.', forbidText: 'Needs attention',
  },
  {
    // Only media waiting to be processed: one aggregate row.
    name: 'overview-awaiting', path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: inventoryFixture([
      { name: 'north-gate-0800.mp4', status: 'Processed' },
      { name: 'yard-sweep-0615.mp4', status: 'NotQueued' },
      { name: 'yard-sweep-0700.mp4', status: 'NotQueued' },
      { name: 'yard-sweep-0745.mp4', status: 'NotQueued' },
    ]),
    expectText: ['Needs attention', '3 videos'],
  },
  {
    // Scene analytics of completed runs: failed and stale need attention;
    // pending and the operator's scene choices do not.
    name: 'overview-analytics', path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: inventoryFixture([
      { name: 'north-gate-0800.mp4', status: 'Processed', readiness: 'Failed' },
      { name: 'north-gate-0900.mp4', status: 'Processed', readiness: 'Stale' },
      { name: 'south-dock-2200.mp4', status: 'Processed', readiness: 'Pending' },
      { name: 'yard-sweep-0615.mp4', status: 'Processed', readiness: 'NotConfigured' },
    ]),
    expectText: ['Analysis failed', 'Stale', 'north-gate-0900.mp4'], forbidText: 'south-dock-2200.mp4 ·',
  },
  {
    // Many items at once, with the longest identities the fixtures carry:
    // concise ordering, a bounded list and its disclosure.
    name: 'overview-attention-many', path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: inventoryFixture([
      { name: 'north-gate-0900-very-long-original-file-name-for-truncation-of-the-identity.mp4', status: 'Failed', camera: OVERVIEW_CAM_2 },
      { name: 'south-dock-2200.mp4', status: 'Failed', code: 'vision_finalization_exhausted' },
      { name: 'south-dock-2300.mp4', status: 'Failed' },
      { name: 'perimeter-0100.mp4', status: 'Failed', camera: OVERVIEW_CAM_2 },
      { name: 'perimeter-0200.mp4', status: 'Failed', camera: OVERVIEW_CAM_2 },
      { name: 'perimeter-0300.mp4', status: 'Failed', camera: OVERVIEW_CAM_2 },
      { name: 'north-gate-0800.mp4', status: 'Processed', readiness: 'Failed' },
      { name: 'north-gate-1000.mp4', status: 'Processed', readiness: 'Stale' },
      { name: 'yard-sweep-0615.mp4', status: 'NotQueued' },
      { name: 'yard-sweep-0700.mp4', status: 'NotQueued' },
    ]),
    expectText: ['Needs attention', 'Show 4 more'],
  },
  {
    // A failed video whose status lookup failed: it stays an item, from the
    // inventory, and the region says its detail could not be read.
    name: 'overview-lookup-unavailable', path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: inventoryFixture([
      { name: 'south-dock-2200.mp4', status: 'Failed', lookup: 'unavailable' },
      { name: 'north-gate-0800.mp4', status: 'Processed' },
    ]),
    expectText: ['Needs attention', 'south-dock-2200.mp4', 'failure detail of 1 video could not be read'],
  },
  {
    // The video inventory still answering: the attention region's own loading line.
    name: 'overview-loading', path: '/', fullWidth: false, archetype: 'ledger-summary',
    holds: 'loading', api: { '/api/videos': 'hang' },
    expectText: 'Checking what needs attention',
  },
  {
    name: 'overview-empty', atTier: { C: { expectText: 'No items need attention' } }, path: '/', fullWidth: false, archetype: 'ledger-summary',
    api: { '/api/videos': [], '/api/tracks': { items: [], nextCursor: null, totalCount: 0 } },
    expectText: 'No tracks yet',
  },
  {
    // One section's request failed; the other three must still answer.
    name: 'overview-partial-failure', atTier: { C: { expectText: ['video inventory is unavailable', 'cannot be determined while the video inventory is unavailable'] } }, path: '/', fullWidth: false, archetype: 'ledger-summary', api: { '/api/videos': 'unavailable' },
    expectText: ['video inventory is unavailable', 'its distribution cannot be shown', 'cannot be determined while the video inventory is unavailable'],
    forbidText: ['No tracks yet', 'No items need attention'],
  },

  // --- Standard Ledgers: full width, column-capped, never stretched. --------
  { name: 'cameras', path: '/cameras', fullWidth: true, archetype: 'ledger' },
  {
    name: 'cameras-unavailable', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/cameras': 'unavailable' },
    expectText: 'unavailable', forbidText: 'No cameras registered',
  },
  {
    name: 'cameras-loading', path: '/cameras', fullWidth: true, archetype: 'ledger',
    holds: 'loading', api: { '/api/cameras': 'hang' }, expectText: 'Loading cameras',
  },
  {
    name: 'cameras-empty', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/cameras': [] }, expectText: 'No cameras registered',
  },
  {
    // The create region open and clean: §21's inline form, and the widest the
    // Context Bar gets on this surface.
    name: 'cameras-create', interaction: 'open the Add camera form', path: '/cameras', fullWidth: true, archetype: 'ledger',
    prepare: OPEN_CAMERA_FORM, expectText: 'Camera timezone',
    forbidText: 'Unsaved changes',
  },
  {
    // Submitted empty: three field-level refusals at once (§21).
    name: 'cameras-create-invalid', interaction: 'submit the Add camera form empty', path: '/cameras', fullWidth: true, archetype: 'ledger',
    prepare: INVALID_CAMERA_FORM, expectText: 'A camera code is required.',
  },
  {
    // A duplicate-code 409 mapped onto the Code field, other drafts intact.
    name: 'cameras-create-conflict', interaction: 'submit a camera whose code is already registered', path: '/cameras', fullWidth: true, archetype: 'ledger',
    prepare: CONFLICTED_CAMERA_FORM,
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
    name: 'cameras-dense', atTier: { C: { prepare: null } }, path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/cameras': DENSE_CAMERAS },
    // M1: the code is the row's identity, so it takes the wide cap (cap-lg,
    // 260px) — the NORTH-PERIMETER-GATE-CAM-000xx cameras differ only in their
    // last digits, and the narrow one (cap-md) cut five rows to one prefix.
    // Asserted as the cap, not as uncut text: the product ships no font
    // (tokens.css), so whether a 30-character code is whole depends on the
    // platform's — it is on the Windows target, not under CI's fallback.
    prepare: `(async () => {
      ${UNTIL}
      const codes = await until(() => {
        const cells = Array.from(document.querySelectorAll('tbody tr td:first-child .truncate'));
        return cells.length === 24 ? cells : null;
      }, 'the 24 code cells');
      const narrow = codes.filter((cell) => parseFloat(getComputedStyle(cell).maxWidth) < 259.5);
      if (narrow.length) throw new Error(narrow.length + ' code cells capped narrower than 260px: ' + getComputedStyle(narrow[0]).maxWidth);
      return true;
    })()`,
  },
  // --- M1: Cameras onto the R2 Ledger. -----------------------------------------
  // The longest valid identities: every cell bounded and both row actions in
  // view (cameras.actions-in-view) and none unreachable (ledger.actions-reachable).
  {
    name: 'cameras-long-identity', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/cameras': LONG_CAMERAS },
    expectText: ['5 cameras registered', 'Inactive'],
  },
  // A create no field owns the refusal of: one alert in the form, naming its
  // subject, the draft kept.
  {
    name: 'cameras-create-error', interaction: 'submit a camera the store cannot accept', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: {
      'POST /api/cameras': { status: 503, body: { title: 'Unavailable', detail: 'The camera store is unavailable.', code: 'camera_store_unavailable' } },
    },
    prepare: SUBMIT_CAMERA('CAM-07', 'East service gate', `/could not be created/.test(document.body.innerText)`),
    expectText: ['The camera could not be created. The camera store is unavailable. (camera_store_unavailable)', 'Unsaved changes'],
  },
  // The deployment timezone unreadable: said in the form, where it is the
  // default, the field left empty rather than filled from the browser, and a
  // submit refused on that field.
  {
    name: 'cameras-config-unavailable', interaction: 'submit a camera with no deployment timezone to default to', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: { '/api/system/config': 'unavailable' },
    prepare: SUBMIT_CAMERA('CAM-07', 'East service gate', `document.querySelector('.field__error')`, { withoutZone: true }),
    expectText: ['The deployment timezone could not be read', 'An IANA timezone is required.', 'Retry display config'],
  },
  // A create that succeeds, whose inventory refresh then fails: the form
  // closes, focus returns to Add camera, and the last known rows stay, said to
  // be so, with their retry (§37.1 degraded).
  {
    name: 'cameras-refresh-degraded', interaction: 'add a camera whose inventory refresh fails', path: '/cameras', fullWidth: true, archetype: 'ledger',
    api: {
      'POST /api/cameras': { ...CAMERAS[0], id: '33333333-3333-7333-8333-333333333399', code: 'CAM-07', name: 'East service gate' },
      'GET /api/cameras': { sequence: [CAMERAS, 'unavailable'] },
    },
    prepare: SUBMIT_CAMERA('CAM-07', 'East service gate', `/last known camera inventory/.test(document.body.innerText)
      && !document.querySelector('form[aria-label="Add camera"]') && document.activeElement && document.activeElement.textContent.trim() === 'Add camera'`),
    expectText: ['Showing the last known camera inventory; refreshing failed.', 'North Gate', 'Retry'],
    forbidText: ['East service gate', 'No cameras registered'],
  },

  { name: 'videos', path: '/videos', fullWidth: true, archetype: 'ledger' },
  {
    // §25 Tier C (T2): the Ledger filters, and the sort, in their full-width
    // drawer, opened from the band's control. The harness's overlay exit then
    // presses real Shift+Tab, Tab and Escape and proves focus returns to the
    // control with nothing left inert.
    name: 'videos-filters-drawer', interaction: 'open the filters drawer', path: '/videos', fullWidth: true, archetype: 'ledger',
    tierPolicy: 'breakpoint-probe', probeOf: 'videos', probeWidths: [390, 430],
    prepare: `(async () => {
      ${UNTIL}
      const toggle = await until(() => document.querySelector('.toolbar-band__drawer-toggle'), 'the filters control in the band');
      if (toggle.getAttribute('aria-expanded') !== 'false') return false;
      toggle.focus();
      window.__vqa.mark('interaction-start');
      toggle.click();
      return Boolean(await until(() => {
        const drawer = document.querySelector('.toolbar-band__controls[role="dialog"][aria-modal="true"]');
        return drawer && drawer.contains(document.activeElement) && drawer.querySelector('input[type="search"]')
          && drawer.getBoundingClientRect().width >= document.documentElement.clientWidth - 1;
      }, 'the full-width filters drawer holding focus, its controls in it'));
    })()`,
  },
  {
    // T1 (§25 Tier B, Codex P1 on #199): with Recorded and Duration folded
    // into the File cell, their sort is still the operator's — through the
    // Sort select that stands in for the headers. Reached only if choosing
    // "Duration, longest first" there actually re-sorts the rows: the folded
    // Duration header reports the order, and the durations the rows carry in
    // their primary cells read longest first.
    name: 'videos-sort-folded', interaction: 'sort by duration from the folded Sort select',
    path: '/videos', fullWidth: true, archetype: 'ledger',
    prepare: `(async () => {
      ${UNTIL}
      const select = await until(() => {
        const s = document.querySelector('.ledger-sort select');
        return s && s.getBoundingClientRect().width > 0 && document.querySelector('tbody .ledger-primary') ? s : null;
      }, 'the folded Sort select beside a loaded Ledger');
      if (!select) return false;
      const seconds = (text) => {
        const part = (unit) => Number((text.match(new RegExp('(\\\\d+)' + unit)) || [0, 0])[1]);
        return part('h') * 3600 + part('m') * 60 + part('s');
      };
      const durations = () => Array.from(document.querySelectorAll('tbody tr .ledger-folded__value'))
        .filter((v) => /^Duration\\b/.test(v.textContent.trim()))
        .map((v) => seconds(v.textContent.replace(/^Duration/, '')));
      const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
      set.call(select, 'duration:desc');
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return Boolean(await until(() => {
        const head = Array.from(document.querySelectorAll('thead th')).find((th) => th.textContent.trim().startsWith('Duration'));
        const values = durations();
        return head && head.getAttribute('aria-sort') === 'descending' && select.value === 'duration:desc'
          && values.length > 1 && values.every((v, i) => i === 0 || values[i - 1] >= v) && new Set(values).size > 1;
      }, 'the rows sorted by duration, longest first'));
    })()`,
    tierPolicy: 'breakpoint-probe', probeOf: 'videos', probeWidths: [768, 1024],
  },
  {
    name: 'videos-empty', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': [] }, expectText: 'No videos imported yet',
  },
  {
    // S1e (D3): a loading Ledger reserves the header the table will draw, so
    // its first skeleton row sits where the first body row arrives.
    name: 'videos-loading', path: '/videos', fullWidth: true, archetype: 'ledger',
    holds: 'loading', api: { '/api/videos': 'hang' }, expectText: 'Loading videos',
  },
  {
    name: 'videos-filtered-empty', path: '/videos?q=no-such-recording', fullWidth: true, archetype: 'ledger',
    expectText: 'No videos match these filters', forbidText: 'No videos imported yet',
  },
  {
    name: 'videos-unavailable', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': 'unavailable' },
    expectText: 'unavailable', forbidText: 'No videos imported yet',
  },
  {
    // Camera metadata gone: the list still lists, and says why the camera
    // column is thin.
    name: 'videos-cameras-unavailable', path: '/videos', fullWidth: true, archetype: 'ledger', api: { '/api/cameras': 'unavailable' },
    expectText: 'Camera metadata is unavailable',
  },
  {
    // R2: every run state a row can show, with the identities that stress it —
    // inference progress, a finalizing run (no bar), a finalization failure,
    // an ordinary failure with its code, a live status and a failure detail
    // that could not be read, a long camera name and a non-ASCII file name.
    name: 'videos-run-states', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: inventoryFixture([
      { name: 'north-gate-0900.mp4', status: 'Processing', progress: 62 },
      { name: 'north-gate-1000.mp4', status: 'Processing', progress: 100, phase: 'finalizing' },
      { name: 'perimeter-0100.mp4', status: 'Processing', lookup: 'unavailable', camera: OVERVIEW_CAM_2 },
      { name: 'south-dock-2200.mp4', status: 'Failed', code: 'vision_finalization_exhausted' },
      { name: 'south-dock-2300.mp4', status: 'Failed' },
      { name: 'yard-sweep-0615.mp4', status: 'Failed', lookup: 'unavailable' },
      { name: 'überwachung-nordtor-kamera-02-aufzeichnung-2026-09-14-nacht.mp4', status: 'Processed', camera: OVERVIEW_CAM_2 },
      { name: 'yard-sweep-0700.mp4', status: 'Queued' },
      { name: 'yard-sweep-0745.mp4', status: 'NotQueued' },
    ]),
    expectText: ['Run: Finalizing', 'Run: Finalization failed', 'Live status unavailable', 'Failure detail unavailable', 'vision_job_attempts_exhausted'],
  },
  {
    // R2: the three committed filters at once, restored from the URL.
    name: 'videos-filtered', path: `/videos?q=gate&cameraId=${CAM}&status=Processed`, fullWidth: true, archetype: 'ledger',
    expectText: ['1 of 4 videos match the filters', 'north-gate-0800.mp4'],
  },
  {
    // R2: queueing that the API refuses — one alert that names the video.
    name: 'videos-queue-error', interaction: 'queue a video for processing', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: {
      'POST /api/videos/66666666-6666-7666-8666-666666666666/process': {
        status: 500, body: { title: 'Queue unavailable', detail: 'The processing queue did not respond.', code: 'queue_unavailable' },
      },
    },
    prepare: `(async () => {
      ${UNTIL}
      const row = await until(() => Array.from(document.querySelectorAll('tr')).find((r) => r.textContent.includes('yard-sweep-0615.mp4')), 'the not-queued row');
      const process = Array.from(row.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Process');
      if (!process) return false;
      process.focus();
      window.__vqa.mark('interaction-start');
      process.click();
      return Boolean(await until(() => document.body.innerText.includes('Processing could not be queued for yard-sweep-0615.mp4'), 'the queue failure alert'));
    })()`,
    expectText: 'Processing could not be queued for yard-sweep-0615.mp4. The processing queue did not respond. (queue_unavailable)',
  },
  {
    // R2 (Codex P2): a row whose details loaded and whose refresh then failed
    // keeps them and appends the degraded note with its retry. In the capped
    // status cell the retry must stay whole after the widest retained details
    // — a failure code and a finalization failure. The failed row's own Retry
    // is answered `processing_already_active` (reconciled, no alert), whose
    // refresh of the row's detail fails; the active row's poll fails alike.
    name: 'videos-row-degraded', interaction: 'retry a failed video whose detail refresh then fails', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: {
      ...inventoryFixture([
        { name: 'south-dock-2200.mp4', status: 'Failed', code: 'vision_finalization_exhausted', refresh: 'unavailable' },
        { name: 'north-gate-0900-very-long-original-file-name.mp4', status: 'Processing', progress: 40, refresh: 'unavailable', camera: OVERVIEW_CAM_2 },
        { name: 'north-gate-0800.mp4', status: 'Processed' },
      ]),
      'POST /api/videos/00000001-0000-7000-8000-000000000001/process': {
        status: 409, body: { title: 'Processing already active', detail: 'Processing is already active for this video.', code: 'processing_already_active' },
      },
    },
    prepare: `(async () => {
      ${UNTIL}
      const row = await until(() => Array.from(document.querySelectorAll('tr')).find((r) => r.textContent.includes('south-dock-2200.mp4') && r.textContent.includes('vision_finalization_exhausted')), 'the failed row with its detail');
      const retry = Array.from(row.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Retry');
      if (!retry) return false;
      retry.focus();
      window.__vqa.mark('interaction-start');
      retry.click();
      return Boolean(await until(() => document.body.innerText.includes('Failure detail may be out of date') && document.body.innerText.includes('Live status may be out of date'), 'both degraded rows', 15000));
    })()`,
    expectText: ['Failure detail may be out of date', 'Live status may be out of date', 'vision_finalization_exhausted'],
    forbidText: 'Processing could not be queued',
  },
  {
    name: 'videos-dense', path: '/videos', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': DENSE_VIDEOS },
  },

  { name: 'processing-queue', path: '/processing', fullWidth: true, archetype: 'ledger' },
  {
    name: 'processing-queue-empty', path: '/processing', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': [] }, expectText: 'Nothing has been queued',
  },
  {
    name: 'processing-queue-loading', path: '/processing', fullWidth: true, archetype: 'ledger',
    holds: 'loading', api: { '/api/videos': 'hang' }, expectText: 'Loading processing state',
  },
  {
    name: 'processing-queue-unavailable', path: '/processing', fullWidth: true, archetype: 'ledger',
    api: { '/api/videos': 'unavailable' },
    expectText: 'unavailable', forbidText: 'Nothing has been queued',
  },
  {
    // The inventory answered and the per-row run lookups did not: each row
    // must say so and offer its retry, never sit on "Loading run…".
    name: 'processing-queue-row-unavailable', path: '/processing', fullWidth: true, archetype: 'ledger',
    api: {
      '/api/videos/22222222-2222-7222-8222-222222222222/processing': 'unavailable',
      '/api/videos/44444444-4444-7444-8444-444444444444/processing': 'unavailable',
      '/api/videos/55555555-5555-7555-8555-555555555555/processing': 'unavailable',
    },
    expectText: 'Run status unavailable', forbidText: 'Loading run…',
  },
  {
    // R2 (Codex P2): the shared run cell after a failed refresh — an active
    // run whose poll fails keeps its badge and progress, appends the degraded
    // note and its Retry, and the Retry stays whole inside the cell's cap.
    name: 'processing-queue-row-degraded', path: '/processing', fullWidth: true, archetype: 'ledger',
    api: inventoryFixture([
      { name: 'north-gate-0900-very-long-original-file-name.mp4', status: 'Processing', progress: 40, refresh: 'unavailable' },
      { name: 'south-dock-2200.mp4', status: 'Failed', code: 'vision_finalization_exhausted' },
      { name: 'north-gate-0800.mp4', status: 'Processed' },
    ]),
    expectText: ['Run status may be out of date', 'vision_finalization_exhausted'],
  },
  {
    // M2: the same degraded row under wide-font pressure — Verdana where it is
    // installed, the platform's own wide fallback where it is not (DejaVu Sans
    // on CI). The product ships no font (tokens.css), and under CI's fallback
    // the full-text Retry ran 6px out of the 260px run cell, clipped where no
    // scrolling reaches it. The preparation only reaches that condition — and
    // proves it from rendered widths, never from the declared family list,
    // which names Verdana whether or not the platform has it; the promoted
    // ledger.actions-reachable is what judges it (the control's name, keyboard
    // operation and message are the feature tests').
    name: 'processing-queue-row-degraded-wide-font', path: '/processing', fullWidth: true, archetype: 'ledger',
    api: inventoryFixture([
      { name: 'north-gate-0900-very-long-original-file-name.mp4', status: 'Processing', progress: 40, refresh: 'unavailable' },
      { name: 'south-dock-2200.mp4', status: 'Failed', code: 'vision_finalization_exhausted' },
      { name: 'north-gate-0800.mp4', status: 'Processed' },
    ]),
    prepare: `(async () => {
      ${UNTIL}
      const style = document.createElement('style');
      style.textContent = ':root { --font-ui: ${QUEUE_WIDE_FONT} !important; }';
      document.head.appendChild(style);
      // The degraded row's own retry, whatever it is called.
      const cell = await until(() => Array.from(document.querySelectorAll('.run-cell')).find((c) => /Run status may be out of date/.test(c.textContent) && c.querySelector('button')), 'the degraded row and its retry');
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      // The pressure, measured: would the original row's fixed items — badge,
      // inference progress and the full-text Retry it carried — overrun the
      // cell's cap in the font actually rendered? Under the Windows target
      // they need 248px of 260 and fit; the clipping needs more than the cap.
      const probe = cell.querySelector('button').cloneNode(true);
      probe.classList.remove('btn--icon');
      probe.querySelectorAll('.visually-hidden').forEach((node) => node.remove());
      Array.from(probe.childNodes).filter((node) => node.nodeType === 3).forEach((node) => node.remove());
      probe.append('Retry');
      probe.removeAttribute('title');
      probe.setAttribute('aria-hidden', 'true');
      probe.tabIndex = -1;
      probe.style.cssText = 'position:absolute;visibility:hidden;left:0;top:0';
      cell.append(probe);
      const width = (selector) => cell.querySelector(selector).getBoundingClientRect().width;
      const gap = parseFloat(getComputedStyle(cell).columnGap) || 0;
      const cap = parseFloat(getComputedStyle(cell).maxWidth);
      const needed = width('.badge') + width('.progress--inline') + probe.getBoundingClientRect().width + 3 * gap;
      probe.remove();
      if (!(needed > cap + 0.5)) {
        throw new Error('the rendered typography is not wide enough to reproduce the condition: the original row would need '
          + Math.round(needed) + 'px of its ' + cap + 'px cell (' + getComputedStyle(cell).fontFamily + ')');
      }
      return true;
    })()`,
    expectText: ['Run status may be out of date', 'vision_finalization_exhausted'],
  },
  {
    name: 'processing-queue-dense', path: '/processing', fullWidth: true, archetype: 'ledger', api: { '/api/videos': DENSE_VIDEOS },
  },

  // --- Records: centred, the page scrolls. --------------------------------
  { name: 'import', path: '/import', fullWidth: false, archetype: 'record' },
  {
    name: 'import-no-active-cameras', path: '/import', fullWidth: false, archetype: 'record',
    api: { '/api/cameras': [{ ...DENSE_CAMERAS[0], isActive: false }] },
    // M3 (§11): the hatched not-configured block is the primary region itself.
    // It was a dashed-bordered block inside the bordered form panel, which
    // containment.depth cannot see (a state presentation is a message, so it
    // is exempt); this measures the rendered borders round it instead.
    prepare: `(async () => {
      ${UNTIL}
      const block = await until(() => document.querySelector('.empty--hatched'), 'the not-configured block');
      const bordered = (el) => {
        const s = getComputedStyle(el);
        return ['Top', 'Right', 'Bottom', 'Left'].every((side) => parseFloat(s['border' + side + 'Width']) >= 1
          && s['border' + side + 'Style'] !== 'none' && !/rgba\\(.*,\\s*0\\)$/.test(s['border' + side + 'Color']));
      };
      const workspace = block.closest('.workspace');
      for (let el = block.parentElement; el && el !== workspace; el = el.parentElement) {
        if (bordered(el)) throw new Error('the not-configured block sits inside a bordered ' + (el.className || el.tagName));
      }
      return true;
    })()`,
    expectText: 'No active camera to import against',
    forbidText: 'New import',
  },
  // M3: the inventory in flight — the form's panel holds the loading
  // statement, and no empty selector stands in for cameras not yet known.
  {
    name: 'import-loading', path: '/import', fullWidth: false, archetype: 'record',
    holds: 'loading', api: { '/api/cameras': 'hang' }, expectText: 'Loading active cameras',
    forbidText: 'Select active camera',
  },
  // M3: the longest identities in the form — a 32-character camera code with a
  // long name in the select, and a long file name in the FileInput, which
  // wraps rather than truncating (F17: the one statement of what is imported).
  {
    name: 'import-long-identity', interaction: 'fill the import form with long identities', path: '/import', fullWidth: false, archetype: 'record',
    api: { '/api/cameras': [{ ...CAMERAS[0], id: '33333333-3333-7333-8333-333333333381', code: 'SOUTH-DOCK-LOADING-BAY-EAST-0007', name: 'South Dock loading bay, east approach (service road)', isActive: true }] },
    prepare: FILL_IMPORT({ cameraValue: '33333333-3333-7333-8333-333333333381', fileName: 'south-dock-loading-bay-east-approach-2026-09-14T08-30-00-camera-0007-recording-segment-0001.mp4', until: `/Read as/.test(document.body.innerText)` }),
    expectText: ['south-dock-loading-bay-east-approach-2026-09-14T08-30-00-camera-0007-recording-segment-0001.mp4', 'SOUTH-DOCK-LOADING-BAY-EAST-0007', 'Unsaved changes'],
  },
  // M3: a refusal the server makes — one form-level alert in operator words
  // (§21: page-level alerts are for server errors), the draft kept.
  {
    name: 'import-submit-error', interaction: 'submit an import the server refuses', path: '/import', fullWidth: false, archetype: 'record',
    api: { 'POST /api/videos/import': { status: 415, body: { title: 'Unsupported', detail: 'The container is not a supported MP4.', code: 'video_container_unsupported' } } },
    prepare: FILL_IMPORT({ cameraValue: CAMERAS[0].id, fileName: 'north-gate-0800.mp4', submit: true, until: `document.querySelector('form .alert')` }),
    expectText: ['The selected file is not a supported MP4 container. (video_container_unsupported)', 'north-gate-0800.mp4', 'Unsaved changes'],
  },
  {
    name: 'import-cameras-unavailable', path: '/import', fullWidth: false, archetype: 'record',
    api: { '/api/cameras': 'unavailable' },
    expectText: 'Camera inventory is unavailable',
    forbidText: 'No active camera to import against',
  },
  {
    name: 'import-invalid', interaction: 'submit the import form with nothing chosen', path: '/import', fullWidth: false, archetype: 'record',
    prepare: SUBMIT_EMPTY_IMPORT, expectText: 'Enter the recording date and time.',
  },

  {
    // A completed run: final counts, the results action, diagnostics closed.
    name: 'processing-detail-completed', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', expectText: 'north-gate-0800.mp4',
  },
  {
    // A running one: determinate progress, counts deliberately withheld.
    name: 'processing-detail-running', path: `/processing/${LONG_VIDEO}`, fullWidth: false,
    archetype: 'record', expectText: 'Final count after completion',
  },
  {
    name: 'processing-detail-failed', path: `/processing/${FAILED_VIDEO}`, fullWidth: false,
    // R3 / F19: a terminal failure's counts were never produced, and it ended by failing.
    archetype: 'record', expectText: ['vision_job_attempts_exhausted', 'Not produced'],
    forbidText: 'Final count after completion',
  },
  {
    // S1.4 B3 F4 plan §15.3 (B5 `finalizingStateDistinct`, `noPrematureCounts`): a job the
    // platform is finalizing reads as Finalizing, not as a generic running job, and shows no
    // count before publication. This is the acceptance of the separate U1 UI PR; on a UI that
    // renders only `status` it FAILS, and that failure is the truthful B5 result, not a
    // harness defect. Fixture data only: never real-video evidence.
    name: 'processing-finalizing', path: `/processing/${LONG_VIDEO}`, fullWidth: false,
    archetype: 'record',
    api: { [`/api/videos/${LONG_VIDEO}/processing`]: FINALIZING_STATUS },
    expectText: ['Finalizing', 'Final count after publication'],
    forbidText: ['Progress', 'Final count after completion'],
  },
  {
    // B5 `failedFinalizationDistinct`: a finalization failure is presented as such, never as
    // an inference failure. Expected to fail until U1, like the state above.
    name: 'processing-failed-finalization', path: `/processing/${FAILED_VIDEO}`, fullWidth: false,
    archetype: 'record',
    api: { [`/api/videos/${FAILED_VIDEO}/processing`]: FAILED_FINALIZATION_STATUS },
    expectText: ['vision_finalization_staging_missing', 'Finalization failed', 'Not published'],
    forbidText: 'Final count after completion',
  },
  {
    name: 'processing-detail-unavailable', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', api: { [`/api/videos/${VIDEO}/processing`]: 'unavailable' },
    expectText: 'Processing status is unavailable.',
  },
  {
    // A valid route whose video is gone: still `Processing › {video}`, named by
    // its identifier; `Not found` is the alert's state, never the crumb (§5).
    name: 'processing-detail-not-found', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record',
    api: { [`/api/videos/${VIDEO}`]: { status: 404, body: { status: 404, code: 'video_not_found', detail: 'Video was not found.' } } },
    expectText: ['Video was not found.', 'Video 22222222…'], forbidText: 'Not found',
  },
  {
    // The video record unreadable (not a 404): the crumb still names the video
    // by its identifier, never a bare `Video` (§5, §14). The override is a
    // prefix, so the run status fails with it.
    name: 'processing-detail-video-unavailable', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record', api: { [`/api/videos/${VIDEO}`]: 'unavailable' },
    expectText: ['Video 22222222…'], forbidText: ['Not found', VIDEO],
  },

  // --- Workbench: declares full width, and must actually use it. `archetype`
  //     additionally measures it against the frozen section 4.3 rules. ---
  { name: 'scene-editor', path: `/cameras/${CAM}/scene`, fullWidth: true, archetype: 'workbench' },
  {
    name: 'scene-editor-unconfigured', atTier: { C: { expectText: ['needs a display at least 768px wide', 'No revision saved yet'] } },
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/scene`]: { cameraId: CAM, configured: false, activeRevision: null, history: [] } },
    // R4: one drawing entry — the mode strip — and one invitation on the stage.
    expectText: ['No scene configured', 'Draw a zone', 'Trip line', 'No zones or trip lines yet.'],
    forbidText: ['Draw a trip line', '+ Zone', '+ Line'],
  },
  {
    // The bar at its fullest: identity, three badges, the note field, Reset and
    // Save, all in 44px.
    name: 'scene-editor-dirty', tierPolicy: 'workbench-variant', interaction: 'rename the selected scene object',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: DIRTY_SCENE,
    // A placeholder is not page text, so the note field is proven by the
    // preparation's own return value instead — a failed prepare is a finding.
    expectText: 'Unsaved changes',
  },
  {
    // The worst identity the domain permits: `Camera.Create` allows a 32-character
    // code, and a long name beside it. A 44px band cannot grow, so this is where
    // the crumb trail either truncates or pushes the controls off the end.
    name: 'scene-editor-long-identity', atTier: { C: { prepare: null, interaction: null, expectText: ['needs a display at least 768px wide'] } }, interaction: 'rename the selected scene object',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
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
    // S1c: Reset over a dirty draft asks, in the product's Dialog (§15).
    name: 'scene-editor-discard-dialog', tierPolicy: 'workbench-variant', interaction: 'reset a dirty draft, opening the discard Dialog',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: DISCARD_DIALOG,
    expectText: ['Discard your unsaved scene changes?', 'Discard changes', 'Cancel'],
  },
  {
    // S1c: a save refused because the active revision moved on; taking the
    // saved revision discards the draft, so it asks first.
    name: 'scene-editor-reload-dialog', tierPolicy: 'workbench-variant', interaction: 'reload the active revision over a dirty draft, opening its Dialog',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: RELOAD_DIALOG,
    api: {
      [`PUT /api/cameras/${CAM}/scene`]: {
        status: 409,
        body: { title: 'Conflict', code: 'scene_revision_conflict', detail: 'The active revision changed while you were editing.' },
      },
    },
    expectText: ['Discard your changes and load the saved revision?', 'Discard and load revision'],
  },
  {
    // §4.3.1 / §25 Tier B: the frozen Workbench progression at its boundaries
    // — stacked at 1100; the overlay-drawer band 1101-1149 (shut, its toggle
    // shown, the stage at full working width); side by side from 1150, through
    // the Tier B top edge (1365) into Tier A (1366). workbench.geometry and
    // tier.b-composition judge each from rendered geometry.
    name: 'scene-editor-drawer-boundaries',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    tierPolicy: 'breakpoint-probe', probeOf: 'scene-editor', probeWidths: [1100, 1101, 1120, 1149, 1150, 1200, 1365, 1366],
  },
  {
    // The drawer band with the drawer open: modal over an inert workspace,
    // focus inside; the harness's overlay exit then proves Escape closes it,
    // the inert regions are released and focus returns to the toggle.
    name: 'scene-editor-drawer', interaction: 'open the inspector drawer',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: OPEN_WORKBENCH_DRAWER,
    tierPolicy: 'breakpoint-probe', probeOf: 'scene-editor', probeWidths: [1101, 1120, 1149],
  },
  {
    // A past revision open for reading: its chip pressed (`is-viewing`) and
    // the Context Bar in its caution form. Without it no capture shows a
    // revision chip pressed, and pressed.visible could not prove its look.
    name: 'scene-editor-viewing-revision', tierPolicy: 'workbench-variant', interaction: 'view revision 3 from the revision strip',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/scene/revisions/3`]: HISTORICAL_REVISION },
    prepare: `(async () => {
      ${UNTIL}
      const strip = Array.from(document.querySelectorAll('button')).find((b) => (b.textContent || '').trim() === 'Revisions');
      if (!strip) return false;
      strip.click();
      const chip = await until(() => Array.from(document.querySelectorAll('.scene-revisions__chip'))
        .find((b) => b.querySelector('.scene-revisions__number')?.textContent.trim() === 'R3'), 'the R3 chip in the open revision strip');
      chip.focus();
      window.__vqa.mark('interaction-start');
      chip.click();
      return Boolean(await until(() => chip.isConnected && chip.getAttribute('aria-pressed') === 'true'
        && document.querySelector('.context-bar--caution'), 'revision 3 open for reading'));
    })()`,
  },
  {
    // A zone's vertex selected in the inspector: its point pressed
    // (`is-selected`) — the only capture that shows one.
    name: 'scene-editor-vertex-selected', tierPolicy: 'workbench-variant', interaction: 'select a vertex of the selected zone',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: `(async () => {
      ${UNTIL}
      const object = document.querySelector('.scene-navigator__name');
      if (!object) return false;
      object.click();
      // R4 (F18): the coordinates are the forensic tier, closed until asked for.
      const geometry = await until(() => document.querySelector('.scene-inspector__geometry'), 'the geometry disclosure of the selected zone');
      if (geometry.open) return false;
      geometry.querySelector('summary').click();
      const point = await until(() => geometry.open && geometry.querySelector('.scene-inspector__point'), 'the vertices of the selected zone');
      point.focus();
      window.__vqa.mark('interaction-start');
      point.click();
      return Boolean(await until(() => document.querySelector('.scene-inspector__point[aria-pressed="true"]') === document.activeElement, 'the selected vertex, still focused'));
    })()`,
    expectText: ['Vertex 1: x', 'Identity'],
  },
  {
    // R4 (F18): the selected zone with its forensic tier closed — name, type,
    // state and loitering first; the coordinates one disclosure away.
    name: 'scene-editor-object-selected', tierPolicy: 'workbench-variant', interaction: 'select a zone in the navigator',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: `(async () => {
      ${UNTIL}
      const object = await until(() => document.querySelector('.scene-navigator__name'), 'the first scene object');
      window.__vqa.mark('interaction-start');
      object.click();
      const geometry = await until(() => document.querySelector('.scene-inspector__geometry'), 'the selected zone in the inspector');
      return !geometry.open;
    })()`,
    expectText: ['Evaluate this zone', 'Loitering', 'Vertices · '],
  },
  {
    // R4: a zone being drawn — the armed tool, its instruction, Finish and
    // Cancel in the mode strip — placed through the canvas's own projection.
    name: 'scene-editor-drawing', tierPolicy: 'workbench-variant', interaction: 'place two vertices of a new zone',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    prepare: `(async () => {
      ${UNTIL}
      const zone = await until(() => Array.from(document.querySelectorAll('[aria-label="Drawing tools"] button')).find((b) => b.textContent.trim() === 'Zone'), 'the Zone tool');
      zone.click();
      const surface = await until(() => document.querySelector('.scene-stage__surface.tool-zone'), 'the armed drawing surface');
      const rect = surface.getBoundingClientRect();
      const at = (fx, fy) => ({ clientX: rect.left + rect.width * fx, clientY: rect.top + rect.height * fy, bubbles: true, pointerId: 1, isPrimary: true });
      // In the frame's vertical middle: a portrait stage letterboxes the frame,
      // and a click on a letterbox bar is (rightly) not a vertex.
      window.__vqa.mark('interaction-start');
      surface.dispatchEvent(new PointerEvent('pointerdown', at(0.55, 0.44)));
      surface.dispatchEvent(new PointerEvent('pointerup', at(0.55, 0.44)));
      surface.dispatchEvent(new PointerEvent('pointerdown', at(0.8, 0.52)));
      surface.dispatchEvent(new PointerEvent('pointerup', at(0.8, 0.52)));
      return Boolean(await until(() => Array.from(document.querySelectorAll('button')).some((b) => b.textContent.trim() === 'Finish zone'), 'Finish zone in the mode strip'));
    })()`,
    expectText: ['Finish zone', 'Cancel', 'Click to add a vertex'],
  },
  {
    // R4 (cold review): the Context Bar's widest state — a long identity, a
    // dirty draft with its note, and the in-band confirmation of a save that
    // disables analytics ("Cancel", "Save and disable analytics").
    name: 'scene-editor-confirm-disable', tierPolicy: 'workbench-variant', interaction: 'save a scene with every object disabled, opening its confirmation',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: R4_LONG_CAMERA,
    prepare: R4_CONFIRM_DISABLE,
    expectText: ['Save and disable analytics', 'Nothing here is enabled'],
  },
  {
    // The same state at the widths that settle where the Scene's no-wrap
    // status rule may begin: the bar's measured minimum (§25, §4.3.1).
    name: 'scene-editor-confirm-disable-probe', interaction: 'save a scene with every object disabled, opening its confirmation',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: R4_LONG_CAMERA,
    prepare: R4_CONFIRM_DISABLE,
    expectText: ['Save and disable analytics', 'Nothing here is enabled'],
    tierPolicy: 'breakpoint-probe', probeOf: 'scene-editor-confirm-disable', probeWidths: [1150, 1180, 1200, 1230],
  },
  {
    // R4: an inactive camera, alone. The server refuses its changes, so the
    // tools are withheld and the reason stands where they would be — once.
    name: 'scene-editor-inactive', atTier: { C: { prepare: null, expectText: ['needs a display at least 768px wide', '(inactive)'] } },
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: {
      [`/api/cameras/${CAM}/scene`]: 'fixture',
      [`/api/cameras/${CAM}`]: { ...R4_CAMERA, isActive: false },
    },
    prepare: `(async () => {
      ${UNTIL}
      await until(() => document.querySelector('.scene-toolbar__readonly'), 'the inactive camera reason in the mode strip');
      return !document.querySelector('[aria-label="Drawing tools"]') && document.querySelectorAll('.workspace__notices .alert').length === 0;
    })()`,
    expectText: 'This camera is inactive, so its scene cannot be changed.',
    forbidText: 'Draw a zone',
  },
  {
    // R4: the reference video fails while its list answers — said on the stage
    // it would have filled (§37.1, media), not as a page alert.
    name: 'scene-editor-media-unavailable', tierPolicy: 'workbench-variant',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: { [`/api/videos/${VIDEO}/content`]: 'unavailable' },
    prepare: `(async () => {
      ${UNTIL}
      await until(() => document.querySelector('.scene-stage__media-note'), 'the reference video failure on the stage');
      return document.querySelectorAll('.workspace__notices .alert').length === 0;
    })()`,
    expectText: 'Reference video unavailable',
  },
  {
    // R4: a save the server refuses for a reason other than a conflict — one
    // alert naming what failed, the draft kept, Save offered again.
    name: 'scene-editor-save-error', tierPolicy: 'workbench-variant', interaction: 'save a renamed object that the API refuses',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
    api: {
      [`PUT /api/cameras/${CAM}/scene`]: {
        status: 503, body: { title: 'Unavailable', code: 'upstream_unavailable', detail: 'The upstream service did not respond.' },
      },
    },
    prepare: `(async () => {
      ${UNTIL}
      const object = await until(() => document.querySelector('.scene-navigator__name'), 'the first scene object');
      object.click();
      const field = await until(() => Array.from(document.querySelectorAll('input')).find((i) => i.labels && i.labels[0] && i.labels[0].textContent.trim() === 'Name'), 'the Name field');
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      setter.call(field, 'Loading bay east');
      field.dispatchEvent(new Event('input', { bubbles: true }));
      const save = await until(() => Array.from(document.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Save revision' && !b.disabled), 'an enabled Save revision');
      save.focus();
      window.__vqa.mark('interaction-start');
      save.click();
      return Boolean(await until(() => document.body.innerText.includes('The scene could not be saved.') && !save.disabled, 'the refused save'));
    })()`,
    expectText: ['The scene could not be saved. The upstream service did not respond. (upstream_unavailable)', 'Unsaved changes'],
  },
  {
    // The stress case for the frozen no-page-scroll rule (§4.3.2): every fixed
    // band this surface can have, at once, above and below the stage.
    name: 'scene-editor-dense', tierPolicy: 'workbench-variant',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    archetype: 'workbench',
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
    expectText: ['This camera is inactive', 'video list is unavailable', 'Revision 3 could not be loaded.', 'Revision 3 is unavailable.'],
    // An unavailable revision is never presented as an empty one (§14).
    forbidText: ['This revision has no geometry', '0 (0 enabled)', 'ANALYTICS OFF'],
  },
  {
    name: 'scene-editor-unavailable',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    api: { [`/api/cameras/${CAM}/scene`]: 'unavailable' },
    expectText: 'The scene could not be loaded. The upstream service did not respond. (upstream_unavailable)',
  },
  {
    // The camera itself unreadable: `Cameras › Camera 11111111… › Scene` (§5),
    // the state said by the region, the full GUID nowhere.
    name: 'scene-editor-camera-unavailable',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    api: { [`/api/cameras/${CAM}`]: 'unavailable' },
    expectText: ['Camera 11111111…', 'The camera could not be loaded.'], forbidText: CAM,
  },
  {
    // A missing camera stays the Scene surface under Cameras, not the global
    // Not found.
    name: 'scene-editor-camera-missing',
    path: `/cameras/${CAM}/scene`,
    fullWidth: true,
    api: { [`/api/cameras/${CAM}`]: { status: 404, body: { status: 404, code: 'camera_not_found', detail: 'Camera was not found.' } } },
    expectText: ['Camera 11111111…', 'This camera does not exist.', 'Go to Cameras'], forbidText: CAM,
  },

  // --- Investigation: Search, migrated in UI-4. -------------------------
  //
  // Twenty-one states, because this is the surface where the operator's whole
  // job happens and almost every §14 state is reachable on it. The breakpoint
  // states below carry their own viewports: a threshold is settled by the
  // widths either side of it and nowhere else.
  {
    name: 'search', path: '/search', fullWidth: true, archetype: 'investigation',
    // R5 (§17, F13): the header says why this set; the keys are in the `?`
    // sheet and a row carries no ordinal.
    expectText: 'Newest first', forbidText: ['Esc close', '#1'],
  },
  {
    name: 'search-loading', path: '/search', fullWidth: true,
    archetype: 'investigation', holds: 'loading', api: { '/api/tracks': 'hang' },
    expectText: 'Searching…',
  },
  {
    name: 'search-empty', path: '/search', fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': { items: [], nextCursor: null, totalCount: 0 } },
    expectText: 'No Tracks matched',
  },
  {
    name: 'search-unavailable', path: '/search', fullWidth: true,
    archetype: 'investigation', api: { '/api/tracks': 'unavailable' },
    // §14.1: a failed first page is distinguishable from an empty one, and
    // offers the retry it did not have before UI-4.
    expectText: ['unavailable', 'Retry'], forbidText: 'No Tracks matched',
  },
  {
    name: 'search-invalid', path: '/search?objectClass=Person&objectClass=Vehicle',
    fullWidth: true, archetype: 'investigation',
    // A malformed committed URL issues no Track request. R5 (F3, §37.1): the
    // results column — the region it would have filled — says why, with the
    // recovery beside it, not a page alert above an empty frame.
    expectText: ['This search link cannot be used.', 'must occur exactly once', 'Reset search'], forbidText: 'Searching…',
  },
  {
    name: 'search-grid', atTier: { C: { prepare: null, interaction: null, storage: { 'mavi.search.view': 'grid' }, expectText: '6 Tracks' } }, interaction: 'switch the results to the grid view', path: '/search', fullWidth: true, archetype: 'investigation',
    prepare: PICK_GRID, expectText: 'Review evidence',
  },
  {
    name: 'search-filtered',
    path: `/search?cameraId=${CAM}&objectClass=Person&fromUtc=2026-09-14T02%3A00%3A00Z&toUtc=2026-09-14T04%3A00%3A00Z&minimumDurationMs=2500&minimumConfidence=0.8`,
    fullWidth: true, archetype: 'investigation',
    // Every committed criterion is a chip, and each resolves to what the
    // operator calls it rather than to the identifier in the URL.
    expectText: ['CAM-01', 'Minimum confidence', '2.5 s'],
  },
  {
    name: 'search-filtered-unresolved',
    path: `/search?cameraId=${CAM}&videoAssetId=${VIDEO}&processingRunId=77777777-7777-7777-8777-777777777777`,
    fullWidth: true, archetype: 'investigation',
    api: { '/api/cameras': 'unavailable', '/api/videos': 'unavailable' },
    // The metadata that names them is gone; the chips shorten the identifier
    // rather than dropping a criterion that is still in force.
    expectText: ['Camera metadata is unavailable', 'Processing run', '11111111…'],
  },
  {
    name: 'search-no-timezone', path: '/search?fromUtc=2026-09-14T02%3A30%3A00Z',
    fullWidth: true, archetype: 'investigation',
    api: { '/api/system/config': 'unavailable' },
    // ADR-004: without the configured zone the bound is stated explicitly in
    // UTC and time editing is refused rather than guessed at.
    expectText: ['Display timezone is unavailable', 'UTC'],
  },
  {
    name: 'search-videos-unavailable', path: '/search', fullWidth: true,
    archetype: 'investigation', api: { '/api/videos': 'unavailable' },
    expectText: 'Video metadata is unavailable',
  },
  {
    // The tallest the rail gets: every field refused at once, on top of the
    // video-outage hint, at the shortest acceptance viewport. This is where a
    // rail that owns its own scroll, or whose actions are stuck to its bottom
    // edge, puts a control on top of a field — and where the containment border
    // has to stay inside the 252px column rather than widening it.
    name: 'search-rail-overflow', path: '/search', fullWidth: true,
    archetype: 'investigation',
    api: { '/api/videos': 'unavailable' },
    prepare: REFUSE_FIELDS,
    expectText: ['Video metadata is unavailable', 'decimal places', 'Reset'],
  },
  {
    name: 'search-field-errors', path: '/search', fullWidth: true,
    archetype: 'investigation', prepare: REFUSE_FIELDS,
    // §10: both refusals land on their own fields, at once.
    expectText: ['decimal places', 'between 0 and 100'],
  },
  {
    // R5 (F13): a field refused above the rail's scroll position. The rail is
    // scrolled to its foot first; the refused To field must be brought into
    // view and focused, with its error, and nothing committed.
    name: 'search-field-errors-above', interaction: 'submit an inverted time range with the rail scrolled to its foot', path: '/search', fullWidth: true,
    archetype: 'investigation',
    prepare: `(async () => {
      ${UNTIL}
      await ${OPEN_FILTERS};
      const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
      const field = (label) => Array.from(document.querySelectorAll('.field')).find((el) => el.querySelector('label')?.textContent.trim() === label)?.querySelector('input');
      const from = await until(() => field('From'), 'the From field');
      const to = field('To');
      set.call(from, '2026-09-14 10:00:00'); from.dispatchEvent(new Event('input', { bubbles: true }));
      set.call(to, '2026-09-14 09:00:00'); to.dispatchEvent(new Event('input', { bubbles: true }));
      let scroller = to.parentElement;
      while (scroller && !(scroller.scrollHeight > scroller.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement;
      if (scroller) scroller.scrollTop = scroller.scrollHeight;
      // The claim this state carries: at 1366 and 1440 the rail, scrolled to its
      // foot, hides To above its scroll box, so focusing it is a scroll-to-
      // invalid and not the focusing of a field already in view. There the
      // precondition must hold, or the state is not reached. Where the rail is
      // tall enough to show To at its foot (1920 and up, 768), the field cannot
      // start above it and the state proves focus and visibility only.
      const claimed = ['1366x768', '1440x900'].includes(window.innerWidth + 'x' + window.innerHeight);
      const above = scroller ? to.getBoundingClientRect().bottom <= scroller.getBoundingClientRect().top : false;
      if (claimed && !above) return false;
      const search = Array.from(document.querySelectorAll('button[type="submit"]')).find((el) => el.textContent.includes('Search'));
      const committedBefore = location.search;
      search.focus();
      window.__vqa.mark('interaction-start');
      search.click();
      await until(() => document.activeElement && document.activeElement.getAttribute('aria-invalid') === 'true', 'focus on the refused field');
      // Refused, so nothing was committed: the URL is the state of record (§17).
      if (location.search !== committedBefore) return false;
      const focused = document.activeElement;
      if (!scroller) return focused === to;
      const r = focused.getBoundingClientRect(); const box = scroller.getBoundingClientRect();
      return focused === to && r.top >= box.top - 1 && r.bottom <= box.bottom + 1;
    })()`,
    expectText: 'To time must be later',
  },
  {
    // R5 (§17, F13): the keys the header no longer carries, in the `?` sheet
    // opened over Search.
    name: 'search-shortcut-sheet', interaction: 'open the keyboard shortcut sheet over Search', path: '/search', fullWidth: true,
    prepare: `(async () => {
      ${UNTIL}
      // Opened from a focused result, as an operator does, so the sheet's
      // return of focus to its invoker is observable (overlay.drawer).
      const invoker = await until(() => document.querySelector('.result-row__select'), 'a result selection control');
      invoker.focus();
      window.__vqa.mark('interaction-start');
      invoker.dispatchEvent(new KeyboardEvent('keydown', { key: '?', bubbles: true }));
      return Boolean(await until(() => document.querySelector('.shortcut-sheet'), 'the shortcut sheet'));
    })()`,
    // (Section headings are uppercase on screen; the rows are asserted.)
    expectText: ['Keyboard shortcuts', 'Select the next result', 'Select the previous result', 'Open the selected result in Review', 'Close the inspector'],
  },
  {
    name: 'search-long-names', path: `/search?cameraId=${CAM2}`, fullWidth: true,
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
    name: 'search-paged', path: '/search', fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': PAGE_ONE },
    expectText: ['Load more', 'more to load'],
  },
  {
    name: 'search-full-page', path: '/search', fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': FULL_PAGE },
    expectText: ['24 Tracks', 'more to load'],
  },
  {
    name: 'search-continuation-failed', interaction: 'load more results', path: '/search', fullWidth: true,
    archetype: 'investigation', api: { '/api/tracks': PAGE_ONE_THEN_503 },
    // The query client retries a 5xx once before the failure is terminal.
    prepare: LOAD_MORE,
    // The page that failed does not take the results with it, and continuation
    // stops being automatic until the operator asks again.
    expectText: ['next page could not be loaded', 'Retry load more'],
  },
  {
    name: 'search-snapshot-expired', interaction: 'load more results', path: '/search', fullWidth: true,
    archetype: 'investigation', api: { '/api/tracks': PAGE_ONE_THEN_EXPIRED }, prepare: LOAD_MORE,
    expectText: ['snapshot can no longer continue', 'Refresh results'],
  },
  {
    name: 'search-end-of-snapshot', path: '/search', fullWidth: true,
    archetype: 'investigation', expectText: ['End of this result snapshot', 'all loaded'],
  },
  {
    name: 'search-inspecting', path: `/search?track=${TRACK}`, fullWidth: true,
    archetype: 'investigation', expectText: INSPECTOR_LOADED,
  },
  {
    // The inspector opened by an action rather than by the URL: below 1600px
    // its drawer must return focus to the selecting control on Escape (§20).
    name: 'search-inspector-opened', interaction: 'select a result to inspect it', path: '/search', fullWidth: true, archetype: 'investigation',
    prepare: `(async () => {
      ${UNTIL}
      const select = await until(() => document.querySelector('.result-row__select'), 'a result selection control');
      select.focus();
      select.click();
      return Boolean(await until(() => {
        if (!new URLSearchParams(location.search).get('track')) return false;
        // The inspector itself, not only the URL: a drawer not yet mounted
        // must not pass for an in-place inspector (T1, stacked drawer).
        const inspector = document.querySelector('.workspace__inspector');
        if (!inspector) return false;
        return inspector.getAttribute('role') !== 'dialog' || inspector.contains(document.activeElement);
      }, 'the inspector open, holding focus when it is a drawer'));
    })()`,
    expectText: INSPECTOR_LOADED,
  },
  {
    name: 'search-inspecting-grid', tierPolicy: 'grid-variant', interaction: 'switch the results to the grid view', path: `/search?track=${TRACK}`, fullWidth: true,
    archetype: 'investigation', prepare: PICK_GRID, expectText: INSPECTOR_LOADED,
  },
  {
    // The narrow host. Marker separation is measured from the rendered track,
    // not assumed from Review's wider column, so dense markers have to stay
    // individually clickable in the drawer too.
    name: 'search-inspecting-dense', path: `/search?track=${TRACK}`, fullWidth: true,
    archetype: 'investigation',
    api: { [`/api/tracks/${TRACK}`]: REVIEW_DENSE_MARKERS },
    expectText: INSPECTOR_LOADED,
  },
  {
    name: 'search-inspector-unavailable', path: `/search?track=${TRACK}`, fullWidth: true, archetype: 'investigation',
    api: { [`/api/tracks/${TRACK}`]: 'unavailable' },
    // The inspector states an ApiError by its detail and code; "could not be
    // loaded" is only the fallback for a failure that is not one.
    expectText: ['upstream_unavailable', 'Retry'],
  },
  {
    name: 'search-inspector-missing', path: `/search?track=${TRACK}`, fullWidth: true, archetype: 'investigation',
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
    name: 'search-threshold', path: `/search?track=${TRACK}`, fullWidth: true,
    // The threshold is 1600, so the widths either side of it are what settle it.
    archetype: 'investigation', tierPolicy: 'breakpoint-probe', probeOf: 'search-inspecting', probeWidths: [1440, 1500, 1550, 1599, 1600, 1700],
    expectText: INSPECTOR_LOADED,
  },
  {
    // S1.3b: the same Evidence Set component in the inspector, uncollapsed in
    // the old Representative-frame disclosure's place. At 1366 the inspector is
    // the drawer, the narrowest host the strip has.
    name: 'search-inspecting-evidence', path: `/search?track=${TRACK}`, fullWidth: true,
    archetype: 'investigation', probeWidths: [1600],
    // The inspector's section title is set in capitals by CSS, so the rendered
    // text is matched through the roles rather than the title.
    expectText: [...INSPECTOR_LOADED, 'Representative', 'Near view', 'Late diverse'],
  },
  {
    name: 'search-inspecting-evidence-unavailable', path: `/search?track=${TRACK}`, fullWidth: true,
    archetype: 'investigation', probeWidths: [1600],
    api: { [`/api/tracks/${TRACK}`]: EVIDENCE_CROP_UNAVAILABLE, ...UNAVAILABLE_CROP },
    expectText: [...INSPECTOR_LOADED, 'No image'],
  },
  {
    // Open decision 4. At 1920 and 2560 the results stay capped and the
    // inspector takes the surplus — asserted as geometry, not by eye.
    name: 'search-ultrawide', path: `/search?track=${TRACK}`, fullWidth: true,
    archetype: 'investigation', expectText: INSPECTOR_LOADED,
  },

  // --- Investigation: Slice 4 analytics on the UI-4 grammar. --------------
  {
    // Zone, relation and dwell committed; the chips name the geometry the scene
    // fixture owns, the coverage strip sits beneath the header and names every
    // non-zero bucket, and the rows carry no second status badge.
    name: 'search-analytics',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}&zoneRelation=entered&minDwellMs=2500&loitering=true`,
    fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': ANALYTIC_PAGE(PARTIAL_COVERAGE) },
    expectText: ['Entered', 'Loading bay', '2 of 5 runs analysed', 'not yet analysed', 'could not be analysed', 'Revision 4'],
    forbidText: 'No Tracks matched',
  },
  {
    name: 'search-analytics-complete',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}`,
    fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': ANALYTIC_PAGE(COMPLETE_COVERAGE) },
    // "Processing" is a navigation item, so the absence asserted is the link's
    // own words in the strip, not the word itself.
    expectText: ['All 4 runs analysed', 'Dwelled in'], forbidText: 'could not be analysed',
  },
  {
    // Incomplete analytics never render as ordinary zero matches (§14, §17).
    name: 'search-analytics-not-analysed',
    path: `/search?cameraId=${CAM}&loitering=true`,
    fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': NOT_ANALYSED_PAGE },
    expectText: ['Not analysed yet.', '3 runs not yet analysed'], forbidText: 'No Tracks matched',
  },
  {
    // The scene that names the geometry is gone: the committed zone stays in
    // force by identifier and the rail says why its choices are unavailable.
    name: 'search-analytics-scene-unavailable',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}`,
    fullWidth: true, archetype: 'investigation',
    api: { '/api/tracks': ANALYTIC_PAGE(PARTIAL_COVERAGE), [`/api/cameras/${CAM}/scene`]: 'unavailable' },
    // The statement is in the rail, which is a drawer at 768-1100 (§25).
    prepare: OPEN_FILTERS,
    expectText: ['Scene geometry is unavailable', '77777777…'],
  },
  {
    // S1b closure: the active scene loaded and named the committed zone, then a
    // later read failed with the old revision still cached. The active scene is
    // mutable, so the rail must not keep offering its geometry as current: it
    // reads as unavailable and the zone falls back to its identifier. Reached
    // for real: the scene goes stale (30s), the operator leaves and comes back,
    // and the refetch on return fails (after the query's one retry).
    name: 'search-analytics-scene-degraded',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}`,
    fullWidth: true, archetype: 'investigation',
    api: {
      '/api/tracks': ANALYTIC_PAGE(PARTIAL_COVERAGE),
      [`/api/cameras/${CAM}/scene`]: {
        sequence: [JSON.parse(readFileSync(new URL(`./fixtures/cameras_${CAM}_scene.json`, import.meta.url), 'utf8')), 'unavailable'],
      },
    },
    prepare: `(async () => {
      ${UNTIL}
      await ${OPEN_FILTERS};
      // First read: the zone resolves to its name from the active scene.
      if (!document.body.innerText.includes('Loading bay')) return false;
      // The scene must be older than its 30s stale time. Rather than sleep for
      // it, the page's clock is moved past it: staleness is judged against
      // Date.now(), so this is the same condition the operator reaches by
      // waiting, without the harness spending 31 seconds per capture on it.
      const realNow = Date.now.bind(Date);
      Date.now = () => realNow() + 31000;
      // An open filters drawer (768-1100) makes the shell inert: close it, as
      // the operator would, before leaving by the rail.
      const closeFilters = Array.from(document.querySelectorAll('.workspace__rail-head button')).find((b) => /Close filters/.test(b.textContent));
      if (closeFilters) {
        closeFilters.click();
        await until(() => !document.querySelector('.workspace__rail[role="dialog"]') && !document.querySelector('#main[inert]'), 'the filters drawer closed');
      }
      // At Tier C the navigation is behind the top-of-page menu (§25).
      const menu = document.querySelector('.shell__menu');
      if (menu) {
        menu.click();
        await until(() => document.querySelector('.sidebar[role="dialog"][aria-modal="true"]'), 'the navigation overlay');
      }
      const overview = Array.from(document.querySelectorAll('a')).find((a) => a.textContent.trim() === 'Overview');
      if (!overview || overview.closest('[inert]')) return false;
      overview.click();
      // The Overview page rendered and Search gone, not only the URL changed:
      // going back while the route is still loading keeps Search mounted, and
      // a page that never remounts never refetches (a race seen on CI).
      await until(() => location.pathname === '/' && !document.querySelector('.workspace--investigation')
        && document.querySelector('.workspace--ledger-summary') && document.body.innerText.includes('Needs attention'), 'the Overview page to replace Search');
      history.back();
      // Search remounts on return, its rail drawer (768-1100) shut again.
      await until(() => document.querySelector('.workspace--investigation'), 'Search to render again');
      await ${OPEN_FILTERS};
      return Boolean(await until(() => document.body.innerText.includes('Scene geometry is unavailable'),
        'the refetch on return to fail after its one retry', 15000));
    })()`,
    expectText: ['Scene geometry is unavailable', '77777777…'],
  },
  {
    // The Analytics group with a camera chosen: zone and line choices resolved
    // from the active revision, dependents unlocked, the rail tall enough to
    // scroll at 1366 — which is what the overlap assertion is for.
    name: 'search-analytics-rail', path: '/search', fullWidth: true, archetype: 'investigation',
    // The group heading is uppercased on screen; its field labels are not.
    prepare: PICK_CAMERA, expectText: ['Zone relation', 'Motion direction', 'Loitering', 'Loading bay'],
    forbidText: 'Choose a camera, video or processing run',
  },
  {
    // The inspector's analytics summary against the pinned identity.
    name: 'search-analytics-inspecting',
    path: `/search?cameraId=${CAM}&zoneId=${ZONE}&track=${TRACK}`,
    fullWidth: true, archetype: 'investigation',
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
    name: 'processing-queue-analytics', path: '/processing', fullWidth: true, archetype: 'ledger',
    expectText: ['Analysed'],
  },
  {
    name: 'processing-detail-analytics-ready', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record',
    expectText: ['Scene analytics', 'Revision 4 · scene-analytics-v1', 'Tracks unavailable'],
  },
  {
    // S1b closure: a Pending run whose analytics loaded and whose later poll
    // failed (the query's one retry included). The details stay, the page says
    // it has stopped checking, and Retry is offered — §37.1 degraded.
    name: 'processing-detail-analytics-degraded', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record',
    api: {
      [`/api/videos/${VIDEO}/processing`]: {
        videoStatus: 'Processed',
        latestRun: {
          processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', status: 'Completed', pipeline: 'phase1-detection-tracking', pipelineVersion: 'phase1-v1',
          workerId: 'worker-a', queuedAtUtc: '2026-09-14T03:05:00Z', startedAtUtc: '2026-09-14T03:05:10Z', completedAtUtc: '2026-09-14T03:09:40Z',
          progressPercent: 100, attemptCount: 1, failureCode: null, framesProcessed: 15000, tracksCreated: 6, analyticsReadiness: 'Pending',
        },
      },
      '/api/processing/runs/bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb/analytics': {
        sequence: [
          {
            processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', readiness: 'Pending', activeSceneRevisionId: REVISION, algorithmVersion: 'scene-analytics-v1',
            analyses: [{
              analysisId: 'aaaaaaa2-aaaa-7aaa-8aaa-aaaaaaaaaaa2', processingRunId: 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb',
              sceneRevisionId: REVISION, sceneRevisionNumber: 4, algorithmVersion: 'scene-analytics-v1', status: 'Running',
              attemptCount: 2, queuedAtUtc: '2026-09-14T03:10:00Z', startedAtUtc: '2026-09-14T03:10:02Z', completedAtUtc: null,
              leaseExpiresAtUtc: '2026-09-14T03:12:02Z', analysedTrackCount: null, unavailableTrackCount: null, failureCode: null,
            }],
          },
          'unavailable',
        ],
      },
    },
    expectText: ['Running · attempt 2', 'stopped checking', 'Retry'],
    forbidText: 'keeps refreshing until it does',
  },
  {
    // Stale: the current geometry is not applied; the camera-wide consequence is
    // stated before the action.
    name: 'processing-detail-analytics-stale', path: `/processing/${VIDEO}`, fullWidth: false,
    archetype: 'record',
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
    archetype: 'record',
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

  // --- R3: the rest of the Processing Detail catalogue (§37.1, every state the
  //     Record can reach). Each answers only what the page asks for, through
  //     the existing fixtures where one serves. ---
  {
    name: 'processing-detail-queued', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: { [`/api/videos/${VIDEO}/processing`]: { videoStatus: 'Queued', latestRun: { ...R3_COMPLETED_RUN, status: 'Queued', phase: 'queued', progressPercent: 0, startedAtUtc: null, completedAtUtc: null, workerId: null, framesProcessed: 0, tracksCreated: 0 } } },
    expectText: ['Queued', 'Final count after completion'], forbidText: ['Queue processing', 'Scene analytics'],
  },
  {
    // No run is a state of its own, never an unavailable one (§14.1).
    name: 'processing-detail-not-queued', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: { [`/api/videos/${VIDEO}/processing`]: { videoStatus: 'NotQueued', latestRun: null } },
    expectText: ['Not queued', 'Queue processing to make this video searchable.'], forbidText: 'unavailable',
  },
  {
    // A route whose identifier is not one: refused before any request.
    name: 'processing-detail-invalid', path: '/processing/not-a-video', fullWidth: false, archetype: 'record',
    expectText: ['Unknown video', 'The video identifier in this route is invalid.'],
  },
  {
    // The video record unreadable while its run status answers: the facts rail
    // says so with its retry; the run, its badge and its action stand.
    name: 'processing-detail-metadata-unavailable', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: { [`/api/videos/${VIDEO}`]: 'unavailable', [`/api/videos/${VIDEO}/processing`]: R3_COMPLETED_STATUS },
    expectText: ['Video metadata is unavailable.', 'Video 22222222…', 'Open results', '15,000', 'Scene analytics', 'Analysed'],
    forbidText: 'Processing status is unavailable.',
  },
  {
    // Codex P2 on PR #191: with the video record unavailable the camera is
    // unknown, so a readiness that points at the Scene Editor offers no link —
    // never the camera ledger in its place. Its recovered form (the link to
    // this camera's editor) is `processing-detail-analytics-not-configured`.
    name: 'processing-detail-metadata-unavailable-unconfigured', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: { ...r3Analytics('NotConfigured', null, []), [`/api/videos/${VIDEO}`]: 'unavailable' },
    expectText: ['Video metadata is unavailable.', 'No scene configured', 'no scene configuration yet'],
    forbidText: ['Open Scene Editor', 'Re-analyse camera', 'Processing status is unavailable.'],
  },
  {
    // Long identities beside a failure and its primary action: the crumb gives
    // way, the badge and `Retry processing` never do (F16, §37.1 long names).
    name: 'processing-detail-long-identity', path: `/processing/${FAILED_VIDEO}`, fullWidth: false, archetype: 'record',
    api: R3_LONG_IDENTITY,
    expectText: ['Retry processing', 'Not produced'],
  },
  {
    // The Diagnostics disclosure opened over long technical values: they wrap
    // inside the facts rail rather than widening it (§37.1 panel long names).
    name: 'processing-detail-diagnostics', interaction: 'open the diagnostics disclosure', path: `/processing/${FAILED_VIDEO}`, fullWidth: false, archetype: 'record',
    api: R3_LONG_IDENTITY,
    prepare: `(async () => {
      ${UNTIL}
      const summary = await until(() => Array.from(document.querySelectorAll('summary')).find((s) => s.textContent.trim() === 'Diagnostics'), 'the Diagnostics disclosure');
      summary.focus();
      window.__vqa.mark('interaction-start');
      summary.click();
      return Boolean(await until(() => summary.parentElement.open && document.body.innerText.includes('worker-gpu-node-17.site-recorder.local'), 'the opened diagnostics'));
    })()`,
    expectText: ['Processing run', 'worker-gpu-node-17.site-recorder.local', 'phase1-detection-tracking · phase1-v1'],
  },
  {
    // Retrying a failed run that the API refuses: one alert naming the video,
    // the run and its action still on screen (§14.1).
    name: 'processing-detail-retry-error', interaction: 'retry a failed run that the API refuses', path: `/processing/${FAILED_VIDEO}`, fullWidth: false, archetype: 'record',
    api: {
      [`POST /api/videos/${FAILED_VIDEO}/process`]: {
        status: 503, body: { title: 'Queue unavailable', detail: 'The processing queue did not respond.', code: 'queue_unavailable' },
      },
    },
    prepare: `(async () => {
      ${UNTIL}
      const retry = await until(() => Array.from(document.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Retry processing'), 'Retry processing');
      retry.focus();
      window.__vqa.mark('interaction-start');
      retry.click();
      return Boolean(await until(() => document.body.innerText.includes('Processing could not be queued for south-dock-2200.mp4'), 'the queue failure alert'));
    })()`,
    expectText: ['Processing could not be queued for south-dock-2200.mp4. The processing queue did not respond. (queue_unavailable)', 'Retry processing'],
  },
  {
    // A running run whose poll then fails (the query's one retry included):
    // the run stays, labelled as last known, with its retry (§37.1 degraded).
    name: 'processing-detail-degraded', path: `/processing/${LONG_VIDEO}`, fullWidth: false, archetype: 'record',
    api: { [`/api/videos/${LONG_VIDEO}/processing`]: { sequence: [R3_RUNNING_STATUS, 'unavailable'] } },
    expectText: ['Showing the last known processing status; refreshing failed.', 'Final count after completion'],
  },
  {
    name: 'processing-detail-analytics-not-configured', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: r3Analytics('NotConfigured', null, []),
    expectText: ['No scene configured', 'Open Scene Editor'], forbidText: 'Disabled by scene',
  },
  {
    name: 'processing-detail-analytics-disabled', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: r3Analytics('Disabled', REVISION, []),
    expectText: ['Disabled by scene', 'Open Scene Editor'], forbidText: 'No scene configured',
  },
  {
    // The lifecycle endpoint unreadable on first load: the readiness the run
    // status carries still stands, said to be from there, with a retry.
    name: 'processing-detail-analytics-unavailable', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: { [`/api/videos/${VIDEO}/processing`]: R3_COMPLETED_STATUS, [`/api/processing/runs/${R3_COMPLETED_RUN.processingRunId}/analytics`]: 'unavailable' },
    expectText: ['Analysis details are unavailable; the readiness above is from the processing status.', 'Analysed'],
  },
  {
    // Retry analytics refused: the failure stated once, the refusal named, the
    // action offered again.
    name: 'processing-detail-analytics-retry-error', interaction: 'retry failed analytics that the API refuses', path: `/processing/${VIDEO}`, fullWidth: false, archetype: 'record',
    api: {
      ...r3Analytics('Failed', REVISION, [{ status: 'Failed', attemptCount: 3, failureCode: 'analytics_attempts_exhausted', analysedTrackCount: 0, unavailableTrackCount: 0 }]),
      [`POST /api/processing/runs/${R3_COMPLETED_RUN.processingRunId}/analytics/retry`]: {
        status: 409, body: { title: 'Not retryable', detail: 'The analysis is not in a retryable state.', code: 'analysis_not_retryable' },
      },
    },
    prepare: `(async () => {
      ${UNTIL}
      const retry = await until(() => Array.from(document.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Retry analytics'), 'Retry analytics');
      retry.focus();
      window.__vqa.mark('interaction-start');
      retry.click();
      return Boolean(await until(() => document.body.innerText.includes('Scene analytics could not be retried.') && !retry.disabled, 'the retry refusal'));
    })()`,
    expectText: 'Scene analytics could not be retried. The analysis is not in a retryable state. (analysis_not_retryable)',
  },

  // --- Review: capped today; its archetype migration is UI-5, not UI-1. ---
  // The evidence overlay: where the bounding-box and trajectory hues have to
  // survive footage the product does not control (section 26).
  // UI-5: Review is on the Review archetype and uses the full width, so the
  // player takes the surplus on a wide display (section 25).
  // R6 (F18, F19): the identifiers are one closed disclosure away, and the
  // analytical identity is stated once, with no footer repeating it.
  { name: 'review', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', expectText: ['North Gate', 'Track summary', 'Record detail', 'Reference point', 'Asia/Kolkata'], forbidText: [TRACK, 'bbbbbbbb-bbbb', 'reference point:', 'Local track', 'persisted evidence'] },
  // A terminal Review state keeps the video the route names: `Search › {video} › Review` (§5).
  { name: 'review-track-missing', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: false, api: { [`/api/tracks/${TRACK}`]: { status: 404, body: { status: 404, code: 'track_not_found', detail: 'Track was not found.' } } }, expectText: ['Track was not found.', 'north-gate-0800.mp4'], forbidText: VIDEO },
  { name: 'review-bright', tierPolicy: 'footage-variant', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'bright', prepare: SEEK, requireOverlay: true },
  { name: 'review-dark', tierPolicy: 'footage-variant', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'dark', prepare: SEEK, requireOverlay: true },
  { name: 'review-saturated', tierPolicy: 'footage-variant', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, requireOverlay: true },
  { name: 'review-lowcontrast', tierPolicy: 'footage-variant', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'lowcontrast', prepare: SEEK, requireOverlay: true },
  { name: 'review-letterbox', tierPolicy: 'footage-variant', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'letterbox', prepare: SEEK, requireOverlay: true },
  { name: 'review-pillarbox', tierPolicy: 'footage-variant', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'pillarbox', prepare: SEEK, requireOverlay: true },
  // The custom transport and the layer toggles that replaced the native
  // controls, captured over real footage. Playback itself is not asserted here:
  // a headless browser refuses programmatic play without a user gesture, and
  // the play/pause transition is covered by the component tests.
  { name: 'review-transport', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, expectText: ['Play', 'Start', 'Evidence', 'End', 'Speed', 'Bounding box', 'Trajectory'] },
  { name: 'review-zone-visit', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, requireOverlay: true, expectText: ['Loading bay', 'Scene revision 4'] },
  { name: 'review-multi-visit', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_MULTI_VISIT }, expectText: ['2 visits', '2s dwell against a 1s threshold'] },
  { name: 'review-overlap-2', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERLAP_2 } },
  { name: 'review-overlap-3', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERLAP_3 } },
  // More concurrent visits than the capped sub-rows, so the overflow rail
  // and its count are exercised rather than only reasoned about.
  { name: 'review-overlap-overflow', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERLAP_5 } },
  { name: 'review-crossing-atob', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, requireOverlay: true, expectText: ['Gate A', 'Inbound'] },
  { name: 'review-crossing-btoa', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, requireOverlay: true, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_CROSSING_BTOA }, expectText: ['Outbound'] },
  { name: 'review-dwell-stationary', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_DWELL_STATIONARY }, expectText: ['2 intervals'] },
  { name: 'review-dense-markers', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_DENSE_MARKERS }, expectText: ['5 crossings'] },
  // --- R6: Review as the reference surface. ---------------------------------
  // More crossings and visits than the rail lists inline: five of each, the
  // rest one closed disclosure away, and the player still pinned (§37.1, §4.5.1).
  { name: 'review-dense-facts', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { [`/api/tracks/${TRACK}`]: REVIEW_DENSE_FACTS }, expectText: ['9 crossings', '4 more crossings', '8 visits', '3 more visits'] },
  // The forensic tier opened: the attestation and the record's full
  // identifiers, at their longest, inside the rail's width.
  { name: 'review-provenance-open', interaction: 'open the runtime attestation and the record detail', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', api: { [`/api/processing/runs/bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb/attestation`]: RUN_ATTESTATION }, prepare: OPEN_PROVENANCE, expectText: ['Verification', 'win-x64-cuda12.4-cudnn9-onnxruntime-gpu-1.19.2', TRACK, 'bbbbbbbb-bbbb-7bbb-8bbb-bbbbbbbbbbbb', 'Representative quality'], forbidText: ['Display timezone'] },
  // The longest identities: the video's file name in the crumb, a four-digit
  // Track number in the subject, a long camera code and name in the summary.
  { name: 'review-long-identity', path: `/review/video/${LONG_VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', api: { [`/api/tracks/${TRACK}`]: REVIEW_LONG_IDENTITY }, expectText: ['Motorcycle · Track 1248', 'South Dock loading bay, east approach (service road)', 'Asia/Kolkata'] },
  // A refresh that fails with the evidence on screen: the operator went back to
  // Search and returned after the evidence went stale. The evidence stays and
  // says it may not be current (§14.1, degraded), with its retry.
  {
    name: 'review-refresh-degraded', interaction: 'return to a stale Review whose refresh fails', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review',
    api: { [`/api/tracks/${TRACK}`]: { sequence: [JSON.parse(readFileSync(new URL(`./fixtures/tracks_${TRACK}.json`, import.meta.url), 'utf8')), 'unavailable'] } },
    prepare: `(async () => {
      ${UNTIL}
      await until(() => document.querySelector('.workspace--review .evidence-player__video'), 'the Review');
      // The Track evidence older than the queries' staleTime (5 s, app/queryClient.ts),
      // read from its own response time, so the return refetches it.
      await until(() => {
        const loaded = performance.getEntriesByType('resource').filter((e) => e.name.endsWith('/api/tracks/${TRACK}'))[0];
        return loaded && performance.now() - loaded.responseEnd > 5100;
      }, 'the Track evidence past its staleTime', 9000);
      const crumb = await until(() => Array.from(document.querySelectorAll('.context-bar a')).find((a) => a.textContent.trim() === 'Search'), 'the Search crumb');
      window.__vqa.mark('interaction-start');
      crumb.click();
      // Search rendered (the Review unmounted), not merely the URL changed.
      await until(() => location.pathname === '/search' && !document.querySelector('.workspace--review') && document.querySelector('.results'), 'Search');
      history.back();
      return Boolean(await until(() => /refreshing failed/.test(document.body.innerText) && document.querySelector('.workspace--review'), 'the degraded notice', 10000));
    })()`,
    expectText: ['Showing the last known Track evidence; refreshing failed.', 'Track summary', 'Retry'],
  },
  // Search → Review → Search: the one way back is the Context Bar's root crumb
  // (F4), and it restores the Investigation the Review was opened from — its
  // committed filter and the Track still selected.
  {
    name: 'review-return-to-search', interaction: 'open a result in Review and return to Search', path: `/search?objectClass=Person&track=${TRACK}`, fullWidth: true, archetype: 'investigation',
    prepare: `(async () => {
      ${UNTIL}
      const open = await until(() => document.querySelector('aside a[href*="/review/video/"], [role="dialog"] a[href*="/review/video/"]'), 'the inspector review link');
      if (!/[?&]from=/.test(open.getAttribute('href'))) throw new Error('the review link carries no return context');
      open.click();
      await until(() => document.querySelector('.workspace--review'), 'the Review');
      const backs = Array.from(document.querySelectorAll('main a, main button')).filter((c) => /back to search|visual search/i.test(c.textContent));
      if (backs.length) throw new Error('Review offers a second way back: ' + backs.map((c) => c.textContent.trim()).join(', '));
      const crumb = await until(() => Array.from(document.querySelectorAll('.context-bar a')).find((a) => a.textContent.trim() === 'Search'), 'the Search crumb');
      window.__vqa.mark('interaction-start');
      crumb.click();
      return Boolean(await until(() => {
        const params = new URLSearchParams(location.search);
        return location.pathname === '/search' && params.get('track') === '${TRACK}' && params.get('objectClass') === 'Person'
          && document.querySelector('[role="dialog"] h2, aside h2');
      }, 'Search restored with its filter and the Track selected'));
    })()`,
    expectText: INSPECTOR_LOADED,
  },
  // --- S1.3b: the Track Evidence Set in Review's evidence rail. --------------
  // The full four-role set at every acceptance width, including 1366x768 where
  // the player and the primary summary must both still be in the first viewport.
  { name: 'review-evidence-set', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, probeWidths: [1600], expectText: ['Evidence Set', 'Representative', 'Near view', 'Early diverse', 'Late diverse', 'Track summary'] },
  { name: 'review-evidence-selected', interaction: 'select an evidence observation', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: INSPECT_LATE_DIVERSE, probeWidths: [1600], expectText: ['Late diverse', 'Frame 78'] },
  { name: 'review-evidence-representative-only', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, probeWidths: [1600], api: { [`/api/tracks/${TRACK}`]: EVIDENCE_REPRESENTATIVE_ONLY }, expectText: ['Evidence Set', 'Representative'], forbidText: ['Near view', 'No image'] },
  { name: 'review-evidence-crop-unavailable', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, probeWidths: [1600], api: { [`/api/tracks/${TRACK}`]: EVIDENCE_CROP_UNAVAILABLE, ...UNAVAILABLE_CROP }, expectText: ['Near view', 'No image'] },
  { name: 'review-evidence-legacy', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated',  api: { [`/api/tracks/${TRACK}`]: EVIDENCE_LEGACY }, expectText: ['No Evidence Set was persisted for this Track.'], forbidText: ['No image'] },
  // Geometry that cannot be loaded must not fall back to the active revision.
  { name: 'review-geometry-unavailable', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/cameras/11111111-1111-7111-8111-111111111111/scene/revisions': 'unavailable' }, expectText: ['could not be loaded'] },
  { name: 'review-analytics-unavailable', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': SINGLE_SAMPLE_TRACK }, expectText: ['trajectory_too_short'] },
  { name: 'review-analytics-pending', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_ANALYTICS_PENDING }, expectText: ['has not been analysed yet'] },
  // Slice 7: a historical identity, pinned by the link a historical search makes.
  { name: 'review-historical-revision', path: `/review/video/${VIDEO}?trackId=${TRACK}&sceneRevisionId=${HISTORICAL_REVISION_ID}&analyticsAlgorithmVersion=scene-analytics-v1`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, requireOverlay: true, api: { [`/api/tracks/${TRACK}`]: HISTORICAL_TRACK_DETAIL, [`/api/cameras/${CAM}/scene/revisions/3`]: HISTORICAL_REVISION }, expectText: ['Scene revision 3'], forbidText: ['Scene revision 4 ·'] },
  { name: 'review-analytics-stale', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_ANALYTICS_STALE }, expectText: ['earlier revision or engine'] },
  // Two separate runs of concurrency: the rail must aggregate each span on
  // its own terms rather than stating one total for the whole timeline.
  { name: 'review-overflow-spans', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SPANS } },
  // Nothing separates visits that begin at the same instant, so the span is
  // the only honest unit: one band, its own count, and a route to each visit.
  { name: 'review-overflow-same-start', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SAME_START } },
  // One overflowed visit singled out through the disclosure: the recovery path
  // is captured in the state it leaves the rail in, not only asserted.
  { name: 'review-overflow-selected', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SHOW_OVERFLOWED, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SAME_START } },
  // Five crossings at one millisecond: one destination, so one control — which
  // has to carry all five names or four of them become unreachable.
  { name: 'review-markers-same-offset', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_MARKERS_SAME_OFFSET }, expectText: ['5 crossings'] },
  // The directed diagonal line over letterboxed and pillarboxed footage: the
  // perpendicular is measured in projected space, where the operator sees it.
  { name: 'review-direction-letterbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'letterbox', prepare: SEEK, requireOverlay: true, expectText: ['Inbound', 'Outbound'] },
  { name: 'review-direction-pillarbox', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'pillarbox', prepare: SEEK, requireOverlay: true, expectText: ['Inbound', 'Outbound'] },
  // Density that rises and falls inside one contiguous run: the rail has to
  // show that profile rather than one flat count for the whole run.
  { name: 'review-overflow-bridging', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_BRIDGING } },
  // A hundred overlapping visits: bounded height, bounded controls, and the
  // navigator still names one of them exactly.
  { name: 'review-overflow-crowd', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SEEK, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_CROWD } },
  { name: 'review-overflow-crowd-stepped', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SHOW_OVERFLOWED_LATER, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_CROWD } },
  // A member other than the first, so the captured state is not only ever
  // "1 of N" and the exact interval drawn is one from the middle of the run.
  { name: 'review-overflow-stepped', path: `/review/video/${VIDEO}?trackId=${TRACK}`, fullWidth: true, archetype: 'review', footage: 'saturated', prepare: SHOW_OVERFLOWED_LATER, api: { '/api/tracks/55555550-5555-7555-8555-555555555550': REVIEW_OVERFLOW_SAME_START } },

  // --- Workbench: Analytics, added in Scene Analytics Slice 6. -----------
  //
  // The states that matter here are the ones where the surface must refuse to
  // draw. Every other MAVI surface can show an empty result; this one cannot,
  // because an empty chart or an empty map is itself a claim about the world.
  {
    name: 'analytics-activity', atTier: { C: { expectText: ['needs a display at least 768px wide', 'Revision'] } }, path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    expectText: ['Coverage complete', 'Active Tracks'],
  },
  {
    // The camera unreadable: named by its shortened identifier, never by the
    // full GUID the crumb used to show (§5, §14). The override is a prefix, so
    // the camera's analytics fail with it.
    name: 'analytics-camera-unavailable', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, api: { [`/api/cameras/${CAM}`]: 'unavailable' },
    expectText: ['Camera 11111111…'], forbidText: CAM,
  },
  {
    // Occupancy: a reading taken at an instant, with its peak and the moment it
    // happened, and the "Not additive" tag that stops a reader summing it.
    name: 'analytics-occupancy', tierPolicy: 'workbench-variant', interaction: 'choose the zone occupancy report', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: OCCUPANCY_METRIC,
    expectText: ['Peak occupancy', 'Not additive'],
  },
  {
    // Two series in one chart: a trip line's directions, told apart by the
    // operator's own labels as well as by hue.
    name: 'analytics-line-crossings', tierPolicy: 'workbench-variant', interaction: 'choose the line crossings report', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: LINE_METRIC,
    expectText: ['Inbound', 'Outbound'],
  },
  {
    // M4 (CI): the bucket table's series headings under wide typography. CI
    // renders in its DejaVu fallback, where "Outbound" on one line is wider
    // than its column at 1366 and 1440; `.table th.num` held the heading to
    // one line, past the analytics table's own wrapping rule. The wide stack is
    // scoped to the table (test pressure on the element under test, not
    // product CSS), and the pressure is measured from rendered widths, never
    // read from the declared family list: the state refuses to report itself
    // reached where the rendered heading would fit on one line anyway.
    // text.overflow then judges the heading.
    name: 'analytics-line-crossings-wide-font', interaction: 'choose the line crossings report', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench', tierPolicy: 'typography-variant',
    prepare: `(async () => {
      ${UNTIL}
      const style = document.createElement('style');
      style.textContent = '.analytics-table, .analytics-table * { font-family: ${QUEUE_WIDE_FONT} !important; }';
      document.head.appendChild(style);
      if (!(await ${LINE_METRIC})) return false;
      const heading = await until(() => Array.from(document.querySelectorAll('.analytics-table thead th'))
        .find((th) => th.textContent.trim() === 'Outbound'), 'the Outbound heading');
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      // The pressure, measured: the heading's text on one line, in the font
      // actually rendered, against the room its column gives it.
      const probe = document.createElement('span');
      probe.style.whiteSpace = 'nowrap';
      probe.textContent = heading.textContent;
      heading.textContent = '';
      heading.appendChild(probe);
      const needed = probe.getBoundingClientRect().width;
      heading.textContent = probe.textContent;
      const cs = getComputedStyle(heading);
      const room = heading.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      if (needed <= room) throw new Error('the rendered typography is not wide enough to pressure the heading (' + Math.round(needed) + 'px in ' + Math.round(room) + 'px)');
      return true;
    })()`,
    expectText: ['Inbound', 'Outbound'],
  },
  {
    // The frozen rule, rendered: an incomplete scope draws nothing at all.
    name: 'analytics-incomplete', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/analytics/aggregates`]: INCOMPLETE_AGGREGATES },
    expectText: ['Not every run in this window has been analysed', 'Coverage incomplete'],
  },
  {
    // Its counterpart: complete, and genuinely zero. This one is an
    // observation and is drawn as one.
    name: 'analytics-complete-zero', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/analytics/aggregates`]: ZERO_AGGREGATES },
    expectText: ['Coverage complete'],
  },
  {
    name: 'analytics-no-scene', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/analytics/aggregates`]: NO_SCENE_AGGREGATES },
    // F25: not configured is its own condition, never partial coverage.
    expectText: ['No scene configured', 'Configure the scene'],
    forbidText: 'Coverage incomplete',
  },
  {
    // F25: analytics disabled by the scene — a domain state, not a shortfall.
    name: 'analytics-disabled', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/analytics/aggregates`]: DISABLED_AGGREGATES },
    expectText: ['Analytics disabled by the scene', 'Analytics disabled'],
    forbidText: 'Coverage incomplete',
  },
  {
    // Codex P1: no runs under a disabled revision is still "analytics
    // disabled", read from the scene, never a complete zero.
    name: 'analytics-disabled-empty-window', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: {
      [`/api/cameras/${CAM}/analytics/aggregates`]: EMPTY_WINDOW_AGGREGATES,
      [`/api/cameras/${CAM}/scene`]: DISABLED_SCENE,
    },
    expectText: ['Analytics disabled by the scene', 'No processing runs in this time window'],
    forbidText: 'Coverage complete',
  },
  {
    // Cold review F1: an empty window whose revision the scene confirms enables
    // analytics is a real, complete zero.
    name: 'analytics-enabled-empty-window', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: {
      [`/api/cameras/${CAM}/analytics/aggregates`]: EMPTY_WINDOW_AGGREGATES,
      [`/api/cameras/${CAM}/scene`]: ENABLED_SCENE,
    },
    expectText: ['Coverage complete', 'No processing runs in this time window'],
    forbidText: 'Analytics unconfirmed',
  },
  {
    // Cold review F1: the scene still being read — no zero until it has.
    name: 'analytics-unconfirmed-scene-loading', atTier: { C: { expectText: ['Reading the camera'] } }, path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench', holds: 'loading',
    api: {
      [`/api/cameras/${CAM}/analytics/aggregates`]: EMPTY_WINDOW_AGGREGATES,
      [`/api/cameras/${CAM}/scene`]: 'hang',
    },
    expectText: ['Reading the camera', 'Analytics unconfirmed'],
    forbidText: 'Coverage complete',
  },
  {
    // Cold review F1: the scene unreadable — said, with its Retry, and no zero.
    name: 'analytics-unconfirmed-scene-unavailable', atTier: { C: { expectText: ['The camera or its scene could not be read.'] } }, path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: {
      [`/api/cameras/${CAM}/analytics/aggregates`]: EMPTY_WINDOW_AGGREGATES,
      [`/api/cameras/${CAM}/scene`]: 'unavailable',
    },
    expectText: ['whether analytics were enabled', 'Retry', 'Analytics unconfirmed'],
    forbidText: 'Coverage complete',
  },
  {
    // Cold review F2: an emptied From refuses the query; the last answer is
    // not presented as the answer to it.
    name: 'analytics-window-invalid-draft', tierPolicy: 'workbench-variant', interaction: 'empty the From field', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: EMPTY_FROM,
    expectText: ['Adjust the window'],
    forbidText: 'Coverage complete',
  },
  {
    // F24: the bucket table scrolled under its header, judged by geometry.
    name: 'analytics-bucket-table-scrolled', tierPolicy: 'workbench-variant', interaction: 'scroll the bucket table', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: SCROLL_BUCKET_TABLE,
    expectText: ['Coverage complete', 'Active Tracks'],
  },
  {
    // F22: a refused window, stated on the field that repairs it.
    name: 'analytics-window-refused', tierPolicy: 'workbench-variant', interaction: 'choose a one-minute interval over a day', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: REFUSE_WINDOW,
    expectText: ['the most that can be shown is 512'],
  },
  {
    name: 'analytics-unavailable', tierPolicy: 'workbench-variant', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    api: { [`/api/cameras/${CAM}/analytics/aggregates`]: 'unavailable' },
    // The server's own words, and the way out beside them.
    expectText: ['did not respond', 'Retry'],
  },
  // The map itself. Slice 6 composites over the neutral matte that plan 9.2
  // allows rather than a reference frame, so there are deliberately no
  // footage-condition variants here: without a frame underneath they would
  // capture identical pixels and assert nothing. Decision 2c's footage
  // measurements are made analytically instead, and re-derived in
  // `contrast.test.ts`.
  {
    name: 'analytics-heatmap', tierPolicy: 'workbench-variant', interaction: 'switch to the heatmap', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: HEATMAP_MODE,
    expectText: ['Trajectory sample density — not people density, and not a probability or a prediction.', '64 × 36'],
  },
  {
    // The refusal that names its bound. A map is never drawn for a scope the
    // server would not open.
    name: 'analytics-heatmap-too-large', tierPolicy: 'workbench-variant', interaction: 'switch to the heatmap', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: HEATMAP_MODE,
    api: {
      [`/api/cameras/${CAM}/analytics/heatmap`]: {
        status: 422,
        body: {
          title: 'Heatmap scope is too large',
          detail: 'The requested scope exceeds a bounded dimension.',
          code: 'analytics_heatmap_scope_too_large',
          dimension: 'candidateTracks',
          limit: 2000,
        },
      },
    },
    expectText: ['This window covers too much to map', '2,000 analysed Tracks'],
  },
  {
    // Evidence that could not be read: no partial map, and no storage key.
    name: 'analytics-heatmap-evidence-unreadable', tierPolicy: 'workbench-variant', interaction: 'switch to the heatmap', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: HEATMAP_MODE,
    api: {
      [`/api/cameras/${CAM}/analytics/heatmap`]: {
        status: 503,
        body: {
          title: 'Evidence unreadable',
          detail: 'Trajectory evidence for an analysed Track could not be read.',
          code: 'analytics_evidence_unreadable',
        },
      },
    },
    expectText: ['not where anything went'],
  },
  {
    // Slice 7: the sparse end of the density scale.
    name: 'analytics-heatmap-sparse', tierPolicy: 'workbench-variant', interaction: 'switch to the heatmap', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: HEATMAP_MODE,
    api: { [`/api/cameras/${CAM}/analytics/heatmap`]: SPARSE_HEATMAP },
    expectText: ['11 samples from 1 Track', 'The busiest cell holds 7 samples'],
  },
  {
    // F25: the map's no-scene state in the same vocabulary as Activity's.
    name: 'analytics-heatmap-no-scene', tierPolicy: 'workbench-variant', interaction: 'switch to the heatmap', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: HEATMAP_MODE,
    api: { [`/api/cameras/${CAM}/analytics/heatmap`]: NO_SCENE_HEATMAP },
    expectText: ['No scene configured', 'Configure the scene'],
    forbidText: ['Coverage incomplete', 'Not every run in this window has been analysed'],
  },
  {
    // Cold review F1, Heatmap independently: an empty map is not drawn while
    // the scene that would confirm its revision is unreadable.
    name: 'analytics-heatmap-unconfirmed-scene-unavailable', tierPolicy: 'workbench-variant', interaction: 'switch to the heatmap', path: `/cameras/${CAM}/analytics`,
    fullWidth: true, archetype: 'workbench',
    prepare: HEATMAP_MODE,
    api: {
      [`/api/cameras/${CAM}/analytics/heatmap`]: EMPTY_WINDOW_HEATMAP,
      [`/api/cameras/${CAM}/scene`]: 'unavailable',
    },
    expectText: ['whether analytics were enabled', 'Analytics unconfirmed'],
    forbidText: ['Coverage complete', 'No samples fell inside this window'],
  },
];

/**
 * T1 (§25 Tier B, 1101-1365): the band between the stacking threshold and the
 * workstation, which neither Tier B anchor (1024, 768) reaches. Each surface's
 * representative states are probed at its lower edge, the 1200 spot check the
 * register names, and its upper edge, so the side-by-side half of every Tier B
 * rule — the Investigation rail in place, the Record facts rail at 280px or
 * more, the Review rail beside a 65% player and its pin — is evaluated, not
 * passed for want of a width. (The Scene Editor has its own threshold probes.)
 */
const COMPACT_PROBE_BASES = [
  'overview', 'videos', 'cameras', 'processing-queue', 'import', 'processing-detail-completed',
  'processing-detail-long-identity', 'analytics-activity', 'search', 'search-inspecting', 'review', 'review-long-identity',
];
for (const name of COMPACT_PROBE_BASES) {
  const base = STATES.find((state) => state.name === name);
  if (!base) throw new Error(`compact probe of an unknown state ${name}`);
  STATES.push({ ...base, name: `${name}-compact-band`, tierPolicy: 'breakpoint-probe', probeOf: name, probeWidths: [1101, 1200, 1365] });
}

/**
 * T2 (§25 Tier C): every width of the tier is Tier C — the old 760px narrow
 * shell left 761-767 composed for Tier B — and 768 is Tier B again. Each
 * representative state is probed across the tier and on both sides of its
 * lower edge: 600 inside it, 760/761 at the retired threshold, 767/768 at
 * the tier boundary.
 */
const NARROW_PROBE_BASES = [
  'overview', 'videos', 'cameras', 'processing-queue', 'import', 'processing-detail-failed',
  'scene-editor', 'analytics-activity', 'search', 'search-inspector-opened', 'review', 'review-long-identity',
];
for (const name of NARROW_PROBE_BASES) {
  const base = STATES.find((state) => state.name === name);
  if (!base) throw new Error(`narrow probe of an unknown state ${name}`);
  STATES.push({ ...base, name: `${name}-narrow-band`, tierPolicy: 'breakpoint-probe', probeOf: name, probeWidths: [600, 760, 761, 767, 768] });
}
