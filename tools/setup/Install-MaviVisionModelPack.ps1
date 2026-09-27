[CmdletBinding()]
param(
    # A built mavi-vision-model-pack-v2 pack, as tools/vision/build_model_pack.py
    # writes it: <PackRoot>/model-pack-manifest.json and every artefact at
    # <PackRoot>/<relativePath>, all under one <packDirectory>.
    [Parameter(Mandatory = $true)]
    [string]$PackRoot,

    # The Model Pack store root (plan P-10): one self-contained directory per
    # pack, <StoreRoot>/<packDirectory>. This is what MAVI_VISION_MODEL_ROOT
    # names and what the launcher passes to the worker as MAVI_MODEL_ROOT. It
    # replaced the per-model install root of the v1 installer.
    [string]$StoreRoot = "$env:ProgramData\MAVI\Development\VisionModels",

    # Do not record the store root in the Machine environment. For contract
    # tests that install into a temporary store without repointing the host.
    [switch]$NoMachineEnvironment
)

# Install exactly one Model Pack into a shared store, touching nothing else in
# it (plan §5.4, P-10). The pack is verified, staged beside its destination as
# <StoreRoot>/.<packDirectory>.stage, and renamed into place; a previous copy of
# the same pack directory is moved aside to <StoreRoot>/.<packDirectory>.previous
# and restored if the swap fails. Other pack directories are never enumerated,
# validated, replaced or removed, so installing pack B leaves pack A as it was.
#
# A v1 installation is never upgraded in place (plan §11, forward-only). If the
# destination pack directory holds a model-install.json that is not
# mavi-vision-model-install-v2, or the store root itself is a v1 per-model
# installation, the installer refuses with model_install_state_v1_rejected. To
# re-install: remove that v1 directory (or choose a store root that is not a v1
# installation) and run this script again.
#
# Refusals are "<code>: <message>". The codes are stable for operators and
# tests; they are installer codes, not launcher codes.

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Integrity.psm1") -Force

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Stop-MaviModelInstall {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Code,
        [Parameter(Mandatory = $true, Position = 1)][string]$Message
    )
    throw "${Code}: $Message"
}

$modelPackSchema = "mavi-vision-model-pack-v2"
$modelInstallSchema = "mavi-vision-model-install-v2"

# --- The candidate pack ------------------------------------------------------
$PackRoot = [IO.Path]::GetFullPath($PackRoot.Trim().Trim('"'))
$manifestPath = Join-Path $PackRoot "model-pack-manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    Stop-MaviModelInstall model_pack_not_found "MAVI Vision Model Pack manifest was not found at '$manifestPath'."
}
$manifest = $null
try { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json }
catch { Stop-MaviModelInstall model_pack_manifest_invalid "MAVI Vision Model Pack manifest is not valid JSON: $manifestPath" }
$candidateSchema = Get-MaviVisionPropertyText -Value $manifest -Name "schemaVersion"
if ($candidateSchema -cne $modelPackSchema) {
    # The v1 pack (mavi-vision-model-pack-v1) is refused, never converted:
    # rebuild it with the v2 tools/vision/build_model_pack.py.
    Stop-MaviModelInstall model_pack_schema_unsupported "Unsupported MAVI Vision Model Pack schema '$candidateSchema'; only '$modelPackSchema' is installable. Rebuild the pack with tools/vision/build_model_pack.py."
}
try { [void](Assert-MaviVisionModelPackManifest -Manifest $manifest) }
catch { Stop-MaviModelInstall model_pack_manifest_invalid $_.Exception.Message }
$packDirectory = Get-MaviVisionModelPackDirectory -Manifest $manifest

# The pack is exactly its manifest plus its one pack directory.
foreach ($entry in @(Get-ChildItem -LiteralPath $PackRoot -Force)) {
    if ($entry.PSIsContainer) {
        if ($entry.Name -cne $packDirectory) { Stop-MaviModelInstall model_pack_content_invalid "Undeclared directory in Vision Model Pack: '$($entry.Name)'." }
    }
    elseif ($entry.Name -cne "model-pack-manifest.json") {
        Stop-MaviModelInstall model_pack_content_invalid "Undeclared file in Vision Model Pack: '$($entry.Name)'."
    }
}
try { [void](Assert-MaviVisionModelPackDirectoryContent -PackDirectoryPath (Join-Path $PackRoot $packDirectory) -Manifest $manifest -AllowedMetadata @()) }
catch { Stop-MaviModelInstall model_pack_content_invalid $_.Exception.Message }
$manifestSha = Get-Sha256 $manifestPath

