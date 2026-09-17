[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Script,
        [Parameter(Mandatory = $true)][string]$MessageFragment
    )
    $thrown = $false
    try { & $Script }
    catch {
        $thrown = $true
        if ($_.Exception.Message -notlike "*$MessageFragment*") {
            throw "Expected error containing '$MessageFragment', got '$($_.Exception.Message)'."
        }
    }
    if (-not $thrown) { throw "Expected failure containing '$MessageFragment'." }
}

$runtimeManifest = [pscustomobject]@{
    schemaVersion = "mavi-vision-runtime-pack-v2"
    runtimePackId = ("mavi-runtime-v2-" + ("a" * 64))
    platformVariant = "windows-x86_64-cpu"
    pythonVersion = "3.12.10"
    nativeAbi = "win_amd64-msvc-14.44-sdk-10.0.26100.0"
    thirdPartyLockSha256 = ("b" * 64)
    runtimeRequirementsSha256 = ("c" * 64)
    assembledFromCommit = ("1" * 40)
    artifacts = @()
}
$runtimeState = [pscustomobject]@{
    schemaVersion = "mavi-vision-runtime-install-v2"
    runtimePackId = $runtimeManifest.runtimePackId
    runtimePackManifestSha256 = ("d" * 64)
    thirdPartyLockSha256 = $runtimeManifest.thirdPartyLockSha256
    runtimeRequirementsSha256 = $runtimeManifest.runtimeRequirementsSha256
    platformVariant = $runtimeManifest.platformVariant
    pythonVersion = $runtimeManifest.pythonVersion
    nativeAbi = $runtimeManifest.nativeAbi
    pythonIdentity = [pscustomobject]@{
        version = "3.12.10"
        implementation = "CPython"
        build = @("tags/v3.12.10:fixture", "fixture")
        compiler = "MSC v.1943 64 bit (AMD64)"
    }
    assembledFromCommit = ("0" * 40)
    installedAtUtc = "2026-09-17T00:00:00Z"
    runtimeRoot = "C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu"
}
$modelManifest = [pscustomobject]@{
    schemaVersion = "mavi-vision-model-pack-v1"
    modelPackId = ("mavi-model-v1-" + ("e" * 64))
    modelId = "rtmdet-m-coco-phase1"
    checkpointSha256 = ("f" * 64)
    resolvedConfigSha256 = ("9" * 64)
    assembledFromCommit = ("2" * 40)
    artifacts = @()
}
$modelState = [pscustomobject]@{
    schemaVersion = "mavi-vision-model-install-v1"
    modelPackId = $modelManifest.modelPackId
    modelPackManifestSha256 = ("8" * 64)
    modelId = $modelManifest.modelId
    checkpointSha256 = $modelManifest.checkpointSha256
    resolvedConfigSha256 = $modelManifest.resolvedConfigSha256
    installedAtUtc = "2026-09-17T00:00:00Z"
    modelRoot = "C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1"
}

# Repository/application provenance must not be part of component compatibility.
if (-not (Assert-MaviVisionWorkerComponentCompatibility `
    -RuntimeState $runtimeState `
    -RuntimeManifest $runtimeManifest `
    -RequiredRuntimePackId $runtimeManifest.runtimePackId `
    -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 `
    -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 `
    -ModelState $modelState `
    -ModelManifest $modelManifest `
    -RequiredModelPackId $modelManifest.modelPackId `
    -RequiredModelId $modelManifest.modelId `
    -RequiredCheckpointSha256 $modelManifest.checkpointSha256 `
    -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256)) {
    throw "Compatible v2 Runtime Pack and Model Pack were rejected."
}

$wrongRuntime = "mavi-runtime-v2-" + ("7" * 64)
Assert-Throws -MessageFragment "Runtime Pack ID mismatch" -Script {
    Assert-MaviVisionWorkerComponentCompatibility `
        -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest `
        -RequiredRuntimePackId $wrongRuntime `
        -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 `
        -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 `
        -ModelState $modelState -ModelManifest $modelManifest `
        -RequiredModelPackId $modelManifest.modelPackId `
        -RequiredModelId $modelManifest.modelId `
        -RequiredCheckpointSha256 $modelManifest.checkpointSha256 `
        -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256
}

Assert-Throws -MessageFragment "Model Pack ID mismatch" -Script {
    Assert-MaviVisionWorkerComponentCompatibility `
        -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest `
        -RequiredRuntimePackId $runtimeManifest.runtimePackId `
        -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 `
        -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 `
        -ModelState $modelState -ModelManifest $modelManifest `
        -RequiredModelPackId ("mavi-model-v1-" + ("6" * 64)) `
        -RequiredModelId $modelManifest.modelId `
        -RequiredCheckpointSha256 $modelManifest.checkpointSha256 `
        -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256
}

$v1State = $runtimeState.PSObject.Copy()
$v1State.schemaVersion = "mavi-vision-runtime-install-v1"
Assert-Throws -MessageFragment "installed state schema" -Script {
    Assert-MaviVisionWorkerComponentCompatibility `
        -RuntimeState $v1State -RuntimeManifest $runtimeManifest `
        -RequiredRuntimePackId $runtimeManifest.runtimePackId `
        -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 `
        -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 `
        -ModelState $modelState -ModelManifest $modelManifest `
        -RequiredModelPackId $modelManifest.modelPackId `
        -RequiredModelId $modelManifest.modelId `
        -RequiredCheckpointSha256 $modelManifest.checkpointSha256 `
        -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256
}

$badModel = $modelManifest.PSObject.Copy()
$badModel.schemaVersion = "1.0"
Assert-Throws -MessageFragment "model manifest schema" -Script {
    Assert-MaviVisionModelPackManifest -Manifest $badModel
}

$launcherText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviVisionWorker.ps1") -Raw
foreach ($required in @(
    "Mavi.VisionRuntime.Common.psm1",
    "Assert-MaviVisionWorkerComponentCompatibility",
    "mavi-vision-runtime-install-v2",
    "mavi-vision-model-pack-v1",
    "MAVI_COMMIT_SHA",
    "src\\vision",
    "models\\qualifications",
    "config\\pipelines"
)) {
    if ($launcherText -notmatch [regex]::Escape($required)) {
        throw "Vision worker launcher is missing component contract fragment: $required"
    }
}
foreach ($forbidden in @(
    "Assert-MaviVisionRuntimeSourceCompatible",
    "state.sourceCommit",
    "release\\models",
    "release\\runtime"
)) {
    if ($launcherText -match [regex]::Escape($forbidden)) {
        throw "Vision worker launcher still contains obsolete monolithic binding: $forbidden"
    }
}

Write-Host "MAVI Vision worker component contracts: OK" -ForegroundColor Green
