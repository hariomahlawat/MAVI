# Task 9 — Invariant Audit and Final Remediation

**Date:** 10 Sep 2026  
**Scope:** PR #14, `feature/task-9-deterministic-track-pipeline`  
**Purpose:** Stop reactive one-comment-at-a-time patching. Define the complete safety/correctness model for Task 9, derive regression scenarios from that model, and make one bounded final remediation pass before merge.

## 1. Architectural invariants

### A. Lease ownership

1. A worker may perform expensive processing only while it has a valid lease.
2. The next heartbeat is scheduled from the **server-returned `leaseExpiresAtUtc`**, never solely from a locally configured cadence.
3. The configured heartbeat interval is a maximum cadence, not a lease guarantee.
4. Heartbeat scheduling leaves a request-timeout safety margin. For a short lease, the margin is bounded to at most half the remaining lease so the next heartbeat is still scheduled in the future.
5. Heartbeat/API failure makes lease ownership unknown/lost, sets cooperative cancellation immediately, waits for the Task-9 processor to stop, and propagates through the existing Task-8 `WorkerApiError` backoff path.
6. After lease loss, the worker must not submit a terminal failure/completion for the stale lease.
7. Processing completion before the next scheduled renewal is accepted only because the scheduled renewal point is itself strictly before the returned lease deadline.

### B. Cancellation propagation

1. Every potentially long-running Task-9 phase has a cooperative cancellation checkpoint.
2. Required checkpoints: before source snapshot, **during each source-copy chunk**, before frame decode/processing, before and after detector execution, before and after tracker execution, and before each track finalisation.
3. Lease cancellation during source snapshotting must stop copy I/O promptly rather than finishing a multi-gigabyte/network copy.
4. Task-9 fixture detector/tracker calls are bounded. Task 10 must preserve or strengthen cancellation at model-runtime boundaries.
5. Cancellation maps to `VideoProcessingError("lease_lost")`; it is not reported as source corruption or generic processing failure.

### C. Source/evidence integrity

1. Bytes analysed by PyAV must be exactly the bytes whose SHA-256 and size match the lease.
2. Pathname replacement after source resolution cannot change analysed bytes.
3. In-place mutation of the source after verification cannot change analysed bytes.
4. Snapshot copying is **bounded by the leased size**: copy exactly `expected_size_bytes`, then probe one extra byte. This prevents unbounded copying if the source grows while being read.
5. Source truncation, growth, hash mismatch and read failure all fail closed.
6. The verified worker-owned snapshot is rewound before decode and always closed on success, failure or cancellation.

### D. Staging filesystem safety

1. Staged artifacts are confined to `staging/<job-id>/...`.
2. Job identity is validated before cleanup.
3. Existing path components are opened with no-follow directory-handle semantics on the supported hardened worker platform.
4. Writes are created and atomically published relative to the pinned parent directory handle.
5. Path swaps after validation cannot redirect the write; logical parent identity is revalidated before a descriptor is returned.
6. Cleanup is anchored to the staging directory and removes only the current job tree.
7. A stale worker never performs cleanup after lease loss, because that could delete a newer attempt's staging tree. A new attempt cleans the job staging area at its own start.
8. Unsupported platforms fail closed with `secure_staging_unavailable`; a future Windows-native hardened staging implementation requires a separate design rather than silently weakening confinement.

### E. Media-relative timestamp semantics

1. `offset_ms` is media-relative, never wall-clock time.
2. The first usable timeline point is anchored at 0 ms (or at the already-established fallback position when PTS first appears later).
3. PTS/time-base is authoritative whenever usable.
4. Missing PTS before the first usable PTS uses rational average-frame-rate fallback.
5. When PTS appears after fallback frames, that PTS is anchored to the fallback position already established for that frame.
6. **Missing PTS after a PTS timeline is established continues from the previous emitted media offset using the rational frame-duration fallback**, not from absolute frame number.
7. Emitted offsets must never move backwards. A genuinely regressing PTS timeline fails closed rather than silently rewriting evidence timing.
8. Millisecond quantisation must not create a decreasing timeline; duplicate millisecond offsets caused only by rounding are advanced minimally to preserve the system's strict integer-ms trajectory contract.

