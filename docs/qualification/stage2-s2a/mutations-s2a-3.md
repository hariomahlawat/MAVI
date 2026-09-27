# S2a.3 mutation record

- **Slice:** S2a.3, the behavioural atomic Component Binding v2 cut-over
- **Plan:** `docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md` §12.1, §12.2, §19
- **Base:** `main@0e5bad6ac0476e275aadb507d4817cffe31006f5`

## Procedure

This is the §12.2 procedure, as for S2a.1 and S2a.2:

1. Apply one mutation per row. A row may change more than one site when one rule is enforced in more than one place (K02: the class-A release-lock requirement is checked both at load, `check_variant_status_pair`, and at classification, `classify_variant`; removing it from one site alone proves nothing). Every anchor must occur exactly once.
2. Compile the mutated Python file first, so any failure is semantic. PowerShell files are parse-checked by the test script itself.
3. Run the named tests:
   - the named `src/vision/tests` modules for runtime, tool and `verify_repo` rows;
   - `tools/phase1/tests` for the promotion fence;
   - the PowerShell contract script (`Test-MaviVisionModelPackStateContracts.ps1`, PowerShell 7 on Linux) for installer and launcher rows.
4. Restore the file byte for byte.

A mutation is **caught** when at least one test fails; the first failing test is listed. After the run every mutated file was compared against its SHA-256 taken before the run: 14 files, all identical.

K04 (the family-level "a class-B variant must be declared in the binding" rule) first **survived**. The existing tests deleted a variant from the binding, but the record check raises the same code, `binding_variant_missing`, for the same fixture, so the family check was never isolated. Two changes followed:

- `test_resolver.py::test_the_family_itself_refuses_a_binding_that_omits_a_class_b_variant` calls `load_role_family` alone, before any record is read;
- `test_verify_repo_vision_metadata.py::test_a_class_b_variant_missing_from_the_binding` now requires the family message.

K04 was re-run and is now caught.

## Coverage

- **Both P-17 class-A mutations (§12.1):** K01 drops the variant-status requirement, and K02 drops the release-lock-status requirement at both sites. Each is caught by the plan's exact fixture:
  - K01: `linux-x86_64-cuda` carries a loader-valid `qualified-development-hardware` entry with development evidence, its lock is still `pending-hardware-qualification`, and there is no lock file;
  - K02: the variant is pending, its lock is `pending-wheelhouse-freeze` (a legal status), and there is no lock file.
  Both are refused as `runtime_variant_classification_invalid:linux-x86_64-cuda`, by the resolver and by `verify_repo`.
- **Resolver fail-closed codes (§10):** R01–R29 and C01–C03 silence, in turn:
  - binding and capability: disabled, unimplemented, capability mismatch, runtime incompatibility;
  - artefacts and indexes: artefact hash, manifest/record ambiguity, lookup by the derived id rather than `modelId`;
  - record identity: every identity key (model pack, manifest, runtime profile, licence notice), the unverified-claims rule, and policies (required, reconciled live);
  - Runtime Pack: the undeclared variant, the lock-derived binding id, the installed-pack re-derivation, variant, binding and interpreter, and the unpacked-environment null id;
  - every Production policy step: unverified, pack required, Development CUDA, variant not passed, profile evidence, stale policy;
  - the P-16 contract rules.
- **Provenance (P01–P07):** no fabricated Runtime Pack id; an unpacked environment is never verified; verified needs an installed pack and the observed variant passed; the override forces unverified; no relabelling of the variant; the binding SHA is the resolved one.
- **Settings, client and entry point (C04–C09):** the override is refused in Production; each retired variable, in any case, is refused, including by `main` before settings load; a completion naming another binding is refused; an overridden completion is never verified.
- **`verify_repo` (K03–K06, V01–V07):** every rule of plan §6 that is not the resolver's own shared function. The shared ones (identity, policy, the family and P-17) are covered through R09–R17 and K01–K04 against both suites.
- **Pack tools and the promotion fence (T01–T06):** licence notice required, sizes measured, kit completeness and unbound components, pairwise artefact ownership, and the v2 promotion fence.
- **Installer and launcher (S01–S03, plan §7 tests 2–4):** a v1 install state is rejected; installing one pack never replaces the store; two directories with one `modelPackId` are ambiguous.

The .NET platform is unchanged by S2a.3 apart from one test harness setting (`S1FinalizationRecoveryTests` now sets the Development override instead of the retired variable), so this record adds no .NET rows; the S2a.2 .NET rows still hold.

## Results: 67 of 67 caught

