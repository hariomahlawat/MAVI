# Task 10 Qualified RTMDet + ByteTrack Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Task-9 fixture detector/tracker path with a qualified, fully offline RTMDet-M + ByteTrack Person/Vehicle runtime while preserving Task-9 lease authority, evidence integrity, artifact security, and deterministic processing semantics on Windows and Linux.

**Architecture:** Keep the existing `VideoProcessor`, `Detector`, and `Tracker` boundaries model-neutral. Add a process-scoped `MMDetectionRuntime`, a single-thread `VisionExecutionLane`, attempt-scoped RTMDet/ByteTrack/staging composition, evidence-backed model/runtime qualification, and security-equivalent POSIX/Windows staging backends. The asyncio worker thread retains lease/heartbeat authority; synchronous model work stays on the dedicated vision lane.

**Tech Stack:** Python 3.12 candidate with Python 3.11 fallback; PyTorch/torchvision; MMDetection 3.3.x-compatible MMEngine/MMCV stack selected by qualification; RTMDet-M; `trackers.ByteTrackTracker`; Supervision/SciPy/NumPy/OpenCV as tracker dependencies; PyAV/FFmpeg; Pydantic 2; pytest; GitHub Actions; Win32/NT filesystem APIs for native Windows staging; SHA-256 release integrity.

**Spec:** `docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md`

## Global Constraints

- Production reference detector is RTMDet-M; do not silently substitute another detector size or backend.
- Qualify Python 3.12 first; use Python 3.11 only if the complete stable Windows/Linux runtime graph cannot qualify on 3.12.
- Use `trackers.ByteTrackTracker`; do not build Task 10 on deprecated `supervision.ByteTrack`.
- Process every decoded frame in the Task-10 correctness baseline; no adaptive skipping or sampling.
- MAVI `DecodedFrame.image` is contiguous `uint8` RGB; the MMDetection runtime owns the single explicit RGB-to-backend colour conversion.
- Person and Vehicle have independent ByteTrack states and are both updated on every decoded frame, including empty-class frames.
- Only confirmed tracks matched to a current-frame detection emit `TrackCandidate`; predicted-only and `tracker_id == -1` outputs emit nothing and are never backfilled later.
- One worker process owns one selected detector runtime/device and at most one active video job.
- Runtime construction, warm-up, inference, safe destruction, and bounded reconstruction run on one dedicated single-thread vision execution lane.
- Production `cuda` never silently falls back to CPU. `auto` is development-only.
- Model checkpoint, resolved MMDetection config, pipeline profile, runtime locks, and qualification identity are immutable for a production worker process lifetime.
- Production effective config must be self-contained; do not rely on unresolved `_base_`, remote model-zoo aliases, environment-dependent analytical configuration, first-run downloads, or Internet telemetry.
- `verificationStatus = verified` is valid only when matching machine-readable qualification evidence exists.
- Windows support includes security-equivalent artifact staging; do not weaken the existing POSIX `dir_fd`/no-follow protections to make Windows pass.
- Lease loss outranks all detector/tracker/runtime failures. A stale attempt must not `/fail`, publish artifacts, or clean mutable filesystem state.
- `worker-health-v2` remains unchanged. Never emit its `ready` payload while the internal runtime is not actually `READY`.
- No direct Python PostgreSQL writes, Task-11 `/complete`, ReID, face recognition, ANPR, cross-camera tracking, embeddings, VLM/LLM reasoning, or behaviour classification.
- No model weights, operational CCTV, biometric datasets, credentials, or private qualification media are committed to Git.
- Hosted GitHub Actions remains authoritative for repository/code quality; hardware qualification is additional evidence, not a replacement.

---

## File Structure Locked by This Plan

```text
src/vision/
├── mavi_vision/
│   ├── common/
│   │   └── settings.py
│   ├── runtime/
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
│   │   └── rtmdet.py
│   ├── tracking/
│   │   └── bytetrack.py
│   ├── storage/
│   │   ├── artifact_store.py
│   │   ├── artifact_store_posix.py
│   │   └── artifact_store_windows.py
│   ├── pipeline/
│   │   ├── process_video.py
│   │   └── production_processor.py
│   └── worker/
│       ├── main.py
│       ├── runner.py
│       └── health.py
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
└── pyproject.toml

models/
├── manifests/
│   └── rtmdet-m-coco-phase1-v1.json
└── qualifications/
    └── rtmdet-m-coco-phase1-v1.json

.github/workflows/
├── quality-gate.yml
└── vision-adapter-gate.yml

.gitattributes
tools/verify_repo.py
tools/vision/probe_runtime.py
tools/vision/build_offline_bundle.py
tools/vision/qualify_phase1.py
```

The existing public import `mavi_vision.storage.artifact_store.StagingArtifactStore` remains stable so Task-9 pipeline/publisher callers do not need platform conditionals.

---

### Task 1: Qualify the Complete Python/OpenMMLab/Trackers Runtime Matrix

**Purpose:** Resolve the only intentionally unknown dependency values before production code begins. Exact versions are outputs of qualification, not guesses embedded in application code.

**Files:**
- Create: `tools/vision/probe_runtime.py`
- Create: `src/vision/runtime/mmdetection-phase1-v1/runtime.json`
- Create after each successful platform qualification: `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cpu.lock`
- Create after qualification: `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.lock`
- Create after qualification: `src/vision/runtime/mmdetection-phase1-v1/linux-x86_64-cpu.lock`
- Create after qualification: `src/vision/runtime/mmdetection-phase1-v1/linux-x86_64-cuda.lock`
- Modify only after a matrix is proven: `src/vision/pyproject.toml`

**Interfaces:**
- Produces: `runtime.json` containing `runtimeProfileId`, `python`, exact package versions/build identities, platform/device qualification states, and hashes of the four lock files.
- Produces: `probe_runtime.py --config <local-config> --checkpoint <local-checkpoint> --device cpu|cuda` returning exit code 0 only after a real RTMDet-M inference completes.
- Later tasks consume the exact values from `runtime.json`; they must not duplicate dependency constants.

- [ ] **Step 1: Write the runtime probe with explicit version capture**

Create `tools/vision/probe_runtime.py` with a JSON output object containing at least:

```python
{
    "python": platform.python_version(),
    "platform": platform.platform(),
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "mmcv": mmcv.__version__,
    "mmengine": mmengine.__version__,
    "mmdet": mmdet.__version__,
    "trackers": importlib.metadata.version("trackers"),
    "supervision": importlib.metadata.version("supervision"),
    "scipy": scipy.__version__,
    "numpy": np.__version__,
    "opencv": cv2.__version__,
    "av": av.__version__,
    "device": args.device,
}
```

After version capture, load the **explicit local** RTMDet-M config/checkpoint, run one inference over an in-memory RGB test image converted according to the backend contract, validate that a prediction object is returned, and print the JSON record. Do not accept a model-zoo alias or URL argument.

- [ ] **Step 2: Prove the probe fails when a local checkpoint is absent**

Run in an isolated candidate environment:

```powershell
python tools/vision/probe_runtime.py --config C:\qualification\rtmdet_m_resolved.py --checkpoint C:\qualification\missing.pth --device cpu
```

Expected: non-zero exit before any download attempt. Network logs must show no model download request.

- [ ] **Step 3: Qualify Python 3.12 as the first candidate on Linux CPU**

Create a clean Python 3.12 virtual environment, install one internally consistent stable stack satisfying MMDetection 3.3.x compatibility constraints, install MAVI and the selected `trackers` package, and run:

```bash
python tools/vision/probe_runtime.py \
  --config /qualification/rtmdet_m_resolved.py \
  --checkpoint /qualification/rtmdet_m.pth \
  --device cpu > linux-cpu-probe.json
```

Acceptance: process exits 0 and `linux-cpu-probe.json` records the complete environment. If dependency resolution or real inference fails, preserve the failure log and continue the same experiment with Python 3.11 rather than forcing incompatible dependencies.

