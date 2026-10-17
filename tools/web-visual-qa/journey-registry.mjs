/**
 * X2 (plan §5.3): the six frozen operator journeys, as the product has them,
 * and after them the journeys a later plan appends (Stage 4 PR-5's plate
 * journey).
 *
 * Each journey names its starting route (the one direct load), the backend it
 * runs against (fixture overrides, answered by the fixture server as the
 * application asks: `{ after }` flips only when the operator's own request
 * arrives, `{ query }` answers the request the operator caused), and its
 * steps — written against the operator object alone (journeys.mjs
 * `createOperator`): keys, Tab to a named control, checkpoints. Nothing here
 * clicks, focuses, navigates or writes application state; a test reads this
 * file's source to keep it so (test/journeys.test.mjs).
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { EXACT_PLATE_PAGE, PLATE_DETAILS, PLATE_TEXT, PLATE_TRACK } from './plate-fixtures.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const fixture = (name) => JSON.parse(readFileSync(join(HERE, 'fixtures', `${name}.json`), 'utf8'));

const CAM = '11111111-1111-7111-8111-111111111111';
const PROCESSED = '22222222-2222-7222-8222-222222222222';
const RUNNING = '44444444-4444-7444-8444-444444444444';
const FAILED = '55555555-5555-7555-8555-555555555555';

// --- Journey 5's backend: a dense, real-looking estate ----------------------------

/** Twenty-four cameras, the fixture's own CAM-01 among them, each with an inventory record. */
const DENSE_CAMERAS = (() => {
  const base = fixture('cameras');
  const extra = Array.from({ length: 22 }, (_, i) => ({
    ...base[0],
    id: `11111111-0000-7000-8000-${String(100 + i).padStart(12, '0')}`,
    code: `CAM-${String(i + 3).padStart(2, '0')}`,
    name: ['Loading dock', 'Visitor car park', 'East gate', 'Warehouse aisle', 'Fuel bay', 'Canteen yard'][i % 6] + ` ${Math.floor(i / 6) + 1}`,
    isActive: i % 7 !== 4,
  }));
  return [...base, ...extra];
})();

/** The fixture's four videos and twenty more, every one with its run status. */
const DENSE_ESTATE = (() => {
  const base = fixture('videos');
  const runs = Object.fromEntries(base.map((v) => [v.id, fixture(`videos_${v.id}_processing`)]));
  const kinds = [[PROCESSED, 'Processed'], [RUNNING, 'Processing'], [FAILED, 'Failed']];
  const extra = Array.from({ length: 20 }, (_, i) => {
    const [from, status] = kinds[i % 3];
    const template = base.find((v) => v.id === from);
    const id = `22222222-0000-7000-8000-${String(100 + i).padStart(12, '0')}`;
    return {
      video: { ...template, id, originalFileName: `perimeter-${String(i + 1).padStart(2, '0')}-${['0600', '1200', '1800'][i % 3]}.mp4`, processingStatus: status, importedAtUtc: `2026-09-${String(10 + (i % 18)).padStart(2, '0')}T0${i % 9}:00:00Z` },
      run: runs[from],
    };
  });
  const videos = [...base, ...extra.map((e) => e.video)];
  // `/api/videos` answers its sub-paths too: the fixture's own videos keep
  // their own records and run statuses.
  const api = { '/api/videos': videos, ...Object.fromEntries(base.map((v) => [`/api/videos/${v.id}`, 'fixture'])) };
  for (const e of extra) {
    api[`/api/videos/${e.video.id}`] = e.video;
    api[`/api/videos/${e.video.id}/processing`] = e.run;
  }
  return api;
})();

// --- Journey 6's backend: a continuation that fails, then recovers -----------------

const TRACKS = fixture('tracks');
/** The first page: the fixture's six Tracks, with a cursor to a second. */
const PAGE_ONE = { ...TRACKS, nextCursor: 'journey-cursor-2', totalCount: 12 };
/** The second page: six more Tracks (their own ids), the end of the snapshot. */
const PAGE_TWO = {
  items: TRACKS.items.map((t, i) => ({ ...t, id: `55555551-5555-7555-8555-${String(600 + i).padStart(12, '0')}`, startOffsetMs: t.startOffsetMs + 300000, endOffsetMs: t.endOffsetMs + 300000 })),
  nextCursor: null, totalCount: 12,
};

// --- Journey 2's backend: a search the operator narrows to people ------------------

const TRACK_ONE = '55555550-5555-7555-8555-555555555550';
const DETAIL_ONE = fixture(`tracks_${TRACK_ONE}`);
const PEOPLE = TRACKS.items.filter((t) => t.objectClass === 'Person');
/** Every person Track opens in the inspector (the fixture has one detail; the others are it, renumbered). */
const PEOPLE_DETAILS = Object.fromEntries(PEOPLE.map((t, i) => [
  `/api/tracks/${t.id}`,
  t.id === TRACK_ONE ? 'fixture' : { ...DETAIL_ONE, id: t.id, localTrackNumber: DETAIL_ONE.localTrackNumber + i * 2 },
]));

// --- Journey 3's backend: vehicles, two of which the server refines as cars -------

const CAR_ONE = '55555551-5555-7555-8555-555555555551';
const CAR_TWO = '55555555-5555-7555-8555-555555555555';
const WITH_CARS = TRACKS.items.map((t) => ([CAR_ONE, CAR_TWO].includes(t.id) ? { ...t, objectSubclass: 'car' } : t));
const VEHICLES = WITH_CARS.filter((t) => t.objectClass === 'Vehicle');
const CARS = VEHICLES.filter((t) => t.objectSubclass === 'car');
const page = (items) => ({ ...TRACKS, items, totalCount: items.length });
const CAR_DETAILS = Object.fromEntries(CARS.map((t, i) => [
  `/api/tracks/${t.id}`,
  { ...DETAIL_ONE, id: t.id, objectClass: 'Vehicle', objectSubclass: 'car', localTrackNumber: 2 + i * 4 },
]));

