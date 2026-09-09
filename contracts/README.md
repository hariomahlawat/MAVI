# MAVI cross-language contracts

The worker control plane uses only schema version **2.0**. UUIDs identify durable jobs, runs, videos, and cameras; `workerId` is a case-sensitive opaque stable string. The retired v1 `mediaUri` job and UUID worker-health shapes are not supported.

Each `*-v2.schema.json` file has one matching canonical example. Lease responses expose a logical `sourceStorageKey`, never a physical path, and expose the raw lease capability only at issuance. Heartbeat and failure requests present that capability; responses never echo it. PostgreSQL persists only its SHA-256 hash.

`vision-result` is a separate result-side scaffold and will be finalized when successful result acceptance is designed. It is not part of Task 7A worker execution.
