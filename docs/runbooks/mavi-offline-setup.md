# MAVI Offline Setup Runbook

## Objective

The supported operator experience is deliberately minimal:

- **Development workstation:** run **Setup-MAVI-Development.cmd**, approve elevation, restart Visual Studio once, then build/run MAVI.
- **Production workstation:** run **Setup-MAVI-Production.cmd**, approve elevation, then open the URL reported by Setup.
- **PoC host (`poc-single-host`, not Production):** run **Install-MAVI-PoC.cmd** from the PoC setup bundle, then **Start-MAVI-PoC.cmd** (section "poc-single-host" below).

Operators do not manually select PostgreSQL versions/ports, edit connection strings, install pgvector, configure FFmpeg PATH, run EF migrations, create databases, or configure the IIS site.

Setup is idempotent. Rerunning the same approved bundle verifies and repairs the MAVI-owned environment instead of creating parallel instances.

## Environment ownership

MAVI owns dedicated PostgreSQL 18 instances so unrelated PostgreSQL installations do not affect it.

| Profile | PostgreSQL service | Port | Database |
| --- | --- | ---: | --- |
| Development | MAVI-Dev-PostgreSQL-18 | 55433 | mavi_dev + mavi_test |
| Production | MAVI-PostgreSQL-18 | 55432 | mavi |

Development uses the repository convention postgres/postgres inside the isolated Development instance.

Production generates strong database credentials automatically. They are never written to setup logs or command lines. Administrative and application passwords are retained only as machine-protected DPAPI material under C:\ProgramData\MAVI\setup; the application receives its connection string through the ACL-protected machine configuration file.

## Machine-owned configuration

The application artifact remains immutable.

Development configuration is written to:

~~~text
C:\ProgramData\MAVI\Development\config\appsettings.development.machine.json
~~~

Production configuration is written to:

~~~text
C:\ProgramData\MAVI\config\appsettings.machine.json
~~~

MAVI loads this file before registering infrastructure services. Environment variables are then reapplied as the final advanced-operator override. Test hosts do not load machine configuration.

Setup also provisions `TrackSearch:CursorSigningKey` in the same file: 32 random bytes, base64-encoded, generated once per installation. The API uses it to authenticate analytic search cursors (Scene Analytics Slice 4). Re-running setup keeps an existing key; deleting the member and re-running setup rotates it, which deliberately invalidates every open analytic result set and nothing else. The key is never logged, never returned by an API and never committed. A Production host with no key refuses to start.

## Canonical offline media

The normal **Production** setup bundle is deliberately smaller than the companion binary kit:

~~~text
MAVI-Offline-Setup/
  Setup-MAVI-Production.cmd
  README-FIRST.txt
  mavi-offline-bundle.json

  setup/
    Setup-MAVI.ps1
    Test-MaviEnvironment.ps1
    Test-MaviOfflineBinaryKit.ps1
    Mavi.Setup.Common.psm1
    Mavi.Setup.Windows.psm1

  config/
    mavi-setup-defaults.json
    offline-binary-catalog-v1.json

  provenance/
    binary-kit/
      mavi-offline-binary-kit.json
      offline-binary-catalog-v1.json

  application/
    <qualified MAVI publish, including tools/ffmpeg/>

  prerequisites/
    postgresql/
      pg18/
        win-x64/
          manifest.json
          LICENSE-POSTGRESQL.txt
          LICENSE-PGVECTOR.txt
          bin/
          lib/
          share/
    hosting/
      win-x64/
        dotnet-hosting.exe
~~~

`mavi-offline-bundle.json` contains SHA-256 and size for every payload file and, when the companion kit was used, records the source binary-kit/catalog hashes.

A combined Development+Production bundle can still be generated with `-IncludeDevelopmentPayload`; only then are `Setup-MAVI-Development.cmd`, the .NET SDK, Node, Python and Development dependency caches copied into the final setup media, together with the kit's Vision component store (`vision\`) when the kit has one. The preferred Development workflow is the source repository plus the separately retained binary kit.

## Preparing the release media

### 1. Stage approved FFmpeg

