# Task 13 — Validated, Atomic Vision Result Completion and Persistence

**Status:** Approved implementation plan. No Task-13 implementation code shall precede this planning baseline.

**Planning baseline:** Phase-1 integration state after Task 12 merge and roadmap re-baseline.

**Primary objective:** convert the successful, track-oriented `VisionProcessingResult` produced by the qualified Python worker into durable, authoritative MAVI intelligence while preserving lease authority, attempt isolation, artifact integrity, deterministic processing semantics, runtime provenance and transactional consistency.

---

## 1. Why Task 13 comes before React

The merged system can import video, queue work, lease a job, run the real RTMDet + ByteTrack pipeline, publish secure attempt-scoped artifacts, supervise the runtime and build a reproducible offline runtime bundle.

It cannot yet accept a successful analytical result.

The current worker therefore deliberately ends successful processing with:

`task9_result_submission_not_implemented`

because `POST /api/vision/jobs/{jobId}/complete` and authoritative result persistence do not yet exist.

Starting React before this backend seam is closed would create UI behavior against an incomplete processing lifecycle and would force frontend rework when the completion/search contracts stabilize.

---

## 2. Goal

At Task-13 completion the successful path shall be:

```text
managed MP4
    ↓
queue ProcessingRun + VisionJob
    ↓
lease exact attempt
    ↓
RTMDet + ByteTrack
    ↓
secure attempt-scoped thumbnail/trajectory artifacts
    ↓
POST /api/vision/jobs/{jobId}/complete
    ↓
validate schema + lease + attempt + result + artifact integrity + provenance
    ↓
single PostgreSQL transaction
    ↓
Artifacts + Tracks + Representative Observations
    ↓
ProcessingRun = Completed
VisionJob     = Completed
VideoAsset    = Processed
```

A completed worker result must never require Python to write PostgreSQL directly.

---

## 3. Non-goals

Task 13 shall not implement:

- Track search/filter APIs;
- evidence-content HTTP streaming;
- React UI;
- trajectory overlays;
- ReID, face recognition, ANPR, embeddings or cross-camera identity;
- new detector/tracker algorithms or tuning;
- GPU/CCTV/performance qualification claims;
- a filesystem garbage collector for abandoned attempts;
- arbitrary user-supplied model/configuration;
- raw frame transfer through normal .NET↔Python APIs;
- direct Python database access.

Those belong to later tasks.

---

## 4. Architecture invariants

Task 13 must preserve all accepted Task-7 through Task-12 invariants.

### 4.1 Operational authority

- ASP.NET Core/.NET owns authoritative lifecycle and persistence.
- PostgreSQL remains exclusively owned by the platform.
- Python produces analytical results and logical artifact descriptors only.
- A worker result is not authoritative until the platform validates and commits it.

### 4.2 Lease authority

Once lease ownership is lost, the stale attempt must not:

- publish more artifacts;
- submit `/complete`;
- submit `/fail`;
- perform mutation cleanup.

Lease-loss precedence remains absolute.

### 4.3 Attempt isolation

Every result artifact must remain bound to the exact:

- `jobId`;
- `attemptCount`;
- attempt staging namespace.

No completion request may reference an artifact from another job or another attempt.

### 4.4 Evidence integrity

Accepted evidence is addressed only by logical storage key plus exact:

- media type;
- byte length;
- lowercase SHA-256.

Local filesystem paths never cross public/worker contracts.

### 4.5 Runtime provenance

Every successful ProcessingRun must retain sufficient immutable runtime/model/profile identity to explain which qualified analytical recipe produced its intelligence.

---

## 5. Canonical worker completion contract

### 5.1 Endpoint

Add:

```http
POST /api/vision/jobs/{jobId}/complete
```

Completion is an additive operation in the existing worker control plane and uses:

`schemaVersion = "2.0"`

Do not create a new control-plane generation unless a later incompatible contract change actually requires one.

### 5.2 Success-only semantics

The completion endpoint represents success only.

The worker lifecycle remains:

```text
processing success → /complete
processing failure → /fail
lease loss         → no terminal mutation
```

