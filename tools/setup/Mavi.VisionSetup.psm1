Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Setup orchestration of the Vision composition (Stage 2 S2a.4).
#
# Component binding v2 is the one composition source. This module decides
# nothing about compatibility itself: the binding is read and a kit is verified
# against it by tools/vision/sync_offline_vision_components.py `plan`, each pack
# is installed by its existing installer, and readiness is the launcher's own
# compatibility assertion (Start-MaviVisionWorker.ps1 -VerifyOnly). What lives
# here is the Setup order: find the source, preflight everything, and only then
# install, in a fixed order, and verify.
#
# The multi-pack install is not one transaction. Each installer stages and
# swaps its own pack; a later failure leaves an earlier valid pack installed,
# Setup fails naming the component, and a rerun converges because the
# installers reuse a verified installed pack.

Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

$script:VisionSetupRole = "vision"
$script:VisionSetupVariant = "windows-x86_64-cpu"
$script:VisionSetupOptionalVariants = @("windows-x86_64-cuda")
$script:VisionInventoryRelativePath = "vision\component-inventory.json"
$script:VisionDefaultModelStore = "C:\ProgramData\MAVI\Development\VisionModels"

function Get-MaviVisionSetupModelStoreRoot {
    <#
    .SYNOPSIS
    The Model Pack store the launcher reads: Machine MAVI_VISION_MODEL_ROOT, else the default store.
    #>
    $root = [Environment]::GetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", "Machine")
    if ([string]::IsNullOrWhiteSpace($root)) { $root = $script:VisionDefaultModelStore }
    return [IO.Path]::GetFullPath($root.Trim().Trim('"'))
}

function Resolve-MaviVisionSetupSource {
    <#
    .SYNOPSIS
    Where Setup takes the Vision components from. Nothing is installed or read beyond presence.

    .DESCRIPTION
    An explicit root (MAVI_VISION_BUNDLE_ROOT) is the operator's choice and is
    never replaced by another source: it is a component store when it holds
    vision\component-inventory.json, otherwise a Runtime Bundle root, and a
    missing explicit root is an error. Without one, the component store of the
    Setup bundle/kit is used when present, else the conventional sibling
    ..\MAVI-Vision-Runtime-Bundle when it exists. Kind is "kit",
    "runtime-bundle" or "none".
    #>
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [AllowEmptyString()][AllowNull()][string]$ExplicitRoot
    )
    if (-not [string]::IsNullOrWhiteSpace($ExplicitRoot)) {
        $root = [IO.Path]::GetFullPath($ExplicitRoot.Trim().Trim('"'))
        if (-not (Test-Path -LiteralPath $root -PathType Container)) {
            throw "MAVI_VISION_BUNDLE_ROOT names '$root', which is not a directory. Point it at a Vision component store or Runtime Bundle, or unset it."
        }
        $kind = if (Test-Path -LiteralPath (Join-Path $root $script:VisionInventoryRelativePath) -PathType Leaf) { "kit" } else { "runtime-bundle" }
        return [pscustomobject][ordered]@{ Kind = $kind; Root = $root; Origin = "explicit" }
    }
    $bundle = [IO.Path]::GetFullPath($BundleRoot.Trim().Trim('"'))
    if (Test-Path -LiteralPath (Join-Path $bundle $script:VisionInventoryRelativePath) -PathType Leaf) {
        return [pscustomobject][ordered]@{ Kind = "kit"; Root = $bundle; Origin = "bundle" }
    }
    $repository = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
    $sibling = Join-Path (Split-Path $repository -Parent) "MAVI-Vision-Runtime-Bundle"
    if (Test-Path -LiteralPath $sibling -PathType Container) {
        return [pscustomobject][ordered]@{ Kind = "runtime-bundle"; Root = [IO.Path]::GetFullPath($sibling); Origin = "default" }
    }
    return [pscustomobject][ordered]@{ Kind = "none"; Root = $null; Origin = $null }
}