# --- The store and this pack's directory in it ---------------------------------
$StoreRoot = [IO.Path]::GetFullPath($StoreRoot.Trim().Trim('"'))
if (Test-Path -LiteralPath $StoreRoot -PathType Leaf) {
    Stop-MaviModelInstall model_install_store_invalid "Vision Model Pack store root is a file: $StoreRoot"
}
foreach ($legacyName in @("model-install.json", "model-pack-manifest.json")) {
    if (Test-Path -LiteralPath (Join-Path $StoreRoot $legacyName) -PathType Leaf) {
        Stop-MaviModelInstall model_install_state_v1_rejected "'$StoreRoot' is a v1 per-model installation root (it holds $legacyName), not a Model Pack store. Install into a store root that is not a v1 installation (default $env:ProgramData\MAVI\Development\VisionModels), or remove the v1 installation, then re-run this installer."
    }
}
New-Item -ItemType Directory -Path $StoreRoot -Force | Out-Null

$packPath = Join-Path $StoreRoot $packDirectory
$stagePath = Join-Path $StoreRoot ("." + $packDirectory + ".stage")
$backupPath = Join-Path $StoreRoot ("." + $packDirectory + ".previous")
if (Test-Path -LiteralPath $packPath -PathType Leaf) {
    Stop-MaviModelInstall model_install_store_invalid "Vision Model Pack destination is a file: $packPath"
}
# Recover this pack's own interrupted swap: its previous copy is the only copy.
if (-not (Test-Path -LiteralPath $packPath) -and (Test-Path -LiteralPath $backupPath -PathType Container)) {
    Move-Item -LiteralPath $backupPath -Destination $packPath
}
if (Test-Path -LiteralPath $backupPath) { Remove-Item -LiteralPath $backupPath -Recurse -Force }

$reused = $false
if (Test-Path -LiteralPath $packPath -PathType Container) {
    $statePath = Join-Path $packPath "model-install.json"
    $installedManifestPath = Join-Path $packPath "model-pack-manifest.json"
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        $installedState = $null
        try { $installedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json }
        catch {
            $installedState = $null
            Write-Host "Existing Vision Model Pack state is unreadable and will be replaced: $statePath" -ForegroundColor Yellow
        }
        if ($null -ne $installedState) {
            $installedSchema = Get-MaviVisionPropertyText -Value $installedState -Name "schemaVersion"
            if ($installedSchema -cne $modelInstallSchema) {
                Stop-MaviModelInstall model_install_state_v1_rejected "'$statePath' has schema '$installedSchema'; only '$modelInstallSchema' is accepted. A v1 installation is never upgraded in place: remove the directory '$packPath' and re-run this installer."
            }
            try {
                $installedManifest = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
                $installedManifestSha = Get-Sha256 $installedManifestPath
                [void](Assert-MaviVisionModelPackManifest -Manifest $installedManifest)
                if ((Get-MaviVisionModelPackDirectory -Manifest $installedManifest) -cne $packDirectory) {
                    throw "Installed Vision Model Pack manifest names another pack directory."
                }
                if ((Get-MaviVisionPropertyText -Value $installedState -Name "modelPackManifestSha256") -cne $installedManifestSha) {
                    throw "Installed Vision Model Pack state does not bind the installed manifest."
                }
                [void](Assert-MaviVisionInstalledModelPackIntegrity -ModelRoot $StoreRoot -Manifest $installedManifest)
                # The candidate may carry different assembledFromCommit
                # provenance while being the same content-addressed pack; reuse
                # is decided by the verified installed pack and material
                # identity, not by candidate provenance bytes.
                $reused = [bool](Test-MaviVisionModelPackReuse -InstalledState $installedState -Manifest $manifest -ModelPackManifestSha256 $installedManifestSha)
            }
            catch { Write-Host "Existing Vision Model Pack cannot be reused and will be replaced: $($_.Exception.Message)" -ForegroundColor Yellow }
        }
    }
}

