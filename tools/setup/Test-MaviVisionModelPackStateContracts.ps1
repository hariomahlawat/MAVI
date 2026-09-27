[CmdletBinding()]
param()

# Model Pack v2 installation and store contracts (S2a plan §5.4, §7 items 2-4,
# §13.1 item 5b, P-10, P-15).
#
# Runs under Windows PowerShell 5.1 (Task 17) and PowerShell 7 on any OS: every
# path is built with Join-Path, nothing touches the Machine environment
# (the installer runs with -NoMachineEnvironment) and all state lives in a
# temporary store that is removed at the end.
#
# What this proves, and what it does not:
#   * Install-MaviVisionModelPack.ps1 v2 installs a builder-shaped v2 pack into
#     a shared store, per pack, writing a v2 model-install.json that binds the
#     byte-copied manifest by SHA-256 and records every artefact SHA-256, and
#     ships the licence notice in the pack directory.
#   * The launcher's store lookup and Assert-MaviVisionWorkerComponentCompatibility
#     accept that installed pack against the REAL committed v2 binding: the
#     fixture pack claims the binding's detector modelPackId and the binding's
#     windows-x86_64-cpu Runtime Pack identity is used for the runtime side.
#   * NOT proven here: that the fixture's modelPackId is the P-3 derivation of
#     its artefacts (the launcher never derives it; the Python resolver does and
#     would reject this fixture), or that the fixture bytes are RTMDet's (the
#     checkpoint is not in Git). Compatibility compares installed state against
#     installed manifest against binding, which is exactly what the launcher
#     checks before the worker starts.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Integrity.psm1") -Force

$repoRoot = [IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot "..") ".."))
$installer = Join-Path $PSScriptRoot "Install-MaviVisionModelPack.ps1"
$bindingPath = Join-Path $repoRoot (Join-Path "src" (Join-Path "vision" (Join-Path "config" (Join-Path "components" "phase1-bindings-v2.json"))))

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

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-Utf8File {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text)
    $directory = Split-Path $Path -Parent
    if ($directory) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    [IO.File]::WriteAllBytes($Path, (New-Object Text.UTF8Encoding -ArgumentList $false).GetBytes($Text))
}

function ConvertTo-FixtureJsonString {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
    return '"' + $Value.Replace('\', '\\').Replace('"', '\"') + '"'
}

# The manifest text is written exactly as tools/vision/build_model_pack.py
# serialises it: json.dumps(sort_keys=True, separators=(",", ":"),
# ensure_ascii=True) + "\n" -- keys in sorted order at both levels, no spaces,
# ASCII only (every fixture value here is plain ASCII, so no escape beyond '"'
# and '\' can arise), artefacts sorted by relativePath.
function New-FixtureModelPack {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$PackDirectory,
        [Parameter(Mandatory = $true)][string]$ModelPackId,
        [Parameter(Mandatory = $true)][string]$Seed,
        [string]$SchemaVersion = "mavi-vision-model-pack-v2",
        [switch]$OmitLicenceNotice,
        [string]$StrayDirectory = ""
    )
    if (Test-Path -LiteralPath $Root) { Remove-Item -LiteralPath $Root -Recurse -Force }
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    $specs = New-Object System.Collections.Generic.List[object]
    $specs.Add([pscustomobject]@{ Role = "checkpoint"; Path = "$PackDirectory/model.pth"; Text = "fixture checkpoint bytes $Seed`n" })
    if (-not $OmitLicenceNotice) {
        $specs.Add([pscustomobject]@{ Role = "licence-notice"; Path = "$PackDirectory/LICENSE"; Text = "Apache License 2.0 fixture notice $Seed`n" })
    }
    $specs.Add([pscustomobject]@{ Role = "resolved-config"; Path = "$PackDirectory/configs/model_resolved.py"; Text = "# resolved fixture config $Seed`n" })
    if ($StrayDirectory) {
        $specs.Add([pscustomobject]@{ Role = "stray"; Path = "$StrayDirectory/stray.bin"; Text = "stray $Seed`n" })
    }
    $artifacts = New-Object System.Collections.Generic.List[object]
    foreach ($spec in $specs) {
        $path = Join-Path $Root ($spec.Path.Replace('/', [IO.Path]::DirectorySeparatorChar))
        Write-Utf8File -Path $path -Text $spec.Text
        $artifacts.Add([pscustomobject]@{
            artifactRole = $spec.Role
            relativePath = $spec.Path
            sha256 = Get-FileSha256 $path
            sizeBytes = [long](Get-Item -LiteralPath $path).Length
        })
    }
    $paths = [string[]]@($artifacts | ForEach-Object { $_.relativePath })
    [Array]::Sort($paths, [StringComparer]::Ordinal)
    $artifactTexts = @(foreach ($relative in $paths) {
        $artifact = @($artifacts | Where-Object { $_.relativePath -ceq $relative })[0]
        '{"artifactRole":' + (ConvertTo-FixtureJsonString $artifact.artifactRole) + ',"relativePath":' + (ConvertTo-FixtureJsonString $artifact.relativePath) + ',"sha256":' + (ConvertTo-FixtureJsonString $artifact.sha256) + ',"sizeBytes":' + ([long]$artifact.sizeBytes).ToString([Globalization.CultureInfo]::InvariantCulture) + '}'
    })
    $text = '{"artifacts":[' + ($artifactTexts -join ",") + '],"assembledFromCommit":' + (ConvertTo-FixtureJsonString ("1" * 40)) + ',"capabilityIds":["detector"],"modelId":"fixture-model-' + $Seed + '","modelPackId":' + (ConvertTo-FixtureJsonString $ModelPackId) + ',"modelVersion":"1.0.0","schemaVersion":' + (ConvertTo-FixtureJsonString $SchemaVersion) + '}' + "`n"
    Write-Utf8File -Path (Join-Path $Root "model-pack-manifest.json") -Text $text
    return [pscustomobject]@{ Root = $Root; PackDirectory = $PackDirectory; ModelPackId = $ModelPackId; Artifacts = $artifacts.ToArray() }
}

