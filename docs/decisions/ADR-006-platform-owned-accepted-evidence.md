# ADR-006: Platform-Owned Sealing for Accepted Vision Evidence

**Status:** Accepted  
**Date:** 2026-09-13  
**Amended:** 2026-09-23 — §6 platform-owned staging reclamation (S1.2a)

## Context

Task 9 and Task 10 intentionally allow the Python worker to publish attempt-scoped analytical artifacts beneath the shared managed-media staging root.

Task 13 initially proposed retaining accepted evidence in that same location after verifying size and SHA-256. Review identified a security and forensic-integrity defect in that design: the worker-writable pathname could be replaced or modified after verification while PostgreSQL continued to advertise the previously verified hash.

Hash verification of a mutable pathname is therefore insufficient as the authoritative evidence binding.

## Decision

MAVI separates **worker staging** from **accepted authoritative evidence**.

### 1. Worker staging remains non-authoritative

The worker continues to publish attempt-scoped outputs beneath:

```text
staging/{jobId}/attempt-{attemptCount:0000}/...
```

These paths are never persisted as authoritative evidence references after successful completion.

### 2. The platform owns a separate evidence root

ASP.NET Core is configured with a distinct `MediaStorage:EvidenceRootPath`.

Production permissions must ensure the Python worker has no write access to this root. The evidence root must be filesystem-disjoint from the worker/shared media root.

### 3. Acceptance seals and verifies in one stream

For every accepted thumbnail or trajectory, the platform:

1. opens the worker staging object through the hardened managed-media boundary;
2. streams bytes into a temporary file beneath the platform-owned evidence root;
3. computes byte length and SHA-256 while copying;
4. rejects missing or mismatched input;
5. atomically publishes the verified file using create-new semantics;
6. never overwrites an existing accepted key.

A pre-existing accepted key is idempotently reusable only if its exact bytes match the expected size and SHA-256.

### 4. Authoritative rows reference only sealed keys

Committed `Artifact` rows for thumbnails and trajectories reference deterministic `evidence/...` logical keys, never `staging/...` keys.

Later mutation of worker staging therefore cannot alter accepted evidence.

### 5. Prefer orphaned sealed evidence over dangling authoritative references

Filesystem publication and PostgreSQL cannot participate in one atomic transaction.

MAVI intentionally chooses the safe failure direction:

- sealing happens before the DB graph references the object;
- if the subsequent DB transaction rolls back, an unreferenced sealed object may remain;
- PostgreSQL must never commit an authoritative evidence row that points at mutable staging or a missing accepted object.

Garbage collection of unreferenced sealed evidence is deferred to a later lifecycle task.

### 6. Platform-owned reclamation of worker staging (amendment, S1.2a)

**Status of this section:** Accepted 2026-09-23 — ratified by the owner with the S1.2a implementation (plan `docs/superpowers/plans/2026-09-23-stage2-s1-2-evidence-set-implementation.md` §6.5, §17 C3).

The Track Evidence Set makes one attempt's staging large (up to ≈ 5.2 GiB transient at 10,000 Tracks) and the worker's own cleanup is not crash-safe: a worker that dies after a successful completion, or never leases again, leaves its staging forever. Therefore:

- the **platform reclaims** `{MediaStorage:RootPath}/staging/{jobId}/attempt-NNNN` directories, using the `vision_jobs` row as the **sole authority** on which attempts can no longer be accepted;
- destructive authority is limited to states the `VisionJob` aggregate can reach: `Completed`/`Failed` after a grace period, `Leased` only for attempts below `AttemptCount` (fenced by the lease), a job with no row only after a long inactivity grace; `Cancelled` is treated as terminal because the enum defines it so; a `Queued` job that has been leased is an invariant violation and nothing is deleted;
- the worker's cleanup after completion and at the next lease remains, as a **fast path only**;
- deletion is handle-relative and never follows a link or reparse point, never leaves `staging/`, and never touches the accepted-evidence root (orphaned sealed evidence remains deferred per §5);
- the normal reclamation **target** is `Grace + Interval`; under a backlog of `B` eligible directories and a per-cycle cap `M` the bound is `Grace + ⌈(B+1)/M⌉ × Interval`. Neither is a universal guarantee: a directory that cannot be deleted stays, is retried and escalates.

**Trade-off accepted:** the platform gains a background lifecycle that deletes files it did not write, and with it a destructive failure mode, in exchange for crash-safe bounded staging. The alternatives — deleting staging inside or after the completion transaction, or leaving reclamation to the worker — are rejected in the plan §6.5 (not crash-safe; entangles large filesystem work with the request path).

## Consequences

### Positive

- accepted evidence remains byte-stable after worker completion;
- PostgreSQL hashes remain meaningful forensic attestations;
- worker compromise or stale-attempt activity cannot rewrite committed evidence through staging;
- completion retries can reuse an identical already-sealed object safely.

### Costs

- accepted evidence requires a second storage root and one streaming copy;
- deployment must enforce separate filesystem permissions;
- failed DB completions can leave unreferenced sealed objects that require later garbage collection;
- future evidence-content APIs must resolve `evidence/` keys against the platform-owned evidence root.

## Rejected alternatives

### Keep staging path after hash verification

Rejected because verification is only a point-in-time observation of a mutable worker-controlled pathname.

### Move staging in place after verification

Rejected because worker and platform ownership are not cleanly separated and cross-platform rename/permission semantics are weaker than a dedicated platform-owned root.

### Commit PostgreSQL first, then copy evidence

Rejected because a copy failure would leave authoritative rows referencing unavailable evidence.

## Related documents

- `AGENTS.md`
- `docs/decisions/ADR-002-modular-monolith-and-ai-workers.md`
- `docs/decisions/ADR-003-offline-production.md`
- `docs/decisions/ADR-005-qualified-vision-runtime.md`
- `docs/superpowers/plans/2026-09-13-task-13-vision-result-persistence.md`
