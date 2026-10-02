[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
function Assert-Throws { param([Parameter(Mandatory=$true)][scriptblock]$Script,[Parameter(Mandatory=$true)][string]$MessageFragment);$thrown=$false;try{&$Script}catch{$thrown=$true;if($_.Exception.Message-notlike"*$MessageFragment*"){throw "Expected error containing '$MessageFragment', got '$($_.Exception.Message)'."}};if(-not$thrown){throw "Expected failure containing '$MessageFragment'."} }
$repoRoot = [IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot "..") ".."))
$bindingPath = Join-Path $repoRoot (Join-Path "src" (Join-Path "vision" (Join-Path "config" (Join-Path "components" "phase1-bindings-v2.json"))))

# --- Compatibility: Runtime Pack side unchanged, Model Packs as a list ---------
# The installed-store path (a real install, the committed binding, and every
# §7 item 2-4 refusal) is exercised in Test-MaviVisionModelPackStateContracts.ps1.
$runtimeManifest=[pscustomobject]@{schemaVersion="mavi-vision-runtime-pack-v2";runtimePackId=("mavi-runtime-v2-"+("a"*64));platformVariant="windows-x86_64-cpu";pythonVersion="3.12.10";nativeAbi="win_amd64-msvc-14.44-sdk-10.0.26100.0";thirdPartyLockSha256=("b"*64);runtimeRequirementsSha256=("c"*64);assembledFromCommit=("1"*40);artifacts=@()}
$runtimeState=[pscustomobject]@{schemaVersion="mavi-vision-runtime-install-v2";runtimePackId=$runtimeManifest.runtimePackId;runtimePackManifestSha256=("d"*64);thirdPartyLockSha256=$runtimeManifest.thirdPartyLockSha256;runtimeRequirementsSha256=$runtimeManifest.runtimeRequirementsSha256;platformVariant=$runtimeManifest.platformVariant;pythonVersion=$runtimeManifest.pythonVersion;nativeAbi=$runtimeManifest.nativeAbi;pythonIdentity=[pscustomobject]@{version="3.12.10";implementation="CPython";build=@("tags/v3.12.10:fixture","fixture");compiler="MSC v.1943 64 bit (AMD64)"};assembledFromCommit=("0"*40);installedAtUtc="2026-09-17T00:00:00Z";runtimeRoot="C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu"}
$modelManifest=[pscustomobject][ordered]@{artifacts=@([pscustomobject][ordered]@{artifactRole="licence-notice";relativePath="unit-pack/LICENSE";sha256=("5"*64);sizeBytes=11},[pscustomobject][ordered]@{artifactRole="checkpoint";relativePath="unit-pack/model.pth";sha256=("f"*64);sizeBytes=12},[pscustomobject][ordered]@{artifactRole="resolved-config";relativePath="unit-pack/resolved.py";sha256=("9"*64);sizeBytes=13});assembledFromCommit=("2"*40);capabilityIds=@("detector");modelId="rtmdet-m-coco-phase1";modelPackId=("mavi-model-v2-"+("e"*64));modelVersion="1.0.0";schemaVersion="mavi-vision-model-pack-v2"}
function New-ModelState { return New-MaviVisionModelInstallState -Manifest $modelManifest -ModelPackManifestSha256 ("8"*64) -InstallRoot "C:\ProgramData\MAVI\Development\VisionModels" }
function New-RequiredPack { param([object]$State = (New-ModelState),[string]$ModelPackId = $modelManifest.modelPackId,[string]$CapabilityId = "detector") return [pscustomobject]@{CapabilityId=$CapabilityId;ModelPackId=$ModelPackId;ModelState=$State;ModelManifest=$modelManifest} }
function Invoke-Compatibility { param([object[]]$ModelPacks = @(New-RequiredPack),[string]$RequiredRuntimePackId = $runtimeManifest.runtimePackId,[object]$State = $runtimeState) return Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $State -RuntimeManifest $runtimeManifest -RequiredRuntimePackId $RequiredRuntimePackId -RequiredThirdPartyLockSha256 $runtimeManifest.thirdPartyLockSha256 -RequiredRuntimeRequirementsSha256 $runtimeManifest.runtimeRequirementsSha256 -RequiredModelPacks $ModelPacks }
if(-not(Invoke-Compatibility)){throw "Compatible v2 Runtime Pack and Model Pack were rejected."}
# A hashtable entry is accepted like an object.
if(-not(Invoke-Compatibility -ModelPacks @(@{CapabilityId="detector";ModelPackId=$modelManifest.modelPackId;ModelState=(New-ModelState);ModelManifest=$modelManifest}))){throw "A hashtable-shaped required Model Pack was rejected."}
Assert-Throws -MessageFragment "Runtime Pack ID mismatch" -Script { Invoke-Compatibility -RequiredRuntimePackId ("mavi-runtime-v2-"+("7"*64)) }
Assert-Throws -MessageFragment "Model Pack ID mismatch" -Script { Invoke-Compatibility -ModelPacks @(New-RequiredPack -ModelPackId ("mavi-model-v2-"+("6"*64))) }
$v1RuntimeState=$runtimeState.PSObject.Copy();$v1RuntimeState.schemaVersion="mavi-vision-runtime-install-v1";Assert-Throws -MessageFragment "installed state schema" -Script { Invoke-Compatibility -State $v1RuntimeState }
$v1ModelState=[pscustomobject]@{schemaVersion="mavi-vision-model-install-v1";modelPackId=$modelManifest.modelPackId;modelPackManifestSha256=("8"*64);modelId=$modelManifest.modelId;checkpointSha256=("f"*64);resolvedConfigSha256=("9"*64);installedAtUtc="2026-09-17T00:00:00Z";modelRoot="C:\legacy"}
Assert-Throws -MessageFragment "model installed state schema is unsupported" -Script { Invoke-Compatibility -ModelPacks @(New-RequiredPack -State $v1ModelState) }
$wrongSha=New-ModelState;$wrongSha.artifactSha256.checkpoint=("0"*64);Assert-Throws -MessageFragment "artifactSha256.checkpoint" -Script { Invoke-Compatibility -ModelPacks @(New-RequiredPack -State $wrongSha) }
$missingRole=New-ModelState;$missingRole.artifactSha256=[pscustomobject]@{checkpoint=("f"*64);"resolved-config"=("9"*64)};Assert-Throws -MessageFragment "artifactSha256.licence-notice" -Script { Invoke-Compatibility -ModelPacks @(New-RequiredPack -State $missingRole) }
$v1Field=New-ModelState;$v1Field|Add-Member -NotePropertyName checkpointSha256 -NotePropertyValue ("f"*64);Assert-Throws -MessageFragment "unexpected field checkpointSha256" -Script { Invoke-Compatibility -ModelPacks @(New-RequiredPack -State $v1Field) }
# Every required pack is checked, not only the first.
Assert-Throws -MessageFragment "does not provide capability 'tracker'" -Script { Invoke-Compatibility -ModelPacks @((New-RequiredPack),(New-RequiredPack -CapabilityId "tracker")) }
$badModel=$modelManifest.PSObject.Copy();$badModel.schemaVersion="mavi-vision-model-pack-v1";Assert-Throws -MessageFragment "model manifest schema" -Script { Assert-MaviVisionModelPackManifest -Manifest $badModel }
$changedIdentity=$runtimeState.pythonIdentity.PSObject.Copy();$changedIdentity.compiler="tampered compiler identity";if(Test-MaviVisionPythonIdentityEqual -Left $runtimeState.pythonIdentity -Right $changedIdentity){throw "Changed Python identity was incorrectly accepted."}