On a **connected Windows preparation machine**, use the pinned acquisition helper:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/Prepare-MaviFfmpegWindows.ps1
~~~

The helper reads the approved FFmpeg version, HTTPS source URL and archive SHA-256 from `config/dependencies/offline-binary-catalog-v1.json`, verifies the downloaded archive before extraction, and stages the app-local pack under `vendor/ffmpeg`.

`tools/native/stage_ffmpeg_windows.ps1` remains the lower-level staging primitive for a separately obtained approved distribution; it is not the preferred routine preparation path. Disconnected Development/Production machines never run the acquisition helper and never download FFmpeg.

### 2. Stage the isolated PostgreSQL runtime

Use a known-good PostgreSQL 18 installation on the build machine after the approved pgvector version has been installed into that PostgreSQL tree:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/native/stage_postgresql_runtime_windows.ps1 -PostgreSqlRoot "C:\Program Files\PostgreSQL\18" -PgVectorLicensePath "<PGVECTOR_LICENSE>"
~~~

The runtime pack contains the PostgreSQL bin, lib and share trees, including pgvector and the PostgreSQL contrib extension `pg_trgm` (the plate-text search index, Stage 4). Staging refuses a source tree without `pg_trgm.control` and `pg_trgm.dll`. Its manifest records every file hash plus the observed PostgreSQL, pgvector and pg_trgm (`pgTrgmVersion`) versions; packs staged before Stage 4 PR-4 already contain pg_trgm (contrib ships with every PostgreSQL 18 Windows installation) but do not record its version.

Setup creates `pg_trgm` as the administrator in each MAVI database, beside `vector`; the platform's startup check refuses to start without it, and `Test-MaviEnvironment.ps1` reports it.

This is the preferred end-user deployment path. The lower-level standalone pgvector staging/installer remains available for controlled maintenance/build-machine workflows but is not required during normal MAVI installation.

### 3. Prepare the offline Development dependency cache

On a connected preparation machine:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/Prepare-MaviDeveloperOfflineCache.ps1
~~~

This populates the canonical vendor/developer-cache/win-x64 location with NuGet, npm and Python dependencies needed by a fresh disconnected Development workstation.

Place the approved installers at the canonical names documented in vendor/installers/README.md.

### 4. Build and retain the companion offline binary kit

After the approved runtime packs, installers and Development caches are staged, create the separately retained binary kit:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/New-MaviOfflineBinaryKit.ps1 ^
  -Destination "D:\Release\MAVI-Offline-Binary-Kit" ^
  -ZipPath "D:\Release\MAVI-Offline-Binary-Kit.zip"
~~~

The generated kit contains no MAVI application build. It contains the external Windows runtime/toolchain payloads and Development caches, plus:

- `mavi-offline-binary-kit.json` — SHA-256 and size for every retained file;
- exact observed PostgreSQL, pgvector and FFmpeg versions;
- observed file/product versions for the .NET Hosting Bundle, .NET SDK and Python installer;
- exact MSI ProductVersion for Node.js;
- the repository-owned binary/version catalog; and
- SHA-256 identity for every installer and retained payload byte.

