[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64"),

    [string]$Python = "python",

    # PoC S4 (ADR-021): the controlled store holding the exported SigLIP 2 embeddings pack (built once by
    # tools\vision\build_siglip2_pack.py; there is no upstream URL for the ONNX towers). Collected SHA-256 verified.
    [string]$EmbeddingsPackSource = "E:\MAVI-Controlled\PoC\S4\pack"
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
$instrumentWheelRoot = Join-Path $destination "python-benchmark-instruments-wheelhouse"
$instrumentPayloadRoot = Join-Path $destination "benchmark-instrument-payloads"
$platesWheelRoot = Join-Path $destination "python-plates-pilot-wheelhouse"
$platesPayloadRoot = Join-Path $destination "plates-pilot-payloads"
$embeddingsWheelRoot = Join-Path $destination "python-embeddings-wheelhouse"
$embeddingsPayloadRoot = Join-Path $destination "embeddings-payloads"

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $nugetRoot -Force | Out-Null
New-Item -ItemType Directory -Path $npmRoot -Force | Out-Null
New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null
New-Item -ItemType Directory -Path $instrumentWheelRoot -Force | Out-Null
New-Item -ItemType Directory -Path $instrumentPayloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path $platesWheelRoot -Force | Out-Null
New-Item -ItemType Directory -Path $platesPayloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path $embeddingsWheelRoot -Force | Out-Null
New-Item -ItemType Directory -Path $embeddingsPayloadRoot -Force | Out-Null

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

    $toolsRequirements = Join-Path $repoRoot "tools\requirements.txt"
    & $Python -m pip download --dest $pythonRoot -r $toolsRequirements
    if ($LASTEXITCODE -ne 0) {
        throw "Repository verification dependency download failed."
    }

    # Stage-4 measuring-instrument environment (Development benchmark only; CPython 3.12, Windows x64 wheels) and
    # the model payloads its instruments load. Installed offline by
    # tools\benchmarks\plates\Install-PlateInstrumentEnvironment.ps1.
    $instrumentRequirements = Join-Path $repoRoot "tools\benchmarks\plates\requirements-instruments.txt"
    & $Python -m pip download --dest $instrumentWheelRoot -r $instrumentRequirements --only-binary=:all: --python-version 3.12 --implementation cp --platform win_amd64
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark instrument wheelhouse preparation failed."
    }
    & $Python (Join-Path $repoRoot "tools\benchmarks\plates\instrument_env.py") fetch-payloads --dest $instrumentPayloadRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Benchmark instrument model payload preparation failed."
    }

    # Issue #225 Development ANPR pilot: the plates-onnx-v1 runtime family (exact wheels of its hash-pinned lock) and
    # the unverified pilot Model Pack payloads. Installed offline by tools\setup\Install-MaviPlatesPilotRuntime.ps1.
    $platesLock = Join-Path $repoRoot "src\vision\runtime\plates-onnx-v1\windows-x86_64-cpu.lock"
    & $Python -m pip download --dest $platesWheelRoot -r $platesLock --require-hashes --no-deps --only-binary=:all: --python-version 3.12 --implementation cp --platform win_amd64
    if ($LASTEXITCODE -ne 0) {
        throw "Plates pilot runtime wheelhouse preparation failed."
    }
    & $Python (Join-Path $repoRoot "tools\vision\plates_pilot_packs.py") fetch --dest $platesPayloadRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Plates pilot Model Pack payload preparation failed."
    }

    # PoC S4 (ADR-021): the embeddings-onnx-v1 runtime family (exact wheels of its hash-pinned lock) and the
    # unverified SigLIP 2 Model Pack payloads. Installed offline by tools\setup\Install-MaviEmbeddingsRuntime.ps1.
    $embeddingsLock = Join-Path $repoRoot "src\vision\runtime\embeddings-onnx-v1\windows-x86_64-cpu.lock"
    & $Python -m pip download --dest $embeddingsWheelRoot -r $embeddingsLock --require-hashes --no-deps --only-binary=:all: --python-version 3.12 --implementation cp --platform win_amd64
    if ($LASTEXITCODE -ne 0) {
        throw "Embeddings runtime wheelhouse preparation failed."
    }
    & $Python (Join-Path $repoRoot "tools\vision\embeddings_packs.py") collect --source $EmbeddingsPackSource --dest $embeddingsPayloadRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Embeddings Model Pack payload preparation failed."
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
    instrumentRequirementsSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "tools\benchmarks\plates\requirements-instruments.txt") -Algorithm SHA256).Hash.ToLowerInvariant()
    instrumentPayloadsSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "tools\benchmarks\plates\instrument-payloads-v1.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    platesPilotLockSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "src\vision\runtime\plates-onnx-v1\windows-x86_64-cpu.lock") -Algorithm SHA256).Hash.ToLowerInvariant()
    platesPilotPayloadsSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "tools\vision\plates-pilot-payloads-v1.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    embeddingsLockSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "src\vision\runtime\embeddings-onnx-v1\windows-x86_64-cpu.lock") -Algorithm SHA256).Hash.ToLowerInvariant()
    embeddingsManifestSha256 = (Get-FileHash -LiteralPath (Join-Path $repoRoot "models\manifests\embeddings-siglip2-base-p16-224-dev-v1.json") -Algorithm SHA256).Hash.ToLowerInvariant()
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

$instrumentArtifacts = @()
foreach ($file in @(Get-ChildItem -LiteralPath $instrumentWheelRoot, $instrumentPayloadRoot -File -Recurse | Sort-Object FullName)) {
    $instrumentArtifacts += [ordered]@{
        path = $file.FullName.Substring($destination.Length).TrimStart('\').Replace('\', '/')
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        sizeBytes = [long]$file.Length
    }
}

$platesArtifacts = @()
foreach ($file in @(Get-ChildItem -LiteralPath $platesWheelRoot, $platesPayloadRoot -File -Recurse | Sort-Object FullName)) {
    $platesArtifacts += [ordered]@{
        path = $file.FullName.Substring($destination.Length).TrimStart('\').Replace('\', '/')
        sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        sizeBytes = [long]$file.Length
    }
}

$embeddingsArtifacts = @()
foreach ($file in @(Get-ChildItem -LiteralPath $embeddingsWheelRoot, $embeddingsPayloadRoot -File -Recurse | Sort-Object FullName)) {
    $embeddingsArtifacts += [ordered]@{
        path = $file.FullName.Substring($destination.Length).TrimStart('\').Replace('\', '/')
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
    benchmarkInstrumentArtifacts = @($instrumentArtifacts)
    platesPilotArtifacts = @($platesArtifacts)
    embeddingsArtifacts = @($embeddingsArtifacts)
}
$cacheManifestPath = Join-Path $destination "developer-cache-manifest.json"
$cacheManifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $cacheManifestPath -Encoding UTF8

Write-Host "MAVI offline developer dependency cache prepared."
Write-Host "  Manifest: $cacheManifestPath"
Write-Host "  NuGet packages : $($nugetPackages.Count)"
Write-Host "  npm packages   : $($npmPackages.Count)"
Write-Host "  Python artifacts: $($pythonArtifacts.Count)"
Write-Host "  Benchmark instrument artifacts: $($instrumentArtifacts.Count)"
Write-Host "  Plates pilot artifacts: $($platesArtifacts.Count)"
Write-Host "  Embeddings artifacts: $($embeddingsArtifacts.Count)"
Write-Host "  NuGet : $nugetRoot"
Write-Host "  npm   : $npmRoot"
Write-Host "  Python: $pythonRoot"
