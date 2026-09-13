# Worker Contract Artifacts

The worker control-plane contract is version 2.0. C# public contracts, JSON Schemas, checked-in examples and Python Pydantic models are maintained as one compatibility boundary.

Task 13 makes `vision-job-complete-v2` the canonical successful analytical-result contract. It is success-only: processing failures continue to use `vision-job-fail-v2`.

The former observation-oriented `vision-result` v1 scaffold has been retired. New worker/result behavior must not recreate or extend it.

All worker request schemas reject unknown members. Cross-system timestamps use canonical RFC3339 UTC `Z` syntax. Media is referenced by logical storage key and integrity facts; raw video frames and local filesystem paths never cross the normal worker API.
