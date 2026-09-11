# Task 10 Design: Qualified RTMDet + ByteTrack Vision Runtime

**Status:** Approved for implementation planning  
**Date:** 2026-09-11  
**Branch:** `feature/task-10-rtmdet-bytetrack`  
**Parent capability:** Visual Intelligence Memory  
**Predecessor:** Task 9 deterministic track-processing pipeline  
**Successor boundary:** Task 11 authoritative result completion and persistence

## 1. Purpose

Task 10 replaces the Task-9 fixture detector/tracker path with a real, qualified, fully offline person/vehicle detection-and-tracking runtime while preserving all Task-9 safety, lease, artifact, and deterministic processing invariants.

The production reference detector is **RTMDet-M**, executed through a qualified MMDetection runtime. Tracking uses **ByteTrack** behind MAVI's existing `Tracker` protocol. MAVI must own the model/runtime boundaries, object-class normalization, track-ID semantics, failure classification, provenance, readiness, and offline deployment controls. Model-specific libraries must not leak into the operational platform or the deterministic Task-9 pipeline.

The guiding invariant is:

> Model/framework code may fail, be replaced, or be upgraded without changing MAVI's analytical pipeline, lease semantics, artifact-safety guarantees, or durable operational authority boundaries.

## 2. Context and existing baseline

Task 9 already provides a deterministic Python processing pipeline with the following properties:

- `VideoProcessor` depends only on model-neutral `Detector` and `Tracker` protocols.
- detections and tracks use normalized MAVI analytical models;
- source integrity is verified before decoding;
- media-relative timing is derived from decoded frame PTS;
- one shared `LeaseGuard` protects processing and irreversible mutation boundaries;
- attempt-scoped staging isolates concurrent/retried lease attempts;
- artifact publication is ownership-aware;
- result completion/persistence is intentionally not implemented yet;
- Python does not own PostgreSQL authority.

Task 10 must extend this architecture rather than reopen it.

The current repository declares Python `>=3.13`, but the stable OpenMMLab/MMDetection ecosystem has a more conservative compatibility envelope. Python 3.13 is therefore not a product requirement. Task 10 will qualify and freeze the most compatible production runtime matrix, testing Python 3.12 first and Python 3.11 as the fallback candidate if necessary.

## 3. Goals

Task 10 shall:

1. load RTMDet-M only from explicit local model/config artifacts;
2. verify model/config integrity before any job is leased;
3. produce real Person/Vehicle detections through the existing `Detector` protocol;
4. produce real single-video tracks through the existing `Tracker` protocol;
5. keep MMDetection/PyTorch/CUDA types behind MAVI runtime interfaces;
6. use a long-lived detector runtime but fresh tracking state for every video attempt;
7. formally support Windows and Linux from Task 10;
8. make Ubuntu/Linux + NVIDIA the authoritative production-performance qualification target;
9. support an explicit CPU mode on both Windows and Linux;
10. remain fully offline in production;
11. freeze model identity separately from pipeline behaviour;
12. expose complete runtime/model/profile provenance for Task 11 to persist later;
13. fail closed when model/runtime integrity or readiness is not proven;
14. preserve all Task-9 lease and artifact-safety guarantees;
15. establish a repeatable CCTV qualification baseline for detection and tracking quality.

## 4. Non-goals

Task 10 shall not implement:

- result completion or `/complete` persistence;
- direct Python PostgreSQL writes;
- ProcessingRun/Track/Observation persistence changes;
- worker-health-v2 schema expansion;
- ReID or cross-camera identity;
- face recognition;
- ANPR;
- vehicle subtype persistence;
- behaviour classification;
- visual-language-model or LLM reasoning;
- embeddings/vector search;
- adaptive frame sampling;
- multi-video batching;
- multiple simultaneous jobs per worker process;
- CUDA stream scheduling;
- automatic model download;
- automatic production fallback from CUDA to CPU;
- silent model/resolution/threshold changes after runtime failure.

