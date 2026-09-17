# PR #44 Final Cold Review Record

Date: 2026-09-17
PR: #44 `feature/runtime-pack-decoupling`
Base: `feature/task-10-rtmdet-bytetrack`

## Final reviewed implementation checkpoint

Exact head `fea8820a95f00121ee04e735f3e4b53a08d074bc` completed all six required qualification workflows successfully immediately before functional testing:

- MAVI Quality Gate — run 1593
- Task 10 Runtime Qualification — run 528
- Task 12 Offline Runtime Pack — run 870
- Task 17 Acceptance Validation — run 737
- Vision Runtime Component Boundary — run 77
- Vision Model Pack — run 35

The functional test was therefore executed only after the exact target application head had re-established the complete six-green gate set.

## Architecture reviewed

The final cold review treated the PR as unseen code and rechecked the following trust boundaries:

1. Runtime Binary Pack is third-party-only and content-derived from runtime dependency, lock, Python/platform and native ABI inputs.
2. Model Pack is independently content-addressed from model checkpoint/config identity.
3. Application/Release Overlay owns first-party source, qualification/release metadata and component requirements without owning heavy binary payloads.
4. Ordinary first-party source changes do not invalidate or trigger rebuild of the heavy Runtime Binary Pack.
5. Dependency-root, lock, Python/platform, native ABI or other material runtime changes invalidate Runtime Pack identity.
6. Candidate Runtime and Model packs remain fail-closed on manifest, path, size and SHA-256 integrity.
7. Component-store publication is staged/content-addressed; conflicting component IDs and cross-component duplicate heavy ownership are rejected.
8. Worker startup binds the current Application Overlay to required Runtime and Model component fingerprints and probes live CPython identity.
9. Runtime reuse and worker startup revalidate the installed third-party closure against the installed reviewed lock and run `pip check`.
10. Worker startup revalidates installed Model Pack artifacts for path safety, presence, size, SHA-256 and undeclared files before accepting the pack.
11. Legacy `runtime-install-v1` state is not silently accepted as v2.
12. Runtime integrity implementation is centralized in `Mavi.VisionRuntime.Integrity.psm1`; callers are required to invoke the shared boundary rather than duplicate verification logic.

## Findings and disposition

### CR-01 — installed Runtime closure revalidation

**Severity:** blocking when found.  
**Disposition:** resolved and qualified.

A shared fail-closed integrity boundary now resolves exactly one installed `third-party-runtime-lock`, verifies its path and SHA-256 against the manifest, validates the installed environment with `pip install --no-index --no-deps --require-hashes -r <installed-lock>`, and runs `python -m pip check`. The boundary is called before no-op Runtime Pack reuse and before worker startup. Fresh installation remains `--no-index --only-binary=:all: --require-hashes`.

### CR-02 — installed Model Pack live artifact revalidation

**Severity:** blocking when found.  
**Disposition:** resolved and qualified.

The post-CR-01 cold pass identified that worker startup previously trusted Model Pack state/manifest identity without re-hashing installed checkpoint/config payloads. Startup now revalidates every declared Model Pack artifact for safe path, presence, size and SHA-256 and rejects undeclared files before accepting the pack.

### CR-03 — over-specified CR-01 source-text contract

**Severity:** CI correctness defect, not an implementation integrity defect.  
**Disposition:** resolved and qualified.

Task 17 exposed a stale contract test that required implementation literals such as `third-party-runtime-lock` to appear directly in both callers after integrity logic had been centralized. The contract now checks the correct architectural split: callers must invoke `Assert-MaviVisionInstalledRuntimeClosure`, while the shared integrity module retains the lock/hash/no-index/require-hashes/pip-check controls. Task 17 is green on the final pre-functional-test exact head.

## Functional qualification

The Development Windows CPU environment reused the existing v2 Runtime Binary Pack and v1 Model Pack without heavy-component replacement. Environment verification passed and the worker loaded the local RTMDet checkpoint.

A 1920x1080 video (`2min.mp4`, duration 2m 28s) was processed using `phase1-detection-tracking` / `phase1-v1`. Attempt 2 progressed to approximately 70 percent before the host entered sleep/standby and the worker stopped. After restart, the same authoritative processing job was recovered automatically as Attempt 3. Recovery was a job-level retry, not frame-level continuation. Attempt 3 reached 100 percent; the UI recorded the processing run as `Completed` and the video as `Processed` at 17 Sep 2026 23:28:14 Asia/Kolkata, with no failure code.

This supplies end-to-end CPU functional evidence for heavy-component reuse, environment/startup validation, local model loading, lease/heartbeat operation, RTMDet inference/tracking execution, progress reporting, unexpected-worker-loss recovery, retry and persisted successful completion. CUDA/GPU execution is not qualified by this result.

Observed non-blocking startup warnings (`data_preprocessor.mean` / `data_preprocessor.std` checkpoint keys and PyTorch/MMDetection deprecations) are technical debt. Exit code 70 observed after the sleep interruption requires separate semantic review; this record does not assign a cause to that code beyond the observed temporal association with host sleep.

## Repository / PR state before documentation close-out

- PR #44 was open, mergeable and draft.
- No unresolved inline review threads were present.
- All six required qualification workflows were green on exact head `fea8820a95f00121ee04e735f3e4b53a08d074bc`.
- No additional blocking architectural finding was identified in the final post-fix cold pass.
- The functional CPU qualification completed successfully on that implementation head.

## Finalization rule

This record and the runbook update are documentation-only commits and therefore move the branch head without changing executable/runtime material. The resulting documentation head must nevertheless re-establish the required exact-head CI evidence before merge-readiness is declared. The expensive 2-minute CPU video run does not need to be repeated solely because of these documentation-only changes. Any later executable/runtime/model/component-boundary change invalidates that functional-test assumption and requires impact-based requalification.
