Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# PoC S1 (ADR-020): the pure parts of the poc-single-host installer, kept apart from
# Install-MAVI-PoC.ps1 so Test-MaviPocSetupContracts.ps1 can call them without a
# machine to install on. Nothing here touches the host.

$script:PocProfile = "poc-single-host"
$script:PocDisclosureStatement = "Proof-of-concept installation (profile poc-single-host). Not Production-qualified. Evidence class: Development."

function Get-MaviPocProfile { $script:PocProfile }
function Get-MaviPocDisclosureStatement { $script:PocDisclosureStatement }

# Every path of one installation, derived from its two roots and nothing else, so a
# second installation on the same host (the Development laptop) never shares a file,
# a service or a Machine environment variable with the Development one.
function Get-MaviPocLayout {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$DataRoot
    )
    $install = [IO.Path]::GetFullPath($InstallRoot.Trim().Trim('"'))
    $data = [IO.Path]::GetFullPath($DataRoot.Trim().Trim('"'))
    if ($install.TrimEnd("\").Equals($data.TrimEnd("\"), [StringComparison]::OrdinalIgnoreCase)) {
        throw "InstallRoot and DataRoot must be different directories."
    }
    [pscustomobject]@{
        InstallRoot = $install
        DataRoot = $data
        ApplicationRoot = Join-Path $install "app"
        OverlayRoot = Join-Path $install "overlay"
        PostgreSqlInstallRoot = Join-Path $install "PostgreSQL\18"
        VisionRuntimeBase = Join-Path $install "vision\runtime"
        VisionRuntimeCpuRoot = Join-Path $install "vision\runtime\windows-x86_64-cpu"
        VisionRuntimeCudaRoot = Join-Path $install "vision\runtime\windows-x86_64-cuda"
        VisionModelRoot = Join-Path $install "vision\models"
        PlatesEnvironmentRoot = Join-Path $install "plates\venv"
        PlatesModelRoot = Join-Path $install "plates\models"
        PostgreSqlDataRoot = Join-Path $data "PostgreSQL\18\data"
        MediaRoot = Join-Path $data "Media"
        EvidenceRoot = Join-Path $data "Evidence"
        ConfigRoot = Join-Path $data "config"
        MachineConfigPath = Join-Path $data "config\appsettings.poc.machine.json"
        InstallationStatePath = Join-Path $data "config\poc-installation.json"
        ReleaseMetadataPath = Join-Path $data "release\mavi-release-metadata.json"
        DeviceResolutionPath = Join-Path $data "release\device-resolution.json"
        SetupRoot = Join-Path $data "setup"
        LogRoot = Join-Path $data "logs"
        RunRoot = Join-Path $data "run"
    }
}

# The GPU check that decides whether the installer offers the Windows CUDA Runtime Pack.
# The pack is built for exactly one compute capability (the frozen build contract's
# targetGpu); any other GPU, or none, gets the CPU pack and a recorded reason. Auto at
# launch still decides the device; this only decides what is installed.
function Test-MaviPocCudaCompatibleGpu {
    param(
        # nvidia-smi --query-gpu=index,name,compute_cap --format=csv,noheader output lines;
        # $null when nvidia-smi is absent.
        [AllowNull()][string[]]$NvidiaSmiLines,
        [Parameter(Mandatory = $true)][string]$RequiredComputeCapability
    )
    if ($null -eq $NvidiaSmiLines) {
        return [pscustomobject]@{ Compatible = $false; Reason = "nvidia_smi_absent"; Gpu = $null; ComputeCapability = $null; Index = $null }
    }
    $gpus = @()
    foreach ($line in @($NvidiaSmiLines)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parts = @($line.Split(",") | ForEach-Object { $_.Trim() })
        if ($parts.Count -lt 3) { continue }
        $gpus += [pscustomobject]@{ Index = $parts[0]; Name = $parts[1]; ComputeCapability = $parts[2] }
    }
    if ($gpus.Count -eq 0) {
        return [pscustomobject]@{ Compatible = $false; Reason = "no_nvidia_gpu"; Gpu = $null; ComputeCapability = $null; Index = $null }
    }
    $match = @($gpus | Where-Object { $_.ComputeCapability -eq $RequiredComputeCapability })
    if ($match.Count -gt 0) {
        return [pscustomobject]@{ Compatible = $true; Reason = "compute_capability_match"; Gpu = $match[0].Name; ComputeCapability = $match[0].ComputeCapability; Index = $match[0].Index }
    }
    return [pscustomobject]@{ Compatible = $false; Reason = "compute_capability_unsupported"; Gpu = $gpus[0].Name; ComputeCapability = $gpus[0].ComputeCapability; Index = $gpus[0].Index }
}

# The verification status the repository records for a Runtime Pack variant
# (runtime.json platformVariants.<variant>.status).
function Get-MaviPocRuntimeVerificationStatus {
    param(
        [Parameter(Mandatory = $true)]$RuntimeProfile,
        [Parameter(Mandatory = $true)][string]$Variant
    )
    $variants = $RuntimeProfile.PSObject.Properties["platformVariants"]
    if (-not $variants) { return "unrecorded" }
    $entry = $variants.Value.PSObject.Properties[$Variant]
    if (-not $entry) { return "unrecorded" }
    $status = $entry.Value.PSObject.Properties["status"]
    if ($status -and -not [string]::IsNullOrWhiteSpace([string]$status.Value)) { return [string]$status.Value }
    return "unrecorded"
}