These remain later capabilities or separate architectural decisions.

## 5. Architectural approach

### 5.1 Component boundaries

The target flow is:

```text
WorkerRunner
    |
    v
ProductionVisionProcessor
    |
    +--> shared DetectorRuntime
    |       |
    |       v
    |   MMDetectionRuntime
    |       |
    |       v
    |     RTMDet-M
    |
    +--> job-scoped RTMDetDetector
    |
    +--> job-scoped ByteTrackTracker
    |
    +--> job/attempt-scoped StagingArtifactStore
    |
    v
existing Task-9 VideoProcessor
```

The existing `VideoProcessor` remains the deterministic orchestration core. It continues to decode verified source frames, call `Detector.detect()`, call `Tracker.update()`, accumulate evidence, select representative observations, build trajectories, enforce lease ownership, and publish attempt-scoped artifacts.

Task 10 should make zero semantic changes to this class unless an implementation detail is strictly necessary to preserve the agreed contracts.

### 5.2 Detector runtime abstraction

A new framework-neutral runtime layer owns heavyweight detector lifecycle and framework state.

Conceptually:

```python
class DetectorRuntime(Protocol):
    @property
    def metadata(self) -> RuntimeMetadata: ...

    def warmup(self) -> None: ...

    def infer(self, image: np.ndarray) -> Sequence[RawDetection]: ...

    def health_check(self) -> RuntimeHealth: ...

    def close(self) -> None: ...
```

This is an internal Python interface. It is not a cross-system API contract.

`MMDetectionRuntime` is the first implementation and exclusively owns:

- MMDetection;
- MMEngine;
- MMCV;
- PyTorch;
- CUDA device interaction;
- RTMDet config/model construction;
- framework-specific preprocessing/postprocessing;
- framework-specific exceptions;
- conversion from framework result objects to MAVI `RawDetection` values.

No MMDetection, tensor, CUDA, or `DetDataSample` type may escape this layer.

### 5.3 Runtime versus session/job lifecycle

The detector model is process-scoped. Tracking and artifact state are attempt-scoped.

```text
worker process starts
    -> verify settings/profile/manifest
    -> verify model/config hashes
    -> select explicit device policy
    -> construct MMDetectionRuntime once
    -> mandatory warm-up
    -> validate output contract
    -> READY
    -> lease job
    -> create RTMDetDetector
    -> create fresh ByteTrackTracker
    -> create attempt-scoped StagingArtifactStore
    -> create VideoProcessor
    -> process
    -> discard job-scoped objects
    -> retain DetectorRuntime
    -> next lease
```

A tracker instance is never reused across videos or lease attempts.

### 5.4 One active GPU job per worker process

For Task 10:

```text
1 worker process = 1 detector runtime = 1 selected device = at most 1 active video job
```

Horizontal scale is achieved by running additional worker processes. Cross-video batching and concurrent GPU jobs are intentionally deferred.

## 6. Model manifest, pipeline profile, and deployment settings

These are three separate configuration concerns.

### 6.1 Model manifest: immutable model identity

A committed manifest under `models/manifests/` identifies exactly which model/config pair MAVI expects.

Reference path:

```text
models/manifests/rtmdet-m-coco-phase1-v1.json
```

Required information includes:

- schema version;
- model ID;
- semantic model version;
- purpose;
- backend/framework;
- architecture (`rtmdet-m`);
- class vocabulary;
- checkpoint relative filename;
- checkpoint SHA-256;
- config relative filename;
- config SHA-256;
- verification status;
- runtime compatibility profile.

The manifest shall not contain absolute paths or URLs. Model files are resolved only beneath an explicitly configured model root.

Both checkpoint and config are integrity-protected because a changed MMDetection config can materially change the effective model even when the checkpoint bytes are unchanged.

Model weights remain excluded from Git.

### 6.2 Pipeline profile: versioned analytical behaviour

A separate pipeline profile defines how the verified model is used.

Reference path:

```text
src/vision/config/pipelines/phase1-detection-tracking-v1.json
```

The profile owns behaviour-affecting policy including:

- detector inference floor;
- allowed detector source classes;
- source-class to MAVI-class mapping;
- maximum accepted detections if required;
- ByteTrack parameters;
- frame policy;
- every-frame sampling for Task 10;
- quality-policy version if needed;
- other qualified detection/tracking parameters.

Thresholds are not hard-coded into source and are not treated as model identity.

Once a profile is used operationally, a behaviour-affecting change produces a new profile version rather than silently modifying the prior qualified semantics.

The canonical profile document is SHA-256 hashed for provenance in addition to recording its friendly ID/version.

### 6.3 Deployment settings: placement and device selection

`WorkerSettings` may select:

- model root;
- model manifest;
- pipeline profile;
- device policy;
- device index;
- development/production verification policy.

Deployment settings shall not expose arbitrary detector/tracker tuning knobs that bypass the qualified profile.

### 6.4 Startup validation order

Before any lease request:

```text
load deployment settings
    -> load/validate pipeline profile
    -> resolve referenced model manifest
    -> validate manifest
    -> resolve local config/checkpoint under model root
    -> path containment checks
    -> SHA-256 verification
    -> runtime compatibility validation
    -> device validation
    -> construct model runtime
    -> mandatory warm-up
    -> output-contract validation
    -> READY
```

Missing artifacts, hash mismatches, incompatible runtime versions, malformed profile data, or failed warm-up prevent leasing.

## 7. Provenance

Task 10 shall produce an immutable runtime provenance snapshot capable of identifying the complete inference recipe.

Minimum provenance includes:

- model ID/version;
- checkpoint SHA-256;
- config SHA-256;
- pipeline-profile ID/version;
- canonical profile SHA-256;
- detector backend/framework and versions;
- tracker implementation and version;
- Python version;
- PyTorch version/build;
- MMDetection version;
- MMCV version/build;
- MMEngine version;
- MAVI worker build/commit identity when available;
- configured device policy;
- actual selected device;
- GPU identity/index where applicable;
- CUDA/runtime versions where applicable;
- effective frame policy;
- verification status.

Task 10 constructs this provenance but does not change platform persistence. Task 11 will decide how it is carried in the completion contract and made authoritative.

## 8. RTMDet detection contract

### 8.1 Framework-neutral raw output

`MMDetectionRuntime` returns a small `RawDetection` value containing:

- source-class identity;
- confidence;
- bounding box in original decoded-frame pixel coordinates using XYXY semantics.

Any resize, padding, or letterbox inversion belongs inside the runtime. Downstream MAVI code must never receive coordinates tied to the detector tensor dimensions.

### 8.2 Native postprocessing

RTMDet/MMDetection owns its native postprocessing and NMS. MAVI does not add a second generic NMS pass unless a later qualified backend explicitly requires one.

The pipeline profile defines a sufficiently low detector emission floor so ByteTrack can use lower-confidence detections for its second association stage.

### 8.3 Validation and normalization

Every raw detection passes the following gate:

1. confidence is finite;
2. coordinates are finite;
3. confidence is within `[0,1]`;
4. source class exists in the validated vocabulary;
5. source class is allowed by the profile;
6. XYXY is clipped to actual frame bounds;
7. resulting width/height are positive;
8. pixel XYXY is converted to normalized MAVI XYWH;
9. `DetectionCandidate` is constructed.

A finite box partly outside the image is clipped. A finite detection that becomes zero-area after clipping is discarded and counted diagnostically. NaN/Inf, malformed output shape, impossible confidence, or incompatible vocabulary are runtime contract violations rather than silently ignored values.

### 8.4 Phase-1 class mapping

The reference profile maps:

| Detector class | MAVI class |
| --- | --- |
| person | PERSON |
| car | VEHICLE |
| motorcycle | VEHICLE |
| bus | VEHICLE |
| truck | VEHICLE |
| all other classes | ignored |

