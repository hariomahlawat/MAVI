[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [string]$PostgreSqlRuntimePack = (Join-Path $PSScriptRoot "..\..\vendor\postgresql\pg18\win-x64"),

    [Parameter(Mandatory = $true)]
    [string]$ApplicationArtifact,

    [string]$HostingBundle = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\dotnet-hosting.exe"),

    [string]$DotNetSdkInstaller = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\dotnet-sdk.exe"),

    [string]$NodeInstaller = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\node.msi"),

    [string]$PythonInstaller = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\python.exe"),

    [string]$DeveloperDependencyCache = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force

$destination = [IO.Path]::GetFullPath($Destination)
$postgreSqlRuntimePack = (Resolve-Path -LiteralPath $PostgreSqlRuntimePack).Path
$applicationArtifact = (Resolve-Path -LiteralPath $ApplicationArtifact).Path
$developerDependencyCache = (Resolve-Path -LiteralPath $DeveloperDependencyCache).Path

[void](Test-MaviManifest -Root $postgreSqlRuntimePack -ManifestPath (Join-Path $postgreSqlRuntimePack "manifest.json") -ExpectedSchemaVersion "mavi-postgresql-runtime-pack-v1")

foreach ($requiredFile in @($HostingBundle, $DotNetSdkInstaller, $NodeInstaller, $PythonInstaller)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required offline installer was not found: $requiredFile"
    }
}

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Target
    )
    $resolved = (Resolve-Path -LiteralPath $Source).Path
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    & robocopy.exe $resolved $Target /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed while copying $Source to $Target with exit code $LASTEXITCODE."
    }
}

Copy-Tree -Source (Join-Path $repoRoot "tools\setup") -Target (Join-Path $destination "setup")

$configDestination = Join-Path $destination "config"
New-Item -ItemType Directory -Path $configDestination -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot "config\setup\mavi-setup-defaults.json") -Destination (Join-Path $configDestination "mavi-setup-defaults.json")

Copy-Tree -Source $postgreSqlRuntimePack -Target (Join-Path $destination "prerequisites\postgresql\pg18\win-x64")
Copy-Tree -Source $applicationArtifact -Target (Join-Path $destination "application")

$applicationDestination = Join-Path $destination "application"
foreach ($required in @(
    "Mavi.Api.dll",
    "web.config",
    "mavi-application-manifest.json",
    "tools\ffmpeg\manifest.json",
    "tools\ffmpeg\win-x64\ffmpeg.exe",
    "tools\ffmpeg\win-x64\ffprobe.exe",
    "tools\ffmpeg\win-x64\LICENSE.txt"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $applicationDestination $required) -PathType Leaf)) {
        throw "Production application artifact is incomplete: $required"
    }
}

$applicationFfmpegRoot = Join-Path $applicationDestination "tools\ffmpeg"
[void](Test-MaviManifest -Root $applicationFfmpegRoot -ManifestPath (Join-Path $applicationFfmpegRoot "manifest.json") -ExpectedSchemaVersion "1.0")

$hostingDestination = Join-Path $destination "prerequisites\hosting\win-x64"
New-Item -ItemType Directory -Path $hostingDestination -Force | Out-Null
Copy-Item -LiteralPath $HostingBundle -Destination (Join-Path $hostingDestination "dotnet-hosting.exe")

$developerDestination = Join-Path $destination "prerequisites\developer\win-x64"
New-Item -ItemType Directory -Path $developerDestination -Force | Out-Null
Copy-Item -LiteralPath $DotNetSdkInstaller -Destination (Join-Path $developerDestination "dotnet-sdk.exe")
Copy-Item -LiteralPath $NodeInstaller -Destination (Join-Path $developerDestination "node.msi")
Copy-Item -LiteralPath $PythonInstaller -Destination (Join-Path $developerDestination "python.exe")

