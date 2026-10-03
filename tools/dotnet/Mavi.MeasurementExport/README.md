# Mavi.MeasurementExport

Read-only vehicle subclass measurement export (Stage 3, S3.2 plan T1,
`docs/superpowers/plans/2026-10-03-stage3-s3-2-vehicle-subclass-measurement.md`).
Development tooling for measurement only: it adds no API, search or UI surface and
writes nothing to the database.

```
Mavi.MeasurementExport --run <processing-run-guid> --pipeline-profile <file> --out <new-dir>
```

- **Configuration:** the web host's own machine configuration file
  (`MAVI_MACHINE_CONFIG`, or the environment's default path), then environment
  variables. It needs `ConnectionStrings:Mavi`, `MediaStorage:RootPath` and
  `MediaStorage:EvidenceRootPath`; there is no separate configuration path.
  The environment is resolved exactly as the web host's `WebApplication.CreateBuilder`
  resolves it: `DOTNET_ENVIRONMENT`, then `ASPNETCORE_ENVIRONMENT`, defaulting to
  **Production**. On the Development host set `DOTNET_ENVIRONMENT=Development` (or point
  `MAVI_MACHINE_CONFIG` at the file). A file named by `MAVI_MACHINE_CONFIG` must exist; a
  missing default file is skipped, as the host skips it. An unloadable machine file
  (missing explicit file, unreadable, malformed JSON) is refused as
  `export_configuration_invalid`. The tool prints which configuration it read before
  anything else.
- **Pipeline profile:** always given explicitly. Its SHA-256 must equal the run's
  attested `pipelineProfileSha256`.
- **Output:** a new directory holding `subclass-measurement-export.json`
  (`contracts/schemas/vehicle-subclass-measurement-export-v1.schema.json`) and
  `evidence/<sha256>.jpg`. Data stays outside Git (`E:\MAVI-Controlled\…\S3\`).
- **Snapshot and checks:** one read-only `REPEATABLE READ` transaction. Two of the
  linkage checks are narrower than their names suggest, because of the data model:
  observations carry no run or video of their own, so `export_observation_orphan`
  checks that each Track's Representative pointer names one of its own observations;
  and a run names exactly one video, so `export_video_mismatch` is a defensive check
  (a Track on another video is `export_track_run_mismatch`, which also compares the
  Track count with the run's recorded `TracksCreated`).
- **Exit codes:** 0 with `exportSha256 <hex>` on standard output; 2 with
  `refused <code>: <reason>` on standard error for any refusal or failure, and no
  output directory. The export is assembled in a hidden sibling
  (`.<name>.partial-<guid>`) and moved into place last; that sibling is removed on
  failure, but a hard kill or a locked file can leave it behind. It is never the
  output, and can be deleted.

Offline: it runs on the Windows Development host with the .NET SDK/runtime the
platform already requires and no network access.