The mapping is profile-driven against the manifest-declared class vocabulary. Application code shall not scatter assumptions about raw COCO numeric class indices.

### 8.5 Deterministic adapter ordering

After validation, detections are fed into tracking in a canonical order. The exact stable tuple is frozen by tests and includes class, descending confidence, and bounding-box coordinates as tie-breakers.

This does not promise bit-for-bit GPU equality across all hardware. It prevents avoidable MAVI-side nondeterminism after inference.

## 9. ByteTrack contract

### 9.1 Implementation selection

Task 10 shall not build on the deprecated `supervision.ByteTrack` API. MAVI will use its own `Tracker` protocol with a qualified modern ByteTrack implementation underneath, currently targeted at `trackers.ByteTrackTracker`.

Any `supervision` dependency is treated only as a qualified data-format/transitive dependency if required by the tracker library; MAVI domain/pipeline code shall not depend directly on Supervision objects.

### 9.2 Separate association domains

Each video owns two independent tracker states:

```text
PERSON detections  -> Person ByteTrack instance
VEHICLE detections -> Vehicle ByteTrack instance
```

A Person can therefore never switch to Vehicle, satisfying the existing Task-9 invariant that a track ID may not change object class.

### 9.3 MAVI-owned track identifiers

Native ByteTrack IDs are private adapter state and are never exposed as MAVI track IDs.

For each video attempt, MAVI assigns a deterministic local namespace such as:

```text
person-000001
person-000002
vehicle-000001
vehicle-000002
```

Counters restart per video/attempt. Simultaneously created native tracks are canonicalized before MAVI IDs are assigned so the output does not depend on process-global third-party counters or arbitrary library iteration order.

The exact external ID format must remain within the existing `TrackCandidate.track_id` contract.

### 9.4 Only observed evidence is emitted

ByteTrack may retain unmatched tracks internally through an occlusion/lost buffer. MAVI shall not emit a `TrackCandidate` for an unmatched predicted-only track.

Only a current-frame detection associated with an active track becomes `TrackCandidate` evidence.

This prevents Task 9 from producing a representative crop or trajectory point for an object that was not actually observed in that frame.

### 9.5 Confidence semantics

An emitted `TrackCandidate.confidence` is the matched current-frame detector confidence, not an internal association score.

Task 9 can therefore continue interpreting final track confidence as an aggregate of actual detector observations.

### 9.6 Occlusion and reacquisition

Short occlusions may preserve the same MAVI track ID when ByteTrack reconnects the object inside the qualified lost-track buffer. Missing intervals produce no synthetic trajectory points.

A sufficiently long disappearance terminates the track. A later object becomes a new MAVI track. ReID-based reconnection is explicitly out of scope.

## 10. Device policy and platform support

Task 10 formally supports Windows and Linux through one source code path.

Device policy values are:

- `cuda`;
- `cpu`;
- development-only `auto`.

### 10.1 CUDA policy

`cuda` is the production default. A requested CUDA device must exist and pass runtime construction and warm-up. Failure leaves the runtime unavailable; production does not silently fall back to CPU.

### 10.2 CPU policy

`cpu` is a fully explicit supported execution path on Windows and Linux for development, CI, diagnostics, and deliberate CPU deployments. Task 10 does not guarantee production real-time throughput on CPU.

### 10.3 Auto policy

`auto` is a developer convenience only. It prefers CUDA and may fall back to CPU with an explicit warning and provenance showing the actual device. It is invalid for a production-qualified offline configuration.

### 10.4 Platform duties

Windows and Linux both require functional qualification for:

- core/unit tests;
- real RTMDet inference;
- ByteTrack integration;
- end-to-end MP4 processing;
- CPU mode;
- NVIDIA GPU mode where applicable;
- offline installation.

Ubuntu/Linux + NVIDIA is the authoritative production-performance and long-run qualification target. Windows GPU performance remains informational.

## 11. Runtime readiness and lifecycle

