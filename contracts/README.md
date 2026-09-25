# Worker Contract Artifacts

The worker control-plane contract is version 2.0. C# public contracts, JSON Schemas, checked-in examples and Python Pydantic models are maintained as one compatibility boundary.

Task 13 makes `vision-job-complete-v2` the canonical successful analytical-result contract. It is success-only: processing failures continue to use `vision-job-fail-v2`.

The former observation-oriented `vision-result` v1 scaffold has been retired. New worker/result behavior must not recreate or extend it.

All worker request schemas reject unknown members. Cross-system timestamps use canonical RFC3339 UTC `Z` syntax. Media is referenced by logical storage key and integrity facts; raw video frames and local filesystem paths never cross the normal worker API.

## Completion 3.0 (Track Evidence Set)

`vision-job-complete-v3` carries, per Track, up to four `observations` (roles `representative`, `near-view`, `early-diverse`, `late-diverse`; ranks contiguous in that order; one source frame per role) instead of the 2.0 `representative` member, and a required `evidenceAccounting` block with candidates/admitted/omitted counts and bytes per role. The platform accepts 2.0 and 3.0 and advertises both at `GET /api/vision/contract`; every other worker contract stays 2.0. Each version has its own server-side digest domain, and a 2.0 body keeps its exact 2.0 digest.

JSON Schema expresses the shape and per-field bounds (including the 64 KiB Representative and 160 KiB supplemental crop caps). The cross-field rules it cannot express — contiguous ranks, unique roles and frames, exact staging crop keys, accounting that matches the descriptors sent, the 1 GiB crop quota — are enforced by the platform validator. `control-plane-v3-invalid.json` marks each vector `rejectedBy: "schema"` or `"validator"` accordingly, and `tools/verify_repo.py` holds both sides to it.

`vision-job-complete-v3.example.json` is a golden fixture: `test-vectors/vision-job-complete-v3-digest.json` pins its file SHA-256 and the digest the platform computes for it. Changing either the example or the v3 digest sequence requires re-pinning deliberately. `test-vectors/vision-job-complete-v3-conformance.json` holds integer-binding cases addressed by JSON pointer, shared by the .NET and Python tests.

**Worker emission (S1.2c).** The worker emits completion **3.0 only**, and only after `GET /api/vision/contract` has listed `"3.0"`. Until then it leases nothing (logged once per incompatible period); it never falls back to 2.0. Its Pydantic model `VisionJobCompleteV3` also enforces the validator-level rules, so it rejects every vector in `control-plane-v3-invalid.json` (schema- and validator-level). The worker's body for the golden inputs is byte-identical to `vision-job-complete-v3.example.json`, so it reproduces the pinned digest (`src/vision/tests/test_worker_completion_v3.py`). The 2.0 schema, example and models stay for the platform's continued 2.0 acceptance.

**Representative ≠ qualified (ADR-013 §4, amended 2026-09-24).** Under selector `evidence-selector-v1-two-tier` (named in the pipeline profile and bound by `pipelineProfileSha256` in provenance), a `representative` observation may be a *fallback* that did not pass every selector quality floor. `near-view`, `early-diverse` and `late-diverse` observations are always qualified. Completion 3.0 has no per-observation qualified flag; `qualityScore` is carried. No consumer may infer "qualified" from `role == "representative"`. A feature that needs qualification-sensitive Representative input must first introduce or derive an explicit qualification contract.


## Completion 3.1 (asynchronous finalization hand-off)

`vision-job-complete-v3.1` is the completion **exchange** version of the S1.4 B3 asynchronous-finalization architecture (`docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md` §5). Its request body is the 3.0 body with `schemaVersion: "3.1"` and nothing else: the schema is the 3.0 schema with only its title and version const changed (checked by `tools/verify_repo.py`), and the example is the 3.0 golden example with its version swapped. The platform validator normalizes both to `CompletionSchema.V3`, so a 3.1 body has the same `mavi:vision-completion-digest:v3` digest as the identical 3.0 body; the raw version string is never hashed and there is no digest v4.

What differs is the acknowledgement. `vision-job-finalization-response-v3.1` says the platform durably owns the hand-off (`state: "finalizing"`, with `acceptedAtUtc`) or that an exact replay found the job already published (`state: "completed"`, adding `completedAtUtc`). `tracksSubmitted` is the validated Track count of the accepted body in both states; it is not a published count, which is why it is not called `tracksAccepted`. A `finalizing` acknowledgement is not a completion: the worker must keep the current attempt's staging and must not run its successful-completion cleanup.

**Staging (F1).** Slice F1 defines 3.1 and its persistence; the endpoint still accepts 2.0 and 3.0 only and `GET /api/vision/contract` still advertises `["2.0","3.0"]`. When F2 enables 3.1, the advertised set becomes `["2.0","3.1"]`: 3.0 is retired, 2.0 is unchanged, and a 3.1 worker never falls back to 3.0.
