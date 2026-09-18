[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

$manifest = [pscustomobject]@{
    schemaVersion = "mavi-vision-model-pack-v1"
    modelPackId = ("mavi-model-v1-" + ("a" * 64))
    modelId = "rtmdet-m-coco-phase1"
    checkpointSha256 = ("b" * 64)
    resolvedConfigSha256 = ("c" * 64)
    assembledFromCommit = ("1" * 40)
    artifacts = @()
}
$manifestSha = "d" * 64
$state = New-MaviVisionModelInstallState `
    -Manifest $manifest `
    -ModelPackManifestSha256 $manifestSha `
    -ModelRoot "C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1"

if ([string]$state.schemaVersion -ne "mavi-vision-model-install-v1") {
    throw "Vision model state did not use v1 component schema."
}
if (-not (Test-MaviVisionModelPackReuse -InstalledState $state -Manifest $manifest -ModelPackManifestSha256 $manifestSha)) {
    throw "Identical Model Pack was not reusable."
}

$sourceOnly = $manifest.PSObject.Copy()
$sourceOnly.assembledFromCommit = "2" * 40
if (-not (Test-MaviVisionModelPackReuse -InstalledState $state -Manifest $sourceOnly -ModelPackManifestSha256 $manifestSha)) {
    throw "Assembly provenance incorrectly invalidated Model Pack reuse."
}

$changed = $manifest.PSObject.Copy()
$changed.modelPackId = "mavi-model-v1-" + ("e" * 64)
if (Test-MaviVisionModelPackReuse -InstalledState $state -Manifest $changed -ModelPackManifestSha256 $manifestSha) {
    throw "Different Model Pack ID was incorrectly reusable."
}

$installerText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MaviVisionModelPack.ps1") -Raw
foreach ($required in @(
    "model-pack-manifest.json",
    "mavi-vision-model-pack-v1",
    "mavi-vision-model-install-v1",
    "Test-MaviVisionModelPackReuse",
    "New-MaviVisionModelInstallState",
    "checkpointSha256",
    "resolvedConfigSha256",
    "MAVI_VISION_MODEL_ROOT"
)) {
    if ($installerText -notmatch [regex]::Escape($required)) {
        throw "Vision model installer is missing component contract fragment: $required"
    }
}

Write-Host "MAVI Vision model pack state contracts: OK" -ForegroundColor Green
