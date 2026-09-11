# ADR-005: Qualified Vision Runtime for RTMDet and ByteTrack

**Status:** Accepted  
**Date:** 2026-09-11  
**Revision:** 2

## Context

MAVI Task 9 established a deterministic, model-neutral Python video-processing pipeline with explicit `Detector` and `Tracker` interfaces, verified source handling, lease ownership enforcement, attempt-scoped artifacts, and no direct Python authority over PostgreSQL.

Task 10 introduces the first real production vision runtime: RTMDet for person/vehicle detection and ByteTrack for single-video temporal tracking.

This introduces architectural concerns that must be resolved before implementation:

- model-specific Python libraries must not leak into MAVI's operational domain;
- production must remain fully offline;
- model/configuration identity must be reproducible and integrity-protected;
- MMDetection's effective configuration may span multiple config files and therefore cannot be trusted by hashing only a top-level file;
- the heavyweight detector lifecycle must not be recreated for every video;
- mutable tracking state must never leak between videos;
- native CUDA/model execution requires explicit thread/lifecycle ownership;
- a hung native inference call cannot safely be cancelled like ordinary Python work;
- Windows and Linux both require formal support, but the existing hardened artifact store is POSIX-specific;
- CUDA failures must not silently change analytical behaviour;
- model/tracker failures need stable classification without contaminating the Task-9 pipeline with framework-specific types;
- the current worker control-plane/lease guarantees must remain authoritative;
- `verified` must represent actual qualification evidence rather than a manually asserted manifest label;
- exact Python/OpenMMLab/PyTorch/Trackers compatibility must be proven as one complete environment rather than assumed package-by-package.

## Decision

MAVI will use a **qualified vision-runtime architecture** with the following rules.

### 1. Keep the existing analytical pipeline model-neutral

`VideoProcessor` continues to depend on MAVI's model-neutral `Detector` and `Tracker` protocols.

MMDetection, MMEngine, MMCV, PyTorch, CUDA, Supervision, and tracker-library types remain behind Python vision/runtime adapters and do not appear in MAVI domain or cross-system contracts.

The only Task-10 extension to the Task-9 orchestration contract is a small model-neutral typed processing-dependency failure path so selected runtime/tracker failures can retain stable classification without exposing framework-specific exceptions.

### 2. Introduce a framework-neutral detector-runtime boundary

A MAVI-internal `DetectorRuntime` abstraction owns heavyweight detector lifecycle, device state, model loading, warm-up, framework-specific inference, runtime metadata, activity/watchdog markers, and health.

`MMDetectionRuntime` is the first implementation and runs the Task-10 reference model, **RTMDet-M**.

Future detector backends such as ONNX Runtime or TensorRT may replace this implementation without changing `VideoProcessor` or MAVI analytical contracts.

### 3. Use one dedicated vision execution lane

One worker process owns one single-thread vision execution lane.

Model construction, warm-up, synchronous video processing/inference, safe runtime destruction, and bounded reconstruction execute through that lane. The asyncio/event-loop thread remains responsible for leasing, heartbeats, watchdog decisions, and control-plane interaction.

This prevents generic thread-pool scheduling from moving a process-scoped CUDA/model runtime across arbitrary worker threads and enforces the Task-10 rule of at most one active vision job per worker process.

### 4. Separate process-scoped detector state from attempt-scoped mutable state

The verified RTMDet runtime is loaded once per worker process and reused across jobs.

Every leased attempt receives fresh:

- `RTMDetDetector` adapter state;
- class-separated ByteTrack state;
- secure attempt-scoped artifact staging state;
- `VideoProcessor` composition.

Tracking or artifact state is never shared across videos or lease attempts.

### 5. Separate model identity, analytical behaviour, qualification evidence, and deployment settings

MAVI uses four distinct configuration layers:

- **model manifest** — immutable model/checkpoint/resolved-config identity and integrity metadata;
- **pipeline profile** — qualified detector/tracker thresholds, class mapping, lost-track policy, and frame policy;
- **qualification record** — machine-readable evidence tying model/config/profile/runtime hashes to required Windows/Linux/CPU/GPU/offline/quality results;
- **deployment settings** — model/profile/runtime selection, model root, device policy, watchdog policy, and placement.

