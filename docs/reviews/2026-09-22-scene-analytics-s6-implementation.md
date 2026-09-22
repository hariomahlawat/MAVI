# Scene Analytics Slice 6 — implementation review

**Branch:** `feature/scene-analytics-s6-aggregates-heatmap`.
**Implementation base:** `main@a65b031094371c8be98293e737d5ca827cf53377` (the Slice-6 plan merge).
**Plan:** `docs/superpowers/plans/2026-09-22-scene-analytics-s6-aggregates-heatmap.md`.
**Pre-implementation review:** `docs/reviews/2026-09-22-scene-analytics-s6-plan-review.md`.

Written after implementation and before external review: what was built, what was decided where the plan left room, what it deliberately does not do, and what my own cold pass found.

---

## 1. What the slice does

Persisted Scene Analytics facts become answers about a camera over a window:

- bucketed zone entries, exits, distinct Tracks and occupancy, with peak and its instant;
- bucketed trip-line crossings, kept separate by direction;
- active Track counts by object class;
- an on-demand trajectory-sample density map;
- one Analytics Workbench at `/cameras/:cameraId/analytics`, reached from the Cameras Ledger.

No new dependency, no cache, no persisted raster, no speculative index, no vision-worker, runtime-pack or model-pack change.

---

## 2. The central architectural objective

**Slice 6 must not create a second implementation of Slice 4 analytical scope, coverage or snapshot semantics.**

It does not. `Mavi.Infrastructure/Persistence/Repositories/AnalyticsScopeQuery.cs` is the one seam, extracted verbatim from `TrackSearchRepository`, which now delegates to it along with `TrackSearchRepository.Analytics.cs`. It owns:

- `BaseCandidates` — the fact-bearing run predicate, `Completed` **and** `Superseded`, gated on the visibility sequence;
- `ResolveRevisionAsync` — single-camera resolution and the analytics-enabled question;
- `ComputeCoverageAsync` — the six readiness buckets plus analysed/unavailable Tracks;
- `VisibleUnits` — the units a snapshot may read.

The extraction is proved behaviour-preserving by the existing suites: 318 Application tests and 29 Slice-4 integration tests unchanged, none rewritten to accommodate it.

**Snapshot ordering.** `AnalyticsAggregateRepository` opens its transaction, takes the shared `ProcessingVisibilityBarrier` and allocates the sequence **before** reading any snapshot-defining state. Scope resolution, coverage and both work bounds are then computed under that one snapshot. The weaker model the plan forbids — resolve scope first, filter by sequence later — is not what is implemented, and the barrier call is the first statement of the read path.

---

## 3. Decisions taken where the plan left room

### 3.1 Counting happens in C#, not in SQL

The repository reads four narrow, bounded projections and `AnalyticsAggregator` does the counting. The trade accepted: a bounded in-memory fact set, in exchange for counting rules that are obviously correct and testable as pure functions over golden fixtures. Nineteen of them pin the boundary cases the plan enumerates — entry exactly on a bucket start, exactly on a bucket end, endpoint-touching visits excluded from positive overlap, a distinct Track counted once despite several visits, peak ties choosing the earliest instant, the final short bucket. Measured optimisation is Slice 7's, against a real profile rather than a guess.

### 3.2 The heatmap port is split in two

`IAnalyticsAggregateRepository` has `ResolveHeatmapScopeAsync` (cheap: identity, coverage and both bounded counts, all database-side) and `ListHeatmapCandidatesAsync` (expensive). The service enforces both bounds between them. A port that answered "give me the heatmap" in one call would have to open artefacts to discover it should not have.

This is tested as **call ordering**, not as a status code: `AnalyticsHeatmapGuardTests` supplies a `ForbiddenEvidenceReader` and a `ScopeRepository` that throw if reached, so a guard that fired after the I/O would fail the test rather than pass it. The integration suite adds the same property against a real database.

### 3.3 `objectClass` casing was aligned, not re-decided

