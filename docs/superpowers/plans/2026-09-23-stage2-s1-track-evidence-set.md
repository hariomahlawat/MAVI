# MAVI Stage 2 — S1 Track Evidence Set Implementation Plan

**Status:** Draft implementation-grade plan for independent review  
**Date:** 2026-09-23  
**Baseline:** `main@6809606e596d121186b5244869760073fe82072a` — PR #73 merged; Stage-2 architecture frozen  
**Governing architecture:** ADR-006, ADR-013, ADR-014, Stage-2 parent plan, Stage-2 acceptance register  
**Acceptance scope:** Stage-2 register **B1–B6** only. S1 MUST NOT implement VisualAttributeAnalysis, real attribute models, attribute search, or component-binding v2.

---

## 1. Purpose

S1 upgrades the raw recorded-video processing path from a single Representative thumbnail per Track to the bounded, deterministic **Track Evidence Set** defined by ADR-013.

The work is deliberately upstream of Visual Attributes. Its product is reusable accepted evidence with stable semantics for later attributes, OCR/ANPR, embeddings and other post-Track intelligence.

S1 closes only when MAVI can truthfully say:

1. Track evidence is selected during the single VisionJob decode pass.
2. the tracker exposes model-neutral exact-once Track retirement semantics;
3. retired Tracks are fully finalised and released from live memory;
4. every accepted Track has one Representative and may have bounded supplemental evidence;
5. evidence selection, encoding and run-level admission are deterministic and bounded;
6. completion schema/digest v3 expresses the evidence set without unbounded request growth;
7. the platform validates, seals and persists the evidence transactionally;
8. Track detail exposes all accepted observations while preserving the Representative convenience path;
9. relevant Task-10/E2E qualification evidence is rebound to the changed raw-processing pipeline.

S1 is not an attribute-inference slice.

---

## 2. Frozen architecture inputs

S1 MUST implement, not reinterpret, these ADR-013 decisions:

### Evidence roles

- `Representative` — mandatory, rank 0, primary display evidence.
- `NearView` — largest qualified non-duplicate subject view; analytic-resolution carrier.
- `EarlyDiverse` — qualified diverse view in the first temporal third.
- `LateDiverse` — qualified diverse view in the last temporal third.

### Initial encoding bounds

- at most 4 roles per Track;
- maximum long edge 1024 px;
- JPEG quality target 85;
- Representative cap 64 KiB;
- supplemental crop cap 160 KiB;
- reduction floor 128 px long edge / JPEG quality 50;
- total sealed EvidenceCrop quota 1 GiB per ProcessingRun;
- existing 512 MiB v2 aggregate bound becomes the trajectory/other-artifact quota;
- existing 64 MiB per-artifact cap remains.

### Retirement semantics

The tracker adapter owns backend-specific retirement knowledge.

A retired MAVI Track id:

- is emitted exactly once;
- is never emitted in the same update as an active candidate for that id;
- can never appear in a later update;
- releases its native-id → MAVI-id mapping;
- is replaced by a fresh MAVI id if a backend native id is ever reused;
- is emitted in deterministic order.

For ByteTrack, retirement occurs only after the lost-track budget has become impossible to reassociate, including the one-accepted-frame safety interval frozen in ADR-013.

At end-of-stream, every still-live Track is finalised without requiring a synthetic retirement event.

### Whole-Track finalisation

Retirement finalises:

- trajectory;
- confidence/count summaries;
- Representative;
- supplemental evidence;
- staged artifacts/descriptors.

A retired Track no longer retains its trajectory list or encoded candidate bytes in live memory.

### Platform boundary

Python produces attempt-scoped staging artifacts and descriptors.

The .NET platform:

- validates the completion;
- verifies/streams/seals accepted evidence under ADR-006;
- persists domain rows transactionally;
- keeps the existing compensation semantics for newly sealed evidence if DB commit fails.

---

## 3. Non-goals

S1 MUST NOT add:

- VisualAttributeAnalysis;
- attribute worker or attribute lease endpoints;
- capability-binding v2 implementation;
- person/vehicle classifier Model Packs;
- attribute search predicates or cursor v4;
- prediction-artifact upload;
- attribute outcomes/persistence;
- OCR/ANPR;
- embeddings;
- Entity/ReID logic;
- historical evidence-only regeneration;
- automatic historical backfill.

Those belong to later Stage-2 slices.

---

## 4. Repository reality at S1 entry

The merged code currently has these relevant properties:

### Python tracker/pipeline

