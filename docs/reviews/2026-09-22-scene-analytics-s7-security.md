# Scene Analytics Slice 7 — security and bounded-resource review

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Scope:** plan §12 / brief §16. Review by reading the merged implementation and testing execution boundaries, not by scanning.

---

## 1. Findings

### P2 — the aggregate read has no work bound (OPEN, decision deferred to PostgreSQL 18)

**What.** `AnalyticsAggregateRepository.ReadFactsAsync` materialises four fact families with `ToListAsync` and no `Take`. The row count scales with facts-in-window, bounded only by the camera and the requested window.

**Why it is not merely a latency question.** The heatmap has two explicit pre-fan-out guards — at most 50 covered runs and 2,000 candidate Analysed Tracks — applied *before* any artefact is opened. The aggregate has no equivalent. Its 512-bucket cap bounds the **response**, not the **work**: a 512-bucket response can be computed from an arbitrary number of facts. A single request for a wide window on a busy camera therefore materialises an unbounded row set into API memory.

**What is already true and limits the severity.** The query *count* is constant and set-based — proven, not assumed, by `AnalyticsQueryShapeTests`, which holds the round-trip count equal from 4 zones/2 lines to 12 zones/6 lines. So this is a materialisation bound, not an N+1.

**Why no fix is proposed here.** Choosing a limit requires knowing what real hardware does at 10^5+ facts, and the plan assigns that decision to the PostgreSQL 18 measurement. Inventing a cap from PostgreSQL 16 intuition is exactly the speculative change §8 of the plan forbids. The harness that will produce the number exists and is committed.

**Required action on the Development machine:** run the plan qualification at 10^5 facts, record rows materialised, peak memory and latency, then take an explicit retain/bound decision in the performance document.

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

## 3. Not executed in this environment

- Cancellation under realistic C3 volume, and PostgreSQL restart/reconnect — both need the PG18 qualification run.
- Resource-exhaustion measurement behind the P2 above.

These are **NOT EXECUTED — environment blocked**, not passes.