function Invoke-MaviVisionComponentPlanTool {
    <#
    .SYNOPSIS
    Run `sync_offline_vision_components.py plan` and return its JSON; a refusal throws its code.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$ComponentBindingPath,
        [string]$KitRoot
    )
    $tool = Join-Path $RepositoryRoot "tools\vision\sync_offline_vision_components.py"
    if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Vision component-store tool is missing: $tool" }
    $arguments = @($tool, "plan", "--component-binding", $ComponentBindingPath, "--role", $script:VisionSetupRole, "--variant", $script:VisionSetupVariant)
    foreach ($optional in $script:VisionSetupOptionalVariants) { $arguments += @("--optional-variant", $optional) }
    if (-not [string]::IsNullOrWhiteSpace($KitRoot)) { $arguments += @("--kit-root", $KitRoot) }

    # Windows PowerShell turns native stderr into terminating errors under
    # "Stop"; the tool's refusal code is on stderr, so read both streams here.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = @(& $Python @arguments 2>&1)
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    $stderr = (@($output | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { $_.ToString() }) -join "`n").Trim()
    $stdout = (@($output | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { [string]$_ }) -join "`n").Trim()
    if ($exitCode -ne 0) {
        if ([string]::IsNullOrWhiteSpace($stderr)) { $stderr = "vision_component_plan_failed:exit_$exitCode" }
        throw $stderr
    }
    try { return $stdout | ConvertFrom-Json }
    catch { throw "Vision component plan output is not JSON: $stdout" }
}

function Invoke-MaviVisionComponentPreflight {
    <#
    .SYNOPSIS
    Decide the complete install before anything is installed. Mutates nothing.

    .DESCRIPTION
    Returns the plan Setup executes: the binding's Windows CPU Runtime Pack,
    every enabled Model Pack of role `vision` in modelPackId order, and an
    optional bound Windows CUDA Runtime Pack when the source carries it. Each
    entry names its source directory, or $null for a Model Pack that a Runtime
    Bundle source does not carry and that is already installed.

    A component store is checked by the Python tool against the repository
    binding (kit_binding_mismatch, kit_incomplete:<id>, kit_unbound_component:<id>,
    and the store verifier's own codes). A Runtime Bundle root must hold a
    runtime-pack-manifest.json for the bound id; a legacy bundle-manifest.json
    is not installable. ApplicationRevision is the kit's provenance and is
    reported, never compared.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Source,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$Python,
        [Parameter(Mandatory = $true)][string]$ModelStoreRoot,
        # The repository binding unless given. Setup never passes it; contract
        # tests use it to exercise bindings with several Model Packs.
        [string]$ComponentBindingPath
    )
    $repository = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
    $bindingPath = if ([string]::IsNullOrWhiteSpace($ComponentBindingPath)) { Join-Path $repository "src\vision\config\components\phase1-bindings-v2.json" } else { [IO.Path]::GetFullPath($ComponentBindingPath) }
    if (-not (Test-Path -LiteralPath $bindingPath -PathType Leaf)) { throw "Vision component binding is missing: $bindingPath" }
    $kind = [string]$Source.Kind
    if ($kind -notin @("kit", "runtime-bundle")) { throw "Vision component preflight needs a component source; found '$kind'." }

    $kitRoot = if ($kind -eq "kit") { [string]$Source.Root } else { $null }
    $toolPlan = Invoke-MaviVisionComponentPlanTool -Python $Python -RepositoryRoot $repository -ComponentBindingPath $bindingPath -KitRoot $kitRoot

    $required = $toolPlan.runtimePack
    $modelPacks = New-Object System.Collections.Generic.List[object]
    $optional = New-Object System.Collections.Generic.List[object]
    $revision = $null
    if ($kind -eq "kit") {
        $kit = $toolPlan.kit
        $revision = [string]$kit.applicationRevision
        $runtime = [pscustomobject][ordered]@{ RuntimePackId = [string]$kit.runtimePack.runtimePackId; Variant = [string]$kit.runtimePack.platformVariant; SourceRoot = [string]$kit.runtimePack.sourceRoot }
        foreach ($item in @($kit.modelPacks)) {
            $modelPacks.Add([pscustomobject][ordered]@{ ModelPackId = [string]$item.modelPackId; CapabilityIds = @($item.capabilityIds | ForEach-Object { [string]$_ }); SourceRoot = [string]$item.sourceRoot })
        }
        foreach ($item in @($kit.optionalRuntimePacks)) {
            $optional.Add([pscustomobject][ordered]@{ RuntimePackId = [string]$item.runtimePackId; Variant = [string]$item.platformVariant; SourceRoot = [string]$item.sourceRoot })
        }
    }
    else {
        $root = [string]$Source.Root
        $runtime = Resolve-MaviVisionRuntimeBundleEntry -Root $root -Requirement $required -Required
        foreach ($candidate in @($toolPlan.optionalRuntimePacks)) {
            $entry = Resolve-MaviVisionRuntimeBundleEntry -Root $root -Requirement $candidate
            if ($null -ne $entry) { $optional.Add($entry) }
        }
        # Nothing under the Runtime Bundle root may claim a variant the binding does not declare.
        $offered = @(@($required) + @($toolPlan.optionalRuntimePacks) | ForEach-Object { [string]$_.platformVariant })
        foreach ($directory in @(Get-ChildItem -LiteralPath $root -Directory -Force | Sort-Object Name)) {
            if ($offered -ccontains $directory.Name) { continue }
            $stray = Join-Path $directory.FullName "runtime-pack-manifest.json"
            if (Test-Path -LiteralPath $stray -PathType Leaf) {
                $strayId = Get-MaviVisionPropertyText -Value (Get-Content -LiteralPath $stray -Raw | ConvertFrom-Json) -Name "runtimePackId"
                throw "kit_unbound_component:${strayId}: '$stray' is not a Runtime Pack the component binding declares."
            }
        }
        # A Runtime Bundle carries no Model Pack: each bound pack must already be installed.
        $bindings = @($toolPlan.modelPacks | ForEach-Object {
            $pack = $_
            @($pack.capabilityIds) | ForEach-Object { [pscustomobject]@{ CapabilityId = [string]$_; ModelPackId = [string]$pack.modelPackId } }
        })
        $installed = Resolve-MaviVisionBoundModelPacks -StoreRoot $ModelStoreRoot -CapabilityBindings $bindings
        foreach ($item in @($toolPlan.modelPacks)) {
            $status = @(@($installed.ModelPacks) | Where-Object { $_.ModelPackId -ceq [string]$item.modelPackId } | ForEach-Object { $_.Status })
            if ($installed.LegacyInstallation -or @($status | Where-Object { $_ -ne "installed" }).Count -gt 0 -or $status.Count -eq 0) {
                throw "kit_incomplete:$($item.modelPackId): the Runtime Bundle '$root' carries no Model Pack, and Model Pack '$($item.modelPackId)' is not installed in '$ModelStoreRoot'. Use a Vision component store (vision\component-inventory.json) or install the Model Pack first."
            }
            $modelPacks.Add([pscustomobject][ordered]@{ ModelPackId = [string]$item.modelPackId; CapabilityIds = @($item.capabilityIds | ForEach-Object { [string]$_ }); SourceRoot = $null })
        }
    }

    return [pscustomobject][ordered]@{
        SourceKind = $kind
        SourceRoot = [string]$Source.Root
        SourceOrigin = [string]$Source.Origin
        ComponentBindingPath = $bindingPath
        ComponentBindingSha256 = [string]$toolPlan.componentBindingSha256
        ApplicationRevision = $revision
        ModelStoreRoot = $ModelStoreRoot
        RuntimePack = $runtime
        ModelPacks = $modelPacks.ToArray()
        OptionalRuntimePacks = $optional.ToArray()
    }
}

