# MAVI Vision Runtime Pack Decoupling Design

**Date:** 17 September 2026  
**Status:** Cold-reviewed and approved for implementation; implemented (ADR-007). **Historical design record** — the single Model Pack binding it describes is generalised by accepted ADR-014 (capability binding v2) for Stage 2; ADR-007/ADR-014 govern where this text differs.  
**Branch:** `feature/runtime-pack-decoupling`  
**Base:** `feature/task-10-rtmdet-bytetrack`

## 1. Problem Statement

MAVI Development intentionally executes the current checkout's `src/vision/mavi_vision` code against a pinned, qualified runtime installed under `ProgramData`. `Start-MaviVisionWorker.ps1` already overlays repository source through `PYTHONPATH` so ordinary first-party source changes should not require rebuilding or downloading the heavy runtime.

The current Task-12 architecture violates that boundary. The offline runtime lock contains `mavi-vision==0.1.0` with the hash of the first-party wheel. Task 12 therefore rebuilds the first-party wheel, regenerates the runtime lock/profile, and republishes an approximately 600 MB bundle whenever `mavi_vision` source changes. Startup then sees changed runtime metadata and rejects an otherwise compatible installed runtime.

The fix must correct artifact boundaries and compatibility fingerprints. It must not weaken integrity checks, special-case commits, or merely cache the oversized artifact more aggressively.

## 2. Architectural Decision

MAVI Vision distribution shall use three independently identifiable layers.

### 2.1 Runtime Binary Pack

The Runtime Binary Pack contains only the heavy platform-specific execution substrate:

- qualified CPython runtime/installer identity;
- PyTorch and torchvision;
- MMCV native wheel;
- MMDetection and MMEngine;
- OpenCV, AV, NumPy, SciPy, supervision, trackers and all other third-party runtime distributions;
- platform/native ABI and toolchain identity;
- a third-party-only exact-hash lock;
- a deterministic application-runtime-requirements projection used to prove that the lock satisfies the current application's declared dependency roots.

It shall **not** contain or lock the `mavi-vision` first-party wheel.

Its identity shall be content-derived from runtime inputs, not from an application commit SHA. A first-party `.py` edit must not change this identity.

### 2.2 Model Pack

The Model Pack contains immutable model assets:

- RTMDet checkpoint;
- resolved MMDetection model configuration;
- a model-pack manifest with content hashes and model identity.

Its identity is content-derived. Qualification metadata may bind to a Model Pack identity, but bookkeeping-only qualification changes shall not force retransmission of unchanged model bytes.

### 2.3 MAVI Application / Release Overlay

The small, frequently changing first-party layer contains:

- `mavi_vision` source/wheel for packaged deployments;
- pipeline and first-party release configuration;
- release/qualification records binding the exact application revision to compatible Runtime Binary Pack and Model Pack identities;
- first-party contract/schema fingerprints where required.

Development mode continues to use the current checkout through the existing verified `PYTHONPATH` overlay.

## 3. Non-Negotiable Integrity Boundary

Decoupling must not mean weakening qualification.

Every exact application head must still be tested against an explicitly identified Runtime Binary Pack and Model Pack. Reusing an immutable heavy component is permitted only when its deterministic fingerprint is identical to the fingerprint required by the current application head.

The following remain fail-closed:

- unsupported/malformed component manifests;
- changed runtime dependency requirements;
- changed Python/platform/native ABI requirements;
- changed third-party lock or runtime profile identity;
- changed checkpoint/resolved config/model identity;
- missing or hash-mismatched artifacts;
- undeclared files, unsafe paths or symlinks;
- CUDA/CPU variant mismatch;
- unknown installed-state schema.

## 4. Application Runtime Requirements Projection

### 4.1 Why it is required

Today the `mavi-vision` wheel's `Requires-Dist` metadata acts as a root for dependency-closure validation. Removing that wheel from the Runtime Binary Pack without replacing this root would be unsafe: the remaining third-party wheelhouse could be internally closed while omitting an application-required distribution such as `httpx` or `msgpack`.