- `Tracker.update(frame, detections) -> Sequence[TrackCandidate]`; no retirement signal.
- `ByteTrackTracker` maintains per-class native-id → MAVI-id maps for the full attempt.
- the deterministic `FixtureTracker` implements the old candidate-only contract.
- `VideoProcessor` stores all Track accumulators until decode ends.
- each accumulator retains its full trajectory list and one raw RGB Representative crop.
- `prepare_track()` encodes the Representative only at finalisation.
- `ArtifactPublisher.publish_track()` writes one thumbnail and one trajectory artifact.
- `StagingArtifactStore.cleanup()` deletes only the current attempt subtree.

### Worker/platform contract

- `WorkerContractRules.SchemaVersion == "2.0"`.
- completion is bounded to 10,000 Tracks, 32 MiB request body, 64 MiB/artifact, 512 MiB aggregate evidence.
- each Track carries one `Representative` with one thumbnail descriptor and one trajectory descriptor.
- the completion digest is canonical/order-independent after validator normalization.

### Domain/persistence

- `ObservationType` still declares `TrackStart, Representative, BestQuality, TrackEnd`.
- only Representative is actually persisted.
- `Observation` has no EvidenceRole, EvidenceRank or SelectionScore.
- `ArtifactType` has Thumbnail and TrackTrajectory, not EvidenceCrop.
- `ProcessingResultStore` seals exactly one thumbnail + trajectory per Track.
- `Track.RepresentativeObservationId` is the existing direct convenience link.

### Read/UI

- Track detail is Representative-centric.
- frontend Track contracts and Investigation/Review flows assume one Representative observation.
- existing Evidence Player remains the primary video surface and MUST NOT be replaced by an image-gallery workflow.

This is the migration starting point.

---

## 5. S1 implementation strategy

S1 should be implemented as **four mergeable sub-slices**. Each sub-slice leaves `main` buildable/testable and does not expose a half-supported external contract.

### S1.1 — Tracker lifecycle + whole-Track retirement infrastructure

**Goal:** establish the lifecycle/memory foundation while preserving completion schema v2 externally.

### S1.2 — Deterministic Evidence Set + completion contract v3

**Goal:** produce bounded evidence roles and move the worker/platform completion boundary to v3 coherently.

### S1.3 — Persistence/read API + minimal Evidence Set UI

**Goal:** expose accepted observations without changing Stage-2 attribute semantics.

### S1.4 — hardening, bound proofs and qualification rebinding

**Goal:** close B1–B6 with exact-head evidence.

The implementation PRs may be separate, but all remain inside Stage-2 S1 and the Stage-2 acceptance register remains the authority.

---

# 6. S1.1 — Tracker lifecycle and retirement infrastructure

## 6.1 Model-neutral tracker result

Modify:

- `src/vision/mavi_vision/tracking/interfaces.py`
- `src/vision/mavi_vision/tracking/fixture.py`
- `src/vision/mavi_vision/tracking/bytetrack.py`

Introduce a frozen result value conceptually equivalent to:

```python
@dataclass(frozen=True, slots=True)
class TrackerUpdate:
    candidates: tuple[TrackCandidate, ...]
    retired_track_ids: tuple[str, ...]
```

The exact class name may differ, but the semantic shape MUST be explicit.

`Tracker.update(...)` returns one update object, not an ambiguous pair or side-channel callback.

Validation/invariants:

- candidate ids unique within one update;
- retired ids unique within one update;
- candidate/retired sets disjoint;
- retired ids canonical;
- adapter never emits the same retired MAVI id twice;
- adapter never emits a retired MAVI id again as a candidate;
- retired ids sorted deterministically.

Do not expose native backend ids through this contract.

## 6.2 ByteTrack retirement ownership

`ByteTrackTracker` remains the only place that understands ByteTrack lost-buffer semantics.

Add attempt-scoped per-native-id lifecycle state sufficient to record:

- MAVI id;
- last emitted source frame/time;
- whether the mapping has retired.

Prefer deleting retired mapping entries rather than retaining an unbounded retired map. No-reuse of MAVI id is guaranteed by monotonic per-class MAVI counters.

Retirement rule:

- never retire on first disappearance;
- never retire while backend reassociation remains possible;
- if no explicit backend-removal event exists, retire only after elapsed accepted media time exceeds the configured lost budget by at least one accepted-frame interval;
- if a native id is emitted again after its old mapping was retired, allocate a fresh MAVI id;
- never retire and emit the same MAVI id in one update.

