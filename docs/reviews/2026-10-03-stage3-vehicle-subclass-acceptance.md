# Vehicle Subclass — Stage-3 Acceptance Register

**Status:** Open. S3.1 is merged. S3.2a (T1–T6) and S3.2b-1 (T7/T8 and fixture-only T9 tooling) are merged. S3.2b-2 (real corpus intake and derivation) has executed event `2026-10-03-commons`: E1–E13 and E15–E21 PASS (E17 NOT TRIGGERED); E14 OPEN until the map digest is on `main` and §16(b) and `verify_repo` pass at that commit. Nothing is operator-exposed, and nothing is Production-qualified.\
**Date opened:** 2026-10-03\
**Baseline:** `main@379b7b22a3d8722d8c4d99df50794805494155aa` (merge of PR #150)

This register is the only authoritative exit gate for Stage 3 (`docs/architecture/README.md`, "Documentation precedence" item 4). Plans and runbooks reference these row IDs rather than keep a second acceptance list. The S3.2b-2 runbook's pre-flight checklist (PF1–PF21) is an evidence-collection aid that maps onto the E rows below.

**Nothing unexecuted is marked PASS.** A row becomes PASS only when its evidence is entered here: commits, run IDs, or artefact SHA-256s with their retained location. Corpus bytes never enter Git.

## Current verdict

**ADR-016 ACCEPTED. MEASUREMENT TOOLING IMPLEMENTED AND MERGED:**
- **S3.1 plumbing:** PR #145;
- **S3.2a T1–T6:** PRs #146–#148;
- **S3.2b-1 T7/T8/T9 tooling:** PRs #149–#150.

**DEVELOPMENT MEASUREMENT IN PROGRESS:** S3.2b-2 executed (E14 OPEN until its post-merge checks pass); S3.2b-3, S3.2c and S3.2d are OPEN. **NOT OPERATOR-EXPOSED. NOT PRODUCTION-QUALIFIED.**

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

Event `2026-10-03-commons` evidence entered 2026-10-04; controlled store event root `Stage3/S3.2/2026-10-03-commons` (store-relative event root; all evidence paths below are relative to it). Every off-repository evidence file is bound by store-relative path and full SHA-256 in the canonical, write-once evidence manifest `evidence/s3-2b-2-evidence-manifest-v2.json`, whose entries the rows below cite by ID; the manifest's own SHA-256 is recorded in the next line. It supersedes `evidence/s3-2b-2-evidence-manifest.json`. All rows started OPEN. Evidence is hash-only; bytes stay in the controlled store. The ingestion map's commitment (E13, E14) is deliberately placed in S3.2b-2. The plan's slice table lists it under S3.2b-3; this register moves it earlier so that it is fixed before the host exists, and starts nothing.

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
| E14 | Ingestion map committed or digest-bound, ancestry-valid, and validated, and `tools/verify_repo.py` passes on that commit [PF14, PF20] | OPEN | Map `ingestion/ingestion-map.json` `46a014e342fbdb9dc3bf98cf6f5f3bd505da524fda191d6a0987260f3eba7c95` validated (`ingestion_map.check`) against the convention at `d12a352c`; its Mode B digest is committed by the PR that adds this evidence. PASS once that digest is on `main` and §16(b) passes at that commit |
| E15 | Exactly one valid T8 `__run1` derivation per pool member (`load_derivations`) [PF15] | PASS | manifest entry `load-derivations` (§16(a) output: exactly one valid `__run1` per member) and the 9 `derivation-<sourceSha256>-run1/run2` entries |
| E16 | Remux/transcode authorised (`create-derivatives`) wherever used [PF16] | PASS | manifest entry `post-t8-checks`: every manifest `operations: ["create-derivatives"]`, `blockers: []` (all 8 transcode) |
| E17 | First real remux determinism repeat byte-identical (NOT TRIGGERED if remux unused) [PF17] | NOT TRIGGERED | Remux was not used (no H.264 source) |
| E18 | First real transcode determinism repeat byte-identical (NOT TRIGGERED if transcode unused) [PF17] | PASS | Manifest entries `determinism-manifest` and `determinism-report`. Evidence manifest `evidence/e18-determinism-evidence.json` (SHA-256 `bd19602338d1c782e21ded7cdbde1930a6ff563479d004c22de8b9127d90f4e6`) names, off-repository, the retained report and both run directories for the first real transcode (pool member with source SHA-256 `2c75b1ae879ebfadb7473d24e29b34c072430cabe8f0b5e5e68f68e58ab372d2`). Report SHA-256 `ae310818e8fb6194e06dd56d33ff3e00c85c08f91f8c03afbc0eff7cbe7464ab`; `__run1/video.mp4` `ffb262545d9ca08a3d1a5d44166ae5e0d6f319e243732a7d75bc0a081e55d98d` = `__run2/video.mp4` `ffb262545d9ca08a3d1a5d44166ae5e0d6f319e243732a7d75bc0a081e55d98d`; `__run1/derivation-manifest.json` `b45d2d156e0e5a0c29558bfe711f00bd74094e720253240d672398f9adc51998` = `__run2/derivation-manifest.json` `b45d2d156e0e5a0c29558bfe711f00bd74094e720253240d672398f9adc51998`; both pairs byte-identical |
| E19 | Every derivation's `importLimitBytes` equals the intended S3.2b-3 host's `VideoImport:MaximumFileSizeBytes` [PF18] | PASS | manifest entry `import-limit` (`evidence/e19-effective-import-limit.json`, SHA-256 `b6bd239e5798d4fa1d42442f6b7e81e3ddcbc79cd12c9f3d3f36ee95d01e1bc1`): effective `VideoImport:MaximumFileSizeBytes` 3221225472 from `appsettings.json` (blob `88d59a59dfa00606296179efae1a98ddec26f0b5cf5a5de81b4932d79bb94e74`); `appsettings.Development.json` (blob `336bd7bd20efd3735533f3431cb0901f9e7aace6f146dd53011f47c29b2c6963`) and the Development machine configuration (file `40e2b14ed04709a0c5b19ae6ed7b5059270c12581962652e8608ae72b4c6940c`) set no value; no `MAVI_MACHINE_CONFIG` and no `VideoImport__*` environment variable in process, user or machine scope; all 9 derivations' `importLimitBytes` equal it |
| E20 | No corpus media, archive, frame, crop or log committed to Git [PF19] | PASS | PF19 audit `evidence/e20-git-audit-07b20a45.txt` (SHA-256 `4692766d744213394d40b06d3e69a5d052eb213b08f5ac98914c19be158443b3`), retaining every command and its output, of commit `07b20a4528bd953aad4a3d5e0fbf3890ff329ed7` against the pre-event baseline `3885d020007bb649f7f6262f0a50afc4ff115a66`: (1) `git ls-tree -r --name-only` inventory, 1575 tracked paths; (2) changes since the baseline are exactly the pool and map digests, the convention and this register; (3) all 89 tracked media/image/archive/log paths are byte-unchanged since the baseline; (4) no tracked path carries an event or controlled-store marker; (5) no tracked blob matches any of the 221 files in the event store, the acquisition and discovery stores or the scratch area (frames, contact sheet, logs) by SHA-256; (6) the event-changed files contain no local path or member name. Result CLEAN. The only later change (this row's text) is in this register |
| E21 | One verified FFmpeg/ffprobe pack identity retained for the event: each tool's `{version, sha256}` and the manifest SHA-256. Every probe's `ffprobe`, every derivation's `sourceMedia.ffprobe`/`outputMedia.ffprobe`, and every remux/transcode `ffmpegVersion`/`ffmpegSha256` equal it (plan §20) [PF21] | PASS | manifest entrys `pack-identity` (`media-tools/pack-identity.json` `94e66e790ac36a6a076e50181705a7a71c66461b19f9bc25cbbd637fe9cf26f0`: ffprobe 9.0.1 `19202b23c0043f15ad1b7bce2344f406fd52bd6efd8f995ce02e7392a1cec52f`, ffmpeg 9.0.1 `72a489eccd008c2ec2c0a5856c5c75bc3d8bbfa90166c4566865c246445e6aa3`, pack manifest `604b387d4d2bbb4535797a0517f19c467409c7d6756531527d16cd46f5463ed7`) and `pack-consistency` (retained §16(c) output `evidence/e21-pack-consistency.txt` `dadd95521d209f603d160fb40867a38769ea5801dddeec3b071877a184eb0c40`): result `pack-consistent` for the live pack, 14 probes and 9 derivation manifests |

## F. S3.2b-3 — Development-host execution (T9)

S3.2b-3 may be scheduled only when every E row is PASS (or NOT TRIGGERED, for E17/E18).

| ID | Requirement | Status |
|---|---|---|
| F1 | Fresh, dedicated Development catalogue and media store, created after the pool freeze | OPEN |
| F2 | Real Model Pack and runtime on the Development host | OPEN |
| F3 | Shipped `1.3.0-candidate` pipeline profile measured (T9 profile identity gate) | OPEN |
| F4 | T9 complete for every pool member (journalled runs, no reuse) | OPEN |
| F5 | `vehicle-subclass-t9-execution-v1` record valid | OPEN |
| F6 | Exact run, export and provenance bindings: one producer identity, the measured profile, exports bound to derivations | OPEN |

## G. S3.2c — pilot (T10)

| ID | Requirement | Status |
|---|---|---|
| G1 | Requirements committed before any result is inspected | OPEN |
| G2 | Labelling guide committed | OPEN |
| G3 | Independent overlap reviewer confirmed | OPEN |
| G4 | Sample binds exactly the T9 export and derivation sets (`--verify-sample`) | OPEN |
| G5 | Blind primary and overlap labelling | OPEN |
| G6 | Adjudication completed where needed | OPEN |
| G7 | Labels frozen | OPEN |
| G8 | T6 measurement and requirement comparison produced | OPEN |
| G9 | Threshold freeze decision recorded on the measurement (ADR-016 §3). Either `minShare`/`minMatchedDetections` are frozen at the measured profile's values; or any change is a new pipeline-profile version, which needs its own Development tuning/evaluation path and a new measurement before G9 can PASS | OPEN |

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
