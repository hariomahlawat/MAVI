[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC")
)

# Stops what Start-MaviPoc.ps1 started (the Vision worker, then the platform), each with
# its process tree, and only when the recorded process is still the one that was started
# (same image, same start time): a stale record after a reboot names someone else's
# process. PostgreSQL is a service and keeps running. The device record is removed with
# the worker, so the disclosure never shows a device for a worker that is not running.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force

$runRoot = Join-Path ([IO.Path]::GetFullPath($DataRoot)) "run"
$failures = @()
foreach ($name in @("vision-worker", "api")) {
    $recordPath = Join-Path $runRoot "$name.pid"
    $process = Get-MaviPocRecordedProcess -Path $recordPath
    if (-not $process) { continue }
    & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0 -and -not $process.HasExited) {
        $failures += "$name (pid $($process.Id), taskkill exit $LASTEXITCODE; started elevated?)"
        continue
    }
    Remove-Item -LiteralPath $recordPath -Force -ErrorAction SilentlyContinue
    Write-Host ("{0,-26} {1}" -f $name, "stopped (pid $($process.Id))")
}
Remove-Item -LiteralPath (Join-Path $runRoot "device-resolution.json") -Force -ErrorAction SilentlyContinue
if ($failures.Count -gt 0) { throw "Could not stop: $($failures -join '; ')." }
