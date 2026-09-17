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
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw "git.exe is required to identify the application revision." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Unable to determine repository HEAD." }

# Reusable third-party Runtime Pack.
$runtimeRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($runtimeRoot)) { $runtimeRoot = "C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu" }
$runtimeRoot = [IO.Path]::GetFullPath($runtimeRoot.Trim().Trim('"'))
$runtimeStatePath = Join-Path $runtimeRoot "runtime-install.json"
$runtimeManifestPath = Join-Path $runtimeRoot "runtime-pack-manifest.json"
if (-not (Test-Path -LiteralPath $runtimeStatePath -PathType Leaf) -or -not (Test-Path -LiteralPath $runtimeManifestPath -PathType Leaf)) {
    throw "MAVI Vision Runtime Pack is not installed. Install the qualified windows-x86_64-cpu Runtime Pack first."
}
$runtimeState = Get-Content -LiteralPath $runtimeStatePath -Raw | ConvertFrom-Json
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionRuntimePackManifest -Manifest $runtimeManifest)
if ([string]$runtimeState.schemaVersion -ne "mavi-vision-runtime-install-v2") { throw "Vision runtime installed state schema is unsupported; reinstall the v2 Runtime Pack." }
if ((Get-Sha256 $runtimeManifestPath) -ne ([string]$runtimeState.runtimePackManifestSha256).ToLowerInvariant()) { throw "Installed Vision Runtime Pack manifest fingerprint does not match runtime-install.json." }
$python = Join-Path $runtimeRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Vision Runtime Pack interpreter is missing: $python" }

# Independently reusable Model Pack.
$modelRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", "Machine")
if ([string]::IsNullOrWhiteSpace($modelRoot)) { $modelRoot = "C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1" }
$modelRoot = [IO.Path]::GetFullPath($modelRoot.Trim().Trim('"'))
$modelStatePath = Join-Path $modelRoot "model-install.json"
$modelPackManifestPath = Join-Path $modelRoot "model-pack-manifest.json"
if (-not (Test-Path -LiteralPath $modelStatePath -PathType Leaf) -or -not (Test-Path -LiteralPath $modelPackManifestPath -PathType Leaf)) {
    throw "MAVI Vision Model Pack is not installed. Install the qualified rtmdet-m-coco-phase1 Model Pack first."
}
$modelState = Get-Content -LiteralPath $modelStatePath -Raw | ConvertFrom-Json
$modelPackManifest = Get-Content -LiteralPath $modelPackManifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionModelPackManifest -Manifest $modelPackManifest)
if ([string]$modelState.schemaVersion -ne "mavi-vision-model-install-v1") { throw "Vision model installed state schema is unsupported; reinstall the Model Pack." }
if ((Get-Sha256 $modelPackManifestPath) -ne ([string]$modelState.modelPackManifestSha256).ToLowerInvariant()) { throw "Installed Vision Model Pack manifest fingerprint does not match model-install.json." }

