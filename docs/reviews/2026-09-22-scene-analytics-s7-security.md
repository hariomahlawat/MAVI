# Scene Analytics Slice 7 — security and bounded-resource review

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Scope:** plan §12 / brief §16. Review by reading the merged implementation and testing execution boundaries, not by scanning.

---

## 1. Findings

### P2 — the aggregate read has no work bound (OPEN — BLOCKED on transcribing the authoritative PostgreSQL 18 figures)

**What.** `AnalyticsAggregateRepository.ReadFactsAsync` materialises four fact families with `ToListAsync` and no `Take`. The row count scales with facts-in-window, bounded only by the camera and the requested window.

**Why it is not merely a latency question.** The heatmap has two explicit pre-fan-out guards — at most 50 covered runs and 2,000 candidate Analysed Tracks — applied *before* any artefact is opened. The aggregate has no equivalent. Its 512-bucket cap bounds the **response**, not the **work**: a 512-bucket response can be computed from an arbitrary number of facts. A single request for a wide window on a busy camera therefore materialises an unbounded row set into API memory.

**What is already true and limits the severity.** The query *count* is constant and set-based — proven, not assumed, by `AnalyticsQueryShapeTests`, which holds the round-trip count equal from 4 zones/2 lines to 12 zones/6 lines. So this is a materialisation bound, not an N+1.

**Why no fix is proposed here.** Choosing a limit requires knowing what real hardware does at 10^5+ facts, and the plan assigns that decision to the PostgreSQL 18 measurement. Inventing a cap from PostgreSQL 16 intuition is exactly the speculative change §8 of the plan forbids. The harness that will produce the number exists and is committed.

**Required action on the Development machine:** run the plan qualification at 10^5 facts, record rows materialised, peak memory and latency, then take an explicit retain/bound decision in the performance document.

