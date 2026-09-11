# Task 10 Design: Qualified RTMDet + ByteTrack Vision Runtime

**Status:** Approved for implementation planning after architecture-hardening review  
**Date:** 2026-09-11  
**Revision:** 2  
**Branch:** `feature/task-10-rtmdet-bytetrack`  
**Parent capability:** Visual Intelligence Memory  
**Predecessor:** Task 9 deterministic track-processing pipeline  
**Successor boundary:** Task 11 authoritative result completion and persistence

## 1. Purpose

Task 10 replaces the Task-9 fixture detector/tracker path with a real, qualified, fully offline person/vehicle detection-and-tracking runtime while preserving all Task-9 safety, lease, artifact, and deterministic-processing invariants.

The production reference detector is **RTMDet-M**, executed through a qualified MMDetection runtime. Tracking uses **ByteTrack** behind MAVI's existing `Tracker` protocol. MAVI owns the model/runtime boundaries, object-class normalization, track-ID semantics, failure classification, provenance, readiness, artifact-security semantics, and offline deployment controls. Model-specific libraries must not leak into the operational platform or the deterministic Task-9 pipeline.

The guiding invariant is:

> Model/framework code may fail, be replaced, or be upgraded without changing MAVI's analytical pipeline, lease semantics, artifact-safety guarantees, or durable operational authority boundaries.

This revision hardens the approved architecture around the seams most likely to create integration bugs: Windows artifact safety, image colour-space handling, ByteTrack input/output semantics, failure propagation, complete model/config integrity, single-thread runtime ownership, native-inference hang containment, evidence-backed qualification, and cross-platform CI.

## 2. Context and existing baseline

Task 9 already provides a deterministic Python processing pipeline with the following properties:

- `VideoProcessor` depends only on model-neutral `Detector` and `Tracker` protocols;
- detections and tracks use normalized MAVI analytical models;
- source integrity is verified before decoding;
- decoded frames use a strict media-relative PTS-derived timeline;
- decoded frame images are contiguous `uint8` RGB arrays;
- one shared `LeaseGuard` protects processing and irreversible mutation boundaries;
- attempt-scoped staging isolates concurrent/retried lease attempts;
- artifact publication is ownership-aware;
- result completion/persistence is intentionally not implemented yet;
- Python does not own PostgreSQL authority.

Task 10 extends this architecture rather than reopening it.

Two existing implementation facts materially affect Task 10:

1. the current `StagingArtifactStore` deliberately requires POSIX secure `dir_fd`/no-follow semantics and therefore cannot satisfy native Windows end-to-end processing as written;
2. the current worker runs synchronous processing through a generic thread-pool call, whereas Task 10 introduces a long-lived CUDA/model runtime whose construction, warm-up, inference, destruction, and recovery need one explicit execution owner.

Both are resolved by this design rather than worked around during implementation.

The repository currently declares Python `>=3.13`, but the stable OpenMMLab/MMDetection ecosystem has a more conservative compatibility envelope. Python 3.13 is therefore not a product requirement. Task 10 qualifies and freezes the most compatible production runtime matrix, testing Python 3.12 first and Python 3.11 as the fallback candidate if necessary.

## 3. Goals

Task 10 shall:

1. load RTMDet-M only from explicit local, integrity-verified model/config artifacts;
2. verify the complete effective deployment configuration and model vocabulary before any job is leased;
3. produce real Person/Vehicle detections through the existing `Detector` protocol;
4. produce real single-video tracks through the existing `Tracker` protocol;
5. keep MMDetection/PyTorch/CUDA/Supervision/tracker-library types behind MAVI runtime adapters;
6. use a long-lived detector runtime but fresh tracking/artifact state for every lease attempt;
7. execute model lifecycle and processing through one dedicated vision execution lane;
8. formally support Windows and Linux from Task 10 without weakening artifact-store security;
9. make Ubuntu/Linux + NVIDIA the authoritative production-performance qualification target;
10. support an explicit CPU mode on both Windows and Linux;
11. remain fully offline in production;
12. freeze model identity separately from pipeline behaviour and deployment placement;
13. expose complete runtime/model/profile/platform provenance for Task 11 to persist later;
14. make `verified` an evidence-backed qualification state rather than a manually asserted label;
15. fail closed when model/runtime integrity or readiness is not proven;
16. contain recoverable CUDA faults and terminate safely on hung/poisoned native inference;
17. preserve all Task-9 lease and artifact-safety guarantees;
18. establish a repeatable CCTV qualification baseline for detection and tracking quality;
19. continuously enforce Linux/Windows adapter behaviour in CI.

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
- production hot reload of model/config/profile/runtime locks;
- automatic production fallback from CUDA to CPU;
- silent model/resolution/threshold/tracker changes after runtime failure;
- retrospective reconstruction/backfill of tentative ByteTrack observations.

These remain later capabilities or separate architectural decisions.

## 5. Non-negotiable invariants

Implementation and review shall treat the following as hard invariants:

1. **Lease authority is absolute.** Once ownership is lost, no terminal worker API request, artifact publication, or mutation cleanup is permitted by that stale attempt.
2. **Model code is not operational authority.** Python produces analytical candidates/results only; Task 11 and the platform remain authoritative for persistence.
3. **No model-specific framework object escapes the runtime adapter.**
4. **One worker process owns at most one active video job and one selected detector runtime/device.**
5. **Detector runtime is process-scoped; tracker and staging state are attempt-scoped.**
6. **Every decoded frame is processed in the Task-10 correctness baseline.**
7. **Only actual current-frame matched detections become MAVI track evidence.** Predicted-only tracker state never becomes evidence.
8. **Production never changes analytical behaviour as a recovery tactic.** No silent CPU fallback, frame skipping, resolution reduction, model swap, threshold change, or tracker retuning.
9. **Production model/config/profile/runtime artifacts are immutable for the worker process lifetime.** Any release change requires a worker restart and requalification identity.
10. **Windows support must provide security properties equivalent to POSIX staging; it is not implemented by weakening POSIX protections or trusting path-string normalization alone.**
11. **Production operation and installation do not require Internet access.**

## 6. Architectural approach

### 6.1 Component boundaries

The target flow is:

```text
Worker event loop / lease control
        |
        v
RuntimeSupervisor + VisionExecutionLane
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
        +--> attempt-scoped RTMDetDetector
        |
        +--> attempt-scoped ByteTrackTracker
        |
        +--> attempt-scoped SecureStagingStore facade
        |
        v
existing Task-9 VideoProcessor
```

The existing `VideoProcessor` remains the deterministic orchestration core. It continues to decode verified source frames, call `Detector.detect()`, call `Tracker.update()`, accumulate evidence, select representative observations, build trajectories, enforce lease ownership, and publish attempt-scoped artifacts.

