# Task 17 Runtime Progress, Watchdog and Device-Qualification Hardening — 16 September 2026

**Status:** Authoritative implementation addendum for the active Task-17 acceptance work. Documentation only; implementation has not started from this document. Cold independent review completed on 16 September 2026 and incorporated below; the architecture and implementation sequence in this revision are the implementation baseline.

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

### 2.7 Checkpoint/config warning requires explicit closure

The live runtime currently emits an MMDetection load warning that the model and loaded state dict do not match exactly, including unexpected `data_preprocessor.mean` and `data_preprocessor.std` keys.

The runtime still reaches READY, so this warning is not presently proven to be the cause of the long-running attempt. Nevertheless, Task 17 must not normalize it away without evidence.

Before qualification, verify:

- the exact checkpoint is the intended OpenMMLab RTMDet-M artifact identified by the current SHA-256;
- the resolved deployment config is derived from the intended upstream model configuration;
- missing model keys equal an explicitly reviewed expected set, ideally empty;
- unexpected checkpoint keys equal an exact reviewed allowlist (for example only the known preprocessor keys if evidence confirms that exact pair); any additional missing/unexpected key fails the compatibility probe;
- detector outputs are numerically sane on the controlled smoke corpus;
- qualification records the exact checkpoint/config pair that was actually tested.

If the warning indicates a genuine incompatibility, stop qualification and correct the release pair before changing performance/watchdog policy.

### 2.8 Release truth remains unchanged

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
11. **The vision execution lane is observationally instrumented but never cooperatively cancelled while native inference is active.**
12. **Watchdog incident evidence is assembled by the worker attempt owner; runtime supervision must not reach back into mutable worker state.**
13. **A frame is reported as forward progress only after its detector, tracker and analytical accumulation work has completed successfully.**

---

## 4. Target architecture

### 4.1 Add an attempt-scoped thread-safe progress source

`WorkerRunner` shall own the lifecycle of one attempt-local progress object and expose it through two narrow interfaces: a read-only `ProcessingProgressReader` for the asyncio/heartbeat side and a write-only `ProcessingProgressSink` for the synchronous vision lane. Do not pass a mutable progress object broadly through the stack and do not use process-global progress state.

Freeze the composition contract before implementation. The preferred shape is:

```text
WorkerRunner
  -> creates ProcessingProgress(source_duration_ms=lease.duration_ms)
  -> retains ProcessingProgressReader
  -> passes ProcessingProgressSink into VisionProcessor.process(...)
      -> ProductionVisionProcessor.process(..., progress_sink=...)
          -> VideoProcessor.process(..., progress_sink=...)
```

`VisionJobLease.duration_ms` is the authoritative duration for progress computation. The worker must not derive a competing duration from container metadata, nominal FPS or decoded-frame counts.

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
- all values are attempt-local and reset for every leased attempt;
- once lease authority is lost or a watchdog incident is declared, the event-loop side captures one immutable incident snapshot; later native-thread writes may complete locally but cannot change the evidence already associated with that incident.

### 4.2 Derive progress from authoritative media time, not guessed FPS totals

The lease already carries source duration and the decoded frame carries media-relative `offset_ms`.

Prefer media-time progress:

`source_offset_ms / duration_ms`

over multiplying a nominal frame rate by duration.

This is robust for variable-frame-rate media and matches the existing Task-9 media timeline contract.

Freeze the computation semantics before implementation:

- clamp media fraction to `[0, 1]`;
- reject/guard invalid numeric states;
- progress for one attempt is `max(previous, newly_derived)`;
- a running attempt never reports 100%;
- if authoritative duration is zero/invalid, remain at the current stage floor, continue only if the media contract otherwise permits it, and emit a diagnostic rather than inventing a guessed frame-count percentage.

Reserve explicit phase ranges so that terminal completion remains authoritative. A proposed mapping is:

- lease/source validation: 0–4%;
- entry into frame processing: 5%;
- frame processing: 5–89%;
- deterministic finalization/artifact publication: 90–95%;
- accepted platform completion: 100%.

