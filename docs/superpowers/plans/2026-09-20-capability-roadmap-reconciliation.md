# Capability Paper → Laptop-Development Milestones (Reconciliation)

**Date:** 2026-09-20  
**Status:** Current capability-development roadmap.  
**Baseline:** `main` after PR #50 merge; PR #49 remains the separate Windows CUDA qualification/runtime stream.  
**Product direction:** recorded-video intelligence capability first; operator workflow/reporting later; live cameras/VMS last. Offline compatibility and the Development-evidence / Production-qualification distinction (ADR-008, ADR-009) remain mandatory.

This document maps the capability paper onto what exists and sets the current implementation sequence. Historical implementation, review and qualification records remain authoritative for what was verified at the time; this roadmap controls what we build next.

## Product sequencing decision — 20 September 2026

The next development objective is **not** cases, reporting, or a large review-management layer.

The present system already supports recorded-video import, RTMDet + ByteTrack processing, Track persistence, structured search and evidence playback. Its immediate limitation is the **thin semantic content of each Track**: primarily person/vehicle class, time, confidence and trajectory.

Therefore the next phase shall increase what MAVI can understand and retrieve from video before building heavier investigation workflow.

Priority order:

1. **Spatial & Temporal Track Analytics**
2. **Visual Attributes**
3. **Expanded operational object classes / vehicle subclasses**
4. **ANPR / OCR**
5. **Visual similarity / query-by-example**
6. **Person/vehicle ReID and candidate cross-camera association**
7. **Event and behaviour analytics**
8. **Richer structured search and, later, natural-language query translation**
9. **Audited human review / cases when the data is rich enough to justify investigation workflow**
10. **Live RTSP / VMS ingestion after recorded-video intelligence is mature**

Identity/audit plumbing may be introduced earlier only when a concrete operator mutation genuinely requires attribution. It is not the next major product capability.

## States

- **Merged and verified** — on `main`, with exact-head CI/evidence.
- **Implemented, unmerged** — complete on a branch with qualification pending merge.
- **Groundwork without a usable feature** — schema/module boundary exists; no operator capability.
- **Future** — not yet implemented.

## Mapping

| Capability-paper element | State | Where / evidence | Next milestone |
|---|---|---|---|
| Camera registry with camera-local time authority | Merged and verified | Task 15; `/api/cameras`, Cameras page; ADR-004 | — |
| Import recorded MP4 with manual recording time; MAVI-owned media | Merged and verified | Task 15; `/api/videos/import`, Import page | — |
| Durable processing-run / vision-job lifecycle | Merged and verified | Tasks 7–9, 13, 17 | — |
| Person/vehicle detection + single-camera tracking | Merged and verified on Windows CPU Development | Task 10 / Task 12 | PR #49 completes Windows CUDA Development stream |
| Atomic Track/observation/trajectory persistence with sealed evidence | Merged and verified | Task 13; ADR-006 | Foundation for analytics |
| Structured Track search with stable cursor snapshot | Merged and verified | Task 14 API, Task 16/PR #50 UI | Extend with analytics/attribute filters |
| Evidence-linked playback and trajectory/bbox overlay | Merged and verified | Task 14 + PR #50 | Reuse for new analytics |
| Processing inventory/status/retry | Merged and verified | Task 15 + PR #50 | Historical runs later |
| Spatial/temporal Track analytics | **Next feature** | Existing trajectory/time data provides groundwork; no operator feature yet | Zone/line/dwell/direction/count/occupancy/loitering analytics |
| Visual attributes | Groundwork without a usable feature | `VisualAttribute` table exists but is unpopulated | Person/vehicle colour and selected appearance attributes |
| Expanded object classes / vehicle subclasses | Future | Current product semantics are person/vehicle centric | Preserve broad `Vehicle` grouping while storing useful subclasses |
| ANPR / OCR | Future | No plate/OCR pipeline yet | Vehicle Track → plate detection → OCR → searchable observations |
| Visual similarity / query-by-example | Future | pgvector present; no embeddings produced | “Find similar” for person/vehicle Tracks |
| Persistent Entity / ReID | Groundwork without usable feature | `Entity` dormant; `Track.EntityId` nullable | Only after similarity retrieval is stable; candidate association first |
| Event/behaviour analytics | Future | Trajectory groundwork only | Loitering, intrusion, wrong-way, stopped vehicle, crowd/group behaviours, repeated visits |
| Natural-language search | Future | — | Translate to deterministic structured queries after semantic fields exist |
| Human review decisions | Groundwork without usable feature | `ReviewStatus` exists, display-only | Deferred until richer intelligence warrants operator decisions |
| Investigation cases | Groundwork without usable feature | Reserved module boundary only | Deferred until richer semantic/search capabilities exist |
| Historical runs per video | Future | Latest-run view only; historical run query possible by ID | Small API/UI increment; can be scheduled between capability slices |
| Mission rules / relationship intelligence | Future | Reserved boundary | After event/entity foundations |
| Face recognition | Future / separate qualified increment | — | Only if mission requirement justifies it |
| Live integration (RTSP/VMS) | Future — intentionally last | No live ingestion path | Dedicated streaming architecture/ADR after recorded-video capability matures |