Task 10 makes only two narrowly-scoped semantic extensions to Task-9 orchestration:

- model-neutral typed processing-dependency failures are allowed to propagate without being collapsed into the generic `pipeline_processing_failed` code;
- production execution is submitted to a dedicated single-thread vision lane rather than a generic executor.

No model/CUDA/MMDetection logic is added to `VideoProcessor` or `WorkerRunner`.

### 6.2 Detector runtime abstraction

A framework-neutral runtime layer owns heavyweight detector lifecycle and framework state.

Conceptually:

```python
class DetectorRuntime(Protocol):
    @property
    def metadata(self) -> RuntimeMetadata: ...

    def warmup(self) -> None: ...

    def infer(self, image_rgb: np.ndarray) -> Sequence[RawDetection]: ...

    def health_check(self) -> RuntimeHealth: ...

    def close(self) -> None: ...
```

This is an internal Python interface, not a cross-system API contract.

`MMDetectionRuntime` is the first implementation and exclusively owns:

- MMDetection;
- MMEngine;
- MMCV;
- PyTorch;
- CUDA device interaction;
- RTMDet config/model construction;
- RGB-to-backend colour conversion;
- framework-specific preprocessing/postprocessing;
- framework-specific exceptions;
- conversion from framework result objects to MAVI `RawDetection` values;
- runtime activity markers used by the native-inference watchdog.

No MMDetection, tensor, CUDA, `DetDataSample`, Supervision, or tracker-library type may escape its relevant adapter boundary.

### 6.3 Process, execution-lane, and attempt lifecycle

The detector model is process-scoped. Mutable tracking and artifact state are attempt-scoped. All synchronous production processing and detector lifecycle operations are serialized through one `VisionExecutionLane` backed by a single worker thread.

```text
worker process starts
    -> create VisionExecutionLane(max_workers=1)
    -> on that lane: verify/load runtime and warm-up
    -> validate runtime output/vocabulary contract
    -> READY
    -> lease job
    -> submit ProductionVisionProcessor.process(...) to same lane
    -> create fresh detector adapter/tracker/staging/VideoProcessor
    -> process attempt
    -> discard attempt-scoped objects
    -> retain detector runtime
    -> next lease
```

Runtime destruction and bounded reconstruction also execute on the same lane when the native runtime is still safely callable.

The asyncio/event-loop thread owns lease acquisition, heartbeats, watchdog decisions, readiness gating, and terminal control-plane interaction. It never performs CUDA inference.

### 6.4 One active job per worker process

For Task 10:

```text
1 worker process
= 1 VisionExecutionLane
= 1 detector runtime
= 1 selected device
= at most 1 active video job
```

Horizontal scale is achieved by additional worker processes. Cross-video batching and concurrent GPU jobs are deliberately deferred.

### 6.5 No production hot reload

Manifest, qualification record, profile, runtime lock, resolved model config, and checkpoint are selected and verified during startup. Production does not hot reload them while a worker process remains alive.

A changed release artifact requires a process restart, complete startup verification, new runtime provenance, and—where the effective analytical recipe changed—a new qualified identity.

## 7. Model manifest, pipeline profile, qualification record, and deployment settings

Task 10 separates four concerns.

### 7.1 Model manifest: immutable model identity

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
- ordered class vocabulary;
- checkpoint relative filename;
- checkpoint SHA-256;
- resolved deployment-config relative filename;
- resolved deployment-config SHA-256;
- runtime compatibility profile ID;
- optional qualification record ID.

The manifest contains no absolute paths or URLs. Model files resolve only beneath an explicitly configured model root.

A manifest does **not** become trusted merely because a text field says `verified`. Effective verification state is derived from a matching qualification record as described below.

### 7.2 Resolved deployment config: protect the effective model recipe

MMDetection configs may compose `_base_` files and execute Python configuration logic. Hashing only a top-level config is therefore insufficient.

Task 10 production uses a **self-contained resolved deployment config** created during qualification. The production config:

- contains the complete effective configuration required to construct RTMDet-M;
- has no unresolved `_base_` chain;
- has no remote includes/download logic;
- does not rely on environment-variable substitution that can change analytical semantics;
- uses only explicitly qualified local imports/packages;
- is hashed as an exact release artifact and referenced by the model manifest.

The config and checkpoint are trusted release artifacts, never job-controlled input. Because Python/MMDetection checkpoints/configuration can execute or deserialize privileged code paths, arbitrary user-supplied model/config files are never accepted by the worker.

Checkpoint provenance names the upstream publisher, immutable artifact URL/release identity, and a full expected SHA-256 that is reviewed and committed independently of the downloaded bytes. Recomputing a digest after an arbitrary download checks transfer consistency only; it does not authenticate provenance. Qualification and production therefore reject a missing or mismatched artifact before model construction. Where an otherwise qualified dependency changes checkpoint loading defaults, MAVI retains restricted deserialization and may use a lexical `torch.serialization.safe_globals` scope containing only types explicitly reviewed for the pinned checkpoint. It must not use unrestricted loading, dynamically allowlist reported names, mutate a permanent process-wide allowlist, or accept a checkpoint merely because its self-computed digest is recorded alongside it.

### 7.3 Pipeline profile: versioned analytical behaviour

Reference path:

```text
src/vision/config/pipelines/phase1-detection-tracking-v1.json
```

The profile owns behaviour-affecting policy including:

- detector inference floor;
- allowed detector source classes;
- source-class to MAVI-class mapping;
- ByteTrack activation/high-confidence/IoU parameters;
- ByteTrack minimum-consecutive-frame policy;
- MAVI lost-track time budget;
- frame policy (`every-frame` for Task 10);
- any future explicitly-qualified suppression policy.

Task 10 does **not** introduce an additional generic `maxDetections` cap. Backend-native qualified postprocessing remains authoritative unless evidence later justifies a versioned MAVI-side cap.

Thresholds are not hard-coded into source and are not treated as model identity.

Once a profile has been qualified, any behaviour-affecting change creates a new profile version rather than mutating the existing qualified recipe.

### 7.4 Qualification record: evidence-backed verification

Reference path:

```text
models/qualifications/rtmdet-m-coco-phase1-v1.json
```

A qualification record contains no CCTV media. It records machine-readable evidence identifiers and hashes, including at least:

- qualification record ID/schema version;
- model manifest ID/hash;
- checkpoint hash;
- resolved config hash;
- pipeline profile ID/hash;
- runtime profile/lock hashes;
- tested platform/device combinations;
- Windows CPU result;
- Windows NVIDIA result;
- Linux CPU result;
- Linux NVIDIA result;
- offline-install/network-disconnected result;
- aggregate CCTV corpus case IDs/hashes and metrics;
- qualification timestamp/tooling version;
- overall result.

