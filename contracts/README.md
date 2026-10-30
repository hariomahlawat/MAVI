# Worker Contract Artifacts

The worker control-plane contract is version 2.0. C# public contracts, JSON Schemas, checked-in examples and Python Pydantic models are maintained as one compatibility boundary.

Task 13 makes `vision-job-complete-v2` the canonical successful analytical-result contract. It is success-only: processing failures continue to use `vision-job-fail-v2`.

The former observation-oriented `vision-result` v1 scaffold has been retired. New worker/result behavior must not recreate or extend it.

All worker request schemas reject unknown members. Cross-system timestamps use canonical RFC3339 UTC `Z` syntax. Media is referenced by logical storage key and integrity facts; raw video frames and local filesystem paths never cross the normal worker API.

## Completion 3.0 (Track Evidence Set)

`vision-job-complete-v3` carries, per Track, up to four `observations` (roles `representative`, `near-view`, `early-diverse`, `late-diverse`; ranks contiguous in that order; one source frame per role) instead of the 2.0 `representative` member, and a required `evidenceAccounting` block with candidates/admitted/omitted counts and bytes per role. From S1.2a the platform accepts 2.0 and 3.0 and advertises both at `GET /api/vision/contract`; this remains the live set until asynchronous finalization is activated with the F3 release (`VisionFinalization:Enabled`), at which point live 3.0 retires and the same body is submitted as completion 3.1 (below). The schema, example, digest pin and invalid vectors remain the semantic definition of the Evidence Set body in both states. Every other worker contract stays 2.0. Each version has its own server-side digest domain, and a 2.0 body keeps its exact 2.0 digest.

JSON Schema expresses the shape and per-field bounds (including the 64 KiB Representative and 160 KiB supplemental crop caps). The cross-field rules it cannot express — contiguous ranks, unique roles and frames, exact staging crop keys, accounting that matches the descriptors sent, the 1 GiB crop quota — are enforced by the platform validator. `control-plane-v3-invalid.json` marks each vector `rejectedBy: "schema"` or `"validator"` accordingly, and `tools/verify_repo.py` holds both sides to it.

`vision-job-complete-v3.example.json` is a golden fixture: `test-vectors/vision-job-complete-v3-digest.json` pins its file SHA-256 and the digest the platform computes for it. Changing either the example or the v3 digest sequence requires re-pinning deliberately. `test-vectors/vision-job-complete-v3-conformance.json` holds integer-binding cases addressed by JSON pointer, shared by the .NET and Python tests.

**Worker emission (S1.2c; S1.4 F2 adds the 3.1 option; Stage 2 S2a.3 moves the default to 3.2, below).** Until S2a.3 the worker emitted exactly its configured completion version (`MAVI_COMPLETION_SCHEMA_VERSION`, default **3.1** since S1.4 F4-C, paired with the platform gate on; **3.0** was the rollback setting for a platform held off). Since S2a.3 that setting is retired and refused; 3.0 and 3.1 are reachable only through the Development-only `MAVI_COMPLETION_SCHEMA_OVERRIDE`. The worker emits its version only after `GET /api/vision/contract` has listed that version. Until then it leases nothing (logged once per incompatible period); it never falls back to 2.0. Its Pydantic model `VisionJobCompleteV3` also enforces the validator-level rules, so it rejects every vector in `control-plane-v3-invalid.json` (schema- and validator-level). The worker's body for the golden inputs is byte-identical to `vision-job-complete-v3.example.json`, so it reproduces the pinned digest (`src/vision/tests/test_worker_completion_v3.py`). The 2.0 schema, example and models stay for the platform's continued 2.0 acceptance.

**Representative ≠ qualified (ADR-013 §4, amended 2026-09-24).** Under selector `evidence-selector-v1-two-tier` (named in the pipeline profile and bound by `pipelineProfileSha256` in provenance), a `representative` observation may be a *fallback* that did not pass every selector quality floor. `near-view`, `early-diverse` and `late-diverse` observations are always qualified. Completion 3.0 has no per-observation qualified flag; `qualityScore` is carried. No consumer may infer "qualified" from `role == "representative"`. A feature that needs qualification-sensitive Representative input must first introduce or derive an explicit qualification contract.


## Completion 3.1 (asynchronous finalization hand-off)

`vision-job-complete-v3.1` is the completion **exchange** version of the S1.4 B3 asynchronous-finalization architecture (`docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md` §5). Its request body is the 3.0 body with `schemaVersion: "3.1"` and nothing else: the schema is the 3.0 schema with only its title and version const changed (checked by `tools/verify_repo.py`), and the example is the 3.0 golden example with its version swapped. The platform validator normalizes both to `CompletionSchema.V3`, so a 3.1 body has the same `mavi:vision-completion-digest:v3` digest as the identical 3.0 body; the raw version string is never hashed and there is no digest v4.