- [ ] **Step 4: Repeat the identical candidate graph on Windows CPU**

```powershell
python tools/vision/probe_runtime.py `
  --config C:\qualification\rtmdet_m_resolved.py `
  --checkpoint C:\qualification\rtmdet_m.pth `
  --device cpu > windows-cpu-probe.json
```

Acceptance: exact semantic package versions match the Linux candidate where the platform permits; platform-specific wheel/build identities may differ.

- [ ] **Step 5: Qualify the selected candidate on Linux NVIDIA and Windows NVIDIA**

Run the same probe with `--device cuda` on both target platforms. Record `torch.version.cuda`, GPU name, driver/runtime details, and the exact PyTorch/MMCV wheel build identities.

Acceptance: real RTMDet-M inference completes on each target. If no complete Python 3.12 graph can pass all four environments, restart Steps 3–5 with Python 3.11. If neither Python minor passes, **stop Task 10 and reopen ADR-005**; do not continue implementation with an unqualified graph.

- [ ] **Step 6: Freeze the exact environment**

Write `runtime.json` from the four successful probe records and generate four hash-locked requirement files. Each lock must contain exact versions and hashes suitable for `pip --require-hashes`; CPU and CUDA graphs may differ where binary packages differ.

`runtime.json` must explicitly record:

```json
{
  "schemaVersion": "1.0",
  "runtimeProfileId": "mmdetection-phase1-v1",
  "pythonMinor": "3.12",
  "platformVariants": [
    "windows-x86_64-cpu",
    "windows-x86_64-cuda",
    "linux-x86_64-cpu",
    "linux-x86_64-cuda"
  ]
}
```

Use the actually qualified Python minor in `pythonMinor`; the shown `3.12` is correct only if 3.12 passed all required gates.

- [ ] **Step 7: Update the package Python requirement only after qualification**

Change `requires-python` from `>=3.13` to an exact compatible minor range that includes the selected qualified minor and excludes an unqualified next minor. For a qualified 3.12 runtime, use:

```toml
requires-python = ">=3.12,<3.13"
```

For a qualified 3.11 runtime, use `>=3.11,<3.12` instead.

Do not yet put heavyweight MMDetection dependencies into the base `dependencies` list; later tasks add a dedicated optional runtime extra using the versions frozen here.

- [ ] **Step 8: Commit the qualification baseline**

```powershell
git add tools/vision/probe_runtime.py src/vision/runtime/mmdetection-phase1-v1 src/vision/pyproject.toml
git commit -m "build: qualify phase1 vision runtime matrix"
```

**Reviewer gate:** Reject this task if any of the four platform/device variants is merely inferred from another platform, if real RTMDet-M inference was not executed, or if dependency conflicts were bypassed with `--no-deps`.

---

### Task 2: Make Attempt Staging Secure on Both POSIX and Native Windows

**Files:**
- Modify: `src/vision/mavi_vision/storage/artifact_store.py`
- Create: `src/vision/mavi_vision/storage/artifact_store_posix.py`
- Create: `src/vision/mavi_vision/storage/artifact_store_windows.py`
- Modify: `src/vision/tests/test_artifact_store.py`
- Create: `src/vision/tests/test_artifact_store_windows.py`
- Modify if type imports require it: `src/vision/mavi_vision/storage/artifact_publisher.py`

**Interfaces:**
- Preserve public constructor: `StagingArtifactStore(media_root: Path, job_id: UUID, attempt_count: int)`.
- Preserve methods/properties: `job_id`, `attempt_count`, `thumbnail_key()`, `trajectory_key()`, `write_bytes()`, `cleanup()`.
- `artifact_store.py` becomes the platform facade and owns shared logical validation/error codes; POSIX and Windows backends implement the same internal protocol.

- [ ] **Step 1: Move the current POSIX implementation behind the facade without changing behaviour**

Write a failing compatibility test that imports `StagingArtifactStore` from the same module and verifies the exact existing key format and error codes.

Run:

```powershell
cd src/vision
python -m pytest tests/test_artifact_store.py -q
```

Expected before refactor: PASS. Treat this as the behaviour lock.

Move the current hardened `dir_fd`/`O_NOFOLLOW` implementation into `artifact_store_posix.py`, keep `StagingArtifactError` and common track/relative-name validation in `artifact_store.py`, and delegate based on `os.name`.

Run the same suite and require identical results.

- [ ] **Step 2: Write Windows path/reparse tests before the Windows backend**

Create Windows-only tests guarded with `pytest.mark.skipif(os.name != "nt", ...)` covering:

```python
def test_windows_rejects_junction_in_attempt_ancestry(...): ...
def test_windows_parent_swap_cannot_redirect_publish(...): ...
def test_windows_cleanup_does_not_follow_reparse_point(...): ...
def test_windows_sibling_attempt_is_preserved(...): ...
def test_windows_publish_rechecks_authority_immediately_before_replace(...): ...
```

Use a real NTFS junction for the mandatory reparse test. Create it with `cmd /c mklink /J <link> <target>` so the test does not depend on Developer Mode symlink privileges.

Run on a native Windows checkout:

```powershell
cd src/vision
python -m pytest tests/test_artifact_store_windows.py -q
```

Expected: FAIL because the Windows backend does not exist.

- [ ] **Step 3: Implement a small handle-relative Win32/NT helper layer**

In `artifact_store_windows.py`, isolate native calls behind helpers with these responsibilities:

```python
class _WindowsHandle:
    value: int
    def close(self) -> None: ...


def _open_directory_no_reparse(path: Path) -> _WindowsHandle: ...
def _open_child_directory_no_reparse(parent: _WindowsHandle, name: str, *, create: bool) -> _WindowsHandle: ...
def _create_exclusive_child_file(parent: _WindowsHandle, name: str) -> _WindowsHandle: ...
def _replace_child_file(parent: _WindowsHandle, temporary_name: str, destination_name: str) -> None: ...
def _directory_identity(handle: _WindowsHandle) -> tuple[int, int]: ...
def _remove_attempt_tree_no_reparse(parent: _WindowsHandle, name: str) -> None: ...
```

Use Windows handle APIs with `FILE_FLAG_OPEN_REPARSE_POINT`/directory semantics and a handle-relative create/rename strategy. Do not implement security by `Path.resolve()` plus prefix checking. Reject traversed entries with reparse semantics; compare directory identity before and after publication.

- [ ] **Step 4: Implement the Windows staging backend with the same mutation boundary as POSIX**

`write_bytes()` must:

1. validate the logical relative name before filesystem mutation;
2. open/create only the exact `staging/<job>/attempt-XXXX/...` ancestry using no-reparse handle semantics;
3. create an exclusive temporary sibling;
4. write and flush file bytes;
5. revalidate parent identity;
6. call `authorize_publish()` immediately before destination replacement;
7. replace inside the validated same directory;
8. revalidate parent identity again;
9. roll back a publication known to have raced;
10. close every native handle in `finally`.

`cleanup()` removes only the current attempt subtree and never follows a reparse point.

- [ ] **Step 5: Run platform security tests**

Linux/POSIX:

```bash
cd src/vision
python -m pytest tests/test_artifact_store.py tests/test_artifact_publisher.py -q
```

Windows:

```powershell
cd src/vision
python -m pytest tests/test_artifact_store.py tests/test_artifact_store_windows.py tests/test_artifact_publisher.py -q
```

Expected: all applicable tests pass; Windows no longer raises `secure_staging_unavailable` for normal secure operation.

- [ ] **Step 6: Commit**

```powershell
git add src/vision/mavi_vision/storage src/vision/tests/test_artifact_store.py src/vision/tests/test_artifact_store_windows.py
git commit -m "feat: add secure windows attempt staging"
```

**Reviewer gate:** If the Windows implementation cannot prove link/reparse and directory-substitution safety, stop and revisit the formal Windows-support decision; do not weaken the POSIX backend.

---

### Task 3: Add Model Manifest, Pipeline Profile, Qualification Record, and Exact-Byte Integrity

**Files:**
- Create: `src/vision/mavi_vision/runtime/manifest.py`
- Create: `src/vision/mavi_vision/runtime/profile.py`
- Create: `src/vision/mavi_vision/runtime/qualification.py`
- Create: `src/vision/tests/test_model_manifest.py`
- Create: `src/vision/tests/test_pipeline_profile.py`
- Create: `src/vision/tests/test_qualification_record.py`
- Create: `src/vision/tests/test_runtime_artifact_hashing.py`
- Create: `src/vision/config/pipelines/phase1-detection-tracking-v1.json`
- Create: `models/manifests/rtmdet-m-coco-phase1-v1.json`
- Create initially as unverified evidence shell, then finalized in Task 14: `models/qualifications/rtmdet-m-coco-phase1-v1.json`
- Create: `.gitattributes`
- Modify: `tools/verify_repo.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ArtifactRef:
    relative_path: str
    sha256: str

