[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [string]$PostgreSqlRuntimePack = (Join-Path $PSScriptRoot "..\..\vendor\postgresql\pg18\win-x64"),

    [string]$FfmpegPack = (Join-Path $PSScriptRoot "..\..\vendor\ffmpeg"),

    [string]$HostingBundle = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\dotnet-hosting.exe"),

    [string]$DotNetSdkInstaller = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\dotnet-sdk.exe"),

    [string]$NodeInstaller = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\node.msi"),

    [string]$PythonInstaller = (Join-Path $PSScriptRoot "..\..\vendor\installers\win-x64\python.exe"),

    [string]$DeveloperDependencyCache = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64"),

    [string]$CatalogPath = (Join-Path $PSScriptRoot "..\..\config\dependencies\offline-binary-catalog-v1.json"),

    [string]$ZipPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force

$destination = [IO.Path]::GetFullPath($Destination)
$postgreSqlRuntimePack = (Resolve-Path -LiteralPath $PostgreSqlRuntimePack).Path
$ffmpegPack = (Resolve-Path -LiteralPath $FfmpegPack).Path
$developerDependencyCache = (Resolve-Path -LiteralPath $DeveloperDependencyCache).Path
$catalogPath = (Resolve-Path -LiteralPath $CatalogPath).Path

$catalog = Read-MaviJson -Path $catalogPath
if ([string]$catalog.schemaVersion -ne "mavi-offline-binary-catalog-v1") {
    throw "Unsupported MAVI offline binary catalog schema."
}

$postgreSqlManifest = Test-MaviManifest -Root $postgreSqlRuntimePack -ManifestPath (Join-Path $postgreSqlRuntimePack "manifest.json") -ExpectedSchemaVersion "mavi-postgresql-runtime-pack-v1"
$ffmpegManifest = Test-MaviManifest -Root $ffmpegPack -ManifestPath (Join-Path $ffmpegPack "manifest.json") -ExpectedSchemaVersion "1.0"

$requiredInstallers = [ordered]@{
    "dotnet-hosting.exe" = $HostingBundle
    "dotnet-sdk.exe" = $DotNetSdkInstaller
    "node.msi" = $NodeInstaller
    "python.exe" = $PythonInstaller
}
foreach ($entry in $requiredInstallers.GetEnumerator()) {
    if (-not (Test-Path -LiteralPath $entry.Value -PathType Leaf)) {
        throw "Required offline installer was not found: $($entry.Value)"
    }
}

foreach ($cacheDirectory in @("nuget-packages", "npm-cache", "python-wheelhouse")) {
    if (-not (Test-Path -LiteralPath (Join-Path $developerDependencyCache $cacheDirectory) -PathType Container)) {
        throw "Developer dependency cache is incomplete: $cacheDirectory"
    }
}

function Copy-MaviTree {
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

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null

$catalogDestination = Join-Path $destination "catalog"
New-Item -ItemType Directory -Path $catalogDestination -Force | Out-Null
Copy-Item -LiteralPath $catalogPath -Destination (Join-Path $catalogDestination "offline-binary-catalog-v1.json")

Copy-MaviTree -Source $postgreSqlRuntimePack -Target (Join-Path $destination "vendor\postgresql\pg18\win-x64")
Copy-MaviTree -Source $ffmpegPack -Target (Join-Path $destination "vendor\ffmpeg")
Copy-MaviTree -Source $developerDependencyCache -Target (Join-Path $destination "vendor\developer-cache\win-x64")

$installerDestination = Join-Path $destination "vendor\installers\win-x64"
New-Item -ItemType Directory -Path $installerDestination -Force | Out-Null
foreach ($entry in $requiredInstallers.GetEnumerator()) {
    Copy-Item -LiteralPath $entry.Value -Destination (Join-Path $installerDestination $entry.Key)
}

$readme = @"
MAVI OFFLINE BINARY KIT

This is a separately retained dependency payload for MAVI.

Recommended layout:
  <workspace>\MAVI
  <workspace>\MAVI-Offline-Binary-Kit

Development setup auto-detects this sibling kit.

Do not edit payload files after this manifest is created. If any dependency is
updated, rebuild the complete kit so hashes and recorded versions stay coherent.

This kit does not replace the final MAVI application setup bundle or Task-17
vision-runtime qualification.
"@
[IO.File]::WriteAllText((Join-Path $destination "README-FIRST.txt"), $readme, [Text.UTF8Encoding]::new($false))

$artifactFiles = @(
    Get-ChildItem -LiteralPath $destination -File -Recurse |
        Where-Object { $_.Name -ne "mavi-offline-binary-kit.json" } |
        Sort-Object FullName
)
$prefix = $destination.TrimEnd("\") + "\"
$artifacts = foreach ($file in $artifactFiles) {
    if (-not $file.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Binary-kit artifact escaped destination root: $($file.FullName)"
    }

    $relative = $file.FullName.Substring($prefix.Length).Replace("\", "/")
    [ordered]@{
        relativePath = $relative
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        sizeBytes = [long]$file.Length
    }
}

function Get-CatalogBaseline {
    param([Parameter(Mandatory = $true)][string]$Id)

    foreach ($component in @($catalog.applicationAndSetup)) {
        if ([string]$component.id -eq $Id) {
            return [string]$component.baselineVersion
        }
    }
    throw "Binary catalog does not contain required component '$Id'."
}

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$sourceInputPaths = [ordered]@{
    offlineDependencyPolicy = (Join-Path $repoRoot "config\dependencies\offline-dependency-policy-v1.json")
    offlineBinaryCatalog = $catalogPath
    globalJson = (Join-Path $repoRoot "global.json")
    webPackageLock = (Join-Path $repoRoot "src\web\mavi-web\package-lock.json")
    visionPyproject = (Join-Path $repoRoot "src\vision\pyproject.toml")
    toolsRequirements = (Join-Path $repoRoot "tools\requirements.txt")
}
$sourceInputs = [ordered]@{}
foreach ($entry in $sourceInputPaths.GetEnumerator()) {
    $sourceInputs[$entry.Key] = Get-MaviSha256 -Path $entry.Value
}

$manifest = [ordered]@{
    schemaVersion = "mavi-offline-binary-kit-v1"
    sourceCatalogSha256 = (Get-MaviSha256 -Path $catalogPath)
    sourceInputs = $sourceInputs
    versions = [ordered]@{
        postgresql = [string]$postgreSqlManifest.postgresqlVersion
        pgvector = [string]$postgreSqlManifest.pgvectorVersion
        ffmpeg = [string]$ffmpegManifest.version
        dotnetHostingBaseline = Get-CatalogBaseline -Id "dotnet-hosting-win-x64"
        dotnetSdkBaseline = Get-CatalogBaseline -Id "dotnet-sdk-win-x64"
        nodeBaseline = Get-CatalogBaseline -Id "node-win-x64"
        pythonDevelopmentBaseline = Get-CatalogBaseline -Id "python-development-win-x64"
    }
    payload = [ordered]@{
        postgresqlRuntime = "vendor/postgresql/pg18/win-x64"
        ffmpeg = "vendor/ffmpeg"
        installers = "vendor/installers/win-x64"
        developerCache = "vendor/developer-cache/win-x64"
    }
    artifacts = @($artifacts)
}

$manifestPath = Join-Path $destination "mavi-offline-binary-kit.json"
Write-MaviJson -Value $manifest -Path $manifestPath -Depth 10
$manifestHash = Get-MaviSha256 -Path $manifestPath

Write-Host "MAVI offline binary kit created."
Write-Host "  Destination : $destination"
Write-Host "  Files       : $($artifactFiles.Count)"
Write-Host "  PostgreSQL  : $($postgreSqlManifest.postgresqlVersion)"
Write-Host "  pgvector    : $($postgreSqlManifest.pgvectorVersion)"
Write-Host "  FFmpeg      : $($ffmpegManifest.version)"
Write-Host "  Manifest SHA-256: $manifestHash"

if (-not [string]::IsNullOrWhiteSpace($ZipPath)) {
    $zipPath = [IO.Path]::GetFullPath($ZipPath)
    $zipParent = Split-Path $zipPath -Parent
    if ($zipParent) {
        New-Item -ItemType Directory -Path $zipParent -Force | Out-Null
    }
    if (Test-Path -LiteralPath $zipPath) {
        Remove-Item -LiteralPath $zipPath -Force
    }

    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        $parent = Split-Path $destination -Parent
        $leaf = Split-Path $destination -Leaf
        & $tar.Source -a -c -f $zipPath -C $parent $leaf
        if ($LASTEXITCODE -ne 0) {
            throw "tar.exe failed while creating binary-kit ZIP with exit code $LASTEXITCODE."
        }
    }
    else {
        Compress-Archive -LiteralPath $destination -DestinationPath $zipPath -CompressionLevel Optimal
    }

    Write-Host "  ZIP         : $zipPath"
    Write-Host "  ZIP SHA-256 : $(Get-MaviSha256 -Path $zipPath)"
}
