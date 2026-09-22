# Spatial & Temporal Track Analytics — Stage-1 acceptance status

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71's qualification-harness branch integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Qualification candidate (measured):** `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`
**Governing gate:** `docs/superpowers/plans/2026-09-22-scene-analytics-s7-hardening-acceptance.md` §25 — the numbering below is that section's, item for item
**Operator actions still owed:** `docs/runbooks/scene-analytics-stage1-development-acceptance.md`

---

## Verdict

**Stage 1 is NOT closed.**

This pass closed every remaining obligation that can be executed without the Development machine: cancellation and failure at realistic volume (item 8), deterministic concurrency race probes (item 9), the explanation/heatmap/UI legs of C1 (item 2), and accessibility and visual QA at all four widths (item 13, except one real-data leg). It also built, verified and engine-proved the three scripted videos the parent plan requires.

What remains needs the Development machine or the owner:

- the aggregate-materialisation **P2** is **BLOCKED** — its decision needs the authoritative §T figures, which are held outside the repository, and a decision rule that is proposed here but not yet approved;
- the Development-corpus unit timing (item 4a), the three scripted videos through the real worker, the runtime-identity record, the no-undeclared-fetch check (item 14) and the Search → Investigation leg on real data (item 13) are prepared as exact operator actions and **not executed**.

Nothing unexecuted is marked PASS.

## Evidence, and which of it is authoritative

| Evidence | Where | Standing |
|---|---|---|
| **Development-machine PostgreSQL 18 qualification** | Windows Development machine, PostgreSQL **18.6**, pgvector **0.8.6**, port 5433, qualification database `mavi_test`; clean tree; SHA `5f516662…` repository-reachable | **Authoritative — PASS** |
| **Development-machine real-worker acceptance** | Same machine, live database `mavi_dev`, real RTMDet + ByteTrack path | **Authoritative — PASS**, including restart persistence |
| Correctness tests added in this pass | Ordinary integration, application and frontend suites; locally on PostgreSQL 16.15, in CI on PostgreSQL 18 | **Correctness evidence** — they assert outcomes, not timings, and hold on any supported server |
| Earlier independent PostgreSQL 18 pass | PostgreSQL 18.6 on Ubuntu 24.04.4 | **Superseded, non-authoritative** — kept in the performance report as history only |
| Container measurements | PostgreSQL **16.15** | **Engineering observations only** — PostgreSQL 16 cannot qualify |

The three qualification evidence files — `plan-qualification.json`, `analytics-unit-throughput.json`, `heatmap-envelope.json` — each report status `qualification evidence` and are tied to `5f516662…`. They are held outside the repository by the operator with SHA-256 hashes, and are deliberately not committed.

## The measured SHA and the current head

PR #71 was integrated by **fast-forward**, so PR #70's history contains `5f5166628b0c4af04cc8f7efcd40f7022f5095c4` itself.

This pass **does** change executable code after that SHA, and says so plainly: it adds test files (`RealisticVolumeResilienceTests`, `ConcurrencyRaceProbeTests`, `ScriptedCorpusTests`, a C1 contract test in `SemanticAcceptanceTests`, `c1OperatorContract.test.tsx`), test fixtures, two visual-QA states and Development tooling (`tools/vision/dev/scripted_corpus.py`, a scenario switch in `fixture_worker_harness.py`, `tools/qualification/`). It changes **no production source file** and **none of the qualification harnesses or their shared corpus** — `PlanQualificationTests`, `ThroughputQualificationTests`, `QualificationCorpus`, `QualificationGate`, `QualificationVerdict` and `SqlCapture` are byte-identical to the measured SHA. The new tests only read `QualificationCorpus`. The PostgreSQL 18 qualification evidence therefore still describes the code it measured, and no qualification rerun is required by this change. The check is mechanical: `git diff --name-only 5f516662 HEAD -- src/` lists exactly one file, the frontend test `src/web/mavi-web/src/features/video-review/c1OperatorContract.test.tsx`, and the diff over the six harness files is empty.

## Formal exit gate (plan §25)

