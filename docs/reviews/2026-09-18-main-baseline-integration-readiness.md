# Main Baseline Integration Readiness Review

**Date:** 2026-09-18  
**Target branch:** `main`  
**Source baseline:** `feature/task-10-rtmdet-bytetrack@671f98f4622c004932b862fc9b56a00c017b823b`  
**Main before integration:** `94b35518aaa0637a0b3613ce8c29ee9cd0abdf9d`  
**Purpose:** promote the current stable Phase-1 engineering baseline to `main` before beginning focused Windows-CUDA development.

## Executive decision

The current long-lived integration branch should no longer remain the de facto trunk.

At review start:

- `main` contains only the original repository bootstrap commit;
- the integration baseline is **1,486 commits ahead and 0 behind** `main`;
- the integration baseline has already passed repeated cold reviews and exact-head subsystem gates;
- PR #46 was merged into the integration baseline and its merge commit passed:
  - Task 17 Acceptance Validation #837;
  - MAVI Quality Gate #1693;
  - Task 10 Runtime Qualification #609.

Holding further engineering work outside `main` would now increase integration debt rather than reduce release risk.

## Review scope

This is a **baseline-integration review**, not an attempt to manually re-review 1,486 historical commits one by one.

The review instead checks the resulting repository tree and the controls that protect it:

- build/test composition;
- architecture boundaries;
- dependency/offline policy;
- repository binary hygiene;
- setup/offline packaging;
- migrations/data layer presence;
- Vision Runtime/Model Pack boundaries;
- Task-17 qualification tooling;
- documentation and ADR state;
- GitHub workflow coverage;
- future branch strategy.

## Repository-tree observations

The reviewed integration tree contains:

- one solution: `MAVI.sln`;
- five production .NET projects and three .NET test projects;
- React/TypeScript web application;
- Python Vision package;
- PostgreSQL/pgvector integration and tracked migrations;
- eight GitHub workflow definitions;
- MAVI Setup, Offline Binary Kit and Vision component installers;
- Runtime Pack / Model Pack / Application Overlay separation;
- Task-17/Task-18 acceptance, prerequisite, lifecycle, backup/restore and profile-aware qualification tooling;
- architecture ADRs, runbooks and independent review records.

The current tree contains no tracked archive/installer/model-weight payload by the repository's prohibited binary suffix policy. `tools/verify_repo.py` additionally enforces direct dependency declarations, architecture reference rules, prohibited tracked payloads, offline dependency policy and release/offline guardrails.

## Finding MBI-01 — HIGH — `main` was not governed by the current CI workflows

### Finding

The current workflows were scoped to the long-lived feature/integration branches. `main` was not included in their pull-request/push branch filters.

Because `main` is still the bootstrap commit, it also does not yet contain these workflows.

### Risk

Promoting the integration baseline to `main` without correcting the workflow targets would create a stable branch that is less governed than the temporary integration branch it replaces.

### Correction

On the dedicated baseline-integration branch, `main` has been added to the applicable branch filters for:

- MAVI Quality Gate;
- Task 10 Runtime Qualification;
- Task 17 Acceptance Validation;
- Task 12 Offline Runtime Pack;
- Vision Runtime Component Boundary;
- Vision Model Pack;
- Task 10 Staging Security;
- Task 14 Read Security.

The baseline PR itself must prove whether GitHub executes these newly introduced PR workflows when targeting the bootstrap `main`. No merge is authorized until the observed PR check set is reviewed and the required gates are green.

**Status: FIXED IN BASELINE PR.**

## Engineering-state boundary

Merging this baseline to `main` means:

> `main` is the stable, tested **engineering baseline** for MAVI Phase 1.

It does **not** mean:

- formal Task-18 Production qualification is complete;
- P1/P2/P3 are all Production-supported;
- Windows CUDA is already qualified;
- deployment is imminent.

Formal Production qualification remains governed by the Task-18 readiness pack and may be deferred until deployment is approaching.

## Post-merge branch policy

After this baseline is merged:

1. `main` becomes the normal engineering trunk/stable baseline.
2. New feature/fix branches start from current `main`.
3. The long-lived `feature/task-10-rtmdet-bytetrack` branch must not continue as the default development trunk.
4. Windows-CUDA engineering should begin from a fresh branch off `main`.
5. Formal Production qualification should use dedicated qualification/release branches when deployment intent and hardware are ready.
6. No future feature branch should accumulate another multi-hundred-commit divergence from `main` without deliberate release/integration checkpoints.

## Recommended immediate work after merge

The next focused engineering milestone should be **Windows CUDA Development enablement and qualification on the available Windows laptop/GPU**, while preserving CPU as the deterministic regression path.

This should initially be treated as engineering qualification rather than final P1 Production acceptance.

## Baseline PR merge criteria

The `main` integration PR may be merged only when all of the following are true:

1. PR head is unchanged from the reviewed candidate.
2. GitHub reports the PR mergeable.
3. MAVI Quality Gate is green on the exact PR head.
4. Task 17 Acceptance Validation is green on the exact PR head.
5. Task 10 Runtime Qualification is green on the exact PR head.
6. Any additional workflow triggered by the broad baseline diff is reviewed; failures are resolved rather than ignored.
7. No unresolved material review thread/comment exists.
8. No tracked binary/dependency/offline-policy regression is introduced.
9. The PR description explicitly states that this is an engineering-baseline merge, not Production acceptance.

After merge, the merge commit on `main` must be checked again for push-triggered workflows before new feature work begins.

## Review conclusion

**READY TO OPEN THE MAIN BASELINE INTEGRATION PR, SUBJECT TO EXACT-HEAD PR GATES.**

The repository should now converge on `main` rather than continue development on the historical Task-10 integration branch.
