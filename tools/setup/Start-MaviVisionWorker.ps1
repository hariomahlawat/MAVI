[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$ApiBaseUrl = "http://localhost:62153",
    [string]$WorkerId = "dev-worker-01",
    [string]$MediaRoot = "C:\ProgramData\MAVI\Development\Data",
    [ValidateSet("cpu","cuda","auto")]
    [string]$DevicePolicy = "cpu",
    [int]$DeviceIndex = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$runtimeRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($runtimeRoot)) {
    $runtimeRoot = "C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu"
}
$runtimeRoot = [IO.Path]::GetFullPath($runtimeRoot.Trim().Trim('"'))

$statePath = Join-Path $runtimeRoot "runtime-install.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw "MAVI Vision Runtime is not installed. Run Setup-MAVI-Development.cmd with the MAVI-Vision-Runtime-Bundle beside the repository."
}
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json

$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw "git.exe is required to verify the worker source/runtime binding." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $head) {
    throw "Unable to determine repository HEAD."
}
if ($head -ne [string]$state.sourceCommit) {
    throw "Installed vision runtime is bound to source '$($state.sourceCommit)' but repository HEAD is '$head'. Reinstall the matching vision runtime bundle."
}

$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Vision runtime interpreter is missing: $python"
}

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_MEDIA_ROOT = $MediaRoot
$env:MAVI_DEVICE_POLICY = $DevicePolicy
$env:MAVI_DEVICE_INDEX = [string]$DeviceIndex
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_MODEL_ROOT = Join-Path $runtimeRoot "release\models"
$env:MAVI_MODEL_MANIFEST_PATH = Join-Path $runtimeRoot "release\models\manifests\rtmdet-m-coco-phase1-v1.json"
$env:MAVI_PIPELINE_PROFILE_PATH = Join-Path $runtimeRoot "release\config\pipelines\phase1-detection-tracking-v1.json"
$env:MAVI_RUNTIME_PROFILE_PATH = Join-Path $runtimeRoot "release\runtime\mmdetection-phase1-v1\runtime.json"
$env:MAVI_QUALIFICATION_RECORD_PATH = Join-Path $runtimeRoot "release\models\qualifications\rtmdet-m-coco-phase1-v1.json"
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head

Push-Location $RepositoryRoot
try {
    Write-Host "Starting MAVI Vision Worker..." -ForegroundColor Cyan
    Write-Host "  Runtime : $runtimeRoot"
    Write-Host "  Source  : $head"
    Write-Host "  API     : $ApiBaseUrl"
    Write-Host "  Worker  : $WorkerId"
    Write-Host "  Device  : $DevicePolicy"
    & $python -m mavi_vision.worker.main
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
