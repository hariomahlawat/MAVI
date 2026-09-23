# Vision Runtime / Model Component Lifecycle

This runbook defines when the large MAVI Vision offline payloads must be rebuilt and how Development migrates from the legacy monolithic runtime bundle.

## Component boundaries

> **Stage-2 note (2026-09-23):** the table below describes the current detector-era binding, in which the component-requirements file names one Model Pack. Accepted ADR-014 replaces it with capability binding v2 — Runtime Pack families keyed by platform variant, declared roles and `capabilityBindings[]` — when Stage-2 slice S2a is implemented. Until that slice merges, this runbook remains the operative procedure; afterwards it is revised in the same change.

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

## Functional qualification — PR #44

The final exact implementation/documentation head before functional testing was `fea8820a95f00121ee04e735f3e4b53a08d074bc`. All six required GitHub qualification workflows completed successfully on that exact head before the local functional run was accepted:

- MAVI Quality Gate
- Task 10 Runtime Qualification
- Task 12 Offline Runtime Pack
- Task 17 Acceptance Validation
- Vision Runtime Component Boundary
- Vision Model Pack

On 17 Sep 2026, the Development Windows CPU installation reused the already-installed v2 Runtime Binary Pack and v1 Model Pack without replacing their heavy payloads. `Test-MaviEnvironment.ps1 -Profile Development` passed and the worker loaded the locally installed RTMDet checkpoint.

A 1920x1080 source video (`2min.mp4`, duration 2m 28s) was then processed through `phase1-detection-tracking` / `phase1-v1`. During Attempt 2 the host entered sleep/standby at approximately 70 percent progress, interrupting the worker. After worker restart, the existing processing job was automatically recovered as Attempt 3; recovery was job-level retry rather than frame-level continuation. Attempt 3 subsequently reached 100 percent and the authoritative UI recorded both the processing run as `Completed` and the video state as `Processed` at 17 Sep 2026 23:28:14 Asia/Kolkata, with no failure code.

This qualifies the CPU end-to-end path exercised by the test: existing heavy-component reuse, environment verification, worker/model startup, job lease and heartbeat, RTMDet inference/tracking execution, progress reporting, worker-loss retry/recovery, and persisted successful completion. It does **not** qualify CUDA/GPU execution and does not claim frame-level resume after interruption.

The PyTorch/MMDetection deprecation warnings and the non-fatal `data_preprocessor.mean` / `data_preprocessor.std` checkpoint-key warning observed during startup are recorded as technical debt; they did not prevent model readiness or completion of this qualification run. The launcher exit-code-70 semantics observed after the sleep interruption should be reviewed separately and must not be inferred from this run alone.

## Functional testing gate

The 2-minute functional test may be performed only after the target application head has completed exact-head qualification and independent cold review. Preserve the exact Runtime Pack ID, Model Pack ID, application head and final processing result in the qualification record. Do not repeat the expensive CPU video run merely for documentation-only changes unless a subsequent change affects the runtime/model/application execution path or invalidates the evidence.
