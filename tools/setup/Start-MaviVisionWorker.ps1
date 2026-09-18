[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$ApiBaseUrl = "http://localhost:62153",
    [string]$WorkerId = "dev-worker-01",
    [string]$MediaRoot = "C:\ProgramData\MAVI\Development\Data",
    [ValidateSet("cpu","cuda","auto")][string]$DevicePolicy = "auto",
    [int]$DeviceIndex = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Integrity.psm1") -Force
$env:CUDA_DEVICE_ORDER = "PCI_BUS_ID"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw "git.exe is required to identify the application revision." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Unable to determine repository HEAD." }

# Runtime Binary Pack: choose the exact interpreter/runtime environment before
# the Python worker starts. Auto selection belongs here because CPU and CUDA are
# separate immutable Runtime Packs/venvs and cannot be safely swapped in-process.
$runtimeBase = "C:\ProgramData\MAVI\Development\VisionRuntime"
$runtimeCpuRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_RUNTIME_WINDOWS_CPU_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($runtimeCpuRoot)) {
    $legacyRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", "Machine")
    $runtimeCpuRoot = if ([string]::IsNullOrWhiteSpace($legacyRoot)) {
        Join-Path $runtimeBase "windows-x86_64-cpu"
    } else { $legacyRoot }
}
$runtimeCudaRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_RUNTIME_WINDOWS_CUDA_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($runtimeCudaRoot)) {
    $runtimeCudaRoot = Join-Path $runtimeBase "windows-x86_64-cuda"
}

