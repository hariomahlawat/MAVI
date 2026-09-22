# Scene Analytics Slice 7 — performance and bounded-resource evidence

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance`
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`

---

## 1. Qualification status, stated first

**No measurement in this document is qualification evidence.** The parent plan requires PostgreSQL 18; this container has 16.15 and cannot obtain 18 (`apt.postgresql.org` returns HTTP 403 through the agent proxy, and there is no Docker daemon to pull `pgvector/pgvector:pg18`). Every figure below is an **engineering observation** taken to prove the harness measures what it claims to measure.

The harness does not rely on a reader remembering this. `QualificationGate.CaptureEnvironmentAsync` reads the live `server_version`, records it beside every result, and computes `isQualificationGradeDatabase`, which is `false` for every run in this document.

## 2. Harnesses built

All under `tests/Mavi.IntegrationTests/Qualification/`, gated on `MAVI_QUALIFICATION=1`, **no new dependency**.

| Harness | Exit-gate item | What it measures |
|---|---|---|
| `PlanQualificationTests` | 3, 5 | Every §S predicate family (23, including all eight headings), and every §T aggregate at three bucket sizes × three class filters (unfiltered, Person, Vehicle) — nine measurements, because the class filter changes `BaseCandidates` and so the joins and cardinalities of every fact query. Each is timed across the whole §T path (repository fetch **and** `AnalyticsAggregator.Compute`, whose cost grows with facts and buckets) and `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`-captured from the SQL the product actually issued |
| `ThroughputQualificationTests.OneAnalyticalUnit…` | 4 | One analytical unit over a synthetic 1,000-Track run with real sealed trajectories: duration, ms/Track, analysed and unavailable counts, rows written per fact table |
| `ThroughputQualificationTests.TheHeatmap…` | 6 | The heatmap at the **frozen** envelope — `MaximumHeatmapRuns` covered runs and `MaximumHeatmapTracks` candidates — at three grid widths |

Three always-on guards keep these from drifting into decoration:

- `TheMeasurementPlanNamesEverySearchPredicateTheContractDefines` reflects over `TrackAnalyticsQuery`'s primary constructor, so a §S predicate added in a later slice fails the build rather than quietly falling out of "every predicate".
- `TheEnvelopeMeasuredIsTheEnvelopeEnforced` reads `AnalyticsQueryRules`, so the harness cannot keep measuring a limit the product no longer has.
- `TheVersionThatQualifiesIsTheVersionTheProductRequires` reads `DatabasePrerequisiteOptions`, so the version that counts as qualification-grade cannot drift from the one the platform accepts.

## 3. A defect in the harness, found by running it

The first heatmap-envelope run built 50 runs and 2,000 Tracks and then reported **0 covered runs, 0 candidate Tracks**, while the heatmap itself contributed 40 Tracks, then 40, then 80 across three successive calls.

**Cause.** The corpus assigned completion visibility sequences from a local counter (1, 2, 3 …). A reader allocates its snapshot from the database's `processing_visibility_sequence` and admits only rows at or below it. On a freshly reset database the first reader's snapshot is 1, the second's 2 — so a corpus numbered locally is almost entirely *invisible*, and each successive call sees one more run.

**Consequence, which is the serious part.** The already-committed `PlanQualificationTests` shares that corpus. Every §S and §T measurement it would have produced on the Development machine would have been taken over a near-empty database: fast, plausible-looking and meaningless. The bug survived the earlier smoke run because a harness that writes an evidence file and asserts the file exists does not notice that every row count in it is zero.

**Fix.** The corpus now publishes the way the pipeline does — one transaction per video, the completion barrier held across a real `nextval` — and, before returning a manifest, takes a reader's own snapshot and refuses to hand back a corpus that snapshot cannot see.

**After the fix:** all 23 §S predicate families return rows and the aggregate sees its facts.

## 3b. Three further defects in the harness, from independent review

All three were in the harness rather than the product, and all three would have produced qualification evidence that looked fine.

