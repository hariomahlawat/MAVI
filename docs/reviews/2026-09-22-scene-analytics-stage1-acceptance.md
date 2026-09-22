# Spatial & Temporal Track Analytics — Stage-1 acceptance status

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71's qualification-harness branch integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Qualification candidate (measured):** `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`
**Governing gate:** `docs/superpowers/plans/2026-09-22-scene-analytics-s7-hardening-acceptance.md` §25 — the numbering below is that section's, item for item

---

## Verdict

**Stage 1 is NOT closed.**

The PostgreSQL 18 qualification, the real-worker Development acceptance and restart persistence all **passed** on the Development machine, against the exact reachable commit above. That closes the evidence gap that held this register open.

It does not close Stage 1. Formal §25 items remain unmet or partly met — the carried aggregate-materialisation P2 has not been dispositioned, and cancellation at volume, concurrency race probes, accessibility/visual QA and the explanation/heatmap/UI legs of C1 were never executed. They are listed exactly in *Open items* below. Nothing unexecuted is marked PASS.

## Evidence, and which of it is authoritative

| Evidence | Where | Standing |
|---|---|---|
| **Development-machine PostgreSQL 18 qualification** | Windows Development machine, PostgreSQL **18.6**, pgvector **0.8.6**, port 5433, qualification database `mavi_test`; clean tree; SHA `5f516662…` repository-reachable | **Authoritative — PASS.** The only PostgreSQL 18 result that closes a gate |
| **Development-machine real-worker acceptance** | Same machine, live database `mavi_dev`, real RTMDet + ByteTrack path | **Authoritative — PASS**, including restart persistence |
| Earlier independent PostgreSQL 18 pass | PostgreSQL 18.6 on Ubuntu 24.04.4 | **Superseded, non-authoritative.** A real run whose named commit was not repository-reachable; kept in the performance report as history only |
| Repair/handoff container runs | PostgreSQL **16.15** | **Engineering observations only.** PostgreSQL 16 cannot qualify |

The three qualification evidence files — `plan-qualification.json`, `analytics-unit-throughput.json`, `heatmap-envelope.json` — each report status `qualification evidence` and are tied to `5f516662…`. They are held outside the repository by the operator, with SHA-256 hashes recorded alongside them, and are deliberately **not** committed: evidence artefacts belong with the Development-machine record, not in Git.

## Why the measured SHA still describes the integrated head

PR #71 was integrated into PR #70 by **fast-forward**, so PR #70's history contains `5f5166628b0c4af04cc8f7efcd40f7022f5095c4` itself — not a replay, cherry-pick or merge of it. Every commit after it on this branch changes documentation only. That is checked, not asserted: `git diff 5f516662 HEAD` over every path outside `docs/` is empty. The executable qualification semantics that produced the evidence are therefore byte-identical in the integrated head.

## Formal exit gate (plan §25)

