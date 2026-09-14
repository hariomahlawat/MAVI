# Task 17 — Phase-1 Hardening, Qualification and Offline Acceptance

**Status:** Authoritative implementation plan. Task 17 is the active final Phase-1 task.

**Planning baseline:** accepted Phase-1 integration head `e877dcac9efaefe4f935fa50b2913e806b197d27` after Task 16 PR #36.

**Primary objective:** prove that the already-built Phase-1 MAVI system is repeatable, evidence-linked, recoverable and operable without Internet connectivity, then close the remaining release-qualification evidence truthfully. Task 17 is a hardening/acceptance task; it does not add new analytical product features.

---

## 1. Acceptance boundary

Task 17 validates the complete Phase-1 chain:

`Camera -> managed MP4 import -> queue -> production worker -> authoritative completion -> Track search -> evidence review`

The task shall prove both:

1. **product correctness** — the operational/API/UI/worker workflow behaves correctly under success, retry and failure conditions; and
2. **release correctness** — the selected model/profile/runtime/bundle can be installed and operated from immutable local artifacts with the qualification evidence required by the existing release architecture.

Task 17 shall not introduce:

- face recognition;
- cross-camera ReID;
- ANPR;
- embeddings/vector retrieval;
- LLM/VLM search;
- trajectory visualization;
- review-status mutation;
- new detector architecture;
- silent CUDA-to-CPU fallback;
- online model/package resolution;
- a second datastore/search engine;
- production Internet telemetry;
- a new authentication architecture;
- arbitrary tuning performed directly against the final evaluation corpus.

Any functional defect found during acceptance may be fixed, but every such fix reopens the relevant exact-head evidence.

---

## 2. Current accepted baseline

At `e877dcac9efaefe4f935fa50b2913e806b197d27`, MAVI already has:

1. PostgreSQL authoritative persistence and migrations.
2. Camera and managed MP4 ingestion.
3. Lease/heartbeat/fail/complete worker control plane.
4. Secure attempt-scoped artifact staging on POSIX and Windows.
5. Deterministic processing contracts and accepted result persistence.
6. RTMDet-M + class-separated ByteTrack production adapters.
7. Runtime supervision, bounded recovery and watchdog containment.
8. Reproducible Windows/Linux CPU offline runtime locks and qualification-candidate bundles.
9. Track search/detail and source/evidence content APIs.
10. React Cameras, Import, Processing, Visual Search and Evidence Review.
11. Same-origin ASP.NET Core/IIS hosting with API-safe SPA fallback.
12. Exact-head Task-16 Quality Gate #783 and final Codex review with no major issues.

Task 17 must preserve these contracts rather than redesign them.

---

## 3. Honest qualification baseline

The current release metadata is intentionally not production-verified.

### Model manifest

`models/manifests/rtmdet-m-coco-phase1-v1.json` currently has:

- `verificationStatus = "unverified"`;
- `qualificationId = null`.

### Runtime profile

`src/vision/runtime/mmdetection-phase1-v1/runtime.json` currently has:

- `qualificationStatus = "partial"`;
- qualified hosted CPU variants for Linux and Windows;
- qualified offline CPU locks for Linux and Windows;
- CUDA variants still `pending-hardware-qualification`;
- CUDA locks still `pending-hardware-qualification`.

### Qualification record

`models/qualifications/rtmdet-m-coco-phase1-v1.json` currently keeps these mandatory gates pending:

- `windows-x86_64-cuda`;
- `linux-x86_64-cuda`;
- `windows-offline-install`;
- `linux-offline-install`;
- `cctv-quality-baseline`;
- `linux-nvidia-recovery-performance`.

The existing mandatory-gate set is enforced by `mavi_vision.runtime.qualification`.

**Task 17 must not mark any pending gate passed from inference, assumption, hosted CPU evidence or documentation alone.**

If a mandatory hardware gate cannot be executed, the release remains pending. Removing or weakening a mandatory gate requires a separate architecture decision and is not a Task-17 implementation shortcut.

---

## 4. Three completion states

Task 17 shall keep three states distinct.

### 4.1 Implementation complete

Code, schemas, tests, acceptance tooling and runbooks are complete and exact-head CI is green.

This state alone does **not** mean Phase 1 is accepted and does not permit release metadata promotion.

### 4.2 Phase-1 functional/offline acceptance complete

A designated qualification deployment has successfully executed the controlled end-to-end workflow with outbound Internet unavailable, and its machine-readable evidence has been retained.

This establishes the Phase-1 product workflow.

### 4.3 Production vision release verified

This is stronger. It requires:

- every mandatory qualification gate passed with evidence;
- runtime profile `qualificationStatus = "qualified"`;
- qualification `overallResult = "passed"`;
- model manifest `verificationStatus = "verified"` with matching qualification ID;
- final production bundle generation from the frozen accepted source;
- final exact-head qualification after metadata rebind.

Task 17 is fully closed only when the required acceptance state defined by the current release architecture has actually been achieved. No status label may be promoted merely to make the roadmap appear complete.

### 4.4 Final Phase-1 deployment topology

The final disconnected acceptance shall use the product topology already stated by the repository unless a later accepted ADR changes it:

- the operational web/API plane published behind Windows Server/IIS;
- PostgreSQL/pgvector on an approved local/LAN deployment;
- the production vision worker on a qualified Linux NVIDIA/CUDA host;
- all model/runtime/package assets supplied locally from controlled release artifacts.

CPU qualification-candidate runs remain valuable for deterministic CI, packaging and fallback development evidence, but they are not a substitute for the final Linux-CUDA production-worker acceptance event.

---

## 5. Branch, PR and evidence discipline

