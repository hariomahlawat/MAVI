/**
 * X2 (plan §5.3): the six frozen operator journeys, as the product has them.
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

// --- The six journeys --------------------------------------------------------------

export const JOURNEYS = [
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