## 2. Failure-scenario matrix

| Area | Scenario | Required result |
|---|---|---|
| Lease | normal long processing | repeated renewal; processing completes |
| Lease | server grants shorter lease than configured cadence | next renewal occurs before returned deadline |
| Lease | heartbeat transport/status failure | cancellation set; no terminal stale call; Task-8 backoff path |
| Lease | processor finishes before renewal point | result accepted and Task-9 deferred-submission path used |
| Cancellation | cancelled before snapshot | no source copy/decode |
| Cancellation | cancelled during snapshot | copy stops at chunk boundary; snapshot closed |
| Cancellation | cancelled during frame loop | processing stops; no subsequent finalisation |
| Cancellation | cancelled during finalisation boundary | no later track is finalised |
| Integrity | source missing | controlled integrity failure |
| Integrity | initial size mismatch | fail before snapshot copy |
| Integrity | source truncated during copy | bounded copy detects short read |
| Integrity | source grows during copy | one-byte probe detects growth without copying unbounded tail |
| Integrity | source pathname replaced | owned snapshot still decodes verified bytes |
| Integrity | source inode mutated after snapshot | owned snapshot remains unchanged |
| Staging | `staging/<job>` symlink | reject; target preserved |
| Staging | intermediate symlink | reject before external mutation |
| Staging | parent swapped during write | fail closed; no redirected artifact |
| Staging | mismatched store/job | reject before cleanup |
| Staging | cleanup current job | other job preserved |
| Time | zero/non-zero/negative initial PTS | media-relative offsets start at 0 |
| Time | missing PTS then PTS | one coherent monotonic timeline |
| Time | PTS then missing PTS | continue from prior timeline; never jump backwards |
| Time | all frames missing PTS with valid rate | deterministic rational fallback |
| Time | no usable PTS and no valid rate | fail closed |
| Time | regressing usable PTS | explicit timestamp error |
| Time | rounding collision | minimally increasing integer-ms offsets |

## 3. Root causes identified on current head

The current head already solves the first-order issues (event-loop blocking, pathname replacement, symlink traversal and late PTS origin). The remaining Codex findings are second-order consequences of incomplete invariants:

- Heartbeat renewal exists but is keyed to a static interval rather than the authoritative server deadline.
- Cancellation exists in the processor but is not propagated into source snapshot copying.
- Mixed timestamp anchoring handles missing-PTS-before-PTS but not missing-PTS-after-PTS.

The audit additionally identifies one integrity-hardening gap worth fixing in the same bounded pass: snapshot copying currently reads until EOF, so a source that grows during copying can cause unnecessary/unbounded extra I/O before the eventual size mismatch is detected.

## 4. Final remediation boundary

This pass may modify only the Task-9 worker scheduling, source snapshot/cancellation logic, media timestamp resolver and associated tests/documentation. Existing hardened staging code is reviewed as satisfying the Task-9 POSIX worker invariant and is not to be refactored further without a reproducible failure.

No Task 10 detector/runtime integration, no ByteTrack/RTMDet, no Task 11 completion endpoint, no result-ingestion schema, no Python database access and no .NET persistence changes.

## 5. Merge gate

Task 9 is mergeable only when all of the following are true:

- every scenario above that belongs to Task 9 has deterministic regression coverage or an explicit bounded-platform rationale;
- the focused Python suite is green;
- the full hosted MAVI Quality Gate is green on the exact final head;
- all blocking P1/P2 review threads are resolved with evidence;
- a fresh Codex review of the exact final head reports no new blocking P1/P2 findings.
