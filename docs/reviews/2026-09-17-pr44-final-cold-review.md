# PR #44 Final Cold Review Record

Date: 2026-09-17
PR: #44 `feature/runtime-pack-decoupling`
Base: `feature/task-10-rtmdet-bytetrack`

## Qualified checkpoint entering review

Exact head `b2cd65be2fbc5b94b6d73f59b16e85b5b3389c51` completed all six qualification workflows successfully:

- MAVI Quality Gate
- Task 10 Runtime Qualification
- Task 12 Offline Runtime Pack
- Task 17 Acceptance Validation
- Vision Runtime Component Boundary
- Vision Model Pack

This checkpoint is retained as historical evidence only after any later review-fix or documentation commit moves the PR head.

## Architecture reviewed

The cold review treats the PR as unseen code and checks the following trust boundaries:

1. Runtime Binary Pack is third-party-only and content-derived from runtime dependency/lock/platform inputs.
2. Model Pack is independently content-addressed from model checkpoint/config identity.
3. Application/Release Overlay owns first-party source, qualification/release metadata and component requirements, without owning heavy binary payloads.
4. Ordinary first-party source changes do not invalidate the heavy Runtime Binary Pack.
5. Dependency, lock, Python/platform or native ABI changes do invalidate the Runtime Binary Pack.
6. Candidate packs are fail-closed on manifest, path, size and SHA-256 integrity.
7. Component-store publication is staged/content-addressed and conflicting component IDs are rejected.
8. Runtime/Model ownership is explicit and cross-component duplicate heavy artifacts are rejected.
9. Worker startup binds the current application overlay to the required Runtime Pack and Model Pack and independently probes the live CPython identity.
10. Legacy runtime-install-v1 state is not silently accepted as v2.

## Cold-review finding CR-01 — installed Runtime closure must be revalidated before reuse/startup

**Severity:** blocking for final architecture qualification.

The Runtime Pack installer fully verifies the supplied candidate pack and performs `pip check` after a fresh offline installation. However, the current no-op reuse path validates installed state, installed manifest and live CPython identity without revalidating that the already-installed venv still satisfies the complete reviewed third-party lock. The worker startup path has the same residual gap.

A post-install removal or version replacement of a locked distribution can therefore survive component-ID/manifest/Python-identity checks and only fail later during application import or execution. This is inconsistent with the fail-closed reuse/startup objective.

### Required correction

Before an installed Runtime Pack is accepted for reuse, and before the worker starts:

- resolve the installed manifest's single `third-party-runtime-lock` artifact;
- verify that artifact remains present and matches `thirdPartyLockSha256`;
- run the installed venv against the reviewed lock in a network-disabled/no-index verification mode so every locked distribution must already be satisfied at its exact version;
- run `python -m pip check`;
- reject reuse/startup on any failure rather than falling through to application execution;
- add regression/contract coverage for the verification path.

Fresh installation remains `--no-index --only-binary=:all: --require-hashes`; this finding does not relax any existing integrity control.

## Non-findings confirmed

No unresolved PR review threads or PR discussion comments were present at the start of this cold-review pass. The PR was open, mergeable and still draft. Runtime/Model/Application component separation, content-addressed Binary Kit storage, duplicate ownership rejection, exact-head checkout checks and source-only heavy-trigger exclusion were present in the reviewed implementation.

## Finalization rule

PR #44 is **not final** while CR-01 is open. After CR-01 is fixed, all affected local/contract checks must pass, documentation must reflect the final behaviour, and the resulting exact head must re-establish the applicable qualification workflows. A final cold-review pass must then confirm no remaining blocking finding before the 2-minute functional video test is resumed.