| # | Requirement | Status |
|---|---|---|
| 1 | Stage-1 functional acceptance met | **NOT MET** — depends on items 2, 8, 9 and 13 below |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **PARTIAL.** `SemanticAcceptanceTests` proves exact hand-derived answers across trajectory → facts → §S search → §T aggregate. The explanation, heatmap and UI legs are **not** in the exact-answer trace. The real-worker run corroborates those layers on real data but is not a hand-derived C1 comparison |
| 3 | PostgreSQL 18 plans and timings for every §S predicate and §T aggregate at 10^5 facts | **PASS.** `PlanQualificationTests` on PostgreSQL 18.6, 110,000 relevant facts, status `qualification evidence`, SHA `5f516662…`. The harness fails closed unless every §S case reaches its predicate's fact table and every measurement captured SQL and a real `EXPLAIN` plan |
| 4 | Analytics-unit duration and rows for (a) the Development corpus and (b) a synthetic 1,000-Track run | **PARTIAL.** (b) **PASS**: 1,000 Tracks, 1,000 analysed, 0 unavailable, unit `Completed`, ≈3.11 s (≈3.11 ms/Track); rows written 1,000 outcomes, 4,000 zone summaries, 185 zone visits, 1,391 line crossings, 1,000 motion summaries. (a) The real-video unit ran to `Analysed` on the Development machine, but its duration and rows-written figures were not recorded |
| 5 | Aggregate scale qualification, including 10^5-fact cases | **PASS** as a recorded measurement — the nine §T cases (three bucket sizes × unfiltered/Person/Vehicle) ran inside the same qualifying `PlanQualificationTests` at 110,000 facts. The P2 disposition that depends on these figures is item 7 |
| 6 | Heatmap 50-run/candidate envelope recorded, and both fan-out limits explicitly decided | **PASS.** `TheHeatmapIsTimedAtItsFrozenFanOutEnvelope`: 50 covered runs, 2,000 candidate Tracks, 2,000 contributing, 48,000 samples, status `qualification evidence`. **Decision: RETAIN both the 50-run and the 2,000-Track limits** — the product completed its full envelope with every integrity expectation met, and one machine's speed is not a reason to widen a resource guard. Not measured: plan §10's 1/5/10/25-run sweep, per-phase read/SHA/decode/grid timings, and cancellation latency |
| 7 | No demonstrated N+1/unbounded DB/evidence-I/O path remains | **NOT MET.** No N+1 — query count is constant in geometry, held by an always-on test. The aggregate read's **unbounded materialisation P2 remains OPEN**: its required retain/bound decision needs the §T rows-materialised, allocation and latency figures from the authoritative `plan-qualification.json`, which are not yet recorded here |
| 8 | Cancellation/failure proven at realistic volume | **NOT EXECUTED.** Failure and cancellation are tested on a one-Track world only; no harness runs them against the C3 corpus |
| 9 | Snapshot/revision consistency proven under concurrency | **NOT EXECUTED.** Barrier ordering tests exist; the deterministic race probes do not |
| 10 | Incomplete/unknown never appears as observed zero | **PASS**, by existing tests on the Slice 4–6 surfaces |
| 11 | Browser parser matches the normalised-coordinate contract | **PASS** — fixed test-first; one shared rule; complement tests guard the closed interval |
| 12 | Security/resource review has no open P1/P2 | **NOT MET** — the item-7 P2 is open. No P1 |
| 13 | Operator workflow / accessibility / visual QA pass | **PARTIAL.** The real-worker run exercised Camera → Scene Configuration → Processing/readiness → evidence explanation → Analytics Activity → Heatmap on real data. The Search → Investigation leg was not reported. **Accessibility and visual QA at 1366/1440/1920/~2560 were not executed** |
| 14 | Development offline/real-worker acceptance recorded with no undeclared dependency | **PARTIAL — real-worker acceptance PASS, restart persistence PASS.** Not recorded: the plan §17 verification that no undeclared Internet fetch occurred, and the exact package/runtime identities of the run. The run used one real video (`2min.mp4`); the parent plan's evidence line asks for the **three scripted videos**, which were not run |
| 15 | No policy-violating dependency/runtime drift | **PASS** — zero files differ across `*.csproj`, `package.json`, lockfiles and `config/dependencies/`; `verify_repo.py` green |
| 16 | Relevant suites and exact-head CI green | **PENDING.** Local suites below; exact-head CI is reported on PR #70 for the final integrated head only |
| 17 | Documentation reflects measured reality, limits and known limitations | **PASS** for these documents at this head |
| 18 | Independent cold review clean of P1/P2 | **NOT MET** while the item-7 P2 is open |
| 19 | No unresolved material review thread | **PENDING** — see PR #70 and PR #71 |
| 20 | Post-merge critical verification on `main` green | **NOT APPLICABLE YET** — PR #70 is not merged |

## Development-machine real-worker acceptance

