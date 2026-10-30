[CmdletBinding()]
param(
    # The PoC data root (holds config\poc-installation.json, written by Install-MAVI-PoC).
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC"),
    # Overrides the installed device policy for this start (ADR-008: Auto, CUDA or CPU).
    [ValidateSet("Auto", "CUDA", "CPU")][string]$DevicePolicy,
    # Overrides the installed plates device policy for this start (PoC S3; the plates role runs on CPU only, so CUDA
    # fails closed).
    [ValidateSet("Auto", "CUDA", "CPU")][string]$PlatesDevicePolicy,
    # Create the demo cameras (config\poc\demo-cameras-v1.json) that do not exist yet.
    [switch]$Seed,
    [int]$HealthTimeoutSeconds = 180,
    [int]$WorkerTimeoutSeconds = 180,
    # How long the worker must stay up after its launcher passed every check. The worker
    # refuses some conditions itself at start-up (an explicit CUDA device that does not
    # answer), and a refusal must not be reported as a running worker.
    [int]$WorkerSettleSeconds = 20
)

# Starts the poc-single-host stack (PoC S1; ADR-020): the platform (published API + UI,
# Kestrel on loopback) and the Vision worker through the ordinary launcher, from the
# installed application overlay. PostgreSQL is the MAVI-owned service the installer
# registered. Processes run as the signed-in operator and are stopped by Stop-MaviPoc.ps1.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Windows.psm1") -Force -DisableNameChecking
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force

$statePath = Join-Path ([IO.Path]::GetFullPath($DataRoot)) "config\poc-installation.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "No MAVI PoC installation is recorded at '$statePath'. Run Install-MAVI-PoC first." }
$state = Read-MaviJson -Path $statePath
if ([string]$state.profile -ne (Get-MaviPocProfile)) { throw "'$statePath' is not a $(Get-MaviPocProfile) installation." }
$layout = Get-MaviPocLayout -InstallRoot ([string]$state.installRoot) -DataRoot ([string]$state.dataRoot)
$policy = if ($DevicePolicy) { $DevicePolicy } else { [string]$state.devicePolicy }
# An installation from before S3 recorded no plates policy; Auto is the installer's default.
$platesPolicy = if ($PlatesDevicePolicy) { $PlatesDevicePolicy } elseif ($state.PSObject.Properties["platesDevicePolicy"] -and $state.platesDevicePolicy) { [string]$state.platesDevicePolicy } else { "Auto" }
$apiBaseUrl = [string]$state.apiBaseUrl
New-Item -ItemType Directory -Path $layout.LogRoot, $layout.RunRoot -Force | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host ""
Write-Host "  $(Get-MaviPocDisclosureStatement)" -ForegroundColor Yellow
Write-Host ""

function Get-MaviPocRunningProcess {
    param([Parameter(Mandatory = $true)][string]$Name)
    $image = if ($Name -eq "api") { "Mavi.Api" } else { "powershell" }
    $command = switch ($Name) { "api" { "Mavi.Api.exe" } "plates-worker" { "Start-MaviPlatesPilotWorker.ps1" } "embeddings-worker" { "Start-MaviEmbeddingsWorker.ps1" } "attributes-worker" { "Start-MaviAttributesWorker.ps1" } "faces-worker" { "Start-MaviFacesWorker.ps1" } default { "Start-MaviVisionWorker.ps1" } }
    Get-MaviPocRecordedProcess -Path (Join-Path $layout.RunRoot "$Name.pid") -ExpectedImageName $image -ExpectedCommandFragment $command
}