# --- Component binding v2 reading ---------------------------------------------
$committedBinding = Get-Content -LiteralPath $bindingPath -Raw | ConvertFrom-Json
$committedRole = Get-MaviVisionBindingRole -Binding $committedBinding -RoleId "vision"
if ([string]$committedRole.RuntimePackFamilyId -cne "mmdetection-phase1-v1") { throw "Role vision of the committed binding is not bound to family mmdetection-phase1-v1." }
if (@($committedRole.CapabilityBindings).Count -ne 1 -or [string]@($committedRole.CapabilityBindings)[0].CapabilityId -cne "detector") { throw "Role vision of the committed binding must bind exactly the detector capability." }
foreach ($declared in @("windows-x86_64-cpu","windows-x86_64-cuda","linux-x86_64-cpu")) { if ($null -eq (Get-MaviVisionBindingRuntimeRequirement -BindingRole $committedRole -Variant $declared)) { throw "The committed binding does not declare '$declared'." } }
# Class A (plan P-17): Linux CUDA is known but not releasable and is absent.
if ($null -ne (Get-MaviVisionBindingRuntimeRequirement -BindingRole $committedRole -Variant "linux-x86_64-cuda")) { throw "linux-x86_64-cuda must not be declared by the binding." }
Assert-Throws -MessageFragment "role 'tracker' exactly once" -Script { Get-MaviVisionBindingRole -Binding $committedBinding -RoleId "tracker" }
$v1Binding = Get-Content -LiteralPath (Join-Path $repoRoot (Join-Path "src" (Join-Path "vision" (Join-Path "tests" (Join-Path "fixtures" (Join-Path "component-binding-v1" "mmdetection-phase1-v1.json")))))) -Raw | ConvertFrom-Json
Assert-Throws -MessageFragment "Unsupported Vision component binding schema 'mavi-vision-component-requirements-v1'" -Script { Get-MaviVisionBindingRole -Binding $v1Binding -RoleId "vision" }
function Copy-Binding { return (Get-Content -LiteralPath $bindingPath -Raw | ConvertFrom-Json) }
$disabled = Copy-Binding; $disabledBinding = @($disabled.capabilityBindings)[0]; $disabledBinding.enabled = $false
Assert-Throws -MessageFragment "is disabled" -Script { Get-MaviVisionBindingRole -Binding $disabled -RoleId "vision" }
$unbound = Copy-Binding; $unbound.capabilityBindings = @()
Assert-Throws -MessageFragment "exactly once" -Script { Get-MaviVisionBindingRole -Binding $unbound -RoleId "vision" }
$traversal = Copy-Binding; $traversalRole = @($traversal.roles)[0]; $traversalRole.runtimePackFamilyId = "..\escape"
Assert-Throws -MessageFragment "invalid runtimePackFamilyId" -Script { Get-MaviVisionBindingRole -Binding $traversal -RoleId "vision" }
$partial = Copy-Binding; $partialEntry = @($partial.runtimePacks)[0].variants.PSObject.Properties["windows-x86_64-cpu"].Value; $partialEntry.PSObject.Properties.Remove("nativeAbi")
if ($null -ne (Get-MaviVisionBindingRuntimeRequirement -BindingRole (Get-MaviVisionBindingRole -Binding $partial -RoleId "vision") -Variant "windows-x86_64-cpu")) { throw "A partial variant entry was treated as declared." }

