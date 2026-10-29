[CmdletBinding()]
param(
    # The PoC setup bundle (MAVI-PoC-Setup\, mavi-poc-bundle.json at its root). Defaults to
    # the bundle this script was launched from (<bundle>\overlay\tools\setup\).
    [string]$BundleRoot,
    [string]$InstallRoot = (Join-Path $env:ProgramFiles "MAVI\PoC"),
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC"),
    [int]$HttpPort = 0,
    # ADR-008, unchanged: Auto prefers an installed, intact, bound CUDA Runtime Pack whose
    # GPU answers, otherwise CPU with the reason recorded; CUDA fails closed; CPU never
    # uses the GPU. Recorded for Start-MAVI-PoC.
    [ValidateSet("Auto", "CUDA", "CPU")][string]$DevicePolicy = "Auto",
    # An already-installed Windows CUDA Runtime Pack to use instead of one from the bundle
    # (the bundle carries none until S1b). It must pass the launcher's integrity preflight;
    # it is referenced, never copied or modified.
    [string]$AdoptCudaRuntimeRoot,
    # Resolve and print the plan; change nothing.
    [switch]$PlanOnly
)

# MAVI poc-single-host installer (PoC S1; ADR-020). Not a Production installer: the
# installation it produces is a proof of concept, Development evidence class, not
# Production-qualified, and says so here, in its release metadata and in the UI.
# Offline: every byte comes from the bundle; nothing is downloaded. Idempotent: a rerun
# verifies and repairs what an earlier run installed.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Windows.psm1") -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Integrity.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force

Assert-MaviWindows
if (-not $PlanOnly) { Assert-MaviAdministrator }

function Write-MaviPocDisclosure {
    Write-Host ""
    Write-Host "  $(Get-MaviPocDisclosureStatement)" -ForegroundColor Yellow
    Write-Host "  This installer never produces a P1, P2 or P3 Production installation (ADR-020 section 4)." -ForegroundColor Yellow
    Write-Host ""
}

if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
    $BundleRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\.."))
}
$BundleRoot = [IO.Path]::GetFullPath($BundleRoot.Trim().Trim('"'))
$bundleManifestPath = Join-Path $BundleRoot "mavi-poc-bundle.json"
if (-not (Test-Path -LiteralPath $bundleManifestPath -PathType Leaf)) {
    throw "Not a MAVI PoC setup bundle: '$bundleManifestPath' is missing. Build one with tools\setup\New-MaviPocSetupBundle.ps1."
}

$layout = Get-MaviPocLayout -InstallRoot $InstallRoot -DataRoot $DataRoot
$bundleOverlay = Join-Path $BundleRoot "overlay"
$defaults = Read-MaviJson -Path (Join-Path $bundleOverlay "config\setup\mavi-setup-defaults.json")
if ([string]$defaults.schemaVersion -ne "mavi-setup-defaults-v1" -or -not $defaults.PSObject.Properties["poc"]) {
    throw "The bundle's setup defaults have no poc-single-host section."
}
$pocDefaults = $defaults.poc
if ($HttpPort -eq 0) { $HttpPort = [int]$pocDefaults.httpPort }
$serviceName = [string]$pocDefaults.postgresqlServiceName
$postgresPort = [int]$pocDefaults.postgresqlPort
$databaseName = [string]$pocDefaults.databaseName
$databaseUser = [string]$pocDefaults.databaseUser

