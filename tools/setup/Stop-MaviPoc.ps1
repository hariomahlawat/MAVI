[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC")
)

# Stops what Start-MaviPoc.ps1 started (the Vision worker, then the platform), each with
# its process tree. PostgreSQL is a service and keeps running.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$runRoot = Join-Path ([IO.Path]::GetFullPath($DataRoot)) "run"
foreach ($name in @("vision-worker", "api")) {
    $pidPath = Join-Path $runRoot "$name.pid"
    if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) { continue }
    $processId = [int](Get-Content -LiteralPath $pidPath -Raw).Trim()
    if (Get-Process -Id $processId -ErrorAction SilentlyContinue) {
        & taskkill.exe /PID $processId /T /F | Out-Null
        Write-Host ("{0,-26} {1}" -f $name, "stopped (pid $processId)")
    }
    Remove-Item -LiteralPath $pidPath -Force
}
