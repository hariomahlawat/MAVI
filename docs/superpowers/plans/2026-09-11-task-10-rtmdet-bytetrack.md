# Task 10 Qualified RTMDet + ByteTrack Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Task-9 fixture detector/tracker path with a qualified, fully offline RTMDet-M + ByteTrack Person/Vehicle runtime while preserving Task-9 lease authority, evidence integrity, artifact security, and deterministic processing semantics on Windows and Linux.

**Architecture:** Keep the existing `VideoProcessor`, `Detector`, and `Tracker` boundaries model-neutral. Add a process-scoped `MMDetectionRuntime`, a single-thread `VisionExecutionLane`, attempt-scoped RTMDet/ByteTrack/staging composition, evidence-backed model/runtime qualification, and security-equivalent POSIX/Windows staging backends. The asyncio worker thread retains lease/heartbeat authority; synchronous model work stays on the dedicated vision lane.

**Tech Stack:** Python 3.12 candidate with Python 3.11 fallback; PyTorch/torchvision; an MMDetection 3.3.x-compatible MMEngine/MMCV stack selected by qualification; RTMDet-M; `trackers.ByteTrackTracker`; Supervision/SciPy/NumPy/OpenCV as tracker dependencies; PyAV/FFmpeg; Pydantic 2; pytest; GitHub Actions; Win32/NT filesystem APIs for native Windows staging; SHA-256 release integrity.

**Spec:** `docs/superpowers/specs/2026-09-11-task-10-rtmdet-bytetrack-design.md`

## Current Execution Status — 2026-09-12

- **Task 1 remains open as a release-qualification task.** Bounded Tasks 1A/1B are complete: the frozen Python 3.12 hosted CPU semantic graph, self-contained resolved RTMDet-M config, restricted checkpoint loading, and real Linux/Windows CPU inference are verified. Linux/Windows NVIDIA qualification and hashed offline wheelhouse locks remain pending and must not be inferred.
- **Task 2 and corrective Task 2A are complete.** Frozen resolved-config identity is enforced in CI, qualification evidence is preserved as a complete non-hidden artifact set, resolver publication is alias-safe/atomic, and native Windows staging includes the additional post-replace rollback and native-name length regressions.
- **Task 3 is complete.** MAVI now has strict model-manifest, pipeline-profile and qualification-record loaders; exact-byte release identities; trusted-root/no-link artifact resolution; an evidence-backed `VerifiedReleaseSelection`; and repository verification that explicitly prevents a pending release from being presented as production-qualified.
- **Task 4 is complete.** Framework-neutral detector-runtime contracts, stable typed dependency failures, operational-only runtime/device/watchdog settings, and immutable provenance are implemented. Provenance is bound to the live qualified dependency graph, exact interpreter identity, platform/device qualification state and verified release lock; development drift is explicitly recorded as `unverified`.
- **Task 5 is complete.** The dedicated `VisionExecutionLane` serializes accepted synchronous runtime work on one process-scoped thread, preserves already-submitted native work across asyncio cancellation, and makes shutdown idempotent and cancellation-safe. `InferenceActivity` provides lock-protected monotonic start/completion state for the later watchdog supervisor and correctly handles the cross-thread pre-start sampling race.
- **Task 6 is complete.** `RTMDetDetector` now provides the deterministic framework-neutral normalization boundary: verified runtime/profile identity checks, strict source-vocabulary validation, finite XYXY/confidence validation, frame-bound clipping, zero-area discard, normalized XYWH conversion, canonical ordering, and frame-local ordinals. No secondary NMS or generic detection cap is introduced. Signed zero is canonicalized before sorting so backend permutation cannot alter serialized output or ordinal assignment.
- **Task 7 is complete.** The production MMDetection/RTMDet runtime now consumes only verified local release artifacts, enforces a deterministic data-only resolved-config contract before MMEngine loading, lazily loads the qualified runtime graph, verifies exact ordered vocabulary, exact platform-qualified Python and PyTorch/TorchVision binary identities, owns the single RGB→BGR conversion, emits framework-neutral raw detections, and preserves typed CUDA/runtime failures. The real production runtime path is exercised on the qualified Linux and Windows CPU candidates. This does **not** promote the overall release to production `verified`: NVIDIA hardware qualification and hashed offline wheelhouse/release locks remain open under Task 1.
- **Task 8 is complete.** The exact `trackers==2.6.0` / `supervision==0.30.2` class-separated ByteTrack adapter is implemented with corrected versioned profile semantics, timestamped empty-frame updates, strict ordinal round-trip, MAVI-owned deterministic IDs, attempt invalidation after partial native failure, and exact-package Linux/Windows qualification evidence. This closes the hosted-CPU Task-8 gate only; it does not promote the overall release to production `verified`.
- **Task 9 is complete.** The fresh production attempt-composition facade is merged into the Task-10 integration branch with typed dependency failures preserved through `VideoProcessor`, one runtime-provider snapshot per accepted attempt, fresh detector/tracker/staging/processor state per attempt, exact-package Linux/Windows qualification, and post-merge validation complete.
- **Task 10 is complete.** Worker-side typed runtime/tracker failures are allowlisted at the control-plane boundary, unknown typed codes fail closed, terminal messages are sanitized, and Task-9 lease-loss precedence remains authoritative. **Task 11 and Task 13 remain implementation work** and may proceed while Task 1 hardware/release evidence is open. They must continue to treat the selected runtime as partially qualified and must not claim production `verified` status unless the complete selected runtime binding is actually qualified.
- **Task 12 remains blocked on the hashed wheelhouse/release-lock portion of Task 1. Task 14 remains blocked on Task 1 GPU qualification and Task 12 offline-bundle evidence. Task 15 is final closure only after every mandatory gate is complete.**
- **Next implementation task:** Task 11 — implement the runtime supervisor, readiness gate, bounded recovery, watchdog, execution-lane worker dispatch, and production worker composition.

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

**Status (verified 2026-09-11): COMPLETE.** Security-equivalent attempt staging is now proven on hosted Linux and native Windows without weakening the Task-9 POSIX no-follow boundary.

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

- [x] **Step 1: Lock existing POSIX behaviour before moving code**

Add any missing assertions needed to preserve exact existing key/error semantics, then run:

```powershell
cd src/vision
python -m pytest tests/test_artifact_store.py tests/test_artifact_publisher.py -q
```

Expected: PASS against the pre-refactor implementation.

Move the current hardened `dir_fd`/`O_NOFOLLOW` implementation to `artifact_store_posix.py`; keep shared logical validation and `StagingArtifactError` in `artifact_store.py`; delegate by `os.name`. Re-run the same suite and require identical results.

- [x] **Step 2: Write Windows path/reparse tests before implementing the backend**

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

- [x] **Step 3: Implement a small isolated handle-relative Windows helper layer**

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

- [x] **Step 4: Implement Windows `write_bytes()` and `cleanup()` with the same authority boundary as POSIX**

`write_bytes()` must validate the logical name, traverse/create only the attempt ancestry without following reparse points, create an exclusive temp sibling, write+flush, revalidate parent identity, call `authorize_publish()` immediately before replacement, replace inside that same validated directory, revalidate identity again, and roll back a publication known to have raced.

`cleanup()` removes only the current attempt subtree and never traverses a reparse point.

- [x] **Step 5: Run platform security tests**

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

- [x] **Step 6: Commit**

```powershell
git add src/vision/mavi_vision/storage src/vision/tests/test_artifact_store.py src/vision/tests/test_artifact_store_windows.py
git commit -m "feat: add secure windows attempt staging"
```

#### Verification evidence

PR #17 (`feat: add secure native Windows attempt staging`) was verified on exact head `0c74fc97aab8765931ceeed023c76c6610f6cce2` and squash-merged as `1045031fba4927db48df55825b5b6bd00186a5f3`.

- MAVI Quality Gate #166, run `34620478019`: **PASS**.
- Task 10 Staging Security #2, run `34620477979`: **PASS**.
- Ubuntu job `103332917805`: **14 passed, 6 Windows-only skips**.
- Windows job `103332918374`: **16 passed, 4 POSIX-only skips**.
- Native Windows coverage exercised a real NTFS junction in attempt ancestry, directory substitution during publication, nested reparse-point cleanup, sibling-attempt isolation, immediate pre-replace lease authorization, and denied-authority rollback.
- The first Windows run exposed `ERROR_INVALID_PARAMETER` in the Win32 rename primitive. The implementation was corrected to native `NtSetInformationFile(FileRenameInformation)` and native disposition handling; no test or security requirement was weakened.
- Post-merge Task 10 Staging Security #3, run `34620795230`, passed again on merge commit `1045031fba4927db48df55825b5b6bd00186a5f3` with Ubuntu job `103333970486` and Windows job `103333970884` both green.

The public `StagingArtifactStore` constructor and methods remain unchanged. Shared logical validation and descriptor generation stay in the facade; POSIX retains `dir_fd`/`O_NOFOLLOW`, while Windows uses validated no-follow handles, stable volume/file identities, NT root-relative descendant opens, handle-relative rename, and handle-based cleanup.

**Reviewer gate:** If link/reparse and directory-substitution safety cannot be demonstrated on native Windows, stop and revisit the formal Windows-support decision; do not weaken the POSIX backend.

### Task 2A — Corrective Qualification/Evidence and Staging Hardening Checkpoint

**Status (verified 2026-09-11): COMPLETE.** PR #18 was squash-merged as `a4cea8ab2db21bc62d2bb9033bcee2af0886e4ab` after all corrective acceptance gates passed on exact head `5528c5cfdb945f69ddac47bbe14089f488b3f77f`.

This checkpoint is intentionally bounded. It does not redesign Task 1 or Task 2 and does not add production detector/tracker functionality.

- [x] Runtime qualification CI compares the generated resolved-config SHA-256 against `runtime.json.resolvedConfig.sha256` and fails closed on mismatch before real inference.
- [x] Runtime qualification evidence is emitted under the non-hidden `qualification-evidence/` directory; the workflow verifies the expected evidence set, probe success, exit code, and resolved-config identity before artifact upload.
- [x] `resolve_mmdet_config.py` rejects relative/absolute, symlink and hard-link aliases of the source using file identity where available and canonical path identity otherwise.
- [x] Resolver validation/reload/equivalence checks occur entirely against a temporary candidate; only a validated candidate is atomically promoted with `os.replace`, so failed validation cannot destroy a previously valid output.
- [x] Native Windows staging validates UTF-16 component length before populating the 16-bit `UNICODE_STRING` length fields and rejects embedded NUL/oversized components with the shared logical error boundary.
- [x] Native Windows regression coverage now substitutes the logical parent **after** handle-relative replacement and proves rollback deletes the exact published handle rather than any redirected logical path.
- [x] Hosted MAVI Quality Gate #170, run `34623326074`, passed on the exact corrective head.
- [x] Task 10 Runtime Qualification #27, run `34623326104`, passed on Linux and Windows on the exact corrective head.
- [x] Task 10 Staging Security #7, run `34623326049`, passed on Linux and native Windows on the exact corrective head.
- [x] Qualification artifacts are preserved as Windows artifact `10274240528` (SHA-256 `43803251bbb543e666f6307827a09540d5ab6bc11fff76e0b0f085b1cbf46873`) and Ubuntu artifact `10273670517` (SHA-256 `734173f898f1ab13b45c7546784c77ebf5e5cda88b2d8a416a399e741c35c8af`).

---

### Task 3: Add Model Manifest, Pipeline Profile, Qualification Record, and Exact-Byte Integrity

**Status (verified 2026-09-11): COMPLETE, including post-review hardening.** The Task-3 implementation and review corrections passed MAVI Quality Gate #195 (run `34631805521`), Task 10 Staging Security #32 (run `34631805597`), and Task 10 Runtime Qualification #52 (run `34631805690`) on exact implementation head `da44c41976ae15a44efa4178cbc41961e79b168e`.