@dataclass(frozen=True, slots=True)
class ModelManifest:
    schema_version: str
    model_id: str
    model_version: str
    backend: str
    architecture: str
    class_vocabulary: tuple[str, ...]
    checkpoint: ArtifactRef
    resolved_config: ArtifactRef
    runtime_profile_id: str
    verification_status: Literal["verified", "unverified"]
    qualification_id: str | None

@dataclass(frozen=True, slots=True)
class PipelineProfile:
    schema_version: str
    profile_id: str
    profile_version: str
    model_id: str
    detector_inference_floor: float
    allowed_source_classes: tuple[str, ...]
    class_mapping: Mapping[str, ObjectClass]
    tracker: ByteTrackProfile
    frame_policy: Literal["every-frame"]

@dataclass(frozen=True, slots=True)
class QualificationRecord:
    schema_version: str
    qualification_id: str
    model_id: str
    model_manifest_sha256: str
    checkpoint_sha256: str
    resolved_config_sha256: str
    pipeline_profile_sha256: str
    runtime_profile_id: str
    runtime_profile_sha256: str
    required_gates: Mapping[str, Literal["passed", "pending"]]


def sha256_release_file(path: Path) -> str: ...
def load_model_manifest(path: Path) -> ModelManifest: ...
def load_pipeline_profile(path: Path) -> PipelineProfile: ...
def load_qualification_record(path: Path) -> QualificationRecord: ...
def verify_release_selection(...) -> VerifiedReleaseSelection: ...
```

- [ ] **Step 1: Lock exact-byte JSON rules**

Create `.gitattributes`:

```gitattributes
*.json text eol=lf
*.lock text eol=lf
*.py text eol=lf
```

Write tests that reject BOM-bearing JSON and CRLF in qualified release JSON files, and verify `sha256_release_file()` hashes the exact UTF-8 bytes on disk rather than parsing/re-serializing JSON.

- [ ] **Step 2: Write failing manifest validation tests**

Cover:

```python
def test_manifest_rejects_absolute_artifact_path(): ...
def test_manifest_rejects_url_artifact_path(): ...
def test_manifest_rejects_bad_sha256(): ...
def test_manifest_requires_ordered_nonempty_vocabulary(): ...
def test_verified_manifest_requires_qualification_id(): ...
def test_model_paths_cannot_escape_model_root_through_dotdot(): ...
```

Run:

```powershell
cd src/vision
python -m pytest tests/test_model_manifest.py tests/test_runtime_artifact_hashing.py -q
```

Expected: FAIL because the loaders do not exist.

- [ ] **Step 3: Implement strict manifest loading**

Use Pydantic or explicit dataclass construction with `extra="forbid"` semantics. Artifact paths are logical forward-slash relative paths only; reject leading slash, drive prefix, backslash, `.`/`..`, URL schemes, and path segments that escape the configured model root after no-follow-safe resolution.

- [ ] **Step 4: Write failing pipeline-profile tests**

Freeze Phase-1 behaviour:

```json
{
  "schemaVersion": "1.0",
  "profileId": "phase1-detection-tracking-v1",
  "profileVersion": "1",
  "modelId": "rtmdet-m-coco-phase1",
  "allowedSourceClasses": ["person", "car", "motorcycle", "bus", "truck"],
  "classMapping": {
    "person": "person",
    "car": "vehicle",
    "motorcycle": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle"
  },
  "framePolicy": "every-frame"
}
```

Do **not** add a generic `maxDetections` field in Task 10. Tracker numeric values and detector floor are inserted from the actual qualified profile, not environment variables.

Test ranges and identity relationships: detector floor in `[0,1]`; ByteTrack thresholds in `[0,1]`; positive frame rate/buffer/consecutive-frame values; mapping keys subset of manifest vocabulary; frame policy exactly `every-frame`.

- [ ] **Step 5: Implement profile loading and immutable profile hash**

`load_pipeline_profile()` returns a frozen model. The provenance hash is the exact file SHA-256 from `sha256_release_file()`, not a JSON reserialization hash.

- [ ] **Step 6: Write qualification-evidence tests**

Tests must prove that a manifest with `verificationStatus="verified"` is rejected unless:

- referenced qualification record exists;
- model/checkpoint/resolved-config/profile/runtime hashes all match;
- every mandatory platform gate is `passed`;
- `runtimeProfileId` matches the selected runtime profile.

For development, `unverified` may load only when the caller explicitly sets `allow_unverified=True`; integrity hashes still apply.

- [ ] **Step 7: Implement `verify_release_selection()`**

Return one immutable object containing the loaded models plus exact artifact hashes and resolved local paths. Production code after this point consumes `VerifiedReleaseSelection` rather than separately re-reading manifest/profile files.

- [ ] **Step 8: Extend repository verification**

Add checks to `tools/verify_repo.py` for:

- manifest/profile/qualification JSON parse and schema validation;
- exact 64-character lowercase SHA-256 syntax;
- no absolute path/backslash/URL in production release artifacts;
- no tracked weights/media/secrets;
- verified manifest ↔ qualification identity consistency;
- LF/no-BOM rules for qualified JSON/lock files;
- no production manifest whose verification evidence is pending.

During implementation before Task 14, keep the committed manifest explicitly `unverified` so repository verification does not falsely certify it for production.

- [ ] **Step 9: Run tests and repository verification**

```powershell
cd src/vision
python -m pytest tests/test_model_manifest.py tests/test_pipeline_profile.py tests/test_qualification_record.py tests/test_runtime_artifact_hashing.py -q
cd ../..
python tools/verify_repo.py
```

Expected: PASS with the development manifest unverified and all structural rules enforced.

- [ ] **Step 10: Commit**

```powershell
git add .gitattributes models src/vision/config src/vision/mavi_vision/runtime/manifest.py src/vision/mavi_vision/runtime/profile.py src/vision/mavi_vision/runtime/qualification.py src/vision/tests tools/verify_repo.py
git commit -m "feat: add verified vision release metadata"
```

---

### Task 4: Add Framework-Neutral Runtime Contracts, Typed Failures, Device Policy, and Provenance

**Files:**
- Create: `src/vision/mavi_vision/runtime/__init__.py`
- Create: `src/vision/mavi_vision/runtime/interfaces.py`
- Create: `src/vision/mavi_vision/runtime/errors.py`
- Create: `src/vision/mavi_vision/runtime/provenance.py`
- Modify: `src/vision/mavi_vision/common/settings.py`
- Create: `src/vision/tests/test_runtime_provenance.py`
- Modify/Create settings tests in: `src/vision/tests/test_worker_settings.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class PixelBoxXYXY:
    x1: float
    y1: float
    x2: float
    y2: float

@dataclass(frozen=True, slots=True)
class RawDetection:
    source_class: str
    confidence: float
    bounding_box: PixelBoxXYXY

@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    backend: str
    model_id: str
    device: str
    versions: Mapping[str, str]
    ordered_class_vocabulary: tuple[str, ...]

