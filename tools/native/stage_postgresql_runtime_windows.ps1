[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PostgreSqlRoot,

    [Parameter(Mandatory = $true)]
    [string]$PgVectorLicensePath,

    [string]$PostgreSqlLicensePath,

    [string]$DestinationRoot = (Join-Path $PSScriptRoot "..\..\vendor\postgresql\pg18\win-x64")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "..\setup\Mavi.Setup.Common.psm1") -Force

$sourceRoot = (Resolve-Path -LiteralPath $PostgreSqlRoot).Path
$pgVectorLicensePath = (Resolve-Path -LiteralPath $PgVectorLicensePath).Path
$destinationRoot = [IO.Path]::GetFullPath($DestinationRoot)
$postgresExe = Join-Path $sourceRoot "bin\postgres.exe"
$pgConfigExe = Join-Path $sourceRoot "bin\pg_config.exe"
$vectorControl = Join-Path $sourceRoot "share\extension\vector.control"
# PostgreSQL contrib: the plate search's trigram index (Stage 4 PR-4). Shipped with PostgreSQL itself,
# so a source runtime without it is an incomplete installation, not a missing optional component.
$trigramControl = Join-Path $sourceRoot "share\extension\pg_trgm.control"
$trigramLibrary = Join-Path $sourceRoot "lib\pg_trgm.dll"

foreach ($required in @($postgresExe, $pgConfigExe, $vectorControl, $trigramControl, $trigramLibrary)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required PostgreSQL runtime artifact is missing: $required"
    }
}

$postgresVersionOutput = (& $postgresExe --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-MaviPostgreSqlMajorVersionOutput -VersionOutput $postgresVersionOutput -Major 18)) {
    throw "MAVI requires a PostgreSQL 18 source runtime."
}
$postgresVersion = (($postgresVersionOutput -split "\s+") | Select-Object -Last 1).Trim()

$control = Get-Content -LiteralPath $vectorControl -Raw
$versionMatch = [regex]::Match($control, 'default_version\s*=\s*[''"](?<v>[^''"]+)[''"]')
if (-not $versionMatch.Success) {
    throw "Unable to determine pgvector version from vector.control."
}
$pgVectorVersion = $versionMatch.Groups["v"].Value

$trigramMatch = [regex]::Match((Get-Content -LiteralPath $trigramControl -Raw), 'default_version\s*=\s*[''"](?<v>[^''"]+)[''"]')
if (-not $trigramMatch.Success) {
    throw "Unable to determine pg_trgm version from pg_trgm.control."
}
$pgTrgmVersion = $trigramMatch.Groups["v"].Value

if (Test-Path -LiteralPath $destinationRoot) {
    Remove-Item -LiteralPath $destinationRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null

foreach ($directory in @("bin", "lib", "share")) {
    $source = Join-Path $sourceRoot $directory
    if (-not (Test-Path -LiteralPath $source -PathType Container)) {
        throw "Required PostgreSQL runtime directory is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination $destinationRoot -Recurse -Force
}

$postgresLicense = $null
if (-not [string]::IsNullOrWhiteSpace($PostgreSqlLicensePath)) {
    $postgresLicense = (Resolve-Path -LiteralPath $PostgreSqlLicensePath).Path
}
else {
    foreach ($candidate in @(
        (Join-Path $sourceRoot "COPYRIGHT"),
        (Join-Path $sourceRoot "doc\COPYRIGHT"),
        (Join-Path $sourceRoot "doc\copyright")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $postgresLicense = $candidate
            break
        }
    }
}
if (-not $postgresLicense) {
    throw "PostgreSQL licence/copyright file was not found. Supply -PostgreSqlLicensePath explicitly."
}
Copy-Item -LiteralPath $postgresLicense -Destination (Join-Path $destinationRoot "LICENSE-POSTGRESQL.txt") -Force
Copy-Item -LiteralPath $pgVectorLicensePath -Destination (Join-Path $destinationRoot "LICENSE-PGVECTOR.txt") -Force

$artifactFiles = @(Get-ChildItem -LiteralPath $destinationRoot -File -Recurse | Sort-Object FullName)
$artifacts = foreach ($file in $artifactFiles) {
    $prefix = $destinationRoot.TrimEnd("\") + "\"
    if (-not $file.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "PostgreSQL staging artifact escaped destination root: $($file.FullName)"
    }
    $relative = $file.FullName.Substring($prefix.Length).Replace("\", "/")
    [ordered]@{
        relativePath = $relative
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        sizeBytes = [long]$file.Length
    }
}

$manifest = [ordered]@{
    schemaVersion = "mavi-postgresql-runtime-pack-v1"
    runtimeId = "win-x64"
    postgresqlMajorVersion = 18
    postgresqlVersion = $postgresVersion
    pgvectorVersion = $pgVectorVersion
    pgTrgmVersion = $pgTrgmVersion
    artifacts = @($artifacts)
}

$manifestPath = Join-Path $destinationRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "Staged MAVI PostgreSQL runtime pack."
Write-Host "  PostgreSQL : $postgresVersion"
Write-Host "  pgvector   : $pgVectorVersion"
Write-Host "  pg_trgm    : $pgTrgmVersion"
Write-Host "  Files      : $($artifactFiles.Count)"
Write-Host "  Output     : $destinationRoot"
Write-Host "  Manifest SHA-256: $manifestHash"
