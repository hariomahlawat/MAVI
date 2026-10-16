# ADR-019: An end-time index on Vehicle Tracks, and no parallel workers inside a plate search

**Status:** Accepted owner decision for Stage 4 PR-4, 2026-10-15 (options (b) and (d) of the PR-4 options packet; implemented with ADR-018).

**Date:** 2026-10-15

**Related:**
- ADR-013, implementation amendment 2026-10-13 (Stage 4 plate search), items 18 and 19;
- ADR-018;
- plan `docs/superpowers/plans/2026-10-12-stage4-anpr-ocr.md` §2.8;
- evidence `docs/qualification/stage4/2026-10-13-plate-search-at-scale.md`.

## Context

Two causes of the plan §2.8 misses were measured and are independent of the candidate design.

1. **The windowed coverage count (Q12).**
   - With a Track-level filter, plate coverage counts the scope's Vehicle Tracks per run for this query.
   - The query is `object_class = 'Vehicle' AND processing_run_id = ANY(…) AND end_timestamp_utc >= fromUtc`; a window's lower bound is on the Track's end time (`AnalyticsScopeQuery`).
   - No index leads with those columns, so on 10^6 Tracks the count is a parallel sequential scan of `tracks` (176 ms in the frozen plan).
2. **Parallel worker start-up.**
   - On the Windows Development host, PostgreSQL's parallel query cost about 150 ms per statement just to start its workers. That is more than the statements it parallelised.
   - In the options packet, `SET LOCAL max_parallel_workers_per_gather = 0` alone took Q03 from 776 ms to 208 ms and Q04 from 718 ms to 229 ms.

## Decision

1. **(b) The index.**
   - Migration `20261015120100_AddTrackVehicleEndTimestampIndex` adds the b-tree `ix_tracks_object_class_end_timestamp_utc ON tracks (object_class, end_timestamp_utc)`. This is exactly the form measured in the packet.
   - Its role is to replace the windowed coverage count's sequential scan with an index range read of the window's Vehicle Tracks.
   - The evidence for that role is the `EXPLAIN (ANALYZE, BUFFERS)` of Q12's real statements, replayed by `PlateSearchScaleMeasurementTests` on the candidate head and retained with the evidence record.
   - It is additive and reversible: Down drops it, and an older platform ignores it.
2. **(d) No parallel workers, scoped to the plate search.**
   - Every plate search runs `SET LOCAL max_parallel_workers_per_gather = 0` inside its own transaction, first page and continuation alike (`TrackSearchRepository.NoParallelWorkers`). The continuation, which previously ran without an explicit transaction, now has one so that the setting has a scope.
   - `SET LOCAL` ends with the transaction. No other query, session, database setting or server configuration changes.
   - The plan evidence replays each captured statement with the same setting, so the plan recorded is the plan the search runs.

## Consequences

### Positive

- Q12, the one-day window, met the budget only with (b): 80 ms p95 in the packet (c2+b+d), against 221 ms without it (c2+d).
- With the parallel start-up removed, the latency of small, indexed statements no longer depends on how many workers the host can start.

### Costs (the trade-off accepted)

- **Write cost of (b).**
  - Every Track insert maintains one more b-tree, at about 10^6 entries per 10^6 Tracks.
  - Tracks are written once, at VisionJob finalisation, in bulk.
  - The cost is not separately measured beyond the plate completion timing, which does not insert Tracks.
- **Disk.** The index takes roughly 30–40 MB per 10^6 Tracks.
- **Planner side effects.**
  - Other Track queries with an `end_timestamp_utc` lower bound and an object class may now choose this index.
  - The planner chooses it only where it is cheaper.
  - No existing plan-shape test names a `tracks` index, and the full regression comparison is the guard.
- **What (d) gives up.**
  - A plate search cannot use parallel query even where it would help: a very large statement on a many-core server would run single-process.
  - The measured statements are all index-driven and small.
  - The decision is scoped to the plate search so that it can be revisited per query path, with its own measurement, without touching anything else.

## Alternatives rejected

- **Narrowing the coverage run scope by the window before counting.** This was option (b) in the original record. It would change the coverage computation, and it was not measured.
- **Changing `max_parallel_workers_per_gather` (or `parallel_setup_cost`) for the server or the database.** That would change every query of the installation on the evidence of one path. Server configuration is outside the platform's migrations and Setup's current scope.
