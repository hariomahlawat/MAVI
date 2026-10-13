# Stage 4 PR-4: plate search at 10^6 Tracks, and the index write cost

**Kind.** Development evidence record (engineering measurement, plan §2.8 and register rows P10–P11). It is not a qualification, a scale qualification or a CI gate.

## Questions (frozen before results were read)

1. Does the **first page** of a plate-only search (`GET /api/tracks?plateText=…`, limit 50) meet the plan's budget of **p95 ≤ 300 ms** over 10^6 Vehicle Tracks and 10^6 `plate_track_texts` rows?
2. What do the two new indexes cost PR-3's synchronous completion at its 10 000-Track worst shape (budget 15 s)?

## Method

**Search.** `MAVI_PLATE_SEARCH_SCALE_DB=<scratch database> dotnet test tests/Mavi.IntegrationTests --filter FullyQualifiedName~PlateSearchScaleMeasurement` (`PlateSearchScaleMeasurementTests`).

- Measures `TrackSearchRepository.SearchPlatesAsync` — the real first page: shared visibility barrier, snapshot, plate coverage, the page and its explanation — wall time per call, 3 warm-ups then 20 samples per query, warm cache.
- Corpus (synthetic, deterministic, seeded once by SQL): 10 cameras × 100 videos, one completed visible run of 1 000 Vehicle Tracks per video over 30 days (10^6 Tracks), one Read plate and one Indian-standard-format Track text per Track, one completed analysis of the identity per run (every run Ready). `VACUUM ANALYZE` after seeding.
- Frozen queries: `contains KA0` (broad), `contains KA01`, `contains 1234`, `prefix MH12`, `exact` (an existing text), `contains ZZ99ZZ` (no match). `EXPLAIN (ANALYZE, BUFFERS)` of every statement for `KA01` and `ZZ99ZZ` is printed by the test.
- Database: a scratch PostgreSQL 18.6 cluster on `E:` (`initdb`, port 5499, `shared_buffers=512MB`), so the 10^6 corpus never touched the shared test database.

**Completion.** PR-3's own opt-in test, unchanged: `MAVI_PLATE_TIMING_TRACKS=10000 dotnet test … --filter FullyQualifiedName~PlateCompletionTiming`, run on this branch and on the PR-3 head (`0125afeb`, separate worktree) **interleaved** on the same database.

**Host.** Development laptop: Intel Core i7-10750H, 15.8 GiB RAM, Windows 11, .NET SDK 10.0.401, PostgreSQL 18.6 on localhost.

## Results

### 1. First page at 10^6 (ms)

| Query | Rows on page | First design p50 / p95 | **Final p50 / p95** |
|---|---|---|---|
| contains `KA0` | 51 | 897.5 / 956.7 | **58.3 / 75.9** |
| contains `KA01` | 51 | 785.3 / 849.1 | **35.4 / 45.8** |
| contains `1234` | 51 | 737.7 / 793.4 | **25.9 / 35.8** |
| prefix `MH12` | 51 | 700.3 / 732.5 | **35.9 / 48.6** |
| exact | 1 | 709.0 / 904.2 | **18.2 / 21.0** |
| contains `ZZ99ZZ` (no match) | 0 | 354.2 / 393.3 | **11.2 / 13.9** |

**The first design missed the budget (observed), and the plans say why (direct mechanism trace):**

- *Coverage* counted the scope through the base candidate chain — every Track joined to its run, video and camera, plus the per-Track latest-run anti-join — 435 ms for 10^6 Tracks on its own.
- *The page*: the plate predicate as a correlated EXISTS (and, tried next, as an `IN` subquery) beside the base chain gave the query more relations than PostgreSQL's join-collapse limit, and the planner joined the whole chain (a sequential scan of 10^6 Tracks) before semi-joining the 279 matching texts, which the trigram index found in 0.5 ms — 450 ms to 1 s.

**Changes (no contract change):**

- The predicate is two statements: the matching Track ids from the text index → analysis → the Track's own run (≈ 4 ms), then the chain with `id = ANY(@ids)` (≈ 5 ms, primary-key probes).
- Coverage reads the runs in scope (1 000 rows) and their analyses, classifies each run, and takes a Ready run's Vehicle Track count from its pinned analysis header — PR-3's completion writes exactly one outcome per Vehicle Track — unless a Track-level filter (time window, duration, confidence, subclass) is present; other runs are counted from `tracks`. `TheCoverageCountEqualsTheBaseChainForEveryFilter` pins the decomposed scope to the base chain.
- Statement count per first page: runs, analyses, [Track counts when needed], matching ids, page, explanation — constant in page size (`APageCostsTheSameStatementsForTwoRowsOrTwenty`).

**Index use (observed in the plans):** contains → `Bitmap Index Scan on ix_plate_track_texts_normalised_text_trgm`; the explanation probes `ux_plate_analyses_identity` and `PK_tracks`. `EachPredicateShapeIsServedByItsIndex` pins, at default planner settings over 200 000 rows, contains → the GIN trigram index and prefix/exact → the `text_pattern_ops` b-tree.

### 2. Index write cost on PR-3's completion (10 000 Tracks × 4 crops, worst shape: 40 000 Track texts of up to 32 characters)

| Run (interleaved) | Completion wall | Phase C row writes |
|---|---|---|
| PR-4 run 4 | 9 258 ms | 5 345 ms |
| PR-3 run 4 | 8 509 ms | 4 701 ms |
| PR-4 run 5 | 8 672 ms | 5 026 ms |
| PR-3 run 5 | 8 137 ms | 4 574 ms |

Derived: the two indexes add ≈ 0.45–0.65 s to Phase C (≈ +10–14 %) at the worst shape; the completion stays ≤ 9.3 s against the 15 s budget. Three earlier, non-interleaved PR-4 runs (11.4–12.1 s, with Phase A and artefact validation also slower, which the indexes cannot affect) were taken straight after a build and are superseded by the interleaved pairs; they are kept here as a disclosed confounded measurement, not as evidence.

## Decision

The budget is met: p95 ≤ 76 ms for every frozen query, about 4× headroom. The GIN trigram index (contains) and the `text_pattern_ops` b-tree (prefix, exact) are kept.

## Recorded limits

- One synthetic corpus, one laptop, warm cache; not CI, not a Production host profile.
- Every run was Ready. With a Track-level filter, or for runs that are not Ready, coverage counts Tracks: a full 10^6-Track count cost ≈ 240 ms in the intermediate measurement (observed in its plan), so a plate search whose Track-level filter still spans 10^6 Tracks would sit near the budget. A time window normally bounds that scan; it was not separately measured.
- A very broad 3-character text resolves every matching Track id before paging (2 800 for `KA0` here). A text matching a large fraction of 10^6 Tracks would grow step one linearly; it was not measured.
- GIN pending-list behaviour: bulk completions fill the pending list until vacuum; the measurement ran after `VACUUM ANALYZE`.
- Raw run output is kept outside Git at `E:\MAVI-Working\tmp\pr4-scale-run{1,2,3}.txt` and `E:\MAVI-Working\tmp\pr4-ab-*-run{4,5}.txt`.