class DetectorRuntime(Protocol):
    @property
    def metadata(self) -> RuntimeMetadata: ...
    def warmup(self) -> None: ...
    def infer(self, image_rgb: NDArray[np.uint8]) -> Sequence[RawDetection]: ...
    def close(self) -> None: ...

class RuntimeDisposition(StrEnum):
    CONTINUE = "continue"
    RECOVER = "recover"
    UNAVAILABLE = "unavailable"

class ProcessingDependencyError(RuntimeError):
    code: str
    disposition: RuntimeDisposition
```

- [ ] **Step 1: Write failing validation tests for `PixelBoxXYXY` and `RawDetection`**

Require finite coordinates/confidence, confidence `[0,1]`, non-empty source class. Do not require the raw box to be inside the frame; clipping belongs to the RTMDet adapter.

- [ ] **Step 2: Implement the framework-neutral types**

No import from `torch`, `mmdet`, `mmcv`, `supervision`, or `trackers` is permitted in `interfaces.py`, `errors.py`, or `provenance.py`.

- [ ] **Step 3: Write typed failure tests**

Instantiate:

```python
GpuOutOfMemoryError("vision_gpu_out_of_memory", RuntimeDisposition.RECOVER)
GpuRuntimeError("vision_gpu_runtime_failed", RuntimeDisposition.UNAVAILABLE)
InferenceContractError("vision_inference_contract_failed", RuntimeDisposition.RECOVER)
TrackerError("vision_tracker_failed", RuntimeDisposition.CONTINUE)
```

Require every external code to match the worker control-plane failure-code grammar and remain <=64 characters.

- [ ] **Step 4: Implement typed errors**

Framework exceptions are not parsed above their adapter. Give backend adapters helper constructors/translation functions; keep stable external codes centralized in `errors.py`.

- [ ] **Step 5: Extend `WorkerSettings` with operational selection only**

Add fields equivalent to:

```python
model_root: Path
model_manifest: Path
pipeline_profile: Path
runtime_profile: Path
device_policy: Literal["cuda", "cpu", "auto"] = "cuda"
device_index: int = Field(default=0, ge=0)
production_mode: bool = True
inference_watchdog_seconds: float = Field(default=120.0, ge=10.0)
watchdog_grace_seconds: float = Field(default=10.0, ge=1.0, le=60.0)
```

Validation: `production_mode=True` rejects `device_policy="auto"`. Do not add detector/tracker threshold environment settings.

- [ ] **Step 6: Implement immutable provenance**

`RuntimeProvenance` records at least model/config/profile/qualification/runtime hashes, Python, PyTorch, torchvision, MMDetection, MMCV, MMEngine, Trackers, Supervision, SciPy, NumPy, OpenCV, PyAV/FFmpeg identity where available, OS/platform, configured/actual device, GPU/driver/CUDA identity where applicable, MAVI commit/build identity, frame policy, tracker parameters, and `inputColourSpace="RGB"`.

Production construction rejects a missing MAVI build/commit identity; development may use an explicit `"unknown-development"` marker.

- [ ] **Step 7: Run tests**

```powershell
cd src/vision
python -m pytest tests/test_runtime_provenance.py tests/test_worker_settings.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add src/vision/mavi_vision/runtime src/vision/mavi_vision/common/settings.py src/vision/tests
git commit -m "feat: add vision runtime contracts and provenance"
```

---

### Task 5: Add the Single-Thread Vision Execution Lane and Activity Monitor

**Files:**
- Create: `src/vision/mavi_vision/runtime/execution_lane.py`
- Create: `src/vision/mavi_vision/runtime/activity.py`
- Create: `src/vision/tests/test_runtime_execution_lane.py`
- Create: `src/vision/tests/test_runtime_watchdog.py`

**Interfaces:**

```python
class VisionExecutionLane:
    async def run(self, func: Callable[..., T], /, *args: object, **kwargs: object) -> T: ...
    async def close(self) -> None: ...

@dataclass(frozen=True, slots=True)
class InferenceActivitySnapshot:
    active: bool
    started_monotonic: float | None
    completed_count: int

class InferenceActivity:
    def mark_started(self) -> None: ...
    def mark_completed(self) -> None: ...
    def snapshot(self) -> InferenceActivitySnapshot: ...
    def is_hung(self, *, now_monotonic: float, threshold_seconds: float) -> bool: ...
```

- [ ] **Step 1: Write a failing serialization test**

Submit two functions concurrently through `VisionExecutionLane`; each records `threading.get_ident()`. Assert they never overlap and both execute on the same non-event-loop thread.

- [ ] **Step 2: Implement the lane**

Use one `ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-vision")`. `run()` uses the current event loop's `run_in_executor` with a `functools.partial` so keyword arguments are supported. Reject calls after `close()`.

- [ ] **Step 3: Write activity/watchdog tests using an injected clock value**

Test inactive, active below threshold, active exactly at threshold, and active beyond threshold. Keep monotonic time values explicit in tests; do not sleep.

- [ ] **Step 4: Implement thread-safe activity markers**

Protect state with `threading.Lock`. `mark_completed()` must clear `active` in `finally` paths even when inference fails.

- [ ] **Step 5: Run tests and commit**

```powershell
cd src/vision
python -m pytest tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py -q
git add mavi_vision/runtime tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py
git commit -m "feat: add dedicated vision execution lane"
```

---

### Task 6: Implement the RTMDet-to-MAVI Detection Adapter with Deterministic Geometry

**Files:**
- Create: `src/vision/mavi_vision/detection/rtmdet.py`
- Create: `src/vision/tests/test_rtmdet_mapping.py`
- Create: `src/vision/tests/test_rtmdet_geometry.py`

**Interfaces:**

```python
class RTMDetDetector:
    def __init__(self, runtime: DetectorRuntime, profile: PipelineProfile) -> None: ...
    def detect(self, frame: DecodedFrame) -> Sequence[DetectionCandidate]: ...
```

`detect()` returns candidates sorted exactly by:

```python
(
    candidate.object_class.value,
    -candidate.confidence,
    candidate.bounding_box.x,
    candidate.bounding_box.y,
    candidate.bounding_box.width,
    candidate.bounding_box.height,
)
```

- [ ] **Step 1: Write class-mapping tests with a fake `DetectorRuntime`**

Feed source classes `person`, `car`, `motorcycle`, `bus`, `truck`, `dog`. Assert MAVI output is Person/Vehicle for the first five and ignores `dog` according to the profile.

- [ ] **Step 2: Write adversarial geometry tests**

Cover in-frame, all four partial overflows, larger-than-frame, fractional XYXY, zero area after clipping, inverted XYXY, NaN/Inf, portrait/landscape/odd frame sizes.

Required policy:

- finite partly-outside box -> clip;
- zero area after clipping -> discard and increment diagnostic counter/log event;
- inverted/malformed/non-finite/impossible confidence/vocabulary mismatch -> `InferenceContractError`;
- accepted box -> exact normalized XYWH satisfying `NormalizedBoundingBox`.

- [ ] **Step 3: Implement normalization with no second NMS**

Call `runtime.infer(frame.image)` once. Do not perform generic NMS or generic detection-count truncation. Validate source class against manifest/profile vocabulary before mapping.

- [ ] **Step 4: Write deterministic-order test**

Return fake raw detections in multiple permutations and assert the same ordered `DetectionCandidate` tuple is emitted.

- [ ] **Step 5: Run tests and commit**

```powershell
cd src/vision
python -m pytest tests/test_rtmdet_mapping.py tests/test_rtmdet_geometry.py -q
git add mavi_vision/detection/rtmdet.py tests/test_rtmdet_mapping.py tests/test_rtmdet_geometry.py
git commit -m "feat: add deterministic RTMDet adapter"
```

---

### Task 7: Implement the Real MMDetection/RTMDet Runtime with Resolved Config, Vocabulary Verification, and RGB→BGR Boundary

**Files:**
- Create: `src/vision/mavi_vision/runtime/mmdetection.py`
- Create: `src/vision/tests/test_rtmdet_colour_space.py`
- Add lightweight contract tests to: `src/vision/tests/test_runtime_provenance.py`
- Modify: `src/vision/pyproject.toml`

