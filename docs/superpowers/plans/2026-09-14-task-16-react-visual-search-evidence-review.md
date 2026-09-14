# Task 16 — React Visual Search and Evidence Review

**Status:** Authoritative implementation plan.

**Planning baseline:** Phase-1 integration head `60d33163bd7d8f7956826e9d554ac47a41a1ad44`.

**Primary objective:** extend the Task-15 React application foundation with a production-quality Visual Search workflow over Task-14 Track APIs and a direct, evidence-linked Video Review workflow that reconstructs entirely from durable route/API state.

Task 16 is deliberately frontend-focused. It shall consume Task-14 search/detail/content contracts exactly as published and shall not recreate PostgreSQL query semantics, historical-run selection, storage addressing, cursor snapshots, evidence authority, or review persistence inside React.

---

## 1. Scope

Task 16 shall implement:

1. a Visual Search page at `/search`;
2. structured search filters for the exact Task-14 public search contract;
3. bookmarkable committed filter state in the browser URL;
4. cursor-driven infinite pagination using Task-14 opaque cursors;
5. compact Track result cards using authoritative thumbnail/content URLs;
6. an Evidence Review page at `/review/video/:videoAssetId?trackId=<track-id>`;
7. direct-route reconstruction with no dependency on navigation state or warm cache;
8. native source-video playback through the Task-14 range-capable content endpoint;
9. deterministic seek to one second before Track start, clamped safely;
10. configured-display-timezone rendering using the Task-15 time architecture;
11. robust loading, empty, error and evidence-unavailable states;
12. frontend regression tests, route/deep-link tests and exact-head qualification.

Task 16 shall not implement:

- face recognition;
- ReID or cross-camera association;
- ANPR;
- embeddings/vector search;
- free-text/LLM/VLM search;
- trajectory decoding or overlay rendering;
- evidence mutation;
- Confirm/Reject mutations for `ReviewStatus`;
- arbitrary historical-run browsing;
- clips, exports or downloads;
- direct PostgreSQL/filesystem access;
- storage-key/path construction;
- new detector/tracker behaviour;
- new backend pagination semantics.

---

## 2. Existing authoritative dependencies

### 2.1 Task-14 backend boundary

Task 16 consumes:

`GET /api/tracks`

Supported filters:

- `cameraId`
- `videoAssetId`
- `processingRunId`
- `objectClass`
- `fromUtc`
- `toUtc`
- `minimumDurationMs`
- `minimumConfidence`
- `cursor`
- `limit`

Task-14 ordering is fixed:

`StartTimestampUtc DESC, Track.Id DESC`

Pagination is opaque cursor pagination with a PostgreSQL-owned visibility snapshot. React shall not interpret, decode, persist indefinitely, modify or reconstruct cursors.

Task 16 also consumes:

- `GET /api/tracks/{trackId}`
- `GET /api/videos/{videoAssetId}/content`
- `GET /api/artifacts/{artifactId}/content`

Content URLs returned by Task-14 DTOs are authoritative and shall be used directly.

### 2.2 Task-15 frontend foundation

Task 16 shall reuse:

- BrowserRouter;
- TanStack Query;
- central `ApiError`;
- central query-key factory;
- `/api` same-origin calls;
- shared configured-timezone formatter;
- application shell/navigation;
- local/system fonts only;
- no runtime Internet/CDN/telemetry dependency;
- existing frontend test harness;
- ASP.NET Core/IIS SPA fallback.

No parallel router, state library, API client or time formatter may be introduced.

---

## 3. Phase-1 object and review semantics

The current authoritative `ObjectClass` values are:

- `Person`
- `Vehicle`

The UI shall expose exactly those values. It must not expand Vehicle into Car/Motorcycle/Bus/Truck because the Task-14 API does not expose those as Phase-1 Track classes.

The current authoritative `ReviewStatus` values are:

- `Unreviewed`
- `Confirmed`
- `Rejected`