Production effective verification is `verified` only when the referenced qualification record exists, validates structurally, matches the selected artifact hashes/runtime identity, and records all mandatory Task-10 qualification gates as passing.

Development may explicitly run an unqualified model/profile combination, but provenance records `unverified`, all local artifact hashes are still checked, and remote model download remains forbidden.

### 7.5 Deployment settings: operational placement, not analytical tuning

`WorkerSettings` may select:

- model root;
- model manifest;
- pipeline profile;
- runtime profile;
- device policy;
- device index;
- production/development verification mode;
- inference watchdog policy;
- normal worker polling/heartbeat/network settings.

Deployment settings shall not expose detector/tracker tuning knobs that bypass the qualified profile.

## 8. Startup validation and artifact immutability

### 8.1 Startup order

Before any lease request:

```text
load deployment settings
    -> load/validate pipeline profile
    -> load/validate model manifest
    -> load/validate qualification record if production
    -> resolve versioned model release directory
    -> secure path-containment/no-link checks
    -> verify exact checkpoint hash
    -> verify exact resolved-config hash
    -> verify profile/runtime-lock/qualification hash relationships
    -> validate complete runtime compatibility
    -> validate requested device
    -> on VisionExecutionLane: construct MMDetectionRuntime
    -> compare runtime ordered class metadata with manifest vocabulary
    -> mandatory synthetic warm-up
    -> output-contract validation
    -> capture immutable runtime provenance
    -> READY
```

The synthetic warm-up image is generated in memory, is not operational evidence, uses deliberately distinct RGB channel values so colour-order regressions can be detected, and validates the configured runtime/device/model path before evidence is leased.

### 8.2 Model/config path security

Model/config files must live in a versioned deployment directory beneath the configured model root. Production validates containment and rejects path traversal, symbolic-link/reparse-point redirection, and URLs.

The qualified release directory is deployed read-only to the worker identity. The worker does not replace model artifacts in place. Deployment tooling installs a new versioned release directory and restarts the worker.

Hash verification occurs immediately before model construction. The deployment security model assumes the verified release directory is immutable/read-only for the worker process lifetime; Task 10 does not rely on a verify-then-load path that is intentionally mutable by untrusted users.

### 8.3 Vocabulary verification

After model construction, MAVI reads the runtime's ordered detector class metadata and compares it exactly with the manifest's ordered class vocabulary.

A mismatch is `RuntimeCompatibilityError`/startup-unavailable even if checkpoint/config SHA-256 values are correct. Source-class mapping never relies solely on hard-coded COCO numeric indices.

## 9. Provenance and artifact hashing semantics

### 9.1 Exact artifact-byte hashing

Task 10 avoids an ambiguous phrase such as “canonical JSON hash.” For committed JSON configuration artifacts, provenance uses:

```text
SHA-256(exact UTF-8 artifact bytes)
```

Repository rules enforce UTF-8, no BOM, and LF line endings for these qualified JSON artifacts. A byte change therefore creates a different artifact identity and invalidates a qualification record that references the prior hash, even if the logical JSON values appear equivalent.

The same exact-byte rule applies to the resolved deployment config and runtime lock/manifest files where applicable.

### 9.2 Minimum runtime provenance

Each processing attempt receives an immutable snapshot including:

- model ID/version;
- model manifest hash;
- checkpoint SHA-256;
- resolved config SHA-256;
- pipeline-profile ID/version/hash;
- qualification record ID/hash and effective verification status;
- runtime profile ID and platform lock hash;
- detector backend/framework and versions;
- tracker implementation/version;
- Python version;
- PyTorch version/build;
- torchvision version;
- MMDetection version;
- MMCV version/build;
- MMEngine version;
- NumPy version;
- SciPy version;
- Supervision version if installed/used;
- OpenCV version if installed/used by the qualified tracker environment;
- PyAV version;
- FFmpeg version where discoverable;
- MAVI worker build/commit identity;
- OS/platform/architecture;
- configured device policy;
- actual selected device;
- GPU name/index and VRAM where applicable;
- NVIDIA driver/CUDA runtime versions where applicable;
- effective frame policy;
- effective tracker parameters;
- RGB input colour-space contract version.

MAVI build/commit identity is mandatory in production. Development may record an explicit `unknown`/dirty state.

Task 10 constructs this provenance but does not change platform persistence. Task 11 decides how it is carried in the completion contract and persisted authoritatively.

## 10. Image, colour-space, and detector-coordinate contract

### 10.1 MAVI frame contract

`DecodedFrame.image` is:

```text
shape: H x W x 3
dtype: uint8
layout: contiguous
colour: RGB
coordinates: original decoded-frame pixels
```

Representative evidence/crops remain RGB.

### 10.2 MMDetection colour conversion

The MMDetection adapter owns the backend colour conversion. Exactly once at the backend boundary:

```text
MAVI RGB -> backend-required BGR -> MMDetection
```

No other component may swap colour channels.

Tests use a deliberately non-grey synthetic image with distinct R/G/B values so accidental double conversion or omitted conversion cannot pass unnoticed.

### 10.3 Framework-neutral raw output

`MMDetectionRuntime` returns `RawDetection` values containing:

- source-class identity/name;
- confidence;
- bounding box in original decoded-frame pixel XYXY coordinates.

Any detector resize, padding, scale-factor reversal, or letterbox restoration remains inside `MMDetectionRuntime`. Downstream MAVI code never receives detector-tensor-space coordinates.

## 11. RTMDet normalization and class mapping

### 11.1 Native postprocessing

RTMDet/MMDetection owns native postprocessing/NMS. Task 10 does not add a second generic MAVI NMS pass.

The pipeline profile sets a sufficiently low detector emission floor so ByteTrack can use low-confidence detections in its second association stage.

### 11.2 Validation gate

Every raw detection passes:

1. finite confidence;
2. finite coordinates;
3. confidence within `[0,1]`;
4. source class present in the startup-validated vocabulary;
5. source class allowed by the profile;
6. XYXY clipped to current frame bounds;
7. positive area after clipping;
8. pixel XYXY converted to normalized MAVI XYWH;
9. `DetectionCandidate` constructed successfully.

A finite partly-outside box is clipped. A finite box that becomes zero-area is dropped with diagnostic accounting. NaN/Inf, malformed shapes, impossible confidence, or incompatible vocabulary are runtime-contract violations.

### 11.3 Phase-1 mapping

| Detector class | MAVI class |
| --- | --- |
| person | PERSON |
| car | VEHICLE |
| motorcycle | VEHICLE |
| bus | VEHICLE |
| truck | VEHICLE |
| all other classes | ignored |

The mapping is profile-driven against the verified vocabulary.

