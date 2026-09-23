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

- the aggregate-materialisation **P2 is closed as RETAIN**: the authoritative PostgreSQL 18 figures were transcribed and all nine §T cases satisfy the predeclared rule (worst total 4,405 ms; worst allocation 42.6 MiB; exactly 10 DB queries in every case);
- the Development-corpus unit timing (item 4a) is **PASS**: Completed, 414 ms, 12 analysed / 0 unavailable, 12 outcomes, 8 visits, 12 zone summaries, 1 crossing, 12 motion summaries and 3,002 trajectory samples;
- runtime identity (D.1) and Search → Investigation on real data (E) are **PASS**;
- the remaining operator-only closure evidence is the scripted videos through the worker/analytics host, disconnected no-fetch, and PostgreSQL restart/reconnect. The scripted corpus itself has been generated and pixel-verified, and its three scene revisions were saved on the canonical Development database. These remaining actions are not marked PASS without execution evidence.

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
| 1 | Stage-1 functional acceptance met | **NOT MET** — depends on item 14 (and on 16 and 19 at the final head) |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **PASS.** Trajectory → facts → §S → §T as before; now also the explanation (track detail), the pinned geometry names and the heatmap (an exact matrix), read through the real HTTP API, compared byte for byte with a committed golden, and the same golden driven through the real explanation, overlay and heatmap components with the heatmap recomputed from the authored path. Details: semantic acceptance §5 |
| 3 | PostgreSQL 18 plans and timings for every §S predicate and §T aggregate at 10^5 facts | **PASS** — `PlanQualificationTests` on PostgreSQL 18.6, 110,000 relevant facts, `qualification evidence`, SHA `5f516662…` |
| 4 | Analytics-unit duration and rows for (a) the Development corpus and (b) a synthetic 1,000-Track run | **PASS.** (a) Development corpus: `Completed`, attempt 1, 414 ms, 12 analysed / 0 unavailable, 12 outcomes, 8 zone visits, 12 zone summaries, 1 crossing, 12 motion summaries, 3,002 samples. (b) synthetic 1,000-Track run: 1,000 analysed, 0 unavailable, `Completed`, ≈3.11 s; 1,000 outcomes, 4,000 zone summaries, 185 visits, 1,391 crossings, 1,000 motion summaries. |
| 5 | Aggregate scale qualification, including 10^5-fact cases | **PASS** as a recorded measurement — the nine §T cases ran inside the qualifying `PlanQualificationTests` at 110,000 facts. The disposition that depends on them is item 7 |
| 6 | Heatmap 50-run/candidate envelope recorded, and both fan-out limits explicitly decided | **PASS — RETAIN both the 50-run and the 2,000-Track limits.** Not measured, and not claimed: the 1/5/10/25-run sweep and per-phase timings |
| 7 | No demonstrated N+1/unbounded DB/evidence-I/O path remains | **PASS for the Stage-1 qualified envelope.** No N+1. The aggregate-materialisation P2 is dispositioned **RETAIN** after the authoritative PostgreSQL 18 evidence satisfied the predeclared rule in all nine §T cases; work remains linear in facts inside the requested window and 10⁵ relevant facts/request is the qualified envelope. Evidence-I/O remains bounded by the heatmap guards and is proved cancellable/fail-closed at the envelope (item 8). |
| 8 | Cancellation/failure proven at realistic volume | **PASS.** `RealisticVolumeResilienceTests`: the heatmap cancelled at the 500th of 2,000 artefact reads and failed at the 1,337th, and a 1,000-Track unit cancelled at its 400th Track and faulted at its 600th — no partial answer returned or published, no read after the interruption, coverage *pending* rather than zero, the lease honoured, reclaim with a fresh token, the stale claim fenced, and every retry equal to the uninterrupted answer. The §11 PostgreSQL-restart case is separate and **NOT EXECUTED** (runbook §F) |
| 9 | Snapshot/revision consistency proven under concurrency | **PASS.** `ConcurrencyRaceProbeTests`: a writer observed waiting on the barrier behind a stopped aggregate, with the reader's answer unmoved and the next answer complete; two publications landing in the heatmap's scope-to-evidence gap without moving its map; an activation observed waiting behind an in-flight unit commit, with no cross-revision reading. A negative probe (barrier removed) makes the first fail. With the existing pinned-pagination, supersession and ownership-fencing tests, this covers the races plan §12 names; the one publication path not raced directly is a **processing-run** completion, which takes the same exclusive barrier through the same `AcquireCompletionExclusiveAsync` statement as the unit commit that is raced — an inference from shared code, stated as one |
| 10 | Incomplete/unknown never appears as observed zero | **PASS** — existing tests, and now at volume: a cancelled or failed unit reads as *pending* |
| 11 | Browser parser matches the normalised-coordinate contract | **PASS** |
| 12 | Security/resource review has no open P1/P2 | **PASS.** No P1. The aggregate-materialisation P2 is closed as dispositioned RETAIN within the qualified envelope. |
| 13 | Operator workflow / accessibility / visual QA pass | **PASS.** Accessibility and visual QA **PASS**: 53 analytics-related states × 4 widths, zero automated findings, human capture pass, no P1/P2 (three P3s). The remaining real-data **Search → Investigation → Evidence Review** leg was executed on the H.264 MOT17-CROWD run: the same Person Track opened from Search into the inspector and Evidence Review, source video played, Revision 1 / Engine v1 identity agreed, and the saved zone overlay rendered against the track evidence. |
| 14 | Development offline/real-worker acceptance recorded with no undeclared dependency | **PARTIAL.** Real-worker acceptance **PASS**; restart persistence **PASS**. The three scripted videos: generated and pixel-verified, their expected facts proved against the real engine — the **run through the real worker is NOT EXECUTED** (runbook §C). Runtime identity **PASS** (runbook §D.1; *Runtime identity evidence* below). No-undeclared-fetch: **NOT EXECUTED**, disconnected procedure prepared (runbook §D.2) |
| 15 | No policy-violating dependency/runtime drift | **PASS** — zero files differ from `main` across `*.csproj`, `package.json`, lockfiles and `config/dependencies/`; the new tools are standard-library Python and plain SQL; `verify_repo.py` green |
| 16 | Relevant suites and exact-head CI green | **PENDING** — local suites below; exact-head CI is reported on PR #70 for the final pushed head only |
| 17 | Documentation reflects measured reality, limits and known limitations | **PASS** for these documents at this head |
| 18 | Independent cold review clean of P1/P2 | **PASS with respect to code/resource findings.** The carried P2 is closed as dispositioned; the bounded review found no new P1/P2. Final merge-readiness still depends on the remaining operator-only actions and exact-head CI after this documentation update. |
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
| A — transcribe the authoritative §T figures, apply the approved decision rule | 7, 12, 18 | **PASS — RETAIN.** Evidence SHA-256 `3e418ab9fca8dccf8b939cf356e6cde979db682b8d96bade0a799163c667275a`; worst total 4,405 ms; worst allocation 42.6 MiB; 10 DB queries in all 9 cases. |
| B — Development-corpus unit record from `mavi_dev` | 4a | **PASS.** Completed, 414 ms, 12 analysed / 0 unavailable, 12 outcomes; integrity equation holds. |
| C — the three scripted videos through the real worker and analytics host, `check` = `ok` for each | 14 | **PARTIAL.** All three videos generated and pixel-verified `ok`; three cameras/scenes created and saved as revision 1. Import/worker/analytics-host/`check` evidence still pending. |
| D.1 — runtime identity of the real-worker runs | 14 | **PASS.** Development SQL output on the H.264 MOT17 real-worker runs shows pipeline `phase1-v1`, detector `rtmdet-m-coco-phase1 1.0.0`, tracker `ByteTrack 2.6.0`, worker `dev-worker-01`, runtime variant `windows-x86_64-cuda`, actual device `cuda:0`, resolution reason `cuda_selected`, qualification id `rtmdet-m-coco-phase1-v1`, runtime profile `mmdetection-phase1-v1`, pipeline profile `phase1-detection-tracking-v1`, checkpoint SHA-256 persisted, dependency versions persisted, GPU `NVIDIA GeForce GTX 1650 Ti` with CUDA runtime 12.4 / driver 576.83, and MAVI commit `401af70d0207095e13b4d5ef935e4ccc24237b6b`. |
| D.2 — disconnected re-run, same-origin network only | 14 | *pending* |
| E — Search → Investigation on real data | 13 | **PASS.** On MOT17-CROWD-H264, Search opened a real Person Track into the inspector and Evidence Review; source video playback worked, Track identity and camera agreed, scene status was **Analysed**, Revision 1 / Engine v1 matched, and the zone overlay rendered. Activity reported **coverage complete** with 29 distinct Person Tracks; Heatmap reported 6,210 trajectory samples from 29 Tracks on a 64 × 36 grid, busiest cell 146, with **All 1 run analysed**. |
| F — PostgreSQL restart/reconnect | plan §11 | **PASS.** The canonical Development service `MAVI-Dev-PostgreSQL-18` was stopped and restarted while the same `Mavi.Api` process remained running. PostgreSQL recovered on `127.0.0.1:55433`; after continuing the Visual Studio debugger from its transient database-exception break, the unchanged API process returned HTTP 200 from both database-independent `/api/health` and database-backed `/api/cameras`. No Mavi.Api restart was required. Debugger suspension is recorded as a Development-only observation, not an application reconnect failure. |

