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

On a connected Windows preparation machine, use `tools/setup/Prepare-MaviFfmpegWindows.ps1`. It reads the pinned version/source/archive SHA-256 from `config/dependencies/offline-binary-catalog-v1.json`, verifies the archive before extraction, and then uses `tools/native/stage_ffmpeg_windows.ps1` to create this pack. The staged manifest records SHA-256 identities for the retained runtime files.

The lower-level staging script remains available for a separately obtained approved distribution, but target Development/Production machines must consume the verified offline binary kit rather than downloading or relying on PATH.

Production publish must pass `-p:RequireMaviBundledMediaTools=true`. The publish target copies this pack into `tools/ffmpeg/` beside the application. MAVI verifies the manifest, SHA-256 values and executable viability before serving requests.

The dependency pack used for a qualified release must be retained with its source, version, licence/notices and hashes in the release evidence.

Any replacement or additional native media tool must follow `docs/architecture/dependency-and-offline-packaging-policy.md`; do not add an undeclared PATH dependency or unverified binary.