Writing the contract tests surfaced a divergence: `/api/tracks` has always accepted `objectClass` in any casing, while the new routes demanded the canonical spelling. The same parameter on the same API behaving two ways is a defect, and a client sharing a serializer between Investigation and Analytics would break on one of them. The vocabulary stays closed; only the spelling rule now matches, and responses still carry the canonical form. A test asserts the parity across both routes.

### 3.4 The coverage vocabulary moved rather than being re-created

The plan forbids a fourth readiness vocabulary. The existing strip lived inside the Investigation feature, so it and the identity labels moved to `shared/evidence`, where `video-review` was already reaching across for them. The only behavioural change: the headline for a scope holding no runs names the scope it is talking about instead of always saying "search scope".

### 3.5 The chart's semantic twin lives in the inspector

Not a presentation preference. §4.3.2 gives the Workbench one scroll owner — the inspector body — and a stage that grows but never scrolls. A bucket list is unbounded, so under the chart it made the stage a second scroll owner; the §26 harness caught it. The inspector is both where the archetype allows it to scroll and where a reader looking for exact numbers goes.

### 3.6 The heatmap composites over a neutral matte

Plan §9.2 allows "a paused exact-revision reference video frame **or** neutral matte". Slice 6 ships the matte; the reference frame is deferred. The consequence is recorded honestly in the QA matrix: there are no footage-condition heatmap states, because without a frame underneath they would capture identical pixels and assert nothing. Decision 2c's footage measurements are analytic instead, and re-derived from the tokens in `styles/contrast.test.ts`. The scrim ships now because it is what makes the scale correct the moment a frame appears under it.

---

## 4. The truthfulness rule, and where it is enforced

> Incomplete analytics must never visually masquerade as observed zero activity.

Three distinct states, kept distinct at three layers:

| State | Server | Surface |
|---|---|---|
| Complete, facts present | `coverage.complete`, series populated | Chart / map drawn |
| Complete, no facts | `coverage.complete`, series of zeros | Chart / map drawn — **this is a real observation** |
| Incomplete | `coverage.complete` false | **Nothing drawn**; what is outstanding is named, with a route to Processing |

`scopePresence` is the pure predicate, tested on its own. The page tests assert that an incomplete scope renders no `figure` at all, and the heatmap tests that it renders no summary region — not merely that a warning appears beside a chart. A zone or line disabled in the resolved revision is **absent** from the response rather than present as zeros, and the surface reports it as never evaluated rather than as seen-and-empty.

The heatmap has two refusals of its own, and neither is an empty map: a scope the server declines to open names the bound it exceeded and offers a narrower window, and evidence that could not be read says so, because a map built from the artefacts that happened to open would show where the readable files went rather than where anything went.

---

## 5. Specification decision 2c

Closed by measurement. Method as UI-1 and decision 2a: linear-light sRGB, Viénot dichromat simulation, CIEDE2000 in CIE L\*a\*b\*.

The finding that decided it: **a sequential scale has to traverse the whole luminance range, so it passes near every hue on the way.** Every candidate that keeps a hue comes closer to a frozen evidence role than the 7.1 that closed decision 2a.

| Candidate | Min separation from a frozen role | Min adjacent step | Luminance range |
|---|---|---|---|
| viridis | 2.0 (`--evidence-crossing` / tritan) | 13.3 | 0.019 → 0.782 |
| magma | 1.4 (`--geo-zone` / tritan) | 17.1 | 0.000 → 0.947 |
| cividis | 1.4 (`--evidence-crossing` / deutan) | 10.7 | 0.017 → 0.802 |
| single-hue blue | 1.3 (`--geo-dir-ab` / deutan) | 15.0 | 0.012 → 0.871 |
| viridis, yellow end cut | 5.0 (`--geo-zone` / deutan) | 11.3 | 0.019 → 0.503 |
| **low-chroma ramp (selected)** | **7.8** (`--evidence-box` / tritan) | **9.8** | **0.009 → 0.776** |

Selected: `--heat-0` `#111827`, `--heat-1` `#27374d`, `--heat-2` `#44566e`, `--heat-3` `#7b8ea6`, `--heat-4` `#dde5ee`.

