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
    $layout = Get-MaviPocLayout -InstallRoot "E:\PoC\Program" -DataRoot "E:\PoC\Data"
    foreach ($property in $layout.PSObject.Properties) {
        $value = [string]$property.Value
        if (-not ($value.StartsWith("E:\PoC\Program", [StringComparison]::OrdinalIgnoreCase) -or $value.StartsWith("E:\PoC\Data", [StringComparison]::OrdinalIgnoreCase))) {
            throw "Layout path '$($property.Name)' escapes the installation roots: $value"
        }
        if ($value -match "MAVI\\Development") { throw "Layout path '$($property.Name)' reuses the Development installation." }
    }
    Assert-Throws { Get-MaviPocLayout -InstallRoot "E:\PoC" -DataRoot "E:\PoC\" } "must be different" "Equal install and data roots"

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
    if (@($config.Deployment.Keys) -join "," -ne "Profile,ReleaseMetadataPath,DeviceResolutionPath") { throw "The Deployment section carries a key the platform does not define." }

    # --- Demo cameras: names only, unique codes. ---
    $cameras = Read-MaviPocDemoCameras -Path (Join-Path $repoRoot "config\poc\demo-cameras-v1.json")
    if ($cameras.Count -lt 5 -or @($cameras | Where-Object { $_.Name -notmatch "placeholder" }).Count -gt 0) { throw "The S1 seed is five or more placeholder cameras." }
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
    $compatibility = $launcher.IndexOf("Assert-MaviVisionWorkerComponentCompatibility")
    $report = $launcher.IndexOf('schemaVersion = "mavi-device-resolution-v1"')
    if ($compatibility -lt 0 -or $report -lt $compatibility) { throw "The device record must be written only after every launch check." }
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
    $install = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MAVI-PoC.ps1") -Raw
    if ($install -match "SetEnvironmentVariable") { throw "Install-MAVI-PoC must not write the Machine environment." }
    foreach ($call in @("Install-MaviVisionRuntime.ps1", "Install-MaviVisionModelPack.ps1")) {
        foreach ($line in @($install -split "`n" | Where-Object { $_ -match [regex]::Escape("& `$install") -and $_ -match "-PackRoot|-BundleRoot" })) {
            if ($line -notmatch "-NoMachineEnvironment") { throw "Install-MAVI-PoC calls a pack installer without -NoMachineEnvironment: $line" }
        }
    }
    $platesInstaller = Get-Content -LiteralPath (Join-Path $PSScriptRoot "Install-MaviPlatesPilotRuntime.ps1") -Raw
    if ($platesInstaller -notmatch 'if \(-not \$ReuseVerified -or -not \$state') { throw "The plates installer must reuse only an environment it installed for the same lock." }

    # --- Plan-only on a minimal bundle: discloses, changes nothing, explicit CUDA fails closed. ---
    $bundle = Join-Path $tempRoot "bundle"
    New-Item -ItemType Directory -Path (Join-Path $bundle "overlay\config\setup"), (Join-Path $bundle "overlay\config\vision") -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\setup\mavi-setup-defaults.json") -Destination (Join-Path $bundle "overlay\config\setup\")
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\vision\windows-cuda-development-build-v1.json") -Destination (Join-Path $bundle "overlay\config\vision\")
    '{"schemaVersion":"mavi-poc-setup-bundle-v1"}' | Set-Content -LiteralPath (Join-Path $bundle "mavi-poc-bundle.json") -Encoding UTF8
    $installRoot = Join-Path $tempRoot "install"
    $dataRoot = Join-Path $tempRoot "data"
    $installer = Join-Path $PSScriptRoot "Install-MAVI-PoC.ps1"
    $planJson = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -BundleRoot $bundle -InstallRoot $installRoot -DataRoot $dataRoot -PlanOnly 6>$null | Out-String)
    if ($LASTEXITCODE -ne 0) { throw "Plan-only failed: $planJson" }
    $plan = $planJson.Substring($planJson.IndexOf("{")) | ConvertFrom-Json
    if ($plan.profile -ne "poc-single-host" -or $plan.productionQualified -ne $false -or $plan.evidenceClass -ne "Development") { throw "The plan does not disclose the PoC profile." }
    if ($plan.postgresql.serviceName -ne "MAVI-PoC-PostgreSQL-18" -or $plan.postgresql.port -ne 55434) { throw "The PoC must own its own PostgreSQL service and port." }
    if ($plan.platform.url -ne "http://127.0.0.1:8090" -or $plan.plates.bound -ne $false) { throw "Plan defaults changed: $($plan.platform.url), plates bound $($plan.plates.bound)." }
    if (Test-Path -LiteralPath $installRoot) { throw "Plan-only created the install root." }
    if (Test-Path -LiteralPath $dataRoot) { throw "Plan-only created the data root." }
    # Windows PowerShell turns a native command's stderr into a terminating error under Stop.
    $ErrorActionPreference = "Continue"
    $cudaOutput = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -BundleRoot $bundle -InstallRoot $installRoot -DataRoot $dataRoot -DevicePolicy CUDA -PlanOnly 2>&1 | Out-String)
    $ErrorActionPreference = "Stop"
    if ($LASTEXITCODE -eq 0 -or $cudaOutput -notmatch "Device policy CUDA requested") { throw "Explicit CUDA without an installable CUDA pack must fail closed, also in plan-only." }

    Write-Host "MAVI PoC setup contracts passed." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
