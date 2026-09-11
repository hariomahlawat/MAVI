# Task 10 Qualified RTMDet + ByteTrack Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Task-9 fixture detector/tracker path with a qualified, fully offline RTMDet-M + ByteTrack Person/Vehicle runtime while preserving Task-9 lease authority, evidence integrity, artifact security, and deterministic processing semantics on Windows and Linux.

**Architecture:** Keep the existing `VideoProcessor`, `Detector`, and `Tracker` boundaries model-neutral. Add a process-scoped `MMDetectionRuntime`, a single-thread `VisionExecutionLane`, attempt-scoped RTMDet/ByteTrack/staging composition, evidence-backed model/runtime qualification, and security-equivalent POSIX/Windows staging backends. The asyncio worker thread retains lease/heartbeat authority; synchronous model work stays on the dedicated vision lane.

**Tech Stack:** Python 3.12 candidate with Python 3.11 fallback; PyTorch/torchvision; an MMDetection 3.3.x-compatible MMEngine/MMCV stack selected by qualification; RTMDet-M; `trackers.ByteTrackTracker`; Supervision/SciPy/NumPy/OpenCV as tracker dependencies; PyAV/FFmpeg; Pydantic 2; pytest; GitHub Actions; Win32/NT filesystem APIs for native Windows staging; SHA-256 release integrity.

**Spec:** `docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md`

## Global Constraints

