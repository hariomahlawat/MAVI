# MAVI Vision Runtime Pack Decoupling Design

**Date:** 17 September 2026  
**Status:** Approved design for implementation planning  
**Branch:** `feature/runtime-pack-decoupling`  
**Base:** `feature/task-10-rtmdet-bytetrack`

## 1. Problem Statement

MAVI currently has a development source-overlay model intended to let the Vision Worker execute the current checkout's `src/vision/mavi_vision` code against a pinned, qualified runtime installed under `ProgramData`. `Start-MaviVisionWorker.ps1` explicitly documents this objective: source-only changes should not require rebuilding or downloading the heavy runtime bundle.

The current Task-12 packaging implementation violates that boundary. The offline runtime lock contains `mavi-vision==0.1.0` with the SHA-256 of the first-party wheel. Task 12 rebuilds the `mavi-vision` wheel into the same wheelhouse as PyTorch, MMCV, MMDetection and other external dependencies, regenerates the lock, and publishes a new approximately 600 MB bundle whenever first-party Vision application code changes. The startup compatibility gate then sees the changed runtime lock/profile/qualification metadata and rejects the previously installed bundle.

The resulting failure mode is operationally expensive but logically unnecessary: a small application-code change causes a large binary runtime artifact to be rebuilt, uploaded, downloaded and reinstalled even when no third-party dependency, native ABI, Python runtime, model checkpoint or native extension has changed.

This is not to be fixed by weakening integrity checks or by adding exceptions for particular commits. The artifact boundaries and fingerprints must be corrected so that every integrity check describes the component it actually protects.

## 2. Design Goals

The implementation shall:

1. Decouple first-party `mavi_vision` application changes from the large third-party/native runtime pack.
2. Preserve fail-closed integrity and qualification semantics.
3. Make heavyweight artifacts content-addressed or content-derived rather than repository-commit-addressed.
4. Reuse an unchanged runtime pack across arbitrary application commits when their declared dependency/runtime requirements remain compatible.
5. Preserve the current development source overlay and verify that it really resolves `mavi_vision` from the checkout.
6. Keep offline installation deterministic and fully usable without internet access.
7. Ensure a genuine dependency, Python ABI, native build, model, runtime-profile or pipeline-contract change invalidates exactly the component that must be replaced.
8. Prevent CI from uploading hundreds of megabytes for ordinary first-party Python source changes.
9. Add regression tests that prove both non-invalidation and required invalidation cases.
10. Update ADRs, setup/offline-kit documentation and version/inventory records so future work does not reintroduce the coupling.

## 3. Non-Goals

This change shall not:

- change RTMDet, ByteTrack or analytical behaviour;
- qualify CUDA hardware or a CUDA runtime;
- change the currently qualified Windows CPU Python version (`3.12.10`) or Linux CPU Python version (`3.12.14`);
- relax model/checkpoint integrity;
- silently resolve dependencies from the internet during installation;
- remove exact hash checking for third-party wheels;
- make the runtime accept undeclared dependency changes;
- treat application tests as a substitute for runtime qualification;
- introduce a new general-purpose package manager or update service.

## 4. Architectural Decision

MAVI Vision distribution will use three independently identifiable layers.

### 4.1 Runtime Binary Pack

The Runtime Binary Pack contains the heavy, platform-specific execution substrate:

- qualified CPython installer/runtime identity;
- PyTorch and torchvision;
- MMCV native wheel;
- MMDetection and MMEngine;
- OpenCV, AV, NumPy, SciPy, supervision, trackers and other third-party runtime distributions;
- any other external wheel required by the Vision Worker;
- platform/native ABI metadata;
- a third-party-only lock with exact versions and SHA-256 hashes.

It shall **not** contain the `mavi-vision` first-party wheel as a locked runtime distribution.

Its identity is derived from the actual runtime inputs: platform variant, Python identity, external dependency lock, native build identity/toolchain where applicable, and any other byte-affecting runtime input. It is not derived from the current application commit SHA.

A first-party Python source edit must not change the Runtime Binary Pack identity.

### 4.2 Model Pack

The Model Pack contains model-specific immutable assets and the metadata required to identify them:

- RTMDet checkpoint;
- resolved MMDetection model configuration;
- model manifest or a model-pack manifest containing their hashes;
- model identity/version.

The Model Pack identity is derived from model/config content, not from the application commit. Qualification records may refer to a Model Pack identity, but changing qualification bookkeeping without changing model bytes shall not force retransmission of the checkpoint.

### 4.3 MAVI Application / Release Overlay

The Application / Release Overlay contains the small and frequently changing first-party layer:

- `mavi_vision` application code or wheel for packaged deployments;
- pipeline profile and first-party release configuration as appropriate;
- release/qualification records that bind a tested application revision to compatible Runtime Binary Pack and Model Pack identities;
- first-party contracts or schema fingerprints where required for compatibility.

In development, the current checkout's `src/vision` remains the application layer through the existing verified `PYTHONPATH` overlay. A packaged offline release may carry a small first-party wheel or equivalent immutable application artifact separately from the heavy Runtime Binary Pack.

## 5. Dependency and Lock Semantics

The current `pyproject.toml` remains the authoritative declaration of the application's Python requirements, but Task-12 runtime locking must no longer treat the local `mavi-vision` wheel as a member of the external runtime closure.

A dedicated runtime-lock generation boundary shall produce a lock containing only third-party distributions. The lock must remain hash-complete and installable with:

```text
--no-index
--only-binary=:all:
--require-hashes
```

The runtime environment may still install a first-party application wheel for a packaged release, but that wheel is installed and verified as an application artifact after the third-party runtime environment is established. In Development mode, it is not required because the checkout source overlay is authoritative.

Dependency compatibility must be explicit. If `pyproject.toml` changes a dependency requirement in a way that alters the resolved runtime closure, Runtime Binary Pack qualification must rerun and produce a new pack. If application source changes without changing dependency/runtime requirements, the existing Runtime Binary Pack remains valid.

## 6. Component Identities and Installed State

The current `runtime-install.json` schema binds the installed runtime to `sourceCommit`. This is too coarse and shall be replaced by a component-oriented schema.

The new installed runtime state shall record at minimum:

```json
{
  "schemaVersion": "mavi-vision-runtime-install-v2",
  "platformVariant": "windows-x86_64-cpu",
  "runtimePackId": "...",
  "runtimePackManifestSha256": "...",
  "thirdPartyLockSha256": "...",
  "pythonVersion": "3.12.10",
  "installedAtUtc": "...",
  "runtimeRoot": "..."
}
```

If Model Pack installation remains colocated under the runtime root during the first implementation, its independently derived `modelPackId` and manifest SHA-256 shall also be recorded. The logical identity must remain separate even if physical directories are temporarily colocated for deployment simplicity.

`sourceCommit` may be retained only as informational provenance for an artifact assembly event; it must not be the compatibility key that invalidates an otherwise identical Runtime Binary Pack.

## 7. Compatibility Model

Startup compatibility shall change from "was this heavy bundle built from the current repository commit?" to "are the installed component fingerprints compatible with the current application requirements?"

For Development mode, startup shall verify:

1. required runtime pack schema and platform variant are supported;
2. the installed third-party lock/runtime profile fingerprint matches the checkout's expected runtime dependency fingerprint;
3. required model assets and their content hashes match the expected Model Pack identity/fingerprint;
4. pipeline/contract/runtime profile inputs that genuinely affect compatibility are consistent;
5. the Python interpreter identity is qualified;
6. `mavi_vision` resolves from the current checkout, not from an old installed wheel.

A changed application `.py` file alone shall not fail runtime compatibility.

A changed dependency declaration, tracked third-party lock, Python/runtime ABI requirement, model checkpoint, resolved model configuration, or other explicitly classified runtime-critical input shall fail closed until the corresponding component is rebuilt/qualified/installed.

The old broad `git diff` check in `Assert-MaviVisionRuntimeSourceCompatible` shall be retired or narrowed to component fingerprints. Compatibility decisions must not depend on repository ancestry when content fingerprints provide the actual invariant.

## 8. CI / Task-12 Behaviour

Task 12 currently triggers on `src/vision/mavi_vision/**` and builds/uploads complete Runtime Binary Packs for ordinary first-party source edits. This must stop.

