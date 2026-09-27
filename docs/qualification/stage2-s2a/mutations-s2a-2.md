# S2a.2 mutation record

- **Slice:** S2a.2, the platform accepts completion 3.2 (nothing emits it)
- **Plan:** `docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md` §12.1, §12.2, §18
- **Base:** `main@c95ce6fba3fc12c82a9d8d8620caaf0a755b4229`

## Procedure

This is the §12.2 procedure used for S2a.1:

1. Apply one textual mutation per row. The anchor must occur exactly once.
2. Build the mutated tree first, so any failure is semantic rather than a build error. For .NET, `dotnet build` of the test project; for Python, `compile()`.
3. Run the named tests:
   - Application tests, or the PostgreSQL 18 integration tests, for .NET rows;
   - the named `src/vision/tests` modules for Python and `verify_repo` rows.
4. Restore the file byte for byte.

A mutation is **caught** when at least one test fails; the first failing test is listed. After the run, every mutated file was compared against its SHA-256 taken before the run: 13 files, all identical.

N15 (the derived-identity prefix check) first **survived**. Its filter ran only the id-swap test, and that test swaps ids of different lengths, so the length check rejected them before the prefix was read. Two changes followed:

- the swap test now also uses ids of the right length with the wrong prefix;
- N15 was re-run with `VisionResultValidatorV32Tests` added to its filter, and it is now caught.

## Coverage of §10 platform codes

Each code below has a triggering test (`VisionResultValidatorV32Tests`, the shared corpus `contracts/test-vectors/control-plane-v3.2-invalid.json`) and at least one mutation that silences it:

| Code | Mutations |
|---|---|
| `provenance_capability_invalid` | N11, N14 |
| `provenance_model_pack_invalid` | N15, N16 |
| `provenance_runtime_pack_invalid` | N17 |
| `provenance_runtime_pack_required` | N19, N20, N21 |
| `provenance_runtime_pack_source_invalid` | N22 |
| `provenance_component_binding_invalid` | N18 |
| `provenance_v32_field_in_v3_body` | N10 |
| worker `completion_32_requires_binding` | P01 |

## Results: 41 of 41 caught