# A start that fails part-way stops what it started, so nothing is left half-running.
$startedHere = @()
try {
$service = Get-Service -Name ([string]$state.postgresqlServiceName) -ErrorAction SilentlyContinue
if (-not $service) { throw "PostgreSQL service '$($state.postgresqlServiceName)' is not installed; rerun Install-MAVI-PoC." }
if ($service.Status -ne "Running") {
    Start-Service -Name $service.Name
    Write-MaviSetupStatus -Name "PostgreSQL" -Status "OK" -Detail "started $($service.Name)"
}

# Platform. Environment name PoC: not Development (no Development-only conveniences),
# and the machine configuration is named explicitly rather than found by convention.
if (Get-MaviPocRunningProcess -Name "api") {
    Write-MaviSetupStatus -Name "Platform" -Status "OK" -Detail "already running"
}
else {
    $apiExe = Join-Path $layout.ApplicationRoot "Mavi.Api.exe"
    if (-not (Test-Path -LiteralPath $apiExe -PathType Leaf)) { throw "The platform is not installed at '$apiExe'." }
    $env:ASPNETCORE_ENVIRONMENT = "PoC"
    $env:MAVI_MACHINE_CONFIG = $layout.MachineConfigPath
    $api = Start-Process -FilePath $apiExe -WorkingDirectory $layout.ApplicationRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $layout.LogRoot "api-$stamp.out.log") -RedirectStandardError (Join-Path $layout.LogRoot "api-$stamp.err.log")
    $startedHere += "api"
    Write-MaviPocProcessRecord -Path (Join-Path $layout.RunRoot "api.pid") -Process $api
}
$health = Wait-MaviHealth -BaseUrl $apiBaseUrl -TimeoutSeconds $HealthTimeoutSeconds
Write-MaviSetupStatus -Name "Platform" -Status "OK" -Detail "$apiBaseUrl ($($health.build) / $($health.commit))"

# Vision worker, through the ordinary launcher: every launch check runs, Auto resolves the
# device, and the device record is rewritten for this launch.
if (Get-MaviPocRunningProcess -Name "vision-worker") {
    Write-MaviSetupStatus -Name "Vision worker" -Status "OK" -Detail "already running"
}
else {
    # No worker is running, so no device is resolved: a record left by a run that ended
    # without Stop (a reboot) must not be shown while this launch is checked.
    Remove-Item -LiteralPath $layout.DeviceResolutionPath -Force -ErrorAction SilentlyContinue
    $previousReport = [DateTime]::MinValue
    $launcher = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviVisionWorker.ps1"
    $arguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $launcher,
        "-RepositoryRoot", $layout.OverlayRoot,
        "-ApiBaseUrl", $apiBaseUrl,
        "-WorkerId", "poc-vision-01",
        "-MediaRoot", $layout.MediaRoot,
        "-DevicePolicy", $policy.ToLowerInvariant(),
        "-RuntimeCpuRoot", $layout.VisionRuntimeCpuRoot,
        "-ModelRoot", $layout.VisionModelRoot,
        "-DeviceReportPath", $layout.DeviceResolutionPath
    )
    if ($state.cudaRuntimeRoot) { $arguments += @("-RuntimeCudaRoot", [string]$state.cudaRuntimeRoot) }
    else { $arguments += @("-RuntimeCudaRoot", $layout.VisionRuntimeCudaRoot) }
    $quoted = @($arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
    $worker = Start-Process -FilePath "powershell.exe" -ArgumentList $quoted -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $layout.LogRoot "vision-worker-$stamp.out.log") -RedirectStandardError (Join-Path $layout.LogRoot "vision-worker-$stamp.err.log")
    # Touching Handle keeps the exit code readable after the process ends (PowerShell 5.1).
    [void]$worker.Handle
    $startedHere += "vision-worker"
    Write-MaviPocProcessRecord -Path (Join-Path $layout.RunRoot "vision-worker.pid") -Process $worker

    # The launcher writes the device record once every check has passed, just before the
    # worker starts. A launcher that exits first has refused; its log says why.
    $deadline = [DateTime]::UtcNow.AddSeconds($WorkerTimeoutSeconds)
    while ($true) {
        if ((Test-Path -LiteralPath $layout.DeviceResolutionPath -PathType Leaf) -and (Get-Item -LiteralPath $layout.DeviceResolutionPath).LastWriteTimeUtc -gt $previousReport) {
            $report = Read-MaviJson -Path $layout.DeviceResolutionPath
            if (-not [bool]$report.verifyOnly) { break }
        }
        if ($worker.HasExited) {
            throw "The Vision worker launcher exited with code $($worker.ExitCode) before starting the worker. See $(Join-Path $layout.LogRoot "vision-worker-$stamp.out.log")."
        }
        if ([DateTime]::UtcNow -gt $deadline) { throw "The Vision worker launcher did not complete its checks within $WorkerTimeoutSeconds s." }
        Start-Sleep -Seconds 2
    }
    $settleUntil = [DateTime]::UtcNow.AddSeconds($WorkerSettleSeconds)
    while ([DateTime]::UtcNow -lt $settleUntil) {
        if ($worker.HasExited) {
            throw "The Vision worker exited with code $($worker.ExitCode) during start-up. See $(Join-Path $layout.LogRoot "vision-worker-$stamp.err.log")."
        }
        Start-Sleep -Seconds 2
    }
    Write-MaviSetupStatus -Name "Vision worker" -Status "OK" -Detail "device $($report.resolvedDevicePolicy) ($($report.deviceResolutionReason)); requested $($report.requestedDevicePolicy)"
}