Therefore the implementation shall introduce a deterministic **Application Runtime Requirements Projection** derived directly from `src/vision/pyproject.toml`.

### 4.2 Projection contents

For the current Vision Worker the projection shall include the union of:

- `[project].dependencies`;
- `[project.optional-dependencies].vision-runtime`.

Development-only dependencies such as `pytest` are excluded.

Each requirement shall be parsed with `packaging.Requirement`, canonicalized, marker-evaluated for the target platform/Python identity, and serialized deterministically. Direct URLs and unsupported environment-dependent markers shall fail closed.

The projection shall carry a schema version and SHA-256 fingerprint, for example:

```text
# schema: mavi-vision-runtime-requirements-v1
# platform-variant: windows-x86_64-cpu
# python-version: 3.12.10
av>=15,<17
httpx>=0.28,<0.29
...
torch==2.6.0
...
```

The exact serialization format is an implementation detail, but ordering and bytes must be deterministic.

### 4.3 Lock validation against projection

The third-party lock validator shall prove all of the following:

1. every applicable root requirement in the projection has a corresponding locked distribution;
2. the locked version satisfies that root requirement;
3. every transitive `Requires-Dist` edge of every locked wheel is present and version-compatible;
4. there are no direct-URL/source-build requirements;
5. platform/Python tags and `Requires-Python` remain compatible;
6. `mavi-vision` itself is absent from the third-party lock.

This replaces the current `offline_lock_mavi_missing` invariant with a stronger and correctly scoped runtime-root invariant.

## 5. Runtime Binary Pack Identity

The Runtime Binary Pack ID shall be derived from the bytes/identities that make the runtime materially different, including at minimum:

- platform variant;
- exact qualified Python identity;
- third-party lock SHA-256;
- Application Runtime Requirements Projection SHA-256;
- native ABI/toolchain identity where applicable;
- runtime-pack schema version.

The pack ID shall not contain or depend upon repository HEAD/source commit.

The build manifest may retain `assembledFromCommit` as informational provenance, but startup compatibility must never compare it to the current application HEAD.

## 6. Model Pack Identity

The Model Pack ID shall derive from:

- model ID;
- checkpoint SHA-256;
- resolved config SHA-256;
- model-pack schema version.

A change to qualification prose, workflow run IDs or application source alone must not change Model Pack identity.

The Model Pack manifest shall enumerate every included file with size and SHA-256. The application/release record shall refer to `modelPackId` rather than assuming that model assets belong to a specific application commit.

## 7. Installed State v2

`runtime-install.json` shall migrate from commit binding to component binding.

Minimum Runtime Binary Pack state:

```json
{
  "schemaVersion": "mavi-vision-runtime-install-v2",
  "platformVariant": "windows-x86_64-cpu",
  "runtimePackId": "...",
  "runtimePackManifestSha256": "...",
  "thirdPartyLockSha256": "...",
  "runtimeRequirementsSha256": "...",
  "pythonVersion": "3.12.10",
  "installedAtUtc": "...",
  "runtimeRoot": "..."
}
```

If Model Pack assets remain physically colocated during migration, their `modelPackId` and manifest hash shall still be recorded separately. Logical identities must not be collapsed merely because directories are colocated.

Existing `mavi-vision-runtime-install-v1` state shall not be silently interpreted as v2. A one-time runtime migration/reinstallation is acceptable. After that migration, ordinary application changes shall not require heavy runtime replacement.

## 8. Development Startup Compatibility

Development startup shall verify component compatibility rather than repository ancestry.

It shall verify:

1. installed-state schema is v2;
2. platform/runtime variant matches;
3. installed Runtime Binary Pack ID/fingerprints match the current checkout's required runtime fingerprint;
4. Model Pack ID/content fingerprints match the current application's model requirement;
5. required release/pipeline/contract fingerprints match;
6. exact qualified Python identity is present;
7. `mavi_vision` resolves from the current repository source overlay.