### 11.1 Internal runtime states

Task 10 introduces an internal supervisor state machine:

```text
STARTING
   -> READY
   -> RECOVERING -> READY
   -> RECOVERING -> UNAVAILABLE

any state -> STOPPING
```

Only `READY` may request a new job lease.

The existing worker-health-v2 contract currently represents only `ready`. Task 10 does not extend it. Richer external health is a separate versioned control-plane change.

### 11.2 Supervisor responsibility

`RuntimeSupervisor` owns:

- manifest/profile validation;
- runtime construction/destruction;
- device readiness;
- warm-up;
- runtime health;
- recovery classification;
- readiness gating;
- runtime provenance.

`WorkerRunner` continues to own:

- lease acquisition;
- source resolution;
- heartbeat renewal;
- the shared `LeaseGuard`;
- lease-ownership precedence;
- worker API terminal interaction.

The runner does not learn about CUDA, MMDetection, model manifests, or tracker internals.

## 12. Failure containment

### 12.1 Typed internal failures

Task 10 shall use typed internal failures rather than scattered string parsing. The design includes categories equivalent to:

- `ConfigurationError`;
- `ModelIntegrityError`;
- `RuntimeCompatibilityError`;
- `InferenceContractError`;
- `GpuOutOfMemoryError`;
- `GpuRuntimeError`;
- `TrackerError`.

Framework-specific exceptions are translated at the adapter/runtime boundary.

### 12.2 Failure scopes

| Failure | Current job | Worker/runtime afterwards |
| --- | --- | --- |
| corrupt/unsupported source | fail job | READY if runtime healthy |
| tracker failure | fail job | recreate tracker; detector may remain READY |
| invalid detector contract output | fail job | revalidate/recover runtime |
| CUDA OOM | fail attempt if still owned | one bounded recovery attempt |
| CUDA device lost / illegal context | fail attempt if still owned | UNAVAILABLE; no blind in-process reuse |
| model/config hash failure | no job should be leased | UNAVAILABLE |
| startup/warm-up failure | no job should be leased | UNAVAILABLE |
| lease loss | no stale terminal failure | runtime health handled independently |

### 12.3 Lease ownership precedence

Lease loss remains authoritative over all ordinary processing errors.

If processing fails at the same time ownership expires, `LeaseLostError` wins. A stale worker must not submit `/fail`, publish artifacts, or perform mutation cleanup after authority is lost.

Task-9 ownership checks before and after detector/tracker calls and before publication remain intact.

### 12.4 Bounded GPU recovery

For a recoverable runtime fault such as CUDA OOM:

```text
processing fault
    -> stop admitting new leases
    -> fail current attempt only if lease still owned
    -> RECOVERING
    -> dispose runtime references
    -> release transient CUDA resources where safe
    -> reconstruct runtime
    -> mandatory warm-up
    -> output-contract validation
    -> READY on success
    -> UNAVAILABLE on failure
```

Exactly one recovery attempt is permitted for the incident. There is no endless model restart loop.

Device-lost, illegal-memory-access, device-side assert, or similarly poisoned-context failures should not be treated as safe normal OOM recovery. The worker remains alive for diagnosis but unavailable for leasing until restarted/corrected.

### 12.5 No semantic rescue

Runtime recovery shall not silently:

- switch a production CUDA worker to CPU;
- change model size;
- lower input resolution;
- skip frames;
- change thresholds;
- alter tracker parameters;
- fetch a replacement checkpoint.

Those changes alter analytical semantics and require explicit profile/runtime qualification.

### 12.6 Stable worker failure codes

The orchestration boundary may expose stable machine-readable failure codes such as:

- `vision_model_integrity_failed`;
- `vision_runtime_incompatible`;
- `vision_inference_contract_failed`;
- `vision_gpu_out_of_memory`;
- `vision_gpu_runtime_failed`;
- `vision_tracker_failed`.