foreach ($cacheDirectory in @("nuget-packages", "npm-cache", "python-wheelhouse")) {
    $source = Join-Path $developerDependencyCache $cacheDirectory
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Developer dependency cache is incomplete: $cacheDirectory"
    }
    Copy-Tree -Source $source -Target (Join-Path $developerDestination $cacheDirectory)
}

$readme = @"
MAVI OFFLINE SETUP

Production:
  Double-click Setup-MAVI-Production.cmd and approve the Administrator prompt.

Development:
  Double-click Setup-MAVI-Development.cmd and approve the Administrator prompt.

The installer verifies every file in this bundle before changing the machine.
MAVI owns its PostgreSQL 18 service, pgvector, database configuration and native
media dependencies so the operator does not need to configure ports, PATH,
connection strings, extensions or migrations manually.
"@
[IO.File]::WriteAllText(
    (Join-Path $destination "README-FIRST.txt"),
    $readme,
    [Text.UTF8Encoding]::new($false))

$developmentLauncher = @'
@echo off
setlocal
echo MAVI Development Setup
echo ======================

net session >nul 2>&1
if not %errorlevel%==0 (
  echo Requesting Administrator permission...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\Setup-MAVI.ps1" -Profile Development -BundleRoot "%~dp0"
set "MAVI_SETUP_EXIT=%errorlevel%"
if not "%MAVI_SETUP_EXIT%"=="0" (
  echo.
  echo MAVI Development Setup FAILED. Review C:\ProgramData\MAVI\Development\setup\logs.
  pause
  exit /b %MAVI_SETUP_EXIT%
)
echo.
echo MAVI Development Setup completed successfully.
pause
endlocal
'@
[IO.File]::WriteAllText(
    (Join-Path $destination "Setup-MAVI-Development.cmd"),
    $developmentLauncher,
    [Text.Encoding]::ASCII)

$productionLauncher = @'
@echo off
setlocal
echo MAVI Production Setup
echo =====================

net session >nul 2>&1
if not %errorlevel%==0 (
  echo Requesting Administrator permission...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\Setup-MAVI.ps1" -Profile Production -BundleRoot "%~dp0"
set "MAVI_SETUP_EXIT=%errorlevel%"
if not "%MAVI_SETUP_EXIT%"=="0" (
  echo.
  echo MAVI Production Setup FAILED. Review C:\ProgramData\MAVI\setup\logs.
  pause
  exit /b %MAVI_SETUP_EXIT%
)
echo.
echo MAVI Production Setup completed successfully.
pause
endlocal
'@
[IO.File]::WriteAllText(
    (Join-Path $destination "Setup-MAVI-Production.cmd"),
    $productionLauncher,
    [Text.Encoding]::ASCII)

$artifactFiles = @(
    Get-ChildItem -LiteralPath $destination -File -Recurse |
        Where-Object { $_.Name -ne "mavi-offline-bundle.json" } |
        Sort-Object FullName
)
$prefix = $destination.TrimEnd("\") + "\"
$artifacts = foreach ($file in $artifactFiles) {
    if (-not $file.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Bundle artifact escaped destination root: $($file.FullName)"
    }
    $relative = $file.FullName.Substring($prefix.Length).Replace("\", "/")
    [ordered]@{
        relativePath = $relative
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        sizeBytes = [long]$file.Length
    }
}

$manifest = [ordered]@{
    schemaVersion = "mavi-offline-setup-bundle-v1"
    createdAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
    profiles = @("Development", "Production")
    containsProductionApplication = $true
    containsHostingBundle = $true
    containsDeveloperToolchain = [ordered]@{
        dotnetSdk = $true
        node = $true
        python = $true
        nugetCache = $true
        npmCache = $true
        pythonWheelhouse = $true
    }
    artifacts = @($artifacts)
}

$manifestPath = Join-Path $destination "mavi-offline-bundle.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "MAVI offline setup bundle created."
Write-Host "  Destination : $destination"
Write-Host "  Files       : $($artifactFiles.Count)"
Write-Host "  Manifest SHA-256: $manifestHash"