1. **The default corpus was half the required volume.** 40 runs × 120 Tracks × 11 facts is **52,800** relevant facts, not the 528,000 a comment claimed — a tenfold arithmetic error on my part. Since those defaults drive the unchanged PostgreSQL 18 command, every §S and §T plan would have been measured below the mandatory 10⁵ prerequisite. Defaults are now 40 × 250 = 110,000 (11.0 facts per Track, confirmed by measurement rather than by arithmetic), the fact count and the prerequisite are both written into the evidence file, and a run on the required server **fails** if the corpus is undersized rather than quietly reporting it.

2. **The §T timer stopped at the repository.** `AggregateAsync` only materialises the fact set; the counting rules — occupancy, unique tracks, repeated visits, the per-bucket series — are `AnalyticsAggregator.Compute`, and their cost grows with facts and buckets. The reported latency was one an operator never experiences. The clock now spans both.

3. **The class-filtered §T path was never planned.** Every aggregate measurement passed `null` for the object class, so the filtered path — which changes `BaseCandidates` and therefore the joins and cardinalities of every fact query — went unmeasured. Now measured as its own case: at a 4-run shape check the filters partition cleanly (1,992 Person + 1,008 Vehicle = 3,000 unfiltered visits), so they are demonstrably not the unfiltered call in disguise.

4. **The throughput harness returned green when nothing was claimable.** A regression in corpus construction or lifecycle eligibility would have passed the qualification command having measured no throughput at all — the same shape of silent emptiness as the visibility defect above. It now writes the diagnostic and then fails.

5. **`isQualificationGradeDatabase` accepted 18 or later.** The platform's own prerequisite check is an equality, so a run against 19 is a run against a planner the product refuses; labelling it qualification-grade would let it be presented as satisfying the PostgreSQL 18 exit gate. It now requires exactly 18, and an always-on test pins that number to the product's.

## 3c. A second independent review, and the worst defect yet

A cold review of the harness found three more ways a PostgreSQL 18 run could report green without having measured its subject. Auditing around them found three more again. All are fixed, and the fix is a shared mechanism rather than six patches, because this is now the third time the same shape of mistake has appeared.

### The §S measurements never exercised a single §S predicate

`PlanQualificationTests` called `TrackSearchRepository.SearchAsync`. That method applies only the **non-analytic** base candidate set — camera, window, class — and discards the analytics query entirely; the §S predicates live in `SearchAnalyticsAsync`.

So all 23 §S predicate families planned and timed **the same plain Track search**, while the evidence named a different predicate each time. Nothing looked wrong: rows came back, the plans were real `EXPLAIN` output, the file was complete.

The evidence from before the fix shows it plainly — every predicate returning exactly the page size, from exactly one database query:

| Predicate | rows | DB queries |
|---|---|---|
| `zoneId (default dwelled)` | 50 | 1 |
| `motionDirection=N` … `NW` | 50 each | 1 each |

and the captured SQL for `motionDirection=N` referenced `tracks` and **none** of `track_motion_summaries`, `track_zone_visits`, `track_line_crossings`, `track_zone_summaries`, `scene_analyses`.

After the fix, the same shape check over a 120-Track corpus:

| Predicate | rows | DB queries |
|---|---|---|
| `zoneId (default dwelled)` | 51 | 8 |
| `motionDirection=N` | 18 | 8 |
| `motionDirection=NE` | 13 | 8 |
| `motionDirection=E` | 15 | 8 |
| `motionDirection=SE` | 17 | 8 |
| `motionDirection=S` | 10 | 8 |
| `motionDirection=SW` | 14 | 8 |
| `motionDirection=W` | 16 | 8 |
| `motionDirection=NW` | 17 | 8 |

The eight headings now sum to 120 — the whole population, partitioned — which is what a real `motionDirection` filter must do.

This is exit-gate item 3. Had PostgreSQL 18 been available before this review, the slice would have produced a complete plan/timing document for "every §S predicate" in which no §S predicate was ever planned.

### The other five

