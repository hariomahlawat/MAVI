# Worker Contract Artifacts

The worker control-plane contract is version 2.0. C# public contracts, JSON Schemas, checked-in examples and Python Pydantic models are maintained as one compatibility boundary.

Task 13 makes `vision-job-complete-v2` the canonical successful analytical-result contract. It is success-only: processing failures continue to use `vision-job-fail-v2`.

The former observation-oriented `vision-result` v1 scaffold has been retired. New worker/result behavior must not recreate or extend it.

All worker request schemas reject unknown members. Cross-system timestamps use canonical RFC3339 UTC `Z` syntax. Media is referenced by logical storage key and integrity facts; raw video frames and local filesystem paths never cross the normal worker API.

## Completion 3.0 (Track Evidence Set)

`vision-job-complete-v3` carries, per Track, up to four `observations` (roles `representative`, `near-view`, `early-diverse`, `late-diverse`; ranks contiguous in that order; one source frame per role) instead of the 2.0 `representative` member, and a required `evidenceAccounting` block with candidates/admitted/omitted counts and bytes per role. The platform accepts 2.0 and 3.0 and advertises both at `GET /api/vision/contract`; every other worker contract stays 2.0. Each version has its own server-side digest domain, and a 2.0 body keeps its exact 2.0 digest.

JSON Schema expresses the shape and per-field bounds (including the 64 KiB Representative and 160 KiB supplemental crop caps). The cross-field rules it cannot express — contiguous ranks, unique roles and frames, exact staging crop keys, accounting that matches the descriptors sent, the 1 GiB crop quota — are enforced by the platform validator. `control-plane-v3-invalid.json` marks each vector `rejectedBy: "schema"` or `"validator"` accordingly, and `tools/verify_repo.py` holds both sides to it.

`vision-job-complete-v3.example.json` is a golden fixture: `test-vectors/vision-job-complete-v3-digest.json` pins its file SHA-256 and the digest the platform computes for it. Changing either the example or the v3 digest sequence requires re-pinning deliberately. `test-vectors/vision-job-complete-v3-conformance.json` holds integer-binding cases addressed by JSON pointer, shared by the .NET and Python tests.

**Worker emission (S1.2c).** The worker emits completion **3.0 only**, and only after `GET /api/vision/contract` has listed `"3.0"`. Until then it stays not ready and leases nothing; it never falls back to 2.0. Its Pydantic model `VisionJobCompleteV3` also enforces the validator-level rules, so it rejects every vector in `control-plane-v3-invalid.json` (schema- and validator-level). The worker's body for the golden inputs is byte-identical to `vision-job-complete-v3.example.json`, so it reproduces the pinned digest (`src/vision/tests/test_worker_completion_v3.py`). The 2.0 schema, example and models stay for the platform's continued 2.0 acceptance.

