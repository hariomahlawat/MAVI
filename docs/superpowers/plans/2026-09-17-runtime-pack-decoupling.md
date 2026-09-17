# MAVI Vision Runtime Pack Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple the approximately 600 MB MAVI Vision third-party runtime and model assets from ordinary first-party `mavi_vision` source changes while preserving exact-head qualification, offline determinism and fail-closed integrity.

**Architecture:** Introduce deterministic component identities: a third-party Runtime Binary Pack, a content-addressed Model Pack, and a small first-party Application/Release Overlay. Replace the `mavi-vision` wheel as the runtime-lock dependency root with a deterministic requirements projection generated from `pyproject.toml`, then make installation/startup compatibility component-fingerprint based instead of repository-commit based.

**Tech Stack:** Python 3.12, `packaging`, deterministic text/JSON manifests, PowerShell 5.1-compatible setup scripts, GitHub Actions, pytest, pip offline `--require-hashes` installs.

**Spec:** `docs/superpowers/specs/2026-09-17-runtime-pack-decoupling-design.md`

## Global Constraints

- Ordinary `src/vision/mavi_vision/**/*.py` changes must not change the third-party lock or Runtime Binary Pack identity.
- `[project].dependencies` plus `[project.optional-dependencies].vision-runtime` are the application runtime dependency roots; `dev` dependencies are excluded.
- Third-party runtime installation remains `--no-index --only-binary=:all: --require-hashes`.
- `mavi-vision` must be absent from the third-party lock and heavy runtime wheelhouse.
- Windows CPU remains CPython `3.12.10`; Linux CPU remains CPython `3.12.14`.
- Existing checkpoint/config SHA-256 verification and checkpoint/model-key compatibility remain mandatory.
- Existing v1 installed state is not silently accepted as v2.
- Exact-head application qualification remains mandatory when heavy components are reused.
- CUDA remains unqualified and no fallback semantics change.

---

### Task 1: Deterministic application runtime requirements projection

**Files:**
- Create: `src/vision/mavi_vision/runtime/requirements_projection.py`
- Create: `src/vision/tests/test_runtime_requirements_projection.py`

**Interfaces:**
- Produces `RuntimeRequirementsProjection(schema_version, platform_variant, python_version, requirements)`.
- Produces `build_runtime_requirements_projection(pyproject_path, platform_variant, python_version) -> RuntimeRequirementsProjection`.
- Produces `serialize_runtime_requirements_projection(projection) -> bytes` and `runtime_requirements_sha256(projection) -> str`.

- [ ] Write tests proving deterministic ordering, union of project + `vision-runtime` roots, dev exclusion, marker evaluation, duplicate-compatible root coalescing, direct-URL rejection, and source-only file independence.
- [ ] Run the targeted pytest module and confirm failures before implementation.
- [ ] Implement strict parsing with `tomllib`, `packaging.Requirement`, existing target marker semantics, canonical names and LF/UTF-8 deterministic serialization.
- [ ] Re-run targeted tests to green.
- [ ] Commit `feat: add deterministic vision runtime requirements projection`.

### Task 2: Third-party-only offline lock validation

**Files:**
- Modify: `src/vision/mavi_vision/runtime/offline_lock.py`
- Modify: `tools/vision/freeze_offline_lock.py`
- Create: `src/vision/tests/test_offline_lock_runtime_roots.py`
- Modify existing offline-lock/freeze tests as required.

**Interfaces:**
- `validate_offline_runtime_lock_for_runtime(..., root_requirements=tuple[str, ...], ...)` validates every application root against the lock.
- `freeze_offline_lock.py` accepts `--exclude-distribution mavi-vision` or equivalent explicit first-party exclusion and fails if excluded first-party content is accidentally retained.

- [ ] Add failing tests that a lock without `mavi-vision` is valid when all projected roots are present, `mavi-vision` in the lock is rejected, missing root is rejected, incompatible root version is rejected, and transitive wheel dependency omission is rejected.
- [ ] Remove the `offline_lock_mavi_missing` invariant and replace it with explicit third-party-only + root-requirement validation.
- [ ] Ensure freeze/closure validation remains complete without the first-party wheel by validating projected roots separately from transitive wheel metadata.
- [ ] Run all offline-lock/freeze tests.
- [ ] Commit `refactor: make vision offline lock third-party only`.

