# ADR-011 — Scene Configuration Revisions and Scene Analytics Post-Processing Lifecycle

**Status:** Accepted  
**Date:** 2026-09-20  
**Context:** Spatial & Temporal Track Analytics (capability roadmap stage 1), Slice 0  
**Plan:** `docs/superpowers/plans/2026-09-20-spatial-temporal-track-analytics.md`

> ADR-010 is reserved by `docs/superpowers/plans/2026-09-20-audited-review-and-cases-plan.md` for operator identity, authorization and audit, which is written when that deferred increment is activated. This ADR therefore takes the next number; the gap is deliberate.

## Context

MAVI persists, per Track, a sealed trajectory artefact of normalised bounding-box centres sampled once per detection. Nothing in the platform derives scene meaning from it: an operator cannot ask which Tracks entered a zone, crossed a line, dwelt, stopped or loitered.

Adding that meaning requires two new long-lived concepts — operator-editable scene geometry, and derived facts computed from Tracks against that geometry — and both touch parts of the system whose invariants are already load-bearing: the single-transaction processing completion that seals evidence and allocates a monotonic visibility sequence, and the snapshot-stable Track search cursor.

This ADR freezes where that computation lives, how scene geometry is versioned, how a derived-fact computation is owned and fenced, and how partially computed analytics appear in search. It deliberately does not freeze table shapes, index choices or class layout, which belong to later slices.

## Decision 1 — Analytics run as a separate deterministic post-processing stage in .NET

Derived analytics are computed by the .NET application in a background stage that runs **after** a processing run has completed and become visible, never inside the completion transaction, never at query time, and never in the Python vision worker.

Rejected alternatives and why:

- **Inside the `ProcessingRun` completion transaction.** Completion is the platform's most sensitive transaction: it validates the worker payload, seals evidence into the platform-owned root (ADR-006), allocates the visibility sequence under an exclusive advisory lock and commits. Folding analytics in would make sealed detector evidence depend on operator-editable geometry, would extend the exclusive-lock window by the cost of geometry over every trajectory, and would leave no way to recompute after a geometry edit without inventing a completion that no worker performed. A geometry fault would then fail, or delay, a run whose detector evidence was already valid.
- **Lazy evaluation at query time.** Search latency would carry the whole geometry cost on every request, fanned out across runs; nothing would be persisted, so results would be reproducible only while inputs and code were unchanged; and the cost would grow with runs × queries.
- **In the Python vision worker.** The worker is qualified as a unit — detector, tracker, runtime pack and lock (ADR-005, ADR-007). Putting deterministic geometry there would add a geometry dependency to a qualified runtime and re-open CPU and CUDA runtime evidence for a computation with no model in it. The worker also sees one job at a time, while re-analysis must sweep many completed runs, and scene configuration lives in the platform, not in the worker.

Consequences accepted: the platform gains its first `BackgroundService`; analytics become visible slightly after the run itself, which makes readiness an explicit part of the search contract (Decision 5); and the operator gains a state to understand ("analysed" versus "not yet analysed").

## Decision 2 — Scene configuration is revisioned as a whole, per camera

- Exactly **one `SceneConfiguration` per `Camera`**, bound to that camera immutably.
- Geometry is versioned as **immutable whole-configuration revisions**, not per object. A search predicate and an analysis unit both need one coherent snapshot of all zones and lines; per-object versions would force every consumer to reassemble one.
- **Zone and trip-line identities are stable across revisions**, so "Zone 3" remains the same operator concept as its shape changes, and facts from different revisions remain comparable by identity.
- **Save-and-activate in one step.** A save creates the next revision and makes it active; there are no server-side drafts in v1 (the editor holds unsaved state locally).
- **Historical revisions are retained** and remain readable and queryable.
- **An empty active revision means analytics are intentionally disabled** for that camera. It is the only way to switch analytics off. No analysis units are created while it is active, and no empty `Completed` analysis is manufactured merely because a revision exists.
- **A geometry edit never silently reinterprets history.** Facts stay bound to the revision that produced them; applying new geometry to old runs is an explicit re-analysis, never an implicit recomputation.

## Decision 3 — One `SceneAnalysis` unit per run, revision and algorithm version

The unit of scheduling, retry, ownership, visibility and re-analysis is one **`SceneAnalysis`** per:

`ProcessingRun` + `SceneConfigurationRevision` + `AlgorithmVersion`

Lifecycle states: `Queued`, `Running`, `Completed`, `Failed`, `Superseded`.

Readiness, derived for a run rather than stored: `NotConfigured` (the camera never had a revision), `Disabled` (the active revision is empty), `Pending`, `Ready`, `Failed`, `Stale` (facts exist only for an older revision or algorithm version).

`AlgorithmVersion` is a domain string; a change to any frozen geometry or temporal rule increments it, which makes existing units `Stale` for readiness without deleting their facts and without automatically queueing recomputation. The Git commit may be recorded for forensics but never participates in identity or staleness.

Persistence shapes, index choices and the exact scheduling loop are deliberately left to the implementing slice.

## Decision 4 — Every running attempt is fenced (architectural invariant)

Analytics execute outside a transaction, so a slow attempt can outlive its claim. Ownership is therefore explicit and revalidated, following the same shape the platform already uses for `VisionJob` leases:

- A **claim** is atomic: it increments `AttemptCount`, generates an opaque `ClaimToken` held only in the executing host's memory, persists **only the token's hash**, sets `LeaseExpiresAtUtc`, marks the unit `Running` and commits **before** the engine starts.
- **Completion and failure must revalidate current ownership** — state `Running`, matching attempt number, matching token hash — inside the final transaction, after locking the row and before any write.
- **Reclaim** issues a new attempt number and a new token; the previous token can never validate again.
- **Lease expiry alone does not invalidate ownership.** A unit whose lease has expired is merely *reclaimable*. Ownership is lost only when the row itself changes hands, which happens in exactly two fenced transitions, both taken under `FOR UPDATE` by the reconciler:
  - **reclaim**, when attempts remain: a new attempt number and token replace the old ones;
  - **terminal exhaustion**, when none remain: the unit moves to `Failed` with `analytics_attempts_exhausted` and its claim-token hash is cleared, so no attempt owns it any longer.

  Both invalidate the previous attempt, which then writes nothing. An attempt that overruns its lease but has not yet been reclaimed or terminated still completes normally, and because the reconciler must take the same row lock, an attempt that finishes first wins the race: correct work is not discarded for a clock margin.
- **Terminal exhaustion waits out a grace period.** The reconciler only reclaims or terminates a `Running` unit after `LeaseExpiresAtUtc` plus a configured grace, so the last permitted attempt is not killed the instant it overruns. Without the grace, an attempt could be marked exhausted while still succeeding, which is the outcome the previous rule exists to avoid.
- A **stale attempt** — one whose ownership no longer holds — fails harmlessly with the stable code `analytics_attempt_stale` and performs none of: deleting facts, inserting facts or outcomes, marking `Completed`, marking `Failed`, superseding another unit, or allocating a visibility sequence. Destructive idempotent rewrites happen only after revalidation, never before.
- **No heartbeat in v1.** The bounded execution window is short; the lease duration must safely exceed it with margin, and configuration validation enforces that relationship. Lease renewal is added only if a later algorithm makes units long-running.
- The claim token and its hash are **internal**. They never appear in any API contract, response, log or status projection.

## Decision 5 — Analytics readiness is explicit in search, never silence

- **Ordinary Track search is unaffected** by analytics readiness. A Track is visible because its run is visible.
- A query using any analytic predicate evaluates **only covered runs** — those whose analysis unit for the resolved revision is `Completed` and visible in the query's snapshot.
- Such a query **must** return an `analyticsCoverage` block naming the resolved revision and algorithm version and counting evaluated, pending, failed, stale and not-configured runs.
- `complete` is true **only** when every unevaluated bucket is zero: pending, failed, stale, not-configured and disabled. A run whose camera is unconfigured or disabled was not evaluated, so it makes the answer incomplete exactly as a pending one does. Never-configured and deliberately disabled are counted **separately**, because an operator is owed the difference between a gap and a switch-off.
- **Incomplete analytics must never be presented as zero matches**, in results or in aggregates.
- A caller may demand completeness and receive `409` rather than a partial answer.

## Decision 6 — Analytic search cursors pin the revision and algorithm version

- **An analytic predicate requires a single-camera scope.** Track search is not camera-scoped in general, but a zone, a line and a revision only have meaning for one camera, and a coverage block names one revision. A query that uses an analytic predicate must therefore resolve to exactly one camera — through `cameraId`, or through a `videoAssetId` or `processingRunId` that determines one — and is otherwise refused as a malformed filter. Multi-camera analytic search would need a per-camera coverage and pinning model and is not in this increment.
- The **first** analytic page resolves the effective `SceneConfigurationRevision` and `AlgorithmVersion` for that camera.
- Both are **pinned into the canonical filter identity, the fingerprint and the cursor**, alongside the existing visibility snapshot.
- **Continuation pages remain bound** to the pinned pair and snapshot. Activating a new revision mid-pagination does **not** invalidate an otherwise valid cursor: the pinned revision's facts are immutable and persisted, so later pages stay consistent with the first.
- **Resolving to no revision is itself pinned.** When the camera has never been configured, or its active revision disables analytics, the first page resolves *no* revision and pins that absence. Continuation pages stay bound to the absence and keep returning the same empty analytic result with the same coverage, so activating a revision mid-pagination cannot make later pages start matching while earlier ones did not. A new search then resolves the newly active revision.
- A **new search** resolves the newly active revision.
- A cursor is invalid only for the existing reasons — decode failure, changed filters, age or clock skew — plus a pinned revision that does not belong to the query's resolved camera.

## Decision 7 — Implementation boundary

- The **.NET Application layer owns the deterministic analytics**: geometry, temporal rules and the algorithm version, as a pure, dependency-free component.
- **Infrastructure** later owns persistence and background execution.
- The **Python vision worker is untouched**: no contract change, no pipeline change, no new runtime dependency.
- **No new external geometry dependency** is introduced; the offline dependency contract is unchanged.
- This stage therefore triggers **no vision requalification**: RTMDet and ByteTrack evidence, the CPU runtime qualification and the Windows CUDA Development evidence (ADR-009) are unaffected.

## Consequences

**Positive.** Sealed detector evidence and operator-editable geometry stay separate. Scene edits are non-destructive and auditable by revision. A stale attempt cannot corrupt a reclaimed unit. Partial analytics are visible rather than silently empty. Pagination stays stable across configuration changes. No qualified vision artefact is disturbed.

**Accepted costs.** The platform gains a background service and the operational surface that comes with it. Analytics lag the run, so readiness must be explained to operators. Re-analysis after a geometry edit is explicit work rather than an automatic consequence. Facts accumulate per revision, so retention of superseded units becomes a future housekeeping decision.

**Deferred deliberately.** Table shapes, indexes and the reconciliation query (implementing slices); physical-speed calibration; attribution of scene edits to a verified principal, which arrives with operator identity (ADR-010) — until then Development mutations are recorded as server-controlled and explicitly unattributed.
