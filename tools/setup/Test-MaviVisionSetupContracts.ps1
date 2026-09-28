[CmdletBinding()]
param(
    # An interpreter that can import mavi_vision (the repository .venv, or any
    # Python with `pip install -e src/vision`). Task 17 passes the one it set up.
    [string]$Python
)

# Setup / offline-kit contracts of the Vision composition (Stage 2 S2a.4 plan
# §3-§8; parent plan §7).
#
# Runs under Windows PowerShell 5.1 (Task 17) and PowerShell 7 on any OS. Every
# path is built with Join-Path, nothing touches the Machine environment, and all
# state lives under one temporary directory that is removed at the end.
#
# What this proves:
#   * the preflight (Mavi.VisionSetup.psm1 over sync_offline_vision_components.py
#     `plan`) decides the whole install before the first installer runs, and a
#     binding mismatch, a missing or unbound pack, or a legacy
#     bundle-manifest.json fails with no installer invoked;
#   * every enabled Model Pack of role vision is installed, in modelPackId
#     order, by the real Install-MaviVisionModelPack.ps1, and the kit's
#     applicationOverlay.revision is provenance, not a compatibility gate;
#   * a later failure leaves the earlier valid packs, never yields READY, and a
#     corrected rerun converges; only a passing composition assertion is READY.
# What it does not: the Runtime Pack installer needs Windows, a signed CPython
# installer and a wheelhouse, so its step is instrumented here; the readiness
# step is the launcher's own compatibility functions over the installed store.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
# Mavi.VisionSetup.psm1 imports the runtime module for itself; import it first
# so the launcher functions this test calls directly stay visible here too.
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionSetup.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Integrity.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force

$repoRoot = [IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot "..") ".."))
$modelInstaller = Join-Path $PSScriptRoot "Install-MaviVisionModelPack.ps1"
$setupScript = Join-Path $PSScriptRoot "Setup-MAVI.ps1"
$tool = Join-Path $repoRoot (Join-Path "tools" (Join-Path "vision" "sync_offline_vision_components.py"))
$repositoryBinding = Join-Path $repoRoot (Join-Path "src" (Join-Path "vision" (Join-Path "config" (Join-Path "components" "phase1-bindings-v2.json"))))

if ([string]::IsNullOrWhiteSpace($Python)) {
    foreach ($candidate in @(
        (Join-Path $repoRoot (Join-Path ".venv" (Join-Path "Scripts" "python.exe"))),
        (Join-Path $repoRoot (Join-Path ".venv" (Join-Path "bin" "python")))
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $Python = $candidate; break }
    }
}
if ([string]::IsNullOrWhiteSpace($Python)) { $Python = "python" }

function Assert-Throws {
    param([Parameter(Mandatory = $true)][scriptblock]$Script, [Parameter(Mandatory = $true)][string]$MessageFragment)
    $thrown = $false
    try { & $Script | Out-Null }
    catch {
        $thrown = $true
        if ($_.Exception.Message -notlike "*$MessageFragment*") { throw "Expected error containing '$MessageFragment', got '$($_.Exception.Message)'." }
    }
    if (-not $thrown) { throw "Expected failure containing '$MessageFragment'." }
}

function Assert-Equal {
    param([AllowNull()][object]$Actual, [AllowNull()][object]$Expected, [Parameter(Mandatory = $true)][string]$What)
    $left = @($Actual) -join "|"
    $right = @($Expected) -join "|"
    if ($left -cne $right) { throw "$What`: expected '$right', got '$left'." }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-TextSha256 {
    param([Parameter(Mandatory = $true)][string]$Text)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Text)))).Replace("-", "").ToLowerInvariant() }
    finally { $sha.Dispose() }
}

function Write-Utf8File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $directory = Split-Path $Path -Parent
    if (-not (Test-Path -LiteralPath $directory)) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function Write-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][object]$Value)
    # Windows PowerShell's ConvertTo-Json writes CRLF; release metadata (the
    # binding included) is LF-only and the loaders refuse CR.
    Write-Utf8File -Path $Path -Text ((($Value | ConvertTo-Json -Depth 12) -replace "`r`n", "`n") + "`n")
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Invoke-Tool {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $output = @(& $Python $tool @Arguments 2>&1); $code = $LASTEXITCODE }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) { throw "sync_offline_vision_components.py $($Arguments[0]) failed ($code): $($output -join ' ')" }
}

$committedBinding = Read-JsonFile $repositoryBinding
$cpuEntry = $committedBinding.runtimePacks[0].variants."windows-x86_64-cpu"
$cudaEntry = $committedBinding.runtimePacks[0].variants."windows-x86_64-cuda"
$cpuId = [string]$cpuEntry.runtimePackId
$cudaId = [string]$cudaEntry.runtimePackId
$modelA = "mavi-model-v2-" + ("a" * 64)
$modelB = "mavi-model-v2-" + ("b" * 64)
$modelUnbound = "mavi-model-v2-" + ("9" * 64)