**Interfaces:**

```python
class MMDetectionRuntime(DetectorRuntime):
    def __init__(
        self,
        release: VerifiedReleaseSelection,
        *,
        device: str,
        activity: InferenceActivity,
    ) -> None: ...

    @property
    def metadata(self) -> RuntimeMetadata: ...
    def warmup(self) -> None: ...
    def infer(self, image_rgb: NDArray[np.uint8]) -> Sequence[RawDetection]: ...
    def close(self) -> None: ...
```

- [ ] **Step 1: Add the qualified runtime optional dependency group**

Using the exact versions produced by Task 1, add a dedicated extra such as:

```toml
[project.optional-dependencies]
vision-runtime = [
  # exact compatible logical requirements corresponding to runtime.json
]
dev = ["pytest>=8.4"]
```

Do not add model weights or download hooks. Base Task-9/core tests must still install without the heavy extra.

- [ ] **Step 2: Write the RGB/BGR regression test before importing the heavy stack**

Expose one internal pure helper:

```python
def _rgb_to_bgr(image_rgb: NDArray[np.uint8]) -> NDArray[np.uint8]: ...
```

Test input pixel `[11, 22, 33]` becomes `[33, 22, 11]`, remains `uint8`, H×W×3, contiguous, and does not mutate the source array.

- [ ] **Step 3: Implement lazy framework imports**

Do not import MMDetection/PyTorch at module import time for code paths that only run core tests. Resolve heavy imports inside runtime construction or a small backend-loader helper and translate ImportError/version mismatch to `RuntimeCompatibilityError` before leasing.

- [ ] **Step 4: Load only explicit local resolved config/checkpoint paths**

Use the verified local paths from `VerifiedReleaseSelection`; never pass a model-zoo alias. Before model construction, reject a deployment config containing unresolved `_base_`, URL references, or code that redirects model artifacts outside the trusted release directory according to the approved config-validation rule.

- [ ] **Step 5: Verify ordered runtime vocabulary exactly**

After construction, read the detector's runtime dataset/class metadata and require exact ordered equality with `ModelManifest.class_vocabulary`. Mismatch -> `RuntimeCompatibilityError`/UNAVAILABLE before any lease.

- [ ] **Step 6: Implement warm-up**

Generate an in-memory, channel-distinct RGB frame of a valid RTMDet input shape; convert once to backend BGR; run inference; validate result shape/types; do not create evidence artifacts. Warm-up must execute on `VisionExecutionLane` in later composition.

- [ ] **Step 7: Implement inference result conversion**

Wrap each call with:

```python
activity.mark_started()
try:
    # RGB -> BGR once; run MMDetection; map boxes/scores/labels to RawDetection
finally:
    activity.mark_completed()
```

Return original-decoded-frame pixel XYXY coordinates. Translate CUDA OOM, poisoned CUDA errors, and invalid output to the typed MAVI errors defined in Task 4. Do not expose tensors/`DetDataSample` objects.

- [ ] **Step 8: Run pure tests and a local real-model smoke test**

Fast test:

```powershell
cd src/vision
python -m pytest tests/test_rtmdet_colour_space.py tests/test_rtmdet_mapping.py tests/test_rtmdet_geometry.py -q
```

Real local smoke on a machine with the qualified extra/model:

```powershell
python ../../tools/vision/probe_runtime.py --config <resolved-config> --checkpoint <checkpoint> --device cpu
```

Expected: PASS, no network access, ordered vocabulary verified.

- [ ] **Step 9: Commit**

```powershell
git add src/vision/mavi_vision/runtime/mmdetection.py src/vision/tests/test_rtmdet_colour_space.py src/vision/pyproject.toml
git commit -m "feat: integrate local RTMDet runtime"
```

---

### Task 8: Implement Class-Separated ByteTrack with Timestamped Empty-Frame Updates and Stable Ordinal Round-Trip

**Files:**
- Create: `src/vision/mavi_vision/tracking/bytetrack.py`
- Create: `src/vision/tests/test_bytetrack_adapter.py`

**Interfaces:**

```python
class ByteTrackTracker:
    def __init__(self, profile: ByteTrackProfile) -> None: ...
    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> Sequence[TrackCandidate]: ...
```

Internally it owns exactly two native trackers: Person and Vehicle.

- [ ] **Step 1: Write failing pixel-conversion and timestamp tests**

For a 200×100 frame and normalized box `(x=.1, y=.2, width=.3, height=.4)`, assert native ByteTrack receives XYXY `[20, 20, 80, 60]` and timestamp `frame.offset_ms / 1000.0`.

- [ ] **Step 2: Write the every-class/every-frame ageing test**

Provide only Person detections for several frames and assert the Vehicle native tracker is still called with an empty detection set on every frame. Repeat symmetrically for Person.

- [ ] **Step 3: Write result-reordering/ordinal tests**

When constructing `sv.Detections`, attach frame-local ordinals in `data["mavi_ordinal"]`. Use a fake native tracker that returns detections in a different order and assert emitted MAVI candidates recover the original normalized box and detector confidence by ordinal, not returned-array position.

- [ ] **Step 4: Write tentative/unmatched evidence tests**

Assert `tracker_id == -1` emits no `TrackCandidate`. Assert an unmatched/predicted native track emits nothing. When a track confirms later, the first MAVI trajectory observation is the confirmation frame; no prior tentative observation is backfilled.

- [ ] **Step 5: Write class-isolation and deterministic-ID tests**

Test Person and Vehicle native ID `1` simultaneously; expected MAVI IDs remain independent namespaces such as `person-000001` and `vehicle-000001`.

For multiple newly confirmed tracks on the same frame, sort new mappings by:

```python
(bbox.x, bbox.y, bbox.width, bbox.height, -confidence, mavi_ordinal)
```

Assign counters only after this sort. Never expose the native tracker ID as the MAVI ID or use it as the ordering source.

- [ ] **Step 6: Write occlusion/expiry sequence tests using the actual qualified `trackers` package**

Cover continuous object, crossing objects, short occlusion/reacquisition, long disappearance/new ID, low-confidence second-stage association, empty scene, and VFR timestamp gaps.

- [ ] **Step 7: Implement adapter and translate backend errors**

Any tracker-library exception becomes `TrackerError(code="vision_tracker_failed", disposition=CONTINUE)`. The next attempt receives fresh tracker instances.

- [ ] **Step 8: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_bytetrack_adapter.py -q
git add mavi_vision/tracking/bytetrack.py tests/test_bytetrack_adapter.py
git commit -m "feat: add class-safe ByteTrack adapter"
```

---

### Task 9: Compose a Fresh Attempt Pipeline Around the Shared Detector Runtime

**Files:**
- Create: `src/vision/mavi_vision/pipeline/production_processor.py`
- Create: `src/vision/tests/test_production_processor.py`

**Interfaces:**

```python
class ProductionVisionProcessor:
    def __init__(
        self,
        runtime: DetectorRuntime,
        profile: PipelineProfile,
        staging_factory: Callable[[Path, UUID, int], StagingArtifactStore],
        runtime_failure_sink: Callable[[ProcessingDependencyError], None],
    ) -> None: ...

    def process(
        self,
        *,
        job_id: UUID,
        attempt_count: int,
        source_path: Path,
        expected_source_size_bytes: int,
        expected_source_sha256: str,
        lease_guard: LeaseGuard,
    ) -> VisionProcessingResult: ...
