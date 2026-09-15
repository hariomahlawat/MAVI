# Vendored FFmpeg dependency pack

This directory is populated by the release/deployment preparation workflow and is intentionally not populated with ad-hoc binaries in source control.

For a Windows x64 application artifact, the staged layout is:

```text
vendor/ffmpeg/
  manifest.json
  win-x64/
    ffmpeg.exe
    ffprobe.exe
    LICENSE.txt
```

Use `tools/native/stage_ffmpeg_windows.ps1` to create the pack from an approved, vetted FFmpeg distribution. The script records SHA-256 hashes in `manifest.json`.

Production publish must pass `-p:RequireMaviBundledMediaTools=true`. The publish target copies this pack into `tools/ffmpeg/` beside the application. MAVI verifies the manifest, SHA-256 values and executable viability before serving requests.

The dependency pack used for a qualified release must be retained with its source, version, licence/notices and hashes in the release evidence.

Any replacement or additional native media tool must follow `docs/architecture/dependency-and-offline-packaging-policy.md`; do not add an undeclared PATH dependency or unverified binary.
