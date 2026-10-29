[CmdletBinding()]
param(
    # CPython 3.12.10, the interpreter identity src\vision\runtime\embeddings-onnx-v1\runtime.json records. The
    # environment is the Development-only embeddings-onnx-v1 runtime of PoC S4 (ADR-021); it is never a qualified
    # Runtime Pack and Production refuses it.
    [Parameter(Mandatory = $true)]
    [string]$Python,

    # A new virtual environment directory (refused if it exists, unless -ReuseVerified). Keep it outside the repository.
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    # The model store the embeddings worker reads (MAVI_MODEL_ROOT); the SigLIP 2 pack is staged into it.
    [Parameter(Mandatory = $true)]
    [string]$ModelRoot,

    # The developer offline cache (or a PoC bundle's embeddings\ directory) holding python-embeddings-wheelhouse\
    # and embeddings-payloads\.
    [string]$Cache = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64"),

    # Reuse an environment this script installed for the same lock (after pip check); the pack is re-staged and
    # re-verified either way.
    [switch]$ReuseVerified
)

# Disconnected installation: pip runs with --no-index --require-hashes from the family's committed lock, and every
# Model Pack payload is staged and SHA-256 verified against the committed unverified manifest
# (tools\vision\embeddings_packs.py). Nothing is downloaded.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$cache = [IO.Path]::GetFullPath($Cache)
$wheelhouse = Join-Path $cache "python-embeddings-wheelhouse"
$payloads = Join-Path $cache "embeddings-payloads"
$lock = Join-Path $repoRoot "src\vision\runtime\embeddings-onnx-v1\windows-x86_64-cpu.lock"
foreach ($required in @($wheelhouse, $payloads)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) {
        throw "Offline cache is missing '$required'. Prepare it with tools\setup\Prepare-MaviDeveloperOfflineCache.ps1 on a connected machine."
    }
}

$version = (& $Python -c "import platform; print(platform.python_version())").Trim()
if ($LASTEXITCODE -ne 0 -or $version -ne "3.12.10") {
    throw "The embeddings-onnx-v1 runtime records CPython 3.12.10; '$Python' is $version."
}

$destination = [IO.Path]::GetFullPath($Destination)
$venvPython = Join-Path $destination "Scripts\python.exe"
$statePath = Join-Path $destination "embeddings-runtime-install.json"
$lockSha256 = (Get-FileHash -LiteralPath $lock -Algorithm SHA256).Hash.ToLowerInvariant()
$reused = $false
if (Test-Path -LiteralPath $destination) {
    $state = if (Test-Path -LiteralPath $statePath -PathType Leaf) { Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json } else { $null }
    if (-not $ReuseVerified -or -not $state -or [string]$state.lockSha256 -ne $lockSha256 -or -not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw "Refusing to overwrite the existing environment '$destination'."
    }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "The existing embeddings-onnx-v1 environment '$destination' is not consistent; remove it and rerun." }
    $reused = $true
}
else {
    try {
        & $Python -m venv $destination
        if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
        & $venvPython -m pip install --no-index --find-links $wheelhouse --require-hashes --no-deps -r $lock
        if ($LASTEXITCODE -ne 0) { throw "Offline installation of the embeddings-onnx-v1 runtime failed." }
        & $venvPython -m pip check
        if ($LASTEXITCODE -ne 0) { throw "The installed embeddings-onnx-v1 environment is not consistent." }
    }
    catch {
        Remove-Item -LiteralPath $destination -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

& $venvPython (Join-Path $repoRoot "tools\vision\embeddings_packs.py") stage --source $payloads --model-root $ModelRoot
if ($LASTEXITCODE -ne 0) { throw "Embeddings Model Pack staging failed." }

if (-not $reused) {
    $utf8 = New-Object Text.UTF8Encoding -ArgumentList $false
    $stateJson = [ordered]@{
        schemaVersion = "mavi-embeddings-runtime-install-v1"
        runtimeFamily = "embeddings-onnx-v1"
        lockSha256 = $lockSha256
        pythonVersion = $version
        installedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
    } | ConvertTo-Json
    [IO.File]::WriteAllText($statePath, $stateJson + [Environment]::NewLine, $utf8)
}
Write-Host ("embeddings-onnx-v1 Development runtime {0} offline (PoC S4; never Production)." -f $(if ($reused) { "verified and reused" } else { "installed" }))
Write-Host "  Python    : $venvPython"
Write-Host "  Model root: $([IO.Path]::GetFullPath($ModelRoot))"
