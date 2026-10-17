[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [string]$WorkerId = "plates-pilot-01",
    # The plates-onnx-v1 environment created by tools\setup\Install-MaviPlatesPilotRuntime.ps1.
    [Parameter(Mandatory = $true)][string]$Python,
    # The model store the pilot packs were staged into.
    [Parameter(Mandatory = $true)][string]$ModelRoot
)

# Issue #225 Development ANPR pilot: the plates role on the Development role binding
# src\vision\config\components\development-plates-onnx-pilot-v1.json and its Development-only plate profile. Always
# Development mode, CPU only. The worker re-resolves everything (binding, family, lock bytes, Model Pack hashes,
# running environment) and leases only when READY. The platform must be started with the matching process-scope
# overrides (Development environment only; Production refuses the profile):
#   Plates__Enabled=true
#   Plates__ComponentBindingPath=<repo>\src\vision\config\components\development-plates-onnx-pilot-v1.json
#   Plates__PipelineProfilePath=<repo>\src\vision\config\plates\development-plates-onnx-pilot-v1.json

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$head = (& git -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Unable to determine repository HEAD." }

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_ROLE_ID = "plates"
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_DEVICE_POLICY = "cpu"
$env:MAVI_COMPONENT_BINDING_PATH = Join-Path $RepositoryRoot "src\vision\config\components\development-plates-onnx-pilot-v1.json"
$env:MAVI_PIPELINE_PROFILE_PATH = Join-Path $RepositoryRoot "src\vision\config\plates\development-plates-onnx-pilot-v1.json"
$env:MAVI_DEPLOYMENT_PROFILE_POLICY_PATH = Join-Path $RepositoryRoot "config\acceptance\phase1-deployment-profiles-v1.json"
$env:MAVI_OVERLAY_ROOT = $RepositoryRoot
$env:MAVI_MODEL_ROOT = [IO.Path]::GetFullPath($ModelRoot)
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head
$env:PYTHONPATH = Join-Path $RepositoryRoot "src\vision"
Remove-Item Env:MAVI_RUNTIME_PACK_MANIFEST_PATH -ErrorAction SilentlyContinue

Write-Host "Starting MAVI plates worker (Development pilot, CPU, unverified Model Packs; never Production)" -ForegroundColor Yellow
Write-Host "  Application : $head"
Write-Host "  Binding     : $env:MAVI_COMPONENT_BINDING_PATH"
Write-Host "  Profile     : $env:MAVI_PIPELINE_PROFILE_PATH"
Write-Host "  Model store : $env:MAVI_MODEL_ROOT"
& $Python -m mavi_vision.plates.main
exit $LASTEXITCODE