What differs is the acknowledgement. `vision-job-finalization-response-v3.1` says the platform durably owns the hand-off (`state: "finalizing"`, with `acceptedAtUtc`) or that an exact replay found the job already published (`state: "completed"`, adding `completedAtUtc`). `tracksSubmitted` is the validated Track count of the accepted body in both states; it is not a published count, which is why it is not called `tracksAccepted`. A `finalizing` acknowledgement is not a completion: the worker must keep the current attempt's staging and must not run its successful-completion cleanup.

**Activation (F2 lands the machinery, F3 the finalizer, F4-C ships it on).** Held off (`VisionFinalization:Enabled = false`, by an override since F4-C), the probe advertises `["2.0","3.0"]`, a 3.1 POST is refused, and no job can enter Finalizing. With the shipped default since S1.4 F4-C (`VisionFinalization:Enabled = true`, worker default 3.1), `GET /api/vision/contract` advertises `["2.0","3.1"]` (`["2.0","3.1","3.2"]` from Stage 2 S2a.2, below). A 3.1 `POST …/complete` is one PostgreSQL transaction: lease capability, validation, the capability-free retained payload (`VisionFinalizationPayloadCodec`: no `workerId`, no `leaseToken`) and `Leased → Finalizing`; it seals nothing and publishes nothing. A 3.0 body is refused with `worker_contract_version_unsupported` and never reinterpreted; 2.0 is unchanged and still synchronous. Replay of a 3.1 hand-off authenticates against the retained `LeaseOwner`/`LeaseTokenHash`/`AttemptCount`, re-validates the body and compares the recomputed digest: same capability, attempt and digest → the same `finalizing` acknowledgement with the original `acceptedAtUtc` (or `completed` once the finalizer has published); anything else conflicts. The worker treats `finalizing` as a successful hand-off, keeps the current attempt's staging (the finalizer's input), does not poll, and never falls back to 3.0.


## Completion 3.2 (component identity; Stage 2 S2a.2)

`vision-job-complete-v3.2` is the 3.1 asynchronous exchange plus five component-identity provenance members (`docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md` P-7, §4.5; ADR-014). It is an asynchronous-only version: the activated platform accepts and advertises `["2.0","3.1","3.2"]`; a platform held off never accepts it. The response is `vision-job-finalization-response-v3.2`, the 3.1 response with its version echoed.

| Member | Rule |
|---|---|
| `capabilityId` | required; the closed capability registry (`detector`, `embedding`, `ocr`, `person-attributes`, `plate-detector`, `vehicle-attributes`), mirrored by `mavi_vision.runtime.capabilities` and the platform validator |
| `modelPackId` | required; `mavi-model-v2-` + 64 lower-case hex |
| `runtimePackId` | optional (absent and `null` are the same body); `mavi-runtime-v2-` + 64 lower-case hex |
| `runtimePackSource` | required; `installed-pack` (then `runtimePackId` is required) or `unpacked-environment` (then `runtimePackId` is absent/null **and** `verificationStatus` is `unverified`) |
| `componentBindingSha256` | required; SHA-256 of the component binding file bytes |

The platform checks these identities' grammar and pairing only; it never derives, re-derives or invents a pack identity. A 2.0, 3.0 or 3.1 body carrying any of the five members is refused (`provenance_v32_field_in_v3_body`), and a 3.2 body missing a required one is refused with that member's code (`provenance_capability_invalid`, `provenance_model_pack_invalid`, `provenance_runtime_pack_source_invalid`, `provenance_component_binding_invalid`, `provenance_runtime_pack_invalid`, `provenance_runtime_pack_required`).

3.2 has its own digest domain, `mavi:vision-completion-digest:v3.2`: the v3 sequence with `capabilityId`, `modelPackId`, nullable `runtimePackId`, `runtimePackSource` and `componentBindingSha256` appended immediately after `platformLockSha256`. The retained finalization payload keeps the version the worker spoke, so replay always selects the domain from the stored version: a 3.2 payload can never match its digest as 3.1, and the same body resubmitted under the other version is a conflict.

The schema is generated from the 3.1 schema by the one delta in `tools/verify_repo.py` (`expected_completion_v32_schema`) and must equal it. `vision-job-complete-v3.2.example.json` (installed pack) and `vision-job-complete-v3.2-unpacked-environment.example.json` are the 3.1 golden example with only the five members added; their pack ids and binding hash are synthetic, grammar-valid placeholders like every other hash in these examples and name no real Model Pack, Runtime Pack or binding. `test-vectors/vision-job-complete-v3.2-digest.json` pins both files and their digests, and `test-vectors/control-plane-v3.2-invalid.json` is the negative corpus that the published schema, the .NET validator (with the exact code) and `verify_repo` all reject.

