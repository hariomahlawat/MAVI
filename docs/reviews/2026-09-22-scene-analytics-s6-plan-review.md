# Scene Analytics Slice 6 — Planning Cold Review

**Date:** 2026-09-22  
**Reviewed branch:** `docs/scene-analytics-s6-plan`  
**Base:** `main@179786e2f4e09930a2c70119080ae565a92474f6` (Slice 5 / PR #66 merge)  
**Plan reviewed:** `docs/superpowers/plans/2026-09-22-scene-analytics-s6-aggregates-heatmap.md`  
**Review mode:** cold, implementation-risk focused; no feature code exists on this branch.

## 1. Review objective

Determine whether the Slice-6 plan is sufficiently precise that an implementation agent can build aggregates, occupancy and heatmap without inventing semantics, duplicating Slice-4 coverage logic, weakening evidence identity, or introducing unnecessary persistence/dependencies.

The review deliberately asks “what could a competent implementer still misunderstand?” rather than whether the document is comprehensive.

## 2. Baseline facts independently verified

- `main` is `179786e2`, the PR #66 merge.
- Scene Analytics Slices 0–5 are merged.
- There is no existing `Mavi.Application/Modules/SceneAnalytics/Aggregates` module.
- There is no existing `features/scene-analytics` frontend.
- `WorkbenchLayout` already exists and Scene Editor is its reference implementation.
- ADR-011 / Slice 4 already define fact-bearing `Completed` + `Superseded`, snapshot gating and `AnalyticsCoverageResponse`.
- `SceneRevision` carries `referenceFrameVideoAssetId` and `referenceFrameOffsetMs`.
- The frontend already has a canonical video-content URL helper for a video asset.
- `IAcceptedEvidenceReader` is already the sanctioned evidence-root boundary.
- The parent plan §T defines aggregate meanings; §U requires on-demand, non-persisted heatmaps; §Z forbids speculative indexes/cache before measurement.
- UI spec decision 2c remains open specifically for Slice 6.

## 3. Findings

### P2-1 — heatmap window semantics were incomplete — CLOSED

**Original gap:** the draft selected Tracks/runs by a UTC window but did not explicitly state whether every sample of an overlapping Track contributed.

That would let a Track crossing the left/right window boundary contribute samples outside the requested interval, making the heatmap disagree with the operator's time filter.

**Correction:** the plan now freezes:
- Track/run overlap determines candidate scope;
- each trajectory sample is mapped to an absolute UTC instant from immutable recording start + media offset;
- only samples in `[fromUtc, toUtc)` contribute.

Regression coverage is required for samples before `fromUtc`, exactly at `fromUtc`, just before `toUtc`, and exactly at `toUtc`.

### P2-2 — non-additive bucket counts could be incorrectly summed — CLOSED

**Original gap:** the Workbench inspector was allowed to show “totals” without distinguishing additive from non-additive series.

Summing bucket `zoneUniqueTrackCount` or class Track counts double-counts a Track spanning several buckets. Summing occupancy is also meaningless.

**Correction:** the backend contract now carries explicit window-level distinct totals and peak fields. The plan states:
- event counts (entry/exit/crossing) are additive across disjoint buckets;
- unique Track counts, class counts, occupancy and peak occupancy are not;
- the UI MUST use server-provided window totals rather than reconstructing them by summing buckets.

### P2-3 — parent-plan explicit-run heatmap scope was omitted — CLOSED

**Original gap:** §U allows either the resolved camera/window run set or an explicit run, while the draft specified only camera/window.

**Correction:** heatmap accepts optional `processingRunId`, validated as completed/published and belonging to the path camera. It does not accept an arbitrary analysis id. Aggregate queries remain camera/window based.

### P2-4 — disabled geometry could be misrepresented as observed zero — CLOSED

**Original gap:** a response containing every revision zone/line with zero arrays would make disabled geometry look evaluated.

**Correction:** analytical series include only geometry enabled in the resolved revision. Disabled geometry remains configuration context available through the exact scene-revision endpoint, not zero analytical evidence.

### P2-5 — worst-case aggregate response envelope was too loose — CLOSED

**Original gap:** a 2048-bucket cap combined with the maximum 64 zones + 64 trip lines could yield hundreds of thousands of numeric cells and multi-megabyte JSON before any measured need.

**Correction:** hard server cap reduced to **512 buckets**. The UI still targets ≤120 using deterministic human-friendly bucket values. Slice 7 may change the limit only from measured evidence.

### Documentation-consistency findings — CLOSED

Cold review found stale statements that still said:
- Slice 5 was next/awaiting review;
- Slice 5 “must” consume the UI-5 seam;
- UI decision 7 remained open.

The parent plan, both capability roadmaps and UI specification have been reconciled to PR #66 / `main@179786e2`.

## 4. Key design choices accepted

### 4.1 Shared scope/coverage semantics

**Accepted.** Slice 6 should extract/reuse the smallest Slice-4 scope/coverage seam rather than duplicate its SQL or state classification. This is the most important architectural protection in the plan.

Guard: all existing Slice-4 search/coverage tests remain unchanged and green after extraction.

### 4.2 Bucket anchoring

**Accepted.** Buckets anchored to request `fromUtc` and half-open `[start,end)` are deterministic, timezone-independent and eliminate boundary double-counting.

### 4.3 Occupancy meaning

**Accepted with explicit naming.** `occupancyAtStart` and peak over those sampled boundary instants follow parent §T. They are not integrated occupancy and may miss a between-boundary instantaneous maximum by design. The response/UI must say so.

### 4.4 Repeated visits

**Accepted.** Parent §T explicitly sources `repeatedVisitTrackCount` from `track_zone_summaries`. The plan therefore treats it as a whole-Track summary for Tracks in the covered request scope, not “two visits within one bucket/window”. The operator copy must preserve that meaning.

### 4.5 Heatmap weighting

**Accepted.** Slice 6 freezes v1 to one count per persisted sample. The parent plan's optional time weighting is not implemented yet. This avoids introducing two heatmap meanings in the qualification slice.

### 4.6 Heatmap resource bounds

**Accepted after repair.** The original 50-run cap did not bound the expensive operation: one dense run can contain many thousands of Track trajectories. The plan now applies two pre-fan-out guards before any artefact open: at most 50 covered runs and at most 2,000 candidate Analysed Track trajectories. The second guard bounds sequential evidence opens independently of run density. Slice 7 must measure both dimensions before either cap is relaxed.

### 4.7 No cache / no new index

**Accepted.** §Z says measure first. Adding either in Slice 6 would pre-optimise the wrong query shape and create additional invalidation/qualification surface.

### 4.8 Workbench UI

**Accepted.** Camera-centric `/cameras/:cameraId/analytics`, Activity and Heatmap modes, one persistent coverage vocabulary, and the shared Workbench archetype align with ADR-012. No global dashboard is pulled forward.

### 4.9 Heatmap reference frame

**Accepted.** The exact resolved revision supplies the reference video asset/offset. If unavailable, neutral matte is honest; borrowing another revision's frame is prohibited.

### 4.10 Colour decision 2c

**Accepted.** The plan deliberately does not choose hex values. The UI specification requires selection against the first real rendered heatmap. The implementation must record candidate measurements and close the decision in the same PR.

## 5. Remaining implementation risks and required controls

These are not open plan defects; they are implementation audit points.

1. **Scope extraction regression:** refactoring Slice-4 coverage code can accidentally alter search behavior. Preserve existing tests unchanged.
2. **Set-based SQL:** avoid zone×bucket N+1 loops. Integration tests should make query shape reviewable.
3. **Timestamp source:** heatmap sample UTC must derive from immutable source recording start, not request/display timezone.
4. **Boundary arithmetic:** do not use floating-point time bucket arithmetic; use integer/time-span operations.
5. **Distinct counts:** compute at the database/service level with explicit distinct Track identity; never deduplicate by display/local Track number.
6. **Superseded units:** remain fact-bearing for a resolved historical identity.
7. **Zero covered runs:** distinguish a non-empty denominator with no covered runs (200 + truthful incomplete coverage, no ordinary zero chart) from a genuinely empty denominator (complete-zero with all coverage buckets zero).
8. **Reference mismatch:** fail closed if scene revision/camera identity is inconsistent.
9. **Evidence corruption:** an `Analysed` outcome whose accepted trajectory cannot be read is an error, not a reduced heatmap.
10. **Resource guards:** apply bucket/grid validation and both heatmap pre-fan-out guards (run count and candidate Analysed Track count) before trajectory artefact work.
11. **Accessibility size:** do not expose every heatmap cell or every chart point as an accessibility node.
12. **No hidden dependency:** hand-built SVG/canvas only unless the plan is explicitly amended.

## 6. Review of scope boundaries

The following remain correctly excluded:

- raster heatmap persistence;
- database indexes added from guesswork;
- in-memory heatmap cache before measurement;
- time-weighted/kernel heatmap;
- live camera analytics;
- event/behaviour framework;
- anomaly/intent;
- trajectory v2;
- physical calibration;
- generic dashboards/reports;
- worker/model changes;
- new dependency/offline-packaging work;
- Evidence Player redesign.

No excluded item is required to make Slice 6 coherent.

## 7. Post-review repair pass

The exact-head external review found three additional contract defects after the initial cold review. All are now incorporated into the plan:

1. **P1 — analytical provenance:** aggregate and heatmap response contracts now return `snapshotVisibilitySequence`, making the ADR-011 analytical identity traceable to the exact visibility snapshot used for the result.
2. **P1 — heatmap resource bound:** the run-only cap is supplemented by a 2,000 candidate-Analysed-Track pre-fan-out cap, enforced before any trajectory artefact open. This directly bounds the expensive per-Track evidence-read fan-out.
3. **P2 — empty-scope coverage:** the plan now preserves Slice-4 semantics for a genuinely empty base denominator: complete-zero with all coverage buckets zero. The not-analysed state applies only when the denominator is non-empty but no run is covered.

Required regression/contract tests must discriminate each repaired rule: snapshot sequence serialization, empty-denominator versus uncovered-denominator behavior, and both heatmap guards firing before evidence I/O.

## 8. Final planning gate

**P1:** 0 open after the post-review repairs.  
**P2:** 0 open after the post-review repairs.  
**P3:** 0 material planning issue open.

The plan is implementation-ready once this planning branch is merged and post-merge `main` gates are green.

Recommended execution remains one bounded Slice-6 feature PR, implemented in the eight tasks in the plan. Use internal cold review as the normal review gate; use Codex only if implementation produces unresolved architectural uncertainty.