**Where that action stands.** The first half is done: `PlanQualificationTests` passed on PostgreSQL 18.6 at 110,000 facts on the Development machine, at reachable SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`, and its evidence file records the rows materialised, database and application time, allocated bytes and GC deltas for all nine §T cases. The second half is not: those figures are held outside the repository and are **not available in this repository or in the environment that prepared this revision**, so no retain/bound decision has been taken. The finding remains **OPEN — BLOCKED on transcription**, and it is the P2 that holds formal exit-gate items 7, 12 and 18.

**What is already known without the authoritative file, and why it is not enough.** Three of the quantities the decision needs do not depend on the database server at all, and are reproducible anywhere from the seeded corpus:

| Quantity | Evidence | Server-independent? |
|---|---|---|
| Rows materialised per §T case | 30,000 visits, 20,000 crossings, 26,565 summaries, 10,000 intervals (unfiltered); 19,920 / 13,280 / 17,653 / 6,640 (Person); 10,080 / 6,720 / 8,912 / 3,360 (Vehicle) — identical in the superseded Ubuntu PostgreSQL 18 pass and in a current-schema PostgreSQL 16 run at the integrated head | Yes — a function of the seeded corpus and the query, both deterministic |
| Managed allocation | 41.8 MiB for the 60-second unfiltered case in both of those runs; 36.8–37.4 MiB for the coarser unfiltered buckets | Yes — it is .NET materialisation and aggregation, not the planner |
| Database query count | 10 per §T case in every run, constant across bucket size and class | Yes, and held always-on by `AnalyticsQueryShapeTests` |

What is **not** known is the one thing that is the server's: database materialisation and total latency on PostgreSQL 18 on the Development machine. That is exactly the figure the plan assigns to the authoritative run, and neither PostgreSQL 16 observations nor the superseded pass may stand in for it. Two further facts bear on the decision: the harness's 60-second case produces 2,400 buckets — beyond the 512-bucket response cap the API enforces — so its application-side cost is an upper bound on any request the API will accept; and the only hard bound on a request's work is the camera plus the window (at most 512 × 86,400 s), so the qualified envelope, not a guard, is what limits the facts one request reads.

**Decision rule — proposed, and written before the authoritative figures have been seen.** Plan §5 requires objectives to be frozen before measurement; that did not happen, so the next best discipline is to fix the rule before the figures are read. **This rule is a proposal and needs the owner's approval before it is applied**:

- **RETAIN** the current design, close the P2 as dispositioned and document the envelope (per-request work linear in the facts inside the window; 10⁵ relevant facts per request is the qualified envelope; no request is truncated) **if, on the authoritative figures, every one of the nine §T cases** completes in **≤ 10,000 ms total**, allocates **≤ 64 MiB**, and issues the constant **10** database queries.
- **BOUND** otherwise: add a pre-work guard on the covered-Track count, taken from the same cheap scope metadata the heatmap guard uses, that **refuses** with a named problem code rather than truncating — never a row cutoff that could return an incomplete aggregate. That is a contract change and is preceded by an ADR-011 note.

**Action:** run `tools/qualification/summarize_aggregate_qualification.py` on the authoritative file (runbook `docs/runbooks/scene-analytics-stage1-development-acceptance.md` §A), paste its table into the performance report §8.3, and apply the approved rule.

### P3 — the Python worker decoder does not enforce the `[0,1]` centre range (RECORDED, not changed)

`deserialize_trajectory` validates structure, types and monotonic offsets, but not the coordinate range; the .NET `TrajectoryDecoder` does, via `NormalizedPoint.IsInRange`. The authoritative gate is the .NET one, because it decides whether a trajectory may produce facts, and it is correct.

Not changed deliberately: tightening read validation in the worker changes what the evidence-production path accepts and would need its own qualification. It is recorded so the asymmetry is known rather than rediscovered.

### P3 — a deterministic parse failure is retried once (RECORDED)

`useTrajectory` retries any non-`ApiError` failure once. A malformed artefact cannot become valid on a second read, so the retry costs one wasted fetch. Harmless, and not worth a behavioural change during a hardening slice.

## 2. Reviewed and found sound

| Area | Finding |
|---|---|
| Strict query whitelist | Both Slice-6 analytics routes reject unknown keys and repeated singleton keys; pinned by `AnalyticsApiTests` |
| Value parsing | Timestamps must name UTC explicitly; a local time is refused rather than guessed |
| Closed vocabularies | Bucket seconds, grid widths, object class and run id all validated before work; `objectClass` casing now matches `/api/tracks` |
| Enumeration | An unknown camera, an unknown run and another camera's run return **byte-identical** bodies — asserted, not assumed |
| Response-size bound | 512 buckets, refused before any query |
| Heatmap fan-out | 50 runs and 2,000 candidate Tracks, both enforced **before** the first artefact open; proven by call-ordering tests that throw if the expensive path is reached |
| Evidence integrity | Missing artefact, de-referenced artefact and SHA-256 mismatch all fail closed as `EvidenceUnreadable`; no partial map |
| Path and error leakage | The 503 body carries no storage key, path, digest or `msgpack` token — asserted explicitly |
| Cursor integrity | v3 is HMAC-authenticated and verified before embedded coverage or identity is trusted |
| Execution boundary vs UI | The manual Refresh bypass found in Slice 6 was closed at the query gate, not by disabling a button; the regression test asserts the **query function is not called**, not the button state |

## 3. Resilience and resource cases, and where each stands

- Cancellation and failure at realistic volume — **PASS**. `RealisticVolumeResilienceTests` cancels the heatmap part-way through its full 50-run / 2,000-Track envelope and a 1,000-Track analytical unit part-way through its Tracks, and fails each part-way with corrupt evidence or an evidence-store fault. No partial answer is returned or published, no read happens after the interruption point, and every retry reproduces the uninterrupted answer exactly. Details in `2026-09-22-scene-analytics-s7-resilience-concurrency.md`.
- PostgreSQL restart/reconnect — **NOT EXECUTED**. An operator action on the Development machine (runbook §F).
- API restart — **PASS**, on the Development machine: after restarting `Mavi.Api`, the real-worker analytics, the Revision 2 identity, the zone facts, the Activity values and the Heatmap were all still present.
- Resource measurement behind the P2 above — **measured** on PostgreSQL 18; **decision BLOCKED** on transcribing the authoritative figures (§1).

Nothing in this list is converted into a pass unless it was executed.