Keeping chroma low is the mechanism: every stop stays near its own grey, so it competes with no frozen role and cannot read as a red-to-green judgement. Luminance rises monotonically, which is the property that survives greyscale and all three dichromacies — density still reads where hue would not.

**The scrim is part of the decision.** Against bright footage the top of *any* light-ended scale measures ~1.02:1 and disappears. At `--heat-scrim: rgb(0 0 0 / 50%)` the top clears 3:1 against every §26 reference frame:

| Frame | Top stop, scrimmed |
|---|---|
| bright `#e8e6e0` | 3.73:1 |
| dark `#14161a` | 15.49:1 |
| saturated `#1d4ed8` | 10.82:1 |
| low contrast `#6b7280` | 9.09:1 |

The bottom of the scale is deliberately left low-contrast: it means "almost nothing here" and should recede into the frame. A non-colour legend with numeric endpoints ships beside the map, because the scale is relative to this answer's busiest cell and a colour bar alone would imply an absolute quantity.

Validated at 1366×768, 1440×900, 1920×1080 and 2560×1080 through the §26 harness. Every figure above is recomputed from the tokens in `styles/contrast.test.ts` rather than transcribed into it.

---

## 6. What my own cold pass found

Five defects, each found by a test or by the QA harness rather than by reading, and each fixed in the commit that found it.

1. **Half-typed times threw out of the change handler.** `configuredWallTimeToUtc` rejects a partial wall time, and the window fields converted on every keystroke. The fields now hold their own text and commit only a whole, unambiguous instant; a value that cannot be interpreted is reported on its own field and the previous window stands.
2. **No configured display zone silently became UTC.** A time shown in the wrong zone reads as a fact about when something happened. The fields are now disabled and say why.
3. **A failed refetch replaced the answer already on screen.** The hard-error branch shadowed the retained data. The answer now stays, marked as possibly no longer current.
4. **The chart's accessible name was the metric's wire key**, not the words the operator reads.
5. **The stage became a second scroll owner** (§4.3.2), fixed as described in §3.5.

Two smaller corrections: an ordering clause that did not translate to SQL now lives inside the shared candidate definition, so the set that is counted and the set that is read are provably one query in one sequence; and a generic caution paragraph in the inspector duplicated the metric definition beside it and became a short tag instead.

---

## 7. Test inventory

| Suite | Count | What it pins |
|---|---|---|
| `AnalyticsAggregatorTests` | 19 | The frozen counting rules, boundary by boundary |
| `HeatmapGridTests` | 17 | Cell indexing, corners including exactly 0 and 1, every grid size |
| `AnalyticsHeatmapGuardTests` | 5 | Both bounds fire **before** evidence access, by call ordering |
| `AnalyticsHeatmapServiceTests` | 7 | Evidence decode, window clipping, failure propagation |
| `AnalyticsAggregateRepositoryTests` | 10 | Barrier ordering, scope, coverage, facts over a real database |
| `AnalyticsHeatmapRepositoryTests` | 10 | Scope without evidence, DB-derived counts, missing and corrupt evidence |
| `AnalyticsApiTests` | 69 | The closed query vocabulary, bounds, typed refusals, provenance, non-enumeration |
| `analyticsState.test.ts` | 14 | Non-additive totals, absent subjects, window snapping, the transport bound |
| `AnalyticsPage.test.tsx` | 10 | The five activity states, including complete-zero versus incomplete |
| `HeatmapMode.test.tsx` | 9 | Summary not enumeration, wording, both evidence refusals, complete-zero |
| `contrast.test.ts` (decision 2c) | 4 | The scale's three defended properties, recomputed |
| §26 visual QA | 10 states × 4 widths | Rendered structure, focus, archetype conformance |

---

## 8. What this slice deliberately does not do

- No cross-camera aggregate dashboard. The analytical identity is per camera; a figure summed across cameras would be summed across different geometry answering different questions.
- No heatmap cache and no persisted raster.
- No reference video frame under the density map (§3.6).
- No new index. Slice 7 owns measured optimisation.
- No mutation route. Everything here is read-only.