The CI design shall separate lightweight validation from heavyweight runtime artifact publication.

### 8.1 Application changes

Changes limited to first-party application source/tests shall run:

- Quality Gate;
- relevant Vision unit/integration tests;
- runtime/API contract tests;
- source-overlay compatibility tests;
- Task-specific acceptance gates where applicable.

They shall not cause a new Runtime Binary Pack upload merely because the first-party wheel hash changed.

### 8.2 Runtime changes

Heavy Runtime Binary Pack build/qualification shall run when inputs such as the following change:

- Python runtime version/platform identity;
- external dependency declarations or resolved pins;
- runtime lock generation logic;
- MMCV source pin/build toolchain/native ABI inputs;
- PyTorch/torchvision selection;
- files that define the third-party runtime profile or its platform lock identities;
- Runtime Binary Pack builder/manifest semantics.

### 8.3 Model changes

Model Pack build or model qualification shall run when checkpoint/config/model-manifest inputs change. An unchanged checkpoint shall not be republished solely because application code or qualification prose changes.

### 8.4 PR release gate

A PR that changes only application code may reuse a previously qualified Runtime Binary Pack. The PR's exact-head release evidence must explicitly record which Runtime Binary Pack and Model Pack identities were used for qualification/testing. This preserves exact-head application qualification without rebuilding immutable heavy dependencies.

## 9. Offline Binary Kit and Deployment

`MAVI-Offline-Binary-Kit` shall store heavy reusable component artifacts by stable component identity/version rather than by application commit.

At minimum the kit inventory shall distinguish:

- Runtime Binary Pack(s) by platform variant and runtime pack ID;
- Model Pack(s) by model pack ID;
- small Application / Release Overlay artifacts by application revision/release ID.

The setup flow shall be idempotent:

- if the required Runtime Binary Pack is already installed and its manifest/hash is valid, do not reinstall it;
- if only the Application / Release Overlay changed, update only that layer;
- if only the Model Pack changed, update only the model layer;
- if Runtime Binary Pack identity changed, perform the existing staged/atomic runtime replacement.

No setup path may silently reuse a component whose fingerprint does not match the application's declared requirement.

## 10. Qualification and Evidence

Runtime qualification and application qualification are related but distinct.

The Runtime Binary Pack qualification proves that a specific third-party/native execution substrate is installable, reproducible where required, offline-complete and functionally able to execute the runtime probe.

Application exact-head qualification proves that the current `mavi_vision` source/release overlay functions correctly against a named, previously qualified Runtime Binary Pack and Model Pack.

Qualification records shall therefore bind:

- application/release revision;
- Runtime Binary Pack ID and manifest/lock fingerprint;
- Model Pack ID and asset fingerprints;
- pipeline/profile fingerprints;
- gate results.

This prevents a stale runtime from being treated as valid while avoiding needless artifact regeneration.

## 11. Security and Integrity Requirements

The decoupling must not weaken security properties introduced by Tasks 10–17.

The implementation shall preserve:

- SHA-256 verification of every distributed artifact;
- exact third-party wheel hashes;
- offline-only installation with network disabled/unavailable;
- no source builds during offline installation;
- trusted CPython installer verification on Windows;
- native ABI/toolchain qualification for MMCV;
- checkpoint/config integrity and exact checkpoint/model-key compatibility probe;
- fail-closed handling of missing/unknown component identities;
- path traversal/symlink/undeclared-artifact protections already present in bundle/install code;
- no silent CPU/CUDA fallback.

## 12. Migration Strategy

The migration shall be deliberate and one-way.

1. Introduce component fingerprint/manifest logic and tests without weakening the existing gate.
2. Generate third-party-only locks and prove that application-source changes leave them byte-identical.
3. Update Task-12 build logic to stop including `mavi-vision` in the heavy runtime closure.
4. Update installer state to v2 component identities.
5. Update Development startup compatibility to use component fingerprints and retain verified source overlay.
6. Update offline-kit tooling/inventory and documentation.
7. Add CI negative/positive invalidation tests.
8. Qualify one new canonical Windows CPU Runtime Binary Pack under the corrected architecture.
9. Install it once on the development machine.
10. Resume the 2-minute video test only after the new architecture's own gates are green.

