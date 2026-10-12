# Stage 4 — ANPR / OCR: Implementation Plan

**Status:** Implementation plan (planning PR; no code, migration, model or dependency change)
**Date:** 2026-10-12
**Starting baseline:** `main@d98d51c260c736d47c838bf96dd79b7711d9a862` (PR #211, capability-roadmap rebaseline)
**Governing:** capability roadmap and implementation roadmap (Stage 4 section); ADR-006, ADR-009, ADR-013, ADR-014, ADR-015, ADR-017; `docs/architecture/engineering-operating-principles.md` (principles 4–6, 5b); `docs/architecture/dependency-and-offline-packaging-policy.md`; MSR method v1 with revisions M1/M2 (`docs/qualification/model-selection/README.md`); UI/UX specification v2.1.
**Exit gate:** the Stage-4 acceptance register (created by PR-1, rows in §8 below) with every row PASS. Stage 4 closes as **Development capability**; no row claims Production qualification.

Stage 4 delivers one operator outcome: *"Show all vehicles whose number plate contains KA01"* returns the matching Vehicle Tracks. Each result carries every plate reading and its confidence, camera and time context, and evidence the operator can navigate. Uncertain, partial and conflicting readings stay visible as candidates. A reading is never promoted to a registration identity.

This plan does not reopen Stage 3.5, the roadmap or any accepted ADR. Where it refines one, it says so and names the document that records the refinement.

---

## 1. Verified current architecture and reusable components

All facts below were read from `main@d98d51c2`. Paths are repository-relative.

### 1.1 Track Evidence Set (ADR-013 §3–§7)

| Fact | Where |
|---|---|
| Built inside the VisionJob decode/tracking loop; staged at Track retirement | `src/vision/mavi_vision/evidence/{selector,policy,encoder,admission,quality,roles}.py`; wired in `pipeline/process_video.py`, `finalization.py`, `production_processor.py` |
| Versions: `evidence-selector-v1-two-tier`, `quality-v2`, `evidence-jpeg-ladder-v1` | `evidence/policy.py:22-24` |
| Roles (≤ 4 per Track, rank 0–3): `representative` (mandatory, may be an unqualified fallback), `near-view`, `early-diverse`, `late-diverse` (qualified only) | `evidence/roles.py`; ADR-013 §4 two-tier amendment |
| Selection is model-neutral; **no plate-oriented selector is allowed** | ADR-013 §4 |
| Crop = **tight vehicle box, no padding** (floor/ceil of the normalised bbox × frame) | `src/vision/mavi_vision/quality/scoring.py:15-26` |
| Encoding: Pillow JPEG 4:2:0, Lanczos, **long edge ≤ 1024 px, never upscaled**; ladder q85 → q75 → shrink ×0.8 to a 128 px floor → q65/55/50 | `evidence/encoder.py`; `PRODUCTION_ENCODER_POLICY` in `evidence/policy.py:70` |
| Byte caps: Representative **64 KiB**, supplemental **160 KiB**; run quota 1 GiB, Representatives first, then NearView → EarlyDiverse → LateDiverse rounds | `evidence/roles.py:26-29`, `evidence/admission.py`; ADR-013 §5–§6 |
| Selector parameters (confidence floor 0.5, sharpness 0.05, edge margin 0.005, occlusion ceiling 0.3, early window 3 s, late refresh 5 s, separation 1 s) | `src/vision/config/pipelines/phase1-detection-tracking-v1.json` (`"evidence"`) |
| Accepted key `evidence/{jobId}/attempt-NNNN/crops/{trackId}-{role}-{sha256}.jpg`; content-addressed, sealed by size + SHA-256 | `Mavi.Application/Modules/Intelligence/EvidenceSealingPlan.cs:33-40`; `Mavi.Infrastructure/Storage/AcceptedEvidenceStore.cs` |
| Reader abstraction (shared) | `Mavi.Application/Abstractions/Storage/IAcceptedEvidenceReader.cs`, `Mavi.Infrastructure/Storage/AcceptedEvidenceReader.cs` |
| An Observation persists frame number, offset, UTC timestamp, normalised bbox, confidence, quality/selection score, role, rank and the crop Artifact FK. **The encoded crop's pixel size is not persisted; no full frame is stored** | `Mavi.Domain/Intelligence/Observation.cs`, migration `20260923160000_AddTrackEvidenceSet.cs` |
| Operator read: `GET /api/tracks/{id}` → `Observations[]` with `EvidenceArtifactId`, `EvidenceContentUrl`; bytes via `GET /api/artifacts/{id}/content` | `Mavi.Api/Endpoints/TrackEndpoints.cs`, `ArtifactEndpoints.cs`; `Mavi.Contracts/Api/Tracks/TrackDetailResponse.cs:86` |

**Consequence for ANPR.** NearView is the analytic-resolution carrier (ADR-013 §5). A plate occupies the plate's share of a tight vehicle crop at native source resolution, down-scaled only when the vehicle box exceeds 1024 px, and JPEG-compressed to fit 160 KiB. Representative crops are capped at 64 KiB, so they hold fewer bytes. Whether this preserves readable plates is the §3 measurement; it is not assumed.

### 1.2 Track and Observation schemas

- `Track` (`Mavi.Domain/Intelligence/Track.cs`, table `tracks`, `TrackConfiguration.cs`):
  - `object_class` is Person or Vehicle.
  - It carries start/end offsets and UTC timestamps, detection count, mean/max confidence, `representative_observation_id`, `trajectory_artifact_id` and `entity_id`.
  - Its ADR-016 subclass fields are `object_subclass`, `object_subclass_vocabulary` and `object_subclass_source`.
  - The camera is reached through `VideoAsset.CameraId` (`Mavi.Domain/Media/VideoAsset.cs`, which also holds `Width`/`Height`).
- `Observation` (table `observations`) has the shape in §1.1. Unique indexes `ux_observations_track_rank`, `_track_role` and `_track_frame`.

### 1.3 VisionJob and ProcessingRun lifecycle

- `VisionJob` (`Mavi.Domain/Processing/VisionJob.cs`):
  - Statuses: `Queued → Leased → Finalizing → Completed | Failed | Cancelled`.
  - Lease fields: token hash, expiry, attempt count, heartbeat.
  - The asynchronous finalizer (`Mavi.Api/Finalization/VisionFinalizationHostedService.cs`, `Mavi.Infrastructure/Finalization/VisionFinalizationExecutor.cs`) seals evidence and publishes the graph.
- `ProcessingRun` (`Mavi.Domain/Processing/ProcessingRun.cs`):
  - Statuses: `Queued | Running | Completed | Failed | Cancelled`.
  - `VisibilitySequence` is assigned at publication.
  - Post-Track work keys off `Status == Completed && VisibilitySequence != null`.
- **Stage 4 does not touch either aggregate.**

### 1.4 Post-Track worker infrastructure — the Stage-2 attribute plane is the template

| Concern | Existing implementation |
|---|---|
| Aggregate | `VisualAttributeAnalysis` per `(ProcessingRun, identity fingerprint)`, status `Queued, Running, Completed, Failed, Superseded` (`Mavi.Domain/VisualAttributes/VisualAttributeAnalysis.cs`). Tables: `visual_attribute_analyses`, `_identity_activations`, `_attempt_failures`, `_track_outcomes`, `visual_attributes` (migration `20260928035552_AddVisualAttributeLifecycle.cs`) |
| Scheduling / idempotency | `Mavi.Api/VisualAttributes/VisualAttributeHostedService.cs` → `Persistence/Repositories/VisualAttributeLifecycle.cs`. `EnsureActivationAsync`; `QueueEligibleAsync` (runs Completed + visible + completed after activation, with no unit for the fingerprint); unique `(processing_run_id, identity_fingerprint)`; claim `FOR UPDATE SKIP LOCKED` fenced on the worker's fingerprint; `SweepAsync`. **No historical backfill, and no explicit re-analysis endpoint yet** |
| Options | `VisualAttributeOptions` (lease 120 s, 3 attempts, 6 h max, reconcile 30 s, worker presence 180 s) |
| Control plane | `Mavi.Contracts/Worker/Attributes/VisualAttributeContracts.cs`, `VisualAttributeContractRules.cs`: schema `mavi-visual-attribute-control-v1`; capability only in `X-Mavi-Lease-Capability`; per-crop lease entry `(ObservationId, Role, EvidenceRank, SizeBytes, Sha256)` |
| Endpoints | `Mavi.Api/Endpoints/VisualAttributeEndpoints.cs`, `VisualAttributeCompletionEndpoint.cs`: lease, heartbeat, fail, lease-scoped evidence read, predictions `PUT`, `complete`, readiness |
| Lease-fenced streaming | `Mavi.Api/VisualAttributes/LeaseFencedStream.cs` (**attribute-namespaced**), audit `VisualAttributeAudit.cs` |
| Completion | three-phase validate → seal → publish (`Mavi.Infrastructure/VisualAttributes/VisualAttributeCompletionService.cs`, `VisualAttributeFactWriter.cs`); staging `staging-attributes/{id}/attempt-NNNN/`; janitor `AttributeStagingJanitor.cs`; integrity monitor `VisualAttributeIntegrityMonitor.cs` |
| Readiness | `NotConfigured, NotApplicable, Pending, Ready, Failed, Stale` (`VisualAttributeReadiness.cs`) |
| Shared primitives already extracted | `Mavi.Domain/Common/CanonicalSha256.cs`, `Mavi.Infrastructure/Security/LeaseCapabilityService.cs`, `IAcceptedEvidenceReader` |
| Python role | `src/vision/mavi_vision/attributes/{main,supervisor,client,runner,pipeline,inference,predictions,contracts,settings}.py`; verifies size + SHA-256 before decode; `AttributeInferencer` seam with `FixtureAttributeInferencer` |

### 1.5 ADR-014 bindings, Model Packs and Runtime Packs

- Release binding `src/vision/config/components/phase1-bindings-v2.json`. It declares **only** the `vision` role and the `detector` binding, on Runtime Pack family `mmdetection-phase1-v1`.
- Development replacement bindings are registered in `src/vision/config/development-producers-v1.json`. The overlay mechanism (adding roles) is accepted but **not implemented** (ADR-014 2026-10-06 note).
- `src/vision/mavi_vision/runtime/capabilities.py`:
  - `KNOWN_CAPABILITIES` already contains `plate-detector` and `ocr`.
  - `IMPLEMENTED_CAPABILITIES = {detector, person-attributes, vehicle-attributes}`.
  - Input contracts are mapped in `IMPLEMENTED_INPUT_CONTRACTS`.
- `runtime/resolver.py:119`: `IMPLEMENTED_ROLE_ENTRY_POINTS` covers `vision` and `attributes`.
- `model_manifest_v2.py` supports `capabilitySpecific.<capabilityId>` with an `adapterId` (ADR-013 item 8).
- Model Pack manifests are in `models/manifests/`, qualification records in `models/qualifications/`, gate sets in `config/acceptance/capability-gate-sets-v1.json` (only `common-v1` and `detector-v1` today), and deployment profiles in `config/acceptance/phase1-deployment-profiles-v1.json`.
- Runtime family profile: `src/vision/runtime/mmdetection-phase1-v1/{runtime.json,*.lock,*.requirements.txt}`.
- Rule for a model outside the vision graph (ADR-013 item 10; S2c plan §12.7): it binds its **own** Runtime Pack family `<role>-<engine>-v1`, with its own locks, wheels, licence inventory, CI build and ADR-009 status. The vision lock is never widened.
- MSR method v1: `docs/qualification/model-selection/README.md`, templates in `templates/`.
  - Event id: `msr-<capabilityId>-<year>-<nn>`.
  - Each learned capability gains a `<capabilityId>-model-selection` gate.

### 1.6 Search, API and indexing

- `GET /api/tracks` (`TrackEndpoints.cs` `SearchAsync`):
  - Query keys are a closed whitelist (`SupportedQueryKeys`, L106–134).
  - The application layer is `Mavi.Application/Modules/Intelligence/TrackSearchService.cs` and `TrackSearchQuery.cs`.
  - The repository builds EF LINQ only: `AnalyticsScopeQuery.BaseCandidates` (latest completed visible run per video, scalar filters), `TrackSearchRepository.BuildQuery`, and `TrackSearchRepository.Analytics.cs` (correlated `Any(...)` EXISTS over fact tables, plus a bounded per-page explanation).
- Ordering is `StartTimestampUtc DESC, Id DESC`, with a keyset cursor and snapshot isolation by `ProcessingVisibilityBarrier`.
- Cursors are in `TrackCursorCodec.cs`. v2 is unsigned, ≤ 512 characters, with a filter fingerprint. v3 is HMAC-signed, ≤ 768 characters, and pins camera, revision and algorithm.
- **ADR-013 §16's v4 signed cursor for cross-camera derived-capability predicates is specified but not implemented.**
- **Stage-2 attributes are not exposed in search at all.** Plate search is therefore the first cross-camera, post-Track predicate family in code.
- Indexes: `TrackConfiguration.cs` L16 (including the partial subclass index). The only database extension is `vector`. **No `pg_trgm`, GIN or trigram index exists.** PostgreSQL is version 18 (`config/dependencies/offline-binary-catalog-v1.json`), where `pg_trgm` is a trusted contrib extension.
- No OpenAPI snapshot. The wire shape is pinned by tests:
  - `tests/Mavi.Application.Tests/Contracts/TrackAnalyticsContractTests.cs`
  - `tests/Mavi.IntegrationTests/{TrackSearchApiTests,TrackSearchAnalyticsApiTests,TrackEvidenceSetReadApiTests,VehicleSubclassExposureApiTests}.cs`
  - query-shape guards `AnalyticsQueryShapeTests.cs` and `TrackDetailQueryShapeTests.cs`
  - `MigrationTests.cs` (index definitions via `pg_indexes`)
  - cursor length bounds in `TrackCursorCodecTests.cs`

### 1.7 Review / Inspector evidence presentation

- Search (`src/web/mavi-web/src/features/visual-search/`):
  - `VisualSearchPage.tsx`: the URL is the state; infinite cursor query.
  - `SearchFilterRail.tsx`: `SearchDraft`, plus Scope, Time and Analytics sections.
  - `searchState.ts`, `searchValidation.ts`, `CommittedFilterChips.tsx`.
  - `TrackResultList.tsx`: `reviewPath` drill-through with return context.
  - `TrackInspector.tsx`.
- Review (`features/video-review/`):
  - `VideoReviewPage.tsx`.
  - `TrackEvidence.tsx`: the shared `EvidencePlayer`, with one timeline marker per Observation.
  - `TrackEvidenceSet.tsx`: crops inspect, and seeking happens on the timeline.
  - `TrackAnalyticsExplanation.tsx`: the "why it matched" pattern.
  - `TrackDetailsPanels.tsx`: `ProvenancePanel`.
- Shared: `shared/evidence/{EvidencePlayer,EvidenceTimeline,CoverageStrip,EvidencePlaceholder}.tsx`, `shared/workspace/Inspector.tsx`.
- UI spec rules that apply:
  - §14: Unknown is a neutral outline plus explicit text, never colour alone.
  - §16: one line and one badge per row.
  - §17: committed chips and a "why this set" header.
  - §17.1: the language model never owns a plate reading.
  - §18: confidence as text.
  - §19: candidates are never styled as confirmed facts.
  - §20: inspector tiers.
  - §24: number and offset formats.
  - §29: Stage-4 row "Investigation; none beyond §17".
  - §37.2: operational, explanation and forensic tiers.

### 1.8 Offline packaging, locks and qualification

- `config/dependencies/offline-dependency-policy-v1.json`:
  - `managedSources` must equal the parsed set of every tracked `pyproject.toml` and every `requirements*.txt` under `src/` or `tools/` (`tools/verify_repo.py` `check_dependency_policy`).
  - There are 11 `nativeAndToolchain` entries and 9 `requiredChangeReview` rules.
- `config/dependencies/offline-binary-catalog-v1.json`; inventory in `docs/architecture/offline-binary-inventory.md`.
- **None of onnxruntime, PaddlePaddle, Tesseract or Ultralytics is a dependency anywhere.** `opencv-python==5.0.0.93` is in the vision family.
- Builders: `tools/vision/{build_runtime_pack,freeze_offline_lock,build_wheelhouse_manifest,write_requirements_projection,build_model_pack,build_offline_bundle}.py`.
- Setup: `tools/setup/{Install-MaviVisionRuntime,Install-MaviVisionModelPack,Test-MaviEnvironment,Test-MaviOfflineBinaryKit}.ps1`.
- Runbook: `docs/runbooks/vision-runtime-model-component-lifecycle.md`.
- Benchmark harness (ADR-017 §11) in `tools/benchmarks/`:
  - `core/{descriptor,envelope,identity,mapping,mavi,producer}`
  - `datasets/{bdd100k_mot,bdd100k_mot_coco,visdrone_mot,synthetic}`
  - `capabilities/{vehicle_subclass,vehicle_tracks}`
- Controlled data lives outside Git under `E:\MAVI-Controlled\Benchmarks\<datasetId>\<release>\…`; candidate model bytes live in a controlled store outside Git.
- CI:
  - Required checks: `quality` (`quality-gate.yml`, scope-classified) and `Task 10 qualification`.
  - Other workflows: `task17-acceptance.yml`, `qualification-tooling-windows.yml`, `task12-offline-bundle.yml`, `vision-runtime-component-boundary.yml`, `vision-model-pack.yml`.

### 1.9 Gaps this plan closes

| # | Gap | Closed by |
|---|---|---|
| G1 | No plate ground-truth, adapters or evaluator in the benchmark harness | PR-1 |
| G2 | No measured evidence-adequacy verdict | PR-1 |
| G3 | No plate capability, role, lifecycle, contracts or persistence | PR-3 |
| G4 | No historical re-analysis request, even though ADR-013 §9 requires an explicit bounded one | PR-3 |
| G5 | No cross-camera derived-predicate search or v4 cursor; no trigram index | PR-4 |
| G6 | No plate UI, and the UI spec has no plate-presentation rules | PR-4 (spec), PR-5 (UI) |
| G7 | No plate/OCR Model Packs, Runtime Pack family, gate sets or MSR events | PR-2 (selection), PR-6 (packaging) |

---

## 2. Stage 4 technical design

### 2.1 Flow and placement

```
ProcessingRun Completed + visible
   └─ PlateAnalysis unit queued per (run, plate identity fingerprint)        [platform, hosted service]
        └─ `plates` role leases the unit                                      [separate process, own Runtime Pack family]
             for each Vehicle Track, for each leased evidence crop:
               GET lease-scoped evidence → verify size + SHA-256 → decode once
               plate-detector capability → 0..P plate boxes (crop pixel coords)
               ocr capability on each plate region → ranked readings (raw text, confidence)
             PUT PlatePredictions artefact (canonical JSON; every raw output)
             POST complete (relational PlateObservations + readings + Track outcomes)
   └─ platform: validate → seal artefact → publish rows + Track plate texts + visibility sequence
```

**Placement:**
- An independent post-Track role `plates`, entry point `mavi_vision.plates.main`, serving capabilities `plate-detector` and `ocr`.
- It reads sealed evidence only through lease-scoped platform endpoints (ADR-013 §10).
- VisionJob, the completion contract v3.x and the evidence selector are **unchanged**.

### 2.2 Scheduling, idempotency and ProcessingRun/Track relationships

- **One unit per `(ProcessingRunId, plate identity fingerprint)`.** This mirrors `VisualAttributeAnalysis` exactly.
  - It is a capability-specific aggregate (ADR-013 §9), not a generic job abstraction (ADR-013 alternative G).
  - The unit covers every Vehicle Track of the run. Person Tracks are not applicable.
- **Identity** is the SHA-256 of the canonical tuple:
  - plate pipeline version;
  - normalisation id and SHA;
  - Track-text summary policy id and SHA;
  - ordered `(capabilityId, modelPackId)` for `ocr` and `plate-detector`;
  - parameters SHA.
- Runtime Pack, device and commit are provenance, not identity (ADR-013 §11).
- **Queueing:** the hosted service queues eligible runs completed after the identity's activation. The unique `(processing_run_id, identity_fingerprint)` constraint makes queueing idempotent.
- **Historical runs** are queued only by an explicit, bounded re-analysis request:
  - `POST /api/plates/reanalysis` with exactly one of `{processingRunIds[≤ 100]}` or `{cameraId, fromUtc, toUtc}`, capped by `MaximumRunsPerRequest`;
  - idempotent through the same unique key; administrative and audited;
  - this closes G4 for plates only.
- **Claim:** `FOR UPDATE SKIP LOCKED`, fenced on the worker's resolved fingerprint. A worker composed from different bindings can neither claim nor consume attempts.
  - If the required capability is unavailable at worker startup, units stay Queued and no attempts are consumed.
- **Relationships:** `PlateAnalysis` → `ProcessingRun` (FK Restrict). `PlateObservation` → `Track` and → source `Observation` (FK Restrict). No column is added to `tracks`, `observations`, `processing_runs` or `vision_jobs`.

### 2.3 Evidence integrity and provenance

- The lease lists, per Vehicle Track, every admitted Observation as `(ObservationId, Role, EvidenceRank, SizeBytes, Sha256)` — the attribute lease entry shape.
  - The worker needs no frame bbox. Plate geometry is expressed in decoded evidence-crop pixel coordinates and can be mapped to frame coordinates through the Observation's bbox and `VideoAsset` dimensions when needed.
- The worker verifies size and SHA-256 before decode.
  - A missing object or a digest mismatch at rest marks the Track `Unavailable` with a reason and raises the integrity signal (ADR-013 item 3).
  - A transient transport failure is retried within the lease and never becomes `Unavailable`.
- **Every role is processed, including the Representative.** It is recorded with its role and never inferred to be qualified.
  - Attributes abstain on the Representative because colour judgements need a qualified frame (ADR-013 item 9). A plate reading carries its own detector and OCR confidence, and the §3 measurement reports usefulness per role.
  - If the measurement shows Representative readings harm Track-level precision, the pipeline profile excludes that role. This is a parameter, not an architecture change.
- **Plate crop as sealed derived evidence, by reference.** A `PlateObservation` stores its source Observation (whose crop bytes are sealed and hash-pinned) plus the plate box in that crop's pixel space.
  - The plate crop is therefore a deterministic function of sealed bytes and a sealed box. The box is in the relational row and in the sealed `PlatePredictions` artefact, whose SHA is on the analysis header.
  - The UI renders the plate region client-side from the existing evidence-crop content endpoint.
  - No second image artefact type, no multi-object upload protocol and no new storage quota are needed.
  - This refines the roadmap's "plate crop artefact" wording without weakening it. It is recorded as an ADR-013 Stage-4 implementation amendment in PR-3 (§9, decision B2).
- **Provenance** on the analysis header:
  - `plateDetectorModelPackId`, `ocrModelPackId`, `runtimePackFamilyId` and variant, `runtimePackId`, resolved device;
  - normalisation id and SHA, summary policy id and SHA, parameters SHA;
  - `PlatePredictions` artefact id and SHA, completion digest, platform build and commit.
- Per-row model fields are not authoritative (ADR-013 §14).

### 2.4 Detector and OCR execution boundary

- One process holds both components.
  - Each is a capability with its own Model Pack and binding: `plate-detector` and `ocr`.
  - Each has a registered adapter `capabilitySpecific.<capabilityId>.adapterId` from a closed, versioned registry in `mavi_vision/plates/adapters/`, with preprocessing and output mapping declared by its Model Pack (ADR-013 item 8).
- Interfaces (Python, internal to the role):
  - `PlateDetector.detect(crop_rgb) -> list[PlateBox(x, y, w, h, polygon?, score)]`
  - `PlateRecogniser.read(plate_region_rgb) -> list[Reading(raw_text, confidence, line_count)]`, at most `k` readings.
  - Two-line plates are handled inside the recogniser adapter. Either the model reads two-line plates natively, or a deterministic line split is declared in that Model Pack's preprocessing. Line order is top to bottom.
- **Independent replaceability:** replacing one component changes one `modelPackId`, and therefore the identity. The other component is untouched.
  - A replacement is still re-measured as a composition (§4.6).
- **Import boundary:** `mavi_vision.plates` must not import torch, mmcv or mmdet, or any module that does. A test enforces this, because the role runs from its own Runtime Pack family.

### 2.5 Failure isolation

- Plate failure never touches VisionJob, ProcessingRun, Tracks, evidence or attribute units.
- A crashed or OOM worker loses only its lease. The unit is reclaimed under a new attempt and token. After the maximum attempts it is `Failed`, and the run's plate readiness is `Failed`.
- Per-crop inference errors are recorded in the artefact as `abstained` with a closed reason (`decode_failed`, `detector_error`, `ocr_error`). They never become a negative fact.
- A unit exceeding its maximum duration fails as a whole and publishes nothing partial.
- Device policy is per role: the `plates` role defaults to CPU on the 4 GiB Development GPU host unless the §4 measurement justifies CUDA co-residency. Silent GPU→CPU fallback is prohibited (ADR-008).

### 2.6 Reprocessing with newer models

- A new binding produces a new fingerprint, and therefore new units for newly completed runs.
- A completed newer unit supersedes the older unit's default status. History stays readable.
- The default analysis per run is derived from the preferred fingerprint, never from completion order (ADR-013 item 5).
- Older runs report `Stale` until explicitly re-analysed (§2.2).

### 2.7 Multiple observations, confidence, disagreement and uncertainty

- A Track carries 0..N `PlateObservation`s: at most 4 crops × `maxPlatesPerCrop` (profile parameter, initial value 2).
- Each `PlateObservation` has:
  - `outcome = Read`, with one or more ranked readings; or
  - `outcome = Unreadable` — a plate was detected but every reading is below the profile's `ocrConfidenceFloor`. Unreadable carries no text.
- Track-level outcome:
  - `Analysed`. With zero plate observations it means **"no plate found in the evidence"**, never "the vehicle has no plate".
  - `Unavailable(reason)`.
- **Track plate texts** (search acceleration, not replacement evidence): one row per distinct normalised text among the rank-0 readings of `Read` observations, with:
  - `supportCount` — the observations whose rank-0 reading equals it;
  - `maxConfidence`;
  - `bestPlateObservationId`.
  - Whether rank > 0 readings also enter the texts is a **summary-policy parameter** fixed by the §4 benchmark (default v1: rank 0 only).
- **Agreement** is derived, not asserted:
  - `single` — one Read observation;
  - `consistent` — ≥ 2 Read observations with one distinct text;
  - `conflicting` — ≥ 2 distinct texts;
  - `none`.
- No reading is ever labelled confirmed, and no Track-level "the plate" field exists.
- Confidence semantics are declared by each OCR Model Pack's output mapping. The API and UI show them as model confidence, under UI-spec §24.

### 2.8 Search indexing and query performance

- The plate predicate is a correlated EXISTS over `plate_track_texts`, keyed by `(analysis_id, track_id)`, for the run's default analysis. It is added in `TrackSearchRepository` beside the analytics predicates.
- Candidate indexes: `pg_trgm` GIN on `normalised_text` for `contains`, and a `text_pattern_ops` b-tree for `prefix`/`exact`.
  - The final choice is made on measured `EXPLAIN (ANALYZE, BUFFERS)` at a seeded scale (PR-4), as ADR-013 §14 and the roadmap require.
- The minimum normalised query length is 3 characters, because trigram indexes need it.
- Budget, measured in PR-4 on the CI PostgreSQL and on the Development host:
  - p95 ≤ 300 ms for the first page of a plate-only search over 10⁶ `plate_track_texts` rows and 10⁶ Vehicle Tracks;
  - no N+1 (query-shape test).

### 2.9 Offline runtime installation and lifecycle

- The selected composition's third-party runtime becomes one new Runtime Pack family `plates-<engine>-v1`. The name is fixed after selection (for example `plates-onnxruntime-v1`).
  - It has per-variant `*.lock`, `*.requirements.txt` and `runtime.json`, an offline wheelhouse and a licence inventory.
  - CUDA variants start `pending-hardware-qualification` (ADR-009).
  - A native binary (for example Tesseract, if it is selected) is a `nativeAndToolchain` entry with staging path, verification and licence handling.
- Model Packs: one per capability, each with a source manifest v2 (`models/manifests/`), a `licence-notice` artefact and a derived `modelPackId`.
- Setup:
  - `Install-MaviVisionRuntime.ps1` and `Install-MaviVisionModelPack.ps1` gain the family and packs.
  - `Test-MaviEnvironment.ps1` gains a plates READY probe.
  - A disconnected install is verified on the offline kit (`Test-MaviOfflineBinaryKit.ps1`).
- No runtime download, telemetry or online activation (policy rule 9). Model bytes never enter Git.

---

## 3. Evidence-adequacy experiment (executes before any model selection or VisionJob change)

**Question.** Do the existing sealed evidence crops (§1.1) preserve enough plate pixels and clarity for useful ANPR? This is asked of the evidence, not of any one model.

### 3.1 Method

The experiment has two parts. It uses only existing code paths and public benchmark data under ADR-017.

**E-A — encoding loss (still images, component level).** For each ground-truth plate in a labelled still-image dataset:
1. Obtain the vehicle box: either the dataset's own box, or the box the phase-1 detector produces on that image, associated to the plate geometrically (plate box ⊂ vehicle box). This is the MAVI system under test, not a ground-truth shortcut.
2. Cut the tight vehicle crop exactly as `quality/scoring.py:crop_region` does.
3. Encode it with **the production encoder itself** (`mavi_vision.evidence.encoder` with `PRODUCTION_ENCODER_POLICY`) at each role cap: 64 KiB and 160 KiB.
4. Map the ground-truth plate polygon into the encoded crop and measure:
   - character height and plate width in pixels;
   - Laplacian variance (blur) on the plate region;
   - JPEG quality step and long-edge reduction applied.
5. Read the ground-truth plate region from (a) the native frame and (b) each encoded crop with **two measuring instruments**: two diverse pretrained OCRs from the §4.3 long list, one plate-specific and one generic. Record exact match (EM) and CER on normalised text.
   - The instruments measure the evidence. They are not selection candidates, and their identities and bytes are recorded. Using two limits the bias of any single model.

**E-B — selection coverage (video, Track level).** On labelled video sequences with per-frame plate boxes and text:
1. Process the clips through real MAVI (benchmark-harness producer path, `tools/benchmarks/core/mavi.py`, release pipeline profile).
2. Export each run's Observations and sealed crop bytes by hash. Extend the measurement-export pattern of `Mavi.Infrastructure/Measurement/SubclassMeasurementExporter.cs`; no product API change.
3. Associate ground-truth vehicle sequences to MAVI Vehicle Tracks with the existing deterministic association (ADR-017 §6), never using predictions.
4. For each associated Track:
   - **oracle-readable**: some source frame's native ground-truth plate crop has character height ≥ `h_min` and is read exactly by an instrument;
   - **evidence-readable**: some evidence crop of that Track is read exactly by an instrument;
   - the evidence-readable result is broken down by role.

### 3.2 Strata (each reported separately; Indian conditions first)

- vehicle type (car, motorcycle, commercial);
- plate layout (one-line, two-line);
- character-height bins (< 10, 10–14, 15–19, 20–31, ≥ 32 px);
- oblique (polygon skew > 15°);
- motion blur (Laplacian-variance tertiles, plus dataset blur labels where present);
- illumination (day / night / low-light, from dataset labels or a mean-luminance proxy);
- partial occlusion (dataset labels where present);
- source resolution;
- role.

A stratum below 50 ground-truth plates is reported as **insufficient evidence**, never as pass or fail.

### 3.3 Data (ADR-017 benchmark-first; admissibility recorded per release before use)

| Purpose | Candidate releases (verify at intake; status per ADR-017 §7) |
|---|---|
| Indian stills (E-A, §4 A–C) | **Indian Licence Plate Dataset in the wild** (Tanwar et al., arXiv 2111.06054: 16,192 images, 21,683 plates, 4-point plate and per-character annotation; code/data `github.com/sanchit2843/Indian_LPR`); IEEE DataPort *Indian License Plate Recognition Dataset (YOLO & OCR)* (stylised and multi-line plates; access terms to verify — BLOCKED if payment is required); IEEE DataPort *IND-VNP* (same caveat) |
| Track-level video sequences (E-B, §4 D) | **UFPR-ALPR** (sequences of 30 consecutive 1920×1080 frames per vehicle; per-frame plate box and text; academic, research-only on request); further video ALPR sets found during the search |
| Two-line / motorcycle and robustness strata | **RodoSol-ALPR** (toll cameras; cars and motorcycles with two-line plates; terms to verify); **CCPD** (oblique, blur, challenge, dark/bright subsets; repository states MIT). Taxonomy: the leading Chinese province glyph is `unsupported`, so OCR is evaluated on the alphanumeric remainder (`subset` mapping, declared per ADR-017 §4) |

Each release gets the ADR-017 release-level record (§7) in Git. Its bytes go under `E:\MAVI-Controlled\Benchmarks\<datasetId>\<release>\` and stay out of Git.

**Indian Track-level gap.** If the PLANNED-stage search finds no labelled Indian ALPR *video* benchmark, the Indian Track-level evidence is partial: Indian stills plus non-Indian sequences. This is recorded, not hidden. A bounded, owner-accepted labelling of Development footage is the ADR-017 §2 fallback (decision O1, §9). It does not block PR-1 or any other PR.

### 3.4 Frozen acceptance criteria and decision rule

These are written into the PR-1 protocol and hashed before any result is read.

1. **`h_min`.** The smallest character-height bin in which the better instrument's native-crop EM is at least 0.9 × its EM in the ≥ 32 px bin. It is derived from E-A native crops. Every other criterion uses it.
2. **Encoding loss.** ΔEM = EM(native ground-truth crop) − EM(encoded ground-truth crop), per role cap, for each instrument, over plates with native character height ≥ `h_min`.
3. **Pixel adequacy.** `U_role` = the share of ground-truth plates in the encoded crop with character height ≥ `h_min`.
4. **Selection coverage.** `C = R_ev / R_oracle` over associated Vehicle Tracks (E-B).

| Verdict | Rule (NearView/supplemental roles; strata reported alongside) | Consequence |
|---|---|---|
| **ADEQUATE** | C ≥ 0.85 **and** ΔEM ≤ 5 pp for both instruments | Stage 4 consumes evidence unchanged; no ADR |
| **MARGINAL** | 0.70 ≤ C < 0.85, **or** 5 pp < ΔEM ≤ 10 pp | Proceed post-Track on unchanged evidence; the gap is recorded in the register with its strata; the owner is informed; alternatives (§3.5) may be evaluated as a follow-on, never selected automatically |
| **INADEQUATE** | C < 0.70 **or** ΔEM > 10 pp | Report to the owner with the measured strata and the §3.5 alternatives and their ADR consequences. PR-3–PR-5 continue, because every alternative still feeds the same plate lifecycle; PR-6 waits for the owner's decision |

A per-stratum failure, such as night two-line plates, with an overall ADEQUATE verdict is an exposure limit recorded in the register. It does not change the evidence contract.

### 3.5 Bounded alternatives if evidence is insufficient (none is selected by this plan)

| # | Alternative | What changes | ADR consequence |
|---|---|---|---|
| X1 | Re-derive encoder/role parameters (larger NearView byte cap, or a padded crop for Vehicle) | Pipeline profile numbers only | New pipeline profile, so new ProcessingRun identity and requalification (ADR-013 §6, ADR-009). Historical Tracks are not improved |
| X2 | Platform-served native-resolution source-frame region at an existing Observation's frame number and bbox (padded), decoded by the platform from the retained source video | A new lease-scoped read endpoint that decodes video; no VisionJob change; works on historical Tracks while their video is retained | ADR-013 §10 amendment (reads of non-sealed derived pixels; decode cost and audit); retention precondition on source video |
| X3 | Plate-aware evidence role inside VisionJob | Selector change | ADR-013 §4 amendment (plate-oriented selection is currently forbidden), completion contract revision, VisionJob requalification. Alternative A of ADR-013 is not reopened without this evidence |

---

## 4. Model benchmark protocol (Model Selection Events)

### 4.1 Events

- Two capability ids, two events, one joint frozen protocol:
  - `msr-plate-detector-2026-01` under `docs/qualification/model-selection/plate-detector/`;
  - `msr-ocr-2026-01` under `docs/qualification/model-selection/ocr/`.
- Each event follows MSR method v1 with M1 credibility: External Evidence Ledger, exact bytes, R/M-D/M-E classes, immutable once closed.
- The shared protocol file is `docs/qualification/model-selection/plates-2026-01-protocol.md`.
- **Composition rule.** Components are first ranked per sub-task (A for detectors; B for OCR). The top `K = 3` of each, plus any packageable baseline, form at most 9 compositions plus the baseline compositions. **Technical ranking is by the composition's end-to-end Track-level result (D).** A and B/C are diagnostics and gates only.
- Each event closes with the component of the selected composition.
- A later event may replace one component. It is measured as a composition against the incumbent other component, so independent replaceability is preserved.
- **Pretrained only.** No fine-tuning or training in these events. A fine-tuning event opens only if the closed events record a measured gap against a frozen target (§4.5, last row).

### 4.2 Entry criteria (all required before `PROTOCOL_FROZEN`)

1. The §3 adequacy verdict is recorded in the register. If it is not ADEQUATE, the protocol names the evidence source D uses.
2. Plate ground-truth schema, dataset adapters and the evaluator are merged with tests (PR-1).
3. ADR-017 release records exist for at least one Indian still dataset and at least one Track-level sequence dataset.
4. `mavi-plate-normalisation-v1` is frozen, with cross-language test vectors.
5. Every shortlisted candidate's exact bytes are pinned by SHA-256 in the controlled store, and its ledger entry is complete.
6. Host profiles are declared:
   - Development Windows CPU;
   - Development Windows CUDA sm75 with 4 GiB VRAM;
   - Linux CPU (hosted CI class).
7. The workload model for the 500-camera scale projection (Vehicle Tracks per camera-minute) is owner-declared or re-used from S2c with its hash.
8. MPID, metric definitions, query set, strata, cluster unit and statistical rule are written and hashed. **The protocol is frozen before any candidate sees selection data.**

### 4.3 Candidate long list (to be confirmed at `PLANNED`; inclusion is not selection)

Plate detection (plate-specific weights only; a generic COCO detector is not a plate detector):

| Id | Candidate | Notes to verify |
|---|---|---|
| PD1 | `open-image-models` YOLOv9 license-plate end2end family (t-256/384/512/640, s-608), ONNX | Licence of code and weights; training data and exposure to §3.3 datasets |
| PD2 | Ultralytics YOLOv8/YOLO11 plate-trained public checkpoints with documented training data | AGPL-3.0 inheritance (licence axis only); credibility class per M1 |
| PD3 | Detector weights released with *Indian Licence Plate Dataset in the wild* (if released) | Exposure: trained on the Indian benchmark, so its scores on that split are reference, not independent |
| PD4 | RTMDet with plate-specific weights | **Shortlisted only if such weights exist**; otherwise `NOT_SHORTLISTED` with "no plate-specific weights" |
| PD5 | PP-OCR text detector (PaddleOCR v4/v5 det) as a plate-region proposer | Generic text detector; justified as a credible non-YOLO alternative; may confuse with other text on vehicles |

OCR / recognition:

| Id | Candidate | Notes to verify |
|---|---|---|
| OC1 | `fast-plate-ocr` global plate recognisers (for example `cct-xs-v2-global-model`), ONNX | Plate-specific; regions in its training data; two-line handling |
| OC2 | PaddleOCR PP-OCRv5 / PP-OCRv4 recognition (mobile and server) | Apache-2.0; route via Paddle Inference or ONNX export (engineering axis) |
| OC3 | PARSeq scene-text recogniser (released checkpoints) | Strong generic recogniser; needs line split for two-line plates |
| OC4 | LPRNet weights from *Indian Licence Plate Dataset in the wild* (if released) | Same exposure note as PD3 |
| OC5 | **Tesseract 5 LSTM (role: baseline)**, `--psm 7`, whitelist `A-Z0-9` declared as preprocessing | Native binary; deterministic floor |

The shortlist is capped at about 5 detectors and 6 recognisers so the event stays bounded (ADR-015 §5 scale). Discovery sources and every exclusion reason are recorded in the ledgers.

### 4.4 Metrics and evaluation layers

| Layer | Measure | Primary | Diagnostics |
|---|---|---|---|
| **A** Plate detection | on ground-truth vehicle crops (encoded as evidence, §3.1 step 3) | Recall at **coverage ≥ 0.95** of the ground-truth plate polygon (a looser box is harmless to OCR; IoU is diagnostic) | AP50, false plates per crop, per-stratum recall |
| **B** OCR on ground-truth crops | normalised plate EM | EM | CER, top-k hit, calibration (ECE), risk–coverage curve, per stratum |
| **C** OCR on detected crops | normalised plate EM | EM | C − B gap attributable to the detector |
| **D** End-to-end, Track level (ranking) | on Track-level sequences after real MAVI processing (§3.1 E-B), and Indian stills as single-observation pseudo-Tracks (reported separately) | **D-score** = mean of (full-plate Track recall at `exact`, partial-query Track precision at `contains`, partial-query Track recall at `contains`) | **Consistent-wrong rate** (Tracks whose readings all agree on a wrong text; gated); conflicting-reading rate; Unreadable rate; per query class |
| **E** Engineering (M-E) | per host profile | CPU and CUDA per-crop latency p50/p95; per-Track cost; throughput; peak RAM/VRAM with the detector co-resident; cold start/READY; pack size; Runtime Pack footprint | 500-camera projection (§7.1 of the MSR method) |

- **Query set for D** is generated deterministically from ground truth:
  - every full plate;
  - the state+RTO prefix (first 4 characters, for example `KA01`);
  - the last-4-digit suffix;
  - a 5-character interior substring;
  - matched negative queries (edit distance 1–2 from a real plate and absent from the corpus).
- **Statistics:** hierarchical paired bootstrap, clustered by sequence/camera (MSR §8.1), 95 % intervals. "Better" requires the interval to exclude zero **and** a difference ≥ MPID (initial value 2 pp on D-score).

### 4.5 Gates (pass/fail; never compensated by score)

| Gate | Rule |
|---|---|
| Offline | Loads and infers from pack artefacts alone, with no network |
| Determinism | Identical bytes in give identical readings and confidences on CPU (bitwise, or within a declared ε for confidence) |
| Baseline | Composition D-score ≥ the Tesseract-baseline composition's D-score + MPID |
| Consistent-wrong | Consistent-wrong rate ≤ 2 % of evaluated Tracks (the dangerous error class) |
| Budget | CPU per-Track p95 ≤ 2 s at ≤ 4 crops on the Development CPU host, and a 500-camera projection inside the declared host envelope |
| Fine-tuning trigger | If the best composition's Indian full-plate EM (B, one-line, character height ≥ `h_min`) is < 0.85, the event records the gap and a fine-tuning event **may** be proposed. It is not started by this plan |

- Licence and deployment eligibility is assessed separately per MSR §2. It never enters the ranking, and the technical ranking is never adjusted for it.
- A candidate whose runtime needs a new Runtime Pack family is not rejected for that reason. **No candidate here is on the existing vision graph**, so the "extension must clear MPID over an existing-graph candidate" rule (MSR §8.1) is vacuous and recorded as such.

### 4.6 Reproducibility

Every M row records:
- harness version and code commit;
- dataset release manifest hash;
- preprocessing configuration hash;
- candidate weight SHA-256 and upstream revision;
- host profile, seed and replicate count;
- result artefact SHA-256.

Results are retained create-only by hash, outside Git, with record hashes in Git (S2c pattern). Benchmark-only candidate runtimes are installed in a Development benchmark environment declared in `tools/benchmarks/plates/requirements-candidates.txt`. That file is classified dev/test in the dependency policy and never enters a Runtime Pack. Exposure of every candidate to every benchmark is recorded (ADR-017 §8).

---

## 5. Data, API and search contracts

### 5.1 Persistence (PR-3 migration `AddPlateAnalysisLifecycle`, additive only)

| Table | Columns (abridged) | Keys and constraints |
|---|---|---|
| `plate_analyses` | the `visual_attribute_analyses` shape: identity fields (`identity_fingerprint`, pipeline version, normalisation id/sha, summary policy id/sha, parameters sha, ordered pack ids JSON), lease/fencing, `completion_digest`, `prediction_artifact_id`, `provenance_json`, `visibility_sequence`, counts | unique `(processing_run_id, identity_fingerprint)`; claim index as the attribute plane |
| `plate_identity_activations`, `plate_attempt_failures` | as the attribute plane | as the attribute plane |
| `plate_track_outcomes` | `analysis_id, track_id, outcome (Analysed\|Unavailable), reason, plate_observation_count, distinct_text_count` | PK `(analysis_id, track_id)` |
| `plate_observations` | `id, analysis_id, track_id, source_observation_id, plate_index, box_x, box_y, box_w, box_h (int, crop px), crop_width, crop_height, detector_confidence, outcome (Read\|Unreadable)` | unique `(analysis_id, source_observation_id, plate_index)`; FKs Restrict; check box inside crop |
| `plate_readings` | `plate_observation_id, rank, raw_text (≤ 32, NFC), raw_line_count (1\|2), normalised_text (nullable), normalisation_outcome (ok\|rejected), confidence, format_class (in-standard\|in-bh\|other)` | PK `(plate_observation_id, rank)`; Read ⇒ rank 0 exists; Unreadable ⇒ no rows |
| `plate_track_texts` | `analysis_id, track_id, normalised_text, support_count, max_confidence, best_plate_observation_id` | unique `(analysis_id, track_id, normalised_text)`; search index per §2.8 |
| `artifacts` | new `ArtifactType.PlatePredictions` | sealed under ADR-006 |

- **Backward compatibility:** no existing column changes, and no historical row is migrated. A Track without a plate analysis reports readiness, never an empty fact (a missing row is not Unknown — ADR-013 §12).

### 5.2 Normalisation `mavi-plate-normalisation-v1`

The same function runs in the Python worker and in .NET query parsing. It is pinned by cross-language vectors `contracts/test-vectors/plate-normalisation-v1.json`.

1. Unicode NFKC.
2. ASCII upper-case.
3. Remove spaces, line breaks, `-`, `.`, `·`, `:`, `/`. Two-line readings are concatenated top line first.
4. If any character outside `[A-Z0-9]` remains, set `normalised_text = null` and `normalisation_outcome = rejected`. The reading stays visible and is not searchable. Nothing is silently dropped.
5. **No confusable substitution** (O/0, I/1, B/8, S/5, Z/2), no character insertion, no grammar repair.
6. `format_class` is advisory only:
   - `in-standard` matches `^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$`;
   - `in-bh` matches `^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$`;
   - anything else is `other`.
   - It never alters text or ranking and is not a validity claim.

Raw OCR text is immutable. Normalisation is a versioned derivation. Its id and SHA are part of the analysis identity.

### 5.3 Worker control plane `mavi-plate-control-v1` (PR-3)

- Route prefix `/api/plates/analyses`: `POST lease`, `POST {id}/heartbeat`, `POST {id}/fail`, `GET {id}/evidence/{observationId}`, `PUT {id}/predictions`, `POST {id}/complete`.
- Readiness: `GET /api/processing/runs/{id}/plates`.
- Envelope `schemaVersion, jobId, workerId, attemptCount, provenance, payload`. The capability travels only in `X-Mavi-Lease-Capability`, with `X-Mavi-Attempt`, `X-Mavi-Worker-Id` and `X-Mavi-Content-Sha256` (ADR-013 item 2).
- Lease payload: `{analysisId, processingRunId, identity{…}, tracks:[{trackId, objectClass:"Vehicle", observations:[{observationId, role, evidenceRank, sizeBytes, sha256}]}]}`.
- `PlatePredictions` (canonical UTF-8 JSON, `mavi-plate-predictions-v1`): per leased crop, exactly once:
  - `scored` or `abstained{reason}`;
  - every detector box with score;
  - every OCR output with all `k` readings and confidences, plus per-character scores where the model emits them;
  - summary inputs and decisions.
- A worst-case size bound is enforced against the 64 MiB upload cap, as `visual-attribute-artifact-bound-v1` does (vector `plate-artifact-bound-v1.json`).
- Completion body: relational facts (§5.1) whose content must equal the artefact's decisions. The platform validates the facts against the artefact using a streaming reader, never by re-serialising.
- JSON schemas go in `contracts/schemas/plate-*.schema.json`, with examples and digest vectors in `contracts/examples` and `contracts/test-vectors`. The attribute plane has none; plates adds them because it is a new cross-language contract.

### 5.4 Search API (PR-4)

`GET /api/tracks` gains two keys, added to `SupportedQueryKeys`, `TrackSearchContractRules` and the cursor filter fingerprint:

| Key | Values | Rules |
|---|---|---|
| `plateText` | string | Normalised by v1. Must yield 3–15 characters of `[A-Z0-9]`; otherwise 400 `track_search_invalid`. Implies `objectClass=Vehicle` (as `objectSubclass` does in `TrackSearchQuery.Canonical`) |
| `plateMatch` | `contains` (default) \| `prefix` \| `exact` | Only with `plateText` |

- **Semantics:** a Track matches when the default plate analysis of its run has a `plate_track_texts` row whose `normalised_text` matches. Matching is literal on normalised text: no confusable expansion, no fuzzy distance.
- Combines (AND) with every existing predicate. With analytics predicates, the single-camera analytics scope stays authoritative (ADR-013 §16). Plate-only searches span cameras.
- **Ordering:** unchanged (`StartTimestampUtc DESC, Id DESC`), deterministic. Relevance ordering is out of scope for v1.
- **Cursor:** v4 signed cursor as specified by ADR-013 §16, implemented here for the first time. It pins:
  - the snapshot position;
  - the plate identity fingerprint (64 hex), tagged with its capability so the attribute search can reuse v4 later without a v5;
  - plate coverage counts;
  - the analytics identity when analytics predicates are combined.
- Encoded length is bounded and contract-tested (≤ 1024 characters).
- **Response additions** (omitted when null, following the established optional-member pattern):
  - item `plate`: `{matchedText, matchKind, supportCount, plateObservationCount, distinctTextCount, maxConfidence, bestPlateObservationId}`;
  - root `plateCoverage`: `{identityFingerprint, vehicleTracksInScope, ready, pending, failed, stale, notConfigured}`.
  - Coverage is always returned when `plateText` is present, so an empty result is never read as "no such plate".
- **Track detail** (`GET /api/tracks/{id}`) gains `plates` for Vehicle Tracks:

```
plates: {
  readiness: NotConfigured|Pending|Ready|Failed|Stale,
  trackOutcome?: Analysed|Unavailable, unavailableReason?,
  agreement?: none|single|consistent|conflicting,
  texts: [ {normalisedText, supportCount, maxConfidence, bestPlateObservationId} ],
  observations: [ {plateObservationId, sourceObservationId, role, offsetMs, sourceFrameNumber, timestampUtc,
                   box{x,y,width,height,cropWidth,cropHeight}, detectorConfidence, outcome,
                   readings:[ {rank, rawText, rawLineCount, normalisedText?, normalisationOutcome, confidence, formatClass} ] } ],
  provenance: {analysisId, plateDetectorModelPackId, ocrModelPackId, normalisation, summaryPolicy, completedAtUtc}
}
```

- Person Tracks omit `plates`, because the capability is not applicable. Wire tests pin the exact member lists.

### 5.5 Privacy and logging

- Plate text is a potentially identifying cue. Access follows the existing Track/evidence boundary.
- `plateText` values are never written to structured logs or audit payloads; only the presence of the predicate and the counts are. PR-4 adds a log-redaction test.
- Retention follows evidence retention (ADR-013 §19 trigger). A dedicated plate retention/access policy is a **Production** precondition, not a Stage-4 Development one.

---

## 6. UI integration (Stage 3.5 architecture reused; no new route, workspace or dashboard)

The UI-spec amendment (v2.2) lands in PR-4, before any UI code (ADR-013 §18). It fills the §29 ANPR row and adds:

1. **Search** (`SearchFilterRail.tsx`, Scope section):
   - a "Plate text" field with a Contains / Starts with / Exact control;
   - helper text "Spaces and dashes are ignored; letters are not substituted";
   - validation from `commitDraft`.
   - The committed chip reads `Plate contains KA01`. The URL is the state (`searchState.ts`).
2. **Results header:** the existing `CoverageStrip` line, for example "Plate readings available for 812 of 840 vehicle tracks in scope · 28 pending".
3. **Result row** (one line, §16; plain secondary text per the §29 attributes rule; no new badge):
   - `Read as KA01AB1234 · 3 of 4 readings · 92 %`.
   - The matched substring is shown with an underline as well as weight, so the cue is not colour alone.
   - A conflict appends `· 1 other reading`.
   - Wording is always "Read as", never "Plate:".
4. **Inspector and Review** — a new `TrackPlateReadings.tsx` in `features/video-review/`, composed in `TrackInspector.tsx` and the `VideoReviewPage.tsx` evidence rail:
   - Distinct texts with support count and max confidence (one decimal in the inspector, §24).
   - Per plate observation:
     - the plate region of the sealed evidence crop, rendered client-side from the existing content URL;
     - raw text and normalised text, labelled;
     - confidence, role and offset `mm:ss.t`.
   - "Unreadable plate" entries.
   - States via `StateRegion`: Pending, No plate found in the evidence, Unavailable, Not configured, Stale.
   - Selecting an observation selects its source crop in `TrackEvidenceSet` and its existing timeline marker. Seeking uses the existing marker action, so there is no new seek pattern.
5. **Provenance tier:** `ProvenancePanel` lists the plate analysis, both Model Pack ids, normalisation and summary policy.
6. **Why it matched:** the row's matched text and the inspector's highlighted text group, following `TrackAnalyticsExplanation`.

Stage 3.5 §34 items 1–17 apply unqualified. The visual sweep gains fixtures for:
- ready-consistent;
- conflicting;
- unreadable;
- pending;
- no plate found;
- not-configured;
- long raw text;
- two-line.

---

## 7. Implementation PR sequence

Two tracks run in parallel. **Track M** (measurement and selection: PR-1 → PR-2) needs no product change. **Track P** (product: PR-3 → PR-4 → PR-5) runs on a deterministic fixture inferencer and needs no selected model. PR-6 joins them.

```
PR-1 adequacy + plate benchmark harness ──► PR-2 model selection events ──┐
PR-3 plate lifecycle (fixture) ──► PR-4 search API + spec ──► PR-5 UI ───┴──► PR-6 real packs + runtime + Stage-4 Dev exit
```

### PR-1 — Plate benchmark harness and evidence-adequacy verdict

- **Outcome:** a measured answer to "is existing evidence good enough for ANPR?", and reusable plate evaluation.
- **Files:**
  - `tools/benchmarks/capabilities/plates/{truth.py, association.py, evaluator.py, adequacy.py, queries.py}`
    - ground truth: plate polygon, text, line count, vehicle link and stratum labels;
    - evaluators A–D;
    - deterministic query generator.
  - `tools/benchmarks/datasets/{indian_lpr_wild.py, ufpr_alpr.py, rodosol_alpr.py, ccpd.py}`: adapters with explicit `exact/subset/unsupported` mappings.
  - `tools/benchmarks/plates/normalisation.py` and `contracts/test-vectors/plate-normalisation-v1.json` (v1 frozen here).
  - Evidence export for E-B, following the `SubclassMeasurementExporter` pattern.
  - `docs/qualification/stage4/{benchmarks/*.descriptor.json, adequacy-protocol.md, adequacy-result.md}` and the ADR-017 release records.
  - The register `docs/reviews/2026-10-12-stage4-anpr-ocr-acceptance.md`.
- **Dependencies:** none. The two measuring-instrument OCRs run in a Development benchmark environment declared in `tools/benchmarks/plates/requirements-candidates.txt`, which needs a policy `managedSources` entry classified dev/test.
- **DB, API, model, runtime changes:** none to the product.
- **Tests:** adapter and mapping unit tests on synthetic fixtures; association determinism; the encoder-equivalence test (adequacy uses `PRODUCTION_ENCODER_POLICY` byte-identically); normalisation vectors; query-generator determinism.
- **Acceptance:** the protocol is hashed before results; E-A and E-B executed; a verdict per §3.4 with strata.
- **Exit:** register rows P1–P3 PASS.

### PR-2 — Plate detector and OCR Model Selection Events (technical decision)

- **Outcome:** technically ranked compositions, with exact bytes and evidence.
- **Files:**
  - `docs/qualification/model-selection/{plate-detector,ocr}/msr-*-2026-01{.md,-evidence-ledger.json}`;
  - `plates-2026-01-protocol.md`;
  - `tools/benchmarks/plates/candidates/` (adapters for benchmark execution only);
  - the gate sets `plate-detector-v1` and `ocr-v1`, plus the `-model-selection` gates, in `config/acceptance/capability-gate-sets-v1.json`.
- **Dependencies:** PR-1.
- **Changes:** none to the product. Candidate runtimes stay in the benchmark environment only.
- **Tests:** `tools/qualification/model_selection_check.py` passes on the new records; hashes re-derived by `verify_repo`.
- **Acceptance:** §4.2 entry criteria met; protocol frozen; A–E executed; gates evaluated; `TECHNICAL_DECISION_RECORDED`; licence/deployment determinations recorded separately; the implementation composition is chosen by the owner.
- **Exit:** P4–P6 PASS. Events reach `QUALIFICATION_PENDING`, or `CLOSED` with `SELECTED_FOR_PACKAGING`.

### PR-3 — Plate analysis lifecycle with fixture inferencer (vertical, end to end)

- **Outcome:** after a run completes, its Vehicle Tracks receive (fixture) plate observations through the real lease, evidence, upload and completion path. Plate failure is shown to be isolated.
- **Files:**
  - .NET Domain: `Mavi.Domain/Plates/{PlateAnalysis,PlateFacts,PlateReadiness}.cs`.
  - .NET Application: `Mavi.Application/Modules/Plates/{PlateOptions, Release/PlateRelease.cs, Completion/*Validator.cs, PlateNormalisation.cs}`.
  - .NET Infrastructure: `Mavi.Infrastructure/Plates/{PlateCompletionService,PlateFactWriter,PlateIntegrityMonitor}.cs`, `Persistence/Repositories/PlateLifecycle.cs`, configurations, migration, `ArtifactType.PlatePredictions`, `Storage/PlateStagingJanitor.cs`.
  - .NET API: `Mavi.Api/Endpoints/PlateEndpoints.cs`, `Mavi.Api/Plates/PlateHostedService.cs`, the re-analysis endpoint.
  - `Mavi.Contracts/Worker/Plates/*`; `contracts/schemas/plate-*.schema.json` with examples and vectors.
  - Python: `src/vision/mavi_vision/plates/{main,supervisor,client,runner,pipeline,inference,predictions,contracts,settings}.py`, `adapters/fixture.py`.
  - `capabilities.py` and `resolver.py`: add `plate-detector` and `ocr` (fixture input contract `evidence-crop-jpeg/RGB`), and the role `plates`.
  - The ADR-013 Stage-4 implementation amendment (§9 B1–B4).
  - The runbook section in `docs/runbooks/local-development.md`.
- **Shared code:** only primitives with identical semantics move out of the attribute namespace: `LeaseFencedStream`, and the lease-scoped evidence-read handler, generalised by parameter. Attribute integration tests run unchanged as the no-regression guard. Aggregates, facts and contracts stay capability-specific.
- **Dependencies:** none on PR-1 or PR-2.
- **DB:** additive migration (§5.1). **API:** worker plane, readiness and re-analysis. **Model/runtime:** fixture only, under the Development binding mechanism. The fixture role runs from the existing vision family in Development and is refused in Production.
- **Tests:**
  - domain state machine;
  - lease fencing, expiry, reclaim and the publication window;
  - evidence digest mismatch → `Unavailable` plus integrity signal; transient → retry;
  - artefact bound and fact/artefact equality;
  - supersession and default derivation;
  - re-analysis bounds and idempotency;
  - worker crash isolation (VisionJob and attribute units unaffected);
  - Python import boundary (no torch/mmcv);
  - normalisation vectors in both languages;
  - migration test.
- **Acceptance:** an end-to-end integration test, run → fixture readings → readiness `Ready`, plus a crash test proving isolation.
- **Exit:** P7–P9 PASS.

### PR-4 — Plate search API, v4 cursor, indexes and UI-spec amendment

- **Outcome:** `GET /api/tracks?plateText=KA01` returns matching Vehicle Tracks with match explanation and coverage. Track detail carries `plates`.
- **Files:**
  - `TrackEndpoints.cs`, `TrackSearchContractRules.cs`, `TrackSearchResponse.cs`, `TrackDetailResponse.cs`, new `TrackPlateContracts.cs`;
  - `TrackSearchQuery.cs`, `TrackSearchService.cs`;
  - `TrackSearchRepository*.cs` (plate EXISTS plus a per-page explanation);
  - `TrackCursorCodec.cs` (v4);
  - migration `AddPlateSearchIndexes` (`CREATE EXTENSION IF NOT EXISTS pg_trgm` and the chosen indexes);
  - the dependency policy / offline inventory note that `pg_trgm` is required (contrib, PostgreSQL 18), plus a `Test-MaviEnvironment` check;
  - UI spec v2.2 (§6).
- **Dependencies:** PR-3.
- **Tests:**
  - query-key whitelist and validation (length, characters, match mode);
  - normalisation parity with the vectors;
  - contains/prefix/exact semantics on fixtures, including conflicting and unreadable Tracks;
  - coverage counts;
  - cursor v4 tamper, replay and length;
  - snapshot stability under a mid-pagination supersession;
  - combination with analytics and subclass predicates;
  - existing searches return identical populations (regression);
  - exact wire-member tests;
  - query-shape (no N+1);
  - `EXPLAIN` plan test asserting index use;
  - log redaction.
- **Acceptance:** search precision/recall = 1.0 on the deterministic fixture corpus (the literal matcher is exact by construction); p95 budget (§2.8) met at the seeded scale.
- **Exit:** P10–P11 PASS.

### PR-5 — Operator UI for plate search and plate evidence

- **Outcome:** an operator searches by plate, sees uncertain and conflicting matches as candidates, opens the Track, inspects plate regions and readings, and seeks the source video.
- **Files:**
  - `api/tracks.ts`;
  - `features/visual-search/{SearchFilterRail,searchState,searchValidation,CommittedFilterChips,TrackResultList,TrackResultCard,TrackInspector}.tsx|ts`;
  - `features/video-review/{TrackPlateReadings.tsx, VideoReviewPage.tsx}`;
  - `ProvenancePanel`;
  - test fixtures `test/trackEvidenceFixtures.ts`;
  - visual-harness state fixtures (§6 list).
- **Dependencies:** PR-4.
- **Tests:** unit and feature tests (modelled on `vehicleSubclass.test.tsx`); URL round-trip; keyboard journey "plate search → inspect → seek"; §34 sweep on the new fixtures; a11y assertions (non-colour cues).
- **Acceptance:** the journey passes; the sweep is green; no new route.
- **Exit:** P12 PASS.

### PR-6 — Selected Model Packs, Runtime Pack family and Stage-4 Development exit

- **Outcome:** real ANPR on real evidence, installed offline.
- **Files:**
  - `models/manifests/<detector>-v2.json` and `<ocr>-v2.json`;
  - `models/qualifications/*.json` (Development, `unverified`, gate evidence citing the closed MSRs by hash);
  - `src/vision/runtime/plates-<engine>-v1/{runtime.json,*.lock,*.requirements.txt}`;
  - binding (Development binding first);
  - `mavi_vision/plates/adapters/<detector>.py`, `<ocr>.py`;
  - dependency policy entries and the offline binary catalog;
  - `tools/setup/*` installers and `Test-MaviEnvironment`;
  - a CI workflow for the family (pattern `task12-offline-bundle.yml`);
  - runbooks.
- **Dependencies:** PR-2 (closed or qualification-pending with an implementation composition) and PR-5.
- **Tests:**
  - adapter golden tests on pinned crops;
  - offline install from the kit on a disconnected host;
  - pack hash and licence-notice verification;
  - READY/fail-closed on a missing pack;
  - CPU determinism;
  - an end-to-end Development run on real processed video, with Track-level D re-measured through the product path and agreeing with PR-2 within the protocol tolerance;
  - engineering measurements with the detector co-resident.
- **Acceptance:** P13–P16.
- **Exit:** Stage 4 Development capability complete. MSR addenda record the qualification outcome.

---

## 8. Testing and qualification matrix (Stage-4 register rows, created by PR-1)

| Row | Evidence | PR | Class |
|---|---|---|---|
| P1 | Plate harness: adapters, mappings, association and evaluators, with tests; release records per ADR-017 | 1 | Development |
| P2 | Normalisation v1 frozen; cross-language vectors | 1 | Contract |
| P3 | Evidence-adequacy verdict (§3.4) with strata; protocol hashed before results | 1 | Development measurement |
| P4 | MSR events PLANNED → PROTOCOL_FROZEN; entry criteria §4.2 met | 2 | Selection |
| P5 | A–E measured; gates; technical ranking by D; consistent-wrong gate | 2 | M-D / M-E |
| P6 | Licence/deployment determinations per profile; owner implementation choice | 2 | Qualification input |
| P7 | Plate lifecycle: lease, fencing, evidence integrity, three-phase completion, supersession | 3 | Integration |
| P8 | Failure isolation (VisionJob, attributes and runs unaffected by a plate crash or OOM) | 3 | Integration |
| P9 | Bounded re-analysis; idempotent queueing | 3 | Integration |
| P10 | Search semantics, coverage, cursor v4, regression of existing populations, wire tests | 4 | Contract / integration |
| P11 | Index plan and p95 budget at seeded scale; log redaction | 4 | Engineering |
| P12 | UI journey, §34 sweep and a11y on plate states | 5 | Frontend |
| P13 | Model/Runtime Packs: hashes, licence notices, `verify_repo`, disconnected install | 6 | Offline |
| P14 | Real end-to-end Track-level D through the product path, consistent with P5 | 6 | Development measurement |
| P15 | Engineering budget and 500-camera projection (M-E, projected; not a scale qualification) | 6 | Engineering |
| P16 | Exact-head CI green (quality, Task 10, Task 17, applicable workflows) | every PR | CI |

- **Development vs Production.** Every row is Development or engineering evidence (ADR-009, ADR-017 §9).
- Production qualification of plate search needs, in addition:
  - a protected, owner-captured Indian holdout under ADR-015 §3–§4;
  - qualified Runtime Pack variants;
  - a plate retention/access policy;
  - the Production audit profile.
- **No Stage-4 PR may claim Production readiness.**

---

## 9. Dependencies, risks and bounded decisions

### 9.1 Engineering decisions taken by this plan (recorded in the ADR-013 Stage-4 implementation amendment, PR-3)

| # | Decision | Trade-off accepted |
|---|---|---|
| B1 | Capability-specific `PlateAnalysis` aggregate mirroring the attribute plane; only identical primitives shared | Some structural duplication, in exchange for no generic job framework (ADR-013 alternative G) |
| B2 | Plate crop held **by reference** (sealed source crop + sealed box), not as new image bytes | The UI renders the region client-side; there is no separately downloadable plate image. In exchange there is one integrity source, no new upload protocol and no storage growth |
| B3 | Per-reading relational rows (`plate_observations`, `plate_readings`) as well as the sealed artefact | More rows than attributes' Track-level-only facts (ADR-013 §13). The operator must see every reading, and these rows are operator-facing final semantics; raw scores stay in the artefact |
| B4 | All evidence roles, including the Representative, are processed; role is recorded | A fallback Representative may yield low-confidence readings; P3 measures this per role and the profile may exclude it |
| B5 | Literal normalised matching; no confusable expansion in v1 | Recall loss on O/0-type OCR errors, measured in D. A future explicit, operator-visible similar-character mode needs its own versioned policy |
| B6 | Time ordering, not relevance, for plate search | Strongest matches are not first, in exchange for a stable snapshot cursor; the row explains match strength |

### 9.2 Owner decisions (genuinely consequential; none blocks PR-1, PR-3, PR-4 or PR-5)

| # | Decision | When needed |
|---|---|---|
| O1 | If no labelled Indian ALPR video benchmark exists: accept partial Indian Track-level evidence, or approve a bounded labelling of Development footage (ADR-017 §2) | At PR-2 `PLANNED` |
| O2 | Implementation composition among licence-cleared, gate-passing candidates (MSR §4) | End of PR-2 |
| O3 | If the adequacy verdict is INADEQUATE: which, if any, of §3.5 X1–X3 to pursue | After PR-1 |
| O4 | The 500-camera workload model (re-use S2c's, or declare one) | Before PR-2 `PROTOCOL_FROZEN` |

### 9.3 Risks

| Risk | Mitigation |
|---|---|
| Evidence crops too small or too compressed for plates | Measured first (PR-1); bounded alternatives §3.5; no silent VisionJob change |
| Indian domain gap in public data (stylised fonts, two-line, Devanagari) | Indian still benchmarks first; strata reporting; non-alphanumeric readings are rejected, not dropped; O1 |
| Benchmark contamination (pretrained models trained on the same sets) | Exposure recorded per candidate per dataset (ADR-017 §8); exposed scores marked reference |
| Consistent wrong readings presented convincingly | Gate on the consistent-wrong rate; "Read as" wording; agreement shown; never "confirmed" |
| New runtime families (ONNX Runtime, Paddle, Tesseract) | Separate `plates-*` family; vision lock untouched; offline kit verification in PR-6 |
| Licence constraints (for example AGPL weights) | Separate licence axis; the declared non-commercial profile; never in the technical ranking |
| Trigram index cost and short queries | Minimum 3 characters; measured plan in PR-4 |
| GPU contention on a 4 GiB host | The `plates` role defaults to CPU; co-residency measured in PR-2/PR-6 |
| Plate text as personal data | Access boundary, log redaction, retention trigger; Production policy precondition |

---

## 10. Immediate first implementation task

**Start PR-1** on a branch from `main`:

1. Create the Stage-4 register (§8 rows) and `docs/qualification/stage4/adequacy-protocol.md`, containing §3.4's rules, strata, support floors and the instrument identities to pin. Commit and hash the protocol before any data is read.
2. Run the ADR-017 §1 benchmark search. Record what was found, including any Indian ALPR video set. Write the release records and intake the first two releases: *Indian Licence Plate Dataset in the wild* and UFPR-ALPR.
3. Implement `tools/benchmarks/capabilities/plates/truth.py`, the two adapters and `normalisation.py`, with vectors and tests on synthetic fixtures.
4. Implement `adequacy.py` E-A over the production encoder, then E-B over the harness producer path and the evidence export.
5. Execute, and record `adequacy-result.md` with the verdict and strata.

PR-3 can start at the same time; it needs nothing from PR-1.