function New-RuntimePack {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Variant, [object]$Entry, [string]$Payload = "runtime")
    if ($null -eq $Entry) { $Entry = $committedBinding.runtimePacks[0].variants.$Variant }
    Write-Utf8File -Path (Join-Path $Root "payload.bin") -Text $Payload
    $payloadPath = Join-Path $Root "payload.bin"
    $manifest = [ordered]@{
        schemaVersion = "mavi-vision-runtime-pack-v2"
        runtimePackId = [string]$Entry.runtimePackId
        platformVariant = $Variant
        pythonVersion = "3.12.10"
        nativeAbi = [string]$Entry.nativeAbi
        thirdPartyLockSha256 = [string]$Entry.thirdPartyLockSha256
        runtimeRequirementsSha256 = [string]$Entry.runtimeRequirementsSha256
        assembledFromCommit = ("1" * 40)
        artifacts = @([ordered]@{ relativePath = "payload.bin"; sizeBytes = [long](Get-Item -LiteralPath $payloadPath).Length; sha256 = (Get-FileSha256 $payloadPath) })
    }
    Write-JsonFile -Path (Join-Path $Root "runtime-pack-manifest.json") -Value $manifest
}

function New-ModelPack {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$ModelPackId, [Parameter(Mandatory = $true)][string]$Directory, [Parameter(Mandatory = $true)][string]$CapabilityId)
    $licence = Join-Path $Root (Join-Path $Directory "LICENSE")
    $weights = Join-Path $Root (Join-Path $Directory "weights.bin")
    Write-Utf8File -Path $licence -Text "Apache License 2.0`n"
    Write-Utf8File -Path $weights -Text ("weights-" + $ModelPackId)
    $manifest = [ordered]@{
        schemaVersion = "mavi-vision-model-pack-v2"
        modelPackId = $ModelPackId
        modelId = ("fixture-" + $Directory)
        modelVersion = "1.0.0"
        capabilityIds = @($CapabilityId)
        assembledFromCommit = ("1" * 40)
        artifacts = @(
            [ordered]@{ artifactRole = "licence-notice"; relativePath = "$Directory/LICENSE"; sha256 = (Get-FileSha256 $licence); sizeBytes = [long](Get-Item -LiteralPath $licence).Length },
            [ordered]@{ artifactRole = "weights"; relativePath = "$Directory/weights.bin"; sha256 = (Get-FileSha256 $weights); sizeBytes = [long](Get-Item -LiteralPath $weights).Length }
        )
    }
    Write-JsonFile -Path (Join-Path $Root "model-pack-manifest.json") -Value $manifest
}

function New-TwoPackBinding {
    # Role vision with two enabled capabilities, each on its own Model Pack.
    param([Parameter(Mandatory = $true)][string]$Directory, [string]$SecondQualification = "embedding-fixture-v1")
    $document = Read-JsonFile $repositoryBinding
    $document.roles[0].capabilityIds = @("detector", "embedding")
    $document.capabilityBindings[0].modelPackId = $modelA
    $document.capabilityBindings = @($document.capabilityBindings[0], [pscustomobject][ordered]@{
        capabilityId = "embedding"; roleId = "vision"; modelPackId = $modelB; qualificationId = $SecondQualification; enabled = $true
    })
    $path = Join-Path $Directory "phase1-bindings-v2.json"
    Write-JsonFile -Path $path -Value $document
    return $path
}

function New-Kit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Binding,
        [string[]]$Runtimes = @("windows-x86_64-cpu"),
        [string[]]$Models = @("a", "b"),
        [string]$Revision = ("1" * 40)
    )
    $sources = Join-Path $Root "sources"
    $arguments = @("sync", "--kit-root", (Join-Path $Root "kit"), "--component-binding", $Binding, "--application-revision", $Revision)
    foreach ($variant in $Runtimes) {
        $packRoot = Join-Path $sources ("runtime-" + $variant)
        New-RuntimePack -Root $packRoot -Variant $variant -Payload ("runtime-" + $variant)
        $arguments += @("--runtime-pack", $packRoot)
    }
    foreach ($name in $Models) {
        $packRoot = Join-Path $sources ("model-" + $name)
        switch ($name) {
            "a" { New-ModelPack -Root $packRoot -ModelPackId $modelA -Directory "fixture-detector" -CapabilityId "detector" }
            "b" { New-ModelPack -Root $packRoot -ModelPackId $modelB -Directory "fixture-embedding" -CapabilityId "embedding" }
            "unbound" { New-ModelPack -Root $packRoot -ModelPackId $modelUnbound -Directory "fixture-unbound" -CapabilityId "detector" }
        }
        $arguments += @("--model-pack", $packRoot)
    }
    Invoke-Tool -Arguments $arguments
    return (Join-Path $Root "kit")
}

function Edit-Inventory {
    param([Parameter(Mandatory = $true)][string]$Kit, [Parameter(Mandatory = $true)][scriptblock]$Change)
    $path = Join-Path $Kit (Join-Path "vision" "component-inventory.json")
    $inventory = Read-JsonFile $path
    & $Change $inventory
    Write-JsonFile -Path $path -Value $inventory
}

# The Setup order under test: preflight, then install, then assert. The steps
# are plain script blocks, exactly as Setup-MAVI passes them (a GetNewClosure()
# block would let the installer's Import-Module -Force unload this script's
# modules); what they do for a case is set in script-scope state.
$script:Calls = New-Object System.Collections.Generic.List[string]
$script:StepStore = $null
$script:FailModelId = $null
$script:ComposeBinding = $null
$script:InstalledRuntimeId = $cpuId

$RuntimeStep = { param($entry) $script:Calls.Add("runtime:" + $entry.RuntimePackId) }
$ModelStep = {
    param($entry)
    $script:Calls.Add("model:" + $entry.ModelPackId)
    if ($entry.ModelPackId -ceq $script:FailModelId) { throw "model_pack_stage_failed: simulated disk failure" }
    & $modelInstaller -PackRoot $entry.SourceRoot -StoreRoot $script:StepStore -NoMachineEnvironment
}
$AssertStep = {
    param($plan)
    $script:Calls.Add("assert")
    if ($script:ComposeBinding) { Assert-TestComposition -StoreRoot $script:StepStore -Binding $script:ComposeBinding -InstalledRuntimePackId $script:InstalledRuntimeId }
}

