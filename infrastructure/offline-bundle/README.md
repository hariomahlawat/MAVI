# MAVI Offline Vision Runtime Bundle

## Purpose

The MAVI vision runtime is distributed to air-gapped workers as a deterministic directory bundle. The bundle contains the exact Python wheels, model/runtime release metadata, resolved model configuration and approved checkpoint required by one platform variant.

Task 12 produces CPU **qualification-candidate** bundles for:

- `linux-x86_64-cpu` on CPython `3.12.14`;
- `windows-x86_64-cpu` on CPython `3.12.10`.

CUDA bundle qualification remains pending hardware qualification. Task 12 does not promote the model manifest to `verified`, the runtime to `qualified`, or the formal offline-install qualification gates to `passed`.

## Relationship to the MAVI application setup bundle

This directory documents the **vision-worker runtime bundle**, not the Windows operational-plane installer.

The Windows Development/Production application environment is prepared through the canonical MAVI setup bundle described in `docs/runbooks/mavi-offline-setup.md`. That bundle carries the qualified MAVI application, MAVI-owned PostgreSQL 18 + pgvector runtime, ASP.NET Core hosting prerequisite and Development toolchain/cache material.

Vision CPU/CUDA bundles remain separate because they are platform/device-qualified Python/model runtime closures. Final acceptance binds the Windows application/setup identity and the selected vision-runtime bundle identity together.

Future Python/model/native dependencies must follow `docs/architecture/dependency-and-offline-packaging-policy.md`; do not add an untracked wheel or manual target-host installation step.

## Release modes

### Qualification candidate

A qualification-candidate bundle is integrity checked and fully installable from local wheel bytes, but it may carry an `unverified` manifest and `pending` qualification record. The pending qualification record must already be rebound to the exact runtime-profile SHA-256 copied into the bundle; the bundle builder intentionally runs `verify_release_selection(..., allow_unverified=True)` and rejects stale qualification/runtime hash relationships. It exists so Task 17 can execute true network-disconnected and release-level qualification.

It must not be represented as a production-qualified release.

### Production

The bundle assembler supports production mode only after all release evidence is complete. Production mode fails closed unless the model manifest is `verified`, the runtime is `qualified`, the qualification result is `passed`, all mandatory qualification gates are passed, and the requested platform has a qualified offline lock.

Task 17 must generate a production bundle for every required qualified platform/device variant in the final runtime profile. Each exact production bundle must then pass a disconnected production-mode install/runtime smoke on the corresponding host/device class before Phase-1 release completion. Qualification-candidate evidence cannot substitute for this post-promotion check.

## Prerequisite and deployment boundary

The exact CPython patch version for the selected bundle must already be provisioned on the target host.

The vision-runtime bundle does not install the operating system, Windows Server/IIS, PostgreSQL/pgvector, CPython itself, NVIDIA/CUDA drivers, compiler toolchains, or the complete MAVI application deployment. Target-machine compilation is prohibited.

The Windows operational-plane prerequisites are owned by the canonical MAVI application setup media. Vision-host prerequisites such as the exact CPython/NVIDIA/CUDA baseline remain controlled offline prerequisites for the qualified worker topology. Final Task-17 evidence must bind the application/setup identity and selected vision-runtime production-bundle identity together.

## Directory contract

~~~text
<bundle-root>/
  bundle-manifest.json
  INSTALL.txt
  wheels/
    <exact locked wheels only>
  release/
    models/
      manifests/
        rtmdet-m-coco-phase1-v1.json
      qualifications/
        rtmdet-m-coco-phase1-v1.json
      rtmdet-m-coco-phase1-v1/
        rtmdet_m_8xb32-300e_coco_20220719_112220-229f527c.pth
        rtmdet_m_resolved.py
    config/
      pipelines/
        phase1-detection-tracking-v1.json
    runtime/
      mmdetection-phase1-v1/
        runtime.json
        <qualified-platform-variant>.lock
        <other-qualified-platform-variant>.lock
~~~

A platform bundle contains the **wheel closure only for its selected platform variant**, but it retains **every qualified runtime lock referenced by `runtime.json`**. The selected platform lock is the only lock used by the offline `pip install` command; the additional qualified locks are immutable release metadata required by runtime startup verification. Pending/unqualified lock entries have no artifact and are not copied into the bundle.

