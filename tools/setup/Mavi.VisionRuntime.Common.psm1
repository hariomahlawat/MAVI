Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:VisionRuntimePackSchema = "mavi-vision-runtime-pack-v2"
$script:VisionRuntimeInstallSchema = "mavi-vision-runtime-install-v2"

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

    $artifactsProperty = $Manifest.PSObject.Properties["artifacts"]
    if (-not $artifactsProperty) {
        throw "Vision runtime manifest is missing 'artifacts'."
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

function Test-MaviVisionPythonIdentityEqual {
    param(
        [AllowNull()][object]$Left,
        [AllowNull()][object]$Right
    )
    if ($null -eq $Left -or $null -eq $Right) { return $false }
    foreach ($name in @("version", "implementation", "compiler")) {
        $leftProperty = $Left.PSObject.Properties[$name]
        $rightProperty = $Right.PSObject.Properties[$name]
        if (-not $leftProperty -or -not $rightProperty -or [string]$leftProperty.Value -ne [string]$rightProperty.Value) {
            return $false
        }
    }
    $leftBuildProperty = $Left.PSObject.Properties["build"]
    $rightBuildProperty = $Right.PSObject.Properties["build"]
    if (-not $leftBuildProperty -or -not $rightBuildProperty) { return $false }
    $leftBuild = @($leftBuildProperty.Value)
    $rightBuild = @($rightBuildProperty.Value)
    if ($leftBuild.Count -ne 2 -or $rightBuild.Count -ne 2) { return $false }
    return ([string]$leftBuild[0] -eq [string]$rightBuild[0] -and [string]$leftBuild[1] -eq [string]$rightBuild[1])
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
    if (-not $schemaProperty -or [string]$schemaProperty.Value -ne $script:VisionRuntimeInstallSchema) {
        return $false
    }

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
        if (-not $property -or [string]$property.Value -ne [string]$comparisons[$name]) {
            return $false
        }
    }

    $identityProperty = $InstalledState.PSObject.Properties["pythonIdentity"]
    if (-not $identityProperty -or -not (Test-MaviVisionPythonIdentityEqual -Left $identityProperty.Value -Right $PythonIdentity)) {
        return $false
    }
    return $true
}

Export-ModuleMember -Function *
