# Scene Analytics Slice 4 — search performance and security review

**Date:** 2026-09-21  
**Scope:** the analytic Track search (`GET /api/tracks` with a §S key), its v3 cursor, and the identity-aware Track detail, as implemented on `feature/scene-analytics-s4-search-readiness`.  
**Purpose:** the §13 performance review and §14 security review the Slice 4 brief requires before the independent cold review. Slice 7 owns the measured index review at corpus volume; this note records what the plans say today and what was checked.

## 1. Query shape and plan review

The SQL was captured from PostgreSQL's statement log while `TrackSearchAnalyticsRepositoryTests.EveryPredicateTranslatesAndMatchesTheFixtureFacts` ran, then re-run with `EXPLAIN (ANALYZE, BUFFERS)` against the same `mavi_test` database (PostgreSQL 16 in the review container; the product runs 18, which changes nothing about these plan shapes).

**One analytic page issues at most five statements:** scope resolution (one indexed lookup per supplied scope id), the revision read, the run-denominator `SELECT DISTINCT p.id` over the base candidate set, the Track-accounting `GROUP BY outcome` join, and the page itself; plus at most three bounded explanation reads keyed on the page's `(analysis_id, track_id)` pairs. A continuation issues the scope check and the page only.

**The page query** joins the base candidate chain to `scene_analyses` pinned by `(revision_id, algorithm_version, status IN (Completed, Superseded), visibility_sequence <= snapshot)` and applies every predicate as a correlated `EXISTS` on `(analysis_id = unit.id AND track_id = track.id AND …)`:

- `scene_analyses` is entered through `IX_scene_analyses_revision_id` with the version/status/visibility filter applied on the row — one revision's units, which is exactly the set the identity names. `ux_scene_analyses_identity (processing_run_id, revision_id, algorithm_version)` would be used instead when the planner starts from runs; both are selective.
- Every fact `EXISTS` resolves through the fact table's primary key `(analysis_id, track_id)` or its `track_id` index (`IX_track_zone_summaries_track_id` in the captured plan), i.e. one index probe per candidate row per predicate. No sequential scan appears on any fact table.
- The latest-run `NOT EXISTS` uses `ix_processing_runs_video_visibility`, as the ordinary search already does; the keyset order and `LIMIT` are unchanged from Task 14.
- `ix_track_motion_summaries_longest_stationary` and the zone/line time indexes from §Y are **not** used by these predicates, because a correlated probe on the primary key is strictly better than a range scan on the threshold column; they remain for the §T aggregates. No new index is proposed by this slice; Slice 7 re-measures on the corpus.

**Coverage** reads the distinct run ids of the base set (`SELECT DISTINCT p.id`, same chain as the ordinary search) and the units for those runs by `ix_scene_analyses_run`; classification is done in memory over that bounded unit list. Track accounting joins `track_analysis_outcomes` by primary key prefix `analysis_id = ANY(evaluated units)` to the base chain and groups by outcome — one statement, index-driven throughout.

**Item explanation** is bounded by the page: `analysis_id IN (page units) AND track_id IN (page tracks)` on each fact family, primary-key driven, three statements at most and none when no predicate of that family was asked about.

**Envelope:** the worst-case v3 cursor (every count at `int.MaxValue`, the longest permitted version, a pinned revision, a full 64-hex fingerprint) encodes to well under the 768-character bound and is pinned by `WorstCaseAnalyticCursorStaysInsideThePublishedEnvelope`.

## 2. Security review

| Concern | Finding |
|---|---|
| Cursor tampering | v3 payload is authenticated with HMAC-SHA-256 under a 32-byte installation key; `CryptographicOperations.FixedTimeEquals` runs **before** the payload is deserialised. A tampered payload, a tampered MAC, a forged payload with a zero MAC and a cursor signed under another key are each refused by test without their contents being parsed. v2 remains unsigned and carries nothing the server trusts. |
| Key handling | `TrackCursorSigningKey` holds bytes only, overrides `ToString()`, exposes them to the codec alone; no log statement, exception message or API response carries the key or a cursor's decoded contents. Setup writes the key to the ACL-restricted machine configuration and keeps it across re-runs; a Production host with no key refuses to start. |
| Information exposure | Scope resolution through `processingRunId` answers only for completed, published runs, matching the analytics endpoint's boundary; a hidden run and an unknown run give the same 400. The detail's analytics block carries no internal analysis id. Cursors carry no operator data beyond identifiers already in the URL. |
| Injection | All predicates are EF Core parameterised queries; the persisted vocabularies (`AToB`/`BToA`, headings) are mapped from closed wire vocabularies at the endpoint, never passed through. |
| Denial of resources | `limit` stays bounded at 100; every fact read is bounded by the page; coverage is bounded by the run count of the base scope, which the ordinary filters already narrow. |
| Complete-coverage demand | `analyticsCoverage=complete` yields 409 with the coverage block and no rows; it cannot be used to enumerate anything the partial answer would not disclose. |

## 3. Environment caveats recorded during validation

- The review container runs PostgreSQL 16; the two `DatabaseStartupMigrationTests` that assert the PostgreSQL 18 prerequisite fail here for that reason alone and are covered by CI.
- `PYTHONDONTWRITEBYTECODE=1` is set in the container, which fails `test_environment_fingerprint_ignores_generated_bytecode_cache` (it expects a `.pyc` to be written); unrelated to this slice.
- PowerShell is unavailable in the container, so `Test-MaviSetupContracts.ps1`'s new cursor-key contract checks were reviewed by reading, not executed; CI's Windows setup lane runs them.