The implementation MUST derive time/frame progression from accepted frames already validated by the adapter. `VideoProcessor` MUST NOT import/use `ByteTrackProfile.lost_track_buffer`.

## 6.3 FixtureTracker parity

`FixtureTracker` must support scripted retirement so the core pipeline tests do not require the native `trackers` package.

Fixtures should be able to express:

- active candidate;
- temporary absence;
- reappearance before retirement;
- retirement;
- later backend/native-id reuse producing a fresh MAVI id analogue where relevant;
- end-of-stream with still-live tracks.

Do not make fixture semantics weaker than production semantics.

## 6.4 Whole-Track finalisation in VideoProcessor

Modify:

- `src/vision/mavi_vision/pipeline/process_video.py`
- `src/vision/mavi_vision/pipeline/finalization.py`
- `src/vision/mavi_vision/storage/artifact_publisher.py`

Separate accumulator state into:

**live Track state**
- object class;
- offsets;
- confidence accumulator;
- observation count;
- trajectory-in-progress;
- evidence candidate state.

**finalised Track state**
- scalar metadata;
- accepted/staged descriptors;
- no trajectory list;
- no raw/encoded candidate payloads.

On each tracker update:

1. process active candidates;
2. perform evidence-candidate replacement;
3. after the update is validated, finalise each retired id;
4. stage the whole Track once;
5. replace/remove the live accumulator.

At end-of-stream:

- finalise all remaining live Tracks in deterministic Track-id order.

Finalisation MUST remain lease-fenced immediately before every external staging side effect.

## 6.5 Cross-attempt staging cleanup

Modify `StagingArtifactStore` / backend abstractions rather than using ad-hoc filesystem traversal from `VideoProcessor`.

Required behavior when attempt N begins:

- cleanup own attempt prefix as today;
- remove earlier attempt prefixes for the **same job** that are now fenced out;
- never remove a later attempt;
- never remove another job;
- operation remains symlink/reparse-safe under the existing hardened backend model;
- cleanup failure follows the existing pipeline-configuration/failure policy rather than silently continuing with unbounded stale bytes.

Add an explicit store method with job-scoped semantics; do not broaden ordinary `cleanup()` ambiguously.

## 6.6 S1.1 tests

Extend/add:

- `src/vision/tests/test_bytetrack_adapter.py`
- `src/vision/tests/test_fixture_detection_tracking.py`
- `src/vision/tests/test_process_video.py`
- `src/vision/tests/test_lease_ownership_matrix.py`
- staging backend/store tests on POSIX and Windows abstractions.

Mandatory discriminating cases:

1. active → absent within lost budget → same MAVI id reappears;
2. active → absent beyond safe retirement → retired exactly once;
3. retired native id re-emitted → fresh MAVI id;
4. candidate and retired id cannot overlap in one update;
5. retirement ordering deterministic;
6. poisoned adapter never produces retirement after failure;
7. new adapter resets all lifecycle state/counters/maps;
8. finalised Track trajectory/candidate payloads leave live memory;
9. end-of-stream drains remaining live Tracks;
10. lease lost before retirement staging → no unauthorized publish;
11. lease lost during finalisation → existing attempt-isolation semantics hold;
12. attempt N cleanup removes N-1 leftovers but not N+1/other jobs.

### S1.1 exit condition

The tracker/pipeline lifecycle is correct and tested while external v2 completion semantics remain unchanged.

**Qualification consequence:** unchanged wire output does not make S1.1 qualification-neutral. Retirement-time whole-Track finalisation changes the processing implementation, staging timing and memory/resource behaviour. S1.1 therefore runs the normal Quality gate plus the relevant Task-10 CPU regression/runtime tests before merge and records the exact head. It does not update the Stage-2 B6 qualification claim yet; final pipeline-profile rebinding occurs only after the complete v3 Evidence Set is frozen in S1.4.

---

# 7. S1.2 — Evidence selector and completion contract v3

## 7.1 Evidence domain types in Python

Evolve `src/vision/mavi_vision/common/analytical.py` away from a Representative-only internal shape.

Introduce:

- `EvidenceRole` enum;
- immutable evidence candidate/observation value;
- encoded evidence payload/descriptors;
- `ProcessedTrack.observations` or equivalent bounded tuple;
- direct `representative` accessor/property retained for compatibility inside the worker.

Do not keep two independently authoritative collections.

Exactly one accepted observation has role Representative/rank 0.

## 7.2 Evidence selector module

Create a dedicated model-neutral selector module, e.g.:

`src/vision/mavi_vision/quality/evidence_selector.py`

