[CmdletBinding()]
param(
    # The installation's data root; its config\poc-installation.json names everything else.
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC"),
    # Print what would be removed; change nothing.
    [switch]$PlanOnly,
    # Required to remove anything: the database, media, evidence, faces and gallery cannot be recovered.
    [switch]$RemoveAllData
)

# MAVI poc-single-host uninstaller (PoC S6; ADR-022 section 5; register C5A.5). It removes what the
# installation recorded and nothing else:
#   1. stops MAVI (Stop-MaviPoc.ps1);
#   2. drops the installation's database and its role: every table goes with it, including the biometric
#      derivatives (face observations and embeddings, the enrolled gallery, transient face queries) and
#      the appearance embeddings;
#   3. removes the PostgreSQL service when this installation owns it (a shared Development instance used by a
#      rehearsal keeps running);
#   4. deletes the data root (evidence, media, logs, configuration, PostgreSQL data) and the install root.
# It then verifies that the database, the owned service and both roots are gone, and exits 1 if anything is
# left. Biometric derivatives never exist outside the database (ADR-022 section 4), so nothing else holds them.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force

Assert-MaviWindows
$DataRoot = [IO.Path]::GetFullPath($DataRoot.Trim().Trim('"'))
if ($DataRoot.Length -gt 3) { $DataRoot = $DataRoot.TrimEnd("\") }
$statePath = Join-Path $DataRoot "config\poc-installation.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
    throw "No MAVI PoC installation is recorded under '$DataRoot' ($statePath is missing). Nothing was removed."
}
$state = Read-MaviJson -Path $statePath
$machineConfigPath = Join-Path $DataRoot "config\appsettings.poc.machine.json"
if (-not (Test-Path -LiteralPath $machineConfigPath -PathType Leaf)) {
    throw "The installation's machine configuration '$machineConfigPath' is missing, so its database is unknown. Nothing was removed."
}
$connection = ConvertFrom-MaviPocConnectionString -ConnectionString ([string](Read-MaviJson -Path $machineConfigPath).ConnectionStrings.Mavi)
$serviceName = [string]$state.postgresqlServiceName
$service = $null
if (-not [string]::IsNullOrWhiteSpace($serviceName)) {
    $service = Get-CimInstance -ClassName Win32_Service -Filter ("Name='{0}'" -f $serviceName.Replace("'", "''")) -ErrorAction SilentlyContinue
}
$plan = New-MaviPocUninstallPlan -State $state -DataRoot $DataRoot -Connection $connection -Service $service

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 6
    return
}
if (-not $RemoveAllData) {
    throw "Uninstalling deletes the MAVI PoC database, media, evidence, face data and gallery permanently. Review -PlanOnly, then rerun with -RemoveAllData."
}
# Removing a service, or the Administrators-owned roots of an installation, needs elevation, as installing did.
if ($plan.postgresqlService.owned -or $plan.installRoot.StartsWith($env:ProgramFiles, [StringComparison]::OrdinalIgnoreCase)) {
    Assert-MaviAdministrator
}
foreach ($root in $plan.removeDirectories) {
    # Remove-Item would follow a junction inside the tree; the installer never creates one.
    Assert-MaviPocNoReparsePoint -Path $root -Recurse
}

Write-Host "MAVI PoC uninstall ($($plan.profile))"
Write-Host "========================================"
$remaining = @()

# 1. MAVI stops before its database disappears under it.
if (Test-Path -LiteralPath (Join-Path $plan.dataRoot "run") -PathType Container) {
    & (Join-Path $PSScriptRoot "Stop-MaviPoc.ps1") -DataRoot $plan.dataRoot
}
Write-MaviSetupStatus -Name "MAVI" -Status "OK" -Detail "stopped"