# --- Retired composition environment ------------------------------------------
$retired = @(Get-MaviVisionRetiredCompositionEnvironment)
if (($retired -join ",") -cne "MAVI_MODEL_MANIFEST_PATH,MAVI_QUALIFICATION_RECORD_PATH,MAVI_RUNTIME_PROFILE_PATH,MAVI_COMPLETION_SCHEMA_VERSION") { throw "The retired composition list drifted: $($retired -join ',')" }
$savedEnvironment = @{}
foreach ($name in @($retired + @("MAVI_PIPELINE_PROFILE_PATH","MAVI_COMPLETION_SCHEMA_OVERRIDE"))) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
try {
    foreach ($name in $retired) { [Environment]::SetEnvironmentVariable($name, "inherited", "Process") }
    [Environment]::SetEnvironmentVariable("MAVI_PIPELINE_PROFILE_PATH", "kept-pipeline", "Process")
    [Environment]::SetEnvironmentVariable("MAVI_COMPLETION_SCHEMA_OVERRIDE", "3.1", "Process")
    $cleared = @(Clear-MaviVisionRetiredCompositionEnvironment)
    if ($cleared.Count -ne $retired.Count) { throw "Not every inherited retired composition variable was reported cleared: $($cleared -join ',')" }
    foreach ($name in $retired) { if ($null -ne [Environment]::GetEnvironmentVariable($name, "Process")) { throw "Retired composition variable '$name' survived; the worker would refuse to start." } }
    if ([Environment]::GetEnvironmentVariable("MAVI_PIPELINE_PROFILE_PATH", "Process") -cne "kept-pipeline") { throw "MAVI_PIPELINE_PROFILE_PATH is not retired and must be kept." }
    if ([Environment]::GetEnvironmentVariable("MAVI_COMPLETION_SCHEMA_OVERRIDE", "Process") -cne "3.1") { throw "The Development completion override is the operator's and must be left alone." }
    if (@(Clear-MaviVisionRetiredCompositionEnvironment).Count -ne 0) { throw "Clearing an already clean environment reported removals." }
    if ($env:OS -ne "Windows_NT") {
        # Names are case-sensitive here (Windows folds case itself); the worker
        # matches them case-insensitively, so the launcher must too.
        [Environment]::SetEnvironmentVariable("mavi_runtime_profile_path", "inherited", "Process")
        if ((@(Clear-MaviVisionRetiredCompositionEnvironment) -join ",") -cne "mavi_runtime_profile_path") { throw "A lower-case retired variable was not cleared." }
        if ($null -ne [Environment]::GetEnvironmentVariable("mavi_runtime_profile_path", "Process")) { throw "A lower-case retired variable survived." }
    }
}
finally {
    foreach ($name in @($savedEnvironment.Keys)) {
        if ($null -eq $savedEnvironment[$name]) { [Environment]::SetEnvironmentVariable([string]$name, [NullString]::Value, "Process") }
        else { [Environment]::SetEnvironmentVariable([string]$name, [string]$savedEnvironment[$name], "Process") }
    }
    [Environment]::SetEnvironmentVariable("mavi_runtime_profile_path", [NullString]::Value, "Process")
}

