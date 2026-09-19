Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:VisionRuntimePackSchema = "mavi-vision-runtime-pack-v2"
$script:VisionRuntimeInstallSchema = "mavi-vision-runtime-install-v2"
$script:VisionModelPackSchema = "mavi-vision-model-pack-v1"
$script:VisionModelInstallSchema = "mavi-vision-model-install-v1"

function Test-MaviVisionSha256Text {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return $false }
    return ([string]$Value) -match '^[0-9a-f]{64}$'
}

function Get-MaviVisionRequiredProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Value,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Description
    )
    $property = $Value.PSObject.Properties[$Name]
    if (-not $property -or $null -eq $property.Value -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "Vision runtime $Description is missing '$Name'."
    }
    return $property.Value
}

function Assert-MaviVisionRuntimePackManifest {
    param([Parameter(Mandatory = $true)][object]$Manifest)

    $schema = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "schemaVersion" -Description "manifest")
    if ($schema -ne $script:VisionRuntimePackSchema) {
        throw "Unsupported vision runtime manifest schema '$schema'; expected '$script:VisionRuntimePackSchema'."
    }

    $packId = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "runtimePackId" -Description "manifest")
    if ($packId -notmatch '^mavi-runtime-v2-[0-9a-f]{64}$') {
        throw "Vision runtime manifest Runtime Pack ID is invalid."
    }

    $platform = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "platformVariant" -Description "manifest")
    if ($platform -notin @("windows-x86_64-cpu", "windows-x86_64-cuda", "linux-x86_64-cpu", "linux-x86_64-cuda")) {
        throw "Vision runtime manifest platform variant '$platform' is unsupported."
    }

    $pythonVersion = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "pythonVersion" -Description "manifest")
    if ($pythonVersion -notmatch '^\d+\.\d+\.\d+$') {
        throw "Vision runtime manifest Python version '$pythonVersion' is invalid."
    }
    [void](Get-MaviVisionRequiredProperty -Value $Manifest -Name "nativeAbi" -Description "manifest")

    $lockSha = Get-MaviVisionRequiredProperty -Value $Manifest -Name "thirdPartyLockSha256" -Description "manifest"
    if (-not (Test-MaviVisionSha256Text $lockSha)) {
        throw "Vision runtime manifest third-party lock SHA-256 is invalid."
    }
    $requirementsSha = Get-MaviVisionRequiredProperty -Value $Manifest -Name "runtimeRequirementsSha256" -Description "manifest"
    if (-not (Test-MaviVisionSha256Text $requirementsSha)) {
        throw "Vision runtime manifest requirements SHA-256 is invalid."
    }

    $assembled = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "assembledFromCommit" -Description "manifest")
    if ($assembled -notmatch '^[0-9a-f]{40}$') {
        throw "Vision runtime manifest assembled-from commit is invalid."
    }

    if (-not $Manifest.PSObject.Properties["artifacts"]) {
        throw "Vision runtime manifest is missing 'artifacts'."
    }
    return $true
}

function Assert-MaviVisionModelPackManifest {
    param([Parameter(Mandatory = $true)][object]$Manifest)

    $schema = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "schemaVersion" -Description "model manifest")
    if ($schema -ne $script:VisionModelPackSchema) {
        throw "Unsupported vision model manifest schema '$schema'; expected '$script:VisionModelPackSchema'."
    }
    $packId = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "modelPackId" -Description "model manifest")
    if ($packId -notmatch '^mavi-model-v1-[0-9a-f]{64}$') {
        throw "Vision model manifest Model Pack ID is invalid."
    }
    [void](Get-MaviVisionRequiredProperty -Value $Manifest -Name "modelId" -Description "model manifest")
    foreach ($name in @("checkpointSha256", "resolvedConfigSha256")) {
        $value = Get-MaviVisionRequiredProperty -Value $Manifest -Name $name -Description "model manifest"
        if (-not (Test-MaviVisionSha256Text $value)) {
            throw "Vision model manifest '$name' is invalid."
        }
    }
    $assembled = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "assembledFromCommit" -Description "model manifest")
    if ($assembled -notmatch '^[0-9a-f]{40}$') {
        throw "Vision model manifest assembled-from commit is invalid."
    }
    if (-not $Manifest.PSObject.Properties["artifacts"]) {
        throw "Vision model manifest is missing 'artifacts'."
    }
    return $true
}

