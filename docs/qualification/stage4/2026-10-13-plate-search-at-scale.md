# Stage 4 PR-4: plate search at 10^6 Tracks, and the index write cost

**Updated 2026-10-16 (cold review of PR #219; owner decisions 1–8):** the 2026-10-15 "budget MET" is scoped to the frozen query set v1. A new query set v2, frozen before it was measured, exercises the filter classes v1 did not, and **misses the budget on 3–4 of its 10 queries**, so the plan §2.8 budget is **NOT MET for v2**. The informational CI job is moved out of the Quality Gate. The 2026-10-15 and 2026-10-14 sections follow unchanged as historical evidence.

## Correction round (2026-10-16): scope of the v1 verdict, query set v2

### What the 2026-10-15 verdict did and did not cover

- **"Budget MET" (2026-10-15) holds for the frozen query set `mavi-plate-search-queries-v1` (Q01–Q14, S1) only.** It still holds on the corrected head (below). It is not a claim about every filter combination the API accepts.
- **Filter classes v1 did not measure.** v1's only Track-level filter was Q12's one-day window over the newest day. It had no historical upper bound (`toUtc` far in the past), no `minimumConfidence`, no `minimumDurationMs`, no `objectSubclass`, no lower bound alone, and no combined analytic + plate search.
- **The repeated-batch mechanism (cold review P1-2).** On the 2026-10-15 head only the run, camera and video filters (and the latest-run scope) reached the candidate statement. The time window, confidence, duration, subclass and analytic predicates were applied only by the base chain, after each batch. Every candidate those predicates rejected therefore cost a batch slot, and every batch re-read the whole text match: the keyset is a heap filter after the trigram scan, not an index condition, so a page needing b batches cost about b full matches (≈ M²/4096 rows read for M matches). The reviewer's probe at 50 runs × 1 000 Tracks, `contains KA0`: 45–106 ms unfiltered; 524–538 ms with `toUtc` at the end of the oldest run; 491–525 ms with `minimumConfidence` 0.95 (`Rows Removed by Filter: 48896`). A combined analytic + plate search whose analytic scope could not be evaluated also walked every candidate batch, because each restricted analytic page returned nothing (P2-1).

### What changed (owner decisions 2, 4, 6)

- **Pushed Track predicates** (`TrackSearchRepository.Plates.cs`, `CandidateBatchAsync`). The candidate statement now applies the base chain's own Track-level predicates, in its exact form: `toUtc` as `track_start_timestamp_utc < toUtc` inside the text match (ADR-018: the column equals the Track's start); `fromUtc` (`end_timestamp_utc >= fromUtc`), `minimumDurationMs`, `minimumConfidence` (`>=`) and the exposed subclass with its approved source as an EXISTS on `tracks`, probed in page order under `ORDER BY … LIMIT`. Each can only remove Tracks the base chain removes; the base chain still applies every predicate. Result semantics, order, cursor, snapshot and plate matching are unchanged; no work cap was added. A first form joined `tracks` to every match; a diagnostic EXPLAIN on this corpus (not evidence) showed `minimumConfidence` 0.8 taking 0.8–0.9 s that way, so the probe was moved after the page-order sort before anything was measured.
- **Analytic short-circuit.** A combined search returns the empty page with both coverage blocks, reading no candidate batch, when the pinned scope has no evaluable revision, analytics is disabled, or the pinned coverage counts zero evaluated runs.
- **Trigger lock.** Migration `20261016120000_LockTrackForPlateTextTrackStart` reads the Track row `FOR SHARE` in the start derivation (ADR-018 item 2).

### Query set v2 (frozen before measuring)

`mavi-plate-search-skewed-queries-v2`, SHA-256 `b2d7d728a4ae23f5241864e55aa56a5a8a17f558c303941bdb06d09f6b0e92fa`. It was committed in `105b1dca` before any v2 timing existed. v1 is unchanged and pinned (SHA-256 `93bcebaabd402917fc44f946dc18714f8c0d0e9744e26016610c0ff6da7fee98`). `TheFrozenQuerySetsArePinned` checks both hashes without a database.

The corpus is unchanged. Every Track in it has mean confidence 0.8, duration 4 000 ms and no subclass. So the meaningful selective thresholds are reject-all ones (0.95, 4 001 ms, `car`), with 0.8 as the inclusive boundary that admits every Track. The budget (300 ms p95), the samples (3 warm-ups, 20 samples), the mode and the host are unchanged, and every v2 query is budgeted.

