# MAVI cross-language contracts

The worker control plane uses only schema version **2.0**. UUIDs identify durable jobs, runs, videos, and cameras; `workerId` is a case-sensitive opaque stable string. The retired v1 `mediaUri` job and UUID worker-health shapes are not supported.

Each `*-v2.schema.json` file has one matching canonical example. Lease responses expose a logical `sourceStorageKey`, never a physical path, and expose the raw lease capability only at issuance. Heartbeat and failure requests present that capability; responses never echo it. PostgreSQL persists only its SHA-256 hash.

`vision-result` v1 is a legacy observation-oriented result-side scaffold retained only until Task 13 freezes the production completion contract. It is not the canonical production result contract and must not be extended for new worker behavior. Task 13 introduces strict worker-control-plane v2 completion contracts with matching C#, JSON Schema, checked-in example and Pydantic models, then removes or explicitly retires this scaffold.
