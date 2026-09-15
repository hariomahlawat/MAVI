[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$KitRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force

$kitRoot = (Resolve-Path -LiteralPath $KitRoot).Path
$manifestPath = Join-Path $kitRoot "mavi-offline-binary-kit.json"
$manifest = Test-MaviManifest -Root $kitRoot -ManifestPath $manifestPath -ExpectedSchemaVersion "mavi-offline-binary-kit-v1"

$catalogPath = Join-Path $kitRoot "catalog\offline-binary-catalog-v1.json"
$catalog = Read-MaviJson -Path $catalogPath
if ([string]$catalog.schemaVersion -ne "mavi-offline-binary-catalog-v1") {
    throw "Offline binary kit contains an unsupported catalog schema."
}
if ((Get-MaviSha256 -Path $catalogPath) -ne ([string]$manifest.sourceCatalogSha256).ToLowerInvariant()) {
    throw "Offline binary kit catalog hash does not match the kit manifest."
}

$postgreSqlRoot = Join-Path $kitRoot "vendor\postgresql\pg18\win-x64"
$postgreSql = Test-MaviManifest -Root $postgreSqlRoot -ManifestPath (Join-Path $postgreSqlRoot "manifest.json") -ExpectedSchemaVersion "mavi-postgresql-runtime-pack-v1"

$ffmpegRoot = Join-Path $kitRoot "vendor\ffmpeg"
$ffmpeg = Test-MaviManifest -Root $ffmpegRoot -ManifestPath (Join-Path $ffmpegRoot "manifest.json") -ExpectedSchemaVersion "1.0"

foreach ($required in @(
    "vendor\installers\win-x64\dotnet-hosting.exe",
    "vendor\installers\win-x64\dotnet-sdk.exe",
    "vendor\installers\win-x64\node.msi",
    "vendor\installers\win-x64\python.exe"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $kitRoot $required) -PathType Leaf)) {
        throw "Offline binary kit is missing required installer: $required"
    }
}

foreach ($cache in @(
    "vendor\developer-cache\win-x64\nuget-packages",
    "vendor\developer-cache\win-x64\npm-cache",
    "vendor\developer-cache\win-x64\python-wheelhouse"
)) {
    if (-not (Test-Path -LiteralPath (Join-Path $kitRoot $cache) -PathType Container)) {
        throw "Offline binary kit is missing required Development cache: $cache"
    }
}

if ([string]$manifest.versions.postgresql -ne [string]$postgreSql.postgresqlVersion) {
    throw "Offline binary kit PostgreSQL version record does not match nested runtime manifest."
}
if ([string]$manifest.versions.pgvector -ne [string]$postgreSql.pgvectorVersion) {
    throw "Offline binary kit pgvector version record does not match nested runtime manifest."
}
if ([string]$manifest.versions.ffmpeg -ne [string]$ffmpeg.version) {
    throw "Offline binary kit FFmpeg version record does not match nested dependency manifest."
}

function Get-CatalogBaseline {
    param([Parameter(Mandatory = $true)][string]$Id)
    foreach ($component in @($catalog.applicationAndSetup)) {
        if ([string]$component.id -eq $Id) {
            return [string]$component.baselineVersion
        }
    }
    throw "Offline binary kit catalog does not contain required component '$Id'."
}

$baselineChecks = [ordered]@{
    dotnetHostingBaseline = "dotnet-hosting-win-x64"
    dotnetSdkBaseline = "dotnet-sdk-win-x64"
    nodeBaseline = "node-win-x64"
    pythonDevelopmentBaseline = "python-development-win-x64"
}
foreach ($entry in $baselineChecks.GetEnumerator()) {
    $expected = Get-CatalogBaseline -Id $entry.Value
    $actualProperty = $manifest.versions.PSObject.Properties[$entry.Key]
    if (-not $actualProperty -or [string]$actualProperty.Value -ne $expected) {
        throw "Offline binary kit version baseline '$($entry.Key)' does not match its catalog."
    }
}

Write-Host "MAVI offline binary kit validation PASSED."
Write-Host "  PostgreSQL : $($postgreSql.postgresqlVersion)"
Write-Host "  pgvector   : $($postgreSql.pgvectorVersion)"
Write-Host "  FFmpeg      : $($ffmpeg.version)"
Write-Host "  Manifest    : $(Get-MaviSha256 -Path $manifestPath)"