| Finding | Why it could pass falsely | Repair |
|---|---|---|
| Throughput green despite failed or partial execution | The only acceptance assertion was that the evidence file existed, so a failed executor, a short population or missing facts all passed | Ten integrity expectations derived from product semantics: unit succeeded, every Track analysed, none unavailable, one outcome and one motion summary per Track, one zone summary per Track per zone, visits and crossings both exercised, unit `Completed` and published |
| Heatmap envelope not proven | Resolved scope and service result were recorded but never asserted, so a fraction of the corpus — or none — still emitted a timing file | Scope must equal the product's own `MaximumHeatmapRuns` and `MaximumHeatmapTracks`; every measurement must succeed, have every candidate contribute, read exactly `candidates × sealed samples`, honour the requested grid width and produce a populated grid |
| §S/§T could measure nothing | Corpus volume was enforced but not per-measurement meaning | Each measurement must be valid, capture SQL, produce a real `EXPLAIN` plan, reach the fact table its predicate names, and select from the corpus |
| SQL or plan capture could vanish silently | Zero captured statements produced zero plans and stayed green | Captured-statement count and plan text are now expectations |
| Stale evidence could be mistaken for current | A run that threw left the previous run's complete, plausible file in place | Each harness claims its filename first with an explicitly incomplete record, so a failed run leaves a file that says so |
| `MAVI_QUALIFICATION=true` skipped silently | Only `1` enabled the pass; anything else was treated as unset | Any other value throws — an operator who believes the qualification ran must not be told it passed |
| Overrides could shrink a qualification run | `MAVI_QUAL_UNIT_TRACKS=20` produced a file headed "1,000-Track run" | The workload shape is a qualification prerequisite, recorded and enforced on the required server |
| Provenance could not identify the binary | `gitSha` reports the parent commit of a dirty tree quite happily | The built assembly's module id and build timestamp are recorded beside it |

### The mechanism, not the six patches

Every harness now routes its expectations through `QualificationVerdict`, which separates two things that were previously conflated:

- **Integrity** — the measurement did not exercise its subject. Fatal on any server, because a harness that measured the wrong thing is broken on PostgreSQL 16 just as much as on 18.
- **Prerequisite** — the run is real but cannot be called qualification evidence (server version, corpus volume, workload shape). Fatal only on the required server; elsewhere recorded, and the run stays an engineering observation.

Every expectation is written into the evidence file beside the numbers it qualifies, and the file names its own status: `qualification evidence`, `engineering observation — not qualification evidence`, or `qualification failure`. The governing rule is that no evidence is better than false evidence, so an unmet expectation fails the run — and the evidence is still written, so the failure can be investigated.

## 4. Engineering observations (PostgreSQL 16.15, NOT qualification)

Environment: Ubuntu 24.04, 4 logical cores, .NET 10.0.12, PostgreSQL 16.15, pgvector 0.6.0, `shared_buffers` 128MB, `work_mem` 4MB.

### 4.1 Analytical unit

| Tracks | Duration | Per Track | Outcome |
|---|---|---|---|
| 20 (shape check) | 586 ms | 29.3 ms | 20 analysed, 0 unavailable |

Not run at 1,000 here; the harness takes `MAVI_QUAL_UNIT_TRACKS` and defaults to 1,000 on the Development machine.

### 4.2 Heatmap at the frozen envelope

50 covered runs, 2,000 candidate Tracks, all 2,000 contributing, 48,000 samples read from disk through the production evidence reader:

| Grid width | Cells | Duration |
|---|---|---|
| 48 | 1,296 | 332 ms |
| 96 | 5,184 | 293 ms |
| 128 | 9,216 | 288 ms |

Cost is dominated by evidence I/O rather than grid size, which is what the design predicts: the same 48,000 samples are read regardless of how finely they are binned. **This is not a basis for an acceptance decision** — the envelope decision belongs to a PostgreSQL 18 run.

## 5. Open finding carried forward

**P2 — the aggregate read materialises an unbounded number of fact rows.** Query *count* is constant in geometry (proven by an always-on test at 4 zones/2 lines versus 12 zones/6 lines), so there is no N+1. Row *volume* is bounded only by the requested window. A limit decision requires PostgreSQL 18 measurement, and the parent brief forbids introducing speculative indexes, caches or limits from PostgreSQL 16 observations alone. It therefore stays open, recorded, and assigned to the qualification run.