## Integrity contract

`bundle-manifest.json` contains one record for every product file except the manifest itself. Each record contains the relative path, byte size and SHA-256. Wheel records also contain canonical package name and exact version.

The manifest is deterministic: canonical UTF-8/LF JSON with no timestamp, hostname, temporary/absolute build path, random identifier or filesystem modification time.

`bundleId` is derived from immutable release identities, including the source commit, platform variant, runtime/profile/qualification identities, the selected release-lock hash, and the hashes of **all qualified runtime locks included in the bundle**.

Before transfer or installation, validate every path, size and SHA-256 in the manifest against the bundle bytes. Transfer records may additionally record the SHA-256 of `bundle-manifest.json` itself.

## Offline installation

Run from the bundle root using the exact required CPython patch version:

~~~text
python -m pip install --no-index --only-binary=:all: --require-hashes --find-links ./wheels -r ./release/runtime/mmdetection-phase1-v1/<platform-variant>.lock
python -m pip check
~~~

The options are mandatory:

- `--no-index` prevents package-index resolution;
- `--only-binary=:all:` prevents source builds;
- `--require-hashes` binds every distribution to the reviewed lock;
- `--find-links ./wheels` limits discovery to local bundle wheels.

Do not remove these options to work around a missing package. A missing/incompatible wheel means the bundle is incomplete and must be rebuilt through the controlled connected freeze process.

## Runtime paths

The bundle records these relative paths in `INSTALL.txt`:

~~~text
MAVI_MODEL_ROOT=./release/models
MAVI_MODEL_MANIFEST_PATH=./release/models/manifests/rtmdet-m-coco-phase1-v1.json
MAVI_QUALIFICATION_RECORD_PATH=./release/models/qualifications/rtmdet-m-coco-phase1-v1.json
MAVI_PIPELINE_PROFILE_PATH=./release/config/pipelines/phase1-detection-tracking-v1.json
MAVI_RUNTIME_PROFILE_PATH=./release/runtime/mmdetection-phase1-v1/runtime.json
~~~

Production deployments additionally supply the required MAVI build/commit identity and device policy through normal worker settings.

## Supply-chain rules

Release bundles must not depend on an Internet index, VCS/direct package URL, model-hub lookup, first-run model download, editable/local source install, target compilation or an unreviewed extra wheel.

The wheelhouse must contain exactly the distributions referenced by the selected lock. Extra wheels are a supply-chain error, not harmless cache content.

## Transfer and storage

Treat a completed bundle as immutable:

1. record its `bundleId`;
2. record the SHA-256 of `bundle-manifest.json`;
3. transfer the complete directory without modification;
4. validate all manifest entries after transfer;
5. install only after validation succeeds;
6. retain the reviewed manifest, runtime profile and all qualified runtime locks with release records.

Task 12 does not define organizational signing/PKI. A future signing layer must wrap these immutable hashes rather than replace file-level verification.

## Qualification boundary

The hosted Task-12 workflow proves reproducible wheel locking, no-index installation, compiled-runtime import and local model smoke with invalid proxy endpoints as an accidental-network tripwire.

That is not the formal disconnected-install qualification. Task 17 owns installation and real inference with network connectivity disabled and records the Windows/Linux qualification evidence.

Task 17 distinguishes three post-freeze acceptance layers:

- **candidate disconnected acceptance** against the frozen, internally consistent unverified candidate release + qualification-candidate bundle identities, used to generate release-level evidence before promotion;
- **per-variant production-bundle verification** after promotion, where every required Windows/Linux CPU/CUDA production bundle is disconnected-installed, started under production verification and smoke-tested against its exact shipped bytes;
- **final production-topology acceptance** on the intended operator topology (Windows/IIS + Linux NVIDIA worker), after all per-variant production-bundle smokes pass.

Candidate bundles are built only after the final runtime profile has been constructed and the still-pending qualification record has been rebound to that exact runtime-profile hash. For candidate runs, persisted runtime provenance may legitimately have `platformLockSha256 = null`; candidate lock authority is the validated candidate bundle manifest + selected qualified lock. For production runs, the persisted lock hash is mandatory and must match the production bundle/runtime selection.

Only the final production-topology event completes Phase 1, and it is valid only if every required production bundle has already passed its per-variant disconnected production-mode smoke.
