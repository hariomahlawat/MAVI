# Scene Analytics Slice 6 — Aggregates, Occupancy and Heatmap

**Status:** Implementation plan rebaselined after Scene Analytics Slice 5 / PR #66 merged.  
**Planning base / implementation gate:** `main@179786e2f4e09930a2c70119080ae565a92474f6` (PR #66 merge commit).  
**Planning branch:** `docs/scene-analytics-s6-plan`.  
**Implementation branch:** `feature/scene-analytics-s6-aggregates-heatmap` (to be created only after this plan is reviewed and merged).  
**Parent plan:** `docs/superpowers/plans/2026-09-20-spatial-temporal-track-analytics.md`.  
**Architecture decisions:** ADR-011 and ADR-012.  
**UI contract:** `docs/architecture/ui-ux-design-specification.md`.  
**Previous slice:** Slice 5 is merged and independently reviewed; one Evidence Player/timeline remains the Review/Investigation contract and is not modified by this slice.

## 1. Objective

Slice 6 turns the persisted Scene Analytics facts and sealed trajectory evidence already present on `main` into a **camera-centric analytical Workbench**:

- zone entry and exit counts;
- zone unique-Track counts;
- sample-based zone occupancy and peak occupancy;
- repeated-visit Track counts;
- trip-line crossing counts split by direction;
- active Track counts by object class;
- an on-demand trajectory heatmap over the scene revision's reference frame;
- explicit analytics coverage on every response and every rendered state.

This slice is **read-only analytics**. It introduces no new analytical inference, no new model, no new worker contract, no new persistence of derived charts/rasters, and no change to the Slice-5 Evidence Player.

## 2. Why the slice is rebaselined now

The parent plan was written before the final Slice-5 architecture landed. The merged baseline now provides several contracts Slice 6 MUST reuse rather than duplicate:

1. Slice 4 already owns analytic scope resolution, fact-bearing `Completed`/`Superseded` semantics, visibility-sequence gating, and the `AnalyticsCoverageResponse` vocabulary.
2. Slice 5 proved exact revision/engine identity through Review and Investigation and established the rule that incomplete analytics is never silently represented as zero evidence.
3. UI-2 already provides `WorkbenchLayout`; Scene Editor is the reference Workbench implementation.
4. The scene revision already carries reference-video identity/offset and immutable zone/line geometry.
5. `IAcceptedEvidenceReader` is the sanctioned path to sealed trajectory artefacts.
6. The repository has no aggregate module and no `features/scene-analytics` frontend today, so Slice 6 is a new bounded vertical slice rather than an extension of hidden existing code.

## 3. Non-negotiable invariants

### 3.1 Evidence and analytical truth

- Aggregate facts come only from persisted Scene Analytics fact/outcome tables.
- Heatmaps come only from sealed trajectory artefacts read through `IAcceptedEvidenceReader`.
- Browser code MUST NOT recalculate zone visits, line crossings, dwell, stationary state, or any other analytical fact.
- Historical facts remain bound to the exact scene revision and algorithm version that produced them.
- `Completed` and `Superseded` remain fact-bearing; currency is not validity.
- No active-revision fallback may reinterpret a pinned historical answer.

### 3.2 Coverage

- Every aggregate response and every heatmap response carries `AnalyticsCoverageResponse`.
- The run denominator follows Slice 4/ADR-011: distinct runs represented by the ordinary base Track candidate set after camera/window/class/latest-run scope and before analytical aggregation.
- `complete` retains exactly the ADR-011 rule: pending, failed, stale, not-configured and disabled run buckets must all be zero.
- `UnavailableTracks` limits evidence but does not make a completed run-level answer incomplete.
- A scope with **zero covered runs and a non-empty base-scope denominator** returns HTTP 200 with empty analytical data and truthful non-zero coverage buckets. The UI MUST render a not-analysed/disabled/not-configured state, never a zero-valued chart that implies observation.
- A **genuinely empty base scope** (the ordinary Track candidate set yields zero denominator runs) is a complete-zero observation: coverage is complete with all coverage buckets zero, analytical arrays/totals are empty or zero as appropriate, and the UI may render the explicit complete-zero state. No synthetic run or non-zero coverage bucket is fabricated merely to distinguish emptiness from incompleteness.
- Partial coverage MAY render the data from covered runs, but the coverage strip remains persistently visible.
- Coverage wording and bucket names are reused from Investigation; Slice 6 does not create a fourth readiness vocabulary.

### 3.3 Time and counting semantics

All server-side windows are UTC and use half-open intervals:

`[fromUtc, toUtc)`

Buckets are anchored to `fromUtc`, not to wall-clock or epoch boundaries:

`bucket[i] = [fromUtc + i×bucketSeconds, min(toUtc, fromUtc + (i+1)×bucketSeconds))`

This makes a shared/bookmarked request deterministic in every timezone.

Event assignment is half-open:
- an entry/crossing/exit exactly at a bucket start belongs to that bucket;
- one exactly at a bucket end belongs to the next bucket;
- `toUtc` itself is outside the request.

### 3.4 UI architecture

- Slice 6 uses the shared `WorkbenchLayout`; it does not create a sixth workspace archetype.
- Workbench MUST fit 1366×768 without page scroll and retain the UI-2 stage-width floor.
- The heatmap is not an Evidence Player and MUST NOT introduce a second Evidence Player/media controller.
- The reference-video element is paused reference context, following the Scene Editor pattern.
- UI colour roles and evidence/spatial roles remain separate namespaces.
- Heatmap colour decision 2c closes only against the rendered Slice-6 surface using §26 visual-QA conditions.

### 3.5 Dependency/offline boundary

- No new npm, NuGet, Python, native, model, runtime-pack or external-asset dependency.
- No CDN colour scale, plotting library, heatmap package, or browser analytics library.
- No offline manifest or binary-kit change is expected.
- If implementation discovers a genuine need for a dependency, stop and amend this plan before adding it.

## 4. Scope

### 4.1 Backend aggregate query

Add `Mavi.Application/Modules/SceneAnalytics/Aggregates/*` with a read-only service/repository boundary.

The request scope is:

- exactly one camera;
- required `fromUtc`;
- required `toUtc`;
- required `bucketSeconds`, integer 60–86400;
- optional object class (`Person` or `Vehicle`);
- current resolved analytical identity unless a server-controlled pinned identity is supplied by an internal caller.

The heatmap query additionally accepts an optional `processingRunId`. When present it narrows the scope to exactly one completed, published run that belongs to the path camera; unknown, hidden, unpublished or cross-camera ids are rejected with the same non-enumerating boundary used elsewhere. Aggregate queries remain camera/window based.

Public Slice-6 UI requests use the camera's resolved identity. The API does not accept arbitrary analysis ids.

The repository/service MUST reuse the same base-scope and coverage semantics as Slice 4. Prefer extracting a narrowly shared analytics-scope resolver from the existing Track-search implementation over copying its SQL/decision tree.

### 4.2 Aggregate metrics

For each requested bucket and exact analytical identity:

| Metric | Frozen Slice-6 meaning |
|---|---|
| `zoneEntryCount` | persisted zone visits with `began_inside = false` and entry timestamp inside the bucket |
| `zoneExitCount` | persisted zone visits with `ended_inside = false` and exit timestamp inside the bucket |
| `zoneUniqueTrackCount` | distinct analysed Tracks with a persisted visit positively overlapping the bucket |
| `lineCrossingCount.aToB` | persisted A→B crossings whose crossing timestamp is inside the bucket |
| `lineCrossingCount.bToA` | persisted B→A crossings whose crossing timestamp is inside the bucket |
| `occupancyAtStart` | number of persisted zone visits satisfying `entry <= bucket.start && exit > bucket.start` |
| `peakOccupancy` | maximum `occupancyAtStart` across the returned bucket starts for that zone |
| `peakOccupancyAtUtc` | earliest bucket-start instant at which the returned peak occurs; null when no bucket has occupancy |
| `repeatedVisitTrackCount` | distinct Tracks in the covered request scope whose persisted `track_zone_summaries.visit_count >= 2` for the zone; this is a **whole-Track summary metric**, not “two visits inside this bucket” |
| `classCount[class]` | distinct analysed Tracks of that class whose Track interval positively overlaps the bucket |

“Positive overlap” is `start < bucketEnd && end > bucketStart`. Endpoint touching alone is not activity in the bucket.

The response and UI MUST use the exact metric names or equally explicit operator wording. “Occupancy” MUST never be described as integrated person-seconds/vehicle-seconds; it is sampled at bucket starts.

### 4.3 Aggregate response shape

The contract should be compact and identity-explicit rather than repeating geometry in every bucket:

- camera id;
- scene revision id and number when resolved;
- algorithm version;
- `snapshotVisibilitySequence` used to resolve the response;
- requested `fromUtc`, `toUtc`, `bucketSeconds`;
- optional class filter;
- `AnalyticsCoverageResponse`;
- ordered bucket descriptors `{ startUtc, endUtc }`;
- per-zone series keyed by stable zone id **for zones enabled in the resolved revision**:
  - display name from the resolved revision;
  - entry counts;
  - exit counts;
  - unique-Track counts;
  - occupancy-at-start series;
  - peak occupancy + instant;
  - **window-level** entry count, exit count and distinct unique-Track count;
  - repeated-visit Track count;
- per-line series keyed by stable line id **for trip lines enabled in the resolved revision**:
  - display name;
  - A→B label;
  - B→A label;
  - A→B counts;
  - B→A counts;
  - window-level A→B and B→A totals;
- class-count series plus window-level distinct Track count per class.

Disabled geometry is not returned as a zero series. It was not evaluated, and a row of zeros would falsely read as an observed absence. The exact revision remains retrievable through the scene API if the UI needs configuration context.

Array lengths MUST equal the bucket count. Contract tests pin this invariant.

**Non-additive metrics are never reconstructed by summing buckets.** `zoneUniqueTrackCount`, `classCount`, occupancy and peak occupancy can repeat the same Track across buckets; the inspector uses the explicit window-level distinct totals/peak fields above. Only event counts such as entries, exits and crossings are safely additive across disjoint buckets.

Do not return internal `SceneAnalysis.Id`, claim/fencing data, filesystem paths, trajectory artifact paths, or cursor-signing material.

### 4.4 Response-size bound

The server rejects a bucket request that would produce more than **512 buckets** with a typed 400 problem (`analytics_bucket_count_invalid`). This is a response-shape bound, not a performance claim.

The UI chooses deterministic human-friendly bucket sizes so normal requests stay well below the bound:

- target no more than 120 buckets;
- choose the smallest value from `60, 300, 900, 3600, 21600, 86400` seconds that satisfies that target;
- the operator may choose another allowed value explicitly.

This is presentation policy; the API continues accepting every integer 60–86400 as long as the 512-bucket bound is respected.

## 5. Heatmap semantics

### 5.1 Source and identity

Heatmaps are computed on demand from the sealed trajectories belonging to **Analysed** Track outcomes in the covered run set for the resolved identity.

A Track/run may overlap the requested window while its trajectory extends outside it. **Only samples whose absolute UTC instant is inside `[fromUtc, toUtc)` contribute.** The absolute instant is derived from the immutable source recording start plus the persisted media-relative sample offset; samples outside the window are ignored, not counted merely because their Track overlaps the scope.

- `Unavailable` Track outcomes contribute no trajectory samples and remain disclosed through coverage.
- A missing/corrupt trajectory for a Track that the analytical unit says was `Analysed` is an operational evidence-integrity failure. The heatmap request fails; it MUST NOT silently produce a lower-density map.
- The heatmap service reads via the accepted-evidence abstraction only.

### 5.2 V1 weighting

Slice 6 implements **sample-count weighting only**:

- each valid trajectory sample contributes exactly 1 to one cell;
- no browser smoothing;
- no kernel-density interpolation;
- no time-to-next-sample weighting in this slice.

The parent plan's optional time weighting remains a possible later refinement. Adding it now would introduce a second heatmap meaning before the first is qualified.

### 5.3 Grid

Default grid is **64×36**.

The public request may specify `gridWidth` from the closed set:

`16 | 32 | 64 | 128`

Height preserves the 16:9 grid ratio:

- 16 → 9
- 32 → 18
- 64 → 36
- 128 → 72

The grid is in normalised source-frame coordinates. It remains valid over a non-16:9 reference frame because the matrix is projected across the same normalised frame extent; cells need not be square source pixels.

Cell mapping:

- `x = 0` / `y = 0` → first column/row;
- `x = 1` / `y = 1` → last column/row, never an out-of-range cell;
- any non-finite or out-of-contract sample is an evidence error, not clamped into a plausible map.

### 5.4 Heatmap response

Return:

- camera id;
- scene revision id/number when resolved;
- algorithm version;
- `snapshotVisibilitySequence` used to resolve the response;
- window + optional class filter;
- coverage;
- grid width/height;
- `sampleCount`;
- `trackCount` actually contributing samples;
- `maxCellValue`;
- row-major integer `values` of exactly `width × height` entries.

Do not return or persist a raster image.

The UI gets the exact scene revision through the existing scene-revision endpoint, then uses that revision's reference-video identity/offset for the backdrop. If the revision has no usable reference frame, the heatmap still renders against the neutral evidence matte with normalised axes and a clear “reference frame unavailable” state; it MUST NOT borrow a frame from a different revision.

### 5.5 Heatmap work bound

Raw trajectory I/O is the expensive part, so run count alone is not an adequate resource bound. Before opening any trajectory artefact, the service MUST materialise only the cheap covered-scope metadata needed to enforce both pre-fan-out limits: **at most 50 covered runs** and **at most 2,000 Analysed Track outcomes whose trajectories are candidates** after camera/window/class/optional-run scope is applied.

Exceeding either limit returns the typed 422 problem (`analytics_heatmap_scope_too_large`) **before any trajectory artefact is opened**, telling the caller to narrow the time window and identifying the exceeded bounded dimension. The Track guard is based on candidate Analysed outcomes, not post-read sample contribution, so enforcement cannot require the expensive I/O it bounds.

The 50-run limit remains aligned with the parent plan's Slice-7 benchmark. The 2,000-Track limit is a conservative pre-measurement ceiling that bounds sequential artefact opens even when one run approaches the worker's much larger completion-track allowance. Slice 7 MUST record both resolved-run count and candidate-trajectory Track count during heatmap timing and may raise/remove either cap only with measured evidence. If cheap accepted-evidence byte metadata becomes available at the scope seam, Slice 7 should also record aggregate bytes; Slice 6 does not open artefacts merely to discover their sizes.

There is **no heatmap cache in Slice 6**. §U permits a short-TTL memory cache only after measurement shows need; implementing one before measurement would create invalidation/concurrency complexity without evidence.

## 6. API surface

Add a dedicated read-only route group without mixing these queries into lifecycle mutation endpoints:

- `GET /api/cameras/{cameraId}/analytics/aggregates`
- `GET /api/cameras/{cameraId}/analytics/heatmap`

Query parameters are strictly whitelisted. Unknown or duplicate singleton parameters are rejected.

Common validation:

- camera exists and is visible;
- optional heatmap `processingRunId`, when present, resolves to a completed/published run of that same camera;
- `fromUtc < toUtc`;
- timestamps include an offset and are converted to UTC;
- object class is closed vocabulary;
- aggregate bucket bounds as §4.4;
- heatmap grid vocabulary and run cap as §5.

Problem responses use existing RFC 7807 + `extensions.code` style.

Do not create mutation endpoints in this slice. Existing retry/re-analysis operations remain the only lifecycle controls.

## 7. Snapshot and scope consistency

Aggregate and heatmap queries each obtain one server-side visibility snapshot and use it for **all** work in that response:

1. resolve latest-visible completed runs for camera/window/class (or the validated explicit heatmap run);
2. resolve the analytical identity under ADR-011;
3. classify coverage;
4. select fact-bearing units visible in the snapshot;
5. aggregate facts or read trajectories only for that covered set.

No step may re-resolve “current” state midway through a request.

The two endpoints are individually self-contained and each returns its own identity and coverage. The Workbench does not combine numerical series from two independently resolved requests into one claim. Aggregate mode uses the aggregate response; Heatmap mode uses the heatmap response. Switching modes is allowed to obtain a newer snapshot and the persistent coverage strip updates with it.

## 8. Backend implementation shape

Preferred decomposition:

`Mavi.Application/Modules/SceneAnalytics/Aggregates/`

- `AnalyticsAggregateQuery`
- `AnalyticsHeatmapQuery`
- `AnalyticsScope` / narrow shared scope projection
- `AnalyticsAggregateService`
- `IAnalyticsAggregateRepository`
- `HeatmapBuilder` (pure matrix builder)
- `IHeatmapEvidenceReader` only if the existing lifecycle evidence port cannot be reused cleanly without depending on implementation-specific types

`Mavi.Infrastructure/`

- repository implementation using EF Core / SQL;
- reuse/extract Slice-4 coverage/scope code where practical;
- accepted-evidence adapter for trajectory reads.

`Mavi.Contracts/Api/Analytics/`

- aggregate and heatmap response records;
- no domain entity types exposed.

`Mavi.Api/Endpoints/`

- `AnalyticsEndpoints.cs` for the two read-only routes;
- lifecycle endpoints remain in `SceneAnalyticsEndpoints.cs`.

No migration is expected. If a schema/index change appears necessary, stop: §Z says indexes beyond the existing plan land only after measured `EXPLAIN` evidence in Slice 7.

## 9. Frontend Workbench

Create:

`src/web/mavi-web/src/features/scene-analytics/*`

and a typed API module (prefer `api/analytics.ts` or an additive extension to the existing scene-analytics API module if naming remains unambiguous).

### 9.1 Route

Canonical route:

`/cameras/:cameraId/analytics`

Add an **Analytics** action from the Cameras Ledger for a specific camera. Do not create a global aggregate dashboard in this slice; the analytical scope is camera-first by design.

### 9.2 Workbench composition

Use the existing `WorkbenchLayout`.

**Context Bar**
- Cameras → camera code/name → Analytics;
- coverage/readiness chip using existing state vocabulary;
- link back to Scene configuration.

**Mode strip**
- Activity
- Heatmap

No extra mode until real need appears.

**Common controls**
- UTC-backed time window with operator-friendly presets;
- optional object class;
- coverage strip;
- explicit Refresh.

**Activity stage**
- primary temporal chart/series for bucketed metrics;
- metric selector limited to the frozen §4 metrics;
- zone or line selector where the metric requires geometry;
- no third-party chart dependency: use existing SVG/HTML primitives.

**Activity inspector**
- selected zone/line identity;
- totals for the current window;
- peak occupancy and instant where applicable;
- counting-definition help text;
- coverage summary.

**Heatmap stage**
- paused exact-revision reference video frame or neutral matte;
- heatmap matrix composited in source-frame coordinates;
- optional exact-revision zone/line outlines as context;
- opacity control;
- legend with min/maximum meaning;
- no animation and no inference.

**Heatmap inspector**
- sample count;
- contributing Track count;
- grid resolution;
- maximum cell count;
- identity + coverage;
- wording explicitly says “trajectory sample density”, not “people density” or “probability”.

## 10. Heatmap colour decision 2c

Slice 6 closes UI-spec decision 2c.

The implementation MUST:

1. define candidate perceptually-uniform sequential scales in the evidence/spatial namespace;
2. prohibit red→green semantics;
3. measure contrast/separation against:
   - the evidence matte;
   - the frozen zone/line/trajectory/crossing roles;
   - bright, dark, saturated and low-contrast reference footage;
   - normal, protan, deutan and tritan simulation;
4. retain a non-colour legend and numeric endpoints;
5. validate at 1366×768, 1440×900, 1920×1080 and approximately 2560×1080;
6. record candidates, measurements and the selected token values in the implementation review and update §32 decision 2c.

The planning PR does **not** preselect hex values. The specification deliberately requires this choice to be made against the real rendered heatmap.

## 11. Accessibility

- Coverage is persistent text, not colour-only.
- Charts have a bounded semantic summary; do not expose hundreds/thousands of SVG points as individual accessibility nodes.
- For the selected metric, provide a concise table/list of bucket start, value and metric definition where useful, capped/virtualised if necessary; the visual chart itself may be `aria-hidden` when its semantic twin is present.
- Heatmap canvas/SVG cell matrix is not enumerated cell-by-cell to assistive technology.
- Heatmap semantic summary includes grid size, sample count, contributing Tracks, maximum cell value and the normalised region of the maximum cell.
- Legend labels and opacity control are real controls with visible focus.
- Minimum pointer targets and contrast remain §23 obligations.

## 12. Empty/error/incomplete states

These states are distinct:

- camera not found;
- no scene configured;
- analytics disabled by empty active revision;
- analysis pending;
- analysis failed;
- stale/partial coverage;
- complete coverage with zero analytical facts;
- heatmap reference frame unavailable;
- heatmap scope too large;
- evidence-integrity failure while reading an analysed trajectory;
- network/API failure.

A complete, covered scope with genuine zero facts may show a zero chart/empty map. An incomplete scope MUST NOT.

## 13. Testing plan

### 13.1 Pure/Application tests

Aggregate arithmetic fixtures:

- entry exactly on bucket start;
- entry exactly on bucket end;
- exit boundary symmetry;
- visit spanning two/many buckets;
- endpoint-touching visit excluded from positive-overlap unique count;
- distinct Track counted once despite multiple visits in a bucket;
- A→B and B→A independent;
- occupancy-at-start;
- peak tie chooses earliest instant;
- repeated-visit count is whole-Track summary semantics;
- class-count interval overlap;
- final short bucket.

Heatmap builder:

- empty;
- one sample;
- corner samples including exactly 0 and 1;
- each supported grid size;
- repeated samples accumulate;
- row-major index correctness;
- non-finite/out-of-range point fails visibly;
- integer totals sum to `sampleCount`.

### 13.2 Integration tests

Use the existing Scene Analytics integration fixture and real PostgreSQL.

Must cover:

- complete covered scope;
- `Superseded` exact-identity facts remain readable;
- pending/failed/stale/not-configured/disabled coverage buckets;
- zero covered runs returns 200 + empty data + truthful coverage;
- partial coverage aggregates only covered runs;
- unavailable Tracks disclosed and excluded from facts/heatmap;
- latest-visible run scope;
- optional class filtering;
- snapshot visibility sequence excludes later commits;
- no internal analysis id exposed;
- heatmap reads sealed accepted evidence;
- trajectory samples before `fromUtc` and at/after `toUtc` are excluded even when their Track overlaps the request;
- explicit heatmap `processingRunId` is camera-bound and visibility-checked;
- corrupt/missing accepted evidence for an `Analysed` outcome fails rather than under-counting;
- >50 covered heatmap runs rejected before trajectory fan-out;
- aggregate >512 buckets rejected.
- disabled zones/trip lines are absent from analytical series rather than rendered as observed-zero data.

### 13.3 API/contract tests

- strict unmapped-member behavior;
- unknown query keys rejected;
- duplicate singleton query keys rejected;
- timestamp validation;
- bucket/grid vocabulary;
- RFC 7807 codes;
- arrays exactly match bucket count;
- matrix exactly `width×height`;
- coverage present on every success response.

### 13.4 Frontend tests

- route and camera action;
- Workbench layout/archetype;
- query keys include camera/window/class/bucket or grid;
- Activity ↔ Heatmap mode isolation;
- partial coverage strip;
- zero-covered state is not rendered as zero;
- complete-zero is rendered honestly;
- not-configured/disabled/pending/failed/stale wording;
- metric and geometry selection;
- inspector uses server-provided window-level distinct totals and never sums bucket distinct counts;
- heatmap opacity and legend;
- exact revision reference-frame retrieval; fail closed on mismatch;
- non-16:9 reference frame projection;
- 1366 no-page-scroll contract.

## 14. Visual QA matrix

Extend `tools/web-visual-qa` with deterministic mocked API/evidence states:

**Activity**
- complete non-zero;
- complete zero;
- partial coverage;
- pending;
- failed;
- disabled;
- not configured;
- dense multi-zone series;
- long zone/line names;
- peak occupancy.

**Heatmap**
- sparse;
- dense hotspot;
- all-zero complete;
- partial coverage;
- reference frame absent;
- bright footage;
- dark footage;
- saturated footage;
- low-contrast footage;
- letterbox;
- pillarbox;
- opacity low/mid/high;
- zone/line context on/off if exposed.

All states at 1366, 1440, 1920 and ~2560 widths.

Automated assertions:
- no page scroll at 1366 Workbench;
- stage ≥65% working width where side-by-side;
- no horizontal page overflow;
- no overlapping controls;
- no clipped legend/inspector;
- heatmap grid stays inside true content rectangle;
- reference geometry and heatmap share the same content rectangle;
- no uncaught errors;
- partial/zero-covered states cannot display an ordinary zero chart.

Human pass:
- heatmap scale readability;
- hotspot legibility over each footage class;
- separation from zone/line roles;
- inspector/chart hierarchy;
- ultra-wide use of space.

## 15. Performance and query discipline

Slice 6 adds **no speculative index and no cache**.

Implementation should:

- keep aggregate computation server-side;
- avoid N+1 queries per zone/line/bucket;
- project only required columns;
- stream/read heatmap trajectories sequentially;
- check cancellation between artefacts;
- enforce the 512-bucket bound plus both heatmap pre-fan-out bounds (50 runs / 2,000 candidate Analysed Tracks) before expensive artefact work;
- log request duration and bounded dimensions/run count without logging operator-sensitive evidence content.

Slice 7 performs the parent plan's measured `EXPLAIN (ANALYZE, BUFFERS)`, 10^5-fact aggregate tests and 50-run heatmap timing, then changes indexes/cache only from evidence.

## 16. Security and information exposure

- No arbitrary filesystem path from the client.
- No raw artefact path or storage topology in responses.
- Camera/run visibility follows existing repository boundaries.
- Unknown/hidden resources use the existing non-enumerating behavior where applicable.
- Do not accept client-supplied analysis-unit ids.
- Strict query whitelists prevent hidden behavior.
- Response counts reveal only information inside the caller's normal camera/time scope; this slice does not add operator authorization (deferred ADR-010 programme).

## 17. Documentation updates in the implementation PR

Update:

- this plan only if an approved plan decision changes;
- `docs/reviews/<date>-scene-analytics-s6-implementation.md`;
- parent Scene Analytics plan status and Slice-6 row;
- capability roadmap and capability implementation roadmap;
- UI/UX spec:
  - Slice 5 / decision 7 shown closed after PR #66;
  - decision 2c closed with measured heatmap scale after implementation;
- API/runbook material only where the new read-only endpoints need operator/developer explanation.

No offline packaging document change unless dependency drift is introduced (not expected).

## 18. Implementation sequence

### Task 1 — Freeze contracts and shared scope
1. Add request/response contracts and strict contract tests.
2. Extract/reuse the smallest Slice-4 scope/coverage seam needed by aggregates. This refactor is behavior-preserving: the complete existing Slice-4 search/coverage test suite MUST pass unchanged.
3. Pin coverage and fact-bearing semantics before metric SQL.

**Gate:** contract + scope tests green; no aggregate arithmetic yet.

### Task 2 — Aggregate repository/service
1. Implement bucket generation as a pure helper.
2. Implement set-based queries for zone visits/summaries, crossings and active Tracks.
3. Project compact per-geometry arrays.
4. Add complete integration matrix.

**Gate:** §T metrics pass golden fixtures and coverage tests.

### Task 3 — Heatmap builder/service
1. Implement pure grid mapper.
2. Resolve bounded covered run set.
3. Enforce the 50-run and 2,000-candidate-Track guards before opening any trajectory artefact.
4. Read trajectories through accepted evidence.
5. Fail closed on analysed-evidence corruption.
6. Add boundary tests proving both guards discriminate before evidence I/O.

**Gate:** matrix totals/identity/coverage exact; no persistence/cache.

### Task 4 — API endpoints
1. Add strict GET endpoints.
2. Add typed problems.
3. Wire DI.
4. API serialization/strictness tests.

**Gate:** real API integration tests green.

### Task 5 — Frontend API + Workbench shell
1. Add typed API models/query functions.
2. Add route and Cameras action.
3. Mount `WorkbenchLayout`.
4. Implement common window/class/coverage controls and async-state boundary.

**Gate:** all non-chart states correct before visualisation work.

### Task 6 — Activity mode
1. Render temporal series without third-party chart dependency.
2. Geometry/metric selection.
3. Inspector totals/definitions.
4. Bounded semantic equivalent.

**Gate:** every frozen aggregate is operator-readable and test-covered.

### Task 7 — Heatmap mode
1. Resolve exact revision/reference frame.
2. Render grid in true content rectangle.
3. Add opacity + legend.
4. Fail closed on revision/reference mismatch.
5. Close colour decision 2c by measurement.

**Gate:** heatmap semantics and projection pass tests and §26 QA.

### Task 8 — Full validation and cold review
1. Full .NET tests including integration DB suite.
2. Full Vitest.
3. `tsc -b`.
4. production web build.
5. `python tools/verify_repo.py`.
6. full Slice-6 visual matrix.
7. implementation review document.
8. independent/light cold review focused on counting semantics, coverage, projection and resource bounds.
9. exact-head CI green before merge.

## 19. Acceptance criteria

Slice 6 is complete only when all are true:

1. Every §T metric has one unambiguous, tested counting rule.
2. Every aggregate and heatmap response carries truthful coverage and the exact `snapshotVisibilitySequence` that resolved it.
3. Incomplete/zero-covered analytics cannot appear as a normal zero result.
4. Aggregate scope uses the same fact-bearing/snapshot semantics as Slice 4, including the genuinely-empty-denominator complete-zero exception.
5. Heatmap values come only from sealed accepted trajectories.
6. Heatmap sample totals are reproducible for the same scope/grid.
7. No raster heatmap is persisted.
8. No cache or new index is added without measurement.
9. Workbench fits 1366×768 without page scroll.
10. Heatmap is projected into the exact reference-frame content rectangle and never borrows another revision's frame.
11. Decision 2c is closed by rendered measurement, with legend and non-colour semantics.
12. No new dependency/offline/runtime-pack impact.
13. Full tests/build/verify/visual QA are green on the exact PR head.
14. No open P1/P2-equivalent finding remains.

## 20. Explicitly out of scope

Slice 6 MUST NOT include:

- persisted raster heatmaps;
- generic dashboard/report builder;
- event/behaviour records beyond persisted loitering;
- anomaly detection or intent;
- trajectory v2 / bottom-centre reference point;
- physical speed/distance calibration;
- live-camera ingestion or live heatmaps;
- new AI/ML model;
- entity/ReID/appearance analytics;
- new database indexes without §Z measurement;
- heatmap cache before measurement;
- operator-auth/audit architecture;
- case management;
- changes to the Slice-5 Evidence Player/timeline unless a directly blocking shared defect is proven.

## 21. Stop rule

This is the penultimate capability slice, not an invitation to polish indefinitely.

After the planned metrics, heatmap, states, tests and visual QA are clean, defects are triaged by impact:

- P1/P2-equivalent correctness, evidence, accessibility, security or bounded-resource defects: fix before merge.
- Cosmetic/P3 issues that do not compromise interpretation or interaction: record for Slice 7 unless the fix is trivial and local.
- Do not repeatedly redesign a correct aggregate/heatmap surface merely because another presentation is possible.

Codex/external review is **not a routine gate** for Slice 6. Use it only if the implementation creates material architectural uncertainty that remains after the internal cold review.