# What the bundle carries decides what can be installed; the GPU decides whether the CUDA
# Runtime Pack is offered at all.
$cpuRuntimeSource = Join-Path $BundleRoot "vision\runtime\windows-x86_64-cpu"
$cudaRuntimeSource = Join-Path $BundleRoot "vision\runtime\windows-x86_64-cuda"
$modelSourceRoot = Join-Path $BundleRoot "vision\models"
$platesCache = Join-Path $BundleRoot "plates"
$buildContract = Read-MaviJson -Path (Join-Path $bundleOverlay "config\vision\windows-cuda-development-build-v1.json")
$requiredComputeCapability = [string]$buildContract.targetGpu.computeCapability
$nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
$smiLines = $null
if ($nvidiaSmi) {
    # A driver that answers on stderr must not stop the installer (Windows PowerShell turns a
    # native command's stderr into a terminating error under Stop); it is "no usable GPU".
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $smiLines = @(& $nvidiaSmi.Source --query-gpu=index,name,compute_cap --format=csv,noheader 2>$null)
        if ($LASTEXITCODE -ne 0) { $smiLines = @() }
    }
    catch { $smiLines = @() }
    finally { $ErrorActionPreference = $previousPreference }
}
$gpu = Test-MaviPocCudaCompatibleGpu -NvidiaSmiLines $smiLines -RequiredComputeCapability $requiredComputeCapability
if ($AdoptCudaRuntimeRoot -and -not $gpu.Compatible) {
    # An explicit request is never silently dropped: the sm_75 pack does not serve this GPU.
    throw "-AdoptCudaRuntimeRoot was given, but this host's GPU is not served by the sm_$($requiredComputeCapability.Replace('.', '')) CUDA Runtime Pack ($($gpu.Reason); compute capability $($gpu.ComputeCapability))."
}
$cudaSource = "none"
if ($gpu.Compatible) {
    if ($AdoptCudaRuntimeRoot) { $cudaSource = "adopted" }
    elseif (Test-Path -LiteralPath (Join-Path $cudaRuntimeSource "runtime-pack-manifest.json") -PathType Leaf) { $cudaSource = "bundle" }
}
$cudaRuntimeRoot = switch ($cudaSource) {
    "adopted" { [IO.Path]::GetFullPath($AdoptCudaRuntimeRoot.Trim().Trim('"')) }
    default { $layout.VisionRuntimeCudaRoot }
}
$cudaDecision = [ordered]@{
    gpuCheck = $gpu.Reason
    gpu = $gpu.Gpu
    computeCapability = $gpu.ComputeCapability
    requiredComputeCapability = $requiredComputeCapability
    cudaRuntimePackSource = $cudaSource
}

$plan = [ordered]@{
    profile = Get-MaviPocProfile
    productionQualified = $false
    evidenceClass = "Development"
    bundleRoot = $BundleRoot
    installRoot = $layout.InstallRoot
    dataRoot = $layout.DataRoot
    postgresql = [ordered]@{ serviceName = $serviceName; port = $postgresPort; database = $databaseName; installRoot = $layout.PostgreSqlInstallRoot; dataRoot = $layout.PostgreSqlDataRoot }
    platform = [ordered]@{ url = (Get-MaviPocOperatorUrl -HttpPort $HttpPort); applicationRoot = $layout.ApplicationRoot; machineConfig = $layout.MachineConfigPath }
    vision = [ordered]@{ cpuRuntimeRoot = $layout.VisionRuntimeCpuRoot; cudaRuntimeRoot = $(if ($cudaSource -eq "none") { $null } else { $cudaRuntimeRoot }); modelStore = $layout.VisionModelRoot; devicePolicy = $DevicePolicy; cuda = $cudaDecision }
    plates = [ordered]@{ environment = $layout.PlatesEnvironmentRoot; modelStore = $layout.PlatesModelRoot; bound = $false }
    releaseMetadata = $layout.ReleaseMetadataPath
}

Write-MaviPocDisclosure
if ($DevicePolicy -eq "CUDA" -and $cudaSource -eq "none") {
    # Explicit CUDA fails closed (ADR-008): no CUDA Runtime Pack will be installed here; plan-only refuses it too.
    throw "Device policy CUDA requested, but no Windows CUDA Runtime Pack can be installed ($($gpu.Reason); CUDA pack source: $cudaSource). Use Auto or CPU."
}
if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    return
}

