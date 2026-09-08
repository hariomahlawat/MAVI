# MAVI Cross-Language Contracts

These JSON schemas define the initial wire boundary between the operational platform and independently deployable vision workers.

## Rules

- Contracts use explicit `schemaVersion` fields.
- UUIDs identify jobs, workers and authoritative video assets.
- Cross-system timestamps are UTC ISO-8601 values.
- `mediaUri` is a MAVI-controlled media reference, not a public Internet URL.
- A vision result is analytical output. It does not by itself create an authoritative identity, investigation, relationship or mission decision.
- Contract-breaking changes require a new schema version and an ADR when they affect architectural ownership.
