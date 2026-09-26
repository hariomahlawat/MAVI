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

Completion 3.0 carries the Track Evidence Set (up to four role-tagged observations per Track and a per-role evidence accounting block). The platform accepted completion **2.0 and 3.0** from S1.2a; **S1.4 F2 adds completion 3.1 behind an activation gate** (`VisionFinalization:Enabled`; worker `MAVI_COMPLETION_SCHEMA_VERSION`). **Since S1.4 F4-C both ship on**: `Enabled` defaults to `true` and the worker to `3.1`. The platform held off by an override and a worker pinned to `3.0` are the rollback pair: the probe then lists `["2.0","3.0"]` and 3.0 completes synchronously. Activated, the probe lists `["2.0","3.1"]`, 3.1 is the same body answered by a durable `finalizing` hand-off, live 3.0 is refused (`worker_contract_version_unsupported`), and the 3.1 worker keeps the current attempt's staging for the platform finalizer — see `docs/superpowers/plans/2026-09-25-s1-4-b3-asynchronous-finalization.md` §5, §6, §15. The S1.2 history below is unchanged; lease, heartbeat and fail stay on control-plane 2.0. Contract artefacts: `contracts/schemas/vision-job-complete-v3.schema.json`, the golden example and its pinned digest (`contracts/test-vectors/vision-job-complete-v3-digest.json`).

1. **Platform (S1.2a).** Apply the `AddTrackEvidenceSet` migration (additive; it refuses to run if any observation carries a retired `TrackStart`/`BestQuality`/`TrackEnd` type), then deploy the platform binary. Verify `GET /api/vision/contract` returns `{"schemaVersion":"2.0","completionSchemaVersions":["2.0","3.0"]}` and that existing 2.0 workers keep completing and replaying idempotently. The staging janitor's first cycle reclaims historical completed-attempt staging once.
2. **Worker with the trajectory spool (S1.2b).** No wire change; 2.0 is still emitted, and trajectory artefacts are byte-identical to the previous worker's. A live Track now keeps at most one chunk of trajectory points in memory (4,096 points, 96 KiB). The rest is spilled to `staging/{jobId}/attempt-NNNN/spool/{trackId}.traj` (24 bytes per point, about 62 MB for a Track that is live for 24 h at 30 fps). Disk use during finalisation: for one Track at a time, the spool, the streamed temp file and the published artefact coexist briefly, peaking at about 3 × 24 bytes × the Track's points. The spool is then removed. Finalisations are sequential. Spools are removed with the attempt directory on failure, by the next attempt after a lease loss, and by the worker right after an accepted completion; the platform staging janitor (ADR-006 §6) remains the crash-safe fallback.
3. **Worker emitting 3.0 (S1.2c).** Profile `1.1` (`profileVersion` 1.2.0-candidate). Before **every** lease the worker calls `GET /api/vision/contract` (one small request per poll). A platform that does not list `"3.0"` (404/405, a malformed answer, or a list without it) keeps the worker from leasing: it logs `vision_platform_contract_unsupported` once, **never leases**, never falls back to 2.0, and re-probes every poll interval, so it becomes ready by itself once the platform is upgraded. A `400 worker_contract_version_unsupported` at completion fails that attempt with `vision_worker_contract_unsupported` and is not retried by the worker.
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

## Asynchronous finalization (S1.4 B3 F3): activation, rollback, health

The platform finalizer (`VisionFinalizationHostedService`, in the API host) consumes completion 3.1 hand-offs: it claims a `Finalizing` job, revalidates the retained payload, seals the attempt's staged evidence into the accepted root, publishes the Track/Observation/Artifact graph under the completion barrier and moves the job, run and video to their terminal state. PostgreSQL is the only authority for hand-off, ownership, attempts, the deadline and publication; no lock file, no separate process. Design: `docs/superpowers/plans/2026-09-25-s1-4-b3-f3-finalizer-recovery-implementation.md`.

**Shipped default is on (S1.4 F4-C).** `VisionFinalization:Enabled = true` in the shipped `appsettings.json`, and the worker's default `completion_schema_version` is `3.1`. The timing values are the F4 freeze (`docs/qualification/stage2-s1/f4-configuration-freeze.md`). A deployment moving onto this release follows the activation sequence below; do not simply restart a mixed fleet onto it. When held off by an override, the platform advertises and accepts 2.0 and 3.0 synchronously, refuses 3.1, no job can enter `Finalizing`, and the finalizer host only refreshes its read-only health counts (event 1500).

