# Vision Runtime / Model Component Lifecycle

This runbook defines when the large MAVI Vision offline payloads must be rebuilt and how Development migrates from the legacy monolithic runtime bundle.

## Component boundaries

| Component | Contains | Stable identity | Rebuild when |
| --- | --- | --- | --- |
| Runtime Binary Pack | CPython/native identity, third-party wheels, exact third-party lock, application runtime-requirements projection | `runtimePackId` | dependency declaration/lock/projection, Python/platform/native ABI/toolchain, Runtime Pack schema/builder materially changes |
| Model Pack | RTMDet checkpoint + resolved config | `modelPackId` | checkpoint, resolved config or model identity changes |
| Application / Release Overlay | current `mavi_vision`, pipeline/qualification/release metadata, component requirements | application revision + file fingerprints | normal application development/release changes |

A normal edit under `src/vision/mavi_vision/` does **not** justify rebuilding or downloading the Runtime Binary Pack or Model Pack.

## One-time v1 -> v2 migration

Legacy `mavi-vision-runtime-install-v1` state is deliberately rejected. Perform the migration once:

1. Obtain the qualified Windows CPU Runtime Pack whose `runtimePackId` matches `src/vision/config/components/mmdetection-phase1-v1.json`.
2. Run `tools/setup/Install-MaviVisionRuntime.ps1` with that pack and the current repository root. Installation is offline and uses the reviewed third-party hash lock.
3. Obtain the required Model Pack whose `modelPackId` matches the same component-requirements file.
4. Run `tools/setup/Install-MaviVisionModelPack.ps1` with that pack.
5. Run `tools/setup/Test-MaviEnvironment.ps1 -Profile Development`.
6. Start the worker with `tools/setup/Start-MaviVisionWorker.ps1` only after environment verification passes.

`runtime-install.json` must report `mavi-vision-runtime-install-v2`; `model-install.json` must report `mavi-vision-model-install-v1`.

## Reuse behaviour

The installers verify the supplied candidate pack before considering reuse. Existing installed state must bind the exact installed manifest and installed artifacts must remain valid. Reuse is then based on material component identity. `assembledFromCommit` is provenance only, so rebuilding the same component at a later application commit does not require replacing its heavy bytes.

Application source is supplied from the current checkout through `PYTHONPATH`. Worker startup verifies that `mavi_vision.__file__` resolves under `src/vision`; it does not accept a stale first-party package from the Runtime Pack.

## Offline Binary Kit / component store

After the ordinary offline binary kit has been prepared, reusable Vision packs can be synchronized into its content-addressed component store:

```powershell
$head = (git rev-parse HEAD).Trim()
python tools/vision/sync_offline_vision_components.py sync `
  --kit-root ..\MAVI-Offline-Binary-Kit `
  --runtime-pack <path-to-windows-runtime-pack> `
  --model-pack <path-to-model-pack> `
  --component-requirements src\vision\config\components\mmdetection-phase1-v1.json `
  --application-revision $head

python tools/vision/sync_offline_vision_components.py verify `
  --kit-root ..\MAVI-Offline-Binary-Kit
```

The store uses `vision/runtime/<runtimePackId>` and `vision/models/<modelPackId>`. Re-running synchronization with another provenance manifest for the same material component reuses the existing heavy directory. A reused ID with different material hashes is rejected as a collision.

## What requires a new large download?

A new Runtime Binary Pack is required when its **material identity** changes: root runtime dependencies, exact third-party lock, Python version/platform, native ABI/toolchain or runtime-pack identity schema. A new Model Pack is required when the checkpoint or resolved model config changes. Application source, tests, documentation, qualification prose, workflow run IDs or application commit alone do not require either large component.

## Qualification rule

Heavy-component reuse does not waive qualification. Every release/current application head must still pass the applicable Quality, runtime qualification, acceptance and component-boundary checks against explicitly identified Runtime and Model Pack IDs. Hardware/CUDA qualification is separate and must not be inferred from CPU CI success.

## Functional testing gate

Do not resume the 2-minute video functional test merely because the component files install. Resume it only after PR #44's final exact-head qualification and independent cold review are complete, then perform the one-time local v2 Runtime/Model Pack installation and environment verification.