## PostgreSQL restart/reconnect evidence

The Development PostgreSQL service `MAVI-Dev-PostgreSQL-18` was stopped and started while `Mavi.Api` remained the same running process. A direct PostgreSQL connection succeeded after restart. Visual Studio had paused the debuggee on the transient database exception, which temporarily made Kestrel appear unresponsive while still listening; pressing **Continue** resumed the same API process. Without restarting Mavi.Api, `GET /api/health` and `GET /api/cameras` both returned HTTP 200. This satisfies the reconnect/recovery intent of plan §11; the debugger pause is a Development-host observation and should be excluded from production-liveness interpretation.

## Runtime identity evidence

The Development-machine real-worker identity query was executed against `mavi_dev`. The H.264 MOT17 runs persisted the expected production provenance: RTMDet-M COCO Phase 1 detector, ByteTrack 2.6.0, `phase1-v1` pipeline, `windows-x86_64-cuda` runtime, actual device `cuda:0`, `cuda_selected` resolution, qualification/runtime/pipeline profile identities, checkpoint digest, dependency versions, and GPU identity. The observed GPU was **NVIDIA GeForce GTX 1650 Ti**, CUDA runtime **12.4**, driver **576.83**. The persisted MAVI commit was `401af70d0207095e13b4d5ef935e4ccc24237b6b`.