// --- Journey 1's backend: an import, its processing, its results ------------------

const IMPORTED = '77777777-7777-7777-8777-777777777777';
const IMPORTED_VIDEO = { ...fixture(`videos_${PROCESSED}`), id: IMPORTED, originalFileName: 'north-gate-0800.mp4', processingStatus: 'Imported' };
const PROCESS_REQUEST = `POST /api/videos/${IMPORTED}/process`;
const COMPLETED_RUN = fixture(`videos_${PROCESSED}_processing`);
const NEW_RUN = 'dddddddd-dddd-7ddd-8ddd-dddddddddddd';
const RUNNING_RUN = { videoStatus: 'Processing', latestRun: { ...COMPLETED_RUN.latestRun, processingRunId: NEW_RUN, status: 'Running', completedAtUtc: null, progressPercent: 40, framesProcessed: 6000, tracksCreated: 0, analyticsReadiness: 'NotConfigured' } };
const DONE_RUN = { ...COMPLETED_RUN, latestRun: { ...COMPLETED_RUN.latestRun, processingRunId: NEW_RUN } };
const IMPORTED_TRACKS = { ...TRACKS, items: TRACKS.items.map((t) => ({ ...t, videoAssetId: IMPORTED, videoContentUrl: `/api/videos/${IMPORTED}/content` })) };

// --- Journey 4's backend: a scene revision, its analysis, its analytic results ----

const SCENE = fixture(`cameras_${CAM}_scene`);
const REV4 = SCENE.activeRevision;
const REV5_ID = '66666666-6666-7666-8666-666666666667';
const WEIGHBRIDGE = 'abababab-abab-7bab-8bab-abababababab';
/** Where the operator's keys place the zone: from the frame's centre, Shift+arrows (0.1). */
const WEIGHBRIDGE_VERTICES = [{ x: 0.7, y: 0.5 }, { x: 0.8, y: 0.5 }, { x: 0.8, y: 0.6 }, { x: 0.7, y: 0.6 }];
const REV5 = {
  ...REV4, revisionId: REV5_ID, revisionNumber: 5, createdAtUtc: '2026-10-11T06:00:00Z', note: null,
  zones: [...REV4.zones, { zoneId: WEIGHBRIDGE, name: 'Weighbridge', kind: 'General', enabled: true, loiteringThresholdSeconds: null, vertices: WEIGHBRIDGE_VERTICES }],
};
const SCENE5 = {
  ...SCENE, activeRevision: REV5,
  history: [{ revisionId: REV5_ID, revisionNumber: 5, createdAtUtc: REV5.createdAtUtc, createdBy: 'operator', note: null, analyticsEnabled: true, zoneCount: REV5.zones.length, tripLineCount: REV5.tripLines.length }, ...SCENE.history],
};
const SAVE = `PUT /api/cameras/${CAM}/scene`;
const ANALYSE = `POST /api/cameras/${CAM}/scene/analyses`;
const RUN = COMPLETED_RUN.latestRun.processingRunId;
const RUN_ANALYTICS = fixture(`processing_runs_${RUN}_analytics`);
const runWith = (readiness) => ({ ...COMPLETED_RUN, latestRun: { ...COMPLETED_RUN.latestRun, analyticsReadiness: readiness } });
const analysis = (status, extra = {}) => ({ ...RUN_ANALYTICS.analyses[0], analysisId: 'aaaaaaa5-aaaa-7aaa-8aaa-aaaaaaaaaaa5', sceneRevisionId: REV5_ID, sceneRevisionNumber: 5, status, ...extra });
const RUN_STALE = { ...RUN_ANALYTICS, readiness: 'Stale', activeSceneRevisionId: REV5_ID, analyses: [{ ...RUN_ANALYTICS.analyses[0], status: 'Superseded' }] };
const RUN_PENDING = { ...RUN_ANALYTICS, readiness: 'Pending', activeSceneRevisionId: REV5_ID, analyses: [analysis('Running', { completedAtUtc: null })] };
const RUN_READY = { ...RUN_ANALYTICS, readiness: 'Ready', activeSceneRevisionId: REV5_ID, analyses: [analysis('Completed', { completedAtUtc: '2026-10-11T06:01:00Z' })] };
const COVERAGE5 = { sceneRevisionId: REV5_ID, algorithmVersion: 'scene-analytics-v1', evaluatedRuns: 1, pendingRuns: 0, failedRuns: 0, notConfiguredRuns: 0, disabledRuns: 0, staleRuns: 0, analysedTracks: 6, unavailableTracks: 0, complete: true };
const IN_WEIGHBRIDGE = {
  ...TRACKS, totalCount: 1, nextCursor: null, analyticsCoverage: COVERAGE5,
  items: [{ ...TRACKS.items[0], analytics: { sceneRevisionId: REV5_ID, algorithmVersion: 'scene-analytics-v1', zones: [{ zoneId: WEIGHBRIDGE, visitCount: 1, totalDwellMs: 1800, loitering: false }], lines: [], motion: null } }],
};
const ANALYTICS_ONE = DETAIL_ONE.analytics;
const DETAIL_IN_WEIGHBRIDGE = {
  ...DETAIL_ONE,
  analytics: {
    ...ANALYTICS_ONE, sceneRevisionId: REV5_ID, sceneRevisionNumber: 5,
    zoneSummaries: [{ ...ANALYTICS_ONE.zoneSummaries[0], zoneId: WEIGHBRIDGE, totalDwellMs: 1800, loiteringThresholdSeconds: null }],
    zoneVisits: [{ ...ANALYTICS_ONE.zoneVisits[0], zoneId: WEIGHBRIDGE, dwellMs: 1800, exitOffsetMs: 2400 }],
    lineCrossings: [],
  },
};

// --- Stage 4 PR-5's backend: a plate search, its Track, its source seek ----------