After this planning PR is accepted and merged, create one Task-17 implementation branch from the **new resulting integration head**, not from the pre-planning baseline `e877dcac9efaefe4f935fa50b2913e806b197d27`:

`feature/task-17-phase1-acceptance`

Open one implementation PR into:

`feature/task-10-rtmdet-bytetrack`

Record that exact post-planning integration SHA in the implementation PR description before code changes begin.

Within that PR keep these commit classes separate:

1. implementation/tests;
2. acceptance tooling/runbooks;
3. generated release locks or immutable release metadata;
4. evidence rebind;
5. closeout documentation.

Use the established release sequence whenever runtime/release metadata is affected:

**implementation frozen -> hardware/runtime qualification -> immutable CUDA/platform artifacts and locks frozen -> final qualified runtime metadata constructed -> release-level evidence attested -> model/qualification metadata promoted -> production bundle built -> production-bundle verification acceptance**

Hardware qualification that establishes a runtime platform as `qualified-hardware` is deliberately earlier than release-level evidence attestation. It must not be confused with the later model/release qualification evidence that binds to the resulting immutable runtime-profile hash.

If implementation changes after freeze, all downstream evidence tied to the prior frozen head is stale and must be regenerated. If a runtime artifact, lock, platform identity, profile or other behavior-bearing release input changes, every downstream evidence package bound to the previous identity is likewise stale.

Never edit a qualification JSON to say `passed` before the referenced evidence actually exists and is verified.

---

## 6. Controlled acceptance data

### 6.1 No operational CCTV in Git

Repository rules remain unchanged:

- no CCTV recordings;
- no biometric datasets;
- no model weights;
- no credentials;
- no private qualification media.

Task 17 may commit schemas, examples and synthetic/generated fixtures only.

### 6.2 Ground-truth manifest

Create:

- `sample-data/ground-truth/phase1-example.json`;
- `sample-data/ground-truth/phase1-ground-truth.schema.json`.

The schema shall be strict and versioned.

Recommended v1 shape:

```json
{
  "schemaVersion": "mavi-phase1-ground-truth-v1",
  "videoSha256": "<64 lowercase hex>",
  "durationMs": 60000,
  "cameraCode": "QUAL-CAM-01",
  "evaluationWindows": [
    { "startOffsetMs": 0, "endOffsetMs": 60000 }
  ],
  "events": [
    {
      "eventId": "person-001",
      "objectClass": "Person",
      "startOffsetMs": 4200,
      "endOffsetMs": 9100,
      "spatialSamples": [
        {
          "offsetMs": 4200,
          "boundingBox": { "x": 0.11, "y": 0.18, "width": 0.09, "height": 0.31 }
        },
        {
          "offsetMs": 9100,
          "boundingBox": { "x": 0.27, "y": 0.17, "width": 0.09, "height": 0.30 }
        }
      ]
    }
  ]
}
```

Rules:

- `Person` and `Vehicle` only;
- offsets are non-negative integer milliseconds;
- `startOffsetMs < endOffsetMs <= durationMs`;
- event IDs unique inside one manifest;
- every scored event has `spatialSamples` sufficient to identify the annotated physical object during its lifetime;
- spatial boxes are normalized to source-video dimensions in `[0,1]` as `x, y, width, height`, with positive width/height and no edge outside the frame;
- spatial-sample offsets are sorted, unique, lie inside the event interval, and use the same media-offset timebase as Track representative observations;
- every event must include a spatial sample at its exact start and exact end offset, and every adjacent sample gap across the event must be less than or equal to the qualification profile's maximum interpolation span; this makes spatial coverage validatable from ground truth + profile before inference and guarantees that any Track representative offset inside the event has a defined reference box;
- `evaluationWindows` are sorted, non-overlapping annotated intervals inside the video;
- every scored event lies fully inside an evaluation window;
- Tracks outside evaluation windows are excluded rather than mislabeled false positives;
- a fully annotated clip uses one window covering the entire duration, which allows empty/no-target clips to measure false positives correctly;
- simultaneous same-class objects are permitted only when each has independent spatial annotation; temporal coincidence alone is never enough to establish identity;
- no person identity, face label, licence plate or other biometric/PII annotation;
- the manifest identifies source bytes by SHA-256, never by private absolute path.

Actual controlled qualification media may remain outside Git. Its retained evidence manifest must record the exact media SHA-256 used.

---

## 7. Ground-truth evaluation contract

Create a deterministic evaluator, preferably:

`tools/phase1/evaluate_ground_truth.py`

It shall consume:

- one ground-truth manifest;
- one normalized list of accepted MAVI Tracks returned from public APIs;
- one versioned acceptance-profile file.

Matching is class-exact, spatially validated and one-to-one. Temporal overlap alone must never identify a physical object.

For interval matching use deterministic temporal IoU:

`intersection duration / union duration`

For spatial validation, use the representative observation already exposed by the Task-14 public Track-detail contract:

- Track representative `videoOffsetMs`;
- Track representative `boundingBox { x, y, width, height }`;
- source-video dimensions from Track detail, used only to validate/normalize API values if required.

For each candidate ground-truth event, derive the reference ground-truth box at the Track representative offset:

1. if a spatial sample exists at that exact offset, use it;
2. otherwise require bracketing spatial samples whose separation does not exceed the acceptance profile's maximum interpolation span;
3. linearly interpolate `x, y, width, height` by media offset;
4. if no valid reference can be derived, that event/Track pair is **ineligible** rather than matched by time alone.

Compute spatial IoU between the Track representative box and the derived ground-truth reference box. A candidate edge exists only when all are true:

- object class is equal;
- temporal IoU meets the configured minimum;
- the Track representative offset lies within the ground-truth event interval;
- a valid ground-truth spatial reference exists at that offset;
- spatial IoU meets the configured minimum.

