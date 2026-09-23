# MAVI Capability Implementation Roadmap

**Status:** Authoritative implementation-level roadmap. `capability-roadmap.md` answers *what we build next*; this document answers *how the stages depend on one another, what each changes technically, and what must be true before advancing*.  
**Baseline:** `main@2717918761fb35e4845b6887772ebdd5c7c6edf8` (Scene Analytics Slice 6 / PR #68 merged; Slice-7 planning rebaseline).  
**Written:** 2026-09-20. Planning only; no feature code, migration, dependency or runtime change accompanies this document.  
**Companion:** `2026-09-20-spatial-temporal-track-analytics.md` remains the parent implementation-grade plan for stage 1; `2026-09-22-scene-analytics-s7-hardening-acceptance.md` is the Slice-7 closure plan written against merged Slice 6 / PR #68. `docs/architecture/ui-ux-design-specification.md` is the adopted UI/UX specification. **UI-1 through UI-5 and Scene Analytics Slices 0–6 are merged. Slice 7 hardening/performance/acceptance is the final Stage-1 unit, adds no new capability, and is IN PROGRESS — Stage 1 is not closed.** PostgreSQL 18 qualification, real-worker Development acceptance, resilience/concurrency/C1/accessibility/visual-QA, the aggregate-materialisation disposition, and the Development-corpus unit record have passed. The carried aggregate P2 is closed as **RETAIN** within the qualified 10⁵-fact envelope. Runtime identity, Search → Investigation and PostgreSQL restart/reconnect have passed. What remains is exit-gate item 14 — the scripted worker path run while disconnected (runbook C + D.2, one operator session) — plus exact-head CI on the final head, itemised in `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md`. Task 18 (`2026-09-18-task-18-phase1-production-qualification-rebaseline.md`) remains a separate, parallel qualification stream and is not a stage here.

## 0. The baseline this roadmap builds on

Facts below were read from the code at the baseline SHA, not from earlier plans.

| Area | Present state | Consequence for the roadmap |
|---|---|---|
| Layering | `Mavi.Domain` (sealed aggregates, `Create` factories, intent methods, `DomainValidationException(code)`), `Mavi.Application` (plain services + repository ports; modules `Cameras`, `Evidence`, `Intelligence`, `Media` implemented; `Audit`, `Entities`, `Identity`, `Investigations`, `Missions`, `SystemHealth` reserved with README only), `Mavi.Infrastructure` (EF Core, PostgreSQL 18 + pgvector extension enabled, no vector column yet), `Mavi.Api` (minimal APIs, RFC 7807 problems with `extensions.code`), `Mavi.Contracts` (typed request/response records, `JsonUnmappedMemberHandling.Disallow`). Project-reference direction is pinned by `ArchitectureBoundaryTests`. | New capabilities land as new Application modules with Domain aggregates, Infrastructure repositories and Contracts records; no MediatR, no generated OpenAPI. |
| Track model | `Track` (`ProcessingRunId`, `VideoAssetId`, `ObjectClass` Person/Vehicle, offsets and UTC timestamps, counts, confidences, `RepresentativeObservationId`, `TrajectoryArtifactId`, `ReviewStatus` display-only, `EntityId` nullable never set). `Observation` rows exist for four types only (`TrackStart`, `Representative`, `BestQuality`, `TrackEnd`) with a normalised bounding box. `VisualAttribute` and `Entity` tables exist, unpopulated. | Per-frame boxes are **not** in the database. |
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
| 2 Attributes ↔ 3 Classes | Soft, overlapping | Vehicle subclass is both a class-vocabulary question (detector) and an attribute question (classifier); the roadmap allows either ordering, and the stage-3 evaluation decides which mechanism produces subclass. |
| 4 ANPR ← 3 Classes | Soft | Plate detection benefits from knowing a Track is a car/truck but works on the broad `Vehicle` class. |
| 4 ANPR ↔ 5/6 | Independent | ANPR may land before or after similarity. |
| 1 Analytics ← trajectory v2 (bottom-centre per sample) | Soft | Stage 1 starts on v1 centre points; a worker-side trajectory v2 improves ground-contact geometry later without blocking stage 1 (see the stage-1 plan §J). |
| Task 18 | Independent | Qualification of the frozen Production candidate; proceeds in parallel and is never gated by a roadmap stage. |
| Frontend polish, historical-runs listing | Independent | May be scheduled between stages without changing the sequence. |
| Stage 1 slice 3 ← UI Foundation UI-2 | Hard | **Satisfied.** The UI Foundation programme (UI-1 → UI-5, §33 of `docs/architecture/ui-ux-design-specification.md`, accepted by ADR-012) is inserted after stage-1 slice 2. UI-2 merged with green post-merge `main`, which lifted the gate, and slice 3 has since merged. Backend/domain work now runs in parallel with UI-4/UI-5 where it introduces no frontend surface. |
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
- **Acceptance / non-goals / slices / exit gate.** See the stage-1 parent plan and the current Slice-7 hardening/performance/acceptance plan. Slices 0–6 and UI-1–UI-5 are merged; Slice 7 hardening/performance/acceptance is **in progress and has not closed Stage 1**. PostgreSQL 18 qualification passed at reachable SHA `5f516662…`, real-worker acceptance with restart persistence passed on the Development machine, and cancellation/failure at volume, concurrency race probes, the C1 explanation/heatmap/UI legs and accessibility/visual QA have passed; the aggregate-materialisation P2 is closed as RETAIN and the Development-corpus unit record has passed; the remaining exit-gate item — 14, the scripted worker path run while disconnected — and final exact-head CI are itemised in `docs/reviews/2026-09-22-scene-analytics-stage1-acceptance.md`. Stage exit: acceptance criteria met on the development laptop with the real worker path; analytics-specific evidence recorded; no P1/P2 open; exact-head CI green; ADR-011 remains authoritative.

### Stage 2 — Visual Attributes

- **Objective.** Search "person, red upper clothing, carrying a backpack" or "white SUV" and see the attribute evidence crop with its confidence. Persons: upper-clothing colour, lower-clothing colour, bag/backpack, headwear or helmet where measured reliable. Vehicles: colour, subclass (car, SUV, van, truck, bus, motorcycle).
- **Preconditions.** Stage 1 search-predicate mechanics (whitelist, fingerprint, disclosed filter groups); Model Pack and Runtime Pack qualification machinery (Tasks 10/12, ADR-005, ADR-007).
- **Domain/data.** Populate `VisualAttribute` (already `TrackId`, `ObservationId?`, `AttributeType`, `Value`, `Confidence`, `ModelName`, `ModelVersion`). Fixed vocabularies per attribute type live in a versioned attribute schema in `config/vision/`. Possibly a per-Track attribute summary (best value per type) for search; decide after measuring query shape.
- **Vision/AI.** New model (person attribute classifier; vehicle colour/subclass classifier) running on representative and best-quality crops inside the worker after tracking.
- **Pipeline placement.** Detector/tracker worker, as an additional pipeline step whose output extends the completion contract with an `attributes` collection per Track (bounded, validated by `VisionResultValidator`). Alternative considered: a separate attribute worker reading sealed thumbnails; rejected initially because it duplicates the control plane for little isolation gain, but kept open if attribute models prove heavy.
- **API.** `attribute[type]=value` predicates with minimum confidence; attribute facts in Track detail.
- **UI.** Filter chips per attribute type; attribute badges with confidence and the crop that produced them in the inspector and Review.
- **Persistence.** Rows in `visual_attributes`; index on `(attribute_type, value)` plus Track; historical Tracks lack attributes until reprocessed (policy: not backfilled automatically; "attributes unavailable" is visible).
- **Offline/dependency.** New Model Pack(s) with manifest, hash, licence; possibly new Python packages for the classifier architecture (prefer models runnable on the existing Torch/MMCV graph); no .NET or npm dependency expected.
- **Qualification.** New model qualification (accuracy on a labelled corpus per attribute, thresholds frozen), runtime compatibility on CPU and CUDA packs. Adding a pipeline step changes the worker's qualified behaviour: Task 10 CPU matrices re-run automatically; the CUDA Development evidence (C4) stays valid for the runtime but the **E2E evidence (C6, when produced) is bound to the pipeline that ran** and would need re-execution for the new step.
- **Performance/scaling.** Attribute rows are bounded (types × Tracks); classifier inference adds per-Track latency proportional to crops evaluated.
- **Security/privacy.** Appearance attributes are not identity; the UI must not present them as such.
- **Acceptance.** Import → process → filter by an attribute → open evidence → see the crop and confidence that produced the attribute; attribute absent or below threshold is displayed as unknown, never inferred.
- **Non-goals.** Fine-grained clothing types, age, gender, face attributes, brand/model recognition.
- **Slices.** Attribute schema and contract extension → worker step behind a flag with model pack → persistence and search predicates → UI → qualification corpus and evidence.
- **Exit gate.** Model Pack qualified on CPU (and CUDA Development where available); attribute accuracy report frozen; contract change covered by `WorkerContractV2Tests`-style tests; exact-head CI green.

### Stage 3 — Expanded operational object / vehicle classes

- **Objective.** Search by "truck" or "motorcycle" rather than "vehicle"; keep every existing "Vehicle" query working.
- **Preconditions.** Stage 2's decision on where subclass comes from.
- **Evaluation first.** RTMDet-m COCO already emits `car`, `truck`, `bus`, `motorcycle`, `bicycle`; the qualified pipeline maps them to `Vehicle`. The stage evaluates whether detector classes (cheap, no new model) or the stage-2 classifier (better for SUV/van) yields reliable subclass, and whether `bicycle` belongs in `Vehicle` at all.
- **Domain/data.** Keep `ObjectClass` (Person/Vehicle) as the broad grouping; add `ObjectSubclass` (nullable, versioned vocabulary) on Track. Historical Tracks have null subclass.
- **Vision/AI.** Existing detector output (class vocabulary change) or the stage-2 classifier; no new model if the detector route is chosen.
- **Pipeline placement.** Worker pipeline mapping and completion contract (additive `subclass` field).
- **API/UI.** `objectSubclass` predicate; subclass shown beside class.
- **Persistence.** Additive column and index; no migration of historical rows.
- **Offline/dependency.** None if detector route; otherwise inherits stage 2.
- **Qualification.** A class-vocabulary change alters the qualified runtime profile and model manifest bindings → qualification record re-issued (as PR #49 did for the runtime-profile digest); detector checkpoint change would be a new Model Pack qualification.
- **Acceptance.** Subclass search works; every pre-existing Vehicle search returns the same Tracks.
- **Non-goals.** Vehicle make/model; pedestrian subtypes.
- **Exit gate.** Backward-compatibility test suite green; qualification record re-derived and reviewed.

### Stage 4 — ANPR / OCR

- **Objective.** "Show vehicles whose plate contains `KA01`" with the plate crop, all OCR readings and their confidences, and the frame they came from.
- **Preconditions.** Vehicle Tracks with sealed thumbnails (present); stage 2/3 helpful but not required.
- **Flow.** `Vehicle Track → plate detection on selected frames → plate crop as sealed evidence artefact → one or more OCR observations (raw text, confidence, engine version) → normalised candidate string per observation → searchable plate evidence`.
- **Domain/data.** New `PlateObservation` aggregate (Track, source frame/offset, crop artefact, raw text, normalised text, confidence, engine and model versions) and a per-Track plate summary for search (best normalised candidate(s)). Normalisation rules (character folding, separator removal, regional grammar) are configuration with a version.
- **Vision/AI.** New plate-detection model and an OCR engine (new native runtime); multiple observations per Track by design.
- **Pipeline placement.** Worker pipeline step (needs frames), producing plate crops and OCR observations in the completion payload; or a separate plate worker reading sealed frames if OCR runtime isolation is needed. Decide by runtime footprint.
- **API/UI.** `plateText` predicate with prefix/partial matching on normalised text; plate panel in inspector/Review listing every observation; never a single "the plate is X" assertion.
- **Persistence.** New tables; trigram or prefix index on normalised text after measuring; historical Tracks require reprocessing to gain plates (on demand).
- **Offline/dependency.** OCR engine as a native runtime dependency (lock, licence, offline pack, CPU and CUDA independence stated), plate-detection Model Pack, language/plate-format packs.
- **Qualification.** New model and engine qualification with a plate corpus per region; worker pipeline change re-runs Task 10 matrices; runtime pack changes if the OCR engine is packed with the vision runtime (Task 12 and boundary gate).
- **Performance.** OCR throughput per Track (bound frames evaluated per Track); index growth.
- **Security/privacy.** Plate text is personal data in many jurisdictions: retention and access rules belong with stage 10's audit work; until then plate search is Development capability and the docs say so.
- **Acceptance.** Partial plate search returns Tracks with evidence; conflicting readings are all visible; normalisation is reproducible.
- **Non-goals.** Registration-database lookup; jurisdiction inference; treating one OCR result as truth.
- **Exit gate.** OCR accuracy report frozen; offline pack verified disconnected; exact-head CI green.

### Stage 5 — Visual Similarity / query-by-example

- **Objective.** From any Track, "Find Similar" returns ranked similarity candidates across cameras and time with side-by-side crops and a score. Candidates, not identities.
- **Preconditions.** pgvector (present); sealed representative/best-quality crops (present); Model Pack machinery.
- **Domain/data.** `TrackEmbedding` (Track, crop observation, model name/version, dimension, vector, created). A Track may carry more than one embedding model over time.
- **Vision/AI.** New embedding model (person and vehicle ReID backbones or one general model); embeddings computed in the worker from crops.
- **Pipeline placement.** Worker step writing embeddings into the completion payload (bounded size) or a separate embedding worker over sealed crops; the latter is attractive because embedding models change more often than detectors and re-embedding without reprocessing video is valuable. Decide at stage entry.
- **API/UI.** `GET`-style similarity query by Track id with optional camera/time constraints and `k`; `Find Similar` action in inspector and Review; results labelled "Similarity candidates".
- **Persistence.** First vector column; index type (HNSW vs IVFFlat) chosen after measuring at expected volume; embedding version bound to results.
- **Offline/dependency.** Embedding Model Pack; `pgvector` already enabled; possibly the `pgvector` .NET provider package (declared in the dependency contract).
- **Qualification.** Embedding model qualification (retrieval metrics on a labelled corpus); index recall/latency measured; pipeline change re-runs Task 10 if in-worker.
- **Performance.** Vector count = Tracks × models; ANN index build/maintenance; recall trade-offs.
- **Security/privacy.** Embeddings of persons are biometric-adjacent; no export, no cross-installation sharing; retention policy stated.
- **Acceptance.** Find Similar returns candidates with scores; the operator can reject or ignore; nothing is written to `EntityId`.
- **Non-goals.** Face embeddings; automatic grouping.
- **Exit gate.** Retrieval evaluation frozen; index decision recorded in a migration and ADR note; CI green.

### Stage 6 — Person / Vehicle ReID and candidate Entity association

- **Objective.** Propose that Track A (camera 1, 09:02) and Track B (camera 4, 09:07) are candidates for the same subject, with score, time/camera plausibility and evidence, for a human to confirm or dismiss.
- **Preconditions.** Stage 5 stable; camera registry with time authority (present); for confirmation, stage 10's attributable identity.
- **Domain/data.** `EntityCandidate` (pair or cluster of Tracks, score, plausibility factors, algorithm version, state proposed/dismissed/confirmed); `Entity` activated only on confirmation; `Track.EntityId` written only by a confirmed, attributable decision.
- **Vision/AI.** Cross-camera association over stage-5 embeddings plus deterministic constraints (time gaps, camera adjacency configured by operators).
- **Pipeline placement.** Application-side background stage (like stage-1 analytics) over persisted embeddings; no worker change.
- **API/UI.** Candidate list per Track; candidate review surface; confirmation requires identity (stage 10).
- **Persistence.** Candidate tables; Entity activation; adjacency configuration.
- **Offline/dependency.** None beyond stage 5.
- **Qualification.** Association precision/recall on a labelled multi-camera corpus; false-association rate is the headline metric.
- **Performance.** Candidate generation is k-NN per Track within time windows; keep windows bounded.
- **Security/privacy.** Entity association is the point where MAVI starts asserting persistent identity hypotheses; confirmation is attributable and auditable by construction.
- **Acceptance.** Candidates shown with evidence; no automatic merge; confirming writes `EntityId` with an audit record.
- **Non-goals.** Automatic hard merges; identity beyond pseudonymous Entities.
- **Exit gate.** Corpus evaluation frozen; ADR on ReID/Entity semantics accepted.

### Stage 7 — Event / Behaviour Analytics

- **Objective.** Measurable events over existing facts: intrusion (zone kind `restricted` + entry), loitering (already a stage-1 rule), wrong-way (crossing direction against a configured allowed direction), stopped vehicle in zone, repeated visit (same Entity candidate across Tracks), crowd build-up (occupancy above threshold), dispersal, group movement (co-moving Tracks), co-occurrence (two attribute- or entity-conditioned Tracks in one zone and window).
- **Preconditions.** Stage 1 (hard); stages 2 and 6 for attribute- and entity-conditioned events.
- **Domain/data.** Versioned rule definitions (configuration with revisions, like scene configuration) and `AnalyticEvent` records bound to inputs (Tracks, zone/line ids, revision), rule id/version and time.
- **Vision/AI.** Deterministic rules; no model.
- **Pipeline placement.** Same background analytics stage as stage 1, running after stage-1 facts exist for a run.
- **API/UI.** Event search and timeline; event evidence explanation reusing stage-1 overlays.
- **Persistence.** Event table with rule/revision binding; recomputation semantics identical to stage 1.
- **Offline/dependency.** None.
- **Qualification.** Deterministic fixtures per rule; no model evidence.
- **Acceptance.** Each event type reproducible from fixtures; every event explainable.
- **Non-goals.** "Anomaly detection", intent inference, learned behaviour models.
- **Exit gate.** Rule catalogue frozen for the increment; fixtures green.

### Stage 8 — Richer Structured Search

- **Objective.** Compose predicates from stages 1–7 (AND across families, OR within a family where meaningful), save searches, and keep results explainable and paginated.
- **Preconditions.** Predicates from the preceding stages.
- **Domain/data.** Saved-search definition (optional); no new facts.
- **Pipeline placement.** Application search service and repository.
- **API/UI.** Consolidated query model (still whitelist-validated, still fingerprinted), advanced filter builder, result explanation per predicate.
- **Persistence.** Index review across fact tables driven by measured query patterns.
- **Qualification.** None new; search contract tests.
- **Non-goals.** Free text; natural language.
- **Exit gate.** Query-composition contract frozen and tested; latency budget met on the development corpus.

### Stage 9 — Natural-language Query Translation

- **Objective.** "People near the north gate for more than five minutes yesterday afternoon" becomes a visible, editable stage-8 structured query, then runs through the existing engine.
- **Preconditions.** Stage 8; an offline-capable language model that runs on the qualified hardware.
- **Domain/data.** None; translation is stateless. Camera and zone names are the vocabulary.
- **Vision/AI.** New model (language), never the search engine itself.
- **Pipeline placement.** Application service calling a local model runtime; the translated query is shown before execution and must validate against the whitelist.
- **Offline/dependency.** Heavy model dependency and runtime; qualified as a Model Pack with its own runtime variant; no network.
- **Qualification.** Translation accuracy on a frozen query corpus; refusal behaviour on untranslatable input.
- **Security/privacy.** Prompts contain camera/zone names only; no media leaves the host.
- **Non-goals.** Free-form answers; summarisation of footage.
- **Exit gate.** Corpus evaluation frozen; translator cannot emit a predicate outside the whitelist (tested).

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
| 3 Classes | requalification likely (manifest/vocabulary re-issued) or new model qualification if checkpoint changes | none | none for runtime; pipeline evidence re-executed | none | additive | additive (subclass column) | additive | none or additive | potentially invalidated (pipeline output change) |
| 4 ANPR/OCR | new model qualification (plate detector) | new runtime qualification (OCR engine in the pack) | new runtime qualification for the CUDA pack too | requalification likely | additive | additive | additive | additive (OCR engine, packs) | potentially invalidated |
| 5 Similarity | new model qualification (embedding) | requalification likely (if in-worker) | as CPU pack | requalification likely | additive | additive (first vector column and index) | additive | additive | potentially invalidated if in-worker; none if separate embedding worker on sealed crops |
| 6 ReID | none | none | none | none | additive | additive | additive | none | none |
| 7 Events | none | none | none | none | additive | additive | additive | none | none |
| 8 Structured search | none | none | none | none | requalification likely of the **search contract tests** only (query model consolidation) | none or additive (indexes) | additive | none | none |
| 9 NL translation | new model qualification (language model) | new runtime qualification (language runtime, possibly separate pack) | as applicable | none | none (emits existing predicates) | none | additive | additive | none |
| 10 Review/cases | none | none | none | none | additive | additive (audit, decisions, cases) | additive | none | none |
| 11 Live | none | requalification likely (continuous-job worker behaviour) | requalification likely | requalification likely | additive | additive | additive | additive (VMS SDKs) | new Production profiles; existing evidence does not carry over |

Reading the matrix: stages 1, 6, 7, 8 and 10 leave every qualified vision artefact untouched. Stages 2, 3, 4, 5 (in-worker) and 11 change the worker or its runtime and therefore re-open pipeline-level evidence; they should each be preceded by a decision on whether the work belongs in the detector/tracker worker or in a separate worker over sealed evidence, precisely to contain that re-opening.

## 4. Roadmap risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Geometry semantics instability (boundary rules, debounce) changing after facts are persisted | Medium | High: historical facts silently mean something else | Freeze rules in stage-1 §K; algorithm version on every fact; golden fixtures pinned; any rule change is a new algorithm version and a visible `Stale` state |
| Analytics lifecycle complexity (states, retries, revisions) | Medium | Medium | Minimal state model; one analysis unit per (run, revision, version); reuse existing patterns (visibility sequence, advisory locks, attempt counting) rather than inventing new control-plane concepts |
| Schema sprawl across stages (one table per fact family per stage) | Medium | Medium | Typed tables for searchable facts only; on-demand aggregates; a review of query patterns before each stage's indexes |
| Model proliferation (attributes, plates, embeddings, language) each with packs and qualification | High | High | Prefer models on the existing Torch/MMCV graph; one Model Pack per stage; separate workers over sealed evidence where isolation pays; the dependency contract per PR |
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