/** Only the operator's exact plate search is answered with the candidate (plate-fixtures.mjs). */
const PLATE_SEARCH = { query: [{ match: { objectClass: 'Vehicle', plateText: PLATE_TEXT, plateMatch: 'exact' }, then: EXACT_PLATE_PAGE }], otherwise: TRACKS };

// --- The journeys ------------------------------------------------------------------

const REGISTERED = [
  {
    id: 'plate-search-inspect-seek',
    title: 'Plate search → inspect → seek',
    start: '/search',
    // Stage 4 plan PR-5 (Tests): Plate text, Exact, Search; the candidate's
    // coverage and "Read as" line; inspect its plate readings; "View source at"
    // seeks the one player to the source Observation; a manual crop choice
    // afterwards inspects without seeking.
    api: { '/api/tracks': PLATE_SEARCH, [`/api/tracks/${PLATE_TRACK}`]: PLATE_DETAILS.consistent },
    ready: 'document.querySelectorAll(".result-select").length === 6',
    async run(op) {
      const drawerFilters = op.viewport.width <= 1100;
      if (drawerFilters) {
        await op.tabTo({ name: 'Filters', role: 'button' }, { note: 'the results header opens the filter drawer (§25 Tier B)' });
        await op.press('Enter', { expectFocus: { name: 'Filters', role: 'heading' } });
      }
      // The plate, as an operator would type it, matched exactly.
      await op.tabTo({ name: 'Plate text', role: 'textbox' }, { max: 40 });
      await op.type('zz-00-ts-0001');
      await op.until('the field holds what was typed', 'Array.from(document.querySelectorAll("input")).some((i) => i.labels?.[0]?.textContent.trim() === "Plate text" && i.value === "zz-00-ts-0001") && "zz-00-ts-0001"');
      await op.tabTo({ name: 'Exact', within: 'Plate match' }, { max: 10, note: 'the match control' });
      await op.press('Enter', { note: 'match the whole text' });
      await op.until('Exact is the pressed match', 'Array.from(document.querySelectorAll("[role=group][aria-label=\'Plate match\'] button")).some((b) => b.textContent.trim() === "Exact" && b.getAttribute("aria-pressed") === "true") && "Exact pressed"');
      await op.tabTo({ name: 'Search', role: 'button' }, { max: 40, note: 'the form\'s submit' });
      await op.press('Enter', { note: 'search for the plate' });
      await op.requested('the search asked for the normalised text, exactly, on vehicles', 'GET', /^\/api\/tracks$/, { query: { objectClass: 'Vehicle', plateText: PLATE_TEXT, plateMatch: 'exact' } });
      await op.until('one candidate, read as the text, beneath its coverage', `(() => { const t = document.body.innerText; return document.querySelectorAll(".result-select").length === 1 && /Plate readings available for 3 of 5 vehicle tracks in scope · 1 pending/.test(t) && /Read as ${PLATE_TEXT} · on 3 of 3 plates · 97%/.test(t) && /plateText=${PLATE_TEXT}/.test(location.search) && /plateMatch=exact/.test(location.search) && "1 candidate · 3 of 5 covered"; })()`);
      if (drawerFilters) await op.press('Escape', { expectFocus: { name: 'Filters', role: 'button' } });
      // Inspect: the result's name carries the reading's support and confidence.
      await op.tabTo({ name: new RegExp(`^Select Vehicle · CAM-01 · North Gate · Read as ${PLATE_TEXT} · on 3 of 3 plates · 97%$`), role: 'button' }, { max: 40, note: 'the candidate' });
      await op.press('Enter', { note: 'inspect it' });
      await op.route('the candidate is selected', new RegExp(`[?&]track=${PLATE_TRACK}`));
      await op.until('its plate readings are shown, each region drawn from its source crop', '(() => { const s = document.querySelector("section[aria-label=\'Plate readings\']"); if (!s) return false; const drawn = Array.from(s.querySelectorAll("canvas[role=img]")).filter((c) => !c.hidden && c.width > 0); return /Consistent readings/.test(s.innerText) && !/Loading plate image|No image/.test(s.innerText) && drawn.length === 3 && drawn.length + " regions drawn · consistent"; })()');
      // Seek: the plate's source Observation, in the one player.
      await op.tabTo({ name: 'View source at 00:02.2', role: 'button' }, { max: 60, note: 'the near-view plate\'s source' });
      await op.press('Enter', { note: 'view the source' });
      await op.until('the player is at the source Observation (2.2 s), and its crop is inspected', '(() => { const v = document.querySelector("video"); const f = document.querySelector("figure.evidence-set__inspection"); return v && Math.abs(v.currentTime - 2.2) < 0.05 && f && /^Inspecting Near view/.test(f.getAttribute("aria-label") || "") && "t=" + v.currentTime.toFixed(2) + " · " + f.getAttribute("aria-label"); })()');
      // A manual crop choice afterwards inspects that crop and does not seek.
      await op.tabTo({ name: /^Late diverse/, role: 'button', within: 'Evidence Set' }, { max: 30, note: 'another crop in the Evidence Set' });
      await op.press('Enter', { note: 'inspect it' });
      await op.until('the chosen crop is inspected and the player stayed at the source', '(() => { const v = document.querySelector("video"); const f = document.querySelector("figure.evidence-set__inspection"); return v && Math.abs(v.currentTime - 2.2) < 0.05 && f && /^Inspecting Late diverse/.test(f.getAttribute("aria-label") || "") && "t=" + v.currentTime.toFixed(2) + " · " + f.getAttribute("aria-label"); })()');
      // Every "View source at" press is a selection the Evidence Set inspects:
      // the same source again after the manual choice, then another, then back.
      await op.tabTo({ name: 'View source at 00:02.2', role: 'button' }, { reverse: true, max: 30, note: 'the same plate source again' });
      await op.press('Enter', { note: 'view the same source again' });
      await op.until('the same source is inspected again', '(() => { const v = document.querySelector("video"); const f = document.querySelector("figure.evidence-set__inspection"); return v && Math.abs(v.currentTime - 2.2) < 0.05 && f && /^Inspecting Near view/.test(f.getAttribute("aria-label") || "") && "t=" + v.currentTime.toFixed(2) + " · " + f.getAttribute("aria-label"); })()');
      await op.tabTo({ name: 'View source at 00:01.6', role: 'button' }, { reverse: true, max: 10, note: 'another plate source' });
      await op.press('Enter', { note: 'view the other source' });
      await op.until('the other source is inspected, the player at it (1.6 s)', '(() => { const v = document.querySelector("video"); const f = document.querySelector("figure.evidence-set__inspection"); return v && Math.abs(v.currentTime - 1.6) < 0.05 && f && /^Inspecting Representative/.test(f.getAttribute("aria-label") || "") && "t=" + v.currentTime.toFixed(2) + " · " + f.getAttribute("aria-label"); })()');
      await op.tabTo({ name: 'View source at 00:02.2', role: 'button' }, { max: 10, note: 'back to the first plate source' });
      await op.press('Enter', { note: 'view the first source again' });
      await op.done('back at the first source: the player and the inspected crop agree', '(() => { const v = document.querySelector("video"); const f = document.querySelector("figure.evidence-set__inspection"); return v && Math.abs(v.currentTime - 2.2) < 0.05 && f && /^Inspecting Near view/.test(f.getAttribute("aria-label") || "") && "t=" + v.currentTime.toFixed(2) + " · " + f.getAttribute("aria-label"); })()');
    },
  },
  {
    id: 'scene-analytic-why',
    title: 'Configure scene → analyse → search analytic → why matched → inspect',
    start: `/cameras/${CAM}/scene`,
    // Revision 5 exists only once the operator's save reached the backend;
    // the camera's runs go stale with it, and are analysed only once the
    // operator asks; the analytic answer is the request their filter caused.
    api: {
      [SAVE]: REV5,
      [ANALYSE]: { cameraId: CAM, sceneRevisionId: REV5_ID, algorithmVersion: 'scene-analytics-v1', scope: 'latestRuns', created: 1, alreadyQueued: 0, alreadyRunning: 0, alreadyReady: 0, failedRequiresRetry: 0, alreadySuperseded: 0, runsInScope: 1 },
      [`/api/cameras/${CAM}/scene`]: { after: SAVE, before: 'fixture', then: SCENE5 },
      [`/api/cameras/${CAM}/scene/revisions/4`]: 'fixture',
      [`/api/cameras/${CAM}/scene/revisions/5`]: { after: SAVE, before: { status: 404, body: {} }, then: REV5 },
      [`/api/videos/${PROCESSED}/processing`]: { after: SAVE, before: 'fixture', then: { after: ANALYSE, before: runWith('Stale'), then: { sequence: [runWith('Pending'), runWith('Ready')] } } },
      [`/api/processing/runs/${RUN}/analytics`]: { after: SAVE, before: 'fixture', then: { after: ANALYSE, before: RUN_STALE, then: { sequence: [RUN_PENDING, RUN_READY] } } },
      '/api/tracks': { query: [{ match: { zoneId: WEIGHBRIDGE }, then: IN_WEIGHBRIDGE }], otherwise: TRACKS },
      [`/api/tracks/${TRACK_ONE}`]: { after: ANALYSE, before: 'fixture', then: DETAIL_IN_WEIGHBRIDGE },
    },
    ready: 'Boolean(document.querySelector("[data-testid=scene-canvas]")) && /Loading bay/.test(document.body.innerText) && Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Zone")',
    async run(op) {
      // Configure: a new zone, drawn and named from the keyboard.
      await op.tabTo({ name: 'Zone', within: 'Drawing tools' }, { max: 60, note: 'the drawing tools\' Zone' });
      await op.press('Enter', { note: 'arm the Zone tool' });
      await op.tabTo({ name: /^Scene frame, drawing a zone/, role: 'group' }, { max: 20, note: 'the frame, a keyboard surface with a tool armed' });
      await op.press('ArrowRight', { shift: true });
      await op.press('ArrowRight', { shift: true });
      await op.press(' ', { note: 'vertex 1 at (0.7, 0.5)' });
      await op.press('ArrowRight', { shift: true });
      await op.press(' ', { note: 'vertex 2 at (0.8, 0.5)' });
      await op.press('ArrowDown', { shift: true });
      await op.press(' ', { note: 'vertex 3 at (0.8, 0.6)' });
      await op.press('ArrowLeft', { shift: true });
      await op.press(' ', { note: 'vertex 4 at (0.7, 0.6)' });
      await op.press('Enter', { note: 'complete the zone' });
      await op.until('the zone is drawn where the keys put it, and selected', '(() => { const z = Array.from(document.querySelectorAll("[data-testid^=scene-zone-]")).find((g) => g.getAttribute("data-points") === "0.700000,0.500000 0.800000,0.500000 0.800000,0.600000 0.700000,0.600000"); return z && z.classList.contains("is-selected") && "zone at (0.7,0.5)-(0.8,0.6), selected"; })()');
      await op.tabTo({ name: 'Name', role: 'textbox' }, { max: 40, note: 'the zone\'s name' });
      for (let i = 0; i < 12; i += 1) await op.press('End');
      for (let i = 0; i < 12; i += 1) await op.press('Backspace');
      await op.type('Weighbridge');
      await op.until('the zone is named Weighbridge', '/Weighbridge/.test(document.body.innerText) && "Weighbridge"');
      await op.tabTo({ name: 'Save revision', role: 'button' }, { reverse: true, max: 60, note: 'the Context Bar\'s save' });
      await op.press('Enter', { note: 'save the revision' });
      await op.requested('the save carried the operator\'s zone, as drawn and named', 'PUT', new RegExp(`^/api/cameras/${CAM}/scene$`), {
        body: (b) => b.expectedRevisionNumber === 4 && b.zones.some((z) => z.name === 'Weighbridge' && !z.zoneId && JSON.stringify(z.vertices) === JSON.stringify(WEIGHBRIDGE_VERTICES)),
      });
      await op.until('revision 5 is the saved revision', '/Revision 5/.test(document.body.innerText) && /Saved/.test(document.body.innerText) && "Revision 5 · Saved"');
      // Analyse: the camera's processed video, re-analysed under revision 5.
      await op.tabTo({ name: 'Processing', role: 'link' }, { reverse: true, max: 80, note: 'the rail\'s Processing' });
      await op.press('Enter');
      await op.route('Processing is open', /^\/processing$/);
      await op.tabTo({ name: 'Processing detail for north-gate-0800.mp4', role: 'link' }, { max: 80, note: 'the processed video\'s detail' });
      await op.press('Enter');
      await op.route('its detail is open', new RegExp(`^/processing/${PROCESSED}$`));
      await op.until('its analytics are stale under the new revision', '/Stale/.test(document.body.innerText) && Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Re-analyse camera") && "Stale · Re-analyse camera offered"');
      await op.tabTo({ name: 'Re-analyse camera', role: 'button' }, { max: 40 });
      await op.press('Enter', { note: 're-analyse the camera' });
      await op.requested('the re-analysis was requested', 'POST', new RegExp(`^/api/cameras/${CAM}/scene/analyses$`));
      await op.until('the analysis ran under revision 5', '(() => { const t = document.body.innerText; return /Re-analysis requested/.test(t) && /Revision 5/.test(t) && !/Stale/.test(t) && "analysed with revision 5"; })()');
      // Search on the analytic: the new zone.
      await op.tabTo({ name: 'Open results', role: 'link' }, { reverse: true, max: 60 });
      await op.press('Enter');
      await op.route('Search opens on the video', new RegExp(`^/search\\?videoAssetId=${PROCESSED}`));
      await op.until('the zone filter offers the new zone', 'Array.from(document.querySelectorAll("select option")).some((o) => o.textContent.trim() === "Weighbridge" && !o.parentElement.disabled) && "Weighbridge offered"');
      const drawerFilters = op.viewport.width <= 1100;
      if (drawerFilters) {
        await op.tabTo({ name: 'Filters', role: 'button' }, { max: 40 });
        await op.press('Enter', { expectFocus: { name: 'Filters', role: 'heading' } });
      }
      await op.tabTo({ name: 'Zone', role: 'combobox' }, { max: 40 });
      await op.type('W');
      await op.tabTo({ name: 'Search', role: 'button' }, { max: 40 });
      await op.press('Enter', { note: 'search on the zone' });
      await op.requested('the search asked for Tracks in the new zone', 'GET', /^\/api\/tracks$/, { query: { zoneId: WEIGHBRIDGE } });
      await op.until('one Track matched', 'document.querySelectorAll(".result-select").length === 1 && "1 match"');
      if (drawerFilters) await op.press('Escape', { expectFocus: { name: 'Filters', role: 'button' } });
      // Why it matched, in the inspector.
      await op.tabTo({ name: /^Select Person · CAM-01/, role: 'button' }, { max: 40 });
      await op.press('Enter', { note: 'inspect the match' });
      await op.route('the match is selected', new RegExp(`[?&]track=${TRACK_ONE}`));
      await op.done('the inspector says why it matched: Weighbridge, under revision 5', '(() => { const s = Array.from(document.querySelectorAll("section, [role=region]")).find((e) => /^Scene analytics/i.test((e.querySelector("h2, h3")?.textContent ?? "").trim())); const t = s ? s.innerText : ""; return /Weighbridge/.test(t) && /revision 5/i.test(t) && "Scene analytics: Weighbridge, revision 5"; })()');
    },
  },
  {
    id: 'import-process-results',
    title: 'Import → Process → Status → Results',
    start: '/import',
    // Nothing of the new video exists until the operator's own requests: the
    // import answers with it; its status exists only once the operator's
    // workflow asked for processing, and then runs to completion.
    api: {
      'POST /api/videos/import': IMPORTED_VIDEO,
      [PROCESS_REQUEST]: { processingRunId: NEW_RUN },
      [`/api/videos/${IMPORTED}/processing`]: { after: PROCESS_REQUEST, before: { status: 404, body: {} }, then: { sequence: [RUNNING_RUN, RUNNING_RUN, RUNNING_RUN, DONE_RUN] } },
      [`/api/videos/${IMPORTED}`]: { after: PROCESS_REQUEST, before: IMPORTED_VIDEO, then: { sequence: [{ ...IMPORTED_VIDEO, processingStatus: 'Processing' }, { ...IMPORTED_VIDEO, processingStatus: 'Processed' }] } },
      '/api/tracks': { query: [{ match: { videoAssetId: IMPORTED }, then: IMPORTED_TRACKS }], otherwise: TRACKS },
    },
    ready: 'Boolean(document.querySelector("input[type=file]")) && Array.from(document.querySelectorAll("select option")).some((o) => /CAM-01/.test(o.textContent))',
    async run(op) {
      await op.tabTo({ name: 'Camera', role: 'combobox' }, { max: 40, note: 'the import form\'s first field' });
      await op.type('C');
      await op.until('Camera reads CAM-01', 'Array.from(document.querySelectorAll("select")).some((s) => /^CAM-01/.test(s.selectedOptions[0]?.textContent.trim() ?? "")) && "CAM-01"');
      await op.tabTo({ name: 'Recording local date/time' }, { note: 'the recording\'s local start' });
      await op.enterDateTime('2026-09-14T08:00', { note: 'segment by segment, in the order the field shows them' });
      await op.until('the recording start reads 14 Sept 2026, 08:00', '(() => { const i = document.querySelector("input[type=datetime-local]"); return i && i.value === "2026-09-14T08:00" && i.value; })()');
      await op.tabTo({ name: /MP4 file/ }, { note: 'the file field' });
      await op.chooseFile(op.upload('north-gate-0800.mp4'), { key: 'Enter' });
      await op.until('the form holds the chosen file', '/north-gate-0800\\.mp4/.test(document.body.innerText) && "north-gate-0800.mp4"');
      await op.tabTo({ name: 'Import and process', role: 'button' }, { note: 'the form\'s submit' });
      await op.press('Enter', { note: 'import and queue processing' });
      await op.requested('the file was imported', 'POST', /^\/api\/videos\/import$/);
      await op.requested('processing was queued for it', 'POST', new RegExp(`^/api/videos/${IMPORTED}/process$`));
      await op.route('the new video\'s processing status is open', new RegExp(`^/processing/${IMPORTED}$`));
      await op.until('its status is stated while it runs', '(() => { const t = document.body.innerText; return /north-gate-0800\\.mp4/.test(t) && /\\b40%/.test(t) && !Array.from(document.querySelectorAll("a")).some((a) => a.textContent.trim() === "Open results") && "running · 40%"; })()');
      await op.until('its processing completed, and its results are offered', '(() => { const l = Array.from(document.querySelectorAll("a")).find((a) => a.textContent.trim() === "Open results"); return l && /Processed|Completed/.test(document.body.innerText) && "Processed · Open results offered"; })()');
      await op.tabTo({ name: 'Open results', role: 'link' }, { max: 40 });
      await op.press('Enter');
      await op.route('Search opens on the new video', new RegExp(`^/search\\?videoAssetId=${IMPORTED}`));
      await op.requested('the search asked for the new video\'s Tracks', 'GET', /^\/api\/tracks$/, { query: { videoAssetId: IMPORTED } });
      await op.done('the imported video\'s results are listed', `(() => { const s = document.querySelectorAll(".result-select"); return s.length === 6 && /[?&]videoAssetId=${IMPORTED}(&|$)/.test(location.search) && "6 results for the imported video"; })()`);
    },
  },
  {
    id: 'vehicle-car-review',
    title: 'Vehicle search → Car refinement → inspect → Review',
    start: '/search',
    // The server's answer follows the committed filter: the refinement to cars
    // is the server's own (`objectSubclass=car`), never a client-side filter.
    api: {
      '/api/tracks': {
        query: [
          { match: { objectClass: 'Vehicle', objectSubclass: 'car' }, then: page(CARS) },
          { match: { objectClass: 'Vehicle' }, then: page(VEHICLES) },
        ],
        otherwise: page(WITH_CARS),
      },
      ...CAR_DETAILS,
    },
    ready: 'document.querySelectorAll(".result-select").length === 6',
    async run(op) {
      const drawerFilters = op.viewport.width <= 1100;
      if (drawerFilters) {
        await op.tabTo({ name: 'Filters', role: 'button' }, { note: 'the results header opens the filter drawer (§25 Tier B)' });
        await op.press('Enter', { expectFocus: { name: 'Filters', role: 'heading' } });
      }
      // Vehicles.
      await op.tabTo({ name: 'Object class', role: 'combobox' }, { max: 40 });
      await op.type('V');
      await op.tabTo({ name: 'Search', role: 'button' }, { max: 40, note: 'the form\'s submit' });
      await op.press('Enter', { note: 'search for vehicles' });
      await op.requested('the search asked for vehicles', 'GET', /^\/api\/tracks$/, { query: { objectClass: 'Vehicle' } });
      await op.until('the results are the three vehicles', '(() => { const s = Array.from(document.querySelectorAll(".result-select")); return s.length === 3 && s.every((b) => /^Select Vehicle/.test(b.getAttribute("aria-label"))) && "3 vehicles"; })()');
      // Refined to cars, back up the same form.
      await op.tabTo({ name: 'Vehicle type', role: 'combobox' }, { reverse: true, max: 40 });
      await op.type('C');
      await op.until('Vehicle type reads Car', 'Array.from(document.querySelectorAll("select")).some((s) => s.labels?.[0]?.textContent.trim() === "Vehicle type" && s.selectedOptions[0]?.textContent.trim() === "Car") && "Car"');
      await op.tabTo({ name: 'Search', role: 'button' }, { max: 40 });
      await op.press('Enter', { note: 'refine to cars' });
      await op.requested('the search asked the server for cars', 'GET', /^\/api\/tracks$/, { query: { objectClass: 'Vehicle', objectSubclass: 'car' } });
      await op.until('the results are the two cars, named as cars', '(() => { const s = Array.from(document.querySelectorAll(".result-select")); return s.length === 2 && s.every((b) => /^Select Vehicle · Car /.test(b.getAttribute("aria-label"))) && /objectSubclass=car/.test(location.search) && "2 cars"; })()');
      if (drawerFilters) await op.press('Escape', { expectFocus: { name: 'Filters', role: 'button' } });
      // Inspect the first car.
      await op.tabTo({ name: /^Select Vehicle · Car /, role: 'button' }, { max: 40 });
      await op.press('Enter', { note: 'select it; the inspector opens' });
      await op.route('the first car is selected', new RegExp(`[?&]track=${CAR_ONE}`));
      await op.until('the inspector names it Vehicle · Car', '/Vehicle · Car · Track 2/i.test(document.body.innerText) && "Vehicle · Car · Track 2"');
      // Its review.
      await op.tabTo({ name: 'Open', role: 'link' }, { max: 30, note: 'the inspector\'s Open' });
      await op.press('Enter');
      await op.route('the review of that car is open', new RegExp(`^/review/video/${PROCESSED}\?.*trackId=${CAR_ONE}`));
      await op.done('the review is of the car that was inspected', `(() => { const t = document.body.innerText; return /[?&]trackId=${CAR_ONE}(&|$)/.test(location.search) && /Track summary/.test(t) && /Vehicle · Car/i.test(t) && "Review: Vehicle · Car, track ${CAR_ONE}"; })()`);
    },
  },
  {
    id: 'search-inspect-evidence',
    title: 'Search → filter → scan → inspect → evidence → return',
    start: '/search',
    // Only the operator's committed filter narrows the list to people.
    api: { '/api/tracks': { query: [{ match: { objectClass: 'Person' }, then: { ...TRACKS, items: PEOPLE, totalCount: PEOPLE.length } }], otherwise: TRACKS }, ...PEOPLE_DETAILS },
    ready: 'document.querySelectorAll(".result-select").length === 6',
    async run(op) {
      const drawerFilters = op.viewport.width <= 1100;
      // Filter: people only, committed by the form's own Search.
      if (drawerFilters) {
        await op.tabTo({ name: 'Filters', role: 'button' }, { note: 'the results header opens the filter drawer (§25 Tier B)' });
        await op.press('Enter', { expectFocus: { name: 'Filters', role: 'heading' }, note: 'the drawer takes focus' });
      }
      await op.tabTo({ name: 'Object class', role: 'combobox' }, { max: 40 });
      await op.type('P');
      await op.until('Object class reads Person', 'Array.from(document.querySelectorAll("select")).some((s) => s.labels?.[0]?.textContent.trim() === "Object class" && s.selectedOptions[0]?.textContent.trim() === "Person") && "Person"');
      await op.tabTo({ name: 'Search', role: 'button' }, { max: 40, note: 'the form\'s submit' });
      await op.press('Enter', { note: 'commit the filter' });
      await op.requested('the search asked for people', 'GET', /^\/api\/tracks$/, { query: { objectClass: 'Person' } });
      await op.until('the results are the three people', '(() => { const s = Array.from(document.querySelectorAll(".result-select")); return s.length === 3 && s.every((b) => /^Select Person /.test(b.getAttribute("aria-label"))) && /objectClass=Person/.test(location.search) && "3 people"; })()');
      if (drawerFilters) await op.press('Escape', { expectFocus: { name: 'Filters', role: 'button' }, note: 'close the drawer; focus returns to its opener' });
      // Scan: select the first result, then step through with j / k.
      await op.tabTo({ name: /^Select Person · CAM-01/, role: 'button' }, { max: 40, note: 'the first result' });
      await op.press('Enter', { note: 'select it; the inspector opens' });
      await op.route('the first person is selected', new RegExp(`[?&]track=${TRACK_ONE}`));
      await op.until('the inspector shows Track 1', '/Person · Track 1/i.test(document.body.innerText) && "Person · Track 1"');
      await op.press('j', { note: 'next result' });
      await op.route('the second person is selected', new RegExp(`[?&]track=${PEOPLE[1].id}`));
      await op.press('j', { note: 'next result' });
      await op.route('the third person is selected', new RegExp(`[?&]track=${PEOPLE[2].id}`));
      await op.press('k');
      await op.press('k', { note: 'back to the first' });
      await op.route('the first person is selected again', new RegExp(`[?&]track=${TRACK_ONE}`));
      await op.until('the inspector shows Track 1 and its evidence', '/Person · Track 1/i.test(document.body.innerText) && Boolean(document.querySelector("video")) && "Track 1 with its player"');
      // Evidence: the player's own keys, on its frame.
      await op.tabTo({ name: /^Person Track 1 evidence frame/, role: 'group' }, { max: 30, note: 'the evidence frame' });
      await op.press('End', { note: 'jump to the subject\'s end' });
      await op.until('the frame is at the subject\'s end (3.4 s)', '(() => { const v = document.querySelector("video"); return v && Math.abs(v.currentTime - 3.4) < 0.05 && "t=" + v.currentTime.toFixed(2); })()');
      await op.press('Home', { note: 'jump to the subject\'s start' });
      await op.until('the frame is at the subject\'s start (0.6 s)', '(() => { const v = document.querySelector("video"); return v && Math.abs(v.currentTime - 0.6) < 0.05 && "t=" + v.currentTime.toFixed(2); })()');
      await op.press('ArrowRight', { note: 'one frame on' });
      await op.until('the frame stepped one frame (40 ms at 25 fps)', '(() => { const v = document.querySelector("video"); return v && Math.abs(v.currentTime - 0.64) < 0.02 && "t=" + v.currentTime.toFixed(2); })()');
      // The full review of the evidence.
      await op.tabTo({ name: 'Open', role: 'link' }, { reverse: true, max: 20, note: 'the inspector\'s Open' });
      await op.press('Enter');
      await op.route('the review of Track 1 is open', new RegExp(`^/review/video/${PROCESSED}\?.*trackId=${TRACK_ONE}`));
      await op.until('the review summarises the Track', '/Track summary/.test(document.body.innerText) && "Track summary"');
      // Return: the breadcrumb back to the search, as it was.
      await op.tabTo({ name: 'Search', role: 'link', within: 'Breadcrumb' }, { max: 30, note: 'the breadcrumb\'s Search' });
      await op.press('Enter', { note: 'return to the search' });
      await op.route('the search is back, filtered and on Track 1', new RegExp(`^/search\?(?=.*objectClass=Person)(?=.*track=${TRACK_ONE})`));
      await op.until('the three people are listed again', 'document.querySelectorAll(".result-select").length === 3 && "3 people"');
      await op.press('Escape', { note: 'close the inspector' });
      await op.done('back in the results, on Track 1\'s own row, filter intact', `(() => { const a = document.activeElement; return a && a.classList.contains("result-select") && a.getAttribute("data-track-id") === "${TRACK_ONE}" && /objectClass=Person/.test(location.search) && !/[?&]track=/.test(location.search) && "focus on Track 1's result"; })()`);
    },
  },
  {
    id: 'error-retry-recovery',
    title: 'Error / retry / recovery',
    start: '/search',
    // The request the operator causes decides the answer: page one without a
    // cursor; with the cursor, the continuation fails (the query's own single
    // retry fails too), and the operator's Retry is answered with page two.
    api: { '/api/tracks': { query: [{ match: { cursor: true }, then: { sequence: ['unavailable', 'unavailable', PAGE_TWO] } }], otherwise: PAGE_ONE } },
    ready: 'document.querySelectorAll(".result-select").length === 6 && Array.from(document.querySelectorAll("button")).some((b) => b.textContent.trim() === "Load more")',
    async run(op) {
      await op.tabTo({ name: 'Load more', role: 'button' }, { max: 80, note: 'past the filters and the six results to the continuation' });
      await op.press('Enter', { note: 'ask for the next page' });
      await op.requested('the continuation was requested, with its cursor', 'GET', /^\/api\/tracks$/, { query: { cursor: 'journey-cursor-2' } });
      await op.until('the continuation failed in its own region; the six results remain', '(() => { const t = document.body.innerText; const btn = Array.from(document.querySelectorAll("button")).find((b) => b.textContent.trim() === "Retry load more"); return /The next page could not be loaded/.test(t) && btn && document.querySelectorAll(".result-select").length === 6 && "failed · Retry load more offered · 6 results kept"; })()');
      await op.tabTo({ name: 'Retry load more', role: 'button' }, { note: 'the failure\'s own retry' });
      await op.press('Enter', { note: 'retry the continuation' });
      await op.until('the retry recovered: page two is in, the failure is gone, the snapshot is complete', '(() => { const t = document.body.innerText; return document.querySelectorAll(".result-select").length === 12 && !/The next page could not be loaded/.test(t) && /End of this result snapshot/.test(t) && "12 results · end of snapshot"; })()');
      await op.done('recovered, and focus is on the first Track the retried page brought', `(() => { const a = document.activeElement; return a && a.classList.contains("result-select") && a.getAttribute("data-track-id") === "${PAGE_TWO.items[0].id}" && document.querySelectorAll(".result-select").length === 12 && "focus on the first new result"; })()`);
    },
  },
  {
    id: 'monitoring',
    title: 'Cameras / Videos / Processing monitoring',
    start: '/',
    api: { '/api/cameras': DENSE_CAMERAS, ...DENSE_ESTATE, [`/api/cameras/${CAM}`]: 'fixture' },
    ready: 'Boolean(document.querySelector("main")) && !document.querySelector(".skeleton, .loading-state")',
    async run(op) {
      // Cameras, through the shell's navigation.
      await op.tabTo({ name: 'Cameras', role: 'link' }, { note: 'the rail\'s Cameras destination' });
      await op.press('Enter');
      await op.route('Cameras is open', /^\/cameras$/);
      await op.until('the camera inventory lists the estate (24 cameras)', 'document.querySelectorAll("table tbody tr").length === 24 && "24 cameras"');
      // An operational row's action: CAM-01's analytics.
      await op.tabTo({ name: 'Analytics for CAM-01', role: 'link', row: 'CAM-01' }, { max: 80, note: 'scan the inventory to CAM-01\'s analytics action' });
      // Videos, back through the shell's navigation.
      await op.tabTo({ name: 'Videos', role: 'link' }, { reverse: true, max: 120, note: 'back up to the rail' });
      await op.press('Enter');
      await op.route('Videos is open', /^\/videos$/);
      await op.until('the video inventory lists the estate (24 videos)', 'document.querySelectorAll("table tbody tr").length === 24 && "24 videos"');
      // The failed video's row: its retry action is reached, not taken (monitoring).
      await op.tabTo({ name: 'Retry', role: 'button', row: 'south-dock-2200.mp4' }, { max: 120, note: 'scan to the failed video\'s Retry' });
      // Processing, through the shell's navigation.
      await op.tabTo({ name: 'Processing', role: 'link' }, { reverse: true, max: 160, note: 'back up to the rail' });
      await op.press('Enter');
      await op.route('Processing is open', /^\/processing$/);
      await op.until('the queue holds the active, failed and completed runs', '(() => { const t = document.body.innerText; return document.querySelectorAll("table tbody tr").length >= 20 && /Running|Processing/.test(t) && /Failed/.test(t) && "queue listed"; })()');
      // The failed run's detail: open it and read its status.
      await op.tabTo({ name: 'Detail', role: 'link', row: 'south-dock-2200.mp4' }, { max: 120, note: 'the failed run\'s detail' });
      await op.press('Enter');
      await op.route('the failed run\'s detail is open', new RegExp(`^/processing/${FAILED}$`));
      await op.until('the detail states the failure and offers its retry', '(() => { const t = document.body.innerText; return /south-dock-2200\\.mp4/.test(t) && /Failed/.test(t) && Array.from(document.querySelectorAll("button")).some((b) => /^Retry processing$/.test(b.textContent.trim())) && "Failed · Retry processing offered"; })()');
      await op.tabTo({ name: 'Retry processing', role: 'button' }, { note: 'the failure\'s own action, reached' });
      await op.done('the failed run\'s retry is reached from the keyboard, on its own detail', '(() => { const a = document.activeElement; return a && a.textContent.trim() === "Retry processing" && location.pathname.endsWith("' + FAILED + '") && "Retry processing focused on the failed run"; })()');
    },
  },
];

/** Plan §5.3's six journeys, in its order — frozen: never renamed, merged or dropped. */
const PLAN_ORDER = ['import-process-results', 'search-inspect-evidence', 'vehicle-car-review', 'scene-analytic-why', 'monitoring', 'error-retry-recovery'];
/**
 * Journeys a later plan adds, after the frozen six and in that plan's order;
 * each names its plan. The six are untouched: a later plan only appends.
 */
const LATER_ORDER = [
  // Stage 4 plan (docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md) PR-5, Tests.
  'plate-search-inspect-seek',
];
export const JOURNEYS = Object.freeze([...PLAN_ORDER, ...LATER_ORDER].map((id) => {
  const journey = REGISTERED.find((j) => j.id === id);
  if (!journey) throw new Error(`planned journey ${id} is not registered`);
  return journey;
}));
if (REGISTERED.length !== PLAN_ORDER.length + LATER_ORDER.length) throw new Error('the registry holds a journey no plan names');