### Task 3: Component identity manifests

**Files:**
- Create: `src/vision/mavi_vision/runtime/component_identity.py`
- Create: `src/vision/tests/test_component_identity.py`
- Modify: `tools/vision/build_offline_bundle.py`

**Interfaces:**
- `RuntimePackIdentity` derives from schema, platform, Python identity, third-party lock SHA-256, runtime-requirements SHA-256, and native ABI/toolchain identity.
- `ModelPackIdentity` derives from schema, model ID, checkpoint SHA-256 and resolved-config SHA-256.
- Runtime manifest schema `mavi-vision-runtime-pack-v2` has informational `assembledFromCommit` only.
- Model manifest schema `mavi-vision-model-pack-v1` enumerates asset hashes/sizes.

- [ ] Add tests proving application commit/source changes do not alter Runtime Pack ID, runtime input changes do, application/qualification bookkeeping does not alter Model Pack ID, and model-byte/config changes do.
- [ ] Implement canonical JSON identity hashing with sorted keys and LF/UTF-8 bytes.
- [ ] Refactor bundle builder so runtime wheels and model assets are represented as separate component manifests/roots; first-party wheel is not included in runtime wheels.
- [ ] Preserve all path, symlink, undeclared-file and copy-hash protections.
- [ ] Run bundle/component tests.
- [ ] Commit `feat: add content-derived vision runtime and model pack identities`.

### Task 4: Regenerate third-party locks and runtime profile bindings

**Files:**
- Modify: `src/vision/runtime/mmdetection-phase1-v1/windows-x86_64-cpu.lock`
- Modify: `src/vision/runtime/mmdetection-phase1-v1/linux-x86_64-cpu.lock`
- Modify: `src/vision/runtime/mmdetection-phase1-v1/runtime.json`
- Modify: `models/qualifications/rtmdet-m-coco-phase1-v1.json` only for new component-binding fields required by the schema.

**Interfaces:**
- CPU locks contain no `mavi-vision` row.
- Runtime profile records third-party lock hashes and runtime requirements fingerprints independently of application commit.

- [ ] Generate expected lock bytes by removing only the first-party distribution from the reviewed exact closure and recomputing lock SHA-256 values.
- [ ] Update runtime profile release-lock hashes and component-binding fields.
- [ ] Add/adjust validation tests proving the tracked locks match projected roots and semantic graph.
- [ ] Commit `build: rebind vision runtime to third-party-only locks`.

### Task 5: Task-12 CI split and no-heavy-rebuild invariant

**Files:**
- Modify: `.github/workflows/task12-offline-bundle.yml`
- Modify: `.github/workflows/task10-runtime-qualification.yml` as necessary for reused component IDs.
- Add lightweight component-boundary verification under `tools/vision/` if workflow shell logic would otherwise duplicate Python logic.

**Interfaces:**
- Heavy Task-12 workflow path filters exclude ordinary `src/vision/mavi_vision/**` source edits.
- Task-12 no longer builds `mavi-vision` into `.task12-wheelhouse`.
- Requirements projection is generated and validated against the tracked third-party lock.
- Heavy artifact names use stable component IDs rather than application commit SHAs where practical.
- Exact-head application/runtime probe still executes in the appropriate acceptance/runtime qualification gate and records reused component IDs.

- [ ] Add a lightweight CI/test assertion encoding which paths invalidate Runtime Binary Pack identity.
- [ ] Remove `Build MAVI Vision wheel` from heavy runtime assembly and remove `mavi-vision` from locally materialized runtime distributions.
- [ ] Materialize projected root requirements and validate the wheelhouse/lock against them.
- [ ] Narrow heavy workflow path filters so normal first-party source does not trigger a 600 MB rebuild/upload.
- [ ] Preserve manual `workflow_dispatch` for deliberate qualification.
- [ ] Ensure Task-10/application acceptance evidence records exact application head + reused runtime/model IDs.
- [ ] Commit `ci: decouple heavy vision runtime publication from app source`.

### Task 6: Installed state v2 and idempotent runtime reuse

**Files:**
- Modify: `tools/setup/Install-MaviVisionRuntime.ps1`
- Modify: `tools/setup/Mavi.Setup.Common.psm1`
- Modify/add setup verification script tests where repository conventions permit.

