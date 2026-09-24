# Cold Review — Stage 2 S1.4 Hardening and Qualification Plan

**Date:** 2026-09-24  
**Reviewed plan:** `docs/superpowers/plans/2026-09-24-stage2-s1-4-hardening-qualification-implementation.md`  
**Planning baseline:** `main@81b43dec32bec0c5e876d2df372503016c05dbdf`  
**Review scope:** plan correctness, acceptance completeness, qualification identity, workflow reality, offline semantics and closure truth.

## Verdict

**First pass (below): "no open P1 or P2".** The independent second pass (§ Second pass) overturns this. It found three P1 and sixteen P2 against the repository mechanics. All are resolved by documentation amendments to the plan in PR #84 (revision 2). After those amendments, no P1/P2 remains open against the plan.

The review treated the S1.4 plan as a qualification contract rather than a feature brief and checked it against:

- Stage-2 acceptance register B1–B6;
- the parent S1 plan;
- Stage-2 qualification protocol;
- the current Task 10 Runtime Qualification workflow;
- MAVI Quality Gate;
- Task 12 Offline Runtime Pack;
- Task 17 Acceptance Validation;
- the current pipeline profile and RTMDet qualification record.

## Findings

### P1

None.

### P2

One ambiguity was found and fixed during review.

**R1 — post-merge Task-10 evidence could have been satisfied by the wrong commit.**  
The initial S1.4 draft required post-merge Task-10 verification but did not say what to do when a documentation/evidence-only merge does not match Task-10 path filters. That could encourage citing a green PR-head or ancestor run as post-merge evidence.

**Resolution:** the plan now requires the existing `workflow_dispatch` to run explicitly against the **merge SHA on `main`** when no automatic push run starts. An ancestor or pre-merge PR-head run cannot satisfy the post-merge gate.

No P2 remains open.

### P3 / clarifications retained deliberately

1. **No invented universal RSS SLA.** B2 uses a structural/shape acceptance criterion: retired history must not create unbounded live-memory growth at a fixed live-Track envelope. This is stronger and more defensible than inventing a hardware-specific RAM threshold during qualification.
2. **No profile mutation for rebinding.** The final plan checks the actual pipeline-profile SHA against the existing qualification record. It does not edit profile behavior merely to obtain a fresh identity.
3. **Hosted CI is not called “offline.”** Task 12 remains the runtime-pack build/verification gate; the disconnected S1 operator path is explicitly a host/local qualification action.
4. **CUDA/E2E remains a non-claim when hardware is unavailable.** B6 requires truthfully pending evidence, not synthetic inheritance from pre-S1 runs.
5. **S1 closure is scoped.** Passing B1–B6 does not advance Stage-2 C/D/E/F/G acceptance rows.

## Acceptance coverage check

| Acceptance | Plan coverage | Review |
|---|---|---|
| B1 selector determinism | §5 | Complete |
| B2 retirement/live memory | §6 | Complete |
| B3 bounds/admission/body | §7 | Complete |
| B4 v3/digest/store | §8 | Complete |
| B5 read/UI/operator | §9 | Complete |
| B6 Task-10/rebinding | §10 | Complete |
| disconnected path | §11 | Explicit and correctly separated from hosted CI |
| performance/resource record | §12 | Complete |
| stop/requalification semantics | §14 | Complete |
| closure reconciliation | §15–§16 | Complete |

## Final assessment

The plan is implementation-grade because it now specifies:

- the identity being qualified;
- what must be rerun versus what may remain pending;
- exact categories of retained evidence;
- how hard bounds are proved without pathological CI allocation;
- how real-video and disconnected acceptance differ from mocked/hosted checks;
- how a behavior-bearing defect invalidates affected qualification evidence;
- how post-merge verification is tied to the actual merge SHA;
- what S1 closure does and does not claim.

No further planning amendment is required before execution unless repository state changes materially before S1.4 starts.


---

# Second pass — independent adversarial review

**Reviewed head:** PR #84 at `82d6a710ee384342c9c2dc6b934c57ef1f05f347`, baseline `main@81b43dec32bec0c5e876d2df372503016c05dbdf` (both verified).  
**Method:** every claim was checked against the repository at that head:
- code: selector, encoder, `VideoProcessor`, `ProcessingResultStore`, the offline bundle builder and the offline-variant tooling;
- tests and their skip conditions;
- workflows: Task 10, Quality Gate, Task 12, Task 17;
- records: the pipeline profile and its SHA, the RTMDet qualification record and the parameter note.

The first pass was not relied on.

## Why the first pass's "Complete" was wrong