For a `poc-single-host` kit, `-VisionCudaRuntimePack <pack>[,<pack>]` adds the Windows CUDA Runtime Packs (only the component binding's `windows-x86_64-cuda` pin and its declared Development builds are accepted, each re-hashed against its manifest) under `vendor/vision/runtime/<build>`, and `-OnnxRuntimeGpuWheel <wheel>` adds the catalogue-pinned `onnxruntime-gpu` wheel under `vendor/vision/onnxruntime-gpu`; the kit manifest records them under its top-level `pocVision` (null when none were given). Both are Development grade (ADR-020) and never Production payloads.

Keep this ZIP with release/development media. Do not commit it to ordinary Git.

### 5. Publish MAVI with app-local FFmpeg

~~~powershell
dotnet publish src/platform/Mavi.Api/Mavi.Api.csproj -c Release -p:RequireMaviBundledMediaTools=true -p:MaviBuild="<BUILD_ID>" -p:MaviCommit="<EXACT_COMMIT>" -o "<PUBLISHED_ROOT>"
~~~

Create the application artifact manifest using the existing Phase-1 tool before assembling setup media.

### 6. Assemble the canonical setup bundle

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/New-MaviOfflineSetupBundle.ps1 ^
  -Destination "D:\Release\MAVI-Offline-Setup" ^
  -ApplicationArtifact "<PUBLISHED_ROOT>" ^
  -BinaryKitRoot "D:\Release\MAVI-Offline-Binary-Kit"
~~~

If `MAVI-Offline-Binary-Kit` is kept beside the repository, the builder auto-detects it and `-BinaryKitRoot` may be omitted.

The builder verifies the binary-kit manifest, copies only the required payloads into the final setup media, retains the source binary-kit/catalog hashes as provenance, verifies the PostgreSQL and application-local FFmpeg manifests, and then hashes the complete final media.


## Where the binaries live

Use a two-tier model:

1. **Ordinary Git** — source, scripts, configuration, dependency/version policies, textual documentation and deterministic small manifests.
2. **MAVI Offline Binary Kit** — external EXE/DLL/MSI/runtime payloads, PostgreSQL/pgvector, FFmpeg and generated NuGet/npm/Python caches.

Repository verification rejects third-party/generated distributable extensions such as EXE, DLL, MSI, ZIP, 7z, WHL, SO and PYD, and rejects unapproved tracked files larger than 10 MiB. This deliberately avoids having one rule for “small” third-party binaries and another for “large” ones.

The binary kit can be kept/downloaded as a separate ZIP. The final MAVI setup bundle is then assembled from the exact verified kit plus the qualified MAVI application artifact.

See `docs/architecture/offline-binary-inventory.md` and `config/dependencies/offline-binary-catalog-v1.json`.

Git LFS or an approved internal binary repository can be adopted later for central retention of the companion kit without changing target-machine Setup.

## Version record

The repository baseline is recorded in `config/dependencies/offline-binary-catalog-v1.json` and summarized in `docs/architecture/offline-binary-inventory.md`.

The catalog records policy/baseline versions; the generated binary-kit manifest records the exact retained bytes. PostgreSQL, pgvector and FFmpeg additionally carry nested manifests with observed versions. Final setup media records the source binary-kit/catalog hashes, and Phase-1 evidence binds the installed/runtime identities.

This separates **human version labels** from **cryptographic release identity**: a version string is useful, but the SHA-256 of the actual retained file is decisive.

## Adding a dependency in a future feature

Do not add a separate manual installation procedure as the default response to a new library or runtime requirement.

Follow `docs/architecture/dependency-and-offline-packaging-policy.md` and update `config/dependencies/offline-dependency-policy-v1.json` in the same feature PR. Depending on the dependency type, update the Development cache/wheelhouse, application publish, native/runtime pack, canonical offline bundle, Setup/repair, readiness verification, licence/notices and qualification evidence together.

The target experience should remain unchanged: Development is one setup launcher followed by F5; Production is one setup launcher followed by normal use.

## Development workstation

Double-click:

~~~text
Setup-MAVI-Development.cmd
~~~

Setup automatically verifies the offline media; installs the pinned .NET/Node/Python prerequisites only if they are missing; deploys the isolated MAVI PostgreSQL 18 runtime; initializes MAVI-Dev-PostgreSQL-18 on port 55433; creates mavi_dev and mavi_test; enables pgvector; creates media/evidence roots; writes machine-owned Development configuration under ProgramData; configures MAVI_TEST_DB_CONNECTION for the PC; restores the repository from the bundled offline NuGet/npm/Python caches when the source tree is attached; and reuses the same verified FFmpeg pack embedded in the application artifact.

Restart Visual Studio once after first setup so it inherits the machine-scoped Development environment. No pgAdmin configuration is required.

For a repository-based Development workstation, keep the extracted `MAVI-Offline-Binary-Kit` beside the `MAVI` repository and double-click `Setup-MAVI-Development.cmd`. The launcher auto-detects and verifies the sibling kit. Loose `vendor/...` staging is accepted only as release-preparation input to the kit builder; target Development Setup deliberately refuses it. No port, database, pgvector or FFmpeg PATH configuration is required.

### Vision components (Development)

With the repository attached, Setup also installs the Vision composition: the Windows CPU Runtime Pack and every Model Pack that role `vision` needs. What is needed is decided by the repository's component binding, `src/vision/config/components/phase1-bindings-v2.json`; nothing is chosen by directory name, order or date.

**Where Setup looks, in this order:**

1. `MAVI_VISION_BUNDLE_ROOT`, if set (process, then machine). It is used as given: a Vision component store if it contains `vision\component-inventory.json`, otherwise a Runtime Bundle root. If it does not exist, Setup fails rather than looking elsewhere.
2. The component store inside the binary kit or a combined setup bundle (`<kit>\vision\component-inventory.json`). A combined bundle's own Development launcher does not attach the repository, so rerun its Setup with `-RepositoryRoot` to install the Vision components from it.
3. A `MAVI-Vision-Runtime-Bundle` directory beside the repository, as a Runtime Bundle root.

A component store has this layout (see the component lifecycle runbook for how to build it):

~~~text
MAVI-Offline-Binary-Kit\
  vision\
    component-inventory.json
    runtime\<runtimePackId>\runtime-pack-manifest.json ...
    models\<modelPackId>\model-pack-manifest.json ...
~~~

A Runtime Bundle root holds one Runtime Pack, at `<root>\runtime-pack-manifest.json` or `<root>\windows-x86_64-cpu\runtime-pack-manifest.json` (and optionally `<root>\windows-x86_64-cuda\`). Before anything is installed, Setup verifies each Runtime Pack in it the same way it verifies a component store: every file's size and SHA-256, no undeclared files, and the pack must be the binding's for its variant. The bundle carries no Model Pack, so every bound Model Pack must already be installed, and intact: its install state must match its manifest and every artefact must re-hash. Otherwise Setup fails before installing the Runtime Pack. A directory that only has the legacy `bundle-manifest.json` is **not** an installable Runtime Pack; Setup fails and says so.

**Preflight, then install.** Before installing anything, Setup checks the complete set:

- the store passes the component-store verifier (every file's size and SHA-256, no symlinks, no undeclared files);
- the inventory's `componentBindingSha256` equals the SHA-256 of the repository binding, and it names the same binding file; otherwise `kit_binding_mismatch`;
- the bound Windows CPU Runtime Pack and every enabled Model Pack of role `vision` are in the store; otherwise `kit_incomplete:<id>`;
- nothing in the store is outside the binding; otherwise `kit_unbound_component:<id>`.

The inventory also records `applicationOverlay.revision`, the application commit the store was assembled at. Setup reports it as provenance and does not compare it with the repository: a store assembled at another commit is reused as long as the binding is the same, because the binding is the composition identity.

Only when the whole set passes does Setup install: the Runtime Pack with `Install-MaviVisionRuntime.ps1`, then each Model Pack with `Install-MaviVisionModelPack.ps1` in `modelPackId` order, then a bound Windows CUDA Runtime Pack if the source carries one. It then runs the launcher's own checks (`Start-MaviVisionWorker.ps1 -DevicePolicy cpu -VerifyOnly`). Only when that passes does Setup report `Vision composition OK READY`.

**Failures and reruns.** Each pack installs on its own, with its own staging and rollback. The set as a whole is not one transaction. If a later pack fails after an earlier one installed:

- Setup fails, names the pack that failed and lists the packs installed so far;
- the earlier packs stay installed and valid; they are not rolled back;
- the Vision composition is **not** ready, and the worker launcher refuses it too.

Fix the cause and rerun Setup. The rerun checks the whole set again, reuses the packs already installed, installs the rest and runs the readiness check. `last-setup-result.json` records the outcome under `vision` (`ready`, or `not-installed` when no source was found).

If no source is found at all, Setup completes the rest of the workstation and reports `Vision composition WARN not installed`. The UI and API work, and vision jobs stay queued until the components are installed.

This is Development CPU installation only. It does not qualify or promote a model, and it does not make CUDA required or qualified. Development Auto uses CUDA only when a bound CUDA Runtime Pack is installed and usable.

## Production deployment profiles

ADR-008 defines three Production profiles over the same application architecture:

| Profile | Physical topology | Worker runtime | Required worker environment |
|---|---|---|---|
| **P1** | Single Windows host | Windows CUDA | `MAVI_DEPLOYMENT_PROFILE=P1`, `MAVI_DEVICE_POLICY=cuda` |
| **P2** | Windows Operational/Data + separate Linux Vision host | Linux CUDA | `MAVI_DEPLOYMENT_PROFILE=P2`, `MAVI_DEVICE_POLICY=cuda` |
| **P3** | Single Windows host | Windows CPU | `MAVI_DEPLOYMENT_PROFILE=P3`, `MAVI_DEVICE_POLICY=cpu` |

Production workers **must** set `MAVI_DEPLOYMENT_PROFILE`. Production rejects `MAVI_DEVICE_POLICY=auto`. At worker startup the selected profile is loaded from the exact deployment-profile policy, the release qualification record is checked for that profile/policy/runtime variant, and the actual host OS/device is required to match the profile. Thus P2 cannot accidentally run on a Windows CUDA host and P1/P3 cannot silently use another runtime variant.

The Windows operational/data setup media remains common. The Vision Runtime Pack and worker installation are profile-specific. A profile is supported only after its exact Production qualification passes.


## Production workstation

Double-click:

~~~text
Setup-MAVI-Production.cmd
~~~

Setup automatically verifies every bundle file; installs/repairs the isolated PostgreSQL runtime; starts MAVI-PostgreSQL-18 on port 55432; generates protected database credentials; creates the mavi database and pgvector extension; creates storage roots; writes and ACL-protects machine configuration; enables required IIS features; installs the ASP.NET Core Hosting Bundle when absent; deploys the qualified application; creates the dedicated MAVI application pool/site, whose IIS request log records no query string, Referer or cookie (plate text and cursors travel in query strings; `Test-MaviEnvironment` fails if they are logged, including under server-wide central logging); starts MAVI; lets startup verify native dependencies and apply EF migrations; and validates both /api/health and the UI root.

Default URL:

~~~text
http://127.0.0.1:8080
~~~

The data root and HTTP port have defaults and normally require no operator input. They remain optional setup parameters for controlled deployments that need a different storage volume or port.

## poc-single-host (PoC installation) — not a Production profile

`poc-single-host` (ADR-020) installs the complete stack on one Windows host for the end-to-end proof of concept. **It is not a Production profile and never becomes one:** evidence class Development, not Production-qualified; the installer, the release metadata, the About page and a persistent banner say so, and the platform refuses to start if its release metadata claims otherwise. Design and spike record: `docs/superpowers/plans/2026-10-28-poc-s1-deployable-v0.md`.

### Building the PoC setup bundle (connected preparation machine)

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/New-MaviPocSetupBundle.ps1 `
  -Destination "E:\Release\MAVI-PoC-Setup" `
  -BinaryKitRoot "<MAVI-Offline-Binary-Kit>" `
  -VisionRuntimeCpuSource "<Windows CPU Runtime Pack bundle>" `
  -ModelPackSource "<built Model Pack>" `
  -PlatesCache "<cache with python-plates-pilot-wheelhouse\ and plates-pilot-payloads\>" `
  [-VisionRuntimeCudaSource "<v1 sm_75 Windows CUDA Runtime Pack>"] [-VisionRuntimeCudaSm89Source "<sm_75;sm_89 Windows CUDA Runtime Pack>"] [-SmokeClip <clip.mp4> -SmokeClipLicence "<CC0/CC-BY attribution>"]
~~~

The builder exports the exact commit first (`git archive`; uncommitted changes never ship) and reads the component binding and the binary catalogue from that export, not from the preparer's checkout; it publishes the platform from it, writes the **application overlay** (the repository subset the setup scripts and workers read, with `mavi-application-overlay.json`: revision + per-file SHA-256), copies the PostgreSQL runtime pack, FFmpeg and the Hosting Bundle from the kit, copies the Runtime and Model Packs the component binding names, including a declared Development build of a variant (ADR-014 amendment 2026-10-29), and refuses any other, copies the plates cache, and hashes every file into `mavi-poc-bundle.json`. The kit's catalogue entries for PostgreSQL, pgvector, FFmpeg and the Hosting Bundle must equal the repository's; the kit's developer caches are not shipped, so their freshness does not apply. The plates payloads may come from `plates_pilot_packs.py fetch` or, verified by SHA-256, from the Stage-4 controlled candidate store.

### Installing (target, network disconnected)

Double-click `Install-MAVI-PoC.cmd` in the bundle and approve elevation, or from an elevated prompt:

~~~powershell
Install-MAVI-PoC.cmd -InstallRoot "E:\MAVI-PoC\Program" -DataRoot "E:\MAVI-PoC\Data" [-DevicePolicy Auto|CUDA|CPU] [-PlatesDevicePolicy Auto|CPU] [-CudaRuntimePack Auto|sm75|sm75-sm89] [-AdoptCudaRuntimeRoot <installed CUDA pack>] [-PlanOnly]
~~~

| Item | Value |
| --- | --- |
| Roots | `%ProgramFiles%\MAVI\PoC` and `%ProgramData%\MAVI\PoC` by default; every PoC file is under the two roots |
| PostgreSQL | `MAVI-PoC-PostgreSQL-18`, port 55434, database `mavi_poc`, DPAPI-protected generated credentials |
| Platform | Kestrel on `http://127.0.0.1:8090` (loopback only: no IIS, no firewall rule); ASP.NET Core 10 from the kit's Hosting Bundle when absent |
| Vision | CPU Runtime Pack always; a CUDA Runtime Pack when `nvidia-smi` reports a compute capability a build contract targets and the bundle carries that build: the v1 `sm_75` pack on 7.5, the PoC `sm_75;sm_89` pack (S1b, build contract v2, `built-hashed-locked`) on 8.9; `-CudaRuntimePack` names a build, which must target the GPU (or `-AdoptCudaRuntimeRoot` names an installed one, which must pass the launcher's integrity preflight); every bound Model Pack. The `sm_75;sm_89` pack is the binding's Development build `sm75-sm89`: the launcher and resolver accept it in Development only, on compute capability 7.5 or 8.9 (`docs/runbooks/poc-windows-cuda-sm89-variant.md`) |
| Plates | **Bound** (PoC S3, plan D4): PD5 (PP-OCRv5 mobile det, Apache-2.0) + OC1-S (fast-plate-ocr cct-s-v2, MIT) on the `plates-onnx-v1` runtime, through `src/vision/config/components/development-plates-onnx-pilot-v1.json`; CPU only (see "Plates role" below) |
| Machine environment | none written; the launchers are given every root explicitly |

Steps, all offline and idempotent (a rerun verifies and repairs): verify the bundle → PostgreSQL + pgvector + pg_trgm → ASP.NET Core 10 runtime → platform and overlay → Vision Runtime Pack(s) → Model Packs → plates runtime and Model Packs → machine configuration (`<DataRoot>\config\appsettings.poc.machine.json`, including the `Plates` section that binds the role) → release metadata (`<DataRoot>\release\mavi-release-metadata.json`, each plate Model Pack with the licence read from its own LICENSE) → launcher readiness check with the chosen device policy, which writes the device record (`<DataRoot>\run\device-resolution.json`) → plates readiness check (the worker composes the release and loads both Model Packs without leasing; its record is `<DataRoot>\run\plates-device-resolution.json`) → start, migrate, seed the demo cameras (`config/poc/demo-cameras-v1.json`: the twelve S2 demo-corpus cameras `POC-S2-01`…`POC-S2-12`, a byte-identical copy of `tools/poc/demo-corpus/demo-cameras-v1.json`; names and time zones only, no scene) → stop. `-PlanOnly` prints the plan and changes nothing; explicit `-DevicePolicy CUDA` without an installable CUDA pack fails closed, in plan-only too. Result: `<DataRoot>\setup\last-install-result.json`; log: `<DataRoot>\logs\install-*.log`.

### Protections and known limits

- The release metadata directory is writable only by administrators; the device record lives under `run\`, where the operator's unelevated start rewrites it, and `Stop-MAVI-PoC.cmd` removes it with the worker, so the disclosure never shows a device for a worker that is not running.
- The bundle's platform is built with `MaviDeploymentProfile=poc-single-host`: removing or emptying `Deployment:Profile` does not remove the disclosure, and a contradicting profile stops the platform at start-up.
- The machine configuration (which holds the PoC database credentials) is readable by every signed-in user, as on a Development workstation, because the operator starts MAVI unelevated. Production keeps its administrator/application-pool-only ACL.
- The bundle carries the Microsoft-signed Visual C++ 2015-2022 x64 redistributable (`prerequisites\vcredist\win-x64\vc_redist.x64.exe`, 14.x, at least 14.44; the builder takes `-VcRedistInstaller` or the kit's `vendor\installers\win-x64\vc_redist.x64.exe`). The installer installs it when the registered x64 runtime is absent or older, before any Vision Runtime Pack, and after each Runtime Pack is installed (or adopted) imports `torch` and an `mmcv` native op in it.
- A rerun stops a running PoC instance before replacing its files. The installer's own start (migrations, camera seed) is always stopped again: the operator runs MAVI unelevated.
- `-AdoptCudaRuntimeRoot` on a GPU the `sm_75` pack does not serve (for example an RTX 4090) is refused; S1b provides that variant.
- Start-up writes process records with image name and start time under `run\`; Start and Stop act only on a record whose process has the image Start launched for it (`Mavi.Api`, `powershell`) and the recorded start time, ignore a stale record (after a reboot), and keep a record whose process cannot be inspected from an unelevated session (stop it from an elevated prompt). Start clears the previous device record, waits for the worker to stay up after its launch checks, and on failure stops only what it started. `run\` is operator-writable, so the device record shown on the About page is as trustworthy as the host's local users; the release metadata is administrator-owned and administrator-writable only. Before creating anything, the installer replaces the install and data roots' owner and access list (Administrators-owned, inheritance removed: SYSTEM and Administrators full control, signed-in users read and execute), refuses a root, or a directory it secures, that is or sits under a junction, and only then grants the operator-writable directories. **Threat model:** this reduces, but does not remove, what a hostile local user can do to the elevated installer (an operator-writable directory can be turned into a mount point in place, and an ancestor such as `%ProgramData%\MAVI` created beforehand by a user stays theirs). **Owner decision S1-T1 (2026-10-28):** `poc-single-host` is installed only on dedicated demonstration machines operated by trusted local users; the residual risk above is accepted for the Development PoC only and does not extend to Production, shared multi-user hosts or untrusted local users.

### Running and the smoke test

In the install root: `Start-MAVI-PoC.cmd` (PostgreSQL service, platform, Vision worker through `Start-MaviVisionWorker.ps1` from the overlay; opens the UI), `Stop-MAVI-PoC.cmd`, and

~~~text
Test-MAVI-PoC.cmd -ClipPath "<small .mp4>" [-EvidenceDirectory <dir>]
~~~

The smoke test checks health and the disclosure, imports the clip to `POC-S2-01` (`-CameraCode` picks another seeded camera) (a re-import reuses the existing video), waits for processing, requires `GET /api/tracks?videoAssetId=…` to return Tracks and reads the first Track's detail back. It exits 0 only when every step passed and always retains `smoke-result.json` and a transcript.

### Plates role (PoC S3)

- **Binding.** The machine configuration sets `Plates:Enabled=true` and points `Plates:ComponentBindingPath` / `Plates:PipelineProfilePath` at the overlay's PD5 + OC1-S release. The profile is Development-only; a platform **built** for `poc-single-host` (the bundle's `MaviDeploymentProfile`; a `Deployment:Profile` setting alone does not count) accepts it, and only this release (analysis identity `c86c930b…`, never the fixture); every other non-Development host refuses it (`plate_development_definition_forbidden`). `Start-MAVI-PoC.cmd` starts the plates worker (`Start-MaviPlatesPilotWorker.ps1`, worker `poc-plates-01`) after the Vision worker and `Stop-MAVI-PoC.cmd` stops it first.
- **Device.** The role resolves its own device. `plates-onnx-v1` is a CPU-only runtime (graph `onnxruntime-cpu-v1`; the adapters use the CPU execution provider), so `Auto` resolves CPU with reason `plates_runtime_cpu_only`, `CPU` gives `explicit_cpu`, and `CUDA` fails closed (installer, plan-only and launcher). GPU plates need a CUDA variant of the runtime family (S1b's `onnxruntime-gpu`) and adapter support; until then the About page says CPU and why. `Start-MAVI-PoC.cmd -PlatesDevicePolicy Auto|CPU` overrides the installed choice for one start.
- **Re-analysis.** `POST /api/plates/reanalysis` is refused (403 `plate_reanalysis_authorisation_not_configured`) until an owner configures an operator key; it then requires that key in the `X-Mavi-Operator-Key` header (401 `plate_reanalysis_unauthorised` otherwise). The platform stores only the key's SHA-256. To enable it, generate a random key (at least 32 random bytes; a short or memorable key can be recovered from its digest, which every signed-in user can read in the machine configuration), for example `$k = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))`, record it for the operator, and in an elevated prompt add `"ReanalysisOperatorKeySha256": "<lowercase SHA-256 of the key's UTF-8 bytes>"` to the `Plates` section of the machine configuration, then restart. Never put the key itself in the machine configuration. This is an interim gate; S11-min replaces it with ADR-010 operator identity.
- **Disabling plates.** `Plates:Enabled=false` stops new activation and queueing, including explicit re-analysis (409 `plate_analysis_disabled`); the authority loop keeps failing overdue or exhausted units and reclaiming plate staging. This holds on every host: a platform with plates disabled or not configured still runs the (cheap) sweep and staging janitor on its reconcile interval.
- **Known limits.** The About page carries the plate known limits (H3 proxy measurement 52/110 and 45/79; no Indian plates; candidate readings). See `docs/qualification/poc/known-limits.md`.

### Device policy (ADR-008, unchanged)

`Auto` resolves CUDA only when the CUDA Runtime Pack is installed, intact, bound and its GPU index answers; otherwise CPU with a reason code from the closed vocabulary (for example `cuda_pack_absent`). Explicit `CUDA` never falls back: with no CUDA pack the launcher refuses with `launch_runtime_pack_not_installed`. `Start-MAVI-PoC.cmd -DevicePolicy CPU|CUDA|Auto` overrides the installed policy for one start. The resolved device and reason appear on the About page and in the banner.

## Verification and repair

Verification only:

~~~powershell
powershell -ExecutionPolicy Bypass -File setup/Test-MaviEnvironment.ps1 -Profile Development
~~~

or:

~~~powershell
powershell -ExecutionPolicy Bypass -File setup/Test-MaviEnvironment.ps1 -Profile Production
~~~

A normal rerun of Setup is the supported repair action. Setup refuses to reuse an unknown process on the reserved PostgreSQL port and refuses to repoint an existing IIS site named MAVI if that site is bound to another physical path.

## Plan-only mode

To inspect the resolved installation plan without changing the machine:

~~~powershell
powershell -ExecutionPolicy Bypass -File setup/Setup-MAVI.ps1 -Profile Production -BundleRoot "<BUNDLE_ROOT>" -PlanOnly
~~~

Plan-only does not generate credentials, create folders, register services, or install software.

## Qualification boundary

Setup prepares the target. It does **not** declare a release qualified.

After setup, profile-specific disconnected lifecycle, production prerequisite, device/runtime, quality/performance, backup/restore and final production acceptance evidence must still be executed against the exact frozen release as defined in `docs/runbooks/phase1-acceptance.md`. Current acceptance tooling still contains legacy four-variant/Linux-CUDA assumptions and must be reconciled with ADR-008 before authoritative Task-18 qualification.
