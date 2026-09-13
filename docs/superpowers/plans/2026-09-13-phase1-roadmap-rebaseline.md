# Phase-1 Roadmap Re-baseline — 13 September 2026

**Status:** Authoritative Phase-1 roadmap. Task 13 is complete and Task 14 is the active backend task.

**Original re-baseline commit:** `f7f13183fd0119be58a63bac2c9fbac580ff719d`

**Task-14 planning baseline:** Task 13 merged as PR #30 at `928b31b8b947c2da5ab7869f09213c88bc063dc4`.

## Purpose

The original Phase-1 plan in `2026-09-08-visual-intelligence-memory.md` numbered result persistence as Task 11, Track/evidence APIs as Task 12, and React work as Tasks 13–14. During implementation, Tasks 11 and 12 were deliberately consumed by production-runtime hardening work that became prerequisite to operating the real RTMDet/ByteTrack worker safely:

- **Actual Task 11:** runtime supervisor, readiness gating, bounded recovery, watchdog containment, execution-lane dispatch, and production worker composition.
- **Actual Task 12:** reproducible offline runtime bundles, exact runtime locks, supply-chain verification, and exact-head qualification evidence.

Both are complete and merged into the Phase-1 integration branch. The original result-persistence and search work remains unimplemented.

This document removes the numbering ambiguity and defines one authoritative remaining Phase-1 sequence.

## Current merged capability

At the re-baseline commit MAVI already has:

1. Managed MP4 import and video metadata/catalog persistence.
2. Worker lease, heartbeat and failure control-plane APIs.
3. Deterministic Task-9 processing and attempt-scoped secure artifact publication.
4. Qualified RTMDet + class-separated ByteTrack production adapters.
5. Production runtime supervision and recovery.
6. Reproducible offline runtime bundles and qualified Windows/Linux CPU runtime locks.

The remaining critical backend gap is successful result acceptance. `WorkerRunner` still ends a successful analytical attempt using the deliberate placeholder failure `task9_result_submission_not_implemented` because no authoritative completion endpoint/persistence transaction exists yet.

## Authoritative remaining sequence

| Task | Authoritative scope | Primary dependency |
|---|---|---|
| **Task 13** | Validated, atomic vision-result completion and persistence — **Complete** | Actual Tasks 11–12 complete |
| **Task 14** | Track search and evidence-content APIs — **Active** | Task 13 durable intelligence |
| **Task 15** | React application foundation, Cameras, Import and Processing UI | Stable existing APIs + Task 13 processing completion |
| **Task 16** | React Visual Search and Evidence Review | Task 14 Track/evidence APIs |
| **Task 17** | Phase-1 end-to-end hardening, qualification closure, ground truth and offline acceptance | Tasks 13–16 |

This sequence supersedes older future-task numbering in earlier planning documents. Historical records of what completed Tasks 9–12 did remain valid.

## Deferred Task-10 continuation work

The Task-10 detailed plan previously used future labels “Task 13 Hosted Adapter CI”, “Task 14 Real Qualification”, and “Task 15 Closure”. Those labels are superseded by this re-baseline.

The engineering work is not discarded:

- hosted Windows/Linux adapter regression coverage remains required;
- real-model/offline/CCTV/recovery/performance qualification remains required;
- exact-head final regression and closure remain required.

Unless a focused earlier gate requires them, these items are now consolidated into **Task 17 Phase-1 hardening and qualification closure**. Task 13 must preserve all existing runtime and offline-bundle qualification gates but must not make new GPU/CCTV/performance qualification claims.

## Release-process rule learned from Task 12

All future runtime/release-affecting work shall use this controlled sequence:

**implementation frozen → deterministic artifacts generated → metadata rebound → evidence attested**

The stages are separate:

1. **Implementation**
   - make source-code changes;
   - run focused tests and the normal quality gate;
   - resolve implementation review findings;
   - freeze the implementation head.

2. **Deterministic artifacts**
   - generate wheels/bundles/locks only from the frozen implementation head;
   - retain exact source identities and hashes.

3. **Metadata rebind**
   - update runtime locks, manifests, qualification metadata and other hash-bound records only after deterministic artifacts exist;
   - do not mix unrelated implementation corrections into rebind commits.

4. **Evidence attestation**
   - run fresh exact-head qualification/offline gates against the rebound metadata;
   - record run/job/artifact/head identities;
   - merge only after all required exact-head gates and review findings are clean.

If implementation changes after the freeze, downstream generated artifacts, metadata binding and attestation from the previous freeze are invalid and must be regenerated.

## Branch and review discipline

For each remaining task:

- create one topic branch from the accepted merged integration head;
- use small cohesive commits rather than multiple competing heads;
- open one PR;
- keep implementation commits separate from any later generated-artifact/rebind/evidence commits;
- use expected-head protection for merge;
- verify the merged target tree and clean obsolete topic branches after merge.

## No premature frontend work

React feature work must not invent or own operational semantics that belong to the backend.

In particular, do not begin Visual Search/Evidence Review before Track/evidence APIs exist, and do not treat “processing finished in Python” as authoritative completion before Task 13 commits Tracks/Artifacts/status transitions in PostgreSQL.

## Source of truth

For remaining Phase-1 sequencing:

1. this re-baseline document controls task numbering;
2. `2026-09-13-task-13-vision-result-persistence.md` records the completed Task-13 implementation baseline;
3. `2026-09-13-task-14-track-search-evidence-apis.md` controls Task-14 implementation;
4. older task plans remain historical design/evidence records unless explicitly updated to reference this re-baseline.
