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

# The integrity and compatibility assertions live in the shared modules and
# raise English prose of their own. Their messages are the useful diagnostic and
# are kept verbatim, but a refusal that reaches an operator or the C7 failure
# matrix needs a stable code too, so each family of them is given one here.
function Invoke-MaviLaunchStep {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Code,
        [Parameter(Mandatory = $true, Position = 1)][scriptblock]$Step
    )
    try { return & $Step }
    catch { Stop-MaviLaunch $Code $_.Exception.Message }
}

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { Stop-MaviLaunch launch_git_unavailable "git.exe is required to identify the application revision." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { Stop-MaviLaunch launch_repository_head_unknown "Unable to determine repository HEAD." }

# Application/Release Overlay: component binding v2 is the one composition
# source (ADR-014; S2a plan P-9). The launcher reads role `vision` from it, and
# the worker resolves the same binding again, authoritatively, in Python.
$componentBindingPath = Join-Path $RepositoryRoot "src\vision\config\components\phase1-bindings-v2.json"
$pipelinePath = Join-Path $RepositoryRoot "src\vision\config\pipelines\phase1-detection-tracking-v1.json"
$qualificationRoot = Join-Path $RepositoryRoot "models\qualifications"
$modelManifestRoot = Join-Path $RepositoryRoot "models\manifests"

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
    # called, and therefore tested, outside this script. It reads the declared
    # windows-x86_64-cuda entry of the v2 binding; that stays Development only.
    $cudaResolution = Resolve-MaviVisionCudaAvailability -Root ([IO.Path]::GetFullPath($runtimeCudaRoot.Trim().Trim('"'))) -ComponentBindingPath $componentBindingPath -DeviceIndex $DeviceIndex
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
$runtimeState = Invoke-MaviLaunchStep launch_runtime_metadata_unreadable { Get-Content -LiteralPath $runtimeStatePath -Raw | ConvertFrom-Json }
$runtimeManifest = Invoke-MaviLaunchStep launch_runtime_metadata_unreadable { Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json }
[void](Invoke-MaviLaunchStep launch_runtime_pack_manifest_invalid { Assert-MaviVisionRuntimePackManifest -Manifest $runtimeManifest })
[void](Invoke-MaviLaunchStep launch_runtime_pack_preflight_failed { Assert-MaviVisionRuntimeInstalledStatePreflight -RuntimeRoot $runtimeRoot -InstalledState $runtimeState -Manifest $runtimeManifest -RuntimePackManifestPath $runtimeManifestPath })
if ([string]$runtimeState.schemaVersion -ne "mavi-vision-runtime-install-v2") { Stop-MaviLaunch launch_runtime_state_schema_unsupported "Vision runtime installed state schema is unsupported; reinstall the v2 Runtime Pack." }
if ((Get-Sha256 $runtimeManifestPath) -ne ([string]$runtimeState.runtimePackManifestSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_manifest_fingerprint_mismatch "Installed Vision Runtime Pack manifest fingerprint does not match runtime-install.json." }
$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { Stop-MaviLaunch launch_runtime_interpreter_missing "Vision Runtime Pack interpreter is missing: $python" }
$identityJson = (& $python -c "import json,platform,sys; print(json.dumps({'version':'.'.join(map(str,sys.version_info[:3])),'implementation':platform.python_implementation(),'build':list(platform.python_build()),'compiler':platform.python_compiler()},sort_keys=True))" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($identityJson)) { Stop-MaviLaunch launch_runtime_python_identity_unverifiable "Unable to verify live Vision Runtime Pack Python identity: $identityJson" }
try { $livePythonIdentity = $identityJson | ConvertFrom-Json } catch { Stop-MaviLaunch launch_runtime_python_identity_malformed "Live Vision Runtime Pack Python identity probe returned malformed data." }
if (-not $runtimeState.PSObject.Properties["pythonIdentity"] -or -not (Test-MaviVisionPythonIdentityEqual -Left $runtimeState.pythonIdentity -Right $livePythonIdentity)) { Stop-MaviLaunch launch_runtime_python_identity_state_mismatch "Live Vision Runtime Pack Python identity does not match runtime-install.json; reinstall the qualified Runtime Pack." }
if ([string]$livePythonIdentity.version -ne [string]$runtimeManifest.pythonVersion -or [string]$livePythonIdentity.implementation -ne "CPython") { Stop-MaviLaunch launch_runtime_python_identity_manifest_mismatch "Live Vision Runtime Pack Python identity does not match the Runtime Pack manifest." }
[void](Invoke-MaviLaunchStep launch_runtime_closure_failed { Assert-MaviVisionInstalledRuntimeClosure -RuntimeRoot $runtimeRoot -Manifest $runtimeManifest -PythonPath $python })

# Component binding v2: role `vision`, its Runtime Pack family and that
# family's runtime profile (src\vision\runtime\<family>\runtime.json v2).
foreach ($path in @($componentBindingPath,$pipelinePath)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-MaviLaunch launch_overlay_file_missing "Required Vision application overlay file is missing: $path" } }
$componentBinding = Invoke-MaviLaunchStep launch_overlay_metadata_unreadable { Get-Content -LiteralPath $componentBindingPath -Raw | ConvertFrom-Json }
if ((Get-MaviVisionPropertyText -Value $componentBinding -Name "schemaVersion") -ne "mavi-vision-component-binding-v2") { Stop-MaviLaunch launch_component_schema_unsupported "Unsupported Vision component binding schema in '$componentBindingPath'; expected mavi-vision-component-binding-v2." }
$bindingRole = Invoke-MaviLaunchStep launch_component_pack_requirement_missing { Get-MaviVisionBindingRole -Binding $componentBinding -RoleId "vision" }
$runtimeFamilyId = [string]$bindingRole.RuntimePackFamilyId
$runtimeFamilyRoot = Join-Path $RepositoryRoot ("src\vision\runtime\" + $runtimeFamilyId)
$runtimeProfilePath = Join-Path $runtimeFamilyRoot "runtime.json"
$runtimeVariant = [string]$runtimeManifest.platformVariant
$runtimeLockPath = Join-Path $runtimeFamilyRoot ($runtimeVariant + ".lock")
$runtimeRequirementsPath = Join-Path $runtimeFamilyRoot ($runtimeVariant + ".requirements.txt")
foreach ($path in @($runtimeProfilePath,$runtimeLockPath,$runtimeRequirementsPath)) { if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { Stop-MaviLaunch launch_overlay_file_missing "Required Vision application overlay file is missing: $path" } }
$runtimeProfile = Invoke-MaviLaunchStep launch_overlay_metadata_unreadable { Get-Content -LiteralPath $runtimeProfilePath -Raw | ConvertFrom-Json }
if ((Get-MaviVisionPropertyText -Value $runtimeProfile -Name "schemaVersion") -ne "2.0" -or (Get-MaviVisionPropertyText -Value $runtimeProfile -Name "runtimeProfileId") -ne $runtimeFamilyId) { Stop-MaviLaunch launch_component_runtime_profile_mismatch "Vision runtime profile '$runtimeProfilePath' is not the v2 profile of family '$runtimeFamilyId' that role 'vision' is bound to." }

# The variant entry of the binding feeds the unchanged Runtime Pack checks.
$runtimeRequirement = Get-MaviVisionBindingRuntimeRequirement -BindingRole $bindingRole -Variant $runtimeVariant
if ($null -eq $runtimeRequirement) { Stop-MaviLaunch launch_component_pack_requirement_missing "Vision component binding declares no complete '$runtimeVariant' Runtime Pack entry for family '$runtimeFamilyId'." }
if ((Get-Sha256 $runtimeLockPath) -ne ([string]$runtimeRequirement.thirdPartyLockSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_lock_binding_stale "Vision application Runtime Pack lock binding is stale." }
if ((Get-Sha256 $runtimeRequirementsPath) -ne ([string]$runtimeRequirement.runtimeRequirementsSha256).ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_requirements_binding_stale "Vision application runtime-requirements binding is stale." }
if ([string]$runtimeRequirement.nativeAbi -ne [string]$runtimeManifest.nativeAbi) { Stop-MaviLaunch launch_runtime_native_abi_binding_stale "Vision application Runtime Pack native ABI binding is stale." }

# Each capability binding names its qualification record by qualificationId
# (found by scanning models\qualifications, plan P-9). The record must name the
# bound Model Pack, the bound family, this runtime profile, this pipeline and a
# model manifest present in the overlay. The worker re-verifies all of it,
# including the derived modelPackId, which this launcher never computes.
$modelManifestFingerprints = @(Invoke-MaviLaunchStep launch_overlay_metadata_unreadable { Get-ChildItem -LiteralPath $modelManifestRoot -Filter "*.json" -File | ForEach-Object { Get-Sha256 $_.FullName } })
foreach ($capabilityBinding in @($bindingRole.CapabilityBindings)) {
    $qualificationId = [string]$capabilityBinding.QualificationId
    $qualificationMatches = @(Invoke-MaviLaunchStep launch_overlay_metadata_unreadable { Find-MaviVisionOverlayRecords -Directory $qualificationRoot -PropertyName "qualificationId" -Value $qualificationId })
    if ($qualificationMatches.Count -eq 0) { Stop-MaviLaunch launch_overlay_file_missing "No Vision qualification record under '$qualificationRoot' carries qualificationId '$qualificationId'." }
    if ($qualificationMatches.Count -gt 1) { Stop-MaviLaunch launch_overlay_metadata_unreadable "Vision qualification record '$qualificationId' is ambiguous: $($qualificationMatches.Count) overlay records carry it." }
    $qualification = $qualificationMatches[0].Record
    if ((Get-MaviVisionPropertyText -Value $qualification -Name "modelPackId") -ne [string]$capabilityBinding.ModelPackId) { Stop-MaviLaunch launch_model_pack_binding_stale "Vision qualification record '$qualificationId' does not name the Model Pack bound to capability '$($capabilityBinding.CapabilityId)'." }
    if ((Get-MaviVisionPropertyText -Value $qualification -Name "runtimePackFamilyId") -ne $runtimeFamilyId) { Stop-MaviLaunch launch_component_runtime_profile_mismatch "Vision qualification record '$qualificationId' targets another Runtime Pack family than '$runtimeFamilyId'." }
    if ((Get-Sha256 $runtimeProfilePath) -ne (Get-MaviVisionPropertyText -Value $qualification -Name "runtimeProfileSha256").ToLowerInvariant()) { Stop-MaviLaunch launch_runtime_profile_qualification_mismatch "Vision application runtime-profile fingerprint does not match qualification metadata." }
    if ((Get-Sha256 $pipelinePath) -ne (Get-MaviVisionPropertyText -Value (Get-MaviVisionPropertyValue -Value $qualification -Name "policies") -Name "pipelineProfileSha256").ToLowerInvariant()) { Stop-MaviLaunch launch_pipeline_qualification_mismatch "Vision application pipeline fingerprint does not match qualification metadata." }
    if ($modelManifestFingerprints -notcontains (Get-MaviVisionPropertyText -Value $qualification -Name "modelManifestSha256").ToLowerInvariant()) { Stop-MaviLaunch launch_model_manifest_qualification_mismatch "No Vision application model manifest matches the fingerprint recorded by qualification '$qualificationId'." }
}

# Model Pack store (plan P-10): MAVI_VISION_MODEL_ROOT is the store root, one
# self-contained <packDirectory> per pack. Each bound modelPackId must be
# carried by exactly one <store>\*\model-pack-manifest.json, which fixes its
# pack directory. Installation-time state is not trusted alone: every declared
# artefact is re-hashed at startup and undeclared files are refused.
$modelRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($modelRoot)) { $modelRoot = "C:\ProgramData\MAVI\Development\VisionModels" }
$modelRoot = [IO.Path]::GetFullPath($modelRoot.Trim().Trim('"'))
$storeResolution = Invoke-MaviLaunchStep launch_model_metadata_unreadable { Resolve-MaviVisionBoundModelPacks -StoreRoot $modelRoot -CapabilityBindings @($bindingRole.CapabilityBindings) }
if ($storeResolution.LegacyInstallation) { Stop-MaviLaunch launch_model_state_schema_unsupported "Vision Model Pack store root '$modelRoot' is a v1 per-model installation; re-install the Model Pack with Install-MaviVisionModelPack.ps1 into a v2 store root." }
foreach ($bound in @($storeResolution.ModelPacks)) {
    if ($bound.Status -eq "not-installed") { Stop-MaviLaunch launch_model_pack_not_installed "MAVI Vision Model Pack '$($bound.ModelPackId)' bound to capability '$($bound.CapabilityId)' is not installed in '$modelRoot'. Install it with Install-MaviVisionModelPack.ps1 first." }
    if ($bound.Status -eq "ambiguous") { Stop-MaviLaunch launch_model_pack_ambiguous "MAVI Vision Model Pack '$($bound.ModelPackId)' is carried by more than one store directory: $(@($bound.Candidates) -join ', ')." }
    if ($bound.Status -eq "state-missing") { Stop-MaviLaunch launch_model_pack_not_installed "MAVI Vision Model Pack directory '$($bound.PackPath)' has no model-install.json; re-install the Model Pack." }
    if ($bound.Status -eq "state-unsupported") { Stop-MaviLaunch launch_model_state_schema_unsupported "Vision model installed state '$($bound.StatePath)' is not mavi-vision-model-install-v2; remove that directory and re-install the Model Pack." }
    if ($bound.Status -ne "installed") { Stop-MaviLaunch launch_model_metadata_unreadable "Vision Model Pack store lookup returned an unknown status for '$($bound.ModelPackId)'." }
    $boundManifest = $bound.ModelManifest
    [void](Invoke-MaviLaunchStep launch_model_pack_manifest_invalid { Assert-MaviVisionModelPackManifest -Manifest $boundManifest })
    if ((Get-MaviVisionModelPackDirectory -Manifest $boundManifest) -cne [string]$bound.PackDirectory) { Stop-MaviLaunch launch_model_pack_integrity_failed "Vision Model Pack in '$($bound.PackPath)' declares another pack directory; re-install the Model Pack." }
    if ((Get-Sha256 ([string]$bound.ManifestPath)) -ne (Get-MaviVisionPropertyText -Value $bound.ModelState -Name "modelPackManifestSha256").ToLowerInvariant()) { Stop-MaviLaunch launch_model_manifest_fingerprint_mismatch "Installed Vision Model Pack manifest fingerprint does not match model-install.json in '$($bound.PackPath)'." }
    [void](Invoke-MaviLaunchStep launch_model_pack_integrity_failed { Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $modelRoot -Manifest $boundManifest })
}

if ($resolvedDevicePolicy -eq "cuda" -and $runtimeVariant -ne "windows-x86_64-cuda") { Stop-MaviLaunch launch_cuda_policy_requires_cuda_pack "Resolved CUDA device policy requires the Windows CUDA Runtime Pack." }
if ($resolvedDevicePolicy -eq "cpu" -and $runtimeVariant -ne "windows-x86_64-cpu") { Stop-MaviLaunch launch_cpu_policy_requires_cpu_pack "Resolved CPU device policy requires the Windows CPU Runtime Pack." }
[void](Invoke-MaviLaunchStep launch_component_compatibility_failed { Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId ([string]$runtimeRequirement.runtimePackId) -RequiredThirdPartyLockSha256 ([string]$runtimeRequirement.thirdPartyLockSha256) -RequiredRuntimeRequirementsSha256 ([string]$runtimeRequirement.runtimeRequirementsSha256) -RequiredModelPacks @($storeResolution.ModelPacks) })

# Worker composition environment (plan §5.2, P-9). The retired per-path
# variables are removed, not emptied: the worker refuses to start if any is
# present at all. The Development completion-schema override (plan P-16) is the
# operator's to set; this launcher neither sets nor clears it.
$clearedComposition = @(Clear-MaviVisionRetiredCompositionEnvironment)
if ($clearedComposition.Count -gt 0) { Write-Host "Removed retired composition variables from the worker environment: $($clearedComposition -join ', ')" -ForegroundColor Yellow }
$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_MEDIA_ROOT = $MediaRoot
$env:MAVI_DEVICE_POLICY = $resolvedDevicePolicy
$env:MAVI_DEVICE_RESOLUTION_REASON = $deviceResolutionReason
$env:MAVI_DEVICE_INDEX = [string]$DeviceIndex
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_COMPONENT_BINDING_PATH = $componentBindingPath
$env:MAVI_ROLE_ID = "vision"
$env:MAVI_OVERLAY_ROOT = $RepositoryRoot
$env:MAVI_RUNTIME_PACK_MANIFEST_PATH = $runtimeManifestPath
$env:MAVI_MODEL_ROOT = $modelRoot
$env:MAVI_PIPELINE_PROFILE_PATH = $pipelinePath
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head
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
    foreach ($bound in @($storeResolution.ModelPacks)) {
        Write-Host "  Model Pack   : $($bound.ModelPackId) ($($bound.CapabilityId), $($bound.PackDirectory))"
    }
    Write-Host "  Binding      : $componentBindingPath (role vision)"
    Write-Host "  Model store  : $modelRoot"
    Write-Host "  Application  : $head"
    Write-Host "  API          : $ApiBaseUrl"
    Write-Host "  Worker       : $WorkerId"
    Write-Host "  Device       : requested=$DevicePolicy resolved=$resolvedDevicePolicy reason=$deviceResolutionReason"
    Write-Host "  Variant      : $runtimeVariant"
    & $python -m mavi_vision.worker.main
    exit $LASTEXITCODE
}
finally { Pop-Location }