**Worker emission (Stage 2 S2a.3).** 3.2 is the worker's default and its contract: the vision role's `provenanceContract` in the component binding (`src/vision/config/components/phase1-bindings-v2.json`, `vision-job-complete-v3.2`) fixes the version at startup, before the capability probe (plan P-16). The five members come from the role's resolution and nothing else: `capabilityId`, `modelPackId` (derived from the bound Model Pack manifest, P-3), `componentBindingSha256` (the SHA-256 of the binding bytes resolved, P-11), and `runtimePackSource`/`runtimePackId` — `installed-pack` with the id re-derived from the installed `runtime-pack-manifest.json`, or `unpacked-environment` with a `null` id, which can never be `verified` (P-8). A completion whose provenance names another binding is refused before anything is sent. `MAVI_COMPLETION_SCHEMA_VERSION` is retired: set at all (any case, even empty) it makes the worker refuse to start with `settings_v1_composition_rejected`, as do `MAVI_MODEL_MANIFEST_PATH`, `MAVI_QUALIFICATION_RECORD_PATH` and `MAVI_RUNTIME_PROFILE_PATH`. The only way to emit 3.1 or 3.0 is the Development-only override `MAVI_COMPLETION_SCHEMA_OVERRIDE` ∈ {`3.0`, `3.1`}: it is refused in Production (`completion_override_forbidden_in_production`), forces every completion `unverified`, logs `completion_schema_override_active`, and drops the five members from the older body. The platform's 3.1 acceptance and replay are unchanged.

## Completion 3.3 (detector-native vehicle subclass; Stage 3)

`vision-job-complete-v3.3` is the 3.2 body plus the detector-native vehicle subclass (ADR-016). It is asynchronous-only: the activated platform accepts and advertises `["2.0","3.1","3.2","3.3"]`. The response is `vision-job-finalization-response-v3.3`, the 3.2 response with its version echoed.

- **Body members:** `objectSubclassVocabulary` (`mavi-vehicle-subclass-v1`) and `objectSubclassSource` (`detector-native:<pipelineProfileSha256>`), both required. The source must name this body's own `provenance.pipelineProfileSha256` (`object_subclass_source_mismatch`).
- **Track member:** `objectSubclass` ∈ {`car`, `truck`, `bus`, `motorcycle`}, present only when the Track-level vote resolved a value. It is never written as null, and never on a Person Track (`object_subclass_invalid`).
- **Older bodies:** a 2.0–3.2 body carrying any of the three members is refused (`object_subclass_field_in_pre_v33_body`).
- **Digest:** its own domain, `mavi:vision-completion-digest:v3.3`: the 3.2 sequence with the vocabulary and source appended after `inputColourSpace`, and each Track's nullable subclass after its `maxConfidence`.
- **Artefacts:** the schema is generated from the 3.2 schema by `expected_completion_v33_schema` in `tools/verify_repo.py`. `vision-job-complete-v3.3.example.json` (a resolved truck) and `vision-job-complete-v3.3-unpacked-environment.example.json` (an abstained vehicle) are the 3.2 examples plus one Vehicle Track and the subclass members. `test-vectors/vision-job-complete-v3.3-digest.json` pins both, and `test-vectors/control-plane-v3.3-invalid.json` is the negative corpus.

**Worker emission (Stage 3).** 3.3 is the vision role's `provenanceContract` and the worker's default. 3.2 is no longer emitted; the platform still accepts and replays it. The Development-only override (3.0, 3.1) drops the subclass members together with the component identity.

## Stage 3 measurement export (`vehicle-subclass-measurement-export-v1`)

The read-only measurement export of S3.2 (`docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md`, T1) is a development artefact, not a worker or API contract: subclass stays off every API and search surface. `tools/dotnet/Mavi.MeasurementExport --run <guid> --pipeline-profile <file> --out <new-dir>` writes one completed run as `subclass-measurement-export.json` plus `evidence/<sha256>.jpg`.

- The embedded `attestation` is the attestation endpoint's response for that run, built by the same `ProcessingRunAttestationFactory` from the export's own read-only `REPEATABLE READ` snapshot.
- The supplied pipeline profile must hash to the attested `pipelineProfileSha256`; the evidence selector and scorer versions are read from that verified file. A path is never inferred from a hash.
- Every evidence image and the source video are re-hashed against their artifact rows; any gap refuses with a stable `export_*` code, exit 2, and no output directory.
- The JSON is canonical (UTF-8 without BOM, members sorted by ordinal name at every depth, no insignificant whitespace, round-trip numbers, no wall-clock member); the export's identity is the SHA-256 of those bytes, and a repeat over the same persisted state is byte-identical.

The schema constrains only the attestation's producer-identity members; the attestation endpoint owns the rest of its shape. The checked-in example is a real export trimmed to three Tracks and pretty-printed.

## Stage 3 measurement tooling artefacts (S3.2a-2, T2–T6)

