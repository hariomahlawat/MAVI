Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:VisionRuntimePackSchema = "mavi-vision-runtime-pack-v2"
$script:VisionRuntimeInstallSchema = "mavi-vision-runtime-install-v2"
# Stage 2 S2a.3 cut-over (plan P-1, P-10, §5.4): a Model Pack is the v2 pack
# built by tools/vision/build_model_pack.py, installed per pack into a shared
# store, and described by a v2 install state. Neither v1 schema is read.
$script:VisionModelPackSchema = "mavi-vision-model-pack-v2"
$script:VisionModelInstallSchema = "mavi-vision-model-install-v2"
$script:VisionComponentBindingSchema = "mavi-vision-component-binding-v2"
$script:VisionModelPackManifestFields = @("artifacts", "assembledFromCommit", "capabilityIds", "modelId", "modelPackId", "modelVersion", "schemaVersion")
$script:VisionModelPackArtifactFields = @("artifactRole", "relativePath", "sha256", "sizeBytes")
# Plan §5.4 as pinned by erratum E-8: sizes live only in the built pack
# manifest, which the install state binds by SHA-256.
$script:VisionModelInstallFields = @("artifactSha256", "capabilityIds", "installRoot", "installedAtUtc", "modelId", "modelPackId", "modelPackManifestSha256", "schemaVersion")
$script:VisionModelPackReservedNames = @("model-pack-manifest.json", "model-install.json")
# Mirrors RETIRED_COMPOSITION_ENVIRONMENT in
# src/vision/mavi_vision/common/settings.py (a test requires the two to agree).
# The worker refuses to start if any of these is present at all, so the
# launcher removes them from its child environment rather than setting them.
$script:VisionRetiredCompositionEnvironment = @("MAVI_MODEL_MANIFEST_PATH", "MAVI_QUALIFICATION_RECORD_PATH", "MAVI_RUNTIME_PROFILE_PATH", "MAVI_COMPLETION_SCHEMA_VERSION")

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

function Get-MaviVisionPropertyValue {
    <#
    .SYNOPSIS
    Read an optional JSON property without tripping Set-StrictMode.

    A missing property is $null here rather than a raw .NET error, so a caller
    such as the launcher can turn it into a stable refusal code instead.
    #>
    param([AllowNull()][object]$Value, [Parameter(Mandatory = $true)][string]$Name)
    if ($null -eq $Value) { return $null }
    $property = $Value.PSObject.Properties[$Name]
    if (-not $property) { return $null }
    return $property.Value
}

function Get-MaviVisionPropertyText {
    param([AllowNull()][object]$Value, [Parameter(Mandatory = $true)][string]$Name)
    $propertyValue = Get-MaviVisionPropertyValue -Value $Value -Name $Name
    if ($null -eq $propertyValue) { return "" }
    return [string]$propertyValue
}

function Get-MaviVisionNotePropertyNames {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return @() }
    return @($Value.PSObject.Properties | Where-Object { $_.MemberType -eq "NoteProperty" } | ForEach-Object { [string]$_.Name })
}

function Assert-MaviVisionExactFields {
    param(
        [AllowNull()][object]$Value,
        [Parameter(Mandatory = $true)][string[]]$Expected,
        [Parameter(Mandatory = $true)][string]$Description
    )
    if ($null -eq $Value) { throw "Vision $Description is missing." }
    $names = @(Get-MaviVisionNotePropertyNames -Value $Value)
    foreach ($name in $names) {
        if ($Expected -cnotcontains $name) { throw "Vision $Description has unexpected field '$name'." }
    }
    foreach ($name in $Expected) {
        if ($names -cnotcontains $name) { throw "Vision $Description is missing '$name'." }
    }
}

function Test-MaviVisionLowerSha256 {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value -or -not ($Value -is [string])) { return $false }
    return ([string]$Value) -cmatch '^[0-9a-f]{64}$'
}

function Test-MaviVisionNonNegativeInteger {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return $false }
    if (-not (($Value -is [int]) -or ($Value -is [long]))) { return $false }
    return ([long]$Value -ge 0)
}