function Get-TreeFingerprint {
    # Every file under a directory, by relative path, with its SHA-256.
    param([Parameter(Mandatory = $true)][string]$Root)
    $separator = [IO.Path]::DirectorySeparatorChar
    $prefix = ([IO.Path]::GetFullPath($Root)).TrimEnd($separator) + $separator
    $lines = [string[]]@(Get-ChildItem -LiteralPath $Root -Recurse -File -Force | ForEach-Object {
        $_.FullName.Substring($prefix.Length).Replace([string]$separator, "/") + "=" + (Get-FileSha256 $_.FullName)
    })
    [Array]::Sort($lines, [StringComparer]::Ordinal)
    return ($lines -join "`n")
}

function Install-Fixture {
    param([Parameter(Mandatory = $true)][string]$PackRoot, [Parameter(Mandatory = $true)][string]$StoreRoot)
    & $installer -PackRoot $PackRoot -StoreRoot $StoreRoot -NoMachineEnvironment 6>$null | Out-Null
}

# --- Unit: manifest, state and reuse -------------------------------------------
$unitArtifacts = @(
    [pscustomobject]@{ artifactRole = "licence-notice"; relativePath = "unit-pack/LICENSE"; sha256 = ("a" * 64); sizeBytes = 10 },
    [pscustomobject]@{ artifactRole = "checkpoint"; relativePath = "unit-pack/model.pth"; sha256 = ("b" * 64); sizeBytes = 20 }
)
$unitManifest = [pscustomobject][ordered]@{
    artifacts = $unitArtifacts
    assembledFromCommit = ("1" * 40)
    capabilityIds = @("detector")
    modelId = "unit-model"
    modelPackId = ("mavi-model-v2-" + ("a" * 64))
    modelVersion = "1.0.0"
    schemaVersion = "mavi-vision-model-pack-v2"
}
[void](Assert-MaviVisionModelPackManifest -Manifest $unitManifest)
if ((Get-MaviVisionModelPackDirectory -Manifest $unitManifest) -cne "unit-pack") { throw "Pack directory was not the shared first segment." }
$unitManifestSha = "d" * 64
$unitState = New-MaviVisionModelInstallState -Manifest $unitManifest -ModelPackManifestSha256 $unitManifestSha -InstallRoot (Join-Path ([IO.Path]::GetTempPath()) "store")
if ([string]$unitState.schemaVersion -cne "mavi-vision-model-install-v2") { throw "Vision model state did not use the v2 schema." }
$unitStateFields = @($unitState.PSObject.Properties | ForEach-Object { $_.Name })
if (($unitStateFields -join ",") -cne "schemaVersion,modelPackId,modelId,capabilityIds,artifactSha256,modelPackManifestSha256,installedAtUtc,installRoot") { throw "v2 install state fields are not the plan §5.4 set: $($unitStateFields -join ',')" }
if ($unitState.PSObject.Properties["checkpointSha256"] -or $unitState.PSObject.Properties["modelRoot"]) { throw "v2 install state still carries v1 fields." }
if (-not ($unitState.capabilityIds -is [array]) -or ($unitState.capabilityIds -join ",") -cne "detector") { throw "v2 install state capabilityIds is not the manifest's list." }
if ([string]$unitState.artifactSha256.checkpoint -cne ("b" * 64) -or [string]$unitState.artifactSha256."licence-notice" -cne ("a" * 64)) { throw "v2 install state artifactSha256 does not record every role." }
if (-not (Test-MaviVisionModelPackReuse -InstalledState $unitState -Manifest $unitManifest -ModelPackManifestSha256 $unitManifestSha)) { throw "Identical Model Pack was not reusable." }

