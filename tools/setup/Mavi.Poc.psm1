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
    # No trailing separator: the roots are written into .cmd launchers, where "...\" would
    # escape the closing quote. A drive root keeps its separator.
    $install = [IO.Path]::GetFullPath($InstallRoot.Trim().Trim('"'))
    $data = [IO.Path]::GetFullPath($DataRoot.Trim().Trim('"'))
    if ($install.Length -gt 3) { $install = $install.TrimEnd("\") }
    if ($data.Length -gt 3) { $data = $data.TrimEnd("\") }
    if ($install.Equals($data, [StringComparison]::OrdinalIgnoreCase)) {
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
        # The plates role's release (PoC S3, plan D4): PD5 + OC1-S on the plates-onnx-v1 family, read from the overlay.
        PlatesComponentBindingPath = Join-Path $install "overlay\src\vision\config\components\development-plates-onnx-pilot-v1.json"
        PlatesPipelineProfilePath = Join-Path $install "overlay\src\vision\config\plates\development-plates-onnx-pilot-v1.json"
        EmbeddingsEnvironmentRoot = Join-Path $install "embeddings\venv"
        EmbeddingsModelRoot = Join-Path $install "embeddings\models"
        # PoC S6 (ADR-022): the face Model Pack's store; the faces worker runs on the embeddings environment.
        FacesModelRoot = Join-Path $install "faces\models"
        # PoC S10 (ADR-026): the Language Runtime Pack (llama.cpp cpu\ and cuda\ variants) and the Language Model Packs.
        LanguageRuntimeRoot = Join-Path $install "language\runtime"
        LanguageModelRoot = Join-Path $install "language\models"
        PostgreSqlDataRoot = Join-Path $data "PostgreSQL\18\data"
        MediaRoot = Join-Path $data "Media"
        EvidenceRoot = Join-Path $data "Evidence"
        ConfigRoot = Join-Path $data "config"
        MachineConfigPath = Join-Path $data "config\appsettings.poc.machine.json"
        InstallationStatePath = Join-Path $data "config\poc-installation.json"
        ReleaseMetadataPath = Join-Path $data "release\mavi-release-metadata.json"
        # Operator-writable (the launcher rewrites it on every start), so it lives under run\,
        # not beside the administrator-only release metadata.
        DeviceResolutionPath = Join-Path $data "run\device-resolution.json"
        # The plates role resolves its own device (ADR-008 per runtime); its record sits beside the Vision worker's.
        PlatesDeviceResolutionPath = Join-Path $data "run\plates-device-resolution.json"
        LanguageDeviceResolutionPath = Join-Path $data "run\language-device-resolution.json"
        # The driver's PTX JIT cache for a GPU without native code in the llama.cpp CUDA build (sm_75).
        LanguageCudaCachePath = Join-Path $data "language\cuda-cache"
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

# The Windows CUDA Runtime Pack builds a PoC bundle may carry (S1b; plan D9, ADR-020), in
# preference order. Each is the windows-x86_64-cuda platform variant built under its own
# build contract; the contract's target GPU list is what the pack serves. The frozen v1
# (sm_75) pack comes first, so an sm_75 host keeps it unless the sm_75;sm_89 one is asked for.
function Get-MaviPocCudaRuntimePackCandidates {
    param(
        # The bundle overlay (or repository) root holding config\vision\.
        [Parameter(Mandatory = $true)][string]$OverlayRoot,
        # The bundle root; a candidate is Available when its pack directory carries a manifest.
        [AllowNull()][string]$BundleRoot
    )
    $candidates = @()
    foreach ($spec in @(
            @{ Key = "sm75"; Contract = "windows-cuda-development-build-v1.json"; Directory = "windows-x86_64-cuda" },
            @{ Key = "sm75-sm89"; Contract = "windows-cuda-development-build-v2.json"; Directory = "windows-x86_64-cuda-sm75-sm89" })) {
        $contractPath = Join-Path $OverlayRoot "config\vision\$($spec.Contract)"
        if (-not (Test-Path -LiteralPath $contractPath -PathType Leaf)) {
            # The frozen v1 contract is required; only a later build's contract may be absent.
            if ($spec.Key -eq "sm75") { throw "The Windows CUDA build contract '$contractPath' is missing." }
            continue
        }
        $contract = Get-Content -LiteralPath $contractPath -Raw | ConvertFrom-Json
        $targets = if ($contract.PSObject.Properties["targetGpus"]) { @($contract.targetGpus) } else { @($contract.targetGpu) }
        $source = if ($BundleRoot) { Join-Path $BundleRoot "vision\runtime\$($spec.Directory)" } else { $null }
        $candidates += [pscustomobject]@{
            Key = $spec.Key
            Contract = $spec.Contract
            NativeAbi = [string]$contract.nativeAbi
            ComputeCapabilities = @($targets | ForEach-Object { [string]$_.computeCapability })
            Source = $source
            Available = [bool]($source -and (Test-Path -LiteralPath (Join-Path $source "runtime-pack-manifest.json") -PathType Leaf))
        }
    }
    return , $candidates
}

# Which CUDA Runtime Pack build serves this host. Auto takes the first candidate (in
# preference order) whose contract targets the GPU's exact compute capability, whether or
# not the bundle carries it (an sm_75 host never drifts onto the sm_75;sm_89 build because
# the sm_75 one is missing); a named pack must target the GPU or nothing is chosen. No
# capability is served by a pack that does not list it: compute_89 PTX would not run on an
# older GPU, and a newer GPU is not claimed until a build contract names it.
function Select-MaviPocCudaRuntimePack {
    param(
        # nvidia-smi --query-gpu=index,name,compute_cap --format=csv,noheader output lines;
        # $null when nvidia-smi is absent.
        [AllowNull()][string[]]$NvidiaSmiLines,
        [Parameter(Mandatory = $true)][AllowEmptyCollection()][object[]]$Candidates,
        [string]$Requested = "Auto"
    )
    $gpu = Test-MaviPocCudaCompatibleGpu -NvidiaSmiLines $NvidiaSmiLines -RequiredComputeCapability "none"
    $none = [pscustomobject]@{ Compatible = $false; Reason = $gpu.Reason; Gpu = $gpu.Gpu; ComputeCapability = $gpu.ComputeCapability; Index = $gpu.Index; Pack = $null }
    if ($gpu.Reason -in @("nvidia_smi_absent", "no_nvidia_gpu")) { return $none }
    $pool = @($Candidates)
    if ($Requested -ne "Auto") {
        $pool = @($Candidates | Where-Object { $_.Key -eq $Requested })
        if ($pool.Count -eq 0) { throw "CUDA Runtime Pack '$Requested' is not declared by this bundle's build contracts." }
    }
    foreach ($line in @($NvidiaSmiLines)) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $parts = @($line.Split(",") | ForEach-Object { $_.Trim() })
        if ($parts.Count -lt 3) { continue }
        foreach ($candidate in $pool) {
            if (@($candidate.ComputeCapabilities) -contains $parts[2]) {
                return [pscustomobject]@{ Compatible = $true; Reason = "compute_capability_match"; Gpu = $parts[1]; ComputeCapability = $parts[2]; Index = $parts[0]; Pack = $candidate }
            }
        }
    }
    $none.Reason = "compute_capability_unsupported"
    return $none
}

# Which declared Windows CUDA build a Runtime Pack id is, from the component binding (ADR-014
# amendment 2026-10-29): "sm75" for the release pin (variants.windows-x86_64-cuda), a build id
# for one of its developmentBuilds, $null for anything else. The binding is the one source the
# bundle builder, the kit builder and the installer all consult.
function Get-MaviPocCudaBuildKey {
    param(
        [Parameter(Mandatory = $true)]$Binding,
        [Parameter(Mandatory = $true)][string]$RuntimePackId
    )
    $family = @($Binding.runtimePacks | Where-Object { [string]$_.runtimePackFamilyId -eq "mmdetection-phase1-v1" })
    if ($family.Count -ne 1) { return $null }
    $variants = $family[0].PSObject.Properties["variants"]
    $primary = if ($variants) { $variants.Value.PSObject.Properties["windows-x86_64-cuda"] } else { $null }
    if ($primary -and [string]$primary.Value.runtimePackId -ceq $RuntimePackId) { return "sm75" }
    $builds = $family[0].PSObject.Properties["developmentBuilds"]
    if (-not $builds) { return $null }
    $cudaBuilds = $builds.Value.PSObject.Properties["windows-x86_64-cuda"]
    if (-not $cudaBuilds) { return $null }
    foreach ($build in @($cudaBuilds.Value)) {
        if ([string]$build.runtimePackId -ceq $RuntimePackId) { return [string]$build.buildId }
    }
    return $null
}

# The status the offline catalogue records for the PoC sm_75;sm_89 CUDA build
# (visionRuntime.windowsCudaPocSm89Candidate), for the pack it names; "unrecorded" otherwise.
function Get-MaviPocCudaBuildStatus {
    param(
        [Parameter(Mandatory = $true)][string]$OverlayRoot,
        [Parameter(Mandatory = $true)][string]$RuntimePackId
    )
    $catalogPath = Join-Path $OverlayRoot "config\dependencies\offline-binary-catalog-v1.json"
    if (-not (Test-Path -LiteralPath $catalogPath -PathType Leaf)) { return "unrecorded" }
    $vision = (Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json).visionRuntime
    $entry = $vision.PSObject.Properties["windowsCudaPocSm89Candidate"]
    if (-not $entry -or [string]$entry.Value.runtimePackId -ne $RuntimePackId) { return "unrecorded" }
    return [string]$entry.Value.status
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

# Operator identity (ADR-010): every interactive local user of the dedicated, trusted PoC host
# (owner decision S1-T1) is an operator, attributed to their own Windows account. The release
# metadata records the mode installed; the platform discloses it beside the mode in effect.
$script:PocIdentityMode = "windows-negotiate"
$script:PocOperatorGroups = @("BUILTIN\Users")

# The URL an operator opens (owner decision D-242-3). Browsers send Windows credentials silently to
# localhost but not to 127.0.0.1 (ADR-010 section 3). The platform still listens on 127.0.0.1 only, and
# scripts and the worker keep apiBaseUrl on 127.0.0.1: through localhost every new connection
# first tries ::1 and costs about 2 s on Windows.
function Get-MaviPocOperatorUrl([int]$HttpPort) { "http://localhost:$HttpPort" }

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
        identityMode = $script:PocIdentityMode
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
        [Parameter(Mandatory = $true)][int]$HttpPort,
        # PoC S10 (ADR-026): the bound Language Model Pack (Select-MaviPocLanguagePack), or $null for none.
        $LanguagePack = $null,
        [int]$LanguagePort = 62301
    )
    $config = [ordered]@{
        ConnectionStrings = [ordered]@{ Mavi = $ConnectionString }
        # Loopback names only: a page on another host name (DNS rebinding) is refused before any endpoint.
        AllowedHosts = "localhost;127.0.0.1"
        MediaStorage = [ordered]@{ RootPath = $Layout.MediaRoot; EvidenceRootPath = $Layout.EvidenceRoot }
        TrackSearch = [ordered]@{ CursorSigningKey = $CursorSigningKey }
        Kestrel = [ordered]@{ Endpoints = [ordered]@{ Http = [ordered]@{ Url = "http://127.0.0.1:$HttpPort" } } }
        Deployment = [ordered]@{
            Profile = $script:PocProfile
            ReleaseMetadataPath = $Layout.ReleaseMetadataPath
            DeviceResolutionPath = $Layout.DeviceResolutionPath
            RoleDeviceResolutionPaths = [ordered]@{ plates = $Layout.PlatesDeviceResolutionPath }
        }
        # The plates role bound (PoC S3, C4.1). Re-analysis is authorised by ADR-010 operator identity (the Identity
        # section below); no plate-specific key is configured.
        Plates = [ordered]@{
            Enabled = $true
            ComponentBindingPath = $Layout.PlatesComponentBindingPath
            PipelineProfilePath = $Layout.PlatesPipelineProfilePath
        }
        # PoC S4 (ADR-021): the embeddings role is bound; the platform's loop queues runs for the SigLIP 2 identity.
        Embeddings = [ordered]@{
            Enabled = $true
            ModelManifestPath = Join-Path $Layout.OverlayRoot "models\manifests\embeddings-siglip2-base-p16-224-dev-v1.json"
            PipelineProfilePath = Join-Path $Layout.OverlayRoot "src\vision\config\embeddings\development-embeddings-siglip2-v1.json"
        }
        # PoC S6 (ADR-022): the faces role is bound; its loop queues only runs of cameras an operator opted in.
        Faces = [ordered]@{
            Enabled = $true
            ModelManifestPath = Join-Path $Layout.OverlayRoot "models\manifests\faces-yunet-adaface-ir50-dev-v1.json"
            PipelineProfilePath = Join-Path $Layout.OverlayRoot "src\vision\config\faces\development-faces-adaface-v1.json"
        }
        # PoC S5: the attributes role with the SigLIP 2 zero-shot inferencer over the same Model Pack (zero-shot,
        # Development); the platform queues an attribute analysis per completed run for the release identity.
        VisualAttributes = [ordered]@{
            Enabled = $true
            ComponentBindingPath = Join-Path $Layout.OverlayRoot "src\vision\config\attributes\development-attributes-siglip2-binding-v1.json"
            PipelineProfilePath = Join-Path $Layout.OverlayRoot "src\vision\config\attributes\development-attributes-siglip2-zero-shot-v1.json"
        }
        Identity = [ordered]@{
            Mode = $script:PocIdentityMode
            Operators = [ordered]@{ AuthorizedGroups = @($script:PocOperatorGroups) }
        }
    }
    # PoC S10 (ADR-026): Ask MAVI calls the language role on loopback; the identity here is what the API reports with
    # every answer, and the launcher's device record supplies the device.
    if ($LanguagePack) {
        $config.Language = [ordered]@{
            Enabled = $true
            Port = $LanguagePort
            TimeoutSeconds = 300
            ModelPackId = [string]$LanguagePack.ModelPackId
            ModelId = [string]$LanguagePack.ModelId
            Quantisation = [string]$LanguagePack.Quantisation
            RuntimeId = [string]$LanguagePack.RuntimeId
            DeviceReportPath = $Layout.LanguageDeviceResolutionPath
            CachePrompt = [bool]$LanguagePack.CachePrompt
        }
        $config.Deployment.RoleDeviceResolutionPaths.language = $Layout.LanguageDeviceResolutionPath
    }
    $config
}

# The licence a Model Pack's own notice states, read from the notice file itself (PoC S3: "licence read from its own
# LICENSE file"): it must be the notice the manifest pins (SHA-256) and must state the licence the manifest declares,
# or the pack is not installed under this profile.
function Get-MaviPocNoticeLicence {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedSha256,
        [Parameter(Mandatory = $true)][string]$DeclaredSpdxId
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "The licence notice '$Path' is missing." }
    $sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha256 -ne $ExpectedSha256) { throw "The licence notice '$Path' is not the one its manifest pins ($sha256)." }
    $text = [IO.File]::ReadAllText($Path)
    $stated = if ($text -match '(?m)^\s*Apache License\s*$' -and $text -match 'Version 2\.0') { "Apache-2.0" }
        elseif ($text -match '(?m)^\s*MIT License\s*$' -and $text -match 'Permission is hereby granted, free of charge') { "MIT" }
        else { $null }
    if (-not $stated) { throw "The licence notice '$Path' states no licence this installer recognises." }
    if ($stated -ne $DeclaredSpdxId) { throw "The licence notice '$Path' states $stated, but its manifest declares $DeclaredSpdxId." }
    [pscustomobject]@{ SpdxId = $stated; Sha256 = $sha256 }
}

# PoC S10 (ADR-026 §2): which Language Model Pack an installation binds. Auto takes the 7B pack only on a GPU with the
# memory to hold it fully (16 GiB or more: the RTX 4090 class), and the 1.5B pack otherwise (the Development laptop's
# 4 GiB GPU, or CPU). An explicit choice is honoured; the reason is recorded either way.
# CachePrompt (ADR-026 §6, D-S10-7): prompt-prefix reuse only for a pack whose recordings were byte-identical in reverse
# order. The 7B pack's prompt-v2 set was not (one output differed; the canonical outcome was the same), so the 7B runs
# with reuse off; the 1.5B pack passed the check.
function Select-MaviPocLanguagePack {
    param(
        [ValidateSet("Auto", "1.5B", "7B")][string]$Choice = "Auto",
        # nvidia-smi --query-gpu=index,name,compute_cap,memory.total --format=csv,noheader lines; $null when absent.
        [AllowNull()][string[]]$NvidiaSmiLines,
        [Parameter(Mandatory = $true)][string]$PayloadsPath
    )
    $payloads = Get-Content -LiteralPath $PayloadsPath -Raw | ConvertFrom-Json
    $small = @($payloads.models | Where-Object { [string]$_.packDirectory -like "*1.5b*" })[0]
    $large = @($payloads.models | Where-Object { [string]$_.packDirectory -like "*7b*" })[0]
    $largestMiB = 0
    foreach ($line in @($NvidiaSmiLines)) {
        if (-not $line) { continue }
        $fields = @($line -split "," | ForEach-Object { $_.Trim() })
        if ($fields.Count -ge 4 -and $fields[3] -match '^(\d+)') { $largestMiB = [Math]::Max($largestMiB, [int]$Matches[1]) }
    }
    $pick, $reason = switch ($Choice) {
        "1.5B" { $small, "operator_choice_1_5b" }
        "7B" { $large, "operator_choice_7b" }
        default {
            if ($largestMiB -ge 16000) { $large, "gpu_memory_${largestMiB}_mib_holds_7b" }
            elseif ($null -eq $NvidiaSmiLines) { $small, "no_nvidia_gpu_1_5b" }
            else { $small, "gpu_memory_${largestMiB}_mib_below_16000_1_5b" }
        }
    }
    [pscustomobject]@{ PackDirectory = [string]$pick.packDirectory; ManifestPath = [string]$pick.manifest; Reason = $reason; CachePrompt = ($pick -eq $small) }
}

# PoC S10 (ADR-026 §3): the language role's device under ADR-008 policy. CUDA needs an NVIDIA GPU that answers; the
# published llama.cpp CUDA build carries native code for sm_86/sm_89 and PTX for sm_50 to sm_90, so any such GPU runs.
function Resolve-MaviPocLanguageDevice {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("auto", "cuda", "cpu")][string]$Policy,
        [AllowNull()][string[]]$NvidiaSmiLines
    )
    $gpu = $null
    foreach ($line in @($NvidiaSmiLines)) {
        if (-not $line) { continue }
        $fields = @($line -split "," | ForEach-Object { $_.Trim() })
        if ($fields.Count -ge 3 -and $fields[2] -match '^\d+\.\d+$' -and [double]$fields[2] -ge 5.0) { $gpu = $fields; break }
    }
    if ($Policy -eq "cpu") {
        return [pscustomobject]@{ Variant = "cpu"; Directory = "cpu"; Device = "cpu"; Reason = "policy_cpu" }
    }
    if (-not $gpu) {
        if ($Policy -eq "cuda") { throw "Language device policy CUDA: no NVIDIA GPU answered (nvidia-smi); refusing to fall back to CPU." }
        $why = if ($null -eq $NvidiaSmiLines) { "auto_nvidia_smi_absent" } else { "auto_no_cuda_gpu" }
        return [pscustomobject]@{ Variant = "cpu"; Directory = "cpu"; Device = "cpu"; Reason = $why }
    }
    $arch = "sm_" + ($gpu[2] -replace '\.', '')
    $path = if ($arch -in @("sm_86", "sm_89")) { "native" } else { "ptx-jit" }
    [pscustomobject]@{
        Variant = "cuda"; Directory = "cuda"
        Device = "cuda:$($gpu[0]) $($gpu[1]) ($arch, $path)"
        Reason = if ($Policy -eq "cuda") { "policy_cuda" } else { "auto_cuda_gpu_present" }
    }
}