function Test-MaviVisionModelPackRelativePath {
    <#
    .SYNOPSIS
    A Model Pack artefact path: logical, forward-slash, at least
    <packDirectory>/<file>, and never able to leave its pack directory.

    Stricter than the Python logical-path validator in two Windows-motivated
    ways: ':' is refused anywhere (drive-relative paths and NTFS alternate data
    streams), and the pack directory may not start with '.' because the store
    reserves dot-prefixed names for the installer's stage and rollback
    directories, which the launcher's store scan skips.
    #>
    param([AllowNull()][object]$Value)
    if ($null -eq $Value -or -not ($Value -is [string])) { return $false }
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text) -or $text -cne $text.Trim()) { return $false }
    if ($text.Contains("\") -or $text.Contains([string][char]0) -or $text.Contains(":") -or $text.StartsWith("/")) { return $false }
    $parts = $text.Split('/')
    if ($parts.Count -lt 2) { return $false }
    foreach ($part in $parts) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") { return $false }
    }
    if ($parts[0].StartsWith(".")) { return $false }
    return $true
}

function Assert-MaviVisionModelPackManifest {
    <#
    .SYNOPSIS
    Validate a built `mavi-vision-model-pack-v2` manifest (plan §5.4, §7, P-10).

    The shape is exactly what tools/vision/build_model_pack.py emits: seven
    fields, sorted unique capabilityIds, and artefacts sorted by relativePath
    with exactly {artifactRole, relativePath, sha256, sizeBytes}. Every
    relativePath shares one first segment, the pack directory, so the pack is
    self-contained in <store>/<packDirectory>. The licence notice is a required
    artefact (P-15). Anything else, the v1 pack schema included, is refused.
    #>
    param([Parameter(Mandatory = $true)][object]$Manifest)

    $schema = [string](Get-MaviVisionRequiredProperty -Value $Manifest -Name "schemaVersion" -Description "model manifest")
    if ($schema -cne $script:VisionModelPackSchema) {
        throw "Unsupported vision model manifest schema '$schema'; expected '$script:VisionModelPackSchema'."
    }
    Assert-MaviVisionExactFields -Value $Manifest -Expected $script:VisionModelPackManifestFields -Description "model manifest"

    $packId = Get-MaviVisionPropertyValue -Value $Manifest -Name "modelPackId"
    if (-not ($packId -is [string]) -or $packId -cnotmatch '^mavi-model-v2-[0-9a-f]{64}$') {
        throw "Vision model manifest Model Pack ID is invalid."
    }
    foreach ($name in @("modelId", "modelVersion")) {
        $text = Get-MaviVisionPropertyValue -Value $Manifest -Name $name
        if (-not ($text -is [string]) -or [string]::IsNullOrWhiteSpace($text)) {
            throw "Vision model manifest '$name' is invalid."
        }
    }
    $assembled = Get-MaviVisionPropertyValue -Value $Manifest -Name "assembledFromCommit"
    if (-not ($assembled -is [string]) -or $assembled -cnotmatch '^[0-9a-f]{40}$') {
        throw "Vision model manifest assembled-from commit is invalid."
    }

    # Read list-valued fields by direct assignment, never through a function's
    # output: PowerShell unrolls a returned array, so a one-element list would
    # come back as a scalar and a JSON string would be indistinguishable from it.
    $capabilityValue = $Manifest.PSObject.Properties["capabilityIds"].Value
    if ($null -eq $capabilityValue -or -not ($capabilityValue -is [array]) -or @($capabilityValue).Count -lt 1) {
        throw "Vision model manifest 'capabilityIds' must be a non-empty list."
    }
    $previousCapability = $null
    foreach ($capabilityId in @($capabilityValue)) {
        if (-not ($capabilityId -is [string]) -or [string]$capabilityId -cnotmatch '^[a-z][a-z0-9-]*$') {
            throw "Vision model manifest capability id '$capabilityId' is invalid."
        }
        if ($null -ne $previousCapability -and [string]::CompareOrdinal($previousCapability, [string]$capabilityId) -ge 0) {
            throw "Vision model manifest 'capabilityIds' must be sorted and unique."
        }
        $previousCapability = [string]$capabilityId
    }

    $artifactValue = $Manifest.PSObject.Properties["artifacts"].Value
    if ($null -eq $artifactValue -or -not ($artifactValue -is [array]) -or @($artifactValue).Count -lt 1) {
        throw "Vision model manifest 'artifacts' must be a non-empty list."
    }
    $roles = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::Ordinal)
    # Case-insensitive: two paths differing only in case would collide on NTFS.
    $paths = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    $packDirectory = $null
    $previousPath = $null
    foreach ($artifact in @($artifactValue)) {
        Assert-MaviVisionExactFields -Value $artifact -Expected $script:VisionModelPackArtifactFields -Description "model manifest artifact"
        $role = $artifact.artifactRole
        if (-not ($role -is [string]) -or [string]::IsNullOrWhiteSpace($role)) { throw "Vision model manifest artifact role is invalid." }
        if (-not $roles.Add([string]$role)) { throw "Vision model manifest artifact role '$role' is duplicated." }
        $relative = $artifact.relativePath
        if (-not (Test-MaviVisionModelPackRelativePath $relative)) { throw "Unsafe artifact path in Vision Model Pack manifest: '$relative'." }
        if (-not $paths.Add([string]$relative)) { throw "Duplicate artifact path in Vision Model Pack manifest: '$relative'." }
        $first = ([string]$relative).Split('/')[0]
        if ($null -eq $packDirectory) { $packDirectory = $first }
        elseif ($first -cne $packDirectory) { throw "Vision Model Pack artefacts must share one pack directory; '$relative' is outside '$packDirectory'." }
        if ($null -ne $previousPath -and [string]::CompareOrdinal($previousPath, [string]$relative) -ge 0) {
            throw "Vision model manifest artefacts must be sorted by relativePath."
        }
        $previousPath = [string]$relative
        foreach ($reserved in $script:VisionModelPackReservedNames) {
            if ([string]::Equals([string]$relative, ($packDirectory + "/" + $reserved), [StringComparison]::OrdinalIgnoreCase)) {
                throw "Vision Model Pack artefact path '$relative' is reserved for installation metadata."
            }
        }
        if (-not (Test-MaviVisionNonNegativeInteger $artifact.sizeBytes)) { throw "Vision model manifest artefact '$relative' has an invalid sizeBytes." }
        if (-not (Test-MaviVisionLowerSha256 $artifact.sha256)) { throw "Vision model manifest artefact '$relative' has an invalid sha256." }
    }
    if (-not $roles.Contains("licence-notice")) {
        throw "Vision Model Pack manifest must carry its licence notice (artifactRole 'licence-notice')."
    }
    return $true
}