| Check | Observed |
|---|---|
| Input | Real video `2min.mp4`, camera CAM-04 / G4 |
| Worker path | Real RTMDet detector; real ByteTrack tracker; existing sealed Tracks and trajectories reused |
| Scene | Revision 2 with 1 zone and 1 trip line |
| Analysis request | Explicit queue through the existing API for the latest runs: first call `created: 1`, repeat call `alreadyReady: 1` — idempotent, as designed |
| Readiness | Processing UI showed **Analysed** |
| Evidence Review | Status Analysed; identity *Scene revision 2 · Engine v1*; reference point *Box centre*; one real Track with *Zone 1 · 1 visit · dwell 2s*, no line crossing, heading *Up (image direction)*, *Never stationary*; trajectory and geometry overlays rendered against the real video |
| Activity (stored window, 20 Sep 2025) | 12 distinct Person Tracks, 0 Vehicle Tracks, non-zero minute buckets, peak 7 Tracks in the 1-minute view |
| Heatmap | 3,002 trajectory samples, 12 contributing Tracks, grid 64 × 36, busiest cell 986 samples, provenance Revision 2 / Engine v1, coverage *All 1 run analysed* |
| Restart persistence | `Mavi.Api` restarted; the same analytics, Revision 2 identity, zone facts, Activity values and Heatmap were all still present |

**Real-worker Development acceptance: PASS. Restart persistence: PASS.**

The Activity and Heatmap agree with each other and with Evidence Review on the same population and identity: 12 Person Tracks in Activity, 12 contributing Tracks in the Heatmap, both under Revision 2 / Engine v1 with complete coverage.

## Open items that stand between this head and closure

1. **P2 — aggregate materialisation (items 7, 12, 18).** Record the §T rows-materialised, allocation and latency figures from the authoritative `plan-qualification.json`, then take the explicit retain/bound decision the security review requires. No performance objective was frozen before measurement (plan §5), so this decision cannot be a pass/fail against a target and has to be an explicit, reasoned disposition.
2. **Cancellation and failure at realistic volume (item 8)** — harness not written.
3. **Deterministic concurrency race probes (item 9)** — not written.
4. **Accessibility and visual QA at four widths (item 13)**, and the Search → Investigation leg of the operator workflow.
5. **C1 explanation/heatmap/UI legs (item 2).**
6. **Development-corpus unit duration and rows (item 4a).**
7. **Offline no-undeclared-fetch verification, runtime identities, and the three scripted videos (item 14).**
8. **Exact-head CI, thread closure and post-merge verification (items 16, 19, 20).**

## Validation of the integrated head

Executed in the repair/handoff container on **PostgreSQL 16.15**. Ordinary-suite results only; none is qualification evidence — that is the Development-machine run above.

Domain 195 passed; Application 369 passed; Integration 649 passed, 2 failed of 651 — both `DatabaseStartupMigrationTests` asserting the PostgreSQL 18 prerequisite against 16.15; `verify_repo.py` passed; frontend unchanged since PR #70's CI-validated `aa17a19`; dependency surface unchanged. Details in `2026-09-22-scene-analytics-s7-performance.md` §7.

## History

- **Slice 7, first pass.** Browser parser `[0,1]` parity; C1 corpus; the qualification corpus and harnesses; the N+1 guard; the reconciled obligation register; the P2.
- **Harness defects, three rounds.** An invisible corpus from locally issued visibility sequences; a half-sized default corpus and four sibling false greens; and §S measurements that called the non-analytic search and so exercised no predicate at all. All fixed, and replaced by the fail-closed `QualificationVerdict` mechanism. Details in the performance report §3–3c.
- **Provenance round.** An earlier PostgreSQL 18 pass named an unreachable commit. The harness now refuses qualification from a dirty tree or an unresolvable SHA (performance report §3d). That pass is superseded by the Development-machine run on `5f516662…`.