| # | Requirement | Status |
|---|---|---|
| 1 | Stage-1 functional acceptance met | **NOT MET** — depends on items 7, 12, 13, 14 and 18 |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **PASS.** Trajectory → facts → §S → §T as before; now also the explanation (track detail), the pinned geometry names and the heatmap (an exact matrix), read through the real HTTP API, compared byte for byte with a committed golden, and the same golden driven through the real explanation, overlay and heatmap components with the heatmap recomputed from the authored path. Details: semantic acceptance §5 |
| 3 | PostgreSQL 18 plans and timings for every §S predicate and §T aggregate at 10^5 facts | **PASS** — `PlanQualificationTests` on PostgreSQL 18.6, 110,000 relevant facts, `qualification evidence`, SHA `5f516662…` |
| 4 | Analytics-unit duration and rows for (a) the Development corpus and (b) a synthetic 1,000-Track run | **PARTIAL.** (b) **PASS**: 1,000 analysed, 0 unavailable, `Completed`, ≈3.11 s; 1,000 outcomes, 4,000 zone summaries, 185 visits, 1,391 crossings, 1,000 motion summaries. (a) **NOT EXECUTED** — the real-video unit ran to `Analysed` but its duration and rows were not recorded; `tools/qualification/development-unit-record.sql` reads them from `mavi_dev` (runbook §B) |
| 5 | Aggregate scale qualification, including 10^5-fact cases | **PASS** as a recorded measurement — the nine §T cases ran inside the qualifying `PlanQualificationTests` at 110,000 facts. The disposition that depends on them is item 7 |
| 6 | Heatmap 50-run/candidate envelope recorded, and both fan-out limits explicitly decided | **PASS — RETAIN both the 50-run and the 2,000-Track limits.** Not measured, and not claimed: the 1/5/10/25-run sweep and per-phase timings |
| 7 | No demonstrated N+1/unbounded DB/evidence-I/O path remains | **NOT MET — BLOCKED.** No N+1. The aggregate read's unbounded-materialisation **P2 remains OPEN**: its decision needs the authoritative §T figures, which are not available here, and the proposed decision rule (security review §1) needs the owner's approval. Evidence-I/O is bounded by the heatmap guards and now proved cancellable and fail-closed at the envelope (item 8) |
| 8 | Cancellation/failure proven at realistic volume | **PASS.** `RealisticVolumeResilienceTests`: the heatmap cancelled at the 500th of 2,000 artefact reads and failed at the 1,337th, and a 1,000-Track unit cancelled at its 400th Track and faulted at its 600th — no partial answer returned or published, no read after the interruption, coverage *pending* rather than zero, the lease honoured, reclaim with a fresh token, the stale claim fenced, and every retry equal to the uninterrupted answer. The §11 PostgreSQL-restart case is separate and **NOT EXECUTED** (runbook §F) |
| 9 | Snapshot/revision consistency proven under concurrency | **PASS.** `ConcurrencyRaceProbeTests`: a writer observed waiting on the barrier behind a stopped aggregate, with the reader's answer unmoved and the next answer complete; two publications landing in the heatmap's scope-to-evidence gap without moving its map; an activation observed waiting behind an in-flight unit commit, with no cross-revision reading. A negative probe (barrier removed) makes the first fail. With the existing pinned-pagination, supersession and ownership-fencing tests, this covers the races plan §12 names; the one publication path not raced directly is a **processing-run** completion, which takes the same exclusive barrier through the same `AcquireCompletionExclusiveAsync` statement as the unit commit that is raced — an inference from shared code, stated as one |
| 10 | Incomplete/unknown never appears as observed zero | **PASS** — existing tests, and now at volume: a cancelled or failed unit reads as *pending* |
| 11 | Browser parser matches the normalised-coordinate contract | **PASS** |
| 12 | Security/resource review has no open P1/P2 | **NOT MET** — the item-7 P2 is open. No P1 |
| 13 | Operator workflow / accessibility / visual QA pass | **PARTIAL.** Accessibility and visual QA **PASS**: 53 analytics-related states × 4 widths, zero automated findings, human capture pass, no P1/P2 (three P3s). The operator workflow ran end to end on real data except the **Search → Investigation** leg, **NOT EXECUTED** (runbook §E) |
| 14 | Development offline/real-worker acceptance recorded with no undeclared dependency | **PARTIAL.** Real-worker acceptance **PASS**; restart persistence **PASS**. The three scripted videos: generated and pixel-verified, their expected facts proved against the real engine — the **run through the real worker is NOT EXECUTED** (runbook §C). Runtime identities: **NOT EXECUTED**, SQL prepared (runbook §D.1). No-undeclared-fetch: **NOT EXECUTED**, disconnected procedure prepared (runbook §D.2) |
| 15 | No policy-violating dependency/runtime drift | **PASS** — zero files differ from `main` across `*.csproj`, `package.json`, lockfiles and `config/dependencies/`; the new tools are standard-library Python and plain SQL; `verify_repo.py` green |
| 16 | Relevant suites and exact-head CI green | **PENDING** — local suites below; exact-head CI is reported on PR #70 for the final pushed head only |
| 17 | Documentation reflects measured reality, limits and known limitations | **PASS** for these documents at this head |
| 18 | Independent cold review clean of P1/P2 | **NOT MET** while the item-7 P2 is open. The bounded review of this pass found no new P1/P2 |
| 19 | No unresolved material review thread | **PENDING** — PR #70 has none. On PR #71, three threads were answered and resolved; the fourth (exact-head CI) has its evidence reply posted and its resolution left to the owner |
| 20 | Post-merge critical verification on `main` green | **NOT APPLICABLE YET** — PR #70 is not merged |