This intentionally uses the stable public API and does **not** query PostgreSQL, read internal Observation rows, or decode the trajectory artifact.

The evaluator shall report, per class and overall:

- ground-truth event count;
- produced Track count;
- matched count;
- missed count;
- unmatched Track count;
- precision;
- recall;
- F1;
- temporal-IoU distribution;
- spatial-IoU distribution;
- duplicate/competing-candidate count;
- spatial-reference failures as baseline diagnostics only; formal qualification ground truth with missing/over-wide spatial coverage fails semantic validation before scoring.

Only Track time intersecting an `evaluationWindow` is scored. A Track crossing a window boundary is clipped to that annotated window before temporal IoU is calculated; Tracks wholly outside all evaluation windows are ignored. Ground-truth events are required to lie wholly inside one evaluation window.

### Deterministic global assignment

Do **not** greedily consume the highest-IoU edge.

For each object class independently:

1. construct the eligible bipartite graph between ground-truth events and produced Tracks;
2. find a **maximum-cardinality matching** first, so the evaluator never sacrifices a valid second match for a locally better first edge;
3. among maximum-cardinality matchings, maximize the **sum of spatial IoU** first because spatial overlap establishes physical-object correspondence;
4. among assignments still tied, maximize the **sum of temporal IoU**;
5. compute both optimization sums from a canonical fixed-precision integer representation of IoU values, using one documented scale/rounding rule, rather than binary-floating comparison noise;
6. if multiple assignments still tie on cardinality, total spatial IoU and total temporal IoU, select the lexicographically smallest canonical assignment ordered by ground-truth `eventId`, then Track `startOffsetMs`, then Track ID.

The implementation may use a deterministic min-cost maximum-flow/assignment algorithm or another reviewed exact equivalent. It must not depend on dictionary/set iteration order, unstable library tie-breaking or random seeds.

The acceptance evidence shall include the selected event↔Track pairs and both IoUs so a qualification result is auditable.

This Phase-1 metric proves class-correct event/Track correspondence, fragmentation/duplicate behavior through one-to-one assignment, and representative spatial correctness. It does **not** claim per-frame same-class identity continuity or Track-purity scoring across the entire trajectory. Task 17 must not decode the internal MessagePack trajectory merely to imply such a guarantee. If full trajectory identity-switch/purity scoring later becomes a mandatory release criterion, first define a stable public trajectory contract and matching metric in a separately reviewed change.

A current-run Track used for formal qualification is expected to have a representative observation. Missing representative time/bounding-box data is an evaluation failure for that Track; it must not silently fall back to temporal-only matching.

Zero-denominator metrics must not be silently converted to misleading perfect scores. Per-class precision/recall/F1 may be `null` where mathematically undefined; raw matched/missed/unmatched counts are always emitted. Corpus-level aggregate metrics are computed from aggregate counts, and the acceptance profile defines any explicit empty-scene false-positive rule.

### Acceptance thresholds

Task 17 shall **not invent operational accuracy thresholds in code**.

Create a reviewed, versioned acceptance profile, for example:

`config/acceptance/phase1-acceptance-v1.json`

It shall contain:

- minimum temporal IoU used for candidate eligibility;
- minimum spatial IoU used for candidate eligibility;
- maximum ground-truth spatial interpolation span;
- the canonical fixed-precision IoU scale/rounding rule used by the assignment optimizer;
- any minimum Person/Vehicle precision/recall/F1 required for formal acceptance;
- allowed unmatched/duplicate policy;
- performance thresholds tied to an identified hardware class, if approved.

The first implementation shall support a `baseline` mode that only measures and reports. Before the qualification freeze, the acceptance profile must be reviewed and switched to a formal `qualification` policy containing approved values; placeholder/null thresholds are not acceptable on a final evidence head. The formal `cctv-quality-baseline` gate is passed only after the corpus, acceptance profile and measured result have been reviewed and the resulting evidence explicitly records an accepted decision.

The Task-17 implementation must not guess those operational thresholds. If approved thresholds are not yet available, the quality gate remains pending while the measurement tooling may still be completed.

Do not tune the pipeline against the final held-out qualification set and then report that same set as independent validation.

---

## 8. End-to-end acceptance harness

Create:

`tools/phase1/phase1_e2e_check.py`

The harness shall use public MAVI HTTP contracts. It must not query PostgreSQL directly or inspect storage directories to decide success.

Inputs shall include at minimum:

- base URL;
- qualification camera code/name/timezone;
- recording-local timestamp;
- controlled MP4 path;
- expected processing timeout;
- optional ground-truth manifest;
- output evidence path.

The qualification environment should use a dedicated database/storage root so repeated runs do not contaminate operational data.

The harness must never delete or rename the operator's source file. For the managed-copy proof it shall first create a disposable qualification working copy, hash that copy, upload it, and delete only the disposable copy after import. The original controlled corpus asset remains untouched.

Prefer Python standard-library HTTP/file primitives for this qualification tool unless a new tooling-only dependency is explicitly justified and pinned; Task 17 must not add an operational runtime dependency merely to implement acceptance automation.

### 8.1 Workflow

The harness shall:

1. verify `/api/health` and `/api/system/config`;
2. create or resolve the qualification Camera deterministically; when create returns a duplicate-code conflict, resolve the existing camera through the public Camera list and require exactly one exact code match rather than guessing an ID;
3. import the controlled MP4;
4. handle authoritative `video_duplicate` reconciliation rather than re-upload guessing;
5. queue processing;
6. poll processing until a terminal state with a bounded timeout;
7. require successful ProcessingRun completion;
8. capture the authoritative completed ProcessingRun ID from processing status;
9. query `GET /api/tracks?videoAssetId=...&processingRunId=...` for the exact accepted run;
10. separately verify the default `videoAssetId` search resolves the latest completed run semantics;
11. page through opaque cursors without decoding them;
12. require every returned Track to belong to both the imported VideoAsset and expected ProcessingRun;
13. resolve each Track detail;
14. verify representative-evidence content where present;
15. verify source-video Range streaming;
16. verify the Search contract can locate Person/Vehicle results as applicable;
17. calculate structural and optional ground-truth metrics;
18. emit one machine-readable evidence document;
19. exit nonzero on any acceptance failure.

### 8.2 Evidence invariants

The harness shall fail if:

- processing reports success but no authoritative completed run exists;
- Track/video identity is inconsistent;
- a Track detail cannot be resolved;
- an accepted representative artifact URL cannot be read;
- source-video Range access fails;
- public responses expose a physical storage path or worker staging path;
- cursor continuation changes committed search semantics;
- an orphan Track is detected;
- required ground-truth acceptance fails;
- timeout is exceeded.

The harness must never decode or reinterpret the Task-14 opaque cursor.

---

## 9. Machine-readable acceptance evidence

Define a strict evidence schema:

`tools/phase1/phase1-acceptance-evidence.schema.json`

The generated record should contain:

- schema version;
- source Git commit;
- MAVI build identity;
- operator-supplied qualification environment label (not an automatically leaked private hostname);
- selected model/profile/runtime IDs and SHA-256 values;
- VideoAsset ID;
- source-media SHA-256;
- ProcessingRun ID;
- processing terminal state;
- processing duration;
- video duration;
- frames processed if available from authoritative provenance;
- effective FPS where derivable;
- Track counts by class;
- search latency measurements;
- number of Track details resolved;
- representative-evidence reads attempted/passed;
- source-video Range result;
- orphan count;
- ground-truth metrics when supplied;
- final result;
- stable failure codes.

Do not embed:

- credentials;
- lease tokens;
- absolute private filesystem paths;
- raw frames;
- CCTV media;
- model weights.

The retained evidence file itself shall have SHA-256 recorded in the qualification/closeout record.

---

## 10. Failure and reprocessing hardening

Add focused integration coverage, including:

`tests/Mavi.IntegrationTests/ProcessingFailureRecoveryTests.cs`

Required scenario:

1. import a VideoAsset;
2. queue processing;
3. lease the job;
4. fail the active attempt through the worker contract;
5. assert the managed source VideoAsset still exists;
6. assert no accepted Tracks from the failed run are visible;
7. explicitly queue processing again;
8. assert a new ProcessingRun ID;
9. assert a new VisionJob ID;
10. prove stale prior-attempt authority cannot complete/publish the new run.

Do not add unbounded automatic retry.

Explicit reprocess remains an operator/system command that creates a new authoritative run.

Also cover:

- failure after partial local staging but before completion;
- duplicate/replayed terminal requests;
- lease loss precedence;
- successful reprocessing after a failed run;
- Task-14 default search selecting the latest completed run only.

---

## 11. Worker end-to-end contract test

Create:

`src/vision/tests/test_worker_end_to_end_contract.py`

This is a contract-level worker test, not a substitute for real-model hardware qualification.

It shall exercise:

- lease;
- source verification;
- heartbeats;
- processing callback;
- completion payload;
- provenance;
- evidence publication authorization;
- terminal failure mapping.

Use deterministic fixture processing where appropriate so CI remains fast and does not download a model.

Real RTMDet/ByteTrack execution remains in qualification gates.

---

## 12. Production host acceptance

Task 15 supplied:

`tools/task15/qualify_windows_host.ps1`

Task 17 shall retain that qualification rather than assuming the existence of the script proves deployment. Preserve the historical Task-15 script and create a Task-17 wrapper/extension at `tools/phase1/qualify_phase1_windows_host.ps1` rather than quietly changing the meaning of past Task-15 evidence.

On the designated Windows/IIS host, evidence shall demonstrate:

- same-origin API reachability;
- direct `/search` refresh;
- direct `/review/video/...?...trackId=...` refresh;
- unknown `/api` route remains 404;
- local static assets only;
- configured request limit accepts a representative >30 MiB multipart import;
- a managed imported video can proceed into the Task-17 processing workflow.

If the production web host is not available, record the gate as pending. Do not substitute Vite dev-server behavior.

---

## 13. Formal offline-install qualification

Task 12 already builds deterministic qualification-candidate bundles.

Task 17 owns the formal disconnected install gates:

- `windows-offline-install`;
- `linux-offline-install`.

A passing offline-install gate requires a clean target environment using the exact required CPython patch version. The evidence must state which platform variant/lock was installed; a CPU installation must never be cited as proof that a CUDA bundle installs, and vice versa. The current OS-level gate names do not remove that evidence requirement.

Installation uses:

```text
pip install --no-index --only-binary=:all: --require-hashes --find-links <wheelhouse> -r <lock>
pip check
```

Then, with outbound connectivity disabled:

1. validate bundle manifest hashes;
2. install only from bundle bytes;
3. start the runtime;
4. perform real local RTMDet inference;
5. start MAVI worker;
6. execute at least one controlled processing flow against the operational API;
7. search accepted Tracks;
8. retrieve evidence/source video;
9. confirm no first-run model/package download, telemetry or online licence check occurs.

Use qualification-candidate bundle mode until the release metadata is legitimately promotable. Pre-promotion qualification may run only through the repository's explicit unverified/development allowance; evidence must say so. The final production-bundle acceptance later in this plan must run with production verification enabled and must not use `allow_unverified` or development `auto` device semantics.

A proxy pointed to an invalid endpoint is useful as an additional tripwire but is **not** by itself proof of a formally disconnected host.