| Id | Query |
|---|---|
| V01 | contains `KA0`, `toUtc` day 1 (historical: the oldest 3 %) |
| V02 | contains `KA0`, `toUtc` day 15 (historical: the older half) |
| V03 | contains `KA01`, `toUtc` day 1 (historical, selective) |
| V04 | contains `KA0`, `minimumConfidence` 0.95 (rejects every Track) |
| V05 | contains `KA0`, `minimumConfidence` 0.8 (inclusive boundary, admits every Track) |
| V06 | contains `KA0`, `minimumDurationMs` 4 001 (rejects every Track) |
| V07 | contains `KA0`, `objectSubclass` `car` (rejects every Track) |
| V08 | contains `KA0`, `fromUtc` day 29 (lower bound only) |
| V09 | contains `KA0`, `toUtc` day 15, page 2 |
| V10 | contains `KA0` + camera 1 + loitering (camera never configured; the analytic short-circuit) |

### Method

- Release build of `112299ab`. Each run's head file records the docs-only working-tree changes of this record.
- Scale database `mavi_perf_skewed` (cluster on port 5499, PostgreSQL 18.6). It is in the state left by the 2026-10-15 measurement: after the 10^6 backfill and `VACUUM FULL plate_track_texts`. The harness's `MigrateAsync` applied the lock migration (1.6–2.3 s; drift 0).
- The same quiet gate as 2026-10-15:

| Run | START (local) | CPU at START | In-run samples | Non-quiet | Valid |
|---|---|---|---|---|---|
| run1 | 00:51:57 | 18.6 % | 5 | 0 | yes |
| run2 | 00:56:13 | 17.1 % | 4 | 0 | yes |

### Results (ms, p50 / p95; Development host, warm; corrected head `112299ab`)

**v1 (unchanged criterion).** Every budgeted query is within 300 ms in both runs.

| Query | Rows | run1 | run2 | 2026-10-15 run1 p95 |
|---|---|---|---|---|
| Q01 contains `KA0` | 51 | 118.0 / **196.3** | 95.0 / 148.1 | 150.3 |
| Q02 prefix `KA0` | 51 | 93.9 / 102.6 | 101.6 / 140.0 | 120.9 |
| Q03 contains `KA01` | 51 | 31.4 / 41.8 | 29.7 / 32.0 | 38.0 |
| Q04 prefix `KA01` | 51 | 37.4 / 46.6 | 36.0 / 37.9 | 39.0 |
| Q05 contains `1234` | 51 | 24.2 / 29.4 | 17.8 / 21.8 | 19.9 |
| Q06 exact | 1 | 15.4 / 17.9 | 13.3 / 14.7 | 14.5 |
| Q07 no match | 0 | 12.6 / 16.7 | 9.7 / 11.2 | 12.9 |
| Q08 + `processingRunId` | 51 | 68.8 / 106.4 | 62.9 / 73.1 | 69.1 |
| Q09 page 2 | 51 | 93.3 / 106.0 | 83.9 / 91.7 | 87.4 |
| Q10 page 5 | 51 | 75.8 / 82.5 | 78.5 / 81.4 | 84.4 |
| Q11 contains `MH12` | 51 | 19.9 / 22.6 | 20.7 / 22.5 | 26.7 |
| Q12 + one-day window | 51 | 54.5 / 58.1 | 55.3 / 57.2 | 49.7 |
| Q13 NotConfigured | 0 | 2.1 / 2.7 | 2.3 / 2.7 | 2.8 |
| Q14 no run Ready | 0 | 6.0 / 7.1 | 5.9 / 7.0 | 7.3 |
| S1 stress probe (outside the bound) | 51 | 26.4 / 27.4 | 28.5 / 29.0 | 31.2 |

**v2. NOT MET.** V04, V05 and V06 miss the budget in both runs, and V02 misses it in run1.

| Query | Rows | run1 | run2 | Budget |
|---|---|---|---|---|
| V01 `toUtc` day 1 | 51 | 56.7 / 60.1 | 56.3 / 59.7 | met |
| V02 `toUtc` day 15 | 51 | 263.7 / **350.4** | 229.8 / 251.1 | **missed in run1** |
| V03 `KA01`, `toUtc` day 1 | 51 | 38.2 / 51.0 | 35.8 / 39.3 | met |
| V04 `minimumConfidence` 0.95 | 0 | 313.9 / **404.1** | 298.7 / **327.6** | **missed** |
| V05 `minimumConfidence` 0.8 | 51 | 355.3 / **488.4** | 348.2 / **362.9** | **missed** |
| V06 `minimumDurationMs` 4 001 | 0 | 298.9 / **362.9** | 313.7 / **348.1** | **missed** |
| V07 `objectSubclass` `car` | 0 | 81.1 / 92.8 | 82.8 / 86.8 | met |
| V08 `fromUtc` day 29 | 51 | 108.6 / 128.3 | 99.7 / 105.5 | met |
| V09 `toUtc` day 15, page 2 | 51 | 55.3 / 63.0 | 52.5 / 56.7 | met |
| V10 analytic, unconfigured camera | 0 | 174.9 / 206.4 | 182.0 / 225.4 | met (shape failure below) |