Do not bury role selection inside `process_video.py`.

Responsibilities:

- candidate qualification;
- quality scoring inputs;
- overlap/occlusion proxy from concurrent boxes;
- temporal thirds;
- duplicate/separation test;
- deterministic role replacement;
- final role ordering;
- selection score.

The selector receives frame/Track facts; it does not call a learned model.

### Numeric policy

Create one versioned pipeline-profile section for the numeric values ADR-013 deliberately left to S1:

- detector-confidence floor;
- sharpness floor;
- frame-edge margin floor;
- maximum concurrent-box IoU;
- duplicate time/frame window;
- duplicate box-IoU threshold;
- minimum temporal separation;
- JPEG parameters and caps.

Do not scatter magic constants across selector/encoder/tests.

The profile id/version/SHA enters raw-processing provenance and therefore completion digest.

Before choosing numeric selector floors, record a small engineering measurement note/corpus. These are engineering selector parameters, not Stage-2 model-quality thresholds.

## 7.3 Crop extraction and deterministic encoder

Create one encoder path shared by all EvidenceRole values.

Algorithm:

1. crop source pixels using the authoritative normalized bounding box;
2. constrain long edge to ≤1024 while preserving aspect ratio;
3. encode JPEG at target quality 85;
4. if above role byte cap, deterministically reduce quality/dimensions;
5. never go below quality 50 or long edge 128;
6. if still oversized at floor:
   - supplemental role: omit;
   - Representative: fall back to next-best qualified Representative candidate;
7. if no Representative can be encoded for an accepted Track: fail the VisionJob result; do not publish a Track without mandatory evidence.

Encoding MUST be deterministic for the qualified Pillow/runtime graph and contract-tested by byte/hash on fixtures.

Do not repeatedly write replacement candidates to staging.

## 7.4 Run-level admission

At Track retirement, stage every selected candidate required to preserve global admission choice.

At end-of-run admission:

1. admit every mandatory Representative;
2. reject the run if mandatory Representatives alone exceed 1 GiB (this should be impossible under 10,000 × 64 KiB but remains an invariant);
3. process NearView candidates by SelectionScore desc / LocalTrackNumber asc;
4. then EarlyDiverse with same ordering;
5. then LateDiverse;
6. stop admitting supplemental candidates when the next candidate would exceed 1 GiB;
7. record candidate/admitted/omitted counts and bytes by role.

**Important implementation point:** LocalTrackNumber is platform-created today, while worker Track ids are deterministic strings such as `person-000001`. S1 MUST NOT invent a platform LocalTrackNumber before persistence. For worker-side deterministic admission, define the secondary key as the canonical worker Track id; because platform LocalTrackNumber is created from the validator's canonical Track ordering, add a contract test proving these orderings are equivalent. If they are not equivalent, amend the plan/ADR before implementation rather than silently drifting.

Omitted supplemental staging objects may be deleted after admission to reduce transfer/storage pressure; this cleanup must remain attempt-scoped and lease-safe.

## 7.5 Completion schema v3

Modify:

- `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`
- `src/platform/Mavi.Contracts/Worker/VisionJobCompleteContracts.cs`
- worker Pydantic/wire models and JSON schema under `src/vision`;
- `src/vision/mavi_vision/worker/client.py`;
- `src/platform/Mavi.Application/Modules/Intelligence/VisionResultValidator.cs`;
- `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingResultStore.cs` schema-version precheck/replay path;
- `src/platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs` only if its request/body/version routing currently assumes one schema;
- canonicalization/digest tests.

v3 Track completion carries:

- Track scalar data;
- trajectory descriptor;
- bounded observations array;
- each observation:
  - role;
  - rank;
  - source frame;
  - offset;
  - bounding box;
  - detector confidence;
  - selection score;
  - EvidenceCrop descriptor.

Remove the wire-level concept that only Representative owns a `thumbnail`.

### v3 validation rules

Fail closed on:

- unknown role;
- duplicate role;
- duplicate rank;
- missing Representative;
- Representative not rank 0;
- supplemental rank 0;
- >4 observations;
- role/rank inconsistency;
- invalid/non-finite score;
- duplicate source/frame evidence where policy forbids it;
- observation outside Track;
- wrong staging attempt/job;
- wrong evidence filename/key;
- wrong media type;
- per-role byte cap violation;
- EvidenceCrop aggregate >1 GiB;
- trajectory/other aggregate >512 MiB;
- artifact >64 MiB;
- >10,000 Tracks;
- body over the re-derived v3 request limit.

