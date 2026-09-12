# MAVI Offline Vision Runtime Bundle

## Purpose

The MAVI vision runtime is distributed to air-gapped workers as a deterministic directory bundle. The bundle contains the exact Python wheels, model/runtime release metadata, resolved model configuration and approved checkpoint required by one platform variant.

Task 12 produces CPU **qualification-candidate** bundles for:

- `linux-x86_64-cpu` on CPython `3.12.14`;
- `windows-x86_64-cpu` on CPython `3.12.10`.

CUDA bundle qualification remains pending hardware qualification. Task 12 does not promote the model manifest to `verified`, the runtime to `qualified`, or the formal offline-install qualification gates to `passed`.

## Release modes

### Qualification candidate

A qualification-candidate bundle is integrity checked and fully installable from local wheel bytes, but it may carry an `unverified` manifest and `pending` qualification record. It exists so Task 14 can execute true network-disconnected and hardware qualification.

It must not be represented as a production-qualified release.

### Production

The bundle assembler supports production mode only after all release evidence is complete. Production mode fails closed unless the model manifest is `verified`, the runtime is `qualified`, the qualification result is `passed`, all mandatory qualification gates are passed, and the requested platform has a qualified offline lock.

## Prerequisite

The exact CPython patch version for the selected bundle must already be provisioned on the target host.

Task 12 does not bundle or install the operating system, CPython itself, NVIDIA/CUDA drivers or compiler toolchains. Target-machine compilation is prohibited.

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
        <platform-variant>.lock
~~~

A bundle contains only the lock and wheel closure for its own platform variant.

## Integrity contract

`bundle-manifest.json` contains one record for every product file except the manifest itself. Each record contains the relative path, byte size and SHA-256. Wheel records also contain canonical package name and exact version.

The manifest is deterministic: canonical UTF-8/LF JSON with no timestamp, hostname, temporary/absolute build path, random identifier or filesystem modification time.

`bundleId` is derived from immutable release identities, including the source commit, platform variant, runtime/profile/qualification identities and selected release-lock hash.

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
6. retain the reviewed manifest/lock with release records.

Task 12 does not define organizational signing/PKI. A future signing layer must wrap these immutable hashes rather than replace file-level verification.

## Qualification boundary

The hosted Task-12 workflow proves reproducible wheel locking, no-index installation, compiled-runtime import and local model smoke with invalid proxy endpoints as an accidental-network tripwire.

That is not the formal disconnected-install qualification. Task 14 still executes installation and real inference with network connectivity disabled and records the Windows/Linux qualification evidence.
