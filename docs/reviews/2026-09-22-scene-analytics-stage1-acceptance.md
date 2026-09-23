# Spatial & Temporal Track Analytics — Stage-1 acceptance status

**Date:** 2026-09-22
**Branch:** `feature/scene-analytics-s7-hardening-acceptance` (PR #70), with PR #71's qualification-harness branch integrated by fast-forward
**Baseline:** `main@11d3450fbc9ca01ca7e7ad75d090ae951f420668`
**Qualification candidate (measured):** `5f5166628b0c4af04cc8f7efcd40f7022f5095c4`
**Governing gate:** `docs/superpowers/plans/2026-09-22-scene-analytics-s7-hardening-acceptance.md` §25 — the numbering below is that section's, item for item
**Operator actions still owed:** `docs/runbooks/scene-analytics-stage1-development-acceptance.md`

---

## Verdict

**Stage 1 functional acceptance is closed.**

Exit-gate items **1–19 are PASS**. Item 20 remains **NOT APPLICABLE** until PR #70 is merged and the post-merge critical verification runs on `main`.

The final operator evidence was completed on the Development machine while disconnected from the network:
- **Action C — PASS.** All three scripted scenarios completed through import → fixture worker → analytics host → `scripted_corpus.py check`, with `ok` for `line-crossing`, `zone-dwell-exit`, and `stationary-then-depart`.
- **Action D.2 — PASS.** The disconnected session exercised Processing, Evidence Review, Analytics Activity and Heatmap with the browser Network panel open; only `localhost` / `127.0.0.1` requests were observed.

The session also exposed and closed two real Development defects before acceptance was completed: floating-point confidence finalisation on long fixture Tracks, and TanStack Query pausing local loopback queries/mutations when `navigator.onLine` was false. Both were repaired with discriminating tests before the final offline run.

Nothing unexecuted is marked PASS.

## Evidence, and which of it is authoritative

| Evidence | Where | Standing |
|---|---|---|
| **Development-machine PostgreSQL 18 qualification** | Windows Development machine, PostgreSQL **18.6**, pgvector **0.8.6**, canonical Development service `MAVI-Dev-PostgreSQL-18` (`127.0.0.1:55433`), qualification database `mavi_test`; clean tree; SHA `5f516662…` repository-reachable | **Authoritative — PASS** |
| **Development-machine real-worker acceptance** | Same machine, live database `mavi_dev`, real RTMDet + ByteTrack path | **Authoritative — PASS**, including restart persistence |
| Correctness tests added in this pass | Ordinary integration, application and frontend suites; locally on PostgreSQL 16.15, in CI on PostgreSQL 18 | **Correctness evidence** — they assert outcomes, not timings, and hold on any supported server |
| Earlier independent PostgreSQL 18 pass | PostgreSQL 18.6 on Ubuntu 24.04.4 | **Superseded, non-authoritative** — kept in the performance report as history only |
| Container measurements | PostgreSQL **16.15** | **Engineering observations only** — PostgreSQL 16 cannot qualify |

The three qualification evidence files — `plan-qualification.json`, `analytics-unit-throughput.json`, `heatmap-envelope.json` — each report status `qualification evidence` and are tied to `5f516662…`. They are held outside the repository by the operator with SHA-256 hashes, and are deliberately not committed.

**Port.** An earlier transcription recorded the qualification server as "port 5433". That was an error, now corrected to the canonical service. The evidence file does not capture host or port (`QualificationGate` records server version, pgvector and planner settings only), so the port was never a measured fact. 5433 has not been a MAVI port since 2026-09-15: it appeared only in three bootstrap commits that day and was replaced the same day by `a625588`. Nothing in `config/`, the setup contracts (`Test-MaviSetupContracts.ps1` enforces 55433) or `appsettings.Development.json` uses it. The one MAVI PostgreSQL 18 service on the Development machine is `MAVI-Dev-PostgreSQL-18` on 55433, and it hosts both `mavi_dev` and `mavi_test`. CI's service container uses 5432 and is not the Development machine.

## The measured SHA and the current head

PR #71 was integrated by **fast-forward**, so PR #70's history contains `5f5166628b0c4af04cc8f7efcd40f7022f5095c4` itself.

Executable code has changed after that SHA:
- **Test files:** `RealisticVolumeResilienceTests`, `ConcurrencyRaceProbeTests`, `DatabaseOutageRecoveryTests`, `ScriptedCorpusTests`, a C1 contract test in `SemanticAcceptanceTests`, and the frontend client, artifact and query-default tests.
- **Test fixtures and two visual-QA states.**
- **Development tooling:** `tools/vision/dev/scripted_corpus.py`, a scenario switch in `fixture_worker_harness.py`, and `tools/qualification/`.
- **One production change, in the browser only:** a 10 s bound on local GET/HEAD reads (`src/web/mavi-web/src/api/client.ts`, shared by `api/artifacts.ts`).

None of this touches what was qualified:
- **Server code is unchanged:** `git diff --stat 5f516662 HEAD -- src/platform` is empty.
- **The qualification harnesses and their corpus are unchanged:** `PlanQualificationTests`, `ThroughputQualificationTests`, `QualificationCorpus`, `QualificationGate`, `QualificationVerdict` and `SqlCapture` are byte-identical to the measured SHA.

The new tests only read `QualificationCorpus`. The PostgreSQL 18 evidence therefore still describes the server code it measured, and this change requires no qualification rerun. (The browser parser `[0,1]` fix is also production code, but it predates the measured SHA.)

## Formal exit gate (plan §25)

| # | Requirement | Status |
|---|---|---|
| 1 | Stage-1 functional acceptance met | **PASS** — Action C and the disconnected D.2 operator path both completed successfully on the Development machine |
| 2 | C1 agrees across trajectory/facts/search/explanation/aggregate/heatmap/UI | **PASS.** Trajectory → facts → §S → §T as before; now also the explanation (track detail), the pinned geometry names and the heatmap (an exact matrix), read through the real HTTP API, compared byte for byte with a committed golden, and the same golden driven through the real explanation, overlay and heatmap components with the heatmap recomputed from the authored path. Details: semantic acceptance §5 |
| 3 | PostgreSQL 18 plans and timings for every §S predicate and §T aggregate at 10^5 facts | **PASS** — `PlanQualificationTests` on PostgreSQL 18.6, 110,000 relevant facts, `qualification evidence`, SHA `5f516662…` |
| 4 | Analytics-unit duration and rows for (a) the Development corpus and (b) a synthetic 1,000-Track run | **PASS.** (a) Development corpus: `Completed`, attempt 1, 414 ms, 12 analysed / 0 unavailable, 12 outcomes, 8 zone visits, 12 zone summaries, 1 crossing, 12 motion summaries, 3,002 samples. (b) synthetic 1,000-Track run: 1,000 analysed, 0 unavailable, `Completed`, ≈3.11 s; 1,000 outcomes, 4,000 zone summaries, 185 visits, 1,391 crossings, 1,000 motion summaries. |
| 5 | Aggregate scale qualification, including 10^5-fact cases | **PASS** as a recorded measurement — the nine §T cases ran inside the qualifying `PlanQualificationTests` at 110,000 facts. The disposition that depends on them is item 7 |
| 6 | Heatmap 50-run/candidate envelope recorded, and both fan-out limits explicitly decided | **PASS — RETAIN both the 50-run and the 2,000-Track limits.** Not measured, and not claimed: the 1/5/10/25-run sweep and per-phase timings |
| 7 | No demonstrated N+1/unbounded DB/evidence-I/O path remains | **PASS for the Stage-1 qualified envelope.** No N+1. The aggregate-materialisation P2 is dispositioned **RETAIN** after the authoritative PostgreSQL 18 evidence satisfied the predeclared rule in all nine §T cases; work remains linear in facts inside the requested window and 10⁵ relevant facts/request is the qualified envelope. Evidence-I/O remains bounded by the heatmap guards and is proved cancellable/fail-closed at the envelope (item 8). |
| 8 | Cancellation/failure proven at realistic volume | **PASS.** `RealisticVolumeResilienceTests`: the heatmap cancelled at the 500th of 2,000 artefact reads and failed at the 1,337th, and a 1,000-Track unit cancelled at its 400th Track and faulted at its 600th — no partial answer returned or published, no read after the interruption, coverage *pending* rather than zero, the lease honoured, reclaim with a fresh token, the stale claim fenced, and every retry equal to the uninterrupted answer. The §11 PostgreSQL restart/reconnect case is **PASS** (action F below) |
| 9 | Snapshot/revision consistency proven under concurrency | **PASS.** `ConcurrencyRaceProbeTests`: a writer observed waiting on the barrier behind a stopped aggregate, with the reader's answer unmoved and the next answer complete; two publications landing in the heatmap's scope-to-evidence gap without moving its map; an activation observed waiting behind an in-flight unit commit, with no cross-revision reading. A negative probe (barrier removed) makes the first fail. With the existing pinned-pagination, supersession and ownership-fencing tests, this covers the races plan §12 names; the one publication path not raced directly is a **processing-run** completion, which takes the same exclusive barrier through the same `AcquireCompletionExclusiveAsync` statement as the unit commit that is raced — an inference from shared code, stated as one |
| 10 | Incomplete/unknown never appears as observed zero | **PASS** — existing tests, and now at volume: a cancelled or failed unit reads as *pending* |
| 11 | Browser parser matches the normalised-coordinate contract | **PASS** |
| 12 | Security/resource review has no open P1/P2 | **PASS.** No P1. The aggregate-materialisation P2 is closed as dispositioned RETAIN within the qualified envelope. |
| 13 | Operator workflow / accessibility / visual QA pass | **PASS.** Accessibility and visual QA **PASS**: 53 analytics-related states × 4 widths, zero automated findings, human capture pass, no P1/P2 (three P3s). The remaining real-data **Search → Investigation → Evidence Review** leg was executed on the H.264 MOT17-CROWD run: the same Person Track opened from Search into the inspector and Evidence Review, source video played, Revision 1 / Engine v1 identity agreed, and the saved zone overlay rendered against the track evidence. |
| 14 | Development offline/real-worker acceptance recorded with no undeclared dependency | **PASS.** Real-worker acceptance, restart persistence and runtime identity passed. The three scripted scenarios were then completed through the fixture-worker control plane and real analytics host with `check = ok` for all three. The final session was disconnected: Processing, Evidence Review, Activity and Heatmap all worked, and DevTools showed only `localhost` / `127.0.0.1` requests. |
| 15 | No policy-violating dependency/runtime drift | **PASS** — zero files differ from `main` across `*.csproj`, `package.json`, lockfiles and `config/dependencies/`; the new tools are standard-library Python and plain SQL; `verify_repo.py` green |
| 16 | Relevant suites and exact-head CI green | **PASS on executable head `f620485`** — Task 17 Acceptance Validation, Task 10 Runtime Qualification and MAVI Quality Gate were all green before this evidence-only documentation update. Exact-head CI on the final documentation head remains the merge gate. |
| 17 | Documentation reflects measured reality, limits and known limitations | **PASS** after the reconciliation in *Independent closure review* below |
| 18 | Independent cold review clean of P1/P2 | **PASS.** The closure review below found no P1. Its P2s were in the operator procedure and the test and documentation claims, not in product code, and each is fixed in this pass |
| 19 | No unresolved material review thread | **PASS** — PR #70 has zero unresolved threads; PR #71 is closed as superseded |
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

## Development-machine acceptance actions

Each is an exact procedure in `docs/runbooks/scene-analytics-stage1-development-acceptance.md`. Record the result here; do not record a PASS for an action not run.

| Action | Closes | Result |
|---|---|---|
| A — transcribe the authoritative §T figures, apply the approved decision rule | 7, 12, 18 | **PASS — RETAIN.** Evidence SHA-256 `3e418ab9fca8dccf8b939cf356e6cde979db682b8d96bade0a799163c667275a`; worst total 4,405 ms; worst allocation 42.6 MiB; 10 DB queries in all 9 cases. |
| B — Development-corpus unit record from `mavi_dev` | 4a | **PASS.** Completed, 414 ms, 12 analysed / 0 unavailable, 12 outcomes; integrity equation holds. |
| C — the three scripted videos through the real worker and analytics host, `check` = `ok` for each | 14 | **PASS.** The regenerated H.264 High-profile videos were verified `ok`. `SCR-LINE` completed through the fixture worker and real analytics host with `line-crossing -> ok`. A wrong-scenario first `SCR-ZONE` run was deliberately rejected as acceptance evidence; a byte-distinct re-encode was imported and processed with `MAVI_FIXTURE_SCENARIO=zone-dwell-exit`, producing the expected eastward heading, ~7 s Pad dwell/loitering, no line crossing, and `zone-dwell-exit -> ok`. `SCR-STILL` was likewise re-encoded/imported and processed with `stationary-then-depart`, producing the expected rightward heading, one ~7 s stationary interval, no zone visit or line crossing, and `stationary-then-depart -> ok`. |
| D.1 — runtime identity of the real-worker runs | 14 | **PASS.** Recorded on the H.264 MOT17 real-worker runs rather than the runbook's `2min.mp4`; any real-worker run satisfies the action. Development SQL output shows pipeline `phase1-v1`, detector `rtmdet-m-coco-phase1 1.0.0`, tracker `ByteTrack 2.6.0`, worker `dev-worker-01`, runtime variant `windows-x86_64-cuda`, actual device `cuda:0`, resolution reason `cuda_selected`, qualification id `rtmdet-m-coco-phase1-v1`, runtime profile `mmdetection-phase1-v1`, pipeline profile `phase1-detection-tracking-v1`, checkpoint SHA-256 persisted, dependency versions persisted, GPU `NVIDIA GeForce GTX 1650 Ti` with CUDA runtime 12.4 / driver 576.83, and MAVI commit `401af70d0207095e13b4d5ef935e4ccc24237b6b`. |
| D.2 — disconnected run, same-origin network only | 14 | **PASS.** The final operator session was completed with the machine disconnected. After the TanStack Query `networkMode: 'always'` repair, the Processing page loaded normally offline and local queries/mutations continued over loopback. The scripted acceptance path completed offline, and Evidence Review, Analytics Activity and Heatmap were opened with DevTools Network inspection enabled. The operator confirmed that all requests stayed on `localhost` / `127.0.0.1`; no remote host or undeclared Internet dependency appeared. |
| E — Search → Investigation on real data | 13 | **PASS.** Run on MOT17-CROWD H.264 rather than the runbook's `2min.mp4` camera. On MOT17-CROWD-H264, Search opened a real Person Track into the inspector and Evidence Review; source video playback worked, Track identity and camera agreed, scene status was **Analysed**, Revision 1 / Engine v1 matched, and the zone overlay rendered. Activity reported **coverage complete** with 29 distinct Person Tracks; Heatmap reported 6,210 trajectory samples from 29 Tracks on a 64 × 36 grid, busiest cell 146, with **All 1 run analysed**. |
| F — PostgreSQL restart/reconnect | plan §11 | **PASS, on two pieces of evidence that together cover the criterion.**<br>• **Machine half** (Development machine): `MAVI-Dev-PostgreSQL-18` was stopped and restarted under the same `Mavi.Api` process, which then answered the database-backed `/api/cameras` with 200 without a restart.<br>• **Outage half** (`DatabaseOutageRecoveryTests`, on every head): the API runs on Kestrel through a relay that drops every connection and refuses new ones. While the database is unreachable, Activity (`/aggregates`) and Heatmap answer 5xx with no host, port, database, user, `Npgsql`, exception or stack text. When it comes back, the same process returns byte-identical answers to those given before the outage (only the per-request snapshot sequence is excluded). The test fails if the outage is a no-op or if the body carries the exception.<br>The manual outage-half observation was not made; see *PostgreSQL restart/reconnect evidence* for what that leaves. |

## PostgreSQL restart/reconnect evidence

The Development PostgreSQL service `MAVI-Dev-PostgreSQL-18` was stopped and started while `Mavi.Api` remained the same running process. A direct PostgreSQL connection succeeded after restart. Visual Studio had paused the debuggee on the transient database exception, which made Kestrel appear unresponsive while still listening. Pressing **Continue** resumed the same API process. Without restarting Mavi.Api, `GET /api/health` and `GET /api/cameras` both returned HTTP 200. That shows reconnect on the real service. It does not show outage behaviour: the debugger was holding the process during the outage, and `/api/cameras` does not exercise the analytics read path.

The outage half is proved by `DatabaseOutageRecoveryTests` instead, as described under action F. Two limits of that test are recorded:
- It runs in the `Testing` environment, which, like Production, has no developer exception page. In `Development` an unhandled exception is rendered by ASP.NET Core's developer exception page, so a raw API request during an outage shows the exception. That is a framework diagnostic available only in `Development`. The operator UI never shows it: each surface renders its own error state with Retry, and never the response body. It was not measured on the machine and is recorded as P3.
- The failure is a bare 500, not a typed problem code. That is recorded as P3, not changed, because it would be a contract change in a hardening slice.

## Runtime identity evidence

The Development-machine real-worker identity query was executed against `mavi_dev`. The H.264 MOT17 runs persisted the expected production provenance: RTMDet-M COCO Phase 1 detector, ByteTrack 2.6.0, `phase1-v1` pipeline, `windows-x86_64-cuda` runtime, actual device `cuda:0`, `cuda_selected` resolution, qualification/runtime/pipeline profile identities, checkpoint digest, dependency versions, and GPU identity. The observed GPU was **NVIDIA GeForce GTX 1650 Ti**, CUDA runtime **12.4**, driver **576.83**. The persisted MAVI commit was `401af70d0207095e13b4d5ef935e4ccc24237b6b`.

## Supplemental real-world MOT17 Development evidence

A browser-compatible H.264 regression corpus was created from MOT17 clips and processed through the normal qualified CUDA worker. On camera `MOT17-CROWD`, the H.264 crowd clip was re-analysed against active Scene Revision 1. Evidence Review showed **Analysed**, `Scene revision 1 · Engine v1`, the configured zone overlay, persisted trajectory/bounding-box evidence and playable source video. Analytics Activity reported **coverage complete** with 29 distinct Person Tracks. Heatmap reported **6,210 trajectory samples**, **29 contributing Tracks**, a **64 × 36** grid and busiest cell **146**, with provenance `Revision 1 / Engine v1` and **All 1 run analysed**. This supplements, but does not replace, the deterministic scripted-corpus acceptance required by action C.

## Known limitations recorded by this pass

- **A slow crossing is not a crossing.** By the frozen rule (plan §K), a Track that lingers in the on-line band for more than k = 3 samples is not credited with a crossing. At 25 fps that is a traverse slower than about 0.0033 of the frame per frame. Found by the scripted corpus, recorded rather than changed.
- The aggregate's work is linear in the facts inside the requested window; the Stage-1 decision is **RETAIN** within the qualified 10⁵-fact envelope. This limitation remains documented even though the P2 is closed as dispositioned.

## Validation of this head

Executed in the review container on **PostgreSQL 16.15** at the head this pass pushes. These are ordinary-suite results only; none is qualification evidence.

- **Domain:** 195 passed.
- **Application:** 373 passed.
- **Integration:** 658 passed, 2 failed of 660. The two failures are `DatabaseStartupMigrationTests`, which assert the PostgreSQL 18 prerequisite against 16.15 and pass in CI's PostgreSQL 18 job. The new `DatabaseOutageRecoveryTests` passes.
- **Python vision:** 1,806 passed, 16 skipped; the skips need `torch`, which is not installed here.
- **Frontend:** 836 tests in 56 files; typecheck clean; production build succeeds.
- **`verify_repo.py`:** passed.
- **Scripted corpus:** `generate` + `verify` is `ok` for all three videos: High profile, 300 frames, no B-frames.
- **Dependency surface:** unchanged.
- **Visual QA:** 212 combinations, zero automated findings, at the earlier head. It was not re-run here, because this pass changes no rendered state.

Every new test was mutation-checked, and each fails against the defect it guards:
- the unbounded artefact read;
- a timer left running;
- a pre-aborted caller ignored;
- the query retry removed;
- a premature timeout;
- an outage that does nothing;
- an exception written into the response body.

## History

- **Slice 7, first pass.** Browser parser `[0,1]` parity; C1 corpus; the qualification corpus and harnesses; the N+1 guard; the reconciled register; the P2.
- **Harness defects, three rounds**, and the fail-closed `QualificationVerdict` mechanism (performance report §3–3c).
- **Provenance round.** The earlier PostgreSQL 18 pass named an unreachable commit; the harness now refuses dirty or unresolvable provenance. Superseded by the Development-machine run on `5f516662…`.
- **Integration.** PR #71 fast-forwarded into PR #70; Development-machine qualification and real-worker acceptance recorded.
- **Remaining-obligations pass.** Items 2, 8 and 9 closed; item 13's accessibility/visual QA executed; the scripted corpus built and engine-proved; exact operator actions prepared for everything that needs the Development machine; the P2 left open and blocked, with a decision rule proposed before its figures are seen.
- **Development evidence.** A (P2 → RETAIN), B, D.1 and E recorded by the owner; the machine half of F; the offline cold-start defect and the bounded-read fix.
- **Independent closure review.** Findings and fixes below; F closed by a deterministic outage test; the runbook's C/D.2 procedure repaired.

## Offline acceptance findings and repairs

During disconnected Development acceptance, the Scene Editor could stay on **Loading scene…** indefinitely when a local API read got no response during cold start. The browser API client now bounds every local GET/HEAD read at 10 s:
- the caller's cancellation still wins, with its own reason;
- the timer is cleared once the whole body has been read;
- writes and uploads are not bounded;
- a server error stays a server error;
- trajectory-artefact reads (`api/artifacts.ts`) share the same bound;
- video is excluded, because the player streams it.

A timed-out read is retried once by the query defaults and then shown with its own Retry, so the worst case before an operator sees the failure is about 21 s (10 s, a 1 s retry delay, 10 s). That retry is intentional and pinned by `app/queryClient.test.ts`: it is what recovers a read that stalled during cold start.

The server honours the abort. The analytics endpoints bind the request-abort token through the barrier transaction and every query, so a browser timeout ends the server's work too.

After the fix, the operator repeated an **offline cold start** and Camera Scene loaded. Network inspection showed no request to any origin other than `localhost`/`127.0.0.1`.

**The Processing-page symptom was a paused query, not a stalled read.** With the adapters disabled, `/processing` stayed on its skeleton, while the same page loaded once connectivity returned. The cause was TanStack Query's default `networkMode: 'online'`: while `navigator.onLine` is false, it pauses every query and mutation *before sending a request*, so the bounded read never started. It is now `'always'` for queries and mutations (`app/queryClient.ts`), and `app/queryClient.test.ts` sets the browser offline and requires the query and the mutation to run. Both tests fail with the default mode. The Development proxy was also moved to `http://127.0.0.1:62153` (no name lookup, no TLS), as a separate configuration hardening; see `docs/runbooks/local-development.md`.

**Not established:** why a local read got no response during cold start. The bound and the retry recover it, but the cause is not identified. It is recorded as a known limitation and not treated as fixed.

## Independent closure review

A cold review of the whole PR against `main`. It covered the .NET test harnesses, the Python and SQL tools, the browser client, and every evidence document. Each finding below was verified against the code before it was acted on.

**P1: none.**

**P2, all fixed in this pass:**
- **Action D.2 could not be executed as written.** It said to *repeat* action C, but `generate` is byte-deterministic and `ux_artifacts_source_video_sha256` is unique, so the second import is refused as `video_duplicate`. The runbook now performs action C itself while disconnected.
- **The scripted videos were likely not browser-playable.** CRF 0 makes x264 emit High 4:4:4 Predictive, which browser decoders commonly refuse, so Evidence Review (C.7, D.2) could fail on a correct run. The generator now emits High profile, CRF 1, no B-frames. `verify` still passes all 300 frames of all three videos, and still reports 250 problems for a mismatched scenario.
- **Trajectory reads were outside the bounded-read fix.** `api/artifacts.ts` called `fetch` directly, so Evidence Review could hang on the stall the fix addresses. It now shares the bound. `artifacts.test.ts` fails without it.
- **The C1 test claimed complements it does not check.** `SemanticAcceptanceTests` said the direction, zone-relation and identity complements were rejected. C1 crosses both ways under one identity, so it cannot express them. The comments and semantic report §3 now say they are held by `TrackSearchAnalyticsRepositoryTests`, which does check them.
- **Documentation contradictions.** Action F was marked PASS on reconnect alone while other reports said NOT EXECUTED. Several documents also claimed "no production source file changed", recorded a stale port, or carried stale item-13/C1/P2 status. All are reconciled.

**P3, fixed:**
- **The summariser accepted an incomplete file.** It could accept another evidence file, or one missing §T rows, and print a missing figure as `0`. It now exits 1 unless exactly nine §T cases carry every figure the rule reads, and prints `missing`.
- **The unit-record SQL mislabelled its duration.** It called the time from the first claim `final_attempt_duration_ms`. It is now `claim_to_completion_ms`, with the caveat that it equals the final attempt only when `attempt_count = 1`. The recorded 414 ms unit was attempt 1, so its figure stands.

**P3, recorded, not changed:**
- The qualification harness's predicate-coverage guard is not structurally linked to the measured-case list; today every key is measured.
- The race probes' `pg_locks` wait counts any ungranted advisory lock, and one `await` there is unbounded.
- The heatmap-cancel read counter increments after a successful read.
- The unit retry is compared as row counts, not fact content.
- `MAVI_UPDATE_GOLDEN=1` is not refused under CI.
- `AnalyticsQueryShapeTests` holds the run count fixed.
- Plan timings are single cold samples.
- `scripted_corpus.py check` compares zone and line names but not the revision's geometry.
- The fixture harness is not bound to the leased job's scenario; the runbook now says to import and process one video at a time.
- The Development-only exception page and the untyped 500 during an outage (action F).
- The unexplained cold-start stall.


## Final scripted/offline operator evidence — 23 Sep 2026

The owner completed the remaining Stage-1 operator gate on the Windows Development machine while disconnected from the network.

- `line-crossing`: fixture worker completed; analytics reached **Analysed**; `scripted_corpus.py check` returned **`ok`**.
- `zone-dwell-exit`: the first completed asset had been leased under the wrong fixture scenario and was not counted. A fresh byte-distinct re-encode was imported to `SCR-ZONE`, processed with `MAVI_FIXTURE_SCENARIO=zone-dwell-exit`, and showed the expected facts in Evidence Review: Pad visit, about 7 s dwell with loitering against the 5 s threshold, heading Right/E, no line crossing, never stationary. `check` returned **`ok`**.
- `stationary-then-depart`: a fresh byte-distinct re-encode was imported to `SCR-STILL`, processed with `MAVI_FIXTURE_SCENARIO=stationary-then-depart`, and showed the expected facts: no zone visit, no line crossing, heading Right/E, one stationary interval of about 7 s. `check` returned **`ok`**.
- With the machine still disconnected, Processing, Evidence Review, Analytics Activity and Heatmap worked as intended. DevTools Network showed requests only to `127.0.0.1` / `localhost`.

This closes actions **C** and **D.2** and therefore Stage-1 exit-gate items **1** and **14**.
