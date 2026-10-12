# MAVI Capability Implementation Roadmap

**Status:** Authoritative implementation-level roadmap. `capability-roadmap.md` answers *what we build next*; this document answers *how the stages depend on one another, what each changes technically, and what must be true before advancing*.  
**Baseline:** `main@e38af446d4e287cb12a8cf3d881e0293f90f7d6d` (Scene Analytics Stage 1 / PR #70 merged and post-merge verified).  
**Written:** 2026-09-20. Planning only; no feature code, migration, dependency or runtime change accompanies this document.  
**Planning amendment:** 2026-10-12 — the forward capability architecture adds Stage 5A Face Intelligence, strengthens Stage 8 into deterministic structured intelligence/aggregation, makes Stage 9 the separate Ask MAVI operator surface, and records capability-specific specialist-model selection. No feature/runtime change is made by this amendment.  
**Companion:** `2026-09-20-spatial-temporal-track-analytics.md` is the completed parent implementation-grade plan for stage 1; `2026-09-22-scene-analytics-s7-hardening-acceptance.md` is the closure plan; `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md` is the final acceptance register. `docs/architecture/ui-ux-design-specification.md` is the adopted UI/UX specification. **UI-1 through UI-5 and Scene Analytics Slices 0–7 are merged. Stage 1 is fully closed: exit-gate items 1–20 PASS, including post-merge verification on `main@e38af446d4e287cb12a8cf3d881e0293f90f7d6d`.** The current capability is **Stage 2 — Visual Attributes** (status 2026-09-28: S1 merged, B1–B6 OPEN pending S1.4 evidence; S2a closed in PR #112; S2b closed through PR #114; PR #115 merged the accepted S2c plan at `main@677afb6b73edf436e23f8d275bb95a7d5b3badac`; S2c.0 closed through PR #116; S2c.1 task/corpus/labels tooling merged in PR #117 with F1 OPEN; S2c.2a candidate admissibility & credibility merged in PR #118; S2c.2b-1 quality/statistical protocol merged in PR #119; S2c.2b-2 architecture merged in PR #121 (`main@8b6614721ff3d0fe7a77cde66ce6051defcceb74`); protocol/validator/replay implementation merged in PR #122 (`main@7b8913982dc6796a1676de075cf1dc22a7676891`; `docs/qualification/stage2-s2c/s2c-2b2-implementation-record.md`); the real qualification execution plan merged in PR #123 (`main@d0db6efff201a003b9699cde675d8069259f980e`), with Slice A preparation recorded in `docs/qualification/stage2-s2c/real-qualification-execution-record.md` (both MSRs remain PLANNED)). **Stage 3 — Vehicle Subclass** ran in parallel as a bounded Development measurement under ADR-016 (S3.1, S3.2a, S3.2b-1, S3.2b-2 and S3.2b-3 complete; S3.2c complete with G1–G9 PASS (G6 by owner-accepted deviation; G9 baseline 0.6 / 3); S3.2d complete with H1–H5 PASS under ADR-017; X1 PASS selects global `{car}`; X2/X3 PASS (PR #179, merged `9ab499bd`, post-merge CI green); Stage 3 is complete; register `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`). Task 18 (`2026-09-18-task-18-phase1-production-qualification-rebaseline.md`) remains a separate, parallel qualification stream and is not a stage here.

## 0. The baseline this roadmap builds on

Facts below were read from the code at the baseline SHA, not from earlier plans.

| Area | Present state | Consequence for the roadmap |
|---|---|---|
| Layering | `Mavi.Domain` (sealed aggregates, `Create` factories, intent methods, `DomainValidationException(code)`), `Mavi.Application` (plain services + repository ports; modules `Cameras`, `Evidence`, `Intelligence`, `Media` implemented; `Audit`, `Entities`, `Identity`, `Investigations`, `Missions`, `SystemHealth` reserved with README only), `Mavi.Infrastructure` (EF Core, PostgreSQL 18 + pgvector extension enabled, no vector column yet), `Mavi.Api` (minimal APIs, RFC 7807 problems with `extensions.code`), `Mavi.Contracts` (typed request/response records, `JsonUnmappedMemberHandling.Disallow`). Project-reference direction is pinned by `ArchitectureBoundaryTests`. | New capabilities land as new Application modules with Domain aggregates, Infrastructure repositories and Contracts records; no MediatR, no generated OpenAPI. |
| Track model | `Track` (`ProcessingRunId`, `VideoAssetId`, `ObjectClass` Person/Vehicle, offsets and UTC timestamps, counts, confidences, `RepresentativeObservationId`, `TrajectoryArtifactId`, `ReviewStatus` display-only, `EntityId` nullable never set). `Observation` declares four types (`TrackStart`, `Representative`, `BestQuality`, `TrackEnd`) but the processing path persists exactly one `Representative` observation per Track with a normalised bounding box; the other three are unpopulated (Stage 2 maps or retires them, ADR-013 §7). `VisualAttribute` and `Entity` tables exist, unpopulated. | Per-frame boxes are **not** in the database. |
| Trajectory evidence | One msgpack artefact per Track (`ArtifactType.TrackTrajectory`), format `{v: 1, points: [[offsetMs, centreX, centreY], …]}` with strictly increasing offsets, sealed into the platform-owned evidence root with SHA-256 (ADR-006). The browser parses it with the same validation (`features/video-review/trajectory.ts`). | Stage 1 analytics work from centre points at v1. Any richer per-sample data (box height, bottom-centre) is a trajectory format change produced by the worker. |
| Processing lifecycle | `ProcessingRun` Queued → Running → Completed/Failed/Cancelled; `VisionJob` 1:1 with lease token, attempts, heartbeat progress, completion digest. Completion (`ProcessingResultStore.CompleteAsync`) is one transaction: validate payload, seal evidence, build entities, then exclusive advisory lock → allocate `processing_visibility_sequence` → `MarkCompleted` → `MarkProcessed` → commit. No background hosted service exists in the platform; expired leases are recovered at the next lease call. | Anything that must happen after completion needs either a new hosted service or an on-demand trigger; the completion transaction must not grow to include operator-editable inputs. |
| Search | `GET /api/tracks` with a strict whitelist of filters (camera, video, run, class, from/to, minimum duration, minimum confidence, cursor, limit). First page takes the shared barrier lock and allocates a snapshot sequence; the cursor carries snapshot time, snapshot sequence, keyset position and a SHA-256 filter fingerprint; default scope is the latest visible completed run per video. | New predicates extend the whitelist, the fingerprint and the repository query; snapshot semantics are the contract to preserve. |
| Operator UI | React 19 + Vite + react-query + react-router; features `cameras`, `video-import`, `videos`, `processing`, `visual-search` (canonical committed-filter URL state in `searchState.ts`), `video-review` (evidence player with letterbox-aware overlay projection in `overlay.ts`). Vitest + jsdom, 161 tests. | Overlays already project normalised coordinates into the rendered frame; analytics geometry reuses that projection. |
| Vision worker | Python, RTMDet + ByteTrack behind `Detector`/`Tracker` protocols, qualified runtime packs (Windows CPU qualified; Windows CUDA `qualified-development-hardware`), `embeddings/interfaces.py` exists with no implementation. Completion payload: tracks with representative observation, thumbnail and trajectory artefact descriptors, runtime provenance. | Model-based stages change the worker and its qualified runtime; deterministic stages do not have to. |
| Dependency discipline | `config/dependencies/offline-dependency-policy-v1.json` and `docs/architecture/dependency-and-offline-packaging-policy.md`; `verify_repo.py` fails closed on undeclared drift; every model or runtime ships as a manifest-verified pack. | Each dependency-bearing stage updates the contract in the same PR. |
| CI | Quality Gate (Python/.NET/web + verify_repo + guard coverage), Task 10 CPU runtime qualification matrices, Task 12 offline runtime pack, Task 17 acceptance (deterministic and Windows script validation), Vision Model Pack, Vision Runtime Component Boundary (PR-only, path-filtered). | New workflows are added only when a stage introduces a new qualified artefact class. |

## 1. Stage map and dependency graph

```
                 ┌──────────────────────────────┐
                 │ 1 Spatial & Temporal Analytics│  (deterministic; no new model)
                 └──────────────┬───────────────┘
      hard ┌────────────────────┼─────────────────────┐ hard
           ▼                    ▼                     ▼
 ┌──────────────────┐  ┌────────────────────┐  ┌───────────────────────┐
 │ 2 Visual         │  │ 7 Event / Behaviour│  │ 8 Richer Structured   │
 │   Attributes     │  │   Analytics        │  │   Search              │
 └────────┬─────────┘  └──────────▲─────────┘  └───────────┬───────────┘
   soft   │                       │ hard (2, 6 as inputs)  │ hard
          ▼                       │                        ▼
 ┌──────────────────┐             │             ┌───────────────────────┐
 │ 3 Expanded       │─────────────┘             │ 9 Natural-language    │
 │   classes        │                           │   translation         │
 └────────┬─────────┘                           └───────────────────────┘
   soft   │
          ▼
 ┌──────────────────┐        ┌───────────────────┐  hard  ┌───────────────────┐
 │ 4 ANPR / OCR     │        │ 5 Visual Similarity│───────▶│ 6 ReID / Entity   │
 └──────────────────┘        └───────────────────┘        │   candidates      │
                                                          └─────────┬─────────┘
                                                                    │ hard (attributable decisions)
                                                                    ▼
                                                          ┌───────────────────┐
                                                          │10 Audited review /│
                                                          │   cases           │
                                                          └───────────────────┘
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │11 Live RTSP / VMS — separate platform phase; depends on 1–8 being mature,     │
 │   not on any single stage                                                     │
 └──────────────────────────────────────────────────────────────────────────────┘
 Parallel, independent: Task 18 Production qualification; PR #49 C5.4/C6/C7 host execution.
```

| Dependency | Kind | Why |
|---|---|---|
| 7 Events ← 1 Analytics | Hard | Events are rules over zones, dwell, crossings and time; without stage-1 facts there is nothing measurable to combine. |
| 7 Events ← 2 Attributes, 6 Entity candidates | Hard for attribute- or entity-conditioned events; soft otherwise | Intrusion, loitering, wrong-way, stopped vehicle need only stage 1; co-occurrence and repeated visit across Tracks need 6. |
| 6 ReID ← 5 Similarity | Hard | Candidate association is nearest-neighbour retrieval plus plausibility constraints; no embeddings, no candidates. |
| 9 NL translation ← 8 Structured search | Hard | The translator emits stage-8 predicates; nothing to translate into otherwise. |
| 8 Structured search ← 1, 2, 4 | Hard for the predicates each contributes; the search layer itself is incremental | Each stage adds its own predicates as it lands; stage 8 is the consolidation and query-composition work, not the first appearance of predicates. |
| 10 Review/cases ← 6 | Hard for Entity confirmation; soft for Track review alone | Writing `Track.EntityId` is an attributable operator decision; identity and audit exist for that. Plain confirm/reject could be built earlier but is deferred by product decision. |
| 2 Attributes ↔ 3 Classes | Soft; **resolved for the current source by ADR-016** | Vehicle subclass could come from the detector's class vocabulary or from a Stage-2-style classifier. Accepted ADR-016 chose **detector-native**, so Stage-3 measurement proceeds in parallel with unfinished Stage 2. This roadmap pursues a classifier as a future replacement source only if the S3.2 measurement shows detector-native performance inadequate; introducing one needs a new ADR on source resolution (ADR-016 §6) and its own Model Pack qualification. |
| 4 ANPR ← 3 Classes | Soft | Plate detection benefits from knowing a Track is a car/truck but works on the broad `Vehicle` class. |
| 4 ANPR ↔ 5/6 | Independent | ANPR may land before or after similarity. |
| 1 Analytics ← trajectory v2 (bottom-centre per sample) | Soft | Stage 1 starts on v1 centre points; a worker-side trajectory v2 improves ground-contact geometry later without blocking stage 1 (see the stage-1 plan §J). |
| Task 18 | Independent | Qualification of the frozen Production candidate; proceeds in parallel and is never gated by a roadmap stage. |
| Frontend polish, historical-runs listing | Independent | May be scheduled between stages without changing the sequence. |
| Stage 1 slice 3 ← UI Foundation UI-2 | Hard | **Satisfied.** The UI Foundation programme (UI-1 → UI-5, §33 of `docs/architecture/ui-ux-design-specification.md`, accepted by ADR-012) was inserted after stage-1 slice 2. UI-2 merged with green post-merge `main`, lifting the slice-3 gate; subsequent backend/domain work proceeded in parallel with the remaining UI Foundation increments where it introduced no frontend surface. UI-1 through UI-5 are now complete. |
| Stage 1 slice 4 ← UI Foundation UI-3 and UI-4 | Hard | **Satisfied.** UI-3 is merged (PR #60) and UI-4 is merged (PR #61, `9dbd74d7`). PR #61 post-merge Task 17 Acceptance #1010 and Quality Gate #1866 are green on exact `main`; Slice 4 may begin. |

No other dependencies are asserted; in particular stage 3 does not block stage 4, and stage 10 does not block anything.

## 2. Stage detail

Conventions used in every stage: **Vision/AI** states which of {existing Track data only, deterministic post-processing, new model, embeddings, OCR, cross-camera association, streaming} applies; **Pipeline placement** names where the work runs; **Qualification** names evidence affected. Stage 1 is detailed in its own plan and summarised here.

### Stage 1 — Spatial & Temporal Track Analytics

- **Objective.** Operators can define zones and trip lines per camera and search for Tracks by scene facts: "persons who dwelt in Zone 3 over two minutes", "vehicles crossing Gate A inbound between 14:00 and 16:00", "vehicles stopped in the restricted bay over ten minutes", plus counts, occupancy and heatmaps per camera and window, each match explained visually on the evidence player.
- **Preconditions.** Present baseline only: sealed trajectory artefacts, completed runs, search snapshot, evidence player.
- **Domain/data.** New `SceneAnalytics` module: revisioned per-camera scene configuration (zones, trip lines), an analysis unit per (processing run, scene revision, algorithm version), typed derived facts per Track (zone visits, line crossings, motion summary). No change to `Track`, `Observation`, `Artifact`.
- **Vision/AI.** Existing Track data only; deterministic post-processing. No model.
- **Pipeline placement.** Application-side post-processing stage in .NET, triggered after completion and on demand, executed by a new hosted background service in the API process; the detector/tracker worker and its contract are untouched.
- **API.** Scene configuration CRUD and activation; analysis status and retry; analytic predicates on `GET /api/tracks`; aggregate endpoints; Track detail gains analytic facts.
- **UI.** Camera scene editor; disclosed analytics filter group; evidence explanation overlays; aggregate views.
- **UI foundation.** The UI Foundation programme is complete: UI-1 through UI-5 are merged. Slice 4 uses the Ledger/Investigation grammar; Slice 5 merged on the one Evidence Player/timeline/layer contract; Slice 6 aggregates/heatmap use the UI-2 Workbench grammar.
- **Persistence.** New tables only; existing data untouched; historical Tracks receive analytics only when a run is analysed (initial policy: future runs automatically, past runs on demand). Scene edits create revisions; facts stay bound to the revision that produced them.
- **Control plane.** Analysis units are fenced like `VisionJob` leases (attempt count, claim-token hash, lease expiry, ownership re-validated inside the final transaction); search cursors pin the resolved scene revision and algorithm version; an empty active revision means analytics disabled for that camera; Development mutations are recorded as `development-unattributed` until stage 10 supplies a real principal.
- **Offline/dependency.** None. In-house geometry in .NET.
- **Qualification.** RTMDet, ByteTrack, CPU and CUDA runtime evidence untouched; new analytics evidence is deterministic golden fixtures plus a small staged-video corpus.
- **Performance risks.** Fact-table growth linear in Tracks × zones; aggregate queries over long windows; heatmap computation over many trajectories.
- **Security/privacy.** None new; scene edits should become attributable when identity exists (stage 10).
- **Acceptance / non-goals / slices / exit gate.** See the stage-1 parent plan and the current Slice-7 hardening/performance/acceptance plan. Slices 0–6 and UI-1–UI-5 are merged; Slice 7 hardening/performance/acceptance has **closed Stage-1 functional acceptance (items 1–19 PASS)**; item 20 follows the merge. PostgreSQL 18 qualification passed at reachable SHA `5f516662…`, real-worker acceptance with restart persistence passed on the Development machine, and cancellation/failure at volume, concurrency race probes, the C1 explanation/heatmap/UI legs and accessibility/visual QA have passed; the aggregate-materialisation P2 is closed as RETAIN and the Development-corpus unit record has passed; item 14, the scripted worker path run while disconnected, has passed; final exact-head CI and the post-merge item 20 are itemised in `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md`. Stage exit: acceptance criteria met on the development laptop with the real worker path; analytics-specific evidence recorded; no P1/P2 open; exact-head CI green; ADR-011 remains authoritative.

### Stage 2 — Visual Attributes

**Architecture authority:** `docs/superpowers/plans/2026-09-23-visual-attributes.md`, accepted ADR-013 and ADR-014. Architecture acceptance items A1–A12 are PASS. S1.1 (PR #75), S1.2a (PR #77), S1.2b (PR #78) and S1.2c (PR #79) are merged; S1.2 is complete on `main@2060599a9786651f36071742034076369520d0ce`. The accepted two-tier Representative and scorer `quality-v2` are now part of the frozen raw-evidence path, and the real-clip measurement retained every selector default. **S1.3 (Track-detail read contract + minimal Evidence Set UI) is complete**, governed by `2026-09-24-stage2-s1-3-evidence-read-ui-implementation.md` (accepted, PR #81): S1.3a merged in PR #82 and S1.3b merged in PR #83 at `main@81b43dec32bec0c5e876d2df372503016c05dbdf`. S1.4 hardening/qualification is governed by `2026-09-24-stage2-s1-4-hardening-qualification-implementation.md`; B1–B6 stay OPEN until its evidence is entered. *(Status 2026-09-28: S2a closed (PR #112); S2b closed through PR #114; PR #115 accepted the S2c plan and MSR method v1; S2c.0 closed through PR #116 (`main@647d8f605d7c29bb6984408cb4d7e87eb5dcc163`); S2c.1 Task + corpus + labels tooling merged in PR #117 (F1 OPEN pending operational corpus evidence); S2c.2a candidate admissibility & credibility (MSR method revision M1) merged in PR #118; S2c.2b-1 quality/statistical protocol merged in PR #119 (`main@3fbfaede6de9aa83697c96d20d95f119cb5b7ef0`); S2c.2b-2 architecture merged in PR #121 (`main@8b6614721ff3d0fe7a77cde66ce6051defcceb74`); protocol/validator/replay implementation merged in PR #122 (`main@7b8913982dc6796a1676de075cf1dc22a7676891`; `docs/qualification/stage2-s2c/s2c-2b2-implementation-record.md`); the real qualification execution plan merged in PR #123 (`main@d0db6efff201a003b9699cde675d8069259f980e`), with Slice A preparation recorded in `docs/qualification/stage2-s2c/real-qualification-execution-record.md` (both MSRs remain PLANNED); the S2c.2 protocol freeze and later S2c slices are OPEN. The acceptance register is authoritative for row state.)*

- **Objective.** Search evidence-backed appearance attributes such as “person, red upper clothing, carrying a backpack” or “white vehicle” and open the exact supporting evidence/source video.
- **Preconditions.** Stage 1 search/evidence mechanics; platform-owned accepted evidence (ADR-006); Development/Production qualification separation (ADR-009); Stage-2 architecture freeze.
- **Domain/data.** Evolve `VisualAttribute` around immutable `VisualAttributeAnalysis` + per-Track outcome + final Observed/Unknown rows. Attributes remain evidence-backed observations, never identity claims.
- **Raw evidence.** Track Evidence Set is produced **inside VisionJob** while decoded frames/boxes exist. Four deterministic candidate roles: Representative, NearView, EarlyDiverse, LateDiverse. JPEG encode in-loop/staging; explicit per-crop and 1 GiB run-level EvidenceCrop bound. Selector changes require a new ProcessingRun/new Track identities under trajectory v1.
- **VisionJob qualification consequence.** Evidence selection changes the qualified raw-processing pipeline: completion schema v3/digest v3, validator/store/sealing evolution, relevant Task-10 CPU re-run and CUDA/E2E rebinding when produced.
- **Component architecture.** ADR-014 component-binding v2 introduces `capabilityBindings[]`, capability-neutral Model Pack manifest v2, Runtime Pack profile v2 decoupled from detector checkpoint identity, capability-scoped qualification and modelPackId/runtimePackId provenance.
- **Worker topology.** Attributes run by default in a **separate process/failure domain** from detector/tracker, initially from the same Runtime Pack. Independent READY/device/provenance/lease/heartbeat. Future separate executable/GPU node must preserve the contract.
- **Evidence read/upload.** Accepted evidence is .NET-owned. Python receives lease-authorised Observation descriptors, fetches through a platform-served lease-scoped API and verifies size/SHA before inference; the prediction artefact is uploaded through a lease-scoped, size-capped endpoint and sealed by the platform. The attribute role has no filesystem dependency on the platform host — no evidence-root mount and no worker staging.
- **Lifecycle.** Capability-specific `VisualAttributeAnalysis`; generic transport envelope only. Shared fencing/hash/claim primitives are extracted where semantics match. Startup model-unavailable leaves work Queued without consuming attempts. Supersession occurs only after successful completion.
- **Predictions.** Raw observation-level outputs + aggregation inputs are a sealed bounded `AttributePredictions` artefact. Relational rows contain final Track semantics only.
- **Semantics.** Per applicable Track/attribute: exactly one `Observed` or `Unknown` final row after completed analysis; Track-level `Unavailable` is separate; `Absent` exists only when explicitly qualified.
- **API/UI.** Attribute-only search may span cameras. v4 HMAC cursor pins the resolved attribute identity/coverage; combined analytics+attribute search pins both and retains analytics camera scope. UI spec governs Unknown, Evidence Set viewer, row density and provenance.
- **Offline/dependency.** Every bound capability has Model Pack, Runtime Pack compatibility, hashes, licence, offline inventory and verification; no first-run network resolution.
- **Qualification.** Annotation agreement, separate validation/frozen-test sets, minimum support, held-camera generalisation, crop-vs-Track aggregation metrics, abstention/non-subject handling, retrieval precision, licence, performance/failure isolation and requalification triggers.
- **Security/privacy.** No demographics/biometrics/face capability; no face-oriented selector; accepted-evidence access remains platform controlled.
- **Slices.** S0 architecture freeze → S1 Evidence Set → S2a component binding v2 → S2b lifecycle with fixture inferencer → S2c real Model Packs → S3 persistence/search → S4 UI → S5 hardening/qualification.
- **Exit gate.** The Stage-2 acceptance register is the only authoritative acceptance list. Exact-head and post-merge verification are required.

### Stage 3 — Expanded operational object / vehicle classes

**State: COMPLETE (closed 2026-10-07 on `main@9ab499bd`) — X1, X2 and X3 PASS; operator-exposed subset `{car}`; Development capability, not Production qualification.** The acceptance register is authoritative: `docs/reviews/2026-10-03-stage3-vehicle-subclass-acceptance.md`.

- **Objective.** Search by "truck" or "motorcycle" rather than "vehicle"; keep every existing "Vehicle" query working.
- **Preconditions (satisfied).** The source decision this stage needed from Stage 2 has been made by **ADR-016 (accepted 2026-10-02)**: subclass is **detector-native**, the qualified detector's own class carried through tracking.
  - Stage 3 does not wait for the rest of Stage 2.
  - No source-precedence rule for a second source is needed until such a source exists (ADR-016 §6).
- **Evaluation first (completed gate).** The S3.2 measurement was the pre-exposure evidence gate (ADR-016 §7): the completed T10 pilot on MAVI-held, publicly sourced video, and the benchmark-driven S3.2d measurements on externally labelled research datasets (ADR-017). H1–H5 are PASS and X1 selected the global `{car}` exposure subset. Public benchmark evidence is Development or reference evidence, never final Production qualification by itself. Its plan is `2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md`; the S3.2b-2 runbook is `docs/qualification/stage3/s3-2b-real-corpus-intake-and-derivation.md`.
  - A Stage-2-style classifier remains a possible **future replacement source**. This roadmap pursues one only if the measurement shows detector-native performance inadequate. Introducing it needs a new ADR on source resolution (ADR-016 §6) and its own Model Pack qualification.
- **Vocabulary.** `mavi-vehicle-subclass-v1` = `car | truck | bus | motorcycle`.
  - **Bicycle is excluded** from both the Phase-1/Stage-3 source-class path and the vocabulary. The pipeline drops `bicycle` before tracking, so no current Vehicle Track includes a bicycle.
  - SUV, van and make/model are not offered.
- **Domain/data (implemented, S3.1, PR #145).** `ObjectClass` (Person/Vehicle) stays the broad grouping. Three immutable, nullable Track fields (`object_subclass`, `object_subclass_vocabulary`, `object_subclass_source`) have database-enforced states. Historical and Person Tracks carry none.
- **Vision/AI (implemented).** No new model. The detector's native class is carried through tracking and resolved once per Vehicle Track by a confidence-weighted vote that may abstain. The thresholds live in pipeline profile `1.3.0-candidate` (schema 1.2, `vehicleSubclass`) and stay provisional until the measurement freezes them.
- **Pipeline placement (implemented).** Completion 3.3 (additive vocabulary/source and per-Track subclass, with its own digest domain). 3.2 is still accepted and replayed.
- **Measurement tooling (implemented).**
  - S3.2a T1–T6: export, evaluator, sampler, labelling, freeze/adjudication, runner (PRs #146–#148).
  - S3.2b-1 T7/T8 and fixture-only T9 tooling (PRs #149–#150).
  - S3.2b-2 real corpus intake and derivation, complete: every E row is PASS, E17 is NOT TRIGGERED (PRs #151–#154).
  - S3.2b-3 Development-host T9 execution, complete: F1–F6 PASS (T9 attempt 2, 2026-10-04; 8 of 8 pool members).
  - S3.2c pilot (T10), complete: G1–G9 PASS. G6 by an owner-accepted pilot-specific deviation (adjudicator designation recorded after adjudication; substantive controls held). G9: the owner froze `minShare` 0.6 and `minMatchedDetections` 3 as the benchmark baseline, with no optimality claim; any change is a separately versioned tuning experiment needing its own benchmark evidence. A bounded real-domain Development cross-check of the full MAVI, blind-label, adjudication and measurement path; 120 Tracks, with evaluable support car 103, bus 7, truck 5, motorcycle 0 against a floor of 30.
  - **S3.2d complete: benchmark-driven evaluation (ADR-017).** H1–H5 are PASS; MAVI did not scale Stage-3 evaluation primarily through manual annotation. Established labelled tracking benchmarks (per-frame boxes, track identities, vehicle classes) are the preferred next evidence source, with exact and partial taxonomies both admitted through explicit per-class mappings.
    - S3.2d-1: capability-neutral benchmark framework and tooling, plan first (dataset release → adapter → shared benchmark envelope plus capability-specific ground truth → MAVI execution → capability-specific association → capability evaluator → result; the envelope owns identity, release, split, provenance and admissibility, mappings, exposure, execution identity and reproducibility, each capability owns only its smallest truth and association contract, with no universal ground-truth schema; vehicle subclass is the first evaluator; no dataset hard-coded): dataset descriptor and adapter contract; native-label mapping contract (`exact`/`subset`/`unsupported` with reasons); ground-truth Track representation; deterministic, prediction-independent GT↔MAVI Track association (frame and time overlap, IoU, temporal continuity, one-to-one constraints, support and purity); ambiguity and unmatched reporting in both directions; dataset and result provenance; benchmark split identity; known-exposure metadata; deterministic tests. New contracts need their schemas and examples under `contracts/`.
    - S3.2d-2: primary benchmark measurement. Prefer a benchmark whose native labels exactly cover the capability where reasonably available; otherwise the strongest benchmark or combination with explicit `exact`/`subset`/`unsupported` mappings. Lack of one perfect taxonomy does not block evidence-supported class subsets. Chosen after the survey in `stage3-benchmark-capability-matrix.md` verifies the material fields (BDD100K box tracking is the leading candidate, not a decision and not a prerequisite).
    - S3.2d-3: domain-diversity benchmarks with partial or alternate taxonomies (fixed-camera traffic, aerial, adverse conditions); no benchmark must support every class.
    - S3.2d-4: evidence-backed capability decision per class and evidence domain: benchmark-supported, Development-only, insufficiently supported, or deferred. The capability does not wait for its weakest class.
    - Register rows: H2 (S3.2d-1), H3 (S3.2d-2), H4 (S3.2d-3, may be NOT TRIGGERED on a technical rationale), H5 (S3.2d-4). X1 requires all of them with G8 and G9. They are evidence outcomes, not PR boundaries or approval stages; one implementation or benchmark run may satisfy several. Development benchmarking follows operating principle 6a (lightest adequate process; no Production qualification ceremony).
  - **Evaluation semantics for benchmarks** (plan §14 amendment): report GT tracks associated to MAVI Tracks, GT tracks MAVI never produced, MAVI Tracks without GT, ambiguous associations rejected, class confusion on valid associations, association coverage, MAVI resolved/undetermined coverage, per-class support, and dataset and domain identity. End-to-end detection and tracking performance and Track-conditional subclass classification are reported separately, never conflated.
- **API/UI (PR #179, merged as `9ab499bd`; X2/X3 PASS).** `objectSubclass=car` is the only operator-facing subclass predicate; search and detail show `Vehicle · Car` only for release-profile Tracks allowed by X1. Truck, bus, motorcycle and any A2-profile `car` stay hidden; every pre-existing Vehicle search keeps its population (X3). **Stage 3.5 UI/UX Professionalisation is complete 2026-10-12** (PR #209 + closure PR #210, final `main@1468286d`): C1–C5 PASS; §34.2 has expired; §34 items 1–17 are the normal frontend baseline; **Stage 4 (ANPR/OCR) is unblocked**. It touched no API contract, domain model, worker, binding or qualification decision.
- **Persistence.** Additive columns and constraints, already merged; no migration of historical rows.
- **Offline/dependency.** No new model or runtime dependency for the detector-native route.
- **Qualification.**
  - Checkpoint, model manifest, Model Pack id, runtime profile and runtime packs are unchanged.
  - The pipeline profile is a new version, so the qualification record's policies were re-derived. The record remains `pending`, and existing qualification evidence does not cover subclass quality.
  - Stage-3 work is Development capability and evidence, not Production qualification.
  - A future replacement source (classifier or new checkpoint) would need its own Model Pack qualification.
- **Acceptance.** Subclass search works, and every pre-existing Vehicle search returns the same Tracks (register X rows).
- **Non-goals.** Vehicle make/model; pedestrian subtypes; bicycle as a Vehicle subclass.
- **Exit gate.** The Stage-3 acceptance register is the only authoritative acceptance list. Stage 3 is complete only when its measurement, exposure and compatibility rows are PASS; completing an intermediate slice such as S3.2b-2 or the T10 pilot does not complete Stage 3.
- **Not changed by the pivot.** The detector (RTMDet-m COCO), ADR-016's detector-native source, `mavi-vehicle-subclass-v1`, `minShare` 0.6, `minMatchedDetections` 3, profile `1.3.0-candidate`, stored Track subclass values and X1's car-only exposure decision. PR #179 adds only that approved release-profile `car` API/search/UI exposure and does not change Production qualification. Benchmark evidence may later justify a replacement source through its own ADR (ADR-016 §6). Public benchmark results are Development or reference evidence (ADR-017 §8–§9), never Production qualification.

### Stage 4 — ANPR / OCR

- **Objective.** "Show vehicles whose plate contains `KA01`" with every supporting plate crop, OCR reading/confidence and source frame/time.
- **Preconditions.** Vehicle Tracks and the sealed Track Evidence Set (present); capability-binding v2 (present). Stage 2/3 semantics are useful but not hard dependencies.
- **Evidence-first entry decision.** Before changing VisionJob, measure plate pixel size/clarity on real current `Representative`/`NearView`/`EarlyDiverse`/`LateDiverse` vehicle evidence. If the existing set supports useful ANPR, consume it unchanged. Only a demonstrated resolution/coverage gap may justify a later plate-specific source-evidence change.
- **Flow.** `Vehicle Track → selected accepted Track evidence → plate detector → plate crop as sealed derived evidence → one or more OCR observations → immutable raw text/confidence → versioned normalisation → per-Track searchable plate summary`.
- **Domain/data.** `PlateObservation` binds Track, source Observation/frame/offset, plate box, plate crop artefact, plate-detector confidence, raw OCR text, OCR confidence, normalised text, normalisation version and detector/OCR execution provenance. A Track retains multiple observations; the summary is a search acceleration, not replacement evidence.
- **Vision/AI selection.** **Pretrained first.** Run a Model Selection Event over credible pretrained plate detectors and OCR recognisers/compositions. Technical ranking is driven primarily by end-to-end Track-level plate retrieval/recognition on representative surveillance evidence; detector mAP and OCR CER are diagnostic layers. Fine-tuning/training is Plan B, triggered only by a demonstrated gap. Framework reuse is an engineering consideration, not an accuracy entitlement.
- **Pipeline placement.** Default to an independently startable `plates` post-Track role reading lease-scoped hash-verified accepted evidence, so ANPR failure never invalidates an already-completed ProcessingRun and detector/OCR runtimes can evolve independently. Move work into VisionJob only if measurement proves post-Track evidence insufficient and an ADR accepts that consequence.
- **Measurement decomposition.** (A) detector quality against plate boxes; (B) OCR on ground-truth crops; (C) OCR on detected crops; (D) end-to-end Track-level partial/full plate search. This separates missed plates from OCR errors and selects the composition on the product outcome.
- **API/UI.** `plateText` supports normalised prefix/partial matching; Search/Review show all observations and crops. Raw OCR is never overwritten by grammar-assisted interpretation. UI never states one unqualified "the plate is X" fact when readings conflict.
- **Persistence/indexing.** New plate-observation/summary tables; trigram/prefix strategy chosen after measured query patterns. Existing Tracks gain ANPR through post-Track analysis where source evidence is sufficient rather than mandatory video reprocessing.
- **Offline/dependency.** Plate detector and OCR runtime/model/language assets are explicit capability Model/Runtime Packs with hashes, locks, licence/provenance and disconnected installation. Different frameworks are permitted when the selected composition warrants them.
- **Qualification.** Capability-scoped detector/OCR/composition evidence, regional plate corpus where required, reproducible normalisation, disconnected pack verification and applicable runtime/boundary gates. No Production inheritance.
- **Performance.** Bound evidence observations evaluated per Track; measure throughput, CPU/GPU memory and projected system-scale scheduling rather than requiring every model resident simultaneously.
- **Security/privacy.** Plate text is a potentially identifying cue; retention/access rules are explicit. Until the relevant Production/audit profile is qualified, plate search remains Development capability.
- **Acceptance.** Partial plate search returns the correct Tracks with evidence; conflicting readings remain inspectable; raw/normalised text and provenance are reproducible.
- **Non-goals.** Registration-database lookup; jurisdiction/owner inference; training merely to own a model; treating one OCR reading as truth.
- **Exit gate.** Model Selection Record closed; end-to-end ANPR evaluation frozen; disconnected packs verified; exact-head CI and applicable qualification gates green.

### Stage 5 — Visual Similarity / query-by-example

- **Objective.** From any Track, "Find Similar" returns ranked similarity candidates across cameras/time with side-by-side evidence and a score. Candidates, not identities.
- **Preconditions.** pgvector (present); Track Evidence Set (present); capability-binding v2.
- **Domain/data.** `TrackEmbedding` (Track, source observation, model/version, dimension, vector, created). Multiple embedding model versions may coexist with explicit identity.
- **Vision/AI.** Benchmark credible pretrained person/vehicle appearance-embedding candidates under the Model Selection Record method; select on retrieval quality plus measured resource profile.
- **Pipeline placement.** Prefer an independently leased embedding role over sealed crops so re-embedding does not require video reprocessing and model changes do not disturb VisionJob.
- **API/UI.** Similarity query by Track id/evidence with camera/time constraints and `k`; `Find Similar` in inspector/Review; results labelled "Similarity candidates".
- **Persistence.** First general Track vector column/table; HNSW vs IVFFlat chosen after measuring expected volume/recall/latency; embedding version bound to every result.
- **Offline/dependency.** Embedding Model Pack/runtime as selected; pgvector already exists.
- **Qualification.** Retrieval metrics on a labelled corpus; index recall/latency; offline pack verification.
- **Security/privacy.** Person appearance embeddings are sensitive derived data; no export/cross-installation sharing by default; retention/access stated.
- **Acceptance.** Find Similar returns ranked candidates with evidence/scores and no automatic `EntityId` write.
- **Non-goals.** Face identity; automatic grouping.
- **Exit gate.** Retrieval evaluation frozen; index decision recorded; CI green.

### Stage 5A — Face Intelligence

- **Objective.** Support "Has this face appeared here before?", "show all candidate appearances", and "is this a candidate match to an enrolled authorised person?" with source evidence, score and time/camera context.
- **Preconditions.** Stage 5 vector/retrieval infrastructure stable; Person Tracks with accepted evidence; camera-local time authority. A usable face is optional — no face evidence means Unknown, not "not the same person".
- **Domain/data.** `FaceObservation` binds Person Track/source Observation, face box/crop, landmarks/quality where supplied, detector provenance and timestamp. `FaceEmbedding` binds observation, embedding model/version/dimension/vector. `EnrolledPerson` stores operator-managed identity/display metadata and one or more reference-image/embedding records; an authorisation state is explicit metadata, not inferred from the face.
- **Vision/AI.** Separate specialist face-detection/quality and face-embedding capabilities selected by measured face-search/verification performance. One framework/model family is not required. Pretrained candidates first; fine-tune only for a demonstrated operational gap.
- **Pipeline placement.** Independent post-Track face role over accepted Person evidence. Face failure never invalidates the Track or ProcessingRun.
- **API/UI.** `Find this face` from selected evidence or a transient query image; candidate appearances across camera/time; enrolled-person gallery search/match; every match shows observed/reference evidence and score/threshold context. Query images are transient unless deliberately enrolled.
- **Persistence.** Face observations/embeddings plus enrolled-person/reference records; pgvector index decision measured at expected scale. No face crop/embedding is silently copied into a general Track identity field.
- **Identity semantics.** Similarity to an enrolled authorised person is a **candidate known-person match**, not a silent hard identity assertion. Confirmed durable identity/Entity linkage remains attributable/audited. Gallery enrolment/update is itself an attributable mutation and may pull forward the minimum identity/audit plumbing from Stage 10.
- **Qualification.** Detection coverage/quality, retrieval/verification ROC/precision-recall and false-match/false-non-match behaviour on representative conditions; threshold calibration is model/version/domain bound. Measure day/night, pose, blur, occlusion, face size and camera-domain slices where evidence supports them.
- **Security/privacy.** Face images/embeddings are biometric-sensitive. Access, retention, deletion, gallery mutation and export policy are explicit before exposure.
- **Acceptance.** Query-by-face retrieves candidate Person Tracks with evidence; previous appearances are navigable; enrolled-person candidate matching is explainable; Unknown is preserved when no usable face exists.
- **Non-goals.** Hidden mass identity assignment; automatic hard merge; claiming identity from a single score without the qualified decision semantics.
- **Exit gate.** Face model-selection/evaluation records frozen; gallery/query contracts tested; privacy/access controls for the Development capability present; exact-head CI green.

### Stage 6 — Person / Vehicle ReID and candidate Entity association

- **Objective.** Propose that Tracks across cameras/time are candidates for the same real-world subject, with the evidence factors shown for operator review.
- **Preconditions.** Stage 5 stable; camera/time authority present. Stage 5A is an additional Person cue where available, not a hard dependency for Vehicle ReID or for Person Tracks without usable faces. Confirmation requires attributable identity/audit.
- **Domain/data.** `EntityCandidate` carries pair/cluster, score, individual plausibility/evidence factors, algorithm version and state; `Entity` activates only on an attributable confirmation; `Track.EntityId` is written only by that decision.
- **Vision/AI.** Appearance similarity plus deterministic time/camera plausibility; Person candidates may include face similarity and attributes as independently visible factors. No opaque single score may erase contradictory cues.
- **Pipeline placement.** Application/background association over persisted evidence; no raw-video worker requirement.
- **API/UI.** Candidate list and side-by-side evidence; confirm/dismiss attributable; explanation identifies which cues contributed.
- **Persistence.** Candidate tables, Entity activation and camera-adjacency/configuration revisions.
- **Qualification.** Association precision/recall and false-association rate on labelled multi-camera evidence; face-assisted and face-absent slices reported separately where used.
- **Acceptance.** Candidates shown with evidence; no automatic merge; confirmation writes `EntityId` with audit.
- **Non-goals.** Automatic hard merges; identity assertion beyond the evidence/confirmation policy.
- **Exit gate.** Corpus evaluation frozen; ReID/Entity semantics ADR accepted.

### Stage 7 — Event / Behaviour Analytics

- **Objective.** Measurable events over persisted facts: intrusion, loitering, wrong-way, stopped vehicle, repeated visit, crowd build-up, dispersal, group movement and co-occurrence.
- **Preconditions.** Stage 1 hard; later attributes/Entity facts only for rules that explicitly require them.
- **Domain/data.** Versioned rule definitions and `AnalyticEvent` records bound to Tracks/Entities, geometry revisions, rule id/version and time.
- **Vision/AI.** Deterministic rules; no model.
- **Pipeline placement.** Application/background analytics after prerequisite facts exist.
- **API/UI.** Event search/timeline and evidence explanation reusing overlays.
- **Persistence.** Event table with rule/revision/input binding and deterministic recomputation semantics.
- **Qualification.** Deterministic fixtures per rule.
- **Acceptance.** Every exposed event is reproducible and explainable.
- **Non-goals.** Intent inference or generic learned "anomaly" claims without measurable semantics.
- **Exit gate.** Rule catalogue frozen for the increment; fixtures green.

### Stage 8 — Structured Intelligence Query + Aggregations

- **Objective.** Provide one deterministic query contract over capabilities from prior stages that can both retrieve evidence and answer bounded analytical questions.
- **Preconditions.** Predicates/events from preceding stages.
- **Query algebra.** Whitelisted predicates plus typed operations: `find`, `count`, `countDistinct`, `groupBy`, `timeBucket`, `first`, `last`, `top` and bounded `compare`. Operations have typed subjects/units; there is no arbitrary SQL or expression language.
- **Cardinality semantics.** An event occurrence, Track and Entity are different units. Before confirmed Entity semantics support a unique-person claim, "how many people" is rendered truthfully as Person Tracks and, where relevant, crossing/event counts.
- **Domain/data.** Versioned structured-query document + optional saved-search definition; query fingerprint/canonical form; typed result envelope that records answer unit, aggregation, scope and evidence/result references. No new analytical facts.
- **Pipeline placement.** Application query service/repository over persisted facts and indexes.
- **API/UI.** **Advanced Search** is the precise builder: composed filters, aggregations, canonical URL/query state where shareable, result explanation, pagination/drill-through and evidence links.
- **Persistence.** Index review driven by measured query patterns; saved queries optional.
- **Qualification.** Query-contract/golden tests; aggregation/cardinality fixtures; latency budget on the Development corpus.
- **Non-goals.** Natural language; arbitrary SQL; LLM execution.
- **Exit gate.** Query/aggregation contract frozen and tested; representative latency budget met.

### Stage 9 — Ask MAVI / Natural-Language Intelligence Query

- **Objective.** An operator asks ordinary questions such as "How many Person Tracks crossed Main Gate between 0800 and 1400?" or "Show vehicles whose plate contains KA01"; MAVI returns a concise factual answer, chart/table where useful, and links to the underlying evidence.
- **Preconditions.** Stage 8 structured query/aggregation contract; an offline-capable language model that meets the translation corpus on qualified Development hardware.
- **Architecture.** `operator utterance → local language model/function-call translation → Stage-8 schema validation/whitelist → deterministic query execution → typed result envelope → deterministic/templated answer rendering`. The language model interprets; MAVI computes.
- **Conversation.** Follow-up questions are explicit transformations of the prior structured query/result scope, not hidden conversational facts. The current interpreted query remains inspectable.
- **Vision/AI.** Benchmark compact local function-calling/structured-output models first; choose the smallest model that satisfies semantic translation/refusal requirements with acceptable latency. Model brand/size is not frozen in the roadmap.
- **API/UI.** Separate top-level **Ask MAVI** Investigation surface with a simple question field, answer summary, optional chart/table, evidence/drill-through actions and a compact **Interpreted as** disclosure. Advanced Search remains available for power users and reproducibility.
- **Grounding rule.** The model never executes SQL, never directly scans media, never invents counts/entities/plate/face facts, and never produces an answer unsupported by the typed deterministic result. Unsupported or ambiguous requests are refused or clarified.
- **Offline/dependency.** Language Model/Runtime Pack, fully local; no network/telemetry. Prompts may contain the operator question and authorised MAVI vocabulary/reference labels required for translation; raw media/embeddings never leave the host.
- **Qualification.** Frozen corpus of representative operator questions and follow-ups; exact/semantic translation accuracy, ambiguity/refusal behaviour, adversarial out-of-contract requests, and answer-grounding tests proving displayed facts equal deterministic result envelopes.
- **Security/privacy.** Same access checks as the underlying query; Ask MAVI grants no new data authority.
- **Non-goals.** LLM-generated analytical facts independent of query results; unrestricted database access; free-form footage summarisation; replacing specialist vision models.
- **Exit gate.** Translation/grounding corpus passes; out-of-contract predicates cannot execute; offline runtime verified; exact-head CI green.
### Stage 10 — Audited Human Review / Cases

- **Objective.** Attributable confirm/reject of Tracks, Entity confirmation (stage 6), append-only decision history, and cases collecting Tracks and notes. Design retained in `2026-09-20-audited-review-and-cases-plan.md`.
- **Preconditions.** Windows-integrated identity (ADR-010 when activated); semantic richness from stages 1–7 that makes review worth doing.
- **Domain/data.** Per the deferred plan; scene-configuration and rule mutations from stages 1 and 7 also become attributable here.
- **Offline/dependency.** In-box ASP.NET Core Negotiate; no package expected.
- **Security/privacy.** Operator identity, server time authority, append-only audit.
- **Exit gate.** Per the deferred plan's acceptance.

### Stage 11 — Live RTSP / VMS integration

- **Objective.** Continuous processing of live camera streams with the same intelligence as recorded video.
- **Preconditions.** Stages 1–8 mature on recorded video; a streaming-architecture ADR.
- **Changes.** New ingestion plane (RTSP/VMS clients, reconnect, buffering, backpressure), continuous jobs instead of run-per-video, rolling storage and retention, live time authority (ADR-004 extended), stream health, GPU scheduling and load shedding, long-running recovery. This is a platform phase, not a feature slice.
- **Vision/AI.** Streaming infrastructure; models unchanged.
- **Offline/dependency.** FFmpeg already present for RTSP; VMS SDKs are new native dependencies.
- **Qualification.** New Production profiles or profile revisions; nothing from recorded-video qualification carries over automatically.
- **Non-goals now.** Everything in this stage.
- **Exit gate.** Not defined until the ADR exists.

## 3. Qualification-preservation matrix

Impact classes: **none**, **additive** (new artefacts, existing evidence untouched), **requalification likely** (an existing qualification record must be re-derived or re-run), **new model/runtime qualification required**, **Production evidence potentially invalidated** (Task 18 evidence for a frozen candidate would not describe the new candidate).

| Stage | Model Pack (RTMDet) | Vision Runtime Pack (CPU) | CUDA runtime (C4 Development) | CPU baseline lock | Search API contract | Database schema | Frontend | Offline Binary Kit | Production qualification evidence |
|---|---|---|---|---|---|---|---|---|---|
| 1 Analytics | none | none | none (worker untouched; C6 evidence, once produced, is bound to the pipeline that ran and is unaffected by .NET-side analytics) | none | additive (new whitelisted predicates; fingerprint extended; existing queries unchanged) | additive (new tables) | additive | none | none for the frozen candidate's worker/runtime; the API/UI candidate changes, so Task 18's application-artefact identity changes if re-frozen |
| 2 Attributes | new model qualification (attribute Model Pack) | requalification likely if new Python packages enter the lock; none if the model runs on the existing graph | same as CPU pack for the CUDA lock; C6/C7 E2E evidence must be re-executed for the changed pipeline | requalification likely (lock change) or none | additive | additive (`visual_attributes` populated; possible summary table) | additive | additive (new model in the kit) | potentially invalidated (worker pipeline change) |
| 3 Classes | detector-native route (ADR-016): checkpoint, manifest and Model Pack unchanged; pipeline profile `1.3.0-candidate` re-derives the qualification record's policies (record `pending`); a future replacement source would be a new model qualification | none | none for runtime; pipeline evidence re-executed | none | additive (PR #179 X2/X3 PASS; merged `9ab499bd`, Stage 3 closed) | additive (subclass columns) | additive (PR #179 X2/X3 PASS; merged `9ab499bd`, Stage 3 closed) | none | potentially invalidated (pipeline output change) |
| 4 ANPR/OCR | new capability qualification (plate detector + OCR composition) | none if separate `plates` runtime family; new runtime qualification for any added family | as applicable to selected runtime | none for existing Vision lock when post-Track; requalification only if VisionJob changes | additive | additive (plate observations/summary) | additive | additive (plate/OCR Model/Runtime Packs) | none for frozen Vision worker if post-Track; application artefact changes if re-frozen |
| 5 Similarity | new model qualification (appearance embedding) | none if separate embedding role; otherwise requalification likely | as applicable | none when separate | additive | additive (vector table/index) | additive | additive | none when separate post-Track role |
| **5A Face Intelligence** | new qualifications (face detector/quality + face embedding as selected) | separate face runtime family preferred; qualify it independently | as applicable | none | additive | additive (face observations/embeddings/enrolled gallery) | additive | additive | none for existing Vision worker; biometric access/audit policy is new capability evidence |
| 6 ReID | none unless association uses a new learned model | none | none | none | additive | additive | additive | none | none |
| 7 Events | none | none | none | none | additive | additive | additive | none | none |
| 8 Structured intelligence query | none | none | none | none | query-contract tests requalified for consolidated predicates/aggregations | none or additive (indexes/saved queries) | additive | none | none |
| 9 Ask MAVI | new model qualification (language/function-calling model) | new separate language runtime qualification | as applicable | none | none to underlying deterministic semantics; additive Ask-MAVI endpoint | none | additive | additive | none |
| 10 Review/cases | none | none | none | none | additive | additive (audit, decisions, cases) | additive | none | none |
| 11 Live | none | requalification likely (continuous-job worker behaviour) | requalification likely | requalification likely | additive | additive | additive | additive (VMS SDKs) | new Production profiles; existing evidence does not carry over |

Reading the matrix: stages 1, 6, 7, 8, 9 and 10 can leave every qualified Vision artefact untouched when implemented through their declared separate/application-side boundaries. Stages 4, 5 and 5A are deliberately biased toward independent post-Track roles so specialist model/runtime changes do not reopen the base detector/tracker path. Stages 2, 3 and 11, and any later decision to move Stage-4/5/5A work into VisionJob, can change that path and therefore re-open the corresponding evidence; they should each be preceded by a decision on whether the work belongs in the detector/tracker worker or in a separate worker over sealed evidence, precisely to contain that re-opening.

## 4. Roadmap risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Geometry semantics instability (boundary rules, debounce) changing after facts are persisted | Medium | High: historical facts silently mean something else | Freeze rules in stage-1 §K; algorithm version on every fact; golden fixtures pinned; any rule change is a new algorithm version and a visible `Stale` state |
| Analytics lifecycle complexity (states, retries, revisions) | Medium | Medium | Minimal state model; one analysis unit per (run, revision, version); reuse existing patterns (visibility sequence, advisory locks, attempt counting) rather than inventing new control-plane concepts |
| Schema sprawl across stages (one table per fact family per stage) | Medium | Medium | Typed tables for searchable facts only; on-demand aggregates; a review of query patterns before each stage's indexes |
| Model proliferation (attributes, plates, embeddings, language) each with packs and qualification | High | High | Prefer models on the existing Torch/MMCV graph; one capability binding per model under ADR-014 (a stage may bind several); separate roles/processes over lease-scoped sealed evidence per ADR-013; the dependency contract per PR |
| Dependency growth (OCR engine, vector provider, language runtime) | Medium | High (offline discipline) | Justify against existing capability; offline pack and licence in the same PR; `verify_repo` fail-closed |
| pgvector scale (index build, recall, memory) | Medium | Medium | Measure at expected Track volume before choosing the index; bound `k` and time windows |
| False ReID associations presented as fact | Medium | High (operational trust) | Candidates only; scores and plausibility shown; confirmation attributable; precision metric as the exit gate |
| OCR uncertainty treated as truth | High | High | Multiple observations, confidences, normalised candidates, partial search; UI never shows one plate as "the" plate |
| Qualification explosion (every stage re-runs everything) | Medium | High | The matrix above; worker-boundary decision per model stage; separate workers for embeddings/plates when it avoids re-opening detector evidence |
| Live-stream operational complexity pulled forward | Low | High | Stage 11 gated behind its ADR and stages 1–8 maturity |
| Trajectory v1 centre points limiting ground-contact geometry | Medium | Medium | Stage 1 states the reference point honestly; trajectory v2 planned as a worker-side additive format change with its own qualification |

## 5. Decisions that need ADRs

| Decision | ADR? | When |
|---|---|---|
| Analytics lifecycle: separate application-side post-processing stage with an analysis unit bound to (run, scene revision, algorithm version); search readiness semantics | **Accepted as ADR-011** (ADR-010 stays reserved by the deferred review/cases plan for operator identity) | Stage 1 Slice 0 — done |
| Scene-configuration revision semantics (whole-configuration revisions, stable ids, activation, empty revision disables analytics) | Accepted in ADR-011 | Stage 1 Slice 0 — done; implemented in Slice 1; operator editor in Slice 2 |
| Worker boundary for model-based stages (in detector/tracker worker vs separate worker over sealed evidence) | Yes, one ADR when stage 2 begins; stages 4 and 5 reference it | Stage 2 entry |
| Embedding storage and index (pgvector column, index type, model versioning) | Yes | Stage 5 entry |
| ReID / Entity semantics (candidate states, confirmation, `EntityId` write rules) | Yes | Stage 6 entry |
| Operator identity, authorization and audit | Yes (ADR-010 per the deferred plan's Slice 0) | Stage 10 entry, or earlier if a mutation needs attribution |
| Live ingestion architecture | Yes | Stage 11 entry |
| Natural-language translation model and runtime | Probably a Model Pack qualification record rather than an ADR, unless a new runtime variant is introduced | Stage 9 entry |

No ADR is written by this planning task.

## 6. Cross-stage engineering rules

1. Every dependency-bearing stage updates `config/dependencies/offline-dependency-policy-v1.json`, packaging, verification, licences and runbooks in the same PR (AGENTS.md; `dependency-and-offline-packaging-policy.md` "Definition of done").
2. Every model-based capability ships as a manifest-verified pack with version, hash, runtime compatibility, offline location and qualification evidence, and states CPU and CUDA runtime applicability separately.
3. A stage that changes the worker's completion payload extends `VisionJobCompleteContracts` additively, updates `VisionResultValidator` and its tests, and re-runs the Task 10 matrices; it never reuses a field for a new meaning.
4. Derived data (analytics, attributes, plates, embeddings, candidates, events) is bound to the identity of what produced it (Track, run, configuration revision, model or algorithm version) and is never silently reinterpreted.
5. Search predicates are whitelisted, fingerprinted and snapshot-stable; "not yet computed" is never presented as "no matches".
6. Production qualification (Task 18) runs in parallel; a merged Development capability is not Production-qualified, and Development CUDA evidence never satisfies P1/P2 (ADR-009).