# The verification status the repository records for a model: the committed model
# manifest (models/manifests/*.json) whose modelId and modelVersion match.
function Get-MaviPocModelVerificationStatus {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestDirectory,
        [Parameter(Mandatory = $true)][string]$ModelId,
        [Parameter(Mandatory = $true)][string]$ModelVersion
    )
    foreach ($file in @(Get-ChildItem -LiteralPath $ManifestDirectory -Filter "*.json" -File | Sort-Object Name)) {
        $manifest = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
        $idProperty = $manifest.PSObject.Properties["modelId"]
        $versionProperty = $manifest.PSObject.Properties["modelVersion"]
        if ($idProperty -and $versionProperty -and [string]$idProperty.Value -eq $ModelId -and [string]$versionProperty.Value -eq $ModelVersion) {
            $status = $manifest.PSObject.Properties["verificationStatus"]
            if ($status) { return [string]$status.Value }
        }
    }
    return "unrecorded"
}

# Release metadata (mavi-poc-release-metadata-v1). The disclosure fields are fixed here
# and checked again by the platform at start-up (DeploymentDisclosureReader); there is no
# parameter that changes them.
function New-MaviPocReleaseMetadata {
    param(
        [Parameter(Mandatory = $true)][string]$ApplicationRevision,
        [Parameter(Mandatory = $true)][string]$BundleSha256,
        [Parameter(Mandatory = $true)][string]$DevicePolicy,
        [Parameter(Mandatory = $true)]$CudaDecision,
        [Parameter(Mandatory = $true)][object[]]$Packs,
        [Parameter(Mandatory = $true)][string]$InstalledAtUtc
    )
    if ($ApplicationRevision -notmatch '^[0-9a-f]{40}$') { throw "Release metadata needs the exact 40-hex application revision." }
    foreach ($pack in $Packs) {
        foreach ($name in @("kind", "role", "packId", "verificationStatus")) {
            if ([string]::IsNullOrWhiteSpace([string]$pack[$name])) { throw "Release metadata pack is missing '$name'." }
        }
    }
    [ordered]@{
        schemaVersion = "mavi-poc-release-metadata-v1"
        profile = $script:PocProfile
        productionQualified = $false
        evidenceClass = "Development"
        disclosure = $script:PocDisclosureStatement
        application = [ordered]@{ revision = $ApplicationRevision; bundleSha256 = $BundleSha256 }
        installedAtUtc = $InstalledAtUtc
        devicePolicy = $DevicePolicy
        cudaRuntimeDecision = $CudaDecision
        packs = @($Packs)
    }
}

# The platform's machine configuration for the PoC host. Kestrel listens on loopback only,
# so no firewall rule is needed and nothing is exposed beyond the host.
function New-MaviPocMachineConfig {
    param(
        [Parameter(Mandatory = $true)]$Layout,
        [Parameter(Mandatory = $true)][string]$ConnectionString,
        [Parameter(Mandatory = $true)][string]$CursorSigningKey,
        [Parameter(Mandatory = $true)][int]$HttpPort
    )
    [ordered]@{
        ConnectionStrings = [ordered]@{ Mavi = $ConnectionString }
        MediaStorage = [ordered]@{ RootPath = $Layout.MediaRoot; EvidenceRootPath = $Layout.EvidenceRoot }
        TrackSearch = [ordered]@{ CursorSigningKey = $CursorSigningKey }
        Kestrel = [ordered]@{ Endpoints = [ordered]@{ Http = [ordered]@{ Url = "http://127.0.0.1:$HttpPort" } } }
        Deployment = [ordered]@{
            Profile = $script:PocProfile
            ReleaseMetadataPath = $Layout.ReleaseMetadataPath
            DeviceResolutionPath = $Layout.DeviceResolutionPath
        }
    }
}

# The demo cameras (S1: names and time zones only; S2 supplies media and scene geometry).
function Read-MaviPocDemoCameras {
    param([Parameter(Mandatory = $true)][string]$Path)
    $document = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ([string]$document.schemaVersion -ne "mavi-poc-demo-cameras-v1") { throw "Unsupported demo camera seed schema '$($document.schemaVersion)'." }
    $codes = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    $cameras = @()
    foreach ($camera in @($document.cameras)) {
        foreach ($name in @("code", "name", "timeZoneId")) {
            if ([string]::IsNullOrWhiteSpace([string]$camera.$name)) { throw "Demo camera is missing '$name'." }
        }
        if (-not $codes.Add([string]$camera.code)) { throw "Duplicate demo camera code '$($camera.code)'." }
        $cameras += [pscustomobject]@{ Code = [string]$camera.code; Name = [string]$camera.name; TimeZoneId = [string]$camera.timeZoneId }
    }
    if ($cameras.Count -eq 0) { throw "The demo camera seed has no cameras." }
    return $cameras
}

Export-ModuleMember -Function Get-MaviPocProfile, Get-MaviPocDisclosureStatement, Get-MaviPocLayout, Test-MaviPocCudaCompatibleGpu, Get-MaviPocRuntimeVerificationStatus, Get-MaviPocModelVerificationStatus, New-MaviPocReleaseMetadata, New-MaviPocMachineConfig, Read-MaviPocDemoCameras