```

- [ ] **Step 1: Write a failing lifecycle test**

Call `process()` twice with a fake long-lived detector runtime. Assert:

- detector runtime object identity is unchanged;
- a new `RTMDetDetector`, ByteTrack adapter, staging store, and `VideoProcessor` are created for each attempt;
- track IDs restart per attempt;
- attempt staging keys contain the correct attempt count.

- [ ] **Step 2: Write a failure-notification test**

Have the detector raise `GpuOutOfMemoryError`; assert `runtime_failure_sink` receives the exact error once and the same typed error is rethrown. Have the tracker raise `TrackerError`; assert the sink receives `CONTINUE` and no detector-runtime replacement happens inside this class.

- [ ] **Step 3: Implement the minimal composition facade**

Do not put lease acquisition, heartbeat, CUDA recovery, or Task-11 persistence in this class. It creates attempt-scoped collaborators and delegates to the existing `VideoProcessor`.

- [ ] **Step 4: Run tests and commit**

```powershell
cd src/vision
python -m pytest tests/test_production_processor.py tests/test_process_video.py -q
git add mavi_vision/pipeline/production_processor.py tests/test_production_processor.py
git commit -m "feat: compose production vision attempts"
```

---

### Task 10: Preserve Typed Runtime/Tracker Failure Classification Through Task-9 Lease Semantics

**Files:**
- Modify: `src/vision/mavi_vision/pipeline/process_video.py`
- Modify: `src/vision/mavi_vision/worker/runner.py`
- Modify: `src/vision/tests/test_process_video.py`
- Modify: `src/vision/tests/test_worker_runner.py`
- Modify: `src/vision/tests/test_lease_ownership_matrix.py`

**Interfaces:**
- `VideoProcessor` passes `ProcessingDependencyError` through unchanged after lease-authorized best-effort cleanup.
- `WorkerRunner` allowlists `ProcessingDependencyError.code` and maps only the approved codes to `/fail` after ownership is rechecked.
- Existing `LeaseLostError` precedence remains unchanged.

- [ ] **Step 1: Write the red test proving Task-9 currently collapses a typed detector failure**

Use a detector that raises `GpuOutOfMemoryError`. Expected new behaviour: `VideoProcessor.process()` rethrows that exact typed error, not `VideoProcessingError("pipeline_processing_failed")`.

Run the test and confirm it fails against the current Task-9 catch-all.

- [ ] **Step 2: Add the narrow pass-through catch**

In both processing/finalization exception blocks, place `except ProcessingDependencyError:` before generic `Exception`, invoke `_cleanup_best_effort(lease_guard)`, then `raise` unchanged. Do not import CUDA/MMDetection types.

- [ ] **Step 3: Write runner failure-code tests**

For each approved job-scoped code:

```text
vision_inference_contract_failed
vision_gpu_out_of_memory
vision_gpu_runtime_failed
vision_tracker_failed
```

assert exactly one `/fail` call with a sanitized generic message while the lease is owned.

- [ ] **Step 4: Write lease-loss race tests for typed errors**

Force the typed error to become ready at the same time the lease guard expires. Assert lease loss wins and the API sees **no** `/fail` call.

- [ ] **Step 5: Implement allowlisted handling in `WorkerRunner`**

Do not forward arbitrary exception text as a failure code. Unknown `ProcessingDependencyError.code` becomes generic `vision_processing_failed` locally logged as a programming error, while the known allowlist retains stable codes.

- [ ] **Step 6: Run Task-9 ownership regression suite**

```powershell
cd src/vision
python -m pytest tests/test_process_video.py tests/test_worker_runner.py tests/test_lease_ownership_matrix.py tests/test_artifact_publisher.py tests/test_artifact_store.py -q
```

- [ ] **Step 7: Commit**

```powershell
git add mavi_vision/pipeline/process_video.py mavi_vision/worker/runner.py tests/test_process_video.py tests/test_worker_runner.py tests/test_lease_ownership_matrix.py
git commit -m "feat: preserve vision runtime failure classification"
```

---

### Task 11: Implement Runtime Supervisor, Readiness Gate, OOM Recovery, Watchdog, and Production Worker Composition

**Files:**
- Create: `src/vision/mavi_vision/runtime/supervisor.py`
- Modify: `src/vision/mavi_vision/worker/main.py`
- Modify: `src/vision/mavi_vision/worker/runner.py`
- Modify: `src/vision/mavi_vision/worker/health.py`
- Create: `src/vision/tests/test_runtime_supervisor.py`
- Extend: `src/vision/tests/test_runtime_watchdog.py`
- Modify: `src/vision/tests/test_worker_runner.py`

**Interfaces:**

```python
class RuntimeState(StrEnum):
    STARTING = "starting"
    READY = "ready"
    RECOVERING = "recovering"
    UNAVAILABLE = "unavailable"
    STOPPING = "stopping"

class RuntimeSupervisor:
    @property
    def state(self) -> RuntimeState: ...
    @property
    def runtime(self) -> DetectorRuntime: ...
    async def start(self) -> None: ...
    def report_processing_failure(self, error: ProcessingDependencyError) -> None: ...
    async def recover_if_required(self) -> None: ...
    async def close(self) -> None: ...
```

The worker's outer loop calls `runner.run_once()` only when supervisor state is `READY`.

- [ ] **Step 1: Write startup state-machine tests**

Cases:

- valid verified release + warm-up -> `READY`;
- missing model/config/hash mismatch -> `UNAVAILABLE`, lease calls = 0;
- requested CUDA unavailable -> `UNAVAILABLE`, lease calls = 0;
- warm-up failure -> `UNAVAILABLE`, lease calls = 0;
- production `auto` -> configuration rejection before leasing.

Use fake runtimes and fake lane functions; do not require PyTorch for state-machine unit tests.

- [ ] **Step 2: Implement supervisor startup on the dedicated lane**

`start()` performs release verification before runtime construction, then executes construction/warm-up/output/vocabulary validation via `VisionExecutionLane.run()`. State changes are explicit and guarded by an asyncio lock or single-event-loop ownership.

- [ ] **Step 3: Write OOM recovery tests**

After `report_processing_failure(GpuOutOfMemoryError(...RECOVER))`:

- state immediately becomes `RECOVERING`;
- no new lease is requested;
- `recover_if_required()` closes/reconstructs the **same release/model/profile/device** once;
- warm-up success -> `READY`;
- warm-up failure -> `UNAVAILABLE`;
- a second automatic reconstruction for the same incident is not attempted.

- [ ] **Step 4: Write poisoned-runtime tests**

`GpuRuntimeError(...UNAVAILABLE)` moves directly to `UNAVAILABLE`; `recover_if_required()` does not try to reuse/reconstruct a process context classified as poisoned.

`TrackerError(...CONTINUE)` leaves the detector runtime `READY`.

- [ ] **Step 5: Add a generic watchdog hook to `WorkerRunner`**

Keep the runner model-neutral. Add optional collaborators equivalent to:

```python
watchdog_expired: Callable[[], bool] | None = None
watchdog_grace_seconds: float = 10.0
fatal_terminator: Callable[[int], NoReturn] = os._exit
```

While a processing task is active, check the watchdog before sending each heartbeat and at a bounded poll interval no larger than `min(heartbeat_wait, 1.0 second)`.

On expiry:

1. mark the active `LeaseGuard` lost;
2. stop heartbeat renewal immediately;
3. wait at most `watchdog_grace_seconds` for the processing future to unwind;
4. if still running, invoke `fatal_terminator(70)`;
5. never call `/fail` after local authority is invalidated.

- [ ] **Step 6: Write watchdog tests without killing pytest**

Inject a fake terminator that records the exit code and raises a test-only sentinel. Use a processor blocked on a `threading.Event`. Assert no heartbeat or `/fail` occurs after expiry, the guard is lost, grace is bounded, and the terminator receives code 70.

- [ ] **Step 7: Make health-v2 truthful without changing its schema**

Change `get_worker_health` to require/read readiness or add a `runtime_ready: bool` argument. It may construct the existing v2 `ready` payload only when true; false raises/returns transport-unavailable behaviour used by the caller. Do not add `degraded`/`unavailable` values to the contract.

- [ ] **Step 8: Compose production worker in `main.py`**

`_run_worker()` should:

1. build `VisionExecutionLane`;
2. load verified release selection;
3. build/start `RuntimeSupervisor`;
4. build `ProductionVisionProcessor` using `supervisor.runtime` and `supervisor.report_processing_failure`;
5. build `WorkerRunner` with the dedicated lane rather than generic `asyncio.to_thread`;
6. loop: if `READY`, `await runner.run_once()`; if `RECOVERING`, `await supervisor.recover_if_required()`; if `UNAVAILABLE`, remain alive and sleep/poll local readiness without calling `lease()`;
7. close supervisor/lane/client in reverse order on shutdown.

Do not use `WorkerRunner.run_forever()` for production readiness gating unless it is refactored to accept a generic readiness callback with the same behaviour.

- [ ] **Step 9: Run worker/supervisor regression tests**

```powershell
cd src/vision
python -m pytest tests/test_runtime_supervisor.py tests/test_runtime_watchdog.py tests/test_worker_runner.py tests/test_lease_ownership_matrix.py -q
```

- [ ] **Step 10: Commit**

```powershell
git add mavi_vision/runtime/supervisor.py mavi_vision/worker mavi_vision/pipeline/production_processor.py tests
git commit -m "feat: supervise qualified vision runtime"
```

---

### Task 12: Build Reproducible Offline Runtime Bundles and Strengthen Supply-Chain Verification

**Files:**
- Create: `tools/vision/build_offline_bundle.py`
- Create: `src/vision/tests/test_offline_bundle_manifest.py`
- Modify: `tools/verify_repo.py`
- Reuse: `infrastructure/windows/`, `infrastructure/linux/`, `infrastructure/offline-bundle/`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class BundleArtifact:
    relative_path: str
    size_bytes: int
    sha256: str
    purpose: str
    package: str | None
    version: str | None
    platform_variant: str
```

