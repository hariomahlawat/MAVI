# Scene Analytics Slice 7 — security and bounded-resource review

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71 integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Scope:** plan §12 / brief §16. Review by reading the merged implementation and testing execution boundaries, not by scanning.

---

## 1. Findings

### P2 — aggregate materialisation envelope (CLOSED — RETAIN within the qualified envelope)

**What.** `AnalyticsAggregateRepository.ReadFactsAsync` materialises four fact families with `ToListAsync` and no `Take`. The row count scales with facts-in-window, bounded only by the camera and the requested window.

**Why it is not merely a latency question.** The heatmap has two explicit pre-fan-out guards — at most 50 covered runs and 2,000 candidate Analysed Tracks — applied *before* any artefact is opened. The aggregate has no equivalent. Its 512-bucket cap bounds the **response**, not the **work**: a 512-bucket response can be computed from an arbitrary number of facts. A single request for a wide window on a busy camera therefore materialises an unbounded row set into API memory.

**What is already true and limits the severity.** The query *count* is constant and set-based — proven, not assumed, by `AnalyticsQueryShapeTests`, which holds the round-trip count equal from 4 zones/2 lines to 12 zones/6 lines. So this is a materialisation bound, not an N+1.

**Why no fix is proposed here.** Choosing a limit requires knowing what real hardware does at 10^5+ facts, and the plan assigns that decision to the PostgreSQL 18 measurement. Inventing a cap from PostgreSQL 16 intuition is exactly the speculative change §8 of the plan forbids. The harness that will produce the number exists and is committed.

**Required action on the Development machine:** run the plan qualification at 10^5 facts, record rows materialised, peak memory and latency, then take an explicit retain/bound decision in the performance document.

**Where that action stands.** Complete. The owner ran `summarize_aggregate_qualification.py` against the authoritative Development-machine `plan-qualification.json` from reachable SHA `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`. The file reported status **qualification evidence**, clean/resolvable provenance, PostgreSQL 18.6 / pgvector 0.8.6, 110,000 relevant facts, and SHA-256 `3e418ab9fca8dccf8b939cf356e6cde979db682b8d96bade0a799163c667275a`.

**What is already known without the authoritative file, and why it is not enough.** Three of the quantities the decision needs do not depend on the database server at all, and are reproducible anywhere from the seeded corpus:

| Quantity | Evidence | Server-independent? |
|---|---|---|
| Rows materialised per §T case | 30,000 visits, 20,000 crossings, 26,565 summaries, 10,000 intervals (unfiltered); 19,920 / 13,280 / 17,653 / 6,640 (Person); 10,080 / 6,720 / 8,912 / 3,360 (Vehicle) — identical in the superseded Ubuntu PostgreSQL 18 pass and in a current-schema PostgreSQL 16 run at the integrated head | Yes — a function of the seeded corpus and the query, both deterministic |
| Managed allocation | 41.8 MiB for the 60-second unfiltered case in both of those runs; 36.8–37.4 MiB for the coarser unfiltered buckets | Yes — it is .NET materialisation and aggregation, not the planner |
| Database query count | 10 per §T case in every run, constant across bucket size and class | Yes, and held always-on by `AnalyticsQueryShapeTests` |

What is **not** known is the one thing that is the server's: database materialisation and total latency on PostgreSQL 18 on the Development machine. That is exactly the figure the plan assigns to the authoritative run, and neither PostgreSQL 16 observations nor the superseded pass may stand in for it. Two further facts bear on the decision: the harness's 60-second case produces 2,400 buckets — beyond the 512-bucket response cap the API enforces — so its application-side cost is an upper bound on any request the API will accept; and the only hard bound on a request's work is the camera plus the window (at most 512 × 86,400 s), so the qualified envelope, not a guard, is what limits the facts one request reads.

**Decision rule — applied.** The predeclared rule was: RETAIN only if **all nine §T cases** complete in **≤ 10,000 ms total**, allocate **≤ 64 MiB**, and issue exactly **10** database queries; otherwise BOUND with a semantics-preserving pre-work refusal guard, never truncation.

| Bucket / class | Buckets | Visits | Crossings | Summaries | Intervals | DB ms | App ms | Total ms | Allocated MiB | GC 0/1/2 | DB queries |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 60 / any | 2400 | 30000 | 20000 | 26565 | 10000 | 1861 | 2544 | 4405 | 42.6 | 3/1/1 | 10 |
| 60 / Person | 2400 | 19920 | 13280 | 17653 | 6640 | 2394 | 1797 | 4191 | 31.9 | 6/6/1 | 10 |
| 60 / Vehicle | 2400 | 10080 | 6720 | 8912 | 3360 | 584 | 874 | 1458 | 15.4 | 2/0/0 | 10 |
| 900 / any | 160 | 30000 | 20000 | 26565 | 10000 | 1346 | 171 | 1517 | 37.9 | 3/1/1 | 10 |
| 900 / Person | 160 | 19920 | 13280 | 17653 | 6640 | 928 | 111 | 1039 | 28.0 | 2/1/1 | 10 |
| 900 / Vehicle | 160 | 10080 | 6720 | 8912 | 3360 | 543 | 58 | 601 | 14.5 | 1/1/1 | 10 |
| 3600 / any | 40 | 30000 | 20000 | 26565 | 10000 | 1335 | 54 | 1389 | 37.8 | 4/2/1 | 10 |
| 3600 / Person | 40 | 19920 | 13280 | 17653 | 6640 | 941 | 31 | 972 | 27.9 | 2/1/1 | 10 |
| 3600 / Vehicle | 40 | 10080 | 6720 | 8912 | 3360 | 543 | 19 | 562 | 14.4 | 2/0/0 | 10 |

Every case satisfies the RETAIN rule. Worst observed total time was **4,405 ms**, worst managed allocation was **42.6 MiB**, and every case issued exactly **10** database queries. **Disposition: RETAIN** the current design for Stage 1, document that work remains linear in facts inside the requested window, and treat **10⁵ relevant facts per request** as the qualified envelope. No row cutoff or truncation is introduced. The P2 is therefore **closed as dispositioned** for this gate.

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
- Resource measurement behind the P2 above — **PASS for the predeclared Stage-1 envelope** on PostgreSQL 18; decision **RETAIN**, with the qualified envelope and linear-work caveat recorded (§1).

Nothing in this list is converted into a pass unless it was executed.
