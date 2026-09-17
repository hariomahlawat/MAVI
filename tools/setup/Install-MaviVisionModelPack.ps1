[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PackRoot,

    [string]$InstallRoot = "$env:ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-ModelPackRoot {
    param([Parameter(Mandatory = $true)][string]$Root)
    $candidate = [IO.Path]::GetFullPath($Root.Trim().Trim('"'))
    if (Test-Path -LiteralPath (Join-Path $candidate "model-pack-manifest.json") -PathType Leaf) { return $candidate }
    $nested = Join-Path $candidate "rtmdet-m-coco-phase1"
    if (Test-Path -LiteralPath (Join-Path $nested "model-pack-manifest.json") -PathType Leaf) { return $nested }
    throw "MAVI Vision Model Pack manifest was not found under '$candidate'."
}

function Test-SafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or [IO.Path]::IsPathRooted($Value) -or $Value.Contains("\") -or $Value.Contains([char]0)) { return $false }
    foreach ($part in $Value.Split('/')) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") { return $false }
    }
    return $true
}

function Assert-ModelPackFiles {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][object]$Manifest,
        [string[]]$AllowedMetadata = @("model-pack-manifest.json", "model-install.json")
    )
    $declared = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::Ordinal)
    foreach ($artifact in @($Manifest.artifacts)) {
        $relative = [string]$artifact.relativePath
        if (-not (Test-SafeRelativePath $relative)) { throw "Unsafe artifact path in Vision Model Pack manifest: '$relative'." }
        if (-not $declared.Add($relative)) { throw "Duplicate artifact path in Vision Model Pack manifest: '$relative'." }
        $path = Join-Path $Root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Vision Model Pack artifact is missing: '$relative'." }
        $item = Get-Item -LiteralPath $path
        if ([int64]$item.Length -ne [int64]$artifact.sizeBytes) { throw "Vision Model Pack artifact size mismatch: '$relative'." }
        if ((Get-Sha256 $path) -ne ([string]$artifact.sha256).ToLowerInvariant()) { throw "Vision Model Pack artifact SHA-256 mismatch: '$relative'." }
    }
    $prefix = $Root.TrimEnd("\") + "\"
    $actual = @(Get-ChildItem -LiteralPath $Root -Recurse -File | ForEach-Object {
        if (-not $_.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Vision Model Pack enumeration escaped its root." }
        $_.FullName.Substring($prefix.Length).Replace("\", "/")
    } | Where-Object { $_ -notin $AllowedMetadata })
    foreach ($relative in $actual) {
        if (-not $declared.Contains($relative)) { throw "Undeclared file exists in Vision Model Pack: '$relative'." }
    }
    if ($actual.Count -ne $declared.Count) { throw "Vision Model Pack artifact set does not match its manifest." }
}

$PackRoot = Resolve-ModelPackRoot $PackRoot
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot.Trim().Trim('"'))
$manifestPath = Join-Path $PackRoot "model-pack-manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionModelPackManifest -Manifest $manifest)
if ([string]$manifest.schemaVersion -ne "mavi-vision-model-pack-v1") { throw "Unsupported MAVI Vision Model Pack schema '$($manifest.schemaVersion)'." }
Assert-ModelPackFiles -Root $PackRoot -Manifest $manifest -AllowedMetadata @("model-pack-manifest.json")
$manifestSha = Get-Sha256 $manifestPath

$statePath = Join-Path $InstallRoot "model-install.json"
$installedManifestPath = Join-Path $InstallRoot "model-pack-manifest.json"
if ((Test-Path -LiteralPath $statePath -PathType Leaf) -and (Test-Path -LiteralPath $installedManifestPath -PathType Leaf)) {
    try {
        $installedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $installedManifest = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
        $installedManifestSha = Get-Sha256 $installedManifestPath
        [void](Assert-MaviVisionModelPackManifest -Manifest $installedManifest)
        Assert-ModelPackFiles -Root $InstallRoot -Manifest $installedManifest
        if ($installedManifestSha -eq $manifestSha -and (Test-MaviVisionModelPackReuse -InstalledState $installedState -Manifest $manifest -ModelPackManifestSha256 $manifestSha)) {
            [Environment]::SetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", $InstallRoot, "Machine")
            Write-Host "MAVI Vision Model Pack already installed and verified; reusing existing model assets." -ForegroundColor Green
            Write-Host "  Model Pack : $($manifest.modelPackId)"
            Write-Host "  Model      : $($manifest.modelId)"
            Write-Host "  Root       : $InstallRoot"
            return
        }
    }
    catch { Write-Host "Existing Vision Model Pack cannot be reused and will be replaced: $($_.Exception.Message)" -ForegroundColor Yellow }
}

$stageRoot = "$InstallRoot.stage"
if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
try {
    foreach ($artifact in @($manifest.artifacts)) {
        $relative = [string]$artifact.relativePath
        $source = Join-Path $PackRoot ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
        $destination = Join-Path $stageRoot ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stageRoot "model-pack-manifest.json") -Force
    Assert-ModelPackFiles -Root $stageRoot -Manifest $manifest -AllowedMetadata @("model-pack-manifest.json")
    $state = New-MaviVisionModelInstallState -Manifest $manifest -ModelPackManifestSha256 $manifestSha -ModelRoot $InstallRoot
    Write-MaviJson -Value $state -Path (Join-Path $stageRoot "model-install.json") -Depth 8

    if (Test-Path -LiteralPath $InstallRoot) {
        $backup = "$InstallRoot.previous"
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
        Move-Item -LiteralPath $InstallRoot -Destination $backup
        try {
            Move-Item -LiteralPath $stageRoot -Destination $InstallRoot
            Remove-Item -LiteralPath $backup -Recurse -Force
        }
        catch {
            if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue }
            Move-Item -LiteralPath $backup -Destination $InstallRoot -ErrorAction SilentlyContinue
            throw
        }
    }
    else { Move-Item -LiteralPath $stageRoot -Destination $InstallRoot }
}
catch {
    if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}

[Environment]::SetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", $InstallRoot, "Machine")
Write-Host ""
Write-Host "MAVI Vision Model Pack installed and verified." -ForegroundColor Green
Write-Host "  Model Pack : $($manifest.modelPackId)"
Write-Host "  Model      : $($manifest.modelId)"
Write-Host "  Root       : $InstallRoot"
Write-Host "  Schema     : mavi-vision-model-install-v1"
