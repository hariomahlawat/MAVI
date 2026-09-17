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

## Cold-review finding CR-01 — installed Runtime closure revalidation

**Severity:** blocking for final architecture qualification.

The cold review identified that fresh installation verified the complete third-party lock, while the reuse/startup path previously relied on installed state, manifest and live CPython identity without revalidating the installed package closure.

### Remediation implemented

CR-01 has been remediated fail-closed. A shared `Mavi.VisionRuntime.Integrity.psm1` verification boundary now:

- resolves exactly one installed `third-party-runtime-lock` artifact from the installed Runtime Pack manifest;
- validates its relative path, presence and SHA-256 against both the artifact entry and `thirdPartyLockSha256`;
- invokes the installed interpreter with `pip install --no-index --no-deps --require-hashes -r <installed-lock>` and no package source, so a missing or wrong-version locked distribution cannot be repaired or downloaded and causes verification failure;
- runs `python -m pip check` after the exact-lock verification;
- is called before an installed Runtime Pack is accepted for no-op reuse;
- is called again before worker startup;
- has repository contract coverage requiring both trust boundaries to retain the closure verification.

Fresh installation remains `--no-index --only-binary=:all: --require-hashes`; no existing integrity control was relaxed.

**CR-01 status:** implementation complete; final status remains pending exact-head CI qualification and the post-fix cold-review pass.

## Non-findings confirmed

No unresolved PR review threads or PR discussion comments were present at the start of the cold-review pass. The PR was open, mergeable and draft. Runtime/Model/Application component separation, content-addressed Binary Kit storage, duplicate ownership rejection, exact-head checkout checks and source-only heavy-trigger exclusion were present in the reviewed implementation.

## Finalization rule

PR #44 is not final until the resulting exact head re-establishes the applicable qualification workflows and the post-fix cold-review pass confirms no remaining blocking finding. Only then should the 2-minute functional video test resume.