Its coverage table marked every B-item "Complete" after reviewing the prose only. Several of the plan's statements are not true of the code:
- "Task 10 covers all relevant S1 behavior paths" is false;
- the B2 criterion contradicts the implementation's designed retention;
- the B4 PASS text claims compensation that the store deliberately does not perform;
- the disconnected run could have used a Runtime Bundle containing different worker code.

## P1

**P1-1 — the disconnected run could execute code other than the measured head** (plan §11).
- *Evidence:* the plan allowed reusing the existing Offline Binary Kit "merely for a new application commit". But the MAVI Vision Runtime Bundle is source-bound:
  - `tools/vision/build_offline_bundle.py` validates `sourceCommit` against the checkout;
  - `_verify_mavi_wheel_source` binds the embedded `mavi-vision` wheel to the source tree;
  - `docs/runbooks/local-development.md` states RTMDet inference uses this source-bound bundle.
- *Why it matters:* a disconnected "S1" run on an older bundle runs older worker code, so the evidence would be false.
- *Resolution:* the Runtime Bundle must be built from the measured SHA, with `sourceCommit` = measured SHA and the wheel SHA recorded. Binary-kit reuse requires identity checks. The install profile is named: Development, not Production. This is stop condition 13.

**P1-2 — the B2 memory criterion contradicts the design and is not falsifiable** (plan §6.2).
- *Evidence:* `VideoProcessor.process` keeps `finalised: dict[str, ProcessedTrack]` until completion, one descriptor per retired Track, capped at 10,000 (`MAXIMUM_TRACKS_PER_RESULT`). Memory therefore grows monotonically with retired history *by design*. The plan's "no monotonic unbounded growth attributable to trajectories/candidates" either fails a correct implementation, or needs a subjective attribution RSS cannot make.
- *Also:* the planned "synthetic/fixture workload" could run through `FixtureTracker`, which cannot see native ByteTrack state.
- *Resolution:* the criterion is decomposed and quantitative:
  - per-live-Track accounting ≤ 544 KiB;
  - a `tracemalloc` per-retired-Track slope with a 16 KiB ceiling, which must be independent of duration and crop size. The workload uses crops of at least 32 KiB so the ceiling discriminates;
  - USS/PSS plateaus without adding `psutil`;
  - the completion peak;
  - the native ByteTrack workload.

**P1-3 — no mechanical binding between the measured SHA and the closure (merge) SHA** (plan §2, §10.4).
- *Evidence:* the plan says moving the head invalidates the gate, but defines neither the behavior-bearing surface nor a check at merge. The post-merge Task-10 rerun re-proves only the CPU suites, not RSS, bounds, sealing, real-video or disconnected evidence. S1 could be recorded closed at a merge SHA that contains unmeasured behavior.
- *Resolution:* §2.1 defines the behavior-bearing surface; §2.2 maps changed paths to the B-items they invalidate; under §2.3, B1–B6 PASS at the merge SHA requires `git diff --name-only measured..merge` to leave that surface untouched, or the affected items to be rerun. The measured SHA must be on `main`, and harness and evidence PRs are separate.

## P2

1. **Cross-variant determinism undefined; Windows golden skipped** (§5.2).
   - *Evidence:* `EvidenceSelector._try_hold` admits a holder only if the encode fits the cap. `JpegLadderEncoder` promises bytes only within a variant. `GOLDEN_SHA256` pins only `("linux", "11.3.0")`, so `test_golden_bytes_per_runtime_variant` skips on `win32`. Repeat determinism is only tested in-process.
   - *Resolution:* three defined levels:
     - within a variant: separate-process runs, exact crop SHA;
     - across variants: roles must match the golden, with divergences traced;
     - golden bytes: the Windows pin lands in PR A, and until then it is an explicit non-claim.
2. **Skips could count as green; Quality Gate is not a qualified variant** (§3).
   - *Evidence:* conditional skips in the golden-bytes test, `test_measure_evidence_real_clips.py`, `test_bytetrack_runtime.py` and one POSIX-only `test_track_lifecycle.py` case. The Quality Gate runs `src/vision` tests on Python 3.13.
   - *Resolution:* record per-suite pass/skip/fail counts with the variant; a skip is never a pass.
3. **"Task 10 covers all relevant S1 behavior paths" is false** (§10.1).
   - *Evidence:* the filters omit `worker/**`, `common/control_plane.py` (v3), `common/contracts.py`, `common/lease.py` and `detection/rtmdet.py`. The suites omit `test_worker_completion_v3.py`, `test_completion_contract_bounds.py` and `test_tracker_update.py`. The parent plan's claim that S1.2 widened the filters to all of `mavi_vision/**` is also untrue.
   - *Resolution:* the statement is corrected in both plans; PR A widens the filters and suites; S1.4 always dispatches at the frozen head.