$sourceOnly = $unitManifest.PSObject.Copy()
$sourceOnly.assembledFromCommit = "2" * 40
if (-not (Test-MaviVisionModelPackReuse -InstalledState $unitState -Manifest $sourceOnly -ModelPackManifestSha256 $unitManifestSha)) { throw "Assembly provenance incorrectly invalidated Model Pack reuse." }
$changedId = $unitManifest.PSObject.Copy()
$changedId.modelPackId = "mavi-model-v2-" + ("e" * 64)
if (Test-MaviVisionModelPackReuse -InstalledState $unitState -Manifest $changedId -ModelPackManifestSha256 $unitManifestSha) { throw "Different Model Pack ID was incorrectly reusable." }
$changedArtifact = $unitManifest.PSObject.Copy()
$changedArtifact.artifacts = @(
    [pscustomobject]@{ artifactRole = "licence-notice"; relativePath = "unit-pack/LICENSE"; sha256 = ("a" * 64); sizeBytes = 10 },
    [pscustomobject]@{ artifactRole = "checkpoint"; relativePath = "unit-pack/model.pth"; sha256 = ("c" * 64); sizeBytes = 20 }
)
if (Test-MaviVisionModelPackReuse -InstalledState $unitState -Manifest $changedArtifact -ModelPackManifestSha256 $unitManifestSha) { throw "A changed artefact SHA-256 was incorrectly reusable." }
if (Test-MaviVisionModelPackReuse -InstalledState $unitState -Manifest $unitManifest -ModelPackManifestSha256 ("e" * 64)) { throw "A state that does not bind the installed manifest was reusable." }
$v1State = [pscustomobject]@{ schemaVersion = "mavi-vision-model-install-v1"; modelPackId = $unitManifest.modelPackId; modelPackManifestSha256 = $unitManifestSha; modelId = "unit-model"; checkpointSha256 = ("b" * 64); resolvedConfigSha256 = ("c" * 64); installedAtUtc = "2026-09-17T00:00:00Z"; modelRoot = "C:\legacy" }
if (Test-MaviVisionModelPackReuse -InstalledState $v1State -Manifest $unitManifest -ModelPackManifestSha256 $unitManifestSha) { throw "A v1 install state was reusable." }

# Manifest shape refusals: each is one field away from the valid unit manifest.
$v1Pack = [pscustomobject]@{ schemaVersion = "mavi-vision-model-pack-v1"; modelPackId = ("mavi-model-v1-" + ("a" * 64)); modelId = "unit-model"; checkpointSha256 = ("b" * 64); resolvedConfigSha256 = ("c" * 64); assembledFromCommit = ("1" * 40); artifacts = @() }
Assert-Throws -MessageFragment "Unsupported vision model manifest schema 'mavi-vision-model-pack-v1'" -Script { Assert-MaviVisionModelPackManifest -Manifest $v1Pack }
$v1Id = $unitManifest.PSObject.Copy(); $v1Id.modelPackId = "mavi-model-v1-" + ("a" * 64)
Assert-Throws -MessageFragment "Model Pack ID is invalid" -Script { Assert-MaviVisionModelPackManifest -Manifest $v1Id }
$extraField = $unitManifest.PSObject.Copy(); $extraField | Add-Member -NotePropertyName checkpointSha256 -NotePropertyValue ("b" * 64)
Assert-Throws -MessageFragment "unexpected field 'checkpointSha256'" -Script { Assert-MaviVisionModelPackManifest -Manifest $extraField }
$scalarCapabilities = $unitManifest.PSObject.Copy(); $scalarCapabilities.capabilityIds = "detector"
Assert-Throws -MessageFragment "capabilityIds" -Script { Assert-MaviVisionModelPackManifest -Manifest $scalarCapabilities }
$twoDirectories = $unitManifest.PSObject.Copy()
$twoDirectories.artifacts = @(
    [pscustomobject]@{ artifactRole = "licence-notice"; relativePath = "other-pack/LICENSE"; sha256 = ("a" * 64); sizeBytes = 10 },
    [pscustomobject]@{ artifactRole = "checkpoint"; relativePath = "unit-pack/model.pth"; sha256 = ("b" * 64); sizeBytes = 20 }
)
Assert-Throws -MessageFragment "share one pack directory" -Script { Assert-MaviVisionModelPackManifest -Manifest $twoDirectories }
foreach ($unsafe in @("../escape/model.pth", "unit-pack/../x", "model.pth", "/unit-pack/model.pth", "unit-pack\model.pth", "C:/unit-pack/model.pth", ".unit-pack/model.pth")) {
    $unsafeManifest = $unitManifest.PSObject.Copy()
    $unsafeManifest.artifacts = @([pscustomobject]@{ artifactRole = "licence-notice"; relativePath = $unsafe; sha256 = ("a" * 64); sizeBytes = 10 })
    Assert-Throws -MessageFragment "Unsafe artifact path" -Script { Assert-MaviVisionModelPackManifest -Manifest $unsafeManifest }
}
$noLicence = $unitManifest.PSObject.Copy()
$noLicence.artifacts = @([pscustomobject]@{ artifactRole = "checkpoint"; relativePath = "unit-pack/model.pth"; sha256 = ("b" * 64); sizeBytes = 20 })
Assert-Throws -MessageFragment "licence notice" -Script { Assert-MaviVisionModelPackManifest -Manifest $noLicence }
$reserved = $unitManifest.PSObject.Copy()
$reserved.artifacts = @(
    [pscustomobject]@{ artifactRole = "licence-notice"; relativePath = "unit-pack/LICENSE"; sha256 = ("a" * 64); sizeBytes = 10 },
    [pscustomobject]@{ artifactRole = "checkpoint"; relativePath = "unit-pack/model-install.json"; sha256 = ("b" * 64); sizeBytes = 20 }
)
Assert-Throws -MessageFragment "reserved" -Script { Assert-MaviVisionModelPackManifest -Manifest $reserved }
$stringSize = $unitManifest.PSObject.Copy()
$stringSize.artifacts = @([pscustomobject]@{ artifactRole = "licence-notice"; relativePath = "unit-pack/LICENSE"; sha256 = ("a" * 64); sizeBytes = "10" })
Assert-Throws -MessageFragment "sizeBytes" -Script { Assert-MaviVisionModelPackManifest -Manifest $stringSize }

