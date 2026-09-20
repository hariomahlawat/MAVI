# Phase-1 Roadmap Re-baseline — 18 September 2026

**Status:** Authoritative Phase-1 roadmap. Tasks 13–17 are complete. **Task 18 — Production Qualification and Phase-1 Closure is active.**

**Current planning baseline:** `feature/task-10-rtmdet-bytetrack@557d5ccc356ae39766d95eec93ce0fdf49fdef31`

## Completed sequence

| Task | Scope | Status |
|---|---|---|
| Task 13 | Atomic Vision result completion and persistence | Complete |
| Task 14 | Track search and evidence-content APIs | Complete |
| Task 15 | React foundation, Cameras, Import and Processing | Complete |
| Task 16 | React Visual Search and Evidence Review | Complete |
| Task 17 | Phase-1 hardening, acceptance tooling, runtime progress/watchdog/recovery hardening | Complete |
| Task 18 | Production qualification and Phase-1 closure | **Active** |

## Current merged capability

The current integration baseline includes:

1. managed video import and authoritative processing state;
2. RTMDet detection + ByteTrack tracking;
3. worker lease/heartbeat/failure control plane;
4. attempt-local progress and recovery/watchdog hardening;
5. atomic Track/evidence persistence and search/review APIs;
6. React operator workflows;
7. one-click offline Development/Production setup architecture;
8. owned PostgreSQL + pgvector and application-local native media tools;
9. deterministic Offline Binary Kit;
10. independently content-addressed Runtime Binary Pack and Model Pack;
11. first-party Application / Release Overlay;
12. six exact-head Vision qualification workflows;
13. successful Windows CPU functional processing and job-level recovery evidence.

## Task-18 re-baseline decision

The original Task-18 planning PR #39 was created from `57f9efd5090f01486ff8a197c6a4aaeda285d065` before the subsequent deployment/runtime/component work. It is historical input and must not be merged as the current execution plan.

The authoritative Task-18 plan is now:

`docs/superpowers/plans/2026-09-18-task-18-phase1-production-qualification-rebaseline.md`

Its independent review is:

`docs/reviews/2026-09-18-task-18-rebaseline-cold-review.md`

## Immediate Task-18 objective

The Qualification Readiness Pack now exists, ADR-008 defines the deployment profiles, and PR #46 implements the profile-aware qualification toolchain.

The immediate decision is to select the first Production profile(s) to qualify:

- **P1** — single-host Windows GPU;
- **P2** — Windows Operational/Data + Linux GPU worker;
- **P3** — single-host Windows CPU.

After profile selection, freeze:

- acceptance corpus and thresholds;
- exact profile-specific Production prerequisites;
- supported-update artifact/policy, if update proof remains mandatory;
- final application artifact;
- Offline Binary Kit identity;
- exact selected Runtime Pack(s) and Model Pack;
- final Production setup/bundle identity.

No authoritative final qualification run begins while a mandatory readiness item applicable to the selected profile remains unresolved. GPU evidence is not a universal blocker: it is required only for P1/P2.

## Evidence already retained

PR #44 provides useful Windows CPU subsystem evidence:
- component reuse;
- environment verification;
- worker/model readiness;
- real RTMDet/ByteTrack processing;
- worker-loss retry;
- persisted completion.

This evidence reduces uncertainty but does not replace clean-machine Production installation or final Production-topology acceptance.

## Capability-development sequencing

Task 18 remains the independent Production-qualification stream. It does **not** define the order of new product capabilities.

For capability development, `docs/superpowers/plans/capability-roadmap.md` is authoritative. With PR #49 merged (`ed1acf4`), the current product sequence is capability-first: Spatial & Temporal Track Analytics, then Visual Attributes, expanded object classes, ANPR/OCR, visual similarity/ReID and event analytics. Audited review/cases are deferred until the underlying intelligence is rich enough to make those workflows useful; live RTSP/VMS integration remains a later platform phase. Development capabilities merged under that roadmap do not become Production-qualified by being merged; Task 18 decides that separately.

## Source of truth

For current Phase-1 sequencing:

1. this roadmap controls task status;
2. completed Task 13–17 plans remain historical implementation/evidence records;
3. the 18 Sep 2026 Task-18 re-baseline plan controls remaining Phase-1 qualification work;
4. current architecture/ADR/runbook documents control operational behavior;
5. older Task-18 PR #39 is superseded and must not be merged into the current integration branch.