Post-review hardening is part of the Task-3 acceptance boundary: every passed qualification gate now requires integrity-backed evidence; repository verification validates every tracked manifest/profile/qualification/runtime metadata record and all cross-record identities; `runtime.json` is strictly schema-validated; every qualified offline lock is resolved from the trusted runtime root and exact-byte SHA-256 checked; and every qualified platform carries an exact Python interpreter identity. Hosted CPU qualification is pinned to Linux CPython 3.12.14 and Windows CPython 3.12.10, and CI verifies those frozen interpreter identities before inference.

The committed Phase-1 manifest deliberately remains `verificationStatus="unverified"`; the qualification record keeps CUDA, offline-install, CCTV-quality and Linux NVIDIA recovery/performance gates `pending`. The initial analytical thresholds/ByteTrack values are therefore candidate profile values, not production-qualified tuning. Task 14 owns final tuning/acceptance and the evidence-backed transition to `verified`.

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

- [x] **Step 1: Lock exact-byte repository rules**

Create:

```gitattributes
*.json text eol=lf
*.lock text eol=lf
*.py text eol=lf
```

Write tests rejecting BOM-bearing qualified JSON and CRLF in release JSON/lock files. `sha256_release_file()` hashes exact on-disk UTF-8 bytes; it does not parse/re-serialize JSON first.

- [x] **Step 2: Write failing manifest validation tests**

Cover absolute/URL/backslash/`..` artifact paths, malformed SHA-256, empty/duplicate vocabulary, verified-without-qualification ID, and model-root escape via filesystem link/reparse component.

- [x] **Step 3: Implement strict manifest loading and trusted-root containment**

Use `extra="forbid"` semantics. Artifact paths are logical forward-slash relative paths only. Release-path verification walks from the configured model root and rejects link/reparse redirection; do not rely solely on string prefix comparison after `resolve()`.

- [x] **Step 4: Write and implement pipeline-profile validation**

The profile includes detector floor, the five allowed source classes, exact class mapping, explicit ByteTrack parameters, and `framePolicy="every-frame"`. Do **not** add a generic `maxDetections` field in Task 10. Numeric thresholds must have explicit validated ranges; mapping keys must exist in the selected manifest vocabulary.

- [x] **Step 5: Implement immutable exact-byte profile identity**

The provenance hash is `sha256_release_file(profile_path)` rather than JSON canonical reserialization.

- [x] **Step 6: Write and implement qualification-evidence verification**

A manifest marked `verified` is accepted only when the referenced qualification file exists and model/checkpoint/config/profile/runtime hashes all match, runtime IDs match, and every mandatory gate is `passed`. Development `unverified` requires explicit `allow_unverified=True`; checkpoint/config integrity still applies.

- [x] **Step 7: Implement `verify_release_selection()`**

Return one frozen `VerifiedReleaseSelection` carrying the loaded manifest/profile/qualification/runtime identities, exact hashes, and resolved local artifact paths. Production runtime construction consumes this object and does not re-resolve configuration ad hoc.

- [x] **Step 8: Extend repository verification**

`tools/verify_repo.py` validates manifest/profile/qualification JSON, lowercase SHA-256 format, path/URL rules, LF/no-BOM, identity consistency, and the existing no-weight/media/secret rule. Before Task 14, the committed manifest remains explicitly `unverified`; repository verification must not report it as production-qualified.

- [x] **Step 9: Run and commit**

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

**Status (verified 2026-09-12): COMPLETE.** The Task-4 implementation is contained in PR #20 and its review-hardening sequence. Exact-head MAVI Quality Gate #209 (run `34665921642`) passed on implementation head `86045fa189795fa7ded8f296b5b2cc1137843c3b` with .NET Domain 71/71, Application 23/23, Integration 150/150, Python 302 passed with 11 platform skips after the final review fixes, frontend 9/9, and repository verification green. Framework-neutral contracts remain free of PyTorch/MMDetection/MMCV/Supervision/Trackers imports; production provenance is bound to the verified runtime semantic graph, exact platform interpreter identity, qualified device variant, and verified offline lock. Development experiments that drift from a verified release are explicitly downgraded to `unverified` rather than inheriting the release label.

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

- [x] **Step 1: Write validation tests for raw runtime values**

Require finite XYXY/confidence, confidence `[0,1]`, and non-empty source class. Raw boxes may be outside the frame; clipping belongs to the RTMDet adapter.

- [x] **Step 2: Implement framework-neutral types with no heavy ML imports**

`interfaces.py`, `errors.py`, and `provenance.py` must not import `torch`, `mmdet`, `mmcv`, `supervision`, or `trackers`.

- [x] **Step 3: Write and implement typed failure codes**

Define:

```python
GpuOutOfMemoryError("vision_gpu_out_of_memory", RuntimeDisposition.RECOVER)
GpuRuntimeError("vision_gpu_runtime_failed", RuntimeDisposition.UNAVAILABLE)
InferenceContractError("vision_inference_contract_failed", RuntimeDisposition.RECOVER)
TrackerError("vision_tracker_failed", RuntimeDisposition.CONTINUE)
```

Enforce the existing worker failure-code grammar and maximum length.

- [x] **Step 4: Extend `WorkerSettings` with operational selection only**

Add model root/manifest/profile/runtime paths, `device_policy`, `device_index`, `production_mode`, `inference_watchdog_seconds`, and `watchdog_grace_seconds`. Production mode rejects `auto`. Do not expose detector/tracker thresholds as environment settings.

- [x] **Step 5: Implement immutable provenance**

Capture model/config/profile/qualification/runtime hashes; Python/PyTorch/torchvision/MMDetection/MMCV/MMEngine/Trackers/Supervision/SciPy/NumPy/OpenCV/PyAV and FFmpeg identity where available; OS/platform; configured/actual device; GPU/driver/CUDA when applicable; MAVI build/commit; frame policy; tracker parameters; and `inputColourSpace="RGB"`.

Production rejects missing MAVI build/commit identity; development may use explicit `unknown-development`.

- [x] **Step 6: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_runtime_provenance.py tests/test_worker_settings.py -q
git add mavi_vision/runtime mavi_vision/common/settings.py tests
git commit -m "feat: add vision runtime contracts and provenance"
```

---

### Task 5: Add the Single-Thread Vision Execution Lane and Activity Monitor

**Status (verified 2026-09-12): COMPLETE.** PR #21 implements the bounded Task-5 execution/activity layer. Exact implementation head `076c1b31aea2bc9887dd87a47b16008d342b822e` passed MAVI Quality Gate #218 (run `34668012484`) with .NET Domain 71/71, Application 23/23, Integration 150/150, Python 333 passed with 11 platform skips, frontend checks green, and repository verification passed. Final Codex review on that head reported no major issues. Review hardening made executor shutdown remain awaitable across repeated cancellation and treats a watchdog timestamp sampled immediately before `mark_started()` as not hung rather than as a false clock-regression error.

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

- [x] **Step 1: Write a failing serialization/thread-affinity test**

Submit two functions concurrently; record `threading.get_ident()` and overlap markers. Assert both execute on the same non-event-loop thread and never overlap.

- [x] **Step 2: Implement the lane**

Use one `ThreadPoolExecutor(max_workers=1, thread_name_prefix="mavi-vision")`; `run()` dispatches a `functools.partial` through `loop.run_in_executor`. Reject calls after `close()`.

- [x] **Step 3: Write activity/watchdog tests using explicit monotonic values**

Cover inactive, active below threshold, exactly at threshold, beyond threshold, and completed activity. Do not sleep in unit tests.

- [x] **Step 4: Implement thread-safe activity markers**

Protect state with `threading.Lock`; inference callers clear active state in `finally`.

- [x] **Step 5: Run and commit**

```powershell
cd src/vision
python -m pytest tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py -q
git add mavi_vision/runtime/execution_lane.py mavi_vision/runtime/activity.py tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py
git commit -m "feat: add dedicated vision execution lane"
```

---

### Task 6: Implement the RTMDet-to-MAVI Detection Adapter with Deterministic Geometry

**Status (verified 2026-09-12): COMPLETE.** PR #22 implements the bounded Task-6 adapter. Exact implementation head `a8ca4bf4e3d7073dec1759109a8dfad07e9631e3` passed MAVI Quality Gate #221 (run `34670140578`) with .NET Domain 71/71, Application 23/23, Integration 150/150, Python 376 passed with 11 platform skips, frontend checks green, and repository verification passed. Final Codex review on that head reported no major issues. Review hardening canonicalizes IEEE-754 signed zero before clipping/sorting/ordinal assignment so permutation-independent serialized output remains deterministic.

**Files:**
- Modify: `src/vision/mavi_vision/detection/interfaces.py`
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

- [x] **Step 1: Write class-mapping tests with a fake runtime**

Feed `person`, `car`, `motorcycle`, `bus`, `truck`, `dog`; assert Person/Vehicle mapping for the first five and profile-driven ignoring of `dog`.

- [x] **Step 2: Write adversarial geometry tests**

Cover all four partial overflows, box larger than frame, fractions, zero area after clipping, inverted XYXY, NaN/Inf, tiny valid boxes, portrait/landscape/odd dimensions. Policy: finite partial overflow clips; zero-area after clipping discards; malformed/inverted/non-finite/impossible confidence or vocabulary violation raises `InferenceContractError`.

- [x] **Step 3: Implement normalization with no second NMS/cap**

Call `runtime.infer(frame.image)` once, validate classes/geometry, map to normalized XYWH, and sort canonically. Do not add generic NMS or generic count truncation.

- [x] **Step 4: Prove deterministic adapter ordering**

Return the same fake detections in multiple backend permutations; assert byte-for-byte equal serialized candidate tuples after normalization.

- [x] **Step 5: Run and commit**

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

- [x] **Step 1: Add a qualified runtime optional dependency group**

Use Task-1 selected semantic versions in `[project.optional-dependencies].vision-runtime`. Production still installs from platform/device hash locks; `pyproject.toml` does not replace those locks. Base/core installation must remain free of heavyweight model runtime packages.

- [x] **Step 2: Write the RGB/BGR regression test**

Internal pure helper:

```python
def _rgb_to_bgr(image_rgb: NDArray[np.uint8]) -> NDArray[np.uint8]: ...
```

Input `[11, 22, 33]` must become `[33, 22, 11]`, remain `uint8` H×W×3 contiguous, and leave source bytes unchanged.

- [x] **Step 3: Implement lazy heavy-framework loading**

Core unit-test collection/import must not require PyTorch/MMDetection. Resolve heavy imports during runtime construction or a backend-loader helper; missing/incompatible packages become `RuntimeCompatibilityError` before leasing.

- [x] **Step 4: Load only verified local resolved config/checkpoint paths**

Consume `VerifiedReleaseSelection`. Reject unresolved `_base_`, URL/model-zoo aliases, or artifact paths outside the trusted model release. No API accepts a model alias.

- [x] **Step 5: Verify ordered runtime vocabulary exactly**

Read detector runtime class metadata after construction and require exact ordered equality with the manifest vocabulary. Mismatch -> runtime unavailable before any lease.

- [x] **Step 6: Implement warm-up**

Generate an in-memory channel-distinct RGB frame, convert exactly once, run inference, and validate output contract without creating evidence artifacts.

- [x] **Step 7: Implement inference conversion and error translation**

Wrap activity start/completion in `try/finally`; convert RGB once; run MMDetection; return only `RawDetection` values in original decoded-frame pixel XYXY coordinates. Translate CUDA OOM, poisoned-context errors, and invalid outputs to the Task-4 typed errors. No tensor/`DetDataSample` escapes.

- [x] **Step 8: Run fast tests and a real local smoke test**

```powershell
cd src/vision
python -m pytest tests/test_rtmdet_colour_space.py tests/test_rtmdet_mapping.py tests/test_rtmdet_geometry.py -q
python ../../tools/vision/probe_runtime.py --config <resolved-config> --checkpoint <checkpoint> --checkpoint-sha256 <reviewed-full-digest> --device cpu
```

Expected: all fast tests pass; real smoke passes without network access and vocabulary matches.

- [x] **Step 9: Commit**

```powershell
git add mavi_vision/runtime/mmdetection.py tests/test_rtmdet_colour_space.py pyproject.toml
git commit -m "feat: integrate local RTMDet runtime"
```

**Completion evidence — 2026-09-12**

- Substantive implementation head: `b43d6a43bffc85b82b759268b90e980a8ca6c8d4`.
- MAVI Quality Gate #265: passed — Domain 71/71, Application 23/23, Integration 150/150, Python 456 passed with 11 platform skips, repository verification passed, and Task-10 release-metadata relationships validated.
- Task 10 Runtime Qualification #107: passed on qualified Linux Python 3.12.14 and Windows Python 3.12.10 CPU candidates using the real production `MMDetectionRuntime` path.
- Final Codex substantive review on `b43d6a43bf`: “Didn't find any major issues.”
- Release boundary remains explicit: CPU runtime integration is qualified for these hosted candidates; CUDA/NVIDIA qualification and hashed offline wheelhouse/release locks remain pending under Task 1 and must not be inferred from Task 7 completion.


---

### Task 8: Implement the Exact Trackers-2.6 Class-Separated ByteTrack Adapter

**Status (verified 2026-09-12): COMPLETE for the bounded Task-8 hosted-CPU adapter gate.** The corrected candidate profile SHA-256 is `1d109f4dd666f18d1a234bf89d13ff3347cff09f48ce0f3c1c6c95714e4c530f`. This status does not imply CUDA/NVIDIA hardware qualification, offline wheelhouse/release-lock completion, CCTV accuracy qualification, or overall production `verified` release status.

**Closure evidence:**
- RED/TDD proof: MAVI Quality Gate run `34687629358` failed intentionally on the legacy profile semantic mismatch before the corrected implementation was introduced.
- Substantive implementation head `81f476f4f00cf381ff14f33a91d8ba547c85db1b`: MAVI Quality Gate #273, Task 10 Staging Security #53 and Task 10 Runtime Qualification #116 passed. The exact-package ByteTrack sequence suite passed on Linux Python 3.12.14 and Windows Python 3.12.10.
- Fresh CPU qualification evidence bound into `models/qualifications/rtmdet-m-coco-phase1-v1.json` from run `34689119149`: Linux job `103541173536`, artifact `10297181212`, SHA-256 `33cf750971960c017675691b02097484dbfb6748f0011b6cda4d4d086a56ed8e`; Windows job `103541173642`, artifact `10297031578`, SHA-256 `ee60755b04d55234ad628e58ccd3712e3dad3e120e24c9af39215ef5bbc489f2`.
- Evidence-binding head `3131d39f6bbc6ac4f960ef1f8fa905e534ede0ef`: MAVI Quality Gate #274, Task 10 Staging Security #54 and Task 10 Runtime Qualification #117 passed; the exact Trackers 2.6 suite re-passed on both hosted CPU candidates after qualification metadata binding.
- Run #117 verification artifacts: Linux artifact `10298280385`, SHA-256 `3bdb0eec69117c90ccc0d9f2af64f122233701d29104d106f7fa49d6d24aab43`; Windows artifact `10297601208`, SHA-256 `96db978da611e5725f88f1b75baf25fd49e628ac658b2164c92d29a53c0718e4`.
- Codex substantive review found one P2 exact-head evidence-integrity issue. The workflow was corrected to explicitly checkout the PR source head, record the executed/event/PR-head SHAs, and verify them before accepting evidence. Codex re-reviewed corrected head `81f476f4f0` and reported no major issues; the finding thread is resolved.
- Qualification record intentionally keeps `windows-x86_64-cuda`, `linux-x86_64-cuda`, both offline-install gates, CCTV quality baseline, and Linux/NVIDIA recovery-performance pending.

**Purpose:** Replace the Task-9 fixture tracker with an attempt-scoped adapter around the exact qualified `trackers==2.6.0` / `supervision==0.30.2` runtime without importing legacy Supervision ByteTrack semantics, leaking predicted-only evidence, depending on backend row order, or allowing Person/Vehicle identity crossover.

**Critical review finding before coding:** the pre-Task-8 pipeline profile still carries legacy-looking `minimumMatchingThreshold=0.8` semantics and the current threshold relationship permits `trackActivationThreshold < highConfidenceThreshold`. Those values/names do **not** map safely to Trackers 2.6.0. Trackers 2.6.0 expects a minimum IoU **similarity** threshold and only spawns new tracks from the high-confidence set. Task 8 therefore corrects the versioned profile first; it must not translate the old `0.8` value directly into `minimum_iou_threshold`.

**Files:**
- Create: `src/vision/mavi_vision/tracking/bytetrack.py`
- Create: `src/vision/tests/test_bytetrack_adapter.py`
- Create: `src/vision/tests/test_bytetrack_runtime.py` for exact installed-package sequence tests
- Modify: `src/vision/mavi_vision/runtime/profile.py`
- Modify: `src/vision/config/pipelines/phase1-detection-tracking-v1.json`
- Modify: `src/vision/tests/test_pipeline_profile.py`
- Modify: `.github/workflows/task10-runtime-qualification.yml`
- Modify after fresh exact-head evidence exists: `models/qualifications/rtmdet-m-coco-phase1-v1.json`
- Modify at closure: this plan

**Public interface remains:**

```python
class ByteTrackTracker(Tracker):
    def __init__(self, profile: ByteTrackProfile) -> None: ...

    def update(
        self,
        frame: DecodedFrame,
        detections: Sequence[DetectionCandidate],
    ) -> tuple[TrackCandidate, ...]: ...
