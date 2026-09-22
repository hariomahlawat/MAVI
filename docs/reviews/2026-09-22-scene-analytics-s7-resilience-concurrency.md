# Scene Analytics Slice 7 — resilience, concurrency and cancellation

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## Status: NOT EXECUTED in this pass

Plan §25 items **8** (cancellation/failure at realistic volume) and **9** (snapshot/revision consistency under concurrency) are **not met**. This document records what exists, what does not, and what must be run — it does not convert either into a pass.

One resilience case *was* executed since this document was written: **API restart persistence — PASS** on the Development machine. After `Mavi.Api` was restarted, the real-worker analytics, the Revision 2 identity, the zone facts, the Activity values and the Heatmap were all unchanged. That is plan §11's API-restart case. It does not touch items 8 or 9.

## 1. What already exists, from Slices 3–6

These are real tests in the suite today, and they are the reason items 9 and 10 are *incomplete* rather than *unaddressed*:

| Property | Where |
|---|---|
| The visibility barrier is acquired **before** any scope-defining read, on both analytics read paths | `AnalyticsAggregateRepositoryTests`, `TrackSearchAnalyticsRepositoryTests` — call ordering, not merely the status code |
| Two successive requests take **distinct, monotonic** snapshots | `AnalyticsAggregateRepositoryTests.TwoRequestsTakeDistinctMonotonicSnapshots` |
| Facts published after a snapshot are absent from that answer | `AnalyticsAggregateRepositoryTests.FactsPublishedAfterTheSnapshotAreNotInTheAnswer` |
| A second host does not block behind another's claim — asserted with a deliberately impatient connection, so waiting *fails* rather than merely finishing late | `SceneAnalyticsWorld.ImpatientHost`, `SceneAnalyticsLifecycleTests` |
| A failed attempt is retried without duplicating facts; the fact fingerprint is unchanged | `SceneAnalyticsExecutorTests` |
| Evidence that is missing, corrupt, invalid or too short is written off as `Unavailable` and the unit completes around it, while a fault that says nothing about the evidence fails the attempt | `SceneAnalyticsExecutorTests` |
| Request cancellation is honoured at the middleware boundary | `RequestCancellationMiddlewareTests` |

Corpus building added one more, incidentally: the corpus now **refuses to return a manifest a reader's own snapshot cannot see**, which is a snapshot-visibility assertion executed on every qualification build.

## 2. What is missing

| Exit-gate item | Missing |
|---|---|
| §25 item 8 — cancellation and failure **at realistic volume** | Every failure test above runs on a one-Track world. None runs against the C3 corpus, so nothing shows what a cancelled or failed unit costs, leaves behind, or holds a lease over at 10^5 facts. PostgreSQL 18 is now available on the Development machine, so this is no longer environment-blocked; the harness is simply **not written** |
| §25 item 9 — snapshot/revision consistency **under concurrency** | The deterministic race probes are not written: a scene revision activated *while* an aggregate is being resolved, a unit completing *between* scope resolution and fact read, two readers interleaved across a publication. The ordering tests above prove the barrier is taken in the right place; they do not prove the outcome when a writer actually races a reader |

## 3. What must be run, and built

1. Write a concurrency probe that activates a new scene revision inside an in-flight aggregate resolution, using the caller-owned transaction seam `SceneAnalyticsWorld.ActivateNewRevisionAsync(MaviDbContext, DateTimeOffset)` already provides, and assert the answer is wholly on one side of the activation — never a mixture.
2. Write a probe that completes an analytical unit between scope resolution and fact read, and assert the unit's facts are absent from that answer and present in the next.
3. Extend both, and the existing cancellation and failure tests, to run against the C3 corpus under `MAVI_QUALIFICATION=1`, recording lease state and orphaned rows after a cancelled unit.
4. Execute all of it on PostgreSQL 18 on the Development machine.

Until 1–4 are done, §25 items 8 and 9 stay **NOT EXECUTED**, and Stage 1 stays open.
