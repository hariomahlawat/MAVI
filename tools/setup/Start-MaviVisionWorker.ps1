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

# Every fail-closed refusal below carries a stable code as well as its message.
# Explicit CUDA never falls back, so a refusal is the entire outcome, and an
# operator runbook, a support comparison between two hosts and the C7 failure
# matrix all need something to key on that does not change when someone rewords
# a sentence. The message stays: a code alone does not say which file to look at.
#
# The codes are a closed contract shared with
# src/vision/mavi_vision/runtime/launch_failures.py, and a test requires the two
# to agree exactly, so a code cannot be added on one side alone.
function Stop-MaviLaunch {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Code,
        [Parameter(Mandatory = $true, Position = 1)][string]$Message
    )
    throw "mavi_launch_failed:${Code}: $Message"
}

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { Stop-MaviLaunch launch_git_unavailable "git.exe is required to identify the application revision." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { Stop-MaviLaunch launch_repository_head_unknown "Unable to determine repository HEAD." }

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

$resolvedDevicePolicy = $DevicePolicy
# Reason codes are a closed contract shared with
# src/vision/mavi_vision/runtime/provenance.py; the worker rejects any code it
# does not recognise, so every literal below must exist in that vocabulary.
$deviceResolutionReason = $null
if ($DevicePolicy -eq "auto") {
    # The decision itself lives in Mavi.VisionRuntime.Common.psm1 so it can be
    # called, and therefore tested, outside this script.
    $cudaResolution = Resolve-MaviVisionCudaAvailability -Root $runtimeCudaRoot -ComponentRequirementsPath (Join-Path $RepositoryRoot "src\vision\config\components\mmdetection-phase1-v1.json") -DeviceIndex $DeviceIndex
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
    $deviceResolutionReason = "explicit_cuda"
}
else {
    $runtimeRoot = $runtimeCpuRoot
    $deviceResolutionReason = "explicit_cpu"
}

$runtimeRoot = [IO.Path]::GetFullPath($runtimeRoot.Trim().Trim('"'))
$runtimeStatePath = Join-Path $runtimeRoot "runtime-install.json"
$runtimeManifestPath = Join-Path $runtimeRoot "runtime-pack-manifest.json"
if (-not (Test-Path -LiteralPath $runtimeStatePath -PathType Leaf) -or -not (Test-Path -LiteralPath $runtimeManifestPath -PathType Leaf)) {
    Stop-MaviLaunch launch_runtime_pack_not_installed "MAVI Vision Runtime Pack for requested device policy '$DevicePolicy' is not installed at '$runtimeRoot'."
}
$runtimeState = Get-Content -LiteralPath $runtimeStatePath -Raw | ConvertFrom-Json
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionRuntimePackManifest -Manifest $runtimeManifest)
[void](Assert-MaviVisionRuntimeInstalledStatePreflight -RuntimeRoot $runtimeRoot -InstalledState $runtimeState -Manifest $runtimeManifest -RuntimePackManifestPath $runtimeManifestPath)
if ([string]$runtimeState.schemaVersion -ne "mavi-vision-runtime-install-v2") { Stop-MaviLaunch launch_runtime_state_schema_unsupported "Vision runtime installed state schema is unsupported; reinstall the v2 Runtime Pack." }
if ((Get-Sha256 $runtimeManifestPath) -ne ([string]$runtimeState.runtimePackManifestSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_manifest_fingerprint_mismatch "Installed Vision Runtime Pack manifest fingerprint does not match runtime-install.json." }
$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-MaviLaunch launch_runtime_interpreter_missing "Vision Runtime Pack interpreter is missing: $python" }
$identityJson = (& $python -c "import json,platform,sys; print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),'implementation':platform.python_implementation(),'build':list(platform.python_build()),'compiler':platform.python_compiler()},sort_keys=True))" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityJson)) { Stop-MaviLaunch launch_runtime_python_identity_unverifiable "Unable to verify live Vision Runtime Pack Python identity: $identityJson" }
try { $livePythonIdentity = $identityJson | ConvertFrom-Json } catch { Stop-MaviLaunch launch_runtime_python_identity_malformed "Live Vision Runtime Pack Python identity probe returned malformed data." }
if (-not $runtimeState.PSObject.Properties["pythonIdentity"] -or -not (Test-MaviVisionPythonIdentityEqual -Left $runtimeState.pythonIdentity -Right $livePythonIdentity)) { Stop-MaviLaunch launch_runtime_python_identity_state_mismatch "Live Vision Runtime Pack Python identity does not match runtime-install.json; reinstall the qualified Runtime Pack." }
if ([string]$livePythonIdentity.version -ne [string]$runtimeManifest.pythonVersion -or [string]$livePythonIdentity.implementation -ne "CPython") { Stop-MaviLaunch launch_runtime_python_identity_manifest_mismatch "Live Vision Runtime Pack Python identity does not match the Runtime Pack manifest." }
[void](Assert-MaviVisionInstalledRuntimeClosure -RuntimeRoot $runtimeRoot -Manifest $runtimeManifest -PythonPath $python)