The completion digest v3 includes the canonical observations and all artifact descriptors.

## 7.6 v2/v3 compatibility policy

Do not perform a flag-day platform/worker deployment.

Recommended migration:

- the platform completion path accepts **v2 and v3** during the transition; this includes the early schema-version check in `ProcessingResultStore`, not only `VisionResultValidator`;
- all new S1 workers emit v3;
- a valid v2 Track normalizes internally to one Representative observation for validation/persistence semantics without rewriting historical rows;
- completed v2 jobs remain idempotently replayable against their original v2 digest;
- an in-flight v2 worker may complete only under the existing v2 bounds/semantics; it never fabricates supplemental Evidence Set coverage;
- v2 cannot produce supplemental evidence and cannot claim S1 B1–B5;
- the completion digest is version-domain-separated so a semantically similar v2/v3 payload cannot collide as the same replay identity;
- after all supported release profiles move to v3, removal of v2 write compatibility is a later explicit cleanup decision.

If repository deployment constraints make dual-version support unsafe or materially complex, stop and amend the plan before coding; do not simply change `SchemaVersion` globally and strand an in-flight v2 worker.

The digest algorithm/version must distinguish v2 from v3 canonical payloads.

## 7.7 Re-derive body bound

Before selecting the new request-body constant:

- generate a true worst-shape 10,000-Track v3 completion with four observation descriptors each;
- serialize through the actual worker model/JSON path;
- measure bytes;
- add bounded safety headroom;
- set `MaximumCompletionRequestBodyBytes` from measurement, not the earlier 250-byte estimate;
- pin the worst-shape serialized size with a contract test.

This is required before S1.2 closes.

---

# 8. S1.2 — Platform domain and persistence

## 8.1 Observation schema

Modify:

- `src/platform/Mavi.Domain/Intelligence/Observation.cs`
- `ObservationType.cs`
- `ObservationConfiguration.cs`
- EF model snapshot + new migration.

Preferred evolution:

- retire unused `TrackStart / BestQuality / TrackEnd` semantics from current writes;
- either replace `ObservationType` with the frozen EvidenceRole vocabulary or retain a compatibility conversion explicitly;
- add:
  - `EvidenceRank`;
  - `SelectionScore`;
- preserve source frame/time/bounding box/confidence;
- keep one crop artifact FK per observation.

Do not add a second role column if `ObservationType` itself becomes the authoritative EvidenceRole.

Database constraints:

- rank non-negative and bounded;
- selection score finite/range per selector contract;
- unique `(track_id, evidence_rank)`;
- unique `(track_id, observation_type)` for current four single-valued roles;
- exactly one Representative/rank 0 is enforced as far as practical in domain + transaction validation;
- crop FK remains immutable after attachment.

Migration must preserve existing Representative observations as Representative rank 0. Historical Tracks do not invent supplemental observations.

## 8.2 Artifact type

Modify `ArtifactType`.

New evidence crops use `ArtifactType.EvidenceCrop`.

Migration policy for historical `Thumbnail` artifacts:

- do not rewrite historical artifact rows merely to rename them;
- current Representative observations may continue referencing historical Thumbnail artifacts;
- new v3 Evidence Set writes use EvidenceCrop;
- read contracts abstract this difference from the UI.

This avoids unnecessary historical evidence mutation.

## 8.3 ProcessingResultStore

Extend sealing/persistence transactionally.

For each validated v3 Track:

1. seal trajectory;
2. seal each **admitted** EvidenceCrop descriptor;
3. create Track;
4. create all Observation rows;
5. attach each crop artifact;
6. attach Track.RepresentativeObservationId to the Representative row;
7. save;
8. allocate/publish visibility sequence exactly as today;
9. commit;
10. on failure, compensate every newly sealed accepted evidence object in reverse order.

Never persist an Observation for an omitted supplemental candidate.

Accepted evidence keys include role or observation rank sufficiently to avoid collisions while retaining SHA-bound identity.

The store must remain idempotent for replay.

## 8.4 Validator/store scale tests

Add worst-shape tests for:

- 10,000 Tracks × Representative;
- 10,000 Tracks × four observations where byte quota permits descriptor validation but admitted set remains bounded;
- role duplicates;
- aggregate EvidenceCrop accounting separate from trajectory accounting;
- rollback compensation over multiple evidence objects per Track;
- idempotent replay v2 and v3;
- failed sealing midway through one Track's evidence set;
- transaction failure after all evidence is sealed.

---

