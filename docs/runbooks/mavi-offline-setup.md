# MAVI Offline Setup Runbook

## Objective

The supported operator experience is deliberately minimal:

- **Development workstation:** run **Setup-MAVI-Development.cmd**, approve elevation, restart Visual Studio once, then build/run MAVI.
- **Production workstation:** run **Setup-MAVI-Production.cmd**, approve elevation, then open the URL reported by Setup.

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

A combined Development+Production bundle can still be generated with `-IncludeDevelopmentPayload`; only then are `Setup-MAVI-Development.cmd`, the .NET SDK, Node, Python and Development dependency caches copied into the final setup media. The preferred Development workflow is the source repository plus the separately retained binary kit.

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

The runtime pack contains the PostgreSQL bin, lib and share trees, including pgvector. Its manifest records every file hash plus the observed PostgreSQL and pgvector versions.

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
2. The component store inside the Setup bundle or binary kit (`<kit>\vision\component-inventory.json`).
3. A `MAVI-Vision-Runtime-Bundle` directory beside the repository, as a Runtime Bundle root.

A component store has this layout (see the component lifecycle runbook for how to build it):

~~~text
MAVI-Offline-Binary-Kit\
  vision\
    component-inventory.json
    runtime\<runtimePackId>\runtime-pack-manifest.json ...
    models\<modelPackId>\model-pack-manifest.json ...
~~~

A Runtime Bundle root holds one Runtime Pack, at `<root>\runtime-pack-manifest.json` or `<root>\windows-x86_64-cpu\runtime-pack-manifest.json` (and optionally `<root>\windows-x86_64-cuda\`). It carries no Model Pack, so every bound Model Pack must already be installed. A directory that only has the legacy `bundle-manifest.json` is **not** an installable Runtime Pack; Setup fails and says so.

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

Setup automatically verifies every bundle file; installs/repairs the isolated PostgreSQL runtime; starts MAVI-PostgreSQL-18 on port 55432; generates protected database credentials; creates the mavi database and pgvector extension; creates storage roots; writes and ACL-protects machine configuration; enables required IIS features; installs the ASP.NET Core Hosting Bundle when absent; deploys the qualified application; creates the dedicated MAVI application pool/site; starts MAVI; lets startup verify native dependencies and apply EF migrations; and validates both /api/health and the UI root.

Default URL:

~~~text
http://127.0.0.1:8080
~~~

The data root and HTTP port have defaults and normally require no operator input. They remain optional setup parameters for controlled deployments that need a different storage volume or port.

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