| ID | Mutation | File | First failing test | Result |
|---|---|---|---|---|
| R01 | disabled binding tolerated | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_disabled_binding_blocks_its_role | caught |
| R02 | unimplemented capability starts | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_unimplemented_capability_never_starts | caught |
| R03 | pack without the capability accepted | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_binding_to_a_pack_without_the_capability_is_refused | caught |
| R04 | pack for another family accepted | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_manifest_for_another_family_is_incompatible | caught |
| R05 | artefact bytes not re-hashed | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_artefact_byte_change_is_refused[checkpoint] | caught |
| R06 | manifest looked up by modelId, not derived id | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_binding_naming_no_manifest_is_refused | caught |
| R07 | two manifests with one derived id accepted | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_two_manifests_deriving_one_id_are_ambiguous | caught |
| R08 | two records with one id accepted | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_two_records_with_one_id_are_ambiguous | caught |
| R09 | record model pack id not compared | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_record_for_another_model_pack_is_refused | caught |
| R10 | record manifest SHA dropped from the identity | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_record_identity_drift_is_refused[manifest-sha] | caught |
| R11 | record runtime profile SHA dropped from the identity | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_record_identity_drift_is_refused[runtime-profile-sha] | caught |
| R12 | licence notice digest dropped from the identity | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_record_identity_drift_is_refused[licence-sha] | caught |
| R13 | unverified manifest may claim a record | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_unverified_manifest_cannot_claim_a_record | caught |
| R14 | detector record may omit its policies | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_detector_record_must_carry_its_policies | caught |
| R15 | policy copied, not reconciled with the live profile | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_record_for_another_pipeline_policy_is_refused[pipelineProfileSha256] | caught |
| R16 | undeclared variant falls back to another entry | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_class_a_variant_never_starts | caught |
| R17 | pinned binding id not re-derived from the lock | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_pinned_runtime_pack_id_no_lock_derives_is_refused | caught |
| R18 | installed pack id not re-derived | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_installed_pack_whose_identity_does_not_re_derive_is_refused[change0-runtime_pack_manifest_mismatch:id] | caught |
| R19 | installed pack for another variant accepted | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_installed_pack_for_another_variant_is_refused | caught |
| R20 | installed pack not the binding pack | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_installed_pack_with_other_inputs_is_not_the_binding_pack | caught |
| R21 | installed pack on another interpreter accepted | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_an_installed_pack_on_another_interpreter_is_refused | caught |
| R29 | installed pack claimed without running from it (cold-review P2, added after the review) | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_a_pack_manifest_the_running_interpreter_does_not_belong_to_is_refused | caught |
| R22 | unpacked environment fabricates the binding's id | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_development_resolves_an_unpacked_environment_truthfully | caught |
| R23 | Production accepts an unverified manifest | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_production_refuses_an_unverified_manifest | caught |
| R24 | Production accepts an unpacked environment | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_production_requires_an_installed_runtime_pack | caught |
| R25 | Development CUDA hardware satisfies Production | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_windows_cuda_development_hardware_never_satisfies_production | caught |
| R26 | Production accepts a variant the record has not passed | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_production_refuses_a_variant_the_record_has_not_passed | caught |
| R27 | Production accepts missing profile evidence | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_production_requires_profile_evidence_for_every_variant_gate | caught |
| R28 | Production accepts a stale deployment policy | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_production_refuses_a_stale_deployment_policy | caught |
| C01 | override allowed in Production (resolver) | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_the_completion_contract_fails_closed[role1-3.1-True-emittable1-completion_override_forbidden_in_production] | caught |
| C02 | a 3.1 contract exists without the override | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_worker_completion_v3.py::test_no_completion_contract_emits_a_pre_cut_over_version_without_the_override | caught |
| C03 | role contract not compared with what the worker emits | `src/vision/mavi_vision/runtime/resolver.py` | tests/test_resolver.py::test_the_completion_contract_fails_closed[role4-None-False-emittable4-role_provenance_contract_mismatch] | caught |
| C04 | override allowed in Production (settings) | `src/vision/mavi_vision/common/settings.py` | tests/test_worker_settings.py::test_the_completion_override_is_refused_in_production | caught |
| C05 | retired MAVI_COMPLETION_SCHEMA_VERSION tolerated | `src/vision/mavi_vision/common/settings.py` | tests/test_worker_settings.py::test_every_retired_v1_composition_variable_is_refused[MAVI_COMPLETION_SCHEMA_VERSION] | caught |
| C06 | retired variables matched case-sensitively | `src/vision/mavi_vision/common/settings.py` | tests/test_worker_settings.py::test_every_retired_v1_composition_variable_is_refused[MAVI_MODEL_MANIFEST_PATH] | caught |
| C07 | worker main does not refuse the retired environment | `src/vision/mavi_vision/worker/main.py` | tests/test_worker_main.py::test_main_refuses_a_v1_composition_environment_before_settings | caught |
| C08 | client sends provenance naming another binding | `src/vision/mavi_vision/worker/client.py` | tests/test_worker_completion_v3.py::test_a_provenance_naming_another_binding_is_refused_before_anything_is_sent | caught |
| C09 | overridden completion may be verified | `src/vision/mavi_vision/worker/client.py` | tests/test_worker_completion_v3.py::test_an_overridden_completion_is_never_verified | caught |
| P01 | unpacked environment may carry a Runtime Pack id | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_an_unpacked_environment_cannot_carry_a_runtime_pack_id | caught |
| P02 | unpacked environment may be verified | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_an_unpacked_environment_is_never_verified | caught |
| P03 | verified without an installed pack | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_verified_requires_pack | caught |
| P04 | verified without the observed variant passed | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_verified_requires_the_observed_variant_to_have_passed | caught |
| P05 | override keeps a verified label | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_override_forces_unverified[3.1] | caught |
| P06 | live runtime relabelled to the resolved variant | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_the_live_runtime_must_be_on_the_resolved_variant | caught |
| P07 | binding SHA not the resolved binding's | `src/vision/mavi_vision/runtime/provenance.py` | tests/test_runtime_provenance.py::test_the_binding_sha_is_the_resolved_binding_file_identity | caught |
| K01 | class A without the variant-status requirement | `src/vision/mavi_vision/runtime/variants.py` | tests/test_resolver.py::test_p17_class_a_variant_status_mutation_is_refused | caught |
| K02 | class A without the release-lock-status requirement | `src/vision/mavi_vision/runtime/variants.py` (2 sites) | tests/test_resolver.py::test_p17_class_a_release_lock_status_mutation_is_refused | caught |
| K03 | binding may declare the class-A variant | `src/vision/mavi_vision/runtime/component_relationships.py` | tests/test_resolver.py::test_class_a_cannot_be_declared_in_the_binding | caught |
| K04 | binding may omit a class-B variant | `src/vision/mavi_vision/runtime/component_relationships.py` | tests/test_resolver.py::test_the_family_itself_refuses_a_binding_that_omits_a_class_b_variant | caught |
| K05 | class-B record may carry a null Runtime Pack id | `src/vision/mavi_vision/runtime/component_relationships.py` | tests/test_verify_repo_vision_metadata.py::test_a_null_runtime_pack_id_for_a_declared_variant[windows-x86_64-cpu] | caught |
| K06 | class-A record may carry a Runtime Pack id | `src/vision/mavi_vision/runtime/component_relationships.py` | tests/test_resolver.py::test_a_record_cannot_name_a_runtime_pack_for_class_a | caught |
| V01 | a second binding accepted | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_a_second_binding_is_not_supported | caught |
| V02 | shared pack directory accepted | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_a_shared_pack_directory | caught |
| V03 | unbound record accepted | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_an_unbound_record | caught |
| V04 | unverified manifest may claim a qualification | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_an_unverified_manifest_claiming_a_qualification | caught |
| V05 | verified manifest without a qualified runtime | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_a_verified_manifest_requires_a_qualified_runtime_profile | caught |
| V06 | record of an unverified manifest may pass | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_a_record_bound_to_an_unverified_manifest_stays_pending | caught |
| V07 | v1 manifests skipped instead of refused | `tools/verify_repo.py` | tests/test_verify_repo_vision_metadata.py::test_a_v1_manifest_is_refused | caught |
| T01 | builder omits the licence notice | `tools/vision/build_model_pack.py` | tests/test_model_pack_builder.py::test_a_missing_licence_notice_input_is_refused | caught |
| T02 | builder writes an authored size | `tools/vision/build_model_pack.py` | tests/test_model_pack_builder.py::test_every_declared_artefact_ships_with_a_measured_size | caught |
| T03 | kit completeness not enforced | `tools/vision/sync_offline_vision_components.py` | tests/test_offline_vision_component_store.py::test_a_kit_without_a_bound_model_pack_is_incomplete | caught |
| T04 | unbound kit component accepted | `tools/vision/sync_offline_vision_components.py` | tests/test_offline_vision_component_store.py::test_a_pack_the_binding_does_not_reach_is_refused | caught |
| T05 | two packs may share artefact bytes | `tools/vision/verify_offline_component_ownership.py` | tests/test_offline_component_ownership.py::test_rejects_same_heavy_artifact_in_runtime_and_model_packs | caught |
| T06 | promotion fence opened | `tools/phase1/v2_promotion_fence.py` | tools/phase1/tests/test_promote_phase1_release.py::test_every_public_writer_function_refuses[build_promoted_metadata] | caught |
| S01 | installer upgrades a v1 install state in place | `tools/setup/Install-MaviVisionModelPack.ps1` | Expected failure containing 'model_install_state_v1_rejected'. | caught |
| S02 | installer replaces the whole store | `tools/setup/Install-MaviVisionModelPack.ps1` | Cannot find path '<temp store>/rtmdet-m-coco-phase1-v1' because it does not exist. | caught |
| S03 | launcher takes the first of two matching packs | `tools/setup/Mavi.VisionRuntime.Common.psm1` | Two store directories carrying one modelPackId were not reported as ambiguous. | caught |
