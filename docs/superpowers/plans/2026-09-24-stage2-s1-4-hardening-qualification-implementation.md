# MAVI Stage 2 — S1.4 Track Evidence Set Hardening and Qualification Closure Plan

**Status:** Proposed implementation-grade execution plan for S1.4; documentation-only until independently reviewed and accepted.  
**Date:** 2026-09-24  
**Baseline:** `main@81b43dec32bec0c5e876d2df372503016c05dbdf` — PR #83 merged; S1.3 complete.  
**Parent plan:** `docs/superpowers/plans/2026-09-23-stage2-s1-track-evidence-set.md` §10 / §16.  
**Governing acceptance:** `docs/reviews/2026-09-23-visual-attributes-acceptance.md` B1–B6.  
**Qualification protocol:** `docs/qualification/2026-09-23-visual-attributes-qualification-plan.md`, especially §8, §10, §15–§17.  
**Scope:** S1.4 only — hardening, resource/bound evidence, disconnected end-to-end evidence, Task-10 rebinding and evidence-set acceptance closure.  
**Non-goals:** new selector/scorer behavior; new Evidence Set roles; new model or runtime dependency; VisualAttributeAnalysis; capability-binding v2; attribute models/search; Production qualification; CUDA hardware execution not already available.

---

## 1. Purpose

S1.1–S1.3 implemented the Track Evidence Set. S1.4 does not add another capability. It proves that the frozen S1 implementation is bounded, reproducible, operationally usable and correctly represented in qualification records.

The slice closes **B1–B6 only**. It must produce retained evidence that another reviewer can inspect without trusting prose in a PR.

The execution rule is:

> **qualify the frozen S1 identity; do not tune it while measuring it.**

The current pipeline profile is already the S1 behavior-bearing identity:

- profile id: `phase1-detection-tracking-v1`;
- schema: `1.1`;
- profile version: `1.2.0-candidate`;
- selector: `evidence-selector-v1-two-tier`;
- scorer: `quality-v2`;
- Representative cap: 65,536 B;
- supplemental cap: 163,840 B;
- EvidenceCrop run quota: 1 GiB.

The existing RTMDet qualification record already references the current pipeline-profile SHA and remains explicitly `pending`. S1.4 therefore does **not** change profile values merely to obtain a new hash.

If execution discovers a behavior-bearing defect, stop qualification, repair it in a separate implementation commit/PR, update the identity if required, and rerun every affected evidence item from the repaired head.

---

## 2. Entry gate

S1.4 execution begins only when all are true on one exact source head:

1. S1.1, S1.2 and S1.3 are merged.
2. `main` contains PR #83 or later with no S1 behavior change.
3. MAVI Quality Gate is green.
4. `python tools/verify_repo.py` passes.
5. no open P1/P2 against S1.
6. the pipeline profile, worker completion v3 contract, DB migration and web Evidence Set contract are unchanged after the chosen qualification head is frozen.
7. the exact commit SHA is recorded in the S1.4 report before authoritative measurements begin.

Moving the behavior-bearing head invalidates the entry gate. Documentation-only report edits after measurement may continue only when they cannot affect execution; the measured source SHA remains explicit.

---

## 3. Qualification identity and non-claims

Every retained S1.4 evidence record must name, where applicable:

- source commit SHA;
- pipeline profile id/version/SHA;
- selector/scorer/encoder version;
- completion schema/digest version;
- Python version;
- relevant package/runtime identity;
- OS/runtime variant;
- fixture/corpus id and SHA;
- command or workflow run;
- timestamp;
- result;
- limitation/non-claim.

S1.4 may close B1–B6 without claiming any of the following:

- Production qualification;
- CUDA qualification beyond previously recorded Development evidence;
- detector/model accuracy beyond existing qualification statements;
- Visual Attributes quality;
- attribute-model readiness;
- S2 capability-binding readiness.