**Holding the gate off** (activation step 1, rollback step 4). Use one of these on each API host; none is a file in the repository:
- **Windows:** the machine configuration file `%ProgramData%\MAVI\config\appsettings.machine.json` (Production), or `%ProgramData%\MAVI\Development\config\appsettings.development.machine.json` (Development), with `{"VisionFinalization":{"Enabled":false}}`;
- **any OS:** `MAVI_MACHINE_CONFIG=<path to such a file>`;
- **any OS, highest precedence:** the environment variable `VisionFinalization__Enabled=false`.

**On Linux there is no default machine-configuration path**, so use `MAVI_MACHINE_CONFIG` or the environment variable.

**Activation sequence** (F3 plan §13.1; S1.4 F4 execution plan §11.3). The completion contract changes between `["2.0","3.0"]` and `["2.0","3.1"]`, and restarting a fleet of API hosts is not atomic. **No worker may lease while the hosts could disagree.** For example, a 3.0 worker that probed a gate-off host and leased would have its completion refused by a gate-on host (`worker_contract_version_unsupported`). Rollback has the inverse race.

The worker fleet is therefore stopped for the whole contract change in both directions:
- it is started only after every host has been verified directly on the new contract;
- load-balancer affinity is never relied on.

When enabled, 3.0 is refused (`worker_contract_version_unsupported`) and the finalizer polls. All hosts must carry the same value: a host with the gate off refuses 3.1 and finalizes nothing.

1. **Platform on the new binary, gate held off.**
   - Deploy the platform binary on every API host with `VisionFinalization:Enabled = false`. The binary's shipped default is `true`, so hold it `false` with an override (see **Holding the gate off** above).
   - On **each host directly**, not through the load balancer, confirm three things:
     - `GET /api/health` shows `details.visionFinalization.enabled = false`, with no options validation error;
     - `GET /api/vision/contract` lists `completionSchemaVersions` exactly `["2.0","3.0"]`;
     - `malformedClaims == 0`.
   - Workers keep running on 3.0 during this step, and only if pinned to it: a worker host upgraded to the F4-C worker package, whose default is 3.1, must set `MAVI_COMPLETION_SCHEMA_VERSION = 3.0` until step 5. Otherwise it fails closed at the probe (it leases nothing), which is safe but stalls processing.
2. **Quiesce the worker fleet.** Stop every worker and keep it stopped: disable any service-manager restart, and confirm on every worker host that no worker process runs.
   - A job a stopped worker had leased returns to the queue when its lease expires.
   - Only that attempt's inference is lost.
3. **Change the contract on every host.** Set `VisionFinalization:Enabled = true`, or remove the override, on every API host. Restart every host.
4. **Verify every host.** On each host directly:
   - `details.visionFinalization.enabled = true`;
   - `completionSchemaVersions` exactly `["2.0","3.1"]`;
   - `malformedClaims == 0`.

   Do not continue until every host passes.
5. **Start workers on 3.1.** Set `MAVI_COMPLETION_SCHEMA_VERSION = 3.1` (or install the worker package whose default is 3.1) on every worker and start them.
   - Each worker probes the contract before every lease.
   - Confirm in each worker's log that its first lease followed a probe listing `"3.1"`, with no `vision_platform_contract_unsupported`.
6. **Watch the finalizer.** In `details.visionFinalization`:
   - `finalizingJobs` rises with hand-offs and falls as jobs publish;
   - `liveClaims` stays at most the number of hosts × `MaxConcurrentFinalizations`;
   - `malformedClaims` stays 0.

**Rollback / disable** (F3 plan §13.3). Disabling the gate stops new hand-offs **and** the finalizer, so `Finalizing` rows must be drained first, with the worker fleet stopped for the whole change:

1. **Quiesce the worker fleet.** Stop every worker and keep it stopped, as in activation step 2.
   - Every API host stays **enabled**, so the finalizer keeps draining.
   - No new hand-off can arrive.
   - A hand-off that landed as a worker stopped is a `Finalizing` row, which step 2 drains.
2. **Drain.** Poll `GET /api/health` until `details.visionFinalization.finalizingJobs == 0` **and** `countsRefreshedAtUtc` is within the last two `PollIntervalSeconds`.
   - Any host will do: the count is PostgreSQL's row count across the deployment.
   - Confirm `enabled = true` on each host while draining.
3. **Malformed claims.** If `malformedClaims > 0`, stop: those rows never drain on their own (below).
4. **Change the contract on every host.** Hold `VisionFinalization:Enabled = false` on every API host with an override (see **Holding the gate off** above; the shipped default is `true`). Restart every host.
5. **Verify every host.** On each host directly:
   - `details.visionFinalization.enabled = false`;
   - `completionSchemaVersions` exactly `["2.0","3.0"]`.

   Do not continue until every host passes.