Messages sent to the platform are sanitized and must not contain local filesystem paths, stack traces, secrets, or environment data. Detailed diagnostics remain in worker-local logs.

## 13. Production processor composition

The existing `WorkerRunner` currently accepts a processor object that can be reused across jobs. A production `VideoProcessor` cannot itself be long-lived because it owns tracker and attempt-scoped storage dependencies.

Task 10 therefore introduces a job-scoped composition façade, conceptually `ProductionVisionProcessor`.

For each call to `process(...)`, it shall:

1. verify the supervisor/runtime is currently available;
2. obtain the shared verified detector runtime;
3. construct a lightweight `RTMDetDetector` bound to that runtime and profile;
4. construct a fresh class-separated `ByteTrackTracker`;
5. construct a fresh `StagingArtifactStore(job_id, attempt_count)`;
6. construct a fresh existing `VideoProcessor`;
7. process the attempt;
8. discard tracker/store/processor state after completion or failure.

The heavyweight detector runtime persists across jobs. Mutable tracking and artifact state never crosses evidence boundaries.

## 14. Dependency qualification and freezing

### 14.1 Qualification is a Task-10 deliverable

Implementation begins with an explicit compatibility qualification rather than assuming the current Python declaration is valid for OpenMMLab.

Candidate order:

1. Python 3.12;
2. Python 3.11 if 3.12 cannot satisfy all required Windows/Linux runtime constraints.

A candidate passes only after a real RTMDet-M inference succeeds with the complete required stack, including:

- Python;
- PyTorch;
- torchvision;
- MMCV with required ops;
- MMEngine;
- MMDetection;
- ByteTrack dependency;
- PyAV;
- NumPy;
- Pillow;
- MAVI tests.

Import success alone is not qualification.

### 14.2 Exact runtime profile

The first qualified runtime becomes `mmdetection-phase1-v1` and freezes exact production versions/builds of the relevant ML stack.

The repository uses two layers:

```text
pyproject.toml -> logical dependency declaration
qualified runtime locks/constraints -> exact deployable graph
```

The large inference stack is kept separate from the lightweight base worker dependencies so core CI does not require CUDA/MMDetection installation.

### 14.3 Platform-specific binary locks

Windows and Linux may require different wheel filenames/build tags/hashes. One logical runtime profile therefore has platform-specific artifact locks while keeping semantic versions aligned where qualification permits.

Reference structure:

```text
src/vision/runtime/mmdetection-phase1-v1/
    runtime.json
    windows-x86_64.lock
    linux-x86_64.lock
```

## 15. Offline packaging and supply-chain integrity

Production release artifacts must install and operate with network physically unavailable.

The offline bundle contains all required local packages/model artifacts and an integrity manifest recording at least:

- filename;
- size;
- SHA-256;
- package/version;
- platform;
- purpose.

Normal production operation must not invoke:

- Internet package resolution;
- `git+https` dependencies;
- MIM remote wheel lookup;
- MMDetection model-zoo downloads;
- model-hub resolution;
- remote telemetry.

Software-package integrity and model/config integrity are verified independently.

`tools/verify_repo.py` will be extended to validate committed model manifests and pipeline profiles, dangerous path/URL rules, release verification status, internal identity consistency, and the existing prohibition on tracked model weights.

## 16. CI and qualification strategy

Testing is layered so routine development remains fast while production qualification remains rigorous.

### 16.1 Gate A: core CI on every PR

Existing repository quality gates remain authoritative:

- Python core tests;
- .NET tests/build;
- frontend tests/build;
- repository verification;
- schema/contract checks.

No model checkpoint or GPU is required.

### 16.2 Gate B: vision adapter CI on relevant PRs

Windows and Linux execute fast tests for:

- manifest/profile parsing and validation;
- canonical hashing/path containment;
- RTMDet mapping and geometry;
- deterministic detection ordering;
- ByteTrack adapter semantics;
- class isolation;
- MAVI-owned deterministic IDs;
- unmatched-track suppression;
- tracker reset;
- failure classification;
- runtime-supervisor state behaviour;
- dependency import smoke tests where appropriate.