The RTMDet manifest remains `unverified`, runtime qualification may remain `partial`, and the qualification JSON may remain `pending` if its other required gates are still pending. S1.4 must not cosmetically promote those records.

---

## 4. Evidence package

Create a dedicated retained record under a path such as:

`docs/qualification/stage2-s1/`

with:

1. `s1-qualification-summary.md` — human-readable B1–B6 report;
2. `s1-qualification-evidence.json` — machine-readable identities, measurements, workflow runs and verdicts;
3. small deterministic measurement outputs that are appropriate for Git;
4. hashes/identities for large or machine-local artifacts that are retained outside Git.

Do not commit operational video, private CCTV, binary crops, runtime/model packs, database dumps or multi-megabyte stress outputs.

The machine-readable record must make PASS impossible unless every required field for that B-item is present.

---

## 5. B1 — deterministic Evidence Set selector

### 5.1 Required proof

Re-run and retain evidence for:

- exact four-role vocabulary and canonical rank order;
- two-tier Representative behavior;
- scorer `quality-v2`;
- credible-occluder rule at `confidence >= confidenceFloor`;
- strict-improvement/tie behavior;
- NearView growth rule;
- EarlyDiverse window;
- LateDiverse refresh;
- separation/duplicate elimination;
- deterministic admission ordering;
- repeated execution stability.

### 5.2 Suites

At minimum include the existing selector/profile/quality/admission/scripted-corpus tests exercised by Task 10:

- `test_evidence_profile.py`;
- `test_evidence_quality.py`;
- `test_evidence_encoder.py`;
- `test_evidence_selector.py`;
- `test_evidence_admission.py`;
- `test_evidence_pipeline.py`;
- `test_evidence_scripted_corpus.py`;
- real-clip harness composition test.

Run a deterministic repeat test over the scripted corpus: same input/profile and runtime variant must produce the same roles, ranks, source-frame/offset choices, scores and artifact descriptor metadata. Exact JPEG bytes are required only within a runtime variant where the existing encoder contract promises that identity.

### 5.3 Real-clip measurement

Reuse the accepted real-clip corpus/harness used to resolve S1.2 F1. Record at least:

- Track count;
- Representative fallback rate;
- role admission rates;
- score distributions;
- crop-size distributions;
- omission reasons;
- duplicate/diversity behavior.

This is confirmation of the frozen defaults, not another parameter-tuning exercise.

**B1 PASS:** all deterministic suites green on the frozen head, repeated output stable, real-clip measurement consistent with the accepted two-tier/scorer design, and no selector default changed during qualification.

---

## 6. B2 — retirement, live-memory and staging lifecycle

### 6.1 Structural proof

Re-run the discriminating lifecycle tests proving:

- exact-once retirement;
- no same-update active+retired identity;
- no post-retirement reappearance;
- native mapping release;
- fresh MAVI id after backend-id reuse;
- FixtureTracker parity;
- one finalisation path for retirement and EOS;
- trajectory spool and Evidence Set candidate state removed from the live Track accumulator after finalisation;
- cross-attempt staging cleanup removes only earlier attempts for the same job.

### 6.2 RSS measurement

Add or use a measurement harness that records process RSS while processing a deterministic synthetic/fixture workload in which:

- Track duration can increase without increasing the number of simultaneously live Tracks;
- simultaneously live Track count can be stepped through several levels;
- retired Track count can grow while live count remains bounded.

Record:

- baseline RSS;
- peak RSS;
- RSS after warm-up;
- live Track count at samples;
- retired Track count;
- staged descriptor/artifact counts.

Acceptance is **shape-based**, not an arbitrary new RAM promise: after warm-up, increasing completed/retired Track history with a fixed live-Track envelope must not produce monotonic unbounded live-memory growth attributable to retained trajectories/candidates. A regression that retains per-Track history fails regardless of whether the machine still has spare RAM.

A controlled stress run should exercise meaningful concurrency; normal CI must not allocate a literal multi-gigabyte fixture.

