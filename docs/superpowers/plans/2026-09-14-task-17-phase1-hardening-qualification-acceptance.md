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

---

## 5. Branch, PR and evidence discipline

Use one Task-17 topic branch from exact baseline:

`feature/task-17-phase1-acceptance`

Open one PR into:

`feature/task-10-rtmdet-bytetrack`

Within that PR keep these commit classes separate:

1. implementation/tests;
2. acceptance tooling/runbooks;
3. generated release locks or immutable release metadata;
4. evidence rebind;
5. closeout documentation.

Use the established release sequence whenever runtime/release metadata is affected:

**implementation frozen -> deterministic artifacts generated -> metadata rebound -> evidence attested**

If implementation changes after freeze, all downstream evidence tied to the prior frozen head is stale and must be regenerated.

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
  "events": [
    {
      "eventId": "person-001",
      "objectClass": "Person",
      "startOffsetMs": 4200,
      "endOffsetMs": 9100
    }
  ]
}
```

Rules:

- `Person` and `Vehicle` only;
- offsets are non-negative integer milliseconds;
- `startOffsetMs < endOffsetMs <= durationMs`;
- event IDs unique inside one manifest;
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

Matching is class-exact and one-to-one.

For interval matching use deterministic temporal IoU:

`intersection duration / union duration`

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
- duplicate-match count.

Tie-breaking for multiple candidate matches shall be deterministic: highest temporal IoU, then earlier Track start, then Track ID lexical order.

### Acceptance thresholds

Task 17 shall **not invent operational accuracy thresholds in code**.

Create a reviewed, versioned acceptance profile, for example:

`config/acceptance/phase1-acceptance-v1.json`

It shall contain:

- minimum temporal IoU used for matching;
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

### 8.1 Workflow

The harness shall:

1. verify `/api/health` and `/api/system/config`;
2. create or resolve the qualification Camera deterministically;
3. import the controlled MP4;
4. handle authoritative `video_duplicate` reconciliation rather than re-upload guessing;
5. queue processing;
6. poll processing until a terminal state with a bounded timeout;
7. require successful ProcessingRun completion;
8. query `GET /api/tracks?videoAssetId=...`;
9. page through opaque cursors without decoding them;
10. require every returned Track to belong to the imported VideoAsset;
11. resolve each Track detail;
12. verify representative-evidence content where present;
13. verify source-video Range streaming;
14. verify the Search contract can locate Person/Vehicle results as applicable;
15. calculate structural and optional ground-truth metrics;
16. emit one machine-readable evidence document;
17. exit nonzero on any acceptance failure.

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
- test/qualification environment identity;
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

Use qualification-candidate bundle mode until the release metadata is legitimately promotable.

A proxy pointed to an invalid endpoint is useful as an additional tripwire but is **not** by itself proof of a formally disconnected host.

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

## 19. Release metadata promotion

Only after all mandatory gates genuinely pass may Task 17 promote the release.

The controlled metadata update shall avoid hash-order ambiguity:

1. construct the intended final `runtime.json` bytes, including final platform variants, release-lock hashes and `qualificationStatus = "qualified"` only when schema rules allow it;
2. compute the final runtime-profile SHA-256 from those exact bytes;
3. construct the intended final model-manifest bytes with `verificationStatus = "verified"` and the matching `qualificationId`;
4. compute the final model-manifest SHA-256 from those exact bytes;
5. construct the qualification record against the **final** model-manifest/profile/runtime hashes;
6. set only genuinely evidenced mandatory gates to `passed`;
7. add evidence for every passed gate;
8. set `overallResult = "passed"` only when all required gates are passed;
9. write the mutually consistent runtime profile, model manifest and qualification record together as one metadata-rebind change;
10. rerun `tools/verify_repo.py` and all release-selection tests.

Intermediate bytes used to calculate hashes need not be committed in an inconsistent state. The committed rebind must be internally consistent as a unit.

Do not hand-edit hashes from memory. Generate/verify them from exact bytes.

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

## 21. Final disconnected acceptance

On a clean designated acceptance deployment:

1. validate final bundle bytes;
2. install with Internet unavailable;
3. start PostgreSQL/pgvector;
4. start Mavi.Api behind the production-equivalent host;
5. start the qualified worker;
6. create/resolve qualification Camera;
7. import controlled MP4;
8. remove the client-side import working copy;
9. prove managed source remains retrievable;
10. process successfully;
11. search Person/Vehicle Tracks;
12. open Evidence Review;
13. verify representative evidence;
14. verify native source-video playback/range;
15. execute ground-truth evaluation if applicable;
16. run failure/reprocess scenario;
17. inspect logs for attempted Internet calls/telemetry/licence checks;
18. retain machine-readable acceptance evidence.

This is the Phase-1 acceptance event. A green unit-test suite alone is not an offline acceptance event.

---

## 22. Proposed implementation files

Create:

- `sample-data/ground-truth/phase1-ground-truth.schema.json`
- `sample-data/ground-truth/phase1-example.json`
- `config/acceptance/phase1-acceptance-v1.json`
- `tools/phase1/phase1_e2e_check.py`
- `tools/phase1/evaluate_ground_truth.py`
- `tools/phase1/phase1-acceptance-evidence.schema.json`
- `tools/phase1/qualify_phase1_windows_host.ps1`
- `tools/phase1/qualify_phase1_linux_host.sh`
- `tools/phase1/tests/test_evaluate_ground_truth.py`
- `tools/phase1/tests/test_phase1_e2e_check.py`
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

1. add RED tests for ground-truth schema validation;
2. add RED tests for deterministic evaluation/matching;
3. add RED `ProcessingFailureRecoveryTests`;
4. add worker end-to-end contract RED tests;
5. implement only enough production changes to satisfy demonstrated defects;
6. add acceptance evidence schema;
7. add repository verification for all new tracked schemas/configs.

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

The workflow shall keep ordinary hosted validation separate from evidence-producing hardware jobs. Hardware/offline jobs must be `workflow_dispatch` and target explicit approved self-hosted runner labels; they must not silently fall back to generic GitHub-hosted runners when the required environment is unavailable.

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

## 27. Checkpoint E — deterministic release artifacts

From the frozen implementation:

- generate any new CUDA locks only from actually qualified hardware/runtime graphs;
- generate qualification-candidate bundles;
- record hashes;
- do not mix source-behavior fixes into artifact commits.

If hardware is unavailable, stop with those gates pending rather than inventing artifacts.

---

## 28. Checkpoint F — metadata rebind

After final immutable artifact hashes exist:

- update runtime profile;
- re-compute runtime hash;
- rebind qualification identities;
- update evidence references;
- promote only gates that have actual evidence;
- promote manifest/runtime/overall status only if all mandatory rules are satisfied.

Run release-selection and repository verification immediately.

---

## 29. Checkpoint G — exact-head attestation

On the exact rebound head run every applicable gate:

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

### Evidence/hardware

- Windows disconnected-install qualification;
- Linux disconnected-install qualification;
- Windows CUDA hardware qualification;
- Linux CUDA hardware qualification;
- Linux NVIDIA recovery/performance;
- CCTV-quality baseline;
- deployed Windows/IIS host acceptance;
- final disconnected end-to-end acceptance.

All evidence must name the exact source/release identities it exercised.

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

Task 17 has two truthful stopping points:

- the implementation PR may be **implementation-complete / evidence-pending** when all deterministic tooling and code are accepted but unavailable external hardware prevents final qualification; in that state Task 17 remains active and the release stays unverified;
- Task 17 is **fully complete** only when the current mandatory qualification set and final disconnected Phase-1 acceptance have actually passed.

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
- Ground truth contains Person/Vehicle temporal events, not identity labels.
- Qualification media remains outside Git.
- Existing mandatory qualification gates remain authoritative until an ADR changes them.
- No evidence is reused across a behavior/hash change without explicit validity.
- Production CUDA never silently falls back to CPU.
- Formal offline qualification requires actual network isolation, not only an invalid proxy.
- Release metadata promotion occurs only after evidence exists.
- Any late functional fix reopens affected downstream qualification.

These constraints are intended to prevent the final Phase-1 task from becoming an unbounded debugging/qualification loop.