# Plates worker (PoC S3): the bound PD5 + OC1-S role, through its launcher, which resolves and records the role's
# device first (CUDA fails closed). The worker exits non-zero when its composition is refused or not READY.
if (Get-MaviPocRunningProcess -Name "plates-worker") {
    Write-MaviSetupStatus -Name "Plates worker" -Status "OK" -Detail "already running"
}
else {
    Remove-Item -LiteralPath $layout.PlatesDeviceResolutionPath -Force -ErrorAction SilentlyContinue
    $platesLauncher = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviPlatesPilotWorker.ps1"
    $platesArguments = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $platesLauncher,
        "-RepositoryRoot", $layout.OverlayRoot,
        "-ApiBaseUrl", $apiBaseUrl,
        "-WorkerId", "poc-plates-01",
        "-Python", (Join-Path $layout.PlatesEnvironmentRoot "Scripts\python.exe"),
        "-ModelRoot", $layout.PlatesModelRoot,
        "-DevicePolicy", $platesPolicy.ToLowerInvariant(),
        "-DeviceReportPath", $layout.PlatesDeviceResolutionPath
    )
    $platesQuoted = @($platesArguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
    $platesWorker = Start-Process -FilePath "powershell.exe" -ArgumentList $platesQuoted -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $layout.LogRoot "plates-worker-$stamp.out.log") -RedirectStandardError (Join-Path $layout.LogRoot "plates-worker-$stamp.err.log")
    [void]$platesWorker.Handle
    $startedHere += "plates-worker"
    Write-MaviPocProcessRecord -Path (Join-Path $layout.RunRoot "plates-worker.pid") -Process $platesWorker
    $deadline = [DateTime]::UtcNow.AddSeconds($WorkerTimeoutSeconds)
    while (-not (Test-Path -LiteralPath $layout.PlatesDeviceResolutionPath -PathType Leaf)) {
        if ($platesWorker.HasExited) {
            throw "The plates worker launcher exited with code $($platesWorker.ExitCode) before starting the worker. See $(Join-Path $layout.LogRoot "plates-worker-$stamp.err.log")."
        }
        if ([DateTime]::UtcNow -gt $deadline) { throw "The plates worker launcher did not complete its checks within $WorkerTimeoutSeconds s." }
        Start-Sleep -Seconds 1
    }
    $settleUntil = [DateTime]::UtcNow.AddSeconds($WorkerSettleSeconds)
    while ([DateTime]::UtcNow -lt $settleUntil) {
        if ($platesWorker.HasExited) {
            throw "The plates worker exited with code $($platesWorker.ExitCode) during start-up. See $(Join-Path $layout.LogRoot "plates-worker-$stamp.err.log")."
        }
        Start-Sleep -Seconds 2
    }
    $platesReport = Read-MaviJson -Path $layout.PlatesDeviceResolutionPath
    Write-MaviSetupStatus -Name "Plates worker" -Status "OK" -Detail "device $($platesReport.resolvedDevicePolicy) ($($platesReport.deviceResolutionReason)); requested $($platesReport.requestedDevicePolicy)"
}

