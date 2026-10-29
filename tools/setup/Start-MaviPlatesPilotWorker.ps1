[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    # Required unless -VerifyOnly (which never contacts the platform).
    [string]$ApiBaseUrl,
    [string]$WorkerId = "plates-pilot-01",
    # The plates-onnx-v1 environment created by tools\setup\Install-MaviPlatesPilotRuntime.ps1.
    [Parameter(Mandatory = $true)][string]$Python,
    # The model store the pilot packs were staged into.
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    # ADR-008 for this role (PoC S3; Issue #229 GPU-first where the runtime supports it): Auto resolves CPU with the
    # reason recorded, because plates-onnx-v1 runs on CPU only; explicit CUDA fails closed. The Development pilot
    # default stays CPU.
    [ValidateSet("cpu", "cuda", "auto")][string]$DevicePolicy = "cpu",
    # Write the role's device-resolution record (mavi-device-resolution-v1, role "plates") here once every launch check
    # has passed; the PoC System page discloses it beside the Vision worker's.
    [string]$DeviceReportPath,
    # Compose the role and load its Model Packs, report READY and exit without leasing (the installer's readiness check).
    [switch]$VerifyOnly
)

# The plates role on the Development role binding src\vision\config\components\development-plates-onnx-pilot-v1.json
# (PD5 PP-OCRv5 mobile det + OC1-S fast-plate-ocr, plan D4) and its Development-only plate profile: the Issue #225
# pilot, and the poc-single-host plates role (PoC S3, ADR-020). Never Production mode. The worker re-resolves
# everything (binding, family, lock bytes, Model Pack hashes, running environment) and leases only when READY. The
# platform runs with the matching configuration (the PoC machine configuration writes it; Development uses
# process-scope overrides; Production refuses the profile):
#   Plates__Enabled=true
#   Plates__ComponentBindingPath=<overlay>\src\vision\config\components\development-plates-onnx-pilot-v1.json
#   Plates__PipelineProfilePath=<overlay>\src\vision\config\plates\development-plates-onnx-pilot-v1.json

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
# A repository checkout (git) or an installed application overlay (its verified manifest).
$head = (Resolve-MaviApplicationRevision -Root $RepositoryRoot).Revision

$componentBindingPath = Join-Path $RepositoryRoot "src\vision\config\components\development-plates-onnx-pilot-v1.json"
$pipelineProfilePath = Join-Path $RepositoryRoot "src\vision\config\plates\development-plates-onnx-pilot-v1.json"
$modelRootPath = [IO.Path]::GetFullPath($ModelRoot)
if ([string]::IsNullOrWhiteSpace($ApiBaseUrl)) {
    if (-not $VerifyOnly) { throw "-ApiBaseUrl is required to start the plates worker." }
    $ApiBaseUrl = "http://127.0.0.1:1"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "The plates-onnx-v1 interpreter '$Python' does not exist (Install-MaviPlatesPilotRuntime.ps1)." }
if (-not (Test-Path -LiteralPath $modelRootPath -PathType Container)) { throw "The plates model store '$modelRootPath' does not exist." }

# Fails closed for explicit CUDA before anything is started or recorded.
$device = Resolve-MaviPlatesDevicePolicy -DevicePolicy $DevicePolicy -ComponentBindingPath $componentBindingPath
if ($DevicePolicy -eq "auto") { Write-Host "Plates Auto selected CPU: $($device.DeviceResolutionReason)" -ForegroundColor Yellow }

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_ROLE_ID = "plates"
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_DEVICE_POLICY = [string]$device.ResolvedDevicePolicy
$env:MAVI_VERIFY_ONLY = if ($VerifyOnly) { "true" } else { "false" }
$env:MAVI_COMPONENT_BINDING_PATH = $componentBindingPath
$env:MAVI_PIPELINE_PROFILE_PATH = $pipelineProfilePath
$env:MAVI_DEPLOYMENT_PROFILE_POLICY_PATH = Join-Path $RepositoryRoot "config\acceptance\phase1-deployment-profiles-v1.json"
$env:MAVI_OVERLAY_ROOT = $RepositoryRoot
$env:MAVI_MODEL_ROOT = $modelRootPath
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head
$env:PYTHONPATH = Join-Path $RepositoryRoot "src\vision"
Remove-Item Env:MAVI_RUNTIME_PACK_MANIFEST_PATH -ErrorAction SilentlyContinue

# The device record. A verify-only run writes it after the worker composed READY; a real start writes it once the
# launcher's own checks have passed, just before the worker composes, and a worker that then refuses exits non-zero,
# which its starter reports (the record never stands for a running worker alone).
function Write-MaviPlatesDeviceReport {
    if (-not $DeviceReportPath) { return }
    Write-MaviJson -Path $DeviceReportPath -Depth 6 -Value ([ordered]@{
        schemaVersion = "mavi-device-resolution-v1"
        role = "plates"
        requestedDevicePolicy = $device.RequestedDevicePolicy
        resolvedDevicePolicy = $device.ResolvedDevicePolicy
        deviceResolutionReason = $device.DeviceResolutionReason
        runtimePackFamilyId = $device.RuntimePackFamilyId
        runtimePackId = $device.RuntimePackId
        runtimeVariant = $device.RuntimeVariant
        modelPacks = @($device.ModelPacks)
        applicationRevision = $head
        verifyOnly = [bool]$VerifyOnly
        resolvedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
    })
}

Write-Host "Starting MAVI plates worker (Development-grade, unverified Model Packs; never Production)" -ForegroundColor Yellow
Write-Host "  Application : $head"
Write-Host "  Device      : requested=$DevicePolicy resolved=$($device.ResolvedDevicePolicy) reason=$($device.DeviceResolutionReason)"
Write-Host "  Binding     : $env:MAVI_COMPONENT_BINDING_PATH"
Write-Host "  Profile     : $env:MAVI_PIPELINE_PROFILE_PATH"
Write-Host "  Model store : $env:MAVI_MODEL_ROOT"
if (-not $VerifyOnly) { Write-MaviPlatesDeviceReport }
& $Python -m mavi_vision.plates.main
$exitCode = $LASTEXITCODE
if ($VerifyOnly -and $exitCode -eq 0) {
    Write-MaviPlatesDeviceReport
    Write-Host "MAVI plates composition verified (READY)." -ForegroundColor Green
}
exit $exitCode