# The language packs as release metadata entries (PoC S10, C9.1): the Runtime Pack and the bound Language Model Pack,
# its licence read from its installed LICENSE file and the runtime's from llama.cpp's LICENSE.
function Get-MaviPocLanguagePacks {
    param(
        [Parameter(Mandatory = $true)][string]$PayloadsPath,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ModelRoot,
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][string]$ModelPackId
    )
    $payloads = Get-Content -LiteralPath $PayloadsPath -Raw | ConvertFrom-Json
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if (@($manifest.capabilityIds) -join "," -ne "query-translation" -or [string]$manifest.verificationStatus -ne "unverified") {
        throw "'$ManifestPath' is not an unverified Language Model Pack."
    }
    $notice = @(@($manifest.artifacts) | Where-Object { [string]$_.artifactRole -eq [string]$manifest.licence.noticeArtifactRole })
    if ($notice.Count -ne 1) { throw "'$ManifestPath' names no single licence notice." }
    $modelLicence = Get-MaviPocNoticeLicence -Path (Join-Path $ModelRoot ([string]$notice[0].relativePath)) -ExpectedSha256 ([string]$notice[0].sha256) -DeclaredSpdxId ([string]$manifest.licence.spdxId)
    $runtimeLicence = Get-MaviPocNoticeLicence -Path (Join-Path $RuntimeRoot ([string]$payloads.runtime.licence.file)) -ExpectedSha256 ([string]$payloads.runtime.licence.sha256) -DeclaredSpdxId ([string]$payloads.runtime.licence.spdxId)
    @(
        [ordered]@{
            kind = "runtime"; role = "language"; capabilityId = "query-translation"
            packId = [string]$payloads.runtime.runtimeId; variant = "windows-x86_64-cpu;windows-x86_64-cuda"
            verificationStatus = "unverified"
            note = "llama.cpp $($payloads.runtime.release) published Windows builds (PoC S10, ADR-026); CUDA 12.4 runtime DLLs under the NVIDIA CUDA EULA Attachment A"
            licence = "$($runtimeLicence.SpdxId), read from its LICENSE (SHA-256 $($runtimeLicence.Sha256)); cudart/cuBLAS redistributables per the retained NVIDIA CUDA 12.4 EULA"
        },
        [ordered]@{
            kind = "model"; role = "language"; capabilityId = "query-translation"
            packId = $ModelPackId; variant = $null
            verificationStatus = [string]$manifest.verificationStatus
            note = "$($manifest.modelId) $($manifest.modelVersion), $($manifest.quantisation.type) (PoC S10, bound; translates questions into structured queries only, never answers)"
            licence = "$($modelLicence.SpdxId), read from its LICENSE (SHA-256 $($modelLicence.Sha256)); licence review $($manifest.licence.reviewStatus)"
        }
    )
}

