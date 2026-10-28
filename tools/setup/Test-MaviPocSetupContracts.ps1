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

    # The plan-only CUDA case above exits 1 by design; the caller's shell reports this
    # script's last exit code.
    $global:LASTEXITCODE = 0
    Write-Host "MAVI PoC setup contracts passed." -ForegroundColor Green
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
