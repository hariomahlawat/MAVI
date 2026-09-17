# ADR-007: Reusable Vision Component Distribution

**Status:** Accepted  
**Date:** 2026-09-17

## Context

The original Task-12 offline bundle coupled the approximately 600 MB Python/OpenMMLab runtime to the first-party `mavi-vision` wheel and repository commit. A normal source edit therefore changed the first-party wheel hash, runtime lock/profile fingerprints and bundle source identity even when no third-party binary, Python ABI or model byte had changed. Development startup then rejected the installed bundle and forced an unnecessary rebuild/download.

That behaviour contradicted the established Development execution model, where the current checkout is intentionally supplied through `PYTHONPATH` over a pinned offline runtime.

## Decision

MAVI Vision distribution is split into three independently identifiable layers.

1. **Runtime Binary Pack** — platform-specific CPython/native identity plus third-party Python wheels, a third-party-only exact-hash lock and the deterministic Application Runtime Requirements Projection. Its stable `runtimePackId` is derived from material runtime inputs; repository/application commit is provenance only.
2. **Model Pack** — immutable checkpoint and resolved MMDetection configuration. Its stable `modelPackId` is derived from model ID, checkpoint SHA-256 and resolved-config SHA-256. Qualification bookkeeping and application commit are not identity inputs.
3. **Application / Release Overlay** — current `mavi_vision` source or packaged first-party artifact, pipeline/release metadata, qualification records and `src/vision/config/components/mmdetection-phase1-v1.json`, which binds an exact application release to compatible Runtime/Model Pack identities.

The Runtime Binary Pack must not contain `mavi-vision`. Application dependency roots are instead projected deterministically from `[project].dependencies` plus `[project.optional-dependencies].vision-runtime` in `src/vision/pyproject.toml` and validated against the complete third-party lock.

Development startup verifies installed component identities and then verifies that `mavi_vision` resolves from the current repository source overlay. Repository ancestry or equality with `assembledFromCommit` is never a compatibility decision.

Component manifests may retain `assembledFromCommit` as informational provenance. Consequently, manifest bytes can differ while material component identity remains unchanged. Installation/reuse first verifies that the existing installed state binds its own installed manifest, then compares the material Runtime/Model Pack identity with the candidate. A provenance-only manifest change must not reinstall unchanged heavy bytes.

## CI and publication rules

- Ordinary `src/vision/mavi_vision/**/*.py` changes do not trigger Task-12 Runtime Pack construction.
- Runtime dependency declarations, reviewed locks/projections, Python/platform/native ABI inputs and Runtime Pack builder/schema changes do trigger the heavy path.
- Model Pack publication is independent and named by stable `modelPackId`.
- Runtime Pack publication is named by stable `runtimePackId`.
- Exact application-head Quality/acceptance/runtime qualification remains mandatory; component reuse never waives testing.
- CUDA remains unqualified until separate hardware qualification is completed.

## Offline Binary Kit

Reusable Vision components are stored content-addressed under the offline kit/component store:

```text
vision/
  runtime/<runtimePackId>/...
  models/<modelPackId>/...
  component-inventory.json
```

`tools/vision/sync_offline_vision_components.py` verifies source pack manifests and every declared artifact before publication. If the same component ID already exists with the same material fingerprint, its heavy bytes are reused. The tool rejects a component-ID collision with different material content. The inventory separately records the Application Overlay revision and component-requirements fingerprint.

## Migration

Existing `mavi-vision-runtime-install-v1` state is not reinterpreted. Development performs a one-time installation of the qualified Windows CPU Runtime Pack v2 and the required Model Pack. Thereafter:

- application-only update: no Runtime/Model Pack replacement;
- model-only update: replace/sync only the Model Pack;
- runtime dependency/ABI change: install a newly qualified Runtime Pack;
- provenance-only rebuild of the same heavy component: reuse the already verified component.

## Consequences

The large runtime/model payloads now have engineering lifecycles based on their actual material inputs rather than source-control churn. Bandwidth and setup time are reduced without weakening SHA-256 verification, exact dependency hashes, offline/no-source-build installation, model/config integrity, platform/ABI checks or exact-head application qualification.

This ADR refines the release/distribution portions of ADR-005; it does not change detector/tracker behaviour, lease authority, watchdog semantics or hardware qualification status.