# The faces role's Model Pack as a release metadata entry (PoC S6, ADR-022, C5A.3): one pack per face pipeline,
# each component's licence read from its own installed LICENSE file (the embedder's LICENSE, YuNet's LICENSE-yunet).
# The AdaFace checkpoint's terms are not in its code licence, so the entry states them.
function Get-MaviPocFacesPack {
    param(
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][string]$ModelRoot
    )
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    if (@($manifest.capabilityIds) -join "," -ne "embedding" -or [string]$manifest.verificationStatus -ne "unverified") {
        throw "'$ManifestPath' is not an unverified face embedding pack."
    }
    $licences = @()
    foreach ($role in @([string]$manifest.licence.noticeArtifactRole, "licence-notice-detector")) {
        $notice = @(@($manifest.artifacts) | Where-Object { [string]$_.artifactRole -eq $role })
        if ($notice.Count -ne 1) { throw "'$ManifestPath' names no single '$role' artefact." }
        # Both components are MIT (AdaFace/CVLface code; YuNet); a notice stating anything else refuses the pack.
        $licences += Get-MaviPocNoticeLicence -Path (Join-Path $ModelRoot ([string]$notice[0].relativePath)) -ExpectedSha256 ([string]$notice[0].sha256) -DeclaredSpdxId ([string]$manifest.licence.spdxId)
    }
    [ordered]@{
        kind = "model"; role = "faces"; capabilityId = "embedding"
        packId = "$($manifest.modelId)@$($manifest.modelVersion)"; variant = $null
        verificationStatus = [string]$manifest.verificationStatus
        note = "$($manifest.modelId) $($manifest.modelVersion) (PoC S6, bound; checkpoint research-only, Development-only; results are candidates, never identification)"
        licence = "embedder $($licences[0].SpdxId), read from its LICENSE (SHA-256 $($licences[0].Sha256)); detector $($licences[1].SpdxId), read from its LICENSE-yunet (SHA-256 $($licences[1].Sha256)); AdaFace checkpoint: WebFace4M non-commercial research terms; licence review $($manifest.licence.reviewStatus)"
    }
}

