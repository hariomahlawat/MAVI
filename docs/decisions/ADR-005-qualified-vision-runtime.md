# ADR-005: Qualified Vision Runtime for RTMDet and ByteTrack

**Status:** Accepted  
**Date:** 2026-09-11

## Context

MAVI Task 9 established a deterministic, model-neutral Python video-processing pipeline with explicit `Detector` and `Tracker` interfaces, verified source handling, lease ownership enforcement, attempt-scoped artifacts, and no direct Python authority over PostgreSQL.

Task 10 introduces the first real production vision runtime: RTMDet for person/vehicle detection and ByteTrack for single-video temporal tracking.

This creates several architectural concerns that must be resolved before implementation:

- model-specific Python libraries must not leak into MAVI's operational domain;
- production must remain fully offline;
- model/configuration identity must be reproducible and integrity-protected;
- the heavyweight detector lifecycle must not be recreated for every video;
- mutable tracking state must never leak between videos;
- Windows and Linux both require formal support;
- CUDA failures must not silently change analytical behaviour;
- the current worker control-plane/lease guarantees must remain authoritative;
- exact Python/OpenMMLab/PyTorch compatibility must be proven rather than assumed.

## Decision

MAVI will use a **qualified vision-runtime architecture** with the following rules.

### 1. Keep the existing analytical pipeline model-neutral

`VideoProcessor` continues to depend only on MAVI's existing `Detector` and `Tracker` protocols.

MMDetection, MMEngine, MMCV, PyTorch, CUDA, Supervision, and tracker-library types remain behind Python vision/runtime adapters and do not appear in MAVI domain or cross-system contracts.

### 2. Introduce a framework-neutral detector-runtime boundary

A MAVI-internal `DetectorRuntime` abstraction owns heavyweight detector lifecycle, device state, model loading, warm-up, framework-specific inference, runtime metadata, and health.

`MMDetectionRuntime` is the first implementation and runs the Task-10 reference model, **RTMDet-M**.

Future detector backends such as ONNX Runtime or TensorRT may replace this implementation without changing `VideoProcessor` or the analytical contracts.

### 3. Separate process-scoped detector state from job-scoped tracking state

The verified RTMDet runtime is loaded once per worker process and reused across jobs.

For every leased video attempt, MAVI creates fresh:

- `RTMDetDetector` adapter;
- ByteTrack state;
- attempt-scoped `StagingArtifactStore`;
- `VideoProcessor` composition.

Tracker state is never shared across videos or lease attempts.

### 4. Separate model identity, pipeline behaviour, and deployment settings

MAVI uses three distinct configuration layers:

- **model manifest**: immutable model/config identity and SHA-256 integrity metadata;
- **pipeline profile**: qualified detector/tracker thresholds, class mapping, and frame policy;
- **deployment settings**: model/profile selection, model root, device policy, and placement.

Behaviour-changing thresholds are not hard-coded into source and are not treated as model identity.

Production requires a model/runtime marked `verified`. Development may explicitly use an `unverified` qualification status, but checkpoint/config hashes are still verified, provenance must show `unverified`, and remote model download remains prohibited.

### 5. Verify model and config before leasing

Production workers load only explicit local artifacts.

Before a worker is eligible to lease a job it must:

1. validate deployment settings;
2. validate the selected pipeline profile;
3. validate the referenced model manifest;
4. resolve model/config beneath the configured model root;
5. verify checkpoint and config SHA-256 values;
6. validate runtime compatibility;
7. validate the requested device;
8. construct the runtime;
9. perform mandatory in-memory synthetic warm-up;
10. validate the detector output contract.

A missing or invalid artifact, hash mismatch, incompatible runtime, unavailable requested GPU, or failed warm-up leaves the runtime unavailable and no job is leased.

### 6. Use explicit device policy

Supported policies are:

- `cuda`;
- `cpu`;
- development-only `auto`.

Production CUDA workers do not silently fall back to CPU after GPU failure.

Runtime recovery must not silently change model size, resolution, frame sampling, thresholds, or tracker parameters.

### 7. Support both Windows and Linux

Task 10 formally supports Windows and Linux through one source code path.

Real-model CPU inference and real NVIDIA GPU inference are Task-10 functional qualification requirements on both platforms.

Ubuntu/Linux + NVIDIA is the authoritative production-performance, long-run, and recovery qualification target. Windows NVIDIA performance is informational, but Windows NVIDIA functional inference is mandatory before Task 10 is considered complete.

### 8. Qualify and freeze the ML runtime matrix

The repository's current Python `>=3.13` declaration is not treated as a production requirement.

Task 10 first tests Python 3.12 and falls back to Python 3.11 if required by the stable OpenMMLab/PyTorch stack.