# Application/Release Overlay requirements are authoritative for the current
# checkout. Repository HEAD is provenance only; compatibility is component-based.
$modelManifestPath = Join-Path $RepositoryRoot "models\manifests\rtmdet-m-coco-phase1-v1.json"
$qualificationPath = Join-Path $RepositoryRoot "models\qualifications\rtmdet-m-coco-phase1-v1.json"
$pipelinePath = Join-Path $RepositoryRoot "src\vision\config\pipelines\phase1-detection-tracking-v1.json"
$runtimeProfilePath = Join-Path $RepositoryRoot "src\vision\runtime\mmdetection-phase1-v1\runtime.json"
$componentRequirementsPath = Join-Path $RepositoryRoot "src\vision\runtime\mmdetection-phase1-v1\components.json"
$runtimeLockPath = Join-Path $RepositoryRoot "src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cpu.lock"
$runtimeRequirementsPath = Join-Path $RepositoryRoot "src\vision\runtime\mmdetection-phase1-v1\windows-x86_64-cpu.requirements.txt"
foreach ($path in @($modelManifestPath, $qualificationPath, $pipelinePath, $runtimeProfilePath, $componentRequirementsPath, $runtimeLockPath, $runtimeRequirementsPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required Vision application overlay file is missing: $path" }
}
$modelSourceManifest = Get-Content -LiteralPath $modelManifestPath -Raw | ConvertFrom-Json
$qualification = Get-Content -LiteralPath $qualificationPath -Raw | ConvertFrom-Json
$components = Get-Content -LiteralPath $componentRequirementsPath -Raw | ConvertFrom-Json
if ([string]$components.schemaVersion -ne "mavi-vision-component-requirements-v1") { throw "Unsupported Vision component-requirements schema '$($components.schemaVersion)'." }
if ([string]$components.runtimeProfileId -ne [string]$qualification.runtimeProfileId) { throw "Vision component requirements target the wrong runtime profile." }
$runtimeRequirement = $components.runtimePacks."windows-x86_64-cpu"
$modelRequirement = $components.modelPack
if (-not $runtimeRequirement -or -not $modelRequirement) { throw "Vision component requirements do not declare the required Windows CPU Runtime Pack and Model Pack." }

if ((Get-Sha256 $modelManifestPath) -ne ([string]$qualification.modelManifestSha256).ToLowerInvariant()) { throw "Vision application model-manifest fingerprint does not match qualification metadata." }
if ((Get-Sha256 $pipelinePath) -ne ([string]$qualification.pipelineProfileSha256).ToLowerInvariant()) { throw "Vision application pipeline fingerprint does not match qualification metadata." }
if ((Get-Sha256 $runtimeProfilePath) -ne ([string]$qualification.runtimeProfileSha256).ToLowerInvariant()) { throw "Vision application runtime-profile fingerprint does not match qualification metadata." }
if ((Get-Sha256 $runtimeLockPath) -ne ([string]$runtimeRequirement.thirdPartyLockSha256).ToLowerInvariant()) { throw "Vision application Runtime Pack lock binding is stale." }
if ((Get-Sha256 $runtimeRequirementsPath) -ne ([string]$runtimeRequirement.runtimeRequirementsSha256).ToLowerInvariant()) { throw "Vision application runtime-requirements binding is stale." }
if ([string]$runtimeRequirement.nativeAbi -ne [string]$runtimeManifest.nativeAbi) { throw "Vision application Runtime Pack native ABI binding is stale." }
if ([string]$modelSourceManifest.modelId -ne [string]$modelRequirement.modelId -or [string]$modelSourceManifest.checkpoint.sha256 -ne [string]$modelRequirement.checkpointSha256 -or [string]$modelSourceManifest.resolvedConfig.sha256 -ne [string]$modelRequirement.resolvedConfigSha256) { throw "Vision application Model Pack binding is stale." }

[void](Assert-MaviVisionWorkerComponentCompatibility `
    -RuntimeState $runtimeState `
    -RuntimeManifest $runtimeManifest `
    -RequiredRuntimePackId ([string]$runtimeRequirement.runtimePackId) `
    -RequiredThirdPartyLockSha256 ([string]$runtimeRequirement.thirdPartyLockSha256) `
    -RequiredRuntimeRequirementsSha256 ([string]$runtimeRequirement.runtimeRequirementsSha256) `
    -ModelState $modelState `
    -ModelManifest $modelPackManifest `
    -RequiredModelPackId ([string]$modelRequirement.modelPackId) `
    -RequiredModelId ([string]$modelRequirement.modelId) `
    -RequiredCheckpointSha256 ([string]$modelRequirement.checkpointSha256) `
    -RequiredResolvedConfigSha256 ([string]$modelRequirement.resolvedConfigSha256))

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_MEDIA_ROOT = $MediaRoot
$env:MAVI_DEVICE_POLICY = $DevicePolicy
$env:MAVI_DEVICE_INDEX = [string]$DeviceIndex
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_MODEL_ROOT = $modelRoot
$env:MAVI_MODEL_MANIFEST_PATH = $modelManifestPath
$env:MAVI_PIPELINE_PROFILE_PATH = $pipelinePath
$env:MAVI_RUNTIME_PROFILE_PATH = $runtimeProfilePath
$env:MAVI_QUALIFICATION_RECORD_PATH = $qualificationPath
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head

# Application overlay: current first-party Python source is supplied by the
# repository while the stable third-party Runtime Pack remains untouched.
$visionSourceRoot = Join-Path $RepositoryRoot "src\vision"
if (-not (Test-Path -LiteralPath (Join-Path $visionSourceRoot "mavi_vision") -PathType Container)) { throw "MAVI vision source tree is missing: $visionSourceRoot" }
$existingPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
$env:PYTHONPATH = if ([string]::IsNullOrWhiteSpace($existingPythonPath)) { $visionSourceRoot } else { $visionSourceRoot + [IO.Path]::PathSeparator + $existingPythonPath }

$sourceProbe = (& $python -c "import pathlib, mavi_vision; print(pathlib.Path(mavi_vision.__file__).resolve())" 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $sourceProbe) { throw "Unable to verify MAVI vision development source overlay: $sourceProbe" }
$expectedSourcePrefix = [IO.Path]::GetFullPath($visionSourceRoot).TrimEnd("\") + "\"
$resolvedSource = [IO.Path]::GetFullPath($sourceProbe)
if (-not $resolvedSource.StartsWith($expectedSourcePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Vision worker resolved MAVI source from '$resolvedSource' instead of repository '$visionSourceRoot'." }

Push-Location $RepositoryRoot
try {
    Write-Host "Starting MAVI Vision Worker..." -ForegroundColor Cyan
    Write-Host "  Runtime Pack : $($runtimeManifest.runtimePackId)"
    Write-Host "  Model Pack   : $($modelPackManifest.modelPackId)"
    Write-Host "  Application  : $head"
    Write-Host "  API          : $ApiBaseUrl"
    Write-Host "  Worker       : $WorkerId"
    Write-Host "  Device       : $DevicePolicy"
    & $python -m mavi_vision.worker.main
    exit $LASTEXITCODE
}
finally { Pop-Location }
