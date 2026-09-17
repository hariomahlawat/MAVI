# MAVI Vision Runtime Pack Decoupling Implementation Plan

**Status:** Implementation and CPU functional qualification complete; final documentation-only exact-head CI requalification pending.

**Goal:** Decouple the approximately 600 MB MAVI Vision third-party runtime and model assets from ordinary first-party `mavi_vision` source changes while preserving exact-head qualification, offline determinism and fail-closed integrity.

**Architecture:** Deterministic component identities separate a third-party Runtime Binary Pack, a content-addressed Model Pack, and a small first-party Application/Release Overlay. The `mavi-vision` wheel is not a Runtime Pack dependency root; deterministic runtime requirements are projected from `pyproject.toml`. Installation/startup compatibility is component-fingerprint based rather than repository-commit based.

**Tech Stack:** Python 3.12, `packaging`, deterministic text/JSON manifests, PowerShell 5.1-compatible setup scripts, GitHub Actions, pytest, pip offline `--require-hashes` installs.

**Spec:** `docs/superpowers/specs/2026-09-17-runtime-pack-decoupling-design.md`

## Global constraints — final disposition

- [x] Ordinary `src/vision/mavi_vision/**/*.py` changes do not change the third-party lock or Runtime Binary Pack identity.
- [x] Application runtime dependency roots are projected deterministically; development-only dependencies are excluded.
- [x] Third-party runtime installation remains offline and hash locked.
- [x] `mavi-vision` is absent from the third-party lock/heavy runtime wheelhouse.
- [x] Runtime and Model components have independent content-derived identities.
- [x] Existing checkpoint/config integrity and compatibility validation remains fail-closed.
- [x] Legacy v1 Runtime installed state is not silently accepted as v2.
- [x] Exact-head application qualification remains mandatory when heavy components are reused.
- [x] CUDA remains unqualified; CPU qualification must not be generalized to GPU execution.

## Completed implementation work

### Task 1 — deterministic application runtime requirements projection
- [x] Deterministic projection implemented and tested, including ordering/root selection/marker handling and source-only independence.

### Task 2 — third-party-only offline lock validation
- [x] Runtime lock is explicitly third-party-only and validated against projected application runtime roots and transitive closure.

### Task 3 — component identity manifests
- [x] Runtime Pack and Model Pack identities are content-derived; application/source provenance does not contaminate heavy-component identity.
- [x] Manifest/path/symlink/undeclared-file/hash protections retained.

### Task 4 — third-party locks and runtime profile bindings
- [x] CPU locks/profile/component bindings regenerated for the decoupled architecture.
- [x] `mavi-vision` is excluded from tracked third-party Runtime Pack locks.

### Task 5 — CI split and no-heavy-rebuild invariant
- [x] Heavy Task-12 invalidation paths narrowed to material Runtime Pack inputs.
- [x] Ordinary first-party source changes are excluded from the heavy rebuild trigger.
- [x] Lightweight component-boundary verification protects the split.

### Task 6 — installed state v2 and idempotent runtime reuse
- [x] Runtime installed state v2 implemented.
- [x] Identical valid Runtime Pack is reused without staged venv replacement.
- [x] Reuse validates manifest/material identity and live interpreter identity.
- [x] Installed third-party closure is revalidated against the reviewed lock and `pip check` before reuse.

### Task 7 — Development startup component compatibility
- [x] Worker startup is bound to Runtime/Model component fingerprints and current Application Overlay.
- [x] Current checkout remains the authoritative first-party source overlay.
- [x] Live CPython identity is probed and checked.
- [x] Installed Runtime closure and Model Pack artifacts are revalidated before worker execution.

### Task 8 — Offline Binary Kit component inventory
- [x] Runtime, Model and Application Overlay ownership is separated.
- [x] Heavy components are content-addressed/reusable.
- [x] Conflicting IDs and cross-component duplicate heavy ownership are rejected.

### Task 9 — documentation and migration record
- [x] Runtime Pack / Model Pack / Application Overlay lifecycle documented.
- [x] v1 -> v2 migration and reuse behaviour documented.
- [x] Heavy-download invalidation rules documented.
- [x] Final cold-review findings and remediation recorded.

### Task 10 — full verification, cold review and functional qualification
- [x] Repository/CI qualification completed on exact implementation head `fea8820a95f00121ee04e735f3e4b53a08d074bc`.
- [x] All six required workflows green on that exact head: MAVI Quality Gate 1593; Task 10 Runtime Qualification 528; Task 12 Offline Runtime Pack 870; Task 17 Acceptance Validation 737; Vision Runtime Component Boundary 77; Vision Model Pack 35.
- [x] Source-only mutation/reuse behaviour demonstrated locally: existing Runtime Pack and Model Pack IDs/payload hashes remained unchanged while the application overlay changed.
- [x] Independent cold review completed; CR-01 Runtime closure, CR-02 live Model Pack integrity and CR-03 source-contract architecture findings resolved and requalified.
- [x] Development environment verification passed with installed v2 Runtime Pack and v1 Model Pack.
- [x] 1920x1080 2m28s functional video processed end-to-end on Windows CPU.
- [x] Unexpected worker loss caused by host sleep was recovered automatically as a new job attempt; final Attempt 3 reached 100 percent and persisted `Completed` / `Processed` with no failure code at 17 Sep 2026 23:28:14 Asia/Kolkata.
- [x] Recovery limitation documented: retry is job-level, not frame-level continuation.
- [ ] Re-establish all required exact-head CI evidence on the final documentation-only head before declaring PR #44 merge-ready.

## Remaining close-out actions

1. Wait for the documentation-only head to complete its required GitHub qualification workflows.
2. If any gate fails, inspect and correct the actual defect; do not reuse evidence from an older SHA.
3. Confirm PR #44 remains mergeable and has no unresolved review threads after the final green head.
4. Do not repeat the expensive CPU video test solely for documentation-only commits. Repeat functional qualification only if subsequent executable/runtime/model/component-boundary changes materially invalidate the recorded evidence.
5. CUDA/GPU qualification and performance optimization remain separate future work.
6. Review the meaning/handling of launcher exit code 70 observed after host sleep as a separate reliability item; do not retroactively classify it without code/log evidence.