Behaviour-changing thresholds are not hard-coded into source and are not treated as model identity.

### 6. Protect the complete effective model configuration

Production does not rely on hashing only an MMDetection top-level config that can include `_base_` configuration chains.

Qualification produces a self-contained resolved deployment config with no unresolved remote/base dependency or environment-driven analytical variation. The model manifest hashes that resolved config and the checkpoint.

Model/config files are trusted release artifacts, never job-controlled input. Production loads them from a versioned, read-only local release directory.

### 7. Make verification evidence-backed

A production model/runtime is effectively `verified` only when a matching qualification record exists and its recorded model/config/profile/runtime hashes and mandatory platform gates match the selected release.

Development may explicitly run an unqualified combination, but local artifact hashes are still checked, provenance records `unverified`, and remote model download remains prohibited.

A free-standing text label is not sufficient to establish production qualification.

### 8. Verify model vocabulary before leasing

After runtime construction, MAVI compares the detector's ordered runtime class metadata exactly with the manifest's ordered class vocabulary.

A mismatch leaves the runtime unavailable even if checkpoint/config hashes are correct. MAVI class mapping does not rely on scattered raw COCO numeric indices.

### 9. Freeze the image/colour-space boundary

MAVI decoded frames are contiguous `uint8` RGB images in original decoded-frame coordinates.

`MMDetectionRuntime` owns exactly one conversion from MAVI RGB to the backend-required colour representation before inference. Representative evidence remains RGB.

Colour conversion is covered by an explicit regression test using non-grey channel-distinct data.

### 10. Use class-separated ByteTrack with explicit time/evidence semantics

Phase-1 mapping is:

- `person` -> MAVI `PERSON`;
- `car`, `motorcycle`, `bus`, `truck` -> MAVI `VEHICLE`.

Person and Vehicle use independent ByteTrack states.

MAVI supplies media-relative frame timestamps to ByteTrack and updates both class trackers on every decoded frame, including empty-class frames, so lost-track ageing follows the Task-9 timeline.

MAVI owns external track IDs; native tracker IDs remain private adapter state. Backend output ordering is not trusted—frame-local detection ordinals are round-tripped explicitly.

Only a confirmed native track matched to an actual current-frame detection emits `TrackCandidate` evidence. Tentative/unconfirmed `tracker_id=-1` observations and predicted-only unmatched tracks emit nothing, and Task 10 performs no retrospective tentative-history backfill.

Task 10 uses a qualified `trackers.ByteTrackTracker` version rather than the deprecated `supervision.ByteTrack` API.

### 11. Do not add silent second-stage detector policy without evidence

RTMDet/MMDetection owns native postprocessing/NMS. Task 10 does not add an arbitrary generic detection cap or second generic NMS pass.

Because several detector source classes collapse to MAVI `VEHICLE`, qualification explicitly measures duplicate-track behaviour after class collapse. If a MAVI post-map suppression rule is later justified, it is introduced as a new versioned pipeline-profile behaviour and requalified.

### 12. Provide security-equivalent attempt staging on Windows and POSIX

Task 10's formal Windows support includes the full artifact pipeline.

The existing hardened POSIX `dir_fd`/no-follow staging design is preserved. Windows receives a platform-appropriate secure staging backend behind the same logical facade, using handle/reparse-point and parent-identity protections rather than path-string normalization alone.

Both backends must preserve:

- attempt isolation;
- path-escape/link/reparse protection;
- lease re-authorization immediately before publication;
- safe same-filesystem publication semantics;
- cleanup restricted to the currently authorized attempt;
- no stale cleanup after lease loss.

If equivalent Windows security cannot be implemented and qualified, native Windows end-to-end support is not declared complete; the security requirement is not weakened.

### 13. Use explicit device policy and no semantic recovery fallback

Supported device policies are:

- `cuda`;
- `cpu`;
- development-only `auto`.

Production CUDA workers do not silently fall back to CPU after GPU failure.

Runtime recovery does not silently change model size, resolution, frame sampling, thresholds, tracker parameters, or checkpoint.