function New-MaviVisionRuntimeInstallState {
    param(
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$RuntimePackManifestSha256,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][object]$PythonIdentity
    )

    [void](Assert-MaviVisionRuntimePackManifest -Manifest $Manifest)
    if (-not (Test-MaviVisionSha256Text $RuntimePackManifestSha256)) {
        throw "Vision runtime pack manifest SHA-256 is invalid."
    }
    if ([string]::IsNullOrWhiteSpace($RuntimeRoot)) {
        throw "Vision runtime installation root is required."
    }

    $version = [string](Get-MaviVisionRequiredProperty -Value $PythonIdentity -Name "version" -Description "Python identity")
    $implementation = [string](Get-MaviVisionRequiredProperty -Value $PythonIdentity -Name "implementation" -Description "Python identity")
    $compiler = [string](Get-MaviVisionRequiredProperty -Value $PythonIdentity -Name "compiler" -Description "Python identity")
    $buildProperty = $PythonIdentity.PSObject.Properties["build"]
    $build = if ($buildProperty) { @($buildProperty.Value) } else { @() }
    if ($build.Count -ne 2) {
        throw "Vision runtime Python identity build tuple is invalid."
    }
    if ($version -ne [string]$Manifest.pythonVersion -or $implementation -ne "CPython") {
        throw "Vision runtime Python identity does not match the Runtime Pack manifest."
    }

    return [pscustomobject][ordered]@{
        schemaVersion = $script:VisionRuntimeInstallSchema
        runtimePackId = [string]$Manifest.runtimePackId
        runtimePackManifestSha256 = $RuntimePackManifestSha256.ToLowerInvariant()
        thirdPartyLockSha256 = ([string]$Manifest.thirdPartyLockSha256).ToLowerInvariant()
        runtimeRequirementsSha256 = ([string]$Manifest.runtimeRequirementsSha256).ToLowerInvariant()
        platformVariant = [string]$Manifest.platformVariant
        pythonVersion = [string]$Manifest.pythonVersion
        nativeAbi = [string]$Manifest.nativeAbi
        pythonIdentity = [pscustomobject][ordered]@{
            version = $version
            implementation = $implementation
            build = @([string]$build[0], [string]$build[1])
            compiler = $compiler
        }
        assembledFromCommit = [string]$Manifest.assembledFromCommit
        installedAtUtc = [DateTime]::UtcNow.ToString("O")
        runtimeRoot = [string]$RuntimeRoot
    }
}

function New-MaviVisionModelInstallState {
    param(
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$ModelPackManifestSha256,
        [Parameter(Mandatory = $true)][string]$ModelRoot
    )
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    if (-not (Test-MaviVisionSha256Text $ModelPackManifestSha256)) {
        throw "Vision model pack manifest SHA-256 is invalid."
    }
    if ([string]::IsNullOrWhiteSpace($ModelRoot)) {
        throw "Vision model installation root is required."
    }
    return [pscustomobject][ordered]@{
        schemaVersion = $script:VisionModelInstallSchema
        modelPackId = [string]$Manifest.modelPackId
        modelPackManifestSha256 = $ModelPackManifestSha256.ToLowerInvariant()
        modelId = [string]$Manifest.modelId
        checkpointSha256 = ([string]$Manifest.checkpointSha256).ToLowerInvariant()
        resolvedConfigSha256 = ([string]$Manifest.resolvedConfigSha256).ToLowerInvariant()
        assembledFromCommit = [string]$Manifest.assembledFromCommit
        installedAtUtc = [DateTime]::UtcNow.ToString("O")
        modelRoot = [string]$ModelRoot
    }
}

function Test-MaviVisionPythonIdentityEqual {
    param([AllowNull()][object]$Left, [AllowNull()][object]$Right)
    if ($null -eq $Left -or $null -eq $Right) { return $false }
    foreach ($name in @("version", "implementation", "compiler")) {
        $leftProperty = $Left.PSObject.Properties[$name]
        $rightProperty = $Right.PSObject.Properties[$name]
        if (-not $leftProperty -or -not $rightProperty -or [string]$leftProperty.Value -ne [string]$rightProperty.Value) { return $false }
    }
    $leftBuildProperty = $Left.PSObject.Properties["build"]
    $rightBuildProperty = $Right.PSObject.Properties["build"]
    if (-not $leftBuildProperty -or -not $rightBuildProperty) { return $false }
    $leftBuild = @($leftBuildProperty.Value)
    $rightBuild = @($rightBuildProperty.Value)
    if ($leftBuild.Count -ne 2 -or $rightBuild.Count -ne 2) { return $false }
    return ([string]$leftBuild[0] -eq [string]$rightBuild[0] -and [string]$leftBuild[1] -eq [string]$rightBuild[1])
}