## Supplemental real-world MOT17 Development evidence

A browser-compatible H.264 regression corpus was created from MOT17 clips and processed through the normal qualified CUDA worker. On camera `MOT17-CROWD`, the H.264 crowd clip was re-analysed against active Scene Revision 1. Evidence Review showed **Analysed**, `Scene revision 1 · Engine v1`, the configured zone overlay, persisted trajectory/bounding-box evidence and playable source video. Analytics Activity reported **coverage complete** with 29 distinct Person Tracks. Heatmap reported **6,210 trajectory samples**, **29 contributing Tracks**, a **64 × 36** grid and busiest cell **146**, with provenance `Revision 1 / Engine v1` and **All 1 run analysed**. This supplements, but does not replace, the deterministic scripted-corpus acceptance required by action C.

## Known limitations recorded by this pass

- **A slow crossing is not a crossing.** By the frozen rule (plan §K), a Track that lingers in the on-line band for more than k = 3 samples is not credited with a crossing. At 25 fps that is a traverse slower than about 0.0033 of the frame per frame. Found by the scripted corpus, recorded rather than changed.
- The aggregate's work is linear in the facts inside the requested window; the Stage-1 decision is **RETAIN** within the qualified 10⁵-fact envelope. This limitation remains documented even though the P2 is closed as dispositioned.

## Validation of this head

Executed in the repair container on **PostgreSQL 16.15**. Ordinary-suite results only; none is qualification evidence.

Domain **195** passed; Application **373** passed; Integration **657 passed, 2 failed of 659** — both `DatabaseStartupMigrationTests` asserting the PostgreSQL 18 prerequisite against 16.15; frontend **826** tests, typecheck clean, production build succeeds; `verify_repo.py` passed; evidence-assembler guard coverage 52/52; visual QA 212 combinations, zero automated findings; dependency surface unchanged.

## History

- **Slice 7, first pass.** Browser parser `[0,1]` parity; C1 corpus; the qualification corpus and harnesses; the N+1 guard; the reconciled register; the P2.
- **Harness defects, three rounds**, and the fail-closed `QualificationVerdict` mechanism (performance report §3–3c).
- **Provenance round.** The earlier PostgreSQL 18 pass named an unreachable commit; the harness now refuses dirty or unresolvable provenance. Superseded by the Development-machine run on `5f516662…`.
- **Integration.** PR #71 fast-forwarded into PR #70; Development-machine qualification and real-worker acceptance recorded.
- **Remaining-obligations pass.** Items 2, 8 and 9 closed; item 13's accessibility/visual QA executed; the scripted corpus built and engine-proved; exact operator actions prepared for everything that needs the Development machine; the P2 left open and blocked, with a decision rule proposed before its figures are seen.


## Offline cold-start recovery

During disconnected Development acceptance, the Scene Editor could remain indefinitely on **Loading scene…** when a local API read stayed pending during cold start. The shared browser API client was hardened so ordinary local GET/HEAD requests are bounded to 10 seconds while caller cancellation is preserved and mutating requests remain unbounded by this read timeout. Regression coverage was added for timeout, composed caller cancellation, and mutation behaviour. The operator then repeated an **offline cold start** and confirmed the Camera Scene now loads successfully. Browser Network inspection had already shown no requests to any origin other than localhost/127.0.0.1.