6. **Start workers on 3.0.** Set `MAVI_COMPLETION_SCHEMA_VERSION = 3.0` on every worker and start them. Confirm in each worker's log that its first lease followed a probe listing `"3.0"`.

A pre-F1 platform binary is never deployed while `Finalizing` rows or unfinished payload rows exist: the `AddVisionFinalization` migration's `Down` refuses.

**Configuration** (`VisionFinalization`, as shipped): `Enabled` (true), `MaxConcurrentFinalizations` (1: the host shares the API process), `PollIntervalSeconds` (5), `ClaimSeconds` (480), `ClaimExtensionSeconds` (300; must not exceed `ClaimSeconds`), `MaximumFinalizationAttempts` (3), `MaximumFinalizationDurationSeconds` (21600), `SealingBatchSize` (200), `PayloadCleanupGraceSeconds` (0). The timing values are frozen by F4 from M1 measurement (`docs/qualification/stage2-s1/f4-configuration-freeze.md`); with them the effective bound below is 22,085 s (≈ 6.13 h). **Effective bound:** the absolute deadline `FinalizationAcceptedAtUtc + MaximumFinalizationDurationSeconds` stops new claims and extensions, but a claim that is live at the deadline runs to its granted expiry, so a job is Completed or Failed no later than `MaximumFinalizationDurationSeconds + ClaimSeconds` after its hand-off (plus one poll interval for reconciliation to observe it). After that, reconciliation fails the job with `vision_finalization_exhausted` (the run and video fail with the same code); reprocessing creates a new run and job as usual.

**Failure codes** (`FailureCode` on the job and `ErrorCode` on the run; never a detector/tracker code): deterministic `vision_finalization_payload_missing`, `vision_finalization_payload_integrity_failed`, `vision_finalization_payload_invalid`, `vision_finalization_staging_missing`, `vision_finalization_staging_integrity_failed`, `vision_finalization_evidence_conflict`, `vision_finalization_context_invalid`; reconciliation `vision_finalization_exhausted`; transient (recorded in `FinalizationLastErrorCode`, retried) `vision_finalization_io_transient`, `vision_finalization_db_transient`, `vision_finalization_publication_ambiguous`. A job that failed after sealing began leaves accepted objects under `evidence/{jobId}/attempt-NNNN/` that no publication references (event 1509 gives their count and bytes); the finalizer never deletes accepted evidence (ADR-006 §7) and no collector exists yet.

**Malformed claim metadata** (`malformedClaims > 0`, event 1512 once per job per host): a `Finalizing` row whose claim columns are not all null and not all present (`finalization_claim_token_hash`, `finalization_claim_expires_at_utc`, `finalization_claim_extended_at_utc`). Only a direct database edit produces it. The finalizer never claims, exhausts or repairs such a row. Investigate how it arose; to release it, restore a canonical state by hand (all three columns `NULL` makes it claimable again if attempts and the deadline permit) and let the next cycle decide, or fail it deliberately with the platform's usual failure transitions.

**Health.** `GET /api/health` exposes `details.visionFinalization.{enabled,finalizingJobs,liveClaims,malformedClaims,oldestFinalizingAcceptedAtUtc,countsRefreshedAtUtc,inFlight,lastCycleUtc,lastCycleClaimed,lastCycleExhausted,lastCyclePayloadsCleaned}`. The first five come from PostgreSQL (`vision_jobs` where `status = 'Finalizing'`) and are refreshed every cycle, and every poll interval while disabled; `countsRefreshedAtUtc` is `null` until the first successful count. The rest are this host's own.

**Events.** 1500 disabled (counts-only mode); 1501 started; 1502 claimed; 1503 claim extended (Debug); 1504 published (tracks, objects created/adopted and bytes, seal/publish/total timings, hand-off-to-publish latency); 1505 deterministic failure (Warning); 1506 transient noted, claim released (Warning); 1507 claim lost, nothing written (Warning); 1508 reconciliation exhausted N jobs (Error); 1509 orphan accounting after a failure (Warning); 1510 payload rows cleaned; 1511 cycle failed (Error; exception type only); 1512 malformed claim metadata or an unexhaustable row (Error, once per job per host); 1513 deadline reached with a live claim (Warning); 1514 stopped for host shutdown, nothing written. No event carries a claim token, lease token, storage path or exception message.

## S1.4 disconnected qualification of the asynchronous path (F4 plan §19)