**Interfaces:**
- Installed state schema is `mavi-vision-runtime-install-v2`.
- State records `runtimePackId`, `runtimePackManifestSha256`, `thirdPartyLockSha256`, `runtimeRequirementsSha256`, platform and Python identity; source commit is informational only if retained.
- Installer detects an already valid identical Runtime Pack and returns successfully without staged venv replacement.
- v1 state requires one-time migration/reinstallation.

- [ ] Add helper-level tests/self-tests for v2 state validation and same-pack reuse decision.
- [ ] Remove commit equality/source-diff from runtime installation compatibility.
- [ ] Verify bundle/runtime manifest hashes before deciding reuse.
- [ ] Implement no-op reuse only when all v2 fingerprints and interpreter identity match.
- [ ] Preserve staged atomic replacement when pack ID differs.
- [ ] Commit `feat: install and reuse vision runtime by component identity`.

### Task 7: Development startup component compatibility

**Files:**
- Modify: `tools/setup/Start-MaviVisionWorker.ps1`
- Modify: `tools/setup/Mavi.Setup.Common.psm1`
- Modify: `tools/setup/Test-MaviEnvironment.ps1`

**Interfaces:**
- Startup computes/reads the current checkout's required runtime/model fingerprints and compares them with v2 installed state/manifests.
- Repository HEAD is retained only as `MAVI_COMMIT_SHA` application provenance.
- Existing verified `PYTHONPATH` source overlay remains mandatory.

- [ ] Add tests/self-test fixtures: source-only HEAD difference accepted, runtime fingerprint difference rejected, wrong model ID rejected, malformed/v1 state rejected, overlay import outside checkout rejected.
- [ ] Retire `Assert-MaviVisionRuntimeSourceCompatible` from the decision path.
- [ ] Add component-fingerprint validation helpers with stable error messages.
- [ ] Re-run setup/environment validation.
- [ ] Commit `fix: bind vision worker startup to component fingerprints`.

### Task 8: Offline Binary Kit component inventory

**Files:**
- Modify: `tools/setup/New-MaviOfflineBinaryKit.ps1`
- Modify: `tools/setup/Test-MaviOfflineBinaryKit.ps1`
- Modify related offline setup/binary inventory docs/config files discovered by the implementation.

**Interfaces:**
- Inventory distinguishes Runtime Binary Pack, Model Pack and Application Overlay identities.
- Unchanged heavy components are deduplicated/reused by component ID + SHA-256.

- [ ] Add verification for duplicate/conflicting component IDs and stable reuse.
- [ ] Update kit creation to keep reusable heavy components independent from application revision.
- [ ] Run binary-kit validation.
- [ ] Commit `feat: inventory offline vision artifacts by component identity`.

### Task 9: Documentation and migration record

**Files:**
- Modify: `docs/decisions/ADR-005-qualified-vision-runtime.md`
- Modify setup/offline installation documentation located during implementation.
- Modify Task-12/Task-17 planning/status documentation where it records the old commit-bound runtime model.

- [ ] Document Runtime Pack / Model Pack / Application Overlay lifecycle and the root-requirements projection.
- [ ] Document one-time `runtime-install-v1` -> v2 migration and subsequent reuse behaviour.
- [ ] Document which future changes require a heavy binary-kit refresh and which do not.
- [ ] Commit `docs: document reusable vision runtime component lifecycle`.

### Task 10: Full verification and cold review

**Files:** none unless verification exposes defects.

- [ ] Run Python Vision tests and repository verification gates.
- [ ] Run/observe GitHub Quality Gate, Task-10 Runtime Qualification, Task-12 Offline Bundle where intentionally triggered, and component-boundary/acceptance gates.
- [ ] Prove a source-only mutation changes application HEAD while leaving runtime lock/pack identity unchanged.
- [ ] Prove a dependency-root mutation invalidates the required runtime identity.
- [ ] Confirm Task-12 heavy artifact is not automatically regenerated for a source-only path.
- [ ] Perform an independent cold code/config review against the spec.
- [ ] Fix all findings and rerun affected checks.
- [ ] Only after exact-head checks are green, generate/install the one-time canonical Windows CPU v2 Runtime Binary Pack and resume functional video testing.