### 14. Fail closed for inference but remain diagnosable

A runtime supervisor maintains internal states equivalent to:

- `STARTING`;
- `READY`;
- `RECOVERING`;
- `UNAVAILABLE`;
- `STOPPING`.

Only `READY` may request new leases.

The existing worker-health-v2 schema remains unchanged. A worker must not emit its `ready` payload unless the runtime is actually ready; non-ready state is represented internally/local-diagnostically until a future versioned health contract exists.

### 15. Preserve Task-9 lease authority through typed failure propagation

Framework-specific exceptions are translated at adapter/runtime boundaries into model-neutral MAVI processing-dependency errors carrying an allowlisted failure code and runtime disposition.

`VideoProcessor` may pass these model-neutral errors through after lease-authorized cleanup. `WorkerRunner` interprets them only after its existing lease-ownership checks.

Lease ownership always outranks ordinary detector/tracker/runtime failure. A stale attempt never submits a terminal failure, publishes an artifact, or mutates cleanup state after authority loss.

### 16. Bound recoverable GPU recovery and terminate on unsafe native hangs

A qualified recoverable GPU fault such as CUDA OOM receives at most one reconstruction + warm-up attempt using the same model/profile/device.

Device loss, illegal memory access, device-side assert, or other poisoned-context failures stop leasing and require process restart.

Task 10 also introduces a generous qualified per-inference watchdog. If a native inference call does not return, the worker stops renewing authority, prevents stale publication through the existing lease guard, waits only a bounded grace interval, and then uses process-level termination/restart rather than unsafe Python thread cancellation or reuse of a potentially hung CUDA context.

### 17. Qualify and freeze the complete ML runtime graph

The repository's current Python `>=3.13` declaration is not a product requirement.

Task 10 tests Python 3.12 first and Python 3.11 as fallback if required. A runtime qualifies only as one complete environment containing the exact compatible Python, PyTorch/torchvision, CUDA build where applicable, MMCV compiled ops, MMEngine, MMDetection, Trackers, Supervision, SciPy, NumPy, OpenCV where required, PyAV, Pillow, and MAVI versions.

Real RTMDet-M inference must succeed in that same environment.

If neither Python 3.12 nor 3.11 can satisfy the stable Windows/Linux requirements, implementation pauses and this ADR is revisited rather than accepting resolver conflicts or an unqualified stack.

Production deployment uses exact platform/device-specific hashed locks/wheelhouses rather than loose minimum-version resolution or target-machine compilation.

### 18. Keep production fully offline

Production installation and runtime do not require:

- Internet package resolution;
- first-run model downloads;
- model-hub lookup;
- MIM remote downloads;
- remote telemetry;
- online licence validation;
- `git+https` dependencies.

Offline release bundles contain all required package/model/config/profile/qualification artifacts plus integrity manifests. Model weights remain outside Git.

### 19. Record complete immutable provenance

Task 10 constructs immutable attempt provenance covering model/config/profile/qualification/runtime hashes, complete relevant framework/dependency versions, MAVI build identity, OS/platform, actual device/runtime, driver/CUDA information where applicable, frame policy, tracker parameters, and colour-space contract.

Qualified JSON/config/lock artifacts are identified by SHA-256 over exact release bytes with deterministic repository line-ending/encoding rules.

MAVI build/commit identity is mandatory in production.

Task 10 does not add PostgreSQL persistence or a completion contract. Task 11 owns authoritative persistence of the analytical result and provenance.

### 20. Support Windows and Linux with explicit qualification duties

Task 10 formally supports Windows and Linux through one source code path.

Real-model CPU and NVIDIA inference, ByteTrack integration, secure end-to-end MP4 artifact processing, and offline installation are functional requirements on both platforms.

Ubuntu/Linux + NVIDIA remains the authoritative production-performance, long-run, recovery, and watchdog qualification target. Windows NVIDIA performance is informational, but Windows functional qualification is mandatory.

Hosted GitHub Actions remains the authoritative repository/code quality gate, with a lightweight Windows + Linux vision-adapter matrix. Hardware qualification complements but does not replace exact-head hosted CI.

