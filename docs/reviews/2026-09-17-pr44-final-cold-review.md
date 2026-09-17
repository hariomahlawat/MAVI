# PR #44 Final Cold Review Record

Date: 2026-09-17
PR: #44 `feature/runtime-pack-decoupling`
Base: `feature/task-10-rtmdet-bytetrack`

## Final reviewed implementation checkpoint

Exact head `269025c79aecbd1e45c996071684e2c4461c2267` completed all six qualification workflows successfully:

- MAVI Quality Gate
- Task 10 Runtime Qualification
- Task 12 Offline Runtime Pack
- Task 17 Acceptance Validation
- Vision Runtime Component Boundary
- Vision Model Pack

The final documentation commit that records this result necessarily moves the branch head. The six-green checkpoint above therefore remains implementation evidence; the resulting documentation-only head must re-establish exact-head CI before merge-readiness is declared.

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

Task 17 exposed a stale contract test that required implementation literals such as `third-party-runtime-lock` to appear directly in both callers after integrity logic had been centralized. The contract now checks the correct architectural split: callers must invoke `Assert-MaviVisionInstalledRuntimeClosure`, while the shared integrity module must retain the lock/hash/no-index/require-hashes/pip-check controls. Task 17 subsequently passed on exact head `269025c79aecbd1e45c996071684e2c4461c2267`.

## Repository / PR state at final cold review

- PR #44 remained open, mergeable and draft.
- No unresolved inline review threads were present.
- No submitted PR reviews were present.
- All six qualification workflows were green on implementation head `269025c79aecbd1e45c996071684e2c4461c2267`.
- No additional blocking architectural finding was identified in the final post-fix pass.

## Finalization rule

The architecture may be considered qualified only after the documentation-only head produced by this record also completes the required exact-head gates successfully. If that head is green and no new review finding appears, PR #44 can move to merge-readiness assessment. The 2-minute functional video test remains on hold until that exact-head confirmation is complete.