Do not reintroduce `succeeded | partial | failed` into the completion payload. Phase 1 has no accepted partial-success persistence semantics.

### 5.3 Contract shape

Create a dedicated C# request contract, matching JSON Schema and matching Pydantic model.

Conceptual shape:

```text
schemaVersion
workerId
leaseToken
attemptCount
framesProcessed
processingDurationMs

provenance
    modelId
    modelVersion
    modelManifestSha256
    checkpointSha256
    resolvedConfigSha256
    pipelineProfileId
    pipelineProfileVersion
    pipelineProfileSha256
    qualificationId
    qualificationSha256
    verificationStatus
    runtimeProfileId
    runtimeProfileSha256
    runtimeVariant
    platformLockSha256
    detectorBackend
    dependencyVersions
    maviBuild
    maviCommit
    framePolicy
    actualDevice

tracks[]
    trackId
    objectClass
    startOffsetMs
    endOffsetMs
    detectionCount
    meanConfidence
    maxConfidence

    representative
        offsetMs
        sourceFrameNumber
        confidence
        qualityScore
        boundingBox
            x
            y
            width
            height
        thumbnail
            storageKey
            mediaType
            sizeBytes
            sha256

    trajectoryArtifact
        storageKey
        mediaType
        sizeBytes
        sha256
```

The endpoint never receives raw thumbnail or trajectory bytes.

---

## 6. Retire the obsolete result scaffold

The repository currently contains an old observation-oriented result scaffold:

- `Mavi.Contracts.Worker.VisionResultContract`;
- `contracts/schemas/vision-result.schema.json`;
- `contracts/examples/vision-result.example.json`.

It predates the deterministic track-oriented Task-9 result and is structurally insufficient for production completion.

Task 13 shall either remove it in the same contract-freeze commit or move it to an explicitly named legacy fixture area if another historical test requires it.

There must be one canonical active successful-result contract after Task 13.

---

## 7. Python analytical result enrichment

The existing `ProcessedTrack` carries a mean confidence but the durable C# `Track` requires:

- `DetectionCount`;
- `MeanConfidence`;
- `MaxConfidence`.

Task 13 shall extend the deterministic accumulator.

For every accepted tracked detection:

```text
observation_count += 1
confidence_sum += confidence
max_confidence = max(max_confidence, confidence)
```

Final values:

```text
detectionCount = observation_count
meanConfidence = confidence_sum / observation_count
maxConfidence  = maximum accepted track-candidate confidence
```

The representative observation remains selected by the existing quality-ranking algorithm. It must not be assumed to equal the maximum-confidence detection.

Tests must prove this distinction.

---

## 8. Deterministic LocalTrackNumber mapping

Python track IDs such as:

- `person-000001`;
- `vehicle-000001`;

are deterministic attempt-local analytical identifiers, not durable database primary keys.

Because Person and Vehicle counters are independent, their numeric suffixes cannot directly serve as a unique `LocalTrackNumber`.

The ingestion boundary shall:

1. reject duplicate `trackId`;
2. order accepted tracks by `trackId` using ordinal comparison;
3. assign `LocalTrackNumber = 1..N`.

This gives deterministic local numbering without adding another arbitrary Python identity or database column.

---

## 9. Artifact retention model

### 9.1 Do not move accepted artifacts during completion

Task 9/10 already securely publishes artifacts beneath:

```text
staging/{jobId}/attempt-{attemptCount:0000}/...
```

Task 13 shall not rename or copy those files into another namespace during the database completion transaction.

Moving files and committing PostgreSQL cannot be made one atomic transaction; introducing such a move creates filesystem/DB split-brain failure modes.

### 9.2 Durable evidence in place

For a successful accepted attempt:

> The immutable attempt-scoped artifact becomes durable evidence in place when the authoritative PostgreSQL transaction commits an `Artifact` row referencing its verified storage key.

The word `staging` therefore describes creation isolation, not the eventual retention status of an accepted artifact.

### 9.3 Abandoned-attempt cleanup

