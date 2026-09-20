# Spatial & Temporal Track Analytics — Implementation Plan

**Date:** 2026-09-20 (implementation-grade revision)  
**Status:** Next feature (stage 1 of `capability-roadmap.md`; technical context in `capability-implementation-roadmap.md`). Planning only. No code, migration, dependency or runtime change accompanies this plan.  
**Base:** `main@370b65fb2e149d97720825d2e09a7d6876c611aa`.  
**Product intent:** turn the trajectories MAVI already persists into searchable, explainable scene facts (zones, trip lines, dwell, crossings, direction, stationary and stopped objects, loitering, counts, occupancy, heatmaps) without a new model, a new dependency, or any change to the qualified detector/tracker worker.

Every rule below that begins with **Decision** is frozen for implementation; changing it is a plan change, not an improvisation.

---

## A. What the code actually provides today

| Fact | Where | Consequence |
|---|---|---|
| A Track has `ProcessingRunId`, `VideoAssetId`, class, media offsets, UTC timestamps, counts, confidences, a representative observation and a `TrajectoryArtifactId`. | `Mavi.Domain/Intelligence/Track.cs` | Camera is reached through `VideoAsset.CameraId`; a Track never changes after completion. |
| The trajectory artefact is msgpack `{v: 1, points: [[offsetMs, centreX, centreY], …]}`, one sample per detection, strictly increasing integer offsets, floats normalised to the source frame, sealed with SHA-256 under the platform evidence root. | `src/vision/mavi_vision/video/trajectory.py`, `common/analytical.py`, `features/video-review/trajectory.ts` | **Only the bounding-box centre is available per sample.** Width/height exist only for the four persisted `Observation` rows per Track. |
| Completion is one transaction: validate → seal evidence → build entities → exclusive advisory lock → allocate `processing_visibility_sequence` → `MarkCompleted` → `MarkProcessed` → commit. | `ProcessingResultStore.CompleteAsync`, `ProcessingVisibilityBarrier` | A run is searchable once `VisibilitySequence` is set and ≤ the reader's snapshot sequence. |
| Search first page takes the shared barrier lock, allocates a snapshot sequence, and encodes it in the cursor with a SHA-256 filter fingerprint; default scope is the latest visible completed run per video; ordering `StartTimestampUtc DESC, Id DESC`. | `TrackSearchRepository`, `TrackCursorCodec`, `TrackSearchService` | Analytics facts must be gated by the same snapshot sequence to keep pages consistent. |
| Query keys are strictly whitelisted at the endpoint; unknown keys → 400 `track_search_invalid`. The web `searchState.ts` mirrors the whitelist and canonicalises URL state. | `TrackEndpoints.cs`, `searchState.ts` | New predicates are added in both places plus the fingerprint. |
| No background hosted service exists in the platform; recovery is lease-driven. | `src/platform` (no `BackgroundService`) | A post-processing stage needs the first hosted service, or an on-demand trigger. |
| Overlays project normalised coordinates into the letterboxed frame (`contentRect`, `projectPoint`); the evidence player drives a rAF playhead; the trajectory is interpolated client-side. | `features/video-review/overlay.ts`, `TrackEvidencePlayer.tsx`, `trajectory.ts` | Zone/line overlays reuse this projection unchanged. |
| Cameras have code, name, description, location, time zone, active flag; no reference image. | `Mavi.Domain/Cameras/Camera.cs` | The scene editor must obtain a reference frame from imported video. |
| Domain style: sealed aggregates, `Create` factories, intent methods, `DomainValidationException(code)`, UUIDv7 ids, UTC everywhere, snake_case tables via fluent configuration, enums as strings, check constraints, hand-written migrations `yyyyMMddHHmmss_Name`. | `Mavi.Domain`, `Mavi.Infrastructure/Persistence` | New aggregates follow the same style. |
| Tests: Domain (pure), Application (stubs), Integration (real PostgreSQL via `MAVI_TEST_DB_CONNECTION`, `mavi_test` only, serialised collection), Vitest + jsdom without msw, `WorkerContractV2Tests` pin the completion contract. | `tests/`, `src/web/mavi-web/src/test` | Test layers in §AC map onto these. |

---

## B. Scope and principles

**In scope.** Per-camera scene configuration with revisions; a deterministic analytics stage over sealed trajectories; typed derived facts; analytic predicates in Track search; evidence explanation; aggregate counts, occupancy, heatmaps; retry and re-analysis; observability in the Processing surfaces.

**Principles.**
1. Derived facts, never inference: every fact traces to trajectory samples plus one configuration revision plus one algorithm version.
2. Scene edits never reinterpret history silently.
3. No false physical precision.
4. "Not analysed" is never displayed as "no matches".
5. No new external dependency; no change to the worker or its contract; no change to `Track`, `Observation`, `Artifact`.
6. Everything offline, everything reproducible from the same inputs.

**Explicit non-goals.** ANPR/OCR, appearance attributes, embeddings, ReID/Entity, event rules beyond the transparent loitering rule, natural-language search, cases/reporting, live ingestion, physical speed without calibration, an operator-editable rules engine, a generic report builder, a reference-frame capture from live cameras.

---

## G. Core architecture decision: analytics lifecycle

Three options were analysed against the completion transaction and lease model described in §A.

| Criterion | A — inside `ProcessingRun` completion | B — separate deterministic stage | C — lazy compute at query time |
|---|---|---|---|
| Failure isolation | A geometry or analytics fault fails or delays a completion that already carries sealed, valid detector evidence; compensation would have to unseal evidence. | Analytics failure leaves the run Completed and searchable; the analysis unit records the failure. | Failures surface as slow or erroring searches, per query. |
| Retry semantics | Bound to the worker's lease/attempt model, which exists to retry video processing, not geometry. | Own bounded attempts, idempotent by construction. | Retried on every query; no persistent state to reason about. |
| Processing latency | Adds O(samples × geometry) to the exclusive-lock section of completion, extending the window in which search first pages wait. | Runs after commit; completion latency unchanged. | Shifts cost to every search; unbounded fan-out over runs. |
| Search visibility | Facts visible exactly when the run is visible. Simple. | Facts visible slightly after the run; readiness must be explicit. | Facts computed per query; visibility trivially "now", correctness depends on cache. |
| Re-analysis after geometry edit | Requires a "completion" without a worker; the model has no such state. | Natural: a new analysis unit for the new revision. | Natural, but recomputes everything each time. |
| Historical reproducibility | Facts bound to run only; the revision in force is implicit. | Facts bound to (run, revision, algorithm version) explicitly. | Nothing persisted; reproducibility only if inputs and code are unchanged. |
| Transaction boundaries | Widens the single most sensitive transaction in the system to include operator-editable configuration. | Own transaction per analysis unit, using the existing barrier for visibility. | Read-only queries; fine. |
| Worker coupling | None to the Python worker, but couples completion to configuration state. | None. | None. |
| Operator UX | Nothing extra to explain. | One readiness indicator per run. | Latency and "computing…" states per query. |
| Scale | Bounded by completion; fine for one video, awkward for large configurations. | Linear per unit; can be scheduled and throttled. | Quadratic in practice (runs × queries). |
| Future attributes/events | Attributes come from the worker anyway; events would compound the completion transaction. | Events reuse the same stage and unit. | Same query-time explosion. |
| Compatibility with lease/job model | Must not extend it. | Independent; borrows patterns (`FOR UPDATE SKIP LOCKED`, attempt counting) without touching `VisionJob`. | N/A. |

**Decision: Option B.** Analytics are a separate, deterministic, idempotent post-processing stage executed in the .NET application process and bound to an explicit **analysis unit**. Option A is rejected because it would put operator-editable geometry inside the evidence-sealing transaction; Option C is rejected because search latency and reproducibility would both depend on recomputation.

### Lifecycle

**Analysis unit.** `SceneAnalysis` — one row per (`ProcessingRunId`, `SceneConfigurationRevisionId`, `AlgorithmVersion`). It is the unit of scheduling, retry, visibility and re-analysis. It reuses `ProcessingRun`'s vocabulary where the meaning is the same.

| State | Meaning | Transitions |
|---|---|---|
| `Queued` | Created by the reconciler (§G "Scheduling") or by an explicit re-analysis request; not yet claimed. | → `Running` on claim |
| `Running` | Claimed by the analytics host; `AttemptCount` incremented; a fresh `ClaimTokenHash` and `LeaseExpiresAtUtc` set (see "Attempt ownership and fencing"). | → `Completed`, → `Failed` (by the owner, or by the reconciler on terminal exhaustion), → reclaimed as a new `Running` attempt after the lease expiry grace with attempts left |
| `Completed` | Every Track of the run has an outcome row (`Analysed` or `Unavailable`); facts committed; `VisibilitySequence` allocated. | terminal, except → `Superseded` |
| `Failed` | Attempts exhausted or a permanent failure (§AE). `FailureCode` set. | → `Queued` by explicit retry |
| `Superseded` | A later `Completed` analysis exists for the same run against a newer revision or algorithm version. Facts remain queryable by revision. | terminal |