# Embeddings worker (PoC S4, ADR-021): bound by the installer; CPU ONNX Runtime. It verifies its pack and leases only
# the platform's embedding identity; a failure there never touches a ProcessingRun.
if ($state.PSObject.Properties["embeddingsBound"] -and [bool]$state.embeddingsBound) {
    if (Get-MaviPocRunningProcess -Name "embeddings-worker") {
        Write-MaviSetupStatus -Name "Embeddings worker" -Status "OK" -Detail "already running"
    }
    else {
        $embeddingsLauncher = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviEmbeddingsWorker.ps1"
        $embeddingsArguments = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $embeddingsLauncher,
            "-RepositoryRoot", $layout.OverlayRoot,
            "-ApiBaseUrl", $apiBaseUrl,
            "-WorkerId", "poc-embeddings-01",
            "-Python", (Join-Path $layout.EmbeddingsEnvironmentRoot "Scripts\python.exe"),
            "-ModelRoot", $layout.EmbeddingsModelRoot,
            "-DevicePolicy", "cpu"
        )
        $quotedEmbeddings = @($embeddingsArguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
        $embeddingsWorker = Start-Process -FilePath "powershell.exe" -ArgumentList $quotedEmbeddings -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $layout.LogRoot "embeddings-worker-$stamp.out.log") -RedirectStandardError (Join-Path $layout.LogRoot "embeddings-worker-$stamp.err.log")
        [void]$embeddingsWorker.Handle
        $startedHere += "embeddings-worker"
        Write-MaviPocProcessRecord -Path (Join-Path $layout.RunRoot "embeddings-worker.pid") -Process $embeddingsWorker
        $settleUntil = [DateTime]::UtcNow.AddSeconds($WorkerSettleSeconds)
        while ([DateTime]::UtcNow -lt $settleUntil) {
            if ($embeddingsWorker.HasExited) {
                throw "The embeddings worker exited with code $($embeddingsWorker.ExitCode) during start-up. See $(Join-Path $layout.LogRoot "embeddings-worker-$stamp.err.log")."
            }
            Start-Sleep -Seconds 2
        }
        Write-MaviSetupStatus -Name "Embeddings worker" -Status "OK" -Detail "SigLIP 2 on CPU (Development)"
    }

    # Attributes worker (PoC S5): the SigLIP 2 zero-shot inferencer on the same runtime and Model Pack, bound with the
    # embeddings role. Zero-shot, Development; a failure leaves the attribute plane Pending and never touches a run.
    if (Get-MaviPocRunningProcess -Name "attributes-worker") {
        Write-MaviSetupStatus -Name "Attributes worker" -Status "OK" -Detail "already running"
    }
    else {
        $attributesLauncher = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviAttributesWorker.ps1"
        $attributesArguments = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $attributesLauncher,
            "-RepositoryRoot", $layout.OverlayRoot,
            "-ApiBaseUrl", $apiBaseUrl,
            "-WorkerId", "poc-attributes-01",
            "-Python", (Join-Path $layout.EmbeddingsEnvironmentRoot "Scripts\python.exe"),
            "-ModelRoot", $layout.EmbeddingsModelRoot,
            "-DevicePolicy", "cpu"
        )
        $quotedAttributes = @($attributesArguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
        $attributesWorker = Start-Process -FilePath "powershell.exe" -ArgumentList $quotedAttributes -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $layout.LogRoot "attributes-worker-$stamp.out.log") -RedirectStandardError (Join-Path $layout.LogRoot "attributes-worker-$stamp.err.log")
        [void]$attributesWorker.Handle
        $startedHere += "attributes-worker"
        Write-MaviPocProcessRecord -Path (Join-Path $layout.RunRoot "attributes-worker.pid") -Process $attributesWorker
        $settleUntil = [DateTime]::UtcNow.AddSeconds($WorkerSettleSeconds)
        while ([DateTime]::UtcNow -lt $settleUntil) {
            if ($attributesWorker.HasExited) {
                throw "The attributes worker exited with code $($attributesWorker.ExitCode) during start-up. See $(Join-Path $layout.LogRoot "attributes-worker-$stamp.err.log")."
            }
            Start-Sleep -Seconds 2
        }
        Write-MaviSetupStatus -Name "Attributes worker" -Status "OK" -Detail "SigLIP 2 zero-shot on CPU (zero-shot, Development)"
    }
}