- **Cold first call** (Q01, first search of the process): 1 479 ms and 1 391 ms (see the limits below).
- **Coverage** is identical to the 2026-10-15 run for every v1 query.

### Where the v2 time goes (run1 plans; `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` of the real statements)

| Query | Plate coverage count (first page) | Candidate statement |
|---|---|---|
| V02 | **251 ms**, sequential scan of `tracks` (500 k Tracks counted) | 48 ms |
| V04 | **110 ms**, sequential scan of `tracks` | **196 ms**: PK probe of all 62 056 matches, none kept |
| V05 | **318 ms**, sequential scan of `tracks` | 84 ms: 256 PK probes, then LIMIT |
| V06 | **120 ms**, sequential scan of `tracks` | **196 ms**: as V04 |
| V10 | — | none (short-circuit); the analytics coverage's `SELECT DISTINCT` run list over camera 1 is 288 ms, with a sequential scan of `tracks` |

- **The candidate read is no longer the repeated-batch cost.** Every v2 first page reads one candidate batch. A filter that keeps most matches costs about a batch of probes (V05: 84 ms). The worst candidate statement is a reject-all filter on an unindexed Track column, which probes every match: 196 ms for 62 k matches. That is bounded by the matching texts, not by the page.
- **The dominant remaining cost is the first page's plate coverage.** With a Track-level filter, `ComputePlateCoverageAsync` counts the scope's Vehicle Tracks per run under that filter (`VehicleTrackCounts`). For `minimumConfidence`, `minimumDurationMs`, and an upper time bound that admits half the Tracks, no index serves the count, so it scans 10^6 Tracks (110–318 ms). Q12 and V08 do not, because ADR-019's (b) index serves a recent lower bound.
- **Shape assertions** (frozen with v2: no sequential scan of a 10^6-row relation) fail for:
  - V02, V04, V05 and V06, all in the coverage count;
  - V10, in the analytics coverage.

### Verdict and stop

- **v1:** within its unchanged criterion on the corrected head.
- **v2:** **NOT MET.** The exact-prefilter correction removed the repeated-batch mechanism. V01, V03 and V07–V09 are now 39–128 ms, against the reviewer's 0.5 s class.
- **Why v2 still misses:**
  - V04–V06 and V02 still miss, by up to 1.6×. The miss comes mainly from the filtered coverage count, which owner decision 2 did not address.
  - It also comes from the reject-all probe of every match.
- **Stopped.** Per the owner's stop condition, no further optimisation architecture was started.
- **Open for owner decision:**
  - a supporting index or other bound for the filtered coverage count;
  - for confidence and duration, a denormalised or indexed path;
  - declaring these filter classes outside plan §2.8.

### CI (owner decision 1)

The plate search at scale now runs in its own informational workflow, `plate-search-scale-informational.yml`:

- It is not a Quality Gate lane, not in `quality.needs` and not a required check.
- Its checkout is verified against the exact head.
- Its artifact is `plate-search-scale-informational-ci-diagnostic`, outside `qualification-evidence/`.
- Its files are `plate-search-scale-ci-diagnostic{.json,-plans.txt}`. They state `qualificationEvidence: false` and carry only the 3 000 ms catastrophic bound, never the 300 ms budget.

**Nothing from that workflow is Development or qualification evidence.** The CI JSON previously published with `budgetMilliseconds: 300` under the same file names as the Development run (P2-3) can no longer be produced.

### Recorded limits of this round

- **Cold first call.** The first search of a process takes about 1.2–1.5 s (1 156–1 264 ms on 2026-10-15; 1 391–1 479 ms here). It includes building the EF model, opening the first connection and counting the 1 000 runs' Vehicle Tracks into an empty process cache. No requirement makes cold-start latency blocking, so no IIS or application-pool warm-up was added.
- **p95 of 20 samples** is the 19th-ranked sample. One slow sample moves it, as Q01 run1 (196 ms) against run2 (148 ms) and V02 (350 ms against 251 ms) show. Two runs are reported, not more.
- **Timing boundary.** The time is that of the repository call (`SearchPlatesAsync`: transaction, barrier, coverage, page and explanation) in-process. It excludes HTTP, authentication, serialisation and the client.
- **Database condition.** The scale database was last compacted with `VACUUM FULL plate_track_texts` (2026-10-15), and the cache was warm. A production database without that step carries the backfill's dead row versions until autovacuum.
- **Not re-measured in this round:**
  - the write cost of the trigger's new `FOR SHARE` row lock on PR-3's completion;
  - the CI diagnostic (it runs when the branch is pushed).
