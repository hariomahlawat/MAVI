# Spatial & Temporal Track Analytics — Implementation Plan

**Date:** 2026-09-20  
**Status:** Proposed next feature after PR #49 is merged and the post-merge baseline is green.  
**Product intent:** derive materially richer, explainable intelligence from Tracks already produced by RTMDet + ByteTrack before adding new recognition models or heavier investigation workflow.

## 1. Why this is next

MAVI already provides:

- recorded-video import;
- person/vehicle detection;
- single-camera tracking;
- persisted observations and trajectory artefacts;
- structured Track search;
- evidence-linked playback;
- an operator Search/Review workspace.

The immediate limitation is semantic depth. A Track currently tells the operator little beyond **what broad class was seen, when, where in the frame, for how long, and with what confidence**.

The next increment should convert trajectory/time data into searchable scene facts without first requiring another heavyweight AI model.

This provides a large capability increase while remaining deterministic, testable and explainable.

## 2. Core principles

1. **Derived facts, not speculative inference.** Every analytic result must be traceable to persisted Track/trajectory data plus explicit scene configuration.
2. **Camera-local geometry.** Zones and lines belong to a camera/view configuration and are never silently shared across unrelated cameras.
3. **Versioned scene configuration.** Analytics must record which zone/line/calibration revision produced a result.
4. **No false physical precision.** Pixel-space distance/direction may be exposed directly; speed in physical units requires calibrated geometry.
5. **Reproducibility.** Reprocessing the same Track against the same analytic configuration must produce deterministic results.
6. **Search-first design.** New analytics are valuable only when operators can filter, inspect and verify them against evidence.
7. **Offline-first.** No new cloud/network dependency.
8. **Live ingestion remains out of scope.** Everything is developed and qualified against recorded video first.

## 3. Initial capability set

### A. Scene geometry

Per-camera configurable:

- polygonal Zones;
- directed/undirected Trip Lines;
- optional named entry/exit points;
- optional calibration metadata for later world-coordinate conversion.

Each geometry object should have:

- stable id;
- camera id;
- name;
- type;
- coordinates in normalized image space;
- enabled state;
- created/updated timestamps;
- revision/version.

### B. Zone analytics

For each Track:

- entered zone;
- exited zone;
- first entry time;
- last exit time;
- total dwell duration;
- number of visits;
- currently/intermittently inside where meaningful for completed Track reconstruction.

Primary operator queries:

- persons entering Zone A;
- vehicles leaving Zone B;
- Tracks remaining in Zone C longer than N seconds;
- repeated visitors to a zone within one recording/run.

### C. Line-crossing analytics

For each Track:

- line crossed;
- crossing time;
- crossing direction;
- number of crossings.

Primary queries:

- vehicles crossing Gate A inbound;
- persons crossing Line B outbound;
- counts per direction and time interval.

Crossing must be based on trajectory segment intersection with defined tolerance/debounce so small tracker jitter does not produce duplicate crossings.

### D. Direction of travel

Derive a stable coarse direction from Track motion:

- left/right/up/down or angle/bearing in image space;
- optional source-zone → destination-zone relation.

Avoid claiming world-heading unless calibrated.

### E. Dwell / stationary / stopped-object analytics

Derived metrics:

- total Track duration;
- dwell inside configured zone;
- stationary interval;
- longest stationary interval;
- stopped vehicle interval.

Stationary logic must use explicit pixel/normalized displacement and duration thresholds and be robust to tracker jitter.

### F. Loitering

Loitering must initially be a transparent rule, not an opaque AI classification.

Example rule:

- object class = person;
- inside zone X;
- accumulated dwell >= configured threshold;
- optional maximum excursion radius.

Persist/expose the exact threshold/config revision used.

### G. Counts and occupancy

Provide:

- entries/exits per zone;
- class counts per time bucket;
- concurrent occupancy over time;
- peak occupancy;
- line-crossing counts by direction.

Be explicit whether a metric counts Tracks, crossings or unique Tracks.

### H. Repeated visits

Detect multiple entries of the same Track into the same zone during one Track lifetime.

Do **not** interpret separate Tracks as the same person/entity at this stage.

### I. Movement heatmaps

Generate aggregate spatial density from Track trajectories for:

- selected camera;
- selected processing run/video/time window;
- optional object class.

Heatmaps are derived visualization data, not new primary evidence.

### J. Speed

Defer physical speed unless camera calibration is available and validated.

Initial implementation may expose:

- normalized image-space velocity;
- pixel/normalized displacement rate for engineering diagnostics.

Operator-facing km/h or m/s must require a calibrated camera-plane transform and documented error tolerance.

## 4. Proposed architecture

### Scene configuration module

Introduce a small scene-analytics configuration boundary rather than embedding polygons into frontend state.

Suggested concepts:

- `SceneZone`
- `TripLine`
- `SceneConfigurationRevision`

Configurations are camera-scoped and versioned.

### Derived analytics

Prefer explicit persisted analytic records for facts operators will search repeatedly.

Candidate concepts:

- `TrackZoneVisit`
- `TrackLineCrossing`
- `TrackMotionSummary`
- `TrackAnalyticEvent`

Avoid one generic untyped JSON event table as the sole domain model. A compact typed event envelope may be useful later, but core searchable facts should have enforceable schema/invariants.

### Processing point

Analytics should run after Track trajectory completion/sealing and before a processing run is made fully searchable, or as a deterministic post-processing stage with an explicit completion state.