Task 16 shall display ReviewStatus only.

There is no Task-14 mutation API for review decisions. Therefore Task 16 must not present Confirm/Reject controls that imply persistence.

For Task 16, “Evidence Review” means inspection of:

- selected Track metadata;
- representative thumbnail;
- processing provenance summary;
- source video;
- source-video position around the Track.

Persistent review actions require a future backend-supported task.

---

## 4. Routes

Extend the existing Task-15 route table with:

`/search`

and:

`/review/video/:videoAssetId?trackId=<track-id>`

The primary navigation shall add **Search**.

### 4.1 Search route

`/search` is the default Visual Search surface.

Committed search filters live in URL query parameters.

Example:

`/search?cameraId=<guid>&objectClass=Person&fromUtc=2026-09-14T02%3A30%3A00Z&toUtc=2026-09-14T04%3A30%3A00Z`

### 4.2 Review route

The route owns the VideoAsset identity:

`/review/video/{videoAssetId}`

The selected Track identity is supplied as:

`?trackId={trackId}`

The page must fetch the Track by ID and verify:

`track.videoAssetId === route.videoAssetId`

A mismatch is an invalid review target and must fail closed. It must never display metadata for one Track while playing another video.

### 4.3 Deep-link invariant

Both routes must reconstruct correctly from a cold browser refresh with:

- no React navigation state;
- no warm TanStack Query cache;
- no prior search page visit.

Production ASP.NET Core host tests shall prove direct HTTP refresh returns the React entry document while unknown `/api` paths still remain API 404s.

---

## 5. Track API client

Create:

`src/web/mavi-web/src/api/tracks.ts`

### 5.1 Public frontend types

Mirror the Task-14 DTOs without renaming backend semantics.

Required types:

- `TrackSearchFilters`
- `TrackSearchResponse`
- `TrackSearchItem`
- `TrackDetail`
- `TrackCamera`
- `TrackProcessing`
- `TrackVideo`
- `TrackRepresentative`
- `TrackBoundingBox`

Use string identities for GUIDs and ISO timestamp strings for wire timestamps.

Do not introduce browser-side domain entities.

### 5.2 Search request builder

Provide one deterministic serializer that:

- omits undefined filters;
- uses backend parameter names exactly;
- never serializes blank strings;
- preserves explicit UTC ISO strings;
- serializes numeric thresholds invariantly;
- serializes the opaque cursor without modification;
- sends one `limit` value only.

Unknown client filters shall not be forwarded.

### 5.3 API functions

Implement:

- `searchTracks(filters, signal)`
- `getTrack(trackId, signal)`

Use `apiRequest` and AbortSignal.

No automatic POST mutation behaviour is involved in Task 16.

---

## 6. Query-key architecture

Extend the central Task-15 query-key factory.

Recommended shape:

- `trackSearch(filtersFingerprint)`
- `track(trackId)`

The search key shall contain only canonical committed semantic filters, not draft form state.

Opaque pagination cursors are page parameters of `useInfiniteQuery`, not independent query keys and not durable bookmark state.

A filter change creates a new query identity and therefore a fresh page chain.

---

## 7. Search-state architecture

Task 16 shall keep three concerns separate:

### Draft form state

What the operator is currently editing.

### Committed URL state

The search definition currently represented by the route.

### Server result state

Track pages owned by TanStack Query.

The authoritative relationship is:

`draft form -> Search action -> canonical URL -> parsed committed filters -> query key -> backend`

Typing in a control must not cause hidden network search.

Pressing Search or explicitly submitting the form commits the draft to the URL.

Browser Back/Forward navigation must restore the prior committed search.

Reset shall remove Task-16 search parameters and navigate to canonical `/search`, which loads the default unfiltered first page.

### 7.1 URL parsing/canonicalization policy

Supported search parameters are exactly:

- `cameraId`;
- `videoAssetId`;
- `processingRunId`;
- `objectClass`;
- `fromUtc`;
- `toUtc`;
- `minimumDurationMs`;
- `minimumConfidence`.

`cursor` is never accepted from durable page URL state and `limit` is owned by the UI constant.

Rules:

- every supported parameter may occur at most once;
- malformed supported parameters make the committed search invalid and no Track request is sent;
- duplicate supported parameters are invalid rather than “first wins”/“last wins”;
- unknown query parameters are ignored for backend semantics and are removed the next time Task-16 canonicalizes the URL;
- canonical URLs use a fixed parameter order;
- empty/default values are omitted;
- GUIDs are normalized to their API string identity without attempting resource discovery;
- `fromUtc`/`toUtc` are canonical UTC `Z` strings;
- numeric filters use invariant canonical decimal text.

The canonical search-key fingerprint shall be the deterministic canonical semantic query string (excluding cursor and page size), so logically identical URLs share one TanStack Query cache identity.

---

## 8. Search-filter UX

Phase-1 Search shall expose:

- Camera;
- Object class;
- From;
- To;
- Minimum duration;
- Minimum confidence.

The backend also supports `videoAssetId` and `processingRunId`. They shall remain supported by URL/API parsing for direct/debug/deep-link use, but the primary operator form need not expose raw GUID text-entry controls.

When either advanced scope is active from the URL, the Search page must show it visibly as an **Active scope** chip/summary with an explicit remove action. Hidden filters must never constrain results without operator-visible indication.

Removing an Active scope is a **committed-state action**: it must immediately canonicalize/navigate the URL with that `videoAssetId` or `processingRunId` removed while preserving all other committed filters. The chip remains visible until that URL transition has committed. It must never disappear only from local draft state while the hidden committed filter remains active.

Visible-form Search submissions preserve valid active advanced scopes unless the operator removes them. Reset clears all scopes and navigates to canonical `/search`.

This avoids clutter while preserving the exact backend capability without creating invisible filtering.

### Camera

Use the existing Cameras API and query key.

Show code + name.

Inactive cameras may remain selectable for historical search because old Tracks can legitimately belong to a camera that is now inactive.

### Object class

Values:

- Any
- Person
- Vehicle

### Minimum duration

Operator-friendly seconds may be accepted in the UI, but convert deterministically to integer milliseconds before committing/API serialization.

Reject:

- non-finite;
- negative;
- fractional values that cannot be represented according to the chosen UI precision.

Do not silently clamp.

### Minimum confidence

UI may present percentage or decimal, but one canonical representation must be selected.

Recommended operator representation: percentage `0–100`.

Convert to backend decimal `0–1` at commit time.

Reject non-finite/out-of-range values; do not silently clamp.

---

## 9. Search time semantics

This is a correctness boundary.

Task 16 updates ADR-004 to align the accepted time architecture with the already-shipped Task-14 UTC-only search API. The API boundary remains UTC. React may convert operator-entered wall time to a UTC boundary **only** through the central explicit-IANA-zone conversion utility defined here; browser timezone inference and fixed-offset arithmetic remain prohibited. This is a deliberate ADR amendment, not an accidental frontend assumption.

Task-14 accepts explicit UTC instants.

Task-16 must not let browser local timezone become an implicit authority.

### 9.1 Display zone

Load:

`GET /api/system/config`

and use:

`displayTimeZoneId`

as the search display/input zone.

The Search page shall visibly show the active display timezone near the From/To controls.

### 9.2 Input representation

The browser may use `datetime-local` controls for operator convenience, but those values are wall-clock values in the configured display zone, not in the browser's timezone.

Task 16 therefore requires a dedicated conversion helper:

`configuredWallTimeToUtc(localValue, displayTimeZoneId)`

The helper must not call `new Date(localValue)` as authority because that would apply browser timezone.

The implementation must use an `Intl.DateTimeFormat(..., { timeZone: displayTimeZoneId })` round-trip algorithm rather than the workstation timezone:

1. parse the wall-clock string manually into numeric calendar fields;
2. build a timezone-neutral naive millisecond value with `Date.UTC` only as arithmetic scaffolding;
3. derive plausible UTC offsets for the configured IANA zone around that wall date using `Intl.DateTimeFormat.formatToParts`;
4. construct candidate UTC instants from those offsets;
5. format each candidate back into the configured zone;
6. retain only candidates whose year/month/day/hour/minute/second exactly equal the requested wall fields;
7. zero matching candidates = nonexistent wall time;
8. more than one matching candidate = ambiguous wall time;
9. exactly one candidate = authoritative UTC instant.

The helper must be browser-timezone-independent and unit tested under at least two simulated workstation timezones. Do not use a heuristic that silently chooses the earlier/later DST offset.

### 9.3 DST ambiguity/nonexistence

For zones with daylight-saving transitions:

- nonexistent wall time must be rejected;
- ambiguous wall time must be rejected unless a future explicit offset-selection UX is introduced.

Task 16 shall not guess an offset.

Time input controls remain disabled until `displayTimeZoneId` has loaded successfully. Camera/class/duration/confidence search can still operate without time filters, but real-world timestamps must never be rendered using browser local time as a fallback. If system configuration is unavailable, show an explicit display-timezone error for timestamp presentation.

### 9.4 URL representation

Committed `fromUtc`/`toUtc` values in the URL shall be normalized explicit UTC strings ending in `Z`.

The UI reconstructs configured-zone display/input values from those committed UTC instants using a dedicated inverse helper:

`configuredUtcToWallTime(utcValue, displayTimeZoneId)`

This helper must use `Intl.DateTimeFormat.formatToParts` with the explicit configured IANA zone and emit the canonical `datetime-local` wall representation. It must not use browser-local Date getters or UTC-string slicing as a substitute for configured-zone conversion.

Cold URL load, Back/Forward navigation and Reset/recommit behavior must all use this inverse conversion when rehydrating From/To draft controls.

### 9.5 Validation

Reject before the Track request when:

- From >= To;
- either committed UTC value is invalid;
- a time filter is being created/edited from wall-clock input and the configured display zone is unavailable/invalid;
- wall-time conversion is ambiguous/nonexistent.

Display-zone availability is **not** a prerequisite for an unfiltered or non-time-filter Track search. If `/api/system/config` fails, camera/class/duration/confidence searches continue to work; only time-input conversion and configured-zone timestamp presentation are unavailable.

Backend validation remains authoritative and `track_search_invalid` must still be handled.

---

## 10. Visual Search query behaviour

Use `useInfiniteQuery`.

First request:

- committed filters;
- `limit` fixed by the UI;
- no cursor.

Continuation:

- same committed filters;
- `cursor = previousPage.nextCursor`.

Recommended Phase-1 page size: **24**.

The exact size should remain a frontend constant within backend range `1–100`.

### 10.1 Cursor invariants

React shall:

- treat the cursor as opaque;
- not expose it to the operator;
- not put it in the URL;
- not reuse it after filter changes;
- not attempt to decode expiry or snapshot metadata.

If the backend returns `track_search_invalid` on an expired continuation cursor, the UI shall offer a clear **Refresh results** action that restarts from page 1 using the same committed filters.

No automatic hidden restart should append a new snapshot onto old pages.

---

## 11. Search result card

Create:

`src/web/mavi-web/src/features/visual-search/TrackResultCard.tsx`

Each card shall show:

- representative thumbnail or evidence-unavailable fallback;
- ObjectClass;
- Camera code/name;
- start time in configured display timezone;
- duration;
- mean confidence;
- detection count;
- ReviewStatus;
- Review action.

Optional secondary data:

- max confidence;
- compact Track ID diagnostic disclosure.

Do not display storage keys.

### 11.1 Thumbnail