function Get-MaviVisionModelPackDirectory {
    <#
    .SYNOPSIS
    The one directory a v2 Model Pack occupies in the store (P-10).
    #>
    param([Parameter(Mandatory = $true)][object]$Manifest)
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    return ([string]@($Manifest.artifacts)[0].relativePath).Split('/')[0]
}

function Get-MaviVisionModelPackArtifactSha256Map {
    <#
    .SYNOPSIS
    {artifactRole: sha256} of a v2 pack manifest, ordered by role.
    #>
    param([Parameter(Mandatory = $true)][object]$Manifest)
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    $roles = [string[]]@(@($Manifest.artifacts) | ForEach-Object { [string]$_.artifactRole })
    [Array]::Sort($roles, [StringComparer]::Ordinal)
    $map = [ordered]@{}
    foreach ($role in $roles) {
        $artifact = @(@($Manifest.artifacts) | Where-Object { [string]$_.artifactRole -ceq $role })[0]
        $map[$role] = [string]$artifact.sha256
    }
    return $map
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
    <#
    .SYNOPSIS
    The v2 `model-install.json` of one pack directory (plan §5.4, erratum E-8).

    installRoot is the Model Pack store root the pack was installed into, the
    value the launcher passes as MAVI_MODEL_ROOT: every artefact resolves at
    <installRoot>/<relativePath>. Sizes are not repeated here; the state binds
    the built pack manifest, which carries them, by SHA-256.
    #>
    param(
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$ModelPackManifestSha256,
        [Parameter(Mandatory = $true)][string]$InstallRoot
    )
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    $manifestSha = $ModelPackManifestSha256.ToLowerInvariant()
    if (-not (Test-MaviVisionLowerSha256 $manifestSha)) {
        throw "Vision model pack manifest SHA-256 is invalid."
    }
    if ([string]::IsNullOrWhiteSpace($InstallRoot)) {
        throw "Vision model installation root is required."
    }
    $capabilityIds = @(@($Manifest.capabilityIds) | ForEach-Object { [string]$_ })
    return [pscustomobject][ordered]@{
        schemaVersion = $script:VisionModelInstallSchema
        modelPackId = [string]$Manifest.modelPackId
        modelId = [string]$Manifest.modelId
        capabilityIds = $capabilityIds
        artifactSha256 = [pscustomobject](Get-MaviVisionModelPackArtifactSha256Map -Manifest $Manifest)
        modelPackManifestSha256 = $manifestSha
        installedAtUtc = [DateTime]::UtcNow.ToString("O", [Globalization.CultureInfo]::InvariantCulture)
        installRoot = [string]$InstallRoot
    }
}

