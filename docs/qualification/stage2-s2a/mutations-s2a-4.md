# S2a.4 mutation record: Setup / offline-kit integration

- **Plan:** `docs/superpowers/plans/2026-09-28-stage2-s2a-4-setup-offline-integration.md` §8 (mutation and discrimination requirement)
- **Base:** `main@137af862f5bd39740fa234cea9bdc1e6f7b7c4a3`
- **Suites:** `src/vision/tests/test_offline_vision_component_store.py` (the Python `plan` preflight) and `tools/setup/Test-MaviVisionSetupContracts.ps1` (PowerShell 7.4 on Linux, with the repository `.venv` Python)

## Procedure

Each mutation replaced one exact anchor in one file. The guarding suites were then run and the file was restored byte for byte, with its SHA-256 checked after restoration. A mutation counts as **caught** only if at least one guarding suite fails. A committed, green baseline and a clean working tree are checked before the first mutation and between mutations (a run interrupted by a container restart once left a mutation in place; the guard makes that impossible to miss). The four mutations the plan requires are M01 (binding-SHA check), M03 and M04 (the full required-model loop, on the Python and PowerShell sides), M05 (the final compatibility assertion) and M07 (revision made a hard gate).

## Results: 28 of 28 caught

| Id | Mutation | File | Caught by |
|---|---|---|---|
| M01 | binding SHA check removed from the kit plan | `tools/vision/sync_offline_vision_components.py` | `test_a_kit_for_another_binding_is_refused`; Setup contracts: binding mismatch refused before install |
| M02 | binding file-name check removed | `tools/vision/sync_offline_vision_components.py` | `test_a_kit_naming_another_binding_file_is_refused` |
| M03 | only the first enabled Model Pack required | `tools/vision/sync_offline_vision_components.py` | `test_the_plan_names_every_enabled_model_pack_of_the_role`; Setup contracts: composition not ready (`launch_model_pack_not_installed`) |
| M04 | only the first Model Pack of the plan installed | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: composition not ready (`launch_model_pack_not_installed` for the second pack) |
| M05 | final composition assertion skipped | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: install order ends in the readiness check; an incompatible installed set is not READY |
| M06 | assertion failure still reports READY | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: "Vision composition is not ready" expected |
| M07 | `applicationOverlay.revision` made a hard gate (== repository HEAD) | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: revision-reuse kit (revision `777…`, different from HEAD) must install |
| M08 | `kit_incomplete` for a missing Model Pack removed | `tools/vision/sync_offline_vision_components.py` | `test_a_kit_without_any_one_bound_model_pack_is_incomplete[…]`; Setup contracts |
| M09 | missing CPU Runtime Pack replaced by the first inventory runtime | `tools/vision/sync_offline_vision_components.py` | `test_a_kit_without_the_bound_windows_runtime_pack_is_incomplete`; Setup contracts |
| M10 | unbound components accepted | `tools/vision/sync_offline_vision_components.py` | `test_an_unbound_component_in_the_kit_is_refused`; Setup contracts |
| M11 | CPU runtime chosen by inventory order, not by id | `tools/vision/sync_offline_vision_components.py` | `test_a_kit_without_the_bound_windows_runtime_pack_is_incomplete`; Setup contracts (`runtime_requirement_mismatch:platformVariant` on the reordered kit) |
| M12 | D-1: a legacy `bundle-manifest.json` not diagnosed as not installable | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: "not an installable Runtime Pack" expected |
| M13 | D-1: the sibling bundle is seen only when it has a `runtime-pack-manifest.json` (a legacy bundle becomes "absent") | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: a legacy sibling bundle is a source to report, not an absent one |
| M14 | Runtime Bundle pack id check removed (any CPU pack accepted) | `tools/vision/sync_offline_vision_components.py` | `test_a_runtime_bundle_pack_that_is_not_the_bound_one_is_refused`; Setup contracts: foreign CPU pack refused with `kit_unbound_component` (moved from the PowerShell locator, which no longer duplicates the check) |
| M15 | Runtime Bundle: Model Pack presence check removed | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: the runtime-only bundle is refused with the "not installed" diagnosis (first survived because the integrity check below still refused the missing pack with the same code; the case now pins the message) |
| M16 | Runtime Bundle: first manifest taken regardless of variant | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: flat CPU bundle offers no CUDA pack (added after this mutation first survived) |
| M17 | explicit `MAVI_VISION_BUNDLE_ROOT` ignored when a bundle kit exists | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: the explicit root wins over the bundle kit |
| M18 | a missing explicit root falls back instead of failing | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: "is not a directory" expected |
| M19 | a failed Model Pack install skipped, not fatal | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: partial-install failure must name the pack |
| M20 | Model Packs installed in plan order, not `modelPackId` order | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: install order |
| M21 | Setup passes `GetNewClosure()` step blocks | `tools/setup/Setup-MAVI.ps1` | Setup contracts: source pin (a closure lets the installers' `Import-Module -Force` unload Setup's modules; reproduced during implementation) |
| M22 | Setup drops `-VerifyOnly` (no launcher readiness check) | `tools/setup/Setup-MAVI.ps1` | Setup contracts: readiness-boundary source pin |
| M23 | launcher `-VerifyOnly` returns nowhere (check removed) | `tools/setup/Start-MaviVisionWorker.ps1` | Setup contracts: `-VerifyOnly` must stop after the compatibility assertion and before the worker starts |
| M24 | Setup restores a `bundle-manifest.json` probe | `tools/setup/Setup-MAVI.ps1` | Setup contracts: D-1 source pin |
| M25 | combined setup bundle omits the Vision component store (PR review, added after it) | `tools/setup/New-MaviOfflineSetupBundle.ps1` | Setup contracts: bundle-builder source pin |
| M26 | Runtime Bundle preflight trusts an installed Model Pack's status (integrity check bypassed) | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: wrong-size, same-size hash, missing and undeclared artefacts and an unbound `model-install.json` are each refused before any installer runs (without the check they surface only at readiness, after the Runtime Pack install) |
| M27 | Runtime Bundle packs used as located, not proven by the component validator | `tools/setup/Mavi.VisionSetup.psm1` | Setup contracts: foreign CPU pack, damaged CPU and damaged CUDA pack refused before any installer runs |
| M28 | `plan --runtime-pack` skips the component validator | `tools/vision/sync_offline_vision_components.py` | `test_a_damaged_runtime_bundle_pack_fails_the_plan[…]`; Setup contracts |

M16 first survived: no case put a Runtime Pack at the bundle root. The flat-bundle case was added, and M16 is now caught.

## What the contract suite cannot run

`Install-MaviVisionRuntime.ps1` needs Windows, a signed CPython 3.12.10 installer and a wheelhouse. Its step is therefore instrumented: it records the call and does not run the installer. The Model Pack step is the real installer. The readiness step is the launcher's own functions (`Get-MaviVisionBindingRole`, `Resolve-MaviVisionBoundModelPacks`, `Assert-MaviVisionInstalledModelPackIntegrity`, `Assert-MaviVisionWorkerComponentCompatibility`) over the real installed store.

Setup's wiring of the real runtime installer and of `Start-MaviVisionWorker.ps1 -VerifyOnly` is pinned from source (M21–M25). Task 17 runs the suite on PowerShell 7 (Linux) and on Windows PowerShell 5.1.