### 11.4 Class-collapse duplicate risk

MMDetection native NMS may retain overlapping predictions from different source classes (for example, a car/truck ambiguity) which subsequently map to one MAVI `VEHICLE` class.

Task 10 does not silently add post-map suppression. The qualification corpus explicitly measures duplicate Vehicle-track behaviour after source-class collapse. If this is materially problematic, a defined post-map suppression policy is introduced as a new versioned pipeline-profile behaviour with its own tests/qualification.

### 11.5 Deterministic detector ordering

After validation and class mapping, detections are sorted by the exact tuple:

```text
(object_class.value, -confidence, bbox.x, bbox.y, bbox.width, bbox.height)
```

A stable ordinal is then assigned within the current frame. Exact duplicate tuples are semantically identical at the detection boundary, but the assigned frame-local ordinal provides a deterministic identity for adapter round-tripping.

This does not claim cross-GPU bitwise inference determinism; it removes MAVI-introduced ordering nondeterminism.

## 12. ByteTrack adapter contract

### 12.1 Backend selection and isolation

Task 10 qualifies and uses `trackers.ByteTrackTracker` underneath MAVI's own `Tracker` protocol. The exact package version is frozen in the qualified runtime profile.

Any `supervision` object required by the library is created and consumed inside the ByteTrack adapter only. MAVI domain/pipeline code never receives a Supervision object.

### 12.2 Two independent association domains

Each attempt owns:

```text
PERSON detections  -> Person ByteTrack instance
VEHICLE detections -> Vehicle ByteTrack instance
```

This structurally prevents Person/Vehicle identity switching.

### 12.3 Exact per-frame adapter sequence

For every decoded frame, including frames with zero detections for a class, the adapter performs for **both** class trackers:

```text
MAVI DetectionCandidate[]
(normalized XYWH + frame-local ordinal)
        -> select this ObjectClass
        -> convert using actual current-frame width/height
        -> pixel XYXY + detector confidence + frame-local ordinal
        -> create backend detection object
        -> ByteTrackTracker.update(
               detections,
               timestamp=frame.offset_ms / 1000.0
           )
        -> recover original current-frame detection by preserved ordinal
        -> tracker_id < 0: emit nothing
        -> tracker_id >= 0: map native ID to MAVI ID and emit TrackCandidate
```

The adapter shall not rely on backend output ordering. Qualification must prove that the selected backend/version preserves the MAVI frame-local ordinal through its detection slicing/return path. If that property does not hold, the backend adapter must provide an equivalent explicit index mapping; output position alone is not accepted.

Calling both class trackers on every frame, even with an empty detection set, is mandatory so occlusion/lost-track ageing remains correct.

### 12.4 Time semantics and lost-track budget

MAVI always supplies the exact media-relative timestamp from `DecodedFrame.offset_ms`. ByteTrack therefore follows the same PTS-aware timeline as Task 9, including variable-frame-rate media.

The MAVI profile expresses the lost-track allowance as a time-domain policy (for example `lostTrackBufferSeconds`) rather than exposing an ambiguous frame-rate-dependent application setting. The adapter converts this policy to the selected backend's qualified parameterization and tests the resulting behaviour across multiple frame rates.

### 12.5 Tentative tracks and confirmation

Backend `tracker_id == -1` means the current detection is not yet a confirmed tracked observation and emits **no** MAVI `TrackCandidate`.

Task 10 performs no retrospective tentative-observation backfill. If a track becomes confirmed on a later frame, the MAVI track begins at the first frame that the backend returns a valid confirmed native tracker ID.

This rule avoids reconstructing backend-private provisional identity and keeps evidence semantics explicit.

### 12.6 Only observed current-frame evidence is emitted

ByteTrack may retain/predict unmatched tracks internally. An unmatched or predicted-only track never creates a MAVI `TrackCandidate`, trajectory point, confidence observation, representative crop, or artifact.

An emitted `TrackCandidate.confidence` is the matched original current-frame detector confidence, not an internal tracker score.

The emitted MAVI bounding box is the original normalized current-frame detection box corresponding to the matched ordinal; it is not a predicted Kalman box unless a future profile explicitly changes that contract.

### 12.7 MAVI-owned track identifiers

Native ByteTrack IDs are private adapter state. MAVI assigns attempt-local IDs such as:

```text
person-000001
person-000002
vehicle-000001
vehicle-000002
```

Counters restart for every attempt. Native IDs are mapped to MAVI IDs only when a confirmed native track is first observed.

Newly confirmed tracks in the same frame are ordered by:

```text
(bbox.x, bbox.y, bbox.width, bbox.height, -confidence, frame_local_ordinal)
```

The third-party native counter is never used as the ordering source for MAVI ID allocation.

### 12.8 Occlusion and reacquisition

Short occlusions may preserve a MAVI ID when the selected backend reconnects the same native track inside the qualified lost-track time budget. Missing intervals create no synthetic trajectory points.

A sufficiently long disappearance terminates the track. A later detection becomes a new MAVI track. ReID-based reconnection is out of scope.

## 13. Secure cross-platform attempt staging

### 13.1 Required security property

Task 10's Windows support includes the full Task-9 artifact pipeline. Therefore Windows must provide staging security equivalent in intent to the existing hardened POSIX implementation:

- artifacts cannot escape `media_root` through traversal, symlink, junction, or reparse-point substitution;
- one lease attempt cannot overwrite or clean a sibling attempt;
- destination publication is atomic at the local-filesystem boundary used by the implementation;
- lease ownership is rechecked immediately before irreversible publication;
- stale attempts do not perform cleanup after ownership loss;
- unsafe filesystem/platform capabilities fail closed.

A naive `Path.resolve()` plus string-prefix comparison is not sufficient.

### 13.2 Platform facade

`VideoProcessor` continues to depend on one staging-store interface/facade. Underneath it:

```text
SecureStagingStore facade
        |
        +--> POSIX backend
        |      existing dir_fd/O_NOFOLLOW design
        |
        +--> Windows backend
               handle-based path/reparse protection
               equivalent attempt isolation
               equivalent atomic publication semantics
```

The existing POSIX security design is preserved rather than weakened.

### 13.3 Windows backend requirements

The Windows implementation shall use platform-appropriate filesystem-handle checks. The exact implementation may use native APIs through a small isolated helper, but it must at minimum:

- reject reparse points/junction redirection in the traversed staging ancestry;
- open/validate directories by handle rather than trusting only normalized strings;
- validate the staging parent identity around publication to detect directory substitution races;
- create/write a temporary artifact inside the validated attempt directory;
- re-check lease ownership immediately before destination replacement;
- perform the strongest available same-volume atomic replacement compatible with the design;
- remove only the exact attempt subtree during authorized cleanup;
- never follow a reparse point during recursive cleanup.

