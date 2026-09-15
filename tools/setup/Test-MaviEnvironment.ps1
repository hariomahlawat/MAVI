[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Development", "Production")]
    [string]$Profile,

    [int]$HttpPort = 0
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Windows.psm1") -Force

Assert-MaviWindows

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$defaults = Read-MaviJson -Path (Join-Path $repoRoot "config\setup\mavi-setup-defaults.json")
$profileDefaults = if ($Profile -eq "Development") { $defaults.development } else { $defaults.production }

$checks = New-Object System.Collections.Generic.List[object]
function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $checks.Add([pscustomobject]@{
        Name = $Name
        Passed = $Passed
        Detail = $Detail
    })
}

$serviceName = [string]$profileDefaults.postgresqlServiceName
$port = [int]$profileDefaults.postgresqlPort
$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
Add-Check -Name "PostgreSQL service" -Passed ($null -ne $service -and $service.Status -eq "Running") -Detail $(if ($service) { "$serviceName / $($service.Status)" } else { "$serviceName not installed" })

$programRoot = if ($Profile -eq "Development") {
    Join-Path $env:ProgramFiles "MAVI\Development"
}
else {
    [string]$profileDefaults.installRoot
}
$psqlPath = Join-Path $programRoot "PostgreSQL\18\bin\psql.exe"
Add-Check -Name "PostgreSQL runtime" -Passed (Test-Path -LiteralPath $psqlPath -PathType Leaf) -Detail $psqlPath

$machineConfigPath = if ($Profile -eq "Development") {
    Join-Path $env:LOCALAPPDATA "MAVI\config\appsettings.development.machine.json"
}
else {
    Join-Path ([string]$profileDefaults.programDataRoot) "config\appsettings.machine.json"
}
$machineConfigExists = Test-Path -LiteralPath $machineConfigPath -PathType Leaf
Add-Check -Name "Machine configuration" -Passed $machineConfigExists -Detail $machineConfigPath

if ($machineConfigExists -and (Test-Path -LiteralPath $psqlPath -PathType Leaf)) {
    $machineConfig = Read-MaviJson -Path $machineConfigPath
    $connection = [string]$machineConfig.ConnectionStrings.Mavi

    $parts = @{}
    foreach ($piece in $connection.Split(";")) {
        if ($piece.Contains("=")) {
            $pair = $piece.Split("=", 2)
            $parts[$pair[0].Trim().ToLowerInvariant()] = $pair[1]
        }
    }

    try {
        $dbPort = [int]$parts["port"]
        $dbName = [string]$parts["database"]
        $dbUser = [string]$parts["username"]
        $dbPassword = [string]$parts["password"]

        $server = Invoke-MaviPsql -PsqlPath $psqlPath -Port $dbPort -User $dbUser -Password $dbPassword -Database $dbName -Sql "select current_setting('server_version_num')::int;" -CaptureOutput
        $major = [int]$server.StandardOutput.Trim() / 10000
        Add-Check -Name "PostgreSQL major version" -Passed ($major -eq 18) -Detail "PostgreSQL $major"

        $vector = Invoke-MaviPsql -PsqlPath $psqlPath -Port $dbPort -User $dbUser -Password $dbPassword -Database $dbName -Sql "select extversion from pg_extension where extname='vector';" -CaptureOutput
        $vectorVersion = $vector.StandardOutput.Trim()
        Add-Check -Name "pgvector" -Passed (-not [string]::IsNullOrWhiteSpace($vectorVersion)) -Detail $(if ($vectorVersion) { $vectorVersion } else { "not enabled" })

        Add-Check -Name "Managed media root" -Passed (Test-Path -LiteralPath ([string]$machineConfig.MediaStorage.RootPath) -PathType Container) -Detail ([string]$machineConfig.MediaStorage.RootPath)
        Add-Check -Name "Evidence root" -Passed (Test-Path -LiteralPath ([string]$machineConfig.MediaStorage.EvidenceRootPath) -PathType Container) -Detail ([string]$machineConfig.MediaStorage.EvidenceRootPath)
    }
    catch {
        Add-Check -Name "Database connectivity" -Passed $false -Detail $_.Exception.Message
    }
}

if ($Profile -eq "Development") {
    Add-Check -Name ".NET 10 SDK" -Passed (Test-MaviDotNet10Sdk) -Detail "developer prerequisite"
    Add-Check -Name "Node.js 22" -Passed (Test-MaviNode22) -Detail "developer prerequisite"
    Add-Check -Name "Python 3.13+" -Passed (Test-MaviPython313) -Detail "developer prerequisite"

    $testConnection = [Environment]::GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION", [System.EnvironmentVariableTarget]::User)
    Add-Check -Name "Integration test connection" -Passed (-not [string]::IsNullOrWhiteSpace($testConnection)) -Detail "MAVI_TEST_DB_CONNECTION"
}
else {
    $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    Add-Check -Name "IIS" -Passed (Test-Path -LiteralPath $appCmd -PathType Leaf) -Detail $appCmd

    $hostingModule = Join-Path $env:ProgramFiles "IIS\Asp.Net Core Module\V2\aspnetcorev2.dll"
    Add-Check -Name "ASP.NET Core Module" -Passed (Test-Path -LiteralPath $hostingModule -PathType Leaf) -Detail $hostingModule

    if ($HttpPort -eq 0) {
        $HttpPort = [int]$profileDefaults.httpPort
    }
    $baseUrl = "http://127.0.0.1:$HttpPort"
    try {
        $health = Invoke-RestMethod -Uri ($baseUrl + "/api/health") -Method Get -TimeoutSec 5
        Add-Check -Name "MAVI health" -Passed ([string]$health.status -eq "ok") -Detail "$baseUrl / $($health.build)"
    }
    catch {
        Add-Check -Name "MAVI health" -Passed $false -Detail $_.Exception.Message
    }
}

$checks | Format-Table -AutoSize
$failed = @($checks | Where-Object { -not $_.Passed })
if ($failed.Count -gt 0) {
    Write-Error "MAVI $Profile environment verification failed: $($failed.Count) check(s) failed."
    exit 1
}

Write-Host ""
Write-Host "MAVI $Profile environment verification PASSED."