# The plates role's packs as release metadata entries (PoC S3, C4.1): the Runtime Pack and both Model Packs the
# plates binding names, each Model Pack with the licence read from its installed notice. The committed manifest of a
# capability is the one named by its binding's qualificationId.
function Get-MaviPocPlatesPacks {
    param(
        [Parameter(Mandatory = $true)][string]$ComponentBindingPath,
        [Parameter(Mandatory = $true)][string]$ManifestDirectory,
        [Parameter(Mandatory = $true)][string]$ModelRoot,
        [Parameter(Mandatory = $true)][string]$RuntimeProfilePath
    )
    $binding = Get-Content -LiteralPath $ComponentBindingPath -Raw | ConvertFrom-Json
    $role = @(@($binding.roles) | Where-Object { [string]$_.roleId -eq "plates" })
    if ($role.Count -ne 1) { throw "'$ComponentBindingPath' binds no single plates role." }
    $family = @(@($binding.runtimePacks) | Where-Object { [string]$_.runtimePackFamilyId -eq [string]$role[0].runtimePackFamilyId })
    if ($family.Count -ne 1) { throw "'$ComponentBindingPath' declares no single runtime family for the plates role." }
    $cpu = $family[0].variants."windows-x86_64-cpu"
    $runtimeProfile = Get-Content -LiteralPath $RuntimeProfilePath -Raw | ConvertFrom-Json
    $packs = @([ordered]@{
        kind = "runtime"; role = "plates"; capabilityId = $null
        packId = [string]$cpu.runtimePackId; variant = "windows-x86_64-cpu"
        verificationStatus = (Get-MaviPocRuntimeVerificationStatus -RuntimeProfile $runtimeProfile -Variant "windows-x86_64-cpu")
        note = "$($family[0].runtimePackFamilyId) Development environment, CPU only (lock $([string]$cpu.thirdPartyLockSha256))"
        licence = $null
    })
    foreach ($capability in @(@($binding.capabilityBindings) | Where-Object { [string]$_.roleId -eq "plates" -and [bool]$_.enabled } | Sort-Object { [string]$_.capabilityId })) {
        $manifestPath = Join-Path $ManifestDirectory ("{0}.json" -f [string]$capability.qualificationId)
        if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "No committed manifest for plates capability '$($capability.capabilityId)' ($manifestPath)." }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if (@($manifest.capabilityIds) -notcontains [string]$capability.capabilityId) { throw "'$manifestPath' does not serve capability '$($capability.capabilityId)'." }
        $notice = @(@($manifest.artifacts) | Where-Object { [string]$_.artifactRole -eq [string]$manifest.licence.noticeArtifactRole })
        if ($notice.Count -ne 1) { throw "'$manifestPath' names no single licence notice." }
        $licence = Get-MaviPocNoticeLicence -Path (Join-Path $ModelRoot ([string]$notice[0].relativePath)) -ExpectedSha256 ([string]$notice[0].sha256) -DeclaredSpdxId ([string]$manifest.licence.spdxId)
        $packs += [ordered]@{
            kind = "model"; role = "plates"; capabilityId = [string]$capability.capabilityId
            packId = [string]$capability.modelPackId; variant = $null
            verificationStatus = [string]$manifest.verificationStatus
            note = "$($manifest.modelId) $($manifest.modelVersion)"
            licence = "$($licence.SpdxId), read from its LICENSE (SHA-256 $($licence.Sha256)); licence review $($manifest.licence.reviewStatus)"
        }
    }
    return ,$packs
}