# --- Launcher text pins ----------------------------------------------------------
$launcherText=Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviVisionWorker.ps1") -Raw
foreach($required in @("Mavi.VisionRuntime.Common.psm1","Mavi.VisionRuntime.Integrity.psm1","Assert-MaviVisionWorkerComponentCompatibility","-RequiredModelPacks","Resolve-MaviVisionBoundModelPacks","Get-MaviVisionBindingRole","Get-MaviVisionBindingRuntimeRequirement","Resolve-MaviVisionCudaAvailability","Assert-MaviVisionInstalledRuntimeClosure","Assert-MaviVisionInstalledModelPackIntegrity","Test-MaviVisionPythonIdentityEqual","Clear-MaviVisionRetiredCompositionEnvironment","sys.version_info","platform.python_implementation","platform.python_compiler","mavi-vision-runtime-install-v2","mavi-vision-component-binding-v2","phase1-bindings-v2.json","MAVI_COMPONENT_BINDING_PATH","MAVI_ROLE_ID","MAVI_OVERLAY_ROOT","MAVI_RUNTIME_PACK_MANIFEST_PATH","MAVI_MODEL_ROOT","MAVI_COMMIT_SHA","MAVI_VISION_RUNTIME_WINDOWS_CPU_ROOT","MAVI_VISION_RUNTIME_WINDOWS_CUDA_ROOT","MAVI_VISION_MODEL_ROOT","VisionModels","windows-x86_64-cuda","src\vision","models\qualifications","models\manifests","config\pipelines")){if($launcherText-notmatch[regex]::Escape($required)){throw "Vision worker launcher is missing component contract fragment: $required"}}
# Each store lookup outcome maps to its stable code (plan §7 items 2-3, §10).
foreach($mapping in @(@("not-installed","launch_model_pack_not_installed"),@("ambiguous","launch_model_pack_ambiguous"),@("state-missing","launch_model_pack_not_installed"),@("state-unsupported","launch_model_state_schema_unsupported"))){$pattern='$bound.Status -eq "'+$mapping[0]+'") { Stop-MaviLaunch '+$mapping[1];if($launcherText-notmatch[regex]::Escape($pattern)){throw "Vision worker launcher does not map store outcome '$($mapping[0])' to $($mapping[1])."}}
foreach($forbidden in @("Assert-MaviVisionRuntimeSourceCompatible","state.sourceCommit","release\models","release\runtime","function Test-CudaRuntimeUsable","mmdetection-phase1-v1.json","mavi-vision-component-requirements-v1","mavi-vision-model-install-v1","rtmdet-m-coco-phase1-v1.json","VisionModels\rtmdet-m-coco-phase1","MAVI_MODEL_MANIFEST_PATH","MAVI_QUALIFICATION_RECORD_PATH","MAVI_RUNTIME_PROFILE_PATH","MAVI_COMPLETION_SCHEMA_VERSION","MAVI_COMPLETION_SCHEMA_OVERRIDE","MAVI_PRODUCTION_MODE = `"true")){if($launcherText-match[regex]::Escape($forbidden)){throw "Vision worker launcher still contains an obsolete or forbidden binding: $forbidden"}}
if($launcherText-notmatch[regex]::Escape('$env:MAVI_PRODUCTION_MODE = "false"')){throw "Vision worker launcher must start the worker in Development mode only."}
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
$autoComponentPath = Join-Path $autoRoot "phase1-bindings-v2.json"
function New-AutoBinding {
    # A component binding v2 whose role `vision` is bound to one family with
    # the given variant map (an ordered dictionary of variant -> entry).
    param([Parameter(Mandatory=$true)][System.Collections.IDictionary]$Variants)
    return [ordered]@{
        schemaVersion = "mavi-vision-component-binding-v2"
        bindingId = "phase1-v2"
        runtimePacks = @([ordered]@{ runtimePackFamilyId = "mmdetection-phase1-v1"; variants = $Variants })
        roles = @([ordered]@{ roleId = "vision"; runtimePackFamilyId = "mmdetection-phase1-v1"; capabilityIds = @("detector"); entryPoint = "mavi_vision.worker.main"; readinessContract = "worker-health-v2"; provenanceContract = "vision-job-complete-v3.3" })
        capabilityBindings = @([ordered]@{ capabilityId = "detector"; roleId = "vision"; modelPackId = ("mavi-model-v2-" + ("4" * 64)); qualificationId = "fixture-v2"; enabled = $true })
    }
}
function New-AutoVariantEntry {
    param([Parameter(Mandatory=$true)][string]$RuntimePackId)
    return [ordered]@{ runtimePackId = $RuntimePackId; thirdPartyLockSha256 = ("b" * 64); runtimeRequirementsSha256 = ("c" * 64); nativeAbi = "win_amd64-msvc-14.44.35207-sdk-10.0.26100.0-cuda12.4-sm75" }
}
function New-AutoFixture {
    param([string]$PlatformVariant = "windows-x86_64-cuda",[string]$DeclaredPackId = $null,[string]$PackId = ("mavi-runtime-v2-" + ("a" * 64)))
    if (Test-Path -LiteralPath $autoRoot) { Remove-Item -LiteralPath $autoRoot -Recurse -Force }
    [void](New-Item -ItemType Directory -Path (Join-Path (Join-Path $autoPackRoot "venv") "Scripts") -Force)
    [void](New-Item -ItemType Directory -Path (Join-Path $autoPackRoot "runtime") -Force)
    Set-Content -LiteralPath (Join-Path $autoPackRoot "venv\Scripts\python.exe") -Value "stub" -NoNewline
    Set-Content -LiteralPath (Join-Path $autoPackRoot "venv\pyvenv.cfg") -Value "home = stub" -NoNewline
    $lockPath = Join-Path (Join-Path $autoPackRoot "runtime") "third-party.lock"
    $requirementsPath = Join-Path (Join-Path $autoPackRoot "runtime") "requirements.txt"
    Set-Content -LiteralPath $lockPath -Value "# fixture lock" -NoNewline
    Set-Content -LiteralPath $requirementsPath -Value "# fixture requirements" -NoNewline
    $lockSha = (Get-FileHash -LiteralPath $lockPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $requirementsSha = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        schemaVersion = "mavi-vision-runtime-pack-v2"
        runtimePackId = $PackId
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
        runtimePackId = $PackId
        runtimePackManifestSha256 = $manifestSha
        thirdPartyLockSha256 = $lockSha
        runtimeRequirementsSha256 = $requirementsSha
        platformVariant = $PlatformVariant
        pythonVersion = "3.12.10"
        nativeAbi = $manifest.nativeAbi
    }
    Set-Content -LiteralPath (Join-Path $autoPackRoot "runtime-install.json") -Value ($state | ConvertTo-Json -Depth 8)
    if ([string]::IsNullOrEmpty($DeclaredPackId)) { $DeclaredPackId = $PackId }
    $variants = [ordered]@{ "windows-x86_64-cpu" = (New-AutoVariantEntry -RuntimePackId ("mavi-runtime-v2-" + ("5" * 64))); "windows-x86_64-cuda" = (New-AutoVariantEntry -RuntimePackId $DeclaredPackId) }
    Set-Content -LiteralPath $autoComponentPath -Value ((New-AutoBinding -Variants $variants) | ConvertTo-Json -Depth 10)
    return $PackId
}
function Assert-AutoReason {
    param([Parameter(Mandatory=$true)][string]$Expected,[scriptblock]$DriverProbe,[string]$ComponentPath = $autoComponentPath,[string]$Root = $autoPackRoot)
    $arguments = @{Root=$Root;ComponentBindingPath=$ComponentPath;DeviceIndex=0}
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

    # The REAL committed binding is what the launcher passes: a pack carrying
    # its declared windows-x86_64-cuda runtimePackId is selectable, and only
    # that id is. (Development Auto only; the binding's CUDA release lock is
    # pending-hardware-qualification and nothing here claims more.)
    $committedCudaId = [string](Get-MaviVisionBindingRuntimeRequirement -BindingRole $committedRole -Variant "windows-x86_64-cuda").runtimePackId
    [void](New-AutoFixture -PackId $committedCudaId)
    Assert-AutoReason -Expected "cuda_selected" -ComponentPath $bindingPath -DriverProbe { param($i) return [string]$i } | Out-Null
    [void](New-AutoFixture)
    Assert-AutoReason -Expected "cuda_pack_id_mismatch" -ComponentPath $bindingPath -DriverProbe { param($i) throw "driver must not be probed" } | Out-Null

    # An absent pack is the default answer, it is not usable, and it does not
    # reach the driver.
    Assert-AutoReason -Expected "cuda_pack_absent" -Root (Join-Path $autoRoot "no-such-pack") -DriverProbe { param($i) throw "driver must not be probed" } | Out-Null

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

    # Every shape of "no CUDA pack declared" is refused, and none of them
    # reaches the driver. Under Set-StrictMode each would otherwise throw out
    # of the function and kill the launcher with raw .NET prose instead of a
    # stable reason.
    [void](New-AutoFixture)
    $noDriver = { param($i) throw "driver must not be probed" }
    Assert-AutoReason -Expected "cuda_pack_not_declared" -ComponentPath (Join-Path $autoRoot "absent.json") -DriverProbe $noDriver | Out-Null
    Set-Content -LiteralPath $autoComponentPath -Value "{ not json"
    Assert-AutoReason -Expected "cuda_pack_not_declared" -DriverProbe $noDriver | Out-Null
    $noFamilies = New-AutoBinding -Variants ([ordered]@{}); $noFamilies.runtimePacks = @()
    Set-Content -LiteralPath $autoComponentPath -Value ($noFamilies | ConvertTo-Json -Depth 10)
    Assert-AutoReason -Expected "cuda_pack_not_declared" -DriverProbe $noDriver | Out-Null
    Set-Content -LiteralPath $autoComponentPath -Value ((New-AutoBinding -Variants ([ordered]@{"windows-x86_64-cpu"=(New-AutoVariantEntry -RuntimePackId ("mavi-runtime-v2-" + ("5" * 64)))})) | ConvertTo-Json -Depth 10)
    Assert-AutoReason -Expected "cuda_pack_not_declared" -DriverProbe $noDriver | Out-Null
    Set-Content -LiteralPath $autoComponentPath -Value ((New-AutoBinding -Variants ([ordered]@{"windows-x86_64-cuda"=[ordered]@{nativeAbi="present-but-no-pack-id"}})) | ConvertTo-Json -Depth 10)
    Assert-AutoReason -Expected "cuda_pack_not_declared" -DriverProbe $noDriver | Out-Null
    # The CUDA entry must belong to role vision's family, not any family.
    $otherFamily = New-AutoBinding -Variants ([ordered]@{"windows-x86_64-cuda"=(New-AutoVariantEntry -RuntimePackId ("mavi-runtime-v2-" + ("a" * 64)))}); $otherFamily.runtimePacks[0].runtimePackFamilyId = "another-family"
    Set-Content -LiteralPath $autoComponentPath -Value ($otherFamily | ConvertTo-Json -Depth 10)
    Assert-AutoReason -Expected "cuda_pack_not_declared" -DriverProbe $noDriver | Out-Null
    # A v1 component-requirements file is no longer read, even one that
    # declares exactly the installed CUDA pack in the v1 layout.
    Set-Content -LiteralPath $autoComponentPath -Value (([ordered]@{schemaVersion="mavi-vision-component-requirements-v1";runtimeProfileId="mmdetection-phase1-v1";runtimePacks=[ordered]@{"windows-x86_64-cuda"=[ordered]@{runtimePackId=("mavi-runtime-v2-" + ("a" * 64))}}}) | ConvertTo-Json -Depth 6)
    Assert-AutoReason -Expected "cuda_pack_not_declared" -DriverProbe $noDriver | Out-Null

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