Security equivalence is validated with real Windows filesystem tests, including junction/reparse/symlink cases where the test environment permits them.

If Task 10 cannot implement and qualify these properties on native Windows, native Windows end-to-end support is not declared complete; the design is revisited rather than bypassing the security gate.

## 14. Device policy and platform support

Supported device policies:

- `cuda`;
- `cpu`;
- development-only `auto`.

### 14.1 CUDA

`cuda` is the production default. The requested device must exist and pass runtime construction, synthetic warm-up, metadata validation, and real-model qualification. Failure leaves the runtime unavailable; production never silently falls back to CPU.

### 14.2 CPU

`cpu` is a supported explicit path on Windows and Linux for development, CI/qualification, diagnostics, and deliberate CPU deployments. Task 10 does not guarantee production real-time throughput on CPU.

### 14.3 Auto

`auto` is a development convenience only. It may prefer CUDA and fall back to CPU with an explicit warning and provenance showing the actual device. `auto` is invalid in a production-qualified configuration.

### 14.4 Platform duties

Windows and Linux both require:

- core/unit tests;
- adapter tests;
- real RTMDet CPU inference;
- real NVIDIA GPU inference on the target platform;
- ByteTrack integration;
- end-to-end MP4 processing;
- secure staging functionality;
- offline installation/inference.

Ubuntu/Linux + NVIDIA is authoritative for production performance, sustained running, and GPU recovery qualification. Windows NVIDIA performance is informational, but Windows NVIDIA functional inference and secure end-to-end artifact processing are mandatory Task-10 acceptance gates.

## 15. Runtime readiness, worker-health semantics, and leasing

### 15.1 Internal state machine

```text
STARTING
   -> READY
   -> RECOVERING -> READY
   -> RECOVERING -> UNAVAILABLE

any state -> STOPPING
```

Only `READY` may request a new lease.

### 15.2 Supervisor responsibility

`RuntimeSupervisor` owns:

- manifest/profile/qualification validation;
- execution-lane lifecycle;
- detector runtime construction/destruction;
- device readiness;
- warm-up;
- runtime health/activity state;
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

### 15.3 Frozen worker-health-v2 contract

Task 10 does not change `worker-health-v2`, whose valid payload represents only `ready`.

MAVI must not emit a false `ready` payload while the runtime is `STARTING`, `RECOVERING`, or `UNAVAILABLE`. If a code path exposes the v2 health payload, it may emit it only when the runtime supervisor is actually `READY`; non-ready behaviour uses local diagnostics/transport-level unavailability rather than inventing an unsupported v2 status value.

Richer degraded/unavailable health requires a future versioned control-plane change.

## 16. Typed failure propagation

### 16.1 Problem in the Task-9 path

Task 9 intentionally normalizes unexpected detector/tracker exceptions into a generic pipeline failure. Task 10 needs selected runtime/tracker failures to retain a stable machine-readable classification without importing model-specific exceptions into `VideoProcessor` or `WorkerRunner`.

### 16.2 Model-neutral processing dependency error

Task 10 introduces a small model-neutral base error, conceptually:

```python
class ProcessingDependencyError(RuntimeError):
    failure_code: str
    runtime_disposition: RuntimeDisposition
```

where `RuntimeDisposition` is equivalent to:

- `CONTINUE` — attempt fails; runtime may remain ready;
- `RECOVER` — attempt fails; runtime must perform bounded reconstruction/revalidation before more leases;
- `UNAVAILABLE` — attempt fails; runtime must stop leasing until process restart/correction.

Framework/backend errors are translated once at their boundary into typed MAVI errors such as:

- `InferenceContractError`;
- `GpuOutOfMemoryError`;
- `GpuRuntimeError`;
- `TrackerError`.

Startup-only configuration/integrity/compatibility errors remain supervisor startup errors because no lease exists yet.

### 16.3 VideoProcessor handling

`VideoProcessor` catches `ProcessingDependencyError` before its generic exception handler, performs the same lease-authorized best-effort cleanup used for ordinary processing failures, and rethrows the typed error unchanged.

It does not inspect CUDA/framework classes.

### 16.4 WorkerRunner handling

`WorkerRunner` observes the typed failure only after `_process_with_lease_heartbeats` has performed its existing lease-ownership checks. Lease loss therefore still outranks runtime failure.

If ownership is still valid, the runner submits only an allowlisted stable failure code and a sanitized generic message. Detailed stack traces/local paths/environment data remain in local logs.

Stable job-scoped codes include:

- `vision_inference_contract_failed`;
- `vision_gpu_out_of_memory`;
- `vision_gpu_runtime_failed`;
- `vision_tracker_failed`.

`vision_model_integrity_failed` and `vision_runtime_incompatible` are primarily startup readiness reasons and normally have no leased job to fail.

## 17. Failure containment and lease precedence

### 17.1 Failure scopes

| Failure | Current job | Runtime afterwards |
| --- | --- | --- |
| corrupt/unsupported source | fail if owned | READY if runtime healthy |
| tracker failure | fail if owned | CONTINUE; next attempt gets fresh tracker |
| invalid detector contract output | fail if owned | RECOVER/revalidate |
| CUDA OOM | fail if owned | one bounded recovery attempt |
| CUDA device lost / illegal context / device-side assert | fail if owned | UNAVAILABLE; process restart required |
| model/config/profile/qualification integrity failure at startup | no lease | UNAVAILABLE |
| requested GPU unavailable | no lease | UNAVAILABLE |
| startup/warm-up failure | no lease | UNAVAILABLE |
| inference watchdog expiry | stop authority renewal; no stale terminal mutation after loss | hard process restart path |
| lease loss | no stale terminal failure | runtime health handled independently |

### 17.2 Lease ownership precedence

If processing failure and lease expiry race, `LeaseLostError` wins. A stale worker never submits `/fail`, publishes an artifact, or performs mutation cleanup after ownership has been lost.

Task-9 ownership checks before/after detector/tracker calls and before publication remain intact.

Runtime recovery occurs only after the synchronous attempt has unwound and no further attempt-specific publication can occur.

## 18. GPU recovery and native-inference hang containment

### 18.1 Bounded recoverable GPU recovery

For a safe recoverable condition such as qualified CUDA OOM handling:

```text
processing fault
    -> stop admitting new leases
    -> fail current attempt only if still owned
    -> wait for processing call to unwind
    -> RECOVERING
    -> on VisionExecutionLane: dispose runtime
    -> release transient CUDA resources where safe
    -> reconstruct same runtime/model/profile/device
    -> synthetic warm-up
    -> output/vocabulary contract validation
    -> READY on success
    -> UNAVAILABLE on failure
```