### 6.3 Staging lifecycle measurement

Measure staging bytes through:

- one successful run;
- failed/retried attempt;
- superseding attempt cleanup;
- successful completion followed by platform janitor ownership.

Record maximum observed staging bytes and prove attempt isolation.

**B2 PASS:** lifecycle tests green, accumulator release directly tested, RSS shape supports the live-Track bound, and retry/staging cleanup is demonstrated without cross-attempt/job deletion.

---

## 7. B3 — byte, quota and request-body bounds

### 7.1 Per-crop bounds

Re-run adversarial encoder cases including high-entropy/noise, extreme aspect ratios and floor-size crops.

Prove:

- Representative <= 65,536 B when admitted;
- supplemental <= 163,840 B when admitted;
- reduction floor is respected;
- non-admissible supplemental evidence is omitted;
- mandatory Representative fallback behavior follows the frozen two-tier contract.

### 7.2 Run quotas and admission

Use deterministic fake/sparse artifact descriptors to exercise:

- mandatory Representatives first;
- NearView, EarlyDiverse, LateDiverse admission order;
- score-desc / canonical Track-id secondary ordering;
- EvidenceCrop aggregate <= 1 GiB;
- trajectory/other aggregate <= 512 MiB;
- per-artifact <= existing 64 MiB;
- quota boundary immediately below/equal/above limit;
- omitted staging objects removed.

No test needs to allocate 1 GiB of real JPEG bytes merely to prove arithmetic.

### 7.3 10,000-Track completion contract

Re-run the true worst-shape 10,000-Track v3 serialization/validation test and record:

- serialized request bytes;
- configured request-body limit;
- headroom;
- validation result.

The accepted S1.2 measurement is ~24.72 MiB; S1.4 records the exact final measurement rather than hard-coding that number as a pass condition.

### 7.4 Platform sealing bound

Exercise a scale harness that uses a sparse/fake content store where appropriate to measure validator/sealing/DB work without producing several GiB of physical test data.

Record:

- Track/Observation counts;
- artifact count;
- validation time;
- sealing/store transaction time;
- resulting DB rows;
- resulting accepted-evidence bytes or simulated byte accounting.

**B3 PASS:** all hard arithmetic boundaries discriminate at exact edges, 10,000-Track body remains below the configured bound with documented headroom, and scale execution does not reveal an unbounded algorithm or N+1 artifact-content read.

---

## 8. B4 — v3 contract, digest, persistence and rollback

Re-run the complete contract matrix on the frozen head:

- Python v3 schema;
- .NET v3 schema;
- cross-language golden fixture;
- digest v3 equality;
- v2 digest/replay compatibility;
- v3 exact replay/idempotency;
- role/rank validation;
- migration/backward read behavior;
- multi-crop sealing;
- compensation after mid-seal failure;
- compensation after transaction failure;
- evidence-key validation;
- Track Representative pointer integrity;
- Track-detail invariant failure behavior.

Retain the golden fixture hash and exact suite results.

**B4 PASS:** Python/.NET agreement is exact, v2 replay remains valid, v3 replay is idempotent, and every partial-failure case leaves neither partially published DB intelligence nor uncompensated newly sealed accepted evidence.

---

## 9. B5 — read/UI/operator acceptance

### 9.1 Automated acceptance

Re-run:

- Track-detail integration tests for 0/1/2/3/4 observations;
- historical Thumbnail-backed Representative;
- authorized EvidenceCrop reads;
- corrupt read-seam invariant failures;
- web Evidence Set contract/component/integration tests;
- source guards enforcing one Representative authority;
- Review and Investigation keyboard/accessibility behavior;
- full visual-QA matrix.

### 9.2 Real-video end-to-end path

Execute at least one real recorded video through the actual S1 path:

`Video -> VisionJob -> v3 completion -> seal/persist -> GET Track detail -> Investigation -> Review`

For the run, record:

- ProcessingRun/VisionJob ids in the local evidence record where safe;
- profile/runtime identity;
- number of Tracks;
- Evidence Set role counts;
- one Representative-only or partial-set example if naturally present;
- one four-role example if present;
- proof that crop URLs are platform-authored and authorized;
- Review source video and Evidence Set visible together;
- exact marker seeks;
- Search remains Representative-only.

If the real corpus does not naturally produce every UI error state, keep synthetic/fixture QA for unavailable crop/legacy/error states rather than corrupting real accepted evidence.

### 9.3 Accessibility/visual record

At minimum inspect 1366x768, 1600x900 and one ultra-wide viewport.

Confirm:

- source video remains primary;
- no Representative duplication;
- no crop distortion;
- no role truncation;
- selected state not color-only;
- keyboard contracts hold;
- crop failure does not disable video;
- video failure does not erase crop metadata.

**B5 PASS:** automated and real-video operator path evidence are green. The merge of PR #83 alone is not the B5 acceptance evidence.

---

## 10. B6 — Task-10 rebinding and qualification truth

### 10.1 Exact-head Task-10 CPU matrix

The current Task-10 workflow covers all relevant S1 behavior paths and runs CPU candidates on:

- Linux x86_64 / Python 3.12.14;
- Windows x86_64 / Python 3.12.10.

Run it on the frozen S1.4 qualification head, using `workflow_dispatch` if the qualification-only change set would not otherwise trigger it.

Retain:

- workflow run ids/URLs;
- source head SHA;
- per-variant result;
- uploaded evidence artifact identity/hash where practical.

### 10.2 Qualification record reconciliation

Before modifying any qualification JSON:

1. hash the current pipeline profile;
2. compare it with `models/qualifications/rtmdet-m-coco-phase1-v1.json.pipelineProfileSha256`;
3. if equal, record that the qualification record already binds the final S1 pipeline identity;
4. if unequal, treat it as identity drift and stop until explained.

Do **not** manufacture a new profile SHA by editing the profile in S1.4.

The qualification record remains `pending` unless all its independent required gates are actually satisfied. S1.4 may add/reconcile evidence metadata only if the existing schema and qualification policy permit it; otherwise keep S1 evidence in the dedicated S1 qualification record and cite it.

### 10.3 CUDA/E2E

Current policy:

- previously recorded Development CUDA runtime evidence is not a substitute for final S1 pipeline E2E;
- no stale pre-S1 E2E evidence may be presented as S1 evidence;
- if supported CUDA hardware is available during S1.4, rerun the appropriate Development S1 E2E and record it;
- if it is not available, explicitly record CUDA/E2E as pending/non-claim.

B6 does not require inventing unavailable hardware evidence.

### 10.4 Post-merge verification

After the S1.4 PR merges, verify the resulting `main` head with:

- MAVI Quality Gate;
- Task 10 Runtime Qualification for the final behavior-bearing identity;
- Task 17 Acceptance Validation;
- any other workflow triggered by actual S1.4 code/config changes.

**B6 PASS:** current CPU matrices are green on the final S1 identity, no qualification record points at a stale pipeline profile, unavailable CUDA/E2E evidence is explicitly pending rather than inherited, and exact-head/post-merge CI is green.

---

## 11. Disconnected end-to-end evidence

S1.4 must prove the S1 path without network resolution.

The authoritative disconnected run is a **host/local qualification action**, not hosted CI pretending to be offline.

Use the existing Offline Binary Kit/runtime/model installation path and record:

- bundle/runtime/model identities;
- network-disconnected condition;
- setup verification;
- worker start;
- real recorded-video process;
- v3 completion;
- sealed Track evidence;
- Track detail;
- Review/Investigation Evidence Set.

No package manager, model hub, CDN, checkpoint download or remote API may be required after disconnection.

Task 12 hosted CI remains a build/verification gate for Runtime Packs; it is not by itself the disconnected operator-path proof.