## Development-machine real-worker acceptance

| Check | Observed |
|---|---|
| Input | Real video `2min.mp4`, camera CAM-04 / G4 |
| Worker path | Real RTMDet detector; real ByteTrack tracker; existing sealed Tracks and trajectories reused |
| Scene | Revision 2 with 1 zone and 1 trip line |
| Analysis request | Explicit queue through the existing API: first call `created: 1`, repeat call `alreadyReady: 1` |
| Readiness | Processing UI showed **Analysed** |
| Evidence Review | *Scene revision 2 · Engine v1*; *Box centre*; one real Track with *Zone 1 · 1 visit · dwell 2s*, no line crossing, *Up (image direction)*, *Never stationary*; overlays rendered against the real video |
| Activity (stored window, 20 Sep 2025) | 12 distinct Person Tracks, 0 Vehicle Tracks, peak 7 in the 1-minute view |
| Heatmap | 3,002 samples, 12 contributing Tracks, 64 × 36, busiest cell 986, Revision 2 / Engine v1, *All 1 run analysed* |
| Restart persistence | `Mavi.Api` restarted; the analytics, Revision 2 identity, zone facts, Activity and Heatmap all unchanged |

**Real-worker Development acceptance: PASS. Restart persistence: PASS.**

## Development-machine actions that close the remaining items

Each is an exact procedure in `docs/runbooks/scene-analytics-stage1-development-acceptance.md`. Record the result here; do not record a PASS for an action not run.

| Action | Closes | Result |
|---|---|---|
| A — transcribe the authoritative §T figures, apply the approved decision rule | 7, 12, 18 | *pending* (and the rule needs the owner's approval) |
| B — Development-corpus unit record from `mavi_dev` | 4a | *pending* |
| C — the three scripted videos through the real worker and analytics host, `check` = `ok` for each | 14 | *pending* |
| D.1 — runtime identity of the real-worker runs | 14 | *pending* |
| D.2 — disconnected re-run, same-origin network only | 14 | *pending* |
| E — Search → Investigation on real data | 13 | *pending* |
| F — PostgreSQL restart/reconnect | plan §11 | *pending* |

## Known limitations recorded by this pass

- **A slow crossing is not a crossing.** By the frozen rule (plan §K), a Track that lingers in the on-line band for more than k = 3 samples is not credited with a crossing. At 25 fps that is a traverse slower than about 0.0033 of the frame per frame. Found by the scripted corpus, recorded rather than changed.
- The aggregate's work is linear in the facts inside the requested window; the only hard bound is the camera and the window. This is the open P2.

## Validation of this head

Executed in the repair container on **PostgreSQL 16.15**. Ordinary-suite results only; none is qualification evidence.

Domain **195** passed; Application **373** passed; Integration **657 passed, 2 failed of 659** — both `DatabaseStartupMigrationTests` asserting the PostgreSQL 18 prerequisite against 16.15; frontend **826** tests, typecheck clean, production build succeeds; `verify_repo.py` passed; evidence-assembler guard coverage 52/52; visual QA 212 combinations, zero automated findings; dependency surface unchanged.

## History

- **Slice 7, first pass.** Browser parser `[0,1]` parity; C1 corpus; the qualification corpus and harnesses; the N+1 guard; the reconciled register; the P2.
- **Harness defects, three rounds**, and the fail-closed `QualificationVerdict` mechanism (performance report §3–3c).
- **Provenance round.** The earlier PostgreSQL 18 pass named an unreachable commit; the harness now refuses dirty or unresolvable provenance. Superseded by the Development-machine run on `5f516662…`.
- **Integration.** PR #71 fast-forwarded into PR #70; Development-machine qualification and real-worker acceptance recorded.
- **Remaining-obligations pass.** Items 2, 8 and 9 closed; item 13's accessibility/visual QA executed; the scripted corpus built and engine-proved; exact operator actions prepared for everything that needs the Development machine; the P2 left open and blocked, with a decision rule proposed before its figures are seen.