Exactly one reconstruction attempt is permitted per incident. No endless restart loop occurs inside the worker.

### 18.2 Poisoned CUDA contexts

Device loss, illegal memory access, device-side assert, or another condition known/qualified to poison the CUDA process context is not treated as ordinary OOM recovery. The worker stops leasing and requires process restart.

### 18.3 Inference watchdog

Python cannot safely cancel a native CUDA/MMDetection call that never returns. Task 10 therefore includes an operational, device-profile-specific inference watchdog.

`MMDetectionRuntime` records thread-safe monotonic activity when each inference call starts and completes. The event-loop supervisor monitors an active inference call against a generous, qualified `inferenceWatchdogSeconds` operational threshold. The threshold is not an analytical tuning parameter and does not change model output.

On watchdog expiry:

1. stop admitting new leases;
2. mark the active `LeaseGuard` lost/stop heartbeat renewal so stale publication becomes impossible;
3. emit local fatal diagnostics;
4. wait only a bounded grace interval for the native call to return;
5. if it remains stuck, terminate the worker process at process level;
6. rely on the service/process supervisor to start a clean process/runtime.

The design does not attempt unsafe Python thread cancellation or reuse of a potentially hung/poisoned CUDA context.

## 19. Production processor composition

`ProductionVisionProcessor` is long-lived only as a composition facade. For each `process(...)` invocation it:

1. verifies the supervisor/runtime is `READY`;
2. obtains the shared immutable detector runtime/provenance snapshot;
3. constructs a lightweight `RTMDetDetector` bound to that runtime/profile;
4. constructs a fresh class-separated ByteTrack adapter;
5. constructs a fresh platform-appropriate attempt staging facade/store;
6. constructs a fresh existing `VideoProcessor`;
7. processes the attempt on the dedicated vision execution lane;
8. discards detector-adapter/tracker/store/processor state after success/failure.

The heavyweight detector runtime persists across jobs. Mutable tracker/artifact state never crosses evidence boundaries.

## 20. Dependency qualification and freezing

### 20.1 Qualification is an implementation gate, not an assumption

Candidate Python order:

1. Python 3.12;
2. Python 3.11 if 3.12 cannot satisfy all required Windows/Linux constraints.

A candidate qualifies only as a **complete environment**, not as individually importable packages. The tested graph includes at least:

- Python;
- PyTorch exact build;
- torchvision exact build;
- CUDA runtime/build where applicable;
- MMCV including required compiled ops;
- MMEngine;
- MMDetection;
- selected `trackers` package version;
- Supervision;
- SciPy;
- NumPy;
- OpenCV where pulled by the selected tracker graph;
- PyAV;
- Pillow;
- MAVI itself.

Real RTMDet-M load and inference must succeed in that same environment.

No production solution may rely on `--no-deps`, ignored resolver conflicts, ad-hoc compilation on the target machine, or a package combination that has not passed the required platform matrix.

If neither Python 3.12 nor 3.11 satisfies the stable required Windows/Linux matrix, implementation pauses and ADR-005 is revisited.

### 20.2 Exact runtime profile and platform/device locks

The first qualified runtime becomes `mmdetection-phase1-v1`.

`pyproject.toml` expresses the logical package relationship. Release deployment uses exact hashed artifact locks/wheelhouse manifests.

CPU and CUDA binary graphs may legitimately differ. Reference structure:

```text
src/vision/runtime/mmdetection-phase1-v1/
    runtime.json
    windows-x86_64-cpu.lock
    windows-x86_64-cuda.lock
    linux-x86_64-cpu.lock
    linux-x86_64-cuda.lock
```

The qualified Python minor is reflected in `requires-python` and hosted CI. The runtime record additionally freezes the exact Python patch/build used for release qualification.

### 20.3 Runtime upgrade policy

Changing Python, PyTorch, CUDA build, MMCV, MMEngine, MMDetection, Trackers, Supervision, SciPy, NumPy, OpenCV, RTMDet checkpoint/config, or a behaviour-affecting profile creates a new candidate qualification event.

An upgrade does not become active merely because dependency resolution succeeds.

## 21. Offline packaging and supply-chain integrity

Production release artifacts must install and operate with the network physically unavailable.

The offline bundle contains the qualified wheels/packages, model checkpoint/config, profile, manifest, qualification record, runtime locks, and an integrity manifest recording at least:

- filename;
- size;
- SHA-256;
- package/version/build;
- platform/device variant;
- purpose.

Installation uses local package sources only, with hash enforcement equivalent to:

```text
pip --no-index --require-hashes --find-links <qualified-wheelhouse>
```

Exact command layout may be generated by release tooling, but target-machine dependency resolution/compilation/download is prohibited.

Normal production operation must not invoke:

- Internet package resolution;
- `git+https` dependencies;
- MIM remote lookup;
- MMDetection model-zoo download;
- model-hub resolution;
- remote telemetry;
- online licence validation.

Software-package integrity and model/config/profile integrity are verified independently.

`tools/verify_repo.py` is extended to validate model manifests, pipeline profiles, qualification records, artifact-hash formats, required identity relationships, production verification evidence, path/URL rules, and the existing prohibition on tracked model weights/media/secrets.

## 22. CI and qualification strategy

### 22.1 Hosted CI remains repository authority

Hosted GitHub Actions remains authoritative for repository/code quality. Hardware qualification complements it; it does not replace exact-head hosted CI.

### 22.2 Gate A: existing core quality gate

On every relevant PR/push to the integration branch:

- .NET build/tests;
- Python core tests;
- frontend tests/typecheck/build;
- repository verification;
- contract/schema checks.

After runtime qualification, the workflow uses the qualified Python minor instead of the current hard-coded Python 3.13 assumption.

### 22.3 Gate B: hosted Windows + Linux vision-adapter gate

A dedicated lightweight workflow runs on hosted Ubuntu and Windows without production model weights. It covers:

- manifest/profile/qualification parsing;
- artifact byte hashing and LF/no-BOM rules;
- path containment rules;
- RGB/BGR adapter tests;
- RTMDet mapping/geometry with synthetic raw outputs;
- deterministic detection ordering;
- ByteTrack pixel-coordinate conversion;
- frame timestamp propagation;
- empty-frame tracker ageing;
- backend-output ordinal round-trip;
- tentative `tracker_id=-1` suppression;
- class isolation;
- deterministic MAVI IDs;
- tracker reset;
- typed failure propagation;
- runtime-supervisor transitions;
- execution-lane serialization;
- lease-loss precedence;
- platform-specific staging unit/integration tests available on the hosted runner.

### 22.4 Gate C: real-model functional qualification

Controlled Windows and Linux qualification environments both perform local RTMDet-M inference using verified artifacts.

Both must prove:

- CPU inference;
- NVIDIA CUDA inference;
- no network/model download;
- resolved config load;
- ordered vocabulary equality;
- RGB/BGR correctness;
- warm-up;
- output/geometry contract;
- detector -> ByteTrack -> MAVI flow;
- secure attempt artifact publication;
- provenance capture;
- clean offline installation.

At least one qualification run is executed with outbound network unavailable.

### 22.5 Gate D: Linux/NVIDIA production qualification

Production-class Linux/NVIDIA hardware executes:

- representative CCTV corpus processing;
- sustained/long-video runs;
- memory/VRAM monitoring;
- OOM/reconstruction injection;
- poisoned-context handling where safely testable;
- watchdog/fatal-restart testing with a controlled hung-inference fixture/fault injection;
- throughput characterization;
- offline installation validation;
- long-run stability verification.

Performance is measured; Task 10 does not impose an invented real-time FPS requirement.

## 23. Test strategy and qualification corpus

### 23.1 TDD at MAVI boundaries

Fast tests are written before implementation for:

- manifest/profile/qualification validation;
- resolved config constraints;
- vocabulary mismatch rejection;
- RGB/BGR conversion;
- detector normalization and clipping;
- malformed/NaN/Inf output rejection;
- class mapping;
- deterministic detection ordinals;
- ByteTrack adapter semantics;
- MAVI track-ID allocation;
- error translation/propagation;
- runtime readiness/recovery;
- cross-platform staging security contracts.

### 23.2 Geometry adversarial cases

Test at least:

- normal boxes;
- each exact image boundary;
- partial overflow on each side;
- box larger than image;
- fractional coordinates;
- inverted XYXY;
- zero width/height;
- NaN/Inf;
- tiny valid box;
- landscape/portrait/odd dimensions;
- multiple frame resolutions.

### 23.3 ByteTrack sequence cases

Test at least:

- one continuous person;
- two crossing persons;
- short occlusion and reacquisition;
- long disappearance producing a new track;
- Person/Vehicle overlap without cross-class identity;
- simultaneous new tracks with deterministic MAVI IDs;
- low-confidence second-stage association;
- repeated empty detections aging tracks correctly;
- VFR/timestamp gaps;
- backend result reordering without ordinal loss;
- tentative tracks returning `-1` then confirming later, with no historical backfill;
- new attempt resetting all tracker/native-ID mapping state.

### 23.4 Representative CCTV qualification corpus

The external corpus covers:

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
- ambiguous/overlapping vehicle source classes;
- mixed people and vehicles;
- fast motion/motion blur;
- camera shake;
- empty scenes;
- shadows/reflections;
- long continuous footage;
- multiple resolutions/frame rates including VFR where available.

Operational CCTV recordings/biometric datasets are never committed to Git.

A smaller labelled subset records ground-truth boxes/classes/track identities.

Detector metrics:

- precision;
- recall;
- AP50;
- false positives per evaluated frame;
- Person and Vehicle separately;
- post-map duplicate Vehicle detections/tracks where relevant.

Tracking metrics:

- IDF1;
- HOTA;
- ID switches;
- fragmentation.

Task 10 records a reference baseline rather than inventing unsupported accuracy percentages before representative data exists.

## 24. Performance and resource metrics

Linux/NVIDIA qualification records:

- decoded FPS;
- inference FPS;
- end-to-end FPS;
- source-video duration / processing-duration ratio;
- GPU utilization;
- peak VRAM;
- host RAM;
- model startup time;
- warm-up time;
- per-frame inference latency distribution;
- track output rate;
- artifact volume;
- long-run memory stability;
- watchdog threshold rationale.

Hard Task-10 performance requirements are stability, bounded resources, and a defensible watchdog threshold—not a fabricated 30-FPS target.

## 25. Failure-injection matrix

The suite deliberately exercises:

- missing checkpoint;
- corrupted checkpoint;
- mutated resolved config;
- unresolved/unsafe config dependency;
- malformed profile;
- qualification record/hash mismatch;
- manifest/profile identity mismatch;
- runtime vocabulary mismatch;
- model-root path escape/link/reparse attempt;
- unsupported device policy;
- unavailable CUDA;
- CUDA OOM;
- fatal CUDA runtime error;
- warm-up failure;
- RGB/BGR regression;
- invalid detector output;
- ByteTrack exception;
- ByteTrack result reordering;
- empty-class frames;
- corrupt video;
- source hash mismatch;
- lease loss during detection;
- lease loss during tracking;
- lease loss before publication;
- Windows junction/reparse staging escape attempts;
- POSIX symlink/directory-swap staging attacks;
- native inference exceeding watchdog threshold.

Every test checks the applicable combination of:

- correct failure classification;
- lease-ownership precedence;
- absence of stale `/fail`;
- artifact safety;
- runtime readiness transition;
- absence of silent CPU/model/profile fallback;
- ability to process a subsequent job only where recovery is safe;
- process restart when a native call cannot be safely recovered.

## 26. Proposed module and file structure

```text
src/vision/
├── mavi_vision/
│   ├── common/
│   │   └── settings.py                         [modify]
│   ├── runtime/                                [new]
│   │   ├── __init__.py
│   │   ├── interfaces.py
│   │   ├── errors.py
│   │   ├── manifest.py
│   │   ├── profile.py
│   │   ├── qualification.py
│   │   ├── provenance.py
│   │   ├── execution_lane.py
│   │   ├── activity.py
│   │   ├── mmdetection.py
│   │   └── supervisor.py
│   ├── detection/
│   │   ├── interfaces.py                       [preserve]
│   │   ├── fixture.py                          [preserve]
│   │   └── rtmdet.py                           [new]
│   ├── tracking/
│   │   ├── interfaces.py                       [preserve]
│   │   ├── fixture.py                          [preserve]
│   │   └── bytetrack.py                        [new]
│   ├── storage/
│   │   ├── artifact_store.py                   [facade/common contract]
│   │   ├── artifact_store_posix.py             [existing hardened logic]
│   │   └── artifact_store_windows.py           [new secure Windows backend]
│   ├── pipeline/
│   │   ├── process_video.py                    [typed failure pass-through only]
│   │   ├── finalization.py                     [preserve]
│   │   └── production_processor.py             [new]
│   └── worker/
│       ├── main.py                             [modify composition]
│       ├── runner.py                           [typed failure + lane/watchdog integration]
│       └── health.py                           [do not emit false ready]
├── config/pipelines/
│   └── phase1-detection-tracking-v1.json
├── runtime/mmdetection-phase1-v1/
│   ├── runtime.json
│   ├── windows-x86_64-cpu.lock
│   ├── windows-x86_64-cuda.lock
│   ├── linux-x86_64-cpu.lock
│   └── linux-x86_64-cuda.lock
├── tests/
│   ├── test_model_manifest.py
│   ├── test_pipeline_profile.py
│   ├── test_qualification_record.py
│   ├── test_runtime_artifact_hashing.py
│   ├── test_rtmdet_mapping.py
│   ├── test_rtmdet_geometry.py
│   ├── test_rtmdet_colour_space.py
│   ├── test_bytetrack_adapter.py
│   ├── test_runtime_execution_lane.py
│   ├── test_runtime_supervisor.py
│   ├── test_runtime_watchdog.py
│   ├── test_runtime_provenance.py
│   └── test_production_processor.py
└── pyproject.toml                              [modify after qualification]

models/
├── manifests/
│   └── rtmdet-m-coco-phase1-v1.json
└── qualifications/
    └── rtmdet-m-coco-phase1-v1.json

.github/workflows/
├── quality-gate.yml                            [qualified Python minor]
└── vision-adapter-gate.yml                     [new Windows + Linux gate]

.gitattributes                                  [qualified JSON LF policy]
tools/verify_repo.py                            [extend]
```