Existing v1 installed runtime state shall not be silently interpreted as v2. Setup may detect v1 and require a one-time migration/reinstallation to establish the new component identity. After that one-time migration, ordinary application changes must no longer require the heavy bundle to be replaced.

## 13. Required Regression Tests

The implementation is incomplete unless automated tests prove all of the following:

### 13.1 Must not invalidate Runtime Binary Pack

Representative changes to:

- `src/vision/mavi_vision/worker/runner.py`;
- another ordinary `mavi_vision` Python module;
- first-party tests;
- application-only documentation;

must leave the third-party runtime fingerprint/lock unchanged and must not require a Runtime Binary Pack rebuild.

### 13.2 Must invalidate Runtime Binary Pack

Representative changes to:

- pinned PyTorch/torchvision versions;
- MMCV source/build identity;
- Python version/platform ABI;
- a third-party dependency requirement that changes the resolved closure;
- runtime lock generation semantics;

must produce a different Runtime Binary Pack fingerprint or fail qualification until the pack is regenerated.

### 13.3 Must invalidate Model Pack or model qualification

Representative changes to checkpoint/config/model identity must fail closed or produce a new Model Pack identity as appropriate.

### 13.4 Startup behaviour

Tests shall prove that:

- Development startup accepts a newer application checkout against an unchanged compatible runtime pack;
- Development startup rejects a checkout requiring a different runtime fingerprint;
- `mavi_vision` imports from the checkout source overlay;
- unknown/malformed installed state fails closed;
- v1 installed state is not silently accepted as v2.

### 13.5 Offline install behaviour

Tests shall prove that:

- the runtime pack installs with no network and exact hashes;
- an already valid identical Runtime Binary Pack is reusable without reinstall;
- first-party application update does not trigger heavy runtime replacement;
- changed heavy runtime identity does trigger staged replacement.

## 14. Files/Areas Expected to Change

Implementation planning shall inspect and likely modify at least:

- `.github/workflows/task12-offline-bundle.yml`;
- `.github/workflows/task10-runtime-qualification.yml` where release/runtime bindings are asserted;
- `tools/vision/build_offline_bundle.py`;
- `tools/vision/freeze_offline_lock.py`;
- runtime lock/profile logic under `src/vision/mavi_vision/runtime/`;
- `src/vision/runtime/mmdetection-phase1-v1/*.lock` and `runtime.json`;
- `tools/setup/Mavi.Setup.Common.psm1`;
- `tools/setup/Install-MaviVisionRuntime.ps1`;
- `tools/setup/Start-MaviVisionWorker.ps1`;
- `tools/setup/New-MaviOfflineBinaryKit.ps1` and its verification tooling;
- tests for the above;
- `docs/decisions/ADR-005-qualified-vision-runtime.md` and relevant setup/offline documentation.

Exact file-level changes belong in the implementation plan after the existing helpers/tests are mapped in detail.

## 15. Acceptance Criteria

This architectural correction is accepted only when all of the following are true:

1. A normal `mavi_vision` source-only commit does not change the third-party runtime lock or Runtime Binary Pack identity.
2. CI does not build/upload the approximately 600 MB Runtime Binary Pack for such a source-only change.
3. The Vision Worker starts from the newer checkout using an already installed compatible Runtime Binary Pack and proves import resolution from the checkout.
4. A genuine third-party/runtime dependency change still fails closed until a newly qualified Runtime Binary Pack is installed.
5. Model/checkpoint changes are independently detected and do not depend on application commit equality.
6. Offline installation remains deterministic, hash-verified and network-independent.
7. The offline binary kit records component versions/identities separately and can reuse unchanged heavy components.
8. All affected Quality, runtime qualification, offline installation and new component-boundary tests are green.
9. Documentation accurately describes the component lifecycle and the one-time v1-to-v2 migration.
10. Only after these conditions are met do we resume functional video processing tests.

## 16. Design Rationale

The essential rule is simple: **large immutable dependencies must be versioned by the content and compatibility properties that make them different, not by unrelated application commits.**

This gives MAVI a reproducible offline deployment model without trading away integrity. It also makes qualification evidence clearer: application code can evolve rapidly, while the expensive native/runtime substrate and model assets change only when their own inputs actually change.