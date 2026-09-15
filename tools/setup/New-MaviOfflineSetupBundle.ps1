[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [Parameter(Mandatory = $true)]
    [string]$PostgreSqlRuntimePack,

    [Parameter(Mandatory = $true)]
    [string]$FfmpegPack,

    [Parameter(Mandatory = $true)]
    [string]$ApplicationArtifact,

    [Parameter(Mandatory = $true)]
    [string]$HostingBundle,

    [Parameter(Mandatory = $true)]
    [string]$DotNetSdkInstaller,

    [Parameter(Mandatory = $true)]
    [string]$NodeInstaller,

    [Parameter(Mandatory = $true)]
    [string]$PythonInstaller,

    [Parameter(Mandatory = $true)]
    [string]$DeveloperDependencyCache
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force

$destination = [IO.Path]::GetFullPath($Destination)
$postgreSqlRuntimePack = (Resolve-Path -LiteralPath $PostgreSqlRuntimePack).Path
$ffmpegPack = (Resolve-Path -LiteralPath $FfmpegPack).Path
$applicationArtifact = (Resolve-Path -LiteralPath $ApplicationArtifact).Path
$developerDependencyCache = (Resolve-Path -LiteralPath $DeveloperDependencyCache).Path

[void](Test-MaviManifest -Root $postgreSqlRuntimePack -ManifestPath (Join-Path $postgreSqlRuntimePack "manifest.json") -ExpectedSchemaVersion "mavi-postgresql-runtime-pack-v1")
[void](Test-MaviManifest -Root $ffmpegPack -ManifestPath (Join-Path $ffmpegPack "manifest.json") -ExpectedSchemaVersion "1.0")

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
Copy-Tree -Source $ffmpegPack -Target (Join-Path $destination "prerequisites\ffmpeg")
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
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%~dp0setup\Setup-MAVI.ps1"" -Profile Development -BundleRoot ""%~dp0""'"
if errorlevel 1 pause
endlocal
'@
[IO.File]::WriteAllText(
    (Join-Path $destination "Setup-MAVI-Development.cmd"),
    $developmentLauncher,
    [Text.Encoding]::ASCII)

$productionLauncher = @'
@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -Wait -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%~dp0setup\Setup-MAVI.ps1"" -Profile Production -BundleRoot ""%~dp0""'"
if errorlevel 1 pause
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