The exact constants shall be centralized and tested. A running worker must never claim 100%. Internal stage bands are semantic ranges, not a guarantee that every band will be externally observed on a heartbeat; a fast finalization may legitimately jump from a high frame-processing percentage directly to terminal completion.

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

A frame-level progress update occurs only after all work attributable to that frame has succeeded: detector inference, tracker update, and analytical accumulator mutation. The existing `VisionProcessingResult.frames_processed` contract is not changed implicitly by this work; if its historical increment point differs, keep that semantic stable unless a separate contract change is deliberately approved and tested.

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

### 4.6 Make watchdog termination diagnosable and assign incident ownership explicitly

`WorkerRunner`, not `RuntimeSupervisor`, owns the lease/job/attempt context. Therefore the watchdog path shall use an immutable worker-assembled incident value, for example `WatchdogIncidentSnapshot`, containing only reviewed operational fields. `RuntimeSupervisor` may supply runtime-local facts such as inference activity, resolved device and runtime provenance, but it must not reach back into mutable runner state to discover job context.

At watchdog declaration, the event-loop side shall atomically capture the latest progress snapshot plus the runtime activity snapshot. That captured value is the incident evidence even if the native thread later unwinds during grace.

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

Treat watchdog expiry as an **attempt/runtime containment incident by default, not an immediate terminal job failure**. The dying worker must not call the existing terminal `/fail` path merely to record the watchdog event because that would bypass normal lease-expiry/retry semantics.

The default watchdog path shall be:

- mark the local attempt/lease guard as lost;
- emit and persist a safe local watchdog incident record;
- terminate the unhealthy worker process with exit code 70;
- allow the authoritative lease to expire naturally;
- let the platform's existing retry/attempt policy decide whether the job is reclaimed or ultimately exhausted.

A bounded remote incident-reporting endpoint may be added later only if it is explicitly **non-terminal** and cannot mutate the job to Failed. Terminal `/fail` remains appropriate only for deterministic job failures or retry exhaustion already governed by platform policy.

The implementation must preserve the existing native-call containment invariant: progress/watchdog instrumentation is observational only. It must never attempt to cancel, abort or interrupt a running native MMDetection/CUDA call inside `VisionExecutionLane`.

### 4.7 Define the qualified Phase-1 input envelope before freezing watchdog policy

A fixed per-inference watchdog cannot be called qualified without a bounded supported media envelope. Before performance qualification, explicitly freeze the Phase-1 acceptance envelope for the media characteristics that materially affect processing cost, including at minimum container/codec set, stream count, maximum width/height or pixel count, frame-rate bounds and any applicable duration bounds.

The exact values shall come from the product/import contract and qualification objectives rather than being guessed in this document. Watchdog evidence collected outside that envelope must not be used to justify the production threshold.

### 4.8 Make watchdog policy variant-aware only after measurement

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

### 4.9 Harden the dynamic-heartbeat contract

Dynamic progress must not weaken the existing lease-precedence behavior. Add explicit tests for:

- non-finite progress values (`NaN`, `+/-Inf`) being rejected before wire transmission;
- progress regression attempts being clamped or rejected locally according to the frozen progress component contract;
- a running heartbeat never transmitting more than 95%;
- a heartbeat response completing on or after the authoritative lease deadline remaining invalid;
- processing completion racing a progress-bearing heartbeat without allowing stale authority to win;
- watchdog expiry while a progress-bearing heartbeat is in flight preserving fatal containment and cancelling only the asyncio-owned HTTP task.

The server-returned heartbeat percentage is not a new source of processing truth; the attempt-local progress reader remains authoritative for the next worker report.

### 4.10 Keep qualification timing bounded and non-invasive

Performance instrumentation must use a monotonic clock. Production code shall keep only bounded aggregate timing state needed for safe diagnostics; it must not accumulate an unbounded list of per-frame timings for long videos. Detailed per-frame samples, if required for qualification, belong in explicit `tools/phase1/` qualification tooling with bounded output and no raw-frame retention.

---

## 5. GPU enablement plan

GPU support is a separate qualification workstream and must not be mixed into the progress fix.

### Phase G1 — host capability probe