`build_offline_bundle.py` consumes exactly one qualified platform/device lock and a model release directory; it emits a directory/ZIP plus `bundle-manifest.json`.

- [ ] **Step 1: Write manifest determinism tests**

Given the same input artifacts, sorted manifest entries and hashes must be identical. Reject duplicate destinations, absolute paths, missing files, wrong hash, and files not declared by the selected runtime/model release.

- [ ] **Step 2: Implement bundle assembly**

Bundle includes:

```text
wheels/
model/checkpoint
model/resolved-config
models/manifest
models/qualification
pipeline/profile
runtime/runtime.json
runtime/<selected-platform>.lock
bundle-manifest.json
```

Do not include Git metadata, caches, source CCTV, or development-only unverified artifacts in a production bundle.

- [ ] **Step 3: Generate an offline install command file**

Emit a platform-appropriate command using local wheels only and hash checking, equivalent to:

```text
python -m pip install --no-index --require-hashes --find-links wheels -r runtime/<selected-platform>.lock
```

No target-machine compilation or network resolution is allowed.

- [ ] **Step 4: Extend repository verification to reject download mechanisms**

Scan production manifest/profile/runtime metadata and packaging scripts for model URLs, `git+https`, model-zoo aliases, or unqualified online installation paths. Development documentation may mention Internet setup, but release runtime metadata must not require it.

- [ ] **Step 5: Run tests**

```powershell
cd src/vision
python -m pytest tests/test_offline_bundle_manifest.py -q
cd ../..
python tools/verify_repo.py
```

- [ ] **Step 6: Commit**

```powershell
git add tools/vision/build_offline_bundle.py tools/verify_repo.py src/vision/tests/test_offline_bundle_manifest.py infrastructure
git commit -m "build: add offline vision runtime bundle"
```

---

### Task 13: Add Hosted Windows + Linux Vision Adapter CI and Move Core CI to the Qualified Python Minor

**Files:**
- Modify: `.github/workflows/quality-gate.yml`
- Create: `.github/workflows/vision-adapter-gate.yml`

**Interfaces:**
- Core quality gate remains the full repository gate.
- Adapter gate runs lightweight ML-adapter/tracking/platform tests on `ubuntu-latest` and `windows-latest` without model weights/GPU.

- [ ] **Step 1: Update core quality gate Python version**

Replace hard-coded `3.13` with the exact qualified minor from Task 1 (`3.12` or `3.11`). Do not make it a floating newest-Python value.

- [ ] **Step 2: Create the cross-platform adapter matrix**

Use:

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest]
runs-on: ${{ matrix.os }}
```

Install the base package, dev dependencies, and only the qualified tracking adapter dependencies needed by Gate B. Do not install/download RTMDet weights.

- [ ] **Step 3: Run the exact Gate-B test set**

The workflow command must include:

```text
test_model_manifest.py
test_pipeline_profile.py
test_qualification_record.py
test_runtime_artifact_hashing.py
test_rtmdet_mapping.py
test_rtmdet_geometry.py
test_rtmdet_colour_space.py
test_bytetrack_adapter.py
test_runtime_execution_lane.py
test_runtime_supervisor.py
test_runtime_watchdog.py
test_runtime_provenance.py
test_production_processor.py
```

On Windows additionally run `test_artifact_store_windows.py`; on both platforms run the generic artifact-store and lease-ownership tests.

- [ ] **Step 4: Ensure workflow does not depend on unavailable model artifacts**

All real-model tests remain out of hosted Gate B. If an import path accidentally forces PyTorch/MMDetection during core/adaptor unit collection, fix the lazy import boundary rather than adding model weights to CI.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/quality-gate.yml .github/workflows/vision-adapter-gate.yml
git commit -m "ci: add cross-platform vision adapter gate"
```

---

### Task 14: Execute Real-Model, Offline, CCTV, Recovery, and Performance Qualification and Finalize `verified`

**Files:**
- Create: `tools/vision/qualify_phase1.py`
- Finalize: `models/qualifications/rtmdet-m-coco-phase1-v1.json`
- Finalize: `models/manifests/rtmdet-m-coco-phase1-v1.json`
- Finalize if thresholds changed during qualification: `src/vision/config/pipelines/phase1-detection-tracking-v1.json`
- Regenerate hashes in: `src/vision/runtime/mmdetection-phase1-v1/runtime.json`

**Interfaces:**
- `qualify_phase1.py` consumes a model root, runtime profile, pipeline profile, external corpus manifest, output directory, and device.
- It outputs machine-readable metrics/evidence; it does not copy corpus media into Git.

- [ ] **Step 1: Implement qualification runner with explicit evidence IDs**

For each external corpus item, input metadata contains only an anonymous case ID, local path, SHA-256, annotation path if present, and scenario tags. Output records case ID/hash, runtime/model/profile hashes, platform/device identity, and metrics. Do not write raw frames into the qualification JSON.

- [ ] **Step 2: Implement detector/tracker metrics collection**

Record Person and Vehicle precision, recall, AP50, false positives/evaluated frame; tracking IDF1, HOTA, ID switches, fragmentation; and post-map duplicate Vehicle detection/track counts. Evaluation tooling may be qualification-only and must not become a production worker dependency.

- [ ] **Step 3: Run real functional qualification on four target variants**

Required evidence:

```text
windows-x86_64-cpu      passed
windows-x86_64-cuda     passed
linux-x86_64-cpu        passed
linux-x86_64-cuda       passed
```

Each run must prove explicit local resolved config/checkpoint loading, exact ordered vocabulary equality, RGB/BGR contract, detector→ByteTrack→Task-9 artifact path, and secure staging.

- [ ] **Step 4: Run at least one network-disconnected installation and inference per OS**

Install from the Task-12 bundle with network unavailable. Run one real RTMDet-M + ByteTrack video through the worker processing path. Record bundle manifest hash and pass/fail in qualification evidence.

- [ ] **Step 5: Run Linux/NVIDIA production qualification**

Execute representative CCTV corpus, sustained/long video, memory/VRAM observation, controlled OOM recovery, controlled poisoned-context path where safely injectable, and watchdog fatal-restart fixture. Record decoded/inference/end-to-end FPS, processing/source-duration ratio, p50/p95 inference latency, peak VRAM, host RAM, startup/warm-up time, artifact volume, and long-run memory behaviour.

- [ ] **Step 6: Freeze the first qualified profile thresholds**

