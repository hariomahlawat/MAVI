# Scene Analytics Slice 7 — resilience, concurrency and cancellation

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Tests:** `tests/Mavi.IntegrationTests/Qualification/RealisticVolumeResilienceTests.cs`, `tests/Mavi.IntegrationTests/Qualification/ConcurrencyRaceProbeTests.cs`

---

## Status

| Plan §25 item | Status |
|---|---|
| 8 — cancellation/failure proven at realistic volume | **PASS** — four deterministic tests at the heatmap's full envelope and over a 1,000-Track unit (§2) |
| 9 — snapshot/revision consistency proven under concurrency | **PASS** — three deterministic race probes that put a writer *inside* a stopped reader (§3) |

Both files run in the **ordinary** integration suite, not behind `MAVI_QUALIFICATION`: the envelope corpus builds in seconds, so these properties are checked on every head, including CI's PostgreSQL 18 job. Locally they ran on PostgreSQL 16.15, which is sufficient for correctness properties of this kind; they are not performance evidence and make no timing claim.

**No sleep decides any outcome.** Interruptions are placed by counting evidence reads through decorators over the production readers. The one wait in the race probes is for an observable database fact — a writer's advisory-lock request appearing in `pg_locks` as not granted — and it is bounded, so a regression fails rather than hangs.

Two plan §11 cases stay outside these items and are recorded, not converted: **API restart — PASS** on the Development machine (unchanged from the previous revision), and **PostgreSQL restart/reconnect — NOT EXECUTED**, an operator action (runbook `docs/runbooks/scene-analytics-stage1-development-acceptance.md` §F).

## 1. What already existed, from Slices 3–6

| Property | Where |
|---|---|
| The visibility barrier is acquired **before** any scope-defining read, on both analytics read paths | `AnalyticsAggregateRepositoryTests`, `TrackSearchAnalyticsRepositoryTests` |
| Two successive requests take **distinct, monotonic** snapshots; facts published after a snapshot are absent from it | `AnalyticsAggregateRepositoryTests` |
| A second host does not block behind another's claim | `SceneAnalyticsWorld.ImpatientHost`, `SceneAnalyticsLifecycleTests` |
| Reclaim and ownership fencing: a reclaimed attempt can neither complete nor fail the unit that replaced it; exhausted units cannot be resurrected; a rejected completion deletes no facts; colliding attempt numbers are rejected | `SceneAnalyticsOwnershipTests` (10 tests) |
| Pagination stays pinned to its revision and coverage across an activation | `TrackSearchAnalyticsRepositoryTests.ActivatingANewRevisionMakesTheRunStaleForANewSearchButNotForThePinnedOne` |
| Supersession ordering across revisions and engines | `SceneAnalyticsRemediationTests` |

These are the sequential halves. What was missing was volume and a real interleaving.

## 2. Cancellation and failure at realistic volume (item 8)

| Test | Interruption | What it proves |
|---|---|---|
| `AHeatmapCancelledPartWayThroughItsEnvelopeReturnsNoMapAndStopsReading` | Client cancellation raised from inside the **500th** of 2,000 artefact reads, at 50 covered runs | No result object exists to be served; **exactly 500** artefacts were read — none after the cancellation; the next request is **byte-for-byte** the uninterrupted map (same identity, coverage, sample count and matrix) |
| `AHeatmapWhoseEvidenceFailsPartWayThroughItsEnvelopeFailsClosedAndRecovers` | The **1,337th** candidate's bytes replaced with another Track's sealed trajectory — decodable, well formed, wrong digest | `EvidenceUnreadable`, **no grid and zero contributing Tracks** although 1,336 had been accumulated; reading stopped at the bad artefact; restoring the bytes restores the exact uninterrupted map |
| `AUnitCancelledPartWayThroughAThousandTracksPublishesNothingAndIsReclaimedToTheFullAnswer` | Host A stopped after its **400th** trajectory read | The unit stays `Running` with no visibility sequence and **zero fact rows of any family**; readers are told the run is **pending**, never that it holds zero activity; the lease holds until lease + grace; host B reclaims it with attempt 2 and a **fresh token**, and produces the full seeded answer (1,000 outcomes, 185 visits, 4,000 zone summaries, 1,391 crossings, 1,000 motion summaries); host A's stale claim can then neither complete nor fail the unit, and the facts are unchanged |
| `AUnitWhoseEvidenceStoreFailsPartWayThroughAThousandTracksPublishesNothingAndRetriesToTheFullAnswer` | An I/O fault on the **600th** read | The attempt fails with `trajectory_read_failed` rather than writing the Track off as `Unavailable`; nothing is published; the unit returns to `Queued`; the retry produces the same full answer and complete coverage |

