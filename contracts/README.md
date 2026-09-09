# MAVI Cross-Language Contracts

These JSON schemas define the initial wire boundary between the operational platform and independently deployable vision workers.

## Rules

- Contracts use explicit `schemaVersion` fields.
- UUIDs identify jobs, workers and authoritative video assets.
- Cross-system timestamps are UTC ISO-8601 values.
- Worker media input uses a logical `sourceStorageKey`; physical filesystem paths and public Internet URLs never cross the contract.
- A vision result is analytical output. It does not by itself create an authoritative identity, investigation, relationship or mission decision.
- Contract-breaking changes require a new schema version and an ADR when they affect architectural ownership.