- Production reference detector is RTMDet-M; do not silently substitute another detector size or backend.
- Qualify Python 3.12 first; use Python 3.11 only if the complete stable Windows/Linux runtime graph cannot qualify on 3.12.
- Use `trackers.ByteTrackTracker`; do not build Task 10 on deprecated `supervision.ByteTrack`.
- Process every decoded frame in the Task-10 correctness baseline; no adaptive skipping or sampling.
- MAVI `DecodedFrame.image` is contiguous `uint8` RGB; the MMDetection runtime owns the single explicit RGB-to-backend colour conversion.
- Person and Vehicle have independent ByteTrack states and both native trackers are updated on every decoded frame, including empty-class frames.
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
tools/vision/resolve_mmdet_config.py
tools/vision/probe_runtime.py
tools/vision/build_offline_bundle.py
tools/vision/qualify_phase1.py
```

The existing public import `mavi_vision.storage.artifact_store.StagingArtifactStore` remains stable so Task-9 pipeline/publisher callers do not need platform conditionals.

---

### Task 1: Qualify the Complete Python/OpenMMLab/Trackers Runtime Matrix

**Purpose:** Resolve the intentionally unknown dependency values before production code begins. Exact versions are outputs of qualification, not guesses embedded in application code.

**Files:**
- Create: `tools/vision/resolve_mmdet_config.py`
- Create: `tools/vision/probe_runtime.py`
- Create: `src/vision/runtime/mmdetection-phase1-v1/runtime.json`
- Create after successful qualification: `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cpu.lock`
- Create after successful qualification: `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cuda.lock`
- Create after successful qualification: `src/vision/runtime/mmdetection-phase1-v1/linux-x86_64-cpu.lock`
- Create after successful qualification: `src/vision/runtime/mmdetection-phase1-v1/linux-x86_64-cuda.lock`
- Modify only after a matrix is proven: `src/vision/pyproject.toml`

**Interfaces:**
- Produces: `runtime.json` containing `runtimeProfileId`, selected Python minor, exact semantic package versions/build identities, platform/device qualification states, and hashes of the four lock files.
- Produces: `resolve_mmdet_config.py --input <source-config> --output <resolved-config>` that loads the source config through MMEngine, fully resolves inherited `_base_` content, emits one local deployment config, and rejects unresolved URL/environment-driven analytical dependencies.
- Produces: `probe_runtime.py --config <local-resolved-config> --checkpoint <local-checkpoint> --checkpoint-sha256 <reviewed-full-digest> --device cpu|cuda` returning exit code 0 only after real RTMDet-M inference completes.
- Later tasks consume exact values from `runtime.json`; they must not duplicate dependency constants.

- [ ] **Step 1: Implement and test resolved-config generation in a candidate environment**

`resolve_mmdet_config.py` must load the selected official/local RTMDet-M source config with `mmengine.Config.fromfile()`, materialize the merged configuration, write a standalone local config using MMEngine's supported dump/export path, reload that emitted config, and assert its effective configuration is equivalent to the merged source config for model/test-pipeline/class-relevant fields.

Run:

```powershell
python tools/vision/resolve_mmdet_config.py --input <source-rtmdet-m-config> --output <qualification-root>/rtmdet_m_resolved.py
```

Acceptance: the emitted deployment file contains no unresolved `_base_` reference or HTTP(S) URL and reloads successfully without access to the original config tree.

- [ ] **Step 2: Write the runtime probe with explicit version/build capture**

Create `tools/vision/probe_runtime.py` with a JSON output object containing at least:

```python
{
    "python": platform.python_version(),
    "platform": platform.platform(),
    "torch": torch.__version__,
    "torchvision": torchvision.__version__,
    "torchCuda": torch.version.cuda,
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

After version capture, load only the explicit local resolved config/checkpoint, run one RTMDet-M inference over an in-memory channel-distinct RGB test image converted according to the backend contract, validate that prediction boxes/scores/labels are accessible, and print the JSON record. The CLI must reject URL/model-alias inputs.

- [ ] **Step 3: Prove the probe fails closed when a local checkpoint is absent**

Run with a nonexistent checkpoint while outbound network is disabled or blocked for the process:

```powershell
python tools/vision/probe_runtime.py --config <qualification-root>/rtmdet_m_resolved.py --checkpoint <qualification-root>/missing.pth --checkpoint-sha256 <reviewed-full-digest> --device cpu
```

Expected: non-zero exit before inference, with no download-created file or cache entry.

- [ ] **Step 4: Qualify Python 3.12 on Linux CPU first**

Create a clean Python 3.12 environment, install one internally consistent stable graph satisfying MMDetection 3.3.x's MMEngine/MMCV constraints plus the selected Trackers stack, install MAVI, then run:

```bash
python tools/vision/probe_runtime.py \
  --config /qualification/rtmdet_m_resolved.py \
  --checkpoint /qualification/rtmdet_m.pth \
  --checkpoint-sha256 <reviewed-full-digest> \
  --device cpu > linux-cpu-probe.json
```

Acceptance: real inference exits 0 and the record contains the entire graph. If dependency resolution or real inference fails, preserve the failure log and repeat Tasks 1.4–1.6 with Python 3.11 rather than forcing incompatible dependencies.

- [ ] **Step 5: Repeat the identical semantic graph on Windows CPU**

```powershell
python tools/vision/probe_runtime.py `
  --config C:\qualification\rtmdet_m_resolved.py `
  --checkpoint C:\qualification\rtmdet_m.pth `
  --checkpoint-sha256 <reviewed-full-digest> `
  --device cpu > windows-cpu-probe.json
```

Acceptance: semantic package versions match the Linux candidate where platform support permits; wheel/build hashes may differ.

- [ ] **Step 6: Qualify the same candidate on Linux NVIDIA and Windows NVIDIA**

Run the probe with `--device cuda` on both target platforms. Record GPU name, driver/runtime details, `torch.version.cuda`, and exact PyTorch/MMCV build identities.

If no complete Python 3.12 graph passes all four environments, repeat the full four-gate matrix with Python 3.11. If neither minor passes, **stop Task 10 and reopen ADR-005**; do not continue with resolver overrides or unqualified source builds.

- [ ] **Step 7: Freeze platform/device wheel graphs with hashes**

For each successful environment:

1. capture exact installed versions;
2. download/build the exact platform wheels into a controlled wheelhouse during qualification;
3. compute SHA-256 for each wheel;
4. generate a lock whose requirement lines use exact versions and `--hash=sha256:<digest>` values accepted by `pip --require-hashes`;
5. prove that a fresh environment installs from that wheelhouse using `--no-index --require-hashes`.

Do not treat `pip freeze` alone as a release lock because it does not establish wheel integrity.

- [ ] **Step 8: Write `runtime.json` and update the package Python requirement**

Example shape:

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

Use the actually qualified Python minor. If 3.12 qualified, set:

```toml
requires-python = ">=3.12,<3.13"
```

If 3.11 qualified, set `>=3.11,<3.12` instead. Heavy ML packages remain outside base dependencies until Task 7.

- [ ] **Step 9: Commit the qualification baseline**

```powershell
git add tools/vision/resolve_mmdet_config.py tools/vision/probe_runtime.py src/vision/runtime/mmdetection-phase1-v1 src/vision/pyproject.toml
git commit -m "build: qualify phase1 vision runtime matrix"
```

**Reviewer gate:** Reject if any platform/device result is inferred rather than executed, the resolved config still depends on its source tree, real RTMDet-M inference was skipped, or dependency conflicts were bypassed with `--no-deps`.

---

### Task 1A — Checkpoint-loading compatibility and dual-platform CPU smoke gate

**Status (verified 2026-09-11): COMPLETE for the bounded Task 1A gate.** This establishes the checkpoint-loading correction and dual-platform hosted CPU smoke evidence only. It does **not** claim complete Task-10 qualification; Tasks 1 and 2–15 retain their own acceptance gates.

#### Final correction

Task 9 commit `f151a70ac2f1d702e25bb504ddb9c4ce144d46d8` remains the accepted integration baseline. The Task-10 target branch was `f544282b0973f702c26ae8f264529bf3143d2e2f` when this bounded remediation started. PR #15 was verified at head `9027fc056a8a3a340fdcf4e9db472ec4cc2d3b74`.

The PyTorch 2.6 restricted-loading failure was caused by an exact serialized-global identity mismatch across NumPy generations. The official RTMDet-M checkpoint uses historical `numpy.core.multiarray` identities, while the hosted NumPy 2.x fixture serializes the same reviewed callables under `numpy._core.multiarray`. The final lexical `torch.serialization.safe_globals(...)` scope therefore contains a finite nine-entry reviewed set: `mmengine.logging.history_buffer.HistoryBuffer`; `_reconstruct` under both legacy and NumPy-2 names; `numpy.ndarray`; `numpy.dtype`; the concrete Float64 and Int64 dtype classes; and `scalar` under both legacy and NumPy-2 names. The scope is temporary and restores the prior safe-global state after success or failure.

The security boundary remains unchanged: no `weights_only=False`, environment bypass, process-global monkey patch, permanent allowlist, automatic unsafe-global discovery, checkpoint conversion, model/backend substitution, or job-controlled model/config input was introduced. The official OpenMMLab checkpoint remains pinned to SHA-256 `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b`.

#### Hosted verification evidence

GitHub Actions **Task 10 Runtime Qualification #13**, run `34610780805`, completed successfully on PR head `9027fc056a8a3a340fdcf4e9db472ec4cc2d3b74`. The default PR checkout tested synthetic merge commit `76853ba4ae31896111c864c4322a346839b31fe3`; the probe separately recorded `pullRequestHeadSha=9027fc056a8a3a340fdcf4e9db472ec4cc2d3b74` on both platforms.

| Gate | Result | Evidence |
| --- | --- | --- |
| MAVI core quality gate | PASS | `MAVI Quality Gate #156`, run `34610780738` |
| Linux hosted CPU | PASS | job `103300442180`; Python 3.12.14; PyTorch 2.6.0+cpu; MMCV 2.1.0; MMEngine 0.10.7; MMDetection 3.3.0; NumPy 2.5.3 |
| Windows hosted CPU | PASS | job `103300442432`; Python 3.12.10; PyTorch 2.6.0+cpu; MMCV 2.1.0; MMEngine 0.10.7; MMDetection 3.3.0; NumPy 2.5.3 |
| Real restricted-load regression | PASS on both | approved NumPy metadata loads only inside the reviewed lexical scope; an unapproved type remains rejected; safe-global state is restored |
| Official checkpoint preflight | PASS on both | missing checkpoint fails before heavyweight loading; expected SHA-256 is required and verified before deserialization |
| Real RTMDet-M inference | PASS on both | probe returned `status="passed"`, `predictionType="DetDataSample"`, `predictionCount=300` |
| Linux evidence artifact | PASS | artifact `10268436863`, archive digest `sha256:d8ae5e6d56f5acd957032549c9298bc32a44b5c620ee0a574c17aeb36822fd7c` |
| Windows evidence artifact | PASS | artifact `10268617493`, archive digest `sha256:15747601db9ec5317494cd0485f9c3ca7540dc23ae76c87f814ed8bc36893fd7` |

The Linux probe recorded the top-level source-config byte hash `c04a67ac0fbb48df14ada534f16186e1e4eb6cd5bb5ad0c32b1c64835f4e39e4`; Windows recorded `63e0ea14d2c0ce5966d8d68e05957c872e17c8296ba9d95e7ebe3bb6c625004f`. These hashes identify the checked-out top-level config bytes only and are **not** treated as an effective configuration identity. The platform difference reinforces the already-planned Task-1 requirement to generate and qualify a self-contained resolved deployment config with deterministic release-byte rules.

#### Acceptance checklist

- [x] Relevant tests demonstrate the correction and validation regressions; hosted unit-test steps and the exact runtime qualification commands passed.
- [x] Real-PyTorch tests establish approved/rejected loading behaviour and restoration of the safe-global state after success and failure.
- [x] Missing, malformed and mismatched checkpoint inputs fail before heavyweight model loading; URL rejection and intended relative/Windows filesystem paths remain covered.
- [x] Invalid prediction labels, malformed shapes, non-finite boxes/scores and mismatched lengths are rejected; valid empty predictions pass.
- [x] Both hosted CPU jobs pass on the same PR head and record the synthetic checkout commit separately from the PR-head identity.
- [x] Evidence artifacts are parseable and identify checkpoint/config identity, exact runtime versions, platform/device, workflow run and PR head.
- [x] Relevant repository/core checks pass on the proposed revision via MAVI Quality Gate #156.
- [x] Documentation records the final Task-1A evidence and limitations without claiming full Task-10 qualification.

#### Remaining boundary

Task 1A is closed. Full runtime qualification is **not** closed. Task 1 must still produce the resolved effective config, qualify/freeze the complete runtime graph and platform/device locks, and perform the remaining required platform/device gates. GPU qualification, offline installation, native Windows end-to-end staging security, model/profile/qualification metadata, production RTMDet/ByteTrack adapters, recovery/watchdog behaviour, detection/tracking quality, performance, and production `verified` status remain governed by Tasks 1 and 2–15.

---

### Task 1B — Self-contained resolved config and hosted CPU runtime freeze

**Status (verified 2026-09-11): COMPLETE for the bounded Task 1B software gate.** Task 1B closes the unresolved-config and hosted-CPU semantic-runtime portions of Task 1. It does **not** close Task 1 as a whole: NVIDIA qualification and reproducible hashed offline wheelhouse locks remain mandatory before the package Python requirement or production runtime status may be finalized.

#### Implementation

`tools/vision/resolve_mmdet_config.py` now loads the official RTMDet-M source config through MMEngine, materializes inherited configuration through the supported `Config.dump()` path, normalizes the emitted artifact to deterministic UTF-8/LF bytes, rejects residual `_base_`, HTTP(S), template and environment-resolution syntax, reloads the emitted file, and compares deployment-relevant model/test configuration semantics with the merged source.

Qualification CI then deletes the cloned MMDetection source-config tree before the missing-checkpoint proof and real inference probe. A passing probe therefore establishes that the deployment config is independently loadable and does not succeed by falling back to the original inherited config files.

The selected hosted CPU semantic graph is recorded once in `src/vision/runtime/mmdetection-phase1-v1/runtime.json`: Python 3.12; PyTorch 2.6.0; torchvision 0.21.0; MMCV 2.1.0; MMEngine 0.10.7; MMDetection 3.3.0; Trackers 2.6.0; Supervision 0.30.2; SciPy 1.18.1; NumPy 2.5.3; OpenCV module 5.0.0 / `opencv-python` 5.0.0.93; Pillow 11.3.0; PyAV 16.1.0. The workflow verifies the installed graph against this metadata before artifact resolution/inference.

Adding the non-package `src/vision/runtime` directory initially exposed setuptools automatic flat-layout discovery in Quality Gate #159. Package discovery is now explicitly restricted to `mavi_vision*`, preserving runtime release metadata outside the Python package. A later exact-head Windows run also exposed an over-strict regression assertion that compared PyTorch safe-global list ordering. PyTorch restored the same members in a different order; the regression now compares `frozenset` membership, which tests the actual no-permission-leak invariant without depending on incidental ordering.

#### Executed qualification evidence

Task 10 Runtime Qualification #17, run `34614293246`, executed the resolver and real RTMDet-M inference on both hosted operating systems. Linux job `103312235001` and Windows job `103312234588` both emitted the **same resolved-config SHA-256**:

`377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3`

Both jobs matched the recorded semantic graph, removed the original MMDetection config tree, proved a missing checkpoint fails before model loading, and completed real RTMDet-M CPU inference with `status="passed"` and `predictionType="DetDataSample"`. The checkpoint remained the reviewed OpenMMLab artifact with SHA-256 `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b`.

The final PR #16 head `de14dcbe37f2af4fa73d481fe701332d04abe4f8` passed MAVI Quality Gate #164 (run `34615702314`) and Task 10 Runtime Qualification #22 (run `34615702414`). Linux job `103316964114` and Windows job `103316964302` both matched the frozen semantic graph, emitted the identical resolved-config SHA-256 `377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3`, removed the source MMDetection config tree, and completed real RTMDet-M CPU inference. Evidence artifacts were uploaded as `10271175803` (Linux, archive digest `sha256:45a72a0212a066c3090f5aaf97f13bf9b41d73581d6be0ed77cff18215f6af4d`) and `10271226473` (Windows, archive digest `sha256:91031acc16763324f151eeb0469d10ef878a1d2c38801d130e391e090d08b51b`). PR #16 was then squash-merged into `feature/task-10-rtmdet-bytetrack` as `4f8762abe84fcaece02f7d837f64d575a51c0296`. Post-merge Task 10 Runtime Qualification #23 (run `34617410443`) also passed on the squash-merge commit itself: Windows job `103322668058` and Linux job `103322668293` again matched the frozen semantic graph, emitted resolved-config SHA-256 `377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3`, and completed real RTMDet-M CPU inference. Post-merge evidence artifacts are `10270904062` (Windows, archive digest `sha256:41b7bd3785ff9b6b80d83aed757f2d4b959b31b5dc322904aad349df4a727c76`) and `10270364571` (Linux, archive digest `sha256:fb52db4d77dff8f879f66b239bbd786ca07528343aaef3fe9ec5e12b4cf784bf`).

#### Task 1B acceptance

- [x] The resolver uses MMEngine's supported load/dump/reload path and validates deployment-relevant effective semantics.
- [x] The resolved artifact rejects residual base, remote URL, template and environment-resolution syntax.
- [x] UTF-8/LF normalization produces one stable resolved-config SHA-256 across hosted Linux and Windows.
- [x] The original MMDetection config tree is removed before real model loading/inference.
- [x] The installed CPU semantic graph is checked against machine-readable runtime metadata.
- [x] Real RTMDet-M CPU inference passes on Linux and Windows from the self-contained resolved config.
- [x] Runtime metadata records CPU evidence and leaves both CUDA variants explicitly `pending-hardware-qualification`.
- [x] Hashed offline wheelhouse locks remain explicitly `pending-wheelhouse-freeze`; they are not inferred from `pip freeze`.
- [x] `requires-python` remains unchanged until the complete four-variant Task-1 matrix is actually proven.

#### Remaining Task-1 boundary

Task 1 remains **OPEN** for two evidence classes that cannot be honestly inferred from hosted CPU runs: Linux NVIDIA + Windows NVIDIA real-model qualification, and platform/device-specific offline wheelhouse locks proven installable with `--no-index --require-hashes`. Until those gates execute, `runtime.json` remains partially qualified, `pyproject.toml` retains its existing Python declaration, and no production `verified` status is permitted.

---

### Task 2: Make Attempt Staging Secure on Both POSIX and Native Windows

**Files:**
- Modify: `src/vision/mavi_vision/storage/artifact_store.py`
- Create: `src/vision/mavi_vision/storage/artifact_store_posix.py`
- Create: `src/vision/mavi_vision/storage/artifact_store_windows.py`
- Modify: `src/vision/tests/test_artifact_store.py`
- Create: `src/vision/tests/test_artifact_store_windows.py`
- Modify only if type imports require it: `src/vision/mavi_vision/storage/artifact_publisher.py`

**Interfaces:**
- Preserve public constructor: `StagingArtifactStore(media_root: Path, job_id: UUID, attempt_count: int)`.
- Preserve `job_id`, `attempt_count`, `thumbnail_key()`, `trajectory_key()`, `write_bytes()`, and `cleanup()`.
- `artifact_store.py` becomes the platform facade and owns shared logical validation/error codes; POSIX and Windows backends implement the same internal protocol.

- [ ] **Step 1: Lock existing POSIX behaviour before moving code**

Add any missing assertions needed to preserve exact existing key/error semantics, then run:

```powershell
cd src/vision
python -m pytest tests/test_artifact_store.py tests/test_artifact_publisher.py -q
```

Expected: PASS against the pre-refactor implementation.

Move the current hardened `dir_fd`/`O_NOFOLLOW` implementation to `artifact_store_posix.py`; keep shared logical validation and `StagingArtifactError` in `artifact_store.py`; delegate by `os.name`. Re-run the same suite and require identical results.

- [ ] **Step 2: Write Windows path/reparse tests before implementing the backend**

Create Windows-only tests guarded by `os.name == "nt"`:

```python
def test_windows_rejects_junction_in_attempt_ancestry(...): ...
def test_windows_parent_swap_cannot_redirect_publish(...): ...
def test_windows_cleanup_does_not_follow_reparse_point(...): ...
def test_windows_sibling_attempt_is_preserved(...): ...
def test_windows_publish_rechecks_authority_immediately_before_replace(...): ...
```

Use a real NTFS junction via `cmd /c mklink /J <link> <target>` for the mandatory reparse case so Developer Mode symlink privileges are not required.

Run on native Windows; expected result before implementation is failure because secure Windows publication is unavailable.

- [ ] **Step 3: Implement a small isolated handle-relative Windows helper layer**

Expose internal helpers:

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

Use platform handle APIs with reparse-point rejection, directory-handle identity checks, and handle-relative child operations. Path-string normalization alone is not accepted as the security boundary.

- [ ] **Step 4: Implement Windows `write_bytes()` and `cleanup()` with the same authority boundary as POSIX**

`write_bytes()` must validate the logical name, traverse/create only the attempt ancestry without following reparse points, create an exclusive temp sibling, write+flush, revalidate parent identity, call `authorize_publish()` immediately before replacement, replace inside that same validated directory, revalidate identity again, and roll back a publication known to have raced.

`cleanup()` removes only the current attempt subtree and never traverses a reparse point.

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

Expected: all applicable tests pass; normal Windows staging no longer raises `secure_staging_unavailable`.

- [ ] **Step 6: Commit**

```powershell
git add src/vision/mavi_vision/storage src/vision/tests/test_artifact_store.py src/vision/tests/test_artifact_store_windows.py
git commit -m "feat: add secure windows attempt staging"
```

**Reviewer gate:** If link/reparse and directory-substitution safety cannot be demonstrated on native Windows, stop and revisit the formal Windows-support decision; do not weaken the POSIX backend.

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
- Create initially with pending/non-production gates, then finalize in Task 14: `models/qualifications/rtmdet-m-coco-phase1-v1.json`
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

- [ ] **Step 1: Lock exact-byte repository rules**

Create:

```gitattributes
*.json text eol=lf
*.lock text eol=lf
*.py text eol=lf
```

Write tests rejecting BOM-bearing qualified JSON and CRLF in release JSON/lock files. `sha256_release_file()` hashes exact on-disk UTF-8 bytes; it does not parse/re-serialize JSON first.

- [ ] **Step 2: Write failing manifest validation tests**

Cover absolute/URL/backslash/`..` artifact paths, malformed SHA-256, empty/duplicate vocabulary, verified-without-qualification ID, and model-root escape via filesystem link/reparse component.

- [ ] **Step 3: Implement strict manifest loading and trusted-root containment**

Use `extra="forbid"` semantics. Artifact paths are logical forward-slash relative paths only. Release-path verification walks from the configured model root and rejects link/reparse redirection; do not rely solely on string prefix comparison after `resolve()`.

- [ ] **Step 4: Write and implement pipeline-profile validation**

The profile includes detector floor, the five allowed source classes, exact class mapping, explicit ByteTrack parameters, and `framePolicy="every-frame"`. Do **not** add a generic `maxDetections` field in Task 10. Numeric thresholds must have explicit validated ranges; mapping keys must exist in the selected manifest vocabulary.

- [ ] **Step 5: Implement immutable exact-byte profile identity**

The provenance hash is `sha256_release_file(profile_path)` rather than JSON canonical reserialization.

- [ ] **Step 6: Write and implement qualification-evidence verification**

A manifest marked `verified` is accepted only when the referenced qualification file exists and model/checkpoint/config/profile/runtime hashes all match, runtime IDs match, and every mandatory gate is `passed`. Development `unverified` requires explicit `allow_unverified=True`; checkpoint/config integrity still applies.

- [ ] **Step 7: Implement `verify_release_selection()`**

Return one frozen `VerifiedReleaseSelection` carrying the loaded manifest/profile/qualification/runtime identities, exact hashes, and resolved local artifact paths. Production runtime construction consumes this object and does not re-resolve configuration ad hoc.

- [ ] **Step 8: Extend repository verification**

`tools/verify_repo.py` validates manifest/profile/qualification JSON, lowercase SHA-256 format, path/URL rules, LF/no-BOM, identity consistency, and the existing no-weight/media/secret rule. Before Task 14, the committed manifest remains explicitly `unverified`; repository verification must not report it as production-qualified.

- [ ] **Step 9: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_model_manifest.py tests/test_pipeline_profile.py tests/test_qualification_record.py tests/test_runtime_artifact_hashing.py -q
cd ../..
python tools/verify_repo.py
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
- Create or modify: `src/vision/tests/test_worker_settings.py`

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

- [ ] **Step 1: Write validation tests for raw runtime values**

Require finite XYXY/confidence, confidence `[0,1]`, and non-empty source class. Raw boxes may be outside the frame; clipping belongs to the RTMDet adapter.

- [ ] **Step 2: Implement framework-neutral types with no heavy ML imports**

`interfaces.py`, `errors.py`, and `provenance.py` must not import `torch`, `mmdet`, `mmcv`, `supervision`, or `trackers`.

- [ ] **Step 3: Write and implement typed failure codes**

Define:

```python
GpuOutOfMemoryError("vision_gpu_out_of_memory", RuntimeDisposition.RECOVER)
GpuRuntimeError("vision_gpu_runtime_failed", RuntimeDisposition.UNAVAILABLE)
InferenceContractError("vision_inference_contract_failed", RuntimeDisposition.RECOVER)
TrackerError("vision_tracker_failed", RuntimeDisposition.CONTINUE)
```

Enforce the existing worker failure-code grammar and maximum length.

- [ ] **Step 4: Extend `WorkerSettings` with operational selection only**

Add model root/manifest/profile/runtime paths, `device_policy`, `device_index`, `production_mode`, `inference_watchdog_seconds`, and `watchdog_grace_seconds`. Production mode rejects `auto`. Do not expose detector/tracker thresholds as environment settings.

- [ ] **Step 5: Implement immutable provenance**

Capture model/config/profile/qualification/runtime hashes; Python/PyTorch/torchvision/MMDetection/MMCV/MMEngine/Trackers/Supervision/SciPy/NumPy/OpenCV/PyAV and FFmpeg identity where available; OS/platform; configured/actual device; GPU/driver/CUDA when applicable; MAVI build/commit; frame policy; tracker parameters; and `inputColourSpace="RGB"`.

Production rejects missing MAVI build/commit identity; development may use explicit `unknown-development`.

- [ ] **Step 6: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_runtime_provenance.py tests/test_worker_settings.py -q
git add mavi_vision/runtime mavi_vision/common/settings.py tests
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
T = TypeVar("T")

class ProcessExecutor(Protocol):
    async def run(self, func: Callable[..., T], /, *args: object, **kwargs: object) -> T: ...

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

`ProcessExecutor` is model-neutral. `VisionExecutionLane` structurally implements it and is the production executor passed to `WorkerRunner` in Task 11.

- [ ] **Step 1: Write a failing serialization/thread-affinity test**

Submit two functions concurrently; record `threading.get_ident()` and overlap markers. Assert both execute on the same non-event-loop thread and never overlap.

- [ ] **Step 2: Implement the lane**

Use one `ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-vision")`; `run()` dispatches a `functools.partial` through `loop.run_in_executor`. Reject calls after `close()`.

- [ ] **Step 3: Write activity/watchdog tests using explicit monotonic values**

Cover inactive, active below threshold, exactly at threshold, beyond threshold, and completed activity. Do not sleep in unit tests.

- [ ] **Step 4: Implement thread-safe activity markers**

Protect state with `threading.Lock`; inference callers clear active state in `finally`.

- [ ] **Step 5: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py -q
git add mavi_vision/runtime/execution_lane.py mavi_vision/runtime/activity.py tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py
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

Canonical output order:

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

- [ ] **Step 1: Write class-mapping tests with a fake runtime**

Feed `person`, `car`, `motorcycle`, `bus`, `truck`, `dog`; assert Person/Vehicle mapping for the first five and profile-driven ignoring of `dog`.

- [ ] **Step 2: Write adversarial geometry tests**

Cover all four partial overflows, box larger than frame, fractions, zero area after clipping, inverted XYXY, NaN/Inf, tiny valid boxes, portrait/landscape/odd dimensions. Policy: finite partial overflow clips; zero-area after clipping discards; malformed/inverted/non-finite/impossible confidence or vocabulary violation raises `InferenceContractError`.

- [ ] **Step 3: Implement normalization with no second NMS/cap**

Call `runtime.infer(frame.image)` once, validate classes/geometry, map to normalized XYWH, and sort canonically. Do not add generic NMS or generic count truncation.

- [ ] **Step 4: Prove deterministic adapter ordering**

Return the same fake detections in multiple backend permutations; assert byte-for-byte equal serialized candidate tuples after normalization.

- [ ] **Step 5: Run and commit**

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
- Modify: `src/vision/tests/test_runtime_provenance.py`
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

- [ ] **Step 1: Add a qualified runtime optional dependency group**

Use Task-1 selected semantic versions in `[project.optional-dependencies].vision-runtime`. Production still installs from platform/device hash locks; `pyproject.toml` does not replace those locks. Base/core installation must remain free of heavyweight model runtime packages.

- [ ] **Step 2: Write the RGB/BGR regression test**

Internal pure helper:

```python
def _rgb_to_bgr(image_rgb: NDArray[np.uint8]) -> NDArray[np.uint8]: ...
```

Input `[11, 22, 33]` must become `[33, 22, 11]`, remain `uint8` H×W×3 contiguous, and leave source bytes unchanged.

- [ ] **Step 3: Implement lazy heavy-framework loading**

Core unit-test collection/import must not require PyTorch/MMDetection. Resolve heavy imports during runtime construction or a backend-loader helper; missing/incompatible packages become `RuntimeCompatibilityError` before leasing.

- [ ] **Step 4: Load only verified local resolved config/checkpoint paths**

Consume `VerifiedReleaseSelection`. Reject unresolved `_base_`, URL/model-zoo aliases, or artifact paths outside the trusted model release. No API accepts a model alias.

- [ ] **Step 5: Verify ordered runtime vocabulary exactly**

Read detector runtime class metadata after construction and require exact ordered equality with the manifest vocabulary. Mismatch -> runtime unavailable before any lease.

- [ ] **Step 6: Implement warm-up**

Generate an in-memory channel-distinct RGB frame, convert exactly once, run inference, and validate output contract without creating evidence artifacts.

- [ ] **Step 7: Implement inference conversion and error translation**

Wrap activity start/completion in `try/finally`; convert RGB once; run MMDetection; return only `RawDetection` values in original decoded-frame pixel XYXY coordinates. Translate CUDA OOM, poisoned-context errors, and invalid outputs to the Task-4 typed errors. No tensor/`DetDataSample` escapes.

- [ ] **Step 8: Run fast tests and a real local smoke test**

```powershell
cd src/vision
python -m pytest tests/test_rtmdet_colour_space.py tests/test_rtmdet_mapping.py tests/test_rtmdet_geometry.py -q
python ../../tools/vision/probe_runtime.py --config <resolved-config> --checkpoint <checkpoint> --checkpoint-sha256 <reviewed-full-digest> --device cpu
```

Expected: all fast tests pass; real smoke passes without network access and vocabulary matches.

- [ ] **Step 9: Commit**

```powershell
git add mavi_vision/runtime/mmdetection.py tests/test_rtmdet_colour_space.py pyproject.toml
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
    def update(self, frame: DecodedFrame, detections: Sequence[DetectionCandidate]) -> Sequence[TrackCandidate]: ...
```

- [ ] **Step 1: Write pixel conversion and timestamp tests**

For a 200×100 frame and normalized box `(x=.1, y=.2, width=.3, height=.4)`, native ByteTrack receives `[20, 20, 80, 60]` and timestamp `frame.offset_ms / 1000.0`.

- [ ] **Step 2: Write every-class/every-frame ageing tests**

With only Person detections, Vehicle native tracker is still called with an empty set every frame; repeat symmetrically. This prevents lost-track age from freezing on absent-class frames.

- [ ] **Step 3: Write backend reordering/ordinal tests**

Attach `data["mavi_ordinal"]` to each `sv.Detections` row. A fake native tracker returns rows reordered; emitted MAVI candidates must recover original normalized box/confidence by ordinal, not returned-array position.

- [ ] **Step 4: Write tentative/unmatched evidence tests**

`tracker_id == -1` emits nothing; predicted/unmatched native state emits nothing; confirmation later starts MAVI evidence on that frame with no backfill.

- [ ] **Step 5: Write class isolation and deterministic MAVI ID tests**

Native tracker ID `1` may exist in both class trackers, but MAVI IDs remain separate. Newly confirmed tracks on the same frame are assigned by `(bbox.x, bbox.y, bbox.width, bbox.height, -confidence, mavi_ordinal)` and never ordered by native tracker ID.

- [ ] **Step 6: Exercise real qualified ByteTrack sequences**

Test continuous object, crossing objects, short occlusion/reacquisition, long disappearance/new ID, low-confidence second stage, empty scene, and VFR/timestamp gaps using the selected Trackers version.

- [ ] **Step 7: Implement adapter and typed tracker failure translation**

Any backend exception becomes `TrackerError(code="vision_tracker_failed", disposition=CONTINUE)`. Every new attempt gets new native tracker objects and ID maps.

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
        staging_factory: Callable[[UUID, int], StagingArtifactStore],
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

The production composition root binds `settings.media_root` into `staging_factory`, for example `lambda job_id, attempt: StagingArtifactStore(settings.media_root, job_id, attempt)`. The processor therefore cannot accidentally choose a different root per job.

- [ ] **Step 1: Write attempt-lifecycle tests**

Call `process()` twice with one fake long-lived runtime. Assert runtime identity is unchanged while detector adapter, ByteTrack adapter, staging store, and `VideoProcessor` are recreated; track IDs restart; attempt keys use the correct count.

- [ ] **Step 2: Write failure-notification tests**

Detector OOM -> sink receives exact RECOVER error once and same error rethrows. Tracker failure -> sink receives CONTINUE; this class does not reconstruct the detector itself.

- [ ] **Step 3: Implement minimal attempt composition**

Create `RTMDetDetector(runtime, profile)`, new `ByteTrackTracker(profile.tracker)`, `staging_factory(job_id, attempt_count)`, and new existing `VideoProcessor`; delegate. No lease acquisition, heartbeat, CUDA recovery, or Task-11 persistence here.

- [ ] **Step 4: Run and commit**

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
- `WorkerRunner` allowlists approved `ProcessingDependencyError.code` values and maps them to `/fail` only after existing ownership checks.

- [ ] **Step 1: Write the red test proving the current catch-all collapses OOM**

A detector raises `GpuOutOfMemoryError`; expected new behaviour is the same typed error exits `VideoProcessor`, not `VideoProcessingError("pipeline_processing_failed")`.

- [ ] **Step 2: Add only the narrow model-neutral pass-through catch**

Catch `ProcessingDependencyError` before generic `Exception`, call `_cleanup_best_effort(lease_guard)`, rethrow unchanged. Do not import backend-specific exception types.

- [ ] **Step 3: Write runner stable-code tests**

Owned lease + each of `vision_inference_contract_failed`, `vision_gpu_out_of_memory`, `vision_gpu_runtime_failed`, `vision_tracker_failed` -> exactly one `/fail` with generic sanitized message.

- [ ] **Step 4: Write lease-loss race tests**

Typed failure and expiry race -> lease loss wins; API receives no `/fail`.

- [ ] **Step 5: Implement allowlisted handling**

Unknown typed code does not pass through blindly; normalize it to generic `vision_processing_failed` and log locally as a programming/configuration defect.

- [ ] **Step 6: Run Task-9 ownership regressions and commit**

```powershell
cd src/vision
python -m pytest tests/test_process_video.py tests/test_worker_runner.py tests/test_lease_ownership_matrix.py tests/test_artifact_publisher.py tests/test_artifact_store.py -q
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

Extend `WorkerRunner.__init__` with a model-neutral executor:

```python
process_executor: ProcessExecutor | None = None
```

If absent, Task-9-compatible tests/dev may use a small default `asyncio.to_thread` executor; production **must** pass the `VisionExecutionLane`. `_process_with_lease_heartbeats()` dispatches through `self._process_executor.run(...)`, never directly through `asyncio.to_thread` when the production lane is configured.

- [ ] **Step 1: Write supervisor startup state tests**

Valid verified release + warm-up -> READY. Missing/bad hash, unavailable requested CUDA, vocabulary mismatch, or warm-up failure -> UNAVAILABLE and lease calls remain zero. Production `auto` rejects before leasing.

- [ ] **Step 2: Implement supervisor startup through `VisionExecutionLane`**

Release verification happens before model construction. Runtime construction, warm-up, and output/vocabulary validation execute on the lane. State mutation is explicit and event-loop-owned.

- [ ] **Step 3: Write and implement OOM recovery tests**

RECOVER error -> state RECOVERING, no lease, exactly one same-release/same-device reconstruction+warm-up. Success -> READY; failure -> UNAVAILABLE; no second automatic reconstruction for the incident.

- [ ] **Step 4: Write and implement poisoned-runtime behaviour**

UNAVAILABLE disposition -> immediate UNAVAILABLE and process restart required. CONTINUE tracker error -> detector remains READY.

- [ ] **Step 5: Inject `ProcessExecutor` into `WorkerRunner` and keep it model-neutral**

Refactor processing dispatch only; heartbeat/LeaseGuard authority remains in the runner. Add a test proving production lane uses one thread while existing Task-9 runner tests can still use the default executor.

- [ ] **Step 6: Add a generic watchdog hook to the runner**

Add optional collaborators:

```python
watchdog_expired: Callable[[], bool] | None = None
watchdog_grace_seconds: float = 10.0
fatal_terminator: Callable[[int], NoReturn] = os._exit
```

While processing is active, check the watchdog at a poll interval <=1 second and before heartbeat renewal. Expiry marks the active guard lost, stops renewal, waits at most the configured grace for unwind, and invokes `fatal_terminator(70)` if native work remains stuck. Do not send `/fail` after local authority is invalidated.

- [ ] **Step 7: Test watchdog fatal path without terminating pytest**

Inject a fake terminator that records code 70 and raises a test sentinel. Block the processor on a `threading.Event`; assert no post-expiry heartbeat or `/fail`, bounded grace, lost authority, and terminator invocation.

- [ ] **Step 8: Keep health-v2 truthful without changing its schema**

`get_worker_health` may construct the existing v2 `ready` payload only when runtime readiness is true. A non-ready call must not invent a new status; use caller-visible unavailability/local diagnostics.

- [ ] **Step 9: Compose production worker loop in `main.py`**

Order:

1. create lane;
2. verify selected release;
3. build/start supervisor;
4. bind `settings.media_root` into staging factory;
5. build `ProductionVisionProcessor(runtime, profile, staging_factory, supervisor.report_processing_failure)`;
6. build `WorkerRunner(..., process_executor=lane, watchdog_expired=...)`;
7. outer loop calls `runner.run_once()` only in READY; calls `recover_if_required()` in RECOVERING; in UNAVAILABLE remains alive for diagnostics and never calls `lease()`;
8. close supervisor/lane/client in reverse order.

Do not hide readiness inside model-specific code in `WorkerRunner`.

- [ ] **Step 10: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_runtime_supervisor.py tests/test_runtime_watchdog.py tests/test_worker_runner.py tests/test_lease_ownership_matrix.py -q
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

- [ ] **Step 1: Write bundle determinism/integrity tests**

Same inputs -> same sorted manifest/hashes. Reject duplicate destinations, absolute paths, undeclared/missing files, and wrong hashes.

- [ ] **Step 2: Implement bundle assembly**

Include wheels, checkpoint, resolved config, manifest, qualification record, pipeline profile, runtime.json, selected lock, and bundle manifest. Exclude Git metadata, caches, CCTV, and unverified production artifacts.

- [ ] **Step 3: Emit offline installation command**

Use local wheels only:

```text
python -m pip install --no-index --require-hashes --find-links wheels -r runtime/<selected-platform>.lock
```

No target compilation/network resolution.

- [ ] **Step 4: Extend repository verification for release network/download hazards**

Reject model URLs, `git+https`, model-zoo aliases, or production metadata that requires an online resolver.

- [ ] **Step 5: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_offline_bundle_manifest.py -q
cd ../..
python tools/verify_repo.py
git add tools/vision/build_offline_bundle.py tools/verify_repo.py src/vision/tests/test_offline_bundle_manifest.py infrastructure
git commit -m "build: add offline vision runtime bundle"
```

---

### Task 13: Add Hosted Windows + Linux Vision Adapter CI and Move Core CI to the Qualified Python Minor

**Files:**
- Modify: `.github/workflows/quality-gate.yml`
- Create: `.github/workflows/vision-adapter-gate.yml`

- [ ] **Step 1: Change core quality gate from Python 3.13 to the Task-1 qualified minor**

Use the exact qualified minor (`3.12` or `3.11`), not a floating newest version.

- [ ] **Step 2: Create the cross-platform adapter matrix**

```yaml
strategy:
  matrix:
    os: [ubuntu-latest, windows-latest]
runs-on: ${{ matrix.os }}
```

Install base/dev dependencies plus only the qualified tracking-adapter dependencies needed by Gate B; no model weights.

- [ ] **Step 3: Run the exact lightweight adapter suite**

Include manifest/profile/qualification/hashing, RTMDet mapping/geometry/colour, ByteTrack, execution lane, supervisor/watchdog/provenance, production processor, generic artifact store, lease ownership; add Windows staging tests on Windows.

- [ ] **Step 4: Enforce lazy heavy-runtime boundaries**

If test collection requires PyTorch/MMDetection weights, fix imports rather than adding weights to hosted CI.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/quality-gate.yml .github/workflows/vision-adapter-gate.yml
git commit -m "ci: add cross-platform vision adapter gate"
```

---

### Task 14: Execute Real-Model, Offline, CCTV, Recovery, and Performance Qualification and Finalize `verified`

**Files:**
- Create: `tools/vision/qualify_phase1.py`
- Finalize: `models/manifests/rtmdet-m-coco-phase1-v1.json`
- Finalize: `models/qualifications/rtmdet-m-coco-phase1-v1.json`
- Finalize if qualified parameters changed: `src/vision/config/pipelines/phase1-detection-tracking-v1.json`
- Regenerate affected hashes in: `src/vision/runtime/mmdetection-phase1-v1/runtime.json`

**Interfaces:**
- `qualify_phase1.py` consumes model root, runtime/profile metadata, external corpus manifest, output directory, and device; it emits machine-readable metrics/evidence only, never corpus media.

- [ ] **Step 1: Implement qualification runner with anonymous evidence IDs**

External corpus input lists case ID, local path, SHA-256, optional annotation path, and scenario tags. Output contains case ID/hash, release hashes, platform/device identity, and metrics; no raw frame bytes.

- [ ] **Step 2: Implement detector/tracker metrics**

Record Person/Vehicle precision, recall, AP50, false positives/evaluated frame, IDF1, HOTA, ID switches, fragmentation, and post-map duplicate Vehicle detection/track counts. Qualification-only metric tooling does not become a production worker dependency.

- [ ] **Step 3: Run functional qualification on all four target variants**

Mandatory passed gates:

```text
windows-x86_64-cpu
windows-x86_64-cuda
linux-x86_64-cpu
linux-x86_64-cuda
```

Each proves explicit local resolved-config/checkpoint load, vocabulary equality, RGB/BGR contract, detector→ByteTrack→Task-9 artifact path, and secure staging.

- [ ] **Step 4: Run network-disconnected install/inference on both operating systems**

Install from Task-12 bundle with network unavailable; run one real video. Record bundle manifest hash and result.

- [ ] **Step 5: Run Linux/NVIDIA production qualification**

Representative CCTV, sustained long video, VRAM/RAM observation, controlled OOM recovery, controlled poisoned-context path where safely injectable, and watchdog fatal-restart fixture. Record decoded/inference/end-to-end FPS, processing/source ratio, p50/p95 inference latency, peak VRAM/RAM, startup/warm-up time, artifact volume, and long-run memory behaviour.

- [ ] **Step 6: Freeze the v1 detector/tracker profile**

Use a designated tuning subset to select conservative detector floor and ByteTrack parameters, then measure final acceptance on a separate baseline subset. Do not retune after seeing final acceptance results. If class-collapse duplicate Vehicle tracks require post-map suppression, stop and create a new profile/design change; do not silently add second NMS to v1.

- [ ] **Step 7: Finalize evidence-backed `verified` without a hash cycle**

Use this order:

1. choose/freeze `qualificationId`;
2. write final profile and runtime metadata; compute their hashes;
3. write the **final manifest** with `verificationStatus="verified"` and that `qualificationId`; compute the final manifest SHA-256;
4. write the qualification record containing the final manifest/checkpoint/config/profile/runtime hashes and all mandatory `passed` gates;
5. run `verify_release_selection()` and `tools/verify_repo.py` against the final pair.

The manifest references qualification by ID; the qualification record may hash the manifest. Do not make the manifest hash the qualification record, which would create a circular identity.

- [ ] **Step 8: Commit qualification metadata only**

```powershell
git add models/manifests models/qualifications src/vision/config/pipelines src/vision/runtime/mmdetection-phase1-v1 tools/vision/qualify_phase1.py
git commit -m "test: qualify phase1 RTMDet ByteTrack runtime"
```

Never add external CCTV or the checkpoint to Git.

---

### Task 15: Full End-to-End Regression, Exact-Head CI, and Review Closure

**Files:**
- No new production files expected.
- Any defect found here gets its own focused regression test and fix commit before rerunning the affected full gate.

- [ ] **Step 1: Run complete Python suite on Linux and Windows**

```powershell
cd src/vision
python -m pytest -q
```

Zero failures; only explicitly platform/hardware-gated skips are acceptable.

- [ ] **Step 2: Run repository verification**

```powershell
python tools/verify_repo.py
```

Must pass release metadata/qualification consistency and no tracked model/media/secret checks.

- [ ] **Step 3: Run .NET build/tests**

```powershell
dotnet build MAVI.sln --configuration Release
dotnet test MAVI.sln --configuration Release --no-build
```

- [ ] **Step 4: Run frontend tests/typecheck/build**

```powershell
cd src/web/mavi-web
npm ci
npm test
npm run typecheck
npm run build
```

- [ ] **Step 5: Re-run critical Task-9 authority/artifact tests explicitly**

```powershell
cd src/vision
python -m pytest tests/test_lease_guard.py tests/test_lease_ownership_matrix.py tests/test_process_video.py tests/test_source_integrity.py tests/test_artifact_store.py tests/test_artifact_publisher.py -q
```

- [ ] **Step 6: Verify Task-11 authority did not leak into Python**

Search production Python for PostgreSQL clients/direct SQL and `/complete` implementation. Expected: none.

- [ ] **Step 7: Push exact head and require hosted success on that SHA**

Required checks:

```text
MAVI Quality Gate               success
Vision Adapter Gate / ubuntu    success
Vision Adapter Gate / windows   success
```

Earlier green commits do not satisfy this gate.

- [ ] **Step 8: Request full-diff code review**

Review for framework-type leakage, hidden network paths, lease precedence, Windows reparse handling, cross-attempt state leakage, RGB/BGR errors, native-ID leakage, metadata drift, generic production thread-pool use, unsafe native-thread cancellation, and accidental Task-11 persistence.

- [ ] **Step 9: Audit the Revision-2 Definition of Done item-by-item**

Every Section-28 requirement in the spec must point to fresh test, qualification, or exact-head CI evidence. Any unsupported item keeps Task 10 open.

- [ ] **Step 10: After review corrections, rerun all affected full gates on the new head**

Only then use the normal finishing/merge workflow.

---

## Dependency and Task Ordering

```text
Task 1  Runtime matrix + resolved-config feasibility ----------------┐
Task 2  Cross-platform secure staging -------------------------------┤
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

Tasks 1 and 2 are explicit feasibility gates. Do not bury failure of either gate under downstream implementation.

## Self-Review / Spec Coverage Matrix

| Revision-2 spec area | Implemented by |
| --- | --- |
| Model-neutral runtime boundary | Tasks 4, 6, 7 |
| Long-lived detector / attempt-scoped tracker | Tasks 8, 9 |
| Dedicated execution lane | Tasks 5, 11 |
| Secure Windows/POSIX staging | Task 2 |
| Manifest/profile/qualification separation | Task 3 |
| Resolved config + vocabulary integrity | Tasks 1, 3, 7 |
| Evidence-backed `verified` | Tasks 3, 14 |
| RGB/BGR contract | Tasks 6, 7, 13, 14 |
| ByteTrack pixel/timestamp/ordinal/empty-frame semantics | Task 8 |
| No tentative backfill / matched-only evidence | Task 8 |
| Typed runtime failure propagation | Tasks 4, 9, 10 |
| Lease-loss precedence | Tasks 10, 11, 15 |
| OOM recovery / poisoned runtime | Task 11 |
| Hung native inference watchdog | Tasks 5, 11, 14 |
| Complete dependency-graph qualification | Task 1 |
| Offline hashed deployment | Tasks 1, 12, 14 |
| Windows + Linux hosted CI | Task 13 |
| CCTV quality/performance baseline | Task 14 |
| No generic second NMS/cap | Tasks 6, 14 |
| Full provenance | Tasks 4, 7, 14 |
| Health-v2 unchanged/truthful | Task 11 |
| Task-11 persistence excluded | Tasks 9, 15 |
| Exact-head regression/CI/review | Task 15 |

## Placeholder and Type-Consistency Review

- No production package version is guessed where the architecture explicitly requires experimental qualification; Task 1 generates exact values and every later packaging/runtime step consumes `runtime.json` and hash locks.
- `DetectorRuntime`, `RawDetection`, `ProcessingDependencyError`, `RuntimeDisposition`, `RuntimeProvenance`, `ProcessExecutor`, `VisionExecutionLane`, `InferenceActivity`, `RTMDetDetector`, `ByteTrackTracker`, `ProductionVisionProcessor`, and `RuntimeSupervisor` are defined before downstream use.
- `ProductionVisionProcessor.staging_factory` is consistently attempt-scoped as `Callable[[UUID, int], StagingArtifactStore]`; the composition root binds `media_root` once.
- `WorkerRunner` receives the model-neutral `ProcessExecutor`; production passes `VisionExecutionLane`, while Task-9-compatible tests may use the default executor.
- Qualification/manifest hashing has no circular dependency: manifest references qualification by ID; qualification may hash the final manifest.
- Existing Task-9 public interfaces (`Detector.detect`, `Tracker.update`, `VideoProcessor.process`, `StagingArtifactStore`) remain stable except for the explicitly approved model-neutral typed-error pass-through and production execution dispatch.
- Hardware-dependent results are explicit blocking acceptance gates, not deferred implementation placeholders.
