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

## Completion contract v3 deployment order

Completion 3.0 carries the Track Evidence Set (up to four role-tagged observations per Track and a per-role evidence accounting block). The platform accepts completion **2.0 and 3.0** from S1.2a; lease, heartbeat and fail stay on control-plane 2.0. Contract artefacts: `contracts/schemas/vision-job-complete-v3.schema.json`, the golden example and its pinned digest (`contracts/test-vectors/vision-job-complete-v3-digest.json`).

1. **Platform (S1.2a).** Apply the `AddTrackEvidenceSet` migration (additive; it refuses to run if any observation carries a retired `TrackStart`/`BestQuality`/`TrackEnd` type), then deploy the platform binary. Verify `GET /api/vision/contract` returns `{"schemaVersion":"2.0","completionSchemaVersions":["2.0","3.0"]}` and that existing 2.0 workers keep completing and replaying idempotently. The staging janitor's first cycle reclaims historical completed-attempt staging once.
2. **Worker with the trajectory spool (S1.2b).** No wire change; 2.0 is still emitted, and trajectory artefacts are byte-identical to the previous worker's. A live Track now keeps at most one chunk of trajectory points in memory (4,096 points, 96 KiB). The rest is spilled to `staging/{jobId}/attempt-NNNN/spool/{trackId}.traj` (24 bytes per point, about 62 MB for a Track that is live for 24 h at 30 fps). Disk use during finalisation: for one Track at a time, the spool, the streamed temp file and the published artefact coexist briefly, peaking at about 3 × 24 bytes × the Track's points. The spool is then removed. Finalisations are sequential. Spools are removed with the attempt directory on failure, by the next attempt after a lease loss, and by the worker right after an accepted completion; the platform staging janitor (ADR-006 §6) remains the crash-safe fallback.
3. **Worker emitting 3.0 (S1.2c).** Profile `1.1` (`profileVersion` 1.2.0-candidate). Before **every** lease the worker calls `GET /api/vision/contract` (one small request per poll). A platform that does not list `"3.0"` (404/405, a malformed answer, or a list without it) keeps the worker **not ready**: it logs `vision_platform_contract_unsupported` once, **never leases**, never falls back to 2.0, and re-probes every poll interval, so it becomes ready by itself once the platform is upgraded. A `400 worker_contract_version_unsupported` at completion fails that attempt with `vision_worker_contract_unsupported` and is not retried by the worker.
   - **What each Track stages.** At retirement, once: the trajectory (`trajectories/{trackId}.msgpack`) and up to four JPEG crops (`evidence/{trackId}-{role}.jpg`, roles `representative`, `near-view`, `early-diverse`, `late-diverse`). No `thumbnails/` directory is written any more.
   - **Memory per live Track.** At most four encoded crops, 64 KiB + 3 × 160 KiB = 544 KiB, plus one trajectory chunk (96 KiB), about 640 KiB in all. Nothing depends on Track or video length, and no raw pixels are kept. Candidate crops are cut and encoded (at most 15 encodes each) only when they would replace a holder.
   - **Staging disk per attempt.** Every Track's crops are staged at retirement. After end of stream, run-level admission keeps every Representative and then admits NearView, EarlyDiverse and LateDiverse in rounds, by score, within the 1 GiB crop quota. Omitted crops are removed before completion, so the accepted set is ≤ 1 GiB. The transient worst case before removal is 10,000 × 544 KiB ≈ 5.19 GiB plus trajectories; a typical run of hundreds of Tracks omits nothing. `evidenceAccounting` in the completion states the candidates, admitted, omitted and bytes per role.
   - **Track limit.** A run that produces more than 10,000 Tracks (the completion's bound) fails at the first extra Track, before anything is staged for it (`vision_processing_failed`). A result that still cannot form a valid 3.0 body fails as `vision_result_invalid` without being sent.
   - **Failure codes.** An accepted Track always has a Representative: before the Track's first qualified frame, the best admissible frame holds the role as a fallback (ADR-013 §4 amendment, accepted 2026-09-24). A Representative is therefore not necessarily qualified evidence; supplemental roles are qualified-only, and completion 3.0 has no per-observation qualified flag. If no crop at all can be encoded within its cap, the attempt fails (`vision_processing_failed`) and its staging is removed.

**Rollback.**

- Worker S1.2c → S1.2b: 2.0 is emitted again and accepted.
- Platform binary after the migration and **before any 3.0 completion exists**: safe. The preceding binary starts against the migrated database; `evidence_rank` defaults to 0 and a `BEFORE INSERT` trigger fills an omitted `selection_score` from `quality_score`, so its 2.0 inserts remain valid.
- Platform binary **after 3.0 completions exist**: unsupported — roll the worker back to 2.0 first; the preceding binary cannot map the new role values.
- Migration down: refused while any non-Representative observation exists; it never deletes evidence bytes.

## Staging reclamation

The platform reclaims worker attempt staging (`{MediaStorage:RootPath}/staging/{jobId}/attempt-NNNN`) with the `vision_jobs` row as its **sole authority**. The worker's own cleanup after completion and at the next lease remains a fast path; the janitor bounds retention when the worker dies or never runs again. It never enumerates outside `staging/`, never opens the evidence root, and deletes handle-relatively without following any symbolic link, junction or reparse point (a linked job or attempt directory is refused and logged).

| Job state | Action |
|---|---|
| `Completed` / `Failed` | every canonical attempt once `CompletedAtUtc + GraceMinutes` has passed, then the empty job directory |
| `Cancelled` (nothing produces it today) | as terminal; logged once (1405) |
| `Leased` | attempts `k < AttemptCount` immediately; never the current or a later attempt |
| `Queued`, `AttemptCount = 0` | preserved; any staging logged once (1401) |
| `Queued`, `AttemptCount > 0` (unreachable) | invariant violation (1406, Error); nothing deleted |
| no row | only after `UnknownJobGraceHours` of directory inactivity (1409, Warning) |

**Configuration** (`StagingJanitor`): `Enabled` (true), `IntervalMinutes` (15), `GraceMinutes` (5), `UnknownJobGraceHours` (24), `MaxDirectoriesPerCycle` (1000), `WarnOldestEligibleMinutes` (60), `ErrorOldestEligibleMinutes` (360). `Enabled=false` stops reclamation without affecting completion, leasing or serving; staging then accumulates until re-enabled.

**Reclamation window.** Normally a completed or failed attempt is gone within `Grace + Interval` (20 minutes with the defaults). This is a target, not a universal guarantee: with a backlog of `B` eligible directories and a per-cycle cap `M`, the bound is `Grace + ⌈(B+1)/M⌉ × Interval`, and a directory that cannot be deleted stays until the obstruction is removed.

**Observability.** EventId 1400 summarises every cycle (`scanned`, `eligible`, `processed`, `removed`, `freedBytes`, `failed`, `deferredByCap`, `oldestEligibleAgeMinutes`, `backlogDepth`, `estimatedCyclesToDrain`). 1401 unrecognised entry; 1402 path escape (Error); 1403 deletion failed (Warning); 1404 the same directory failed three consecutive cycles (Error); 1405 unexpected status; 1406 invariant violation (Error); 1407/1408 backlog age above the warning/critical threshold; 1409 orphan job directory reclaimed; 1410–1413 scheduler lifecycle (disabled, unsupported platform, started, cycle failed). `GET /api/health` exposes `details.stagingJanitor.{enabled,lastRunUtc,lastCycleRemoved,failed,deferredByCap,backlogDepth,oldestEligibleAgeMinutes,consecutiveFailures,backlogState,scanFailed}`. After each cycle:

- `failed`: eligible job directories attempted this cycle and still present because reclamation failed;
- `deferredByCap`: eligible job directories not attempted because of `MaxDirectoriesPerCycle`;
- `backlogDepth`: eligible reclaimable work still outstanding, `deferredByCap + failed`;
- `estimatedCyclesToDrain` (cycle summary): `⌈backlogDepth / MaxDirectoriesPerCycle⌉`, assuming later attempts succeed; it does not predict repeated failures and is zero only when nothing eligible is outstanding;
- `oldestEligibleAgeMinutes`: the oldest outstanding eligible directory, deferred or failed; `backlogState` follows it;
- `scanFailed`: job directories that could not be read, so their eligibility is unknown. They are not backlog and nothing in them is deleted; each is logged (1403, "could not inspect") and escalates with the same three-cycle streak (1404, `consecutiveFailures`).

**Responding.** `backlogState = "critical"` or a repeated 1404: look for a directory the service account cannot delete (read-only file, open handle held by another process, a tree nested deeper than 32 levels); remove the obstruction and the next cycle retries. 1402 means a link or junction was placed under `staging/`: investigate how, remove the link itself (never its target), and the janitor proceeds. Supported platforms are Windows and Linux x64/arm64; elsewhere the janitor logs 1411 and deletes nothing.