Development artefacts of the S3.2 measurement (`docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md`); none is an API, worker or search contract. Each is canonical JSON written once (`tools/stage3/artefacts.py`: UTF-8 without BOM, members sorted at every depth, no insignificant whitespace, no trailing newline, round-trip numbers, no generated timestamp) and identified by the SHA-256 of its bytes. Consumers re-hash every input and refuse with a stable code. T1 exports are identified by their exact bytes and are never re-canonicalised.

| Schema | Producer | Binds |
|---|---|---|
| `vehicle-subclass-requirements-v1` | the owner, committed before sampling | nothing; every operational value may be `null` |
| `vehicle-subclass-sample-v1` | `tools/stage3/sample_tracks.py` (T3) | exports, derivations, one release record, the requirements file at a commit that is an ancestor of `HEAD` |
| `vehicle-subclass-labeling-pack-v1` | `tools/stage3/build_labeling_pack.py` (T4) | the sample, exports, verified profile, the labelling guide at a commit; `parentPackSha256` for an overlap pack |
| `vehicle-subclass-track-labels-v1` | `tools/stage3/freeze_labels.py freeze` (T5) | the pack (and its view and parent), guide, sample, exports |
| `vehicle-subclass-adjudication-v1` | `tools/stage3/freeze_labels.py adjudicate` (T5) | both frozen label files |
| `vehicle-subclass-measurement-v1` | `tools/phase1/evaluate_vehicle_subclass.py --track-labels` (T2) | every input above |
| `vehicle-subclass-requirement-comparison-v1` | `tools/stage3/run_subclass_measurement.py` (T6) | the measurement and the requirements |

- **Prediction blindness.** The sampler decides from an allow-list projection of each Track that never includes `objectSubclass*` or the confidence summaries. Packs show reviewers only item ids and images. The adjudication commands accept no export, result or attestation. Predictions first appear in T6's `measurement-summary.md`, after every label and adjudication is frozen.
- **Pack identity.** `packSha256` is the SHA-256 of `pack-manifest.json`. `files[]` lists every pack file except the manifest and `pack-data.js`. `pack-data.js` is derived from the manifest and checked by regenerating it.
- **Final truth.** The primary decision applies outside the overlap; the adjudication decides overlap Tracks. Human `unknown` is reported and never scored, and MAVI's abstention is never a correct classification.
- **Batches.** The primary aggregate is the pilot plus same-design continuations only. Supplemental batches are always reported separately and never pooled.
- **Derivation manifests.** T3 reads `vehicle-subclass-derivation-v1` manifests as a consumer only. It checks the release, the output digest and the authorisation T8 must have obtained: exactly `{purposes, operations, blockers}`, with purposes `["benchmarking", "development"]`, operations `[]` for passthrough and `["create-derivatives"]` for remux or transcode, and no blockers. T3 makes no legal or R-5 decision. Since S3.2b-1, T3 first validates each manifest against the `vehicle-subclass-derivation-v1` schema (`derivation_invalid:schema`); the checks above remain as defence in depth.
- **Requirement statuses** are decided in this order: `insufficient-support` when evaluable support is below the pre-registered minimum, whether or not a minimum is set; `no-requirement` when the minimum is null; `does-not-meet` when the estimate is undefined (for example precision for a class MAVI never predicted) despite adequate support, while the raw value stays `null`; otherwise an exact rational comparison gives `meets` or `does-not-meet`.
- **Adjudication sessions.** `adjudicate-prepare` writes a `sessionId` derived from the exact frozen primary and overlap label hashes. The page resumes adjudication by that session and labelling by `packSha256`. The exported decisions carry the `sessionId`, and `adjudicate` recomputes it and refuses decisions made for another pair, even of the same pack.
- **Examples.** The examples come from the synthetic fixture pipeline (`tools/stage3/tests/test_s32_pipeline.py`). The requirements example shows the shape only, with every operational value `null`; it is not the owner's pre-registration.

## Stage 3 media, derivation and Development-host execution artefacts (S3.2b-1, T7–T9)

Same canonical form and write-once rule as above; none is an API, worker or search contract. Local paths (release root, media pack, API URL, journal, export root) are runtime-only and never recorded.

| Schema | Producer | Binds |
|---|---|---|
| `vehicle-subclass-media-probe-v1` | `tools/stage3/probe_media.py` (T7) | the probed bytes' SHA-256 and size, the verified ffprobe `{version, sha256}` |
| `vehicle-subclass-source-pool-v1` | `tools/stage3/freeze_source_pool.py` (T7) | the release record (`release_sha256`), each member's release hash and probe record |
| `vehicle-subclass-derivation-v1` | `tools/stage3/derive_mp4.py` (T8); consumed by T3 and T9 | the release record and member, the authorisation obtained, source and output probes, the FFmpeg identity and pinned args, the host import limit |
| `vehicle-subclass-ingestion-map-v1` | the operator, committed before the first T9 import | the source pool; release metadata or the committed Development convention per member |
| `vehicle-subclass-t9-execution-v1` | `tools/stage3/ingest_source_pool.py` (T9) | the committed pool and map, the release, the measured profile, the single producer identity; per member its derivation, MAVI asset, journalled run, attestation and export |