Most tests use synthetic `RawDetection` sequences.

### 16.3 Gate C: real-model functional qualification

Windows and Linux both perform a real local RTMDet-M inference using verified config/checkpoint artifacts and at least one representative image/video.

The test validates:

- local-only loading;
- CPU mode;
- CUDA mode where available;
- warm-up;
- output contract;
- class mapping;
- coordinate restoration;
- provenance;
- detector -> ByteTrack -> MAVI contract flow.

At least one qualification test runs with outbound network unavailable.

### 16.4 Gate D: production GPU qualification

Linux/NVIDIA production-class hardware executes:

- representative CCTV corpus processing;
- sustained/long-video runs;
- memory/VRAM monitoring;
- OOM/recovery injection;
- throughput characterization;
- offline installation validation;
- stability verification.

Performance is recorded rather than imposing an arbitrary real-time requirement. MAVI Phase 1 does not require real-time processing.

## 17. CCTV qualification corpus

Task 10 establishes a small, difficult, repeatable external qualification corpus. Operational CCTV recordings or biometric datasets are not committed to Git.

The corpus should cover:

- daylight persons;
- night/artificial light;
- distant/small persons;
- high camera angle;
- partial occlusion;
- groups/crowds;
- frame-boundary entry/exit;
- stationary people;
- cars;
- motorcycles;
- buses/trucks;
- mixed people and vehicles;
- fast motion/motion blur;
- camera shake;
- empty scenes;
- shadows/reflections;
- long continuous footage;
- multiple resolutions/frame rates.

A smaller golden labelled subset records ground-truth boxes/classes/track identities.

Detector baseline metrics include:

- precision;
- recall;
- AP50;
- false positives per evaluated frame;
- Person and Vehicle separately.

Tracking baseline metrics include:

- IDF1;
- HOTA;
- ID switches;
- fragmentation.

Task 10 does not invent an unsupported percentage target before representative data exists. Instead, RTMDet-M + `phase1-detection-tracking-v1` becomes the measured reference baseline against which future runtime/profile changes are compared.

## 18. Performance metrics

Linux/NVIDIA qualification records:

- decoded FPS;
- inference FPS;
- end-to-end FPS;
- source-video duration / processing duration ratio;
- GPU utilization;
- peak VRAM;
- host RAM;
- model startup time;
- warm-up time;
- track output rate;
- artifact volume;
- long-run memory stability.

Hard Task-10 performance requirements are stability and bounded resources, not a fabricated 30-FPS target.

## 19. Failure-injection matrix

The test suite shall deliberately exercise:

- missing checkpoint;
- corrupted checkpoint;
- corrupted config;
- malformed profile;
- profile/manifest identity mismatch;
- unsupported device policy;
- unavailable CUDA;
- CUDA OOM;
- fatal CUDA runtime error;
- warm-up failure;
- invalid detector output;
- ByteTrack failure;
- corrupt video;
- source hash mismatch;
- lease loss during detection;
- lease loss during tracking;
- lease loss before publication.

Each test must verify the correct combination of:

- failure classification;
- lease-ownership precedence;
- artifact safety;
- runtime readiness transition;
- absence of silent CPU/model/profile fallback;
- ability to process a subsequent job only where recovery is safe.

## 20. Proposed module and file structure

