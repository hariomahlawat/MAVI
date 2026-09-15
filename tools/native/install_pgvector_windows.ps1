[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackageRoot,

    [string]$PostgreSqlRoot = "C:\Program Files\PostgreSQL\18"
)

$ErrorActionPreference = "Stop"
$packageRoot = (Resolve-Path $PackageRoot).Path
$postgresRoot = [System.IO.Path]::GetFullPath($PostgreSqlRoot)
$manifestPath = Join-Path $packageRoot "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "pgvector manifest not found: $manifestPath" }

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schemaVersion -ne "1.0") { throw "Unsupported pgvector pack schema." }
if ([int]$manifest.postgresqlMajorVersion -ne 18) { throw "This MAVI baseline requires a PostgreSQL 18 pgvector pack." }
if ($manifest.runtimeId -ne "win-x64") { throw "This bootstrapper requires a win-x64 pgvector pack." }

$postgresExe = Join-Path $postgresRoot "bin\postgres.exe"
if (-not (Test-Path -LiteralPath $postgresExe -PathType Leaf)) { throw "PostgreSQL 18 installation not found at $postgresRoot" }
$versionOutput = & $postgresExe --version
if ($LASTEXITCODE -ne 0 -or $versionOutput -notmatch "PostgreSQL 18\.") { throw "The selected PostgreSQL installation is not PostgreSQL 18." }

foreach ($artifact in $manifest.artifacts) {
    $relative = [string]$artifact.relativePath
    if ([string]::IsNullOrWhiteSpace($relative) -or $relative.Contains("..") -or [System.IO.Path]::IsPathRooted($relative)) {
        throw "Invalid pgvector artifact path in manifest: $relative"
    }
    $source = Join-Path $packageRoot $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "pgvector artifact missing: $source" }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $source).Hash.ToLowerInvariant()
    $expected = ([string]$artifact.sha256).ToLowerInvariant()
    if ($actual -ne $expected) { throw "pgvector artifact failed SHA-256 verification: $relative" }
}

foreach ($artifact in $manifest.artifacts) {
    $relative = [string]$artifact.relativePath
    $source = Join-Path $packageRoot $relative
    $destination = Join-Path $postgresRoot $relative
    $destinationDirectory = Split-Path $destination -Parent
    if ($PSCmdlet.ShouldProcess($destination, "Install verified pgvector artifact")) {
        New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
}

Write-Host "Verified pgvector $($manifest.pgvectorVersion) prerequisite pack installed for PostgreSQL 18."
Write-Host "Restart PostgreSQL if it was running, then start MAVI. MAVI will enable the vector extension automatically."