## Next feature: Spatial & Temporal Track Analytics

This is the preferred first capability slice after PR #49 because it extracts materially more intelligence from data MAVI already persists without first introducing another heavyweight AI model.

Initial capability set should be designed around **deterministic, explainable Track-derived facts**:

- configurable zones/polygons;
- configurable trip lines;
- zone entry/exit;
- line crossing;
- direction of travel;
- dwell duration;
- stationary / stopped-object duration;
- loitering rule based on explicit thresholds;
- Track path length in image/world coordinates as available;
- counts by class, zone and time window;
- occupancy over time;
- repeated zone visits;
- movement heatmaps;
- speed only where camera calibration makes the estimate defensible.

Search/API should expose these as structured predicates rather than free-text logic.

Examples of target operator queries:

- persons remaining in Zone 3 for more than two minutes;
- vehicles crossing Gate A between 1400–1600;
- vehicles stopped in a restricted area longer than ten minutes;
- person Tracks moving from Zone A toward Zone B;
- occupancy/count trends for a selected zone and interval.

## Capability expansion sequence

### Stage A — deterministic scene analytics
Spatial/temporal analytics from existing Tracks. No new recognition model required.

### Stage B — richer appearance semantics
Visual attributes and useful object subclasses. Each new model/runtime dependency must follow the offline dependency and qualification policy.

### Stage C — vehicle identity cues
ANPR/OCR with plate evidence tied to vehicle Tracks.

### Stage D — similarity
Embeddings + pgvector for query-by-example. Results are **similarity candidates**, not identity assertions.

### Stage E — ReID / entity candidates
Person/vehicle candidate association across Tracks/cameras. Human-verifiable evidence remains available; automatic hard merges are avoided initially.

### Stage F — event/behaviour intelligence
Rules over trajectories, zones, time, attributes and candidate entities.

### Stage G — richer query layer
Structured query expansion first; natural-language translation only after underlying semantics are deterministic and testable.

### Stage H — operator investigation workflow
Audited review, cases and reporting become useful once MAVI has enough semantic content to investigate rather than merely catalogue detections.

### Stage I — live operations
RTSP/VMS ingestion, buffering, reconnect semantics, retention, stream health, GPU scheduling/load shedding and continuous processing.

## Recorded separately

**Windows CUDA Development qualification.** PR #49 remains an infrastructure/qualification stream and is completed before beginning the next feature branch.

**Formal Production qualification.** Task 18 remains independent of feature sequencing. Development capability does not imply Production profile support.

**Historical plans.** Earlier plans that placed audited review/cases immediately after PR #50 remain useful design work but are now **deferred**, not the active next implementation increment.

## Current execution order

1. Finish and merge PR #49.
2. Establish the post-#49 exact-head baseline.
3. Plan and implement **Spatial & Temporal Track Analytics**.
4. Implement **Visual Attributes**.
5. Expand operational object/vehicle classes where useful.
6. Implement **ANPR/OCR**.
7. Implement **Visual Similarity / Find Similar**.
8. Implement **ReID / Entity candidate association**.
9. Implement **Event / Behaviour Analytics**.
10. Extend structured search; consider natural-language query translation.
11. Add audited review/cases when semantic richness justifies them.
12. Add live RTSP/VMS ingestion last.
