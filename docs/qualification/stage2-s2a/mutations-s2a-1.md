# S2a.1 mutation record

- **Slice:** S2a.1, the v2 contracts (Python only; no shipped behaviour)
- **Plan:** `docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md` §12.2
- **Base:** `main@1a20a562f73b7fbd8e7ecb884fb3f1e917510968`

## Procedure

Each row applied one textual mutation to the implementation and compiled the mutated file first, so any failure is semantic rather than a syntax error. It then ran the named test module(s) and restored the file byte for byte. A mutation is **caught** when at least one test fails; the first failing test is listed. This is the same procedure as for PRs #101 and #102.

Every new module is new in this slice, so every new test fails on `main` by construction (import error). This record is the evidence that each individual guard is load-bearing.

M29–M43 cover the guards added after the independent cold review of this slice (licence and detector roles, strict booleans and integers, duplicate JSON keys, gate-set applicability, the stable cross-check error, the family-id rule, control characters, and generator output and identity checks).

## Results: 43 of 43 caught

| ID | Mutation | File (`runtime/` = `src/vision/mavi_vision/runtime/`) | First failing test | Result |
|---|---|---|---|---|
| M01 | binding ordering guard removed | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_binding_rules_fail_closed[<lambda>-capability_bindings_unordered]` | caught |
| M02 | binding duplicate guard removed | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_binding_rules_fail_closed[<lambda>-capability_binding_duplicate]` | caught |
| M03 | per-role required-ness loop removed | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_binding_rules_fail_closed[<lambda>-capability_binding_missing:vision:embedding]` | caught |
| M04 | provenance-contract vocabulary widened to v3.1 | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_binding_rules_fail_closed[<lambda>-role_provenance_contract_unknown:vision-job-complete-v3.1]` | caught |
| M05 | role->family existence check removed | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_binding_rules_fail_closed[<lambda>-runtime_family_unknown:mmdetection-phase2-v1]` | caught |
| M06 | binding schema-version gate removed | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_wrong_or_v1_schema_version_is_rejected[mavi-vision-component-requirements-v1]` | caught |
| M07 | licence-notice presence check removed | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_manifest_rules_fail_closed[<lambda>-model_licence_notice_missing]` | caught |
| M08 | authored sizeBytes accepted | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_authored_byte_size_is_rejected` | caught |
| M09 | unregistered capability section accepted | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_manifest_rules_fail_closed[<lambda>-capability_section_unsupported:ocr]` | caught |
| M10 | detector section made optional | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_manifest_rules_fail_closed[<lambda>-capability_section_missing:detector]` | caught |
| M11 | modelVersion dropped from identity | `runtime/model_pack_identity.py` | `tests/test_model_pack_identity_v2.py::test_golden_vector_pins_the_canonical_encoding` | caught |
| M12 | artifacts not sorted for identity | `runtime/model_pack_identity.py` | `tests/test_model_pack_identity_v2.py::test_identity_is_independent_of_declaration_order` | caught |
| M13 | canonical encoding separators changed | `runtime/component_identity.py` | `tests/test_model_pack_identity_v2.py::test_golden_vector_pins_the_canonical_encoding` | caught |
| M14 | class A without variant-status requirement | `runtime/variants.py` | `tests/test_capability_registry_and_variants.py::test_anything_neither_a_nor_b_fails_closed[qualified-development-hardware-pending-hardware-qualification-False]` | caught |
| M15 | class A without release-lock requirement (loader pair check also removed) | `runtime/variants.py` | `tests/test_capability_registry_and_variants.py::test_anything_neither_a_nor_b_fails_closed[pending-hardware-qualification-pending-wheelhouse-freeze-False]` | caught |
| M16 | runtime profile v2 accepts per-variant resolvedConfigSha256 | `runtime/runtime_profile_v2.py` | `tests/test_runtime_profile_v2.py::test_runtime_profile_rules_fail_closed[<lambda>-runtime_profile_invalid2]` | caught |
| M17 | runtime profile v2 status-pair check removed | `runtime/runtime_profile_v2.py` | `tests/test_runtime_profile_v2.py::test_runtime_profile_rules_fail_closed[<lambda>-runtime_variant_classification_invalid:linux-x86_64-cuda]` | caught |
| M18 | record: null-id variant allowed to pass | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_variant_without_runtime_pack_can_never_pass[<lambda>1]` | caught |
| M19 | record: missing-variant check removed | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_record_rules_fail_closed[<lambda>-qualification_variant_missing:linux-x86_64-cuda]` | caught |
| M20 | record: profile on null-id variant allowed | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_profile_qualification_on_pending_variant_is_rejected` | caught |
| M21 | record: per-variant gate-set equality removed | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_record_rules_fail_closed[<lambda>-qualification_variant_gates_mismatch:windows-x86_64-cpu0]` | caught |
| M22 | relationships: null id accepted for deployable variant | `runtime/component_relationships.py` | `tests/test_component_binding_v2.py::test_record_variant_identity_rules_fail_closed[<lambda>-qualification_runtime_pack_required:windows-x86_64-cpu]` | caught |
| M23 | relationships: id accepted for known-not-releasable variant | `runtime/component_relationships.py` | `tests/test_component_binding_v2.py::test_record_variant_identity_rules_fail_closed[<lambda>-qualification_runtime_pack_forbidden:linux-x86_64-cuda]` | caught |
| M24 | relationships: binding omission read as optional | `runtime/component_relationships.py` | `tests/test_component_binding_v2.py::test_binding_omitting_a_deployable_variant_is_rejected` | caught |
| M25 | generator: non-pending v1 record carried forward | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_passed_v1_record_cannot_be_carried_forward` | caught |
| M26 | generator: stale v1 record accepted | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_inconsistent_or_qualified_v1_state_is_not_migrated[<lambda>-migration_v1_record_stale]` | caught |
| M27 | generator: lock hash cross-check removed | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_inconsistent_or_qualified_v1_state_is_not_migrated[<lambda>-runtime_lock_binding_mismatch:windows-x86_64-cpu]` | caught |
| M28 | generator: licence notice omitted from manifest | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_generated_documents_load_and_relate` | caught |
| M29 | licence notice may be re-pointed at another artefact | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_manifest_rules_fail_closed[<lambda>-model_licence_notice_role_invalid0]` | caught |
| M30 | detector checkpoint and config roles may coincide | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_manifest_rules_fail_closed[<lambda>-detector_section_artifact_roles_invalid0]` | caught |
| M31 | enabled coerced from strings/ints | `runtime/binding.py` | `tests/test_component_binding_v2.py::test_enabled_must_be_a_json_boolean[yes]` | caught |
| M32 | embedding dimension coerced | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_embedding_section_must_be_well_formed[512-capability_section_invalid:embedding]` | caught |
| M33 | duplicate JSON keys accepted (last wins) | `runtime/schema_common.py` | `tests/test_component_binding_v2.py::test_duplicate_json_key_is_rejected` | caught |
| M34 | record may omit or add gate sets | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_detector_record_without_detector_gates_is_rejected` | caught |
| M35 | capability without its own gate set accepted | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_detector_gates_are_not_imposed_on_another_capability` | caught |
| M36 | gate-set scope consistency removed | `runtime/qualification_v2.py` | `tests/test_qualification_record_v2.py::test_gate_set_policy_fails_closed[gate_sets_document4-gate_set_scope_invalid:a-v1]` | caught |
| M37 | record check indexes the binding directly | `runtime/component_relationships.py` | `tests/test_component_binding_v2.py::test_record_check_is_safe_without_the_binding_check_first` | caught |
| M38 | runtime profile id not held to the family-id rule | `runtime/runtime_profile_v2.py` | `tests/test_runtime_profile_v2.py::test_runtime_profile_rules_fail_closed[<lambda>-runtime_profile_id_invalid]` | caught |
| M39 | control characters accepted in identity text | `runtime/schema_common.py` | `tests/test_component_binding_v2.py::test_identity_text_rejects_control_characters[abi\twith-tab]` | caught |
| M40 | generator: one path for two outputs | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_cli_rejects_one_path_for_two_outputs` | caught |
| M41 | generator: requirements hash not cross-checked | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_inconsistent_or_qualified_v1_state_is_not_migrated[<lambda>-runtime_requirements_binding_mismatch:linux-x86_64-cpu]` | caught |
| M42 | generator: v1 modelPackId not re-derived | `tools/vision/migrate_component_binding_v1.py` | `tests/test_migrate_component_binding_v1.py::test_inconsistent_or_qualified_v1_state_is_not_migrated[<lambda>-migration_v1_model_identity_mismatch1]` | caught |
| M43 | modelId not held to kebab form | `runtime/model_manifest_v2.py` | `tests/test_model_manifest_v2.py::test_manifest_rules_fail_closed[<lambda>-model_id_invalid0]` | caught |

## Fail-closed codes outside the table

Every other fail-closed code introduced by S2a.1 is triggered directly by a parametrized negative case in:
- `test_component_binding_v2.py`
- `test_model_manifest_v2.py`
- `test_runtime_profile_v2.py`
- `test_qualification_record_v2.py`
- `test_capability_registry_and_variants.py`
- `test_model_pack_identity_v2.py`
- `test_migrate_component_binding_v1.py`

The §10 codes of later slices (resolver, launcher, installer, kit, platform) are not implemented in S2a.1, so they are not in this record. They belong to the S2a.2–S2a.4 mutation records.