```text
src/vision/
├── mavi_vision/
│   ├── common/
│   │   └── settings.py                     [modify]
│   ├── runtime/                            [new]
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── errors.py
│   │   ├── manifest.py
│   │   ├── profile.py
│   │   ├── provenance.py
│   │   ├── mmdetection.py
│   │   └── supervisor.py
│   ├── detection/
│   │   ├── interfaces.py                   [preserve]
│   │   ├── fixture.py                      [preserve]
│   │   └── rtmdet.py                       [new]
│   ├── tracking/
│   │   ├── interfaces.py                   [preserve]
│   │   ├── fixture.py                      [preserve]
│   │   └── bytetrack.py                    [new]
│   ├── pipeline/
│   │   ├── process_video.py                [minimal/no semantic change]
│   │   ├── finalization.py                 [preserve]
│   │   └── production_processor.py         [new]
│   └── worker/
│       ├── main.py                         [modify composition]
│       └── runner.py                       [minimal failure integration]
├── config/pipelines/
│   └── phase1-detection-tracking-v1.json
├── runtime/mmdetection-phase1-v1/
│   ├── runtime.json
│   ├── windows-x86_64.lock
│   └── linux-x86_64.lock
├── tests/
│   ├── test_model_manifest.py
│   ├── test_pipeline_profile.py
│   ├── test_rtmdet_mapping.py
│   ├── test_rtmdet_geometry.py
│   ├── test_bytetrack_adapter.py
│   ├── test_runtime_supervisor.py
│   ├── test_runtime_provenance.py
│   └── test_production_processor.py
└── pyproject.toml                          [modify]

models/manifests/
└── rtmdet-m-coco-phase1-v1.json

tools/verify_repo.py                        [extend]
```

Existing Windows/Linux/offline infrastructure directories are reused for qualification and deployment documentation rather than creating a parallel structure.

## 21. Implementation sequence

After this design is approved and converted into an implementation plan, implementation should proceed in the following order:

1. qualify the Windows/Linux Python/OpenMMLab/PyTorch/ByteTrack matrix;
2. implement manifest/profile validation and repository verification using TDD;
3. implement framework-neutral runtime contracts, provenance, device policy, and typed errors;
4. implement RTMDet normalization adapter using synthetic TDD cases;
5. integrate real MMDetection/RTMDet local inference;
6. implement ByteTrack adapter using deterministic sequence tests;
7. implement production job-scoped composition around the existing Task-9 processor;
8. implement runtime supervisor/readiness/recovery and stable failure mapping;
9. freeze platform runtime locks and offline wheelhouse manifests;
10. execute real-model functional qualification on Windows/Linux CPU/GPU;
11. execute Linux/NVIDIA long-run, recovery, CCTV-quality, and performance qualification;
12. run full repository regression/quality gates and exact-head code review before merge.

No production implementation begins as part of this design-document commit.

## 22. Definition of Done

Task 10 is complete only when all of the following are demonstrated:

- an exact Python/OpenMMLab/PyTorch/ByteTrack runtime matrix has been experimentally qualified and frozen;
- RTMDet-M loads only from verified local config/checkpoint artifacts;
- model/config/profile integrity is machine-verified before leasing;
- real Person/Vehicle detections map correctly into existing MAVI analytical contracts;
- ByteTrack produces class-safe, job-scoped MAVI tracks;
- Person and Vehicle cannot share/cross tracking state;
- native third-party track IDs never leak into MAVI output;
- only actual matched current-frame observations become MAVI `TrackCandidate` evidence;
- deterministic adapter tests produce repeatable IDs/output for fixed synthetic input;
- a real MP4 completes the full existing Task-9 processing path;
- Windows CPU and Linux CPU modes are proven functional;
- Windows NVIDIA and Linux NVIDIA functional inference are proven where target hardware exists;
- Linux/NVIDIA passes long-run and recovery qualification;
- offline installation and inference succeed with network unavailable;
- representative CCTV detection/tracking baseline metrics are recorded;
- runtime/model/profile/device provenance is complete and immutable for the processing attempt;
- Task-9 lease-loss, attempt-isolation, source-integrity, and artifact-safety tests remain green;
- no PostgreSQL write path is added to Python;
- worker-health-v2 remains unchanged;
- Task-11 completion/persistence remains out of scope;
- the full repository quality gate is green.

## 23. Architectural decision record

The architectural choices in this design are formalized in `docs/decisions/ADR-005-qualified-vision-runtime.md` before production implementation begins.
