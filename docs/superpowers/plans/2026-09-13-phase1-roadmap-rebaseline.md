# Phase-1 Roadmap Re-baseline — 13 September 2026

**Status:** Authoritative Phase-1 roadmap. Tasks 13–16 are complete and Task 17 is the active final Phase-1 task.

**Original re-baseline commit:** `f7f13183fd0119be58a63bac2c9fbac580ff719d`

**Task-15 planning baseline:** Task 14 merged as PR #31 at `3e0382185d6a3a1907870226af3561ff97f2ba8f`.

**Task-15 completion:** PR #33 squash-merged at `abe0b16f11fad0227efe742ce01211b9ddf689c2` after exact-head Quality Gate #709 and final Codex review reported no major issues on implementation head `96e72a6cd87d20cbc1f2cd4eab186f65232a620a`.

**Task-16 completion:** PR #36 squash-merged at `e877dcac9efaefe4f935fa50b2913e806b197d27` after exact-head MAVI Quality Gate #783 succeeded and final Codex review reported no major issues on reviewed implementation head `2301d0cad5ead5c634abf4438bb7b3a617887bac`. The prior confidence-preservation P2 was root-caused and closed before the final review; unresolved review threads at merge were zero.

## Purpose

The original Phase-1 plan in `2026-09-08-visual-intelligence-memory.md` numbered result persistence as Task 11, Track/evidence APIs as Task 12, and React work as Tasks 13–14. During implementation, Tasks 11 and 12 were deliberately consumed by production-runtime hardening work that became prerequisite to operating the real RTMDet/ByteTrack worker safely:

- **Actual Task 11:** runtime supervisor, readiness gating, bounded recovery, watchdog containment, execution-lane dispatch, and production worker composition.
- **Actual Task 12:** reproducible offline runtime bundles, exact runtime locks, supply-chain verification, and exact-head qualification evidence.

Both are complete and merged into the Phase-1 integration branch. Task 13 subsequently completed authoritative result acceptance/persistence, and Task 14 completed Track search, Track detail, source-video streaming and accepted-evidence read APIs.

This document removes the numbering ambiguity and defines one authoritative remaining Phase-1 sequence.

## Current merged capability

At the current Task-17 planning baseline MAVI has:

1. Managed MP4 import and video metadata/catalog persistence.
2. Worker lease, heartbeat and failure control-plane APIs.
3. Deterministic Task-9 processing and attempt-scoped secure artifact publication.
4. Qualified RTMDet + class-separated ByteTrack production adapters.
5. Production runtime supervision and recovery.
6. Reproducible offline runtime bundles and qualified Windows/Linux CPU runtime locks.
7. Authoritative Task-13 successful result completion, evidence sealing, atomic intelligence persistence and runtime provenance.
8. Task-14 structured Track search with stable monotonic cursor snapshots, Track detail, source-video streaming and secure accepted-evidence content APIs.

The critical backend Phase-1 path and complete first operator workflow are now present. Task 15 delivered the React application foundation, Cameras, Import and Processing workflow, explicit processing contracts, recoverable duplicate-import semantics, same-origin ASP.NET Core/IIS hosting, bounded polling and configured-timezone rendering. Task 16 then delivered bookmarkable Visual Search, opaque-cursor result pagination, evidence-linked direct Review routes, native source-video playback, configured-zone time reconstruction, robust route/filter preservation and production SPA deep-link qualification over the Task-14 Track/evidence APIs.

The only remaining Phase-1 work is **Task 17 end-to-end hardening, qualification closure, controlled ground truth and offline acceptance**. Task 17 is an acceptance/release-hardening task, not a new analytical-feature task.

## Authoritative remaining sequence

| Task | Authoritative scope | Primary dependency |
|---|---|---|
| **Task 13** | Validated, atomic vision-result completion and persistence — **Complete** | Actual Tasks 11–12 complete |
| **Task 14** | Track search and evidence-content APIs — **Complete** | Task 13 durable intelligence |
| **Task 15** | React application foundation, Cameras, Import and Processing UI — **Complete** | Stable existing APIs + Task 13 processing completion |
| **Task 16** | React Visual Search and Evidence Review — **Complete** | Task 14 Track/evidence APIs + Task 15 frontend foundation |
| **Task 17** | Phase-1 end-to-end hardening, qualification closure, controlled ground truth and offline acceptance — **Active** | Tasks 13–16 |

This sequence supersedes older future-task numbering in earlier planning documents. Historical records of what completed Tasks 9–12 did remain valid.

## Deferred Task-10 continuation work

The Task-10 detailed plan previously used future labels “Task 13 Hosted Adapter CI”, “Task 14 Real Qualification”, and “Task 15 Closure”. Those labels are superseded by this re-baseline.

The engineering work is not discarded:

- hosted Windows/Linux adapter regression coverage remains required;
- real-model/offline/CCTV/recovery/performance qualification remains required;
- exact-head final regression and closure remain required.

Unless a focused earlier gate requires them, these items are now consolidated into **Task 17 Phase-1 hardening and qualification closure**. Tasks 15–16 must preserve all existing runtime and offline-bundle qualification gates but must not make new GPU/CCTV/performance qualification claims.

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

## Frontend boundary discipline

React feature work must not invent or own operational semantics that belong to the backend.

Task 14 established the Track/evidence read boundary, Task 13 established authoritative processing completion, Task 15 established the shared frontend shell/API/query/error/time/hosting foundation, and Task 16 completed Visual Search and Evidence Review without bypassing backend authority. Task 17 must preserve these boundaries while proving the complete operator and offline deployment path under controlled acceptance evidence.

## Source of truth

For remaining Phase-1 sequencing:

1. this re-baseline document controls task numbering;
2. `2026-09-13-task-13-vision-result-persistence.md` records the completed Task-13 implementation baseline;
3. `2026-09-13-task-14-track-search-evidence-apis.md` records the completed Task-14 implementation baseline;
4. `2026-09-14-task-15-react-foundation-import-processing.md` records the completed Task-15 implementation baseline and closure evidence;
5. `2026-09-14-task-16-react-visual-search-evidence-review.md` records the completed Task-16 implementation and acceptance evidence;
6. `2026-09-14-task-17-phase1-hardening-qualification-acceptance.md` is the authoritative Task-17 plan and branches from accepted integration head `e877dcac9efaefe4f935fa50b2913e806b197d27`;
7. older task plans remain historical design/evidence records unless explicitly updated to reference this re-baseline.