function Assert-MaviVisionRuntimeInstalledStatePreflight {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][object]$InstalledState,
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$RuntimePackManifestPath
    )

    [void](Assert-MaviVisionRuntimePackManifest -Manifest $Manifest)
    if (-not $InstalledState.PSObject.Properties["schemaVersion"] -or
        [string]$InstalledState.schemaVersion -ne $script:VisionRuntimeInstallSchema) {
        throw "Vision runtime installed state schema is unsupported."
    }

    $manifestSha = (Get-FileHash -LiteralPath $RuntimePackManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([string]$InstalledState.runtimePackManifestSha256 -ne $manifestSha) {
        throw "Installed Vision Runtime Pack state does not bind the installed manifest."
    }

    $comparisons = [ordered]@{
        runtimePackId = [string]$Manifest.runtimePackId
        thirdPartyLockSha256 = ([string]$Manifest.thirdPartyLockSha256).ToLowerInvariant()
        runtimeRequirementsSha256 = ([string]$Manifest.runtimeRequirementsSha256).ToLowerInvariant()
        platformVariant = [string]$Manifest.platformVariant
        pythonVersion = [string]$Manifest.pythonVersion
        nativeAbi = [string]$Manifest.nativeAbi
    }
    foreach ($name in $comparisons.Keys) {
        $property = $InstalledState.PSObject.Properties[$name]
        if (-not $property -or [string]$property.Value -ne [string]$comparisons[$name]) {
            throw "Installed Vision Runtime Pack state does not match manifest field '$name'."
        }
    }

    $root = [IO.Path]::GetFullPath($RuntimeRoot.Trim().Trim('"'))
    foreach ($purpose in @("third-party-runtime-lock", "application-runtime-requirements")) {
        $artifacts = @($Manifest.artifacts | Where-Object { [string]$_.purpose -eq $purpose })
        if ($artifacts.Count -ne 1) {
            throw "Installed Vision Runtime Pack must declare exactly one '$purpose' artifact."
        }
        $relative = [string]$artifacts[0].relativePath
        if ($relative -notmatch '^runtime/[A-Za-z0-9._-]+$') {
            throw "Installed Vision Runtime Pack retained artifact path is invalid: '$relative'."
        }
        $path = Join-Path $root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Installed Vision Runtime Pack retained artifact is missing: '$relative'."
        }
        $actualSha = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualSha -ne ([string]$artifacts[0].sha256).ToLowerInvariant()) {
            throw "Installed Vision Runtime Pack retained artifact SHA-256 mismatch: '$relative'."
        }
    }

    $pythonPath = Join-Path $root "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Installed Vision Runtime Pack interpreter is missing."
    }
    $pyvenv = Join-Path $root "venv\pyvenv.cfg"
    if (-not (Test-Path -LiteralPath $pyvenv -PathType Leaf)) {
        throw "Installed Vision Runtime Pack virtual-environment metadata is missing."
    }

    return $true
}

function Test-MaviVisionRuntimePackReuse {
    param(
        [AllowNull()][object]$InstalledState,
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$RuntimePackManifestSha256,
        [Parameter(Mandatory = $true)][object]$PythonIdentity
    )

    [void](Assert-MaviVisionRuntimePackManifest -Manifest $Manifest)
    if (-not (Test-MaviVisionSha256Text $RuntimePackManifestSha256)) { return $false }
    if ($null -eq $InstalledState) { return $false }
    $schemaProperty = $InstalledState.PSObject.Properties["schemaVersion"]
    if (-not $schemaProperty -or [string]$schemaProperty.Value -ne $script:VisionRuntimeInstallSchema) { return $false }

    $comparisons = [ordered]@{
        runtimePackId = [string]$Manifest.runtimePackId
        runtimePackManifestSha256 = $RuntimePackManifestSha256.ToLowerInvariant()
        thirdPartyLockSha256 = ([string]$Manifest.thirdPartyLockSha256).ToLowerInvariant()
        runtimeRequirementsSha256 = ([string]$Manifest.runtimeRequirementsSha256).ToLowerInvariant()
        platformVariant = [string]$Manifest.platformVariant
        pythonVersion = [string]$Manifest.pythonVersion
        nativeAbi = [string]$Manifest.nativeAbi
    }
    foreach ($name in $comparisons.Keys) {
        $property = $InstalledState.PSObject.Properties[$name]
        if (-not $property -or [string]$property.Value -ne [string]$comparisons[$name]) { return $false }
    }

    $identityProperty = $InstalledState.PSObject.Properties["pythonIdentity"]
    if (-not $identityProperty -or -not (Test-MaviVisionPythonIdentityEqual -Left $identityProperty.Value -Right $PythonIdentity)) { return $false }
    return $true
}

