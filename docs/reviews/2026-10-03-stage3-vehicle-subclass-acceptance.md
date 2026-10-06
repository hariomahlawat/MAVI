# Vehicle Subclass — Stage-3 Acceptance Register

**Status:** Open. S3.1 is merged. S3.2a (T1–T6) and S3.2b-1 (T7/T8 and fixture-only T9 tooling) are merged. S3.2b-2 (real corpus intake and derivation) has executed event `2026-10-03-commons`: E1–E21 PASS (E17 NOT TRIGGERED). S3.2b-3 (Development-host T9 execution) is complete: F1–F6 PASS (attempt 2). S3.2c (pilot, T10) is pre-registered (G1–G3 PASS). The pilot is labelled, adjudicated and measured: G4–G9 PASS (G6 with an owner-accepted pilot-specific deviation; G9 freezing the measured thresholds 0.6 / 3 as the benchmark baseline, with no optimality claim). Nothing is operator-exposed, and nothing is Production-qualified.\
**Date opened:** 2026-10-03\
**Baseline:** `main@379b7b22a3d8722d8c4d99df50794805494155aa` (merge of PR #150)

This register is the only authoritative exit gate for Stage 3 (`docs/architecture/README.md`, "Documentation precedence" item 4). Plans and runbooks reference these row IDs rather than keep a second acceptance list. The S3.2b-2 runbook's pre-flight checklist (PF1–PF21) is an evidence-collection aid that maps onto the E rows below.

**Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: commits, run IDs, or artefact SHA-256s with their retained location. Corpus bytes never enter Git.

## Current verdict

**ADR-016 ACCEPTED. MEASUREMENT TOOLING IMPLEMENTED AND MERGED:**
- **S3.1 plumbing:** PR #145;
- **S3.2a T1–T6:** PRs #146–#148;
- **S3.2b-1 T7/T8/T9 tooling:** PRs #149–#150.

**DEVELOPMENT MEASUREMENT IN PROGRESS:** S3.2b-2 complete (every E row PASS, E17 NOT TRIGGERED); S3.2b-3 complete (F1–F6 PASS); S3.2c pilot complete (G1–G9 PASS; G6 by owner-accepted deviation, G9 baseline 0.6 / 3); S3.2d is the current slice, benchmark-driven under ADR-017 (H1 PASS; H2 PASS — framework and tooling, synthetic evidence only; H3 PASS — primary BDD100K benchmark measurement recorded, association coverage weak; H4–H5 OPEN). **NOT OPERATOR-EXPOSED. NOT PRODUCTION-QUALIFIED.**

## Governing documents

1. `docs/decisions/ADR-016-detector-native-vehicle-subclass.md`: accepted 2026-10-02; the subclass source, vocabulary, resolution and measurement-first rule. `docs/decisions/ADR-017-benchmark-first-development-and-research-dataset-reuse.md`: accepted 2026-10-04; the Development benchmark and data strategy that governs S3.2d intake, admissibility and evaluation. `docs/decisions/ADR-015-public-first-protected-qualification.md`: the public-first / protected-final-qualification boundary. This register remains the only exit authority.
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

**Measurement first** (ADR-016 §7). Subclass is measured before any operator exposure. Stage-3 Development evidence comprises the completed T10 pilot on MAVI-held, publicly sourced video (G rows) and benchmark-driven measurements on externally labelled research datasets (H rows, ADR-017). Public benchmark evidence is Development or reference evidence and never becomes final Production qualification merely by being a respected benchmark (ADR-015 §3–§4, ADR-017 §8–§9). API, search and UI exposure is a later increment, decided per class subset and evidence domain (X1), and happens only if that evidence supports it.

These are four distinct levels. Completing one never implies the next.

| Level | Meaning | Rows | State |
|---|---|---|---|
| Implementation complete | the plumbing and the measurement tooling are merged with green exact-head and post-merge CI | A, B, C, D | **PASS** |
| Development measurement complete | real corpus intake, derivation, Development-host execution, the labelled pilot and its measurement exist (any expansion only if justified) | E, F, G, H | OPEN |
| Operator exposure | the API predicate, search and UI exposure of subclass, decided on measurement evidence and built as a later increment | X | OPEN |
| Production qualification | outside this register: Task 18 and the qualification record (`models/qualifications/rtmdet-m-coco-phase1-v2.json`, status `pending`) | — | not claimed |

**Stage 3 exit.** Stage 3 is complete only when:
- every row in A–G and X1 is PASS;
- H1, H2, H3 and H5 are PASS, and H4 is PASS or recorded NOT TRIGGERED;
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
- **Independence conditions for G5–G7** (owner, 2026-10-04), met as recorded in G5 and G6: the overlap reviewer never sees MAVI's predicted subclass, nor the primary reviewer's labels before her own overlap labels are frozen. The two reviewers do not discuss or reconcile individual cases before both label sets are frozen. Adjudication happens only afterwards, under T5.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| G1 | Requirements committed before any result is inspected | PASS | `docs/qualification/stage3/s3-2-subclass-requirements.json` SHA-256 `ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75`, committed on `main` at `d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9` (PR #156) and bound there (post-merge binding above). The floor is 30 per class and 30 total; every operational minimum is `null`. No T10 sample, pack, label or result existed when it was committed. The sample and packs were created afterwards, bound to it (G4, G5). T3 fails closed on this exact identity: `sample_tracks._requirements()` keeps the git binding (file equals the named commit's blob, and that commit is an ancestor of HEAD) and schema validation. It also requires the bound SHA-256 to equal the registered `artefacts.REGISTERED_REQUIREMENTS_SHA256` (`ca28702f…`), refusing otherwise with `requirements_not_preregistered`. So a later commit carrying changed requirements is refused even when the caller names it, while `d520db10`, or any later ancestor with the same bytes, is accepted. Tests in `tools/stage3/tests/test_s32_preregistration.py` cover this, including that the T3 refusal tests fail when the pin is removed. T6 then refuses requirements differing from the ones each sample bound. |
| G2 | Labelling guide committed | PASS | `docs/qualification/stage3/s3-2-labeling-guide.md` (`mavi-vehicle-subclass-labeling-guide-v1`) SHA-256 `c5f8be38be9977ea05692e1e9d45d4ca7ea9b200629316f6375640778a251fc5`, committed on `main` at `d520db1034b4eb63ddd077f5e4df3b8d0f4e33d9` (PR #156), canonical, and bound there. The owner approved this exact hash on 2026-10-04 (owner decisions above). It was committed before any pack exists. T4 fails closed on this exact identity: `build_labeling_pack._guide()` keeps the git binding and the canonical-text check, and also requires the bound SHA-256 to equal the registered `artefacts.REGISTERED_LABELING_GUIDE_SHA256` (`c5f8be38…`), refusing otherwise with `labeling_guide_not_preregistered`. A later, canonical, committed but modified guide is refused even when its commit is named. Identical bytes at `d520db10` or a later ancestor are accepted. This is covered by the same tests, and the T4 refusal test fails when the pin is removed. |
| G3 | Independent overlap reviewer confirmed | PASS | The owner confirmed Savita as the independent overlap reviewer for S3.2c/T10 on 2026-10-04 (Hari Om Ahlawat), under the independence conditions above. The primary reviewer stays R-4 Aarav (plan §10). |
| G4 | Sample binds exactly the T9 export and derivation sets (`--verify-sample`) | PASS | Pilot sample `S32T10/pilot/sample.json` (paths relative to the controlled-store root), SHA-256 `5f6fb581e8ce3d2e99022445cbc9e0fae935138ffd4899db28bd347ecf52c7b3`. It was drawn 2026-10-04 by T3 at `main@3cbe245b`: algorithm `s3-2-video-quota-diversity-v1`, design `continuation` with no parent sample, seed `s3-2c-pilot-2026-10-03-commons-v1`, target 120, overlap fraction 0.2. The result is 120 selected and 24 overlap Tracks (⌈0.2 × 120⌉), with no duplicates and the overlap inside the selection. The sampling saw only Track class, timing and evidence; no subclass or confidence field is in the sample. It binds the registered requirements `ca28702f…` at `d520db10` (T3 pin). It binds exactly the 8 export SHA-256s and the 8 `__run1` derivation-manifest SHA-256s named by the T9 execution record `4750e4f4…`, and its release `325f2055…`. `ingest_source_pool.py --verify-sample` against that record: `sample verified`, exit 0. Evidence: the write-once manifest `S32T10/pilot/s3-2c-evidence-manifest-pre-labelling.json`, SHA-256 `f66bbcc77ad94c520c3f52617fc3f821b4c5dd4a731861b7d8e0db7c9188d8f0`, entries `sample`, `t3-log` and `t9-verify-sample`. |
| G5 | Blind primary and overlap labelling | PASS | Both packs were labelled independently on 2026-10-04 and frozen with T5. Primary: R-4 Aarav on pack `44e3592e…` (120 items), frozen labels `S32T10/pilot/frozen-labels/primary-labels.json` SHA-256 `8d8ca68063aef35d43c4cb5a5a466f28e7f129d390ac48774930f636d098faad`, 120 decisions. Overlap: Savita (typed `savita` in the exported file) on pack `c0f613006cfd…` (24 items), frozen labels `frozen-labels/overlap-labels.json` SHA-256 `273ad05c98be416ea3c71d1dcb0eeb5817adf6180009fe5368560d5c04a959ac`, 24 decisions, `parentPackSha256` the primary pack. Both files validate (`vehicle-subclass-track-labels-v1`), are canonical, bind their pack, the sample `5f6fb581…`, the T9 export set and the registered guide `c5f8be38…`, and carry one decision per pack item. The packs carried no prediction or confidence (G4/G5 pack verification), so the reviews were prediction-blind by construction. The unedited exported decision files are retained (post-measurement manifest entries `review-decisions-primary`, `review-decisions-overlap`). Evidence: write-once manifest `S32T10/pilot/s3-2c-evidence-manifest-post-measurement.json`, SHA-256 `b345154a88f686a4c5afb1bed650a4f88349d687b8207f6c233075e483cf4b00`, entries `frozen-labels-primary`, `frozen-labels-overlap`. |
| G6 | Adjudication completed where needed | PASS — owner-accepted pilot-specific deviation | The adjudication artefact is sound: `frozen-labels/adjudication.json` SHA-256 `a6cdd0a1c546465f2e3a027c47058e4ca173f3b48d73cc9cd202a8bdc5d19a29` (`vehicle-subclass-adjudication-v1`, canonical), binding both frozen label files by hash and covering exactly the 24 overlap Tracks: 23 carried automatically, 1 adjudicated (both reviewers chose `unknown` with different reasons; label agreement was 24 of 24). Adjudicator: Hari Om (Hari Om Ahlawat, repository owner), 2026-10-04, using `adjudicate-prepare`/`adjudicate` after both label sets were frozen; those commands take no prediction input. The sheet and decision file are retained (manifest entries `adjudication-sheet`, `adjudication-decisions`). **Deviation.** The governing procedure (plan §6 T10 step 5, §10, §19 item 4a, as reconciled in PR #158) requires the adjudicator's designation to be recorded before adjudication. No such record preceded it; the designation was first recorded here, at reconciliation on 2026-10-04. **Owner acceptance (2026-10-04, Hari Om Ahlawat).** The owner accepts this pilot-specific procedural deviation: the adjudicator designation was recorded after, rather than before, adjudication. The substantive independence, freeze-order and prediction-blindness controls were satisfied: both label sets were frozen before adjudication, adjudication happened only after both freezes, no model prediction or confidence was available to the adjudicator, the adjudicator is named, and the frozen artefact is valid. Only the timing of recording the designation failed the pre-registered administrative order, and repeating the adjudication would add no scientific value. No re-adjudication is required. The frozen adjudication artefact and the T6 measurement bound to it (G8) are unchanged. This acceptance applies only to this completed pilot and does not amend the execution requirement for future adjudications. |
| G7 | Labels frozen | PASS | Frozen, write-once label artefacts: primary `8d8ca68063aef35d43c4cb5a5a466f28e7f129d390ac48774930f636d098faad`, overlap `273ad05c98be416ea3c71d1dcb0eeb5817adf6180009fe5368560d5c04a959ac`, adjudication `a6cdd0a1c546465f2e3a027c47058e4ca173f3b48d73cc9cd202a8bdc5d19a29`. Each is content-addressed and bound to its pack, sample and guide (G5, G6). The pre-labelling artefacts (sample, both packs) are byte-identical to their write-once manifest `f66bbcc7…` after labelling, so no T10 input changed after the freeze. Corrections, if ever needed, produce new artefacts and a new measurement (plan T5). |
| G8 | T6 measurement and requirement comparison produced | PASS | T6 (`run_subclass_measurement.py`) on the frozen inputs: `S32T10/pilot/measurement/measurement-result.json` SHA-256 `d7b9f213b29b5c3d64c29f4b5e589be61025c403bbe4161be64912cd8b8a3276` (`vehicle-subclass-measurement-v1`), `requirement-comparison.json` SHA-256 `44e3f2a744af845f7090d6b7f8d394768d675796a737af7366b2a4c65ccbc022` (`vehicle-subclass-requirement-comparison-v1`), `measurement-summary.md` SHA-256 `35d66f3d279cfe1471d5ef5a2560da3dafcb680e55dfe2f1e86104f9afa58e4a`. The result binds the registered requirements `ca28702f…`, the measured profile `afb03b6c…`, the T9 export set, the sample `5f6fb581…`, both packs, both frozen label files, the adjudication and the registered guide; its producer is the T9 producer (`maviCommit` `49a5566d…`). The comparison binds this result and the requirements. Primary aggregate (the pilot only; no supplemental batch): 120 labelled Tracks, 115 evaluable, 111 resolved, 4 abstained; human `unknown`: `ambiguous-type` 2, `mixed-track` 2, `other` 1. Evaluable support per class: car 103, bus 7, truck 5, motorcycle 0. Reviewer reliability on the 24 overlap Tracks: 24 label agreements, 23 exact. Requirement comparison (every operational minimum `null`, floor 30/30): coverage and both car criteria `no-requirement` (support 115 and 103 ≥ 30); truck, bus and motorcycle precision and recall `insufficient-support` (5, 7 and 0 < 30). No pass or fail operational claim is made, as pre-registered. Per-class conclusions for truck, bus and motorcycle are not drawn. The aggregate uses the adjudication whose procedural deviation the owner accepted in G6; the measurement stands as the historical pilot measurement. Evidence: manifest `b345154a…` entries `measurement-result`, `requirement-comparison`, `measurement-summary`. |
| G9 | Threshold freeze decision recorded on the measurement (ADR-016 §3). Either `minShare`/`minMatchedDetections` are frozen at the measured profile's values; or any change is a new pipeline-profile version, which needs its own Development tuning/evaluation path and a new measurement before G9 can PASS | PASS — baseline frozen at 0.6 / 3, no optimality claim | **Owner decision (2026-10-04, Hari Om Ahlawat), taken on the frozen measurement (G8).** The owner freezes the measured profile values `minShare` 0.6 and `minMatchedDetections` 3 (profile `1.3.0-candidate`, SHA-256 `afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf`) as the baseline configuration for benchmark evaluation. This establishes a stable evaluation baseline only; it does not claim these values are optimal. Any future threshold change is a separately versioned Development or tuning experiment, under ADR-016 §3 and plan §13 ("No tuning in S3.2"), and needs its own benchmark evidence before it can replace the baseline. This decision retains the existing measured values: the pipeline profile and its hash are unchanged, and no code or configuration is modified. |

## H. S3.2d — expansion (T11)

H2–H5 are evidence outcomes, not mandated PR boundaries, approval meetings, independent work packages or owner decision points. One implementation or one benchmark execution may satisfy several rows at once when the required evidence exists, and a row closes when its evidence is recorded here, by hash.

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| H1 | Expansion undertaken only if the pilot evidence justifies it (continuation or supplemental), otherwise recorded NOT TRIGGERED | PASS | On the G8 evidence, two of the plan §14 triggers hold: an important class is below the minimum support (truck 5, bus 7, motorcycle 0, each < 30), and support is too small for per-class conclusions. The pilot evidence therefore justified expansion. **Mechanism (owner decision 2026-10-04, ADR-017):** expansion is benchmark-driven, through S3.2d-1 to S3.2d-4 in the amended plan §14, against established labelled tracking benchmarks with explicit per-class mappings. The manual `continuation`/`supplemental` path of the pilot design remains available only as a documented-gap fallback. ADR-017 adopted this benchmark-driven expansion mechanism in PR #159 (`main@906fc8a7fcdfebac646ecedf503a77cb34fecc6a`), and the expansion has since been undertaken through S3.2d (H2 PASS; H3 measured). H1 is therefore closed PASS. H1 alone never unlocks exposure: X1 still depends on H2–H5 and the other register requirements. |
| H2 | S3.2d-1: benchmark framework and tooling merged with deterministic tests: dataset descriptor and adapter contract; per-native-class mapping contract (`exact`/`subset`/`unsupported` with reason); ground-truth Track representation; prediction-independent GT↔MAVI association with ambiguity and unmatched reporting in both directions; dataset and result provenance; split identity; known-exposure metadata (plan §14 amendment; ADR-017 §4–§6) | PASS | **S3.2d-1 slices 1–3 (PR #161, PR #162, PR #163), effective when PR #163 merges with green exact-head CI.** Contracts (schema SHA-256 / example SHA-256): `benchmark-dataset-release-v1` `aa47eefe…`/`5aa46d7b…`, `benchmark-class-mapping-v1` `210fa4c9…`/`144ccf22…`, `benchmark-association-v1` `6686ba74…`/`086d5535…`, `benchmark-vehicle-subclass-result-v1` `db814601…`/`acec370d…`. Association policy `vehicle-tracks-association-v1` SHA-256 `a8e2e7f18d6912c226444a2639dc7ee928575085d683690b8408efc6eb8ffe05`. Synthetic end-to-end through the CLI (`tools/benchmarks/tests/test_bench_synthetic_e2e.py`: describe → prepare with the FFmpeg pack → exports → evaluate, byte-identical on repeat): golden `associationBodySha256` `57266783a8bc97fce8b8a11a80e0fd7dc7dd85195d1f65425f233899f740db9b`, golden scope A+B `dfa53811a90ef76f90bf76ac8bf7ee87e6b3f7f67f23738079080d35a6bf0a73`. Mutation tests present: class/subclass/confidence mutation leaves the association body identical (`test_bench_association.py`); prediction, native-class and mapping mutations change only evaluation (`test_bench_vehicle_subclass_evaluate.py`, E2E). Modules: `tools/benchmarks/{core,datasets,capabilities/vehicle_tracks,capabilities/vehicle_subclass}`, `prepare.py`, `run.py`, `cli.py`; `msgpack>=1.1,<2` on the tools surface (`tools/requirements.txt`, dependency policy). Synthetic and tooling evidence only: no real dataset, no capability claim. |
| H3 | S3.2d-2: primary benchmark measurement recorded. A benchmark whose native labels exactly cover the capability is preferred where reasonably available; otherwise the strongest available benchmark or combination, with explicit `exact`/`subset`/`unsupported` mappings. Lack of one perfect taxonomy does not block evidence-supported class subsets. Recorded: dataset and release identity (and source, including any archival copy and its credibility basis), research-use status with its basis (ADR-017 §7), mapping declarations, association coverage, class confusion on valid associations, per-class support, known or possible exposure; dataset bytes outside Git | PASS — evidence-completeness gate; performance findings feed H5 | **Run `bea73d13cd76bcd432319cab88a763d2af6139a34c013e2e93b71363a17f9f9b` (attempt 2), executed 2026-10-05 on `main@359073429154bb0839e53cc30b2f55f58f9f35d4`** under the runbook `docs/superpowers/plans/2026-10-05-stage3-s3-2d-2-bdd100k-h3-execution.md`. Complete (200 of 200 sequences), reproducible (frozen descriptor; derivation manifest reproduced byte-for-byte across two attempts; write-once results verified by `run.verify`), provenance-bound and reported under the frozen association policy. Association coverage is weak (12.6%) but not coverage-limited (1.87% against the 1/10 threshold). Full evidence in **H3 evidence** below. |
| H4 | S3.2d-3: domain-diversity benchmark measurement(s) recorded with the same fields, each contributing only to the classes and domains it supports; or recorded NOT TRIGGERED with a technical rationale showing that additional domain-diversity evidence is not materially useful for the current capability decision (no owner approval needed for that call; the owner may still intervene where the decision is consequential) | OPEN — on HOLD | Held pending the H3 tracker-gate diagnosis; see *H3 diagnostic interpretation*. |
| H5 | S3.2d-4: evidence-backed capability decision recorded per class and evidence domain (benchmark-supported, Development-only, insufficiently supported, deferred), on H3, H4 and the pilot (G8); no unsupported class advanced | OPEN | |

### H3 evidence — S3.2d-2 primary benchmark measurement (BDD100K MOT 2020 val)

Paths are relative to the controlled-store root `Stage3/H3-attempt2`. No dataset bytes, derived videos, exports or trajectories are in Git.

**Attempts.**
- **Attempt 1 stopped (root `Stage3/H3`, `main@e55b47ad`).** `prepare` encoded all 200 sequences, then the final move of its staging directory raised a raw `PermissionError: [WinError 5] Access is denied`. The staging output is preserved unmodified as evidence (`.derived.partial-ade2c41c…`, derivation manifest `a295809d…`). The defect was fixed in PR #168: bounded retry on transient Windows denials, `output_move_failed` otherwise.
- **Attempt 2 is the measured attempt.** Fresh root, descriptor freeze and catalogue on `main@35907342`. Operational events, none of which changed an input or identity: the host slept for about 85 minutes during `prepare`, which resumed by itself; the API was rebuilt with `-p:MaviNativeMediaToolsDirectory` set to the same verified FFmpeg pack `prepare` used, because the worktree's `vendor/ffmpeg` holds only its README (no source change); and the first worker launch failed its pack preflight under Windows PowerShell 5.1 and was relaunched under PowerShell 7 before any run.

**Dataset and provenance.**

| Item | Value |
|---|---|
| Dataset / release / split | `bdd100k-mot-2020-cocofmt` / `MOT 2020 val (box_track_20) via MASA COCO-format derivative sha256:074ff795` / `val` |
| Adapter | `bdd100k-mot-coco` v1 |
| Frozen descriptor | `desc/frozen.json`, SHA-256 `7169263ab3787e7af4eb7ca73ac4e24af39239e5b898aca878a297c75c51e9c9`; 39,974 manifest entries (39,973 JPEGs and the annotation) |
| Annotation | `bdd_box_track_val_cocofmt.json`, 117,094,032 bytes, SHA-256 `074ff79555483296cf7ccadddeeceeec7a83452c900506dc46588ed3a3e65d5d` (MASA `dereksiyuanli/masa@25ed372c`) |
| Image archive | `images20-track-val-1.zip`, 4,983,938,716 bytes, SHA-256 `4d678810a14095ab4064013d81e3bc2bda45f730bfc09c3e66d3a5ef1c076778`, MD5 `743ab4c7b5ff8eeebd60bbfd15b20bd6`; owner download from the Berkeley BDD100K MOT mirror; 200 sequences, 39,973 frames |
| Derivation manifest | SHA-256 `a295809d4e5865017b63fc4edd0b7a049e9e7391527ff008ca43b4f50da86cda`, identical in attempts 1 and 2; 200 sequences, 39,973 frames, 5/1 fps, FFmpeg 9.0.1 (`72a489ec…`), ffprobe `19202b23…` |
| Raw GT tracks (not support) | 18,842: car 13,866; truck 744; bus 193; motorcycle 46; pedestrian 3,603; rider 133; bicycle 251; train 6 |
| Mapping | SHA-256 `28e5ec5ef78ca9e4b36cc98b9d09bb33a5788bd21a4e5a797c14a100d3a318d3`: car, truck, bus, motorcycle `exact`; pedestrian, rider, bicycle, train `outside-capability` |
| Research use | RESEARCH-ADMISSIBLE: BDD100K data and label licence; MASA is the retrieval and conversion source, not a relicensor |
| Exposure | `none-known`: the detector trains on COCO 2017 only (resolved config `377d9f57…`); no MAVI record names BDD100K |
| Lineage | `scalabel/scalabel@071d0735`, blob `3e19c83d`, video `b1c66a42-6f7d68ca`: 202 frames, 3,241 boxes, zero material mismatches |
| GT semantics | `iscrowd=0,ignore=0` and genuine crowd `iscrowd=1,ignore=0` are ordinary GT; converted distractors `iscrowd=1,ignore=1` are ignored; 46 class-inconsistent ids are ignored in full |

**Domain and interpretation caveats.** BDD100K MOT is moving U.S. dashcam footage, a weak proxy for fixed CCTV. The historical conversion may fold `van`/`caravan` aliases into `car`, which affects the interpretation of car precision and truck recall. These results are not an official BDD100K MOT score. No MAVI-class claim is made for trailer, other vehicle, van or caravan.

**MAVI execution.**

| Item | Value |
|---|---|
| MAVI commit / tooling | `359073429154bb0839e53cc30b2f55f58f9f35d4`; `toolingSha256` `9add54ebdadfb32197b245e4e6deccf56df47770f08287887ee1d56dfd3299d3`, `toolingCommit` the same commit |
| Runtime Pack | `mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d` (`windows-x86_64-cuda`, installed pack) |
| Model Pack / checkpoint | `mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700`; checkpoint `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b` |
| Component binding / profile | `7ef226193232b90b0a20f8648a95f21e0bbc9416b353605c9be6d81262abe205` / `afb03b6c4da61fbf6021ef855307f80c5b7206996e7e21c8d297394b091a18bf` (`1.3.0-candidate`, `minShare` 0.6, `minMatchedDetections` 3) |
| Requirements / association policy | `ca28702f82c6845298a2cf348d7b057024923c7a0a0f4fd496097bf1b7272d75` / `a8e2e7f18d6912c226444a2639dc7ee928575085d683690b8408efc6eb8ffe05` (`vehicle-tracks-association-v1`) |
| Device | `cuda:0`, NVIDIA GeForce GTX 1650 Ti (CUDA 12.4, driver 576.83), attested on every run; `nvidia-smi` showed the worker as a CUDA compute process during inference (`evidence/cuda-confirmation.txt`) |
| Catalogue | `mavi_s32d2_h3_20261005_a2`, created 2026-10-05T08:15:01Z after the freeze, 0 tables and empty media at creation (`evidence/h3-catalogue-creation.json`, SHA-256 `baeee3c14d779724b0a77d8e384a9d1f650f261a0bc08f4dfeed21b39982b718`); afterwards exactly the 200 cameras and 200 videos the journal created |
| Completion | 200 of 200 sequences; 200 distinct processing runs, all `Completed`; one producer identity; 6,057 sealed trajectories; run-id list SHA-256 `9a96f1eface74bd23f403d2f5644baefee61ecddba0693504a3979037ce1cf2c` |

**Result identities.** `benchmarkRunId` `bea73d13cd76bcd432319cab88a763d2af6139a34c013e2e93b71363a17f9f9b`. `results/<runId>/association.json` SHA-256 `897ba2551f3c9c501354cb300c8ff6cbd87c300436471438c0727683ed83b589` (equal to `result.associationSha256`); `result.json` `65aeef165ac396d4efac7ab6ce5c52d0ed86aaa89784d6f3fffa4d0fd755c735`; `report.md` `f1ee975dac018f50c8591531bba06812610592ae400e1b427fa4272f79679380`. `run.verify` passed.

**Scope A — association coverage (detection and tracking, not subclass accuracy).**

| Measure | Value |
|---|---|
| Expected vehicle GT | 13,412: assigned 1,685; ambiguous 1; fragmented 203; merged 5; unverified 42; unmatched 11,476 |
| Ignored GT | 1,968 |
| MAVI Vehicle Tracks | 6,057: assigned 1,685; fragment 237; unverified 42; ignored 38; unmatched 4,055 |
| Association rate | 1,685/13,412 = 0.1256 |
| Coverage-limited GT rate | 251/13,412 = 0.0187 (threshold 1/10); `coverageLimited` false |
| MAVI unverified rate | 42/6,057 = 0.0069 |
| Outside-capability GT | 3,462; Vehicle Tracks assigned to them: 0 |
| Per native class (total / assigned / fragmented / merged / unverified / unmatched) | car 12,496 / 1,595 / 193 / 5 / 39 / 10,663 (ambiguous 1); truck 690 / 56 / 7 / 0 / 3 / 624; bus 185 / 34 / 3 / 0 / 0 / 148; motorcycle 41 / 0 / 0 / 0 / 0 / 41; pedestrian 3,095, rider 123, bicycle 238, train 6, all unmatched |
| Sequences above 1/10 coverage-limited | 4: `b1dce572-c6a8cb5e` 7/60; `b1e1a7b8-65ec7612` 4/31; `b1fc95c9-644e3c3f` 7/40; `b21c86ac-71205084` 5/36 |
| Per-sequence association rate | quartiles 0.056 / 0.129 / 0.206; minimum 0 (9 sequences); maximum 0.774 |

Assigned pairs have containment 1.0 at every quartile and mean normalised centre distance 0.014–0.040, so the assigned subset shows no time or coordinate offset. That subset is selected by the association gates, so it does not rule out an offset in the missed population. MAVI produced 6,057 Vehicle Tracks against 13,412 expected vehicle GT tracks. Among unmatched GT (outside-capability included), 820 had no MAVI Track overlapping in time, 10,249 had overlapping Tracks that never contained the object, 2,916 were contained for less than half their length (fragmentation), 878 were partially contained and 75 were contained but failed another gate (14,938 in all). Whether the 10,249 never-contained misses are detector and tracker coverage or an alignment or geometry error in the missed population is not established here; the H5 diagnosis must inspect unmatched geometry and per-sequence alignment first.

**Scope B — Track-conditional subclass quality (assigned exact-GT pairs only).**

| Class | Support (floor 30) | Recall | Precision (status) | Among judged | Unjudgeable | Accuracy over resolved | Accuracy over evaluable | Undetermined | Requirement |
|---|---|---|---|---|---|---|---|---|---|
| car | 1,595 adequate | 1,561/1,595 = 0.9787 | 1,561/1,567 = 0.9962 (computed) | 1,561/1,567 | 0 | 1,561/1,591 = 0.9811 | 1,561/1,595 = 0.9787 | 4/1,595 = 0.0025 | no-requirement |
| truck | 56 adequate | 47/56 = 0.8393 | 47/74 = 0.6351 (computed) | 47/74 | 0 | 47/53 = 0.8868 | 47/56 = 0.8393 | 3/56 = 0.0536 | no-requirement |
| bus | 34 adequate | 34/34 = 1.0000 | 34/37 = 0.9189 (computed) | 34/37 | 0 | 34/34 = 1.0000 | 34/34 = 1.0000 | 0/34 = 0 | no-requirement |
| motorcycle | 0 insufficient-support | 0/0 (n/a) | no-judgeable-predictions | — | 0 | n/a | n/a | n/a | insufficient-support |

Confusion (truth → MAVI outcome): car → car 1,561, truck 27, bus 3, undetermined 4; truck → truck 47, car 6, undetermined 3; bus → bus 34. No motorcycle pair was assigned. Overall exact-GT: 1,685 assigned, 1,678 resolved, 1,642 correct, 7 undetermined; accuracy over resolved 1,642/1,678 = 0.9785; over evaluable 1,642/1,685 = 0.9745; undetermined share 7/1,685 = 0.0042. Macro over car, truck and bus (motorcycle excluded for no support): recall 0.9393, accuracy over resolved 0.9560 (exact rationals in `result.json`). Taxonomy coverage `full`. Excluded native classes (bicycle, pedestrian, rider, train): 0 assigned Vehicle Tracks.

**Findings for H5.** The main failure is association coverage, not classification: only 12.6% of expected vehicle GT is associated, and the cause of the misses is not yet established (see Scope A). On the associated Tracks, car and bus are classified reliably. Truck precision is the weak point: 27 BDD100K `car` Tracks were classified `truck`, which is consistent with the van-to-car caveat. Motorcycle has no benchmark support: 41 GT tracks, none associated. Per the runbook's decision tree, weak association calls for a separate detection, tracking and association diagnosis experiment, starting with unmatched geometry and per-sequence alignment; it does not reopen H3.

### H3 diagnostic interpretation (recorded 2026-10-06)

Non-authoritative diagnostics run after H3 on its frozen inputs. They do not change the H3 run, its artefacts or its PASS. H3 stays a valid Development measurement on a **5 Hz tracking domain** (the labelled instants are at 5 Hz and the derived videos are encoded at 5/1, so every MAVI frame is a labelled instant).

- **Association diagnosis.** No implementation defect: GT and MAVI agree in time and space (no lag; centre fit slope about 1). Misses concentrate in small objects (under 40 px is 54.5% of GT), dark sequences and short or late tracks.
- **Detector-only diagnosis** (one-to-one per-frame matching frozen before results). RTMDet localises most GT vehicles but at low confidence. At IoU ≥ 0.50, of 13,412 expected-vehicle GT tracks: 691 have no matched detection, 6,052 never reach 0.60, 141 reach 0.60 but never 0.61, 885 reach 0.61 but never on two adjacent labelled frames, and 5,643 have at least two adjacent labelled frames at ≥ 0.61. Frame-level one-to-one centre-inside rate: 94.4% at ≥ 0.05 and 20.3% at ≥ 0.70. Under 20 px, no GT frame is matched at ≥ 0.70.
- **Exact replay fidelity.** A second, owner-approved diagnostic RTMDet pass (same Model Pack, checkpoint, CUDA Runtime Pack, pipeline profile, `cuda:0`, floor 0.05, complete Person + Vehicle stream) reproduced all 4,593,988 Vehicle detections over 39,973 frames exactly. Replaying that stream through the production `VideoProcessor` and `ByteTrackTracker` at the frozen settings reproduced all 6,057 Vehicle Tracks (trajectory bytes, observation times, frame numbers, boxes, evidence selection) and the authoritative H3 association exactly. A vehicle-only replay had differed on 9 Tracks' evidence frames because Person boxes are occlusion competitors in evidence selection; the full stream removed that difference.
- **Activation-only sensitivity** (`highConfidenceThreshold` fixed at 0.60, all else frozen, unchanged association):

  | Run | Activation | Vehicle Tracks | Assigned GT | Association rate | Fragmented GT | Unmatched MAVI Tracks |
  |---|---|---|---|---|---|---|
  | Baseline | 0.70 | 6,057 | 1,685 | 12.56% | 203 | 4,055 |
  | A1 | 0.65 | 7,428 | 2,078 | 15.49% | 286 | 4,874 |
  | A2 | 0.61 | 8,690 | 2,390 | 17.82% | 364 | 5,623 |

  `trackActivationThreshold = 0.70` is demonstrated to be causally restrictive on this domain. Lowering it within its legal range improves association, materially but modestly against the full deficit, while Track count, fragmentation and unmatched MAVI Tracks also rise. Unmatched MAVI Tracks are not automatically false positives: BDD100K may not label every visible object. Under 20 px, assigned GT moves only 1 → 1 → 3 of 2,635.
- **A2 residual (exact, ≥ 0.61, IoU ≥ 0.50).** Of the 11,022 GT tracks not assigned at A2, 7,732 never have two adjacent labelled frames at ≥ 0.61 and stay activation-blocked. 3,290 are activation-eligible but not assigned: 2,853 unmatched (2,506 of them with ≥ 0.61 support on under half their lifetime), 361 fragmented, 64 unverified and 12 merged or ambiguous.
- **What this does not establish.** H3 does not establish a Production tracker profile; 0.61 is not a recommended value, and no single benchmark selects Production thresholds (`docs/qualification/2026-10-06-tracker-profile-qualification-principles.md`).
- **Status.** H4 stays on HOLD (row status OPEN, not started). H5 stays OPEN; no decision is justified yet.

Retained evidence, outside Git under the controlled store `Stage3/` (SHA-256):

| File | SHA-256 |
|---|---|
| `H3-detector-diagnosis/detection-index.json` (first pass, vehicle classes) | `27001167073a3bc18828ddb044110fabf8a8bed15aca7ce8cefec023b8a791f4` |
| `H3-detector-diagnosis/detector-diagnostic-report.json` | `ba4a4753de9617bf61591ac4864a8562b62187150152a1694a565d1f312d7650` |
| `H3-detector-diagnosis/detector-diagnostic-addendum.json` | `970dab705496c860049b2540761a3fb9384fbbca37213942f521e61211b1257c` |
| `H3-detector-diagnosis/availability-060.json` | `8abb72b94953815dc0f5856482d62ac276dc087bbe74d84c54c5ab0a090c67cc` |
| `H3-detector-diagnosis-full/detection-index.json` (second pass, full stream) | `ce720de2dec2d29293f1e91a76936e8aad4961429f36758905b6accb777576b3` |
| `H3-detector-diagnosis-full/determinism-vs-first-pass.json` | `92e0ccbb4771dc4526ae50d7e92a2d8ef24e33e70020771347b51c585851cb13` |
| `H3-replay/fidelity-gate-v2-baseline-full.json` | `a4fcb4aba5fd4b5f00db1ce616ab07533255734451e0763b16863dcface8e7fb` |
| `H3-replay/sensitivity-report-baseline-full_A1-act0.65.json` | `058904aca9b27cbcff4e2988d816c3d4f0774b5a549ef19b6f247350f3f9f4bd` |
| `H3-replay/sensitivity-report-baseline-full_A2-act0.61.json` | `27b2ce94f36fb04f27ab95ebea4047e76648da56fd494b6baf36fd2ece94fc58` |
| `H3-replay/availability-061-tracks-v2.json` | `fb59be2110a6deb77b2689b7b83a7f07aab26c43b41448ac3a9fb8fd61334f1b` |
| `H3-detector-diagnosis/spawn-eligibility.json` | `ca2a4fda4e0e02fcbe4df1721f380f81a0214770ad04d8b88d7df2859d482401` |

The diagnostic scripts are hashed before use in the `frozen-scripts*.sha256` files beside these outputs.

## X. Operator exposure

| ID | Requirement | Status |
|---|---|---|
| X1 | Exposure decision (expose or decline) recorded on S3.2 measurement evidence: G8, G9, and every S3.2d row (H1, H2, H3, H5 PASS; H4 PASS or NOT TRIGGERED); exposure is decided per class subset and evidence domain (H5), only for a profile whose thresholds G9 froze | OPEN |
| X2 | `objectSubclass` API/search predicate and UI display, as a later implementation increment, exposing only the class subset X1 approved on H5: an explicit allowlist in the API, search and UI, so a class H5 left Development-only, insufficiently supported or deferred is neither returned, filterable nor displayed even though Track persists every vocabulary value; acceptance evidence shows the deferred classes remain unavailable (NOT TRIGGERED if X1 declines) | OPEN |
| X3 | Every pre-existing Vehicle search returns the same Tracks (implementation roadmap Stage-3 acceptance; NOT TRIGGERED if X1 declines) | OPEN |