function Get-MaviVisionModelInstallStateMismatch {
    <#
    .SYNOPSIS
    $null when a v2 install state describes exactly this pack manifest,
    otherwise the name of the first field that does not.

    Compared: the exact v2 field set, schema, modelPackId, modelId,
    capabilityIds (in order), and the artefact SHA-256 of every role, with no
    role missing or extra. The manifest fingerprint is checked for syntax only
    here; binding it to the installed manifest bytes is the caller's job,
    because only the caller has those bytes.
    #>
    param(
        [AllowNull()][object]$State,
        [Parameter(Mandatory = $true)][object]$Manifest
    )
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    if ($null -eq $State) { return "state" }
    $names = @(Get-MaviVisionNotePropertyNames -Value $State)
    foreach ($name in $names) { if ($script:VisionModelInstallFields -cnotcontains $name) { return "unexpected field $name" } }
    foreach ($name in $script:VisionModelInstallFields) { if ($names -cnotcontains $name) { return "missing field $name" } }
    if ((Get-MaviVisionPropertyText -Value $State -Name "schemaVersion") -cne $script:VisionModelInstallSchema) { return "schemaVersion" }
    if ((Get-MaviVisionPropertyText -Value $State -Name "modelPackId") -cne [string]$Manifest.modelPackId) { return "modelPackId" }
    if ((Get-MaviVisionPropertyText -Value $State -Name "modelId") -cne [string]$Manifest.modelId) { return "modelId" }
    # Direct assignment keeps a one-element JSON list a list (see
    # Assert-MaviVisionModelPackManifest).
    $stateCapabilities = $State.PSObject.Properties["capabilityIds"].Value
    if ($null -eq $stateCapabilities -or -not ($stateCapabilities -is [array])) { return "capabilityIds" }
    if ((@($stateCapabilities | ForEach-Object { [string]$_ }) -join "`n") -cne (@($Manifest.capabilityIds) -join "`n")) { return "capabilityIds" }
    $expected = Get-MaviVisionModelPackArtifactSha256Map -Manifest $Manifest
    $stateArtifacts = Get-MaviVisionPropertyValue -Value $State -Name "artifactSha256"
    if ($null -eq $stateArtifacts -or $stateArtifacts -is [string] -or $stateArtifacts -is [array]) { return "artifactSha256" }
    $stateRoles = @(Get-MaviVisionNotePropertyNames -Value $stateArtifacts)
    foreach ($role in $stateRoles) { if (-not $expected.Contains($role)) { return "artifactSha256.$role" } }
    foreach ($role in $expected.Keys) {
        $recorded = Get-MaviVisionPropertyValue -Value $stateArtifacts -Name ([string]$role)
        if (-not ($recorded -is [string]) -or [string]$recorded -cne [string]$expected[$role]) { return "artifactSha256.$role" }
    }
    if (-not (Test-MaviVisionLowerSha256 (Get-MaviVisionPropertyValue -Value $State -Name "modelPackManifestSha256"))) { return "modelPackManifestSha256" }
    return $null
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
    # v2: the candidate is reusable only if the installed v2 state describes
    # the same content-addressed pack (id, model, capabilities and every
    # artefact SHA-256) and binds the installed manifest bytes. The candidate's
    # assembledFromCommit is provenance, not identity, and does not block reuse.
    [void](Assert-MaviVisionModelPackManifest -Manifest $Manifest)
    $manifestSha = $ModelPackManifestSha256.ToLowerInvariant()
    if (-not (Test-MaviVisionLowerSha256 $manifestSha)) { return $false }
    if ($null -eq $InstalledState) { return $false }
    if ((Get-MaviVisionPropertyText -Value $InstalledState -Name "schemaVersion") -cne $script:VisionModelInstallSchema) { return $false }
    if ($null -ne (Get-MaviVisionModelInstallStateMismatch -State $InstalledState -Manifest $Manifest)) { return $false }
    return ((Get-MaviVisionPropertyText -Value $InstalledState -Name "modelPackManifestSha256") -ceq $manifestSha)
}