function Test-MaviVisionModelPackReuse {
    param(
        [AllowNull()][object]$InstalledState,
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$ModelPackManifestSha256
    )
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    if (-not (Test-MaviVisionSha256Text $ModelPackManifestSha256)) { return $false }
    if ($null -eq $InstalledState) { return $false }
    $schemaProperty = $InstalledState.PSObject.Properties["schemaVersion"]
    if (-not $schemaProperty -or [string]$schemaProperty.Value -ne $script:VisionModelInstallSchema) { return $false }
    $comparisons = [ordered]@{
        modelPackId = [string]$Manifest.modelPackId
        modelPackManifestSha256 = $ModelPackManifestSha256.ToLowerInvariant()
        modelId = [string]$Manifest.modelId
        checkpointSha256 = ([string]$Manifest.checkpointSha256).ToLowerInvariant()
        resolvedConfigSha256 = ([string]$Manifest.resolvedConfigSha256).ToLowerInvariant()
    }
    foreach ($name in $comparisons.Keys) {
        $property = $InstalledState.PSObject.Properties[$name]
        if (-not $property -or [string]$property.Value -ne [string]$comparisons[$name]) { return $false }
    }
    return $true
}

function Assert-MaviVisionWorkerComponentCompatibility {
    param(
        [Parameter(Mandatory = $true)][object]$RuntimeState,
        [Parameter(Mandatory = $true)][object]$RuntimeManifest,
        [Parameter(Mandatory = $true)][string]$RequiredRuntimePackId,
        [Parameter(Mandatory = $true)][string]$RequiredThirdPartyLockSha256,
        [Parameter(Mandatory = $true)][string]$RequiredRuntimeRequirementsSha256,
        [Parameter(Mandatory = $true)][object]$ModelState,
        [Parameter(Mandatory = $true)][object]$ModelManifest,
        [Parameter(Mandatory = $true)][string]$RequiredModelPackId,
        [Parameter(Mandatory = $true)][string]$RequiredModelId,
        [Parameter(Mandatory = $true)][string]$RequiredCheckpointSha256,
        [Parameter(Mandatory = $true)][string]$RequiredResolvedConfigSha256
    )

    [void](Assert-MaviVisionRuntimePackManifest -Manifest $RuntimeManifest)
    [void](Assert-MaviVisionModelPackManifest -Manifest $ModelManifest)

    if (-not $RuntimeState.PSObject.Properties["schemaVersion"] -or [string]$RuntimeState.schemaVersion -ne $script:VisionRuntimeInstallSchema) {
        throw "Vision runtime installed state schema is unsupported; reinstall the v2 Runtime Pack."
    }
    if (-not $ModelState.PSObject.Properties["schemaVersion"] -or [string]$ModelState.schemaVersion -ne $script:VisionModelInstallSchema) {
        throw "Vision model installed state schema is unsupported; reinstall the Model Pack."
    }

    if ([string]$RuntimeState.runtimePackId -ne $RequiredRuntimePackId -or [string]$RuntimeManifest.runtimePackId -ne $RequiredRuntimePackId) {
        throw "Vision Runtime Pack ID mismatch. Required '$RequiredRuntimePackId'."
    }
    if ([string]$RuntimeState.thirdPartyLockSha256 -ne $RequiredThirdPartyLockSha256 -or [string]$RuntimeManifest.thirdPartyLockSha256 -ne $RequiredThirdPartyLockSha256) {
        throw "Vision Runtime Pack third-party lock fingerprint mismatch."
    }
    if ([string]$RuntimeState.runtimeRequirementsSha256 -ne $RequiredRuntimeRequirementsSha256 -or [string]$RuntimeManifest.runtimeRequirementsSha256 -ne $RequiredRuntimeRequirementsSha256) {
        throw "Vision Runtime Pack application requirements fingerprint mismatch."
    }
    if ([string]$RuntimeState.platformVariant -ne [string]$RuntimeManifest.platformVariant -or [string]$RuntimeState.pythonVersion -ne [string]$RuntimeManifest.pythonVersion -or [string]$RuntimeState.nativeAbi -ne [string]$RuntimeManifest.nativeAbi) {
        throw "Vision Runtime Pack installed state does not match its manifest."
    }

    if ([string]$ModelState.modelPackId -ne $RequiredModelPackId -or [string]$ModelManifest.modelPackId -ne $RequiredModelPackId) {
        throw "Vision Model Pack ID mismatch. Required '$RequiredModelPackId'."
    }
    if ([string]$ModelState.modelId -ne $RequiredModelId -or [string]$ModelManifest.modelId -ne $RequiredModelId) {
        throw "Vision Model ID mismatch. Required '$RequiredModelId'."
    }
    if ([string]$ModelState.checkpointSha256 -ne $RequiredCheckpointSha256 -or [string]$ModelManifest.checkpointSha256 -ne $RequiredCheckpointSha256) {
        throw "Vision Model Pack checkpoint fingerprint mismatch."
    }
    if ([string]$ModelState.resolvedConfigSha256 -ne $RequiredResolvedConfigSha256 -or [string]$ModelManifest.resolvedConfigSha256 -ne $RequiredResolvedConfigSha256) {
        throw "Vision Model Pack resolved-config fingerprint mismatch."
    }
    return $true
}