The selected combination of Python, PyTorch, torchvision, MMCV, MMEngine, MMDetection, ByteTrack-related dependencies, and other required binaries is accepted only after real RTMDet-M inference succeeds on the supported platforms.

If neither Python 3.12 nor Python 3.11 can satisfy the stable required Windows/Linux matrix, implementation pauses and the runtime decision is revisited rather than accepting an unqualified stack.

Production deployment then uses exact qualified runtime locks/constraints rather than loose minimum-version resolution.

### 9. Keep production fully offline

Production runtime and installation must not require:

- Internet package resolution;
- first-run model downloads;
- model-hub lookup;
- MIM remote downloads;
- remote telemetry;
- online licence validation.

Offline release bundles contain all required packages/model artifacts plus integrity manifests.

Model weights remain outside Git.

### 10. Use class-separated ByteTrack adapters

Phase-1 detector mapping is:

- `person` -> MAVI `PERSON`;
- `car`, `motorcycle`, `bus`, `truck` -> MAVI `VEHICLE`.

Person and Vehicle detections are tracked by separate ByteTrack states, structurally preventing Person/Vehicle identity switches.

MAVI owns the external track-ID namespace; native tracker IDs are private adapter state.

Only tracks matched to an actual current-frame detection emit `TrackCandidate` evidence. Predicted-only unmatched tracker state is retained internally but does not create MAVI observations or representative crops.

Task 10 uses `trackers.ByteTrackTracker` as the ByteTrack backend, with its exact package version frozen during runtime qualification. It does not build new code on the deprecated `supervision.ByteTrack` API.

### 11. Fail closed for inference but remain alive for diagnosis

A runtime supervisor maintains internal states equivalent to:

- `STARTING`;
- `READY`;
- `RECOVERING`;
- `UNAVAILABLE`;
- `STOPPING`.

Only `READY` may request new leases.

The existing worker-health-v2 contract is not modified by Task 10.

Recoverable GPU faults receive at most one bounded runtime reconstruction + warm-up attempt. Fatal/poisoned CUDA-context failures leave the runtime unavailable until corrected/restarted.

### 12. Preserve Task-9 lease authority

Lease ownership always outranks ordinary detector/tracker/runtime failure.

If ownership is lost, a stale worker must not:

- submit a terminal failure;
- publish artifacts;
- mutate cleanup state after authority loss.

Task-10 recovery may repair worker readiness for future jobs but cannot restore authority over an expired attempt.

### 13. Record complete provenance

Task 10 constructs immutable provenance covering model/config/profile hashes, framework/runtime versions, MAVI build identity, actual device/runtime, and effective frame policy.

Task 10 does not add PostgreSQL persistence or a completion contract. Task 11 owns authoritative persistence of the analytical result and provenance.

## Consequences

### Positive

- RTMDet/MMDetection can evolve without contaminating MAVI's deterministic pipeline.
- expensive model initialization is amortized across jobs;
- tracker state cannot leak between evidence items;
- offline deployment becomes reproducible and machine-verifiable;
- model/profile/runtime provenance supports later forensic traceability;
- GPU failures cannot silently change analytical semantics;
- Windows remains a first-class functional platform while Linux/NVIDIA provides a clear production qualification authority;
- Task-9 lease and artifact-safety architecture remains intact.

### Costs and constraints

- release engineering must maintain platform-specific qualified binary locks/wheelhouse manifests;
- ML dependency upgrades become deliberate qualification events rather than casual package bumps;
- real-model CPU/GPU qualification requires dedicated Windows and Linux test environments and model artifacts outside Git;
- richer degraded-worker health reporting is deferred because worker-health-v2 remains frozen;
- Task 10 does not yet make real tracks authoritative in PostgreSQL; Task 11 is still required.

## Alternatives considered

### Direct MMDetection calls inside `VideoProcessor`

Rejected because it couples the deterministic pipeline to OpenMMLab types/lifecycle and makes later backend replacement difficult.

### Multiple detector backends in Task 10

Rejected as premature. MAVI defines the abstraction now but implements only the qualified MMDetection/RTMDet backend.

### Reuse deprecated `supervision.ByteTrack`

Rejected because the API is deprecated and intended for removal. MAVI retains its own tracker contract and uses a qualified current ByteTrack implementation underneath it.

### Production `auto` device fallback

Rejected because silent CUDA-to-CPU fallback can radically change processing time and operational behaviour while appearing healthy.

### Keep Python 3.13 as a fixed requirement

Rejected because MAVI's requirement is a stable qualified inference stack, not a specific language minor version. Runtime compatibility is determined experimentally and frozen afterward.

## Related documents

- `AGENTS.md`
- `docs/decisions/ADR-001-technology-baseline.md`
- `docs/decisions/ADR-003-offline-production.md`
- `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`
- `docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md`
