# Stage 2 — S2a.4 Setup / offline integration plan

- **Date:** 2026-09-28
- **Status:** implemented on `feature/stage2-s2a-4-offline-kit`; implementation record and errata in the parent plan §20, mutation record `docs/qualification/stage2-s2a/mutations-s2a-4.md`
- **Baseline:** `d99d259f5202815e7f312b3364c74574ead9f005` (`main`, PR #110 merge)
- **Parent plan:** `docs/superpowers/plans/2026-09-27-stage2-s2a-component-binding-v2.md`, especially §§7, 10, 12 and 13
- **Governing decisions:** ADR-014, ADR-007, ADR-009
- **Purpose:** complete the operator/offline-kit integration of Component Binding v2 without changing component identity, qualification semantics, detector behaviour, or the S2a.3 composition architecture.

## 1. Scope boundary

S2a.3 already delivered the v2 binding/resolver cut-over, v2 Runtime/Model Pack contracts, N-pack Python component-store tooling, the minimum v2 Model Pack installer, launcher compatibility checks, and fail-closed worker composition. S2a.4 MUST reuse those mechanisms rather than introduce a second composition resolver in PowerShell.

S2a.4 is limited to:

1. Repairing the pre-existing Setup-MAVI D-1 operator-path defect.
2. Integrating `Setup-MAVI.ps1` with the v2 offline component inventory.
3. Installing the binding-selected Windows Runtime Pack and every enabled Model Pack required by role `vision`.
4. Verifying application-overlay/binding identity before installation.
5. Running the existing launcher/component compatibility assertion after installation.
6. Completing N-pack setup/orchestration tests and the offline/lifecycle runbooks.
7. Running the parent plan's exact-head S2a.4 CI gate.

Explicitly out of scope:

- no RTMDet promotion;
- no Production qualification;
- no CUDA qualification;
- no change to the family-wide Production qualification semantics deferred from S2a.3;
- no new Runtime Pack or Model Pack identity;
- no change to detector/tracker/evidence behaviour;
- no new composition source of truth;
- no S2a.5 qualification-harness cleanup.

## 2. Authoritative composition sources

There is one composition truth: the repository Component Binding v2 plus the v2 component inventory produced from it.

`Setup-MAVI.ps1` MUST NOT independently infer model/runtime compatibility from directory names, model IDs, or legacy bundle layout. It may discover candidate roots, but selection and acceptance are identity-driven.

The existing Python component-store verifier remains authoritative for inventory/component integrity. PowerShell orchestration should call/reuse the existing verification boundary where practical and should perform only the host/install decisions that belong to Setup.

## 3. Preflight-before-mutation rule

S2a.4 adds an explicit two-phase Setup flow.

### Phase A — preflight (no installation mutation)

Before invoking either installer, Setup MUST establish all of the following:

1. Repository Component Binding v2 exists and is valid.
2. If the v2 kit path is used, `vision/component-inventory.json` exists, has schema `mavi-offline-vision-component-inventory-v2`, and passes the existing component-store verification.
3. `applicationOverlay.componentBindingSha256` equals the SHA-256 of the repository binding. Mismatch fails `kit_binding_mismatch`.
4. `applicationOverlay.componentBinding` identifies the expected binding file.
5. `applicationOverlay.revision` is a valid 40-hex provenance value. It is recorded/reported but is **not** an independent compatibility gate when the binding SHA matches: the component store is intentionally reusable across application commits, and Component Binding v2 is the composition identity. A revision difference must not override a matching binding identity or manufacture a second composition rule.
6. The Windows CPU Runtime Pack required by the role's runtime family is present exactly once in inventory and its source contains `runtime-pack-manifest.json`.
7. Every enabled Model Pack required by role `vision` is present exactly once and its source contains `model-pack-manifest.json`.
8. No unbound component is selected for installation.
9. All required source directories are readable and resolve beneath the expected kit/component root; traversal/symlink protections remain fail closed through the existing verifier.

Only after the complete required set passes preflight may Setup begin installation.

Implementation note (parent plan §20, E4-15/E4-16): the preflight covers every component Setup will rely on, whether it comes from the selected source or is already installed. Packs from a component store or a Runtime Bundle are re-hashed by the store's component validator, and an already-installed Model Pack passes the launcher's per-pack checks (`Assert-MaviVisionInstalledModelPackIntegrity`) before the first installer runs.

The legacy/manual Runtime Bundle path remains supported only where already intentionally supported, but D-1 is repaired: installability is determined by `runtime-pack-manifest.json`, never by legacy `bundle-manifest.json`. A directory containing only `bundle-manifest.json` is reported as not installable and is never treated as a valid Runtime Pack.

## 4. Installation orchestration

For Development setup with an attached repository:

1. Resolve the observed target as `windows-x86_64-cpu` for the mandatory CPU installation path.
2. Resolve the required Runtime Pack ID from Component Binding v2.
3. Resolve its source from the verified component inventory (or the existing explicit Runtime Bundle root when using that supported manual source).
4. Invoke the existing `Install-MaviVisionRuntime.ps1`; do not duplicate Runtime Pack validation/install logic.
5. Resolve all enabled Model Pack IDs for role `vision` from the binding.
6. Resolve each Model Pack source from the verified inventory and invoke the existing v2 `Install-MaviVisionModelPack.ps1` for each pack in deterministic ID order.
7. After all required installs succeed, invoke/reuse the existing worker component compatibility assertion used by the launcher. A runtime-only or partial model installation is a setup failure, not INFO and not READY.
8. CUDA remains optional/pending exactly as defined by the binding/runtime profile. S2a.4 must not promote or synthesize a CUDA pack.

Setup MUST NOT set legacy v1 composition environment variables or reinterpret v1 install state.

## 5. Failure and rerun semantics

The individual Runtime/Model Pack installers retain their existing staging/swap guarantees. S2a.4 MUST NOT claim that the multi-pack Setup operation is globally transactional.

If component N fails after earlier components were installed successfully:

- Setup exits failed and names the failing component/reason;
- already-completed valid installations are left intact;
- no READY/success message is emitted;
- a subsequent run re-preflights the complete desired set and converges idempotently, reusing valid installed components where existing installer semantics permit;
- Setup never rolls back a previously valid component merely because a later independent component failed.

This behaviour must be documented in the runbook so operators do not mistake partial physical installation for a valid MAVI composition. Compatibility validation is the final readiness boundary.

## 6. Fail-closed error contract

Retain parent-plan codes:

- `kit_incomplete:<id>`
- `kit_unbound_component:<id>`
- `kit_binding_mismatch`
- launcher/installer v2 codes already introduced by S2a.3

No new application-revision mismatch error is introduced: `applicationOverlay.revision` is provenance, while `componentBindingSha256` is the composition compatibility boundary.

Do not create aliases for existing launcher/installer errors merely because Setup surfaces them.

## 7. Required implementation surfaces

Expected primary files (the implementation may touch directly related tests/docs discovered during coding, but scope expansion requires explanation in the PR):

- `tools/setup/Setup-MAVI.ps1`
- `tools/setup/Sync-MaviOfflineVisionComponentStore.ps1`
- relevant `tools/setup/Test-*.ps1` contract tests
- `src/vision/tests/test_offline_vision_component_store.py` only if a missing inventory invariant belongs in the Python verifier
- `tools/vision/sync_offline_vision_components.py` only for a proven verifier gap; do not rewrite working N-pack logic
- `docs/runbooks/vision-runtime-model-component-lifecycle.md`
- `docs/runbooks/mavi-offline-setup.md`
- parent S2a plan implementation record/status references as appropriate

The implementation should prefer a small shared Setup helper over embedding a second large parser/resolver in `Setup-MAVI.ps1`.

## 8. Discriminating tests

At minimum, tests must prove:

1. **D-1:** `bundle-manifest.json` without `runtime-pack-manifest.json` is not installable; the old INFO/false-positive path cannot return.
2. **Binding mismatch:** inventory binding SHA differs from the live repository binding → `kit_binding_mismatch`, with zero installer invocation.
3. **Revision reuse:** inventory `applicationOverlay.revision` differs from repository HEAD while `componentBindingSha256` matches → preflight remains valid; revision is retained/reported as provenance and no second composition gate is created.
4. **Missing runtime:** bound Windows CPU Runtime Pack absent → fail before mutation.
5. **Missing model:** any enabled role Model Pack absent → fail before mutation.
6. **N-model install:** two or more enabled Model Packs in a fixture are all selected and installed; no first-pack/singular assumption.
7. **Unbound component:** unbound pack cannot be selected/installed.
8. **Partial installer failure:** a later Model Pack install failure yields overall failure and never emits READY/success; rerun is safe.
9. **Final compatibility:** syntactically successful installs with an incompatible installed set fail the existing compatibility assertion.
10. **Legacy state:** v1 model install state remains rejected; no compatibility fallback is introduced.
11. **CUDA non-promotion:** absent/pending CUDA does not become qualified or required by this slice.
12. **Identity freeze:** S2a.4 changes no `modelPackId`, `runtimePackId`, manifest material SHA, detector config/checkpoint SHA, or qualification status.

Mutation/discrimination requirement: at least remove/disable each of the binding-SHA check, full required-model loop, and final compatibility assertion and demonstrate that the corresponding test fails. Also mutate revision handling to make revision equality a hard gate and prove the revision-reuse test catches that regression. Record these mutations with the S2a evidence convention.

## 9. Documentation requirements

Update both runbooks to show:

- v2 inventory layout (`vision/runtime/<runtimePackId>`, `vision/models/<modelPackId>`, `vision/component-inventory.json`);
- Component Binding v2 as composition authority;
- `applicationOverlay.revision` as provenance rather than an independent compatibility identity;
- preflight-before-install behaviour;
- Runtime + all bound Model Packs installation order;
- partial physical installation versus valid READY composition;
- safe rerun/idempotent recovery;
- explicit Development/Production and CPU/CUDA non-claims;
- removal of any operator instruction that relies on `bundle-manifest.json` for Runtime Pack installability.

Internal planning language must not leak into operator-facing instructions.

## 10. Exact-head acceptance gate

Before merge, on one immutable S2a.4 head SHA:

- Quality Gate — complete and green;
- Task 12 — complete and green;
- Vision Model Pack — complete and green;
- Task 17 — complete and green, including D-1 and the new preflight contract tests;
- `verify_repo` green;
- no unresolved P1/P2 review findings;
- no unresolved review threads;
- PR mergeable;
- changed-file review confirms the slice contains no qualification/promotion change and no component-identity drift.

If any required workflow reruns because the head changes, acceptance is against the new exact head only.

## 11. Post-merge handoff

S2a.4 completion means the v2 architecture is installable through the supported offline/operator path. It does **not** close S2a.

S2a.5 remains responsible for the final S2a reconciliation/evidence/documentation closure and the final Task-10 evidence run defined by the parent plan. The family-wide Production qualification issue deferred from PR #110 remains a separate promotion/qualification decision and must not be silently resolved in S2a.4.