# 9. S1.3 — Track detail/read contracts and minimal UI

## 9.1 API contract

Modify:

- `src/platform/Mavi.Contracts/Api/Tracks/TrackDetailResponse.cs`
- Track application/repository projection;
- `src/platform/Mavi.Api/Endpoints/TrackEndpoints.cs`;
- relevant API/application tests.

Add bounded:

`observations[]`

Each item includes:

- Observation id;
- EvidenceRole;
- EvidenceRank;
- source frame;
- offset/timestamp;
- bbox;
- confidence;
- selection score;
- evidence/crop URL or artifact retrieval reference consistent with existing authorization.

Retain the existing direct Representative field/reference for compatibility/convenience, but derive it from the same Representative observation rather than maintaining a second independent representation.

Historical v2 Tracks naturally return one observation.

## 9.2 Evidence retrieval security

Reuse the existing accepted-evidence read path/authorization.

Do not create public filesystem paths.

Every UI image URL must resolve through the same platform evidence boundary used today for Representative evidence.

## 9.3 Web API model

Modify `src/web/mavi-web/src/api/tracks.ts` and associated tests.

Use a typed role union; do not pass arbitrary role strings deep into UI components.

## 9.4 Evidence Set viewer

Implement only the Stage-2 S1 UI obligation from the adopted specification:

- Representative remains primary;
- supplemental evidence appears as a compact bounded strip/list;
- role + timestamp visible;
- selected supplemental crop can be inspected;
- Evidence Player remains the primary review/video surface;
- no badge swarm;
- no attributes, model predictions, confidence claims or Stage-2 search filters yet.

Reuse existing Investigation/Review inspector primitives.

UI must handle:

- one Representative only;
- 2–4 observations;
- missing supplementals;
- historical Thumbnail-backed Representative;
- evidence image unavailable/error distinctly from empty.

---

# 10. S1.4 — hardening and qualification rebinding

## 10.1 Performance/resource evidence

Measure at minimum:

- peak worker RSS against live Track count;
- proof that retired Track trajectory/candidate payloads leave live accumulators;
- staging bytes per run;
- cross-attempt staging cleanup;
- completion JSON bytes;
- selector CPU cost/frame;
- JPEG encode CPU cost;
- finalisation latency;
- platform validation/sealing time;
- DB row/artifact growth.

Use realistic videos plus synthetic bound tests.

Do not allocate a literal 5.2 GiB fixture in normal CI. Boundary arithmetic and fake/sparse-store tests can prove hard bounds; one controlled stress run should exercise meaningful volume.

## 10.2 Task-10 qualification rebinding

S1 changes the raw processing pipeline and evidence contract.

Therefore:

- rerun relevant Task-10 CPU qualification matrices on the final S1 head;
- update pipeline profile identity/hash;
- update retained qualification evidence to the v3 contract;
- preserve detector/tracker model qualification claims only where the actual detector/tracker semantics remain unchanged and the qualification policy permits;
- explicitly record that evidence-selection/finalisation changes were requalified;
- rebind CUDA/E2E evidence when that evidence is produced/re-run; do not claim a stale exact pipeline identity.

Do not silently reuse a pre-S1 pipeline-profile hash.

## 10.3 Offline

S1 adds no third-party dependency unless the implementation proves one unavoidable.

The JPEG/MessagePack work must use the already qualified dependency graph.

Run disconnected processing through:

Video → VisionJob → v3 completion → seal/persist → Track detail → Evidence Set viewer.

No network resolution.

---

# 11. Detailed file-impact map

This is a planning map, not permission to touch unrelated files.

## Python — expected modifications

- `src/vision/mavi_vision/tracking/interfaces.py`
- `src/vision/mavi_vision/tracking/bytetrack.py`
- `src/vision/mavi_vision/tracking/fixture.py`
- `src/vision/mavi_vision/pipeline/process_video.py`
- `src/vision/mavi_vision/pipeline/finalization.py`
- `src/vision/mavi_vision/common/analytical.py`
- `src/vision/mavi_vision/quality/scoring.py`
- new selector/encoder module(s) under `quality/` or `pipeline/`
- `src/vision/mavi_vision/storage/artifact_store.py`
- POSIX/Windows staging backends as needed for prior-attempt cleanup
- `src/vision/mavi_vision/storage/artifact_publisher.py`
- `src/vision/mavi_vision/worker/client.py`
- v3 worker schema/Pydantic model/profile files

## Platform — expected modifications

