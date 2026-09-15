[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PostgreSqlRoot,

    [string]$DestinationRoot = (Join-Path $PSScriptRoot "..\..\vendor\postgresql\pg18\win-x64")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$sourceRoot = (Resolve-Path -LiteralPath $PostgreSqlRoot).Path
$destinationRoot = [IO.Path]::GetFullPath($DestinationRoot)
$postgresExe = Join-Path $sourceRoot "bin\postgres.exe"
$pgConfigExe = Join-Path $sourceRoot "bin\pg_config.exe"
$vectorControl = Join-Path $sourceRoot "share\extension\vector.control"

foreach ($required in @($postgresExe, $pgConfigExe, $vectorControl)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required PostgreSQL runtime artifact is missing: $required"
    }
}

$postgresVersionOutput = (& $postgresExe --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $postgresVersionOutput -notmatch "PostgreSQL 18\.") {
    throw "MAVI requires a PostgreSQL 18 source runtime."
}
$postgresVersion = (($postgresVersionOutput -split "\s+") | Select-Object -Last 1).Trim()

$control = Get-Content -LiteralPath $vectorControl -Raw
$versionMatch = [regex]::Match($control, 'default_version\s*=\s*[''"](?<v>[^''"]+)[''"]')
if (-not $versionMatch.Success) {
    throw "Unable to determine pgvector version from vector.control."
}
$pgVectorVersion = $versionMatch.Groups["v"].Value

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

$copyright = Join-Path $sourceRoot "COPYRIGHT"
if (Test-Path -LiteralPath $copyright -PathType Leaf) {
    Copy-Item -LiteralPath $copyright -Destination $destinationRoot -Force
}

$artifactFiles = @(Get-ChildItem -LiteralPath $destinationRoot -File -Recurse | Sort-Object FullName)
$artifacts = foreach ($file in $artifactFiles) {
    $relative = [IO.Path]::GetRelativePath($destinationRoot, $file.FullName).Replace("\", "/")
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
    artifacts = @($artifacts)
}

$manifestPath = Join-Path $destinationRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Host "Staged MAVI PostgreSQL runtime pack."
Write-Host "  PostgreSQL : $postgresVersion"
Write-Host "  pgvector   : $pgVectorVersion"
Write-Host "  Files      : $($artifactFiles.Count)"
Write-Host "  Output     : $destinationRoot"
Write-Host "  Manifest SHA-256: $manifestHash"
