[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PostgreSqlRoot,

    [Parameter(Mandatory = $true)]
    [string]$PgVectorVersion,

    [string]$DestinationRoot = (Join-Path $PSScriptRoot "..\..\vendor\pgvector\pg18\win-x64")
)

$ErrorActionPreference = "Stop"
$pgRoot = (Resolve-Path $PostgreSqlRoot).Path
$destinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)
$postgresExe = Join-Path $pgRoot "bin\postgres.exe"
if (-not (Test-Path -LiteralPath $postgresExe -PathType Leaf)) { throw "PostgreSQL executable not found at $postgresExe" }
$versionOutput = & $postgresExe --version
if ($LASTEXITCODE -ne 0 -or -not (Test-MaviPostgreSqlMajorVersionOutput -VersionOutput ($versionOutput | Out-String) -Major 18)) { throw "MAVI requires a PostgreSQL 18 pgvector source installation." }

$sources = @(
    [ordered]@{ source = (Join-Path $pgRoot "lib\vector.dll"); relative = "lib/vector.dll" },
    [ordered]@{ source = (Join-Path $pgRoot "share\extension\vector.control"); relative = "share/extension/vector.control" }
)

$controlPath = Join-Path $pgRoot "share\extension\vector.control"
$control = Get-Content -LiteralPath $controlPath -Raw
$escapedVersion = [System.Text.RegularExpressions.Regex]::Escape($PgVectorVersion)
$versionPattern = 'default_version\s*=\s*[''"]{0}[''"]' -f $escapedVersion
if ($control -notmatch $versionPattern) {
    throw "vector.control does not declare pgvector version '$PgVectorVersion'."
}
$sqlFiles = Get-ChildItem -LiteralPath (Join-Path $pgRoot "share\extension") -Filter "vector--*.sql" -File
if (-not $sqlFiles) { throw "No pgvector extension SQL files were found." }
foreach ($sql in $sqlFiles) {
    $sources += [ordered]@{ source = $sql.FullName; relative = "share/extension/$($sql.Name)" }
}
foreach ($entry in $sources) {
    if (-not (Test-Path -LiteralPath $entry.source -PathType Leaf)) { throw "Required pgvector artifact not found: $($entry.source)" }
}

if (Test-Path -LiteralPath $destinationRoot) { Remove-Item -LiteralPath $destinationRoot -Recurse -Force }
New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null

$artifacts = @()
foreach ($entry in $sources | Sort-Object relative) {
    $destination = Join-Path $destinationRoot ($entry.relative -replace "/", "\")
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $entry.source -Destination $destination
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant()
    $artifacts += [ordered]@{ relativePath = $entry.relative; sha256 = $hash }
}

$manifest = [ordered]@{
    schemaVersion = "1.0"
    postgresqlMajorVersion = 18
    pgvectorVersion = $PgVectorVersion
    runtimeId = "win-x64"
    artifacts = $artifacts
}
$manifestPath = Join-Path $destinationRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
$manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
Write-Host "Staged pgvector offline prerequisite pack at $destinationRoot"
Write-Host "Manifest SHA-256: $manifestHash"
Get-Content -LiteralPath $manifestPath