# Faces worker (PoC S6, ADR-022): bound by the installer; CPU ONNX Runtime on the embeddings-onnx-v1 environment. It
# verifies its pack and leases only the platform's face identity, for runs of cameras an operator opted in; a failure
# there never touches a ProcessingRun. Results are candidates, never identification.
if ($state.PSObject.Properties["facesBound"] -and [bool]$state.facesBound) {
    if (Get-MaviPocRunningProcess -Name "faces-worker") {
        Write-MaviSetupStatus -Name "Faces worker" -Status "OK" -Detail "already running"
    }
    else {
        $facesLauncher = Join-Path $layout.OverlayRoot "tools\setup\Start-MaviFacesWorker.ps1"
        $facesArguments = @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $facesLauncher,
            "-RepositoryRoot", $layout.OverlayRoot,
            "-ApiBaseUrl", $apiBaseUrl,
            "-WorkerId", "poc-faces-01",
            "-Python", (Join-Path $layout.EmbeddingsEnvironmentRoot "Scripts\python.exe"),
            "-ModelRoot", $layout.FacesModelRoot,
            "-DevicePolicy", "cpu"
        )
        $quotedFaces = @($facesArguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
        $facesWorker = Start-Process -FilePath "powershell.exe" -ArgumentList $quotedFaces -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $layout.LogRoot "faces-worker-$stamp.out.log") -RedirectStandardError (Join-Path $layout.LogRoot "faces-worker-$stamp.err.log")
        [void]$facesWorker.Handle
        $startedHere += "faces-worker"
        Write-MaviPocProcessRecord -Path (Join-Path $layout.RunRoot "faces-worker.pid") -Process $facesWorker
        $settleUntil = [DateTime]::UtcNow.AddSeconds($WorkerSettleSeconds)
        while ([DateTime]::UtcNow -lt $settleUntil) {
            if ($facesWorker.HasExited) {
                throw "The faces worker exited with code $($facesWorker.ExitCode) during start-up. See $(Join-Path $layout.LogRoot "faces-worker-$stamp.err.log")."
            }
            Start-Sleep -Seconds 2
        }
        Write-MaviSetupStatus -Name "Faces worker" -Status "OK" -Detail "YuNet + AdaFace IR-50 on CPU (Development; opt-in per camera)"
    }
}
if ($Seed) {
    $cameras = Read-MaviPocDemoCameras -Path (Join-Path $layout.OverlayRoot "config\poc\demo-cameras-v1.json")
    # Windows PowerShell 5.1 hands a JSON array down the pipeline as one object; unroll it.
    $existing = @(Invoke-RestMethod -Uri "$apiBaseUrl/api/cameras" -Method Get -TimeoutSec 30 | ForEach-Object { $_ })
    $created = 0
    foreach ($camera in $cameras) {
        if (@($existing | Where-Object { [string]$_.code -eq $camera.Code }).Count -gt 0) { continue }
        $fields = @{ code = $camera.Code; name = $camera.Name; timeZoneId = $camera.TimeZoneId }
        if ($camera.SiteCode) { $fields.siteCode = $camera.SiteCode }
        $body = $fields | ConvertTo-Json -Compress
        [void](Invoke-RestMethod -Uri "$apiBaseUrl/api/cameras" -Method Post -ContentType "application/json" -Body $body -TimeoutSec 30)
        $created++
    }
    Write-MaviSetupStatus -Name "Demo cameras" -Status "OK" -Detail "$created created, $($cameras.Count - $created) already present (names and sites only; no scene configured)"
}

$deployment = Invoke-RestMethod -Uri "$apiBaseUrl/api/system/deployment" -Method Get -TimeoutSec 30
if ([string]$deployment.profile -ne (Get-MaviPocProfile) -or [bool]$deployment.productionQualified) {
    throw "The platform does not report the $(Get-MaviPocProfile) disclosure."
}
Write-MaviSetupStatus -Name "Disclosure" -Status "OK" -Detail "$($deployment.profile); not Production-qualified; evidence $($deployment.evidenceClass)"
}
catch {
    # Only what this start launched; an instance that was already running is left alone.
    if ($startedHere.Count -gt 0) {
        # The start failure is what the operator needs; a failing rollback only adds to it.
        try { & (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -DataRoot $layout.DataRoot -Only $startedHere }
        catch { Write-Warning "Rolling back the failed start also failed: $($_.Exception.Message)" }
    }
    throw
}
Write-Host ""
# An installation state written before operatorUrl existed has no such property (strict mode).
$operatorUrlProperty = $state.PSObject.Properties['operatorUrl']
$operatorUrl = if ($operatorUrlProperty -and [string]$operatorUrlProperty.Value) { [string]$operatorUrlProperty.Value } else { $apiBaseUrl }
Write-Host "MAVI PoC running: $operatorUrl" -ForegroundColor Green