- `src/platform/Mavi.Contracts/Worker/WorkerContractRules.cs`
- `src/platform/Mavi.Contracts/Worker/VisionJobCompleteContracts.cs`
- `src/platform/Mavi.Application/Modules/Intelligence/VisionResultValidator.cs`
- `src/platform/Mavi.Domain/Intelligence/Observation.cs`
- `src/platform/Mavi.Domain/Intelligence/ObservationType.cs`
- `src/platform/Mavi.Domain/Media/ArtifactType.cs`
- `src/platform/Mavi.Infrastructure/Persistence/Configurations/ObservationConfiguration.cs`
- `src/platform/Mavi.Infrastructure/Persistence/Repositories/ProcessingResultStore.cs`
- new EF migration + model snapshot
- Track detail contracts/projections/endpoints

## Web — expected modifications

- `src/web/mavi-web/src/api/tracks.ts`
- existing Investigation/Review inspector/evidence components
- focused tests for evidence-set rendering and state handling

## Tests — expected extensions

- ByteTrack adapter
- fixture tracker
- process-video
- staging store/backends
- lease ownership
- worker wire/schema
- validator/canonicalization/digest
- ProcessingResultStore/integration
- Track detail/API
- web Track API + evidence UI
- qualification/offline harnesses

Implementation should use repository search at each sub-slice start to capture renamed/new tests rather than relying only on this list.

---

# 12. Test architecture

## 12.1 Unit tests

High-volume deterministic unit coverage for:

- role selector;
- candidate qualification;
- duplicate detection;
- temporal thirds/separation;
- tie-breaking;
- encoder cap/floor behavior;
- run admission;
- tracker retirement;
- canonical v3 digest.

## 12.2 Contract tests

Cross-language fixtures must prove Python and .NET agree on:

- v3 schema;
- enum vocabulary/casing;
- canonical SHA/digest inputs;
- byte caps;
- role/rank semantics;
- storage-key rules;
- provenance/profile identity.

Keep a small checked-in golden v3 fixture.

## 12.3 Integration tests

Must cover:

- real completion endpoint;
- sealing multiple crops;
- rollback compensation;
- replay/idempotency;
- v2 compatibility;
- v3 persistence;
- Track detail observations;
- source/evidence authorization.

## 12.4 Native tracker tests

The ByteTrack suite must discriminate against:

- no retirement;
- one-frame-early retirement;
- map not pruned;
- MAVI id resurrection;
- nondeterministic retirement order.

## 12.5 Visual QA

At 1366×768 and 1600-class viewport:

- Representative primary;
- 1/2/3/4 observation cases;
- evidence-unavailable case;
- no overflow/badge clutter;
- Evidence Player remains dominant.

---

# 13. Failure semantics

S1 must explicitly preserve these behaviours:

- lease loss before side effect: no publish;
- lease loss after an atomic staging write: attempt remains fenced and cannot complete;
- source integrity failure: no accepted result;
- tracker poison/failure: whole attempt fails;
- missing mandatory Representative: whole VisionJob result fails;
- missing supplemental role: valid omission;
- supplemental cannot fit cap: valid omission;
- EvidenceCrop aggregate quota reached: deterministic supplemental omission, not failure;
- mandatory Representatives somehow exceed run quota: fail closed;
- platform artifact missing/hash mismatch: completion fails;
- DB commit fails after sealing: compensate newly sealed evidence;
- retry gets fresh adapter/lifecycle state and cleans fenced earlier staging.

---

# 14. Migration and rollback

## Database

One additive migration:

- new Observation evidence fields/constraints;
- enum conversion strategy;
- no destructive rewrite of historical evidence;
- historical Representative rows become/behave as Representative rank 0.

Migration down-path must be explicit if repo policy requires it, but rollback must not delete accepted evidence bytes blindly.

## Wire

Use v2/v3 transition support as described in §7.6.

## Application rollback

A deployment rollback to a v2-only platform after v3 worker processing has begun is not supported unless the v3 DB migration is backward-readable. Deployment order therefore remains:

1. DB migration that is backward-compatible with the current v2 platform/domain reads;
2. platform that can accept/read v2+v3 and expose the additive Track-detail shape;
3. v3 worker;
4. web UI.

If the EF migration cannot be proven backward-compatible with the immediately preceding platform binary, deploy migration + dual-version platform as one coordinated maintenance step and document that exception; do not deploy a v3 worker first.

Document this in the development runbook for the slice.

---

# 15. Acceptance mapping

## B1 — deterministic selector

PASS only with:
- four-role selector implemented;
- numeric profile frozen/versioned;
- deterministic fixture/golden tests;
- tie/duplicate/temporal/occlusion tests.