Use the DTO's `thumbnailContentUrl` directly.

Do not construct `/api/artifacts/...` from the ID in React.

Use:

- native lazy loading;
- meaningful alt text;
- deterministic placeholder on 404/load failure;
- component-local image failure state keyed/reset by the thumbnail URL so a recycled card cannot retain a stale failure;
- no retry storm for permanently missing historical evidence.

### 11.2 Review navigation

The Review action navigates to:

`/review/video/{videoAssetId}?trackId={trackId}`

Do not rely on passing the full Track object through router state.

Navigation state may be used only as a non-authoritative UX optimization if introduced later.

---

## 12. Visual Search page states

The page must distinguish:

### Default unfiltered state

`/search` with no search parameters is a valid committed search and automatically loads the newest 24 Tracks under Task-14 default latest-completed semantics.

There is no separate browser-only “not searched yet” state. An all-blank submitted form canonicalizes back to `/search`.

### Loading

First page request pending.

### Empty

Valid search returned zero Tracks.

### Results

One or more Tracks.

### Loading more

Continuation pending while existing cards remain visible.

### Search error

First-page request failed.

### Continuation error

Existing pages remain visible and a retry for Load More is offered.

### Expired/invalid cursor

Existing pages may remain visible, but operator is told the snapshot can no longer continue and can refresh from page 1.

Do not convert every search error into “No results.”

---

## 13. Evidence Review data flow

Create:

`src/web/mavi-web/src/features/video-review/VideoReviewPage.tsx`

Inputs:

- route `videoAssetId`;
- query `trackId`.

Validate both as non-empty GUID-shaped identities before querying.

The `trackId` query parameter must occur exactly once. Missing, blank, malformed or duplicated `trackId` is an invalid review target and must not issue a Track request. Unknown Review-page query parameters do not affect authority.

Fetch:

`GET /api/tracks/{trackId}`

Also load system config for display-zone rendering.

No independent `GET /api/videos/{videoAssetId}` is required for the core Review page because Task-14 Track detail already carries:

- video timestamps;
- dimensions;
- frame rate;
- duration;
- authoritative video content URL.

This avoids duplicate state ownership.

---

## 14. Review-page identity safety

After Track detail resolves, compare canonical GUID identity rather than raw string spelling.

Both identities must first pass the existing standard GUID-shape validation and then be normalized to lowercase canonical hyphenated text for comparison.

Conceptually:

`normalizeGuid(detail.videoAssetId) !== normalizeGuid(routeVideoAssetId)`

means invalid review target.

This explicitly allows equivalent uppercase/lowercase GUID spellings while still failing closed when durable identities differ.

On mismatch, render an invalid-target error and do not mount/play the source video.

This guards malformed/stale copied URLs and future routing mistakes.

Do not “fix” the route automatically based on Track detail because the route mismatch itself is evidence of an invalid request.

---

## 15. Native video playback

Use native:

`<video controls preload="metadata">`

with:

`src={detail.video.videoContentUrl}`

Do not fetch the video into JavaScript memory or create a Blob URL.

Task-14 range support and browser media streaming already provide the correct boundary.

Recommended attributes:

- `controls`;
- `preload="metadata"`;
- descriptive accessible label/context;
- no autoplay.

No custom playback framework is required in Phase 1.

---

## 16. Seek semantics

The selected Track shall open with one-second preroll.

Canonical target:

`targetSeconds = max(0, startOffsetMs / 1000 - 1.0)`

Example:

`197420 ms -> 196.420 seconds`

Seek only after media metadata is available.

If finite media duration is known:

`targetSeconds = min(targetSeconds, max(0, duration - epsilon))`

Use a small deterministic epsilon only if required to avoid browser rejection at exact end-of-media.

### 16.1 Seek lifecycle

The implementation must guard:

- repeated `loadedmetadata` events;
- route changes from one Track to another;
- **same-source Track changes where `videoContentUrl` does not change and `loadedmetadata` will not fire again**;
- stale event handlers from a previous Track;
- invalid/non-finite duration;
- invalid negative offsets despite backend guarantees;
- media load failure.

Seeking must be keyed to the selected Track identity/start offset, not only to a media-source change.

When the selected Track changes:

1. compute a new seek identity from the Track ID and start offset;
2. if the existing video element already has metadata (`readyState >= HTMLMediaElement.HAVE_METADATA`), apply the new seek immediately;
3. otherwise wait for the matching source's `loadedmetadata`;
4. ignore stale handlers/effects belonging to a previous Track/source.

The seek helper should be independently testable.

Do not auto-play after seeking.

---

## 17. Evidence Review layout

Recommended desktop structure:

Left/main:

- native video player;
- current evidence context.

Right/secondary:

- representative thumbnail;
- Track summary;
- camera;
- class;
- ReviewStatus;
- start/end;
- duration;
- mean/max confidence;
- detection count;
- source frame number;
- representative confidence/quality;
- pipeline version;
- detector/tracker identities.

On narrower screens, stack vertically.

The representative thumbnail is evidence context, not a decorative image.

Trajectory artifact identity may be shown in diagnostics if useful, but Task 16 shall not fetch/decode/render trajectory content.

---

## 18. Configured-timezone presentation

All Track real-world timestamps shall use the existing Task-15 `shared/time/time.ts` formatter with `displayTimeZoneId`.

Do not create another absolute timestamp formatter.

Show the configured timezone explicitly on Search and Review surfaces where time interpretation matters.

Video-relative offsets remain durations/seconds and must not pass through timezone conversion.

---

## 19. Error semantics

Use central `ApiError`.

### Search

Expected stable backend code:

- `track_search_invalid`

Display a human-readable operator message while retaining the stable code in diagnostic text where appropriate.

### Detail

Expected:

- `track_not_found`

A 404 means the Track is unavailable/not publishable under the backend contract.

### Content

Native `img`/`video` elements may encounter content 404/416/server failures outside the JSON API client.

Provide UI fallbacks:

- thumbnail unavailable;
- video unavailable / media failed to load.

Do not attempt storage-path fallback.

---

## 20. Accessibility

Task 16 shall include:

- labels for every filter;
- keyboard-submittable Search form;
- visible focus states using the Task-15 style system;
- semantic result cards/articles;
- meaningful image alt text;
- accessible Load More / Refresh Results controls;
- native video controls;
- errors using existing Alert component semantics;
- no information conveyed only by colour;
- no auto-playing media.

---

## 21. Responsive/offline constraints

Task 16 must remain usable on the target offline LAN with no runtime Internet.

No:

- remote fonts;
- remote icon libraries;
- map/CDN dependencies;
- analytics;
- telemetry;
- cloud media transformation.

Prefer CSS and inline/local assets already available in the repository.

Result-grid density should remain compact and operator-oriented rather than marketing-card style.

---

## 22. Proposed files

Create:

- `src/web/mavi-web/src/api/tracks.ts`
- `src/web/mavi-web/src/api/tracks.test.ts`
- `src/web/mavi-web/src/features/visual-search/VisualSearchPage.tsx`
- `src/web/mavi-web/src/features/visual-search/TrackResultCard.tsx`
- `src/web/mavi-web/src/features/visual-search/VisualSearchPage.test.tsx`
- `src/web/mavi-web/src/features/visual-search/searchState.ts`
- `src/web/mavi-web/src/features/visual-search/searchState.test.ts`
- `src/web/mavi-web/src/features/video-review/VideoReviewPage.tsx`
- `src/web/mavi-web/src/features/video-review/VideoReviewPage.test.tsx`
- `src/web/mavi-web/src/features/video-review/seek.ts`
- `src/web/mavi-web/src/features/video-review/seek.test.ts`
- `src/web/mavi-web/src/shared/time/wallTime.ts`
- `src/web/mavi-web/src/shared/time/wallTime.test.ts`