if ($reused) {
    if (-not $NoMachineEnvironment) { [Environment]::SetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", $StoreRoot, "Machine") }
    Write-Host "MAVI Vision Model Pack already installed and verified; reusing existing model assets." -ForegroundColor Green
    Write-Host "  Model Pack : $($manifest.modelPackId)"
    Write-Host "  Model      : $($manifest.modelId)"
    Write-Host "  Store      : $StoreRoot"
    Write-Host "  Directory  : $packDirectory"
    return
}

# --- Stage beside the destination ---------------------------------------------
if (Test-Path -LiteralPath $stagePath) { Remove-Item -LiteralPath $stagePath -Recurse -Force }
New-Item -ItemType Directory -Path $stagePath -Force | Out-Null
try {
    $sourcePackPath = Join-Path $PackRoot $packDirectory
    foreach ($artifact in @($manifest.artifacts)) {
        $inner = ([string]$artifact.relativePath).Substring($packDirectory.Length + 1)
        $nativeInner = $inner.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $source = Join-Path $sourcePackPath $nativeInner
        $destination = Join-Path $stagePath $nativeInner
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $destination -Force
    }
    # The installed manifest is a byte copy: its SHA-256 is what the state binds.
    $stagedManifestPath = Join-Path $stagePath "model-pack-manifest.json"
    Copy-Item -LiteralPath $manifestPath -Destination $stagedManifestPath -Force
    if ((Get-Sha256 $stagedManifestPath) -cne $manifestSha) { throw "Staged Vision Model Pack manifest is not a byte copy of the candidate." }
    [void](Assert-MaviVisionModelPackDirectoryContent -PackDirectoryPath $stagePath -Manifest $manifest -AllowedMetadata @("model-pack-manifest.json"))
    $state = New-MaviVisionModelInstallState -Manifest $manifest -ModelPackManifestSha256 $manifestSha -InstallRoot $StoreRoot
    Write-MaviJson -Value $state -Path (Join-Path $stagePath "model-install.json") -Depth 8
    [void](Assert-MaviVisionModelPackDirectoryContent -PackDirectoryPath $stagePath -Manifest $manifest -AllowedMetadata @("model-pack-manifest.json", "model-install.json"))
}
catch {
    if (Test-Path -LiteralPath $stagePath) { Remove-Item -LiteralPath $stagePath -Recurse -Force -ErrorAction SilentlyContinue }
    Stop-MaviModelInstall model_pack_stage_failed $_.Exception.Message
}

# --- Swap this one pack directory ---------------------------------------------
try {
    if (Test-Path -LiteralPath $packPath) {
        Move-Item -LiteralPath $packPath -Destination $backupPath
        try { Move-Item -LiteralPath $stagePath -Destination $packPath }
        catch {
            if (Test-Path -LiteralPath $packPath) { Remove-Item -LiteralPath $packPath -Recurse -Force -ErrorAction SilentlyContinue }
            Move-Item -LiteralPath $backupPath -Destination $packPath -ErrorAction SilentlyContinue
            throw
        }
        # The new pack is in place; a leftover previous copy is removed by the
        # next run of this installer for the same pack.
        Remove-Item -LiteralPath $backupPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    else { Move-Item -LiteralPath $stagePath -Destination $packPath }
}
catch {
    if (Test-Path -LiteralPath $stagePath) { Remove-Item -LiteralPath $stagePath -Recurse -Force -ErrorAction SilentlyContinue }
    Stop-MaviModelInstall model_install_swap_failed $_.Exception.Message
}

if (-not $NoMachineEnvironment) { [Environment]::SetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", $StoreRoot, "Machine") }
Write-Host ""
Write-Host "MAVI Vision Model Pack installed and verified." -ForegroundColor Green
Write-Host "  Model Pack : $($manifest.modelPackId)"
Write-Host "  Model      : $($manifest.modelId)"
Write-Host "  Store      : $StoreRoot"
Write-Host "  Directory  : $packDirectory"
Write-Host "  Schema     : $modelInstallSchema"