Garbage collection of unaccepted attempt directories is explicitly out of scope for Task 13 and may be designed separately after successful result persistence is proven.

---

## 10. Artifact acceptance rules

Every submitted artifact descriptor must be validated against the exact current attempt.

For a track with `trackId`:

```text
staging/{jobId}/attempt-{attemptCount:0000}/thumbnails/{trackId}.jpg
staging/{jobId}/attempt-{attemptCount:0000}/trajectories/{trackId}.msgpack
```

Required checks:

- logical key is syntactically safe;
- job ID matches route/current job;
- attempt count matches the current leased attempt;
- track ID matches the expected file stem;
- thumbnail media type is `image/jpeg`;
- trajectory media type is `application/msgpack`;
- artifact exists;
- actual byte length equals descriptor size;
- actual SHA-256 equals descriptor SHA-256;
- no two descriptors reuse a storage key;
- no descriptor references the source video or another managed asset.

Prefer a single streaming integrity inspection that calculates byte length and SHA-256 from one opened stream rather than separate existence/open races.

---

## 11. Application-layer validation

Create a pure validation service such as:

`VisionResultValidator`

with no EF persistence side effects.

It shall validate at least:

### Job/result identity

- route `jobId` equals request/result job identity where represented;
- `attemptCount >= 1`;
- `framesProcessed >= 0`;
- `processingDurationMs >= 0`.

### Track collection

- unique track IDs;
- supported ObjectClass only;
- deterministic/safe track-ID syntax;
- offsets are non-negative;
- `endOffsetMs >= startOffsetMs`;
- `endOffsetMs <= video.DurationMs`;
- `detectionCount > 0`;
- zero frames cannot accompany one or more tracks.

### Confidence semantics

- all values finite;
- all confidence/quality values in `[0,1]`;
- `meanConfidence <= maxConfidence`;
- representative confidence does not exceed max confidence.

### Representative observation

- offset lies inside the track;
- source frame number is non-negative;
- normalized bounding box is finite and fully contained in `[0,1]`;
- width and height are strictly positive.

### Artifact descriptors

- valid media types;
- non-negative byte lengths;
- canonical lowercase SHA-256;
- exact current-attempt namespace;
- no duplicate logical storage key.

### Provenance

- required identities are non-empty;
- hashes are canonical lowercase SHA-256;
- verified results require qualification identity and platform-lock identity;
- production-completion provenance must not claim `verified` unless the worker's already-established supervisor provenance is verified.

Do not sanitize malformed analytical data into accepted intelligence.

Return one stable top-level rejection code:

`vision_result_invalid`

while retaining structured internal field/reason codes for tests and safe diagnostics.

---

## 12. Domain changes

### 12.1 VideoAsset

Add:

`MarkProcessed()`

Allowed only from `Processing`.

It transitions:

`Processing → Processed`.

### 12.2 Track

Add explicit one-time relationship methods, for example:

- `AttachTrajectoryArtifact(Guid artifactId)`;
- `AttachRepresentativeObservation(Guid observationId)`.

Rules:

- non-empty IDs only;
- cannot replace an already attached relationship with another ID;
- idempotent same-ID call may be accepted if useful to persistence retry logic;
- invalid transitions raise stable domain errors.

### 12.3 Observation

Add:

`AttachThumbnailArtifact(Guid artifactId)`

with the same one-time relationship semantics.

### 12.4 ProcessingRun

Extend successful completion so the run records:

- frames processed;
- tracks created;
- processing duration;
- detector identity;
- tracker identity;
- immutable runtime provenance JSON.

Do not leave the existing detector/tracker fields permanently null for successful production runs.

---

## 13. Persistence model and migration

Add a JSONB provenance column to `processing_runs`, for example:

`runtime_provenance_json`

Migration requirements:

- additive;
- nullable for historical/earlier rows;
- successful Task-13 completion always supplies it;
- migration tests verify upgrade and model snapshot consistency.

The existing unique constraint:

`(processing_run_id, local_track_number)`

shall remain the durable track uniqueness boundary.