function Test-CudaRuntimeUsable {
    param([Parameter(Mandatory = $true)][string]$Root)

    $result = [ordered]@{
        Usable = $false
        Reason = "cuda_pack_absent"
        RuntimeRoot = $Root
    }

    $pythonPath = Join-Path $Root "venv\Scripts\python.exe"
    $manifestPath = Join-Path $Root "runtime-pack-manifest.json"
    $statePath = Join-Path $Root "runtime-install.json"
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        return [pscustomobject]$result
    }

    try {
        $manifestValue = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $stateValue = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        [void](Assert-MaviVisionRuntimeInstalledStatePreflight -RuntimeRoot $Root -InstalledState $stateValue -Manifest $manifestValue -RuntimePackManifestPath $manifestPath)
    }
    catch {
        $result.Reason = "cuda_pack_integrity_failed"
        return [pscustomobject]$result
    }

    if ([string]$manifestValue.platformVariant -ne "windows-x86_64-cuda") {
        $result.Reason = "cuda_pack_variant_mismatch"
        return [pscustomobject]$result
    }

    $componentPath = Join-Path $RepositoryRoot "src\vision\config\components\mmdetection-phase1-v1.json"
    if (-not (Test-Path -LiteralPath $componentPath -PathType Leaf)) {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    try {
        $componentValue = Get-Content -LiteralPath $componentPath -Raw | ConvertFrom-Json
    }
    catch {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    $cudaRequirement = $componentValue.runtimePacks.PSObject.Properties["windows-x86_64-cuda"]
    if (-not $cudaRequirement) {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    if ([string]$cudaRequirement.Value.runtimePackId -ne [string]$manifestValue.runtimePackId) {
        $result.Reason = "cuda_pack_id_mismatch"
        return [pscustomobject]$result
    }

    $nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if (-not $nvidiaSmi) {
        $result.Reason = "cuda_driver_probe_unavailable"
        return [pscustomobject]$result
    }
    try {
        $probe = (& $nvidiaSmi.Source -i $DeviceIndex --query-gpu=index --format=csv,noheader,nounits 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $probe -ne [string]$DeviceIndex) {
            $result.Reason = "cuda_device_unavailable"
            return [pscustomobject]$result
        }
    }
    catch {
        $result.Reason = "cuda_driver_probe_failed"
        return [pscustomobject]$result
    }

    $result.Usable = $true
    $result.Reason = "cuda_selected"
    return [pscustomobject]$result
}

$resolvedDevicePolicy = $DevicePolicy
$deviceResolutionReason = "explicit_$DevicePolicy"
if ($DevicePolicy -eq "auto") {
    $cudaResolution = Test-CudaRuntimeUsable -Root $runtimeCudaRoot
    if ($cudaResolution.Usable) {
        $runtimeRoot = $runtimeCudaRoot
        $resolvedDevicePolicy = "cuda"
        $deviceResolutionReason = [string]$cudaResolution.Reason
    }
    else {
        $runtimeRoot = $runtimeCpuRoot
        $resolvedDevicePolicy = "cpu"
        $deviceResolutionReason = [string]$cudaResolution.Reason
        Write-Host "Development Auto selected CPU: $deviceResolutionReason" -ForegroundColor Yellow
    }
}
elseif ($DevicePolicy -eq "cuda") {
    $runtimeRoot = $runtimeCudaRoot
}
else {
    $runtimeRoot = $runtimeCpuRoot
}

$runtimeRoot = [IO.Path]::GetFullPath($runtimeRoot.Trim().Trim('"'))
$runtimeStatePath = Join-Path $runtimeRoot "runtime-install.json"
$runtimeManifestPath = Join-Path $runtimeRoot "runtime-pack-manifest.json"
if (-not (Test-Path -LiteralPath $runtimeStatePath -PathType Leaf) -or -not (Test-Path -LiteralPath $runtimeManifestPath -PathType Leaf)) {
    throw "MAVI Vision Runtime Pack for requested device policy '$DevicePolicy' is not installed at '$runtimeRoot'."
}
$runtimeState = Get-Content -LiteralPath $runtimeStatePath -Raw | ConvertFrom-Json
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionRuntimePackManifest -Manifest $runtimeManifest)
[void](Assert-MaviVisionRuntimeInstalledStatePreflight -RuntimeRoot $runtimeRoot -InstalledState $runtimeState -Manifest $runtimeManifest -RuntimePackManifestPath $runtimeManifestPath)
if ([string]$runtimeState.schemaVersion -ne "mavi-vision-runtime-install-v2") { throw "Vision runtime installed state schema is unsupported; reinstall the v2 Runtime Pack." }
if ((Get-Sha256 $runtimeManifestPath) -ne ([string]$runtimeState.runtimePackManifestSha256).ToLowerInvariant()) { throw "Installed Vision Runtime Pack manifest fingerprint does not match runtime-install.json." }
$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Vision Runtime Pack interpreter is missing: $python" }
$identityJson = (& $python -c "import json,platform,sys; print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),'implementation':platform.python_implementation(),'build':list(platform.python_build()),'compiler':platform.python_compiler()},sort_keys=True))" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityJson)) { throw "Unable to verify live Vision Runtime Pack Python identity: $identityJson" }
try { $livePythonIdentity = $identityJson | ConvertFrom-Json } catch { throw "Live Vision Runtime Pack Python identity probe returned malformed data." }
if (-not $runtimeState.PSObject.Properties["pythonIdentity"] -or -not (Test-MaviVisionPythonIdentityEqual -Left $runtimeState.pythonIdentity -Right $livePythonIdentity)) { throw "Live Vision Runtime Pack Python identity does not match runtime-install.json; reinstall the qualified Runtime Pack." }
if ([string]$livePythonIdentity.version -ne [string]$runtimeManifest.pythonVersion -or [string]$livePythonIdentity.implementation -ne "CPython") { throw "Live Vision Runtime Pack Python identity does not match the Runtime Pack manifest." }
[void](Assert-MaviVisionInstalledRuntimeClosure -RuntimeRoot $runtimeRoot -Manifest $runtimeManifest -PythonPath $python)

# Model Pack: do not trust installation-time state alone. Re-hash every declared
# model artifact at worker startup and reject missing, changed or undeclared files.
$modelRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($modelRoot)) { $modelRoot = "C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1" }
$modelRoot = [IO.Path]::GetFullPath($modelRoot.Trim().Trim('"'))
$modelStatePath = Join-Path $modelRoot "model-install.json"
$modelPackManifestPath = Join-Path $modelRoot "model-pack-manifest.json"
if (-not (Test-Path -LiteralPath $modelStatePath -PathType Leaf) -or -not (Test-Path -LiteralPath $modelPackManifestPath -PathType Leaf)) { throw "MAVI Vision Model Pack is not installed. Install the qualified rtmdet-m-coco-phase1 Model Pack first." }
$modelState = Get-Content -LiteralPath $modelStatePath -Raw | ConvertFrom-Json
$modelPackManifest = Get-Content -LiteralPath $modelPackManifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionModelPackManifest -Manifest $modelPackManifest)
if ([string]$modelState.schemaVersion -ne "mavi-vision-model-install-v1") { throw "Vision model installed state schema is unsupported; reinstall the Model Pack." }
if ((Get-Sha256 $modelPackManifestPath) -ne ([string]$modelState.modelPackManifestSha256).ToLowerInvariant()) { throw "Installed Vision Model Pack manifest fingerprint does not match model-install.json." }
[void](Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $modelRoot -Manifest $modelPackManifest)

