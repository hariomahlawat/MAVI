# Stage 4 PR-4: plate search at 10^6 Tracks, and the index write cost

**Updated 2026-10-15:** re-measured on the candidate head of ADR-018/ADR-019 (budget met); the 2026-10-14 walk-design record follows as superseded evidence.

**Kind.** Development evidence record (engineering measurement, plan §2.8 and register rows P10–P11). It is not a qualification, a scale qualification or a CI gate.

**Verdict on the candidate head `ff4ac4ef` (2026-10-15; ADR-018 (c2), ADR-019 (b) and (d)).** The plan §2.8 budget, p95 ≤ 300 ms, is **MET** on every budgeted query (Q01–Q14), in three quiet runs. The worst budgeted p95 is 150.3 ms (Q01). The declared stress probe S1 is 31–34 ms, against about 63 s for the walk. The corpus, the query set, the sample counts and the budget are the frozen ones (`b9cb50eb`), unchanged. The owner chose the design from the options packet (2026-10-14) before this measurement, and nothing was tuned after it.

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
- The S1-like case of a window far in the past under a common text is not in the frozen query set. Under ADR-018 its cost is bounded by the matching texts newer than the window: several batches of about 100 ms each. It is not measured.
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