Modify:

- `src/web/mavi-web/src/app/router.tsx`
- `src/web/mavi-web/src/app/router.test.tsx`
- `src/web/mavi-web/src/app/queryClient.ts`
- `src/web/mavi-web/src/app/AppShell.tsx`
- `src/web/mavi-web/src/app.css`
- host-level integration test only as required to cover new deep links.

Backend files should not change unless implementation exposes a genuine Task-14 contract defect.

---

## 23. Controlled implementation checkpoints

### Checkpoint A — contract and state foundation

1. Create Task-16 implementation branch from the accepted integration head after this planning PR merges.
2. Write RED tests for:
   - exact Track query serialization;
   - object-class values;
   - numeric conversion;
   - AbortSignal propagation;
   - URL committed-state parsing/canonicalization;
   - wall-time to configured-zone UTC conversion;
   - DST ambiguous/nonexistent rejection.
3. Implement typed Track API client.
4. Add query keys.
5. Implement canonical search-state utilities.
6. Implement wall-time conversion utility.
7. Run:
   - frontend tests;
   - typecheck;
   - build.

Do not start UI pages until Checkpoint A is green.

### Checkpoint B — Visual Search

Write RED tests for:

- Search route;
- canonical `/search` automatically loads the unfiltered first page;
- camera loading;
- inactive historical camera availability;
- Person/Vehicle filters;
- draft values not triggering requests;
- Search committing canonical URL;
- Back/Forward restoration;
- configured timezone display;
- validation;
- first-page request;
- empty state;
- error state;
- result-card fields;
- thumbnail fallback;
- recycled/rerendered card whose old thumbnail URL fails and whose replacement URL succeeds, proving failure state resets by URL;
- Review URL;
- Load More;
- exact nextCursor reuse;
- filter change resetting page chain;
- continuation failure preserving prior pages;
- invalid/expired cursor refresh path.

Then implement the Search UI.

Gate before proceeding.

### Checkpoint C — Evidence Review

Write RED tests for:

- valid direct deep link;
- malformed route VideoAsset ID;
- missing/malformed `trackId`;
- duplicated `trackId` query parameter (including two individually valid GUIDs) is rejected and issues no Track request;
- Track 404;
- Track/video route mismatch;
- representative thumbnail;
- configured-zone timestamps;
- processing provenance summary;
- native video URL;
- 1-second preroll;
- zero clamp;
- duration clamp;
- repeated metadata event;
- route change across different videos;
- **same-video Track A -> Track B change after metadata is already loaded, proving the seek updates without another `loadedmetadata` event**;
- media error.

Then implement Review.

Gate before proceeding.

### Checkpoint D — navigation and production deep links

1. Add Search to primary navigation.
2. Extend router tests.
3. Extend production-host deep-link test for:
   - `/search`;
   - `/review/video/<guid>?trackId=<guid>`.
4. Re-prove:
   - `/api` unknown routes remain 404;
   - static assets are local;
   - no runtime external asset dependency.

### Checkpoint E — internal subsystem audit

Before Codex review, inspect the complete subsystem for:

- implicit browser timezone use;
- duplicate timestamp formatter;
- malformed URL acceptance;
- stale draft/committed filter state;
- page-number/OFFSET assumptions;
- cursor decoding;
- cursor stored as durable bookmark;
- cursor reused after filter changes;
- accidental auto-restart mixing snapshots;
- duplicate network calls;
- unbounded Query retry;
- AbortSignal omissions;
- stale Track/video route identity;
- navigation-state dependency;
- manual construction of storage/content URLs;
- evidence-path leakage;
- image retry loops;
- video Blob buffering;
- incorrect seek units;
- stale media event handlers;
- custom review mutation without backend authority;
- inaccessible form/card controls;
- remote assets/CDNs;
- backend scope creep.

Fix sibling defects before external review.

