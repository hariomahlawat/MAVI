# Cold Review — Stage 2 S1.4 Hardening and Qualification Plan

**Date:** 2026-09-24  
**Reviewed plan:** `docs/superpowers/plans/2026-09-24-stage2-s1-4-hardening-qualification-implementation.md`  
**Planning baseline:** `main@81b43dec32bec0c5e876d2df372503016c05dbdf`  
**Review scope:** plan correctness, acceptance completeness, qualification identity, workflow reality, offline semantics and closure truth.

## Verdict

**No open P1 or P2. The plan is suitable to proceed after this documentation PR is merged.**

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