A `.py` source edit alone shall be accepted against an unchanged compatible Runtime Binary Pack.

A dependency declaration, runtime requirements projection, third-party lock, ABI, Python identity, model asset or explicitly classified compatibility input change shall fail closed.

The broad commit-diff compatibility function `Assert-MaviVisionRuntimeSourceCompatible` shall be removed from the decision path or narrowed to diagnostic use only; repository ancestry is not a component compatibility invariant.

## 9. CI Architecture

### 9.1 Lightweight application path

Ordinary first-party source/test changes shall run:

- MAVI Quality Gate;
- Vision unit/integration tests;
- contract/source-overlay/component-compatibility tests;
- task-specific acceptance gates.

They shall not build or upload a new Runtime Binary Pack merely because `mavi_vision` changed.

### 9.2 Heavy runtime path

Runtime Binary Pack build/qualification shall run when any runtime identity input changes, including:

- `pyproject.toml` runtime dependency declarations;
- third-party lock generation/validation semantics;
- Python version/platform identity;
- PyTorch/torchvision selection;
- MMCV source pin/build toolchain/native ABI inputs;
- runtime profile/lock identity inputs;
- Runtime Binary Pack builder or manifest schema.

### 9.3 Model path

Model Pack build/qualification shall run when checkpoint, resolved config or model identity changes. Unchanged model bytes shall not be republished solely because first-party source or qualification bookkeeping changes.

### 9.4 Exact-head qualification when heavy packs are reused

A source-only PR must still prove the exact application head against named immutable components. Its release evidence shall record:

- application HEAD/release ID;
- Runtime Binary Pack ID and relevant manifest/lock fingerprints;
- Model Pack ID and asset fingerprints;
- pipeline/profile/contract fingerprints;
- gate results.

The CI implementation may restore/cache or otherwise reuse immutable qualified heavy components, but it must not claim qualification without actually executing the required application/runtime probes for the exact head.

## 10. Offline Installation and Reuse

Offline installation remains deterministic and network-independent:

```text
--no-index
--only-binary=:all:
--require-hashes
```

The Runtime Binary Pack installer shall install only third-party distributions from the third-party lock. A packaged `mavi-vision` wheel, when used, is a separately verified Application Overlay artifact installed after the runtime environment is established. Development mode uses the repository source overlay and does not require that wheel to be installed.

Setup shall be idempotent:

- identical valid Runtime Binary Pack already installed -> reuse, no reinstall;
- application-only update -> update/rebind application layer only;
- model-only update -> update Model Pack only;
- Runtime Binary Pack ID change -> staged/atomic heavy runtime replacement.

No path may silently reuse a component whose fingerprint differs from the application's declared requirement.

## 11. Offline Binary Kit

`MAVI-Offline-Binary-Kit` shall inventory reusable artifacts by component identity, not application commit:

- Runtime Binary Pack by platform variant + `runtimePackId`;
- Model Pack by `modelPackId`;
- Application / Release Overlay by application revision/release ID.

The inventory shall record SHA-256, size, schema/version and source provenance. Re-running kit preparation must not duplicate an unchanged heavy component.

## 12. Security Properties to Preserve

The implementation shall preserve all existing relevant controls:

- SHA-256 verification for distributed artifacts;
- exact third-party wheel hashes;
- no network during offline installation;
- no source builds during offline installation;
- trusted Windows CPython installer signature/version verification;
- qualified native ABI/toolchain for MMCV;
- checkpoint/resolved-config integrity;
- exact checkpoint/model-key compatibility probe;
- path traversal/symlink/undeclared-artifact protections;
- fail-closed unknown schemas/identities;
- no silent CPU/CUDA fallback.

## 13. Migration Sequence

