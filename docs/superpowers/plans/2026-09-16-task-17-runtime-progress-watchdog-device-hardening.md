# Task 17 Runtime Progress, Watchdog and Device-Qualification Hardening — 16 September 2026

**Status:** Authoritative implementation addendum for the active Task-17 acceptance work. Documentation only; implementation has not started from this document.

**Applies to:** `feature/task-10-rtmdet-bytetrack` and the future Task-17 implementation branch.

**Purpose:** Convert the live Windows acceptance findings from 16 September 2026 into a controlled engineering plan before further runtime qualification. This addendum does not promote any CUDA, performance, offline-install or production-verification claim.

---

## 1. Live acceptance finding

The current Windows development flow can successfully:

- install and verify the qualified Windows CPU runtime bundle;
- start the MAVI API and React application;
- start the vision worker;
- load the RTMDet-M checkpoint and resolved configuration;
- lease jobs and maintain lease heartbeats;
- enter the production processing pipeline.

The live run also exposed three important operational gaps:

1. the Processing UI remains at **5%** for the entire long-running inference attempt;
2. the worker can continue returning successful lease heartbeats while the native vision lane is making very slow or no useful forward progress;
3. the current development runtime is the qualified **`windows-x86_64-cpu`** variant, so an installed NVIDIA GPU is not used by this runtime.

A later watchdog termination with process exit code **70** is therefore not enough, by itself, to distinguish:

- one genuinely hung native inference call;
- a legitimate but extremely slow CPU inference call that exceeded the current watchdog threshold;
- a long-running job that is progressing frame-by-frame but cannot report that progress through the existing worker/control-plane seam.

The next acceptance work shall resolve this observability ambiguity before performance or CUDA conclusions are drawn.

---

## 2. Current code status

### 2.1 Control plane already supports changing progress

`ProcessingOrchestrator.HeartbeatAsync(... progressPercent ...)` already accepts and persists a worker-supplied progress percentage.

The control-plane storage model therefore does **not** need a redesign merely to display truthful processing progress.

### 2.2 Worker currently publishes a constant progress value

`src/vision/mavi_vision/worker/runner.py` currently:

- sends an initial heartbeat with `5.0`;
- renews the lease while processing;
- does not receive a progress source from `VisionProcessor`;
- consequently has no authoritative changing processing percentage to send on later heartbeats.

The current 5% UI is therefore expected from the implementation; it is not evidence that processing is frozen at exactly 5%.

### 2.3 VideoProcessor knows forward progress but does not publish it

`src/vision/mavi_vision/pipeline/process_video.py` increments `frames_processed` inside the decoded-frame loop and has access to every frame's media-relative `offset_ms`.

That is the correct layer to generate model-neutral forward-progress observations, but no callback/snapshot seam currently exposes them outside the synchronous processing lane.

### 2.4 InferenceActivity is a native-call watchdog marker, not job progress

`src/vision/mavi_vision/runtime/activity.py` records:

- whether one inference call is active;
- the monotonic start time of that inference call;
- a completed-inference count.

`MMDetectionRuntime.infer()` marks each individual inference start/completion.

This is intentionally useful for detecting a **single native inference call that does not return**. It is not a job-progress counter and must not be repurposed as one.

### 2.5 Current watchdog threshold is operational policy, not measured performance evidence

`WorkerSettings.inference_watchdog_seconds` currently defaults to **120 seconds**.

The live Windows CPU acceptance run shows that a fixed 120-second per-inference watchdog cannot yet be treated as a qualified performance threshold for full-resolution RTMDet-M CPU processing. No change to that value should be promoted as correct until per-frame inference timings are measured.

### 2.6 Current device selection is correctly CPU-only for the installed bundle

The current runtime metadata qualifies:

- `windows-x86_64-cpu`;
- `linux-x86_64-cpu`.

Both CUDA variants remain `pending-hardware-qualification`.

In development, `device_policy=auto` deliberately resolves to CPU. Therefore the present Windows runtime should show no material NVIDIA CUDA utilization. That is consistent with the code and metadata, not a GPU-selection bug.

### 2.7 Release truth remains unchanged

The current model/runtime selection is still a qualification candidate:

- model manifest remains unverified;
- runtime profile remains partial;
- Windows/Linux CUDA qualification remains pending;
- formal offline-install, CCTV quality and Linux NVIDIA recovery/performance gates remain pending.

This addendum must not be used to change those statuses.

---

## 3. Engineering principles for the correction

The implementation shall preserve these boundaries:

