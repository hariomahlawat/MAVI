[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC"),
    # Stop only these (Start-MaviPoc's rollback stops only what it started). Default: all three.
    [ValidateSet("plates-worker", "vision-worker", "api")][string[]]$Only = @("plates-worker", "vision-worker", "api")
)

# Stops what Start-MaviPoc.ps1 started (the Vision worker, then the platform), each with
# its process tree, and only when the recorded process is still the one that was started
# (the image Start launched for it, the same start time): a stale record after a reboot
# names someone else's process. PostgreSQL is a service and keeps running. The device
# record is removed with the worker, so the disclosure never shows a device for a worker
# that is not running.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force

$runRoot = Join-Path ([IO.Path]::GetFullPath($DataRoot)) "run"
$images = @{ "plates-worker" = "powershell"; "vision-worker" = "powershell"; "api" = "Mavi.Api" }
$commands = @{ "plates-worker" = "Start-MaviPlatesPilotWorker.ps1"; "vision-worker" = "Start-MaviVisionWorker.ps1"; "api" = "Mavi.Api.exe" }
$failures = @()
foreach ($name in @("plates-worker", "vision-worker", "api")) {
    if ($Only -notcontains $name) { continue }
    $recordPath = Join-Path $runRoot "$name.pid"
    $process = Get-MaviPocRecordedProcess -Path $recordPath -ExpectedImageName $images[$name] -ExpectedCommandFragment $commands[$name]
    if (-not $process) { continue }
    # taskkill reports on stderr (a child of the tree already gone, access denied); under
    # Stop, Windows PowerShell would turn that into a terminating error before the exit
    # code could be read.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = (& taskkill.exe /PID $process.Id /T /F 2>&1 | Out-String).Trim()
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousPreference }
    # Existence, not HasExited: reading an elevated process's handle from an unelevated
    # session is itself access-denied.
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    while ((Get-Process -Id $process.Id -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
    if (Get-Process -Id $process.Id -ErrorAction SilentlyContinue) {
        $failures += "$name (pid $($process.Id), taskkill exit $exitCode; started elevated? $output)"
        continue
    }
    Remove-Item -LiteralPath $recordPath -Force -ErrorAction SilentlyContinue
    Write-Host ("{0,-26} {1}" -f $name, "stopped (pid $($process.Id))")
}
# No worker of ours is running now (none recorded, or it was just stopped): no device is.
if ($Only -contains "vision-worker" -and @($failures | Where-Object { $_ -like "vision-worker*" }).Count -eq 0) {
    Remove-Item -LiteralPath (Join-Path $runRoot "device-resolution.json") -Force -ErrorAction SilentlyContinue
}
if ($Only -contains "plates-worker" -and @($failures | Where-Object { $_ -like "plates-worker*" }).Count -eq 0) {
    Remove-Item -LiteralPath (Join-Path $runRoot "plates-device-resolution.json") -Force -ErrorAction SilentlyContinue
}
$global:LASTEXITCODE = 0
if ($failures.Count -gt 0) { throw "Could not stop: $($failures -join '; '). Stop it from an elevated prompt." }
