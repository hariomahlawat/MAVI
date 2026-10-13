[CmdletBinding()]
param(
    # CPython 3.12 (rapidocr-onnxruntime 1.4.4 needs Python < 3.13). The environment is a Development benchmark
    # environment only; it is never part of a MAVI Runtime Pack.
    [Parameter(Mandatory = $true)]
    [string]$Python,

    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [Parameter(Mandatory = $true)]
    [string]$ModelRoot,

    [string]$Cache = (Join-Path $PSScriptRoot "..\..\..\vendor\developer-cache\win-x64")
)

# Disconnected installation of the Stage-4 measuring-instrument environment (adequacy protocol §6) from the
# developer offline cache prepared by tools\setup\Prepare-MaviDeveloperOfflineCache.ps1: pip runs with --no-index,
# and every model payload is staged and verified against docs\qualification\stage4\instruments\*.json.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
$cache = [IO.Path]::GetFullPath($Cache)
$wheelhouse = Join-Path $cache "python-benchmark-instruments-wheelhouse"
$payloads = Join-Path $cache "benchmark-instrument-payloads"
foreach ($required in @($wheelhouse, $payloads)) {
    if (-not (Test-Path -LiteralPath $required -PathType Container)) {
        throw "Developer offline cache is missing '$required'. Prepare it with tools\setup\Prepare-MaviDeveloperOfflineCache.ps1 on a connected machine."
    }
}

$version = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
if ($LASTEXITCODE -ne 0 -or $version -ne "3.12") {
    throw "The instrument environment needs CPython 3.12; '$Python' is $version."
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

& $venvPython -m pip install --no-index --find-links $wheelhouse -r (Join-Path $repoRoot "tools\benchmarks\plates\requirements-instruments.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Offline installation of the instrument environment failed."
}

$sitePackages = (& $venvPython -c "import sysconfig; print(sysconfig.get_paths()['purelib'])").Trim()
& $venvPython (Join-Path $repoRoot "tools\benchmarks\plates\instrument_env.py") stage-models --cache $payloads --site-packages $sitePackages --model-root $ModelRoot
if ($LASTEXITCODE -ne 0) {
    throw "Instrument model payload staging failed."
}

Write-Host "Stage-4 instrument environment installed offline."
Write-Host "  Python    : $venvPython"
Write-Host "  Model root: $([IO.Path]::GetFullPath($ModelRoot))"