The S1.4 disconnected unit is an operator run on an isolated Development host, executed on the exact measured `main` SHA (M2) and recorded as `s1-disconnected-run-v2`. It qualifies the **activated** completion path: a run on the synchronous 3.0 path is refused by the evidence checker. Nothing here is hosted CI.

1. **Bundle from the measured code.** On a connected build host, build the Runtime Bundle from M2 (`tools/vision/build_offline_bundle.py --source-commit <M2> --platform-variant <variant> …`). Retain its manifest: `sourceCommit` must equal M2 and it must name exactly one `mavi-vision` wheel. Verify the companion binary kit against M2's lock files.
2. **Isolate.** Disable the network adapter or apply a deny-all outbound firewall rule, and record which. Record the system proxy state: `netsh winhttp show proxy` (Windows), or the proxy environment and the pip/apt index configuration (Linux). Confirm no LAN package mirror is reachable. Run `assert_outbound_internet_unavailable` (`tools/phase1/qualify_offline_variant.py`, five targets) and retain its JSON output as `disconnected.isolation-before`.
3. **Install and activate 3.1 / Finalizing.** Perform the clean Development install. These are the shipped defaults since F4-C (`VisionFinalization:Enabled = true`, worker `completion_schema_version = 3.1`). Confirm them: no override may hold the gate off (no machine configuration file or `MAVI_MACHINE_CONFIG` setting `Enabled = false`, no `VisionFinalization__Enabled`), and `MAVI_COMPLETION_SCHEMA_VERSION` is unset or `3.1`. Retain `GET /api/vision/contract`: it must list `["2.0","3.1"]`. The run record's `activation` must be `{"visionFinalizationEnabled": true, "completionSchemaVersion": "3.1"}`.
4. **Trace connections for the whole run.** On Linux, run the platform and the worker under `strace -f -e trace=connect -o <file>`. On Windows, enable the Windows Firewall dropped-packet log. Convert the attempts to `s1-disconnected-connect-trace-v1` (`sourceCommit`, `method`, `attempts[{address, port}]`). Any non-loopback address is a finding; loopback and local sockets are expected.
5. **Operate.** Run setup verification, start the worker, process a real recorded video, observe the `finalizing` hand-off and the hosted publication, then open Track detail and the Review/Investigation Evidence Set. Retain one evidence file per outcome from this same run.
6. **Isolation after.** Rerun the probe and retain it as `disconnected.isolation-after`.
7. **Static dependency proof.** On the build host, run `git diff <previous-qualified-sha> <M2> -- config/dependencies/ src/vision/pyproject.toml 'src/platform/**/*.csproj' src/web/mavi-web/package.json src/web/mavi-web/package-lock.json`. Record every added dependency as `s1-disconnected-dependency-diff-v1` (`fromSha`, `toSha = M2`, `addedDependencies`). An empty list is expected.
8. **Runtime manifests.** Record the model pack manifest, the runtime profile, the pipeline profile and `resolved-config.json` with their SHA-256 as `s1-disconnected-runtime-manifests-v1`.

The checker binds all of it to M2 and refuses any of the following:
- a bundle from another commit;
- a run without the 3.1 activation;
- a non-loopback connect attempt;
- an added dependency;
- a manifest list without hashes;
- evidence retained outside `docs/qualification/stage2-s1/evidence/<M2-sha12>/`.

The host's storage class is measured by the harness probes. On Windows, retain `Get-PhysicalDisk | Format-List DeviceId,MediaType,BusType` and point `MAVI_QUALIFICATION_WINDOWS_DISK_EVIDENCE` and `MAVI_QUALIFICATION_WINDOWS_DISK_ID` at it and at the disk behind the evidence volume.

## Staging reclamation

The platform reclaims worker attempt staging (`{MediaStorage:RootPath}/staging/{jobId}/attempt-NNNN`) with the `vision_jobs` row as its **sole authority**. The worker's own cleanup after completion and at the next lease remains a fast path; the janitor bounds retention when the worker dies or never runs again. It never enumerates outside `staging/`, never opens the evidence root, and deletes handle-relatively without following any symbolic link, junction or reparse point (a linked job or attempt directory is refused and logged).

| Job state | Action |
|---|---|
| `Completed` / `Failed` | every canonical attempt once `CompletedAtUtc + GraceMinutes` has passed, then the empty job directory |
| `Cancelled` (nothing produces it today) | as terminal; logged once (1405) |
| `Leased` | attempts `k < AttemptCount` immediately; never the current or a later attempt |
| `Finalizing` | as `Leased`: the current attempt is the finalizer's input and survives until the job is terminal (ADR-006 §7); a later attempt is preserved and logged once (1401) |
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