# 2. The database and its role.
$adminSecretPath = Join-Path $plan.dataRoot "setup\postgres-admin.dpapi"
$adminPassword = if (Test-Path -LiteralPath $adminSecretPath -PathType Leaf) { Unprotect-MaviSecret -Path $adminSecretPath }
    elseif (-not [string]::IsNullOrEmpty($env:PGPASSWORD)) { $env:PGPASSWORD }
    else { throw "No PostgreSQL administrator credential: '$adminSecretPath' is missing and PGPASSWORD is not set. Nothing was removed." }
$psql = [string]$plan.database.psql
if (-not (Test-Path -LiteralPath $psql -PathType Leaf)) { throw "psql was not found at '$psql'. Nothing was removed." }
$port = [int]$plan.database.port
$databaseIdentifier = ConvertTo-PgIdentifier -Value $plan.database.name
$databaseLiteral = ConvertTo-PgLiteral -Value $plan.database.name
Invoke-MaviPsql -PsqlPath $psql -Port $port -User "postgres" -Password $adminPassword -Database "postgres" -Sql "drop database if exists $databaseIdentifier with (force);"
Write-MaviSetupStatus -Name "Database" -Status "OK" -Detail "dropped $($plan.database.name) (all MAVI data, face observations, face embeddings, gallery, face queries)"
if ($plan.database.dropRole) {
    $roleIdentifier = ConvertTo-PgIdentifier -Value $plan.database.role
    try {
        Invoke-MaviPsql -PsqlPath $psql -Port $port -User "postgres" -Password $adminPassword -Database "postgres" -Sql "drop role if exists $roleIdentifier;"
        Write-MaviSetupStatus -Name "Database role" -Status "OK" -Detail "dropped $($plan.database.role)"
    }
    catch { Write-MaviSetupStatus -Name "Database role" -Status "WARN" -Detail "kept $($plan.database.role): $($_.Exception.Message)" }
}
$exists = (Invoke-MaviPsql -PsqlPath $psql -Port $port -User "postgres" -Password $adminPassword -Database "postgres" -Sql "select count(*) from pg_database where datname = $databaseLiteral;" -CaptureOutput).StandardOutput.Trim()
if ($exists -ne "0") { $remaining += "database $($plan.database.name)" }

# 3. The PostgreSQL service, only when this installation owns it.
if ($plan.postgresqlService.owned) {
    $name = [string]$plan.postgresqlService.name
    $running = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($running -and $running.Status -ne "Stopped") {
        Stop-Service -Name $name -Force -ErrorAction Stop
        $running.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(60))
    }
    Invoke-MaviCommand -FilePath "sc.exe" -Arguments @("delete", $name)
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    while ((Get-Service -Name $name -ErrorAction SilentlyContinue) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 500 }
    if (Get-Service -Name $name -ErrorAction SilentlyContinue) { $remaining += "service $name" }
    else { Write-MaviSetupStatus -Name "PostgreSQL service" -Status "OK" -Detail "removed $name" }
}
else {
    Write-MaviSetupStatus -Name "PostgreSQL service" -Status "INFO" -Detail "$($plan.postgresqlService.name) kept ($($plan.postgresqlService.reason))"
}

# 4. Both roots. The working directory moves out of them first, so this process holds nothing open there.
Set-Location -LiteralPath $env:SystemRoot
foreach ($root in $plan.removeDirectories) {
    if (Test-Path -LiteralPath $root) {
        try { Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction Stop }
        catch { Write-MaviSetupStatus -Name "Remove" -Status "FAIL" -Detail "$root ($($_.Exception.Message))" }
    }
    if (Test-Path -LiteralPath $root) { $remaining += "directory $root" }
    else { Write-MaviSetupStatus -Name "Directory" -Status "OK" -Detail "removed $root" }
}

Write-Host ""
if ($remaining.Count -gt 0) {
    Write-Host "MAVI PoC uninstall incomplete; still present: $($remaining -join '; ')." -ForegroundColor Red
    exit 1
}
Write-Host "MAVI PoC uninstalled: database $($plan.database.name) dropped, both roots removed, no face data or gallery remains." -ForegroundColor Green
exit 0