The existing Artifact storage-key uniqueness constraint shall remain authoritative.

---

## 14. Concurrency and lease validation

Completion is a worker-owned terminal mutation and must follow the hardened orchestration pattern.

Acquire the `VisionJob` row using `FOR UPDATE`.

Before any authoritative completion mutation, validate:

- job exists;
- status is `Leased`;
- worker ID equals current lease owner using ordinal/case-sensitive semantics;
- lease capability token matches the stored hash;
- lease expiry is strictly later than authoritative mutation time;
- request `attemptCount == VisionJob.AttemptCount`;
- related ProcessingRun is `Running`;
- related VideoAsset is `Processing`.

The mutation time is sampled after the authoritative row lock is acquired, consistent with the existing hardened lease model.

---

## 15. Idempotent completion

Network failure after a successful server commit must not cause duplicate intelligence.

A duplicate completion request after a committed success shall:

- recognize that the job is already `Completed`;
- verify the request belongs to the same completed attempt/worker result identity as needed by the implementation;
- return the same successful completion response;
- insert no new Tracks, Observations or Artifacts.

Do not implement idempotency by catching arbitrary unique-constraint exceptions after partially building another graph.

Design the completed-state path explicitly.

If necessary, persist a stable completion-result digest derived from the canonical accepted result payload/provenance so a conflicting second completion can be distinguished from an exact retry. If such a digest is introduced, define canonical serialization once and test it cross-language before implementation.

---

## 16. Atomic PostgreSQL transaction

All accepted intelligence and terminal state transitions belong to one database transaction.

Conceptual sequence:

```text
BEGIN
  lock VisionJob
  validate lease + attempt + lifecycle
  load ProcessingRun + VideoAsset
  validate full result
  verify all artifact bytes

  create Artifact entities
  create Track entities
  create representative Observation entities

  attach trajectory artifacts
  attach thumbnail artifacts

  SaveChanges #1

  attach RepresentativeObservationId to Tracks
  mark ProcessingRun Completed
  mark VisionJob Completed
  mark VideoAsset Processed

  SaveChanges #2
COMMIT
```

The two saves are allowed only inside the same explicit PostgreSQL transaction.

They are required because:

```text
Track → RepresentativeObservation
Observation → Track
```

forms an insertion dependency cycle.

Any exception before COMMIT rolls back all Task-13 database effects.

The source-video Artifact and VideoAsset imported before processing remain intact when completion fails.

---

## 17. Completion response

Return a small response, for example:

```text
schemaVersion
jobId
processingRunId
tracksAccepted
completedAtUtc
```

Do not return storage keys, local paths, lease-token information or large analytical payloads.

---

## 18. Error model

Stable external problem codes shall distinguish the major safe boundaries.

At minimum:

- `worker_contract_version_unsupported`;
- `worker_id_invalid`;
- `vision_job_not_found`;
- `vision_job_not_leased`;
- `vision_job_lease_invalid`;
- `vision_job_attempt_mismatch`;
- `vision_result_invalid`;
- `vision_result_artifact_missing`;
- `vision_result_artifact_integrity_failed`;
- `vision_job_completion_conflict`.

Do not expose:

- raw lease tokens;
- filesystem paths;
- detailed cryptographic material not already part of an approved public contract;
- internal exception text.

---

## 19. Worker integration

### 19.1 API client

Add:

`WorkerApiClient.complete(...)`

using the same sanitized transport/status behavior as existing worker mutations.

### 19.2 WorkerRunner success path

Replace:

```text
successful process
→ /fail task9_result_submission_not_implemented
```

with:

```text
successful process
→ verify lease authority still held
→ project completion DTO from VisionProcessingResult
→ attach immutable supervisor provenance snapshot
→ /complete
→ return successful work iteration
```

### 19.3 Provenance source

Use the immutable `RuntimeSupervisor.provenance` snapshot associated with the ready runtime.

Do not reconstruct model/runtime provenance independently in the runner.

The attempt must not mix analytical output from one runtime with provenance captured from a later recovered runtime.

