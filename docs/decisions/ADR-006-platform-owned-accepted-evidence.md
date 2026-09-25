# ADR-006: Platform-Owned Sealing for Accepted Vision Evidence

**Status:** Accepted  
**Date:** 2026-09-13  
**Amended:** 2026-09-23 — §6 platform-owned staging reclamation (S1.2a)  
**Amended:** 2026-09-25 — §7 asynchronous finalization ownership (S1.4 B3, slice F1)

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

### 7. Asynchronous finalization ownership (amendment, S1.4 B3)

**Status of this section:** Accepted 2026-09-25 with the frozen architecture in `docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md`; slice F1 lands the contracts, domain state and schema, F2 the submission transaction, F3 the finalizer.

S1.4 B3 measured sealing of a 10,000-Track Evidence Set at p50 104 s inside the completion request, against a 15 s lease-bound budget. Sealing (§3) therefore moves out of the worker's request into a platform finalizer, and the completion exchange becomes a durable hand-off:

- **Hand-off authority is PostgreSQL.** Completion 3.1 is accepted when one transaction moves the `VisionJob` from `Leased` to `Finalizing` and stores the exact request bytes (`vision_finalization_payloads`, keyed by job and attempt, with length, SHA-256 and the completion digest). No filesystem manifest, queue or second store participates. A Finalizing row and its payload exist together or not at all; the finalizer re-reads the bytes, re-validates them and requires the recomputed digest to equal the job's before sealing anything.
- **Sealing stays platform-owned and precedes publication.** §3–§5 are unchanged: the finalizer streams staging into the evidence root, verifies size and SHA-256, publishes with create-new semantics, and only then commits the authoritative graph. The visibility barrier is the publication transaction, so rows publish only after sealing and commit.
- **No compensation deletion of accepted evidence in the asynchronous path.** The synchronous request path deleted its own freshly sealed objects on rollback. The finalizer does not: a sealed object is an idempotently reusable accepted object for the next claimant (§3), and deleting it could race a concurrent or later publication. Objects that no publication ever references are **orphans** under §5 and remain a separate retention concern; nothing in F1–F3 collects them.
- **The worker lease ends at the hand-off.** `LeaseOwner`, `LeaseTokenHash` and `AttemptCount` are retained on the Finalizing row solely to authenticate an exact replay of the completion after an ambiguous HTTP outcome; heartbeat, worker failure and re-lease are refused by status. The finalizer's own ownership is a separate PostgreSQL-fenced claim (token hash, expiry, bounded attempts) that rotates on every claim.
- **Staging retention.** Worker staging of the current Finalizing attempt is the finalizer's input and is not reclaimable under §6 until the job is terminal; F3 teaches the janitor the rule. Earlier attempts stay reclaimable.

**Trade-off accepted:** between hand-off and publication a job is neither Completed nor Failed, the operator sees a distinct `finalizing` phase without a fabricated percentage, and a Finalizing row is opaque to a preceding binary (rollback requires draining Finalizing jobs, plan §15.3). In exchange the completion request is bounded by validation and one bytea insert, independent of Evidence Set size, and a platform-process loss after the hand-off is recoverable from PostgreSQL alone.

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
- `docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md`