function Assert-MaviVisionWorkerComponentCompatibility {
    param(
        [Parameter(Mandatory = $true)][object]$RuntimeState,
        [Parameter(Mandatory = $true)][object]$RuntimeManifest,
        [Parameter(Mandatory = $true)][string]$RequiredRuntimePackId,
        [Parameter(Mandatory = $true)][string]$RequiredThirdPartyLockSha256,
        [Parameter(Mandatory = $true)][string]$RequiredRuntimeRequirementsSha256,
        # One entry per enabled capability binding of the role, each with
        # CapabilityId, ModelPackId (the binding's), ModelState (the installed
        # v2 model-install.json) and ModelManifest (the installed
        # model-pack-manifest.json). Resolve-MaviVisionBoundModelPacks returns
        # entries of exactly this shape.
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$RequiredModelPacks
    )

    [void](Assert-MaviVisionRuntimePackManifest -Manifest $RuntimeManifest)

    if (-not $RuntimeState.PSObject.Properties["schemaVersion"] -or [string]$RuntimeState.schemaVersion -ne $script:VisionRuntimeInstallSchema) {
        throw "Vision runtime installed state schema is unsupported; reinstall the v2 Runtime Pack."
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

    # Model Packs: every enabled capability binding of the role must be
    # satisfied by an installed pack whose manifest and v2 install state both
    # carry the binding's modelPackId, and whose install state records exactly
    # the manifest's artefact SHA-256 for every role. The id is compared, never
    # re-derived here (P-3 derivation is the Python resolver's).
    $requiredPacks = @($RequiredModelPacks)
    if ($requiredPacks.Count -lt 1) {
        throw "Vision role requires at least one bound Model Pack; none was supplied."
    }
    foreach ($entry in $requiredPacks) {
        $required = $entry
        if ($required -is [System.Collections.IDictionary]) { $required = [pscustomobject]$required }
        $capabilityId = [string](Get-MaviVisionRequiredProperty -Value $required -Name "CapabilityId" -Description "required Model Pack")
        $requiredModelPackId = [string](Get-MaviVisionRequiredProperty -Value $required -Name "ModelPackId" -Description "required Model Pack")
        $modelState = Get-MaviVisionPropertyValue -Value $required -Name "ModelState"
        $modelManifest = Get-MaviVisionPropertyValue -Value $required -Name "ModelManifest"
        if ($null -eq $modelState -or $null -eq $modelManifest) {
            throw "Vision Model Pack '$requiredModelPackId' for capability '$capabilityId' is not installed."
        }
        [void](Assert-MaviVisionModelPackManifest -Manifest $modelManifest)
        if ((Get-MaviVisionPropertyText -Value $modelState -Name "schemaVersion") -cne $script:VisionModelInstallSchema) {
            throw "Vision model installed state schema is unsupported; reinstall the Model Pack."
        }
        if ((Get-MaviVisionPropertyText -Value $modelState -Name "modelPackId") -cne $requiredModelPackId -or [string]$modelManifest.modelPackId -cne $requiredModelPackId) {
            throw "Vision Model Pack ID mismatch for capability '$capabilityId'. Required '$requiredModelPackId'."
        }
        if (@($modelManifest.capabilityIds) -cnotcontains $capabilityId) {
            throw "Vision Model Pack '$requiredModelPackId' does not provide capability '$capabilityId'."
        }
        $mismatch = Get-MaviVisionModelInstallStateMismatch -State $modelState -Manifest $modelManifest
        if ($null -ne $mismatch) {
            throw "Vision Model Pack installed state does not match its manifest ($mismatch) for '$requiredModelPackId'."
        }
    }
    return $true
}

function Get-MaviVisionBindingRole {
    <#
    .SYNOPSIS
    Read one role out of a `mavi-vision-component-binding-v2` binding.

    Returns RoleId, RuntimePackFamilyId, Variants (the family's variant map)
    and CapabilityBindings: one {CapabilityId, ModelPackId, QualificationId}
    per capability of the role, each of which must be bound exactly once and
    enabled. A disabled binding cannot start its role (plan §4.1 rule 4). This
    is a launch-time reading of the binding, not its validator: the Python
    loader (mavi_vision/runtime/binding.py) and verify_repo own the full rules.
    #>
    param(
        [AllowNull()][object]$Binding,
        [Parameter(Mandatory = $true)][string]$RoleId
    )
    $schema = Get-MaviVisionPropertyText -Value $Binding -Name "schemaVersion"
    if ($schema -cne $script:VisionComponentBindingSchema) {
        throw "Unsupported Vision component binding schema '$schema'; expected '$script:VisionComponentBindingSchema'."
    }
    $roles = @(@(Get-MaviVisionPropertyValue -Value $Binding -Name "roles") | Where-Object { (Get-MaviVisionPropertyText -Value $_ -Name "roleId") -ceq $RoleId })
    if ($roles.Count -ne 1) { throw "Vision component binding must declare role '$RoleId' exactly once." }
    $role = $roles[0]
    $familyId = Get-MaviVisionPropertyText -Value $role -Name "runtimePackFamilyId"
    # The family id names a directory under src/vision/runtime.
    if ($familyId -cnotmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { throw "Vision component binding role '$RoleId' has an invalid runtimePackFamilyId." }
    $families = @(@(Get-MaviVisionPropertyValue -Value $Binding -Name "runtimePacks") | Where-Object { (Get-MaviVisionPropertyText -Value $_ -Name "runtimePackFamilyId") -ceq $familyId })
    if ($families.Count -ne 1) { throw "Vision component binding must declare Runtime Pack family '$familyId' exactly once." }
    $variants = Get-MaviVisionPropertyValue -Value $families[0] -Name "variants"
    if ($null -eq $variants -or $variants -is [string] -or $variants -is [array]) { throw "Vision component binding Runtime Pack family '$familyId' has no variants." }

    $roleCapabilities = @(@(Get-MaviVisionPropertyValue -Value $role -Name "capabilityIds") | Where-Object { $null -ne $_ } | ForEach-Object { [string]$_ })
    if ($roleCapabilities.Count -lt 1) { throw "Vision component binding role '$RoleId' declares no capability." }
    $roleBindings = @(@(Get-MaviVisionPropertyValue -Value $Binding -Name "capabilityBindings") | Where-Object { (Get-MaviVisionPropertyText -Value $_ -Name "roleId") -ceq $RoleId })
    $capabilityBindings = New-Object System.Collections.Generic.List[object]
    foreach ($capabilityId in $roleCapabilities) {
        $matching = @($roleBindings | Where-Object { (Get-MaviVisionPropertyText -Value $_ -Name "capabilityId") -ceq $capabilityId })
        if ($matching.Count -ne 1) { throw "Vision component binding must bind capability '$capabilityId' of role '$RoleId' exactly once." }
        $enabled = Get-MaviVisionPropertyValue -Value $matching[0] -Name "enabled"
        if (-not ($enabled -is [bool]) -or -not $enabled) { throw "Vision component binding for capability '$capabilityId' is disabled." }
        $modelPackId = Get-MaviVisionPropertyText -Value $matching[0] -Name "modelPackId"
        if ($modelPackId -cnotmatch '^mavi-model-v2-[0-9a-f]{64}$') { throw "Vision component binding for capability '$capabilityId' has an invalid modelPackId." }
        $qualificationId = Get-MaviVisionPropertyText -Value $matching[0] -Name "qualificationId"
        if ([string]::IsNullOrWhiteSpace($qualificationId)) { throw "Vision component binding for capability '$capabilityId' has no qualificationId." }
        $capabilityBindings.Add([pscustomobject][ordered]@{
            CapabilityId = $capabilityId
            ModelPackId = $modelPackId
            QualificationId = $qualificationId
        })
    }
    return [pscustomobject][ordered]@{
        RoleId = $RoleId
        RuntimePackFamilyId = $familyId
        Variants = $variants
        CapabilityBindings = $capabilityBindings.ToArray()
    }
}

function Get-MaviVisionBindingRuntimeRequirement {
    <#
    .SYNOPSIS
    The binding's Runtime Pack entry for one variant of the role's family, or
    $null when the binding declares no complete entry for it.

    Never throws for an absent or partial entry: an omission is reported as
    absent, and the caller decides what absent means (the launcher refuses;
    Development Auto chooses CPU).
    #>
    param(
        [Parameter(Mandatory = $true)][object]$BindingRole,
        [Parameter(Mandatory = $true)][string]$Variant
    )
    $entry = Get-MaviVisionPropertyValue -Value (Get-MaviVisionPropertyValue -Value $BindingRole -Name "Variants") -Name $Variant
    if ($null -eq $entry -or $entry -is [string] -or $entry -is [array]) { return $null }
    foreach ($name in @("runtimePackId", "thirdPartyLockSha256", "runtimeRequirementsSha256", "nativeAbi")) {
        if ([string]::IsNullOrWhiteSpace((Get-MaviVisionPropertyText -Value $entry -Name $name))) { return $null }
    }
    return $entry
}

function Resolve-MaviVisionBoundModelPacks {
    <#
    .SYNOPSIS
    Find, in a Model Pack store, the installed pack of every capability binding.

    .DESCRIPTION
    The store holds one self-contained directory per pack (plan P-10). This
    scans exactly one level, <store>/*/model-pack-manifest.json, and matches
    each binding's modelPackId against the manifests' modelPackId field. It
    never re-derives the id (P-3 derivation is the Python resolver's), and
    never looks deeper, so a pack is found only where the installer puts it.
    Dot-prefixed directories are the installer's stage and rollback
    directories and are skipped.

    Each result carries a Status, which the launcher turns into its stable
    refusal code:
      not-installed      no store directory carries the id
      ambiguous          more than one does
      state-missing      the one match has no model-install.json
      state-unsupported  its model-install.json is not v2 (a v1 state)
      installed          one match with a v2 state; PackDirectory is now fixed
    and, for installed, ModelManifest and ModelState, so the result can be
    passed straight to Assert-MaviVisionWorkerComponentCompatibility
    -RequiredModelPacks.

    LegacyInstallation is true when the store root itself is a v1 per-model
    installation (model-install.json directly under it), which is what an
    inherited pre-cut-over MAVI_VISION_MODEL_ROOT points at.

    An unreadable manifest anywhere in the store, or an unreadable state in the
    matched directory, is an error rather than a skip: an unreadable manifest
    could be hiding a second copy of the id, so uniqueness cannot be shown.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$StoreRoot,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$CapabilityBindings
    )
    $store = [IO.Path]::GetFullPath($StoreRoot.Trim().Trim('"'))
    $index = New-Object System.Collections.Generic.List[object]
    $legacy = $false
    if (Test-Path -LiteralPath $store -PathType Container) {
        $legacy = Test-Path -LiteralPath (Join-Path $store "model-install.json") -PathType Leaf
        foreach ($directory in @(Get-ChildItem -LiteralPath $store -Directory -Force | Sort-Object Name)) {
            if ($directory.Name.StartsWith(".")) { continue }
            $manifestPath = Join-Path $directory.FullName "model-pack-manifest.json"
            if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { continue }
            $manifestValue = $null
            try { $manifestValue = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json }
            catch { throw "Vision Model Pack store manifest is unreadable: $manifestPath" }
            $index.Add([pscustomobject][ordered]@{
                ModelPackId = Get-MaviVisionPropertyText -Value $manifestValue -Name "modelPackId"
                PackDirectory = $directory.Name
                PackPath = $directory.FullName
                ManifestPath = $manifestPath
                Manifest = $manifestValue
            })
        }
    }

    $results = New-Object System.Collections.Generic.List[object]
    foreach ($binding in @($CapabilityBindings)) {
        $capabilityId = Get-MaviVisionPropertyText -Value $binding -Name "CapabilityId"
        $modelPackId = Get-MaviVisionPropertyText -Value $binding -Name "ModelPackId"
        $candidates = @($index | Where-Object { $_.ModelPackId -ceq $modelPackId -and -not [string]::IsNullOrEmpty($modelPackId) })
        $status = "installed"
        $packDirectory = $null
        $packPath = $null
        $manifestPath = $null
        $statePath = $null
        $manifestValue = $null
        $stateValue = $null
        if ($candidates.Count -eq 0) {
            $status = "not-installed"
        }
        elseif ($candidates.Count -gt 1) {
            $status = "ambiguous"
        }
        else {
            $packDirectory = $candidates[0].PackDirectory
            $packPath = $candidates[0].PackPath
            $manifestPath = $candidates[0].ManifestPath
            $manifestValue = $candidates[0].Manifest
            $statePath = Join-Path $packPath "model-install.json"
            if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
                $status = "state-missing"
            }
            else {
                try { $stateValue = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
                catch { throw "Vision Model Pack installed state is unreadable: $statePath" }
                if ((Get-MaviVisionPropertyText -Value $stateValue -Name "schemaVersion") -cne $script:VisionModelInstallSchema) {
                    $status = "state-unsupported"
                }
            }
        }
        $results.Add([pscustomobject][ordered]@{
            CapabilityId = $capabilityId
            ModelPackId = $modelPackId
            Status = $status
            Candidates = @($candidates | ForEach-Object { $_.PackPath })
            PackDirectory = $packDirectory
            PackPath = $packPath
            ManifestPath = $manifestPath
            StatePath = $statePath
            ModelManifest = $manifestValue
            ModelState = $stateValue
        })
    }
    return [pscustomobject][ordered]@{
        StoreRoot = $store
        LegacyInstallation = [bool]$legacy
        ModelPacks = $results.ToArray()
    }
}

function Find-MaviVisionOverlayRecords {
    <#
    .SYNOPSIS
    Every *.json directly under an overlay directory whose top-level
    $PropertyName equals $Value (e.g. qualification records by qualificationId,
    plan P-9). Unreadable JSON is an error, not a skip.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$PropertyName,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )
    $found = New-Object System.Collections.Generic.List[object]
    if ([string]::IsNullOrEmpty($Value) -or -not (Test-Path -LiteralPath $Directory -PathType Container)) { return $found.ToArray() }
    foreach ($file in @(Get-ChildItem -LiteralPath $Directory -Filter "*.json" -File | Sort-Object Name)) {
        $record = $null
        try { $record = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json }
        catch { throw "Vision overlay record is unreadable: $($file.FullName)" }
        if ((Get-MaviVisionPropertyText -Value $record -Name $PropertyName) -ceq $Value) {
            $found.Add([pscustomobject][ordered]@{ Path = $file.FullName; Record = $record })
        }
    }
    return $found.ToArray()
}

function Get-MaviVisionRetiredCompositionEnvironment {
    return $script:VisionRetiredCompositionEnvironment
}

function Clear-MaviVisionRetiredCompositionEnvironment {
    <#
    .SYNOPSIS
    Remove every retired composition variable from this process's environment,
    whatever its case, so the worker the launcher starts never inherits one.

    The worker fails closed (settings_v1_composition_rejected) on any of them,
    even an empty one, so clearing means absent, not set to "". Returns the
    names that were removed. MAVI_COMPLETION_SCHEMA_OVERRIDE is not retired and
    is left exactly as the operator set it.
    #>
    $cleared = New-Object System.Collections.Generic.List[string]
    $names = @([Environment]::GetEnvironmentVariables([EnvironmentVariableTarget]::Process).Keys | ForEach-Object { [string]$_ })
    foreach ($name in $names) {
        foreach ($retired in $script:VisionRetiredCompositionEnvironment) {
            if ([string]::Equals($name, $retired, [StringComparison]::OrdinalIgnoreCase)) {
                [Environment]::SetEnvironmentVariable($name, [NullString]::Value, [EnvironmentVariableTarget]::Process)
                if ($null -ne [Environment]::GetEnvironmentVariable($name, [EnvironmentVariableTarget]::Process)) {
                    throw "Unable to clear retired composition variable '$name'."
                }
                $cleared.Add($name)
            }
        }
    }
    return $cleared.ToArray()
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
        [Parameter(Mandatory = $true)][string]$ComponentBindingPath,
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

    if (-not (Test-Path -LiteralPath $ComponentBindingPath -PathType Leaf)) {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    # Component binding v2 (plan §5.5, P-13): the declared CUDA Runtime Pack is
    # runtimePacks[family].variants["windows-x86_64-cuda"] for the family of
    # role `vision`. Every way of not declaring it -- a missing or unreadable
    # file, a v1 binding, no vision role, no family entry, no CUDA variant, a
    # CUDA variant without a complete entry -- is the same answer, and none of
    # them reaches the driver. Declaring it is not a Production or verified
    # claim: its release lock stays pending-hardware-qualification and this
    # decision is Development Auto only.
    $cudaRequirement = $null
    try {
        $bindingValue = Get-Content -LiteralPath $ComponentBindingPath -Raw | ConvertFrom-Json
        $bindingRole = Get-MaviVisionBindingRole -Binding $bindingValue -RoleId "vision"
        $cudaRequirement = Get-MaviVisionBindingRuntimeRequirement -BindingRole $bindingRole -Variant "windows-x86_64-cuda"
    }
    catch {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    if ($null -eq $cudaRequirement) {
        $result.Reason = "cuda_pack_not_declared"
        return [pscustomobject]$result
    }
    if ([string]$cudaRequirement.runtimePackId -ne [string]$manifestValue.runtimePackId) {
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