The implementation should therefore capture the runtime/provenance snapshot at one clearly defined attempt boundary and test runtime-replacement races.

---

## 20. Required tests

### 20.1 Contract parity

Prove exact semantic parity among:

- C# completion DTO;
- JSON Schema;
- Pydantic model;
- checked-in example.

Reject unknown fields in all strict contract models.

### 20.2 Python result tests

Cover:

- detection count;
- mean confidence;
- max confidence;
- representative selected by quality while max confidence belongs to another detection;
- zero-detection result;
- deterministic track ordering/projection;
- exact artifact descriptors.

### 20.3 Application validation tests

Cover:

- offset beyond video duration;
- negative/invalid offsets;
- invalid normalized box;
- duplicate track ID;
- invalid ObjectClass;
- non-finite scores;
- mean > max;
- representative outside track;
- no frames + non-empty tracks;
- malformed artifact SHA;
- duplicate artifact key;
- wrong attempt namespace;
- wrong track filename;
- invalid provenance.

Each test should start from one fully valid deterministic fixture and modify one condition only.

### 20.4 Artifact integrity tests

Cover:

- valid thumbnail/trajectory;
- missing file;
- size mismatch;
- SHA mismatch;
- artifact from another job;
- artifact from earlier attempt;
- traversal/key escape rejection;
- media-type mismatch.

### 20.5 Persistence atomicity tests

Cover:

- one-track success;
- multiple-track success;
- zero-track successful completion;
- failure after first track would otherwise persist;
- failure during second SaveChanges;
- no partial Tracks/Observations/Artifacts after rollback;
- imported source video remains intact.

### 20.6 Lease/concurrency tests

Cover:

- stale lease token;
- wrong worker ID;
- expired lease;
- stale attempt count;
- completion after reclaim;
- duplicate exact completion retry;
- conflicting second completion;
- concurrent duplicate completion;
- completion-vs-fail race;
- complete-vs-reclaim race.

### 20.7 Worker behavior tests

Cover:

- success invokes exactly one `/complete`;
- success never invokes placeholder `/fail`;
- processing failure invokes `/fail`, not `/complete`;
- lease loss suppresses both terminal calls;
- completion transport error does not masquerade as processing success;
- supervisor runtime replacement cannot pair old analytical output with new provenance.

### 20.8 End-to-end backend proof

Without React:

```text
POST camera
POST video import
POST process
run production-composed worker
GET processing status
query PostgreSQL through platform/repository
```

Required final state:

```text
VideoAsset.ProcessingStatus = Processed
ProcessingRun.Status        = Completed
VisionJob.Status            = Completed
Tracks                      = expected count
Observations                = one representative per track
Artifacts                   = thumbnail + trajectory per track
runtime provenance          = present
```

---

## 21. Expected files

Exact names may be refined only when a repository convention requires it, but scope should remain approximately:

### Contracts

- Modify/Create: `src/platform/Mavi.Contracts/Worker/*Complete*`
- Create: `contracts/schemas/vision-job-complete-v2.schema.json`
- Create: `contracts/examples/vision-job-complete-v2.example.json`
- Remove/retire: old `vision-result` active scaffold

### Application

- Create: `src/platform/Mavi.Application/Modules/Intelligence/VisionResultValidator.cs`
- Create: `src/platform/Mavi.Application/Modules/Intelligence/IProcessingResultStore.cs`
- Create: `src/platform/Mavi.Application/Modules/Intelligence/VisionResultIngestService.cs`
- Create or extend a media artifact integrity abstraction

### Domain

- Modify: `Track.cs`
- Modify: `Observation.cs`
- Modify: `VideoAsset.cs`
- Modify: `ProcessingRun.cs`

### Infrastructure

- Create: `ProcessingResultStore.cs`
- Modify: persistence configurations
- Add migration + model snapshot update
- Modify DI registration

### API

- Modify: `VisionJobEndpoints.cs`

### Python

- Modify: `common/analytical.py`
- Modify: `pipeline/process_video.py`
- Modify: `common/control_plane.py`
- Modify: `worker/client.py`
- Modify: `worker/runner.py`
- Modify composition only as needed to pass an immutable provenance snapshot safely