### 13.1 Disconnected evidence transport

A genuinely disconnected host cannot simultaneously be a live GitHub Actions runner. Therefore the formal offline gate shall run locally from the transferred qualification bundle and Task-17 scripts.

The disconnected host shall emit a self-contained evidence package containing:

- canonical acceptance JSON;
- exact source/model/profile/runtime/bundle identities;
- platform/Python identity;
- isolation method/operator record;
- command exit statuses;
- required logs with secrets/tokens redacted;
- SHA-256 manifest covering every evidence file.

After the run, transfer the evidence package back through the controlled offline-transfer process. A connected verification step may validate its schema/hashes and bind its immutable reference into the qualification record, but it must never rewrite the disconnected result.

Create `tools/phase1/verify_phase1_evidence.py` to perform this connected-side validation. Qualification metadata records only the immutable evidence reference and SHA-256 required by the existing qualification schema; large/raw evidence artifacts remain outside Git.

---

## 14. CUDA hardware qualification

Current architecture requires both:

- `linux-x86_64-cuda`;
- `windows-x86_64-cuda`.

A passing hardware gate must execute on real supported NVIDIA hardware and record:

- GPU model;
- driver version;
- CUDA runtime/toolkit identity as applicable;
- exact Python identity;
- exact PyTorch/TorchVision binary build identities;
- MMDetection/MMCV/MMEngine identities;
- resolved-config SHA-256;
- checkpoint SHA-256;
- pipeline-profile SHA-256;
- real RTMDet inference result;
- ByteTrack contract smoke;
- device policy actually resolved to CUDA;
- proof that no CPU fallback occurred.

Do not copy hosted CPU evidence into CUDA gates.

If one CUDA platform is no longer a product requirement, change that only through a separate accepted ADR and corresponding qualification-schema migration before Task-17 closure.

---

## 15. CUDA locks and offline bundles

A CUDA offline lock may become `qualified-offline-lock` only after its corresponding platform variant is `qualified-hardware`.

The required sequence is:

1. qualify exact CUDA hardware/runtime graph;
2. freeze the exact reviewed wheelhouse;
3. generate deterministic CUDA lock;
4. verify lock grammar/completeness/hashes;
5. bind the lock SHA-256 into `runtime.json`;
6. rebuild qualification-candidate bundle;
7. execute disconnected installation on the intended platform where required;
8. rerun final qualification on the rebound metadata.

No target-machine compilation is permitted in the final offline path.

---

## 16. Linux NVIDIA recovery/performance gate

The mandatory `linux-nvidia-recovery-performance` gate must use the same selected release/profile/device.

At minimum prove:

- normal repeated processing does not leak Track state across videos;
- one qualified recoverable CUDA OOM incident causes at most one same-release reconstruction/warm-up before the next lease;
- a poisoned/unavailable runtime does not attempt semantic fallback;
- watchdog expiry prevents stale publication and reaches the process-restart containment boundary;
- after a successful bounded recovery, a later fresh attempt uses the replacement runtime;
- no CUDA-to-CPU fallback occurs;
- repeated-video memory usage does not show an unbounded growth trend over the defined soak;
- processing FPS and end-to-end latency are measured on the identified hardware profile.

Performance thresholds must come from the reviewed acceptance profile, not from an arbitrary value embedded in the test script.

---

## 17. CCTV quality baseline

The `cctv-quality-baseline` gate uses a controlled, versioned corpus manifest outside source control when media is private.

Evidence must bind:

- corpus manifest/version;
- each source-video SHA-256;
- ground-truth schema version;
- acceptance-profile version/hash;
- model manifest hash;
- pipeline profile hash;
- runtime profile hash;
- per-video and aggregate metrics;
- accepted/rejected decision.

The corpus should cover representative Phase-1 conditions such as:

- persons at near/far scale;
- vehicles at near/far scale;
- partial occlusion;
- entry/exit at frame boundaries;
- short and longer Tracks;
- low/high illumination where available;
- empty/no-target intervals.

No identity or biometric label is required.

---

## 18. No tuning on the final evidence head

If Task 17 reveals that detector/tracker thresholds need adjustment:

1. change the versioned pipeline profile;
2. increment its profile version;
3. invalidate evidence bound to the prior profile hash;
4. run development/tuning data;
5. freeze the new profile;
6. rerun the complete required qualification set against the new hash.

Never change a threshold and preserve old qualification evidence as though it exercised the new behavior.

---

## 19. Runtime qualification, candidate rebind, evidence attestation and final promotion

Task 17 must avoid two circular mistakes: marking qualification gates passed before their evidence exists, and requiring a final runtime hash before the hardware qualification needed to construct that runtime has occurred.

### 19.1 Hardware/runtime qualification before final runtime hash

After implementation is frozen:

1. execute the Windows/Linux CUDA hardware qualification needed to establish exact platform/device/runtime identities;
2. generate and validate any CUDA release locks only from the actually qualified runtime graphs;
3. record immutable evidence for the platform qualification itself;
4. update CUDA platform entries to `qualified-hardware` only when that platform evidence exists;
5. update CUDA release-lock entries to `qualified-offline-lock` only when the exact lock bytes exist and validate;
6. do not yet promote model qualification gates merely because the runtime platform is now qualified.

The purpose of this stage is to establish the immutable runtime inputs. Hardware evidence used to justify a `qualified-hardware` runtime entry is not, by itself, the later model/release-level attestation.

### 19.2 Candidate metadata rebind

Only after every required runtime platform identity and release lock is immutable:

1. construct the final intended `runtime.json`;
2. set `qualificationStatus = "qualified"` only when the runtime schema permits it and every required platform/lock condition is actually satisfied;
3. compute the resulting final runtime-profile SHA-256;
4. keep the model manifest `unverified` and model qualification gates `pending`;
5. rebind the pending qualification record to the final runtime/profile identities as required;
6. run repository/release-selection validation.

This candidate-rebind head is the head on which release-level offline, CCTV-quality, recovery/performance and end-to-end candidate evidence is generated.

### 19.3 Evidence attestation

Every evidence package must bind the exact behavior-bearing identities it exercised:

- frozen implementation/source identity;
- checkpoint/config/profile hashes;
- candidate runtime-profile hash;
- platform/device/lock identity;
- controlled media/corpus hashes where relevant.

For the later status-only manifest promotion, Task 17 may precompute the exact intended verified-manifest bytes and target SHA-256 (same model/config/runtime identity, only the reviewed qualification/status linkage changes) and include that target hash in evidence. Do not commit an inconsistent verified manifest before evidence exists.

### 19.4 Final evidence-binding/promotion commit

Only after every mandatory gate has real validated evidence:

1. construct the intended final model-manifest bytes with `verificationStatus = "verified"` and the matching `qualificationId`;
2. verify its SHA-256 equals the target verified-manifest hash attested by the evidence set;
3. construct the qualification record against the **final** verified-manifest/profile/runtime hashes;
4. set only genuinely evidenced mandatory gates to `passed`;
5. add immutable evidence references/SHA-256 values for every passed gate;
6. set `overallResult = "passed"` only when all required gates are passed;
7. commit the final manifest + qualification evidence binding together;
8. make **no behavior/profile/runtime-artifact change** in this promotion commit;
9. rerun `tools/verify_repo.py`, release-selection tests and normal exact-head CI.

If the promotion commit would change model/config/profile/runtime behavior or an artifact hash, the previous evidence is invalid and the sequence returns to candidate rebind/attestation.

Do not hand-edit hashes from memory. Generate and verify them from exact bytes.

---

## 20. Production bundle generation

After metadata promotion is frozen, build final production bundles using:

`tools/vision/build_offline_bundle.py --release-status production ...`

The production bundle build must fail closed unless:

- manifest is verified;
- qualification ID matches;
- all mandatory qualification gates are passed;
- runtime is qualified;
- requested platform has an allowed qualified lock;
- every included file matches its recorded SHA-256.

Record:

- source commit;
- platform variant;
- bundle ID;
- bundle-manifest SHA-256;
- selected release-lock SHA-256;
- model/profile/runtime/qualification hashes.

The bundle directory/archive itself remains a release artifact, not a Git-tracked file.

---

## 21. Final production-bundle verification acceptance

The final Phase-1 disconnected acceptance is executed only after legitimate release promotion and production-bundle generation. It verifies the exact production artifacts rather than reusing candidate evidence as a substitute.

The deployment prerequisites must be explicit. The Task-12 vision bundle does **not** provision Windows Server/IIS, PostgreSQL/pgvector, CPython, NVIDIA/CUDA drivers or the complete MAVI application deployment. For the final acceptance:

- Windows Server/IIS prerequisites are pre-provisioned or installed from separately controlled offline media;
- PostgreSQL/pgvector is pre-provisioned or installed from approved local/offline media;
- the exact required CPython patch version and NVIDIA/CUDA driver prerequisites are pre-provisioned on the Linux worker;
- the MAVI application build/deployment artifact is separately identified, hashed and retained;
- the Task-12 production bundle supplies the qualified vision Python/runtime/model closure;
- acceptance evidence binds both the MAVI application build identity and the vision-runtime production-bundle identity.

On a clean designated production-representative acceptance deployment (Windows/IIS operational plane + qualified Linux NVIDIA worker):

1. verify the approved prerequisite baseline and record its versioned identities;
2. validate the MAVI application deployment artifact hash;
3. validate final vision production-bundle bytes and bundle-manifest hash;
4. install the vision runtime from the production bundle with Internet unavailable;
5. start PostgreSQL/pgvector from the approved local deployment;
6. start Mavi.Api behind the production-equivalent Windows/IIS host;
7. start the qualified Linux NVIDIA worker;
8. create/resolve qualification Camera;
9. import controlled MP4;
10. remove the client-side import working copy;
11. prove managed source remains retrievable;
12. process successfully;
13. search Person/Vehicle Tracks;
14. open Evidence Review;
15. verify representative evidence;
16. verify native source-video playback/range;
17. execute ground-truth evaluation if applicable;
18. run failure/reprocess scenario;
19. inspect logs for attempted Internet calls/telemetry/licence checks;
20. retain machine-readable acceptance evidence.

This is the **final Phase-1 disconnected acceptance event**. A candidate acceptance, a green unit-test suite, or an invalid-proxy CI run is not a substitute.

---

## 22. Proposed implementation files

Create:

- `sample-data/ground-truth/phase1-ground-truth.schema.json`
- `sample-data/ground-truth/phase1-example.json`
- `config/acceptance/phase1-acceptance-v1.json`
- `tools/phase1/phase1_e2e_check.py`
- `tools/phase1/evaluate_ground_truth.py`
- `tools/phase1/phase1-acceptance-evidence.schema.json`
- `tools/phase1/verify_phase1_evidence.py`
- `tools/phase1/qualify_phase1_windows_host.ps1`
- `tools/phase1/qualify_phase1_linux_host.sh`
- `tools/phase1/tests/test_evaluate_ground_truth.py`
- `tools/phase1/tests/test_phase1_e2e_check.py`
- `tools/phase1/tests/test_verify_phase1_evidence.py`
- `tests/Mavi.IntegrationTests/ProcessingFailureRecoveryTests.cs`
- `src/vision/tests/test_worker_end_to_end_contract.py`
- `docs/runbooks/phase1-acceptance.md`
- `.github/workflows/task17-acceptance.yml`.