# The demo cameras: the S2 demo-corpus manifest, seeded as names, time zones and declared sites only
# (S2's corpus definition carries each camera's media and scene geometry).
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
        # The optional declared site (ADR-023 amendment 2026-10-30): Entity candidates pair only cameras of one site.
        $site = if ($null -ne $camera.PSObject.Properties["siteCode"]) { [string]$camera.siteCode } else { $null }
        if ($null -ne $site -and $site -cnotmatch '\A[a-z0-9][a-z0-9._-]{0,63}\z') { throw "Demo camera '$($camera.code)' has an invalid siteCode." }
        $cameras += [pscustomobject]@{ Code = [string]$camera.code; Name = [string]$camera.name; TimeZoneId = [string]$camera.timeZoneId; SiteCode = $site }
    }
    if ($cameras.Count -eq 0) { throw "The demo camera seed has no cameras." }
    return $cameras
}

# The demo corpus in the offline kit (PoC S13; plan D3; register B2, B3, D5): only the trimmed clips the S2
# definition pins with kit=true, each byte-identical to its pinned SHA-256, next to the definition, the
# attribution file and the licence texts. Kit media is CC0 / CC BY only, so any other licence code is refused;
# nothing else may sit in the folder, so no crop, embedding, gallery or owner-machine-only clip can ride along.
$script:PocDemoCorpusLicences = [ordered]@{
    "cc0"       = [ordered]@{ name = "CC0 1.0 Universal (public domain dedication)"; uri = "https://creativecommons.org/publicdomain/zero/1.0/legalcode"; textPrefix = "CC0-1.0" }
    "cc-by-2.0" = [ordered]@{ name = "Creative Commons Attribution 2.0 Generic"; uri = "https://creativecommons.org/licenses/by/2.0/legalcode"; textPrefix = "CC-BY-2.0" }
    "cc-by-3.0" = [ordered]@{ name = "Creative Commons Attribution 3.0 Unported"; uri = "https://creativecommons.org/licenses/by/3.0/legalcode"; textPrefix = "CC-BY-3.0" }
    "cc-by-4.0" = [ordered]@{ name = "Creative Commons Attribution 4.0 International"; uri = "https://creativecommons.org/licenses/by/4.0/legalcode"; textPrefix = "CC-BY-4.0" }
}
$script:PocDemoCorpusFixedFiles = @("demo-corpus-v1.json", "demo-corpus-attribution.md", "LICENCES.md")

function Copy-MaviPocDemoCorpus {
    param(
        [Parameter(Mandatory = $true)][string]$DefinitionPath,
        # The S2 corpus root: the clips are read from its derivatives\ folder.
        [Parameter(Mandatory = $true)][string]$CorpusRoot,
        [Parameter(Mandatory = $true)][string]$AttributionPath,
        # Full licence texts held offline: the legal codes, each named <textPrefix>-... (for example
        # CC-BY-4.0-legalcode.txt), and other notices such as MEVA's licence file. When any is given, every licence a kit
        # clip uses must have its legal code among them.
        [string[]]$LicenceFile = @(),
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $definition = Get-Content -LiteralPath $DefinitionPath -Raw | ConvertFrom-Json
    if ([string]$definition.schemaVersion -ne "mavi-poc-demo-corpus-v1") { throw "Unsupported demo corpus definition schema '$($definition.schemaVersion)'." }
    if (-not (Test-Path -LiteralPath $AttributionPath -PathType Leaf)) { throw "The demo corpus attribution file '$AttributionPath' is missing." }
    $clips = @($definition.clips | Where-Object { $_.kit -eq $true })
    if ($clips.Count -eq 0) { throw "The demo corpus definition names no kit clip." }
    if (Test-Path -LiteralPath $Destination) { throw "Demo corpus destination '$Destination' already exists." }
    $derivatives = Join-Path $Destination "derivatives"
    $licenceRoot = Join-Path $Destination "licences"
    New-Item -ItemType Directory -Path $derivatives, $licenceRoot -Force | Out-Null

    $records = @()
    $codes = New-Object "System.Collections.Generic.SortedSet[string]" ([StringComparer]::Ordinal)
    foreach ($clip in $clips) {
        $code = [string]$clip.source.licenceCode
        if (-not $script:PocDemoCorpusLicences.Contains($code)) { throw "Clip '$($clip.clipId)' has licence '$code'; kit media is CC0 / CC BY only (plan D3)." }
        $fileName = [string]$clip.derivative.fileName
        if ($fileName -notmatch '\A[A-Za-z0-9._-]+\.mp4\z') { throw "Clip '$($clip.clipId)' names an invalid derivative file '$fileName'." }
        $source = Join-Path (Join-Path $CorpusRoot "derivatives") $fileName
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "Kit clip '$($clip.clipId)' is missing at '$source'." }
        $expected = ([string]$clip.derivative.sha256).ToLowerInvariant()
        if ((Get-MaviSha256 -Path $source) -ne $expected) { throw "Kit clip '$($clip.clipId)' does not match its pinned SHA-256." }
        $target = Join-Path $derivatives $fileName
        Copy-Item -LiteralPath $source -Destination $target
        if ((Get-MaviSha256 -Path $target) -ne $expected) { throw "Kit clip '$($clip.clipId)' changed while it was copied." }
        [void]$codes.Add($code)
        $records += [ordered]@{ clipId = [string]$clip.clipId; fileName = $fileName; sha256 = $expected; licenceCode = $code; provider = [string]$clip.source.provider }
    }
    Copy-Item -LiteralPath $DefinitionPath -Destination (Join-Path $Destination "demo-corpus-v1.json")
    Copy-Item -LiteralPath $AttributionPath -Destination (Join-Path $Destination "demo-corpus-attribution.md")
    $licenceRecords = @()
    foreach ($file in @($LicenceFile)) {
        $item = Get-Item -LiteralPath $file
        if ($item.Name -notmatch '\A[A-Za-z0-9._-]+\.(txt|html)\z') { throw "Licence file '$($item.Name)' must be a .txt or .html file with a simple name." }
        $target = Join-Path $licenceRoot $item.Name
        if (Test-Path -LiteralPath $target) { throw "Two licence files are named '$($item.Name)'." }
        Copy-Item -LiteralPath $item.FullName -Destination $target
        $licenceRecords += [ordered]@{ fileName = $item.Name; sha256 = (Get-MaviSha256 -Path $target) }
    }

    $lines = @("# Demo corpus licences", "", "The clips in derivatives\ are published under the licences below; each clip's author, source, licence and changes are in demo-corpus-attribution.md, which must accompany the clips.", "", "| Licence | Clips | Legal code | Full text |", "|---|---|---|---|")
    foreach ($code in $codes) {
        $licence = $script:PocDemoCorpusLicences[$code]
        $ids = @($records | Where-Object { $_.licenceCode -eq $code } | ForEach-Object { $_.clipId }) -join ", "
        $texts = @($licenceRecords | Where-Object { $_.fileName.StartsWith($licence.textPrefix + "-", [StringComparison]::Ordinal) } | ForEach-Object { "licences\$($_.fileName)" })
        if ($licenceRecords.Count -gt 0 -and $texts.Count -eq 0) { throw "Licence texts were given, but none is the legal code of $($licence.name) ($($licence.textPrefix)-...)." }
        $lines += "| $($licence.name) | $ids | $($licence.uri) | $(if ($texts.Count -gt 0) { $texts -join ', ' } else { '(URI only)' }) |"
    }
    if ($licenceRecords.Count -gt 0) {
        $lines += @("", "Full texts held with the clips (licences\):", "")
        foreach ($licence in $licenceRecords) { $lines += "- $($licence.fileName) (SHA-256 $($licence.sha256))" }
    }
    [IO.File]::WriteAllText((Join-Path $Destination "LICENCES.md"), (($lines -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))

    return [ordered]@{
        definitionSha256 = Get-MaviSha256 -Path (Join-Path $Destination "demo-corpus-v1.json")
        attributionSha256 = Get-MaviSha256 -Path (Join-Path $Destination "demo-corpus-attribution.md")
        licenceIndexSha256 = Get-MaviSha256 -Path (Join-Path $Destination "LICENCES.md")
        clips = @($records)
        licences = @($licenceRecords)
    }
}

# Checks a kit's demo corpus folder against its record: every kit clip of the shipped definition present and
# byte-identical, the attribution and licence index present, and nothing else in the folder.
function Test-MaviPocDemoCorpus {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)]$Record)
    $definitionPath = Join-Path $Root "demo-corpus-v1.json"
    foreach ($name in $script:PocDemoCorpusFixedFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $name) -PathType Leaf)) { throw "The kit's demo corpus has no $name." }
    }
    if ((Get-MaviSha256 -Path $definitionPath) -ne [string]$Record.definitionSha256) { throw "The kit's demo corpus definition does not match its record." }
    if ((Get-MaviSha256 -Path (Join-Path $Root "demo-corpus-attribution.md")) -ne [string]$Record.attributionSha256) { throw "The kit's demo corpus attribution file does not match its record." }
    if ((Get-MaviSha256 -Path (Join-Path $Root "LICENCES.md")) -ne [string]$Record.licenceIndexSha256) { throw "The kit's demo corpus licence index does not match its record." }
    $definition = Get-Content -LiteralPath $definitionPath -Raw | ConvertFrom-Json
    $expected = @{}
    foreach ($clip in @($definition.clips | Where-Object { $_.kit -eq $true })) {
        if (-not $script:PocDemoCorpusLicences.Contains([string]$clip.source.licenceCode)) { throw "Kit clip '$($clip.clipId)' is not CC0 / CC BY." }
        $expected["derivatives/" + [string]$clip.derivative.fileName] = ([string]$clip.derivative.sha256).ToLowerInvariant()
    }
    foreach ($licence in @($Record.licences)) { $expected["licences/" + [string]$licence.fileName] = [string]$licence.sha256 }
    $prefix = ([IO.Path]::GetFullPath($Root)).TrimEnd("\") + "\"
    $seen = @{}
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force)) {
        $relative = $file.FullName.Substring($prefix.Length).Replace("\", "/")
        if ($script:PocDemoCorpusFixedFiles -contains $relative) { continue }
        if (-not $expected.ContainsKey($relative)) { throw "The kit's demo corpus carries an unlisted file '$relative'." }
        if ((Get-MaviSha256 -Path $file.FullName) -ne $expected[$relative]) { throw "The kit's demo corpus file '$relative' does not match its pinned SHA-256." }
        $seen[$relative] = $true
    }
    foreach ($key in $expected.Keys) { if (-not $seen.ContainsKey($key)) { throw "The kit's demo corpus is missing '$key'." } }
    return $expected.Count
}