## B2 — bounded live memory / retirement

PASS only with:
- model-neutral retirement contract;
- ByteTrack exact-once/no-reappearance;
- FixtureTracker parity;
- whole-Track retirement finalisation;
- EOS drain;
- cross-attempt staging cleanup;
- tests proving trajectory/candidates do not remain in live accumulators after retirement.

## B3 — bounds/admission

PASS only with:
- role byte caps/floors;
- 1 GiB EvidenceCrop accounting;
- 512 MiB other-artifact accounting;
- score-ordered deterministic admission;
- actual v3 body-size re-derivation;
- 10,000-Track contract/bound tests.

## B4 — schema/digest/store

PASS only with:
- v3 worker/.NET contract agreement;
- digest v3;
- validation;
- transactional sealing/persistence;
- migration;
- v2 compatibility/idempotent replay;
- multi-artifact rollback compensation.

## B5 — read/UI

PASS only with:
- `TrackDetail.observations[]`;
- Representative convenience path preserved;
- historical Track behavior;
- Evidence Set viewer;
- visual/error-state QA.

## B6 — qualification

PASS only with:
- relevant Task-10 CPU matrix rerun;
- pipeline-profile/qualification identity updated;
- E2E/CUDA evidence explicitly rebound or explicitly recorded as pending/non-claim;
- exact-head CI green.

---

# 16. Recommended PR sequence

## PR S1.1 — Tracker retirement and finalisation

No wire/schema change.

Primary risk: backend retirement semantics and memory lifecycle.

Do not proceed to v3 until its native + fixture tests are green.

## PR S1.2 — Evidence Set + v3 contracts + persistence

Largest correctness PR.

Must include worker/platform golden contract fixtures and DB migration.

Do not split worker v3 emission from platform v3 acceptance into independently deployable incompatible commits.

## PR S1.3 — Track detail + Evidence Set UI

No attribute intelligence.

Keep UI compact and evidence-oriented.

## PR S1.4 — qualification/hardening closure

Run bound/performance/offline/Task-10 evidence and update acceptance B1–B6.

S1 closes only here.

---

# 17. Stop conditions

Implementation stops for architecture review if any of these occurs:

1. ByteTrack cannot provide/derive retirement without duplicating or guessing backend semantics.
2. the worker/platform canonical Track ordering cannot provide a stable secondary admission key equivalent to platform LocalTrackNumber.
3. v3 worst-case request body requires an unreasonable HTTP limit rather than a bounded contract redesign.
4. 1 GiB accepted evidence or ~5.2 GiB transient staging proves operationally unsuitable on intended Development hardware.
5. JPEG bounds/floors materially damage later NearView utility.
6. v2/v3 dual support creates ambiguous idempotent completion semantics.
7. Observation migration cannot preserve historical Representative evidence safely.
8. a new dependency would be required.
9. Task-10 qualification evidence cannot be truthfully inherited/rebound under the changed pipeline identity.

Do not solve any of these silently inside implementation.

---

# 18. Completion report required from implementation

For each S1 sub-PR retain:

- starting main SHA;
- exact final head;
- files changed;
- migration/schema version;
- test counts/results;
- exact workflow runs;
- resource/bound measurements where applicable;
- acceptance items advanced;
- qualification/non-claims;
- unresolved findings.

At S1 closure provide one consolidated report against B1–B6.

---

# 19. Review questions for Fable

The independent plan review should challenge at minimum:

1. Is `TrackerUpdate(candidates, retired_track_ids)` the correct minimal contract, or does whole-Track finalisation expose another lifecycle edge?
2. Is the ByteTrack derived-retirement rule actually implementable against the current third-party adapter without relying on unavailable internal state?
3. Is dual v2/v3 platform support the right migration strategy?
4. Is worker Track-id ordering a valid deterministic substitute for platform LocalTrackNumber during supplemental admission?
5. Should old Thumbnail artifacts remain historical while new crops use EvidenceCrop, or should artifact typing be normalized differently?
6. Does the 1 GiB / ~5.2 GiB accepted/transient storage design remain sensible after real repository constraints are considered?
7. Is S1 UI scope correctly minimal?
8. Are Task-10 qualification/rebinding consequences complete?
9. Can S1.1–S1.4 merge independently without leaving `main` in an incoherent operational state?
10. Is any B1–B6 acceptance requirement still not directly testable from this plan?

Fable is authorised to amend this **plan/documentation only**, not implementation code.