Modify as required:

- `docs/runbooks/offline-readiness.md`;
- `docs/runbooks/local-development.md`;
- `README.md`;
- `.github/workflows/quality-gate.yml` to execute deterministic `tools/phase1/tests` in addition to the existing suites;
- `tools/verify_repo.py` for new schema/release invariants;
- `runtime.json`, qualification record and model manifest only during controlled evidence/rebind stages.

Do not change backend/API/runtime behavior unless a demonstrated acceptance defect requires it.

---

## 23. Checkpoint A — acceptance contracts and failure hardening

Before hardware or release metadata work:

1. add RED tests for ground-truth schema validation plus semantic ground-truth/profile validation, including normalized spatial boxes, exact start/end coverage, ordering and maximum-gap interpolation rules;
2. add RED tests for deterministic evaluation/matching;
3. add explicit evaluator adversarial vectors for:
   - two simultaneous same-class objects with distinct spatial locations;
   - one real object plus a temporally overlapping false Track elsewhere in the frame;
   - the maximum-cardinality counterexample where greedy matching returns one pair but two valid pairs exist;
   - equal-cardinality/equal-quality assignments requiring canonical deterministic tie-breaking;
   - missing start/end spatial coverage or over-wide interpolation gaps that must invalidate formal ground truth before scoring;
   - Tracks crossing evaluation-window boundaries;
4. add RED `ProcessingFailureRecoveryTests`;
5. add worker end-to-end contract RED tests;
6. implement only enough production changes to satisfy demonstrated defects;
7. add acceptance evidence schema;
8. add repository verification for all new tracked schemas/configs.

Gate:

- .NET build/tests;
- Python tests;
- frontend tests/typecheck/build;
- `tools/verify_repo.py`.

No release metadata promotion in Checkpoint A.

---

## 24. Checkpoint B — API end-to-end harness

Implement and test `phase1_e2e_check.py`.

Required automated tests shall cover:

- camera create/existing reconciliation;
- import success;
- duplicate import reconciliation;
- processing queue;
- bounded status polling;
- failed processing result;
- successful completed result;
- Track search pagination;
- Track/video identity;
- evidence URL access;
- source Range request;
- malformed/expired cursor behavior;
- no storage-path leakage;
- evidence JSON generation;
- nonzero exit on failed invariant.

Use mocked HTTP for CLI unit tests and integration-host tests where appropriate.

Do not require live RTMDet in the normal Quality Gate.

---

## 25. Checkpoint C — operator/host/offline qualification tooling

Create the Phase-1 acceptance runbook and `.github/workflows/task17-acceptance.yml`.

The workflow shall keep ordinary hosted validation separate from evidence-producing qualification work:

- connected hardware qualification may use `workflow_dispatch` with explicit approved self-hosted GPU runner labels;
- formal disconnected-install/final-offline acceptance must **not** run as a live GitHub Actions job, because that would contradict network isolation;
- GitHub Actions may validate a transferred offline evidence package after the isolated run, but may not manufacture or mutate the result.

Hardware jobs must never silently fall back to generic GitHub-hosted runners when the required environment is unavailable.

Prove the scripts:

- fail closed on missing evidence;
- never auto-mark a gate passed;
- preserve exact source/head/hash identities;
- do not store secrets;
- do not silently skip unavailable hardware;
- distinguish `pending`, `failed` and `passed`.

At this checkpoint the implementation can be code-complete while release evidence remains pending.

---

## 26. Checkpoint D — implementation freeze and internal review

Before final qualification:

1. inspect the complete Task-17 diff;
2. remove accidental feature scope;
3. verify acceptance tooling uses public APIs rather than DB/storage shortcuts;
4. verify all time values distinguish UTC vs media offsets;
5. verify retry is bounded;
6. verify no cursor decoding;
7. verify no operational CCTV/media/weights are tracked;
8. verify no Internet runtime dependency was introduced;
9. verify no gate is auto-promoted;
10. verify evidence hashes/identities are computed from exact bytes;
11. verify failures are stable and machine-readable;
12. verify UI/API/worker state is not inferred from local tool state.

Then freeze the implementation head.

Any implementation change after this point invalidates downstream release evidence.

---

## 27. Checkpoint E — hardware/runtime qualification and deterministic artifacts

From the frozen implementation:

- execute required CUDA hardware qualification first;
- establish exact Windows/Linux CUDA platform identities from real qualified hosts;
- generate any new CUDA locks only from those actually qualified runtime graphs;
- validate the generated locks against the qualified platform identities;
- record immutable platform evidence and exact hashes;
- generate qualification-candidate bundles after the runtime artifacts are frozen;
- do not mix source-behavior fixes into artifact commits.

If required hardware is unavailable, stop with those runtime/platform gates pending rather than inventing artifacts or constructing a falsely final runtime hash.

---

## 28. Checkpoint F — final runtime construction and candidate metadata rebind

After final immutable runtime/platform/lock identities exist:

- construct the final runtime profile from the already qualified platform identities and frozen release locks;
- set runtime `qualificationStatus` to `qualified` only if the schema and all runtime prerequisites are satisfied;
- compute the final candidate runtime hash only after that construction;
- keep model manifest unverified and model qualification gates pending;
- rebind only identities that are legitimately knowable before release-level evidence;
- precompute (do not prematurely publish) the intended final verified-manifest bytes/hash;
- run release-selection and repository verification immediately.

No gate is promoted merely because the candidate metadata is internally consistent.

---

## 29. Checkpoint G — evidence attestation and final promotion

On the exact candidate-rebind head run every applicable evidence gate:

### Always automated

