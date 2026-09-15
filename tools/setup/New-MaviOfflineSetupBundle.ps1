[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [Parameter(Mandatory = $true)]
    [string]$PostgreSqlRuntimePack,

    [Parameter(Mandatory = $true)]
    [string]$FfmpegPack,

    [string]$ApplicationArtifact,
    [string]$HostingBundle,
    [string]$DotNetSdkInstaller,
    [string]$NodeInstaller,
    [string]$PythonInstaller
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$destination = [IO.Path]::GetFullPath($Destination)

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null

function Copy-Tree([string]$Source, [string]$Target) {
    $resolved = (Resolve-Path -LiteralPath $Source).Path
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    & robocopy.exe $resolved $Target /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed while copying $Source to $Target with exit code $LASTEXITCODE."
    }
}

$setupSource = Join-Path $repoRoot "tools\setup"
$setupDestination = Join-Path $destination "setup"
Copy-Tree $setupSource $setupDestination

$configSource = Join-Path $repoRoot "config\setup\mavi-setup-defaults.json"
$configDestination = Join-Path $destination "config"
New-Item -ItemType Directory -Path $configDestination -Force | Out-Null
Copy-Item -LiteralPath $configSource -Destination (Join-Path $configDestination "mavi-setup-defaults.json")

$postgresDestination = Join-Path $destination "prerequisites\postgresql\pg18\win-x64"
Copy-Tree $PostgreSqlRuntimePack $postgresDestination
if (-not (Test-Path -LiteralPath (Join-Path $postgresDestination "manifest.json") -PathType Leaf)) {
    throw "PostgreSQL runtime pack has no manifest.json."
}

$ffmpegDestination = Join-Path $destination "prerequisites\ffmpeg"
Copy-Tree $FfmpegPack $ffmpegDestination
if (-not (Test-Path -LiteralPath (Join-Path $ffmpegDestination "manifest.json") -PathType Leaf)) {
    throw "FFmpeg pack has no manifest.json."
}

if ($ApplicationArtifact) {
    $applicationDestination = Join-Path $destination "application"
    Copy-Tree $ApplicationArtifact $applicationDestination
    foreach ($required in @(
        "Mavi.Api.dll",
        "web.config",
        "mavi-application-manifest.json",
        "tools\ffmpeg\manifest.json",
        "tools\ffmpeg\win-x64\ffmpeg.exe",
        "tools\ffmpeg\win-x64\ffprobe.exe"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $applicationDestination $required) -PathType Leaf)) {
            throw "Production application artifact is incomplete: $required"
        }
    }
}

if ($HostingBundle) {
    $hostingDestination = Join-Path $destination "prerequisites\hosting\win-x64"
    New-Item -ItemType Directory -Path $hostingDestination -Force | Out-Null
    Copy-Item -LiteralPath $HostingBundle -Destination (Join-Path $hostingDestination "dotnet-hosting.exe")
}

$developerDestination = Join-Path $destination "prerequisites\developer\win-x64"
$developerInstallers = [ordered]@{
    "dotnet-sdk.exe" = $DotNetSdkInstaller
    "node.msi" = $NodeInstaller
    "python.exe" = $PythonInstaller
}
foreach ($entry in $developerInstallers.GetEnumerator()) {
    if (-not [string]::IsNullOrWhiteSpace([string]$entry.Value)) {
        New-Item -ItemType Directory -Path $developerDestination -Force | Out-Null
        Copy-Item -LiteralPath ([string]$entry.Value) -Destination (Join-Path $developerDestination ([string]$entry.Key))
    }
}

$readme = @"
MAVI OFFLINE SETUP

Production:
  Double-click Setup-MAVI-Production.cmd and approve the Administrator prompt.

Development:
  Double-click Setup-MAVI-Development.cmd and approve the Administrator prompt.

The installer verifies this bundle before changing the machine. Default deployment
parameters are intentionally opinionated to minimize operator configuration.
See docs/runbooks/mavi-offline-setup.md in the source repository for details.
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
$artifacts = foreach ($file in $artifactFiles) {
    $relative = [IO.Path]::GetRelativePath($destination, $file.FullName).Replace("\", "/")
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
    containsProductionApplication = [bool]$ApplicationArtifact
    containsHostingBundle = [bool]$HostingBundle
    containsDeveloperToolchain = [ordered]@{
        dotnetSdk = [bool]$DotNetSdkInstaller
        node = [bool]$NodeInstaller
        python = [bool]$PythonInstaller
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