## Consequences

### Positive

- RTMDet/MMDetection can evolve without contaminating MAVI's deterministic analytical pipeline.
- expensive model initialization is amortized across jobs;
- tracker state cannot leak between evidence items;
- CUDA/model lifecycle has explicit single-thread ownership;
- colour-space and coordinate boundaries are explicit and testable;
- ByteTrack output reordering/tentative-state behaviour cannot silently corrupt evidence semantics;
- complete effective config/vocabulary integrity is verified before leasing;
- `verified` has auditable engineering meaning through qualification evidence;
- offline deployment becomes reproducible and machine-verifiable;
- Windows support no longer implies weakening the Task-9 artifact security model;
- runtime failures retain stable classification while Task-9 lease authority remains intact;
- hung/poisoned native execution has a defined process-level containment path;
- model/profile/runtime provenance supports later forensic traceability;
- Windows remains a first-class functional platform while Linux/NVIDIA provides a clear production qualification authority.

### Costs and constraints

- release engineering must maintain platform/device-specific qualified binary locks and wheelhouse manifests;
- Task 10 must implement and qualify a secure native Windows staging backend;
- ML dependency upgrades become deliberate qualification events rather than casual package bumps;
- model/config/profile changes invalidate matching qualification evidence and require requalification where semantics change;
- real-model CPU/GPU qualification requires dedicated Windows and Linux test environments and model artifacts outside Git;
- hung native inference may require deliberate worker-process termination/restart rather than graceful in-process recovery;
- richer degraded-worker health reporting is deferred because worker-health-v2 remains frozen;
- Task 10 still does not make real tracks authoritative in PostgreSQL; Task 11 remains required.

## Alternatives considered

### Direct MMDetection calls inside `VideoProcessor`

Rejected because they couple the deterministic pipeline to OpenMMLab types/lifecycle and make later backend replacement difficult.

### Generic thread-pool execution for a long-lived detector runtime

Rejected because runtime construction/warm-up/inference/recovery ownership becomes implicit and may move across arbitrary worker threads. A dedicated single-thread execution lane is simpler and safer.

### Multiple detector backends in Task 10

Rejected as premature. MAVI defines the abstraction now but implements only the qualified MMDetection/RTMDet backend.

### Reuse deprecated `supervision.ByteTrack`

Rejected because the API is deprecated. MAVI retains its own tracker contract and uses a qualified current ByteTrack implementation underneath it.

### Trust ByteTrack return ordering

Rejected because the selected tracker backend may reorder returned detections. MAVI carries a frame-local detection ordinal through the adapter boundary instead.

### Backfill tentative ByteTrack observations after confirmation

Rejected because it requires reconstructing backend-private provisional identity and complicates evidence semantics. Task 10 begins the MAVI track at the first confirmed current-frame observation.

### Add a generic MAVI NMS/max-detection cap immediately

Rejected because MMDetection already performs qualified native postprocessing and no Task-10 evidence yet demonstrates that a second generic policy is needed.

### Use path normalization alone for Windows staging

Rejected because it is not security-equivalent to the existing POSIX no-follow/dirfd design and does not adequately defend against reparse/junction substitution races.

### Production `auto` device fallback

Rejected because silent CUDA-to-CPU fallback can radically change processing time and operational behaviour while appearing healthy.

### Attempt to cancel a hung native inference thread in-process

Rejected because Python cannot safely terminate arbitrary native CUDA work. Process-level containment/restart is the defined fatal path.

### Treat a manifest `verified` field as sufficient qualification

Rejected because it is self-asserted metadata. Production verification must be tied to matching machine-readable qualification evidence.

### Keep Python 3.13 as a fixed requirement

Rejected because MAVI requires a stable qualified inference stack, not a particular language minor version. Runtime compatibility is determined experimentally and frozen afterward.

## Related documents

- `AGENTS.md`
- `docs/decisions/ADR-001-technology-baseline.md`
- `docs/decisions/ADR-003-offline-production.md`
- `docs/superpowers/specs/2026-09-08-visual-intelligence-memory-design.md`
- `docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md`
