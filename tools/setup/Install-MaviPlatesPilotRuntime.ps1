[CmdletBinding()]
param(
    # CPython 3.12.10, the interpreter identity src\vision\runtime\plates-onnx-v1\runtime.json records. The environment
    # is the Development-only plates-onnx-v1 runtime of the Issue #225 ANPR pilot; it is never a qualified Runtime Pack
    # and Production refuses it.
    [Parameter(Mandatory = $true)]
    [string]$Python,

    # A new virtual environment directory (refused if it exists). Keep it outside the repository.
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    # The Development model store the plates worker reads (MAVI_MODEL_ROOT); the pilot packs are staged into it.
    [Parameter(Mandatory = $true)]
    [string]$ModelRoot,

    [string]$Cache = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64"),

    # Stage the packs from the Stage-4 controlled candidate store instead of the developer cache payloads.
    [string]$ControlledStore
)

# Disconnected installation from the developer offline cache prepared by
# tools\setup\Prepare-MaviDeveloperOfflineCache.ps1: pip runs with --no-index --require-hashes from the family's
# committed lock, and every Model Pack payload is staged and SHA-256 verified against the committed unverified
# manifests (tools\vision\plates_pilot_packs.py). Nothing is downloaded.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$cache = [IO.Path]::GetFullPath($Cache)
$wheelhouse = Join-Path $cache "python-plates-pilot-wheelhouse"
$payloads = Join-Path $cache "plates-pilot-payloads"
$lock = Join-Path $repoRoot "src\vision\runtime\plates-onnx-v1\windows-x86_64-cpu.lock"
if (-not (Test-Path -LiteralPath $wheelhouse -PathType Container)) {
    throw "Developer offline cache is missing '$wheelhouse'. Prepare it with tools\setup\Prepare-MaviDeveloperOfflineCache.ps1 on a connected machine."
}

$version = (& $Python -c "import platform; print(platform.python_version())").Trim()
if ($LASTEXITCODE -ne 0 -or $version -ne "3.12.10") {
    throw "The plates-onnx-v1 runtime records CPython 3.12.10; '$Python' is $version."
}

$destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destination) {
    throw "Refusing to overwrite the existing environment '$destination'."
}
& $Python -m venv $destination
if ($LASTEXITCODE -ne 0) {
    throw "Virtual environment creation failed."
}
$venvPython = Join-Path $destination "Scripts\python.exe"

& $venvPython -m pip install --no-index --find-links $wheelhouse --require-hashes --no-deps -r $lock
if ($LASTEXITCODE -ne 0) {
    throw "Offline installation of the plates-onnx-v1 runtime failed."
}
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "The installed plates-onnx-v1 environment is not consistent."
}

$packTool = Join-Path $repoRoot "tools\vision\plates_pilot_packs.py"
if ([string]::IsNullOrWhiteSpace($ControlledStore)) {
    if (-not (Test-Path -LiteralPath $payloads -PathType Container)) {
        throw "Developer offline cache is missing '$payloads'."
    }
    & $venvPython $packTool stage --source $payloads --model-root $ModelRoot
}
else {
    & $venvPython $packTool stage --source $ControlledStore --controlled-store --model-root $ModelRoot
}
if ($LASTEXITCODE -ne 0) {
    throw "Plates pilot Model Pack staging failed."
}

Write-Host "plates-onnx-v1 Development runtime installed offline (Issue #225 pilot; never Production)."
Write-Host "  Python    : $venvPython"
Write-Host "  Model root: $([IO.Path]::GetFullPath($ModelRoot))"
