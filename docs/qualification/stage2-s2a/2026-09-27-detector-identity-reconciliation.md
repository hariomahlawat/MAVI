# Detector identity reconciliation: component binding v2 cut-over (Stage 2 S2a.3)

- **Plan:** `docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md` §9 (and P-2, P-3, P-15, P-17)
- **Decision:** ADR-014
- **Base:** `main@0e5bad6ac0476e275aadb507d4817cffe31006f5`
- **Behavioural regression evidence:** `record-replay-s2a-3/` beside this file, checked by `tools/qualification/tests/test_s2a_provenance_diff.py`

S2a.3 moves the RTMDet detector from the v1 composition (a model manifest, a qualification record, a runtime profile carrying the model's checkpoint and config, and a v1 component-requirements file) to the component binding v2. It changes **identities, not bytes**: the checkpoint, the resolved config, the pipeline profile, every lock and every Runtime Pack are byte-identical. **No gate result is carried forward. RTMDet remains `pending` on every variant, and the manifest remains `unverified`.**

## Identities

| Identity | v1 (consumed at the base) | v2 (this head) | Where it is re-derived |
|---|---|---|---|
| Runtime profile SHA-256 | `b3c59ac4e535d5e2e7356fef55f5266937e56751207f37a06dd13140b01c6873` | `296b034d5f80ee13ab3f3bf86ed41b84109abd47d0103600b15b24078412acfb` | qualification record v2 `runtimeProfileSha256`; the resolver (`check_record_identity`); `verify_repo`; every run's provenance |
| Model manifest SHA-256 | `0049875d8190af7f268b4613cba99afef8a9f0d39a64471fd84f9ab0bc8d8d7d` | `bc8127c1c00513a90f1b00325dcae3d4f31243ef1ce04ebe38350f945cb79c90` | qualification record v2 `modelManifestSha256`; resolver; `verify_repo` |
| `modelPackId` | `mavi-model-v1-2abf67800cec8a9c63d735bf50e44ac695e8b8ccf01397e2cfd884305a5638b4` | `mavi-model-v2-86754e364c7560c407b531900de58eb5e66fd365685677f8f24a5a61b3186700` | derived from the source manifest (P-3) by `model_manifest_v2`; pinned by the binding; emitted by `build_model_pack.py` and compared in `vision-model-pack.yml` |
| `qualificationId` | `rtmdet-m-coco-phase1-v1` | `rtmdet-m-coco-phase1-v2` | binding `capabilityBindings[detector]`; record v2 `supersedes` the v1 id |
| Qualification record SHA-256 | `7d7083d902f8a8ff4a8ebe4d114fd03255b1b0c0192461357b584a1a01f3e7b9` | `100b8f102697dfaa7ac4cd02abfc7d83fd0fbbe73adaa1908fbf3f6dcfa40e40` | provenance `qualificationSha256` |
| Component binding SHA-256 | v1 requirements file `3bfa97a9727024415f6023722b360c4c6957de2bea164829da08cee52b1fc1f6` | `081c0c8948a16480626dd6d05f18c4037758e1cf513c8bf891d06ee7fb9f2819` | provenance `componentBindingSha256` (P-11); Task-10 evidence; bundle id |
| `runtimePackId` linux-x86_64-cpu | `mavi-runtime-v2-bd94fded938183dce8dc50390d48e97d913d9dad9dc98b528a962ad32314ff61` | **unchanged** | re-derived from the tracked lock by the resolver, `verify_repo`, the component-boundary gate and Task 12 |
| `runtimePackId` windows-x86_64-cpu | `mavi-runtime-v2-5d6229da58554bc951ddc8bd719574c1b33109a7916afdf717339d8847e39e61` | **unchanged** | as above |
| `runtimePackId` windows-x86_64-cuda | `mavi-runtime-v2-89fd8bfcc32fb1bd8ab77f0deb9f33675ae228c75ffd11f13e6838e990003a1d` | **unchanged** | as above (Development only, ADR-009, P-13) |
| `runtimePackId` linux-x86_64-cuda | — (pending, no lock) | **none**: class A, absent from the binding, `null` in the record | P-17 classification from the tracked lock files |
| Checkpoint SHA-256 | `229f527ca88498e8894a778a62a878a322b4a3ea2cae09ea537d34b7e907792b` | unchanged | manifest v2 artefact `checkpoint` |
| Resolved config SHA-256 | `377d9f57abf6a73a6c308f765b70fc571715448c62998819d609d2eebc7c5ee3` | unchanged | manifest v2 artefact `resolved-config` (no longer in the runtime profile) |
| Licence notice SHA-256 | — (not an artefact in v1) | `874b8b2e6f12306a1ff7812c068a0dbf880418b8ac1f7190382bd6c6da9f23a1` | manifest v2 artefact `licence-notice`, in the `modelPackId` (P-15) |
| Pipeline profile SHA-256 | `503225be736d9622ed110aa69e49a83dde4ae02c858d5e8fa41e527b1c4b23fb` | unchanged | record v2 `policies.pipelineProfileSha256`, reconciled live by the resolver and `verify_repo` |

The licence notice is the Apache-2.0 `LICENSE` of `open-mmlab/mmdetection` at the commit already pinned for the model (`44ebd17b145c2372c4b700bfb9cb20dbd28ab64a`), taken as the Git blob (`git show <commit>:LICENSE`) so no checkout filter can change its bytes. `modelPackId` v2 is `mavi-model-v2-` + SHA-256 of the canonical JSON of `{schemaVersion: "mavi-vision-model-pack-v2", modelId: "rtmdet-m-coco-phase1", modelVersion: "1.0.0", capabilityIds: ["detector"], artifacts: [{checkpoint, 229f527c…}, {licence-notice, 874b8b2e…}, {resolved-config, 377d9f57…}]}`. It carries no authored id and no byte size (P-3, P-14). It is frozen once here and is not changed by S2a.4.

## How the v2 artefacts were produced

The four v2 files (`src/vision/config/components/phase1-bindings-v2.json`, `models/manifests/rtmdet-m-coco-phase1-v2.json`, `models/qualifications/rtmdet-m-coco-phase1-v2.json`, and `src/vision/runtime/mmdetection-phase1-v1/runtime.json` v2) are the output of the one-shot generator `tools/vision/migrate_component_binding_v1.py`, run over the v1 files consumed at the base. `src/vision/tests/test_migrate_component_binding_v1.py` re-runs it and requires the committed bytes to equal its output (`test_the_published_v2_artefacts_are_exactly_the_generator_output`).

The v1 files are deleted from the release roots (no runtime dual reader, plan §5). Byte-identical copies are frozen as test fixtures under `src/vision/tests/fixtures/component-binding-v1/`, pinned by SHA-256 (`test_frozen_v1_inputs_are_the_bytes_the_cut_over_consumed`). They are what the frozen hashes in the table above are hashes of. Every loader, `verify_repo`, the resolver, the Model Pack builder and the component store refuse them.

The v1 contents, as consumed (`…fixtures/component-binding-v1/`):

- **manifest** `rtmdet-m-coco-phase1-v1.manifest.json`:
  - schema `1.0`, `modelId: rtmdet-m-coco-phase1`, `modelVersion: 1.0.0`, `backend: mmdetection`, `architecture: rtmdet-m`;
  - checkpoint `rtmdet-m-coco-phase1-v1/rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth` (`229f527c…`) and resolved config `rtmdet-m-coco-phase1-v1/rtmdet_m_resolved.py` (`377d9f57…`);
  - `runtimeProfileId: mmdetection-phase1-v1`, `verificationStatus: unverified`, `qualificationId: null`.
- **record** `rtmdet-m-coco-phase1-v1.qualification.json`:
  - `qualificationId: rtmdet-m-coco-phase1-v1`, bound to manifest `0049875d…`, runtime profile `b3c59ac4…` and pipeline profile `503225be…`;
  - `requiredGates` all `pending` (the four variants, `windows-offline-install`, `linux-offline-install`, `cctv-quality-baseline`, `linux-nvidia-recovery-performance`), and `overallResult: pending`.
- **component requirements** `mmdetection-phase1-v1.json`:
  - schema `mavi-vision-component-requirements-v1`;
  - `modelPack.modelPackId: mavi-model-v1-2abf6780…38b4`;
  - `runtimePacks` for the three class-B variants, with the three ids above.

The v2 record has every gate of every variant `pending`, `qualifiedProfiles: []`, `evidence: {}`, `overallResult: pending` and `supersedes.qualificationId: rtmdet-m-coco-phase1-v1` ("model bytes unchanged; no gate result carried forward"). The v2 manifest is `verificationStatus: unverified`, `qualificationId: null`, `licence.reviewStatus: pending-review`.

## Runtime Pack ids are unchanged: proof

- The lock and requirements files under `src/vision/runtime/mmdetection-phase1-v1/` have no diff at this head; the binding pins the same `thirdPartyLockSha256`/`runtimeRequirementsSha256`/`nativeAbi` as the v1 file.
- `test_migrate_component_binding_v1.py::test_the_cut_over_changes_no_runtime_pack_identity`, `test_component_identity.py::test_the_runtime_pack_identities_the_cut_over_consumed_are_unchanged` and `test_resolver.py::test_every_class_b_binding_id_is_the_lock_derived_id` compare the binding with the ids at the base and re-derive each from the tracked lock.
- At start-up the resolver re-derives every pinned id from its tracked lock (`runtime_pack_binding_id_mismatch:<variant>`); `verify_repo` runs the same family load.
- CI re-derives them: `vision-runtime-component-boundary.yml` compares each class-B variant with the binding, and Task 12 compares the pack it builds from the lock with the binding entry (`task12_runtime_pack_binding_mismatch`).

## Variant classes (P-17)

| Variant | Class | Binding | Record `runtimePackId` | Status |
|---|---|---|---|---|
| linux-x86_64-cpu | B | declared | the binding's id | pending |
| windows-x86_64-cpu | B | declared | the binding's id | pending |
| windows-x86_64-cuda | B (Development only) | declared | the binding's id | pending |
| linux-x86_64-cuda | A | absent | `null` | pending |

## Behavioural regression (C7)

The same two real clips (MOT17-02-FRCNN and MOT17-13-FRCNN, 1080p MJPEG, the S1 B1 originals; SHA-256 recorded in each summary) were run through the B1 producer `tools/vision/dev/measure_evidence_real_clips.py` on Linux CPU:

- once at the accepted baseline `c176b048` with the v1 composition;
- once at the S2a.3 head, composed through the binding.

The retained summaries and the SHA-256 of both runs' recorded detection streams and evidence candidates are in `record-replay-s2a-3/`. `tools/qualification/tests/test_s2a_provenance_diff.py` requires:

- zero differences in every compared section (`s1_b1.normalized`, which strips only host timing and provenance);
- byte-identical detection streams and candidates;
- provenance differences only in the allow-listed identity keys;
- the identity keys changed exactly as the table above says;
- the checkpoint, config, pipeline profile, runtime variant and `unverified` label unchanged.

The result is recorded in `record-replay-s2a-3/README.md`.

## What this does not claim

- No gate passed; no Production release; no Production or CUDA promotion. Windows CUDA stays Development-only (ADR-009).
- **S1 remains OPEN.** The S1 identities are pre-S2a. After S2a.3 the worker emits 3.2, and the S1 checker's activation rule reads a completion default that no longer exists, so no S1 closure is claimed or implied by this slice (see the S1 closure-identity note).
- Phase-1 promotion is fenced (`v2_promotion_not_supported_by_this_slice`); a later slice defines v2 promotion in an ADR.