| ID | Mutation | File | First failing test | Result |
|---|---|---|---|---|
| N01 | digest drops Add(ComponentBindingSha256) | `App/VisionResultValidator.cs` | `VisionResultValidatorTests.DigestChangesWithComponentBindingSha` | caught |
| N02 | digest drops Add(CapabilityId) | `App/VisionResultValidator.cs` | `CompletionExchange32Tests.EveryComponentIdentityMemberIsInTheDigest` | caught |
| N03 | digest appends ModelPackId and RuntimePackId in the other order | `App/VisionResultValidator.cs` | `CompletionExchange32Tests.V32ExamplesMatchTheirPinnedFileHashesAndDigests` | caught |
| N04 | digest appends the identity at the end instead of after platformLockSha256 | `App/VisionResultValidator.cs` | `CompletionExchange32Tests.EveryComponentIdentityMemberIsInTheDigest` | caught |
| N05 | v3.2 domain tag reuses v3 | `App/VisionResultValidator.cs` | `CompletionExchange32Tests.V32ExamplesMatchTheirPinnedFileHashesAndDigests` | caught |
| N06 | 3.2 normalised to V3 (domain from the platform default) | `App/VisionResultValidator.cs` | `VisionFinalizationReplayTests.AStored32PayloadNeverMatchesItsDigestUnderTheV3Domain` | caught |
| N07 | 3.2 not an Evidence Set | `App/VisionResultValidator.cs` | `VisionResultValidatorV32Tests.EvidenceSetRulesStillApplyTo32` | caught |
| N08 | sealing-plan crop quota only for V3 | `App/EvidenceSealingPlan.cs` | `EvidenceSealingPlanTests.TheV32EvidenceSetIsSealedAndQuotaCheckedExactlyLikeV3` | caught |
| N09 | executor accepts only V3 | `platform/Mavi.Infrastructure/Finalization/VisionFinalizationExecutor.cs` | `VisionFinalizationExecutorTests.A32HandOffIsFinalizedUnderItsOwnDomainAndAttestsItsComponentIdentity` | caught |
| N10 | 3.2 fields tolerated in earlier bodies | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.AnyOneComponentIdentityMemberIsRefusedInAnEarlierEvidenceSetBody` | caught |
| N11 | 3.2 rules not applied (identity optional) | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorTests.A32BodyWithoutThe32FieldsIsRejected` | caught |
| N12 | persisted provenance read under the earlier rules | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.ThePersistedProvenanceReaderAppliesThe32RulesToA32Row` | caught |
| N13 | persisted provenance always read under 3.2 | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.ThePersistedProvenanceReaderAppliesThe32RulesToA32Row` | caught |
| N14 | capability registry not consulted | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.MalformedButPlausibleMembersAreRefusedWithTheirCode` | caught |
| N15 | derived-identity prefix not checked | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.MalformedButPlausibleMembersAreRefusedWithTheirCode` | caught |
| N16 | derived-identity hex not checked | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.MalformedButPlausibleMembersAreRefusedWithTheirCode` | caught |
| N17 | runtimePackId grammar not checked | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.MalformedButPlausibleMembersAreRefusedWithTheirCode` | caught |
| N18 | componentBindingSha256 not checked | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.MalformedButPlausibleMembersAreRefusedWithTheirCode` | caught |
| N19 | installed pack need not name its Runtime Pack | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.AnInstalledPackMustNameItsRuntimePack` | caught |
| N20 | unpacked environment may borrow a Runtime Pack id | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.AnUnpackedEnvironmentNamesNoRuntimePack` | caught |
| N21 | unpacked environment may be verified | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.AnUnpackedEnvironmentIsNeverVerified` | caught |
| N22 | unknown runtimePackSource accepted | `App/VisionRuntimeProvenanceParser.cs` | `VisionResultValidatorV32Tests.MalformedButPlausibleMembersAreRefusedWithTheirCode` | caught |
| N23 | codec stores a fixed 3.1 version | `App/VisionFinalizationPayloadCodec.cs` | `VisionFinalizationReplayTests.AStored32PayloadNeverMatchesItsDigestUnderTheV3Domain` | caught |
| N24 | codec reads any stored version | `App/VisionFinalizationPayloadCodec.cs` | `CompletionExchange31Tests.FinalizationPayloadCodecRejectsSynchronousAndMalformedPayloads` | caught |
| N25 | hand-off response ignores the worker's version | `platform/Mavi.Contracts/Worker/VisionJobCompleteContracts.cs` | `CompletionExchange32Tests.TheV32ResponseExampleIsTheFactoryOutput` | caught |
| N26 | hand-off response answers any version | `platform/Mavi.Contracts/Worker/VisionJobCompleteContracts.cs` | `CompletionExchange32Tests.TheHandOffEchoesTheAsynchronousVersionTheWorkerSpoke` | caught |
| N27 | 3.2 missing from the asynchronous set | `platform/Mavi.Contracts/Worker/WorkerContractRules.cs` | `CompletionExchange31Tests.AcceptanceListsFollowTheActivationGate` | caught |
| N28 | 3.2 also accepted synchronously | `platform/Mavi.Contracts/Worker/WorkerContractRules.cs` | `CompletionExchange31Tests.AcceptanceListsFollowTheActivationGate` | caught |
| N29 | 3.2 not asynchronous (codec refuses it) | `platform/Mavi.Contracts/Worker/WorkerContractRules.cs` | `VisionFinalizationReplayTests.AStored32PayloadNeverMatchesItsDigestUnderTheV3Domain` | caught |
| N30 | null component identity written to 3.1 JSON | `platform/Mavi.Contracts/Worker/VisionJobCompleteContracts.cs` | `CompletionExchange32Tests.A31ContractSerialisesByteIdenticallyWithTheNewMembersPresentButNull` | caught |
| N31 | endpoint answers every hand-off as 3.1 | `platform/Mavi.Api/Endpoints/VisionJobEndpoints.cs` | `VisionFinalizationExecutorTests.A32HandOffIsFinalizedUnderItsOwnDomainAndAttestsItsComponentIdentity` | caught |
| N32 | attestation drops the capability | `platform/Mavi.Api/Endpoints/ProcessingEndpoints.cs` | `ProcessingRunAttestationApiTests.Completion32RunAttestsItsComponentIdentity` | caught |
| P01 | worker settings allow 3.2 | `mavi_vision/common/settings.py` | `tests/test_worker_settings.py::test_the_shipped_completion_default_is_3_1_and_3_0_remains_the_rollback_setting` | caught |
| P02 | worker drops the hand-off version echo check | `mavi_vision/worker/client.py` | `tests/test_worker_completion_v3.py::test_a_3_1_worker_refuses_a_3_2_hand_off_acknowledgement` | caught |
| P03 | worker reads a 3.2 hand-off as synchronous | `mavi_vision/worker/client.py` | `tests/test_worker_completion_v3.py::test_the_worker_recognises_completion_3_2_as_an_asynchronous_version` | caught |
| P04 | worker cannot read a 3.2 acknowledgement | `mavi_vision/common/control_plane.py` | `tests/test_contract_schema_canonicalization.py::test_the_3_2_finalization_response_example_is_schema_valid_and_read_by_the_worker` | caught |
| P05 | worker completion model admits 3.2 | `mavi_vision/common/control_plane.py` | `tests/test_worker_completion_v3.py::test_the_worker_never_emits_a_completion_3_2_body` | caught |
| V01 | verify_repo stops calling the 3.2 check | `tools/verify_repo.py` | `tests/test_verify_repo_completion_v32.py::test_completion_3_2_drift_fails_closed` | caught |
| V02 | verify_repo delta loses the unpacked pairing rule | `tools/verify_repo.py` | `tests/test_verify_repo_completion_v32.py::test_the_published_3_2_contract_is_the_pinned_delta` | caught |
| V03 | verify_repo skips the shared negative corpus | `tools/verify_repo.py` | `tests/test_verify_repo_completion_v32.py::test_completion_3_2_drift_fails_closed` | caught |
| V04 | verify_repo skips the example pin | `tools/verify_repo.py` | `tests/test_verify_repo_completion_v32.py::test_completion_3_2_drift_fails_closed` | caught |