4. **`workflow_dispatch` cannot target a SHA** (§10.1, §10.4).
   - *Evidence:* dispatch runs a ref's tip, and Task 10 uses `cancel-in-progress` per ref.
   - *Resolution:* use an immutable tag at the SHA, verify the run's `head_sha`, and treat a cancelled run as no evidence.
5. **The B4 PASS text overclaims compensation** (§8).
   - *Evidence:* `ProcessingResultStore` deliberately skips compensation when rollback confirmation fails (`compensationSafe = false`). A process kill between seal and commit leaves unreferenced accepted objects. No test covers a `CommitAsync` failure or a rollback-confirmation failure.
   - *Resolution:* the PASS criterion is restated; both tests are added in PR A; never-served and replay-idempotent are proven for the non-compensable windows; the residual orphans are recorded.
6. **A fake store makes the sealing-time measurement vacuous** (§7.4).
   - *Evidence:* `DurableFilePublication` flushes per object and re-fsyncs the directory chain, inside the `FOR UPDATE` completion transaction; the vision lease is 900 s.
   - *Resolution:* measure the real store on the real filesystem at worst-case object count, with at least 2× headroom against the lease.
7. **Missing B3 boundaries** (§7).
   - *Resolution:* added the 10,001st-Track fail-before-staging, the exact per-role cap edges (worker and platform), cross-source bound agreement, staging measured against the ADR-013 5.2 GiB derivation, the completion-time peak, and both worst-shape body figures (the Python body and the .NET body without provenance).
8. **One real video, with examples picked after the fact** (§9.2).
   - *Evidence:* qualification plan §17 says Stage 2 cannot close on one successful video.
   - *Resolution:* at least two hashed clips with declared characteristics; a predeclared rule for choosing examples; the platform import path; `real-video`/`fixture` labels.
9. **The B1 real-clip "consistent with" was qualitative** (§5.3).
   - *Resolution:* exact equality with the recorded parameter-note counts (63 Tracks, 8,284 candidates) on the same input SHAs and variant.
10. **Offline isolation was assumed** (§11).
    - *Resolution:* the existing `assert_outbound_internet_unavailable` probe runs before and after, with the isolation method retained. Attempt-level capture is optional (P3-1).
11. **Qualification-record mutation path undefined** (§10.2).
    - *Evidence:* gate changes are owned by the Task-17 `promote_phase1_release.py`.
    - *Resolution:* S1.4 does not edit the RTMDet record at all, and Task-10 green is not written as detector/model qualification.
12. **Measurement quality** (§12).
    - *Resolution:* n, min/p50/p95/max, warm-up, three repeats and host identity are mandatory.
13. **Evidence retention**.
    - *Evidence:* Actions artifacts expire.
    - *Resolution:* the small Task-10 JSON records are committed with their SHA, run id and `head_sha`.
14. **Stale statuses inside PR #84.**
    - *Evidence:* the parent plan's "Current implementation state" and the implementation roadmap both still said S1.3b was "in review".
    - *Resolution:* corrected.
15. **Qualification-plan §8 items not closable in S1** (§3.1).
    - *Resolution:* the model-dependent comparison, retention decision and re-encoding impact are explicitly deferred; S1 closure is not §8 closure.
16. **The `-candidate` profile version is a latent identity trap** (§1).
    - *Evidence:* no semantics exist for the suffix, and a later rename changes the SHA.
    - *Resolution:* the qualified identity is the exact file; any version change happens before the freeze, never after.

## P3

1. Optional capture of network connection attempts during the disconnected run.
2. `psutil` is not a MAVI dependency; memory sampling uses `/proc` and `ctypes`.
3. The evidence checker ships with negative tests (§4).
4. The real-video record states whether the marker rail saturated (S1.3 R8).
5. The pre-existing Review sticky-player behaviour is recorded rather than hidden.
6. The first pass's coverage table should not be read as evidence.

## Resolution commits (PR #84)

- `0be0087` — stale S1.3 statuses and the Task-10 trigger correction;
- `324cc84` — identity, behavior-bearing surface, invalidation map, closure binding, skips and retention;
- `cac5913`, `b1c18a6` — B1–B4 made falsifiable against the implementation;
- `aa05b16` — B5/B6/offline evidence bound to the measured code; dispatch mechanics; qualification-record rule; measurement quality.

## Second-pass verdict

**READY WITH AMENDMENTS — amendments applied.** With revision 2, no P1/P2 remains open against the plan. B1–B6 remain **OPEN**. Nothing here is qualification evidence.