# A Runtime Pack is installed only when its native code loads on this host: torch and
# an mmcv native op are imported in the installed runtime, after the bundled Visual C++
# runtime is in place, so a worker that cannot start is never left behind.
function Assert-MaviPocRuntimeLoads {
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot)
    $python = Join-Path $RuntimeRoot "venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "The Runtime Pack at '$RuntimeRoot' has no interpreter." }
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& $python -c "import torch, mmcv; from mmcv.ops import nms; print('torch', torch.__version__, 'mmcv', mmcv.__version__)" 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    if ($exitCode -ne 0) {
        $hint = if ($output -match "DLL load failed|msvcp140|vcruntime140|WinError 126|Error loading") { " A native library did not load; the installer installs the bundled Visual C++ x64 redistributable first, so check its result in the log." } else { "" }
        throw "The Runtime Pack at '$RuntimeRoot' does not load on this host.$hint Diagnostic: $output"
    }
    Write-Host "  $output"
}

# The Visual C++ 2015-2022 x64 runtime the Vision Runtime Packs load (torch, mmcv native
# ops; built with MSVC 14.44). Shipped in the PoC bundle and installed by the installer when
# the machine has none, or an older one, so a clean host needs nothing beforehand.
$script:VcRuntimeMinimum = [version]"14.44.0.0"

function Get-MaviPocVcRuntimeMinimum { $script:VcRuntimeMinimum }

# The installer the bundle carries: Microsoft-signed, a 14.x product version at least the
# minimum. Returns its version and SHA-256.
function Assert-MaviPocVcRedistInstaller {
    param([Parameter(Mandatory = $true)][string]$Path)
    $signature = Get-AuthenticodeSignature -FilePath $Path
    if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch '^CN=Microsoft Corporation,') {
        throw "'$Path' is not a valid Microsoft-signed installer ($($signature.Status))."
    }
    $productVersion = [string](Get-Item -LiteralPath $Path).VersionInfo.ProductVersion
    $parsed = $null
    if (-not [version]::TryParse($productVersion, [ref]$parsed) -or $parsed.Major -ne 14 -or $parsed -lt $script:VcRuntimeMinimum) {
        throw "'$Path' is version '$productVersion'; the Vision runtimes need the 14.x redistributable, at least $($script:VcRuntimeMinimum)."
    }
    [pscustomobject]@{ ProductVersion = $productVersion; Sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
}

# Whether the installed runtime (HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64:
# Installed, Major, Minor, Bld) satisfies the minimum. $Installed is that key's values, or
# $null when the key is absent.
function Test-MaviPocVcRuntimeSatisfied {
    param([AllowNull()]$Installed)
    if ($null -eq $Installed) { return $false }
    foreach ($name in @("Installed", "Major", "Minor", "Bld")) {
        if (-not $Installed.PSObject.Properties[$name]) { return $false }
    }
    if ([int]$Installed.Installed -ne 1) { return $false }
    $version = New-Object Version ([int]$Installed.Major), ([int]$Installed.Minor), ([int]$Installed.Bld), 0
    return $version -ge $script:VcRuntimeMinimum
}

function Get-MaviPocInstalledVcRuntime {
    Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -ErrorAction SilentlyContinue
}

# Installs the bundled redistributable unless a sufficient runtime is already there.
function Install-MaviPocVcRuntime {
    param([Parameter(Mandatory = $true)][string]$InstallerPath)
    if (Test-MaviPocVcRuntimeSatisfied -Installed (Get-MaviPocInstalledVcRuntime)) { return "already-present" }
    [void](Assert-MaviPocVcRedistInstaller -Path $InstallerPath)
    $process = Start-Process -FilePath $InstallerPath -ArgumentList @("/install", "/quiet", "/norestart") -Wait -PassThru
    # 1638: a newer version is installed; 3010: installed, restart pending.
    if ($process.ExitCode -notin @(0, 1638, 3010)) { throw "The Visual C++ redistributable installer failed with exit code $($process.ExitCode)." }
    if (-not (Test-MaviPocVcRuntimeSatisfied -Installed (Get-MaviPocInstalledVcRuntime))) {
        throw "The Visual C++ x64 runtime is still below $($script:VcRuntimeMinimum) after installing the bundled redistributable."
    }
    return "installed"
}