# Application/Release Overlay is authoritative for the current checkout.
$modelManifestPath = Join-Path $RepositoryRoot "models\manifests\rtmdet-m-coco-phase1-v1.json"
$qualificationPath = Join-Path $RepositoryRoot "models\qualifications\rtmdet-m-coco-phase1-v1.json"
$pipelinePath = Join-Path $RepositoryRoot "src\vision\config\pipelines\phase1-detection-tracking-v1.json"
$runtimeProfilePath = Join-Path $RepositoryRoot "src\vision\runtime\mmdetection-phase1-v1\runtime.json"
$componentRequirementsPath = Join-Path $RepositoryRoot "src\vision\config\components\mmdetection-phase1-v1.json"
$runtimeVariant = [string]$runtimeManifest.platformVariant
$runtimeLockPath = Join-Path $RepositoryRoot ("src\vision\runtime\mmdetection-phase1-v1\" + $runtimeVariant + ".lock")
$runtimeRequirementsPath = Join-Path $RepositoryRoot ("src\vision\runtime\mmdetection-phase1-v1\" + $runtimeVariant + ".requirements.txt")
foreach ($path in @($modelManifestPath,$qualificationPath,$pipelinePath,$runtimeProfilePath,$componentRequirementsPath,$runtimeLockPath,$runtimeRequirementsPath)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required Vision application overlay file is missing: $path" } }
$modelSourceManifest = Get-Content -LiteralPath $modelManifestPath -Raw | ConvertFrom-Json
$qualification = Get-Content -LiteralPath $qualificationPath -Raw | ConvertFrom-Json
$components = Get-Content -LiteralPath $componentRequirementsPath -Raw | ConvertFrom-Json
if ([string]$components.schemaVersion -ne "mavi-vision-component-requirements-v1") { throw "Unsupported Vision component-requirements schema '$($components.schemaVersion)'." }
if ([string]$components.runtimeProfileId -ne [string]$qualification.runtimeProfileId) { throw "Vision component requirements target the wrong runtime profile." }
$runtimeRequirementProperty = $components.runtimePacks.PSObject.Properties[$runtimeVariant]
$runtimeRequirement = if ($runtimeRequirementProperty) { $runtimeRequirementProperty.Value } else { $null }
$modelRequirement = $components.modelPack
if (-not $runtimeRequirement -or -not $modelRequirement) { throw "Vision component requirements do not declare the required '$runtimeVariant' Runtime Pack and Model Pack." }
if ((Get-Sha256 $modelManifestPath) -ne ([string]$qualification.modelManifestSha256).ToLowerInvariant()) { throw "Vision application model-manifest fingerprint does not match qualification metadata." }
if ((Get-Sha256 $pipelinePath) -ne ([string]$qualification.pipelineProfileSha256).ToLowerInvariant()) { throw "Vision application pipeline fingerprint does not match qualification metadata." }
if ((Get-Sha256 $runtimeProfilePath) -ne ([string]$qualification.runtimeProfileSha256).ToLowerInvariant()) { throw "Vision application runtime-profile fingerprint does not match qualification metadata." }
if ((Get-Sha256 $runtimeLockPath) -ne ([string]$runtimeRequirement.thirdPartyLockSha256).ToLowerInvariant()) { throw "Vision application Runtime Pack lock binding is stale." }
if ((Get-Sha256 $runtimeRequirementsPath) -ne ([string]$runtimeRequirement.runtimeRequirementsSha256).ToLowerInvariant()) { throw "Vision application runtime-requirements binding is stale." }
if ([string]$runtimeRequirement.nativeAbi -ne [string]$runtimeManifest.nativeAbi) { throw "Vision application Runtime Pack native ABI binding is stale." }
if ([string]$modelSourceManifest.modelId -ne [string]$modelRequirement.modelId -or [string]$modelSourceManifest.checkpoint.sha256 -ne [string]$modelRequirement.checkpointSha256 -or [string]$modelSourceManifest.resolvedConfig.sha256 -ne [string]$modelRequirement.resolvedConfigSha256) { throw "Vision application Model Pack binding is stale." }
if ($resolvedDevicePolicy -eq "cuda" -and $runtimeVariant -ne "windows-x86_64-cuda") { throw "Resolved CUDA device policy requires the Windows CUDA Runtime Pack." }
if ($resolvedDevicePolicy -eq "cpu" -and $runtimeVariant -ne "windows-x86_64-cpu") { throw "Resolved CPU device policy requires the Windows CPU Runtime Pack." }
[void](Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId ([string]$runtimeRequirement.runtimePackId) -RequiredThirdPartyLockSha256 ([string]$runtimeRequirement.thirdPartyLockSha256) -RequiredRuntimeRequirementsSha256 ([string]$runtimeRequirement.runtimeRequirementsSha256) -ModelState $modelState -ModelManifest $modelPackManifest -RequiredModelPackId ([string]$modelRequirement.modelPackId) -RequiredModelId ([string]$modelRequirement.modelId) -RequiredCheckpointSha256 ([string]$modelRequirement.checkpointSha256) -RequiredResolvedConfigSha256 ([string]$modelRequirement.resolvedConfigSha256))

$env:MAVI_API_BASE_URL=$ApiBaseUrl;$env:MAVI_WORKER_ID=$WorkerId;$env:MAVI_MEDIA_ROOT=$MediaRoot;$env:MAVI_DEVICE_POLICY=$resolvedDevicePolicy;$env:MAVI_DEVICE_RESOLUTION_REASON=$deviceResolutionReason;$env:MAVI_DEVICE_INDEX=[string]$DeviceIndex;$env:MAVI_PRODUCTION_MODE="false";$env:MAVI_MODEL_ROOT=$modelRoot;$env:MAVI_MODEL_MANIFEST_PATH=$modelManifestPath;$env:MAVI_PIPELINE_PROFILE_PATH=$pipelinePath;$env:MAVI_RUNTIME_PROFILE_PATH=$runtimeProfilePath;$env:MAVI_QUALIFICATION_RECORD_PATH=$qualificationPath;$env:MAVI_BUILD_ID="development";$env:MAVI_COMMIT_SHA=$head
$visionSourceRoot = Join-Path $RepositoryRoot "src\vision"
if (-not (Test-Path -LiteralPath (Join-Path $visionSourceRoot "mavi_vision") -PathType Container)) { throw "MAVI vision source tree is missing: $visionSourceRoot" }
$existingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH","Process")
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($existingPythonPath)) { $visionSourceRoot } else { $visionSourceRoot + [IO.Path]::PathSeparator + $existingPythonPath }
$sourceProbe = (& $python -c "import pathlib, mavi_vision; print(pathlib.Path(mavi_vision.__file__).resolve())" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceProbe) { throw "Unable to verify MAVI vision development source overlay: $sourceProbe" }
$expectedSourcePrefix = [IO.Path]::GetFullPath($visionSourceRoot).TrimEnd("\") + "\"
$resolvedSource = [IO.Path]::GetFullPath($sourceProbe)
if (-not $resolvedSource.StartsWith($expectedSourcePrefix,[StringComparison]::OrdinalIgnoreCase)) { throw "Vision worker resolved MAVI source from '$resolvedSource' instead of repository '$visionSourceRoot'." }

Push-Location $RepositoryRoot
try {
    Write-Host "Starting MAVI Vision Worker..." -ForegroundColor Cyan
    Write-Host "  Runtime Pack : $($runtimeManifest.runtimePackId)"
    Write-Host "  Model Pack   : $($modelPackManifest.modelPackId)"
    Write-Host "  Application  : $head"
    Write-Host "  API          : $ApiBaseUrl"
    Write-Host "  Worker       : $WorkerId"
    Write-Host "  Device       : requested=$DevicePolicy resolved=$resolvedDevicePolicy reason=$deviceResolutionReason"
    Write-Host "  Variant      : $runtimeVariant"
    & $python -m mavi_vision.worker.main
    exit $LASTEXITCODE
}
finally { Pop-Location }
