# Spatial & Temporal Track Analytics — Implementation Plan

**Date:** 2026-09-20  
**Status:** Next feature per `docs/superpowers/plans/capability-roadmap.md` (stage 1). Planning only; no implementation has started.  
**Base:** `main@ed1acf4` (PR #50 and PR #49 merged).  
**Product intent:** derive materially richer, explainable intelligence from Tracks that RTMDet + ByteTrack already produce, before adding new recognition models or heavier investigation workflow.

## 1. Why this is next

MAVI already provides recorded-video import, person/vehicle detection, single-camera tracking, sealed observations and trajectory artefacts, structured Track search, evidence-linked playback and an operator Search/Review workspace.

The limitation is semantic depth. A Track tells the operator little beyond **what broad class was seen, when, where in the frame, for how long, and with what confidence**. Converting trajectory and time data into searchable scene facts is the largest capability gain available without another model, and it is deterministic, testable and explainable.

## 2. Principles

1. **Derived facts, not inference.** Every analytic result traces to persisted Track/trajectory data plus an explicit scene-configuration revision.
2. **Camera-local geometry.** Zones and lines belong to one camera; nothing is shared implicitly across cameras.
3. **Revisioned configuration.** Every result records the configuration revision and the algorithm version that produced it. A later geometry edit never reinterprets historical results silently.
4. **No false physical precision.** Image-space or normalised motion diagnostics are fine; km/h or m/s appear only for a calibrated camera with a stated error tolerance.
5. **Determinism.** The same Track, configuration revision and algorithm version always yield the same facts.
6. **Search-first, evidence-backed.** A fact is worth persisting only if an operator can filter on it and see why it matched.
7. **Offline-first, no new dependency.** Geometry is implemented in-house in the .NET Application layer; no new model, Python package or native runtime. Any library considered instead goes through the offline dependency policy in the same PR.
8. **Recorded video only.** Live ingestion is a later platform phase.

## 3. Scene configuration

Per camera, an operator defines geometry in a **scene configuration** with explicit revisions.

| Object | Fields |
|---|---|
| `SceneConfiguration` | `cameraId` (explicit binding, immutable), `revision` (monotonic integer per camera), `createdAtUtc`, `createdBy` (when identity exists; otherwise `development-operator`), `referenceFrame` (optional artefact id of the frame used for drawing), `note` |
| `SceneZone` | stable `zoneId` (GUID, survives revisions), `name`, `enabled`, polygon vertices in normalised image coordinates, optional `kind` tag (e.g. `restricted`, `entrance`), optional loitering threshold override |
| `TripLine` | stable `lineId`, `name`, `enabled`, two normalised endpoints, `directed` flag, direction labels (`aToB` / `bToA` display names such as "inbound"/"outbound") |
| `CameraCalibration` (later slice) | optional plane transform and its validation record; absent by default |

Rules:

- A stable id keeps its meaning across revisions; editing geometry creates a new revision that references the same ids. Deleting a zone or line removes it from later revisions only.
- A revision is immutable once saved. Search and evidence always name the revision they used.
- Geometry validation on save: at least three non-collinear vertices, no self-intersection, vertices within `[0, 1]`, distinct line endpoints, minimum edge length above a jitter floor. Invalid geometry is refused with a stable code.
- The camera binding is part of the configuration's identity; a configuration cannot be re-pointed at another camera.

## 4. Derived analytics

All facts are derived from the trajectory samples persisted for a Track (frame time, normalised bounding box) and the scene configuration revision in force for the Track's camera at analysis time.

The **reference point** of a Track sample is the bottom-centre of the bounding box (the ground contact for a person or vehicle), stated explicitly because zone membership depends on it.

| Family | Facts | Notes |
|---|---|---|
| Zone visits | per Track and zone: entry time, exit time (or "ended inside"), dwell duration, visit index; per Track: total dwell per zone, number of visits, "began inside" flag | A visit opens on the first sample inside after a sample outside (or at Track start), closes on the first sample outside after the debounce rule |
| Repeated zone visits | visit count ≥ 2 for one Track in one zone | Says nothing about the same person returning in another Track |
| Trip-line crossings | line, crossing time (interpolated), direction (`aToB`/`bToA`), crossing point, crossing index | Segment intersection with debounce |
| Direction of travel | coarse eight-way image-space heading over the Track (and per zone transition where useful); optional source-zone → destination-zone relation | Not a compass heading unless calibrated |
| Stationary intervals | intervals where displacement stays within a threshold for at least a minimum duration; longest interval; total stationary time | Applies to any class |
| Stopped-vehicle duration | stationary interval for a vehicle Track, optionally within a zone | Same rule, class-filtered |
| Loitering | transparent rule: class = person, accumulated dwell in zone ≥ threshold (zone override or default), optional maximum excursion radius | Persisted with the exact thresholds used |
| Counts | entries and exits per zone; crossings per line and direction; class counts per time bucket | Each count states whether it counts Tracks, visits or crossings |
| Occupancy | concurrent Tracks inside a zone over time; peak occupancy and its time | From visit intervals; time-bucketed |
| Movement heatmap | aggregate spatial density of reference points for a camera, class, run/video and window | Derived visualisation, not primary evidence |
| Motion diagnostics | normalised displacement per second, path length in normalised units | Engineering diagnostics; never labelled as speed |

**Physical speed** is out of this increment unless a calibrated `CameraCalibration` exists and has a validation record; even then the UI shows the error tolerance beside the value.

## 5. Determinism and geometry semantics

These rules are the contract; one implementation in the Application layer is the source of truth, and the frontend draws but never decides.

- **Coordinates.** Normalised image space: origin top-left, `x` right, `y` down, range `[0, 1]` in both axes; stored as decimals with fixed precision (6 places) to make equality and hashing stable.
- **Reference point.** Bottom-centre of the bounding box, computed once per sample.
- **Point-in-polygon.** Even–odd rule; a point exactly on an edge or vertex counts as **inside**. Polygons are simple (validated on save); orientation is irrelevant.
- **Segment intersection.** A trajectory segment (consecutive samples) crosses a trip line when the two open segments intersect properly, or when the endpoint touches the line and the previous strict side differs from the next strict side. Collinear overlap is not a crossing.
- **Crossing debounce.** A crossing is recorded only if the reference point was at least `ε` (default 0.005 normalised) on the previous side before the crossing and reaches at least `ε` on the new side within the next `k` samples (default 3); otherwise the transition is jitter and is ignored. Two crossings of the same line in the same direction less than `t_min` (default 1.0 s) apart collapse into one.
- **Zone hysteresis.** Entry requires the reference point inside; exit requires the reference point outside by at least `ε` for `k` consecutive samples. This prevents one-sample flicker from splitting a visit.
- **Interpolation.** Linear interpolation of the reference point between consecutive samples for crossing times and visit boundaries. No extrapolation beyond the first or last sample.
- **Beginning or ending inside.** A Track that begins inside a zone opens a visit at its first sample with `beganInside = true`; a Track that ends inside closes the visit at its last sample with `endedInside = true`. Dwell counts the observed interval only.
- **Sampling gaps.** A gap between samples longer than `g_max` (default 2.0 s) is treated as unknown: no crossing or visit boundary is inferred across it, an open visit is closed at the last sample before the gap, and the gap is recorded on the Track's motion summary.
- **Missing or corrupt trajectory.** If the trajectory artefact is missing, fails its digest, or has fewer than two valid samples, the Track receives an analytics record with `state = unavailable` and a reason code; it is never silently treated as "no events".
- **Direction classification.** Eight-way heading from the displacement between the first and last valid samples of the window; below a minimum displacement the heading is `none`.
- **Stationary detection.** A sliding window over samples; stationary while the maximum displacement of the reference point within the window is below `d_stat` (default 0.01 normalised) for at least `t_stat` (default 5.0 s).

Defaults are algorithm parameters, versioned with the algorithm, and recorded on every fact.

## 6. Processing semantics — decision

Analytics are a **separate, idempotent post-processing stage**, not part of atomic processing completion.

Reasons: completion is the worker's sealed contract for what the model observed (ADR-006) and must not depend on operator-editable geometry; analytics depend on a configuration revision that can legitimately change; and re-analysis must be possible without reprocessing video. This keeps the Python vision worker boundary unchanged: the stage runs in the .NET Application layer over persisted trajectories.

To keep partially analysed runs distinguishable from fully analysed ones:

- Each processing run carries an `analyticsState` per camera configuration revision: `notStarted`, `running`, `complete`, `unavailable` (with counts of Tracks analysed and Tracks unavailable).
- Analytics run automatically after completion for the configuration revision current at that time, and on demand ("Re-analyse with current configuration") producing facts for the new revision alongside, never replacing, the old ones.
- Search predicates on analytics only consider runs whose `analyticsState` is `complete` for the revision being queried; the UI states when a run is not yet analysed rather than returning an empty result that looks like "nothing happened".
- The stage is idempotent: re-running for the same Track, revision and algorithm version replaces identical facts and never duplicates them.

## 7. Persistence

Typed tables rather than one untyped event table, so invariants are enforceable:

- `scene_configurations`, `scene_zones`, `trip_lines` (revisioned as in §3).
- `track_zone_visits` — track id, processing run id, camera id, configuration revision, algorithm version, zone id, entry/exit times, dwell, visit index, began/ended-inside flags.
- `track_line_crossings` — track id, run id, camera id, revision, algorithm version, line id, crossing time, direction, crossing point, crossing index.
- `track_motion_summaries` — track id, run id, revision, algorithm version, heading, path length, stationary intervals (as a small typed array or child table), longest stationary interval, loitering flag and the thresholds used, gaps, `state` and reason.
- `run_analytics_states` — run id, revision, algorithm version, state, counts, timestamps.

Every row binds Track, processing run, camera, configuration revision and algorithm version. Deleting a configuration never deletes facts; facts for retired revisions remain queryable by revision.

## 8. Search and API

Extend the committed-filter contract (canonical URL state and snapshot semantics preserved) with explicit predicates: `zoneId`, `zoneRelation = entered | exited | dwelled`, `minDwellSeconds`, `lineId`, `crossingDirection`, `motionDirection`, `minStationarySeconds`, `loitering = true`, plus `sceneRevision` (defaults to the latest complete revision for the camera). Predicates combine with the existing camera, class, time, duration and confidence filters. No natural-language search in this slice.

Aggregate endpoints (read-only): counts by zone/time bucket, crossings by line/direction/time bucket, occupancy series and peak, heatmap grid for a camera/window/class.

## 9. Evidence and operator UI

**Scene editor** per camera: reference frame, draw/edit/delete polygons and lines, name, enable/disable, line direction indicator, validation feedback, explicit Save creating a new revision, revision history.

**Search filters:** analytics predicates in a disclosed "Scene analytics" group so the existing rail stays usable.

**Evidence explanation:** when a Track matched an analytic predicate, the inspector and Review page overlay the zone or line, mark the crossing point and time or the dwell/stationary interval on the timeline, and show the configuration revision and algorithm version responsible. The operator can verify every derived result visually.

**Aggregate views:** only those that exploit the new data directly (counts by zone/time, occupancy trend, crossing directions, heatmap). No generic report builder.

## 10. Performance

Expected query patterns, in order: Tracks in a camera and time window with a zone relation and minimum dwell; crossings by line, direction and time; loitering flag with camera/time; occupancy series per zone; heatmap per camera/window. Facts are stored and indexed for these; geometry is never recomputed at search time.

Initial indexes: `(camera_id, zone_id, entry_time)` on visits; `(camera_id, line_id, crossing_time, direction)` on crossings; `(track_id)` and `(processing_run_id)` on all fact tables; `(camera_id, revision)` on run states. Dwell- and stationary-duration indexes are added only after measured need. Analysis is linear in sample count per Track.

## 11. Tests

- **Geometry unit tests:** inside/outside/on-edge/on-vertex points, concave polygons, invalid or self-intersecting polygon rejection, proper and touching intersections, collinear overlap non-crossing, direction classification, jitter around a line (no crossing), genuine repeated crossings.
- **Temporal tests:** dwell accumulation, multiple visits, entry without exit, Track beginning and ending inside, stationary threshold edges, gaps closing visits, missing/corrupt trajectory → `unavailable`.
- **Determinism:** golden fixtures of trajectories and configurations with expected facts; identical output across runs and across CPU/CUDA-produced trajectories of the same content.
- **Persistence/integration (PostgreSQL):** revision binding, idempotent re-analysis, retired revisions remain queryable, search predicates and snapshot pagination with analytics filters, `analyticsState` gating.
- **UI:** editor validation, canonical filter state, overlay alignment against known geometry, explanation content, keyboard access.
- **Real-stack evidence:** recorded videos with deliberately staged crossings and dwells, expected outcomes checked independently, run through the real worker path on the development laptop.

## 12. Slices

0. **Design/ADR:** coordinate convention, reference point, revisioning, persistence, processing semantics (§6), speed/calibration policy, dependency statement (none).
1. **Scene geometry:** domain, persistence, API, scene editor.
2. **Analytics engine:** deterministic geometry and temporal rules with golden tests.
3. **Persistence and search:** fact tables, indexes, `analyticsState`, structured predicates.
4. **Evidence visualisation:** overlays and explanations in inspector and Review.
5. **Aggregates:** counts, occupancy, heatmap.
6. **Hardening:** cold review, real-stack corpus, performance check against the query patterns, `verify_repo`, exact-head CI.

## 13. Acceptance

The increment is complete when, offline, an operator can: define zones and lines for a camera and save a revision; process a recorded video; search for persons or vehicles by zone entry/exit, minimum dwell, line crossing with direction, stationary duration or loitering; open the Track evidence and see the exact geometry, crossing point or interval and the revision responsible; re-analyse after a geometry edit and see both revisions' facts distinguished; and reproduce identical facts from the same Track, revision and algorithm version. Runs not yet analysed are visibly not analysed rather than empty.

## 14. Out of scope

ANPR/OCR, appearance attributes, embeddings, ReID, Entity association, face recognition, natural-language search, cases and reporting, live ingestion, physical speed without calibration.

## 15. Next capability after this increment

**Visual Attributes** — see `capability-roadmap.md` stage 2.