# --- Store: install, per-pack isolation, discovery and compatibility ----------
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("mavi-model-store-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
try {
    $binding = Read-JsonFile $bindingPath
    $bindingRole = Get-MaviVisionBindingRole -Binding $binding -RoleId "vision"
    $detectorBindings = @($bindingRole.CapabilityBindings | Where-Object { $_.CapabilityId -ceq "detector" })
    if ($detectorBindings.Count -ne 1) { throw "The committed v2 binding must bind the detector capability of role vision exactly once." }
    $boundModelPackId = [string]$detectorBindings[0].ModelPackId
    $runtimeRequirement = Get-MaviVisionBindingRuntimeRequirement -BindingRole $bindingRole -Variant "windows-x86_64-cpu"
    if ($null -eq $runtimeRequirement) { throw "The committed v2 binding declares no windows-x86_64-cpu Runtime Pack." }
    $runtimeManifest = [pscustomobject]@{ schemaVersion = "mavi-vision-runtime-pack-v2"; runtimePackId = [string]$runtimeRequirement.runtimePackId; platformVariant = "windows-x86_64-cpu"; pythonVersion = "3.12.10"; nativeAbi = [string]$runtimeRequirement.nativeAbi; thirdPartyLockSha256 = [string]$runtimeRequirement.thirdPartyLockSha256; runtimeRequirementsSha256 = [string]$runtimeRequirement.runtimeRequirementsSha256; assembledFromCommit = ("1" * 40); artifacts = @() }
    $runtimeState = [pscustomobject]@{ schemaVersion = "mavi-vision-runtime-install-v2"; runtimePackId = $runtimeManifest.runtimePackId; runtimePackManifestSha256 = ("d" * 64); thirdPartyLockSha256 = $runtimeManifest.thirdPartyLockSha256; runtimeRequirementsSha256 = $runtimeManifest.runtimeRequirementsSha256; platformVariant = $runtimeManifest.platformVariant; pythonVersion = $runtimeManifest.pythonVersion; nativeAbi = $runtimeManifest.nativeAbi }
    function Invoke-Compatibility {
        param([Parameter(Mandatory = $true)][object[]]$ModelPacks, [object]$State = $runtimeState, [object]$Manifest = $runtimeManifest)
        return Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $State -RuntimeManifest $Manifest -RequiredRuntimePackId ([string]$runtimeRequirement.runtimePackId) -RequiredThirdPartyLockSha256 ([string]$runtimeRequirement.thirdPartyLockSha256) -RequiredRuntimeRequirementsSha256 ([string]$runtimeRequirement.runtimeRequirementsSha256) -RequiredModelPacks $ModelPacks
    }

    $store = Join-Path $tempRoot "store"
    $packADirectory = "rtmdet-m-coco-phase1-v1"
    $packA = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-a") -PackDirectory $packADirectory -ModelPackId $boundModelPackId -Seed "a"
    $packASourceTree = Get-TreeFingerprint $packA.Root

    # An absent store and an empty store both mean "not installed".
    $absent = Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings)
    if ($absent.LegacyInstallation -or @($absent.ModelPacks).Count -ne 1 -or $absent.ModelPacks[0].Status -cne "not-installed") { throw "An absent store must report the bound pack as not-installed." }

    # Installability (§13.1 5b): install pack A into a temporary shared store.
    Install-Fixture -PackRoot $packA.Root -StoreRoot $store
    $packAPath = Join-Path $store $packADirectory
    $installedManifestPath = Join-Path $packAPath "model-pack-manifest.json"
    $installedStatePath = Join-Path $packAPath "model-install.json"
    if ((Get-FileSha256 $installedManifestPath) -cne (Get-FileSha256 (Join-Path $packA.Root "model-pack-manifest.json"))) { throw "Installed model-pack-manifest.json is not a byte copy of the pack's." }
    if ((Get-TreeFingerprint $packA.Root) -cne $packASourceTree) { throw "Installing a pack modified its source." }
    $stateA = Read-JsonFile $installedStatePath
    $stateAFields = [string[]]@($stateA.PSObject.Properties | ForEach-Object { $_.Name })
    [Array]::Sort($stateAFields, [StringComparer]::Ordinal)
    if (($stateAFields -join ",") -cne "artifactSha256,capabilityIds,installRoot,installedAtUtc,modelId,modelPackId,modelPackManifestSha256,schemaVersion") { throw "Installed model-install.json fields are not the v2 set: $($stateAFields -join ',')" }
    if ([string]$stateA.schemaVersion -cne "mavi-vision-model-install-v2") { throw "Installed state is not mavi-vision-model-install-v2." }
    if ([string]$stateA.modelPackId -cne $boundModelPackId -or [string]$stateA.modelId -cne "fixture-model-a") { throw "Installed state identity is not the pack's." }
    if (-not ($stateA.capabilityIds -is [array]) -or (@($stateA.capabilityIds) -join ",") -cne "detector") { throw "Installed state capabilityIds is not the pack's list." }
    if ([string]$stateA.modelPackManifestSha256 -cne (Get-FileSha256 $installedManifestPath)) { throw "Installed state does not bind the installed manifest bytes." }
    if ([string]$stateA.installRoot -cne [IO.Path]::GetFullPath($store)) { throw "Installed state installRoot is not the store root." }
    $recordedRoles = @($stateA.artifactSha256.PSObject.Properties | ForEach-Object { $_.Name })
    if ($recordedRoles.Count -ne 3) { throw "Installed state must record exactly the pack's three artefact roles." }
    foreach ($artifact in $packA.Artifacts) {
        $installedPath = Join-Path $store ($artifact.relativePath.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $installedPath -PathType Leaf)) { throw "Installed artefact is missing at <store>/<relativePath>: $($artifact.relativePath)" }
        if ((Get-FileSha256 $installedPath) -cne $artifact.sha256) { throw "Installed artefact bytes differ: $($artifact.relativePath)" }
        if ([string]$stateA.artifactSha256.PSObject.Properties[$artifact.artifactRole].Value -cne $artifact.sha256) { throw "Installed state artifactSha256 is wrong for role $($artifact.artifactRole)." }
    }
    # P-15: the licence notice ships in the installed pack directory.
    $licencePath = Join-Path $packAPath "LICENSE"
    $licenceArtifact = @($packA.Artifacts | Where-Object { $_.artifactRole -ceq "licence-notice" })[0]
    if (-not (Test-Path -LiteralPath $licencePath -PathType Leaf) -or (Get-FileSha256 $licencePath) -cne $licenceArtifact.sha256) { throw "The licence notice is not installed in the pack directory with its SHA-256." }
    if ([string]$stateA.artifactSha256."licence-notice" -cne $licenceArtifact.sha256) { throw "The install state does not bind the licence notice." }
    if (@(Get-ChildItem -LiteralPath $store -Force | Where-Object { $_.Name.StartsWith(".") }).Count -ne 0) { throw "The installer left stage or rollback directories in the store." }
    [void](Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $store -Manifest (Read-JsonFile $installedManifestPath))

    # Launcher path against the REAL committed binding.
    $resolved = Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings)
    $boundA = $resolved.ModelPacks[0]
    if ($boundA.Status -cne "installed" -or [string]$boundA.PackDirectory -cne $packADirectory -or [string]$boundA.CapabilityId -cne "detector") { throw "The installed bound pack was not found in its pack directory: $($boundA.Status)." }
    if (-not (Invoke-Compatibility -ModelPacks @($resolved.ModelPacks))) { throw "The installed pack was rejected against the committed v2 binding." }

    # Reuse: re-installing the same pack is a no-op that keeps its bytes.
    $packATree = Get-TreeFingerprint $packAPath
    Install-Fixture -PackRoot $packA.Root -StoreRoot $store
    if ((Get-TreeFingerprint $packAPath) -cne $packATree) { throw "Re-installing an intact identical pack rewrote it." }

    # Per-pack staging (P-10): installing pack B leaves pack A byte-identical.
    $packB = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-b") -PackDirectory "fixture-second-pack-v1" -ModelPackId ("mavi-model-v2-" + ("b" * 64)) -Seed "b"
    Install-Fixture -PackRoot $packB.Root -StoreRoot $store
    if ((Get-TreeFingerprint $packAPath) -cne $packATree) { throw "Installing pack B changed pack A." }
    $stateB = Read-JsonFile (Join-Path (Join-Path $store "fixture-second-pack-v1") "model-install.json")
    if ([string]$stateB.modelPackId -cne $packB.ModelPackId) { throw "Pack B was not installed." }
    # Replacing pack B with a new pack of the same directory still leaves A alone.
    $packB2 = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-b2") -PackDirectory "fixture-second-pack-v1" -ModelPackId ("mavi-model-v2-" + ("c" * 64)) -Seed "b2"
    Install-Fixture -PackRoot $packB2.Root -StoreRoot $store
    if ((Get-TreeFingerprint $packAPath) -cne $packATree) { throw "Replacing pack B changed pack A." }
    if ([string](Read-JsonFile (Join-Path (Join-Path $store "fixture-second-pack-v1") "model-install.json")).modelPackId -cne $packB2.ModelPackId) { throw "Pack B was not replaced by its new version." }
    # A corrupt, unrelated pack in the store does not stop pack A installing.
    Write-Utf8File -Path (Join-Path (Join-Path $store "fixture-second-pack-v1") "model.pth") -Text "tampered"
    $bTreeTampered = Get-TreeFingerprint (Join-Path $store "fixture-second-pack-v1")
    Remove-Item -LiteralPath $packAPath -Recurse -Force
    Install-Fixture -PackRoot $packA.Root -StoreRoot $store
    if ((Get-TreeFingerprint (Join-Path $store "fixture-second-pack-v1")) -cne $bTreeTampered) { throw "Installing pack A read or repaired pack B." }
    Remove-Item -LiteralPath (Join-Path $store "fixture-second-pack-v1") -Recurse -Force

    # §7 item 2: bound pack absent -> not-installed (launch_model_pack_not_installed).
    $otherBinding = @([pscustomobject]@{ CapabilityId = "detector"; ModelPackId = ("mavi-model-v2-" + ("d" * 64)); QualificationId = "fixture" })
    if ((Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings $otherBinding).ModelPacks[0].Status -cne "not-installed") { throw "An absent bound pack was not reported as not-installed." }

    # Leftover stage/rollback directories are skipped by the scan.
    Copy-Item -LiteralPath $packAPath -Destination (Join-Path $store ("." + $packADirectory + ".stage")) -Recurse
    if ((Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings)).ModelPacks[0].Status -cne "installed") { throw "A dot-prefixed stage directory was counted as a second pack." }
    Remove-Item -LiteralPath (Join-Path $store ("." + $packADirectory + ".stage")) -Recurse -Force

    # §7 item 2: the same modelPackId in two store directories -> ambiguous.
    $duplicatePath = Join-Path $store "rtmdet-duplicate"
    Copy-Item -LiteralPath $packAPath -Destination $duplicatePath -Recurse
    $ambiguous = (Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings)).ModelPacks[0]
    if ($ambiguous.Status -cne "ambiguous" -or @($ambiguous.Candidates).Count -ne 2) { throw "Two store directories carrying one modelPackId were not reported as ambiguous." }
    Remove-Item -LiteralPath $duplicatePath -Recurse -Force

    # An unreadable manifest elsewhere could hide a duplicate: fail closed.
    Write-Utf8File -Path (Join-Path (Join-Path $store "broken-pack") "model-pack-manifest.json") -Text "{ not json"
    Assert-Throws -MessageFragment "store manifest is unreadable" -Script { Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings) }
    Remove-Item -LiteralPath (Join-Path $store "broken-pack") -Recurse -Force

    # A pack directory without its state is not installed.
    Rename-Item -LiteralPath $installedStatePath -NewName "model-install.json.moved"
    if ((Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings)).ModelPacks[0].Status -cne "state-missing") { throw "A pack directory without model-install.json was not reported as state-missing." }
    Rename-Item -LiteralPath (Join-Path $packAPath "model-install.json.moved") -NewName "model-install.json"

    # §7 item 4: installed set does not match the binding -> compatibility fails
    # (launcher: launch_component_compatibility_failed).
    function Get-FreshBound {
        return (Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings @($bindingRole.CapabilityBindings)).ModelPacks[0]
    }
    # (a) the install state's artefact SHA-256 is not the manifest's
    $bound = Get-FreshBound
    $bound.ModelState.artifactSha256.checkpoint = ("0" * 64)
    Assert-Throws -MessageFragment "artifactSha256.checkpoint" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    $bound = Get-FreshBound
    $bound.ModelState.artifactSha256 | Add-Member -NotePropertyName extra-role -NotePropertyValue ("0" * 64)
    Assert-Throws -MessageFragment "artifactSha256.extra-role" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    # (b) the install state's identity is not the pack manifest's
    $bound = Get-FreshBound
    $bound.ModelState.modelPackId = "mavi-model-v2-" + ("e" * 64)
    Assert-Throws -MessageFragment "Model Pack ID mismatch" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    $bound = Get-FreshBound
    $bound.ModelState.modelId = "another-model"
    Assert-Throws -MessageFragment "(modelId)" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    $bound = Get-FreshBound
    $bound.ModelState.capabilityIds = @("tracker")
    Assert-Throws -MessageFragment "(capabilityIds)" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    # (c) the binding requires another pack than the one installed
    $bound = Get-FreshBound
    $bound.ModelPackId = "mavi-model-v2-" + ("f" * 64)
    Assert-Throws -MessageFragment "Model Pack ID mismatch" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    $bound = Get-FreshBound
    $bound.CapabilityId = "tracker"
    Assert-Throws -MessageFragment "does not provide capability 'tracker'" -Script { Invoke-Compatibility -ModelPacks @($bound) }
    # (d) the installed runtimePackId is not the binding entry's
    $otherRuntimeManifest = $runtimeManifest.PSObject.Copy(); $otherRuntimeManifest.runtimePackId = "mavi-runtime-v2-" + ("7" * 64)
    $otherRuntimeState = $runtimeState.PSObject.Copy(); $otherRuntimeState.runtimePackId = $otherRuntimeManifest.runtimePackId
    Assert-Throws -MessageFragment "Runtime Pack ID mismatch" -Script { Invoke-Compatibility -ModelPacks @(Get-FreshBound) -State $otherRuntimeState -Manifest $otherRuntimeManifest }
    # (e) nothing bound, or bound but not installed
    Assert-Throws -MessageFragment "at least one bound Model Pack" -Script { Assert-MaviVisionWorkerComponentCompatibility -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest -RequiredRuntimePackId ([string]$runtimeRequirement.runtimePackId) -RequiredThirdPartyLockSha256 ([string]$runtimeRequirement.thirdPartyLockSha256) -RequiredRuntimeRequirementsSha256 ([string]$runtimeRequirement.runtimeRequirementsSha256) -RequiredModelPacks @() }
    Assert-Throws -MessageFragment "is not installed" -Script { Invoke-Compatibility -ModelPacks @((Resolve-MaviVisionBoundModelPacks -StoreRoot $store -CapabilityBindings $otherBinding).ModelPacks) }
    # The untouched store still passes: the refusals above came from the edits.
    if (-not (Invoke-Compatibility -ModelPacks @(Get-FreshBound))) { throw "The unmodified installed pack stopped being compatible." }

    # Installed bytes that no longer match the manifest fail the startup
    # re-hash (launcher: launch_model_pack_integrity_failed), and so does an
    # undeclared file in the pack directory.
    $checkpointPath = Join-Path $packAPath "model.pth"
    $originalCheckpoint = [IO.File]::ReadAllBytes($checkpointPath)
    $tampered = [byte[]]$originalCheckpoint.Clone(); $tampered[0] = [byte](($tampered[0] + 1) % 256)
    [IO.File]::WriteAllBytes($checkpointPath, $tampered)
    Assert-Throws -MessageFragment "SHA-256 mismatch" -Script { Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $store -Manifest (Read-JsonFile $installedManifestPath) }
    [IO.File]::WriteAllBytes($checkpointPath, $originalCheckpoint)
    Write-Utf8File -Path (Join-Path $packAPath "undeclared.bin") -Text "x"
    Assert-Throws -MessageFragment "Undeclared file" -Script { Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $store -Manifest (Read-JsonFile $installedManifestPath) }
    Remove-Item -LiteralPath (Join-Path $packAPath "undeclared.bin") -Force
    [void](Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $store -Manifest (Read-JsonFile $installedManifestPath))

    # §7 item 3: a stale v1 model-install.json in the pack directory.
    $v1StateText = '{"schemaVersion":"mavi-vision-model-install-v1","modelPackId":"mavi-model-v1-' + ("2" * 64) + '","modelPackManifestSha256":"' + ("8" * 64) + '","modelId":"rtmdet-m-coco-phase1","checkpointSha256":"' + ("f" * 64) + '","resolvedConfigSha256":"' + ("9" * 64) + '","installedAtUtc":"2026-09-17T00:00:00Z","modelRoot":"legacy"}' + "`n"
    Write-Utf8File -Path $installedStatePath -Text $v1StateText
    $v1Tree = Get-TreeFingerprint $packAPath
    #   launcher -> launch_model_state_schema_unsupported
    if ((Get-FreshBound).Status -cne "state-unsupported") { throw "A v1 model-install.json was not reported as state-unsupported." }
    #   installer -> model_install_state_v1_rejected, and the directory is left as it was
    Assert-Throws -MessageFragment "model_install_state_v1_rejected" -Script { Install-Fixture -PackRoot $packA.Root -StoreRoot $store }
    if ((Get-TreeFingerprint $packAPath) -cne $v1Tree) { throw "A rejected v1 installation was modified." }
    # Re-install as documented: remove the v1 directory, run the installer again.
    Remove-Item -LiteralPath $packAPath -Recurse -Force
    Install-Fixture -PackRoot $packA.Root -StoreRoot $store
    if ((Get-FreshBound).Status -cne "installed") { throw "Re-installing after removing the v1 directory did not restore the pack." }

    # A store root that is itself a v1 per-model installation (an inherited
    # pre-cut-over MAVI_VISION_MODEL_ROOT) is refused by both.
    $legacyStore = Join-Path $tempRoot "legacy-root"
    Write-Utf8File -Path (Join-Path $legacyStore "model-install.json") -Text $v1StateText
    if (-not (Resolve-MaviVisionBoundModelPacks -StoreRoot $legacyStore -CapabilityBindings @($bindingRole.CapabilityBindings)).LegacyInstallation) { throw "A v1 per-model root was not reported as a legacy installation." }
    Assert-Throws -MessageFragment "model_install_state_v1_rejected" -Script { Install-Fixture -PackRoot $packA.Root -StoreRoot $legacyStore }
    if (Test-Path -LiteralPath (Join-Path $legacyStore $packADirectory)) { throw "The installer wrote into a v1 per-model root." }

    # Installer refusals of the candidate pack: nothing is written to the store.
    $storeTree = Get-TreeFingerprint $store
    $v1Candidate = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-v1") -PackDirectory "fixture-v1-pack" -ModelPackId ("mavi-model-v2-" + ("1" * 64)) -Seed "v1" -SchemaVersion "mavi-vision-model-pack-v1"
    Assert-Throws -MessageFragment "model_pack_schema_unsupported" -Script { Install-Fixture -PackRoot $v1Candidate.Root -StoreRoot $store }
    $noNotice = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-no-notice") -PackDirectory "fixture-no-notice" -ModelPackId ("mavi-model-v2-" + ("3" * 64)) -Seed "n" -OmitLicenceNotice
    Assert-Throws -MessageFragment "licence notice" -Script { Install-Fixture -PackRoot $noNotice.Root -StoreRoot $store }
    $mixed = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-mixed") -PackDirectory "fixture-mixed" -ModelPackId ("mavi-model-v2-" + ("4" * 64)) -Seed "m" -StrayDirectory "zz-elsewhere"
    Assert-Throws -MessageFragment "share one pack directory" -Script { Install-Fixture -PackRoot $mixed.Root -StoreRoot $store }
    $tamperedPack = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-tampered") -PackDirectory "fixture-tampered" -ModelPackId ("mavi-model-v2-" + ("5" * 64)) -Seed "t"
    $tamperedCheckpoint = Join-Path (Join-Path $tamperedPack.Root "fixture-tampered") "model.pth"
    $tamperedBytes = [IO.File]::ReadAllBytes($tamperedCheckpoint); $tamperedBytes[0] = [byte](($tamperedBytes[0] + 1) % 256)
    [IO.File]::WriteAllBytes($tamperedCheckpoint, $tamperedBytes)
    Assert-Throws -MessageFragment "SHA-256 mismatch" -Script { Install-Fixture -PackRoot $tamperedPack.Root -StoreRoot $store }
    $undeclaredPack = New-FixtureModelPack -Root (Join-Path $tempRoot "pack-undeclared") -PackDirectory "fixture-undeclared" -ModelPackId ("mavi-model-v2-" + ("6" * 64)) -Seed "u"
    Write-Utf8File -Path (Join-Path (Join-Path $undeclaredPack.Root "fixture-undeclared") "extra.bin") -Text "extra"
    Assert-Throws -MessageFragment "Undeclared file" -Script { Install-Fixture -PackRoot $undeclaredPack.Root -StoreRoot $store }
    if ((Get-TreeFingerprint $store) -cne $storeTree) { throw "A refused candidate pack changed the store." }
}
finally {
    if (Test-Path -LiteralPath $tempRoot) { Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}

# --- Installer text pins -----------------------------------------------------
$installerText = Get-Content -LiteralPath $installer -Raw
foreach ($required in @(
    "model-pack-manifest.json",
    "mavi-vision-model-pack-v2",
    "mavi-vision-model-install-v2",
    "model_install_state_v1_rejected",
    "Test-MaviVisionModelPackReuse",
    "New-MaviVisionModelInstallState",
    "Assert-MaviVisionModelPackDirectoryContent",
    "MAVI_VISION_MODEL_ROOT",
    "VisionModels"
)) {
    if ($installerText -notmatch [regex]::Escape($required)) {
        throw "Vision model installer is missing component contract fragment: $required"
    }
}
foreach ($forbidden in @("checkpointSha256", "resolvedConfigSha256", "VisionModels\rtmdet-m-coco-phase1", "mavi-vision-model-install-v1")) {
    if ($installerText -match [regex]::Escape($forbidden)) {
        throw "Vision model installer still carries a v1 contract fragment: $forbidden"
    }
}

Write-Host "MAVI Vision model pack state contracts: OK" -ForegroundColor Green