- **Approved binaries.** FFmpeg and ffprobe come only from a MAVI FFmpeg dependency pack (`--media-tools`; manifest, runtime id, SHA-256, version), never from PATH. Artefacts record the manifest's version token and the executable SHA-256 only.
- **Import parity.** `maviImport.containerSupported` is an exact port of `PhaseOneMp4ContainerPolicy.IsSupported`. `contracts/test-vectors/phase1-mp4-container-policy-v1.json` pins it and is consumed by both `Mavi.Application.Tests` and the Python probe tests.
- **Rights.** Release records stay `mavi-attribute-dataset-release-v1` and are checked only by `tools/qualification/attributes/datasets/release.py`. T8 authorises `operations=[]` for passthrough and `["create-derivatives"]` for remux or transcode and writes nothing on a blocker. No S3.2 tool makes a legal or R-5 decision.
- **Freshness.** T9 refuses a catalogue that holds anything its own journal does not explain, never adopts a duplicate import, and never polls a run it did not queue. The execution record carries no native-media pack identity, because no product surface exposes one.
- **Examples** are synthetic and name no real release, camera or member.

## Stage 3 benchmark harness contracts (S3.2d-1)

Development artefacts of the benchmark harness (`docs/superpowers/plans/2026-10-04-stage3-s3-2d-benchmark-harness.md`, ADR-017); none is an API, worker or search contract. Same canonical form as the S3.2 artefacts (`tools/stage3/artefacts.py`), identified by the SHA-256 of their bytes; refusals print `refused <code>`.

