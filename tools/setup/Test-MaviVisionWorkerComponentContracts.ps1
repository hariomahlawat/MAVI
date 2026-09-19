[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
function Assert-Throws { param([Parameter(Mandatory=$true)][scriptblock]$Script,[Parameter(Mandatory=$true)][string]$MessageFragment);$thrown=$false;try{&$Script}catch{$thrown=$true;if($_.Exception.Message-notlike"*$MessageFragment*"){throw "Expected error containing '$MessageFragment', got '$($_.Exception.Message)'."}};if(-not$thrown){throw "Expected failure containing '$MessageFragment'."} }
$runtimeManifest=[pscustomobject]@{schemaVersion="mavi-vision-runtime-pack-v2";runtimePackId=("mavi-runtime-v2-"+("a"*64));platformVariant="windows-x86_64-cpu";pythonVersion="3.12.10";nativeAbi="win_amd64-msvc-14.44-sdk-10.0.26100.0";thirdPartyLockSha256=("b"*64);runtimeRequirementsSha256=("c"*64);assembledFromCommit=("1"*40);artifacts=@()}
$runtimeState=[pscustomobject]@{schemaVersion="mavi-vision-runtime-install-v2";runtimePackId=$runtimeManifest.runtimePackId;runtimePackManifestSha256=("d"*64);thirdPartyLockSha256=$runtimeManifest.thirdPartyLockSha256;runtimeRequirementsSha256=$runtimeManifest.runtimeRequirementsSha256;platformVariant=$runtimeManifest.platformVariant;pythonVersion=$runtimeManifest.pythonVersion;nativeAbi=$runtimeManifest.nativeAbi;pythonIdentity=[pscustomobject]@{version="3.12.10";implementation="CPython";build=@("tags/v3.12.10:fixture","fixture");compiler="MSC v.1943 64 bit (AMD64)"};assembledFromCommit=("0"*40);installedAtUtc="2026-09-17T00:00:00Z";runtimeRoot="C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu"}
$modelManifest=[pscustomobject]@{schemaVersion="mavi-vision-model-pack-v1";modelPackId=("mavi-model-v1-"+("e"*64));modelId="rtmdet-m-coco-phase1";checkpointSha256=("f"*64);resolvedConfigSha256=("9"*64);assembledFromCommit=("2"*40);artifacts=@()}
$modelState=[pscustomobject]@{schemaVersion="mavi-vision-model-install-v1";modelPackId=$modelManifest.modelPackId;modelPackManifestSha256=("8"*64);modelId=$modelManifest.modelId;checkpointSha256=$modelManifest.checkpointSha256;resolvedConfigSha256=$modelManifest.resolvedConfigSha256;installedAtUtc="2026-09-17T00:00:00Z";modelRoot="C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1"}
if(-not(Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId $runtimeManifest.runtimePackId -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 -ModelState $modelState -ModelManifest $modelManifest -RequiredModelPackId $modelManifest.modelPackId -RequiredModelId $modelManifest.modelId -RequiredCheckpointSha256 $modelManifest.checkpointSha256 -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256)){throw "Compatible v2 Runtime Pack and Model Pack were rejected."}
$wrongRuntime="mavi-runtime-v2-"+("7"*64);Assert-Throws -MessageFragment "Runtime Pack ID mismatch" -Script { Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId $wrongRuntime -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 -ModelState $modelState -ModelManifest $modelManifest -RequiredModelPackId $modelManifest.modelPackId -RequiredModelId $modelManifest.modelId -RequiredCheckpointSha256 $modelManifest.checkpointSha256 -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256 }
Assert-Throws -MessageFragment "Model Pack ID mismatch" -Script { Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId $runtimeManifest.runtimePackId -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 -ModelState $modelState -ModelManifest $modelManifest -RequiredModelPackId ("mavi-model-v1-"+("6"*64)) -RequiredModelId $modelManifest.modelId -RequiredCheckpointSha256 $modelManifest.checkpointSha256 -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256 }
$v1State=$runtimeState.PSObject.Copy();$v1State.schemaVersion="mavi-vision-runtime-install-v1";Assert-Throws -MessageFragment "installed state schema" -Script { Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $v1State -RuntimeManifest $runtimeManifest -RequiredRuntimePackId $runtimeManifest.runtimePackId -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 -ModelState $modelState -ModelManifest $modelManifest -RequiredModelPackId $modelManifest.modelPackId -RequiredModelId $modelManifest.modelId -RequiredCheckpointSha256 $modelManifest.checkpointSha256 -RequiredResolvedConfigSha256 $modelManifest.resolvedConfigSha256 }
$badModel=$modelManifest.PSObject.Copy();$badModel.schemaVersion="1.0";Assert-Throws -MessageFragment "model manifest schema" -Script { Assert-MaviVisionModelPackManifest -Manifest $badModel }
$changedIdentity=$runtimeState.pythonIdentity.PSObject.Copy();$changedIdentity.compiler="tampered compiler identity";if(Test-MaviVisionPythonIdentityEqual -Left $runtimeState.pythonIdentity -Right $changedIdentity){throw "Changed Python identity was incorrectly accepted."}
$launcherText=Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviVisionWorker.ps1") -Raw
foreach($required in @("Mavi.VisionRuntime.Common.psm1","Mavi.VisionRuntime.Integrity.psm1","Assert-MaviVisionWorkerComponentCompatibility","Resolve-MaviVisionCudaAvailability","Assert-MaviVisionInstalledRuntimeClosure","Assert-MaviVisionInstalledModelPackIntegrity","Test-MaviVisionPythonIdentityEqual","sys.version_info","platform.python_implementation","platform.python_compiler","mavi-vision-runtime-install-v2","mavi-vision-model-install-v1","mavi-vision-component-requirements-v1","mmdetection-phase1-v1.json","MAVI_COMMIT_SHA","MAVI_VISION_RUNTIME_WINDOWS_CPU_ROOT","MAVI_VISION_RUNTIME_WINDOWS_CUDA_ROOT","windows-x86_64-cuda","src\vision","models\qualifications","config\pipelines")){if($launcherText-notmatch[regex]::Escape($required)){throw "Vision worker launcher is missing component contract fragment: $required"}}
foreach($forbidden in @("Assert-MaviVisionRuntimeSourceCompatible","state.sourceCommit","release\models","release\runtime","function Test-CudaRuntimeUsable")){if($launcherText-match[regex]::Escape($forbidden)){throw "Vision worker launcher still contains obsolete monolithic binding: $forbidden"}}
# --- Development Auto decision -------------------------------------------
# Resolve-MaviVisionCudaAvailability makes the whole Auto decision on Windows,
# and whichever reason it returns is what the worker records. It previously
# lived inside the launcher and closed over script variables, so nothing could
# call it and nothing did: the only coverage was grepping the launcher's text
# for fragments. Every branch below runs here with no GPU present.
#
# The fixture must pass the full installed-state preflight, because that runs
# before any later check -- a thinner one returns cuda_pack_integrity_failed for
# every case and exercises exactly one branch while appearing to cover nine.
$autoRoot = Join-Path ([IO.Path]::GetTempPath()) ("mavi-auto-" + [Guid]::NewGuid().ToString("N"))
$autoPackRoot = Join-Path $autoRoot "windows-x86_64-cuda"
$autoComponentPath = Join-Path $autoRoot "mmdetection-phase1-v1.json"
function New-AutoFixture {
    param([string]$PlatformVariant = "windows-x86_64-cuda",[string]$DeclaredPackId = $null)
    if (Test-Path -LiteralPath $autoRoot) { Remove-Item -LiteralPath $autoRoot -Recurse -Force }
    [void](New-Item -ItemType Directory -Path (Join-Path $autoPackRoot "venv\Scripts") -Force)
    [void](New-Item -ItemType Directory -Path (Join-Path $autoPackRoot "runtime") -Force)
    Set-Content -LiteralPath (Join-Path $autoPackRoot "venv\Scripts\python.exe") -Value "stub" -NoNewline
    Set-Content -LiteralPath (Join-Path $autoPackRoot "venv\pyvenv.cfg") -Value "home = stub" -NoNewline
    $lockPath = Join-Path $autoPackRoot "runtime\third-party.lock"
    $requirementsPath = Join-Path $autoPackRoot "runtime\requirements.txt"
    Set-Content -LiteralPath $lockPath -Value "# fixture lock" -NoNewline
    Set-Content -LiteralPath $requirementsPath -Value "# fixture requirements" -NoNewline
    $lockSha = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $requirementsSha = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $packId = "mavi-runtime-v2-" + ("a" * 64)
    $manifest = [ordered]@{
        schemaVersion = "mavi-vision-runtime-pack-v2"
        runtimePackId = $packId
        platformVariant = $PlatformVariant
        pythonVersion = "3.12.10"
        nativeAbi = "win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75"
        thirdPartyLockSha256 = $lockSha
        runtimeRequirementsSha256 = $requirementsSha
        assembledFromCommit = ("1" * 40)
        artifacts = @(
            [ordered]@{purpose="third-party-runtime-lock";relativePath="runtime/third-party.lock";sha256=$lockSha},
            [ordered]@{purpose="application-runtime-requirements";relativePath="runtime/requirements.txt";sha256=$requirementsSha}
        )
    }
    $manifestPath = Join-Path $autoPackRoot "runtime-pack-manifest.json"
    Set-Content -LiteralPath $manifestPath -Value ($manifest | ConvertTo-Json -Depth 8)
    $manifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $state = [ordered]@{
        schemaVersion = "mavi-vision-runtime-install-v2"
        runtimePackId = $packId
        runtimePackManifestSha256 = $manifestSha
        thirdPartyLockSha256 = $lockSha
        runtimeRequirementsSha256 = $requirementsSha
        platformVariant = $PlatformVariant
        pythonVersion = "3.12.10"
        nativeAbi = $manifest.nativeAbi
    }
    Set-Content -LiteralPath (Join-Path $autoPackRoot "runtime-install.json") -Value ($state | ConvertTo-Json -Depth 8)
    if ([string]::IsNullOrEmpty($DeclaredPackId)) { $DeclaredPackId = $packId }
    $component = [ordered]@{
        schemaVersion = "mavi-vision-component-requirements-v1"
        runtimeProfileId = "mmdetection-phase1-v1"
        runtimePacks = [ordered]@{"windows-x86_64-cuda" = [ordered]@{runtimePackId = $DeclaredPackId}}
    }
    Set-Content -LiteralPath $autoComponentPath -Value ($component | ConvertTo-Json -Depth 8)
    return $packId
}
function Assert-AutoReason {
    param([Parameter(Mandatory=$true)][string]$Expected,[scriptblock]$DriverProbe,[string]$ComponentPath = $autoComponentPath,[string]$Root = $autoPackRoot)
    $arguments = @{Root=$Root;ComponentRequirementsPath=$ComponentPath;DeviceIndex=0}
    if ($DriverProbe) { $arguments["DriverProbe"] = $DriverProbe }
    $resolution = Resolve-MaviVisionCudaAvailability @arguments
    if ([string]$resolution.Reason -ne $Expected) { throw "Expected Auto reason '$Expected', got '$($resolution.Reason)'." }
    if ($Expected -eq "cuda_selected") {
        if (-not $resolution.Usable) { throw "cuda_selected must be usable." }
    } elseif ($resolution.Usable) { throw "Reason '$Expected' must not be usable." }
    return $resolution
}
try {
    # The fixture itself must reach the driver probe, or nothing below is
    # testing what it claims.
    [void](New-AutoFixture)
    Assert-AutoReason -Expected "cuda_selected" -DriverProbe { param($i) return [string]$i } | Out-Null

    # An absent pack is the default answer, and it is not usable.
    Assert-AutoReason -Expected "cuda_pack_absent" -Root (Join-Path $autoRoot "no-such-pack") | Out-Null

    # A pack whose installed state no longer binds its manifest fails integrity,
    # and fails it before the driver is ever probed.
    [void](New-AutoFixture)
    $tamperedStatePath = Join-Path $autoPackRoot "runtime-install.json"
    $tamperedState = Get-Content -LiteralPath $tamperedStatePath -Raw | ConvertFrom-Json
    $tamperedState.runtimePackManifestSha256 = ("0" * 64)
    Set-Content -LiteralPath $tamperedStatePath -Value ($tamperedState | ConvertTo-Json -Depth 8)
    Assert-AutoReason -Expected "cuda_pack_integrity_failed" -DriverProbe { param($i) throw "driver must not be probed" } | Out-Null

    # A pack built for another variant is refused before the driver is probed.
    [void](New-AutoFixture -PlatformVariant "windows-x86_64-cpu")
    Assert-AutoReason -Expected "cuda_pack_variant_mismatch" -DriverProbe { param($i) throw "driver must not be probed" } | Out-Null

    # An undeclared pack, and an unparseable component file, are both refused.
    [void](New-AutoFixture)
    Assert-AutoReason -Expected "cuda_pack_not_declared" -ComponentPath (Join-Path $autoRoot "absent.json") | Out-Null
    Set-Content -LiteralPath $autoComponentPath -Value "{ not json"
    Assert-AutoReason -Expected "cuda_pack_not_declared" | Out-Null

    # A declared identity that is not the installed one is refused.
    [void](New-AutoFixture -DeclaredPackId ("mavi-runtime-v2-" + ("9" * 64)))
    Assert-AutoReason -Expected "cuda_pack_id_mismatch" -DriverProbe { param($i) throw "driver must not be probed" } | Out-Null

    # Driver outcomes, all reachable without a GPU.
    [void](New-AutoFixture)
    Assert-AutoReason -Expected "cuda_driver_probe_unavailable" -DriverProbe { param($i) return $null } | Out-Null
    Assert-AutoReason -Expected "cuda_device_unavailable" -DriverProbe { param($i) return "" } | Out-Null
    Assert-AutoReason -Expected "cuda_device_unavailable" -DriverProbe { param($i) return "3" } | Out-Null
    Assert-AutoReason -Expected "cuda_driver_probe_failed" -DriverProbe { param($i) throw "nvml exploded" } | Out-Null

    # The only path that selects CUDA names the root it selected.
    $selected = Assert-AutoReason -Expected "cuda_selected" -DriverProbe { param($i) return [string]$i }
    if ([string]$selected.RuntimeRoot -ne $autoPackRoot) { throw "cuda_selected must name the pack root it selected." }
}
finally {
    if (Test-Path -LiteralPath $autoRoot) { Remove-Item -LiteralPath $autoRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

Write-Host "MAVI Vision worker component contracts: OK" -ForegroundColor Green