If the current Offline Binary Kit already contains every unchanged dependency, S1.4 does not rebuild it merely for a new application commit. It verifies the component relationship truthfully.

---

## 12. Performance measurements and reporting

S1.4 records measurements; it does not invent unsupported universal SLAs.

Minimum metrics:

| Area | Metrics |
|---|---|
| worker memory | baseline/peak RSS, live Track count, retired count |
| selector | CPU time/frame or sampled selector cost |
| JPEG | encode count, total/mean/p95 encode time, bytes by role |
| finalisation | per-Track and run-finalisation timing |
| staging | peak bytes, admitted/omitted bytes and counts |
| completion | JSON bytes, serialization/validation time |
| platform | validation, sealing and transaction time |
| persistence | Track/Observation/Artifact row growth |
| UI/read | Track-detail payload size for representative-only and four-role cases |

Where a metric has no pre-existing product limit, report the measured value and regression interpretation rather than declaring a new arbitrary PASS threshold inside S1.4.

A result is blocking when it violates a frozen bound, demonstrates unbounded growth, breaks an existing timeout/lease/request limit, or makes the supported workflow operationally unusable.

---

## 13. Recommended implementation structure

Keep S1.4 reviewable. Preferred sequence:

### PR/commit A — qualification harness and plan support

Only if required:

- small measurement harnesses;
- sparse/fake-store scale helpers;
- machine-readable S1 qualification schema/checker;
- no selector/profile behavior change.

Every new test/harness must first demonstrate a failure mode against an intentionally broken implementation or otherwise prove discrimination.

### PR/commit B — execute and record S1 evidence

- run bound/resource measurements;
- run real-video and disconnected acceptance;
- run Task-10 CPU matrix;
- write B1–B6 evidence;
- update acceptance register.

If no new harness code is needed, A and B may be one PR, but evidence and implementation changes must remain easy to distinguish.

### Post-merge

Run required `main` workflows and append/post a final closure record only if the repository convention requires post-merge evidence.

---

## 14. Stop conditions

Stop and amend/fix rather than weakening evidence if any occurs:

1. selector output is non-deterministic for the same input/profile/runtime;
2. profile hash differs from the qualification record unexpectedly;
3. RSS grows with retired history at fixed live-Track envelope;
4. a hard crop/run/body quota can be exceeded;
5. v2 or v3 replay/digest drifts;
6. rollback leaves accepted evidence or DB rows partially published;
7. real-video Evidence Set cannot be read through the platform boundary;
8. disconnected execution performs network resolution;
9. Task-10 CPU matrix fails on the frozen identity;
10. a P1/P2 appears in final review.

A stop condition does not become a qualification exception. Repair first, then rerun affected evidence.

---

## 15. Documentation updates at closure

When S1.4 is actually executed:

- update the Stage-2 acceptance register B1–B6 with exact evidence references;
- mark S1 closed only when B1–B6 are PASS;
- update both capability roadmaps from “S1 in progress” to “S1 complete”;
- record the exact final `main` SHA and post-merge workflows;
- retain non-claims for Production/CUDA/E2E as applicable;
- do not mark any C/D/E/F/G Stage-2 acceptance item PASS merely because S1 closes.

The next implementation slice after S1 closure is S2a Component Binding v2, not attribute-model inference.

---

## 16. Completion report template

The S1.4 completion report must contain:

- starting `main` SHA;
- exact final PR head;
- merge SHA;
- behavior-bearing source SHA used for measurements;
- files changed;
- profile id/version/SHA;
- schema/digest versions;
- B1–B6 verdict table;
- commands/workflow run ids;
- test counts;
- resource measurements;
- real-video E2E result;
- disconnected result;
- qualification-record reconciliation;
- CUDA/E2E non-claim or evidence;
- unresolved findings;
- independent cold-review result;
- post-merge exact-head verification.

S1 is complete only when this report and the authoritative acceptance register agree.