function Reset-Calls { $script:Calls.Clear() }

function Invoke-VisionSetup {
    param(
        [Parameter(Mandatory = $true)][object]$Source,
        [Parameter(Mandatory = $true)][string]$Binding,
        [Parameter(Mandatory = $true)][string]$StoreRoot,
        [string]$FailModelId,
        # Readiness is the launcher's compatibility functions over the store.
        [switch]$Compose,
        [string]$InstalledRuntimePackId = $cpuId
    )
    $script:StepStore = $StoreRoot
    $script:FailModelId = $FailModelId
    $script:ComposeBinding = if ($Compose) { $Binding } else { $null }
    $script:InstalledRuntimeId = $InstalledRuntimePackId
    $plan = Invoke-MaviVisionComponentPreflight -Source $Source -RepositoryRoot $repoRoot -Python $Python -ModelStoreRoot $StoreRoot -ComponentBindingPath $Binding
    $script:Calls.Add("preflight-ok")
    return Invoke-MaviVisionComponentInstallation -Plan $plan -InstallRuntimePack $RuntimeStep -InstallModelPack $ModelStep -AssertComposition $AssertStep
}

# The launcher's own compatibility functions over the installed store, with the
# runtime side described by the binding entry the recorder "installed".
function Assert-TestComposition {
    param([Parameter(Mandatory = $true)][string]$StoreRoot, [Parameter(Mandatory = $true)][string]$Binding, [string]$InstalledRuntimePackId = $cpuId)
    $entry = $cpuEntry
    $role = Get-MaviVisionBindingRole -Binding (Get-Content -LiteralPath $Binding -Raw | ConvertFrom-Json) -RoleId "vision"
    $resolution = Resolve-MaviVisionBoundModelPacks -StoreRoot $StoreRoot -CapabilityBindings @($role.CapabilityBindings)
    foreach ($bound in @($resolution.ModelPacks)) {
        if ($bound.Status -ne "installed") { throw "launch_model_pack_not_installed: $($bound.ModelPackId) is $($bound.Status)" }
        [void](Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $StoreRoot -Manifest $bound.ModelManifest)
    }
    $manifest = [pscustomobject][ordered]@{
        schemaVersion = "mavi-vision-runtime-pack-v2"; runtimePackId = $InstalledRuntimePackId; platformVariant = "windows-x86_64-cpu"; pythonVersion = "3.12.10"
        nativeAbi = [string]$entry.nativeAbi; thirdPartyLockSha256 = [string]$entry.thirdPartyLockSha256; runtimeRequirementsSha256 = [string]$entry.runtimeRequirementsSha256
        assembledFromCommit = ("1" * 40); artifacts = @()
    }
    $state = [pscustomobject][ordered]@{
        schemaVersion = "mavi-vision-runtime-install-v2"; runtimePackId = $InstalledRuntimePackId; platformVariant = "windows-x86_64-cpu"; pythonVersion = "3.12.10"
        nativeAbi = [string]$entry.nativeAbi; thirdPartyLockSha256 = [string]$entry.thirdPartyLockSha256; runtimeRequirementsSha256 = [string]$entry.runtimeRequirementsSha256
    }
    [void](Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $state -RuntimeManifest $manifest -RequiredRuntimePackId ([string]$entry.runtimePackId) -RequiredThirdPartyLockSha256 ([string]$entry.thirdPartyLockSha256) -RequiredRuntimeRequirementsSha256 ([string]$entry.runtimeRequirementsSha256) -RequiredModelPacks @($resolution.ModelPacks))
}

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("mavi-vision-setup-contracts-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$repositoryBindingSha = Get-FileSha256 $repositoryBinding
try {
    # ------------------------------------------------------------------ D-1
    # Setup no longer probes the legacy bundle manifest, and a directory that
    # carries only one is reported as not installable, never as absent.
    $setupText = Get-Content -LiteralPath $setupScript -Raw
    # A quoted path literal is a probe; the explanatory comment is not.
    if ($setupText -match "[`"'][^`"'\r\n]*bundle-manifest\.json[`"']") { throw "D-1: Setup-MAVI.ps1 still probes the legacy bundle-manifest.json." }
    if (-not $setupText.Contains("Invoke-MaviVisionComponentPreflight") -or -not $setupText.Contains("Invoke-MaviVisionComponentInstallation")) { throw "Setup-MAVI.ps1 does not run the Vision preflight and installation." }
    if (-not $setupText.Contains("Start-MaviVisionWorker.ps1") -or -not $setupText.Contains("-VerifyOnly")) { throw "Setup-MAVI.ps1 does not use the launcher's compatibility check as its readiness boundary." }
    $preflightAt = $setupText.IndexOf("Invoke-MaviVisionComponentPreflight -Source")
    foreach ($installer in @("Install-MaviVisionRuntime.ps1", "Install-MaviVisionModelPack.ps1")) {
        if ($setupText.IndexOf($installer) -lt $preflightAt) { throw "Setup-MAVI.ps1 references $installer before the preflight." }
    }
    if ($setupText -match '\}\.GetNewClosure\(\)') { throw "Setup-MAVI.ps1 must pass plain script blocks: from a closure the installers' Import-Module -Force unloads Setup's modules." }
    foreach ($retired in @("MAVI_MODEL_MANIFEST_PATH", "MAVI_QUALIFICATION_RECORD_PATH", "MAVI_RUNTIME_PROFILE_PATH", "MAVI_COMPLETION_SCHEMA_VERSION")) {
        if ($setupText.Contains($retired)) { throw "Setup-MAVI.ps1 must not set the retired composition variable $retired." }
    }
    # A combined Development bundle carries the kit's Vision store before its
    # manifest is written, so bundle Setup finds <bundle>\vision (Windows-only builder).
    $bundleBuilder = Get-Content -LiteralPath (Join-Path $PSScriptRoot "New-MaviOfflineSetupBundle.ps1") -Raw
    $storeCopyAt = $bundleBuilder.IndexOf('Copy-Tree -Source $visionStore -Target (Join-Path $destination "vision")')
    if ($storeCopyAt -lt 0 -or $storeCopyAt -gt $bundleBuilder.IndexOf('$artifactFiles = @(')) { throw "New-MaviOfflineSetupBundle.ps1 must copy the Vision component store into the bundle before hashing its files." }
    $launcherText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviVisionWorker.ps1") -Raw
    $verifyAt = $launcherText.IndexOf("if (`$VerifyOnly)")
    if ($verifyAt -lt 0 -or $verifyAt -lt $launcherText.IndexOf("launch_component_compatibility_failed") -or $verifyAt -gt $launcherText.IndexOf("& `$python -m mavi_vision.worker.main")) {
        throw "Start-MaviVisionWorker.ps1 -VerifyOnly must stop after the compatibility assertion and before the worker starts."
    }

    $legacyRepo = Join-Path $tempRoot (Join-Path "legacy" "MAVI")
    New-Item -ItemType Directory -Path $legacyRepo -Force | Out-Null
    $legacyBundle = Join-Path $tempRoot (Join-Path "legacy" "MAVI-Vision-Runtime-Bundle")
    Write-Utf8File -Path (Join-Path $legacyBundle (Join-Path "windows-x86_64-cpu" "bundle-manifest.json")) -Text "{}"
    $legacySource = Resolve-MaviVisionSetupSource -BundleRoot (Join-Path $tempRoot "no-kit") -RepositoryRoot $legacyRepo -ExplicitRoot $null
    Assert-Equal $legacySource.Kind "runtime-bundle" "a legacy sibling bundle is a source to report, not an absent one"
    Reset-Calls
    $store = Join-Path $tempRoot "store-legacy"
    Assert-Throws { Invoke-VisionSetup -Source $legacySource -Binding $repositoryBinding -StoreRoot $store } "kit_incomplete:${cpuId}: "
    Assert-Throws { Invoke-VisionSetup -Source $legacySource -Binding $repositoryBinding -StoreRoot $store } "not an installable Runtime Pack"
    Assert-Equal $script:Calls.Count 0 "D-1: nothing may be installed from a legacy bundle"

    # ------------------------------------------------------------------ sources and MAVI_VISION_BUNDLE_ROOT
    $sourceRoot = Join-Path $tempRoot "sources-case"
    $binding2 = New-TwoPackBinding -Directory (Join-Path $sourceRoot "binding")
    $kit = New-Kit -Root (Join-Path $sourceRoot "bundle") -Binding $binding2
    # The kit's own directory is the Setup bundle root here: vision\component-inventory.json sits under it.
    $bundleRoot = $kit
    $nothing = Resolve-MaviVisionSetupSource -BundleRoot (Join-Path $tempRoot "empty-bundle") -RepositoryRoot (Join-Path $tempRoot (Join-Path "lonely" "MAVI")) -ExplicitRoot ""
    Assert-Equal $nothing.Kind "none" "no source at all"
    $fromBundle = Resolve-MaviVisionSetupSource -BundleRoot $bundleRoot -RepositoryRoot $legacyRepo -ExplicitRoot $null
    Assert-Equal @($fromBundle.Kind, $fromBundle.Origin) @("kit", "bundle") "the kit beside Setup wins over the default sibling bundle"
    $explicitRuntime = Join-Path $tempRoot "explicit-runtime"
    New-RuntimePack -Root (Join-Path $explicitRuntime "windows-x86_64-cpu") -Variant "windows-x86_64-cpu"
    $explicit = Resolve-MaviVisionSetupSource -BundleRoot $bundleRoot -RepositoryRoot $legacyRepo -ExplicitRoot $explicitRuntime
    Assert-Equal @($explicit.Kind, $explicit.Origin, $explicit.Root) @("runtime-bundle", "explicit", [IO.Path]::GetFullPath($explicitRuntime)) "MAVI_VISION_BUNDLE_ROOT is the operator's choice over the bundle kit"
    $explicitKit = Resolve-MaviVisionSetupSource -BundleRoot (Join-Path $tempRoot "empty-bundle") -RepositoryRoot $legacyRepo -ExplicitRoot $kit
    Assert-Equal @($explicitKit.Kind, $explicitKit.Origin) @("kit", "explicit") "an explicit root holding an inventory is a component store"
    Assert-Throws { Resolve-MaviVisionSetupSource -BundleRoot $bundleRoot -RepositoryRoot $legacyRepo -ExplicitRoot (Join-Path $tempRoot "missing-explicit") } "is not a directory"

    # ------------------------------------------------------------------ N Model Packs, revision provenance, order
    # The kit was assembled at another application commit than this checkout;
    # the binding is identical, so it installs.
    $happyRoot = Join-Path $tempRoot "happy"
    $happyBinding = New-TwoPackBinding -Directory (Join-Path $happyRoot "binding")
    $happyKit = New-Kit -Root $happyRoot -Binding $happyBinding -Revision ("7" * 40)
    $happyStore = Join-Path $happyRoot "store"
    $head = ""
    try { $head = (& git -C $repoRoot rev-parse HEAD 2>$null | Out-String).Trim() } catch { $head = "" }
    if ($head -eq ("7" * 40)) { throw "The revision-reuse fixture must differ from repository HEAD." }
    Reset-Calls
    $happySource = [pscustomobject]@{ Kind = "kit"; Root = $happyKit; Origin = "bundle" }
    $result = Invoke-VisionSetup -Source $happySource -Binding $happyBinding -StoreRoot $happyStore -Compose
    Assert-Equal $result.Status "ready" "a complete kit"
    Assert-Equal $result.ApplicationRevision ("7" * 40) "the kit revision is reported as provenance"
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "model:$modelA", "model:$modelB", "assert") "install order"
    foreach ($directory in @("fixture-detector", "fixture-embedding")) {
        $state = Read-JsonFile (Join-Path $happyStore (Join-Path $directory "model-install.json"))
        Assert-Equal $state.schemaVersion "mavi-vision-model-install-v2" "installed state of $directory"
    }
    Assert-Equal @($result.ModelPackIds) @($modelA, $modelB) "every bound Model Pack is installed"

    # A corrected rerun of a complete install reuses both packs and is READY again.
    Reset-Calls
    $rerun = Invoke-VisionSetup -Source $happySource -Binding $happyBinding -StoreRoot $happyStore -Compose
    Assert-Equal $rerun.Status "ready" "an idempotent rerun"

    # Selection is by binding id and variant, not by inventory or directory order.
    $orderRoot = Join-Path $tempRoot "order"
    $orderBinding = New-TwoPackBinding -Directory (Join-Path $orderRoot "binding")
    $orderKit = New-Kit -Root $orderRoot -Binding $orderBinding -Runtimes @("windows-x86_64-cuda", "windows-x86_64-cpu") -Models @("b", "a")
    Edit-Inventory -Kit $orderKit -Change { param($inventory) $inventory.runtimePacks = @($inventory.runtimePacks | Sort-Object platformVariant -Descending); $inventory.modelPacks = @($inventory.modelPacks | Sort-Object modelPackId -Descending) }
    $orderStore = Join-Path $orderRoot "store"
    Reset-Calls
    $ordered = Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "kit"; Root = $orderKit; Origin = "bundle" }) -Binding $orderBinding -StoreRoot $orderStore
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "model:$modelA", "model:$modelB", "runtime:$cudaId", "assert") "CPU first, then models by id, then the optional CUDA pack"
    Assert-Equal @($ordered.OptionalRuntimePackIds) @($cudaId) "the bound CUDA pack is installed only because the kit carries it"

    # A Runtime Bundle root with both variants: the CPU directory is chosen by variant.
    $bothRoot = Join-Path $tempRoot "both-variants"
    New-RuntimePack -Root (Join-Path $bothRoot "windows-x86_64-cuda") -Variant "windows-x86_64-cuda"
    New-RuntimePack -Root (Join-Path $bothRoot "windows-x86_64-cpu") -Variant "windows-x86_64-cpu"
    $cpuRequirement = [pscustomobject]@{ platformVariant = "windows-x86_64-cpu"; runtimePackId = $cpuId; thirdPartyLockSha256 = $cpuEntry.thirdPartyLockSha256; runtimeRequirementsSha256 = $cpuEntry.runtimeRequirementsSha256; nativeAbi = $cpuEntry.nativeAbi }
    $selected = Resolve-MaviVisionRuntimeBundleEntry -Root $bothRoot -Requirement $cpuRequirement -Required
    Assert-Equal $selected.SourceRoot ([IO.Path]::GetFullPath((Join-Path $bothRoot "windows-x86_64-cpu"))) "the CPU Runtime Pack directory"

    # ------------------------------------------------------------------ preflight refusals before any install
    function Assert-RefusedBeforeInstall {
        param([Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][object]$Source, [Parameter(Mandatory = $true)][string]$Binding, [Parameter(Mandatory = $true)][string]$Fragment)
        $caseStore = Join-Path $tempRoot ("store-" + $Name)
        Reset-Calls
        Assert-Throws { Invoke-VisionSetup -Source $Source -Binding $Binding -StoreRoot $caseStore } $Fragment
        Assert-Equal $script:Calls.Count 0 "$Name must be refused before any installer runs"
        if (Test-Path -LiteralPath $caseStore) { throw "$Name created the Model Pack store before preflight passed." }
    }

    # Binding SHA-256: the kit was assembled for another binding.
    $mismatchRoot = Join-Path $tempRoot "mismatch"
    $mismatchBinding = New-TwoPackBinding -Directory (Join-Path $mismatchRoot "binding")
    $mismatchKit = New-Kit -Root $mismatchRoot -Binding $mismatchBinding
    $changedBinding = New-TwoPackBinding -Directory (Join-Path $mismatchRoot "changed") -SecondQualification "embedding-fixture-v2"
    Assert-RefusedBeforeInstall -Name "binding-mismatch" -Source ([pscustomobject]@{ Kind = "kit"; Root = $mismatchKit; Origin = "bundle" }) -Binding $changedBinding -Fragment "kit_binding_mismatch"

    # Missing Windows CPU Runtime Pack.
    $noRuntimeRoot = Join-Path $tempRoot "no-runtime"
    $noRuntimeBinding = New-TwoPackBinding -Directory (Join-Path $noRuntimeRoot "binding")
    $noRuntimeKit = New-Kit -Root $noRuntimeRoot -Binding $noRuntimeBinding -Runtimes @("windows-x86_64-cpu", "windows-x86_64-cuda")
    Edit-Inventory -Kit $noRuntimeKit -Change { param($inventory) $inventory.runtimePacks = @($inventory.runtimePacks | Where-Object { $_.platformVariant -ne "windows-x86_64-cpu" }) }
    Assert-RefusedBeforeInstall -Name "no-runtime" -Source ([pscustomobject]@{ Kind = "kit"; Root = $noRuntimeKit; Origin = "bundle" }) -Binding $noRuntimeBinding -Fragment "kit_incomplete:$cpuId"

    # Missing any one bound Model Pack; the other one is present and must not be installed either.
    foreach ($missing in @($modelA, $modelB)) {
        $caseRoot = Join-Path $tempRoot ("no-model-" + $missing.Substring($missing.Length - 1))
        $caseBinding = New-TwoPackBinding -Directory (Join-Path $caseRoot "binding")
        $caseKit = New-Kit -Root $caseRoot -Binding $caseBinding
        Edit-Inventory -Kit $caseKit -Change { param($inventory) $inventory.modelPacks = @($inventory.modelPacks | Where-Object { $_.modelPackId -ne $missing }) }.GetNewClosure()
        Assert-RefusedBeforeInstall -Name ("no-model-" + $missing.Substring($missing.Length - 1)) -Source ([pscustomobject]@{ Kind = "kit"; Root = $caseKit; Origin = "bundle" }) -Binding $caseBinding -Fragment "kit_incomplete:$missing"
    }

    # Unbound component in the kit: assembled when the binding still named a third pack.
    $unboundRoot = Join-Path $tempRoot "unbound"
    $unboundBinding = New-TwoPackBinding -Directory (Join-Path $unboundRoot "binding")
    $unboundKit = New-Kit -Root $unboundRoot -Binding $unboundBinding
    $unboundModel = Join-Path (Join-Path $unboundRoot "sources") "model-unbound"
    New-ModelPack -Root $unboundModel -ModelPackId $modelUnbound -Directory "fixture-unbound" -CapabilityId "detector"
    $storedUnbound = Join-Path $unboundKit (Join-Path "vision" (Join-Path "models" $modelUnbound))
    Copy-Item -LiteralPath $unboundModel -Destination $storedUnbound -Recurse
    $unboundManifest = Read-JsonFile (Join-Path $storedUnbound "model-pack-manifest.json")
    Edit-Inventory -Kit $unboundKit -Change {
        param($inventory)
        $material = [ordered]@{ modelPackId = $modelUnbound; modelId = $unboundManifest.modelId; modelVersion = $unboundManifest.modelVersion; capabilityIds = @($unboundManifest.capabilityIds); artifacts = @($unboundManifest.artifacts | ForEach-Object { [ordered]@{ relativePath = $_.relativePath; sizeBytes = $_.sizeBytes; sha256 = $_.sha256; artifactRole = $_.artifactRole } }) }
        $inventory.modelPacks = @($inventory.modelPacks) + @([pscustomobject][ordered]@{ modelPackId = $modelUnbound; relativePath = "vision/models/$modelUnbound"; materialIdentity = $material })
    }.GetNewClosure()
    Assert-RefusedBeforeInstall -Name "unbound" -Source ([pscustomobject]@{ Kind = "kit"; Root = $unboundKit; Origin = "bundle" }) -Binding $unboundBinding -Fragment "kit_unbound_component:$modelUnbound"

    # A Runtime Bundle whose CPU pack is not the bound one.
    $foreignRoot = Join-Path $tempRoot "foreign-runtime"
    $foreignEntry = [pscustomobject]@{ runtimePackId = ("mavi-runtime-v2-" + ("f" * 64)); nativeAbi = $cpuEntry.nativeAbi; thirdPartyLockSha256 = $cpuEntry.thirdPartyLockSha256; runtimeRequirementsSha256 = $cpuEntry.runtimeRequirementsSha256 }
    New-RuntimePack -Root (Join-Path $foreignRoot "windows-x86_64-cpu") -Variant "windows-x86_64-cpu" -Entry $foreignEntry
    Assert-RefusedBeforeInstall -Name "foreign-runtime" -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $foreignRoot; Origin = "explicit" }) -Binding $repositoryBinding -Fragment "kit_unbound_component:mavi-runtime-v2-ffff"

    # A Runtime Bundle carries no Model Pack: an uninstalled bound pack fails before the runtime is installed.
    $bundleOnly = Join-Path $tempRoot "runtime-only"
    New-RuntimePack -Root (Join-Path $bundleOnly "windows-x86_64-cpu") -Variant "windows-x86_64-cpu"
    $runtimeOnlyBinding = New-TwoPackBinding -Directory (Join-Path $bundleOnly "binding")
    Assert-RefusedBeforeInstall -Name "runtime-only" -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $bundleOnly; Origin = "explicit" }) -Binding $runtimeOnlyBinding -Fragment "kit_incomplete:${modelA}: the Runtime Bundle"
    # ...and with the bound packs already installed the Runtime Bundle path installs only the runtime.
    Reset-Calls
    $manual = Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $bundleOnly; Origin = "explicit" }) -Binding $happyBinding -StoreRoot $happyStore -Compose
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "assert") "a Runtime Bundle over already installed Model Packs"
    Assert-Equal $manual.Status "ready" "the Runtime Bundle path"
    # Pre-mutation boundary for a Runtime Bundle source: the Runtime Pack comes
    # from the bundle, and both bound Model Packs are relied on from the
    # installed store. Each damage below leaves the pack's manifest and
    # model-install.json otherwise valid (status "installed"); preflight must
    # still refuse it, and neither installer may run.
    $damageCases = [ordered]@{
        "wrong-size"      = { param($pack) Write-Utf8File -Path (Join-Path $pack "weights.bin") -Text "corrupted" }
        "hash-same-size"  = { param($pack) $path = Join-Path $pack "weights.bin"; $bytes = [IO.File]::ReadAllBytes($path); $bytes[0] = [byte](($bytes[0] + 1) % 256); [IO.File]::WriteAllBytes($path, $bytes) }
        "missing"         = { param($pack) Remove-Item -LiteralPath (Join-Path $pack "weights.bin") -Force }
        "undeclared-file" = { param($pack) Write-Utf8File -Path (Join-Path $pack "extra.bin") -Text "not declared" }
        "state-unbound"   = { param($pack) $statePath = Join-Path $pack "model-install.json"; $state = Read-JsonFile $statePath; $state.modelPackManifestSha256 = ("0" * 64); Write-JsonFile -Path $statePath -Value $state }
    }
    foreach ($damage in $damageCases.Keys) {
        $damagedStore = Join-Path $tempRoot ("store-damaged-" + $damage)
        Copy-Item -LiteralPath $happyStore -Destination $damagedStore -Recurse
        $damagedPack = Join-Path $damagedStore "fixture-embedding"
        & $damageCases[$damage] $damagedPack
        $status = @((Resolve-MaviVisionBoundModelPacks -StoreRoot $damagedStore -CapabilityBindings @([pscustomobject]@{ CapabilityId = "embedding"; ModelPackId = $modelB })).ModelPacks)[0].Status
        Assert-Equal $status "installed" "the damaged pack ($damage) still looks installed to the store lookup"
        Reset-Calls
        Assert-Throws { Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $bundleOnly; Origin = "explicit" }) -Binding $happyBinding -StoreRoot $damagedStore -Compose } "kit_incomplete:${modelB}: the installed Model Pack"
        Assert-Equal @($script:Calls | Where-Object { $_ -like "runtime:*" }).Count 0 "Runtime Pack installer calls with a damaged installed Model Pack ($damage)"
        Assert-Equal @($script:Calls | Where-Object { $_ -like "model:*" }).Count 0 "Model Pack installer calls with a damaged installed Model Pack ($damage)"
        Assert-Equal $script:Calls.Count 0 "a damaged installed Model Pack ($damage) must be refused in preflight"
    }

    # The Runtime Bundle's own packs are proven in preflight too: a damaged CPU
    # pack, or a damaged optional CUDA pack that would be installed last, fails
    # before the CPU Runtime Pack is installed.
    foreach ($damagedVariant in @("windows-x86_64-cpu", "windows-x86_64-cuda")) {
        $damagedBundle = Join-Path $tempRoot ("bundle-damaged-" + $damagedVariant)
        New-RuntimePack -Root (Join-Path $damagedBundle "windows-x86_64-cpu") -Variant "windows-x86_64-cpu"
        New-RuntimePack -Root (Join-Path $damagedBundle "windows-x86_64-cuda") -Variant "windows-x86_64-cuda"
        Write-Utf8File -Path (Join-Path $damagedBundle (Join-Path $damagedVariant "payload.bin")) -Text "tampered-runtime-payload"
        Reset-Calls
        Assert-Throws { Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $damagedBundle; Origin = "explicit" }) -Binding $happyBinding -StoreRoot $happyStore -Compose } "component_artifact_mismatch"
        Assert-Equal $script:Calls.Count 0 "a damaged $damagedVariant Runtime Pack in a Runtime Bundle must be refused before any installer runs"
    }
    # ...and an intact bundle with both variants installs CPU, then CUDA.
    $intactBundle = Join-Path $tempRoot "bundle-intact-both"
    New-RuntimePack -Root (Join-Path $intactBundle "windows-x86_64-cpu") -Variant "windows-x86_64-cpu"
    New-RuntimePack -Root (Join-Path $intactBundle "windows-x86_64-cuda") -Variant "windows-x86_64-cuda"
    Reset-Calls
    [void](Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $intactBundle; Origin = "explicit" }) -Binding $happyBinding -StoreRoot $happyStore -Compose)
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "runtime:$cudaId", "assert") "an intact two-variant Runtime Bundle"

    # A flat Runtime Bundle (the CPU pack at its root) offers no CUDA pack: the
    # optional CUDA lookup must not take the CPU manifest it finds there.
    $flatBundle = Join-Path $tempRoot "flat-runtime"
    New-RuntimePack -Root $flatBundle -Variant "windows-x86_64-cpu"
    Reset-Calls
    $flat = Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "runtime-bundle"; Root = $flatBundle; Origin = "explicit" }) -Binding $happyBinding -StoreRoot $happyStore -Compose
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "assert") "a flat Runtime Bundle"
    Assert-Equal @($flat.OptionalRuntimePackIds).Count 0 "a flat CPU bundle carries no CUDA pack"

    # A tampered kit fails the existing store verifier in preflight.
    $tamperRoot = Join-Path $tempRoot "tamper"
    $tamperBinding = New-TwoPackBinding -Directory (Join-Path $tamperRoot "binding")
    $tamperKit = New-Kit -Root $tamperRoot -Binding $tamperBinding
    Write-Utf8File -Path (Join-Path $tamperKit (Join-Path "vision" (Join-Path "models" (Join-Path $modelB (Join-Path "fixture-embedding" "weights.bin"))))) -Text "tampered"
    Assert-RefusedBeforeInstall -Name "tamper" -Source ([pscustomobject]@{ Kind = "kit"; Root = $tamperKit; Origin = "bundle" }) -Binding $tamperBinding -Fragment "component_artifact_mismatch"

    # ------------------------------------------------------------------ partial install, rerun, readiness
    $partialRoot = Join-Path $tempRoot "partial"
    $partialBinding = New-TwoPackBinding -Directory (Join-Path $partialRoot "binding")
    $partialKit = New-Kit -Root $partialRoot -Binding $partialBinding
    $partialStore = Join-Path $partialRoot "store"
    $partialSource = [pscustomobject]@{ Kind = "kit"; Root = $partialKit; Origin = "bundle" }
    Reset-Calls
    $partialFailure = $null
    try { [void](Invoke-VisionSetup -Source $partialSource -Binding $partialBinding -StoreRoot $partialStore -FailModelId $modelB -Compose) }
    catch { $partialFailure = $_.Exception.Message }
    if ($null -eq $partialFailure) { throw "A failing second Model Pack must fail Setup." }
    foreach ($fragment in @("Vision Model Pack '$modelB' failed to install", "installed so far: $cpuId, $modelA", "model_pack_stage_failed")) {
        if ($partialFailure -notlike "*$fragment*") { throw "The partial-install failure must say '$fragment'; got '$partialFailure'." }
    }
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "model:$modelA", "model:$modelB") "no readiness check after a failed install"
    $keptState = Read-JsonFile (Join-Path $partialStore (Join-Path "fixture-detector" "model-install.json"))
    Assert-Equal $keptState.modelPackId $modelA "the earlier valid Model Pack is left installed"
    if (Test-Path -LiteralPath (Join-Path $partialStore "fixture-embedding")) { throw "The failed Model Pack must not appear installed." }
    # The partial store is not a READY composition by the launcher's own check.
    Assert-Throws { Assert-TestComposition -StoreRoot $partialStore -Binding $partialBinding } "launch_model_pack_not_installed"
    # The corrected rerun converges: A is reused, B is installed, READY.
    Reset-Calls
    $recovered = Invoke-VisionSetup -Source $partialSource -Binding $partialBinding -StoreRoot $partialStore -Compose
    Assert-Equal $recovered.Status "ready" "the corrected rerun"
    Assert-Equal $script:Calls @("preflight-ok", "runtime:$cpuId", "model:$modelA", "model:$modelB", "assert") "the rerun installs the complete set again"

    # Installs that all succeed but do not form the bound composition are not READY.
    Reset-Calls
    Assert-Throws {
        Invoke-VisionSetup -Source $partialSource -Binding $partialBinding -StoreRoot $partialStore -Compose -InstalledRuntimePackId $cudaId
    } "Vision composition is not ready"
    Assert-Equal $script:Calls[$script:Calls.Count - 1] "assert" "the readiness check ran and refused"

    # A v1 install state in the destination is refused by the installer; no fallback.
    $legacyStateRoot = Join-Path $tempRoot "legacy-state"
    $legacyStateBinding = New-TwoPackBinding -Directory (Join-Path $legacyStateRoot "binding")
    $legacyStateKit = New-Kit -Root $legacyStateRoot -Binding $legacyStateBinding
    $legacyStore = Join-Path $legacyStateRoot "store"
    Write-JsonFile -Path (Join-Path $legacyStore (Join-Path "fixture-detector" "model-install.json")) -Value ([ordered]@{ schemaVersion = "mavi-vision-model-install-v1" })
    Reset-Calls
    Assert-Throws { Invoke-VisionSetup -Source ([pscustomobject]@{ Kind = "kit"; Root = $legacyStateKit; Origin = "bundle" }) -Binding $legacyStateBinding -StoreRoot $legacyStore } "model_install_state_v1_rejected"
    if ($script:Calls -contains "assert") { throw "A refused v1 state must not reach the readiness check." }

    # ------------------------------------------------------------------ non-promotion and identity
    # Setup reads the binding; it never writes it, and never requires CUDA.
    Assert-Equal (Get-FileSha256 $repositoryBinding) $repositoryBindingSha "the repository binding bytes"
    $cpuOnlyPlan = Invoke-MaviVisionComponentPreflight -Source $happySource -RepositoryRoot $repoRoot -Python $Python -ModelStoreRoot $happyStore -ComponentBindingPath $happyBinding
    Assert-Equal @($cpuOnlyPlan.OptionalRuntimePacks).Count 0 "an absent CUDA pack is not required"
    Assert-Equal $cpuOnlyPlan.RuntimePack.Variant "windows-x86_64-cpu" "the mandatory Setup variant"

    # The installers ran from inside the Setup module many times above; this
    # script's own module functions must still resolve, as Setup-MAVI's do.
    foreach ($command in @("Get-MaviVisionBindingRole", "Resolve-MaviVisionBoundModelPacks", "Write-MaviSetupStatus", "Invoke-MaviVisionComponentInstallation")) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "Running the installers from the Setup orchestration unloaded '$command' from the caller." }
    }

    Write-Host "MAVI Vision Setup contracts passed." -ForegroundColor Green
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