| Schema | Producer | Binds |
|---|---|---|
| `benchmark-dataset-release-v1` | the operator (descriptor); `python -m tools.benchmarks.cli describe --freeze-manifest` fills the manifest once | release-level provenance and ADR-017 §7 status, splits, native taxonomy, frame time, exposure, source manifest |
| `benchmark-class-mapping-v1` | the operator, per release | the release; one row per native class |
| `benchmark-association-v1` | `tools/benchmarks/capabilities/vehicle_tracks/association.py` (S3.2d-1 slice 2) | the run envelope (which binds the policy and each sequence's canonical GT); class-free association body |
| `benchmark-vehicle-subclass-result-v1` | `tools/benchmarks/capabilities/vehicle_subclass/evaluate.py` (S3.2d-1 slice 3; `python -m tools.benchmarks.cli evaluate`) | the run envelope, the association and mapping hashes, the registered requirements |

- **Manifest.** A descriptor may exist with an empty manifest; `prepare` refuses it (`source_manifest_missing`) and first reconciles the whole frozen manifest against the source root, before any discovery: `source_manifest_incomplete` (a member is absent), `source_manifest_unexpected` (an unlisted file), `source_manifest_mismatch` (size or bytes differ). Paths are relative POSIX, sorted by code point; links are refused (`source_root_invalid`). `BLOCKED` releases are refused (`descriptor_blocked`).
- **Mappings.** Native classes are unique, sorted and exactly the descriptor's taxonomy (`mapping_incomplete`); `unsupported` rows carry `unsupportedKind` (`vehicle-unresolved` or `outside-capability`); at most one `exact` native class per MAVI class and no `subset` beside an `exact` one (`mapping_invalid`).
- **Envelope.** `$defs/envelope` is written identically in both schemas that embed it. `benchmarkRunId` is the SHA-256 of the envelope without that member, so the descriptor (and so the manifest), each sequence's derived-video and canonical ground-truth hashes, the derivation manifest, the MAVI producer, exports and trajectories, the mapping, association policy, registered requirements, tooling and exposure are all bound. `toolingSha256` hashes the behaviour-bearing files the benchmark process loaded (every module under `tools/`, tests excluded, plus the four benchmark schemas), listed in `toolingFiles` and taken from the blobs at `toolingCommit`; any enumerated file that differs from that commit is refused (`tooling_dirty`). Version labels are recorded, never relied on for uniqueness.
- **Association.** Inputs are class-free projections only: canonical GT reduced to track ids, labelled instants, boxes and ignore flags; MAVI Vehicle Tracks (Person Tracks removed first) reduced to trajectory points and observation boxes, with every observation's `videoOffsetMs` checked against `sourceFrameNumber` at the derived video's declared rate. Trajectories are read by hash and decoded strictly (`trajectory_invalid`). Everything that changes the result is bound by the envelope and checked first: the policy (one object, `vehicle-tracks-association-v1`), the labelled timing (taken from the descriptor that hashes to `descriptorSha256`, never a caller-chosen rate), each canonical GT, and the MAVI evidence (each run's derived video, the exports, trajectories and producer; mismatches are `video_asset_mismatch`, `mavi_export_mismatch`, `trajectory_set_mismatch`, `processing_run_duplicate`, `producer_mismatch`). `associationBodySha256` is unchanged by any class, subclass or confidence mutation (test-enforced).
- **Evaluation.** The result binds the same envelope as its association (`associationSha256`), and the evaluator refuses a descriptor, mapping, requirements file, canonical GT or export set that is not the one the envelope names. Scope A partitions non-ignored GT into expected-vehicle (exact, subset, vehicle-unresolved) and outside-capability negatives; the coverage-limited GT rate is reported, with `coverageLimited` above 1/10. Scope B scores assigned pairs only with MAVI's stored Track outcome (`evaluate_vehicle_subclass._track_outcome`): recall and support over assigned exact pairs; precision over judgeable predictions, `not-available` when any prediction of the class landed on a vehicle-unresolved track; subset classes in their own block; `requirementStatus` per criterion (`not-in-dataset`, then the T6 ordering of `run_subclass_measurement.status`). `prepare` writes `derivation-manifest.json` (code-validated, not a registered contract) whose SHA-256 is the envelope's `derivationManifestSha256`.
- **Exact numbers.** Ratios are `{numerator, denominator, value}` fractions as in `vehicle-subclass-measurement-v1`; policy thresholds, rates and frame times are exact `{numerator, denominator}` rationals in lowest terms.
- **Examples** come from the synthetic dataset adapter (`tools/benchmarks/datasets/synthetic.py`); the descriptor and mapping examples are its output exactly (a test keeps them equal), and the association and result examples are shape illustrations whose identities recompute.

## Stage 4 plate control plane (`mavi-plate-control-v1`)

The worker contract of the `plates` role (Stage 4 PR-3; ADR-013 implementation amendment 2026-10-13, items 11–15). It is capability-specific: it shares no DTO with the attribute plane, only the run-level bounds of `WorkerContractRules`. C# records are in `Mavi.Contracts/Worker/Plates`; the lease capability travels only in `X-Mavi-Lease-Capability`.

| Schema | Example | Pinned by |
|---|---|---|
| `plate-lease-v1` (lease response) | `plate-lease-v1.example.json` | `test-vectors/plate-identity-v1.json` (canonical identity and fingerprint, derived from `tests/fixtures/plates/fixture-pipeline-v1.json`) |
| `plate-predictions-v1` (the sealed `PlatePredictions` artefact) | `plate-predictions-v1.example.json` — the worker's canonical bytes, exactly as sealed | the completion example's `predictionArtifact` size and SHA-256 |
| `plate-complete-v1` (completion request) | `plate-complete-v1.example.json` | `test-vectors/plate-completion-v1-digest.json` (digest domain `mavi:plate-completion-digest:v1`) |

- **Identity.** `mavi-plate-identity-v1` names the pipeline, the artefact version, `mavi-plate-normalisation-v1` with the SHA-256 of `test-vectors/plate-normalisation-v1.json`, the summary policy, the ordered `ocr` and `plate-detector` Model Packs and the parameters SHA-256.
- **Readings carry raw text only.** The platform derives normalised text, its outcome and the advisory format class with the shared normalisation (vectors `plate-normalisation-v1.json`, consumed by .NET and Python). Raw text is 1–32 UTF-16 code units, at most two lines joined by one LF, with no other C0 control character or DEL; NFKC then yields at most 128 characters. `mavi-plate-normalisation-v1` is frozen (SHA-256 `6e505158a735a1c4c5d96ad33d08e4ddb0b98d456f0dd532a6af25de120bf935`).
- **Canonical form is the worker's obligation.** The worker writes `PlatePredictions` as canonical JSON (as for `AttributePredictions`, ADR-013 item 6). The platform validates the content with a streaming reader against the schema, the typed rules and the completion, and seals exactly the bytes it received under their size and SHA-256; it does not re-serialise them or verify byte-canonical form.
- **Reading order.** A plate's readings are ranked by confidence, descending; equal confidences are ordered by raw text in ascending UTF-16 code-unit order (.NET `string.CompareOrdinal`; the worker compares UTF-16BE bytes, because Python's `str` order is code-point order and differs outside the Basic Multilingual Plane). The order is strict: two readings equal in confidence and raw text have no order, the platform refuses such a sequence, and the worker therefore abstains that crop (`ocr_output_invalid`, its proposals kept without a plate) rather than de-duplicating output — one bad crop never fails the run. **Recorded exception (owner decision, 2026-10-13):** an `ocr_output_invalid` abstention (a malformed, duplicate or non-strict reading sequence) keeps the crop's detector proposals, their scores and the reason, but not its readings, because the v1 abstained-crop shape has no slot for them; this is an exception to "everything inside the bounds is retained", and retaining rejected readings needs a new `PlatePredictions` version (ADR-013 item 15). Both sides test `test-vectors/plate-reading-order-v1.json`, which includes a supplementary-plane tie and refused duplicate cases.
- **Bounded v1 profile.** At most 2 detector proposals and 1 accepted plate per evidence crop, and at most 3 candidate readings for it. Output beyond a configured bound fails the attempt (`plate_output_invalid`) and is never truncated; everything inside the bounds is kept in the artefact. `test-vectors/plate-artifact-bound-v1.json` pins the worst-case artefact and completion sizes per profile shape at 10,000 Tracks × 4 crops; the largest v1 shape fits 64 MiB.
- **Validator-level rules** the schemas cannot express — lease order and exactly-once crop coverage, the kept-reading prefix (`read` keeps the readings at or above the OCR floor as ranks `0..m-1`; `unreadable` keeps none), the box inside its crop, Track texts equal to the summary policy's derivation, and equality between the completion and the sealed artefact — are enforced by the platform validator. `tools/verify_repo.py` holds the examples to each other and to the vectors.

## PoC Stage 5 embedding control plane (`mavi-embedding-control-v1`)

The worker contract of the `embeddings` role (PoC S4; ADR-021). It is capability-specific, like the plate plane. The C# records are in `Mavi.Contracts/Worker/Embeddings`. The lease capability travels only in `X-Mavi-Lease-Capability`; worker and attempt travel in `X-Mavi-Worker-Id` and `X-Mavi-Attempt` on evidence reads.

| Schema | Example | Pinned by |
|---|---|---|
| `embedding-lease-v1` (analysis lease response) | `embedding-lease-v1.example.json` | `test-vectors/embedding-identity-v1.json`: canonical identity and fingerprint from the model manifest and pipeline profile bytes |
| `embedding-complete-v1` (analysis completion request) | `embedding-complete-v1.example.json` | completion digest = SHA-256 of the exact request body |
| `embedding-text-query-lease-v1` (appearance text lease response) | `embedding-text-query-lease-v1.example.json` | — |
| `embedding-text-query-complete-v1` (appearance text completion) | `embedding-text-query-complete-v1.example.json` | — |

**Routes**

| Route | Request | Response |
|---|---|---|
| `POST /api/embeddings/analyses/lease` | `{schemaVersion, workerId, identityFingerprint}` | 204 if nothing is queued; 200 with `embedding-lease-v1` and the capability header |
| `POST …/{analysisId}/heartbeat` | `{schemaVersion, analysisId, workerId, attemptCount}` | `{schemaVersion, leaseExpiresAtUtc}` |
| `POST …/{analysisId}/fail` | `{schemaVersion, analysisId, workerId, attemptCount, failureCode, failureMessage?}` | `{schemaVersion, outcome: "requeued" \| "failed"}` |
| `GET …/{analysisId}/evidence/{observationId}` | — | The accepted JPEG crop, the shared lease-scoped handler (ADR-013 §10) |
| `POST …/{analysisId}/complete` | `embedding-complete-v1` | `{schemaVersion, analysisId, processingRunId, status: "completed" \| "superseded", completedAtUtc, tracksEmbedded, tracksUnavailable}` |
| `POST /api/embeddings/text-queries/lease` | `{schemaVersion, workerId, identityFingerprint}` | 204, or 200 with `embedding-text-query-lease-v1` and the capability header |
| `POST /api/embeddings/text-queries/{queryId}/complete` | `embedding-text-query-complete-v1` | `{schemaVersion, status: "completed"}` |
| `POST /api/embeddings/text-queries/{queryId}/fail` | `{schemaVersion, queryId, workerId, attemptCount, failureCode, failureMessage?}` | `{schemaVersion, outcome}` |

**Rules**

- **Failure codes** (code: retryable):
  - Analysis: `embedding_runtime_failed`: true; `embedding_evidence_transport_failed`: true; `embedding_model_unavailable`: true; `embedding_cancelled`: true; `embedding_output_invalid`: false.
  - Text: `embedding_text_runtime_failed`: true; `embedding_text_invalid`: false.
- **Lease refusals:**
  - 409 with `embedding_lease_invalid`, `embedding_not_running`, `embedding_attempt_stale` or `embedding_deadline_exceeded`;
  - 404 with `embedding_analysis_not_found` or `embedding_text_query_not_found`.
- **Evidence integrity:** 422 with `embedding_evidence_missing` or `embedding_evidence_integrity_failed` makes the crop unavailable, not the run.
- **Vectors:** float32 little-endian, standard base64, finite, L2 norm 1 ± 1e-3, exactly `identity.model.dimension` components.
- **Completion:**
  - Every leased Track appears exactly once, in lease order.
  - An `embedded` Track names only leased observations of that Track; each is a crop whose shorter side is at least the profile's `minimumCropSide`.
  - An `unavailable` Track gives `no_evidence` (nothing leased), `evidence_too_small` (no crop met the floor) or `evidence_unavailable` (every adequate crop failed integrity or transport).

## PoC Stage 5A face control plane (`mavi-face-control-v1`)

The worker contract of the `faces` role (PoC S6; ADR-022), built like the embedding plane. The C# records are in `Mavi.Contracts/Worker/Faces`. The lease capability travels only in `X-Mavi-Lease-Capability`. Worker and attempt travel in `X-Mavi-Worker-Id` and `X-Mavi-Attempt` on evidence and query-image reads.

| Schema | Example | Pinned by |
|---|---|---|
| `face-lease-v1` (analysis lease response, Person Tracks only) | `face-lease-v1.example.json` | `test-vectors/face-identity-v1.json`: canonical identity (`mavi-face-identity-v1`) and fingerprint from the manifest and profile bytes. The examples carry the first vector's fingerprint. |
| `face-complete-v1` (analysis completion request) | `face-complete-v1.example.json` | Completion digest = SHA-256 of the exact request body |
| `face-query-lease-v1` (transient query-image lease response) | `face-query-lease-v1.example.json` | — |
| `face-query-complete-v1` (query-image completion) | `face-query-complete-v1.example.json` | — |

**Routes**

| Route | Request | Response |
|---|---|---|
| `POST /api/faces/analyses/lease` | `{schemaVersion, workerId, identityFingerprint}` | 204 if nothing is queued; 200 with `face-lease-v1` and the capability header |
| `POST …/{analysisId}/heartbeat` | `{schemaVersion, analysisId, workerId, attemptCount}` | `{schemaVersion, leaseExpiresAtUtc}` |
| `POST …/{analysisId}/fail` | `{schemaVersion, analysisId, workerId, attemptCount, failureCode, failureMessage?}` | `{schemaVersion, outcome: "requeued" \| "failed"}` |
| `GET …/{analysisId}/evidence/{observationId}` | — | The accepted JPEG crop, through the shared lease-scoped handler |
| `POST …/{analysisId}/complete` | `face-complete-v1` | `{schemaVersion, analysisId, processingRunId, status: "completed" \| "superseded", completedAtUtc, tracksObserved, tracksUnknown}` |
| `POST /api/faces/queries/lease` | `{schemaVersion, workerId, identityFingerprint}` | 204, or 200 with `face-query-lease-v1` and the capability header |
| `GET /api/faces/queries/{queryId}/image` | — | The query image bytes (`image.mimeType`, exactly `image.sizeBytes`) |
| `POST /api/faces/queries/{queryId}/complete` | `face-query-complete-v1` | `{schemaVersion, status: "completed"}` |
| `POST /api/faces/queries/{queryId}/fail` | `{schemaVersion, queryId, workerId, attemptCount, failureCode, failureMessage?}` | `{schemaVersion, outcome}` |

**Rules**

- **Failure codes** (code: retryable):
  - Analysis: `face_runtime_failed`: true; `face_evidence_transport_failed`: true; `face_model_unavailable`: true; `face_cancelled`: true; `face_output_invalid`: false.
  - Query: `face_query_runtime_failed`: true; `face_query_image_invalid`: false.
- **Lease refusals:**
  - 409 with `face_lease_invalid`, `face_not_running`, `face_attempt_stale` or `face_deadline_exceeded`;
  - 404 with `face_analysis_not_found` or `face_query_not_found`.
- **Integrity refusals:**
  - 422 with `face_evidence_missing` or `face_evidence_integrity_failed` makes the crop unavailable, not the run.
  - 422 with `face_query_image_missing` fails the query as `face_query_image_invalid`.
- **Completion:**
  - 422 `face_completion_invalid` is the only refusal the worker treats as its own bad output.
- **Faces:**
  - Every reported face has a detection score at least the profile's `detector.scoreThreshold`. A crop reports at most 8 faces, highest score first; crops are in lease order. A query reports at most 16.
  - Boxes and landmarks are in source pixels, at 3 decimals. A face is `usable` exactly when the shorter side of its *reported* box is at least `minimumFaceSide`.
  - Only usable faces carry `embedding`: float32 little-endian, standard base64, L2 norm 1 ± 1e-3, `identity.model.dimension` components.
  - A usable query face also carries `thumbnail`, its aligned 112×112 JPEG. It is the only face image the role produces.
- **Track outcomes:**
  - Every leased Track appears once, in lease order.
  - `observed` ⇔ at least one usable face.
  - Otherwise the Track is `unknown` with one of these reasons. Unknown is never "no match".
    - `no_evidence`: nothing was leased.
    - `evidence_unavailable`: no crop could be read and decoded.
    - `no_face_detected`.
    - `face_too_small`: faces were found, but none was usable. They are reported without vectors.