# Process records for what Start-MaviPoc started. A bare process id is not enough: MAVI
# does not survive a reboot, so a stale id can name an unrelated process by the next start.
# The record keeps the image name and start time, and a process that does not match both
# is not MAVI's.
function Write-MaviPocProcessRecord {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)
    $record = [ordered]@{
        schemaVersion = "mavi-poc-process-v1"
        processId = $Process.Id
        imageName = $Process.ProcessName
        startTimeUtc = $Process.StartTime.ToUniversalTime().ToString("O")
    }
    $directory = Split-Path $Path -Parent
    if ($directory) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    [IO.File]::WriteAllText($Path, ($record | ConvertTo-Json -Compress), (New-Object Text.UTF8Encoding -ArgumentList $false))
}

# The elevated installer changes ACLs and owners only on its own directories. A directory
# that is (or, with -Recurse, contains) a junction or symbolic link could redirect that to
# any other tree, so it is refused before anything is changed; its existing ancestors are
# checked too.
function Assert-MaviPocNoReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path, [switch]$Recurse)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing '$current': it is a junction or symbolic link." }
        }
        $parent = Split-Path $current -Parent
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    if ($Recurse -and (Test-Path -LiteralPath $Path -PathType Container)) {
        try { $links = @(Get-ChildItem -LiteralPath $Path -Recurse -Force -Attributes ReparsePoint -ErrorAction Stop) }
        catch { throw "Refusing '$Path': part of it cannot be inspected ($($_.Exception.Message)). Remove what you did not create there and rerun." }
        if ($links.Count -gt 0) { throw "Refusing '$Path': it contains a junction or symbolic link ($($links[0].FullName))." }
    }
}

# Secures an installation root before anything is created in it. Owned by Administrators,
# inheritance removed: SYSTEM and Administrators full control, Authenticated Users read and
# execute. No other user can then create, rename or replace anything under it, so a
# directory checked here cannot be swapped for a junction before the elevated installer
# uses it (the default ACL of ProgramData, or of another drive, lets every user create and
# own folders). The operator-writable directories get their own grants afterwards. The
# PostgreSQL service runs as LocalSystem and keeps full control.
function Protect-MaviPocRoot {
    param([Parameter(Mandatory = $true)][string]$Path)
    Assert-MaviPocNoReparsePoint -Path $Path
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    # The whole DACL is replaced, not edited: icacls /grant:r keeps any other explicit entry
    # (one a user who created the folder beforehand added for themselves).
    $administrators = New-Object Security.Principal.SecurityIdentifier("S-1-5-32-544")
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetOwner($administrators)
    $acl.SetAccessRuleProtection($true, $false)
    $inherit = [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit"
    $none = [Security.AccessControl.PropagationFlags]::None
    foreach ($entry in @(@("S-1-5-18", "FullControl"), @("S-1-5-32-544", "FullControl"), @("S-1-5-11", "ReadAndExecute"))) {
        $sid = New-Object Security.Principal.SecurityIdentifier($entry[0])
        $acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule($sid, [Security.AccessControl.FileSystemRights]$entry[1], $inherit, $none, "Allow")))
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
    $applied = Get-Acl -LiteralPath $Path
    $explicit = @($applied.Access | Where-Object { -not $_.IsInherited })
    $foreign = @($explicit | Where-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -notin @("S-1-5-18", "S-1-5-32-544", "S-1-5-11") })
    if ($foreign.Count -gt 0 -or -not $applied.AreAccessRulesProtected -or $applied.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne "S-1-5-32-544") {
        throw "Failed to secure '$Path': its owner or access list is not the one set."
    }
    # Anything that was already there (a rerun, or a folder planted before the first run)
    # must not be a link now that nobody else can replace it.
    $links = @(Get-ChildItem -LiteralPath $Path -Force -Attributes ReparsePoint -ErrorAction SilentlyContinue)
    if ($links.Count -gt 0) { throw "Refusing '$Path': it contains a junction or symbolic link ($($links[0].FullName))." }
}

# The recorded process if it is still the one that was started; otherwise the stale record
# is removed and $null returned. The identity comes from WMI (Win32_Process), which any
# user can read for every process, elevated or SYSTEM ones included: the image must be the
# one Start launched for this record (-ExpectedImageName), the creation time must be the
# recorded start time, and -ExpectedCommandFragment must appear in the command line where
# that is readable (always for the operator's own processes and for an elevated caller).
# An unreadable command line (another user's protected process, seen unelevated) is not
# checked; Stop's taskkill is then denied and reported. When WMI cannot answer at all for a
# live process, the record is kept and the call fails: neither Start (which would launch a
# second instance) nor Stop (which would report success) may proceed on a guess.
function Get-MaviPocRecordedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ExpectedImageName,
        [string]$ExpectedCommandFragment
    )
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $record = $null
    try { $record = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json } catch { $record = $null }
    $process = $null
    if ($record -and $record.PSObject.Properties["processId"] -and $record.PSObject.Properties["startTimeUtc"] -and $record.PSObject.Properties["imageName"] -and
        (-not $ExpectedImageName -or [string]$record.imageName -eq $ExpectedImageName)) {
        $processId = [int]$record.processId
        $candidate = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $wmi = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if ($candidate -and -not $wmi -and $candidate.ProcessName -eq [string]$record.imageName) {
            throw "Cannot verify process $processId recorded in '$Path' (WMI did not describe it); it may still be MAVI's. Check it, then remove the record."
        }
        if ($candidate -and $wmi -and $candidate.ProcessName -eq [string]$record.imageName -and $wmi.CreationDate) {
            $started = ([DateTime]$wmi.CreationDate).ToUniversalTime()
            $recorded = [DateTimeOffset]::Parse([string]$record.startTimeUtc).UtcDateTime
            $commandLine = [string]$wmi.CommandLine
            $commandMatches = (-not $ExpectedCommandFragment) -or [string]::IsNullOrEmpty($commandLine) -or
                $commandLine.IndexOf($ExpectedCommandFragment, [StringComparison]::OrdinalIgnoreCase) -ge 0
            if ([Math]::Abs(($started - $recorded).TotalSeconds) -lt 2 -and $commandMatches) { $process = $candidate }
        }
    }
    if (-not $process) { Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue }
    return $process
}

# --- Uninstall (PoC S6; ADR-022 section 5; register C5A.5) --------------------------------------
# The uninstaller removes only what an installation recorded: its two roots, its database and, when this
# installation owns it, its PostgreSQL service. Dropping the database removes every biometric derivative
# (face observations and embeddings, the enrolled gallery, transient face queries) with everything else.