Use the measured corpus to select the conservative detector floor and ByteTrack parameters. Write them to `phase1-detection-tracking-v1.json`. Do not tune to improve only the final test set after seeing final acceptance results; preserve the tuning/baseline split in the qualification record.

If duplicate Vehicle tracks caused by source-class collapse are materially problematic, **stop and create a new explicitly versioned profile design for post-map suppression**. Do not silently add a second NMS rule to v1.

- [ ] **Step 7: Finalize qualification-backed verification**

Write final hashes and all mandatory gates to `models/qualifications/rtmdet-m-coco-phase1-v1.json`; then change the manifest to `verificationStatus="verified"` with the exact `qualificationId`.

Run:

```powershell
python tools/verify_repo.py
```

Expected: PASS only when manifest, profile, runtime locks, and qualification evidence all match.

- [ ] **Step 8: Commit qualification metadata only**

```powershell
git add models/manifests models/qualifications src/vision/config/pipelines src/vision/runtime/mmdetection-phase1-v1 tools/vision/qualify_phase1.py
git commit -m "test: qualify phase1 RTMDet ByteTrack runtime"
```

Never add the external CCTV corpus or model checkpoint to Git.

---

### Task 15: Full End-to-End Regression, Exact-Head CI, and Review Closure

**Files:**
- No new production files expected.
- Modify only files required by failures proven during this verification task; every fix receives its own regression test and commit.

**Interfaces:**
- Definition of Done is the Revision-2 spec Section 28 plus all global constraints in this plan.

- [ ] **Step 1: Run the complete Python test suite on Linux**

```bash
cd src/vision
python -m pytest -q
```

Expected: zero failures/skips other than tests explicitly platform/hardware-gated by design.

- [ ] **Step 2: Run the complete Python test suite on Windows**

```powershell
cd src/vision
python -m pytest -q
```

Expected: Windows staging tests execute rather than skip; POSIX-only attack tests may skip for explicit platform reasons.

- [ ] **Step 3: Run repository verification**

```powershell
python tools/verify_repo.py
```

Expected: PASS, including release metadata/qualification consistency and no tracked model/media/secret files.

- [ ] **Step 4: Run the full .NET repository build/tests**

```powershell
dotnet build MAVI.sln --configuration Release
dotnet test MAVI.sln --configuration Release --no-build
```

Expected: zero failures.

- [ ] **Step 5: Run frontend tests/typecheck/build**

```powershell
cd src/web/mavi-web
npm ci
npm test
npm run typecheck
npm run build
```

Expected: zero failures.

- [ ] **Step 6: Re-run critical Task-9 lease/artifact regression tests explicitly**

```powershell
cd src/vision
python -m pytest \
  tests/test_lease_guard.py \
  tests/test_lease_ownership_matrix.py \
  tests/test_process_video.py \
  tests/test_source_integrity.py \
  tests/test_artifact_store.py \
  tests/test_artifact_publisher.py \
  -q
```

Expected: zero failures; no Task-10 change may weaken stale-worker protections.

- [ ] **Step 7: Verify no Task-11 authority leaked into Python**

Search production Python for PostgreSQL clients/direct SQL and any `/complete` result-submission implementation. Expected: none. The existing Task-11 boundary remains intact.

- [ ] **Step 8: Push the exact implementation head and wait for hosted gates**

Required GitHub checks on the exact head:

```text
MAVI Quality Gate               success
Vision Adapter Gate / ubuntu    success
Vision Adapter Gate / windows   success
```

Do not merge based on an earlier commit's green status.

- [ ] **Step 9: Request code review against the full Task-10 diff**

Review specifically for:

- MMDetection/Supervision/Trackers type leakage;
- hidden network/download paths;
- lease-loss precedence;
- unsafe Windows path/reparse handling;
- cross-attempt tracker/storage state leakage;
- incorrect RGB/BGR conversion;
- use of native tracker IDs as MAVI IDs;
- unverified manifest/profile/runtime drift;
- generic thread-pool use for production model processing;
- unsafe in-process cancellation of hung native work;
- accidental Task-11 persistence scope.

- [ ] **Step 10: Final Definition-of-Done audit**

Check every item in `docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md` Section 28 against fresh test/qualification/CI evidence. If any item cannot be evidenced, Task 10 remains open.

- [ ] **Step 11: Commit any review-only documentation/evidence corrections and re-run exact-head gates**

Only after the final head is green and review threads are resolved is the branch ready for the normal finishing/merge workflow.

---

## Dependency and Task Ordering

```text
Task 1  Runtime matrix qualification -----------------------------┐
Task 2  Cross-platform secure staging ----------------------------┤
                                                                  v
Task 3  Manifest/profile/qualification integrity
        |
        +--> Task 4 Runtime contracts/provenance/settings
                |
                +--> Task 5 Execution lane/activity
                |
                +--> Task 6 RTMDet normalization
                         |
                         +--> Task 7 Real MMDetection runtime
                         |
                         +--> Task 8 ByteTrack adapter
                                  |
                                  +--> Task 9 Attempt composition
                                           |
                                           +--> Task 10 Typed failure propagation
                                                    |
                                                    +--> Task 11 Supervisor/watchdog/main
                                                             |
                                                             +--> Task 12 Offline bundle
                                                             +--> Task 13 Hosted CI
                                                                      |
                                                                      +--> Task 14 Real qualification
                                                                               |
                                                                               +--> Task 15 Closure
```

Task 1 and Task 2 are deliberate feasibility gates. Do not bury failure of either gate under downstream implementation work.

## Self-Review / Spec Coverage Matrix

| Revision-2 spec area | Implemented by |
| --- | --- |
| Model-neutral runtime boundary | Tasks 4, 6, 7 |
| Long-lived detector / attempt-scoped tracker | Tasks 8, 9 |
| Dedicated execution lane | Tasks 5, 11 |
| Secure Windows/POSIX staging | Task 2 |
| Manifest/profile/qualification separation | Task 3 |
| Resolved config + vocabulary integrity | Tasks 3, 7 |
| Evidence-backed `verified` | Tasks 3, 14 |
| RGB/BGR contract | Tasks 6, 7, 13, 14 |
| ByteTrack pixel/timestamp/ordinal/empty-frame semantics | Task 8 |
| No tentative backfill / matched-only evidence | Task 8 |
| Typed runtime failure propagation | Tasks 4, 9, 10 |
| Lease-loss precedence | Tasks 10, 11, 15 |
| OOM recovery / poisoned runtime | Task 11 |
| Hung native inference watchdog | Tasks 5, 11, 14 |
| Complete dependency-graph qualification | Task 1 |
| Offline hashed deployment | Task 12 |
| Windows + Linux hosted CI | Task 13 |
| CCTV quality/performance baseline | Task 14 |
| No generic second NMS/cap | Tasks 6, 14 |
| Full provenance | Tasks 4, 7, 14 |
| Health-v2 unchanged/truthful | Task 11 |
| Task-11 persistence excluded | Tasks 9, 15 |
| Exact-head regression/CI/review | Task 15 |

## Placeholder and Type-Consistency Review

- No production version number is guessed where the architecture requires experimental qualification; Task 1 is the explicit gate that generates those exact values, and later tasks consume `runtime.json`.
- `DetectorRuntime`, `RawDetection`, `ProcessingDependencyError`, `RuntimeDisposition`, `RuntimeProvenance`, `VisionExecutionLane`, `InferenceActivity`, `RTMDetDetector`, `ByteTrackTracker`, `ProductionVisionProcessor`, and `RuntimeSupervisor` are defined before later tasks consume them.
- Existing Task-9 public interfaces (`Detector.detect`, `Tracker.update`, `VideoProcessor.process`, `StagingArtifactStore`) remain stable except for the explicitly planned model-neutral typed-error pass-through and production execution dispatch.
- The plan contains no deferred `TODO`/`TBD` implementation steps; hardware-dependent evidence is an explicit acceptance gate rather than a hidden placeholder.
