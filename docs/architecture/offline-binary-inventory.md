# Offline Binary and Runtime Inventory

This is the human-readable companion to `config/dependencies/offline-binary-catalog-v1.json`.

The JSON catalog is authoritative for automation. The generated `mavi-offline-binary-kit.json` is authoritative for the **exact bytes** retained for a particular kit.

## Windows application and Development baseline

| Component | Repository baseline | Exact release identity |
| --- | --- | --- |
| PostgreSQL | 18.x | exact patch + every file SHA-256 recorded by the staged PostgreSQL runtime-pack manifest |
| pgvector | PostgreSQL-18-compatible approved build | exact version + every file SHA-256 recorded inside the PostgreSQL runtime-pack manifest |
| FFmpeg / ffprobe | 9.0.1 Windows x64 essentials build | pinned source archive SHA-256 + exact FFmpeg version + executable SHA-256 recorded by the staged FFmpeg pack manifest |
| ASP.NET Core Hosting Bundle | 10.0.11 baseline; compatible 10.0 servicing line | observed installer file/product version + installer SHA-256 in the binary-kit manifest; installed ASP.NET Core 10/ANCM rechecked by Setup |
| .NET SDK | 10.0.100 repository baseline | `global.json` baseline + observed installer file/product version + installer SHA-256 + post-install `dotnet --list-sdks` check |
| Node.js | 22.13.0 minimum on major 22 | exact MSI ProductVersion + MSI SHA-256 + post-install `node --version` check |
| Python Development | 3.13.x | observed installer file/product version + installer SHA-256 + post-install `python --version` check |
| NuGet cache | current solution dependency closure | every retained cache file SHA-256 in binary-kit manifest + offline restore/build |
| npm cache | `package-lock.json` v3 closure | every retained cache file SHA-256 in binary-kit manifest + `npm ci --offline` |
| Python Development wheelhouse | current `pyproject.toml` Development closure | every retained wheel SHA-256 in binary-kit manifest + `pip --no-index` install/tests |

A friendly version label is useful for humans, but **the SHA-256 identity of the retained bytes is the decisive release identity**.


### Connected FFmpeg preparation

On a connected Windows preparation/development PC, MAVI can stage the approved FFmpeg pack reproducibly with:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/Prepare-MaviFfmpegWindows.ps1
~~~

The helper reads the pinned version, HTTPS source URL and archive SHA-256 from `config/dependencies/offline-binary-catalog-v1.json`, downloads only on the connected preparation machine, verifies the archive **before extraction**, stages only `ffmpeg.exe`, `ffprobe.exe` and the licence into `vendor/ffmpeg`, and verifies the resulting manifest. It is not invoked on disconnected target machines.

## Vision runtime baseline

Current Phase-1 runtime profile: `mmdetection-phase1-v1`.

| Item | Version/status |
| --- | --- |
| Windows CPU CPython | 3.12.10 |
| Linux CPU CPython | 3.12.14 |
| Windows CUDA CPython | pending hardware qualification |
| Linux CUDA CPython | pending hardware qualification |
| torch | 2.6.0 |
| torchvision | 0.21.0 |
| mmcv | 2.1.0 |
| mmengine | 0.10.7 |
| mmdet | 3.3.0 |
| trackers | 2.6.0 |
| supervision | 0.30.2 |
| scipy | 1.18.1 |
| numpy | 2.5.3 |
| OpenCV semantic version | 5.0.0 |
| opencv-python | 5.0.0.93 |
| av | 16.1.0 |
| Pillow | 11.3.0 |

The runtime profile and platform locks remain authoritative for vision qualification. CUDA versions must not be invented before the corresponding hardware qualification freezes them.

## Storage split

### Ordinary Git

Keep source code, scripts, policies, JSON/configuration, test fixtures, textual licence material and small deterministic manifests.

Repository verification rejects third-party/generated distributable extensions such as EXE, DLL, MSI, ZIP, 7z, WHL, SO and PYD and also rejects unapproved tracked files larger than 10 MiB.

### MAVI Offline Binary Kit

Keep the external Windows runtime/installers and generated Development dependency caches here. It is created by:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/New-MaviOfflineBinaryKit.ps1 ^
  -Destination "D:\MAVI-Offline-Binary-Kit" ^
  -ZipPath "D:\MAVI-Offline-Binary-Kit.zip"
~~~

The resulting folder/ZIP can be archived independently of the source repository and reused to prepare disconnected Development PCs or to assemble a final MAVI setup bundle.

### Final MAVI setup bundle

The setup bundle contains the qualified MAVI application plus only the prerequisites needed by the supported Setup workflow. Its manifest records the source binary-kit/catalog hashes when a companion kit was used.

### Vision bundles

Platform/device-qualified vision bundles and model weights remain separately retained because CPU/CUDA validity is hardware/runtime-specific. They are bound into Phase-1 acceptance through their own immutable manifests and qualification evidence.