function Resolve-MaviVisionRuntimeBundleEntry {
    <#
    .SYNOPSIS
    The Runtime Pack of one variant in a Runtime Bundle root, checked against the binding's entry.

    .DESCRIPTION
    The pack is <Root>\runtime-pack-manifest.json or <Root>\<variant>\runtime-pack-manifest.json
    for exactly the requested variant; nothing else under the root is considered.
    A legacy bundle-manifest.json without a runtime-pack-manifest.json is not an
    installable Runtime Pack. With -Required an absent pack throws; otherwise it
    is $null.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][object]$Requirement,
        [switch]$Required
    )
    $variant = [string]$Requirement.platformVariant
    $runtimePackId = [string]$Requirement.runtimePackId
    $candidates = @($Root, (Join-Path $Root $variant))
    $manifestPath = $null
    foreach ($candidate in $candidates) {
        $path = Join-Path $candidate "runtime-pack-manifest.json"
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            $manifest = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
            if ((Get-MaviVisionPropertyText -Value $manifest -Name "platformVariant") -ceq $variant) { $manifestPath = $path; break }
        }
    }
    if ($null -eq $manifestPath) {
        if (-not $Required) { return $null }
        foreach ($candidate in $candidates) {
            if (Test-Path -LiteralPath (Join-Path $candidate "bundle-manifest.json") -PathType Leaf) {
                throw "kit_incomplete:${runtimePackId}: '$candidate' holds a legacy bundle-manifest.json and no runtime-pack-manifest.json; it is not an installable Runtime Pack. Obtain the $variant Runtime Pack whose runtimePackId is '$runtimePackId'."
            }
        }
        throw "kit_incomplete:${runtimePackId}: no $variant runtime-pack-manifest.json under '$Root'."
    }
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    [void](Assert-MaviVisionRuntimePackManifest -Manifest $manifest)
    $foundId = Get-MaviVisionPropertyText -Value $manifest -Name "runtimePackId"
    if ($foundId -cne $runtimePackId) {
        throw "kit_unbound_component:${foundId}: '$manifestPath' is not the $variant Runtime Pack the component binding declares ('$runtimePackId')."
    }
    foreach ($key in @("thirdPartyLockSha256", "runtimeRequirementsSha256", "nativeAbi")) {
        if ((Get-MaviVisionPropertyText -Value $manifest -Name $key) -cne [string]$Requirement.$key) {
            throw "runtime_requirement_mismatch:${key}: '$manifestPath' does not match the component binding."
        }
    }
    return [pscustomobject][ordered]@{ RuntimePackId = $foundId; Variant = $variant; SourceRoot = (Split-Path $manifestPath -Parent) }
}