- MAVI Quality Gate;
- .NET complete suite;
- Python complete suite;
- frontend tests/typecheck/build;
- repository verification;
- Task-14 read-security gate;
- Task-10 staging-security gate;
- hosted CPU runtime qualification;
- Task-12 bundle reproduction/comparison.

### Release-level evidence / acceptance

The CUDA platform qualification that establishes the final runtime identities occurred in Checkpoint E and must not be repeated here merely to manufacture the runtime hash. Checkpoint G validates evidence bound to that now-immutable runtime identity and executes the remaining release-level gates:

- Windows disconnected-install qualification from transferred locally generated evidence;
- Linux disconnected-install qualification from transferred locally generated evidence;
- validation of retained Windows/Linux CUDA platform evidence against the final runtime identity;
- Linux NVIDIA recovery/performance;
- CCTV-quality baseline;
- deployed Windows/IIS host acceptance;
- **candidate disconnected end-to-end acceptance** from transferred locally generated evidence.

All evidence must name the exact behavior-bearing source/release identities it exercised. Connected CI validates evidence; it does not substitute for a disconnected execution environment.

When every mandatory gate has validated evidence, perform the status/evidence-only final promotion in section 19.4. Then rerun all deterministic exact-head gates and build the production bundle. Execute the **final production-bundle verification acceptance** in Section 21. A failure at this stage reopens the release; it is not waived because the earlier candidate disconnected acceptance passed.

---

## 30. Checkpoint H — external review and merge

Only after internal audit and exact-head gates:

1. request broad Codex Critical/P1/P2 review;
2. root-cause every material finding;
3. add focused regression coverage;
4. invalidate/re-run affected evidence after any code or release-bound metadata change;
5. require zero unresolved material review threads;
6. merge with `expected_head_sha`;
7. verify integration branch moved to the actual merge result;
8. record final evidence in this plan/roadmap.

Do not merge merely because ordinary CI is green while a required hardware/offline/quality gate is still being represented as complete.

---

## 31. Internal audit checklist before Codex

Search explicitly for:

- DB/filesystem access in acceptance code where a public API should be used;
- hard-coded credentials or private paths;
- checked-in video/model/bundle bytes;
- unbounded polling/retry;
- implicit browser/system timezone assumptions;
- confusion between media offsets and UTC;
- cursor decoding or replay across filter changes;
- success inferred from HTTP 2xx without authoritative IDs/state;
- duplicate import causing accidental re-upload;
- failed run leaving accepted Tracks;
- stale lease completing/publishing;
- evidence content not bound to hashes;
- gate marked passed without evidence;
- evidence from an older model/profile/runtime hash reused;
- runtime/profile tuning after evidence capture;
- CUDA fallback to CPU;
- development `auto` treated as production;
- offline test that still has usable outbound network;
- missing `--no-index --only-binary --require-hashes`;
- target-machine compilation;
- first-run downloads;
- remote fonts/CDNs/telemetry;
- production bundle built while release is still pending;
- manual evidence that cannot be tied to an exact source head.

Fix sibling defects discovered by this audit before external review.

---

## 32. Definition of done

Task 17 has two truthful states during execution:

- the implementation may become **code-complete / evidence-pending** when all deterministic tooling and code are green but external hardware/evidence is not yet available; in that state the single Task-17 implementation PR remains open (or draft), Task 17 remains active, and the release stays unverified;
- Task 17 is **fully complete** only when the current mandatory qualification set and final disconnected Phase-1 acceptance have actually passed.

Do not merge an evidence-pending Task-17 PR merely to shorten the branch lifetime. If program scheduling genuinely requires splitting implementation from later qualification, first re-baseline the roadmap explicitly into separate numbered/sub-numbered tasks so the repository never records an incomplete Task 17 as complete.

For full completion, at minimum:

- failure/reprocess integration coverage is green;
- worker end-to-end contract coverage is green;
- ground-truth schema/evaluator is deterministic and reviewed;
- Phase-1 E2E harness is deterministic and fail-closed;
- one controlled end-to-end product run succeeds;
- Search and Evidence Review resolve accepted intelligence correctly;
- no orphan accepted Track/evidence inconsistency exists;
- production-host deep links/API behavior are qualified;
- formal offline-install evidence exists for required platforms;
- every current mandatory hardware/quality/performance gate is passed with evidence;
- no mandatory gate is silently removed;
- final release metadata passes repository/release-selection verification;
- production bundles are generated only after legitimate release promotion;
- final disconnected acceptance succeeds;
- exact-head automated gates are green;
- final broad Codex review has no material Critical/P1/P2 blocker;
- merge uses expected-head protection;
- integration-head verification is recorded.

Phase 1 must not be declared accepted merely because RTMDet returns detections. Acceptance means the complete offline evidence-linked visual-memory workflow is repeatable, recoverable, reviewable and backed by truthful release evidence.

---

## 33. Planning decisions that must not be re-opened casually

The following are deliberate:

- Task 17 is hardening/qualification, not feature expansion.
- Public APIs are the acceptance boundary for product E2E checks.
- Ground truth contains Person/Vehicle event intervals plus non-biometric spatial bounding-box samples needed for event-level physical-object correspondence; it contains no person identity labels and does not claim full per-frame identity continuity.
- Qualification media remains outside Git.
- Existing mandatory qualification gates remain authoritative until an ADR changes them.
- No evidence is reused across a behavior/hash change without explicit validity.
- Production CUDA never silently falls back to CPU.
- Formal offline qualification requires actual network isolation, not only an invalid proxy.
- Release metadata promotion occurs only after evidence exists.
- Any late functional fix reopens affected downstream qualification.

These constraints are intended to prevent the final Phase-1 task from becoming an unbounded debugging/qualification loop.