1. Add deterministic runtime-requirements projection and tests.
2. Change offline-lock validation to third-party-only + explicit application roots.
3. Regenerate reviewed third-party-only Windows/Linux CPU locks.
4. Introduce Runtime Binary Pack component manifest/ID independent of source commit.
5. Introduce Model Pack manifest/ID independent of source commit.
6. Update Task-12 trigger/build publication boundaries.
7. Update installer state to v2 and implement idempotent component reuse.
8. Replace commit-based Development startup compatibility with component fingerprints while retaining verified source overlay.
9. Update offline-kit tooling and inventory.
10. Update runtime/application exact-head qualification evidence.
11. Run all repository gates and dedicated non-invalidation/invalidation tests.
12. Perform one final cold review.
13. Generate/install one canonical Windows CPU Runtime Binary Pack under the corrected architecture.
14. Only then resume the two-minute functional video test.

## 14. Required Regression Tests

### Must NOT invalidate Runtime Binary Pack

Representative changes to ordinary `src/vision/mavi_vision/*.py`, Vision tests, or application-only documentation must leave the Runtime Binary Pack fingerprint and third-party lock byte-identical.

### Must invalidate Runtime Binary Pack

Representative changes to Python identity, pinned PyTorch/torchvision, MMCV build identity, a root runtime dependency requirement, runtime lock generation semantics, or native ABI inputs must change the required Runtime Binary Pack fingerprint or fail qualification until rebuilt.

### Dependency-root safety

Tests must prove that after `mavi-vision` is removed from the lock:

- omitting an application-required package is rejected;
- a locked version outside the declared requirement is rejected;
- transitive dependency omission is rejected;
- `mavi-vision` appearing in the third-party lock is rejected.

### Model independence

Checkpoint/resolved-config changes must change Model Pack identity; application-code and qualification-bookkeeping-only changes must not.

### Startup

Tests must prove:

- newer source-only checkout starts against unchanged compatible v2 runtime;
- checkout requiring a different runtime fingerprint is rejected;
- wrong Model Pack is rejected;
- source overlay resolves from checkout;
- malformed/unknown state fails closed;
- v1 state is not silently accepted.

### Offline install/reuse

Tests must prove:

- runtime installs with no network and exact hashes;
- identical installed Runtime Binary Pack is reusable without staged replacement;
- application-only update does not trigger heavy runtime replacement;
- changed runtime pack identity does trigger staged replacement.

## 15. Acceptance Criteria

The correction is complete only when:

1. a normal `mavi_vision` source-only commit does not change the third-party runtime lock or Runtime Binary Pack ID;
2. CI does not rebuild/upload the approximately 600 MB Runtime Binary Pack for such a source-only change;
3. exact-head application qualification still runs and records the reused component identities;
4. Development startup accepts the newer checkout against the compatible installed v2 Runtime Binary Pack and verifies source overlay resolution;
5. genuine runtime/dependency changes still fail closed until a newly qualified Runtime Binary Pack is installed;
6. Model Pack identity is independent of application commit and qualification bookkeeping;
7. offline installation remains deterministic, hash-verified and network-independent;
8. the Offline Binary Kit reuses unchanged heavy components by stable identity;
9. all affected Quality, runtime qualification, offline installation and component-boundary tests are green;
10. documentation describes the three component lifecycles and one-time v1 -> v2 migration;
11. only after these conditions are green is functional video testing resumed.

## 16. Cold Review Closure — 17 September 2026

An independent cold review of this design identified one material omission in the first draft: removing the `mavi-vision` wheel from the heavy lock also removes the wheel metadata that currently anchors the application's root dependencies. The design was therefore strengthened with the deterministic Application Runtime Requirements Projection and explicit root-to-lock validation above.

The review also made exact-head qualification semantics explicit: heavy-component reuse reduces artifact churn but never waives testing of the current application head against the named component identities.

With those corrections, no unresolved architectural blocker remains. The design preserves fail-closed integrity while eliminating repository-commit coupling from large immutable artifacts.