```

Third-party types never appear in this public interface.

#### Locked Trackers 2.6.0 mapping

| MAVI profile | Trackers 2.6.0 |
| --- | --- |
| `reference_frame_rate` | `frame_rate` |
| `lost_track_buffer_seconds` | `lost_track_buffer = int(seconds * 30)` |
| `track_activation_threshold` | `track_activation_threshold` |
| `high_confidence_threshold` | `high_conf_det_threshold` |
| `minimum_iou_threshold` | `minimum_iou_threshold` |
| `minimum_consecutive_frames` | `minimum_consecutive_frames` |

The adapter always supplies `timestamp=frame.offset_ms / 1000.0` and never passes `frame.image` to native ByteTrack.

The first corrected candidate uses the exact Trackers-2.6 default association tuning as a neutral starting point:

```text
referenceFrameRate          = 30.0
lostTrackBufferSeconds      = 1.0
trackActivationThreshold    = 0.7
highConfidenceThreshold     = 0.6
minimumIouThreshold         = 0.1
minimumConsecutiveFrames    = 2
```

This is a candidate configuration, not an accuracy claim. Later CCTV qualification may tune it through a new profile hash/evidence event.

- [x] **Step 0: Correct and lock profile semantics before adapter implementation**

Change `ByteTrackProfile` / JSON as follows:

- add `reference_frame_rate` / `referenceFrameRate`;
- replace `minimum_matching_threshold` / `minimumMatchingThreshold` with `minimum_iou_threshold` / `minimumIouThreshold`;
- bump `profileVersion` to the next candidate revision;
- validate `detectorInferenceFloor < highConfidenceThreshold < trackActivationThreshold <= 1.0`;
- require `lostTrackBufferSeconds * 30` to be exactly integral within a tight numeric tolerance; never silently round an ambiguous policy;
- keep `minimumIouThreshold` in `[0,1]`, `referenceFrameRate > 0`, and existing positive confirmation/lost-buffer constraints.

Do **not** implement a compatibility alias for `minimumMatchingThreshold`; fail closed on stale profile bytes so old semantics cannot silently survive.

Because the pipeline-profile bytes change, the old CPU qualification evidence must not be represented as evidence for the corrected profile. On the implementation branch, after calculating the corrected profile hash, update the qualification record to that hash, set both `linux-x86_64-cpu` and `windows-x86_64-cpu` required gates back to `pending`, and remove their old evidence entries. The runtime profile may still retain its independently established hosted-CPU runtime identities; only the candidate pipeline qualification is reopened. The two CPU gates return to `passed` only after Step 10/11 produces fresh evidence for the corrected profile and real adapter.

- [x] **Step 1: Write fast tests for the exact profile/backend parameter mapping**

Tests must prove the exact native constructor arguments and reject the legacy mapping:

```text
1.0 s lost budget -> lost_track_buffer=30
referenceFrameRate=30 -> frame_rate=30.0
0.7 activation -> track_activation_threshold=0.7
0.6 high split -> high_conf_det_threshold=0.6
0.1 IoU -> minimum_iou_threshold=0.1
2 confirmation frames -> minimum_consecutive_frames=2
```

Also test non-integral 30-Hz lost-budget values, reversed confidence-threshold relationships, stale `minimumMatchingThreshold`, and invalid reference-rate/IoU values.

- [x] **Step 2: Build a lazy third-party boundary**

Create a private `_ByteTrackBindings` / loader in `tracking/bytetrack.py`.

Requirements:
- no top-level import of `trackers` or `supervision`;
- core MAVI imports/tests remain valid without optional vision-runtime packages;
- the loader uses the reviewed public `from trackers import ByteTrackTracker as NativeByteTrackTracker` API and a local Supervision `Detections` factory;
- unit tests replace the loader with fakes rather than importing heavy packages;
- application code does not duplicate `trackers==2.6.0` or `supervision==0.30.2` constants; version authority remains `runtime.json` and the production runtime qualification.

Add an AST/import regression analogous to the Task-7 lazy MMDetection boundary.

- [x] **Step 3: Implement strict frame/input validation before either native tracker mutates**

On each call:
- materialize the input sequence exactly once;
- require positive current-frame width and height;
- require global `frame_ordinal` uniqueness for all detections in the frame;
- require `source_frame_number` to increase strictly from the prior accepted call;
- require `offset_ms` to increase strictly from the prior accepted call.

This intentionally fails before native mutation instead of relying on Trackers 2.6.0's warning/skip behaviour for backwards or duplicate timestamps. Update the adapter's last-frame state only after both class updates succeed.

- [x] **Step 4: Implement exact normalized-to-native conversion**

For each class independently, convert the original normalized MAVI box using the **current** frame geometry:

```python
x1 = bbox.x * width
y1 = bbox.y * height
x2 = (bbox.x + bbox.width) * width
y2 = (bbox.y + bbox.height) * height
```

Construct a native detection set with:
- pixel XYXY array;
- confidence array always present, so Trackers 2.6 uses its two-stage ByteTrack path;
- `data["mavi_ordinal"]` as an integer array;
- no dependency on backend class IDs because class separation already occurs outside the native tracker.

Regression: normalized `(.1,.2,.3,.4)` on a 200×100 frame must produce `[20,20,80,60]`. Source MAVI candidates must remain unchanged.

- [x] **Step 5: Create two completely independent association domains and update both every frame**

Each adapter instance owns fresh attempt-local state:

```text
PERSON  -> one NativeByteTrackTracker + person native-ID map + person counter
VEHICLE -> one NativeByteTrackTracker + vehicle native-ID map + vehicle counter
```

Use fixed execution order Person then Vehicle for reproducibility, but never share tracker state or ID maps.

Call **both** native trackers on every frame, including an empty detection set. This preserves timestamp anchoring before a class first appears and advances lost-track ageing during class-absent frames.

If one native update raises after the other has already mutated, translate the failure and abort the attempt; do not attempt state rollback. Task 9 creates a fresh adapter on the next attempt, so partially advanced tracker state is never reused.

- [x] **Step 6: Prove and validate ordinal round-trip instead of trusting output order**

Trackers 2.6.0 may return rows in a different order. For a non-empty class input, validate native output before emitting anything:

- `tracker_id` exists and is an integral array with exactly one row per input detection;
- `mavi_ordinal` exists and is integral;
- output ordinals are unique and their set exactly equals the class input ordinal set;
- no unknown/missing/duplicate ordinal exists;
- `tracker_id == -1` is the only accepted tentative/unmatched sentinel;
- `tracker_id < -1` is a backend contract failure;
- the same non-negative native tracker ID cannot correspond to two current-frame rows in one class.

Recover original normalized box and confidence **only** from the ordinal map. Never use native output position, native/predicted XYXY, native confidence, or `tracked_objects` as MAVI evidence.

- [x] **Step 7: Implement tentative suppression and deterministic MAVI-owned IDs**

`tracker_id == -1` emits nothing and creates no MAVI mapping. No tentative observation is backfilled later.

For each class, when previously unseen confirmed native IDs appear:
1. recover their original current-frame MAVI detections by ordinal;
2. sort only the newly confirmed rows by
   `(bbox.x, bbox.y, bbox.width, bbox.height, -confidence, frame_ordinal)`;
3. allocate `person-000001`, `person-000002`, ... or `vehicle-000001`, ...;
4. persist native-ID -> MAVI-ID mapping only inside this adapter attempt.

Existing mappings never change. Native ID values/order never influence MAVI allocation.

Return all emitted `TrackCandidate` values sorted by original global `frame_ordinal` so backend reordering cannot change MAVI output order.

- [x] **Step 8: Translate every tracker-boundary failure once**

Any native construction/update exception or malformed native result is translated by raising the existing `TrackerError(local_diagnostic_message)`. Do **not** pass `code` or `disposition` arguments to its constructor: the existing type already fixes `failure_code == "vision_tracker_failed"` and `runtime_disposition == RuntimeDisposition.CONTINUE`.

Do not leak third-party exception text/types across the adapter boundary. MAVI input-contract failures detected by the adapter use the same stable tracker failure classification with a local diagnostic message.

Do not catch/translate process-level exceptions such as `KeyboardInterrupt`/`SystemExit`.

- [x] **Step 9: Complete the fast fake-backend regression matrix**

`test_bytetrack_adapter.py` must cover at least:

- exact pixel conversion and timestamp seconds;
- confidence/ordinal field construction;
- Person-only frame still calls Vehicle with empty input and vice versa;
- fully empty frame calls both trackers;
- strict frame-number and offset monotonicity;
- output reordering with ordinal recovery;
- missing/duplicate/unknown/non-integral ordinal;
- missing/non-integral/misaligned tracker IDs and invalid ID below `-1`;
- `-1` suppression and no historical backfill;
- original MAVI confidence/box retained despite altered native return values;
- independent Person/Vehicle native ID spaces;
- simultaneous new confirmations receive deterministic MAVI IDs independent of native IDs/output order;
- stable existing mappings;
- final output sorted by global frame ordinal;
- new adapter instance resets both maps/counters/native trackers;
- construction/update exception -> `TrackerError` with `vision_tracker_failed` and `CONTINUE`;
- no top-level Trackers/Supervision import.

- [x] **Step 10: Add exact-package Linux/Windows ByteTrack qualification tests**

`test_bytetrack_runtime.py` runs only after the qualified vision-runtime graph is installed and must fail, not skip, if Trackers/Supervision are absent or version-drifted.

Against the exact installed `trackers==2.6.0` and `supervision==0.30.2`, prove:

1. Supervision `data["mavi_ordinal"]` survives the backend's own slicing/reordering path.
2. A first native spawn returns `tracker_id=-1`; a later qualifying match confirms according to the selected candidate profile.
3. One continuous object retains identity.
4. Two crossing objects exercise association without adapter-order dependence.
5. A low-confidence observation can participate in second-stage association but cannot spawn a new track by itself.
6. Repeated empty frames age a confirmed track; reacquisition inside the 1.0 s budget may retain identity, while expiry beyond the backend's inclusive `<= 1.0 s` budget produces a new identity.
7. Equivalent time-domain behaviour is exercised at representative regular cadences and with VFR timestamp gaps.
8. Person/Vehicle overlap never shares association state.
9. Reordered native rows still emit original MAVI box/confidence by ordinal.

These are backend-contract/behaviour tests, not CCTV accuracy claims.

- [x] **Step 11: Extend Task-10 qualification CI and produce truthful fresh evidence**

Update `.github/workflows/task10-runtime-qualification.yml` triggers to include Task-8 production/test/profile inputs, especially:
- `src/vision/mavi_vision/tracking/**`;
- `src/vision/mavi_vision/detection/interfaces.py`;
- `src/vision/mavi_vision/runtime/profile.py`;
- `src/vision/tests/test_bytetrack_*.py`;
- the pipeline profile and qualification record.

After the qualified runtime packages are installed on both hosted CPU candidates:
- verify installed Trackers/Supervision versions against `runtime.json`;
- run the exact-package ByteTrack sequence suite;
- emit a parseable ByteTrack qualification evidence JSON containing exact profile hash, effective native parameters, platform/Python/package identities and sequence-test result;
- upload evidence as a non-hidden workflow artifact.

Only after both Linux and Windows runs pass may the qualification record bind the corrected pipeline-profile hash and fresh CPU evidence. Never reuse the old CPU evidence as if it had exercised the corrected tracking profile.

- [x] **Step 12: Full Task-8 acceptance, documentation, merge and cleanup**

Require on the final substantive PR head:
- MAVI Quality Gate green;
- Task 10 Runtime Qualification green on both qualified CPU candidates with the real ByteTrack sequence suite;
- repository release-metadata relationships green;
- clean Codex substantive review with all legitimate findings regression-covered.

Then update this plan with exact evidence while retaining the global Task-10 partial-qualification boundary (CUDA/NVIDIA and offline wheelhouse remain Task-1 work). Require exact-head gates again for the documentation-only closure commit, squash-merge into `feature/task-10-rtmdet-bytetrack` with expected-head protection, verify the integration SHA, and delete the Task-8 topic branch only through guarded merged-branch cleanup.

**Explicitly out of scope for Task 8:** detector tuning, post-map Vehicle duplicate suppression, ReID, face/ANPR features, cross-camera identity, CCTV accuracy claims, Task-9 lease/failure pass-through changes (Task 10), runtime supervisor/recovery (Task 11), CUDA qualification and offline wheelhouse freezing (Task 1/12).

---

### Task 9: Compose a Fresh Attempt Pipeline Around the Recoverable Shared Detector Runtime

**Status (2026-09-12): COMPLETE — SQUASH-MERGED INTO TASK-10 INTEGRATION.** Task 9 composes the already-qualified Task-7 detector boundary and Task-8 class-separated ByteTrack adapter into the existing `VideoProcessor`. It must not move lease authority, runtime lifecycle/recovery, or persistence into the pipeline layer.

**Additional corrections locked by this review:**

1. **Use a runtime provider, not a permanently captured runtime object.** Task 11 may replace the detector runtime object during bounded recovery. The processor must resolve the current runtime exactly once at the start of each accepted attempt, keep that snapshot fixed for the attempt, and allow a later attempt to receive the replacement runtime.
2. **Keep lease authority separate from local runtime-health reporting.** Lease loss forbids stale `/fail`, publication and cleanup mutation, but it must not erase a real OOM/inference/tracker health signal before the local supervisor can classify it.
3. **Add exact-package composition proof on Linux and Windows.** Unit tests prove lifecycle semantics with fakes; hosted runtime CI must also exercise the real RTMDet adapter + real Trackers-2.6 ByteTrack adapter + real `VideoProcessor` + real staging store with only the detector backend faked.
**Planning correction (2026-09-12):** Task 9's failure-sink contract requires detector/tracker `ProcessingDependencyError` values to survive `VideoProcessor` unchanged. The pre-Task-9 `VideoProcessor` catch-all currently collapses them into `VideoProcessingError("pipeline_processing_failed")`. The narrow model-neutral pass-through originally scheduled as Task-10 Steps 1–2 is therefore moved forward as Task-9 Step 0. This is a dependency-order correction, not a scope expansion: Task 10 still owns worker allowlisting, `/fail` mapping, and typed-error/lease-loss races.

**Files:**
- Create: `src/vision/mavi_vision/pipeline/production_processor.py`
- Create: `src/vision/tests/test_production_processor.py`
- Create: `src/vision/tests/test_production_processor_runtime.py`
- Modify: `src/vision/mavi_vision/pipeline/process_video.py`
- Modify: `src/vision/tests/test_process_video.py`
- Modify: `.github/workflows/task10-runtime-qualification.yml`

**Interfaces:**

```python
RuntimeProvider = Callable[[], DetectorRuntime]
ProcessingFailureSink = Callable[[ProcessingDependencyError], None]

class ProductionVisionProcessor:
    def __init__(
        self,
        runtime_provider: RuntimeProvider,
        profile: PipelineProfile,
        staging_factory: Callable[[UUID, int], StagingArtifactStore],
        runtime_failure_sink: ProcessingFailureSink,
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

The production composition root later binds `runtime_provider=lambda: supervisor.runtime` and binds `settings.media_root` into `staging_factory`, for example `lambda job_id, attempt: StagingArtifactStore(settings.media_root, job_id, attempt)`.

**Locked lifecycle/ownership invariants:**
- `ProductionVisionProcessor` is a long-lived facade, not a runtime owner.
- It calls `lease_guard.check_owned()` before attempt-local construction and then calls `runtime_provider()` exactly once for that accepted attempt.
- The returned runtime snapshot is fixed for the full attempt and is not cached after the call returns.
- Normal attempts may receive the same process-scoped runtime; after Task-11 recovery, a later attempt may receive a replacement runtime object.
- Every attempt creates a fresh `RTMDetDetector`, fresh `ByteTrackTracker`, fresh staging store and fresh `VideoProcessor`.
- No native tracker state, MAVI track-ID map/counter or staging namespace crosses attempts.
- The facade never calls `warmup()`, `close()`, runtime constructors, CUDA cleanup, supervisor recovery, lease/heartbeat APIs, `/fail`, `/complete`, or persistence.
- Readiness is a Task-11 control-loop precondition; Task 9 does not import or query `RuntimeSupervisor`.
- `runtime_failure_sink` is a local health-notification seam, not a job-terminal action. It must be synchronous, thread-safe, non-blocking, non-throwing and perform no network/control-plane I/O from the vision lane.
- Importing `mavi_vision.pipeline.production_processor` must not eagerly import PyTorch, MMDetection, MMCV, Trackers or Supervision.

- [x] **Step 0: Preserve typed dependency failures through `VideoProcessor` before composing attempts**

Write RED regressions proving:
- detector `GpuOutOfMemoryError` exits `VideoProcessor` as the exact same exception object;
- tracker `TrackerError` exits as the exact same exception object;
- an owned typed dependency failure performs the existing attempt-scoped best-effort failure cleanup;
- if ownership is already lost at the typed-failure cleanup boundary, cleanup is skipped but the **original typed dependency error still propagates unchanged** so the local runtime-health layer can classify it;
- generic processing failure + lease loss retains the existing Task-9 precedence and must not be changed.

Implement only the narrow model-neutral catch before the existing generic catch. The cleanup attempt remains lease-authorized, but loss of cleanup authority must not replace the typed dependency failure:

```python
except ProcessingDependencyError:
    try:
        self._cleanup_best_effort(lease_guard)
    except LeaseLostError:
        pass  # stale cleanup is forbidden; preserve the runtime-health signal
    raise
```

Apply the same invariant to any `VideoProcessor` exception region in which a future `ProcessingDependencyError` could otherwise fall into the generic catch. Do not import backend-specific exception classes into `process_video.py`. Do not change generic decode, integrity, lease, or pipeline error semantics.

This distinction is intentional: `ProductionVisionProcessor` may notify the local supervisor of the typed error, while `WorkerRunner` later re-checks lease ownership before any authoritative terminal API call.

- [x] **Step 1: RED — lock construction order, fresh attempt state, and runtime replacement compatibility**

Use recording fakes for `RTMDetDetector`, `ByteTrackTracker`, `staging_factory` and `VideoProcessor`. Assert the exact order:

```text
lease_guard.check_owned()
runtime_provider()                 # exactly once
RTMDetDetector(runtime_snapshot, profile)
ByteTrackTracker(profile.tracker)
staging_factory(job_id, attempt_count)
VideoProcessor(detector, tracker, store)
VideoProcessor.process(...)
```

Required assertions:
- a pre-lost guard raises `LeaseLostError` before the provider or any constructor/factory is called;
- the provider is called exactly once for each accepted attempt;
- two normal attempts can receive the same runtime object without `warmup()` or `close()` being called;
- detector/tracker/store/`VideoProcessor` instances are fresh for every attempt;
- attempt 2 cannot reuse attempt-1 fake tracker state or MAVI-ID counter state;
- `staging_factory` receives the exact `(job_id, attempt_count)` pair;
- source path, expected size/hash and the exact same `LeaseGuard` are delegated unchanged;
- the exact `VisionProcessingResult` object from `VideoProcessor` is returned unchanged;
- if the provider changes from runtime A to runtime B between attempts, the next fresh detector adapter receives runtime B; this is mandatory proof that Task-11 recovery cannot leave the facade pinned to a disposed runtime;
- detector-construction failure prevents tracker/staging/`VideoProcessor` construction;
- tracker-construction failure prevents staging/`VideoProcessor` construction;
- staging-factory failure prevents `VideoProcessor` construction.

Keep the production API free of test-only constructor hooks; monkeypatch module-level adapter/processor symbols in the unit test.

- [x] **Step 2: Write exact failure-notification tests**

Cover both construction-time and processing-time typed failures:
- `RTMDetDetector` / runtime inference `GpuOutOfMemoryError` -> sink called exactly once with the exact RECOVER error, then the same error rethrows;
- ByteTrack construction/update `TrackerError` -> sink called exactly once with the exact CONTINUE error, then the same error rethrows;
- inference-contract failure -> sink receives the exact RECOVER error once;
- `LeaseLostError`, `SourceIntegrityError`, ordinary `VideoProcessingError`, and staging/configuration failures do **not** notify the runtime-failure sink;
- a real typed runtime/tracker failure is still reported once to the **local** sink even if lease ownership is lost while the attempt is unwinding; Task 10/`WorkerRunner` later suppresses stale `/fail`;
- a pre-lost lease performs no work and therefore emits no sink notification;
- one failure produces one sink call only; no adapter/layer reports the same error twice.

The sink is a local health-notification boundary only. Task 9 does not recover/rebuild the detector and does not call the control-plane failure API. Do **not** add a lease check immediately before `runtime_failure_sink(exc)`, because doing so would erase runtime-health information that the supervisor needs independently of job ownership.

- [x] **Step 3: Implement minimal deterministic attempt composition**

Implementation shape:

```python
def process(...):
    lease_guard.check_owned()

    try:
        runtime = self._runtime_provider()  # one snapshot for this attempt
        detector = RTMDetDetector(runtime, self._profile)
        tracker = ByteTrackTracker(self._profile.tracker)
        store = self._staging_factory(job_id, attempt_count)
        processor = VideoProcessor(detector, tracker, store)
        return processor.process(
            job_id=job_id,
            attempt_count=attempt_count,
            source_path=source_path,
            expected_source_size_bytes=expected_source_size_bytes,
            expected_source_sha256=expected_source_sha256,
            lease_guard=lease_guard,
        )
    except ProcessingDependencyError as exc:
        self._runtime_failure_sink(exc)
        raise
```

The facade must not cache the provider result beyond the call, call the provider twice, inspect `RuntimeDisposition`, catch generic exceptions, perform async work, rebuild/close the runtime, or create staging outside the supplied factory. Document the sink callback contract in the class docstring.

- [x] **Step 4: Add import-boundary and lightweight composition regressions**

Add tests proving:
- importing `mavi_vision.pipeline.production_processor` does not load `torch`, `mmdet`, `mmcv`, `trackers` or `supervision`;
- real `VideoProcessor` can sit under the facade with fake attempt adapters without changing attempt scoping;
- attempt 1 and attempt 2 use distinct staging namespaces;
- fresh fake tracker state restarts per attempt while the runtime provider remains shared.

These tests must run in the ordinary MAVI Quality Gate without optional ML packages.

- [x] **Step 5: Add an exact-package Linux/Windows production-composition smoke**

Create `test_production_processor_runtime.py`, gated by `MAVI_RUN_QUALIFIED_PRODUCTION_PROCESSOR_TESTS=1`. In qualified mode it must fail, not skip, if exact packages are missing or drifted.

Use a tiny locally generated MP4, a framework-neutral fake `DetectorRuntime` that emits deterministic Person raw detections, and the **real** `RTMDetDetector`, exact-package `ByteTrackTracker`, `StagingArtifactStore`, `VideoProcessor`, and `ProductionVisionProcessor`.

Run attempt 1 and attempt 2 through the same runtime provider and prove:
1. both process successfully;
2. the same runtime is shared during normal operation;
3. each fresh tracker restarts deterministic MAVI IDs at `person-000001`;
4. artifacts are isolated under `attempt-0001` and `attempt-0002`;
5. no cross-attempt artifact leakage occurs;
6. the facade never warms, closes or reconstructs the runtime;
7. installed `trackers==2.6.0` and `supervision==0.30.2` are verified explicitly.

Extend `.github/workflows/task10-runtime-qualification.yml` to trigger on `src/vision/mavi_vision/pipeline/**`, `src/vision/tests/test_production_processor*.py`, and `src/vision/tests/test_process_video.py`, then run this qualified smoke on both Linux and Windows after the exact candidate graph is installed. The smoke uses no model checkpoint and introduces no new production network dependency.

- [x] **Step 6: Run complete Task-9 regression and repository verification**

Focused:

```powershell
cd src/vision
python -m pytest tests/test_production_processor.py tests/test_process_video.py tests/test_bytetrack_adapter.py tests/test_rtmdet_mapping.py -q
```

Then full Python/repository verification:

```powershell
python -m pytest -q
cd ../..
python tools/verify_repo.py
```

Hosted exact-head acceptance:
- MAVI Quality Gate green;
- Task 10 Runtime Qualification green on Linux and Windows including the new production-composition smoke;
- Task 10 Staging Security green if triggered by the changed paths;
- clean substantive Codex review with all legitimate findings resolved.

**Task-9 implementation evidence (exact implementation head `0b34640c5453979f1d4833eff3659cc09dfe7056`):**

- TDD RED — typed dependency preservation: MAVI Quality Gate #276 / run `34696676008` failed exactly the three new regressions (`3 failed, 499 passed, 12 skipped`), proving OOM/tracker collapse and lease-loss replacement before the fix.
- Typed-error GREEN: MAVI Quality Gate #278 / run `34696894884`: PASS.
- TDD RED — production composition: MAVI Quality Gate #279 / run `34697065369` failed the deliberate `ProductionVisionProcessor` stub contract (`16 failed, 503 passed, 12 skipped`) without unrelated regressions.
- Facade GREEN: MAVI Quality Gate #281 / run `34697296761`: PASS.
- Exact implementation-head repository gate: MAVI Quality Gate #283 / run `34697544693`: PASS.
- Exact implementation-head Task 10 Runtime Qualification #123 / run `34697544697`: PASS on both hosted CPU platforms.
  - Ubuntu job `103563506515`: PASS; artifact `10299183348`; SHA-256 `25a600c30961a4d2b32e1ca3f84a7079042d905b05b647bdfc995171a47f1407`.
  - Windows job `103563506652`: PASS; artifact `10299178503`; SHA-256 `e963426cd1d59fce2107dff4ae2b90a770b54a7636d926fe73ff7be895b472d4`.
- Both runtime jobs passed the expanded no-heavy-import boundary suite, exact `trackers==2.6.0` / `supervision==0.30.2`, exact production attempt-composition qualification, real RTMDet-M CPU probe/runtime smoke, and final qualification-evidence verification.
- The topic branch is `8` commits ahead / `0` behind the Task-10 integration branch at this evidence point; merge base is exactly `9f229234699d13aa6093eb9dd7438a60a1557a86`.
- No Task-9 code changes claim completion of CUDA/NVIDIA, offline wheelhouse, CCTV-quality, watchdog or recovery-performance gates; those remain explicitly pending under later Task-10 work.

**Final closure rule:** Step 7 may be marked complete only after the documentation closure head itself passes all triggered exact-head gates, receives a clean substantive Codex review with all legitimate findings resolved, is squash-merged into `feature/task-10-rtmdet-bytetrack` with expected-head protection, and the resulting integration SHA is verified.
- [x] **Step 7: Commit, close evidence, merge and cleanup**

Recommended reviewable commits before squash:

```text
feat: preserve vision dependency failures
feat: compose production vision attempts
ci: qualify production attempt composition
docs: close Task 9 attempt composition
```

Use topic branch `feature/task-10-attempt-composition`, created only from the accepted Task-10 integration head. At closure record RED evidence, exact hosted run/job/artifact identities, keep CUDA/offline/CCTV/recovery gates pending, squash-merge only into `feature/task-10-rtmdet-bytetrack` with expected-head protection, verify the integration SHA, then perform guarded merged-branch cleanup.
**Final Task-9 closure:**

- Final merge-candidate head: `fec5965a53f9f8c1a4cf5bd1b75f4916cdbf4a72`.
- Final MAVI Quality Gate #284 / run `34698377442`: PASS.
- Final Task 10 Staging Security #59 / run `34698377465`: PASS on Ubuntu and Windows.
- Final Task 10 Runtime Qualification #124 / run `34698377460`: PASS.
  - Ubuntu job `103565685192`: PASS; artifact `10300000200`; SHA-256 `270455c7a1887ab5867563f53231b21573ff76c6ec478c0c13111c809c59d282`.
  - Windows job `103565685054`: PASS; artifact `10300035296`; SHA-256 `2e5b8c0c8763b43c53fd1211480884751c3f3b70bc3baaead9c3a5452ff67d9c`.
- Final Codex review on `fec5965a53`: no major issues.
- PR #25 squash-merged with expected-head protection.
- Squash merge SHA: `e63c1b3c14ae0f16b1ea44b55a0f9527281bd9d0`.
- Integration branch advanced exactly to that SHA and the squash commit tree `1f1dcca8fa96c3d2d0173ddf1321dec766001ea7` exactly matches the final topic-head tree.
- The topic branch contains no unique code after the squash merge. Repository setting `delete_branch_on_merge=false`; branch deletion is housekeeping only and is not a Task-9 correctness blocker.
**Reviewer gate — reject Task 9 if any of the following is true:**
- a concrete runtime object is permanently captured such that a post-recovery attempt can use a disposed runtime;
- `runtime_provider` is called more than once in one attempt;
- tracker/MAVI-ID/staging state crosses attempts;
- a typed dependency failure is swallowed or converted before the local supervisor can classify it;
- lease loss permits stale cleanup, publication or terminal control-plane mutation;
- `ProductionVisionProcessor` performs readiness decisions, recovery, heartbeat/API work, persistence or generic exception normalization;
- the sink can block on async/network work from the vision lane;
- exact-package Linux/Windows composition is not exercised;
- optional heavy packages become required merely to import the core pipeline.

---

### Task 10: Map Typed Runtime/Tracker Failures Through Task-9 Lease Semantics

**Status (2026-09-12): COMPLETE — SQUASH-MERGED INTO TASK-10 INTEGRATION.** Task 10 is intentionally narrow. Task 9 already preserves model-neutral `ProcessingDependencyError` values and reports local runtime health. This task adds only worker-side allowlisted control-plane mapping while preserving the runner's existing lease-precedence boundary. Runtime disposition/recovery remains Task 11.

**Planning corrections locked by this review:**

1. **Do not branch on backend classes or `RuntimeDisposition` in `WorkerRunner`.** The runner may import only the model-neutral `ProcessingDependencyError`. Recovery/readiness decisions remain entirely outside the runner.
2. **Use an explicit immutable allowlist of the four approved leased-job failure codes.** `ProcessingDependencyError` validates syntax, not membership, so a future/custom typed code must not pass through automatically.
3. **Use one generic sanitized control-plane message for all dependency failures.** The stable failure code carries machine meaning; `str(exc)`, stack traces, local paths, device details and environment data must never be sent to `/fail`.
4. **Unknown typed codes fail closed to `vision_processing_failed`.** They are a local programming/configuration defect, not a new wire contract. Log only sanitized metadata needed to diagnose the defect; do not leak the exception message into the terminal request.
5. **Prove lease precedence in the worker heartbeat tests, not only the pipeline ownership matrix.** The critical boundary is `_process_with_lease_heartbeats()`: it checks ownership before accepting either a result or a processing exception. A typed failure completing after expiry, or while heartbeat ownership is lost, must therefore produce no `/fail`.
6. **Do not refactor lease lifecycle, processor dispatch, execution lanes, watchdogs, or supervisor state in Task 10.** Those changes belong to Task 11. This task must preserve the already-qualified Task-9 runner behavior and add the smallest possible typed mapping seam.

**Files:**
- Modify: `src/vision/mavi_vision/worker/runner.py`
- Modify: `src/vision/tests/test_worker_runner.py`
- Modify: `src/vision/tests/test_worker_lease_heartbeat.py`
- Regress: `src/vision/tests/test_lease_ownership_matrix.py`
- Regress: `src/vision/tests/test_process_video.py`
- Regress: `src/vision/tests/test_artifact_publisher.py`
- Regress: `src/vision/tests/test_artifact_store.py`
- Do **not** modify: `runtime/errors.py`, `pipeline/production_processor.py`, runtime supervisor/execution-lane code, worker health schema, or worker API wire models unless a real failing test proves an independently reviewable defect.

**Interfaces and stable codes:**

`VideoProcessor` already rethrows the exact `ProcessingDependencyError` after lease-authorized cleanup. `ProductionVisionProcessor` already reports the same error once to the local runtime-health sink. `WorkerRunner` therefore performs only the terminal job mapping after `_process_with_lease_heartbeats()` has accepted the exception under current ownership.

Approved leased-job codes:

```python
_APPROVED_PROCESSING_DEPENDENCY_CODES: Final[frozenset[str]] = frozenset({
    "vision_inference_contract_failed",
    "vision_gpu_out_of_memory",
    "vision_gpu_runtime_failed",
    "vision_tracker_failed",
})
```

Control-plane message for both approved and normalized-unknown dependency failures:

```text
Vision processing failed.
```

Unknown syntactically valid `ProcessingDependencyError.failure_code` values normalize to:

```text
vision_processing_failed
```

The runner must not use `error.runtime_disposition` to decide recovery, leasing, restart, or readiness. Task 11's supervisor owns those decisions through the already-established local failure sink.

- [x] **Step 1: RED — lock the four approved stable-code mappings**

In `test_worker_runner.py`, parameterize the concrete model-neutral failures:
- `InferenceContractError` -> `vision_inference_contract_failed`;
- `GpuOutOfMemoryError` -> `vision_gpu_out_of_memory`;
- `GpuRuntimeError` -> `vision_gpu_runtime_failed`;
- `TrackerError` -> `vision_tracker_failed`.

For each case prove:
- the processor is called exactly once;
- the initial heartbeat succeeds before processing;
- `/fail` is called exactly once with the approved code;
- the message is exactly `"Vision processing failed."`;
- a deliberately sensitive exception message is absent from the terminal request;
- no generic `worker_unhandled_error` or trailing `task9_result_submission_not_implemented` request is emitted;
- `run_once()` returns `True` when the terminal fail succeeds.

This RED test should fail against the current runner because typed dependency failures presently fall into the generic exception path.

- [x] **Step 2: RED — lock fail-closed handling for unknown typed codes**

Construct a base `ProcessingDependencyError` using a syntactically valid but unapproved code such as `vision_future_dependency_failed`.

Prove:
- the arbitrary code is **not** sent to the API;
- the API receives exactly one `vision_processing_failed`;
- the message remains exactly `"Vision processing failed."`;
- the exception's message/text is absent from the API request;
- a local log record identifies an unallowlisted typed dependency code using sanitized metadata only;
- no second terminal request follows.

Do not weaken `ProcessingDependencyError` itself into a global enum in this task. Its broader syntax-valid contract is useful for fail-closed forward compatibility; the wire allowlist belongs at the worker boundary.

- [x] **Step 3: RED — prove typed-failure lease precedence at the real worker boundary**

Extend `test_worker_lease_heartbeat.py` with deterministic race regressions based on its existing event-loop-stall/heartbeat-loss fixtures.

Required cases:

1. **Typed failure completes after authoritative expiry.** The processor raises a real `GpuOutOfMemoryError` after the short deadline while the event loop is deliberately stalled. When the loop resumes, `_process_with_lease_heartbeats()` must raise lease loss before accepting the typed exception. Assert zero `/fail` calls.
2. **Heartbeat ownership is lost while processing unwinds with a typed error.** The API loses the lease on renewal; the shared guard is marked lost; the processing thread then raises a typed dependency error. The heartbeat/ownership failure remains authoritative and the API receives no terminal `/fail`.
3. Preserve the existing ordinary-error expiry regression unchanged to prove typed handling did not special-case around the general lease rule.

Do not invent a new cancellation or terminal-authorization abstraction in Task 10. These tests validate the established ownership boundary that Task 11 will later reuse.

- [x] **Step 4: Implement the minimal allowlisted worker mapping**

In `runner.py`:
- import `logging`, `Final`, and model-neutral `ProcessingDependencyError`;
- define the immutable four-code allowlist and one generic message constant at module scope;
- add an `except ProcessingDependencyError as exc` branch **before** the generic exception branch;
- choose `exc.failure_code` only when it is in the allowlist;
- otherwise normalize to `vision_processing_failed` and emit a sanitized local defect log;
- call `_best_effort_fail(...)` exactly once;
- return `True` after a successful fail;
- let `WorkerApiError` from the fail propagate exactly as existing terminal failures do.

Implementation must not:
- inspect CUDA/MMDetection/Trackers exception classes;
- branch on `RuntimeDisposition`;
- call the runtime-health sink again;
- perform recovery/readiness changes;
- reuse arbitrary `str(exc)` as the API message;
- catch `WorkerApiError` and attempt a second `/fail`.

- [x] **Step 5: GREEN — add terminal-fail transport regression for the new branch**

Using the existing `FailingTerminalWorkerApiClient`, prove a typed dependency failure whose `/fail` request itself raises `WorkerApiError`:
- results in one and only one fail attempt;
- propagates `WorkerApiError` for polling/backoff behavior;
- never falls through to `worker_unhandled_error`;
- never emits a second terminal request.

This prevents a common error where a newly added catch branch is accidentally re-caught by the generic handler.

- [x] **Step 6: Run the focused Task-10 regression set**

```powershell
cd src/vision
python -m pytest tests/test_worker_runner.py tests/test_worker_lease_heartbeat.py tests/test_process_video.py tests/test_lease_ownership_matrix.py tests/test_artifact_publisher.py tests/test_artifact_store.py -q
```

Acceptance:
- all new stable-code, sanitization, unknown-code and lease-race tests pass;
- all existing Task-9 source-integrity, heartbeat, lease-loss and artifact mutation invariants remain green.

- [x] **Step 7: Run full Python/repository verification**

```powershell
cd src/vision
python -m pytest -q
cd ../..
python tools/verify_repo.py
```

No optional heavy-runtime import may become necessary merely to collect or execute the runner tests.

**Task-10 implementation evidence:**

- Accepted planning baseline: `2b0f6a85411789b0531e67280816bc7e865f2162`; pre-implementation Task 10 Runtime Qualification #127 passed on Ubuntu and Windows and Staging Security #62 passed.
- RED contract commit: `e595853ee41ecb167630932ac04524cd7be9cc6b`.
- MAVI Quality Gate #285 / run `34700824266`: intentional RED — `6 failed, 521 passed, 13 skipped`.
  - The six failures were exactly the four approved stable-code mappings, unapproved-code fail-closed normalization, and single-terminal-action mapping assertion.
  - The new typed lease-expiry and heartbeat-loss precedence tests already passed in RED, proving the existing ownership boundary remained authoritative.
- Minimal production mapping commit: `0af760adcd26dcd71732e21d79f0b6108589582c`.
- MAVI Quality Gate #286 / run `34700989721`: PASS.
- Full Python contract result on #286: `527 passed, 13 skipped`; repository verification, .NET tests/build, frontend tests/typecheck/build all passed.
- Implementation diff is exactly 2 commits ahead / 0 behind the planning baseline and changes only `worker/runner.py`, `test_worker_runner.py`, and `test_worker_lease_heartbeat.py` before closure documentation.
- Production runner imports only model-neutral `ProcessingDependencyError`; it does not inspect backend-specific failures or `RuntimeDisposition`, does not perform recovery/readiness work, and never forwards exception text as a terminal message.
- Final merge-candidate head: `aa04cdd04e53122e88342f7c9823c2864a3bf41e`.
- MAVI Quality Gate #287 / run `34701380065`: PASS; Python contracts `527 passed, 13 skipped`.
- Task 10 Staging Security #63 / run `34701379969`: PASS on Ubuntu job `103573643249` and Windows job `103573643363`.
- Task 10 Runtime Qualification #128 / run `34701380037`: PASS on Ubuntu job `103573643400` and Windows job `103573643514`.
  - Ubuntu artifact `10299614701`, digest `sha256:f129e23f8b2abf60d2abba66c15b1a0584cf7f60ba7641a5178765fcf5ccbef4`.
  - Windows artifact `10299844761`, digest `sha256:836755209c572e72e3e85ce546b7a482087a5b5d58a1c17f8a72ffcb5a9c7bf3`.
- Final Codex review on `aa04cdd04e`: **no major issues**; no unresolved review threads.
- PR #26 was guarded squash-merged into `feature/task-10-rtmdet-bytetrack` with expected-head protection.
- Squash merge commit: `95e2e0189b082daa15209c2b6748dd298b89956f`.
- Merge parent is exactly the accepted planning baseline `2b0f6a85411789b0531e67280816bc7e865f2162`.
- Squash tree `6e91c212e421af13fcb8934c9131fca1d11fda6e` is exactly identical to the final topic-head tree, proving no code/evidence drift during merge.
- The merged topic branch has no unique repository content after squash. Repository auto-delete is disabled and the connected GitHub interface exposes no delete-ref/delete-branch operation, so branch deletion remains non-code housekeeping only.
- [x] **Step 8: Hosted exact-head acceptance and review**

Use a dedicated topic branch created from the accepted planning head, recommended name:

```text
feature/task-10-failure-classification
```

Require before merge:
- MAVI Quality Gate green on the exact PR head;
- Task 10 Runtime Qualification and Task 10 Staging Security green if triggered by changed/closure-documentation paths;
- clean substantive Codex review focused on allowlist correctness, message sanitization, lease precedence, single terminal action, and Task-11 scope separation;
- zero unresolved legitimate review threads.

Recommended reviewable implementation commits:

```text
test: lock vision dependency failure mapping
feat: map vision runtime failure classification
docs: close Task 10 failure mapping
```

- [x] **Step 9: Guarded merge, verification, and cleanup**

Squash-merge only into `feature/task-10-rtmdet-bytetrack` with expected-head protection. Verify:
- integration head equals the returned squash SHA;
- squash tree equals final topic-head tree;
- Task-10 closure evidence is recorded;
- no Task-11 supervisor/watchdog/executor code entered this task;
- merged topic branch has no unique code before deletion/housekeeping.

**Reviewer gate — reject Task 10 if any of the following is true:**
- `WorkerRunner` imports or branches on backend-specific failure classes;
- arbitrary `ProcessingDependencyError.failure_code` values can reach `/fail`;
- exception text/local paths/device details are sent as the terminal failure message;
- a typed error can emit more than one terminal request;
- lease expiry/loss can be known before exception acceptance yet the runner still submits `/fail`;
- runner code starts recovery, changes readiness, interprets `RuntimeDisposition`, or otherwise consumes Task-11 responsibilities;
- existing source-integrity/video-processing/generic failure semantics change without an explicit failing regression;
- Task-9 artifact cleanup/publication or attempt-isolation tests regress.

---
### Task 11: Runtime Supervisor, Recovery, Watchdog, and Production Worker Composition

**Status (reviewed 2026-09-12): READY FOR IMPLEMENTATION after the hardening below.**

**Accepted planning baseline:** `a160c0a9820a07e43baf20bdf4e2c548c59b1255` before this Task-11 planning revision.

Task 11 is the first point where process-scoped runtime lifecycle, asyncio lease authority, the dedicated vision thread, recovery, watchdog containment, worker health, and real production composition meet. It must therefore be implemented as one controlled feature branch with explicit TDD checkpoints rather than as a broad refactor.

#### Current-state findings that this plan locks

1. `runtime/supervisor.py` does not yet exist.
2. `VisionExecutionLane` is already qualified and must be reused unchanged unless a failing Task-11 regression proves a defect. It serializes accepted synchronous work on one dedicated thread and deliberately does not cancel already-running native work.
3. `InferenceActivity` already provides the required thread-safe monotonic inference start/completion marker. Task 11 consumes it; it does not redesign detector inference accounting.
4. `ProductionVisionProcessor` already has the correct recovery seams: one runtime-provider snapshot per accepted attempt and one synchronous local `ProcessingDependencyError` sink. A regression already proves a long-lived facade can see runtime A and then runtime B.
5. `WorkerRunner` still dispatches with `asyncio.to_thread`. Task 11 must inject `ProcessExecutor` without changing lease/heartbeat ownership semantics.
6. The current runner's generic exception cleanup waits for an unfinished processing task without a timeout. A watchdog implementation that merely raises would therefore deadlock instead of honoring bounded grace. The watchdog path requires an explicit non-blocking fatal-cleanup branch.
7. `worker-health-v2` currently always reports `ready`; Task 11 must make that impossible when the runtime is not READY without changing the v2 schema.
8. `worker/main.py` currently constructs no runtime, supervisor, production processor, staging factory, or readiness-gated loop.
9. The checked-in release remains intentionally incomplete: manifest `verificationStatus = unverified`, runtime profile `qualificationStatus = partial`, CUDA qualification is pending, and offline locks are pending. Task 11 must not promote this release. Production mode must fail closed before leasing; development mode may explicitly run the integrity-checked unverified CPU candidate.
10. Runtime provenance is already implemented, but the existing Task-11 plan did not wire it into supervisor readiness. Task 11 must publish READY only after provenance construction succeeds.
11. `WorkerSettings` currently lacks an explicit qualification-record path and production build/commit identity needed by the verifier/provenance path.
12. CUDA `GpuIdentity` capture is not yet implemented. Task 11 must keep a fail-closed injectable GPU-identity seam; it must not invent or fake CUDA provenance while Task-1 hardware qualification remains open.

#### Scope and non-goals

Task 11 shall implement:
- process-scoped `RuntimeSupervisor` state and runtime ownership;
- immutable release verification before model construction;
- runtime construction/warm-up/validation on the existing `VisionExecutionLane`;
- immutable runtime provenance before READY;
- thread-safe processing-failure handoff from the lane to the event-loop lifecycle;
- one bounded same-release/same-device recovery attempt per RECOVER incident;
- fail-closed UNAVAILABLE behavior for poisoned runtime failures;
- model-neutral `ProcessExecutor` injection into `WorkerRunner`;
- native-inference watchdog polling, lease invalidation, bounded grace and fatal termination;
- truthful health-v2 readiness gating;
- real production worker composition and readiness-gated outer loop.

Task 11 shall **not** implement:
- Task-11 result `/complete` persistence or PostgreSQL writes;
- Task-12 wheelhouse/offline-bundle completion;
- Task-14 GPU hardware qualification/performance claims;
- a new worker-health schema;
- automatic production CUDA-to-CPU fallback;
- runtime/profile/model hot reload;
- more than one concurrent leased video;
- cancellation of native inference threads;
- changes to Task-9 artifact/lease authority semantics.

#### Files

- Create: `src/vision/mavi_vision/runtime/supervisor.py`
- Modify: `src/vision/mavi_vision/common/settings.py`
- Modify: `src/vision/mavi_vision/worker/runner.py`
- Modify: `src/vision/mavi_vision/worker/health.py`
- Modify: `src/vision/mavi_vision/worker/main.py`
- Create: `src/vision/tests/test_runtime_supervisor.py`
- Extend: `src/vision/tests/test_runtime_watchdog.py`
- Modify: `src/vision/tests/test_worker_runner.py`
- Modify: `src/vision/tests/test_worker_health.py`
- Modify: `src/vision/tests/test_worker_settings.py`
- Create or extend: `src/vision/tests/test_worker_main.py`
- Regress unchanged unless a test proves otherwise: `runtime/execution_lane.py`, `runtime/activity.py`, `pipeline/production_processor.py`, `pipeline/process_video.py`, staging backends, Task-10 failure mapping.

#### Locked supervisor contract

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

    @property
    def provenance(self) -> RuntimeProvenance | None: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    @property
    def restart_required(self) -> bool: ...

    async def start(self) -> None: ...
    def report_processing_failure(self, error: ProcessingDependencyError) -> None: ...
    def report_watchdog_expiry(self) -> None: ...
    def watchdog_expired(self) -> bool: ...
    async def recover_if_required(self) -> None: ...
    async def close(self) -> None: ...
```

Implementation ownership rules:

- lifecycle state transitions (`STARTING/READY/RECOVERING/UNAVAILABLE/STOPPING`) are event-loop-owned;
- `runtime_provider()` is called from the vision lane, so the current runtime reference is published/read under a small `threading.Lock`; it is a side-effect-free snapshot and raises a stable local error when no runtime is published;
- `report_processing_failure()` is invoked from the vision lane and must be synchronous, non-blocking and non-throwing. It records only a lock-protected pending disposition/incident; it does not destroy/rebuild the runtime and does not perform asyncio/network I/O;
- pending disposition severity is monotonic for the current incident: `UNAVAILABLE > RECOVER > CONTINUE`; repeated reports cannot downgrade it;
- `recover_if_required()` is the event-loop reconciliation point. It atomically consumes the pending incident **after the current attempt has unwound and before any next lease**;
- `CONTINUE` leaves the published detector runtime READY;
- `RECOVER` performs exactly one reconstruction attempt for that incident;
- `UNAVAILABLE` caused by a poisoned runtime sets `restart_required=True`, stops leasing, and must not attempt unsafe runtime reconstruction;
- watchdog expiry records an unavailable/restart-required incident independently of the leased job result.

#### Runtime publication and recovery rules

Startup sequence:

1. state is `STARTING`; no lease path is reachable;
2. invoke release verification before any model constructor;
3. resolve the configured device deterministically;
4. on the vision lane construct the runtime;
5. verify runtime metadata/model/vocabulary against the selected immutable release;
6. warm up on the lane;
7. build immutable runtime provenance;
8. only after every preceding step succeeds, atomically publish runtime + provenance and transition to `READY`.

Candidate runtime construction is transactional. If construction succeeds but warm-up/metadata/provenance fails, the candidate is never published and is closed best-effort on the lane when safe.

Recovery sequence for one RECOVER incident:

1. transition `READY -> RECOVERING`; no new lease;
2. atomically unpublish the old runtime so no new attempt can snapshot it;
3. close the old runtime on the vision lane;
4. reconstruct using the **same stored release selection and same resolved device**; do not reread analytical config and do not change model/profile/device;
5. repeat metadata validation, warm-up and provenance construction;
6. publish the replacement atomically and transition to READY;
7. if any recovery step fails, transition to UNAVAILABLE; do not automatically attempt a second reconstruction for that incident.

A later, separately observed RECOVER incident after a successful recovery may receive its own single reconstruction attempt.

For `RuntimeDisposition.UNAVAILABLE`, do not perform same-process reconstruction. If the runtime may be poisoned, do not invoke CUDA cleanup merely for tidiness; process restart is the containment boundary.

#### Device and release-selection policy

- `cpu` resolves to `cpu`.
- `cuda` resolves to `cuda:{device_index}` and never falls back to CPU.
- production `auto` remains invalid in `WorkerSettings` and is rejected again defensively by supervisor composition.
- development `auto` in the Task-11 baseline resolves deterministically to CPU with an explicit warning. Do **not** implement fragile fallback by parsing `RuntimeCompatibilityError` text. A later qualified development preference for CUDA can be introduced separately.
- add `qualification_record_path` to `WorkerSettings` (defaulting to the current local qualification record) so release evidence selection is explicit rather than inferred from filenames;
- add optional deployment build/commit identity settings used by `build_runtime_provenance`; development may retain the existing `unknown-development` provenance behavior, while production must fail closed if required identity is absent;
- production calls `verify_release_selection(..., allow_unverified=False)` and therefore the current checked-in unverified/partial release correctly remains non-ready;
- development calls the same verifier with explicit `allow_unverified=True`; hashes/containment/runtime relationships are still verified and provenance remains `unverified`.

CUDA provenance must receive a real `GpuIdentity` from an injected provider. Until that provider is backed by qualified hardware evidence, a CUDA production runtime cannot become READY. Task 11 must not manufacture placeholder GPU identity.

#### WorkerRunner executor contract

Add a small default model-neutral executor implementing `ProcessExecutor` via the existing `asyncio.to_thread` behavior for Task-9-compatible tests/development.

`WorkerRunner.__init__` adds:

```python
process_executor: ProcessExecutor | None = None
watchdog_expired: Callable[[], bool] | None = None
watchdog_expiry_sink: Callable[[], None] | None = None
watchdog_grace_seconds: float = 10.0
watchdog_poll_seconds: float = 1.0
fatal_terminator: Callable[[int], NoReturn] = os._exit
```

The runner always submits processing through `self._process_executor.run(...)`; production passes the shared `VisionExecutionLane`. It still owns the lease guard, heartbeat schedule, source resolution and terminal API interaction.

#### Watchdog algorithm — do not implement as a simple exception

The watchdog must not reset the heartbeat timer on every poll. Maintain an absolute monotonic `next_heartbeat_due` for scheduling only; the server UTC lease deadline remains authoritative for acceptance.

While a process task is active:

1. wait for `min(time_until_next_heartbeat, watchdog_poll_seconds)` when watchdog is configured;
2. if processing completes, retain the existing lease-ownership precedence checks before accepting success or exception;
3. if watchdog is not expired and the heartbeat due time has arrived, renew through the existing `_heartbeat_before_deadline()` path and calculate a new due time;
4. if watchdog expires, immediately mark the shared `LeaseGuard` lost, invoke the non-throwing watchdog-expiry sink, and stop all further heartbeats;
5. wait for the existing process task for at most `watchdog_grace_seconds` using a non-cancelling wait;
6. if the task unwinds inside grace, discard its result/error as non-authoritative and raise lease loss so `run_once()` emits no `/fail`; supervisor remains UNAVAILABLE/restart-required;
7. if the task is still running after grace, invoke `fatal_terminator(70)`;
8. set a local fatal-path flag before invoking the terminator so the runner's outer exception cleanup **must not** execute its ordinary unbounded `await process_task`; if an injected test terminator raises, that sentinel must escape promptly;
9. if a production terminator unexpectedly returns, raise a stable fatal error without awaiting the stuck task.

This is required because `VisionExecutionLane` deliberately shields native work from asyncio cancellation.

#### Health contract

`worker-health-v2` remains unchanged. `get_worker_health()` may return the existing `ready` payload only when the caller supplies/derives runtime READY. A non-ready call raises a local `WorkerHealthUnavailable` (or equivalently stable local exception) for the caller to map to transport/local diagnostics. Do not invent `starting`, `recovering`, or `unavailable` v2 payload values.

#### Production control-loop contract

`worker/main.py` must not use `runner.run_forever()` for the supervised production path. Keep `run_forever()` for backward-compatible tests/dev callers.

Production composition order:

1. load settings;
2. create the single `VisionExecutionLane` and transfer runtime-lifecycle ownership to the supervisor;
3. create `InferenceActivity`;
4. create release-loader/runtime-factory/provenance/GPU-identity seams;
5. construct and `await supervisor.start()`;
6. build the staging factory bound to `settings.media_root`;
7. build one long-lived `ProductionVisionProcessor(runtime_provider=lambda: supervisor.runtime, profile=<selected profile>, staging_factory=..., runtime_failure_sink=supervisor.report_processing_failure)`;
8. build `WorkerRunner(..., process_executor=lane, watchdog_expired=supervisor.watchdog_expired, watchdog_expiry_sink=supervisor.report_watchdog_expiry, ...)`;
9. enter the supervised outer loop.

Outer-loop ordering is mandatory:

```text
before any lease:
    await supervisor.recover_if_required()
    if READY -> runner.run_once()
    if RECOVERING -> recover_if_required(), no lease
    if UNAVAILABLE + restart_required -> exit with service-restart code
    if UNAVAILABLE + not restart_required -> remain alive for diagnostics, no lease

after every run_once outcome (success, leased-job failure, lease loss, API error):
    in finally -> await supervisor.recover_if_required()
```

The `finally` reconciliation is critical: an OOM may be reported locally even when lease loss or `/fail` transport failure causes `run_once()` to raise. Recovery must still occur before another lease.

Normal shutdown order:

1. stop admitting new work;
2. `await supervisor.close()` (idempotent; closes safe runtime lifecycle on the lane and transitions STOPPING);
3. close the worker API client;
4. ensure the lane is closed exactly once by its designated owner.

Do not double-own lane shutdown between `main.py` and the supervisor. The implementation must choose one owner and tests must assert one close path. Preferred Task-11 design: ownership is transferred to `RuntimeSupervisor`, which closes the lane after safe runtime teardown; `main.py` does not close it again.

---

- [ ] **Step 1: RED — lock supervisor startup and transactional publication**

Create `test_runtime_supervisor.py` with lightweight fake release/runtime/lane collaborators. Prove:
- initial state STARTING and no runtime is published;
- release verification occurs before runtime construction;
- successful construct + metadata validation + warm-up + provenance -> READY;
- `runtime` returns the exact published snapshot and `provenance` is immutable/current;
- hash/release verification failure, requested-device failure, vocabulary mismatch, warm-up failure, and provenance failure -> UNAVAILABLE with zero lease opportunity;
- a candidate that fails after construction is never published and is cleaned up once when safe;
- production `auto` is rejected defensively;
- current unverified release policy is explicit: development may load unverified, production may not.

- [ ] **Step 2: Implement supervisor startup on the existing VisionExecutionLane**

Keep heavy/model operations on the lane. Do not add top-level torch/MMDetection imports to supervisor, runner, health, or main. Store the immutable selected release and resolved device for later recovery. Publish runtime/provenance only after the complete startup transaction succeeds.

- [ ] **Step 3: RED/GREEN — lock the cross-thread incident handoff**

Prove `report_processing_failure()` is synchronous, thread-safe, non-blocking and non-throwing when called from a real background thread. Test severity coalescing (`CONTINUE < RECOVER < UNAVAILABLE`) and prove it performs no runtime close/rebuild itself.

Add a supervisor-specific regression using one long-lived `ProductionVisionProcessor`: attempt 1 snapshots runtime A; report RECOVER; reconcile/recover; attempt 2 snapshots runtime B without rebuilding the facade.

- [ ] **Step 4: RED/GREEN — bounded recovery and poisoned-runtime semantics**

Required cases:
- `TrackerError/CONTINUE` -> no reconstruction and READY remains;
- `GpuOutOfMemoryError/RECOVER` -> exactly one old-runtime close + exactly one same-release/same-device reconstruction/warm-up/provenance; success -> READY;
- recovery construction/warm-up/provenance failure -> UNAVAILABLE and no second automatic attempt;
- `GpuRuntimeError/UNAVAILABLE` -> no reconstruction, no next lease, `restart_required=True`;
- report received while STOPPING is ignored/non-throwing;
- two separate OOM incidents separated by a successful recovery may each receive one recovery.

- [ ] **Step 5: RED/GREEN — add settings and provenance wiring**

Extend settings tests for:
- explicit qualification-record path;
- optional build ID / commit SHA deployment identity;
- unchanged rejection of production `auto`;
- no analytical tuning knobs added.

Supervisor must build provenance before READY. CPU development provenance remains explicitly `unverified`; verified production fixtures require matching qualification/runtime-lock/build identity. CUDA provenance without a real GPU-identity provider fails closed.

- [ ] **Step 6: RED — lock ProcessExecutor injection before changing runner dispatch**

Add worker tests proving:
- default executor preserves existing Task-9 behavior;
- injected fake executor receives the processor callable/arguments exactly once;
- injected `VisionExecutionLane` executes processing on its dedicated single thread;
- heartbeat and `LeaseGuard` behavior remains on the asyncio side;
- all Task-10 typed failure mapping/lease precedence tests remain unchanged.

- [ ] **Step 7: Implement model-neutral executor dispatch**

Replace the direct `asyncio.to_thread(self._processor.process, ...)` call with `self._process_executor.run(...)` only. Do not move heartbeat logic into the executor and do not give the executor lease/control-plane authority.

- [ ] **Step 8: RED — lock watchdog scheduling and heartbeat coexistence**

Add deterministic clock/event-based tests proving:
- watchdog is polled at <=1 second while work is active;
- periodic watchdog polling does not postpone the next scheduled heartbeat;
- normal long processing continues to renew before the authoritative lease deadline;
- watchdog is never considered expired while `InferenceActivity` is inactive;
- a completed inference clears the watchdog condition.

- [ ] **Step 9: RED/GREEN — implement bounded watchdog containment**

Use a blocking processor and injected fake terminator. Prove:
- expiry marks the shared guard lost before any fatal action;
- no heartbeat occurs after expiry;
- no terminal `/fail` occurs after expiry;
- processing that unwinds inside grace is discarded and surfaces only lease loss/restart-required state;
- processing still stuck after grace calls the terminator exactly once with code 70;
- the injected terminator sentinel escapes within bounded test time and is not swallowed by the runner's ordinary cleanup;
- the runner never attempts Python thread cancellation or reuses the hung runtime.

- [ ] **Step 10: RED/GREEN — truthful worker-health-v2**

Update health tests so READY returns the exact existing v2 payload and every non-ready state is locally unavailable rather than serialized as a new status. No schema or contract fixture changes are permitted.

- [ ] **Step 11: RED — lock supervised production-loop ordering**

Create/extend `test_worker_main.py` with fake supervisor/runner/client/lane. Prove:
- startup never calls lease before supervisor READY;
- STARTING/RECOVERING/UNAVAILABLE never call `lease()`;
- reconciliation occurs in `finally` after `run_once()` success and after `WorkerApiError`; 
- an OOM pending incident is recovered before the next lease even when terminal `/fail` transport failed;
- restart-required UNAVAILABLE exits through the defined service-restart path;
- startup/configuration UNAVAILABLE remains alive for diagnostics without busy-looping;
- shutdown closes resources once in the locked order.

- [ ] **Step 12: Implement production composition in `worker/main.py`**

Wire only existing qualified boundaries. Do not introduce model-specific logic into `WorkerRunner`. Keep one process-scoped supervisor/lane/runtime and one attempt-scoped tracker/staging graph.

- [ ] **Step 13: Focused regression suite**

```powershell
cd src/vision
python -m pytest tests/test_runtime_supervisor.py tests/test_runtime_execution_lane.py tests/test_runtime_watchdog.py tests/test_runtime_provenance.py tests/test_production_processor.py tests/test_worker_runner.py tests/test_worker_lease_heartbeat.py tests/test_worker_health.py tests/test_worker_settings.py tests/test_worker_main.py tests/test_lease_ownership_matrix.py tests/test_process_video.py tests/test_artifact_publisher.py tests/test_artifact_store.py -q
```

Acceptance:
- no heavy ML import is required merely to collect the supervisor/runner/health/main unit tests;
- Task-9/10 lease authority and typed failure semantics remain green;
- watchdog tests are deterministic and do not rely on long wall-clock sleeps;
- no direct PostgreSQL path or `/complete` path appears.

- [ ] **Step 14: Full repository verification**

```powershell
cd src/vision
python -m pytest -q
cd ../..
python tools/verify_repo.py
```

- [ ] **Step 15: Hosted review workflow**

Use **one** Task-11 topic branch to avoid branch proliferation:

```text
feature/task-11-runtime-supervisor
```

Create it from the final accepted Task-11 planning head and open one draft PR early. Recommended reviewable checkpoints:

```text
test: lock runtime supervisor lifecycle
feat: supervise qualified vision runtime
test: lock worker watchdog containment
feat: dispatch worker on supervised vision lane
feat: compose supervised production worker
docs: close Task 11 runtime supervision
```

Require:
- intentional RED evidence before each behavioral implementation where practical;
- exact-head MAVI Quality Gate green;
- Task 10 Runtime Qualification and Staging Security green whenever triggered by touched/closure paths;
- substantive Codex review focused on state ownership, recovery count, watchdog deadlock avoidance, lease precedence, production readiness and shutdown ownership;
- zero unresolved legitimate review threads.

- [ ] **Step 16: Guarded squash merge and closure**

Squash-merge only into `feature/task-10-rtmdet-bytetrack` with expected-head protection. Verify exact squash/tree identity, update this plan with final evidence, and confirm no Task-12/14 qualification claim entered Task 11.

**Reviewer rejection gate — do not merge Task 11 if any of the following is true:**
- supervisor lifecycle state is mutated directly from the vision lane thread;
- a processing-failure sink performs network/async runtime lifecycle work;
- a RECOVER incident can trigger more than one reconstruction attempt;
- recovery changes release/model/profile/device;
- runtime is published before warm-up/provenance succeeds;
- watchdog polling can starve/postpone heartbeat scheduling;
- watchdog expiry enters the runner's ordinary unbounded `await process_task` cleanup;
- any heartbeat, `/fail`, artifact publication or mutation cleanup occurs after watchdog/lease authority loss;
- production `auto` or CUDA-to-CPU fallback is introduced;
- current unverified/partial release is presented as production READY/verified;
- CUDA provenance uses placeholder GPU identity;
- worker-health-v2 emits invented non-ready statuses;
- `WorkerRunner` learns MMDetection/CUDA/model-manifest details;
- lane shutdown has two owners or may be skipped/doubled;
- Task-11 persistence `/complete`, PostgreSQL writes, Task-12 wheelhouse or Task-14 hardware qualification scope leaks in.

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
Task 1A/1B  Hosted CPU runtime + resolved-config software gate -------┐
Task 2/2A   Cross-platform secure staging + corrective checkpoint ----┤
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
                                                             +--> Task 13 Hosted adapter CI
                                                                      |
                                                                      +-------------------┐
                                                                                          |
Task 1 GPU qualification ------------------------------┐                                  |
Task 1 hashed wheelhouse/release locks ----------------+--> Task 12 Offline bundle -------+--> Task 14 Real qualification
                                                                                                  |
                                                                                                  +--> Task 15 Closure
```

The completed hosted-CPU/config gate and cross-platform staging gate are sufficient to begin framework-neutral Tasks 3–11 and Task 13 after Task 2A is green. The still-open Task-1 hardware/release evidence is an explicit blocker for Task 12/14 and therefore for final Task-15 closure; it must never be converted into an inferred qualification.

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