1. **Heartbeat liveness is not processing progress.**
2. **Native-call watchdog activity is not whole-job progress.**
3. **Progress reporting must not perform network I/O from the vision execution lane.**
4. **A slow CPU inference must not be classified as a hang merely because a guessed timeout is too small.**
5. **A genuinely stuck native call must still be containable by process-level termination.**
6. **CUDA must never be silently selected or silently used as a fallback.**
7. **Progress must remain monotonic for one attempt.**
8. **Lease ownership remains authoritative over all terminal mutations and artifact publication.**
9. **No new DB or API schema is introduced unless the existing `progressPercent` contract is proven insufficient.**
10. **Performance/device qualification is evidence-driven and variant-specific.**

---

## 4. Target architecture

### 4.1 Add an attempt-scoped thread-safe progress source

Create a model-neutral progress component, for example:

`mavi_vision.runtime.progress.ProcessingProgress`

with a small immutable snapshot such as:

```text
stage
frames_processed
source_offset_ms
source_duration_ms
progress_percent
last_progress_monotonic
```

Rules:

- writers run on the vision execution lane;
- readers run on the asyncio/control-plane thread;
- no network call is made from the writer;
- snapshots are lock-protected and cheap;
- progress for one attempt can only move forward;
- all values are attempt-local and reset for every leased attempt.

### 4.2 Derive progress from authoritative media time, not guessed FPS totals

The lease already carries source duration and the decoded frame carries media-relative `offset_ms`.

Prefer media-time progress:

`source_offset_ms / duration_ms`

over multiplying a nominal frame rate by duration.

This is robust for variable-frame-rate media and matches the existing Task-9 media timeline contract.

Reserve explicit phase ranges so that terminal completion remains authoritative. A proposed mapping is:

- lease/source validation: 0–5%;
- frame processing: 5–90%;
- deterministic finalization/artifact publication: 90–95%;
- accepted platform completion: 100%.

The exact constants shall be centralized and tested. A running worker must never claim 100%.

### 4.3 Thread the progress seam through composition without contaminating detector/tracker contracts

Recommended path:

```text
WorkerRunner
  -> creates attempt ProcessingProgress
  -> passes progress sink to ProductionVisionProcessor.process
      -> VideoProcessor.process
          -> updates after each successfully processed frame
          -> updates finalization stage
  -> heartbeat loop reads latest snapshot
  -> WorkerApiClient.heartbeat(progress_percent)
```

Do not add progress concepts to `Detector`, `Tracker`, `DetectorRuntime`, or persisted analytical result contracts.

### 4.4 Preserve separate inference-watchdog semantics

Keep `InferenceActivity` focused on one inference-bearing native call.

Extend its diagnostic snapshot only if required to record safe local facts such as:

- completed inference count;
- current inference start time;
- most recent completed inference duration;
- maximum observed inference duration;
- optional current source-frame number supplied outside the runtime.

Do not turn its timeout into a whole-video SLA.

### 4.5 Add explicit job forward-progress observation

The worker/event-loop side shall separately observe the progress snapshot.

This enables diagnosis of:

- **worker alive + job progressing**;
- **worker alive + one inference call active too long**;
- **worker alive + no frame-level progress, but not inside inference**;
- **control-plane/API failure while native work continues**.

A job-level no-progress policy may be introduced only after the state distinctions are covered by tests. It must not duplicate the native inference watchdog blindly.

### 4.6 Make watchdog termination diagnosable

Before fatal exit 70, emit a structured local diagnostic containing only safe operational data:

- stable failure code;
- worker ID;
- job ID;
- attempt number;
- processing stage;
- latest progress percent;
- frames processed;
- latest source offset;
- current inference elapsed time;
- watchdog threshold;
- device;
- runtime/model/profile identity hashes or IDs.

Do not log lease capabilities, private filesystem secrets or arbitrary exception payloads.

Where lease authority still exists, design a **bounded best-effort terminal failure report** using an allowlisted code such as `vision_inference_watchdog_expired` or `vision_processing_stalled`. The API call must have a strict timeout and fatal containment must not wait indefinitely for it.

If the lease has already expired or the fail request is rejected, preserve the current fail-closed process termination and allow normal lease recovery/retry semantics.

### 4.7 Make watchdog policy variant-aware only after measurement

Do not simply increase 120 seconds to an arbitrary larger number.

First collect measurements for:

- Windows CPU;
- Linux CPU;
- qualified CUDA variants when available.

For each variant record at minimum:

- warm-up latency;
- p50/p95/p99 per-frame inference latency;
- maximum observed per-frame inference latency;
- decoded FPS;
- inference FPS;
- end-to-end processing/source ratio;
- peak RAM;
- peak VRAM for CUDA.

Then freeze a watchdog policy with a documented safety margin. Runtime variant metadata or deployment configuration may carry the resulting threshold, but analytical profile semantics must remain unchanged.

---

## 5. GPU enablement plan

GPU support is a separate qualification workstream and must not be mixed into the progress fix.

### Phase G1 — local capability probe

Add/retain an explicit operator command that reports:

- NVIDIA driver visibility;
- PyTorch build CUDA identity;
- `torch.cuda.is_available()`;
- device count/name;
- compatible runtime variant availability.

It must not mutate release metadata.

### Phase G2 — Windows CUDA candidate bundle

Build a distinct:

`windows-x86_64-cuda`

runtime bundle only from exact pinned dependencies compatible with the intended NVIDIA/CUDA environment.

Never modify the existing CPU bundle to opportunistically use CUDA.

### Phase G3 — CUDA runtime qualification

Run the existing runtime qualification architecture against the exact candidate and hardware.

Required evidence includes:

- exact source commit;
- exact Python identity;
- Torch/Torchvision CUDA build identities;
- GPU model/driver identity;
- model/config/profile/runtime hashes;
- warm-up and real inference;
- OOM handling;
- watchdog/restart path;
- no silent CPU fallback.

### Phase G4 — Linux NVIDIA production qualification

The final production-worker gate remains Linux/NVIDIA as already defined by Task 17.

Windows CUDA may be a supported qualified variant, but it does not replace the final Linux NVIDIA production-topology acceptance requirement unless a later ADR changes that architecture.

---

## 6. Detailed implementation sequence

### Step 1 — Freeze and record the implementation baseline

Before code changes:

- capture the exact topic-head SHA;
- run current Python/.NET/frontend focused gates;
- retain the live reproduction evidence;
- do not regenerate runtime bundles merely because documentation changed.

### Step 2 — Add RED tests for truthful progress

Add focused tests proving:

- initial processing heartbeat remains below frame-processing range;
- progress increases as source offsets increase;
- repeated heartbeats without a new frame keep the same progress;
- progress never regresses;
- final running progress never reaches 100;
- VFR/media-offset progress is deterministic;
- zero/invalid duration fails to a safe fallback policy;
- attempt N progress cannot leak into attempt N+1.

Likely files:

- `src/vision/tests/test_worker_runner.py`;
- `src/vision/tests/test_process_video.py`;
- new `src/vision/tests/test_processing_progress.py`.

### Step 3 — Implement the thread-safe progress component

Create:

- `src/vision/mavi_vision/runtime/progress.py`.

Keep it independent of MMDetection, ByteTrack and HTTP.

### Step 4 — Extend model-neutral processor composition

Modify:

- `src/vision/mavi_vision/worker/runner.py`;
- `src/vision/mavi_vision/pipeline/production_processor.py`;
- `src/vision/mavi_vision/pipeline/process_video.py`.

Use an injected attempt-local progress sink/source.

Do not alter final `VisionProcessingResult.frames_processed` semantics.

### Step 5 — Replace constant 5% heartbeat behaviour

`WorkerRunner` shall read the latest attempt snapshot for every heartbeat.

The initial 5% may remain as the transition into frame processing, but subsequent heartbeats must be snapshot-driven.

Update tests that currently assert `[5.0]` for long-running processing.

### Step 6 — Add stage and timing diagnostics

Add safe structured logging around:

- source verification start/end;
- decode/frame loop;
- detector call start/end;
- tracker update;
- finalization;
- artifact publication;
- completion request.

Keep per-frame INFO logging off by default. Aggregate/periodic progress logs are preferred.

### Step 7 — Harden watchdog evidence

Add RED tests for:

- genuinely hung inference -> watchdog -> bounded fatal path;
- slow but completing inference below measured threshold -> no fatal path;
- progress continues across many frames -> no whole-job false stall;
- fail-report timeout does not block exit 70;
- expired lease cannot produce stale terminal mutation;
- watchdog diagnostics contain no capability/token/path secret.

### Step 8 — Add performance probe tooling

Create a non-production qualification tool under `tools/phase1/` that can process designated local media and emit machine-readable timing metrics without storing raw frames.

The tool must be explicitly separated from production runtime behavior.

### Step 9 — Measure the Windows CPU candidate

Run the 2-minute acceptance clip and at least one short controlled clip.

Record real:

- frame count;
- per-frame inference distribution;
- processing/source ratio;
- memory high-water mark.

Use these measurements to decide whether the current 120-second native-call threshold is valid for the CPU candidate.

### Step 10 — Freeze watchdog policy

Only after Step 9:

- retain 120s if evidence supports it; or
- change deployment/runtime policy to a measured threshold.

Any policy change gets focused tests and documentation.

### Step 11 — Re-run CPU acceptance before CUDA work

Required outcome:

- processing percentage moves truthfully;
- no unexplained UI plateau at 5%;
- no false watchdog kill on the controlled CPU clip;
- a deliberately injected hung call still terminates within the bounded watchdog envelope;
- result completion/search/evidence flow remains unchanged.

### Step 12 — Implement qualified CUDA candidate work separately

Only after CPU observability is trustworthy, execute the GPU phases in Section 5.

### Step 13 — Update runtime/release metadata only from evidence

Do not change:

- `verificationStatus`;
- CUDA variant status;
- CUDA lock status;
- mandatory qualification gate status;

until the corresponding exact evidence exists.

### Step 14 — Full regression

Run at least:

```text
Python full suite
repository verification
.NET build/tests
frontend test/typecheck/build
Task-10 runtime qualification
Task-12 offline bundle gates when runtime-affecting files changed
Task-17 deterministic acceptance checks
```

### Step 15 — Independent cold review

Review specifically for:

- cross-thread races in progress snapshots;
- progress/lease authority confusion;
- stale-attempt progress leakage;
- accidental network calls from the vision lane;
- watchdog false positives;
- loss of fatal containment;
- silent device fallback;
- release-metadata overclaim;
- UI interpreting liveness as progress.

Only after this pass should the implementation go to external review.

---

## 7. Acceptance criteria

This addendum is complete only when all applicable criteria are proven:

1. A real CPU processing run visibly advances beyond 5%.
2. Heartbeat renewal can continue even when the displayed percentage is unchanged, without implying false progress.
3. Progress is derived from actual frame/media advancement.
4. A single stuck native inference is still bounded by the watchdog.
5. A valid slow inference is not killed by an unqualified guessed threshold.
6. Exit 70 leaves a safe, actionable local diagnostic.
7. The control plane reaches a correct terminal state or safe retry path after watchdog containment.
8. No lease/token secret is logged.
9. CPU and CUDA runtime identities remain explicit and separate.
10. NVIDIA utilization is claimed only when a CUDA runtime variant is explicitly selected and qualified.
11. All existing Task-9 through Task-16 authority, evidence and offline invariants remain green.
12. Release metadata remains truthful throughout the process.

---

## 8. Files expected to change

Likely production/test files:

- `src/vision/mavi_vision/runtime/progress.py` — new;
- `src/vision/mavi_vision/worker/runner.py`;
- `src/vision/mavi_vision/pipeline/production_processor.py`;
- `src/vision/mavi_vision/pipeline/process_video.py`;
- `src/vision/mavi_vision/runtime/activity.py` — diagnostics only if required;
- `src/vision/mavi_vision/runtime/supervisor.py` — watchdog diagnostics/policy seam only if required;
- `src/vision/mavi_vision/common/settings.py` — only if measured policy needs explicit configuration;
- worker/progress/process/supervisor tests;
- Task-17 performance/qualification tooling.

Potential platform/UI files should change only if the existing progress percentage contract proves insufficient. The default plan is to avoid a schema/database migration.

---

## 9. Explicit non-goals for this correction

Do not:

- redesign Track persistence;
- change detector/tracker analytical thresholds merely to make CPU runs faster;
- introduce frame skipping silently;
- reduce source resolution silently;
- enable CUDA through `auto`;
- replace RTMDet-M;
- mark CUDA qualified from Task Manager screenshots;
- equate heartbeat success with inference progress;
- remove the fatal watchdog because CPU inference is slow;
- increase watchdog timeouts without measurements;
- regenerate large offline bundles unless runtime-affecting inputs actually changed.

---

## 10. Relationship to Task 17

This work is now a **pre-qualification hardening prerequisite** inside Task 17.

The correct order is:

```text
truthful progress + watchdog observability
        ->
CPU live acceptance and timing evidence
        ->
watchdog policy freeze
        ->
CUDA candidate construction/qualification
        ->
Linux NVIDIA recovery/performance evidence
        ->
formal offline/topology acceptance
        ->
release metadata promotion
```

This ordering prevents faster hardware from masking an observability or pipeline-control defect and prevents CPU slowness from being misclassified as a native hang.
