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
%LOCALAPPDATA%\MAVI\config\appsettings.development.machine.json
~~~

Production configuration is written to:

~~~text
C:\ProgramData\MAVI\config\appsettings.machine.json
~~~

MAVI loads this file before registering infrastructure services. Environment variables are then reapplied as the final advanced-operator override. Test hosts do not load machine configuration.

## Canonical offline media

The canonical bundle has this shape:

~~~text
MAVI-Offline-Setup/
  Setup-MAVI-Development.cmd
  Setup-MAVI-Production.cmd
  README-FIRST.txt
  mavi-offline-bundle.json

  setup/
    Setup-MAVI.ps1
    Test-MaviEnvironment.ps1
    Mavi.Setup.Common.psm1
    Mavi.Setup.Windows.psm1

  config/
    mavi-setup-defaults.json

  application/
    <qualified MAVI publish, including tools/ffmpeg/>

  prerequisites/
    postgresql/
      pg18/
        win-x64/
          manifest.json
          bin/
          lib/
          share/
    ffmpeg/
      manifest.json
      win-x64/
        ffmpeg.exe
        ffprobe.exe
        LICENSE.txt
    hosting/
      win-x64/
        dotnet-hosting.exe
    developer/
      win-x64/
        dotnet-sdk.exe
        node.msi
        python.exe
~~~

mavi-offline-bundle.json contains SHA-256 and size for every payload file. Setup verifies the complete bundle before changing the target machine.

## Preparing the release media

### 1. Stage approved FFmpeg

From the approved FFmpeg Windows x64 distribution:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/native/stage_ffmpeg_windows.ps1 ^
  -SourceDirectory "C:\Approved\ffmpeg\bin" ^
  -Version "<APPROVED_VERSION>"
~~~

### 2. Stage the isolated PostgreSQL runtime

Use a known-good PostgreSQL 18 installation on the build machine after the approved pgvector version has been installed into that PostgreSQL tree:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/native/stage_postgresql_runtime_windows.ps1 ^
  -PostgreSqlRoot "C:\Program Files\PostgreSQL\18"
~~~

The runtime pack contains the PostgreSQL bin, lib and share trees, including pgvector. Its manifest records every file hash plus the observed PostgreSQL and pgvector versions.

This is the preferred end-user deployment path. The lower-level standalone pgvector staging/installer remains available for controlled maintenance/build-machine workflows but is not required during normal MAVI installation.

### 3. Publish MAVI with app-local FFmpeg

~~~powershell
dotnet publish src/platform/Mavi.Api/Mavi.Api.csproj -c Release -p:RequireMaviBundledMediaTools=true -p:MaviBuild="<BUILD_ID>" -p:MaviCommit="<EXACT_COMMIT>" -o "<PUBLISHED_ROOT>"
~~~

Create the application artifact manifest using the existing Phase-1 tool before assembling setup media.

### 4. Assemble the canonical bundle

Provide approved offline installers for the .NET Hosting Bundle, .NET 10 SDK, Node.js 22 and Python 3.13+:

~~~powershell
powershell -ExecutionPolicy Bypass -File tools/setup/New-MaviOfflineSetupBundle.ps1 -Destination "D:\Release\MAVI-Offline-Setup" -PostgreSqlRuntimePack "vendor\postgresql\pg18\win-x64" -FfmpegPack "vendor\ffmpeg" -ApplicationArtifact "<PUBLISHED_ROOT>" -HostingBundle "<DOTNET_HOSTING_BUNDLE_EXE>" -DotNetSdkInstaller "<DOTNET_10_SDK_EXE>" -NodeInstaller "<NODE_22_MSI>" -PythonInstaller "<PYTHON_313_EXE>"
~~~

The builder verifies the nested PostgreSQL and FFmpeg manifests and then hashes the complete final media.

## Development workstation

Double-click:

~~~text
Setup-MAVI-Development.cmd
~~~

Setup automatically verifies the offline media; installs the pinned .NET/Node/Python prerequisites only if they are missing; deploys the isolated MAVI PostgreSQL 18 runtime; initializes MAVI-Dev-PostgreSQL-18 on port 55433; creates mavi_dev and mavi_test; enables pgvector; creates media/evidence roots; writes Development machine configuration; configures MAVI_TEST_DB_CONNECTION for the current user; and stages the approved FFmpeg pack into vendor/ffmpeg when the repository path is available.

Restart Visual Studio once after first setup so it inherits the new user environment variable. No pgAdmin configuration is required.

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

After setup, the existing Task-17/Phase-1 disconnected lifecycle, production prerequisite, CPU/CUDA, quality/performance, backup/restore and final production acceptance evidence must still be executed against the exact frozen release as defined in docs/runbooks/phase1-acceptance.md.
