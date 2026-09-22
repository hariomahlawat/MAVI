# Scene Analytics Slice 5 — Evidence Overlays and Explanation

**Status:** Implementation plan rebaselined after UI-5 / PR #64.  
**Planning base / implementation gate:** `main@273718ca078b5d86879d5a166af6c9eaff4c1c28` (PR #64 merge commit), with post-merge Task 17 Acceptance and MAVI Quality Gate both green.  
**Implementation branch:** `feature/scene-analytics-s5-evidence-explanation`.  
**Parent plan:** `docs/superpowers/plans/2026-09-20-spatial-temporal-track-analytics.md`.  
**UI contract:** `docs/architecture/ui-ux-design-specification.md`.  
**Architecture decisions:** ADR-011 (Scene Analytics identity/lifecycle), ADR-012 (UI archetypes/programme).

---

## 1. Objective

Make the Scene Analytics facts already exposed by Slice 4 directly verifiable against the source video.

An operator reviewing a Track must be able to answer, from one evidence surface:

- Which exact scene revision and analytics engine produced these facts?
- Which zones and trip lines existed in that revision?
- Which geometry did this Track actually interact with?
- Where and when did each crossing occur?
- When was the Track inside a zone?
- When was it stationary?
- Was a reported position persisted or interpolated?
- Why is analytical evidence absent when it is unavailable, pending, stale, disabled or not configured?

Slice 5 is an **evidence-presentation slice**. It does not add new analytics rules, recompute facts in the browser, or introduce another player.

---

## 2. Entry gate

Implementation MUST NOT begin until both conditions are true on the exact PR #64 merge commit:

1. Task 17 Acceptance Validation is green.
2. MAVI Quality Gate is green.

The gate is satisfied on `main@273718ca078b5d86879d5a166af6c9eaff4c1c28`. The Slice-5 implementation branch should therefore be created from that exact green `main` state (or a later `main` containing only separately reviewed/merged changes).

Before coding, record the exact implementation base SHA in the Slice-5 PR body.

---

## 3. Existing merged foundation — reuse, do not replace

Slice 5 is built on these existing surfaces:

- `shared/evidence/EvidencePlayer.tsx` — the only evidence player.
- `shared/evidence/useEvidenceTransport.ts` — the only media controller / rAF loop.
- `shared/evidence/EvidenceTimeline.tsx` + `timeline.ts` — the only timeline and its extension seam.
- `shared/evidence/layers.ts` — the spatial-layer contract. A `kind: 'spatial'` layer cannot compile without `describe`.
- `shared/evidence/projection.ts` — letterbox/pillarbox-aware `projectPoint` / `projectBox`.
- `features/video-review/TrackEvidence.tsx` — Track-specific adapter over the shared player.
- `features/visual-search/TrackInspector.tsx` and `features/video-review/VideoReviewPage.tsx` — both already mount the same Track adapter.
- `features/visual-search/TrackAnalyticsSummary.tsx` — current Slice-4 typed-fact summary.
- `api/tracks.ts` — full typed detail facts: zone summaries/visits, line crossings, motion/stationary intervals, analytics identity and state.
- `api/scene.ts` — immutable scene revision geometry by revision number.

No second player, second scrubber, page-level media clock or analytics-specific playback controller may be introduced.

---

## 4. Scope

### 4.1 Spatial overlays

For the exact revision named by `TrackDetailAnalytics`:

- draw zone geometry;
- draw trip-line geometry;
- distinguish geometry that has Track facts from contextual geometry;
- draw persisted line-crossing points;
- retain the existing bounding-box and trajectory layers;
- expose every spatial object through the UI-5 same-control accessibility contract.

### 4.2 Timeline evidence

Extend the one timeline with:

- zone-visit / dwell intervals;
- stationary intervals;
- zone entry markers where an actual boundary entry exists;
- zone exit markers where an actual boundary exit exists;
- line-crossing markers;
- existing subject interval and representative-frame marker.

### 4.3 Explanation

Evolve the Slice-4 analytics summary into an evidence explanation that shows:

- analytics state;
- revision number/id and engine version;
- reference point in operator language;
- zone visits and dwell;
- loitering result and threshold where applicable;
- line crossings, direction and exact media time;
- heading;
- stationary summary;
- unavailable/not-analysed explanation;
- other analysed identities as context, without substituting them for the selected identity.

### 4.4 Interaction

- activating a crossing/entry/exit marker seeks to its exact persisted/interpolated evidence offset;
- pointer and keyboard activation use the same semantic control;
- the Evidence Player's existing keyboard grammar remains authoritative.

---

## 5. Explicit non-goals

Slice 5 MUST NOT include:

- aggregate analytics or heatmaps (Slice 6);
- persisted raster heatmaps;
- Stage-7 event/behaviour records;
- anomaly detection or intent claims;
- new backend analytical rules;
- trajectory v2 / bottom-centre reference point;
- metric speed or distance;
- live cameras / RTSP / VMS work;
- a new media element or player implementation;
- a second timeline;
- a generic plugin framework;
- new npm/.NET/Python/native dependencies;
- human confirm/reject workflow or case management;
- unrelated cleanup.

If a missing fact requires backend recomputation rather than presentation of the existing typed detail contract, stop and document the gap rather than silently inventing it in the web client.

---

## 6. Identity and geometry resolution — fail closed

The analytical facts and the geometry MUST describe the same identity.

### 6.1 Authority

`TrackDetailAnalytics.sceneRevisionId`, `sceneRevisionNumber` and `algorithmVersion` are authoritative for the evidence being displayed.

The active camera revision is **not** a fallback for an analysed historical Track.

### 6.2 Revision retrieval

Add/reuse a focused hook that retrieves the full immutable revision by:

- camera id;
- `sceneRevisionNumber` from the detail response;
- expected `sceneRevisionId`.

After retrieval, verify the returned revision id equals the expected id. If it does not, fail closed.

This is preferable to resolving a detail overlay through whatever revision happens to be active now.

### 6.3 Geometry unavailable

If `Analysed` is returned without a complete revision identity (`sceneRevisionId` and positive `sceneRevisionNumber`), treat that as an unavailable/inconsistent analytical identity: show the facts only as unbound diagnostic content if safe, draw no revision-dependent overlay, and do not guess a revision.

If facts are present but the named revision cannot be loaded:

- keep the typed analytical facts visible;
- keep raw Track evidence visible;
- show a warning that scene geometry is unavailable;
- do not substitute active geometry;
- do not draw zone/line outlines from another revision;
- timeline facts that do not require geometry coordinates may still be shown using stable ids/short ids;
- persisted crossing points may remain evidence, but their line name falls back to the stable id.

---

## 7. State matrix

| Detail analytics state | Spatial analytical overlay | Analytical timeline | Explanation |
|---|---|---|---|
| `Analysed` + revision ready | Full | Full | Full facts + identity |
| `Analysed` + revision loading | Raw Track only until ready | Facts that do not require geometry may render | Loading geometry notice + facts |
| `Analysed` + revision unavailable | No substituted zone/line geometry; persisted crossing point may remain | Facts may render with id fallback | Warning + facts + pinned identity |
| `Unavailable` | None | None | Warning with persisted unavailable reason |
| `Pending` | None | None | “Not analysed yet” |
| `Failed` | None | None | Analysis failure state |
| `Stale` | None unless the detail response explicitly supplies facts for the selected historical identity | None unless facts are supplied for that same identity | Stale explanation; never silently switch identity |
| `NotConfigured` | None | None | No scene configured |
| `Disabled` | None | None | Analytics disabled by revision |

“Unavailable”, “not analysed” and “no analytical match” remain distinct states.

---

## 8. Raw one-sample evidence versus analytical sufficiency

A one-observation Track is valid raw evidence.

UI-5 correctly treats a one-sample trajectory as:

- one persisted position;
- one filled sample disc;
- no polyline;
- no interpolation;
- no claimed position away from that exact offset.

Scene Analytics v1, however, requires at least two trajectory samples for path-derived spatial/temporal facts. Therefore `trajectory_too_short` in the analytics engine means:

> the raw trajectory exists and remains reviewable, but it is insufficient to derive Scene Analytics v1 facts.

Slice 5 MUST preserve both truths simultaneously:

- raw one-sample Track evidence remains visible;
- analytics may honestly be `Unavailable / trajectory_too_short`.

Do not “fix” either side to match the other.

---

## 9. Component decomposition

Keep Track-specific assembly out of the generic player.

Recommended decomposition:

### 9.1 `features/video-review/analyticsEvidence.ts` (pure)

Pure transforms from:

- `TrackDetailAnalytics`;
- pinned `SceneRevision | undefined`;
- optional geometry-name helpers;

into a bounded evidence model:

```ts
type TrackAnalyticsEvidenceModel = {
  layers: EvidenceLayer[];
  intervals: EvidenceTimelineInterval[];
  markers: EvidenceTimelineMarker[];
  matchedZoneIds: ReadonlySet<string>;
  matchedLineIds: ReadonlySet<string>;
};
```

No React Query, no media element, no DOM.

### 9.2 `TrackEvidence.tsx`

Remain the one Track adapter.

It combines:

- raw Track layers (box, trajectory);
- analytical layers from the pure adapter;
- raw Track timeline records;
- analytical timeline records;

and passes one combined model to one `EvidencePlayer`.

Do not turn `EvidencePlayer` into a Track/Scene-aware component.

### 9.3 `TrackAnalyticsExplanation.tsx`

Evolve/replace the current summary component with one reusable presentational explanation used by Review and the Investigation inspector.

A compact prop may change density only, not semantics or available facts.

---

## 10. Spatial layer rules

### 10.1 Zones layer

- Source: exact pinned `SceneRevision.zones`.
- Draw normalized vertices through existing projection.
- Enabled contextual zone: frozen `--geo-zone` treatment with low fill.
- Zone with one or more facts for this Track: emphasis stroke/non-colour treatment in addition to the same evidence role.
- Disabled zone in the revision: dashed neutral/minimal fill per §19; never presented as matched.
- Accessible description names the zone, enabled/disabled state, kind, whether this Track visited it, and a bounded geometry summary. The always-mounted description must not enumerate every vertex: give normalized x/y extent, vertex count, and at most the first 4 normalized vertices; if more exist, state the remaining count. Full geometry remains the visual source of truth and may be exposed only through explicit on-demand disclosure if needed. `describe(currentOffsetMs)` must remain bounded in work and output.
- Never infer a visit from the trajectory in the browser; use persisted analytics facts only.

### 10.2 Trip-lines layer

- Source: exact pinned `SceneRevision.tripLines`.
- Draw through existing projection.
- Use frozen `--geo-line`.
- Direction, when semantically meaningful, retains arrowhead + A/B letters + labels; colour is not the only cue.
- A line with crossings for this Track receives emphasis treatment.
- Disabled line is dashed neutral and never presented as matched.
- Accessible description names line, its two normalized endpoints, direction state and crossing count. Trip lines are inherently bounded at two endpoints.

### 10.3 Crossings layer

Crossing facts are persisted analytics, not recomputed browser intersections.

For each `TrackDetailLineCrossing`:

- project `pointX/pointY`;
- draw one event/crossing glyph;
- encode A→B / B→A with the already-frozen directional evidence roles and a non-colour cue;
- accessible description names line, crossing index, direction, normalized point and media time.

The layer control label should be **Crossings**, not “Events”, so Stage-7 event semantics are not pulled forward.

---

## 11. Event/crossing marker hue decision (UI spec decision 2a)

Slice 5 closes decision 2a because it is the first surface drawing event-like analytical instants.

Do not pick a colour by taste in the plan.

During implementation:

1. introduce a candidate evidence token in the evidence/geo namespace;
2. evaluate it for separation from zone, trip-line, A→B, B→A, bbox and trajectory roles;
3. test normal vision plus protan/deuteran/tritan simulation using the same method as UI-1;
4. render it across bright, dark, saturated, low-contrast, letterboxed and pillarboxed evidence;
5. retain a glyph/shape cue so hue is never the sole distinction;
6. only then freeze the numeric value in §8.3 / §32 and the token set.

Do not use a UI success/warning/error token as the evidence role.

---

## 12. Timeline decision 7 — close in Slice 5

Choose **stacked, bounded analytical lanes**, not a second timeline and not a single undifferentiated glyph lane.

The one timeline remains one semantic list and one scrub surface.

Fixed lane families:

1. **Subject** — existing Track interval.
2. **Zone / dwell** — one band per persisted zone visit.
3. **Stationary** — one band per persisted stationary interval.

Crossings and real boundary entry/exit are markers, not interval lanes.

Why stacked lanes:

- zone occupancy and stationary are different facts and may overlap;
- a single interval lane would make overlaps visually ambiguous;
- dynamic one-row-per-zone layouts would grow without a bounded height;
- the zone/dwell family uses bounded interval packing inside its family, so overlapping visits remain visually distinguishable rather than painting over one another;
- the accessible list retains exact object identity independently of visual packing.

### 12.1 Visual grammar

- dwell/zone-visit and stationary bands use **hatched fills, not new hues** (§8.3);
- use different hatch orientation/pattern plus different fixed vertical lane position as non-colour cues;
- subject keeps its existing solid treatment;
- markers use glyph + position + accessible wording;
- no opacity is used to encode evidence confidence.

### 12.2 Bounded overlap packing

The Zone / dwell family is one semantic lane family, not one row per zone. Its renderer uses a deterministic bounded packing rule: sort by start, end, then stable evidence id; greedily place each interval in the first non-overlapping visual sub-row; expose at most 3 visual sub-rows. A fourth-or-greater concurrent visit goes to one fixed overflow aggregate rail for the affected span, labelled with the concurrent count, rather than painting over an existing visit. The complete semantic list still names every visit individually, and selecting/focusing an overflowed visit must identify/highlight its exact persisted interval without adding a row. Endpoint-touching intervals may reuse a sub-row; positive-duration overlaps may not. Packing is presentation only: never merge visits, change offsets, infer facts, or create one persistent row per zone.

Stationary remains one fixed visual row because persisted stationary intervals for one Track are expected not to overlap. Malformed overlapping stationary facts must fail visibly in tests/model handling rather than silently occlude.

### 12.3 Timeline height

The timeline may grow only by the fixed analytical families, the capped Zone/dwell sub-rows, and its fixed overflow rail. It MUST NOT grow with the number of zones, visits or stationary intervals.

---

## 13. Marker interaction — exact seek

Current pointer scrubbing computes an offset from pointer x. That is not sufficient for a crossing marker whose persisted offset is authoritative.

Upgrade timeline markers into semantic activation controls while keeping one timeline:

- the evidence record remains one semantic list item: render a real `<li>` containing a real `<button type="button">` marker control rather than assigning button ARIA to the list item;
- the button has an effective 24×24 CSS px target while the visible tick/glyph may remain smaller inside it;
- pointer activation calls `onSeek(marker.offsetMs)` exactly;
- `Enter` / `Space` activate the marker and seek exactly;
- marker pointer-down MUST NOT first bubble into approximate scrub seeking;
- `ArrowLeft` / `ArrowRight`, `J` / `L`, `Home` / `End` remain the Evidence Player grammar when focus is on the marker button;
- focus ring is visible.

**Dense-marker collision rule.** Two 24×24 hit targets must not overlap in a way that makes one pointer-inaccessible. Add a small pure marker-layout/packing rule that vertically staggers nearby marker controls within a bounded marker rail. The number of marker rows is fixed/bounded; it does not grow with evidence count. Markers at exactly the same offset may share one cluster control only if activation seeks to that common exact offset and the control's accessible name enumerates the evidence at that instant. Markers at different offsets MUST remain separately activatable. Add a dense-marker fixture/test.

Representative-frame markers use the same exact-seek mechanism, eliminating two different marker interaction contracts.

This is a generic timeline improvement, not a Scene-Analytics-specific media controller.

---

## 14. Deriving timeline records from persisted facts

### 14.1 Zone visits

Each persisted `zoneVisit` yields one zone/dwell interval:

- start = `entryOffsetMs`;
- end = `exitOffsetMs`;
- label includes zone name/id and dwell duration;
- semantics include `beganInside`, `endedInside`, `closedByGap`.

Do **not** fabricate boundary markers:

- add an entry marker only when `beganInside == false`;
- add an exit marker only when `endedInside == false && closedByGap == false`;
- a visit closed by a sample gap is described as such; it is not represented as crossing the zone boundary.

### 14.2 Line crossings

Each persisted crossing yields:

- one crossing marker at `offsetMs`;
- one projected crossing glyph at `pointX/pointY`;
- direction from the persisted `direction`.

Do not recompute the crossing from the browser trajectory.

### 14.3 Stationary

Each persisted stationary interval yields one stationary lane band.

No additional motion classification is performed in the browser.

---

## 15. Matched versus contextual geometry

For a full analysed Track:

- **contextual geometry** = geometry present in the pinned revision;
- **Track-interacted geometry** = zones with persisted visits/summaries or lines with persisted crossings.

The latter receives emphasis styling, but the underlying zone/line evidence role remains the same.

If Review was opened from an analytic search, the Track detail remains the authority for complete evidence. Slice 5 does not add another “matched filter” identity to the URL unless a concrete operator requirement proves it necessary.

The explanation may state all persisted facts for the selected analytics identity; it must not pretend that every fact was part of the original search predicate.

---

## 16. Explanation content

For `Analysed`:

### Identity header

- `Scene revision <n>`;
- shortened/stable revision id available in disclosure;
- engine label from `algorithmVersion`;
- reference point: render `bbox-centre` / current v1 value as **Box centre** (image reference point, not ground position);
- sample/gap counts where useful.

### Zones

Per zone with facts:

- name (stable id fallback);
- visit count;
- total dwell;
- loitering yes/no;
- loitering threshold and qualifying dwell where relevant;
- visit intervals in a disclosure if multiple.

### Lines

Per line with crossings:

- name/id;
- crossing count;
- each crossing time;
- direction in operator wording/labels.

### Motion

- image heading wording (Up, Up-right, etc.; never compass);
- longest stationary;
- total stationary;
- count of stationary intervals.

Engineering diagnostics such as normalized path length/rate remain behind the existing disclosure rule and are not promoted into headline copy.

### Footer

Always state:

`Scene revision N · Engine vN · reference point: Box centre`

for analysed facts.

---

## 17. Host composition

### 17.1 Review

Preserve the Review archetype:

- Track summary remains the first rail panel so §4.5.1 stays true at 1366×768;
- analytics explanation follows the primary summary;
- representative evidence/provenance remain below;
- player stays sticky above 1100 and releases at/below 1100;
- no new page-level scroll owner.

### 17.2 Investigation inspector

Use the same evidence model and explanation component.

`compact` changes density only.

No facts or controls may exist only in Review if the same selected Track/identity is shown in the inspector, except content that is intentionally collapsed behind a disclosure for space.

---

## 18. Accessibility contract

Every new spatial layer is `kind: 'spatial'` and therefore MUST supply `describe`.

Every spatial description:

- names the object;
- states enabled/disabled/context/matched state;
- gives normalized source-frame coordinates;
- is associated with the same visible layer row/control;
- adds no extra tab stop.

Every timeline interval remains one semantic list item.

Every interactive marker:

- has an accessible name containing its visible/semantic label;
- is keyboard activatable;
- has a 24×24 effective target;
- exposes a visible focus indicator.

Colour is never the only distinction for:

- matched/context geometry;
- crossing direction;
- zone/stationary lane family;
- persisted/interpolated position;
- analytical state.

---

## 19. Query/cache rules

Add query keys only if a new full-revision hook requires them; reuse the existing immutable revision key:

`['camera-scene-revision', cameraId, revisionNumber]`.

The evidence model MUST update when any of these change:

- Track id;
- analytics scene revision id/number;
- analytics algorithm version;
- full scene revision response.

No cache entry for one analytical identity may overwrite another.

---

## 20. Error handling

No state may silently collapse into “nothing to show”.

Required distinctions:

- raw Track request failed;
- source video failed;
- trajectory absent;
- trajectory failed/corrupt;
- one-sample raw trajectory;
- analytics unavailable / `trajectory_too_short`;
- analytics pending;
- analytics failed;
- analytics stale;
- scene not configured;
- analytics disabled;
- pinned scene revision could not be loaded.

Where a retry is meaningful, expose the existing retry mechanism. Do not invent a new backend mutation in this slice.

---

## 21. Test-first acceptance matrix

Before implementation, add/define fixtures covering these facts.

### 21.1 Pure evidence-model tests

1. Zone visit → one interval, correct id/label/offsets.
2. `beganInside` → no fabricated entry marker.
3. `endedInside` → no fabricated exit marker.
4. `closedByGap` → no fabricated boundary exit marker.
5. Two visits to one zone remain two intervals.
6. Overlapping visits to different zones are deterministically packed into at most 3 visual sub-rows; positive-duration overlaps never share a sub-row.
7. Fourth-or-greater concurrency uses the fixed overflow aggregate rail and does not obscure an existing visit.
8. Packing is deterministic for equal starts/ends; endpoint-touching intervals may reuse a sub-row.
9. An overflowed visit remains individually identifiable from the semantic list without adding an unbounded row.
10. Line crossing → exact marker + exact projected point.
11. A→B and B→A retain distinct direction semantics beyond colour.
12. Stationary intervals map exactly from persisted offsets.
13. No analytical fact is derived from the browser trajectory.
14. One-sample raw Track + analytics `trajectory_too_short` preserves raw evidence while showing analytics unavailable.

### 21.2 Revision identity tests

1. Historical analytics identity fetches historical revision.
2. Active revision changes after search → overlay still uses pinned revision.
3. Returned revision id mismatches expected id → fail closed.
4. Pinned revision unavailable → no active-revision fallback.
5. Stable-id label fallback works when geometry metadata cannot resolve.

### 21.3 Timeline interaction tests

1. Pointer marker activation seeks to exact `offsetMs`, not pointer-derived approximation.
2. Enter seeks exact marker.
3. Space seeks exact marker.
4. Marker pointer-down does not trigger parent scrub first.
5. Arrows still rational-frame-step while marker is focused.
6. J/L still nudge one second while marker is focused.
7. Home/End still use subject bounds.
8. Marker target >=24×24.
9. One timeline only.
10. Dense markers at different offsets remain separately pointer/keyboard activatable without overlapping effective targets.
11. Same-offset marker clustering, if used, seeks once to that exact shared offset and names every clustered evidence item.

### 21.4 Overlay tests

1. Zone vertices project correctly under letterbox.
2. Zone vertices project correctly under pillarbox.
3. Trip line endpoints project correctly.
4. Crossing point projects correctly.
5. Matched vs contextual geometry has a non-colour cue.
6. Disabled geometry uses disabled grammar and cannot appear matched.
7. SVG raw geometry remains hidden where the UI-5 accessibility model requires it; layer-control semantics remain available.
8. A maximum-complexity zone set (64 zones × 64 vertices) produces bounded always-mounted descriptions: per-zone vertex count + normalized extent + at most 4 sample vertices, never a full vertex dump.
9. Repeated `describe(currentOffsetMs)` calls do not expand description size with playhead position or enumerate full polygon geometry.

### 21.5 Explanation tests

1. Revision/engine/reference point visible.
2. Zone visit/dwell/loitering wording.
3. Multiple visits.
4. Crossing count/time/direction.
5. Heading wording is image direction, not compass.
6. Stationary summary.
7. Unavailable reason.
8. Pending/Failed/Stale/NotConfigured/Disabled copy remains distinct.
9. Other identities do not replace selected identity.

### 21.6 Host regression

- Review and Inspector mount one shared Track evidence composition.
- Search → inspector → Review preserves analytics identity.
- Keyboard Enter Review route preserves identity.
- malformed Review provenance still fails closed.
- Review primary summary remains in initial 1366×768 viewport.

---

## 22. Visual QA

Run scripted browser QA at:

- 1366×768;
- 1440×900;
- 1920×1080;
- approximately 2560×1080.

Evidence conditions:

- normal/saturated;
- bright;
- dark;
- low contrast;
- letterboxed;
- pillarboxed.

States:

- analysed with zone visit;
- analysed with line crossing A→B;
- analysed with line crossing B→A;
- analysed with dwell + stationary overlap;
- multiple visits;
- geometry unavailable;
- analytics unavailable;
- analytics pending/stale;
- Investigation inspector selected;
- Review.

**Harness evidence requirement.** UI-5 visual QA had no served trajectory artefact. Slice 5 should close that test-fixture gap rather than carry it forward: add a small local msgpack trajectory fixture and a harness route for it (test tooling only) so the rendered matrix can exercise raw trajectory + analytical overlays together. The fixture must be deterministic and offline; production code must not be altered to make the harness work.

Measure/assert:

- no horizontal page overflow;
- no unexpected overlap;
- concurrent zone visits remain visually distinguishable through bounded packing/overflow aggregation at 2, 3 and greater-than-3 concurrency;
- one timeline;
- one video element/player implementation;
- Review player >=65%;
- ultra-wide rail cap/surplus-to-player retained;
- Review sticky behavior retained;
- primary summary visible initially at 1366×768;
- overlay projection stays inside true video content rectangle;
- marker hit targets/focus remain usable.

---

## 23. Implementation sequence

### Step 1 — base/gate

- wait for exact PR #64 merge-commit `main` CI green;
- branch from that exact SHA;
- record base in PR.

### Step 2 — pinned revision data

- add/refactor exact revision hook;
- add identity mismatch/fail-closed tests;
- no UI drawing yet.

### Step 3 — pure analytical evidence adapter

- introduce pure transforms;
- pin all interval/marker/overlay semantics with fixtures;
- no media lifecycle changes.

### Step 4 — timeline analytical presentation

- close decision 7 with fixed stacked lanes;
- implement hatch grammar;
- make markers exact-seek semantic controls;
- preserve player keyboard grammar.

### Step 5 — spatial overlays

- zones;
- lines;
- crossing points;
- same-control accessible semantics;
- matched/context/disabled treatments.

### Step 6 — explanation component

- evolve Slice-4 summary;
- preserve status vocabulary;
- add identity/reference-point footer.

### Step 7 — host wiring

- Review;
- Investigation;
- pinned revision loading/error states;
- no duplicate fetch/state mechanisms.

### Step 8 — event-marker token decision

- choose/validate candidate token against real rendered evidence and colour-vision simulations;
- freeze token/spec decision 2a in the same PR.

### Step 9 — full regression and visual QA

- focused Vitest;
- full web Vitest;
- `tsc -b`;
- production build;
- `python tools/verify_repo.py`;
- §26 matrix;
- PR #63 provenance regression tests.

### Step 10 — documentation / PR closure

- update parent plan status;
- close UI-spec decision 7;
- close UI-spec decision 2a with measured hue evidence;
- update capability roadmap status;
- document exact-head validation.

---

## 24. Files likely touched

Expected web surface:

- `src/web/mavi-web/src/features/video-review/TrackEvidence.tsx`
- `src/web/mavi-web/src/features/video-review/analyticsEvidence.ts` (new, recommended)
- `src/web/mavi-web/src/features/video-review/TrackAnalyticsExplanation.tsx` (new or rename/evolution)
- `src/web/mavi-web/src/features/visual-search/TrackInspector.tsx`
- `src/web/mavi-web/src/features/video-review/VideoReviewPage.tsx`
- `src/web/mavi-web/src/shared/evidence/EvidenceTimeline.tsx`
- `src/web/mavi-web/src/shared/evidence/timeline.ts`
- `src/web/mavi-web/src/shared/evidence/layers.ts` only if the existing contract genuinely needs an additive field
- `src/web/mavi-web/src/styles/features.css`
- `src/web/mavi-web/src/api/scene.ts` only for a focused retrieval helper if needed
- `src/web/mavi-web/src/app/queryClient.ts` only if an immutable revision key is not already sufficient
- corresponding tests and visual-QA fixtures/assertions.

Expected backend changes: **none**.

If implementation discovers that a required persisted fact is absent from `TrackDetailAnalytics`, stop and document the contract gap before adding an endpoint/contract change.

---

## 25. Dependency / offline impact

Expected: **none**.

No new npm, .NET, Python, model, native, OS, database or external asset dependency is justified for Slice 5.

Any proposed dependency is automatically a scope review and must satisfy AGENTS.md offline policy in the same PR.

---

## 26. Slice-7 hardening note retained

Do not interrupt Slice 5 for this P3 unless it becomes directly relevant:

The browser `parseTrajectory` currently validates finite coordinates but does not enforce normalized `[0,1]` center coordinates as strictly as the worker/domain contract does.

Record for Slice 7 hardening:

- add malformed-artifact tests for x/y outside `[0,1]`;
- make browser parsing reject them, matching the producer/application decoder.

Correct worker-produced evidence cannot hit this path today, so it is not a Slice-5 blocker.

---

## 27. Exit criteria

Slice 5 is complete only when all are true:

1. one Evidence Player remains the only analytical playback surface;
2. exact pinned scene revision is used; no active-revision substitution;
3. every persisted analytical fact shown is explainable from typed detail data;
4. zone/line/crossing overlays align under letterbox and pillarbox;
5. crossing/entry/exit markers seek to exact evidence offsets by pointer and keyboard;
6. zone/dwell and stationary intervals use the single timeline and bounded analytical lane families; overlapping zone visits remain distinguishable through deterministic capped packing/overflow aggregation without unbounded height;
7. raw one-sample evidence remains valid even when Scene Analytics reports `trajectory_too_short`;
8. unavailable/pending/failed/stale/not-configured/disabled remain distinct;
9. event/crossing marker hue decision 2a is closed with rendered evidence;
10. timeline presentation decision 7 is closed and documented;
11. no new dependency/offline burden;
12. exact-head CI green;
13. visual QA matrix clean;
14. lighter independent Slice-5 review finds no P1/P2 before merge.

Do not merge on “tests green” alone if identity, evidence semantics or rendered geometry has not been independently checked.