Existing infrastructure Windows/Linux/offline-bundle directories are reused for installation/qualification guidance and release tooling rather than creating a parallel deployment tree.

## 27. Implementation sequence

After this hardened design is accepted and converted into an implementation plan, work proceeds in this order:

1. **Runtime compatibility spike:** prove one complete Python/OpenMMLab/Trackers dependency graph on Windows and Linux; choose Python 3.12 or fall back to 3.11; record exact candidate versions/builds.
2. **Cross-platform staging spike:** design and prove the secure Windows staging backend against path/reparse/substitution tests before promising end-to-end Windows support.
3. **Manifest/profile/qualification foundation:** schemas/models, exact-byte hashing, resolved-config rules, qualification-backed `verified`, repository verification, LF/no-BOM policy.
4. **Runtime contracts:** `RawDetection`, runtime metadata/provenance, device policy, typed `ProcessingDependencyError`, runtime disposition.
5. **Dedicated execution lane/activity monitor:** single-thread lifecycle, serialized job processing, thread ownership tests, watchdog state plumbing.
6. **RTMDet adapter TDD:** RGB/BGR conversion, vocabulary, geometry, clipping, class mapping, deterministic ordinals.
7. **Real MMDetection runtime:** explicit local resolved config/checkpoint, CPU/CUDA selection, model load, metadata/vocabulary verification, warm-up, real inference.
8. **ByteTrack adapter TDD:** normalized-to-pixel conversion, timestamps, empty-frame updates, ordinal round-trip, class isolation, tentative suppression/no backfill, deterministic MAVI IDs.
9. **Production attempt composition:** shared runtime + fresh adapter/tracker/staging/`VideoProcessor`; preserve Task-9 processing/lease semantics.
10. **Typed failure propagation:** minimal `VideoProcessor` pass-through change and allowlisted `WorkerRunner` failure mapping with lease-loss precedence tests.
11. **Supervisor recovery/watchdog:** OOM reconstruction, poisoned-context quarantine, hung-native process-restart policy, no semantic fallback.
12. **Offline/runtime packaging:** exact platform/device locks, hashed wheelhouses, release integrity manifests, network-disconnected installation.
13. **Hosted cross-platform CI:** qualified Python version in core gate plus Windows/Linux adapter gate.
14. **Real-model qualification:** Windows/Linux CPU/NVIDIA functional runs, secure staging, offline execution, provenance.
15. **Production qualification:** Linux/NVIDIA long-run, recovery/watchdog, CCTV metrics, resource/performance baseline.
16. **Regression closure:** full Task-9 tests, full repository quality gate, exact-head hosted CI, and code review before merge.

No Task-11 persistence/completion work is included.

## 28. Definition of Done

Task 10 is complete only when all of the following are demonstrated:

- one complete exact Python/OpenMMLab/PyTorch/Trackers dependency graph is experimentally qualified and frozen;
- the qualified Python minor replaces the current unqualified Python 3.13 assumption in the vision package/CI;
- RTMDet-M loads only from a versioned, read-only, local resolved config/checkpoint release;
- complete effective config, checkpoint, profile, runtime locks, and qualification identity are machine-verified before leasing;
- runtime ordered class vocabulary exactly matches the manifest;
- effective `verified` state is backed by a matching qualification record rather than a free-standing declaration;
- MAVI RGB -> backend BGR conversion is explicit and regression-tested;
- real Person/Vehicle detections map correctly into existing MAVI contracts;
- no unnecessary second generic NMS/cap is introduced in Task 10;
- vehicle source-class collapse duplicate behaviour has been measured and recorded;
- ByteTrack receives pixel XYXY/confidence/timestamp for every frame/class, including empty-class frames;
- backend result order cannot corrupt detection-to-track association because frame-local ordinals are round-tripped explicitly;
- tentative/unconfirmed tracker outputs emit no MAVI evidence and are not retrospectively backfilled;
- Person and Vehicle cannot share/cross tracking state;
- native third-party IDs never leak into MAVI output;
- only matched current-frame observations create `TrackCandidate` evidence;
- deterministic adapter tests produce repeatable IDs/output for fixed synthetic input;
- model construction, warm-up, processing, destruction, and safe recovery use one dedicated vision execution lane;
- typed runtime/tracker failure classifications survive through `VideoProcessor`/`WorkerRunner` without weakening lease precedence;
- CUDA OOM bounded recovery is proven;
- poisoned/hung native runtime handling stops leasing and uses process-level restart rather than unsafe thread cancellation/reuse;
- POSIX staging security remains intact;
- native Windows staging provides qualified equivalent attempt isolation/path-escape/reparse protections;
- a real MP4 completes the full Task-9 processing/artifact path on Windows and Linux;
- Windows CPU and Linux CPU modes are functional;
- Windows NVIDIA and Linux NVIDIA functional inference are both proven;
- Linux/NVIDIA passes long-run, recovery, watchdog, CCTV-quality, and performance qualification;
- offline install and inference succeed with network unavailable using only hashed local artifacts;
- runtime/model/profile/platform/build provenance is complete and immutable for the attempt;
- hosted Windows/Linux adapter CI is green;
- Task-9 lease-loss, attempt-isolation, source-integrity, timeline, and artifact-safety tests remain green;
- no PostgreSQL write path is added to Python;
- worker-health-v2 schema remains unchanged and non-ready workers do not falsely emit `ready`;
- Task-11 completion/persistence remains out of scope;
- the full exact-head hosted repository quality gate is green.

## 29. Architectural decision record

The durable architectural decisions in this hardened specification are formalized in `docs/decisions/ADR-005-qualified-vision-runtime.md` before production implementation begins.