# A root the uninstaller may delete: absolute, at least two levels below its drive, not a drive root, not a
# well-known system or profile directory or an ancestor of one, and neither a junction nor under one.
function Assert-MaviPocRemovableRoot {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][AllowNull()][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ([string]::IsNullOrWhiteSpace($Path)) { throw "Refusing to remove the ${Name}: no path is recorded." }
    $trimmed = $Path.Trim().Trim('"')
    if (-not [IO.Path]::IsPathRooted($trimmed) -or $trimmed -notmatch '^[A-Za-z]:\\') { throw "Refusing to remove the $Name '$Path': it is not an absolute local path." }
    $full = [IO.Path]::GetFullPath($trimmed)
    if ($full.Length -gt 3) { $full = $full.TrimEnd("\") }
    $driveRoot = [IO.Path]::GetPathRoot($full)
    $segments = @($full.Substring($driveRoot.Length).Split("\", [StringSplitOptions]::RemoveEmptyEntries))
    if ($segments.Count -lt 2) { throw "Refusing to remove the $Name '$full': it is a drive root or a top-level directory." }
    $protected = @($env:SystemRoot, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramData, $env:USERPROFILE, $env:PUBLIC, $env:APPDATA, $env:LOCALAPPDATA, (Join-Path $driveRoot "Users")) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd("\") }
    foreach ($directory in $protected) {
        if ($full.Equals($directory, [StringComparison]::OrdinalIgnoreCase) -or $directory.StartsWith($full + "\", [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove the $Name '$full': it is, or contains, the system directory '$directory'."
        }
    }
    Assert-MaviPocNoReparsePoint -Path $full
    return $full
}

# Host, port, database and user of the platform's connection string (the machine configuration).
function ConvertFrom-MaviPocConnectionString {
    param([Parameter(Mandatory = $true)][string]$ConnectionString)
    $values = @{}
    foreach ($part in $ConnectionString.Split(";")) {
        $pair = $part.Split("=", 2)
        if ($pair.Count -eq 2) { $values[$pair[0].Trim().ToLowerInvariant()] = $pair[1].Trim() }
    }
    foreach ($key in @("host", "port", "database", "username")) {
        if (-not $values.ContainsKey($key) -or [string]::IsNullOrWhiteSpace($values[$key])) { throw "The machine configuration's connection string has no $key." }
    }
    [pscustomobject]@{ Host = $values["host"]; Port = [int]$values["port"]; Database = $values["database"]; Username = $values["username"] }
}

# What an uninstall removes, from the recorded installation alone. $Service is the Win32_Service record of the
# recorded PostgreSQL service ($null when absent): it is removed only when its command line names this
# installation's PostgreSQL install and data directories (the installer's own ownership test); a shared
# instance (the Development rehearsal) keeps running and loses only this installation's database and role.
function New-MaviPocUninstallPlan {
    param(
        [Parameter(Mandatory = $true)]$State,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)]$Connection,
        $Service
    )
    if ([string]$State.schemaVersion -ne "mavi-poc-installation-v1" -or [string]$State.profile -ne (Get-MaviPocProfile)) {
        throw "The installation state is not a $(Get-MaviPocProfile) installation (schema '$($State.schemaVersion)')."
    }
    $data = Assert-MaviPocRemovableRoot -Path $DataRoot -Name "data root"
    $recordedData = Assert-MaviPocRemovableRoot -Path ([string]$State.dataRoot) -Name "recorded data root"
    if (-not $data.Equals($recordedData, [StringComparison]::OrdinalIgnoreCase)) { throw "The installation state records data root '$recordedData', not '$data'." }
    $install = Assert-MaviPocRemovableRoot -Path ([string]$State.installRoot) -Name "install root"
    if ($install.StartsWith($data + "\", [StringComparison]::OrdinalIgnoreCase) -or $data.StartsWith($install + "\", [StringComparison]::OrdinalIgnoreCase) -or $install.Equals($data, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to uninstall: the install root '$install' and data root '$data' overlap."
    }
    $layout = Get-MaviPocLayout -InstallRoot $install -DataRoot $data
    if ([string]$Connection.Host -notin @("127.0.0.1", "localhost", "::1")) { throw "Refusing to drop a database on '$($Connection.Host)': only the local instance is the installation's." }
    $database = [string]$Connection.Database
    if ($database -in @("postgres", "template0", "template1") -or $database -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw "Refusing to drop database '$database'." }
    $role = [string]$Connection.Username
    $dropRole = $role -match '^[A-Za-z_][A-Za-z0-9_]*$' -and $role -ne "postgres"
    $serviceName = [string]$State.postgresqlServiceName
    $owned = $false
    $psql = $null
    if ($Service) {
        $pathName = [string]$Service.PathName
        $owned = $pathName.IndexOf($layout.PostgreSqlInstallRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
            $pathName.IndexOf($layout.PostgreSqlDataRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
        $match = [regex]::Match($pathName, '^\s*"?(?<exe>[A-Za-z]:\\[^"]*?pg_ctl\.exe)"?', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if ($match.Success) { $psql = Join-Path (Split-Path $match.Groups["exe"].Value -Parent) "psql.exe" }
    }
    if (-not $psql) { $psql = Join-Path $layout.PostgreSqlInstallRoot "bin\psql.exe" }
    [ordered]@{
        schemaVersion = "mavi-poc-uninstall-plan-v1"
        profile = Get-MaviPocProfile
        installRoot = $install
        dataRoot = $data
        stopMavi = $true
        database = [ordered]@{ action = "drop"; port = [int]$Connection.Port; name = $database; role = $role; dropRole = $dropRole; psql = $psql }
        postgresqlService = [ordered]@{
            name = $serviceName
            present = [bool]$Service
            owned = $owned
            action = $(if ($owned) { "remove" } else { "keep" })
            reason = $(if (-not $Service) { "absent" } elseif ($owned) { "owned by this installation" } else { "not this installation's (shared instance): only its database and role are dropped" })
        }
        removeDirectories = @($data, $install)
    }
}

Export-ModuleMember -Function Copy-MaviPocDemoCorpus, Test-MaviPocDemoCorpus, Assert-MaviPocRemovableRoot, ConvertFrom-MaviPocConnectionString, New-MaviPocUninstallPlan, Get-MaviPocVcRuntimeMinimum, Assert-MaviPocVcRedistInstaller, Test-MaviPocVcRuntimeSatisfied, Get-MaviPocInstalledVcRuntime, Install-MaviPocVcRuntime, Protect-MaviPocRoot, Assert-MaviPocNoReparsePoint, Assert-MaviPocRuntimeLoads, Write-MaviPocProcessRecord, Get-MaviPocRecordedProcess, Get-MaviPocProfile, Get-MaviPocOperatorUrl, Get-MaviPocDisclosureStatement, Get-MaviPocLayout, Test-MaviPocCudaCompatibleGpu, Get-MaviPocCudaRuntimePackCandidates, Select-MaviPocCudaRuntimePack, Get-MaviPocCudaBuildKey, Get-MaviPocCudaBuildStatus, Get-MaviPocRuntimeVerificationStatus, Get-MaviPocModelVerificationStatus, New-MaviPocReleaseMetadata, New-MaviPocMachineConfig, Read-MaviPocDemoCameras, Get-MaviPocNoticeLicence, Get-MaviPocPlatesPacks, Get-MaviPocFacesPack, Select-MaviPocLanguagePack, Resolve-MaviPocLanguageDevice, Get-MaviPocLanguagePacks