- **One host, one corpus.** The v2 thresholds are reject-all or admit-all because the corpus has no confidence, duration or subclass variation. Intermediate selectivities lie between those measured.
- **Raw output, outside Git:**
  - `E:\MAVI-Working\tmp\corr-run{1,2}.txt`, with `.quiet.txt` and `.head.txt` beside each;
  - `E:\MAVI-Working\tmp\corr-run{1,2}\plate-search-scale{.json,-plans.txt}`;
  - the quietness log, `E:\MAVI-Working\tmp\corr-quiet.txt`.

**Updated 2026-10-15:** re-measured on the candidate head of ADR-018/ADR-019 (budget met); the 2026-10-14 walk-design record follows as superseded evidence.

**Kind.** Development evidence record (engineering measurement, plan §2.8 and register rows P10–P11). It is not a qualification, a scale qualification or a CI gate.

**Verdict on the candidate head `ff4ac4ef` (2026-10-15; ADR-018 (c2), ADR-019 (b) and (d)).** The plan §2.8 budget, p95 ≤ 300 ms, is **MET** on every budgeted query (Q01–Q14), in three quiet runs. *[Scope note added 2026-10-16: this verdict is for the frozen query set v1 only; see the correction round above for the filter classes v1 did not measure and for v2.]* The worst budgeted p95 is 150.3 ms (Q01). The declared stress probe S1 is 31–34 ms, against about 63 s for the walk. The corpus, the query set, the sample counts and the budget are the frozen ones (`b9cb50eb`), unchanged. The owner chose the design from the options packet (2026-10-14) before this measurement, and nothing was tuned after it.

The 2026-10-14 verdict below, NOT MET, describes the superseded walk design (`23dc85d5`). It is kept as superseded evidence.

## Re-measurement on the candidate head (2026-10-15)

### What changed (owner decision 2026-10-15: (c2)+(b)+(d), not (a2))

- **(c2), ADR-018:** a page reads candidate texts in page order by `plate_track_texts.track_start_timestamp_utc`, a trigger-maintained copy of the Track's start time, through a materialised text match. The base chain still decides membership, order and keyset over `tracks`.
- **(b), ADR-019:** `ix_tracks_object_class_end_timestamp_utc`.
- **(d), ADR-019:** `SET LOCAL max_parallel_workers_per_gather = 0` inside each plate search's transaction.

### Method

- The harness, corpus, query set, samples (3 warm-ups and 20 samples; S1 1 and 5), mode (`development`) and host are those of the frozen measurement.
- Release build of `ff4ac4ef`, with a clean tree recorded per run.
- The scale database `mavi_perf_skewed` was first returned to the `23dc85d5` schema: the prototype column, trigger and (b) index were dropped, then `VACUUM FULL`.
- **Run m0 (migration run; timings not used as evidence).** The harness's own `MigrateAsync` applied the two new migrations to the populated 10^6 corpus:
  - 45.3 s, including the backfill of 10^6 texts and the (b) index build;
  - drift check 0 rows.
- `VACUUM FULL plate_track_texts; ANALYZE plate_track_texts; ANALYZE tracks;` followed (7.9 s), as in the options packet. This reclaims the backfill's dead row versions; a production upgrade leaves that to autovacuum or to the `VACUUM (ANALYZE)` that ADR-018 recommends.
- **Runs 1–3**, each gated by the quiet-host check, with in-run samples:
  - The gate requires no foreign test, browser-automation or `dotnet test` process active (more than 0.25 s CPU in 5 s) and total CPU below 20 %.
  - In-run samples count foreign activity only.
  - A run is valid only if its START is quiet and it has no non-quiet in-run sample.
- Every run asserted:
  - the budget;
  - zero denormalisation drift;
  - no sequential scan of a 10^6-row relation in the EXPLAINed queries;
  - the trigram index on Q07 and Q11.

  Since ADR-018, the plan capture includes the `WITH` candidate statement and replays each statement with the search's own `SET LOCAL`.

### Quietness record

| Run | START (local) | CPU at START | In-run samples | Non-quiet | Valid |
|---|---|---|---|---|---|
| m0 (migration) | 05:42:59 | 15.6 % | 2 | 0 | (not evidence) |
| run1 | 05:44:32 | 18.8 % | 1 | 0 | yes |
| run2 | 05:45:40 | 17.5 % | 2 | 0 | yes |
| run3 | 05:56:09 | 19.6 % | 2 | 0 | yes |

### Results (ms; p50 / p95 per run; Development host, warm)