function Resolve-MaviVisionCudaAvailability {
    <#
    .SYNOPSIS
    Decide whether Development `Auto` may use the Windows CUDA Runtime Pack.

    .DESCRIPTION
    This is the whole of the Auto decision on Windows: it runs before Python
    starts, and whichever reason it returns is what the worker records as
    `deviceResolutionReason`. Every literal below belongs to the closed
    vocabulary in src/vision/mavi_vision/common/control_plane.py.

    It lived inside Start-MaviVisionWorker.ps1 and closed over the script's
    $RepositoryRoot and $DeviceIndex, which is why it could never be tested:
    nothing could call it. Both are parameters now, and the driver probe is
    injectable, so every branch is exercisable on a machine with no GPU.

    Note the trust order is deliberate and must not be rearranged: integrity
    and declared identity are checked before the driver is probed, so a pack
    that fails its preflight is never executed just to ask what device exists.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ComponentRequirementsPath,
        [int]$DeviceIndex = 0,
        [scriptblock]$DriverProbe
    )

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

    if (-not (Test-Path -LiteralPath $ComponentRequirementsPath -PathType Leaf)) {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    try {
        $componentValue = Get-Content -LiteralPath $ComponentRequirementsPath -Raw | ConvertFrom-Json
        $runtimePacks = $componentValue.PSObject.Properties["runtimePacks"]
        if (-not $runtimePacks) {
            $result.Reason = "cuda_pack_not_declared"
            return [pscustomobject]$result
        }
        $cudaRequirement = $runtimePacks.Value.PSObject.Properties["windows-x86_64-cuda"]
    }
    catch {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    if (-not $cudaRequirement) {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    if ([string]$cudaRequirement.Value.runtimePackId -ne [string]$manifestValue.runtimePackId) {
        $result.Reason = "cuda_pack_id_mismatch"
        return [pscustomobject]$result
    }

    if (-not $DriverProbe) {
        $DriverProbe = {
            param([int]$Index)
            $nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
            if (-not $nvidiaSmi) { return $null }
            $probe = (& $nvidiaSmi.Source -i $Index --query-gpu=index --format=csv,noheader,nounits 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -ne 0) { return "" }
            return $probe
        }
    }

    try {
        $probe = & $DriverProbe $DeviceIndex
    }
    catch {
        $result.Reason = "cuda_driver_probe_failed"
        return [pscustomobject]$result
    }
    if ($null -eq $probe) {
        $result.Reason = "cuda_driver_probe_unavailable"
        return [pscustomobject]$result
    }
    if ([string]$probe -ne [string]$DeviceIndex) {
        $result.Reason = "cuda_device_unavailable"
        return [pscustomobject]$result
    }

    $result.Usable = $true
    $result.Reason = "cuda_selected"
    return [pscustomobject]$result
}

Export-ModuleMember -Function *