function Invoke-MaviVisionComponentInstallation {
    <#
    .SYNOPSIS
    Install a preflighted plan in a fixed order, then require the composition assertion.

    .DESCRIPTION
    Order: the Windows CPU Runtime Pack, every Model Pack in ordinal
    modelPackId order, any optional bound Runtime Pack, then -AssertComposition.
    Only a passing assertion returns a result with Status "ready"; every other
    outcome throws, naming the component that failed. Earlier valid installs are
    left in place (the installers are per pack), and a rerun reuses them.

    The steps are script blocks so Setup passes the real installers and the
    launcher's -VerifyOnly check, and contract tests pass instrumented ones.
    Pass plain blocks from the caller's scope, not GetNewClosure() blocks: the
    installer scripts `Import-Module -Force`, and from a closure's dynamic
    module that unloads the caller's copies of those modules.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Plan,
        [Parameter(Mandatory = $true)][scriptblock]$InstallRuntimePack,
        [Parameter(Mandatory = $true)][scriptblock]$InstallModelPack,
        [Parameter(Mandatory = $true)][scriptblock]$AssertComposition
    )
    $completed = New-Object System.Collections.Generic.List[string]
    $runtime = $Plan.RuntimePack
    try { & $InstallRuntimePack $runtime | Out-Host }
    catch { throw "Vision Runtime Pack '$($runtime.RuntimePackId)' ($($runtime.Variant)) failed to install; installed so far: $(Format-MaviVisionInstalled $completed). $($_.Exception.Message)" }
    $completed.Add([string]$runtime.RuntimePackId)

    $ordered = [object[]]@($Plan.ModelPacks)
    $ids = [string[]]@($ordered | ForEach-Object { [string]$_.ModelPackId })
    [Array]::Sort($ids, $ordered, [StringComparer]::Ordinal)
    foreach ($pack in $ordered) {
        if ([string]::IsNullOrWhiteSpace([string]$pack.SourceRoot)) { continue }
        try { & $InstallModelPack $pack | Out-Host }
        catch { throw "Vision Model Pack '$($pack.ModelPackId)' failed to install; installed so far: $(Format-MaviVisionInstalled $completed). $($_.Exception.Message)" }
        $completed.Add([string]$pack.ModelPackId)
    }
    foreach ($extra in @($Plan.OptionalRuntimePacks)) {
        try { & $InstallRuntimePack $extra | Out-Host }
        catch { throw "Vision Runtime Pack '$($extra.RuntimePackId)' ($($extra.Variant)) failed to install; installed so far: $(Format-MaviVisionInstalled $completed). $($_.Exception.Message)" }
        $completed.Add([string]$extra.RuntimePackId)
    }

    try { & $AssertComposition $Plan | Out-Host }
    catch { throw "Vision composition is not ready: the installed components do not pass the launcher compatibility check. $($_.Exception.Message)" }

    return [pscustomobject][ordered]@{
        Status = "ready"
        RuntimePackId = [string]$runtime.RuntimePackId
        ModelPackIds = [string[]]$ids
        OptionalRuntimePackIds = [string[]]@(@($Plan.OptionalRuntimePacks) | ForEach-Object { [string]$_.RuntimePackId })
        ComponentBindingSha256 = [string]$Plan.ComponentBindingSha256
        ApplicationRevision = $Plan.ApplicationRevision
        Installed = $completed.ToArray()
    }
}

function Format-MaviVisionInstalled {
    param([AllowEmptyCollection()][System.Collections.Generic.List[string]]$Completed)
    if ($Completed.Count -eq 0) { return "none" }
    return ($Completed -join ", ")
}

Export-ModuleMember -Function Get-MaviVisionSetupModelStoreRoot, Resolve-MaviVisionSetupSource, Invoke-MaviVisionComponentPlanTool, Invoke-MaviVisionComponentPreflight, Resolve-MaviVisionRuntimeBundleEntry, Invoke-MaviVisionComponentInstallation
