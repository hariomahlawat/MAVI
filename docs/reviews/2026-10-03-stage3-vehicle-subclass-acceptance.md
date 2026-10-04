# Vehicle Subclass — Stage-3 Acceptance Register

**Status:** Open. S3.1 is merged. S3.2a (T1–T6) and S3.2b-1 (T7/T8 and fixture-only T9 tooling) are merged. S3.2b-2 (real corpus intake and derivation) has executed event `2026-10-03-commons`: E1–E21 PASS (E17 NOT TRIGGERED). S3.2b-3 (Development-host T9 execution) is complete: F1–F6 PASS (attempt 2). S3.2c (pilot, T10) is pre-registered (G1–G3 PASS). The sample is drawn and verified (G4 PASS), and the blind packs await human labelling; G5–G9 are OPEN. Nothing is operator-exposed, and nothing is Production-qualified.\
**Date opened:** 2026-10-03\
**Baseline:** `main@379b7b22a3d8722d8c4d99df50794805494155aa` (merge of PR #150)

This register is the only authoritative exit gate for Stage 3 (`docs/architecture/README.md`, "Documentation precedence" item 4). Plans and runbooks reference these row IDs rather than keep a second acceptance list. The S3.2b-2 runbook's pre-flight checklist (PF1–PF21) is an evidence-collection aid that maps onto the E rows below.

**Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: commits, run IDs, or artefact SHA-256s with their retained location. Corpus bytes never enter Git.

## Current verdict

**ADR-016 ACCEPTED. MEASUREMENT TOOLING IMPLEMENTED AND MERGED:**
- **S3.1 plumbing:** PR #145;
- **S3.2a T1–T6:** PRs #146–#148;
- **S3.2b-1 T7/T8/T9 tooling:** PRs #149–#150.

**DEVELOPMENT MEASUREMENT IN PROGRESS:** S3.2b-2 complete (every E row PASS, E17 NOT TRIGGERED); S3.2b-3 complete (F1–F6 PASS); S3.2c pre-registered (G1–G3 PASS), sample verified (G4 PASS), with labelling to measurement (G5–G9) OPEN; S3.2d OPEN. **NOT OPERATOR-EXPOSED. NOT PRODUCTION-QUALIFIED.**

## Governing documents

1. `docs/decisions/ADR-016-detector-native-vehicle-subclass.md`: accepted 2026-10-02; the subclass source, vocabulary, resolution and measurement-first rule.
2. `docs/superpowers/plans/capability-roadmap.md` (sequence) and `docs/superpowers/plans/capability-implementation-roadmap.md` (Stage-3 technical impact).
3. This register.
4. `docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md`: the S3.2 parent plan (T1–T11).
5. `docs/qualification/stage3/s3-2b-real-corpus-intake-and-derivation.md`: the S3.2b-2 operational runbook.

Also binding: ADR-005, ADR-006, ADR-007, ADR-009, and the dependency/offline-packaging policy.

## Scope and completion levels

**Capability.** Detector-native vehicle subclass (`mavi-vehicle-subclass-v1` = `car | truck | bus | motorcycle`).
- Bicycle is excluded, because adding it would change the existing Vehicle Track population (ADR-016 §2). It is not a Phase-1 source class, so no Vehicle Track contains it.
- SUV, van and make/model are out of scope.
- The product meaning is "detector-reported vehicle type" (ADR-016).

**Measurement first** (ADR-016 §7). Subclass is measured on MAVI-held Development clips before any operator exposure. API, search and UI exposure is a later increment, and happens only if that measurement supports it.

These are four distinct levels. Completing one never implies the next.

| Level | Meaning | Rows | State |
|---|---|---|---|
| Implementation complete | the plumbing and the measurement tooling are merged with green exact-head and post-merge CI | A, B, C, D | **PASS** |
| Development measurement complete | real corpus intake, derivation, Development-host execution, the labelled pilot and its measurement exist (any expansion only if justified) | E, F, G, H | OPEN |
| Operator exposure | the API predicate, search and UI exposure of subclass, decided on measurement evidence and built as a later increment | X | OPEN |
| Production qualification | outside this register: Task 18 and the qualification record (`models/qualifications/rtmdet-m-coco-phase1-v2.json`, status `pending`) | — | not claimed |

**Stage 3 exit.** Stage 3 is complete only when:
- every row in A–G and X1 is PASS;
- H1 is PASS or recorded NOT TRIGGERED;
- X2 and X3 are PASS, or recorded NOT TRIGGERED when X1 declines exposure.

If exposure is declined, Stage 3 closes without operator exposure; a replacement source would then need its own ADR (ADR-016 §6) and its own register. **Completing S3.2b-2 (E rows) does not complete Stage 3.**

## A. Decisions

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| A1 | The subclass source is decided: detector-native (no classifier, model, dataset or dependency added) | PASS | ADR-016 §1, accepted 2026-10-02 |
| A2 | Vocabulary `mavi-vehicle-subclass-v1` = `car \| truck \| bus \| motorcycle`; bicycle excluded | PASS | ADR-016 §2 |
| A3 | Measurement first: no API, search or UI exposure before the Development measurement supports it | PASS (decision) | ADR-016 §7 |

## B. S3.1 — detector-native plumbing (PR #145)

**Evidence for all B rows.** Merge `d7508201b217261bed9979390ebfaa0bf61b8e18`. Post-merge runs on that commit:
- MAVI Quality Gate 37085090783;
- Task 10 Runtime Qualification 37085090808;
- Task 17 Acceptance Validation 37085090776;
- Vision Model Pack 37085090840;
- Task 12 Offline Runtime Pack 37085090787;
- Qualification Tooling Windows 37085090817;
- Task 10 Staging Security 37085090881.

All succeeded.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| B1 | The native class is carried through tracking unchanged and resolved once per Vehicle Track by a confidence-weighted vote that may abstain | PASS | `src/vision/mavi_vision/common/subclass.py`, `src/vision/tests/test_vehicle_subclass.py` |
| B2 | Three immutable, nullable Track fields with database-enforced states; historical and Person Tracks carry none | PASS | migration `20261002120000_AddTrackObjectSubclass` (check constraints), `tests/Mavi.IntegrationTests/TrackObjectSubclassPersistenceTests.cs` |
| B3 | Completion 3.3, with its own digest domain; 3.2 is still accepted and replayed | PASS | `contracts/schemas/vision-job-complete-v3.3.schema.json`, `contracts/test-vectors/vision-job-complete-v3.3-digest.json`, `control-plane-v3.3-invalid.json` |
| B4 | Pipeline profile `1.3.0-candidate` (schema 1.2, `vehicleSubclass` block with provisional `minShare`/`minMatchedDetections`); qualification-record policies re-derived; the record stays `pending` | PASS | `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, `models/qualifications/rtmdet-m-coco-phase1-v2.json` |
| B5 | Track-identity compatibility gate: output equals the pre-Stage-3 baseline apart from the subclass fields | PASS | `src/vision/tests/fixtures/vehicle-subclass-track-identity-gate-v1.json`, `src/vision/tests/test_vehicle_subclass_gate.py` |
| B6 | No API, search or UI exposure of subclass | PASS | no subclass reference in `src/platform/Mavi.Api` or `src/web` at the baseline |
| B7 | A Development evaluator attributes every measurement to its attested processing run | PASS | `tools/phase1/evaluate_vehicle_subclass.py`, `tools/phase1/tests/test_evaluate_vehicle_subclass.py` |

## C. S3.2a — measurement tooling T1–T6 (PRs #146, #147, #148)

**Evidence for all C rows.**
- Plan merge: `e5ccd4c635737d54408cc977fcd0a851cf71357c` (PR #146).
- T1 merge: `7172ba1e12cb05b2fc96998083037be833ebc304` (PR #147). Post-merge Quality Gate 37095921206 and Task 17 37095921352 succeeded.
- T2–T6 merge: `8fd15857cdb2a33baa1dd36361e714d9c312bd95` (PR #148). Post-merge Quality Gate 37111589024 and Task 17 37111589041 succeeded.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| C1 | T1 read-only measurement export (`Mavi.MeasurementExport`) bound to the run attestation | PASS | `tools/dotnet/Mavi.MeasurementExport`, `tests/Mavi.IntegrationTests/SubclassMeasurementExportTests.cs` |
| C2 | T2 Track-label evaluator mode | PASS | `tools/phase1/evaluate_vehicle_subclass.py --track-labels` |
| C3 | T3 prediction-blind sampler | PASS | `tools/stage3/sample_tracks.py`, `tools/stage3/tests/test_s32_sampler.py` |
| C4 | T4 labelling pack and static page | PASS | `tools/stage3/build_labeling_pack.py`, `tools/stage3/labeling/` |
| C5 | T5 freeze and adjudication | PASS | `tools/stage3/freeze_labels.py`, `tools/stage3/tests/test_s32_freeze.py` |
| C6 | T6 runner and requirement comparison | PASS | `tools/stage3/run_subclass_measurement.py`, `tools/stage3/tests/test_s32_runner.py` |

## D. S3.2b-1 — T7/T8 tooling and fixture-only T9 tooling (PRs #149, #150)

**Evidence for all D rows.**
- Plan merge: `9c6fb0367548cfecce8c07a66c44e904f844d9d8` (PR #149).
- Implementation merge: `379b7b22a3d8722d8c4d99df50794805494155aa` (PR #150). Post-merge Quality Gate 37121910501, Task 17 37121910490 and Qualification Tooling Windows 37121910487 succeeded.
- On PR #150's final head, `repo contracts` ran the Stage-3 suite with media tests required (`MAVI_REQUIRE_MEDIA_TESTS=1`).

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| D1 | Approved media binaries only from a verified MAVI FFmpeg pack; never PATH | PASS | `tools/stage3/media_tools.py` |
| D2 | Media probe, with an exact port of the Phase-1 MP4 policy pinned by a shared vector consumed by .NET and Python | PASS | `tools/stage3/probe_media.py`, `contracts/test-vectors/phase1-mp4-container-policy-v1.json`, `tests/Mavi.Application.Tests/PhaseOneMp4ContainerPolicyVectorTests.cs` |
| D3 | Source-pool freeze tool from source-side facts only | PASS | `tools/stage3/freeze_source_pool.py` |
| D4 | T8 derivation with exact per-mode authorisation, pinned args and atomic output; T3 schema-validates derivations | PASS | `tools/stage3/derive_mp4.py`, `tools/stage3/sample_tracks.py` |
| D5 | Ingestion-map validation and T9 tooling against a stub API only (fresh catalogue, journal, no run reuse, `--verify-sample`) | PASS | `tools/stage3/ingestion_map.py`, `tools/stage3/ingest_source_pool.py`, `tools/stage3/tests/test_s32b_t9.py` |
| D6 | S3.2b contracts registered; `tzdata` declared; CI FFmpeg for the Stage-3 tests | PASS | `contracts/schemas/vehicle-subclass-*-v1.schema.json`, `tools/requirements.txt`, `.github/workflows/quality-gate.yml` |

## E. S3.2b-2 — real corpus intake and derivation (runbook PF items in brackets)

Event `2026-10-03-commons` evidence entered 2026-10-04; controlled store event root `Stage3/S3.2/2026-10-03-commons` (store-relative event root; all evidence paths below are relative to it). The canonical evidence chain is two write-once manifests, and it binds every off-repository evidence file by store-relative path and full SHA-256. The rows below cite entries of either manifest by ID; entry IDs are unique across the chain.
- Manifest v2, `evidence/s3-2b-2-evidence-manifest-v2.json`, SHA-256 `e28ddbadcf3fa62cb544ffbe445dec920f6d55b05e01e4870650f2bfce31cc7e`, 43 entries. It holds the pre-merge evidence and supersedes `evidence/s3-2b-2-evidence-manifest.json`. It is not modified.
- The supplement, `evidence/s3-2b-2-evidence-manifest-supplement-e14.json`, SHA-256 `13fdbf3acbc7a81f19a2447070b70b2e39d4adc8c7c2dc49af915c688bac9872`, 2 entries. It extends v2 by v2's full SHA-256 and holds the post-merge E14 evidence: `binding-check-16b` and `verify-repo-post-merge`.

All rows started OPEN. Evidence is hash-only; bytes stay in the controlled store. The ingestion map's commitment (E13, E14) is deliberately placed in S3.2b-2. The plan's slice table lists it under S3.2b-3; this register moves it earlier so that it is fixed before the host exists, and starts nothing.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| E1 | Official release and source retained: name, version, official URL, retrieval date [PF1] | PASS | manifest entry `release-record` (`releaseRecordSha256` `325f20554354fb6b9bcc607c8c845b6ab27455dea320d1db16eaef8e4994ecb3`; 14 exact Commons revisions, retrieved 2026-10-03) and `files-inventory`; per-file receipts and Commons metadata are listed with sizes and SHA-256s in the record's `files[]` |
| E2 | Exact terms/licence retained, with SHA-256 equal to `licence.textSha256` [PF2] | PASS | manifest entry `licence-statement` (equals the record's `licence.textSha256`) |
| E3 | R-5 determination completed and recorded in the release record [PF3] | PASS | manifest entry `release-record` (determination `s3-2-commons-2026`: R-5 Hari Om Ahlawat, 2026-10-03; rights `PERMITTED_FOR_ENGINEERING_USE`, privacy `PERMITTED`; `evaluate`/`create-derivatives` granted, `train`/`run-operationally`/`redistribute-derived-weights` not-granted; share-alike ruling `PERMITTED` for internal, undistributed transcodes; purposes `benchmarking`, `development`), `purpose-approvals`, `r5-package` |
| E4 | Release record parses (`parse_release`) [PF4] | PASS | manifest entry `authorisation-report`: the record parses |
| E5 | `verify_release_files` clean against a root outside Git [PF5] | PASS | manifest entry `authorisation-report`: `problems 0`, root outside Git |
| E6 | No selected member excluded [PF6] | PASS | manifest entry `release-record`: `excludedMembers` is empty |
| E7 | Every selected member authorised for `benchmarking` + `development` [PF7] | PASS | manifest entry `authorisation-report`: every member `evaluate: OK` and `create-derivatives: OK` |
| E8 | Every selected member has a valid probe matching its release SHA-256 [PF8] | PASS | manifest entrys `probe-<sourceSha256>` (14), and `source-pool` (`probeSha256` per member) |
| E9 | Each selected member confirmed derivable before the pool freeze [PF9] | PASS | manifest entry `candidate-review`: every member one video stream, transcode-eligible, `create-derivatives` granted, before the freeze |
| E10 | Intended derivation mode recorded before the pool freeze [PF10] | PASS | manifest entrys `ledger` (intended mode `transcode` and reason per member, before the freeze) and `selection` |
| E11 | 6–10 member `pilot` pool frozen [PF11] | PASS | manifest entry `source-pool` (`fe72e2e9d055259d66042b07e104de14504e93ec3e9098c42fbc581ff79eca06`): `kind: pilot`, 8 members |
| E12 | Pool record or digest committed on `main`, ancestry-valid on the S3.2b-3 checkout, and `tools/verify_repo.py` passes on that commit [PF12, PF20] | PASS | Mode B digest `docs/qualification/stage3/s3-2-source-pool.sha256` (65 bytes) on `main` at `d12a352c10b5f12c967f62768490c824028e94a4` (PR #152); `verify_repo` PASSED at that commit |
| E13 | Ingestion convention committed on `main` before the map, where used, and `tools/verify_repo.py` passes on that commit [PF13, PF20] | PASS | `docs/qualification/stage3/s3-2-ingestion-convention.md` (blob SHA-256 `b52554e36ff4a026a7f355cfea79ae7a620b3f9fcd55a2e235f03f4e78b41982`) on `main` at `d12a352c10b5f12c967f62768490c824028e94a4` before the map; names no member; `verify_repo` PASSED at that commit |
| E14 | Ingestion map committed or digest-bound, ancestry-valid, and validated, and `tools/verify_repo.py` passes on that commit [PF14, PF20] | PASS | Mode B digest `docs/qualification/stage3/s3-2-ingestion-map.sha256` (65 bytes) on `main` at `fa096ca72597aac497db3765a2f497e6424c9ea6` (PR #153) binds map `ingestion/ingestion-map.json` `46a014e342fbdb9dc3bf98cf6f5f3bd505da524fda191d6a0987260f3eba7c95` (convention at `d12a352c10b5f12c967f62768490c824028e94a4`). §16(b) on a checkout of that `main` (pool commit `d12a352c`, map commit `fa096ca7`; pilot kind, pool invariants, release match, `ingestion_map.check`) passed: `evidence/e14-binding-check-fa096ca7.txt` `6e1520a9ac5ce532463c0bde2ab7800da7b77fec5b1ab87e2daede241435123f`; `tools/verify_repo.py` PASSED at that commit: `evidence/e14-verify-repo-fa096ca7.txt` `f3b21c5a0dc5e90b79c1087ce7888107029d02f1639d1794f1d09dd90a06ea99`. Both are bound (path, size, full SHA-256) as entries `binding-check-16b` and `verify-repo-post-merge` of the canonical, write-once supplement `evidence/s3-2b-2-evidence-manifest-supplement-e14.json` `13fdbf3acbc7a81f19a2447070b70b2e39d4adc8c7c2dc49af915c688bac9872`, which extends manifest v2 `e28ddbadcf3fa62cb544ffbe445dec920f6d55b05e01e4870650f2bfce31cc7e` without modifying it |
| E15 | Exactly one valid T8 `__run1` derivation per pool member (`load_derivations`) [PF15] | PASS | manifest entry `load-derivations` (§16(a) output: exactly one valid `__run1` per member) and the 9 `derivation-<sourceSha256>-run1/run2` entries |
| E16 | Remux/transcode authorised (`create-derivatives`) wherever used [PF16] | PASS | manifest entry `post-t8-checks`: every manifest `operations: ["create-derivatives"]`, `blockers: []` (all 8 transcode) |
| E17 | First real remux determinism repeat byte-identical (NOT TRIGGERED if remux unused) [PF17] | NOT TRIGGERED | Remux was not used (no H.264 source) |
| E18 | First real transcode determinism repeat byte-identical (NOT TRIGGERED if transcode unused) [PF17] | PASS | Manifest entries `determinism-manifest` and `determinism-report`. Evidence manifest `evidence/e18-determinism-evidence.json` (SHA-256 `bd19602338d1c782e21ded7cdbde1930a6ff563479d004c22de8b9127d90f4e6`) names, off-repository, the retained report and both run directories for the first real transcode (pool member with source SHA-256 `2c75b1ae879ebfadb7473d24e29b34c072430cabe8f0b5e5e68f68e58ab372d2`). Report SHA-256 `ae310818e8fb6194e06dd56d33ff3e00c85c08f91f8c03afbc0eff7cbe7464ab`; `__run1/video.mp4` `ffb262545d9ca08a3d1a5d44166ae5e0d6f319e243732a7d75bc0a081e55d98d` = `__run2/video.mp4` `ffb262545d9ca08a3d1a5d44166ae5e0d6f319e243732a7d75bc0a081e55d98d`; `__run1/derivation-manifest.json` `b45d2d156e0e5a0c29558bfe711f00bd74094e720253240d672398f9adc51998` = `__run2/derivation-manifest.json` `b45d2d156e0e5a0c29558bfe711f00bd74094e720253240d672398f9adc51998`; both pairs byte-identical |
| E19 | Every derivation's `importLimitBytes` equals the intended S3.2b-3 host's `VideoImport:MaximumFileSizeBytes` [PF18] | PASS | manifest entry `import-limit` (`evidence/e19-effective-import-limit.json`, SHA-256 `b6bd239e5798d4fa1d42442f6b7e81e3ddcbc79cd12c9f3d3f36ee95d01e1bc1`): effective `VideoImport:MaximumFileSizeBytes` 3221225472 from `appsettings.json` (blob `88d59a59dfa00606296179efae1a98ddec26f0b5cf5a5de81b4932d79bb94e74`); `appsettings.Development.json` (blob `336bd7bd20efd3735533f3431cb0901f9e7aace6f146dd53011f47c29b2c6963`) and the Development machine configuration (file `40e2b14ed04709a0c5b19ae6ed7b5059270c12581962652e8608ae72b4c6940c`) set no value; no `MAVI_MACHINE_CONFIG` and no `VideoImport__*` environment variable in process, user or machine scope; all 9 derivations' `importLimitBytes` equal it |
| E20 | No corpus media, archive, frame, crop or log committed to Git [PF19] | PASS | Manifest entry `git-audit`. PF19 audit `evidence/e20-git-audit-8304aed4.txt` (SHA-256 `b9dfb5858a10e92170a00c071cf0bc7f276d81dac9042dc5e78cc28324fe34bb`), retaining every command and its output, of commit `8304aed46dde6d7644780b27ed56bf995bce3d44` against the pre-event baseline `3885d020007bb649f7f6262f0a50afc4ff115a66`: (1) `git ls-tree -r --name-only` inventory, 1575 tracked paths; (2) changes since the baseline are exactly the pool and map digests, the convention and this register; (3) all 89 tracked media/image/archive/log paths are byte-unchanged since the baseline; (4) no tracked path carries an event or controlled-store marker; (5) no tracked blob matches any of the 226 files in the event store, the acquisition and discovery stores or the scratch area (frames, contact sheet, logs) by SHA-256; (6) the event-changed files contain no local path or member name. Result CLEAN. The only later change (this row's text) is in this register |
| E21 | One verified FFmpeg/ffprobe pack identity retained for the event: each tool's `{version, sha256}` and the manifest SHA-256. Every probe's `ffprobe`, every derivation's `sourceMedia.ffprobe`/`outputMedia.ffprobe`, and every remux/transcode `ffmpegVersion`/`ffmpegSha256` equal it (plan §20) [PF21] | PASS | manifest entrys `pack-identity` (`media-tools/pack-identity.json` `94e66e790ac36a6a076e50181705a7a71c66461b19f9bc25cbbd637fe9cf26f0`: ffprobe 9.0.1 `19202b23c0043f15ad1b7bce2344f406fd52bd6efd8f995ce02e7392a1cec52f`, ffmpeg 9.0.1 `72a489eccd008c2ec2c0a5856c5c75bc3d8bbfa90166c4566865c246445e6aa3`, pack manifest `604b387d4d2bbb4535797a0517f19c467409c7d6756531527d16cd46f5463ed7`) and `pack-consistency` (retained §16(c) output `evidence/e21-pack-consistency.txt` `dadd95521d209f603d160fb40867a38769ea5801dddeec3b071877a184eb0c40`): result `pack-consistent` for the live pack, 14 probes and 9 derivation manifests |

## F. S3.2b-3 — Development-host execution (T9)

S3.2b-3 may be scheduled only when every E row is PASS (or NOT TRIGGERED, for E17/E18).

Executed 2026-10-04 on `main@49a5566d78c91e2a1d99fd7a62b13b76401adead`, with every E row PASS. The worker attests `maviCommit` `49a5566d…`, and the API and T1 exporter were built from that commit with no source change. Paths below are relative to the controlled-store root.

**Evidence chain.** The canonical, write-once S3.2b-3 evidence manifest is `S32T9-a2/host-evidence/s3-2b-3-evidence-manifest.json`, SHA-256 `27d96605079e4039a5731bc7cf10917dba98bea37bad67b55519e92aa18d9f27`, with 30 entries. Each entry gives a path, size and full SHA-256. The rows below cite its entry IDs. It names the S3.2b-2 chain (manifest v2 and the E14 supplement) by hash and leaves both unmodified.

**Attempts.**
- **Attempt 1 failed and was not adopted.**
  - Catalogue `mavi_s32_t9_20261004`; media and evidence roots under `Stage3/S3.2/2026-10-03-commons-t9-host`.
  - It created 8 cameras, imported 1 video and queued 1 run. Inference completed, but finalization failed with `vision_finalization_exhausted`: 0 of 225 evidence crops were accepted. It wrote no export and no execution record.
  - Cause: a path-length-dependent product defect, outside this slice. Accepted-evidence publication (`DurableFilePublication.Publish`) calls `MoveFileExW` with a plain path. Under the `Mavi.Api.exe` app host, which is not long-path aware, it fails once the temporary path exceeds 260 characters; that root produced about 265.
  - T9 refuses to resume a terminally failed journalled run (`t9_run_failed`).
  - Entries: `a1-outcome`, `a1-catalogue-creation`, `a1-journal` and the `a1-log-*` entries.
- **Attempt 2 is the measured attempt.**
  - New catalogue `mavi_s32_t9_20261004_a2` and new media and evidence roots `S32T9-a2/m` and `S32T9-a2/ev`. A new journal and a new export root sit under `S32T9-a2/t9`.
  - The API ran as `dotnet Mavi.Api.dll`.
  - Only runtime layout and orchestration changed: shorter roots and the launch command. Product, worker, T9 and T1 code are unchanged. The profile, packs, binding, T9 contract and evidence content are unchanged.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| F1 | Fresh, dedicated Development catalogue and media store, created after the pool freeze | PASS | Entry `a2-catalogue-creation`: the database was created 2026-10-04T03:04:57Z, after the pool-freeze commit `d12a352c`. At creation it had 0 application tables, empty media and evidence roots, and the root did not previously exist (the tool refuses to reuse one). T9 started with a new journal, and its freshness gate (`t9_catalogue_not_fresh`) admits only state the journal explains. It passed, so the catalogue was empty before the first mutation. The first cameras were created at 03:06:15Z. After the run the catalogue holds exactly the 8 cameras and 8 videos T9 created (entry `a2-audit-r2`). Attempt 1 state was not adopted: separate database, roots and journal. Entry `a2-ordinary-catalogue-untouched`: the ordinary Development catalogue and media were not used; the default machine configuration is byte-identical to E19; no ordinary media or evidence file changed after 2026-09-24. |
| F2 | Real Model Pack and runtime on the Development host | PASS | All 8 attestations carry one producer identity (entry `a2-audit-r2`): Model Pack `mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700` and Runtime Pack `mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d`. Its `runtimeVariant` is `windows-x86_64-cuda` and its `runtimePackSource` is `installed-pack`. The CUDA variant was a deliberate Development device decision. The `componentBindingSha256` `7ef226193232b90b0a20f8648a95f21e0bbc9416b353605c9be6d81262abe205` equals committed `phase1-bindings-v2.json`, whose `windows-x86_64-cuda` entry is that Runtime Pack. The device used is `cuda:0` (GTX 1650 Ti, CUDA 12.4, torch `2.6.0+cu124`), and there was no substitution. Worker launch verification is entry `preflight-worker-verify-cuda`; the worker log is `a2-log-t9-worker`. `Test-MaviEnvironment -Profile Development` PASSED (entry `a2-test-environment`); it checks the CPU installation and is a generic Development check. F2 PASS means the real, bound CUDA Runtime Pack and Model Pack produced this Development measurement. It is not CUDA Production qualification: the qualification record and its `windows-x86_64-cuda` entry stay `pending`. |
| F3 | Shipped `1.3.0-candidate` pipeline profile measured (T9 profile identity gate) | PASS | Profile `src/vision/config/pipelines/phase1-detection-tracking-v1.json`, from the bytes T9 and T1 used: schema `1.2`, id `phase1-detection-tracking-v1`, version `1.3.0-candidate`, vocabulary `mavi-vehicle-subclass-v1`, SHA-256 `afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf`. That hash equals the qualification record's `pipelineProfileSha256`. Every attestation, every export and the execution record's `measuredProfileSha256` bind it (entries `a2-audit-r2` and `a2-export-*`). `VideoImport:MaximumFileSizeBytes` is still 3,221,225,472 with the E19 sources unchanged (entry `a2-post-t9-config`). |
| F4 | T9 complete for every pool member (journalled runs, no reuse) | PASS | Attempt 2 exited 0 for all 8 frozen members (entries `a2-journal` and `a2-log-t9-run`). For each member, T9 created or bound the camera, imported the T8 `__run1` `video.mp4` through the product API, queued a new run, journalled it before polling, saw `Completed`, and ran the T1 export. Every API run ID and asset equals the journalled one, and the API's latest run is that `Completed` run. The T8 bytes are unchanged. There was no missing, extra or duplicate member, no adopted asset and no outside run (entry `a2-audit-r2`). Runs: `01a104e0-6118-7e77-97dd-287b1a853f47`, `01a104e1-d460-75b3-b0d8-8f460107fcdd`, `01a104e3-9b43-7779-94a6-2f892ce6c9a2`, `01a104f1-7cf8-7df1-9962-818347d58b19`, `01a104f2-e6ff-7444-9d83-f0cb7c0af302`, `01a104f3-a6ab-7f41-bd6e-c3970e90798d`, `01a104f8-82ee-7b51-9fa7-3016d106ad5a`, `01a104f9-77dc-75dc-a55e-10a8bbaa0ca4`. |
| F5 | `vehicle-subclass-t9-execution-v1` record valid | PASS | Entry `a2-execution-record`: `S32T9-a2/t9/vehicle-subclass-t9-execution.json`, SHA-256 `4750e4f4d2efeb5143a9bc2405f61bcb57cc730097d90ae41653cb665258066c`. The merged T9 tool wrote it after its own exit checks. It re-validates against the schema and is canonical (entry `a2-audit-r2`). It has 8 members, pool `fe72e2e9…` at `d12a352c`, map `46a014e3…` at `fa096ca7`, and release `325f2055…`. |
| F6 | Exact run, export and provenance bindings: one producer identity, the measured profile, exports bound to derivations | PASS | Entry `a2-audit-r2` (`t9-attempt-2-audit-r2.json`, SHA-256 `929ece88a86903cfc20d5da8c207b7801016915a876776aebea523e9864b469a`) records 91 of 91 checks passing. They cover: one run1 derivation per member, and each derivation bound to its pool member and release; each export's `video.sourceSha256` equal to its T8 `outputSha256`; each export run being the journalled `Completed` run; one export per member, with no duplicate run, asset or source; each attestation hash equal to the record; one producer identity across the 8 attestations, binding the measured profile and `maviCommit` `49a5566d…`. It supersedes the r1 audit (`a2-audit-r1-superseded`), whose run1 check was wrong: the E18 determinism repeat makes one run2 manifest byte-identical to its run1. Exports, as `a2-export-<run>`: `214ac272f9b51dbe1086d755b1d75c7c6b46a8fd724b15ba8c149b886393055d`, `86a83c57c1902987cb3e405e724bfe379ce3c7431dc58cc20332bb4b33709a53`, `8e6a6e8ba4092d39ab2d22e04cba3c2e7812c51d8d8d0d931a707f5169e8f074`, `b716876b351d8a0ad04394f259bb135462de65e1a06dc62032b9d8acbc9fe62f`, `ccc2d91703981c86f303052d906088a65516bb99db7d324f6c4069a17756cef5`, `e476052cc3fb1911b8b6193db23b37d9513477b4cc67c840fd7834d08243fefc`, `6de3ab4ce4b7b81bab038f6527db8b823d3d343597f2672db84ca703d498e426`, `a75eec27cbcaa6980efa35cdf5a6d49abc670c37292860f4a6eac19c0c1b37c5`, in run order as listed in F4. |

## G. S3.2c — pilot (T10)

**Pre-registration (merged 2026-10-04 in PR #156 as `main@d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9`; at that point nothing had been sampled, packed, labelled or measured).** Both documents are fixed before any T10 result exists. The T9 exports were read only for provenance and identity (attestations, run, video and source bindings); no subclass value, distribution or confidence was read.
- **Requirements:** `docs/qualification/stage3/s3-2-subclass-requirements.json`, SHA-256 `ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75`, canonical JSON, schema-valid.
  - The support floor is `minimumSupport.evaluablePerClass` 30 and `evaluableTotal` 30, with outcome `insufficient-support` below it. This is the plan's proposed value (§13), adopted by the owner's instruction of 2026-10-04.
  - Every operational minimum is `null`: coverage, and per-class precision and recall. No owner-approved operational requirement exists, and none may be chosen from T9 or T10 output.
  - The pilot is therefore a valid descriptive Development measurement, and no pass or fail operational claim can be made. The mechanism and exposure decisions (X1) may stay open after the pilot.
  - **How T6 applies the floor.** Support is checked first: a criterion whose evaluable support is below its `minimumSupport` (30 per class, 30 for the total) is `insufficient-support`. With adequate support, a `null` minimum is `no-requirement`. This includes the all-`null` case. The T6 repair to `run_subclass_measurement.status()` and its tests are on `main` at the same commit.
- **Labelling guide:** `docs/qualification/stage3/s3-2-labeling-guide.md` (`mavi-vehicle-subclass-labeling-guide-v1`), SHA-256 `c5f8be38be9977ea05692e1e9d45d4ca7ea9b200629316f6375640778a251fc5`. It is canonical UTF-8 with LF line endings; `.gitattributes` keeps this path at `eol=lf`, so the working-tree bytes equal the blob that T4 binds.
- **Post-merge binding (2026-10-04).**
  - On a clean checkout of `main@d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9`, `artefacts.git_binding` binds both files at that commit, with the same paths and checks T3 and T4 use. Each is byte-identical to its blob there: requirements `ca28702f…`, guide `c5f8be38…`.
  - The guide passes `canonical_text`, the requirements validate against `vehicle-subclass-requirements-v1`, and the repaired T6 ordering is present.
  - `tools/verify_repo.py` PASSED at that commit.
  - T3 and T4 must name `d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9` (or a later `main` commit carrying the same bytes) as `--requirements-commit` and `--labeling-guide-commit`.
  - The registered SHA-256s are pinned in `tools/stage3/artefacts.py` (`REGISTERED_REQUIREMENTS_SHA256`, `REGISTERED_LABELING_GUIDE_SHA256`). An invariant test ties them to the committed files, so changing either file needs an explicit, reviewed change to the registration. A later deliberate revision is a new governed pre-registration, with a fresh sample, packs and labels (plan §13).
- **Owner decisions (2026-10-04, Hari Om Ahlawat):**
  - The guide is approved, as plan §5 and §19 item 3a require. The approval was reaffirmed for exactly SHA-256 `c5f8be38be9977ea05692e1e9d45d4ca7ea9b200629316f6375640778a251fc5` after the review fixes.
  - Savita is confirmed as the independent overlap reviewer for S3.2c/T10.
  - The requirements stay as pre-registered: a support floor of 30 per class and 30 overall, and every operational precision, recall and coverage minimum `null`. No operational threshold may be derived after viewing T9 or T10 results; T10 stays a descriptive Development measurement unless a separately governed threshold or exposure decision is made.
- **Independence conditions for G5–G7** (owner, 2026-10-04): the overlap reviewer never sees MAVI's predicted subclass, nor the primary reviewer's labels before her own overlap labels are frozen. The two reviewers do not discuss or reconcile individual cases before both label sets are frozen. Adjudication happens only afterwards, under T5.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| G1 | Requirements committed before any result is inspected | PASS | `docs/qualification/stage3/s3-2-subclass-requirements.json` SHA-256 `ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75`, committed on `main` at `d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9` (PR #156) and bound there (post-merge binding above). The floor is 30 per class and 30 total; every operational minimum is `null`. No T10 sample, pack, label or result existed when it was committed. The sample and packs were created afterwards, bound to it (G4, G5). T3 fails closed on this exact identity: `sample_tracks._requirements()` keeps the git binding (file equals the named commit's blob, and that commit is an ancestor of HEAD) and schema validation. It also requires the bound SHA-256 to equal the registered `artefacts.REGISTERED_REQUIREMENTS_SHA256` (`ca28702f…`), refusing otherwise with `requirements_not_preregistered`. So a later commit carrying changed requirements is refused even when the caller names it, while `d520db10`, or any later ancestor with the same bytes, is accepted. Tests in `tools/stage3/tests/test_s32_preregistration.py` cover this, including that the T3 refusal tests fail when the pin is removed. T6 then refuses requirements differing from the ones each sample bound. |
| G2 | Labelling guide committed | PASS | `docs/qualification/stage3/s3-2-labeling-guide.md` (`mavi-vehicle-subclass-labeling-guide-v1`) SHA-256 `c5f8be38be9977ea05692e1e9d45d4ca7ea9b200629316f6375640778a251fc5`, committed on `main` at `d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9` (PR #156), canonical, and bound there. The owner approved this exact hash on 2026-10-04 (owner decisions above). It was committed before any pack exists. T4 fails closed on this exact identity: `build_labeling_pack._guide()` keeps the git binding and the canonical-text check, and also requires the bound SHA-256 to equal the registered `artefacts.REGISTERED_LABELING_GUIDE_SHA256` (`c5f8be38…`), refusing otherwise with `labeling_guide_not_preregistered`. A later, canonical, committed but modified guide is refused even when its commit is named. Identical bytes at `d520db10` or a later ancestor are accepted. This is covered by the same tests, and the T4 refusal test fails when the pin is removed. |
| G3 | Independent overlap reviewer confirmed | PASS | The owner confirmed Savita as the independent overlap reviewer for S3.2c/T10 on 2026-10-04 (Hari Om Ahlawat), under the independence conditions above. The primary reviewer stays R-4 Aarav (plan §10). |
| G4 | Sample binds exactly the T9 export and derivation sets (`--verify-sample`) | PASS | Pilot sample `S32T10/pilot/sample.json` (paths relative to the controlled-store root), SHA-256 `5f6fb581e8ce3d2e99022445cbc9e0fae935138ffd4899db28bd347ecf52c7b3`. It was drawn 2026-10-04 by T3 at `main@3cbe245b`: algorithm `s3-2-video-quota-diversity-v1`, design `continuation` with no parent sample, seed `s3-2c-pilot-2026-10-03-commons-v1`, target 120, overlap fraction 0.2. The result is 120 selected and 24 overlap Tracks (⌈0.2 × 120⌉), with no duplicates and the overlap inside the selection. The sampling saw only Track class, timing and evidence; no subclass or confidence field is in the sample. It binds the registered requirements `ca28702f…` at `d520db10` (T3 pin). It binds exactly the 8 export SHA-256s and the 8 `__run1` derivation-manifest SHA-256s named by the T9 execution record `4750e4f4…`, and its release `325f2055…`. `ingest_source_pool.py --verify-sample` against that record: `sample verified`, exit 0. Evidence: the write-once manifest `S32T10/pilot/s3-2c-evidence-manifest-pre-labelling.json`, SHA-256 `f66bbcc77ad94c520c3f52617fc3f821b4c5dd4a731861b7d8e0db7c9188d8f0`, entries `sample`, `t3-log` and `t9-verify-sample`. |
| G5 | Blind primary and overlap labelling | OPEN | Packs built 2026-10-04 and verified (32 of 32 checks, manifest entry `pack-verification-r2`). Neither is labelled yet. The primary pack is for R-4 Aarav: `packSha256` `44e3592e024a6f2de57ede4255a6cb6a900df0f7999750e95b0607ac4e6b17bf`, 120 items, seed `s3-2c-pilot-primary-v1`. The overlap pack is for Savita: `packSha256` `c0f613006cfd3604f9e319b35a9a27ebfbe4f0e8677c74445a5cbafb750321a2`, 24 items, seed `s3-2c-pilot-overlap-v1`, parent the primary pack. Both bind the sample, its exports, the measured profile `afb03b6c…` and the registered guide `c5f8be38…` at `d520db10` (T4 pin). |
| G6 | Adjudication completed where needed | OPEN | |
| G7 | Labels frozen | OPEN | |
| G8 | T6 measurement and requirement comparison produced | OPEN | |
| G9 | Threshold freeze decision recorded on the measurement (ADR-016 §3). Either `minShare`/`minMatchedDetections` are frozen at the measured profile's values; or any change is a new pipeline-profile version, which needs its own Development tuning/evaluation path and a new measurement before G9 can PASS | OPEN | |

## H. S3.2d — expansion (T11)

| ID | Requirement | Status |
|---|---|---|
| H1 | Expansion undertaken only if the pilot evidence justifies it (continuation or supplemental), otherwise recorded NOT TRIGGERED | OPEN (conditional) |

## X. Operator exposure

| ID | Requirement | Status |
|---|---|---|
| X1 | Exposure decision (expose or decline) recorded on S3.2 measurement evidence (G8, G9, and H1 where triggered); exposure is decided only for a profile whose thresholds G9 froze | OPEN |
| X2 | `objectSubclass` API/search predicate and UI display, as a later implementation increment (NOT TRIGGERED if X1 declines) | OPEN |
| X3 | Every pre-existing Vehicle search returns the same Tracks (implementation roadmap Stage-3 acceptance; NOT TRIGGERED if X1 declines) | OPEN |