The full-answer figures are asserted exactly, not as "non-zero". They are the same rows the qualification harness recorded on the Windows Development machine, the superseded Ubuntu pass and this Linux container — three environments, one answer.

**The heatmap persists nothing**, so "leaves no misleading complete evidence" is proved there by the next request being the exact uninterrupted answer. **The analytical unit** is where evidence is persisted, and there the proof is that the cancelled or faulted attempt left no fact row and no visibility sequence, and that coverage said *pending*.

## 3. Concurrency race probes (item 9)

Each probe names the protection it exercises. A read that resolves scope and reads facts in one transaction holds the shared visibility barrier, so a publication must **wait** for it. The heatmap reads its evidence outside any transaction after its scope has committed, so a publication can land in that gap; there the protection is that everything after the scope is **pinned** to the identity and snapshot the scope resolved.

| Probe | Interleaving | What it proves |
|---|---|---|
| `AnAggregateStoppedInsideItsSnapshotIsUnmovedByAUnitCompletionThatMustWaitForIt` | The aggregate is stopped immediately before its first fact read — after barrier, snapshot, scope and coverage. A unit for revision 2 then computes and tries to publish | The writer is **observed waiting** on the advisory lock and has not completed; the reader's answer equals the pre-writer answer in identity, coverage and facts; the unit's sequence is greater than the reader's snapshot; the next read sees the publication **in full** (the run evaluated, every one of its 25 Tracks counted) |
| `AHeatmapStoppedBetweenItsScopeAndItsEvidenceDrawsTheWorldItsScopeResolved` | The heatmap is stopped after scope resolution and before the candidate listing. **Two** publications land in the gap and complete without waiting: a new revision is activated, and a unit is analysed and published against it | The map is revision 1's **exactly** — same identity, coverage, Track count and matrix. Following the activation would have drawn one run; following the new unit without its revision would have counted run 0's Tracks twice. The next heatmap is revision 2's and holds only what revision 2 has evaluated |
| `ARevisionActivationWaitsForAUnitCommitAlreadyHoldingThePublicationBarrier` | A unit commit is stopped immediately after taking the exclusive barrier, facts written but uncommitted. A revision activation then starts | The activation is **observed waiting**; nothing of the unit is observable while it is held; after release the unit publishes under its own pinned revision and the activation lands after it; revision 3's aggregate reports **zero evaluated runs and no facts** — revision 2's facts are never read as revision 3's |

**The probes discriminate.** With the shared-barrier acquisition removed from `AnalyticsAggregateRepository.AggregateAsync`, the first probe fails: the writer never has to wait. The source was restored immediately; the negative run is recorded here, not committed.

**What the heatmap probe does not exercise.** Both publications in its gap are under a *new* revision, so it proves the listing's **revision** pin. A publication under the *same* revision in that gap — which would exercise the listing's snapshot-sequence pin — is not raced; that filter is the same `VisibleUnits(…, snapshotVisibilitySequence)` predicate whose behaviour `FactsPublishedAfterTheSnapshotAreNotInTheAnswer` holds sequentially.

**The one publication path not raced directly** is a processing-run completion. It takes the same exclusive barrier, through the same `ProcessingVisibilityBarrier.AcquireCompletionExclusiveAsync` statement, as the unit commit the first and third probes race, so the same protection applies — but that is an inference from shared code, not a probe, and it is stated as one.

**What these prove, together with §1:** no mixed visibility generation; aggregate/heatmap coverage and facts from one snapshot; no geometry/fact revision mixing; pagination pinned (§1); historical results reproducible after activation; and no competing ownership commit (§1 and §2's stale-claim assertions at 1,000 Tracks).