---

## 24. Required frontend tests

At minimum:

### Track API/client

- no filters;
- every supported filter;
- deterministic parameter names;
- `Person` and `Vehicle`;
- explicit UTC serialization;
- cursor preserved opaquely;
- undefined values omitted;
- AbortSignal propagated;
- `track_search_invalid` preserved;
- `track_not_found` preserved.

### Search state

- URL -> committed filters;
- committed filters -> canonical URL;
- round-trip canonicalization;
- unknown params cannot influence API semantics and are removed by canonicalization;
- duplicate supported params rejected;
- malformed GUID rejected;
- malformed UTC rejected;
- From >= To rejected;
- duration conversion;
- confidence conversion;
- advanced video/run filters preserved when valid.

### Wall-time conversion

- fixed-offset-equivalent zone;
- normal DST date;
- nonexistent DST wall time rejected;
- ambiguous DST wall time rejected;
- browser timezone does not affect result;
- round-trip candidate matching returns exactly one valid instant;
- time controls do not use browser-timezone fallback when system config is unavailable;
- UTC -> configured-wall inverse conversion for cold URL hydration;
- UTC -> configured-wall inverse conversion after Back/Forward;
- inverse conversion with browser timezone different from configured zone;
- inverse conversion on dates around DST transitions.

### Visual Search

- cameras;
- filter validation;
- no request from draft typing;
- Search URL commit;
- browser history restoration;
- result cards;
- configured-zone display;
- empty state;
- API error;
- thumbnail unavailable;
- thumbnail error-state recovery after `thumbnailContentUrl` changes;
- Load More;
- cursor handoff;
- filter reset;
- continuation retry;
- expired/invalid cursor refresh.

### Video Review

- cold direct route;
- route validation;
- duplicate `trackId` rejection with no Track API call;
- Track 404;
- Track/video mismatch;
- video source;
- representative image;
- metadata/provenance;
- configured timezone;
- 197420 ms -> 196.420 s;
- <1000 ms -> 0;
- media duration clamp;
- repeated metadata;
- route replacement;
- media failure.

### Router/host

- Search nav;
- Search direct route;
- Review direct route;
- production-host refresh for both;
- API-safe fallback remains intact.

---

## 25. Backend-change policy

Task 16 should normally modify **zero backend source files**.

If UI implementation appears to require a backend change:

1. stop;
2. determine whether the UI is attempting to recreate semantics already intentionally omitted;
3. check the Task-14 contract;
4. write a focused failing backend contract test if the API is genuinely defective;
5. make the narrowest compatible backend correction;
6. run Task-14 security/contract coverage as well as the normal quality gate.

Do not casually widen Task 16 into another backend feature task.

---

## 26. Completion criteria

Task 16 is complete only when all of the following are true:

- `/search` works from cold direct load;
- committed filters are bookmarkable;
- browser Back/Forward restores committed search;
- configured timezone, not browser timezone, governs search time input/presentation;
- Person/Vehicle semantics match the backend;
- search uses Task-14 opaque cursor pagination;
- Load More never mixes changed filters with an old cursor;
- Track cards use backend-provided content URLs;
- `/review/video/:videoAssetId?trackId=...` works from cold direct load;
- route video identity is checked against Track detail;
- native video plays from the Task-14 range endpoint;
- one-second preroll seek is deterministic and tested;
- representative evidence is visible or fails gracefully;
- no ReviewStatus mutation is implied without backend support;
- no storage path/key leaks into React;
- no remote/runtime Internet dependency is added;
- frontend tests pass;
- frontend typecheck passes;
- frontend build passes;
- .NET/Python/repository quality gates remain green;
- production publish/deep-link qualification remains green;
- internal subsystem audit finds no material sibling defect;
- broad exact-head Codex review has no unresolved Critical/P1/P2 finding.

Only after these conditions are met should Task 16 be marked complete and the roadmap advance to Task 17.
