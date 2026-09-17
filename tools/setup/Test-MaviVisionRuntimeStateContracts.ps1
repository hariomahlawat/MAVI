[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modulePath = Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1"
Import-Module $modulePath -Force

function Assert-Throws {
    param(
        [Parameter(Mandatory = $true)][scriptblock]$Script,
        [Parameter(Mandatory = $true)][string]$MessageFragment
    )
    $thrown = $false
    try {
        & $Script
    }
    catch {
        $thrown = $true
        if ($_.Exception.Message -notlike "*$MessageFragment*") {
            throw "Expected error containing '$MessageFragment', got '$($_.Exception.Message)'."
        }
    }
    if (-not $thrown) {
        throw "Expected failure containing '$MessageFragment'."
    }
}

$manifest = [pscustomobject]@{
    schemaVersion = "mavi-vision-runtime-pack-v2"
    runtimePackId = "runtime-pack-abc123"
    platformVariant = "windows-x86_64-cpu"
    pythonVersion = "3.12.10"
    nativeAbi = "win_amd64-msvc-14.44-sdk-10.0.26100.0"
    thirdPartyLockSha256 = ("a" * 64)
    runtimeRequirementsSha256 = ("b" * 64)
    assembledFromCommit = ("1" * 40)
    artifacts = @()
}
$manifestSha = "c" * 64
$state = New-MaviVisionRuntimeInstallState `
    -Manifest $manifest `
    -RuntimePackManifestSha256 $manifestSha `
    -RuntimeRoot "C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu" `
    -PythonIdentity ([pscustomobject]@{
        version = "3.12.10"
        implementation = "CPython"
        build = @("tags/v3.12.10:fixture", "fixture")
        compiler = "MSC v.1943 64 bit (AMD64)"
    })

if ([string]$state.schemaVersion -ne "mavi-vision-runtime-install-v2") {
    throw "Vision runtime state did not use v2 schema."
}
foreach ($name in @(
    "runtimePackId",
    "runtimePackManifestSha256",
    "thirdPartyLockSha256",
    "runtimeRequirementsSha256",
    "platformVariant",
    "pythonVersion",
    "nativeAbi",
    "pythonIdentity",
    "runtimeRoot"
)) {
    if (-not $state.PSObject.Properties[$name]) {
        throw "Vision runtime v2 state is missing '$name'."
    }
}

if (-not (Test-MaviVisionRuntimePackReuse `
    -InstalledState $state `
    -Manifest $manifest `
    -RuntimePackManifestSha256 $manifestSha `
    -PythonIdentity $state.pythonIdentity)) {
    throw "Identical v2 Runtime Pack was not reusable."
}

$sourceOnlyManifest = $manifest.PSObject.Copy()
$sourceOnlyManifest.assembledFromCommit = "2" * 40
if (-not (Test-MaviVisionRuntimePackReuse `
    -InstalledState $state `
    -Manifest $sourceOnlyManifest `
    -RuntimePackManifestSha256 $manifestSha `
    -PythonIdentity $state.pythonIdentity)) {
    throw "Source-only commit provenance incorrectly invalidated Runtime Pack reuse."
}

$changedManifest = $manifest.PSObject.Copy()
$changedManifest.runtimePackId = "runtime-pack-different"
if (Test-MaviVisionRuntimePackReuse `
    -InstalledState $state `
    -Manifest $changedManifest `
    -RuntimePackManifestSha256 $manifestSha `
    -PythonIdentity $state.pythonIdentity) {
    throw "Different Runtime Pack ID was incorrectly reusable."
}

$wrongPython = [pscustomobject]@{
    version = "3.12.11"
    implementation = "CPython"
    build = $state.pythonIdentity.build
    compiler = $state.pythonIdentity.compiler
}
if (Test-MaviVisionRuntimePackReuse `
    -InstalledState $state `
    -Manifest $manifest `
    -RuntimePackManifestSha256 $manifestSha `
    -PythonIdentity $wrongPython) {
    throw "Different Python identity was incorrectly reusable."
}

$v1 = [pscustomobject]@{
    schemaVersion = "mavi-vision-runtime-install-v1"
    runtimePackId = $manifest.runtimePackId
}
if (Test-MaviVisionRuntimePackReuse `
    -InstalledState $v1 `
    -Manifest $manifest `
    -RuntimePackManifestSha256 $manifestSha `
    -PythonIdentity $state.pythonIdentity) {
    throw "Legacy v1 installed state was incorrectly accepted for v2 reuse."
}

Assert-Throws -MessageFragment "runtime manifest schema" -Script {
    $bad = $manifest.PSObject.Copy()
    $bad.schemaVersion = "1.0"
    Assert-MaviVisionRuntimePackManifest -Manifest $bad
}

Assert-Throws -MessageFragment "third-party lock SHA-256" -Script {
    $bad = $manifest.PSObject.Copy()
    $bad.thirdPartyLockSha256 = "not-a-sha"
    Assert-MaviVisionRuntimePackManifest -Manifest $bad
}

$installerText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MaviVisionRuntime.ps1") -Raw
foreach ($required in @(
    "runtime-pack-manifest.json",
    "mavi-vision-runtime-pack-v2",
    "mavi-vision-runtime-install-v2",
    "Test-MaviVisionRuntimePackReuse",
    "New-MaviVisionRuntimeInstallState",
    "thirdPartyLockSha256",
    "runtimeRequirementsSha256"
)) {
    if ($installerText -notmatch [regex]::Escape($required)) {
        throw "Vision runtime installer is missing v2 contract fragment: $required"
    }
}
foreach ($forbidden in @(
    "Assert-MaviVisionRuntimeSourceCompatible",
    "BundleSourceCommit"
)) {
    if ($installerText -match [regex]::Escape($forbidden)) {
        throw "Vision runtime installer still uses obsolete commit-coupled contract: $forbidden"
    }
}

Write-Host "MAVI Vision runtime v2 state contracts: OK" -ForegroundColor Green