# Model Pack: do not trust installation-time state alone. Re-hash every declared
# model artifact at worker startup and reject missing, changed or undeclared files.
$modelRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($modelRoot)) { $modelRoot = "C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1" }
$modelRoot = [IO.Path]::GetFullPath($modelRoot.Trim().Trim('"'))
$modelStatePath = Join-Path $modelRoot "model-install.json"
$modelPackManifestPath = Join-Path $modelRoot "model-pack-manifest.json"
if (-not (Test-Path -LiteralPath $modelStatePath -PathType Leaf) -or -not (Test-Path -LiteralPath $modelPackManifestPath -PathType Leaf)) { Stop-MaviLaunch launch_model_pack_not_installed "MAVI Vision Model Pack is not installed. Install the qualified rtmdet-m-coco-phase1 Model Pack first." }
$modelState = Get-Content -LiteralPath $modelStatePath -Raw | ConvertFrom-Json
$modelPackManifest = Get-Content -LiteralPath $modelPackManifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionModelPackManifest -Manifest $modelPackManifest)
if ([string]$modelState.schemaVersion -ne "mavi-vision-model-install-v1") { Stop-MaviLaunch launch_model_state_schema_unsupported "Vision model installed state schema is unsupported; reinstall the Model Pack." }
if ((Get-Sha256 $modelPackManifestPath) -ne ([string]$modelState.modelPackManifestSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_model_manifest_fingerprint_mismatch "Installed Vision Model Pack manifest fingerprint does not match model-install.json." }
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
foreach ($path in @($modelManifestPath,$qualificationPath,$pipelinePath,$runtimeProfilePath,$componentRequirementsPath,$runtimeLockPath,$runtimeRequirementsPath)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-MaviLaunch launch_overlay_file_missing "Required Vision application overlay file is missing: $path" } }
$modelSourceManifest = Get-Content -LiteralPath $modelManifestPath -Raw | ConvertFrom-Json
$qualification = Get-Content -LiteralPath $qualificationPath -Raw | ConvertFrom-Json
$components = Get-Content -LiteralPath $componentRequirementsPath -Raw | ConvertFrom-Json
if ([string]$components.schemaVersion -ne "mavi-vision-component-requirements-v1") { Stop-MaviLaunch launch_component_schema_unsupported "Unsupported Vision component-requirements schema '$($components.schemaVersion)'." }
if ([string]$components.runtimeProfileId -ne [string]$qualification.runtimeProfileId) { Stop-MaviLaunch launch_component_runtime_profile_mismatch "Vision component requirements target the wrong runtime profile." }
$runtimeRequirementProperty = $components.runtimePacks.PSObject.Properties[$runtimeVariant]
$runtimeRequirement = if ($runtimeRequirementProperty) { $runtimeRequirementProperty.Value } else { $null }
$modelRequirement = $components.modelPack
if (-not $runtimeRequirement -or -not $modelRequirement) { Stop-MaviLaunch launch_component_pack_requirement_missing "Vision component requirements do not declare the required '$runtimeVariant' Runtime Pack and Model Pack." }
if ((Get-Sha256 $modelManifestPath) -ne ([string]$qualification.modelManifestSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_model_manifest_qualification_mismatch "Vision application model-manifest fingerprint does not match qualification metadata." }
if ((Get-Sha256 $pipelinePath) -ne ([string]$qualification.pipelineProfileSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_pipeline_qualification_mismatch "Vision application pipeline fingerprint does not match qualification metadata." }
if ((Get-Sha256 $runtimeProfilePath) -ne ([string]$qualification.runtimeProfileSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_profile_qualification_mismatch "Vision application runtime-profile fingerprint does not match qualification metadata." }
if ((Get-Sha256 $runtimeLockPath) -ne ([string]$runtimeRequirement.thirdPartyLockSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_lock_binding_stale "Vision application Runtime Pack lock binding is stale." }
if ((Get-Sha256 $runtimeRequirementsPath) -ne ([string]$runtimeRequirement.runtimeRequirementsSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_requirements_binding_stale "Vision application runtime-requirements binding is stale." }
if ([string]$runtimeRequirement.nativeAbi -ne [string]$runtimeManifest.nativeAbi) { Stop-MaviLaunch launch_runtime_native_abi_binding_stale "Vision application Runtime Pack native ABI binding is stale." }
if ([string]$modelSourceManifest.modelId -ne [string]$modelRequirement.modelId -or [string]$modelSourceManifest.checkpoint.sha256 -ne [string]$modelRequirement.checkpointSha256 -or [string]$modelSourceManifest.resolvedConfig.sha256 -ne [string]$modelRequirement.resolvedConfigSha256) { Stop-MaviLaunch launch_model_pack_binding_stale "Vision application Model Pack binding is stale." }
if ($resolvedDevicePolicy -eq "cuda" -and $runtimeVariant -ne "windows-x86_64-cuda") { Stop-MaviLaunch launch_cuda_policy_requires_cuda_pack "Resolved CUDA device policy requires the Windows CUDA Runtime Pack." }
if ($resolvedDevicePolicy -eq "cpu" -and $runtimeVariant -ne "windows-x86_64-cpu") { Stop-MaviLaunch launch_cpu_policy_requires_cpu_pack "Resolved CPU device policy requires the Windows CPU Runtime Pack." }
[void](Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId ([string]$runtimeRequirement.runtimePackId) -RequiredThirdPartyLockSha256 ([string]$runtimeRequirement.thirdPartyLockSha256) -RequiredRuntimeRequirementsSha256 ([string]$runtimeRequirement.runtimeRequirementsSha256) -ModelState $modelState -ModelManifest $modelPackManifest -RequiredModelPackId ([string]$modelRequirement.modelPackId) -RequiredModelId ([string]$modelRequirement.modelId) -RequiredCheckpointSha256 ([string]$modelRequirement.checkpointSha256) -RequiredResolvedConfigSha256 ([string]$modelRequirement.resolvedConfigSha256))

$env:MAVI_API_BASE_URL=$ApiBaseUrl;$env:MAVI_WORKER_ID=$WorkerId;$env:MAVI_MEDIA_ROOT=$MediaRoot;$env:MAVI_DEVICE_POLICY=$resolvedDevicePolicy;$env:MAVI_DEVICE_RESOLUTION_REASON=$deviceResolutionReason;$env:MAVI_DEVICE_INDEX=[string]$DeviceIndex;$env:MAVI_PRODUCTION_MODE="false";$env:MAVI_MODEL_ROOT=$modelRoot;$env:MAVI_MODEL_MANIFEST_PATH=$modelManifestPath;$env:MAVI_PIPELINE_PROFILE_PATH=$pipelinePath;$env:MAVI_RUNTIME_PROFILE_PATH=$runtimeProfilePath;$env:MAVI_QUALIFICATION_RECORD_PATH=$qualificationPath;$env:MAVI_BUILD_ID="development";$env:MAVI_COMMIT_SHA=$head
$visionSourceRoot = Join-Path $RepositoryRoot "src\vision"
if (-not (Test-Path -LiteralPath (Join-Path $visionSourceRoot "mavi_vision") -PathType Container)) { Stop-MaviLaunch launch_vision_source_tree_missing "MAVI vision source tree is missing: $visionSourceRoot" }
$existingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH","Process")
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($existingPythonPath)) { $visionSourceRoot } else { $visionSourceRoot + [IO.Path]::PathSeparator + $existingPythonPath }
$sourceProbe = (& $python -c "import pathlib, mavi_vision; print(pathlib.Path(mavi_vision.__file__).resolve())" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceProbe) { Stop-MaviLaunch launch_vision_source_overlay_unverifiable "Unable to verify MAVI vision development source overlay: $sourceProbe" }
$expectedSourcePrefix = [IO.Path]::GetFullPath($visionSourceRoot).TrimEnd("\") + "\"
$resolvedSource = [IO.Path]::GetFullPath($sourceProbe)
if (-not $resolvedSource.StartsWith($expectedSourcePrefix,[StringComparison]::OrdinalIgnoreCase)) { Stop-MaviLaunch launch_vision_source_overlay_foreign "Vision worker resolved MAVI source from '$resolvedSource' instead of repository '$visionSourceRoot'." }

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