# Both roots are secured before anything is created in them (see Protect-MaviPocRoot).
Protect-MaviPocRoot -Path $layout.InstallRoot
Protect-MaviPocRoot -Path $layout.DataRoot
New-Item -ItemType Directory -Path $layout.SetupRoot, $layout.LogRoot -Force | Out-Null
Set-MaviPrivateDirectoryAcl -Path $layout.SetupRoot
$logPath = Join-Path $layout.LogRoot ("install-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
Start-Transcript -LiteralPath $logPath -Force | Out-Null
$resultPath = Join-Path $layout.SetupRoot "last-install-result.json"
$startedAt = [DateTimeOffset]::UtcNow
try {
    Write-Host "MAVI PoC installation ($(Get-MaviPocProfile))"
    Write-Host "========================================"
    Write-MaviPocDisclosure

    $bundleManifest = Test-MaviManifest -Root $BundleRoot -ManifestPath $bundleManifestPath -ExpectedSchemaVersion "mavi-poc-setup-bundle-v1"
    if ([string]$bundleManifest.profile -ne (Get-MaviPocProfile)) { throw "The bundle is not a $(Get-MaviPocProfile) bundle." }
    $revision = [string]$bundleManifest.applicationRevision
    $bundleSha256 = Get-MaviSha256 -Path $bundleManifestPath
    Write-MaviSetupStatus -Name "PoC bundle" -Status "OK" -Detail "SHA-256 verified; application $revision"

    # Secrets: generated once per installation, DPAPI-protected for the machine, never logged.
    $adminSecretPath = Join-Path $layout.SetupRoot "postgres-admin.dpapi"
    $appSecretPath = Join-Path $layout.SetupRoot "mavi-app.dpapi"
    $adminPassword = if (Test-Path -LiteralPath $adminSecretPath -PathType Leaf) { Unprotect-MaviSecret -Path $adminSecretPath } else { $value = New-MaviPassword; Protect-MaviSecret -PlainText $value -Path $adminSecretPath; $value }
    $databasePassword = if (Test-Path -LiteralPath $appSecretPath -PathType Leaf) { Unprotect-MaviSecret -Path $appSecretPath } else { $value = New-MaviPassword; Protect-MaviSecret -PlainText $value -Path $appSecretPath; $value }

    $postgres = Install-MaviPostgreSqlInstance -RuntimePackRoot (Join-Path $BundleRoot "prerequisites\postgresql\pg18\win-x64") -InstallRoot $layout.PostgreSqlInstallRoot -DataRoot $layout.PostgreSqlDataRoot -ServiceName $serviceName -Port $postgresPort -AdminPassword $adminPassword
    Write-MaviSetupStatus -Name "PostgreSQL 18" -Status "OK" -Detail "$serviceName @ 127.0.0.1:$postgresPort"
    Initialize-MaviDatabase -PsqlPath $postgres.PsqlPath -Port $postgresPort -AdminPassword $adminPassword -DatabaseName $databaseName -DatabaseUser $databaseUser -DatabasePassword $databasePassword
    Write-MaviSetupStatus -Name $databaseName -Status "OK" -Detail "database ready (pgvector $($postgres.Manifest.pgvectorVersion), pg_trgm)"

    # ASP.NET Core 10 runtime from the kit's approved Hosting Bundle, only when absent. The
    # PoC hosts the platform under Kestrel, not IIS, so only the shared runtime is required.
    if (-not (Test-MaviAspNetCore10Runtime)) {
        $hostingBundle = Join-Path $BundleRoot "prerequisites\hosting\win-x64\dotnet-hosting.exe"
        if (-not (Test-Path -LiteralPath $hostingBundle -PathType Leaf)) { throw "The ASP.NET Core 10 runtime is absent and the bundle carries no Hosting Bundle." }
        Invoke-MaviCommand -FilePath $hostingBundle -Arguments @("/install", "/quiet", "/norestart") -AllowedExitCodes @(0,3010)
        if (-not (Test-MaviAspNetCore10Runtime)) { throw "The ASP.NET Core 10 runtime is still absent after the Hosting Bundle ran; a Windows restart may be required." }
        Write-MaviSetupStatus -Name "ASP.NET Core 10" -Status "OK" -Detail "installed from the kit's Hosting Bundle"
    }
    else {
        Write-MaviSetupStatus -Name "ASP.NET Core 10" -Status "OK" -Detail "already present"
    }

    # A rerun while MAVI is running would find the platform's files locked: stop the
    # processes a previous installation started (the PostgreSQL service keeps running).
    if (Test-Path -LiteralPath $layout.InstallationStatePath -PathType Leaf) {
        & (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -DataRoot $layout.DataRoot
    }

    # Platform (API + UI, app-local FFmpeg) and the application overlay the
    # workers read. Both are replaced wholesale from the verified bundle on every run.
    foreach ($copy in @(@{ Source = (Join-Path $BundleRoot "application\api"); Destination = $layout.ApplicationRoot }, @{ Source = $bundleOverlay; Destination = $layout.OverlayRoot })) {
        New-Item -ItemType Directory -Path $copy.Destination -Force | Out-Null
        Invoke-MaviCommand -FilePath "robocopy.exe" -Arguments @($copy.Source, $copy.Destination, "/MIR", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/NFL", "/NDL", "/NP", "/NJH", "/NJS") -AllowedExitCodes @(0,1,2,3,4,5,6,7)
    }
    [void](Test-MaviManifest -Root (Join-Path $layout.ApplicationRoot "tools\ffmpeg") -ManifestPath (Join-Path $layout.ApplicationRoot "tools\ffmpeg\manifest.json"))
    $overlayRevision = (Resolve-MaviApplicationRevision -Root $layout.OverlayRoot).Revision
    if ($overlayRevision -ne $revision) { throw "The application overlay revision $overlayRevision is not the bundle's $revision." }
    Write-MaviSetupStatus -Name "Platform" -Status "OK" -Detail "$($layout.ApplicationRoot) (FFmpeg verified)"
    Write-MaviSetupStatus -Name "Application overlay" -Status "OK" -Detail "verified at $overlayRevision"

    New-Item -ItemType Directory -Path $layout.ConfigRoot -Force | Out-Null
    # The operator starts MAVI unelevated (Start-MAVI-PoC.cmd); the platform and the worker
    # write media, evidence, logs, process records and the device record as that user.
    foreach ($root in @($layout.MediaRoot, $layout.EvidenceRoot, $layout.RunRoot, $layout.LogRoot)) {
        Assert-MaviPocNoReparsePoint -Path $root
        Set-MaviDirectoryAcl -Path $root -Identity "*S-1-5-11" -Rights "M"
    }
    # The release metadata is the installer's alone: readable by every user, writable only
    # by administrators, so no local user can rewrite a pack's identity or status.
    # The installer regenerates everything in it, so the directory is emptied first (a file
    # planted beforehand with its own explicit grant cannot survive), then its owner is reset
    # (a user who created it would otherwise keep WRITE_DAC) and its ACL set. No recursive
    # icacls: a junction under it, or the directory itself being one, is refused before
    # anything is changed, so the elevated installer never rewrites permissions elsewhere.
    $releaseRoot = Split-Path $layout.ReleaseMetadataPath -Parent
    Assert-MaviPocNoReparsePoint -Path $releaseRoot -Recurse
    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    Get-ChildItem -LiteralPath $releaseRoot -Force | Remove-Item -Recurse -Force
    & icacls.exe $releaseRoot /setowner "*S-1-5-32-544" /C | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to give Administrators ownership of '$releaseRoot'." }
    Set-MaviPrivateDirectoryAcl -Path $releaseRoot -ApplicationIdentity "*S-1-5-11" -ApplicationRights "R"

    # Visual C++ x64 runtime for the Vision runtimes' native code (torch, mmcv), from the
    # bundle, only when absent or older (AGENTS.md: machine prerequisites belong to Setup).
    $vcResult = Install-MaviPocVcRuntime -InstallerPath (Join-Path $BundleRoot "prerequisites\vcredist\win-x64\vc_redist.x64.exe")
    Write-MaviSetupStatus -Name "Visual C++ x64 runtime" -Status "OK" -Detail $vcResult

    # Vision: the CPU Runtime Pack always; the CUDA one when a compatible GPU is present
    # and a pack is available; then every Model Pack the binding needs. The installers
    # write no Machine environment variable (H5).
    $installRuntime = Join-Path $layout.OverlayRoot "tools\setup\Install-MaviVisionRuntime.ps1"
    & $installRuntime -BundleRoot $cpuRuntimeSource -RepositoryRoot $layout.OverlayRoot -Variant "windows-x86_64-cpu" -InstallRoot $layout.VisionRuntimeCpuRoot -NoMachineEnvironment
    Assert-MaviPocRuntimeLoads -RuntimeRoot $layout.VisionRuntimeCpuRoot
    Write-MaviSetupStatus -Name "Vision CPU Runtime Pack" -Status "OK" -Detail "$($layout.VisionRuntimeCpuRoot) (torch and mmcv native ops load)"
    switch ($cudaSource) {
        "bundle" {
            & $installRuntime -BundleRoot $cudaRuntimeSource -RepositoryRoot $layout.OverlayRoot -Variant "windows-x86_64-cuda" -InstallRoot $layout.VisionRuntimeCudaRoot -NoMachineEnvironment
            Assert-MaviPocRuntimeLoads -RuntimeRoot $layout.VisionRuntimeCudaRoot
            Write-MaviSetupStatus -Name "Vision CUDA Runtime Pack" -Status "OK" -Detail "$($gpu.Gpu) (compute $($gpu.ComputeCapability))"
        }
        "adopted" {
            $adoptedManifest = Read-MaviJson -Path (Join-Path $cudaRuntimeRoot "runtime-pack-manifest.json")
            $adoptedState = Read-MaviJson -Path (Join-Path $cudaRuntimeRoot "runtime-install.json")
            [void](Assert-MaviVisionRuntimePackManifest -Manifest $adoptedManifest)
            [void](Assert-MaviVisionRuntimeInstalledStatePreflight -RuntimeRoot $cudaRuntimeRoot -InstalledState $adoptedState -Manifest $adoptedManifest -RuntimePackManifestPath (Join-Path $cudaRuntimeRoot "runtime-pack-manifest.json"))
            if ([string]$adoptedManifest.platformVariant -ne "windows-x86_64-cuda") { throw "The adopted runtime '$cudaRuntimeRoot' is not a Windows CUDA Runtime Pack." }
            Assert-MaviPocRuntimeLoads -RuntimeRoot $cudaRuntimeRoot
            Write-MaviSetupStatus -Name "Vision CUDA Runtime Pack" -Status "OK" -Detail "adopted (integrity preflight passed): $cudaRuntimeRoot"
        }
        default {
            Write-MaviSetupStatus -Name "Vision CUDA Runtime Pack" -Status "INFO" -Detail "not installed ($($gpu.Reason)); Auto will resolve CPU"
        }
    }

    $installModel = Join-Path $layout.OverlayRoot "tools\setup\Install-MaviVisionModelPack.ps1"
    $modelPacks = @(Get-ChildItem -LiteralPath $modelSourceRoot -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "model-pack-manifest.json") -PathType Leaf } | Sort-Object Name)
    if ($modelPacks.Count -eq 0) { throw "The bundle carries no Vision Model Pack." }
    foreach ($pack in $modelPacks) {
        & $installModel -PackRoot $pack.FullName -StoreRoot $layout.VisionModelRoot -NoMachineEnvironment
    }
    Write-MaviSetupStatus -Name "Vision Model Packs" -Status "OK" -Detail "$($modelPacks.Count) installed into $($layout.VisionModelRoot)"

    # Plates runtime (Issue #225 pilot family) and its Model Packs: installed, not bound.
    # S3 binds the plates role; until then the platform's plate loop stays NotConfigured.
    $platesPython = Join-Path $layout.VisionRuntimeBase "Python312\python.exe"
    if (-not (Test-Path -LiteralPath $platesPython -PathType Leaf)) {
        $platesPython = (& (Join-Path $layout.VisionRuntimeCpuRoot "venv\Scripts\python.exe") -c "import sys; print(sys._base_executable)" | Out-String).Trim()
    }
    & (Join-Path $layout.OverlayRoot "tools\setup\Install-MaviPlatesPilotRuntime.ps1") -Python $platesPython -Destination $layout.PlatesEnvironmentRoot -ModelRoot $layout.PlatesModelRoot -Cache $platesCache -ReuseVerified
    Write-MaviSetupStatus -Name "Plates runtime" -Status "OK" -Detail "installed, not bound (S3)"

    # Machine configuration (connection string, roots, cursor key, loopback URL, profile).
    $cursorSigningKey = Get-MaviExistingCursorSigningKey -MachineConfigPath $layout.MachineConfigPath
    if (-not $cursorSigningKey) { $cursorSigningKey = New-MaviCursorSigningKey }
    $connectionString = "Host=127.0.0.1;Port=$postgresPort;Database=$databaseName;Username=$databaseUser;Password=$databasePassword"
    Write-MaviJson -Value (New-MaviPocMachineConfig -Layout $layout -ConnectionString $connectionString -CursorSigningKey $cursorSigningKey -HttpPort $HttpPort) -Path $layout.MachineConfigPath -Depth 8
    # Read for Authenticated Users, as on a Development workstation: whoever signs in starts
    # MAVI unelevated and the platform reads this file as that user (an installing
    # administrator is often not the operator). It holds the PoC database credentials; a
    # single-host PoC accepts that every local user can read them (runbook).
    & icacls.exe $layout.MachineConfigPath /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" "*S-1-5-11:R" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to secure the PoC machine configuration." }
    Write-MaviSetupStatus -Name "Machine config" -Status "OK" -Detail $layout.MachineConfigPath

    # Release metadata: every bound pack's identity and verification status.
    $runtimeProfile = Read-MaviJson -Path (Join-Path $layout.OverlayRoot "src\vision\runtime\mmdetection-phase1-v1\runtime.json")
    $manifestDirectory = Join-Path $layout.OverlayRoot "models\manifests"
    $packs = @()
    $cpuManifest = Read-MaviJson -Path (Join-Path $layout.VisionRuntimeCpuRoot "runtime-pack-manifest.json")
    $packs += [ordered]@{ kind = "runtime"; role = "vision"; capabilityId = $null; packId = [string]$cpuManifest.runtimePackId; variant = "windows-x86_64-cpu"; verificationStatus = (Get-MaviPocRuntimeVerificationStatus -RuntimeProfile $runtimeProfile -Variant "windows-x86_64-cpu"); note = $null }
    if ($cudaSource -ne "none") {
        $cudaManifest = Read-MaviJson -Path (Join-Path $cudaRuntimeRoot "runtime-pack-manifest.json")
        $packs += [ordered]@{ kind = "runtime"; role = "vision"; capabilityId = $null; packId = [string]$cudaManifest.runtimePackId; variant = "windows-x86_64-cuda"; verificationStatus = (Get-MaviPocRuntimeVerificationStatus -RuntimeProfile $runtimeProfile -Variant "windows-x86_64-cuda"); note = $(if ($cudaSource -eq "adopted") { "adopted from an existing installation" } else { $null }) }
    }
    foreach ($pack in $modelPacks) {
        $manifest = Read-MaviJson -Path (Join-Path $pack.FullName "model-pack-manifest.json")
        $packs += [ordered]@{ kind = "model"; role = "vision"; capabilityId = (@($manifest.capabilityIds) -join ","); packId = [string]$manifest.modelPackId; variant = $null; verificationStatus = (Get-MaviPocModelVerificationStatus -ManifestDirectory $manifestDirectory -ModelId ([string]$manifest.modelId) -ModelVersion ([string]$manifest.modelVersion)); note = "$($manifest.modelId) $($manifest.modelVersion)" }
    }
    $platesLockSha = Get-MaviSha256 -Path (Join-Path $layout.OverlayRoot "src\vision\runtime\plates-onnx-v1\windows-x86_64-cpu.lock")
    $packs += [ordered]@{ kind = "runtime"; role = "plates"; capabilityId = $null; packId = "plates-onnx-v1@lock-sha256:$platesLockSha"; variant = "windows-x86_64-cpu"; verificationStatus = "development-pilot"; note = "installed, not bound (S3)" }
    foreach ($payloadManifest in @("plates-pd5-ppocrv5-mobile-det-dev-v1.json", "plates-oc1-fast-plate-ocr-cct-s-v2-dev-v1.json")) {
        $manifest = Read-MaviJson -Path (Join-Path $manifestDirectory $payloadManifest)
        $packs += [ordered]@{ kind = "model"; role = "plates"; capabilityId = $null; packId = "$($manifest.modelId)@$($manifest.modelVersion)"; variant = $null; verificationStatus = [string]$manifest.verificationStatus; note = "installed, not bound (S3)" }
    }
    $metadata = New-MaviPocReleaseMetadata -ApplicationRevision $revision -BundleSha256 $bundleSha256 -DevicePolicy $DevicePolicy -CudaDecision $cudaDecision -Packs $packs -InstalledAtUtc ([DateTimeOffset]::UtcNow.ToString("O"))
    Write-MaviJson -Value $metadata -Path $layout.ReleaseMetadataPath -Depth 8
    Write-MaviSetupStatus -Name "Release metadata" -Status "OK" -Detail $layout.ReleaseMetadataPath

    $state = [ordered]@{
        schemaVersion = "mavi-poc-installation-v1"
        profile = Get-MaviPocProfile
        installRoot = $layout.InstallRoot
        dataRoot = $layout.DataRoot
        httpPort = $HttpPort
        apiBaseUrl = "http://127.0.0.1:$HttpPort"
        operatorUrl = Get-MaviPocOperatorUrl -HttpPort $HttpPort
        devicePolicy = $DevicePolicy
        cudaRuntimeRoot = $(if ($cudaSource -eq "none") { $null } else { $cudaRuntimeRoot })
        postgresqlServiceName = $serviceName
        applicationRevision = $revision
    }
    Write-MaviJson -Value $state -Path $layout.InstallationStatePath -Depth 6

    # Readiness: the launcher's own checks with the recorded policy, from the installed
    # overlay (no git). This is what records the resolved device and reason.
    $launcher = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviVisionWorker.ps1"
    $launchArguments = @{
        RepositoryRoot = $layout.OverlayRoot; DevicePolicy = $DevicePolicy.ToLowerInvariant(); RuntimeCpuRoot = $layout.VisionRuntimeCpuRoot
        RuntimeCudaRoot = $cudaRuntimeRoot; ModelRoot = $layout.VisionModelRoot; DeviceReportPath = $layout.DeviceResolutionPath; VerifyOnly = $true
    }
    & $launcher @launchArguments
    $device = Read-MaviJson -Path $layout.DeviceResolutionPath
    Write-MaviSetupStatus -Name "Vision composition" -Status "OK" -Detail "READY; device $($device.resolvedDevicePolicy) ($($device.deviceResolutionReason))"

    # Start once: migrations run, the disclosure is checked by the platform, the demo
    # cameras are seeded. Always stopped afterwards: processes started here run elevated, and
    # the operator starts MAVI unelevated with Start-MAVI-PoC.cmd.
    $start = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviPoc.ps1"
    & $start -DataRoot $layout.DataRoot -Seed
    & (Join-Path $layout.OverlayRoot "tools\setup\Stop-MaviPoc.ps1") -DataRoot $layout.DataRoot

    # Operator launchers in the install root.
    foreach ($launcherName in @("Start-MAVI-PoC.cmd", "Stop-MAVI-PoC.cmd", "Test-MAVI-PoC.cmd")) {
        $text = [IO.File]::ReadAllText((Join-Path $layout.OverlayRoot "tools\setup\poc\$launcherName"))
        $text = $text.Replace("__MAVI_POC_DATA_ROOT__", $layout.DataRoot).Replace("__MAVI_POC_URL__", (Get-MaviPocOperatorUrl -HttpPort $HttpPort))
        [IO.File]::WriteAllText((Join-Path $layout.InstallRoot $launcherName), $text, (New-Object Text.ASCIIEncoding))
    }

    $result = [ordered]@{
        schemaVersion = "mavi-poc-install-result-v1"
        profile = Get-MaviPocProfile
        productionQualified = $false
        evidenceClass = "Development"
        passed = $true
        startedAtUtc = $startedAt.ToString("O")
        completedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        applicationRevision = $revision
        bundleSha256 = $bundleSha256
        device = [ordered]@{ requested = $DevicePolicy.ToLowerInvariant(); resolved = [string]$device.resolvedDevicePolicy; reason = [string]$device.deviceResolutionReason }
        cuda = $cudaDecision
        logPath = $logPath
    }
    Write-MaviJson -Value $result -Path $resultPath -Depth 8
    Write-Host ""
    Write-Host "MAVI PoC installed: $(Get-MaviPocOperatorUrl -HttpPort $HttpPort) (start with $(Join-Path $layout.InstallRoot 'Start-MAVI-PoC.cmd'))." -ForegroundColor Green
    Write-MaviPocDisclosure
}
catch {
    $failure = [ordered]@{
        schemaVersion = "mavi-poc-install-result-v1"
        profile = Get-MaviPocProfile
        passed = $false
        startedAtUtc = $startedAt.ToString("O")
        completedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        error = $_.Exception.Message
        logPath = $logPath
    }
    Write-MaviJson -Value $failure -Path $resultPath -Depth 8
    Write-Error $_
    throw
}
finally {
    Stop-Transcript | Out-Null
}