Derived, not stored, **readiness** for a run as seen by the API and UI: `NotConfigured` (the camera has never had a scene revision; no unit exists), `Disabled` (the camera's active revision contains no enabled zone or line, §I; no unit is created), `Pending` (unit `Queued`/`Running`, or no unit yet for the active revision), `Ready` (a `Completed` unit for the active revision and current algorithm version), `Failed`, `Stale` (only a `Completed` unit for an older revision or algorithm version exists; the active pair has no unit yet or is pending). `Stale` is what §P calls "history intact, current geometry not yet applied".

**Scheduling.** A hosted `SceneAnalyticsHostedService` in `Mavi.Api` (the platform's first `BackgroundService`; Development runs it in-process, Production profiles run it in the API host, which ADR-008 already places on the operational plane) performs two loops:

1. **Reconcile** every `ReconcileIntervalSeconds` (default 5): for each camera whose active revision contains at least one enabled zone or line (a camera with no revision, or whose active revision is empty, is skipped and never receives units), find `ProcessingRun`s with `Status = Completed AND VisibilitySequence IS NOT NULL` whose video belongs to that camera and for which no `SceneAnalysis` exists for (active revision, current algorithm version), and insert `Queued` units. Scope of automatic reconciliation is **runs completed after the revision was activated** plus **runs completed after deployment**; older runs are analysed only on explicit request (§AD).
2. **Execute**: claim one claimable unit (`Queued`, or `Running` with `LeaseExpiresAtUtc < now`) with `SELECT … FOR UPDATE SKIP LOCKED`; in that same transaction increment `AttemptCount`, generate a new 32-byte random claim token, store `ClaimTokenHash = SHA-256(token)`, set `LeaseExpiresAtUtc = now + LeaseSeconds`, set `Running`, commit **before** running the engine. Run the engine outside any transaction under a cancellation bound of `MaxUnitDurationSeconds`. Then, in one final transaction: lock the unit `FOR UPDATE`, **re-validate ownership** (below), delete any facts for this unit id (idempotency), insert facts and outcomes, take the exclusive barrier lock, allocate a `processing_visibility_sequence`, mark `Completed`, mark older `Completed` units for the same run `Superseded`, commit. Reclaim and terminal exhaustion are both **fenced transitions taken by the reconciler under `FOR UPDATE`**, and both only act on a unit whose `LeaseExpiresAtUtc` passed more than `ReclaimGraceSeconds` (default 60) ago. With attempts remaining the reconciler reclaims (new attempt, new token). With `AttemptCount` already at `MaximumAttempts` (default 3) it instead marks the unit `Failed` with `analytics_attempts_exhausted` **and clears `ClaimTokenHash`**, which invalidates the overrunning attempt exactly as a reclaim would; that attempt's later completion then fails `RequireOwnership` and writes nothing. Because both paths take the same row lock, an attempt that finishes inside the grace wins the race and completes normally.

**Attempt ownership and fencing (Decision).** Every running attempt is fenced exactly like a `VisionJob` lease, with the same shape of fields: `AttemptCount`, `ClaimTokenHash` (SHA-256 of an opaque token that exists only in the executing host's memory for that attempt), `LeaseExpiresAtUtc`. Ownership belongs to the (attempt number, claim token) pair recorded on the row; lease expiry makes the unit *reclaimable*, and ownership is lost the moment another claim succeeds (new attempt number, new token), never merely by the clock. `SceneAnalysis.RequireOwnership(attemptCount, claimToken)` mirrors `VisionJob.RequireValidLease` and passes only when `Status == Running`, `AttemptCount` equals the caller's attempt and `SHA-256(claimToken) == ClaimTokenHash`.

- **Completion** calls `RequireOwnership` inside the final transaction, after the `FOR UPDATE` lock and before any write. A stale attempt fails with `analytics_attempt_stale` and performs **none** of: deleting facts, inserting facts or outcomes, superseding another unit, allocating a visibility sequence, overwriting failure state, or marking completion. The stale host logs the code with the unit id and its attempt number and discards its in-memory results.
- **Failure reporting** is fenced the same way: marking `Failed` or recording `FailureCode`/`FailureDetails` requires `RequireOwnership`; a stale attempt cannot mark a newer attempt failed. (Attempt exhaustion is decided by the reconciler on the row it holds under `FOR UPDATE`, not by the expired attempt.)
- **Reclaim and terminal exhaustion** are the only two ways a unit changes hands, both fenced under `FOR UPDATE` and both gated by `ReclaimGraceSeconds`: reclaim increments `AttemptCount` and replaces `ClaimTokenHash`; exhaustion moves the unit to `Failed` and clears `ClaimTokenHash`. Either way the previous token can never validate again, so a still-running attempt cannot resurrect a terminated unit and the reconciler never overwrites a unit someone still owns.
- **No heartbeat in v1.** Expected unit duration is seconds to low minutes (§Z); `LeaseSeconds` (default 900) must exceed `MaxUnitDurationSeconds` (default 300) with margin, and options validation enforces `LeaseSeconds ≥ 2 × MaxUnitDurationSeconds`. If a later algorithm makes units long-running, lease renewal is added as a fenced heartbeat then, not now.

Why the barrier: allocating a visibility sequence at analysis completion lets search snapshots gate analytics exactly as they gate runs (§H, §S) with no new mechanism. The exclusive lock is held only for the short final transaction, as completion already does.

Configuration lives in `SceneAnalyticsOptions` (validated on start like `VisionProcessingOptions`): `Enabled`, `ReconcileIntervalSeconds`, `LeaseSeconds`, `MaxUnitDurationSeconds`, `ReclaimGraceSeconds`, `MaximumAttempts`, `MaxConcurrentUnits` (default 1 in Development); validation refuses `LeaseSeconds < 2 × MaxUnitDurationSeconds`.

---

## H. Search visibility semantics

Given `processing = Completed` and analytics readiness other than `Ready`:

| Surface | Behaviour |
|---|---|
| Ordinary Track search (no analytic predicate) | Unchanged. The Track is visible. Analytics readiness does not gate Track visibility. |
| Zone, line, dwell, direction, stationary predicates | The query is evaluated **only over runs whose analysis unit for the requested revision is `Completed` and visible in the snapshot**. Every other run in the query's scope is reported, never dropped silently, in the response's `analyticsCoverage` block. |
| Loitering | Same as zone predicates (loitering is a persisted per-Track flag with its thresholds). |
| Aggregates | Computed over covered runs only; the same `analyticsCoverage` block with the same `complete` rule is returned; a request whose scope has **zero** covered runs returns `200` with empty series and `coverage.evaluatedRuns = 0`, plus the pending/failed/stale/not-configured/disabled counts, so the UI renders "Not analysed yet" or "Analytics disabled for this camera", never a zero-valued chart. |

**Decision: partial-results metadata, not an error.** Every response to a query that used at least one analytic predicate carries:

```
analyticsCoverage: {
  sceneRevisionId, algorithmVersion,
  evaluatedRuns, pendingRuns, failedRuns, notConfiguredRuns, disabledRuns, staleRuns,
  complete: bool   // every unevaluated bucket is zero
}
```

`evaluatedRuns` counts runs whose facts were actually evaluated for the query; every other run in the query's scope falls into exactly one of the five remaining buckets. `notConfiguredRuns` counts **only** runs of cameras that are `NotConfigured` (§G) — the camera has never had a scene revision — and runs of a camera whose active revision deliberately disables analytics are counted under `disabledRuns` instead. The two are never merged: an operator is owed the difference between a gap and a switch-off. `complete` is true only when **every** run in scope was evaluable, which means `pendingRuns`, `failedRuns`, `notConfiguredRuns`, `disabledRuns` and `staleRuns` are all zero; an unconfigured or disabled run was not evaluated for an analytics-dependent query, so it makes `complete = false` like a pending one. An optional query flag `analyticsCoverage=complete` makes the service return `409 track_analytics_incomplete` (same block in the problem details) whenever any of the five buckets is non-zero, for callers that must not work with partial data (bulk exports later). The UI uses the metadata to show a persistent notice naming each non-zero bucket ("3 runs not yet analysed, 1 run's camera has analytics disabled") with a link to the Processing view; it never renders an empty list or a zero-valued aggregate without that notice when `complete = false`.

An analytic predicate that names a zone or line belonging to a camera other than the query's `cameraId`, or that names a revision that does not exist for the camera, is `400 track_search_invalid` like any other malformed filter.

---

## I. Scene configuration model

**Decision: whole-configuration revisions; stable geometry identities across revisions; save-and-activate in one step (no drafts in v1).**

Per-object revisions were rejected because a search predicate and an analysis unit need one coherent snapshot of all zones and lines at once; a hybrid (per-object versions inside a configuration revision) adds a level of indirection with no consumer. Server-side drafts were rejected for v1 because the editor holds unsaved state locally and nothing else needs a draft.

| Aggregate | Fields | Notes |
|---|---|---|
| `SceneConfiguration` | `Id`, `CameraId` (unique, immutable), `ActiveRevisionId?`, `CreatedAtUtc`, `UpdatedAtUtc` | One per camera; created on first save. |
| `SceneConfigurationRevision` | `Id` (UUIDv7), `SceneConfigurationId`, `RevisionNumber` (1, 2, …, unique per configuration), `CreatedAtUtc`, `CreatedBy` (string; server-controlled constant `development-unattributed` until identity exists, §AG), `Note` (≤ 500), `ReferenceFrameVideoAssetId?`, `ReferenceFrameOffsetMs?` | Immutable after insert. `ReferenceFrameArtifactId` was **not** created in slice 1: no frame is extracted in this increment, so a stored still would have nothing to hold. The pair is accepted whole or not at all, the video must belong to the same camera and the offset must fall inside its duration. |
| `SceneZone` | `RevisionId`, `ZoneId` (stable across revisions), `Name` (≤ 64, unique within a revision), `Kind` (`General`, `Restricted`, `Entrance`, `Exit`; extensible enum stored as string), `Enabled`, `Vertices` (ordered, 3–64 points, normalised, fixed 6-decimal precision, stored as jsonb array of `[x, y]`), `LoiteringThresholdSeconds?` | Composite key (`RevisionId`, `ZoneId`). |
| `TripLine` | `RevisionId`, `LineId` (stable), `Name`, `Enabled`, `A` (point), `B` (point), `Directed`, `AToBLabel` (≤ 32, e.g. "inbound"), `BToALabel` | Composite key (`RevisionId`, `LineId`). |
| `CameraCalibration` (future) | reserved name; not created in this increment | §N. |

**Activation semantics.** `PUT` of a new configuration for a camera creates the next revision with the submitted zones and lines (client supplies existing `zoneId`/`lineId` values to keep identities; new objects get server-issued ids), sets `ActiveRevisionId`, and returns the revision. Previous revisions remain readable.

**Empty active revision = analytics intentionally disabled for that camera (Decision).** A revision with no enabled zone and no enabled line is valid and is the only way to switch analytics off; `ActiveRevisionId` points to it like any other revision. Consequences, all consistent with §G and §H: the reconciler creates no units for runs of that camera while such a revision is active, so no empty `Completed` analysis is ever produced; run readiness reads `Disabled` (distinct from `NotConfigured`, which means the camera never had a revision); an analytics-dependent search that resolves the active revision of a disabled camera reports every run of that camera under `disabledRuns`, never under `notConfiguredRuns`, and therefore `complete = false`; a search that explicitly names a historical `sceneRevisionId` of that camera evaluates that revision's persisted facts normally; historical revisions and their facts are untouched; re-enabling is simply saving a later revision with geometry, after which new runs are analysed automatically and earlier runs follow §P. The scene editor requires an explicit confirmation ("Disable analytics for this camera") before saving an empty revision, and the scene response carries `analyticsEnabled: false` for it.

**Validation on save (all `DomainValidationException` codes, HTTP 400):** `scene_zone_vertex_count` (3–64), `scene_zone_vertex_range` (each coordinate in [0, 1]), `scene_zone_self_intersecting`, `scene_zone_degenerate` (area below `1e-6` normalised or collinear), `scene_zone_name_duplicate`, `scene_line_endpoints_identical` (distance below `0.005`), `scene_line_range`, `scene_line_name_duplicate`, `scene_geometry_count` (≤ 64 zones and ≤ 64 lines per revision), `scene_identity_unknown` (client-supplied id not present in the previous revision), `scene_camera_inactive` (camera `IsActive = false`). **Added in slice 1**, because the frozen list did not cover every way a request can be malformed: `scene_zone_name_required` / `scene_zone_name_too_long`, `scene_zone_kind_invalid`, `scene_zone_loitering_threshold_invalid` (1 to 86 400 s), `scene_line_name_required` / `scene_line_name_too_long`, `scene_line_label_too_long`, `scene_note_too_long`, `scene_identity_duplicate` (one identity supplied twice in a revision), `scene_reference_frame_incomplete` / `scene_reference_frame_not_found` / `scene_reference_frame_camera_mismatch` / `scene_reference_frame_offset_invalid`, `scene_revision_invalid` and `scene_configuration_mismatch`. Names are compared case-insensitively, so "Gate" and "gate" collide; the operator's own capitalisation is stored unchanged. **Degeneracy is decided before self-intersection**, except that a polygon whose vertices are all collinear is degenerate rather than self-intersecting: a bow tie encloses no net area either, and the two must not be confused.

---

## J. Coordinate convention and reference point

**Decision (frozen).**
- Coordinates are normalised to the **source video frame** of the `VideoAsset`: origin top-left, `x` right, `y` down, range `[0, 1]` on both axes. This is the convention `Observation`, the trajectory artefact and `overlay.ts` already use.
- Stored with fixed precision of six decimals; comparisons in the engine use `double` with an epsilon `1e-9` after rounding inputs to six decimals, so equality and hashing are stable.
- **Reference point of a Track sample = the trajectory sample itself, i.e. the bounding-box centre**, because that is what trajectory v1 persists. Every fact records `referencePoint = "bbox-centre"`.

Why not bottom-centre now: for persons and vehicles the foot point is the better ground-contact reference and would make zones drawn on the ground plane behave intuitively; but per-sample box height is not persisted, and deriving it from the single representative box would fabricate geometry. **Planned follow-up (not this increment):** trajectory format v2 emitted by the worker with `[offsetMs, cx, cy, h]` (or `[offsetMs, cx, bottomY]`), additive, both formats accepted by parser and browser; when a Track's trajectory is v2 the engine uses `referencePoint = "bbox-bottom-centre"`, records it on the facts, and a new algorithm version marks v1-based analyses `Stale`. That change touches the worker and its completion evidence and is therefore scheduled as its own qualified slice after this increment.

**Letterboxing.** The editor and evidence overlays draw geometry through `contentRect` + `projectPoint`/`projectBox` from `features/video-review/overlay.ts`, so a zone drawn on a letterboxed reference frame maps to the same normalised coordinates the engine evaluates. Editing converts pointer positions back through the inverse of `contentRect` (to be added beside it as `unprojectPoint`).

---

## K. Geometry semantics (frozen)

Notation: `ε = 0.005` normalised (jitter tolerance), `k = 3` samples (confirmation window), `t_min = 1000 ms` (repeat-crossing suppression), `g_max = 2000 ms` (maximum bridged gap). These are parameters of algorithm version `scene-analytics-v1` (§R) and are recorded on every analysis unit.

**Point-in-polygon.** Even–odd (crossing-number) rule on the polygon's vertices in order. A point exactly on an edge or vertex (within `1e-9` after rounding) is **inside**. Polygons are simple (validated), orientation-agnostic.

**Line crossing.** For consecutive samples `P(i)`, `P(i+1)` and line segment `A–B`:
- Compute signed side `s(i) = sign(cross(B−A, P(i)−A))`; treat `|cross| < ε·|B−A|` as side `0` (the on-line band).
- A **candidate crossing** occurs between `i` and `i+1` when the two open segments properly intersect, or when one endpoint lies in the band and the last non-zero side before it differs from the first non-zero side after it.
- **Confirmation (debounce):** the crossing is recorded only if the reference point was on the departing side by at least `ε` at some sample within the previous `k` samples (or since Track start) and reaches at least `ε` on the arriving side within the next `k` samples (or by Track end). Otherwise it is jitter and ignored. **Both windows are measured from the crossing itself** (slice 1), not from the samples that happen to bracket it, so a Track that drifts into the band and lingers there past `k` samples is not credited with a crossing at an instant it cannot be pinned to.
- **Repeat suppression:** two confirmed crossings of the same line in the same direction less than `t_min` apart collapse into the first. Opposite-direction crossings are always distinct.
- **Direction:** `aToB` if the arriving side is the left side of `A→B` in image coordinates; else `bToA`. **Spelled out in slice 1:** `y` grows downwards, so the left of a line drawn left to right is the side visually **above** it, where the cross product of the line's direction with the vector to the point is negative. A Track moving upwards through such a line therefore crosses `aToB` and one moving downwards crosses `bToA`; swapping the endpoints reverses both. The editor draws the arrow from this rule. Undirected lines still record direction; the labels are what the operator sees.
- **Crossing time and point:** linear interpolation of the segment `P(i)→P(i+1)` at the intersection parameter; time interpolated between the two sample offsets.
- **Collinear overlap** (segment lies along the line) is never a crossing.

**Zone entry/exit (visits).**
- A visit **opens** at the first sample inside the zone that follows a sample outside (or at Track start).
- A visit **closes** when the reference point is outside by at least `ε` distance from the polygon boundary for `k` consecutive samples, at the first of those samples; brief excursions shorter than `k` samples do not close a visit. Touching the boundary from inside keeps the visit open.
- **Starts inside:** visit opens at sample 0 with `BeganInside = true`.
- **Ends inside:** visit closes at the last sample with `EndedInside = true`.
- **Re-entry** after a closed visit opens a new visit with `VisitIndex + 1`.
- Entry and exit times are the interpolated boundary-crossing instants where a segment crosses the polygon boundary; when the visit opens at Track start or closes at Track end the sample offset is used.
- Dwell of a visit = exit − entry; Track dwell per zone = sum over visits.

**Interpolation.** Linear in normalised space and in time between consecutive samples. No extrapolation beyond the first or last sample; a Track's facts are confined to `[firstOffset, lastOffset]`.

**Missing samples (gaps).** A gap between consecutive samples longer than `g_max`: no crossing or visit boundary is inferred across it; an open visit closes at the sample before the gap with `ClosedByGap = true`; the gap count and total gap duration are recorded on the motion summary. Analysis of the Track continues after the gap as if it began there (a visit may re-open with `BeganInside = true` after a gap).

**Corrupt or missing trajectory.** If the artefact is missing from the evidence root, its SHA-256 does not match `Artifact.Sha256`, msgpack fails the v1 validation, or it has fewer than two samples, the Track receives an outcome row with `Outcome = Unavailable` and `Reason` ∈ {`trajectory_missing`, `trajectory_integrity_failed`, `trajectory_invalid`, `trajectory_too_short`} and **no facts**. The analysis unit still completes; `UnavailableTrackCount` is visible on the unit and in coverage metadata. A Track is never silently treated as "no events".

**Direction of travel.** Eight-way image heading (`N, NE, E, SE, S, SW, W, NW`, with `N` = decreasing `y`) from the displacement between the first and last valid samples of the Track; `None` when displacement < `0.02` normalised. Also recorded per visit: the zone entered from / exited towards as a heading. No compass claim.

---

## L. Stationary and stopped-object semantics

**Decision.** Stationarity is evaluated on the reference-point path with a sliding window, not on raw bbox jitter:
- Smooth the reference point with a centred moving median over `w = 5` samples (edges use available samples).
- A sample is **stationary-candidate** if the maximum displacement of the smoothed point within the trailing window of duration `T_window` is below `d_stat`. Near the start of an observed run the window uses only the samples that exist, exactly as the smoothing filter treats its edges (slice 1); the opening samples of a moving Track therefore qualify briefly, which costs nothing because such a run is far shorter than `T_min`. Requiring a fully covered window instead would start every interval `T_window` late and would make a Track that stood still from its first sample unreportable until `T_window + T_min` had passed.
- A **stationary interval** is a maximal run of stationary-candidate samples of duration ≥ `T_min`.
- Class-specific defaults, all in normalised frame units and seconds: persons `d_stat = 0.015`, `T_window = 3 s`, `T_min = 5 s`; vehicles `d_stat = 0.010`, `T_window = 3 s`, `T_min = 10 s`. Tracks shorter than `T_min` never yield intervals.
- Persisted per Track: `StationaryIntervals` (list of `[startOffsetMs, endOffsetMs]`, jsonb, for evidence), `LongestStationaryMs`, `TotalStationaryMs`, `StationaryInZoneIds` (zones containing the interval midpoint).

**`stationary person`** and **`stopped vehicle`** are the same computation with the class-specific thresholds and are searched through one predicate `minStationaryMs` combined with `objectClass`; the UI labels them differently. Perspective is not corrected: the same normalised threshold means a larger real distance far from the camera, and the documentation and UI say "stationary in image space". Calibration (§N) would allow class-independent metric thresholds later.

---

## M. Loitering semantics

**Decision.** Loitering is a transparent persisted rule, evaluated per (Track, zone):
- class = `Person`;
- accumulated dwell in the zone (sum of visits) ≥ threshold, where threshold = zone `LoiteringThresholdSeconds` if set, else the algorithm default `120 s`;
- optional maximum excursion: if the zone has `LoiteringMaxExcursionSeconds` (v1: not exposed; reserved), visits separated by more than it do not accumulate.

Persisted on the zone-visit summary for the Track: `Loitering = true`, `LoiteringThresholdSeconds` used, `LoiteringDwellMs` observed, the visit indices that contributed. The inspector shows "Loitering: 2 visits, 143 s in Zone 3, threshold 120 s (revision 4)". No model is involved and no other classes are flagged in v1.

---

## N. Physical speed policy

**Decision.** No `km/h`, `m/s` or any metric unit appears in the API, UI or persisted facts in this increment. Persisted motion diagnostics are `PathLengthNormalised` and `MeanDisplacementRateNormalisedPerSecond`, labelled as engineering diagnostics and hidden behind a disclosure in the UI. A future `CameraCalibration` (homography from image to a ground plane with a validation record and stated error) would enable metric conversion as a separate increment with its own evidence; the schema reserves nothing for it now beyond the name.

---

## O. Derived persistence model

**Decision: typed tables for searchable facts; jsonb only for evidence-display detail inside a typed row; nothing generic.** A single untyped event table would give no constraints, no useful indexes and would push validation into consumers; per-family typed tables keep invariants in the database and make stage-7 events an additional typed table rather than a re-design.

| Table | Row per | Key columns | Purpose |
|---|---|---|---|
| `scene_configurations` | camera | `id`, `camera_id` (unique), `active_revision_id`, timestamps | Anchor |
| `scene_configuration_revisions` | revision | `id`, `scene_configuration_id`, `revision_number` (unique per configuration), `created_at_utc`, `created_by`, `note`, `reference_frame_*` | Immutable |
| `scene_zones` | zone × revision | (`revision_id`, `zone_id`), `name`, `kind`, `enabled`, `vertices` jsonb, `loitering_threshold_seconds` | Immutable |
| `trip_lines` | line × revision | (`revision_id`, `line_id`), `name`, `enabled`, `ax, ay, bx, by`, `directed`, labels | Immutable |
| `scene_analyses` | analysis unit | `id`, `processing_run_id`, `revision_id`, `algorithm_version`, `parameters_sha256`, `status`, `attempt_count`, `claim_token_hash` (32 bytes, null when not `Running`), `lease_expires_at_utc`, `queued/started/completed_at_utc`, `visibility_sequence`, `analysed_track_count`, `unavailable_track_count`, `failure_code`, `failure_details` | Unique (`processing_run_id`, `revision_id`, `algorithm_version`) |
| `track_analysis_outcomes` | Track × analysis | (`analysis_id`, `track_id`), `outcome` (`Analysed`/`Unavailable`), `reason`, `reference_point`, `sample_count`, `gap_count`, `gap_total_ms` | One row per Track per unit, always |
| `track_zone_visits` | visit | `id`, `analysis_id`, `track_id`, `zone_id`, `visit_index`, `entry_offset_ms`, `exit_offset_ms`, `entry_timestamp_utc`, `exit_timestamp_utc`, `dwell_ms`, `began_inside`, `ended_inside`, `closed_by_gap`, `entry_heading`, `exit_heading` | Searchable |
| `track_zone_summaries` | Track × zone × analysis | (`analysis_id`, `track_id`, `zone_id`), `visit_count`, `total_dwell_ms`, `first_entry_timestamp_utc`, `last_exit_timestamp_utc`, `loitering`, `loitering_threshold_seconds`, `loitering_dwell_ms` | The row search predicates hit |
| `track_line_crossings` | crossing | `id`, `analysis_id`, `track_id`, `line_id`, `crossing_index`, `offset_ms`, `timestamp_utc`, `direction` (`AToB`/`BToA`), `point_x`, `point_y` | Searchable |
| `track_motion_summaries` | Track × analysis | (`analysis_id`, `track_id`), `heading`, `path_length_normalised`, `mean_displacement_rate`, `longest_stationary_ms`, `total_stationary_ms`, `stationary_intervals` jsonb, `stationary_zone_ids` jsonb | Searchable by the two duration columns |

**Calculated on demand (not persisted):** occupancy series, counts per bucket, peak occupancy, heatmaps (§T, §U). They are aggregations over the tables above or over trajectories and are cheap to recompute for a camera/window; persisting them would create a cache-invalidation problem on every re-analysis.

All fact rows carry `analysis_id`; the unit carries run, revision and algorithm version, so every fact is bound to all three without denormalising them per row. `track_id` is denormalised onto facts for indexing.

---

## P. Revision and historical semantics

Scenario: Zone A exists in revision 1; analyses completed against revision 1; the operator edits Zone A.

**Decision.**
1. Saving creates revision 2 and activates it. Revision 1 and every fact bound to it remain exactly as they were; nothing is mutated or deleted.
2. Runs completing after activation are analysed against revision 2 automatically (reconciler).
3. Runs already analysed against revision 1 are **not** re-analysed automatically. Their readiness for the active revision is `Stale`; search against revision 2 reports them in `analyticsCoverage.staleRuns`; search may explicitly target `sceneRevision = 1` and get the historical facts unchanged.
4. Re-analysis is **explicit**: "Analyse existing runs with this revision" on the scene page (per camera; scope = latest visible completed run of each video of that camera by default, with an option for all completed runs), or per run from the Processing page. It creates new `Queued` units; on completion the revision-1 unit becomes `Superseded` (still queryable by revision).
5. Re-analysis never mutates old facts: a new unit produces a new fact set. Deleting facts happens only for the same unit id on retry (idempotency).
6. The detector/tracker never re-runs for analytics; trajectories are inputs, not outputs.

Retention: revisions and superseded units are retained indefinitely in this increment. A future housekeeping policy may delete `Superseded` units older than N revisions; it is out of scope and would be an explicit, audited operation.

---

## Q. Re-analysis model

Compared: reusing `ProcessingRun` (rejected: it is the worker's completion record with lease, attempts, provenance and visibility tied to video processing; overloading it would blur the evidence boundary and complicate `VisionJob` invariants); per-Track analytic revision rows without a unit (rejected: retry, visibility and coverage would each need their own bookkeeping across thousands of rows); a separate unit (**chosen**: `SceneAnalysis`, §G).

`SceneAnalysis` is the minimum that supports re-analysis against new geometry (new unit per revision), historical reproducibility (unit records revision, algorithm version and parameter hash), retry (attempts and lease on the unit), and future algorithms (new algorithm version → new unit). No `AnalyticsRun` beyond this and no `AnalysisRevision` concept is introduced.

---

## R. Algorithm versioning

**Decision.** `AlgorithmVersion` is a domain string, `scene-analytics-v<major>`, declared as a constant in the engine, plus `ParametersSha256` over the canonical JSON of the parameter set actually used (ε, k, t_min, g_max, stationary thresholds, loitering default, reference point). Both are stored on the unit. The Git SHA is recorded on the unit as `SourceCommit` for forensics only and never participates in identity or staleness.

Rules: any change to a frozen rule in §K–§M or to a default parameter increments the major version; the reconciler then treats existing `Completed` units as `Stale` for readiness purposes (they were computed by an older version) but does **not** auto-queue re-analysis; the scene page and Processing page show "Analysed with scene-analytics-v1; current engine v2" and offer explicit re-analysis. Facts from older versions are retained and remain queryable by version.

---

## S. Search contract

Additions to `TrackSearchQuery`, the endpoint whitelist, `searchState.ts` and the cursor fingerprint (all or nothing per PR):

| Key | Type | Semantics |
|---|---|---|
| `sceneRevisionId` | GUID | Revision to evaluate against; default = the camera's active revision. Requires `cameraId` (or a `videoAssetId` from which the camera follows). |
| `zoneId` | GUID | Restricts to Tracks with a zone summary for this zone in the evaluated revision. |
| `zoneRelation` | `entered` \| `exited` \| `dwelled` | With `zoneId`: `entered` = at least one visit not `BeganInside`; `exited` = at least one visit not `EndedInside`; `dwelled` = `total_dwell_ms > 0`. Default `dwelled`. |
| `minDwellMs` | integer ≥ 0 | `total_dwell_ms ≥ value` for the zone. |
| `lineId` | GUID | At least one crossing of the line. |
| `crossingDirection` | `aToB` \| `bToA` | With `lineId`. |
| `motionDirection` | eight-way heading | Motion summary heading. |
| `minStationaryMs` | integer ≥ 0 | `longest_stationary_ms ≥ value`. |
| `loitering` | `true` | Any zone summary with `loitering = true` (with `zoneId`: that zone). |
| `analyticsCoverage` | `partial` (default) \| `complete` | §H. |

Rules: a query that uses any analytic key is an **analytic query**; the repository joins the fact tables through `scene_analyses` filtered by `revision_id`, `algorithm_version`, `status = 'Completed'` and `visibility_sequence ≤ snapshotVisibilitySequence`.

**Analytic predicates require a single-camera scope (Decision).** A zone, a line and a revision only mean anything for one camera, and one coverage block names one revision, so a query using any analytic key must resolve to exactly one camera through `cameraId`, `videoAssetId` or `processingRunId`; anything else is `400 track_search_invalid`. Multi-camera analytic search would need per-camera coverage and pinning and is out of this increment.

**Revision-pinned cursors (Decision).** The cursor represents a stable snapshot, so the scene revision and algorithm version are resolved once and pinned:
- **First page:** resolve the effective `sceneRevisionId` (the explicit query value, else the camera's active revision at that instant) and the current `algorithmVersion`; allocate the visibility snapshot as today; compute the filter fingerprint over the client-supplied keys **plus the resolved revision id and algorithm version**; issue a cursor whose payload (a new cursor version) carries snapshot time, snapshot sequence, keyset position, fingerprint, `sceneRevisionId` and `algorithmVersion`. The response's `analyticsCoverage` names the pinned pair.
- **Continuation:** pages are evaluated against the pinned revision, the pinned algorithm version and the pinned snapshot sequence, whatever the camera's active revision is now. Activating a new revision between pages does **not** invalidate the cursor; the pinned revision's facts are persisted (§P) and remain queryable, and even if the pinned unit has since been marked `Superseded` its facts still exist and its visibility sequence is still ≤ the snapshot, so continuation stays consistent.
- **Resolving to no revision is pinned too:** for a never-configured or disabled camera the first page pins the absence, and continuation keeps returning the same empty analytic result with the same coverage, so a mid-pagination activation cannot make later pages start matching.
- **A new search** (no cursor) after activation resolves the new active revision.
- **A cursor is genuinely invalid** only when: it fails to decode; its fingerprint differs from the fingerprint recomputed from the supplied keys plus the *pinned* pair (the client changed filters); it is older than the one-hour limit or ahead of the clock; or it names a revision id that does not belong to the query's camera. Revisions are immutable and never deleted, so a pinned revision cannot disappear.

Ordering, keyset pagination, the one-hour cursor age and the default latest-visible-run scope are unchanged. `processingRunId` continues to select a historical run, and an analytic query against it reports that run's coverage.

Response: `TrackSearchResponse` gains optional `analyticsCoverage` (present only for analytic queries) and each item gains optional `analytics` (matched zone/line ids, dwell, crossing times, loitering flag) so the list can show why a row matched. `TrackDetailResponse` gains `analytics` with the full facts for the Track under the active revision plus a list of other analysed revisions.

---

## T. Aggregate analytics

Read-only aggregates over a camera, a time window in UTC, an optional class and the resolved revision, with time bucket `bucketSeconds` (60–86400). Every metric is named by what it counts:

| Metric | Counts | Source |
|---|---|---|
| `zoneEntryCount` | visits with `began_inside = false` whose entry time is in the bucket | `track_zone_visits` |
| `zoneExitCount` | visits with `ended_inside = false` whose exit time is in the bucket | `track_zone_visits` |
| `zoneUniqueTrackCount` | distinct Tracks with a visit overlapping the bucket | `track_zone_visits` |
| `lineCrossingCount[direction]` | crossings in the bucket per direction | `track_line_crossings` |
| `occupancy` | number of visits covering each bucket boundary instant (sample-based occupancy); `peakOccupancy` = max over boundaries with its instant | `track_zone_visits` |
| `repeatedVisitTrackCount` | Tracks with `visit_count ≥ 2` in the zone | `track_zone_summaries` |
| `classCount` | Tracks per class active in the bucket | `tracks` joined to outcomes |

Responses include `analyticsCoverage` and state the bucket boundaries. Occupancy is sample-based at bucket boundaries, not integrated seconds; this is stated in the response schema.

---

## U. Heatmaps

**Decision: computed on demand from trajectory artefacts, not persisted, cached in memory per request key for a short TTL only after measurement shows need.** Inputs: camera, window, optional class, resolved run set (latest visible runs of the camera's videos in the window, or an explicit run), grid `64×36` cells by default (configurable 16–128 wide), normalised coordinates; each trajectory sample adds 1 to its cell (optionally weighted by time to the next sample, capped at `g_max`). Output is a small integer matrix plus the run set and sample count; the UI renders it over the reference frame. Cost is linear in samples read; trajectories are read through the existing `IAcceptedEvidenceReader`. No raster artefacts are stored.

---

## V. Scene editor UI

Route `cameras/:cameraId/scene` from the Cameras page.

**Reference frame.** **Decision:** the editor lists the camera's imported videos (existing `GET /api/videos?cameraId`) and lets the operator pick a video and scrub to a frame; the chosen frame is rendered from the video content endpoint at that offset and recorded on the revision as (`ReferenceFrameVideoAssetId`, `ReferenceFrameOffsetMs`). No server-side frame extraction or new artefact is required in v1; the browser draws the paused `<video>` frame. A later option to upload an explicit reference image is reserved (`ReferenceFrameArtifactId`) but not built. If the camera has no videos, the editor shows an empty frame with a message and still allows geometry (coordinates are normalised, so this is meaningful but discouraged).

**Interactions.** Draw polygon (click to add vertices, close by clicking the first vertex or Enter), draw line (two clicks), select/move vertices, delete object, name, enabled toggle, zone kind, loitering threshold override, line direction arrow with labels; validation messages inline using the codes in §I; unsaved-changes guard on navigation; Cancel/Reset to the active revision; Save creates and activates a revision with an optional note; revision history list with "view" (read-only overlay of an older revision) and "Analyse existing runs with active revision". Keyboard: arrow keys nudge the selected vertex by 0.001, Delete removes, Tab cycles objects, Escape cancels drawing; every control reachable and labelled; canvas has an accessible list twin (objects and vertex coordinates) so the configuration is inspectable without a pointer.

---

## W. Evidence UI

In `TrackInspector` and `VideoReviewPage`, when a Track has facts under the revision the search used (or the active revision on a direct link):
- zone outlines and trip lines of that revision drawn through `overlay.ts` projection, matched objects highlighted;
- crossing markers at the crossing point with a timeline tick and the crossing time; clicking seeks the player to it;
- dwell intervals and stationary intervals as timeline bands; entry/exit ticks;
- an "Analytics" panel: rule summary ("Dwelled 143 s in Zone 3 across 2 visits; Loitering (threshold 120 s)"), heading, stationary summary, and the footer "Scene revision 4 · scene-analytics-v1 · reference point: box centre";
- a notice when the Track is `Unavailable` with its reason, or when the run is not analysed for the active revision.

---

## X. API design

Follows the existing minimal-API groups and problem-details conventions; routes are indicative and must match `Mavi.Contracts` records when implemented.

| Capability | Route (indicative) | Notes |
|---|---|---|
| Read scene (active revision, history summary) | `GET /api/cameras/{id}/scene` | 404 `camera_not_found`; `configured: false` when none |
| Save and activate a revision | `PUT /api/cameras/{id}/scene` | Body: zones, lines, note, reference frame; 201 with revision; 400 codes §I; 409 `scene_revision_conflict` when `expectedRevisionNumber` ≠ current |
| Read a specific revision | `GET /api/cameras/{id}/scene/revisions/{revisionNumber}` | |
| Analytics status for a run | `GET /api/processing/runs/{runId}/analytics` | Readiness, unit rows (state, attempts, counts, failure) |
| Retry a failed unit | `POST /api/processing/runs/{runId}/analytics/retry` | `Failed` → `Queued`; 409 otherwise |
| Re-analyse | `POST /api/cameras/{id}/scene/analyses` | Body: scope `latestRuns` (default) or `allRuns`; creates `Queued` units; returns counts |
| Analytic search | `GET /api/tracks` | §S |
| Track detail analytics | `GET /api/tracks/{id}` | `analytics` block |
| Aggregates | `GET /api/cameras/{id}/analytics/aggregates` | Query: window, bucket, class, zone/line ids, revision |
| Heatmap | `GET /api/cameras/{id}/analytics/heatmap` | Query: window, class, grid width, revision |
| Processing status | `GET /api/videos/{id}/processing` | `LatestRun` gains `analyticsReadiness` (string) |

No worker-facing endpoint changes. No new endpoint fragmentation beyond these groups.

---

## Y. Persistence and migrations

One migration per slice that needs one (§AJ), hand-written in the existing style, snake_case, fluent configuration per aggregate.

Keys and constraints: as in §O plus check constraints for coordinate ranges (`0 ≤ x ≤ 1`), `dwell_ms ≥ 0`, `exit_offset_ms ≥ entry_offset_ms`, `visit_index ≥ 0`, `attempt_count ≥ 0`, status enums as strings ≤ 32. Zone vertices live in jsonb, so their range check calls a small `IMMUTABLE` function (`scene_vertices_in_range`, added in slice 1) that refuses any element which is not a two-number array inside `[0, 1]`; a plain expression cannot walk a jsonb array.

Foreign keys and delete behaviour: a configuration's `active_revision_id` is pinned to its own configuration by a **composite foreign key declared `DEFERRABLE INITIALLY DEFERRED`** (slice 1), because that reference and the revision's own foreign key form a cycle that a statement-by-statement check cannot order around; deferring it to commit lets one transaction insert a configuration and the revision it activates in either order while still refusing an active revision that is missing or belongs to another camera. Configuration → camera `Restrict`; revisions → configuration `Restrict`; zones/lines → revision `Cascade` (a revision is only ever deleted with its geometry, and nothing deletes revisions in this increment); `scene_analyses` → `processing_runs` `Restrict` and → revision `Restrict`; fact tables → `scene_analyses` `Cascade` (facts have no meaning without their unit) and → `tracks` `Restrict` (never let an analytics row hold a Track hostage the other way; Track deletion is already cascade-from-run and would need to remove facts first, which the existing run-deletion path does not do today because runs are not deleted; documented invariant). Uniqueness: (`processing_run_id`, `revision_id`, `algorithm_version`) on units; (`revision_id`, `zone_id`), (`revision_id`, `line_id`); (`analysis_id`, `track_id`) on outcomes and summaries; (`analysis_id`, `track_id`, `zone_id`, `visit_index`) on visits; (`analysis_id`, `track_id`, `line_id`, `crossing_index`) on crossings.

Indexes (initial, driven by §S/§T patterns): visits (`zone_id`, `entry_timestamp_utc`), (`analysis_id`, `track_id`); summaries (`zone_id`, `total_dwell_ms`), (`zone_id`, `loitering`) partial where `loitering`; crossings (`line_id`, `timestamp_utc`, `direction`); motion (`longest_stationary_ms`); units (`processing_run_id`), (`status`, `queued_at_utc`) partial where `status IN ('Queued','Running')`, (`visibility_sequence`) unique where not null. Anything else waits for measurement (§Z).

---

## Z. Performance model

Per unit: read `T` trajectories (I/O bound, sequential), then per Track `O(n · (Z + L))` for `n` samples, `Z` enabled zones, `L` lines, plus `O(n)` for smoothing and stationary windows. Point-in-polygon is `O(v)` per test with `v ≤ 64` vertices; a bounding-box pre-check per zone rejects most samples cheaply. Expected: a 10-minute 25 fps video with 200 Tracks and 15 000 samples against 10 zones and 5 lines is well under a second of CPU; persistence volume is dominated by visits and crossings (bounded by samples) and summaries (Tracks × zones).

Likely bottlenecks in order: aggregate queries over long windows without the initial indexes; heatmaps over many runs (I/O); fact-table growth when many zones are enabled; the reconciler scanning runs (bounded by the partial index on unit status and a `completed_at_utc` watermark).

Required measurements before any further index or cache: (1) unit duration and rows written for the development corpus and for a synthetic 1 000-Track run; (2) latency of each §S predicate and each §T aggregate at 10⁵ facts with `EXPLAIN (ANALYZE, BUFFERS)`; (3) heatmap time for 50 runs. Results go in the slice-7 report; indexes beyond §Y are added only against a measured plan.

---

## AA. Implementation boundary

| Option | For | Against |
|---|---|---|
| Python vision worker | Geometry libraries (Shapely) readily available; near the trajectory producer. | Couples analytics to the qualified runtime pack and its lock (any library is a runtime dependency to freeze and requalify on CPU and CUDA); the worker sees one job's trajectories only, but re-analysis needs sealed evidence for many runs; scene configuration lives in the platform; the completion contract would have to grow or a new worker endpoint be created; re-analysis without video processing does not fit the lease model. |
| Separate Python analytics worker | Isolation from the detector; could reuse Python geometry. | A second control plane (lease, heartbeat, completion, sealing) for a deterministic computation with no AI; a second runtime pack to qualify; another process to operate offline. |
| **.NET application-side post-processing (chosen)** | Reads sealed evidence through the existing `IAcceptedEvidenceReader`; owns scene configuration and search projection already; deterministic `double` arithmetic in-house (~500 lines: point-in-polygon, segment intersection, interpolation, windows); no new dependency, no runtime pack impact, no qualification re-opening; reuses `TimeProvider`, options validation, the visibility barrier and the test harnesses. | First hosted service in the API process (operational concern: it shares the host; mitigated by `MaxConcurrentUnits = 1` and bounded units); future AI analytics (attributes, embeddings) will not live here, which is correct: they belong to the worker or a separate model worker per the master roadmap. |

**Decision: .NET Application layer**, module `Mavi.Application/Modules/SceneAnalytics` with the geometry engine as a pure, dependency-free library class set (`TrajectoryDecoder`, `TrajectoryPath`, `ZoneVisitDetector`, `LineCrossingDetector`, `StationaryDetector`, `LoiteringRule`, `SceneAnalysisEngine`) unit-tested in `Mavi.Application.Tests`. **Refined in slice 1:** the geometry *primitives and predicates* (`NormalizedPoint`, containment, simplicity, degeneracy, segment intersection) live in `Mavi.Domain/Scene/Geometry` rather than in the engine, because scene validation needs them and Domain may not depend on Application. Domain carries no framework reference, so this keeps the dependency direction right and leaves the primitives as pure as they were; the detectors and the engine stay in Application. repositories and the hosted service in `Mavi.Infrastructure`; endpoints in `Mavi.Api`. The trajectory msgpack parser is a small in-house decoder mirroring `trajectory.py`/`trajectory.ts` validation (no new package; `MessagePack` NuGet was considered and rejected because the format is three fields).

---

## AB. Contract design

No cross-process contract changes. The detector/tracker completion contract (`VisionJobCompleteContracts`) is untouched. Responsibilities: **raw Track evidence** (worker → sealed artefacts and `tracks`/`observations`), **derived analytics** (SceneAnalytics module → typed fact tables bound to a unit), **search projection** (`TrackSearchRepository` joins facts through units gated by the snapshot). New `Mavi.Contracts/Api/Scene*` and `Analytics*` records are added for the API; the web client mirrors them by hand as today.

---

## AC. Test strategy

| Layer | Location | Content |
|---|---|---|
| Pure geometry (Application.Tests) | `SceneAnalytics/GeometryTests` | inside/outside/on-edge/on-vertex; concave and reflex polygons; invalid/self-intersecting/degenerate rejection; proper intersection; touching endpoint with side change; collinear overlap (no crossing); direction sign for both line orientations; jitter across the line within ε (no crossing); tangent approach without crossing; genuine repeated crossings > `t_min`; repeated within `t_min` collapsed. |
| Temporal (Application.Tests) | `SceneAnalytics/VisitTests`, `StationaryTests`, `LoiteringTests` | dwell accumulation; visit open/close with `k` hysteresis; starts inside; ends inside; brief excursion keeps visit open; re-entry increments visit index; gap closes visit with `ClosedByGap`; stationary thresholds per class at boundaries; smoothing removes single-sample jumps; loitering threshold default and override; golden fixtures (`tests/fixtures/scene-analytics/*.json`) with expected facts, asserted byte-for-byte after canonical JSON serialisation. |
| Domain (Domain.Tests) | `SceneConfigurationTests`, `SceneAnalysisTests` | revision numbering, stable ids, activation, validation codes; unit state machine, attempt bounds, `Superseded` rules, visibility sequence invariant. |
| DB integration (IntegrationTests) | `SceneConfigurationPersistenceTests`, `SceneAnalyticsLifecycleTests`, `SceneAnalyticsOwnershipTests` | uniqueness constraints; revision history retention; reconciler queues only eligible runs and **never** queues a camera whose active revision is empty (`Disabled`) or absent (`NotConfigured`); claim with `SKIP LOCKED` under two concurrent hosts; lease expiry reclaim increments the attempt and replaces the token; attempts exhausted after the grace → `Failed` with the token cleared, and the still-running last attempt is then rejected as stale while a last attempt that finishes inside the grace completes normally; retry; re-analysis creates a new unit and supersedes; facts deleted only for the same unit id after ownership re-validation; visibility sequence allocated under the barrier. **Stale-attempt scenario:** attempt A claims → A's lease expires (clock advanced via `TimeProvider`) → attempt B claims (attempt 2, new token) → B completes with facts → A attempts completion with its attempt number and token → A is rejected with `analytics_attempt_stale` → B's facts, `Completed` state, visibility sequence and `Superseded` marks are byte-for-byte unchanged. **Stale failure scenario:** same set-up, A reports failure late → rejected; B's state unchanged. Also: an attempt whose lease expired but was **not** reclaimed still completes (ownership is lost only on reclaim). |
| Search integration (IntegrationTests) | `TrackSearchAnalyticsApiTests` | each §S predicate; coverage metadata for pending, failed, stale, not-configured and disabled runs, each in its own bucket, with `complete` true only when all five buckets are zero and a disabled camera's runs counted under `disabledRuns` rather than `notConfiguredRuns`; `analyticsCoverage=complete` 409 for each non-zero bucket including a disabled camera; **revision-pinned cursor:** page 1 resolves revision 4, revision 5 is activated, page 2 still evaluates revision 4 and stays consistent with page 1, and a new search resolves revision 5; cursor rejected only for changed filters, age, skew, decode failure or a foreign revision id; snapshot excludes a unit completed after the first page; explicit historical `sceneRevisionId` including one of a now-disabled camera; whitelist rejection of malformed keys. |
| API contract (IntegrationTests) | `SceneApiContractTests` | request/response shapes, problem codes, 404/409 semantics, in the `Task15ApiContractTests` style. |
| UI (Vitest) | `features/scene-editor/*.test.tsx`, `visual-search/*analytics*.test.tsx`, `video-review/*analytics*.test.tsx` | draw/edit/delete/validation/unsaved guard; explicit confirmation before saving an empty (disabling) revision; unattributed-action labelling; `unprojectPoint` round-trip with letterboxing; filter canonicalisation for new keys; coverage notice rendering; overlay alignment against fixture geometry; explanation panel; keyboard paths. |
| Real-stack corpus (Development laptop) | `tools/vision/dev/` fixture harness + three short synthetic videos generated with FFmpeg (`testsrc2` + moving box) with known paths: straight crossing of a line, dwell inside a zone then exit, stationary then depart | Expected facts are computed from the scripted motion, not by eye; run through the real worker path (fixture detector) and through the real analytics host; assert facts and overlays. |

Determinism: the same fixture inputs must yield identical facts on Windows and Linux CI (`double` with rounding to six decimals before comparison).

---

## AD. Migration and backward compatibility

After deployment every existing completed Track lacks analytics.

**Decision: future runs automatically; existing runs on demand.** The reconciler's automatic scope is runs completed after the camera's active revision was activated (which, for a camera configured after deployment, is every run completed from then on). Existing runs show readiness `NotConfigured` (camera never configured), `Disabled` (empty active revision) or, once a revision with geometry is active, `Stale`/`Pending` only after an explicit "Analyse existing runs" request creates units. No full historical backfill is forced; the operator chooses per camera. Ordinary search over existing Tracks is unaffected.

---

## AE. Failure semantics

| Failure | Code | Scope | Retryable | Effect |
|---|---|---|---|---|
| Scene geometry invalid at save | `scene_zone_*`, `scene_line_*` (§I) | request | n/a (400) | Nothing saved |
| Revision activated concurrently | `scene_revision_conflict` | request | client retries with new expected number | Nothing saved |
| Trajectory missing / integrity / invalid / too short | `trajectory_missing` etc. | per Track | no (permanent for this evidence) | Outcome `Unavailable`; unit completes |
| Trajectory read I/O error | `trajectory_read_failed` | per unit attempt | yes | Unit `Queued` again if attempts remain |
| Engine exception (bug) | `analytics_engine_failed` | per unit attempt | yes, up to `MaximumAttempts` | Then `Failed`; details logged with unit id |
| Configuration revision deleted/missing (should not happen; `Restrict`) | `analytics_revision_missing` | per unit | no | `Failed` |
| Database failure during fact commit | `analytics_persistence_failed` | per unit attempt | yes | Transaction rolled back; retry rewrites facts idempotently |
| Host restart mid-unit | (lease expiry) | per unit | yes | Reclaimed by the next claim after `LeaseSeconds + ReclaimGraceSeconds`; new attempt, new token |
| Stale attempt completing or failing after reclaim | `analytics_attempt_stale` | per stale attempt | no (the stale host discards its results) | Nothing written; the owning attempt's state and facts untouched |
| Engine exceeds `MaxUnitDurationSeconds` | `analytics_unit_timeout` | per unit attempt | yes | Cancelled by the executor before the lease can expire; counted as an attempt |
| Attempts exhausted | `analytics_attempts_exhausted` | per unit | explicit retry only | `Failed` and `ClaimTokenHash` cleared by the reconciler after the grace, so any overrunning attempt becomes stale; visible in readiness |
| Run not visible (no `VisibilitySequence`) | not eligible | per run | n/a | Not queued |

A malformed Track never fails a unit. A unit fails only when the whole attempt cannot proceed.

---

## AF. Observability

On the unit and in `GET …/analytics`: state, attempt count and current lease expiry (never the claim token), queued/started/completed times (elapsed time is derived from them rather than carried as a `DurationMs`, which AGENTS.md reserves for media-relative values), algorithm version and parameters hash, revision number, analysed and unavailable Track counts, failure code; `analytics_attempt_stale` rejections are logged with unit id and attempt number. In the Processing page's run detail: one line "Scene analytics: Ready (revision 4, 212 Tracks, 3 unavailable)" or "Pending / Failed (code) [Retry]" with a link to the scene page; the queue view adds a readiness badge. Structured logs from the hosted service at unit start/completion/failure with unit id, run id, revision, duration. No engineering diagnostics in the operator UI beyond the disclosure in §N.

---

## AG. Security and authorization

No new authentication is introduced, and **no request may supply an identity**: scene saves, re-analysis requests and retries record the server-controlled constant `CreatedBy = "development-unattributed"`; any caller-supplied name or identity field is rejected as an unknown member (the contracts use `JsonUnmappedMemberHandling.Disallow`). Attribution is therefore explicitly **not trustworthy** in this increment, and the UI labels these mutations as unattributed Development actions rather than showing a person. When stage 10 (ADR-010) brings Windows-integrated identity, the same column carries the verified server-side principal and an `IdentitySource` column is added then; no fake audit semantics are created now. Mutations that become attributable at that point: saving a scene revision, requesting re-analysis, retrying a failed unit. Nothing here blocks on the identity architecture.

---

## AH. Offline and dependency discipline

**Decision: no new dependency of any kind.** Geometry is in-house .NET; the msgpack trajectory decoder is in-house; the editor uses the existing React/Canvas platform APIs; no new npm, NuGet, Python, native, model or database-extension dependency. `config/dependencies/offline-dependency-policy-v1.json` is unchanged and `verify_repo.py` confirms it on every slice. A geometry library was considered (NetTopologySuite: capable, but a large dependency for point-in-polygon and segment intersection, with its own precision model that would make the frozen rules harder to state) and rejected.

---

## AI. Qualification impact

**Unchanged:** RTMDet Model Pack, ByteTrack and detector qualification (Task 10), CPU Runtime Pack and lock (Task 12), Windows CUDA Development runtime and its C4 evidence, the completion contract and `VisionResultValidator`, the evidence root layout and sealing (ADR-006). The processing boundary does not move: the worker's inputs and outputs are identical.

**Changed:** the application artefact (API, UI, schema) — relevant to Task 18 only in that a re-frozen Production candidate has a new application identity; no vision evidence is invalidated.

**New evidence required:** golden-fixture determinism across OSes in CI; the real-stack corpus results on the development laptop (facts and overlays for the three scripted videos through the real worker path); the §Z measurements; the ADR of slice 0. Recorded in a dated review document under `docs/reviews/` at slice 7.

---

## AJ. Implementation slices

**Eight slices, numbered 0–7**; each slice is one PR against `main`, merged before the next starts. "Must not include" guards scope. The decomposition was rebaselined from eleven slices to eight on 2026-09-20 to cut PR and process overhead: geometry and the scene backend merged because the scene domain model and the geometry semantics constrain one another and are only reviewable together; lifecycle and derived-fact persistence merged because a lifecycle with no persisted output is not independently useful and the fact writes depend directly on the lifecycle's transaction and fencing model; hardening and acceptance merged because they close the same gate. No acceptance criterion was dropped in the merge.

| # | Slice | Scope | Likely files/modules | Prerequisites | Tests | Acceptance | Must not include |
|---|---|---|---|---|---|---|---|
| 0 (done) | ADR and contracts | ADR recording the §G, §I, §J, §K–§R decisions; `Mavi.Contracts/Api/Scene*` and analytics status/coverage records; strict-serialisation and information-exposure tests | `docs/decisions/ADR-011-*.md` (ADR-010 is reserved by the deferred review/cases plan for operator identity), `src/platform/Mavi.Contracts/Api/{Scene,Analytics}`, `tests/Mavi.Application.Tests/Contracts` | this plan reviewed | contract serialisation and strictness; coverage-completeness rule; no claim secret exposed | ADR accepted; `verify_repo` green; contracts compile with no project reference added | persistence, migrations, engine, hosted service, search, UI |
| 1 (done) | Geometry engine and scene configuration backend | Pure deterministic engine (geometry primitives, visit/crossing/stationary/loitering detectors, `AnalysisEngine`, trajectory msgpack decoder, algorithm version and parameters, golden fixtures) **and** the scene domain (aggregates, revision rules, validation codes, repository, migration, `GET/PUT scene` and revision endpoints) | `Mavi.Application/Modules/SceneAnalytics/Engine/*`, `Mavi.Domain/Scene/*`, `Mavi.Infrastructure/Persistence/{Configurations,Repositories,Migrations}`, `Mavi.Api/Endpoints/SceneEndpoints.cs`, `tests/fixtures/scene-analytics/*` | 0 | §AC pure geometry and temporal layers with fixtures byte-identical on Windows and Linux; Domain revision invariants; DB integration; API contract | every frozen rule in §K–§M pinned by a test; save/activate/read/history with all §I codes, including the empty-revision (disable) path | scene editor UI, analytics lifecycle execution, derived-fact persistence |
| 2 | Scene editor UI | Reference-frame workflow, polygon and trip-line editing, validation, enable/disable semantics, revision save and activate, empty-scene confirmation, revision history, accessibility, `unprojectPoint` | `src/web/mavi-web/src/features/scene-editor/*`, `api/scene.ts`, `features/video-review/overlay.ts` (additive) | 1 | Vitest editor suite; letterbox round-trip; empty-revision confirmation; a11y | an operator can define, disable and re-enable a camera's scene and read its history | analytics execution, search, overlays |
| 3 | Analytics lifecycle and derived facts | `SceneAnalysis` aggregate with fenced attempt ownership (`RequireOwnership`), outcome rows, options, reconciler and executor hosted service, claim/lease/reclaim/retry, visibility-sequence integration, idempotent fact writes for zone visits, zone summaries, line crossings and motion summaries, Processing readiness, status and retry/re-analysis endpoints | `Mavi.Domain/SceneAnalytics/*`, `Mavi.Infrastructure/SceneAnalytics/SceneAnalyticsHostedService.cs`, repositories, migration, `ProcessingEndpoints`, `VideoEndpoints` (readiness field) | 1 | Domain state machine incl. ownership fencing; DB lifecycle suite incl. two-host claim, lease expiry and reclaim, the seven-step stale-completion scenario and stale failure rejection, retry, supersede; fact uniqueness and idempotent rewrite | units run end to end on the fixture harness and persist facts and outcomes; a stale attempt cannot alter a reclaimed unit; disabled and unconfigured cameras are never queued | search, UI, aggregates |
| 4 | Search integration and analytics readiness | `TrackSearchQuery` and whitelist extension, revision- and algorithm-pinned fingerprint and cursor, repository joins gated by the snapshot, `analyticsCoverage` block and its completeness rule, item and detail `analytics`, `searchState.ts` keys, filter UI group and not-ready messaging | `TrackSearchQuery/Service/Repository`, `TrackCursorCodec`, `TrackEndpoints`, contracts, `searchState.ts`, `SearchFilterRail.tsx`, `VisualSearchPage.tsx` | 3 | search integration suite incl. revision-pinned continuation across activation; `searchState` tests; coverage notice UI tests | every §S predicate works with pagination; coverage is `complete` only when all five buckets are zero; incomplete analytics never render as zero matches | evidence overlays, aggregates |
| 5 | Evidence overlays and explanation | Zone and line overlays, crossing markers and times, dwell and stationary intervals, matched-rule summary, scene revision and algorithm version disclosure, unavailable and not-analysed notices | `TrackInspector.tsx`, `VideoReviewPage.tsx`, `TrackEvidencePlayer.tsx`, `TrackDetailsPanels.tsx` | 4 | overlay alignment against fixture geometry; explanation content; seek-to-crossing | an operator can visually verify every analytic match and see which revision produced it | aggregates |
| 6 | Aggregates and heatmap | Entry, exit, crossing and directional counts, unique-Track counts, occupancy and peak occupancy, repeated visits, heatmap; aggregate and heatmap endpoints; camera analytics view | `Mavi.Application/Modules/SceneAnalytics/Aggregates/*`, `Mavi.Api/Endpoints/AnalyticsEndpoints.cs`, `features/scene-analytics/*` | 4 | aggregate integration tests with fixture facts; heatmap unit tests; coverage on every aggregate response | counts, occupancy, peak and heatmap render with coverage and unambiguous counting semantics | persisted raster heatmaps unless §Z measurement demands them |
| 7 | Hardening, performance, acceptance, qualification and docs closure | §Z measurements on the corpus and synthetic volumes; index review against real `EXPLAIN` plans; failure injection; full real-stack deterministic corpus on the laptop; independent cold review and P1/P2 remediation; analytics qualification evidence; runbook and roadmap updates; final exact-head validation | `docs/reviews/<date>-scene-analytics-acceptance.md`, `docs/runbooks/local-development.md`, roadmap status, indexes as measured | 2, 5, 6 | all suites; `verify_repo`; performance report | the §Acceptance criteria met and recorded; no P1/P2; measurements committed | any new capability |

Trajectory v2 (bottom-centre reference point) is deliberately **not** a slice here; it is the first follow-up after acceptance and is planned as a worker-side change with its own qualification.

---

## AK. Integration strategy

**Decision: eight bounded sequential PRs (slices 0–7), each from a short-lived branch off `main`, merged in order 0→7, no stacking.** Branch names `feature/scene-analytics-s<N>-<topic>`. Each PR: exact-head CI green on all triggered workflows; **independent cold review at slices 0 (architecture and contracts), 1 (geometry, domain and persistence), 3 (lifecycle, fencing and fact persistence), 4 (search and snapshot semantics) and 7 (final hardening and acceptance)**, and a lighter review at slices 2, 5 and 6; no PR opens against another PR's branch; if a later slice needs a change to an earlier one, it is a small commit in the later slice's PR, not a reopened earlier PR. Stop gates: a slice does not start until the previous merged and its post-merge `main` CI is green.

---

## AL. Stop rules

A slice is done when all hold, and then it stops:
1. its acceptance row in §AJ passes;
2. no open P1 or P2 finding;
3. exact-head CI green on every triggered workflow;
4. docs updated where the slice changes operator-visible behaviour;
5. `verify_repo` green and the offline dependency contract truthful (unchanged, for this feature);
6. no undeclared dependency;
7. no unresolved review thread.

No speculative bug hunting after a clean gate; new findings become P3 notes or a later slice.

---

## Acceptance for the increment

Offline, on the development laptop, an operator can: define zones and lines for a camera from an imported video's frame and save a revision; process a recorded video; see the run become `Ready`; search persons or vehicles by zone entry/exit, minimum dwell, line crossing with direction, stationary duration and loitering, with coverage stated; open a matched Track and see the geometry, crossing point or interval and the revision and algorithm version responsible; edit the scene, see existing results marked `Stale` with history intact, request re-analysis and see both revisions' facts distinguished; retry a failed unit; disable analytics for a camera with an empty revision and see its runs reported as not evaluated rather than as zero matches; and reproduce identical facts from the same Track, revision and algorithm version. Runs not yet analysed are visibly not analysed rather than empty, and a stale attempt can never alter a reclaimed unit.

## Next capability after this increment

Trajectory v2 (worker-side, qualified) as the direct follow-up, then **Visual Attributes** per `capability-implementation-roadmap.md` stage 2.
