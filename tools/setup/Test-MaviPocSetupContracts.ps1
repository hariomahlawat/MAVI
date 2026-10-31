[CmdletBinding()]
param()

# Contract tests for the poc-single-host installer (PoC S1; ADR-020; register rows A2-A5).
# They need no administrator rights, no network and no installation: the pure functions are
# called directly, plan-only runs against a minimal fake bundle, and the scripts that must
# keep a shape (fail closed, no Machine environment, overlay revision) are checked by text.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("mavi-poc-contracts-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

function Assert-Throws {
    param([Parameter(Mandatory = $true)][scriptblock]$Block, [Parameter(Mandatory = $true)][string]$Pattern, [Parameter(Mandatory = $true)][string]$Because)
    try { & $Block } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw "$Because - threw '$($_.Exception.Message)', expected /$Pattern/." }
        return
    }
    throw "$Because - did not throw."
}

try {
    # --- Layout: every path under the two roots; equal roots refused (no shared state). ---
    # Roots under the temporary directory: Join-Path in Windows PowerShell refuses a drive the
    # host does not have, and CI runners have no E:.
    $pocRoot = Join-Path $tempRoot "PoC"
    $layout = Get-MaviPocLayout -InstallRoot (Join-Path $pocRoot "Program") -DataRoot (Join-Path $pocRoot "Data")
    foreach ($property in $layout.PSObject.Properties) {
        $value = [string]$property.Value
        if (-not ($value.StartsWith($layout.InstallRoot, [StringComparison]::OrdinalIgnoreCase) -or $value.StartsWith($layout.DataRoot, [StringComparison]::OrdinalIgnoreCase))) {
            throw "Layout path '$($property.Name)' escapes the installation roots: $value"
        }
        if ($value -match "MAVI\\Development") { throw "Layout path '$($property.Name)' reuses the Development installation." }
    }
    Assert-Throws { Get-MaviPocLayout -InstallRoot $pocRoot -DataRoot ($pocRoot + "\") } "must be different" "Equal install and data roots"

    # --- GPU check: only the build contract's compute capability gets the CUDA pack. ---
    $contract = Read-MaviJson -Path (Join-Path $repoRoot "config\vision\windows-cuda-development-build-v1.json")
    $required = [string]$contract.targetGpu.computeCapability
    if ($required -ne "7.5") { throw "The frozen v1 build contract no longer targets 7.5; revisit the PoC GPU check." }
    $none = Test-MaviPocCudaCompatibleGpu -NvidiaSmiLines $null -RequiredComputeCapability $required
    if ($none.Compatible -or $none.Reason -ne "nvidia_smi_absent") { throw "A host without nvidia-smi must not be offered CUDA." }
    $empty = Test-MaviPocCudaCompatibleGpu -NvidiaSmiLines @() -RequiredComputeCapability $required
    if ($empty.Compatible -or $empty.Reason -ne "no_nvidia_gpu") { throw "A host with no GPU listed must not be offered CUDA." }
    $laptop = Test-MaviPocCudaCompatibleGpu -NvidiaSmiLines @("0, NVIDIA GeForce GTX 1650 Ti, 7.5") -RequiredComputeCapability $required
    if (-not $laptop.Compatible -or $laptop.Index -ne "0") { throw "The sm_75 Development laptop GPU must be compatible." }
    $ada = Test-MaviPocCudaCompatibleGpu -NvidiaSmiLines @("0, NVIDIA GeForce RTX 4090, 8.9") -RequiredComputeCapability $required
    if ($ada.Compatible -or $ada.Reason -ne "compute_capability_unsupported") { throw "An sm_89 GPU must not get the sm_75 pack (S1b builds its variant)." }

    # --- S1b pack selection: each GPU gets the build whose contract targets it; sm_75 keeps v1. ---
    $selectionBundle = Join-Path $tempRoot "selection-bundle"
    foreach ($directory in @("windows-x86_64-cuda", "windows-x86_64-cuda-sm75-sm89")) {
        New-Item -ItemType Directory -Path (Join-Path $selectionBundle "vision\runtime\$directory") -Force | Out-Null
        "{}" | Set-Content -LiteralPath (Join-Path $selectionBundle "vision\runtime\$directory\runtime-pack-manifest.json") -Encoding ASCII
    }
    $candidates = Get-MaviPocCudaRuntimePackCandidates -OverlayRoot $repoRoot -BundleRoot $selectionBundle
    if ((@($candidates | ForEach-Object { $_.Key }) -join ",") -ne "sm75,sm75-sm89") { throw "The CUDA builds must be offered v1 (sm75) first, then sm75-sm89." }
    if ((@($candidates[1].ComputeCapabilities) -join ";") -ne "7.5;8.9" -or -not $candidates[1].Available) { throw "The sm75-sm89 build must come from the v2 contract's targetGpus." }
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, NVIDIA GeForce GTX 1650 Ti, 7.5") -Candidates $candidates
    if (-not $pick.Compatible -or $pick.Pack.Key -ne "sm75") { throw "Auto on sm_75 must keep the v1 sm_75 pack." }
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, NVIDIA GeForce RTX 4090, 8.9") -Candidates $candidates
    if (-not $pick.Compatible -or $pick.Pack.Key -ne "sm75-sm89" -or $pick.Pack.Source -notlike "*windows-x86_64-cuda-sm75-sm89") { throw "Auto on sm_89 must take the sm75-sm89 pack from the bundle." }
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, NVIDIA GeForce GTX 1650 Ti, 7.5") -Candidates $candidates -Requested "sm75-sm89"
    if (-not $pick.Compatible -or $pick.Pack.Key -ne "sm75-sm89") { throw "The sm75-sm89 pack may be selected explicitly on sm_75 (it targets 7.5)." }
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, NVIDIA GeForce RTX 4090, 8.9") -Candidates $candidates -Requested "sm75"
    if ($pick.Compatible -or $pick.Reason -ne "compute_capability_unsupported") { throw "The sm_75 pack must not be installed on sm_89." }
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, NVIDIA GeForce RTX 3080, 8.6") -Candidates $candidates
    if ($pick.Compatible -or $pick.Reason -ne "compute_capability_unsupported") { throw "No build targets sm_86; compute_89 PTX must not be claimed for it." }
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines $null -Candidates $candidates
    if ($pick.Compatible -or $pick.Reason -ne "nvidia_smi_absent") { throw "No nvidia-smi means no CUDA pack." }
    $v1Only = @($candidates[0].PSObject.Copy())
    $v1Only[0].Available = $false
    $pick = Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, NVIDIA GeForce GTX 1650 Ti, 7.5") -Candidates @($v1Only[0], $candidates[1])
    if ($pick.Pack.Key -ne "sm75" -or $pick.Pack.Available) { throw "Auto on sm_75 must not drift onto the sm75-sm89 pack because the bundle lacks the sm_75 one." }
    Assert-Throws { Select-MaviPocCudaRuntimePack -NvidiaSmiLines @("0, X, 8.9") -Candidates $candidates -Requested "sm90" } "not declared" "An undeclared pack name"
    if ((Get-MaviPocCudaBuildStatus -OverlayRoot $repoRoot -RuntimePackId ("mavi-runtime-v2-" + "0" * 64)) -ne "unrecorded") { throw "A pack the catalogue does not name has no recorded status." }
    $install = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MAVI-PoC.ps1") -Raw
    if ($install -notmatch 'Get-MaviPocCudaBuildStatus -OverlayRoot') { throw "The sm75-sm89 pack must report its own status, never v1's." }
    if (([regex]::Matches($install, 'Get-MaviPocCudaBuildKey -Binding \$overlayBinding')).Count -ne 2) { throw "The installer must check both a bundled and an adopted CUDA pack against the component binding." }
    if ($install -notmatch 'this bundle does not carry that CUDA Runtime Pack') { throw "An explicit -CudaRuntimePack the bundle lacks must not be dropped silently." }

    # --- The component binding decides which CUDA pack is which build (ADR-014 amendment 2026-10-29). ---
    # One rule for the bundle builder, the kit builder and the installer: the release pin is sm75,
    # a declared Development build is its buildId, anything else is nothing.
    $releaseBinding = Read-MaviJson -Path (Join-Path $repoRoot "src\vision\config\components\phase1-bindings-v2.json")
    $pinId = [string]$releaseBinding.runtimePacks[0].variants."windows-x86_64-cuda".runtimePackId
    $buildId = [string]@($releaseBinding.runtimePacks[0].developmentBuilds."windows-x86_64-cuda")[0].runtimePackId
    if ((Get-MaviPocCudaBuildKey -Binding $releaseBinding -RuntimePackId $pinId) -ne "sm75") { throw "The release CUDA pin must be the sm75 build." }
    if ((Get-MaviPocCudaBuildKey -Binding $releaseBinding -RuntimePackId $buildId) -ne "sm75-sm89") { throw "The declared Development build must be sm75-sm89." }
    if ($null -ne (Get-MaviPocCudaBuildKey -Binding $releaseBinding -RuntimePackId ("mavi-runtime-v2-" + "0" * 64))) { throw "An undeclared pack is no build." }
    $catalogEntry = (Read-MaviJson -Path (Join-Path $repoRoot "config\dependencies\offline-binary-catalog-v1.json")).visionRuntime.windowsCudaPocSm89Candidate
    if ([string]$catalogEntry.runtimePackId -ne $buildId -or (Get-MaviPocCudaBuildStatus -OverlayRoot $repoRoot -RuntimePackId $buildId) -ne "built-hashed-locked") { throw "The disclosed sm75-sm89 status must be the catalogue's built-hashed-locked for the bound build." }
    $withoutBuilds = Read-MaviJson -Path (Join-Path $repoRoot "src\vision\config\components\phase1-bindings-v2.json")
    $withoutBuilds.runtimePacks[0].PSObject.Properties.Remove("developmentBuilds")
    if ($null -ne (Get-MaviPocCudaBuildKey -Binding $withoutBuilds -RuntimePackId $buildId)) { throw "Without the declaration the sm75-sm89 pack is no build." }
    if ((Get-MaviPocCudaBuildKey -Binding $withoutBuilds -RuntimePackId $pinId) -ne "sm75") { throw "The release pin must not depend on the Development builds." }
    $bundleBuilder = Get-Content -LiteralPath (Join-Path $PSScriptRoot "New-MaviPocSetupBundle.ps1") -Raw
    if ($bundleBuilder -notmatch 'Get-MaviPocCudaBuildKey -Binding \$binding') { throw "The bundle builder must accept the sm75-sm89 pack only as the binding's declared build." }
    $kitBuilder = Get-Content -LiteralPath (Join-Path $PSScriptRoot "New-MaviOfflineBinaryKit.ps1") -Raw
    if ($kitBuilder -notmatch 'Get-MaviPocCudaBuildKey -Binding \$repoBinding') { throw "The kit builder must accept only CUDA packs the binding declares." }
    $noV1 = Join-Path $tempRoot "no-v1"
    New-Item -ItemType Directory -Path (Join-Path $noV1 "config\vision") -Force | Out-Null
    Assert-Throws { Get-MaviPocCudaRuntimePackCandidates -OverlayRoot $noV1 -BundleRoot $null } "is missing" "A bundle without the frozen v1 build contract"

    # --- Kit demo corpus (S13; B2, B3, D5): only pinned kit clips, CC0 / CC BY, with attribution and licences. ---
    $corpus = Join-Path $tempRoot "corpus"
    New-Item -ItemType Directory -Path (Join-Path $corpus "derivatives") -Force | Out-Null
    $clipFiles = [ordered]@{ "a.mp4" = "clip a"; "b.mp4" = "clip b"; "owner-only.mp4" = "not for the kit"; "unlisted.mp4" = "never listed" }
    foreach ($entry in $clipFiles.GetEnumerator()) { [IO.File]::WriteAllText((Join-Path $corpus "derivatives\$($entry.Key)"), $entry.Value) }
    $clipSha = @{}; foreach ($name in $clipFiles.Keys) { $clipSha[$name] = Get-MaviSha256 -Path (Join-Path $corpus "derivatives\$name") }
    function New-TestCorpusDefinition([string]$Path, [string]$SecondLicence = "cc-by-4.0", [string]$SecondSha = $clipSha["b.mp4"]) {
        $clips = @(
            [ordered]@{ clipId = "c-a"; kit = $true; source = [ordered]@{ provider = "wikimedia-commons"; licenceCode = "cc0" }; derivative = [ordered]@{ fileName = "a.mp4"; sha256 = $clipSha["a.mp4"] } },
            [ordered]@{ clipId = "c-b"; kit = $true; source = [ordered]@{ provider = "meva"; licenceCode = $SecondLicence }; derivative = [ordered]@{ fileName = "b.mp4"; sha256 = $SecondSha } },
            [ordered]@{ clipId = "c-owner"; kit = $false; source = [ordered]@{ provider = "pexels"; licenceCode = "pexels" }; derivative = [ordered]@{ fileName = "owner-only.mp4"; sha256 = $clipSha["owner-only.mp4"] } })
        Write-MaviJson -Value ([ordered]@{ schemaVersion = "mavi-poc-demo-corpus-v1"; clips = $clips }) -Path $Path -Depth 6
    }
    $corpusDefinition = Join-Path $tempRoot "demo-corpus-v1.json"
    New-TestCorpusDefinition -Path $corpusDefinition
    $attribution = Join-Path $tempRoot "attribution.md"
    [IO.File]::WriteAllText($attribution, "# attribution")
    $licenceText = Join-Path $tempRoot "MEVA-data-license.txt"
    [IO.File]::WriteAllText($licenceText, "CC BY 4.0 full text")
    $cc0Text = Join-Path $tempRoot "CC0-1.0-legalcode.txt"; [IO.File]::WriteAllText($cc0Text, "CC0 legal code")
    $ccBy4Text = Join-Path $tempRoot "CC-BY-4.0-legalcode.html"; [IO.File]::WriteAllText($ccBy4Text, "<p>CC BY 4.0 legal code</p>")
    $kitCorpus = Join-Path $tempRoot "kit-corpus"
    $corpusRecord = Copy-MaviPocDemoCorpus -DefinitionPath $corpusDefinition -CorpusRoot $corpus -AttributionPath $attribution -LicenceFile $cc0Text, $ccBy4Text, $licenceText -Destination $kitCorpus
    if ((Test-MaviPocDemoCorpus -Root $kitCorpus -Record $corpusRecord) -ne 5) { throw "The kit corpus must verify its two kit clips and three licence texts." }
    if ((@(Get-ChildItem -LiteralPath (Join-Path $kitCorpus "derivatives") -File).Name -join ",") -ne "a.mp4,b.mp4") { throw "Only kit=true clips may enter the kit (owner-machine media and unlisted files never do)." }
    $licenceIndex = Get-Content -LiteralPath (Join-Path $kitCorpus "LICENCES.md") -Raw
    if ($licenceIndex -notmatch 'publicdomain/zero/1\.0/legalcode' -or $licenceIndex -notmatch 'licenses/by/4\.0/legalcode' -or $licenceIndex -notmatch 'MEVA-data-license\.txt' -or $licenceIndex -notmatch 'licences\\CC0-1\.0-legalcode\.txt' -or $licenceIndex -notmatch 'licences\\CC-BY-4\.0-legalcode\.html') { throw "The licence index must name each clip licence's legal code and the shipped texts." }
    Copy-Item -LiteralPath (Join-Path $corpus "derivatives\unlisted.mp4") -Destination (Join-Path $kitCorpus "derivatives\unlisted.mp4")
    Assert-Throws { Test-MaviPocDemoCorpus -Root $kitCorpus -Record $corpusRecord } "unlisted file" "A file the definition does not pin in the kit corpus (for example a crop or another dataset's clip)"
    Remove-Item -LiteralPath (Join-Path $kitCorpus "derivatives\unlisted.mp4")
    New-Item -ItemType Directory -Path (Join-Path $kitCorpus "faces") -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $kitCorpus "faces\crop.jpg"), "x")
    Assert-Throws { Test-MaviPocDemoCorpus -Root $kitCorpus -Record $corpusRecord } "unlisted file" "A biometric derivative in the kit corpus"
    Remove-Item -LiteralPath (Join-Path $kitCorpus "faces") -Recurse
    [IO.File]::WriteAllText((Join-Path $kitCorpus "derivatives\b.mp4"), "tampered")
    Assert-Throws { Test-MaviPocDemoCorpus -Root $kitCorpus -Record $corpusRecord } "pinned SHA-256" "A changed kit clip"
    Remove-Item -LiteralPath (Join-Path $kitCorpus "derivatives\b.mp4")
    Assert-Throws { Test-MaviPocDemoCorpus -Root $kitCorpus -Record $corpusRecord } "missing" "A kit clip removed from the kit corpus"
    Remove-Item -LiteralPath (Join-Path $kitCorpus "demo-corpus-attribution.md")
    Assert-Throws { Test-MaviPocDemoCorpus -Root $kitCorpus -Record $corpusRecord } "attribution" "A kit corpus without its attribution file"
    $nc = Join-Path $tempRoot "nc.json"; New-TestCorpusDefinition -Path $nc -SecondLicence "cc-by-nc-4.0"
    Assert-Throws { Copy-MaviPocDemoCorpus -DefinitionPath $nc -CorpusRoot $corpus -AttributionPath $attribution -Destination (Join-Path $tempRoot "kit-nc") } "CC0 / CC BY only" "A non-CC0/CC-BY clip marked for the kit"
    $wrong = Join-Path $tempRoot "wrong.json"; New-TestCorpusDefinition -Path $wrong -SecondSha ("0" * 64)
    Assert-Throws { Copy-MaviPocDemoCorpus -DefinitionPath $wrong -CorpusRoot $corpus -AttributionPath $attribution -Destination (Join-Path $tempRoot "kit-wrong") } "pinned SHA-256" "A source clip that does not match its pin"
    Assert-Throws { Copy-MaviPocDemoCorpus -DefinitionPath $corpusDefinition -CorpusRoot $corpus -AttributionPath $attribution -LicenceFile $cc0Text, $licenceText -Destination (Join-Path $tempRoot "kit-no-by4") } "none is the legal code of Creative Commons Attribution 4\.0" "Licence texts without a used licence's legal code"
    Assert-Throws { Copy-MaviPocDemoCorpus -DefinitionPath $corpusDefinition -CorpusRoot $corpus -AttributionPath (Join-Path $tempRoot "none.md") -Destination (Join-Path $tempRoot "kit-none") } "attribution file" "A kit corpus without an attribution source"
    if ($kitBuilder -notmatch 'Copy-MaviPocDemoCorpus -DefinitionPath \(Join-Path \$PSScriptRoot "\.\.\\\.\.\\tools\\poc\\demo-corpus\\demo-corpus-v1\.json"\)' -or $kitBuilder -notmatch 'docs\\qualification\\poc\\demo-corpus-attribution\.md') { throw "The kit builder must take the corpus definition and attribution from the repository." }
    $kitChecker = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Test-MaviOfflineBinaryKit.ps1") -Raw
    if ($kitChecker -notmatch 'Test-MaviPocDemoCorpus' -or $kitChecker -notmatch 'carries media but records no demo corpus') { throw "The kit checker must verify a kit's demo corpus and refuse unrecorded media." }

    # --- Release metadata: the disclosure is fixed; the platform's start-up checks hold. ---
    $packs = @([ordered]@{ kind = "runtime"; role = "vision"; capabilityId = $null; packId = "mavi-runtime-v2-x"; variant = "windows-x86_64-cpu"; verificationStatus = "qualified-hosted-cpu"; note = $null })
    $metadata = New-MaviPocReleaseMetadata -ApplicationRevision ("a" * 40) -BundleSha256 ("b" * 64) -DevicePolicy "Auto" -CudaDecision ([ordered]@{ gpuCheck = "nvidia_smi_absent" }) -Packs $packs -InstalledAtUtc "2026-10-28T00:00:00Z"
    if ($metadata.schemaVersion -ne "mavi-poc-release-metadata-v1" -or $metadata.profile -ne "poc-single-host" -or $metadata.productionQualified -ne $false -or $metadata.evidenceClass -ne "Development") {
        throw "Release metadata does not carry the fixed poc-single-host disclosure."
    }
    if ((Get-Command New-MaviPocReleaseMetadata).Parameters.Keys -match "Qualified|Evidence|Profile|Disclosure") {
        throw "New-MaviPocReleaseMetadata must offer no parameter that changes the disclosure."
    }
    Assert-Throws { New-MaviPocReleaseMetadata -ApplicationRevision "main" -BundleSha256 ("b" * 64) -DevicePolicy "Auto" -CudaDecision @{} -Packs $packs -InstalledAtUtc "x" } "40-hex" "A non-commit revision"
    Assert-Throws { New-MaviPocReleaseMetadata -ApplicationRevision ("a" * 40) -BundleSha256 ("b" * 64) -DevicePolicy "Auto" -CudaDecision @{} -Packs @(@{ kind = "model"; role = "vision"; packId = "x" }) -InstalledAtUtc "x" } "verificationStatus" "A pack without verification status"

    # --- Machine configuration: loopback only, the profile declared, nothing else. ---
    $config = New-MaviPocMachineConfig -Layout $layout -ConnectionString "Host=127.0.0.1" -CursorSigningKey (New-MaviCursorSigningKey) -HttpPort 8090
    if ($config.Kestrel.Endpoints.Http.Url -ne "http://127.0.0.1:8090") { throw "The PoC platform must listen on loopback only." }
    if ($config.Deployment.Profile -ne "poc-single-host" -or $config.Deployment.ReleaseMetadataPath -ne $layout.ReleaseMetadataPath) { throw "The machine configuration must declare the PoC profile and its metadata." }
    if (@($config.Deployment.Keys) -join "," -ne "Profile,ReleaseMetadataPath,DeviceResolutionPath,RoleDeviceResolutionPaths") { throw "The Deployment section carries a key the platform does not define." }
    if ($config.Identity.Mode -ne "windows-negotiate" -or (@($config.Identity.Operators.AuthorizedGroups) -join ",") -ne "BUILTIN\Users") { throw "The PoC platform must identify operators by Windows account (ADR-010)." }
    if ($metadata.identityMode -ne $config.Identity.Mode) { throw "The release metadata must record the identity mode the machine configuration sets." }
    if ((Get-MaviPocOperatorUrl -HttpPort 8090) -ne "http://localhost:8090") { throw "Operators must open the PoC at localhost, where browsers negotiate Windows identity (ADR-010)." }
    $installText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MAVI-PoC.ps1") -Raw
    $startText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviPoc.ps1") -Raw
    if (-not $startText.Contains("`$state.PSObject.Properties['operatorUrl']") -or $startText -match '\$state\.operatorUrl') { throw "Start-MaviPoc must accept an installation state without operatorUrl under strict mode." }
    $oldStateUrl = & { Set-StrictMode -Version Latest; $state = [pscustomobject]@{ apiBaseUrl = "http://127.0.0.1:8090" }; $p = $state.PSObject.Properties['operatorUrl']; if ($p -and [string]$p.Value) { [string]$p.Value } else { $state.apiBaseUrl } }
    if ($oldStateUrl -ne "http://127.0.0.1:8090") { throw "An installation state without operatorUrl must fall back to apiBaseUrl." }
    if (-not $installText.Contains('.Replace("__MAVI_POC_URL__", (Get-MaviPocOperatorUrl -HttpPort $HttpPort))') -or -not $installText.Contains('apiBaseUrl = "http://127.0.0.1:$HttpPort"')) { throw "The launcher must open the operator URL; scripts must keep the loopback API URL." }
    if ($config.AllowedHosts -ne "localhost;127.0.0.1") { throw "The PoC platform must accept only loopback host names." }
    $serialised = ConvertTo-Json -InputObject $config -Depth 8 | ConvertFrom-Json
    if (@($serialised.Identity.Operators.AuthorizedGroups).Count -ne 1 -or $serialised.Identity.Operators.AuthorizedGroups -isnot [array]) { throw "The operator groups must serialise as a JSON array." }
    # PoC S3 (C4.1): the plates role is bound by the machine configuration, its device record disclosed beside the
    # Vision worker's; re-analysis is authorised by ADR-010 operator identity, not a plate-specific key.
    if ($config.Deployment.RoleDeviceResolutionPaths.plates -ne $layout.PlatesDeviceResolutionPath) { throw "The plates device record is not disclosed." }
    if ($config.Plates.Enabled -ne $true -or $config.Plates.ComponentBindingPath -ne $layout.PlatesComponentBindingPath -or $config.Plates.PipelineProfilePath -ne $layout.PlatesPipelineProfilePath) {
        throw "The machine configuration must bind the plates role to the overlay's PD5 + OC1-S release."
    }
    if (@($config.Plates.Keys) -contains "ReanalysisOperatorKeySha256") { throw "Re-analysis is authorised by ADR-010 operator identity; the installer configures no operator key." }
    if (-not $layout.PlatesComponentBindingPath.EndsWith("development-plates-onnx-pilot-v1.json") -or -not (Test-Path -LiteralPath (Join-Path $repoRoot "src\vision\config\components\development-plates-onnx-pilot-v1.json"))) {
        throw "The PoC plates binding must be the committed PD5 + OC1-S binding."
    }

    # --- Plates device (ADR-008 per runtime; PoC S3): CPU only, reason recorded, CUDA fails closed. ---
    $platesBinding = Join-Path $repoRoot "src\vision\config\components\development-plates-onnx-pilot-v1.json"
    $auto = Resolve-MaviPlatesDevicePolicy -DevicePolicy auto -ComponentBindingPath $platesBinding
    if ($auto.ResolvedDevicePolicy -ne "cpu" -or $auto.DeviceResolutionReason -ne "plates_runtime_cpu_only" -or $auto.RuntimeVariant -ne "windows-x86_64-cpu" -or -not $auto.RuntimePackId.StartsWith("mavi-runtime-v2-")) {
        throw "Plates Auto must resolve CPU with the reason plates_runtime_cpu_only."
    }
    if ((@($auto.ModelPacks | ForEach-Object { $_.capabilityId }) -join ",") -ne "ocr,plate-detector") { throw "The plates device record must name both bound Model Packs." }
    $explicitCpu = Resolve-MaviPlatesDevicePolicy -DevicePolicy cpu -ComponentBindingPath $platesBinding
    if ($explicitCpu.ResolvedDevicePolicy -ne "cpu" -or $explicitCpu.DeviceResolutionReason -ne "explicit_cpu") { throw "Plates CPU must resolve explicit_cpu." }
    Assert-Throws { Resolve-MaviPlatesDevicePolicy -DevicePolicy cuda -ComponentBindingPath $platesBinding } "plates_device_unsupported:plates_runtime_cpu_only" "Explicit plates CUDA"
    # A binding that declared a CUDA variant would still run on CPU (the adapters use the CPU provider only), and says so.
    $cudaDeclared = Get-Content -LiteralPath $platesBinding -Raw | ConvertFrom-Json
    $cudaDeclared.runtimePacks[0].variants | Add-Member -NotePropertyName "windows-x86_64-cuda" -NotePropertyValue ([pscustomobject]@{ runtimePackId = "mavi-runtime-v2-x" })
    $cudaDeclaredPath = Join-Path $tempRoot "plates-cuda-declared.json"
    $cudaDeclared | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $cudaDeclaredPath -Encoding UTF8
    if ((Resolve-MaviPlatesDevicePolicy -DevicePolicy auto -ComponentBindingPath $cudaDeclaredPath).DeviceResolutionReason -ne "plates_worker_cpu_only") { throw "A declared but unusable CUDA variant must be named as such." }
    Assert-Throws { Resolve-MaviPlatesDevicePolicy -DevicePolicy cuda -ComponentBindingPath $cudaDeclaredPath } "plates_device_unsupported" "Explicit plates CUDA with an unusable variant"
    $noRole = Join-Path $tempRoot "plates-no-role.json"
    '{"roles":[],"runtimePacks":[],"capabilityBindings":[]}' | Set-Content -LiteralPath $noRole -Encoding UTF8
    Assert-Throws { Resolve-MaviPlatesDevicePolicy -DevicePolicy auto -ComponentBindingPath $noRole } "plates_binding_invalid:no_plates_role" "A binding without the plates role"

    # --- Plates Model Pack licences: read from each pack's own notice, pinned and matching its manifest. ---
    $apache = Join-Path $tempRoot "LICENSE-apache"
    [IO.File]::WriteAllText($apache, "                                 Apache License`n                           Version 2.0, January 2004`n")
    $mit = Join-Path $tempRoot "LICENSE-mit"
    [IO.File]::WriteAllText($mit, "MIT License`n`nPermission is hereby granted, free of charge, to any person`n")
    $apacheSha = Get-MaviSha256 -Path $apache
    $mitSha = Get-MaviSha256 -Path $mit
    if ((Get-MaviPocNoticeLicence -Path $apache -ExpectedSha256 $apacheSha -DeclaredSpdxId "Apache-2.0").SpdxId -ne "Apache-2.0") { throw "An Apache-2.0 notice was not read as Apache-2.0." }
    if ((Get-MaviPocNoticeLicence -Path $mit -ExpectedSha256 $mitSha -DeclaredSpdxId "MIT").SpdxId -ne "MIT") { throw "An MIT notice was not read as MIT." }
    Assert-Throws { Get-MaviPocNoticeLicence -Path $mit -ExpectedSha256 $mitSha -DeclaredSpdxId "Apache-2.0" } "states MIT, but its manifest declares Apache-2.0" "A notice contradicting its manifest"
    Assert-Throws { Get-MaviPocNoticeLicence -Path $mit -ExpectedSha256 $apacheSha -DeclaredSpdxId "MIT" } "not the one its manifest pins" "A notice other than the pinned one"
    $unknown = Join-Path $tempRoot "LICENSE-gpl"
    [IO.File]::WriteAllText($unknown, "GNU GENERAL PUBLIC LICENSE`nVersion 3`n")
    Assert-Throws { Get-MaviPocNoticeLicence -Path $unknown -ExpectedSha256 (Get-MaviSha256 -Path $unknown) -DeclaredSpdxId "GPL-3.0" } "states no licence this installer recognises" "An unrecognised notice"
    # The committed plates manifests pin the notices the packs ship: one Apache-2.0 detector, one MIT recogniser.
    $platesManifests = @("plates-pd5-ppocrv5-mobile-det-dev-v1", "plates-oc1-fast-plate-ocr-cct-s-v2-dev-v1") | ForEach-Object { Get-Content -LiteralPath (Join-Path $repoRoot "models\manifests\$_.json") -Raw | ConvertFrom-Json }
    if ((@($platesManifests | ForEach-Object { $_.licence.spdxId }) -join ",") -ne "Apache-2.0,MIT") { throw "The plates manifests must declare Apache-2.0 (PD5) and MIT (OC1-S)." }

    # --- Plates launcher, start and stop: device policy, record, the worker started and stopped with the stack. ---
    $platesLauncher = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviPlatesPilotWorker.ps1") -Raw
    foreach ($fragment in @('[ValidateSet("cpu", "cuda", "auto")][string]$DevicePolicy', 'Resolve-MaviPlatesDevicePolicy', '[string]$DeviceReportPath', '[switch]$VerifyOnly', '$env:MAVI_VERIFY_ONLY', 'role = "plates"')) {
        if (-not $platesLauncher.Contains($fragment)) { throw "Start-MaviPlatesPilotWorker.ps1 lost '$fragment'." }
    }
    if ($platesLauncher.IndexOf("Resolve-MaviPlatesDevicePolicy -DevicePolicy") -gt $platesLauncher.IndexOf("& `$Python -m mavi_vision.plates.main")) { throw "The plates device must be resolved before the worker starts." }
    $startScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviPoc.ps1") -Raw
    $stopScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -Raw
    foreach ($fragment in @('"plates-worker"', 'Start-MaviPlatesPilotWorker.ps1', '$layout.PlatesDeviceResolutionPath')) {
        if (-not $startScript.Contains($fragment)) { throw "Start-MaviPoc.ps1 does not start the plates worker ('$fragment')." }
    }
    foreach ($fragment in @('"plates-worker" = "Start-MaviPlatesPilotWorker.ps1"', 'plates-device-resolution.json')) {
        if (-not $stopScript.Contains($fragment)) { throw "Stop-MaviPoc.ps1 does not stop the plates worker ('$fragment')." }
    }

    # --- Faces role (PoC S6, ADR-022, C5A.3/C5A.5): bound, opt-in per camera, on the embeddings environment, both
    #     component licences read from their own LICENSE files, the worker started and stopped with the stack. ---
    if ($config.Faces.Enabled -ne $true -or -not $config.Faces.ModelManifestPath.EndsWith("models\manifests\faces-yunet-adaface-ir50-dev-v1.json") -or
        -not $config.Faces.PipelineProfilePath.EndsWith("src\vision\config\faces\development-faces-adaface-v1.json")) {
        throw "The machine configuration must bind the faces role to the overlay's committed manifest and profile."
    }
    if (@($config.Faces.Keys) -join "," -ne "Enabled,ModelManifestPath,PipelineProfilePath") { throw "The Faces section carries a key the installer does not own." }
    if (-not $layout.FacesModelRoot.EndsWith("faces\models") -or -not $layout.FacesModelRoot.StartsWith($layout.InstallRoot)) { throw "The face Model Pack store must live under the install root." }
    $facesManifestPath = Join-Path $repoRoot "models\manifests\faces-yunet-adaface-ir50-dev-v1.json"
    $facesManifest = Get-Content -LiteralPath $facesManifestPath -Raw | ConvertFrom-Json
    if ($facesManifest.licence.spdxId -ne "MIT" -or $facesManifest.verificationStatus -ne "unverified" -or (@($facesManifest.capabilityIds) -join ",") -ne "embedding") { throw "The face manifest must be an unverified MIT embedding pack." }
    # A staged face pack built from fixture notices: both licences are read, and a detector notice stating another
    # licence refuses the pack.
    $facesRoot = Join-Path $tempRoot "faces-models"
    $facesPackDir = Join-Path $facesRoot "faces-yunet-adaface-ir50-dev-v1"
    New-Item -ItemType Directory -Path $facesPackDir -Force | Out-Null
    Copy-Item -LiteralPath $mit -Destination (Join-Path $facesPackDir "LICENSE")
    Copy-Item -LiteralPath $mit -Destination (Join-Path $facesPackDir "LICENSE-yunet")
    $fixtureManifest = Get-Content -LiteralPath $facesManifestPath -Raw | ConvertFrom-Json
    foreach ($artifact in @($fixtureManifest.artifacts)) { if ([string]$artifact.artifactRole -like "licence-notice*") { $artifact.sha256 = $mitSha } }
    $fixtureManifestPath = Join-Path $tempRoot "faces-manifest.json"
    $fixtureManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $fixtureManifestPath -Encoding UTF8
    $facesEntry = Get-MaviPocFacesPack -ManifestPath $fixtureManifestPath -ModelRoot $facesRoot
    if ($facesEntry.role -ne "faces" -or $facesEntry.capabilityId -ne "embedding" -or $facesEntry.verificationStatus -ne "unverified" -or
        $facesEntry.licence -notmatch "^embedder MIT, read from its LICENSE .*; detector MIT, read from its LICENSE-yunet" -or $facesEntry.licence -notmatch "non-commercial research" -or
        $facesEntry.note -notmatch "Development-only" -or $facesEntry.note -notmatch "candidates, never identification") {
        throw "The face pack disclosure must read both licences and state the research-only, candidate-only scope: $($facesEntry.licence) / $($facesEntry.note)"
    }
    Copy-Item -LiteralPath $apache -Destination (Join-Path $facesPackDir "LICENSE-yunet") -Force
    foreach ($artifact in @($fixtureManifest.artifacts)) { if ([string]$artifact.artifactRole -eq "licence-notice-detector") { $artifact.sha256 = $apacheSha } }
    $fixtureManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $fixtureManifestPath -Encoding UTF8
    Assert-Throws { Get-MaviPocFacesPack -ManifestPath $fixtureManifestPath -ModelRoot $facesRoot } "states Apache-2.0, but its manifest declares MIT" "A detector notice contradicting the face manifest"
    $facesLauncher = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviFacesWorker.ps1") -Raw
    foreach ($fragment in @('$env:MAVI_FACE_MANIFEST_PATH', '$env:MAVI_FACE_PIPELINE_PROFILE_PATH', '$env:MAVI_MODEL_ROOT', '$env:MAVI_PRODUCTION_MODE = "false"', '-m mavi_vision.faces.main', 'faces-yunet-adaface-ir50-dev-v1.json', 'development-faces-adaface-v1.json')) {
        if (-not $facesLauncher.Contains($fragment)) { throw "Start-MaviFacesWorker.ps1 lost '$fragment'." }
    }
    foreach ($fragment in @('"faces-worker"', 'Start-MaviFacesWorker.ps1', '$state.facesBound', '$layout.FacesModelRoot', '$layout.EmbeddingsEnvironmentRoot "Scripts\python.exe"')) {
        if (-not $startScript.Contains($fragment)) { throw "Start-MaviPoc.ps1 does not start the faces worker ('$fragment')." }
    }
    # Stop-MaviPoc stops the faces worker first: Uninstall-MAVI-PoC drops the database only after it.
    if (-not $stopScript.Contains('"faces-worker" = "Start-MaviFacesWorker.ps1"') -or -not $stopScript.Contains('foreach ($name in @("language-runtime", "faces-worker", "attributes-worker", "embeddings-worker"')) { throw "Stop-MaviPoc.ps1 does not stop the faces worker first (after the language role, which holds no data)." }
    foreach ($fragment in @('tools\vision\faces_packs.py") stage', 'facesBound = $true', 'Get-MaviPocFacesPack -ManifestPath', '"faces-payloads"')) {
        if (-not $installText.Contains($fragment)) { throw "Install-MAVI-PoC.ps1 does not install and disclose the face pack ('$fragment')." }
    }
    $bundleText = Get-Content -LiteralPath (Join-Path $PSScriptRoot "New-MaviPocSetupBundle.ps1") -Raw
    if (-not $bundleText.Contains('(Join-Path $PlatesCache "faces-payloads") -Target (Join-Path $destination "faces\faces-payloads")')) { throw "The PoC bundle must carry the face pack payloads." }
    # --- Language role (PoC S10, ADR-026, C9.1): staged, one pack bound by GPU memory, verified before every start,
    # loopback only; CUDA fails closed. ---
    $payloadsPath = Join-Path $repoRoot "tools\language\language-payloads-v1.json"
    $pick = Select-MaviPocLanguagePack -NvidiaSmiLines @("0, NVIDIA GeForce RTX 4090, 8.9, 24564 MiB") -PayloadsPath $payloadsPath
    if ($pick.PackDirectory -ne "language-qwen2.5-7b-instruct-q4-k-m-dev-v1" -or $pick.Reason -ne "gpu_memory_24564_mib_holds_7b") { throw "Auto must bind the 7B pack on a 24 GiB GPU: $($pick.PackDirectory) $($pick.Reason)" }
    $pick = Select-MaviPocLanguagePack -NvidiaSmiLines @("0, NVIDIA GeForce GTX 1650 Ti, 7.5, 4096 MiB") -PayloadsPath $payloadsPath
    if ($pick.PackDirectory -ne "language-qwen2.5-1.5b-instruct-q8-0-dev-v1") { throw "Auto must bind the 1.5B pack on a 4 GiB GPU." }
    $pick = Select-MaviPocLanguagePack -NvidiaSmiLines $null -PayloadsPath $payloadsPath
    if ($pick.PackDirectory -ne "language-qwen2.5-1.5b-instruct-q8-0-dev-v1" -or $pick.Reason -ne "no_nvidia_gpu_1_5b") { throw "Auto must bind the 1.5B pack without a GPU." }
    $pick = Select-MaviPocLanguagePack -Choice "7B" -NvidiaSmiLines $null -PayloadsPath $payloadsPath
    if ($pick.PackDirectory -ne "language-qwen2.5-7b-instruct-q4-k-m-dev-v1" -or $pick.Reason -ne "operator_choice_7b") { throw "An explicit pack choice must be honoured and recorded." }
    $device = Resolve-MaviPocLanguageDevice -Policy auto -NvidiaSmiLines @("0, NVIDIA GeForce RTX 4090, 8.9, 24564 MiB")
    if ($device.Variant -ne "cuda" -or $device.Device -notmatch "sm_89, native") { throw "The 4090 must run the CUDA build natively." }
    $device = Resolve-MaviPocLanguageDevice -Policy auto -NvidiaSmiLines @("0, NVIDIA GeForce GTX 1650 Ti, 7.5, 4096 MiB")
    if ($device.Variant -ne "cuda" -or $device.Device -notmatch "sm_75, ptx-jit") { throw "The 1650 Ti must run the CUDA build through the PTX JIT." }
    $device = Resolve-MaviPocLanguageDevice -Policy auto -NvidiaSmiLines $null
    if ($device.Variant -ne "cpu" -or $device.Reason -ne "auto_nvidia_smi_absent") { throw "Auto without nvidia-smi must resolve CPU with the reason." }
    Assert-Throws { Resolve-MaviPocLanguageDevice -Policy cuda -NvidiaSmiLines $null } "refusing to fall back to CPU" "Explicit language CUDA without a GPU"
    # D-S10-7: prompt-prefix reuse only where the reverse-order check reproduced byte for byte (off for the 7B pack).
    foreach ($case in @(@("7B", $false), @("1.5B", $true))) {
        $bound = Select-MaviPocLanguagePack -Choice $case[0] -NvidiaSmiLines $null -PayloadsPath $payloadsPath
        if ($bound.CachePrompt -ne $case[1]) { throw "The $($case[0]) pack must bind CachePrompt=$($case[1]) (D-S10-7)." }
        $binding = [pscustomobject]@{ ModelPackId = "mavi-language-v1-x"; ModelId = "m"; Quantisation = "q"; RuntimeId = "r"; CachePrompt = $bound.CachePrompt }
        $boundConfig = New-MaviPocMachineConfig -Layout $layout -ConnectionString "Host=x" -CursorSigningKey ("k" * 44) -HttpPort 8090 -LanguagePack $binding -LanguagePort 62301
        if ($boundConfig.Language.CachePrompt -ne $case[1]) { throw "The machine configuration must carry Language:CachePrompt=$($case[1]) for the $($case[0]) pack." }
    }
    $languageConfig = New-MaviPocMachineConfig -Layout $layout -ConnectionString "Host=x" -CursorSigningKey ("k" * 44) -HttpPort 8090 -LanguagePack ([pscustomobject]@{ ModelPackId = "mavi-language-v1-x"; ModelId = "m"; Quantisation = "Q8_0"; RuntimeId = "r"; CachePrompt = $true }) -LanguagePort 62301
    if ($languageConfig.Language.Enabled -ne $true -or $languageConfig.Language.Port -ne 62301 -or $languageConfig.Language.DeviceReportPath -ne $layout.LanguageDeviceResolutionPath -or
        $languageConfig.Deployment.RoleDeviceResolutionPaths.language -ne $layout.LanguageDeviceResolutionPath) { throw "The machine configuration must bind the language role on loopback with its device record." }
    $noLanguage = New-MaviPocMachineConfig -Layout $layout -ConnectionString "Host=x" -CursorSigningKey ("k" * 44) -HttpPort 8090
    if ($noLanguage.Contains("Language")) { throw "Without a bound pack the machine configuration must carry no Language section." }
    if (-not $layout.LanguageRuntimeRoot.StartsWith($layout.InstallRoot) -or -not $layout.LanguageCudaCachePath.StartsWith($layout.DataRoot)) { throw "The language runtime lives under the install root and its JIT cache under the data root." }
    $languageLauncher = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviLanguageRuntime.ps1") -Raw
    foreach ($fragment in @('schemaVersion = "mavi-device-resolution-v1"', 'role = "language"', 'Write-MaviJson -Value $report -Path $DeviceReportPath', 'language_packs.py") verify', 'Resolve-MaviPocLanguageDevice', '"--host", "127.0.0.1"', '"--parallel", "1"', '$env:CUDA_CACHE_PATH', '"--no-webui"')) {
        if (-not $languageLauncher.Contains($fragment)) { throw "Start-MaviLanguageRuntime.ps1 lost '$fragment'." }
    }
    if ($languageLauncher.IndexOf('language_packs.py") verify') -gt $languageLauncher.IndexOf('& $server @arguments')) { throw "The packs must be verified before llama-server starts." }
    # Codex P1 (round 1): no CUDA binary runs, not even the device probe, before the CUDA variant is verified; after an
    # Auto fallback the CPU variant is verified before it starts.
    $probeAt = $languageLauncher.IndexOf('--list-devices')
    $cudaVerifyAt = $languageLauncher.IndexOf('Invoke-MaviLanguagePackVerification "cuda"')
    if ($cudaVerifyAt -lt 0 -or $probeAt -lt 0 -or $cudaVerifyAt -gt $probeAt) { throw "Start-MaviLanguageRuntime.ps1 must verify the CUDA variant before probing it." }
    if (-not $languageLauncher.Contains('if ($device.Variant -ne "cuda") { $identity = Invoke-MaviLanguagePackVerification $device.Variant }')) { throw "Start-MaviLanguageRuntime.ps1 must verify the CPU variant it falls back to." }
    if ($languageLauncher.IndexOf('throw "The Language Runtime Pack ($Variant) or Model Pack failed verification') -lt 0) { throw "A failed verification must stop the language role." }
    foreach ($fragment in @('"language-runtime"', 'Start-MaviLanguageRuntime.ps1', '$state.languageBound', '$layout.LanguageDeviceResolutionPath')) {
        if (-not $startScript.Contains($fragment)) { throw "Start-MaviPoc.ps1 does not start the language role ('$fragment')." }
    }
    foreach ($fragment in @('"language-runtime" = "Start-MaviLanguageRuntime.ps1"', 'language-device-resolution.json')) {
        if (-not $stopScript.Contains($fragment)) { throw "Stop-MaviPoc.ps1 does not stop the language role ('$fragment')." }
    }
    foreach ($fragment in @('tools\language\language_packs.py") stage', 'languageBound = $true', 'Get-MaviPocLanguagePacks', 'Select-MaviPocLanguagePack')) {
        if (-not $installText.Contains($fragment)) { throw "Install-MAVI-PoC.ps1 does not install and disclose the language packs ('$fragment')." }
    }
    if (-not $bundleText.Contains('(Join-Path $PlatesCache "language-payloads") -Target (Join-Path $destination "language\language-payloads")')) { throw "The PoC bundle must carry the language payloads." }
    # --- PoC S5 attributes worker: zero-shot on the embeddings runtime and pack, started and stopped with the stack. ---
    $attributesLauncher = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviAttributesWorker.ps1") -Raw
    foreach ($fragment in @('$env:MAVI_PRODUCTION_MODE = "false"', 'development-attributes-siglip2-binding-v1.json', 'development-attributes-siglip2-zero-shot-v1.json', 'embeddings-siglip2-base-p16-224-dev-v1.json', 'mavi_vision.attributes.main')) {
        if (-not $attributesLauncher.Contains($fragment)) { throw "Start-MaviAttributesWorker.ps1 lost '$fragment'." }
    }
    foreach ($fragment in @('"attributes-worker"', 'Start-MaviAttributesWorker.ps1')) {
        if (-not $startScript.Contains($fragment)) { throw "Start-MaviPoc.ps1 does not start the attributes worker ('$fragment')." }
    }
    if (-not $stopScript.Contains('"attributes-worker" = "Start-MaviAttributesWorker.ps1"')) { throw "Stop-MaviPoc.ps1 does not stop the attributes worker." }
    $pocModule = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Raw
    if (-not $pocModule.Contains('VisualAttributes = [ordered]@{') -or -not $pocModule.Contains('development-attributes-siglip2-zero-shot-v1.json')) {
        throw "The PoC platform configuration does not bind the zero-shot attributes release."
    }

    # --- Demo cameras: the S2 demo-corpus manifest (copied byte-identical), unique codes. ---
    $cameras = Read-MaviPocDemoCameras -Path (Join-Path $repoRoot "config\poc\demo-cameras-v1.json")
    $expectedCodes = @(1..13 | ForEach-Object { "POC-S2-{0:D2}" -f $_ })
    if ((@($cameras.Code) -join ",") -ne ($expectedCodes -join ",") -or @($cameras | Where-Object { $_.TimeZoneId -ne "Asia/Kolkata" }).Count -gt 0) {
        throw "The seed must be the S2 demo-corpus manifest: POC-S2-01..13, Asia/Kolkata."
    }
    $corpusCameras = Join-Path $repoRoot "tools\poc\demo-corpus\demo-cameras-v1.json"
    if ((Test-Path -LiteralPath $corpusCameras) -and ([IO.File]::ReadAllText($corpusCameras).Replace("`r", "")) -cne ([IO.File]::ReadAllText((Join-Path $repoRoot "config\poc\demo-cameras-v1.json")).Replace("`r", ""))) {
        throw "config\poc\demo-cameras-v1.json must be byte-identical (line endings aside) to tools\poc\demo-corpus\demo-cameras-v1.json."
    }
    $smokeScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Test-MaviPocSmoke.ps1") -Raw
    if ($smokeScript -notmatch '\[string\]\$CameraCode = "([^"]+)"' -or @($cameras.Code) -notcontains $Matches[1]) {
        throw "The smoke test's default camera must be one the installer seeds."
    }
    $duplicate = Join-Path $tempRoot "cameras.json"
    '{"schemaVersion":"mavi-poc-demo-cameras-v1","cameras":[{"code":"A","name":"a","timeZoneId":"UTC"},{"code":"a","name":"b","timeZoneId":"UTC"}]}' | Set-Content -LiteralPath $duplicate -Encoding UTF8
    Assert-Throws { Read-MaviPocDemoCameras -Path $duplicate } "Duplicate" "Duplicate camera codes"

    # --- Application overlay revision: verified manifest, tamper refused, no git needed. ---
    $overlay = Join-Path $tempRoot "overlay"
    New-Item -ItemType Directory -Path (Join-Path $overlay "src\vision") -Force | Out-Null
    $file = Join-Path $overlay "src\vision\a.py"
    [IO.File]::WriteAllText($file, "print(1)`n")
    $overlayManifest = [ordered]@{ schemaVersion = "mavi-application-overlay-v1"; revision = ("c" * 40); artifacts = @([ordered]@{ relativePath = "src/vision/a.py"; sha256 = (Get-MaviSha256 -Path $file); sizeBytes = (Get-Item $file).Length }) }
    Write-MaviJson -Value $overlayManifest -Path (Join-Path $overlay "mavi-application-overlay.json")
    $resolved = Resolve-MaviApplicationRevision -Root $overlay
    if ($resolved.Revision -ne ("c" * 40) -or $resolved.Source -ne "application-overlay") { throw "The overlay revision was not taken from its manifest." }
    [IO.File]::WriteAllText($file, "print(2)`n")
    Assert-Throws { Resolve-MaviApplicationRevision -Root $overlay } "SHA-256|size" "A modified overlay file"
    [IO.File]::WriteAllText($file, "print(1)`n")
    $overlayManifest.revision = "main"
    Write-MaviJson -Value $overlayManifest -Path (Join-Path $overlay "mavi-application-overlay.json")
    Assert-Throws { Resolve-MaviApplicationRevision -Root $overlay } "valid revision" "An overlay without an exact revision"

    # --- Launchers: overlay instead of git; explicit roots; device record after the checks. ---
    $launcher = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviVisionWorker.ps1") -Raw
    foreach ($fragment in @('launch_application_overlay_invalid', '[string]$RuntimeCpuRoot', '[string]$RuntimeCudaRoot', '[string]$ModelRoot', '[string]$DeviceReportPath', 'if ($RuntimeCpuRoot) { $RuntimeCpuRoot } else', 'if ($ModelRoot) { $ModelRoot } else')) {
        if (-not $launcher.Contains($fragment)) { throw "Start-MaviVisionWorker.ps1 lost '$fragment'." }
    }
    # The record is written at the -VerifyOnly boundary and, for a launch, only after the
    # last launch check (the source-overlay probe), immediately before the worker starts.
    $calls = [regex]::Matches($launcher, '(?m)^\s*Write-MaviDeviceReport\s*$')
    if ($calls.Count -ne 2) { throw "Start-MaviVisionWorker.ps1 must write the device record exactly twice (verify-only and launch); found $($calls.Count)." }
    $compatibility = $launcher.IndexOf("Assert-MaviVisionWorkerComponentCompatibility")
    $verifyOnly = $launcher.IndexOf("if (`$VerifyOnly) {")
    $foreign = $launcher.IndexOf("launch_vision_source_overlay_foreign")
    $workerStart = $launcher.IndexOf("& `$python -m mavi_vision.worker.main")
    if (-not ($compatibility -lt $verifyOnly -and $verifyOnly -lt $calls[0].Index -and $foreign -lt $calls[1].Index -and $calls[1].Index -lt $workerStart)) {
        throw "The device record must follow every launch check and precede only the worker start."
    }
    $launchCodes = Get-Content -LiteralPath (Join-Path $repoRoot "src\vision\mavi_vision\runtime\launch_failures.py") -Raw
    foreach ($code in @("launch_application_overlay_invalid", "launch_device_report_unwritable")) {
        if (-not $launchCodes.Contains("`"$code`"")) { throw "launch_failures.py does not declare $code." }
    }
    $plates = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Start-MaviPlatesPilotWorker.ps1") -Raw
    if ($plates -notmatch "Resolve-MaviApplicationRevision" -or $plates -match "& git ") { throw "The plates launcher must resolve its revision without requiring git." }

    # --- Installers write no Machine environment when told not to. ---
    $runtimeInstaller = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MaviVisionRuntime.ps1") -Raw
    $guards = ([regex]::Matches($runtimeInstaller, 'if\(-not\$NoMachineEnvironment\)\{\$variantEnv')).Count
    $writes = ([regex]::Matches($runtimeInstaller, 'SetEnvironmentVariable\(\$variantEnv')).Count
    if ($writes -ne 2 -or $guards -ne 2) { throw "Every Machine environment write of Install-MaviVisionRuntime.ps1 must be guarded by -NoMachineEnvironment ($guards of $writes)." }
    # The CPython installer's paths survive a root with spaces (%ProgramFiles%\MAVI\PoC):
    # Start-Process joins -ArgumentList into one command line, so each path carries quotes.
    if (-not $runtimeInstaller.Contains('(''"''+$installerLog+''"'')') -or -not $runtimeInstaller.Contains('(''"TargetDir=''+$pythonRoot+''"'')')) {
        throw "Install-MaviVisionRuntime.ps1 must quote the CPython installer's log path and TargetDir."
    }
    $install = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MAVI-PoC.ps1") -Raw
    if ($install -match "SetEnvironmentVariable") { throw "Install-MAVI-PoC must not write the Machine environment." }
    $packCalls = @($install -split "`n" | Where-Object { $_ -match [regex]::Escape("& `$install") -and $_ -match "-PackRoot|-BundleRoot" })
    if ($packCalls.Count -lt 3) { throw "Install-MAVI-PoC no longer calls the Runtime and Model Pack installers where this test expects them." }
    foreach ($line in $packCalls) {
        if ($line -notmatch "-NoMachineEnvironment") { throw "Install-MAVI-PoC calls a pack installer without -NoMachineEnvironment: $line" }
    }
    # Review fixes: the release metadata is administrator-only; a rerun stops a running
    # instance first; an explicit adoption on an unsupported GPU is refused; every
    # installed Runtime Pack must load its native code; the operator never inherits
    # elevated processes.
    if ($install -match '/T /C' -or $install -match '/reset') { throw "The installer must not change ACLs or owners recursively." }
    if ($install -notmatch 'Assert-MaviPocNoReparsePoint -Path \$releaseRoot -Recurse') { throw "The release directory must be refused when it is or contains a reparse point." }
    $protectInstall = $install.IndexOf('Protect-MaviPocRoot -Path $layout.InstallRoot')
    $protectData = $install.IndexOf('Protect-MaviPocRoot -Path $layout.DataRoot')
    if ($protectInstall -lt 0 -or $protectData -lt 0 -or $protectData -gt $install.IndexOf('Start-Transcript') -or $protectData -gt $install.IndexOf('Install-MaviPostgreSqlInstance')) {
        throw "Both roots must be secured before anything is created in them."
    }
    $junctionRoot = Join-Path $tempRoot "junction"
    New-Item -ItemType Directory -Path (Join-Path $junctionRoot "release"), (Join-Path $junctionRoot "target") -Force | Out-Null
    & cmd.exe /c mklink /J (Join-Path $junctionRoot "release\link") (Join-Path $junctionRoot "target") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "mklink /J failed ($LASTEXITCODE); the junction refusal cannot be tested." }
    Assert-Throws { Assert-MaviPocNoReparsePoint -Path (Join-Path $junctionRoot "release") -Recurse } "junction or symbolic link" "A release directory containing a junction"
    Assert-Throws { Assert-MaviPocNoReparsePoint -Path (Join-Path $junctionRoot "release\link") } "junction or symbolic link" "A directory that is a junction"
    Assert-MaviPocNoReparsePoint -Path (Join-Path $junctionRoot "target") -Recurse
    & cmd.exe /c rmdir (Join-Path $junctionRoot "release\link") | Out-Null
    if ($install -notmatch 'Set-MaviPrivateDirectoryAcl -Path \$releaseRoot -ApplicationIdentity "\*S-1-5-11" -ApplicationRights "R"' -or $install -notmatch '/setowner "\*S-1-5-32-544"') { throw "The release metadata directory must be administrator-owned and administrator-writable only." }
    $modifyRoots = @($install -split "`n" | Where-Object { $_ -match 'foreach \(\$root in @\(' })
    if ($modifyRoots.Count -ne 1 -or $modifyRoots[0] -match 'ReleaseMetadataPath') { throw "The release metadata directory must not be among the operator-writable roots." }
    if ($install.IndexOf('Stop-MaviPoc.ps1') -lt 0 -or $install.IndexOf('Stop-MaviPoc.ps1') -gt $install.IndexOf('"robocopy.exe"')) { throw "Install-MAVI-PoC must stop a running instance before replacing its files." }
    if ($install -notmatch 'AdoptCudaRuntimeRoot -and -not \$gpu\.Compatible') { throw "An explicit -AdoptCudaRuntimeRoot must not be dropped silently." }
    if (([regex]::Matches($install, 'Assert-MaviPocRuntimeLoads -RuntimeRoot')).Count -ne 3) { throw "Every Runtime Pack the installer installs or adopts must pass the native load check." }
    if ($install -match 'LeaveRunning') { throw "The installer must not leave elevated processes running." }
    if ($layout.DeviceResolutionPath -notlike "$($layout.RunRoot)*") { throw "The operator-written device record belongs under run\." }
    $stop = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -Raw
    if ($stop -notmatch 'device-resolution\.json' -or $stop -notmatch 'Get-MaviPocRecordedProcess' -or $stop -notmatch '\$LASTEXITCODE') { throw "Stop-MaviPoc must verify the process, check taskkill and remove the device record." }

    # --- Process records: a stale record (another process, or one gone) is not MAVI's. ---
    $records = Join-Path $tempRoot "run"
    $self = Get-Process -Id $PID
    Write-MaviPocProcessRecord -Path (Join-Path $records "self.pid") -Process $self
    if ((Get-MaviPocRecordedProcess -Path (Join-Path $records "self.pid")).Id -ne $PID) { throw "A live recorded process was not recognised." }
    $stale = [ordered]@{ schemaVersion = "mavi-poc-process-v1"; processId = $PID; imageName = $self.ProcessName; startTimeUtc = $self.StartTime.ToUniversalTime().AddHours(-1).ToString("O") }
    [IO.File]::WriteAllText((Join-Path $records "stale.pid"), ($stale | ConvertTo-Json -Compress))
    if ($null -ne (Get-MaviPocRecordedProcess -Path (Join-Path $records "stale.pid"))) { throw "A record whose start time differs must not match the reused process id." }
    if (Test-Path -LiteralPath (Join-Path $records "stale.pid")) { throw "A stale process record must be removed." }
    [IO.File]::WriteAllText((Join-Path $records "legacy.pid"), "$PID")
    if ($null -ne (Get-MaviPocRecordedProcess -Path (Join-Path $records "legacy.pid"))) { throw "A bare process id is not a process record." }

    if ($null -ne (Get-MaviPocRecordedProcess -Path (Join-Path $records "self2.pid") -ExpectedImageName "Mavi.Api")) { throw "A missing record must not match." }
    Write-MaviPocProcessRecord -Path (Join-Path $records "self3.pid") -Process $self
    if ($null -ne (Get-MaviPocRecordedProcess -Path (Join-Path $records "self3.pid") -ExpectedImageName "Mavi.Api")) { throw "A record for another image must not be acted on." }

    # --- Stop: stops a recorded worker, removes its record and the device record, and
    #     leaves alone a process recorded under the wrong image. ---
    $stopData = Join-Path $tempRoot "stopdata"
    $stopRun = Join-Path $stopData "run"
    New-Item -ItemType Directory -Path $stopRun -Force | Out-Null
    # The dummy's command line carries the worker launcher's name, as Start's worker does.
    $dummy = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 120 # Start-MaviVisionWorker.ps1") -WindowStyle Hidden -PassThru
    $bystander = Start-Process -FilePath "powershell.exe" -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 120") -WindowStyle Hidden -PassThru
    try {
        Write-MaviPocProcessRecord -Path (Join-Path $stopRun "vision-worker.pid") -Process $dummy
        Write-MaviPocProcessRecord -Path (Join-Path $stopRun "api.pid") -Process $bystander
        '{"schemaVersion":"mavi-device-resolution-v1"}' | Set-Content -LiteralPath (Join-Path $stopRun "device-resolution.json") -Encoding ascii
        & (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -DataRoot $stopData | Out-Null
        Start-Sleep -Milliseconds 500
        if (Get-Process -Id $dummy.Id -ErrorAction SilentlyContinue) { throw "Stop-MaviPoc did not stop the recorded worker." }
        if (Test-Path -LiteralPath (Join-Path $stopRun "vision-worker.pid")) { throw "Stop-MaviPoc left the worker record." }
        if (Test-Path -LiteralPath (Join-Path $stopRun "device-resolution.json")) { throw "Stop-MaviPoc left the device record." }
        if (-not (Get-Process -Id $bystander.Id -ErrorAction SilentlyContinue)) { throw "Stop-MaviPoc stopped a process recorded under another image." }
        # Right image, right start time, but not the worker launcher: not MAVI's.
        Write-MaviPocProcessRecord -Path (Join-Path $stopRun "vision-worker.pid") -Process $bystander
        & (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -DataRoot $stopData | Out-Null
        if (-not (Get-Process -Id $bystander.Id -ErrorAction SilentlyContinue)) { throw "Stop-MaviPoc stopped a powershell process that is not the worker launcher." }
    }
    finally {
        foreach ($p in @($dummy, $bystander)) { if (Get-Process -Id $p.Id -ErrorAction SilentlyContinue) { Stop-Process -Id $p.Id -Force } }
    }

    # --- Visual C++ x64 runtime: shipped and installed before any Vision Runtime Pack. ---
    if (Test-MaviPocVcRuntimeSatisfied -Installed $null) { throw "An absent VC++ runtime must not satisfy the minimum." }
    $vc = { param($installed, $major, $minor, $bld) [pscustomobject]@{ Installed = $installed; Major = $major; Minor = $minor; Bld = $bld } }
    if (Test-MaviPocVcRuntimeSatisfied -Installed (& $vc 1 14 40 33810)) { throw "VC++ 14.40 must not satisfy the 14.44 minimum." }
    if (Test-MaviPocVcRuntimeSatisfied -Installed (& $vc 0 14 51 36247)) { throw "A runtime not marked installed must not satisfy the minimum." }
    if (-not (Test-MaviPocVcRuntimeSatisfied -Installed (& $vc 1 14 44 35211))) { throw "VC++ 14.44.35211 must satisfy the minimum." }
    if (-not (Test-MaviPocVcRuntimeSatisfied -Installed (& $vc 1 14 51 36247))) { throw "A newer VC++ runtime must satisfy the minimum." }
    $unsigned = Join-Path $tempRoot "vc_redist.x64.exe"
    [IO.File]::WriteAllText($unsigned, "not an installer")
    Assert-Throws { Assert-MaviPocVcRedistInstaller -Path $unsigned } "Microsoft-signed" "An unsigned redistributable"
    $vcInstall = $install.IndexOf("Install-MaviPocVcRuntime -InstallerPath")
    if ($vcInstall -lt 0 -or $vcInstall -gt $install.IndexOf("& `$installRuntime")) { throw "The VC++ runtime must be installed before any Vision Runtime Pack." }
    $builder = Get-Content -LiteralPath (Join-Path $PSScriptRoot "New-MaviPocSetupBundle.ps1") -Raw
    if ($builder -notmatch 'prerequisites\\vcredist\\win-x64\\vc_redist\.x64\.exe' -or $builder -notmatch 'Assert-MaviPocVcRedistInstaller') { throw "The bundle must carry the verified VC++ redistributable." }
    # The builder deletes only the work directory it created, never the caller's -WorkRoot.
    if ($builder -match 'Remove-Item -LiteralPath \$WorkRoot' -or $builder -notmatch '\$work = Join-Path \(\[IO\.Path\]::GetFullPath\(\$WorkRoot\)\) \("mavi-poc-bundle-work-"') { throw "The bundle builder must work in, and remove, only its own subdirectory of -WorkRoot." }
    # The composition comes from the packaged revision, never from the preparer's checkout.
    if ($builder -match 'Join-Path \$repoRoot "src\\vision\\config' -or $builder -match 'Join-Path \$repoRoot "config\\dependencies') { throw "The bundle builder must read the binding and catalogue from the exported revision." }
    if ($builder.IndexOf('archive --format=tar') -gt $builder.IndexOf('phase1-bindings-v2.json')) { throw "The revision must be exported before its binding is read." }

    # --- Layout roots carry no trailing separator (they are written into .cmd launchers). ---
    $trailing = Get-MaviPocLayout -InstallRoot ((Join-Path $pocRoot "Program") + "\") -DataRoot ((Join-Path $pocRoot "Data") + "\")
    if ($trailing.DataRoot.EndsWith("\") -or $trailing.InstallRoot.EndsWith("\")) { throw "Layout roots must not end with a separator." }
    $platesInstaller = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MaviPlatesPilotRuntime.ps1") -Raw
    if ($platesInstaller -notmatch 'if \(-not \$ReuseVerified -or -not \$state') { throw "The plates installer must reuse only an environment it installed for the same lock." }

    # --- Plan-only on a minimal bundle: discloses, changes nothing, explicit CUDA fails closed. ---
    $bundle = Join-Path $tempRoot "bundle"
    New-Item -ItemType Directory -Path (Join-Path $bundle "overlay\config\setup"), (Join-Path $bundle "overlay\config\vision") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\setup\mavi-setup-defaults.json") -Destination (Join-Path $bundle "overlay\config\setup\")
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\vision\windows-cuda-development-build-v1.json") -Destination (Join-Path $bundle "overlay\config\vision\")
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\vision\windows-cuda-development-build-v2.json") -Destination (Join-Path $bundle "overlay\config\vision\")
    '{"schemaVersion":"mavi-poc-setup-bundle-v1"}' | Set-Content -LiteralPath (Join-Path $bundle "mavi-poc-bundle.json") -Encoding UTF8
    $installRoot = Join-Path $tempRoot "install"
    $dataRoot = Join-Path $tempRoot "data"
    $installer = Join-Path $PSScriptRoot "Install-MAVI-PoC.ps1"
    $planJson = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -BundleRoot $bundle -InstallRoot $installRoot -DataRoot $dataRoot -PlanOnly 6>$null | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Plan-only failed: $planJson" }
    $plan = $planJson.Substring($planJson.IndexOf("{")) | ConvertFrom-Json
    if ($plan.profile -ne "poc-single-host" -or $plan.productionQualified -ne $false -or $plan.evidenceClass -ne "Development") { throw "The plan does not disclose the PoC profile." }
    if ($plan.postgresql.serviceName -ne "MAVI-PoC-PostgreSQL-18" -or $plan.postgresql.port -ne 55434) { throw "The PoC must own its own PostgreSQL service and port." }
    if ($plan.platform.url -ne "http://localhost:8090" -or $plan.plates.bound -ne $true -or $plan.plates.devicePolicy -ne "Auto") { throw "Plan defaults changed: $($plan.platform.url), plates bound $($plan.plates.bound), plates device $($plan.plates.devicePolicy)." }
    if ($plan.faces.bound -ne $true -or $plan.faces.optInPerCamera -ne $true -or $plan.faces.devicePolicy -ne "cpu" -or $plan.faces.environment -ne $plan.embeddings.environment) { throw "The plan must bind the faces role, opt-in per camera, on the embeddings environment." }    if (Test-Path -LiteralPath $installRoot) { throw "Plan-only created the install root." }
    if (Test-Path -LiteralPath $dataRoot) { throw "Plan-only created the data root." }
    # Windows PowerShell turns a native command's stderr into a terminating error under Stop.
    $ErrorActionPreference = "Continue"
    $cudaOutput = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -BundleRoot $bundle -InstallRoot $installRoot -DataRoot $dataRoot -DevicePolicy CUDA -PlanOnly 2>&1 | Out-String)
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -or $cudaOutput -notmatch "Device policy CUDA requested") { throw "Explicit CUDA without an installable CUDA pack must fail closed, also in plan-only." }
    $ErrorActionPreference = "Continue"
    $platesCudaOutput = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -BundleRoot $bundle -InstallRoot $installRoot -DataRoot $dataRoot -PlatesDevicePolicy CUDA -PlanOnly 2>&1 | Out-String)
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -or $platesCudaOutput -notmatch "Plates device policy CUDA requested") { throw "Explicit plates CUDA must fail closed, also in plan-only." }

    # --- Uninstall (PoC S6; ADR-022 section 5; C5A.5): only the recorded installation, fail closed. ---
    Assert-Throws { Assert-MaviPocRemovableRoot -Path "" -Name "data root" } "no path is recorded" "An empty root"
    Assert-Throws { Assert-MaviPocRemovableRoot -Path "relative\Data" -Name "data root" } "not an absolute local path" "A relative root"
    Assert-Throws { Assert-MaviPocRemovableRoot -Path "\\server\share\MAVI\PoC" -Name "data root" } "not an absolute local path" "A UNC root"
    Assert-Throws { Assert-MaviPocRemovableRoot -Path "C:\" -Name "data root" } "drive root or a top-level" "A drive root"
    Assert-Throws { Assert-MaviPocRemovableRoot -Path "C:\MAVI" -Name "data root" } "drive root or a top-level" "A top-level directory"
    Assert-Throws { Assert-MaviPocRemovableRoot -Path $env:ProgramData -Name "data root" } "system directory|top-level" "ProgramData itself"
    Assert-Throws { Assert-MaviPocRemovableRoot -Path (Split-Path $env:LOCALAPPDATA -Parent) -Name "data root" } "system directory" "An ancestor of a profile directory"
    $uninstallLinkTarget = Join-Path $tempRoot "uninstall-target"
    $uninstallLink = Join-Path $tempRoot "uninstall-link"
    New-Item -ItemType Directory -Path $uninstallLinkTarget -Force | Out-Null
    & cmd.exe /c mklink /J "$uninstallLink" "$uninstallLinkTarget" | Out-Null
    Assert-Throws { Assert-MaviPocRemovableRoot -Path (Join-Path $uninstallLink "Data") -Name "data root" } "junction or symbolic link" "A root under a junction"
    $uninstallInstall = Join-Path $tempRoot "uninstall\Program"
    $uninstallData = Join-Path $tempRoot "uninstall\Data"
    if ((Assert-MaviPocRemovableRoot -Path ($uninstallData + "\") -Name "data root") -ne $uninstallData) { throw "A removable root must be returned normalised." }

    $connection = ConvertFrom-MaviPocConnectionString -ConnectionString "Host=127.0.0.1;Port=55434;Database=mavi_poc;Username=mavi_poc;Password=secret"
    if ($connection.Database -ne "mavi_poc" -or $connection.Port -ne 55434 -or $connection.Username -ne "mavi_poc") { throw "The connection string was not read." }
    Assert-Throws { ConvertFrom-MaviPocConnectionString -ConnectionString "Host=127.0.0.1;Port=1;Username=x" } "has no database" "A connection string without a database"
    $uninstallState = [pscustomobject]@{ schemaVersion = "mavi-poc-installation-v1"; profile = "poc-single-host"; installRoot = $uninstallInstall; dataRoot = $uninstallData; postgresqlServiceName = "MAVI-PoC-PostgreSQL-18" }
    $uninstallLayout = Get-MaviPocLayout -InstallRoot $uninstallInstall -DataRoot $uninstallData
    $absent = New-MaviPocUninstallPlan -State $uninstallState -DataRoot $uninstallData -Connection $connection -Service $null
    if ($absent.database.action -ne "drop" -or $absent.database.name -ne "mavi_poc" -or -not $absent.database.dropRole -or -not $absent.stopMavi) { throw "The uninstall plan must stop MAVI and drop the database and its role." }
    if (@($absent.removeDirectories).Count -ne 2 -or $absent.removeDirectories[0] -ne $uninstallData -or $absent.removeDirectories[1] -ne $uninstallInstall) { throw "The uninstall plan must remove both recorded roots: $($absent.removeDirectories -join ', ')" }
    if ($absent.postgresqlService.action -ne "keep" -or $absent.postgresqlService.reason -ne "absent") { throw "An absent service is not removed." }
    $ownedService = [pscustomobject]@{ PathName = "`"$($uninstallLayout.PostgreSqlInstallRoot)\bin\pg_ctl.exe`" runservice -N `"MAVI-PoC-PostgreSQL-18`" -D `"$($uninstallLayout.PostgreSqlDataRoot)`" -w" }
    $owned = New-MaviPocUninstallPlan -State $uninstallState -DataRoot $uninstallData -Connection $connection -Service $ownedService
    if ($owned.postgresqlService.action -ne "remove" -or $owned.database.psql -ne (Join-Path $uninstallLayout.PostgreSqlInstallRoot "bin\psql.exe")) { throw "The installation's own PostgreSQL service must be removed." }
    $sharedService = [pscustomobject]@{ PathName = "`"C:\Program Files\MAVI\Development\PostgreSQL\18\bin\pg_ctl.exe`" runservice -N `"MAVI-Dev-PostgreSQL-18`" -D `"C:\ProgramData\MAVI\Development\PostgreSQL\18\data`" -w" }
    $shared = New-MaviPocUninstallPlan -State $uninstallState -DataRoot $uninstallData -Connection $connection -Service $sharedService
    if ($shared.postgresqlService.action -ne "keep" -or $shared.postgresqlService.owned -or $shared.database.psql -ne "C:\Program Files\MAVI\Development\PostgreSQL\18\bin\psql.exe") { throw "A shared PostgreSQL service is kept; only the database is dropped through its psql." }
    Assert-Throws { New-MaviPocUninstallPlan -State $uninstallState -DataRoot (Join-Path $tempRoot "elsewhere\Data") -Connection $connection -Service $null } "records data root" "A data root other than the recorded one"
    $overlapping = [pscustomobject]@{ schemaVersion = "mavi-poc-installation-v1"; profile = "poc-single-host"; installRoot = (Join-Path $uninstallData "Program"); dataRoot = $uninstallData; postgresqlServiceName = "x" }
    Assert-Throws { New-MaviPocUninstallPlan -State $overlapping -DataRoot $uninstallData -Connection $connection -Service $null } "overlap" "Nested roots"
    $notPoc = [pscustomobject]@{ schemaVersion = "mavi-installation-v1"; profile = "p1"; installRoot = $uninstallInstall; dataRoot = $uninstallData; postgresqlServiceName = "x" }
    Assert-Throws { New-MaviPocUninstallPlan -State $notPoc -DataRoot $uninstallData -Connection $connection -Service $null } "not a poc-single-host installation" "A non-PoC installation"
    Assert-Throws { New-MaviPocUninstallPlan -State $uninstallState -DataRoot $uninstallData -Connection ([pscustomobject]@{ Host = "db.example"; Port = 5432; Database = "mavi_poc"; Username = "u" }) -Service $null } "only the local instance" "A remote database"
    Assert-Throws { New-MaviPocUninstallPlan -State $uninstallState -DataRoot $uninstallData -Connection ([pscustomobject]@{ Host = "127.0.0.1"; Port = 5432; Database = "postgres"; Username = "u" }) -Service $null } "Refusing to drop database" "The postgres database"

    # The script: a missing installation state fails closed; plan-only and an unconfirmed run change nothing.
    $uninstaller = Join-Path $PSScriptRoot "Uninstall-MAVI-PoC.ps1"
    $ErrorActionPreference = "Continue"
    $missingOutput = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstaller -DataRoot (Join-Path $tempRoot "never-installed\Data") -PlanOnly 2>&1 | Out-String)
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -or $missingOutput -notmatch "No MAVI PoC installation is recorded") { throw "Uninstall without an installation state must fail closed: $missingOutput" }
    if (Test-Path -LiteralPath (Join-Path $tempRoot "never-installed")) { throw "A refused uninstall created a directory." }
    New-Item -ItemType Directory -Path (Join-Path $uninstallData "config"), (Join-Path $uninstallInstall "overlay") -Force | Out-Null
    $uninstallState.postgresqlServiceName = "MAVI-PoC-Contract-Test-NoSuchService"
    $uninstallState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $uninstallData "config\poc-installation.json") -Encoding UTF8
    @{ ConnectionStrings = @{ Mavi = "Host=127.0.0.1;Port=55434;Database=mavi_poc;Username=mavi_poc;Password=secret" } } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $uninstallData "config\appsettings.poc.machine.json") -Encoding UTF8
    $uninstallPlanJson = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstaller -DataRoot $uninstallData -PlanOnly 6>$null | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Uninstall plan-only failed: $uninstallPlanJson" }
    $uninstallPlan = $uninstallPlanJson.Substring($uninstallPlanJson.IndexOf("{")) | ConvertFrom-Json
    if ($uninstallPlan.database.name -ne "mavi_poc" -or $uninstallPlan.postgresqlService.action -ne "keep" -or @($uninstallPlan.removeDirectories).Count -ne 2) { throw "The uninstall plan is not the recorded installation's." }
    if ($uninstallPlanJson -match "secret") { throw "The uninstall plan must not print the database password." }
    $ErrorActionPreference = "Continue"
    $unconfirmed = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstaller -DataRoot $uninstallData 2>&1 | Out-String)
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -or $unconfirmed -notmatch "-RemoveAllData") { throw "An uninstall without -RemoveAllData must refuse." }
    if (-not (Test-Path -LiteralPath $uninstallData) -or -not (Test-Path -LiteralPath $uninstallInstall)) { throw "Plan-only or an unconfirmed uninstall removed a root." }
    $uninstallText = Get-Content -LiteralPath $uninstaller -Raw
    foreach ($required in @("Stop-MaviPoc.ps1", "drop database if exists", "with (force)", "sc.exe", "Assert-MaviPocNoReparsePoint -Path `$root -Recurse", "exit 1")) {
        if ($uninstallText.IndexOf($required, [StringComparison]::Ordinal) -lt 0) { throw "The uninstaller must keep '$required'." }
    }

    # The plan-only CUDA case above exits 1 by design; the caller's shell reports this
    # script's last exit code.
    $global:LASTEXITCODE = 0
    Write-Host "MAVI PoC setup contracts passed." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