| Query | Rows | Statements | run1 | run2 | run3 | packet c2+b+d p95 | frozen walk p95 |
|---|---|---|---|---|---|---|---|
| Q01 contains `KA0` | 51 | 6 | 102.2 / **150.3** | 99.5 / 123.9 | 99.6 / 133.6 | 154.0 | 497.8 |
| Q02 prefix `KA0` | 51 | 6 | 97.6 / 120.9 | 99.1 / 114.4 | 105.3 / 117.5 | 123.3 | 374.1 |
| Q03 contains `KA01` | 51 | 6 | 32.6 / 38.0 | 32.0 / 34.6 | 31.9 / 38.0 | 48.1 | 988.6 |
| Q04 prefix `KA01` | 51 | 6 | 34.9 / 39.0 | 37.1 / 43.0 | 36.6 / 42.3 | 43.5 | 841.9 |
| Q05 contains `1234` | 51 | 6 | 17.7 / 19.9 | 18.9 / 21.2 | 18.0 / 20.1 | 22.2 | 48.2 |
| Q06 exact (the newest Ready Track's text) | 1 | 6 | 13.5 / 14.5 | 12.9 / 15.2 | 14.1 / 15.9 | 15.1 | 49.7 |
| Q07 contains `ZZ99ZZ` (no match) | 0 | 4 | 10.5 / 12.9 | 10.9 / 12.1 | 9.7 / 11.2 | 12.3 | 31.1 |
| Q08 contains `KA0` + `processingRunId` | 51 | 6 | 64.0 / 69.1 | 67.0 / 77.1 | 66.7 / 76.2 | 80.9 | 33.0 |
| Q09 contains `KA0`, page 2 | 51 | 4 | 79.3 / 87.4 | 85.8 / 95.5 | 88.9 / 101.5 | 95.7 | 48.7 |
| Q10 contains `KA0`, page 5 | 51 | 4 | 80.0 / 84.4 | 79.7 / 83.4 | 83.1 / 92.2 | 121.0 | 62.1 |
| Q11 contains `MH12` | 51 | 6 | 21.2 / 26.7 | 20.8 / 22.1 | 21.2 / 22.7 | 38.1 | 51.7 |
| Q12 contains `KA01` + one-day window | 51 | 7 | 42.0 / 49.7 | 43.4 / 46.0 | 45.2 / 49.0 | 80.3 | 1 270.3 |
| Q13 contains `KA01`, NotConfigured | 0 | 1 | 2.2 / 2.8 | 2.4 / 3.6 | 2.5 / 3.5 | 4.3 | 5.7 |
| Q14 contains `KA01`, no run Ready | 0 | 3 | 6.1 / 7.3 | 7.1 / 8.5 | 7.0 / 8.9 | 8.0 | 18.1 |
| S1 prefix `XQ0` (stress probe, outside the bound) | 51 | 6 | 28.2 / 31.2 | 28.9 / 34.1 | 29.8 / 32.0 | 33.1 | 63 644.4 |

- Worst budgeted p95 by run: 150.3, 123.9 and 133.6 ms.
- Cold first call: 1 156–1 264 ms. On the frozen run it was 13 792 ms, measured just after seeding, so the two are not comparable.
- **Coverage** was identical to the frozen run in every row (Ready 900 000 / Stale 100 000; window 29 335 / 4 000 of 33 335; and so on).

### Plans (run1; `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)` of the real statements)

- **Q01, contains `KA0`: the candidate statement, 86 ms.**
  - Bitmap Index Scan on `ix_plate_track_texts_normalised_text_trgm`, 69 051 rows, then Bitmap Heap Scan into the materialised CTE.
  - Hash Join to the 900 visible analyses (sequential scan of `plate_analyses`, 1 000 rows), giving 62 056 rows.
  - Top-N heapsort, LIMIT 256.
  - The CTE spills 4 MB to temp.
- **Q02, prefix `KA0`.** The planner chose the trigram index over the pattern b-tree; the shape is the same as Q01, 78 ms.
- **Q07 and Q11.** A trigram bitmap of 1 and 974 rows, under 4 ms.
- **Q08, run-scoped.** The trigram bitmap (69 k rows) is joined to the single analysis through `ux_plate_analyses_identity`, 57 ms. The run scope does not narrow the text match, which is why Q08–Q10 are slower than under the walk. They remain within the budget.
- **Q12, the windowed coverage count: Index Scan using `ix_tracks_object_class_end_timestamp_utc`**, Index Cond `object_class = 'Vehicle' AND end_timestamp_utc >= fromUtc`, 33 335 rows, 17 ms. In the frozen plan this was a parallel sequential scan of 10^6 Tracks taking 176 ms. This plan is the evidence that (b) is used (ADR-019).
- **Restricted pages.** Each is a bitmap over the candidate Track ids. No warm statement scans `tracks`, `plate_track_texts`, `plate_track_outcomes`, `plate_observations` or `observations` sequentially.

### Write cost on PR-3's completion (interleaved, quiet, 10 000 Tracks × 4 crops)

The opt-in `PlateCompletionTimingTests` was run with `MAVI_PLATE_TIMING_TRACKS=10000` (Debug builds, isolated databases). Each run was gated as above, with 2 of 2 in-run samples quiet.

| Round | Base `23dc85d5`: completion / publication rows | Candidate `ff4ac4ef` (trigger + (b) index): completion / publication rows |
|---|---|---|
| 1 | 10 890 / 6 941 ms | 10 108 / 6 532 ms |
| 2 | 9 927 / 6 233 ms | 9 699 / 6 024 ms |
| 3 | 9 255 / 5 343 ms | 9 819 / 6 160 ms |
| mean | 10 024 / 6 172 ms | 9 875 / 6 239 ms |

- **Derived:** the trigger's cost is within run-to-run noise (mean row writes +67 ms, ≈ 1 %). Completion stays ≤ 10.9 s against the 15 s budget.
- The candidate's run also asserted that every text written by PR-3's `COPY` had the trigger-derived Track start (zero drift).
- The (b) index costs Track inserts, which this measurement does not exercise (ADR-019).

### Recorded limits of the re-measurement

- One host, one corpus, warm cache, after `VACUUM FULL`.
- Run1 had a single in-run quietness sample. Its START was quiet, and runs 2 and 3 agree within ±25 ms.
- The S1-like case of a window far in the past under a common text is not in the frozen query set. Under ADR-018 its cost is bounded by the matching texts newer than the window: several batches of about 100 ms each. It is not measured. *[2026-10-16: measured as v2 V01–V03 and V09 after the predicates were pushed; see above.]*
- Raw output, kept outside Git:
  - `E:\MAVI-Working\tmp\c2bd-cand-{m0,run1,run2,run3}.txt`, with `.quiet.txt` and `.head.txt` beside each;
  - `E:\MAVI-Working\tmp\c2bd-cand-run*\plate-search-scale{.json,-plans.txt}`;
  - `E:\MAVI-Working\tmp\c2wc-{base,cand}-{1,2,3}.txt`;
  - the quietness log, `E:\MAVI-Working\tmp\c2-quiet.txt`.

## Superseded: the frozen walk design (`23dc85d5`, 2026-10-14)

**Verdict of the walk design on the frozen skewed set (2026-10-14; superseded by the re-measurement above).** The plan §2.8 budget, p95 ≤ 300 ms, is **NOT MET**. It is missed by 5 of the 14 budgeted queries, and the declared stress probe takes about 63 s. The search was not tuned after these timings were read; see *What would change the result*.

## Questions (frozen before results were read)

1. Does a plate search meet the plan's budget of **p95 ≤ 300 ms** over 10^6 Vehicle Tracks and 10^6 `plate_track_texts` rows? The search covers the first page, run-scoped pages, time-windowed pages and continuation pages, and the corpus is skewed in the way real Indian plates are.
2. What do the two new indexes cost PR-3's synchronous completion at its 10 000-Track worst shape (budget 15 s)?

## Method

### Search: the frozen skewed set (cold review P1-1/P1-2)

The corpus, the query set, the sample counts and both bounds were committed in `b9cb50eb` before anything was measured on them. The test is `PlateSearchScaleMeasurementTests`, and its remarks are the normative definition.

- **Corpus `mavi-plate-search-skewed-v1`:**
  - 10 cameras × 100 videos. Each video has one completed, visible run of 1 000 Vehicle Tracks, so there are 10^6 Tracks over 30 days, and newer runs hold newer Tracks.
  - Each Track has one Read plate and one Track text.
  - State codes in runs 21–1 000: `KA` 70 %, `MH` 10 %, and 34 other codes sharing 20 %.
  - The oldest 20 runs (2 % of Tracks) are all `XQ0`*d*.
  - District, series and number are hash-uniform.
  - Every tenth run's only analysis is of an older identity. For the measured identity, 900 runs are Ready and 100 are not, and the newest run is not Ready.
- **Query set `mavi-plate-search-queries-v1`** (15 queries; results below).
- **Measurement:**
  - The real repository call `TrackSearchRepository.SearchPlatesAsync`: barrier, snapshot, coverage, page and explanation.
  - Wall time per call: 3 warm-ups, then 20 samples; the stress probe takes 1 warm-up and 5 samples.
  - The first call of the process is reported separately, with empty process caches.
  - A warm call of Q01, Q02, Q07, Q08, Q11 and Q12 is captured, and every one of its statements is replayed under `EXPLAIN (ANALYZE, BUFFERS, VERBOSE)`.
  - Shape assertions: no sequential scan of a 10^6-row relation, and the trigram index on the sparse path.
- **Modes:**
  - `development` asserts the 300 ms budget. It is the authority, run on the host below.
  - `ci` asserts a catastrophic bound of 3 000 ms (10× the budget) plus the same shape assertions. This bound is justified in the test's remarks: a shared runner with PostgreSQL's default 128 MB buffers against a ≈ 1 GB corpus, where an order-of-magnitude margin still catches a change of complexity class.
  - The CI job `plate search at scale (informational)` in `quality-gate.yml` is not a `quality` lane. It runs when the branch is pushed; **it has not run yet** (local-only remediation).
- **Database:** the scratch PostgreSQL 18.6 cluster on `E:` (port 5499), database `mavi_perf_skewed`. Seeding took 1 161 s, followed by `VACUUM ANALYZE`.
- **Host:** Development laptop: Intel Core i7-10750H, 15.8 GiB RAM, Windows 11, .NET SDK 10.0.401, Release build.

### Completion (unchanged)

PR-3's own opt-in test, unchanged:

```
MAVI_PLATE_TIMING_TRACKS=10000 dotnet test … --filter FullyQualifiedName~PlateCompletionTiming
```

It was run on this branch and on the PR-3 head (`0125afeb`, separate worktree), **interleaved**, on the same database.

## Results

### 1. Plate search on the frozen skewed set (ms, Development host, warm)

| Query | Rows | Statements | p50 | p95 | max | Budget |
|---|---|---|---|---|---|---|
| Q01 contains `KA0` (broad, 3 characters) | 51 | 12 | 381.7 | **497.8** | 566.7 | **missed** |
| Q02 prefix `KA0` (broad, 3 characters) | 51 | 12 | 351.7 | **374.1** | 388.0 | **missed** |
| Q03 contains `KA01` | 51 | 21 | 785.8 | **988.6** | 1 098.6 | **missed** |
| Q04 prefix `KA01` | 51 | 21 | 715.6 | **841.9** | 984.8 | **missed** |
| Q05 contains `1234` | 51 | 8 | 32.8 | 48.2 | 48.6 | met |
| Q06 exact (the newest Ready Track's text) | 1 | 8 | 28.3 | 49.7 | 59.9 | met |
| Q07 contains `ZZ99ZZ` (no match) | 0 | 6 | 21.1 | 31.1 | 31.7 | met |
| Q08 contains `KA0` + `processingRunId` | 51 | 9 | 30.9 | 33.0 | 35.9 | met |
| Q09 contains `KA0`, page 2 | 51 | 7 | 33.8 | 48.7 | 49.5 | met |
| Q10 contains `KA0`, page 5 | 51 | 10 | 54.9 | 62.1 | 64.1 | met |
| Q11 contains `MH12` | 51 | 8 | 43.6 | 51.7 | 52.9 | met |
| Q12 contains `KA01` + one-day window | 51 | 22 | 929.9 | **1 270.3** | 1 282.6 | **missed** |
| Q13 contains `KA01`, NotConfigured | 0 | 1 | 2.7 | 5.7 | 6.4 | met |
| Q14 contains `KA01`, no run Ready | 0 | 6 | 16.5 | 18.1 | 18.7 | met |
| S1 prefix `XQ0` (declared stress probe) | 51 | 492 | 62 911.9 | **63 644.4** | 63 644.4 | outside the bound by declaration; reported as a failure of the design |

**Cold first call** (the first search of the process, Q01): **13 791.6 ms**. It includes building the EF model, opening the first connection and counting the Vehicle Tracks of 1 000 runs into an empty process cache, on a cluster that had just been seeded. It was not decomposed further.

**Coverage** was correct in every row:
- Ready 900 000 and Stale 100 000 of 1 000 000;
- `processingRunId`: 1 000 of 1 000;
- the window: 29 335 Ready and 4 000 Stale of 33 335;
- NotConfigured: 1 000 000;
- no run Ready: 1 000 000 Stale.

**Shape assertions:**
- The sparse path read `ix_plate_track_texts_normalised_text_trgm` (Q07, Q11).
- No warm statement scanned `tracks`, `plate_track_texts`, `plate_track_outcomes`, `plate_observations` or `observations` sequentially, **except Q12**. There, the windowed coverage count is a parallel sequential scan of `tracks` (176 ms in its plan).

### Why it misses (direct mechanism trace from the plans)

1. **The density probe is fooled by a non-Ready newest run (Q01–Q04).**
   - The first walk batch (256 Tracks) lies in the newest run, which is not Ready for the identity, so it holds no match.
   - The search therefore takes the sparse path.
   - The sparse statement is `SELECT DISTINCT track_id … LIMIT 4097`. Its `LIMIT` sits above a sort of every in-scope match, so it is not bounded by the cap: for `KA0` it joined 62 056 matches before the `LIMIT`, in 209 ms.
   - Over the cap, the walk then resumes.
   - The cap bounds the ids returned, not the work done.
2. **The walk at moderate density (Q03, Q04).** `KA01` is about 0.7 % of Tracks. After the wasted sparse statement, 50 matches need about 7 000 Tracks of walk: batches 256 to 4 096, 21 statements in all.
3. **The windowed coverage (Q12).**
   - With a Track-level filter, coverage counts Tracks per run over every run in scope; the run scope is not narrowed by the window.
   - This is a sequential scan of 10^6 Tracks, in addition to the walk of (2).
4. **The stress probe (S1).** A text dense only in the oldest 2 % has more in-scope matches than the cap, so the walk reads about 98 % of the scope: 492 statements, about 63 s. This was declared before measuring as the walk's worst case. Its cost grows with the scope, so the walk alone gives no installation-size bound.

### What would change the result (not done; owner decision)

None of these was applied, because each would be a change of design after reading the timings. Each needs its own frozen re-measurement on this corpus and query set.

- (a) A density probe that ignores runs that are not Ready, plus a sparse statement whose work is bounded by the cap (a `LIMIT` applied before de-duplication, since a Track may hold several texts).
- (b) Narrowing the coverage run scope by the time window before counting.
- (c) For the S1 class: a design whose cost is bounded by the page rather than by the scope. One candidate is denormalising the Track's sort key into `plate_track_texts` (with a migration and an ADR). Others are a product rule requiring a scope or window for texts that are broad in scope, or a different budget for such texts.

### Superseded: the first measurement (uniform corpus, previous design)

The 2026-10-13 run used a uniform corpus (36 state codes, every run Ready, six queries). The design then resolved every matching id of the installation before paging, and gave p95 ≤ 76 ms.

That corpus did not exercise skew, readiness mix, windows or continuation. The cold review (P1-1) showed that design is unbounded on skewed data, and it was replaced. **That figure no longer describes the code and is not evidence for the budget.**

### 2. Index write cost on PR-3's completion

The worst shape: 10 000 Tracks × 4 crops, giving 40 000 Track texts of up to 32 characters.

| Run (interleaved) | Completion wall | Phase C row writes |
|---|---|---|
| PR-4 run 4 | 9 258 ms | 5 345 ms |
| PR-3 run 4 | 8 509 ms | 4 701 ms |
| PR-4 run 5 | 8 672 ms | 5 026 ms |
| PR-3 run 5 | 8 137 ms | 4 574 ms |

Derived: at the worst shape, the two indexes add ≈ 0.45–0.65 s to Phase C (≈ +10–14 %). Completion stays ≤ 9.3 s against the 15 s budget.

Three earlier PR-4 runs (11.4–12.1 s) were not interleaved and were taken straight after a build. They are superseded by the interleaved pairs and are kept here as a disclosed confounded measurement, not as evidence.

## Decision

- **Search budget:** not met. The plan §2.8 budget holds on this host only for:
  - selective and digit texts;
  - exact match;
  - no match;
  - run-scoped pages;
  - continuation pages;
  - NotConfigured or no-run-Ready searches.

  It does not hold for:
  - broad 3–4 character state-code texts in an installation-wide scope;
  - a windowed search;
  - a text dense only in old data.

  This is reported for an owner decision (options (a)–(c)), not resolved here.
- **Indexes:** the GIN trigram index (contains) and the `text_pattern_ops` b-tree (prefix and exact) are kept. Their write cost is within PR-3's budget.

## Recorded limits

- One synthetic corpus, one laptop, warm cache. Not CI, not a Production host profile.
- The CI measurement is prepared but has not run.
- GIN pending-list behaviour: bulk completions fill the pending list until vacuum, and the measurement ran after `VACUUM ANALYZE`.
- Raw output is kept outside Git:
  - `E:\MAVI-Working\tmp\pr4-skewed-dev-run1.txt`;
  - `E:\MAVI-Working\tmp\pr4-skewed-dev-run1\plate-search-scale.json` and `plate-search-scale-plans.txt` (every plan);
  - the first measurement in `E:\MAVI-Working\tmp\pr4-scale-run{1,2,3}.txt` and `pr4-ab-*-run{4,5}.txt`.