Add/retain an explicit operator command that reports host-level facts without assuming the current CPU-only Python runtime can use CUDA:

- NVIDIA adapter presence;
- driver visibility/version;
- device identity;
- compatible MAVI CUDA runtime variant availability.

The existing CPU-only PyTorch bundle must not be used to conclude that the host is CUDA-incapable.

### Phase G2 — candidate-runtime capability probe

For a CUDA-enabled candidate runtime, report and verify:

- PyTorch build CUDA identity;
- `torch.cuda.is_available()`;
- device count/name;
- an actual CUDA tensor/inference execution path;
- no silent CPU fallback.

Neither probe may mutate release metadata.

### Phase G3 — Windows CUDA candidate bundle

Build a distinct:

`windows-x86_64-cuda`

runtime bundle only from exact pinned dependencies compatible with the intended NVIDIA/CUDA environment.

Never modify the existing CPU bundle to opportunistically use CUDA.

### Phase G4 — CUDA runtime qualification

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

### Phase G5 — Linux NVIDIA production qualification

The final production-worker gate remains Linux/NVIDIA as already defined by Task 17.

Windows CUDA may be a supported qualified variant, but it does not replace the final Linux NVIDIA production-topology acceptance requirement unless a later ADR changes that architecture.

---

## 6. Detailed implementation sequence

### Step 1 — Freeze and record the implementation baseline

Before code changes:

- capture the exact topic-head SHA;
- run current Python/.NET/frontend focused gates;
- retain the live reproduction evidence;
- record the currently installed runtime-bundle identity;
- do not regenerate runtime bundles merely because documentation or non-runtime files changed.

### Step 2 — Freeze the progress and watchdog contracts in code-facing terms

Before writing production behavior, define the narrow interfaces and immutable values used by the implementation:

- `ProcessingProgressReader`;
- `ProcessingProgressSink`;
- immutable `ProcessingProgressSnapshot`;
- immutable `WatchdogIncidentSnapshot` or equivalent;
- the exact `VisionProcessor.process(..., progress_sink=...)` seam;
- source duration supplied from `VisionJobLease.duration_ms`;
- stage constants and running maximum of 95%.

The watchdog incident value is assembled by `WorkerRunner`; the supervisor contributes runtime-local facts only.

### Step 3 — Add RED tests for truthful attempt-local progress

Add focused tests proving:

- validation progress remains in the validation band;
- frame processing enters at 5%;
- progress increases from authoritative source offsets;
- a frame does not advance progress until detector, tracker and analytical accumulation for that frame succeed;
- repeated heartbeats without a newly completed frame retain the same progress;
- progress never regresses;
- a running attempt never reports more than 95%;
- VFR/media-offset progress is deterministic;
- zero/invalid duration follows the documented safe fallback and never invents FPS-derived progress;
- attempt N progress cannot leak into attempt N+1;
- lease loss freezes the incident evidence seen by the event-loop side even if native work later unwinds.

Likely files:

- `src/vision/tests/test_worker_runner.py`;
- `src/vision/tests/test_process_video.py`;
- new `src/vision/tests/test_processing_progress.py`.

### Step 4 — Implement the thread-safe progress component

Create:

- `src/vision/mavi_vision/runtime/progress.py`.

Requirements:

- model-neutral;
- independent of HTTP, MMDetection and ByteTrack;
- cheap lock-protected snapshots;
- monotonic values;
- finite-number validation;
- no process-global mutable state;
- no cancellation behavior.

### Step 5 — Thread the progress sink through processor composition

Modify:

- `src/vision/mavi_vision/worker/runner.py`;
- `src/vision/mavi_vision/pipeline/production_processor.py`;
- `src/vision/mavi_vision/pipeline/process_video.py`.

Use the frozen injected attempt-local sink. Do not add progress to detector/tracker/runtime analytical interfaces.

Do not alter final `VisionProcessingResult.frames_processed` semantics as a side effect of this work.

### Step 6 — Replace constant 5% heartbeat behavior and harden the wire path

`WorkerRunner` shall read the latest attempt snapshot for every heartbeat.

Add tests proving:

- no NaN/Inf reaches the API client;
- regression attempts cannot produce regressing wire progress;
- running progress never exceeds 95%;
- completion/heartbeat races preserve lease precedence;
- heartbeat responses at/after expiry remain invalid;
- watchdog expiry during an in-flight heartbeat cancels only asyncio-owned network work and preserves native-call containment.

### Step 7 — Add bounded stage and timing diagnostics

Add safe structured diagnostics around:

- source verification start/end;
- decode/frame loop;
- detector call start/end;
- tracker update;
- finalization;
- artifact publication;
- completion request.

Use monotonic timing. Keep per-frame INFO logging off by default. Production runtime timing state must remain bounded; detailed frame-level measurements belong in qualification tooling.

### Step 8 — Implement explicit watchdog incident evidence and containment tests

Add RED tests and then implementation proving:

- a genuinely hung inference -> watchdog -> immutable incident capture -> bounded fatal path;
- a slow but completing inference below the qualified threshold -> no fatal path;
- progress can remain unchanged during one legitimate slow inference without being treated as a whole-job stall;
- progress can advance across successive inference calls without resetting the native-call watchdog semantics;
- stale frame-level progress while no inference is active is diagnostically distinguishable from a hung inference;
- watchdog expiry while recent frame progress exists is still governed by current native-call elapsed time;
- the incident contains reviewed job/attempt/progress/runtime facts but no lease capability, token, arbitrary exception payload or private path;
- the dying worker does not call terminal `/fail` merely to report watchdog expiry;
- the fatal path never waits for poisoned native-lane teardown.

### Step 9 — Close checkpoint/config compatibility before performance qualification

Add a focused release-compatibility check or qualification assertion for the exact checkpoint/resolved-config pair.

Verify before benchmarking:

- exact checkpoint SHA-256;
- intended resolved deployment config;
- expected missing-key set;
- exact reviewed unexpected-key allowlist;
- controlled smoke inference with numerically sane outputs.

Any unexpected key beyond the reviewed set, any unexpected missing key, or failed smoke inference blocks performance qualification. Do not suppress the warning broadly.

### Step 10 — Prove watchdog containment plus external recovery semantics

Qualify the operational contract around exit code 70, not only the in-process exception path.

Acceptance shall demonstrate:

- hung native inference triggers exit 70;
- the old worker PID disappears;
- the configured service supervisor starts a fresh worker process/PID;
- runtime initialization succeeds after restart;
- the old attempt cannot publish stale completion/artifacts;
- the lease expires and is reclaimable according to platform retry policy;
- a subsequent healthy job can be processed.

Document Windows and Linux supervision behavior separately where they differ.

### Step 11 — Define and freeze the Phase-1 qualified input envelope

Record the exact media envelope against which watchdog/performance claims are valid, including at minimum:

- supported container/codec set;
- stream count;
- width/height or pixel-count bounds;
- frame-rate bounds;
- duration bounds where applicable.

Do not freeze a watchdog threshold from one representative clip.

### Step 12 — Add performance probe tooling

Create non-production tooling under `tools/phase1/` that processes designated local media and emits machine-readable timing metrics without storing raw frames.

The tool shall:

- use monotonic timing;
- separate decode/detector/tracker/finalization timings;
- maintain bounded in-memory aggregates;
- optionally emit bounded per-frame samples only when explicitly requested;
- never change runtime/release qualification status itself.

### Step 13 — Measure the Windows CPU candidate

Run the 2-minute acceptance clip plus a controlled corpus spanning the qualified input envelope, including at minimum a short simple clip, representative 1080p footage, a dense scene, a low-detection/empty scene, the highest qualified resolution and a sustained run sufficient to expose thermal/resource behavior.

Capture cold and warmed observations where relevant.

Record:

- frame count;
- decode duration distribution;
- detector duration distribution;
- tracker duration distribution;
- total frame-processing duration distribution;
- min/mean/median/p95/p99/max inference latency;
- decoded FPS;
- inference FPS;
- processing/source ratio;
- memory high-water mark.

### Step 14 — Freeze watchdog policy from evidence

Only after Step 13:

- retain 120 seconds if evidence supports it; or
- change deployment/runtime policy to a measured threshold with a documented safety margin.

Any change requires focused tests and documentation. No arbitrary timeout inflation is allowed.

### Step 15 — Re-run complete CPU acceptance before CUDA work

Required outcome:

- processing percentage advances truthfully;
- no unexplained 5% plateau remains;
- lease heartbeats and progress remain semantically distinct;
- no false watchdog kill occurs inside the qualified CPU envelope;
- a deliberately injected hung call still exits through the bounded fatal path;
- restart/reclaim behavior is proven;
- completion/search/evidence behavior remains unchanged.

### Step 16 — Implement qualified CUDA candidate work separately

Only after CPU observability, compatibility and watchdog semantics are trustworthy, execute the GPU phases in Section 5.

CUDA work should be a separate implementation/qualification workstream rather than being mixed into the initial progress/watchdog PR.

### Step 17 — Update runtime/release metadata only from exact evidence

Do not change:

- `verificationStatus`;
- CUDA variant status;
- CUDA lock status;
- mandatory qualification gate status;

until the corresponding exact evidence exists.

### Step 18 — Full regression

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

### Step 19 — Independent cold review

Review specifically for:

- cross-thread races in progress snapshots;
- watchdog incident ownership violations;
- progress/lease authority confusion;
- stale-attempt progress leakage;
- frame-progress updates before full frame success;
- accidental network calls from the vision lane;
- attempts to cancel active native work;
- heartbeat/progress boundary bugs;
- watchdog false positives;
- loss of fatal containment;
- silent device fallback;
- unbounded performance instrumentation;
- checkpoint/config warning normalization without evidence;
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
7. Watchdog expiry does not force terminal job failure merely to record the incident; lease expiry/retry remains platform-authoritative unless retry exhaustion or a deterministic job failure is proven.
8. Production/service supervision proves worker restart after exit 70 and stale-attempt publication remains impossible.
9. No lease/token secret is logged.
10. CPU and CUDA runtime identities remain explicit and separate.
11. NVIDIA utilization is claimed only when a CUDA runtime variant is explicitly selected and qualified.
12. All existing Task-9 through Task-16 authority, evidence and offline invariants remain green.
13. Release metadata remains truthful throughout the process.
14. Watchdog incident evidence is immutable once declared and is assembled without supervisor-to-runner backreferences.
15. A frame advances observable progress only after detector, tracker and analytical accumulation for that frame succeed.
16. Dynamic progress preserves all existing lease-deadline and terminal-authority invariants.
17. Production progress/timing instrumentation remains bounded and never attempts native-call cancellation.

---

## 8. Files expected to change

Likely production/test files:

- `src/vision/mavi_vision/runtime/progress.py` — new, containing progress reader/sink/snapshot contracts and implementation;
- `src/vision/mavi_vision/worker/runner.py`;
- `src/vision/mavi_vision/pipeline/production_processor.py`;
- `src/vision/mavi_vision/pipeline/process_video.py`;
- `src/vision/mavi_vision/runtime/activity.py` — diagnostics only if required;
- `src/vision/mavi_vision/runtime/supervisor.py` — runtime-local watchdog facts/policy seam only; no backreference into mutable worker attempt state;
- `src/vision/mavi_vision/common/settings.py` — only if measured policy needs explicit configuration;
- worker/progress/process/supervisor tests;
- Task-17 performance/qualification tooling;
- tests for dynamic-heartbeat boundaries, immutable watchdog incidents and checkpoint/config compatibility.

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
- regenerate large offline bundles unless runtime-affecting inputs actually changed;
- make progress reporting responsible for cancelling or interrupting native inference;
- let runtime supervision discover job/attempt context by reaching into `WorkerRunner` state;
- count a frame as observable forward progress before its detector/tracker/analytical work has succeeded;
- retain unbounded per-frame timing samples in the production worker.

---

## 10. Relationship to Task 17

This work is now a **pre-qualification hardening prerequisite** inside Task 17.

The correct order is:

```text
frozen progress/watchdog contracts
        ->
truthful progress + immutable watchdog observability
        ->
checkpoint/config compatibility closure
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