The architecture review must decide whether:

1. analytics are part of atomic processing completion; or
2. analytics are a separate idempotent stage whose readiness is visible in search.

Do not silently expose partially analysed runs.

## 5. Search/API expansion

Extend structured search with explicit predicates such as:

- `zoneId`
- `zoneRelation=entered|exited|dwelled`
- `minDwellSeconds`
- `lineId`
- `crossingDirection`
- `motionDirection`
- `minStationarySeconds`
- `loitering=true`

Maintain canonical URL state and snapshot semantics.

Do not add natural-language search in this slice.

## 6. Operator UI

### Camera scene editor

A professional per-camera configuration view should support:

- display representative/reference frame;
- draw/edit/delete polygon zones;
- draw trip lines;
- name and enable/disable geometry;
- direction indication for lines;
- validation against self-intersecting/degenerate shapes;
- explicit Save producing a new configuration revision.

### Search filters

Add analytics filters without overcrowding the existing rail.

Use grouped/disclosed advanced filters where appropriate.

### Evidence review

When a Track matched an analytic condition, show why:

- zone outline;
- line;
- entry/exit/crossing marker;
- dwell interval on timeline;
- stationary interval;
- analytic configuration revision.

The operator should be able to visually verify every derived result.

### Analytics overview

Add focused aggregate views only where they directly exploit the new data:

- counts by zone/time;
- occupancy trend;
- crossing direction counts;
- heatmap.

Avoid a generic report builder.

## 7. Persistence and revision semantics

A scene geometry edit must not retroactively change the meaning of old persisted results without explicit recomputation.

Every persisted analytic fact should reference:

- Track id;
- processing run id as applicable;
- camera id;
- scene configuration revision;
- analytic algorithm/version;
- derived timestamps/metrics.

If configuration changes, old analytics remain historically interpretable.

Provide an explicit re-analyse operation later if required; do not mutate historical facts silently.

## 8. Determinism and geometry rules

Define and test:

- normalized coordinate convention;
- trajectory interpolation;
- point-in-polygon boundary semantics;
- line-crossing intersection rule;
- crossing debounce;
- jitter tolerance;
- minimum samples;
- dwell start/end rules;
- stationary displacement window;
- time interpolation between trajectory samples;
- behaviour when trajectory data is missing/corrupt.

Use one geometry implementation as the source of truth; avoid slightly different frontend/backend definitions.

## 9. Tests

Minimum test families:

### Geometry unit tests
- point inside/outside/on polygon edge;
- concave polygons;
- invalid/self-intersecting polygon rejection;
- line intersection;
- endpoint/tangent cases;
- direction classification;
- jitter around line;
- repeated crossing.

### Temporal tests
- dwell accumulation;
- multiple zone visits;
- entry without exit before Track end;
- Track begins inside zone;
- Track ends inside zone;
- stationary threshold;
- gaps in trajectory samples.

### Persistence/integration tests
- configuration revision binding;
- deterministic recomputation;
- search predicates;
- snapshot pagination with analytic filters;
- processing visibility only after required analytics readiness;
- historical results remain bound to historical config.

### UI tests
- zone/line editor;
- invalid geometry;
- canonical filter state;
- overlay alignment;
- analytic explanation;
- keyboard/accessibility.

### Real-stack evidence
Use recorded videos containing deliberately chosen crossings/dwells where expected outcomes can be independently inspected.

## 10. Performance considerations

Analytics should be linear or near-linear in trajectory sample count.

Avoid per-search geometry recomputation for common predicates.

Persist/index frequently searched facts.

Candidate indexes:

- zone id + entry time;
- line id + crossing time + direction;
- Track id;
- processing run id;
- camera id;
- dwell duration where query patterns justify it.

Measure before introducing specialized indexes.

## 11. Out of scope

This increment does not include:

- ANPR/OCR;
- clothing/vehicle attributes;
- image embeddings;
- ReID;
- Entity association;
- face recognition;
- natural-language search;
- cases/reporting;
- live RTSP/VMS ingestion;
- automatic physical speed without calibration.

## 12. Proposed implementation slices

### Slice 0 — design/ADR
Freeze coordinate system, scene configuration revisioning, analytic persistence strategy, processing visibility semantics and speed/calibration policy.

### Slice 1 — scene geometry
Domain/persistence/API + camera scene editor for zones and lines.

### Slice 2 — deterministic Track analytics engine
Zone visits, line crossings, direction, dwell, stationary metrics.

### Slice 3 — persistence and search
Persist analytic facts, indexes, structured search filters and API contracts.

### Slice 4 — evidence visualization
Overlay zones/lines and explain matched analytics on Track evidence.

### Slice 5 — aggregate analytics
Counts, occupancy and heatmap views.

### Slice 6 — hardening
Cold review, deterministic real-stack corpus, performance checks, offline/dependency verification and exact-head CI.

## 13. Acceptance

The increment is complete when an operator can:

1. define a camera zone/line;
2. process a recorded video;
3. search for a person/vehicle based on zone/line/dwell/stationary conditions;
4. open the Track evidence;
5. see the exact geometry/event that caused the match;
6. reproduce the same result from the same Track + configuration revision;
7. run the entire workflow offline.

## 14. Next capability after this increment

**Visual Attributes** — person/vehicle appearance attributes and useful vehicle subclasses, integrated into the same structured search/evidence model.