### Tests

- Application validation tests
- Integration completion/persistence tests
- Contract parity tests
- Python analytical/result tests
- Worker completion/lease-precedence tests

---

## 22. Implementation checkpoints and commit discipline

Use one branch:

`feature/task-13-result-persistence`

from the accepted documentation/re-baselined integration head.

Recommended cohesive implementation commits:

1. `docs: freeze Task 13 result-persistence contract` only if a final plan correction is genuinely required before code;
2. `feat: add worker completion v2 contract`;
3. `feat: enrich deterministic vision track results`;
4. `feat: add result validation and domain completion transitions`;
5. `feat: persist completed vision results atomically`;
6. `feat: add vision job completion endpoint`;
7. `feat: submit successful worker results`;
8. `test: prove Task 13 end-to-end completion invariants`.

Avoid multiple competing Task-13 branches unless a security remediation must be isolated deliberately.

---

## 23. Implementation freeze and release sequence

Task 13 modifies `src/vision/**`; therefore the MAVI vision wheel changes.

The Task-12 lesson is mandatory:

**implementation frozen → deterministic artifacts generated → metadata rebound → evidence attested**

### Stage A — implementation

- complete all Task-13 source changes;
- run focused tests;
- run full repository quality gate;
- obtain clean code review;
- fix all implementation findings;
- freeze exact implementation head.

### Stage B — deterministic artifacts

Only after Stage A freeze:

- generate affected MAVI vision wheel(s);
- regenerate any exact platform bundle/lock inputs whose MAVI wheel hash changes;
- record exact source head and artifact hashes.

### Stage C — metadata rebind

Only after deterministic artifacts exist:

- rebind runtime lock/bundle metadata to the new wheel;
- update hash-bound release metadata;
- do not add unrelated implementation corrections in these commits.

### Stage D — evidence attestation

Run fresh exact-head:

- MAVI Quality Gate;
- Windows runtime qualification;
- Linux runtime qualification;
- Task-12 Offline Bundle matrix;
- Task-13 focused end-to-end completion gate if introduced;
- final review/Codex review.

If implementation changes after Stage A freeze, Stages B–D must restart from the new implementation head.

---

## 24. Acceptance criteria

Task 13 is complete only when all of the following are true:

1. `/complete` exists and is strict worker-contract v2.
2. Old active observation-only result contract is retired.
3. Successful Python output includes detection count, mean and max confidence.
4. Successful worker attempts call `/complete`, not the placeholder failure.
5. Stale/expired/reclaimed attempts cannot complete.
6. Current-attempt artifact namespace is enforced.
7. Every accepted evidence artifact is verified for size and SHA-256.
8. Tracks, representative observations and artifacts are authoritative only after PostgreSQL commit.
9. Completion is atomic: no partial intelligence survives a failed transaction.
10. Exact duplicate completion retry is idempotent.
11. ProcessingRun, VisionJob and VideoAsset finish in mutually consistent successful states.
12. Successful ProcessingRun stores runtime/model/profile provenance.
13. No Python PostgreSQL write path exists.
14. All existing Task-9/10 artifact-security and lease tests remain green.
15. Task-11 runtime supervisor/recovery tests remain green.
16. Task-12 runtime qualification and offline bundle gates remain green after required artifact/metadata rebind.
17. Final exact-head review has no unresolved Critical/P1/P2 implementation findings.
18. PR is merged with expected-head protection and repository branch state is cleaned.

---

## 25. Successor boundary

After Task 13 merges:

- **Task 14** implements Track Search and Evidence Content APIs over durable completed intelligence.
- **Task 15** implements React Cameras/Import/Processing UI.
- **Task 16** implements React Visual Search and Evidence Review.
- **Task 17** performs final Phase-1 end-to-end hardening, remaining real/offline qualification, ground truth and acceptance.

Do not start Task 14 implementation until Task 13's merged exact head and authoritative persistence behavior are verified.
