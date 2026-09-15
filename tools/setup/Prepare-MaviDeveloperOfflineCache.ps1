[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64"),

    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Assert-MaviWindows

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$destination = [IO.Path]::GetFullPath($Destination)
$nugetRoot = Join-Path $destination "nuget-packages"
$npmRoot = Join-Path $destination "npm-cache"
$pythonRoot = Join-Path $destination "python-wheelhouse"

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $nugetRoot -Force | Out-Null
New-Item -ItemType Directory -Path $npmRoot -Force | Out-Null
New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null

Push-Location $repoRoot
try {
    & dotnet restore "MAVI.sln" --packages $nugetRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Connected NuGet cache preparation failed."
    }

    Push-Location (Join-Path $repoRoot "src\web\mavi-web")
    try {
        & npm ci --cache $npmRoot --prefer-online
        if ($LASTEXITCODE -ne 0) {
            throw "Connected npm cache preparation failed."
        }
        & npm cache verify --cache $npmRoot
        if ($LASTEXITCODE -ne 0) {
            throw "npm cache verification failed."
        }
    }
    finally {
        Pop-Location
    }

    & $Python -m pip download --dest $pythonRoot "setuptools>=75"
    if ($LASTEXITCODE -ne 0) {
        throw "Python build dependency download failed."
    }

    $visionRoot = Join-Path $repoRoot "src\vision"
    $visionEggInfo = Join-Path $visionRoot "mavi_vision.egg-info"
    Push-Location $visionRoot
    try {
        & $Python -m pip download --dest $pythonRoot ".[dev]"
        if ($LASTEXITCODE -ne 0) {
            throw "Python Development wheelhouse preparation failed."
        }
    }
    finally {
        Pop-Location
        # pip may materialize local project metadata while resolving the source
        # tree. It is generated build state and must never dirty the repository.
        if (Test-Path -LiteralPath $visionEggInfo -PathType Container) {
            Remove-Item -LiteralPath $visionEggInfo -Recurse -Force
        }
    }
}
finally {
    Pop-Location
}

# Create a human/audit-readable exact cache inventory. The binary-kit manifest
# will additionally hash this file and every retained cache byte.
$sourceInputs = [ordered]@{
    offlineDependencyPolicySha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "config\dependencies\offline-dependency-policy-v1.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    globalJsonSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "global.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    packageLockSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "src\web\mavi-web\package-lock.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    visionPyprojectSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "src\vision\pyproject.toml") -Algorithm SHA256).Hash.ToLowerInvariant()
    toolsRequirementsSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "tools\requirements.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
}

$nugetPackages = @()
foreach ($packageDirectory in @(Get-ChildItem -LiteralPath $nugetRoot -Directory | Sort-Object Name)) {
    foreach ($versionDirectory in @(Get-ChildItem -LiteralPath $packageDirectory.FullName -Directory | Sort-Object Name)) {
        $nugetPackages += [ordered]@{
            id = $packageDirectory.Name
            version = $versionDirectory.Name
        }
    }
}

$packageLockPath = Join-Path $repoRoot "src\web\mavi-web\package-lock.json"

# Windows PowerShell / ConvertFrom-Json cannot reliably materialize npm lockfile
# package maps because lockfileVersion 3 contains the required root entry with
# an empty-string property name (""). Parse the lock with Node.js (which is
# already a required preparation tool) and emit a normalized array containing
# only the fields needed for the audit manifest.
$nodeParser = @'
const fs = require("fs");
const path = process.argv[2];
const lock = JSON.parse(fs.readFileSync(path, "utf8"));

if (!lock.packages || typeof lock.packages !== "object") {
  throw new Error("package-lock.json does not contain the expected top-level packages object.");
}

const rows = Object.entries(lock.packages)
  .filter(([packagePath, entry]) =>
    packagePath.length > 0 &&
    entry &&
    typeof entry === "object" &&
    typeof entry.version === "string")
  .sort(([a], [b]) => a.localeCompare(b))
  .map(([packagePath, entry]) => ({
    packagePath,
    version: entry.version,
    developmentOnly: entry.dev === true
  }));

process.stdout.write(JSON.stringify(rows));
'@

$nodeParserPath = Join-Path ([IO.Path]::GetTempPath()) ("mavi-npm-lock-parser-" + [Guid]::NewGuid().ToString("N") + ".js")
try {
    # Avoid passing JavaScript through Windows PowerShell's native-command
    # quoting layer. Writing the parser to a temporary file preserves the
    # JavaScript source exactly and keeps package-lock.json as a normal argv.
    [IO.File]::WriteAllText($nodeParserPath, $nodeParser, (New-Object Text.UTF8Encoding($false)))
    $npmInventoryJson = (& node.exe $nodeParserPath $packageLockPath | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($npmInventoryJson)) {
        throw "Unable to derive npm package inventory from '$packageLockPath'."
    }
}
finally {
    Remove-Item -LiteralPath $nodeParserPath -Force -ErrorAction SilentlyContinue
}

try {
    $npmInventory = ConvertFrom-Json -InputObject $npmInventoryJson -ErrorAction Stop
}
catch {
    throw "Unable to parse normalized npm package inventory for '$packageLockPath': $($_.Exception.Message)"
}

$npmPackages = @()
foreach ($entry in @($npmInventory)) {
    $npmPackages += [ordered]@{
        packagePath = [string]$entry.packagePath
        version = [string]$entry.version
        developmentOnly = [bool]$entry.developmentOnly
    }
}

$pythonArtifacts = @()
foreach ($file in @(Get-ChildItem -LiteralPath $pythonRoot -File | Sort-Object Name)) {
    $pythonArtifacts += [ordered]@{
        fileName = $file.Name
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        sizeBytes = [long]$file.Length
    }
}

$cacheManifest = [ordered]@{
    schemaVersion = "mavi-developer-offline-cache-v1"
    sourceInputs = $sourceInputs
    nugetPackages = @($nugetPackages)
    npmPackages = @($npmPackages)
    pythonArtifacts = @($pythonArtifacts)
}
$cacheManifestPath = Join-Path $destination "developer-cache-manifest.json"
$cacheManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $cacheManifestPath -Encoding UTF8

Write-Host "MAVI offline developer dependency cache prepared."
Write-Host "  Manifest: $cacheManifestPath"
Write-Host "  NuGet packages : $($nugetPackages.Count)"
Write-Host "  npm packages   : $($npmPackages.Count)"
Write-Host "  Python artifacts: $($pythonArtifacts.Count)"
Write-Host "  NuGet : $nugetRoot"
Write-Host "  npm   : $npmRoot"
Write-Host "  Python: $pythonRoot"
