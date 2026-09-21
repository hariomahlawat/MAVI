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
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

Assert-MaviWindows

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$defaults = Read-MaviJson -Path (Join-Path $repoRoot "config\setup\mavi-setup-defaults.json")
$profileDefaults = if ($Profile -eq "Development") { $defaults.development } else { $defaults.production }

$checks = New-Object System.Collections.Generic.List[object]
function Add-Check {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $checks.Add([pscustomobject]@{ Name = $Name; Passed = $Passed; Detail = $Detail })
}
function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$serviceName = [string]$profileDefaults.postgresqlServiceName
$port = [int]$profileDefaults.postgresqlPort
$service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
Add-Check -Name "PostgreSQL service" -Passed ($null -ne $service -and $service.Status -eq "Running") -Detail $(if ($service) { "$serviceName / $($service.Status)" } else { "$serviceName not installed" })

$programRoot = if ($Profile -eq "Development") { Join-Path $env:ProgramFiles "MAVI\Development" } else { [string]$profileDefaults.installRoot }
$psqlPath = Join-Path $programRoot "PostgreSQL\18\bin\psql.exe"
Add-Check -Name "PostgreSQL runtime" -Passed (Test-Path -LiteralPath $psqlPath -PathType Leaf) -Detail $psqlPath

$machineConfigPath = if ($Profile -eq "Development") { Join-Path $env:ProgramData "MAVI\Development\config\appsettings.development.machine.json" } else { Join-Path ([string]$profileDefaults.programDataRoot) "config\appsettings.machine.json" }
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
        $versionNumber = [int]$server.StandardOutput.Trim()
        $major = [int][Math]::Floor($versionNumber / 10000)
        Add-Check -Name "PostgreSQL major version" -Passed ($major -eq 18) -Detail "PostgreSQL $major"
        $vector = Invoke-MaviPsql -PsqlPath $psqlPath -Port $dbPort -User $dbUser -Password $dbPassword -Database $dbName -Sql "select extversion from pg_extension where extname='vector';" -CaptureOutput
        $vectorVersion = $vector.StandardOutput.Trim()
        Add-Check -Name "pgvector" -Passed (-not [string]::IsNullOrWhiteSpace($vectorVersion)) -Detail $(if ($vectorVersion) { $vectorVersion } else { "not enabled" })
        Add-Check -Name "Managed media root" -Passed (Test-Path -LiteralPath ([string]$machineConfig.MediaStorage.RootPath) -PathType Container) -Detail ([string]$machineConfig.MediaStorage.RootPath)
        Add-Check -Name "Evidence root" -Passed (Test-Path -LiteralPath ([string]$machineConfig.MediaStorage.EvidenceRootPath) -PathType Container) -Detail ([string]$machineConfig.MediaStorage.EvidenceRootPath)
        $cursorKeyPresent = $null -ne (Get-MaviExistingCursorSigningKey -MachineConfigPath $machineConfigPath)
        Add-Check -Name "Search cursor signing key" -Passed $cursorKeyPresent -Detail $(if ($cursorKeyPresent) { "TrackSearch:CursorSigningKey provisioned" } else { "missing or malformed; re-run Setup-MAVI" })
    }
    catch { Add-Check -Name "Database connectivity" -Passed $false -Detail $_.Exception.Message }
}

if ($Profile -eq "Development") {
    Add-Check -Name ".NET 10 SDK" -Passed (Test-MaviDotNet10Sdk) -Detail "developer prerequisite"
    Add-Check -Name "Node.js 22" -Passed (Test-MaviNode22) -Detail "developer prerequisite"
    Add-Check -Name "Python 3.13+" -Passed (Test-MaviPython313) -Detail "developer prerequisite"
    $testConnection = [Environment]::GetEnvironmentVariable("MAVI_TEST_DB_CONNECTION", [System.EnvironmentVariableTarget]::Machine)
    Add-Check -Name "Integration test connection" -Passed (-not [string]::IsNullOrWhiteSpace($testConnection)) -Detail "MAVI_TEST_DB_CONNECTION"

    try {
        $runtimeRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", "Machine")
        if ([string]::IsNullOrWhiteSpace($runtimeRoot)) { $runtimeRoot = "C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu" }
        $runtimeStatePath = Join-Path $runtimeRoot "runtime-install.json"
        $runtimeManifestPath = Join-Path $runtimeRoot "runtime-pack-manifest.json"
        $runtimeState = Read-MaviJson -Path $runtimeStatePath
        $runtimeManifest = Read-MaviJson -Path $runtimeManifestPath
        [void](Assert-MaviVisionRuntimePackManifest -Manifest $runtimeManifest)
        $runtimeStateValid = ([string]$runtimeState.schemaVersion -eq "mavi-vision-runtime-install-v2") -and ((Get-Sha256 $runtimeManifestPath) -eq ([string]$runtimeState.runtimePackManifestSha256).ToLowerInvariant())
        Add-Check -Name "Vision Runtime Pack state" -Passed $runtimeStateValid -Detail ([string]$runtimeManifest.runtimePackId)

        $modelRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_MODEL_ROOT", "Machine")
        if ([string]::IsNullOrWhiteSpace($modelRoot)) { $modelRoot = "C:\ProgramData\MAVI\Development\VisionModels\rtmdet-m-coco-phase1" }
        $modelStatePath = Join-Path $modelRoot "model-install.json"
        $modelManifestPath = Join-Path $modelRoot "model-pack-manifest.json"
        $modelState = Read-MaviJson -Path $modelStatePath
        $modelManifest = Read-MaviJson -Path $modelManifestPath
        [void](Assert-MaviVisionModelPackManifest -Manifest $modelManifest)
        $modelStateValid = ([string]$modelState.schemaVersion -eq "mavi-vision-model-install-v1") -and ((Get-Sha256 $modelManifestPath) -eq ([string]$modelState.modelPackManifestSha256).ToLowerInvariant())
        Add-Check -Name "Vision Model Pack state" -Passed $modelStateValid -Detail ([string]$modelManifest.modelPackId)

        $componentPath = Join-Path $repoRoot "src\vision\config\components\mmdetection-phase1-v1.json"
        $component = Read-MaviJson -Path $componentPath
        if ([string]$component.schemaVersion -ne "mavi-vision-component-requirements-v1") { throw "unsupported component requirements schema" }
        $requiredRuntime = $component.runtimePacks."windows-x86_64-cpu"
        $requiredModel = $component.modelPack
        $compatible = Assert-MaviVisionWorkerComponentCompatibility `
            -RuntimeState $runtimeState -RuntimeManifest $runtimeManifest `
            -RequiredRuntimePackId ([string]$requiredRuntime.runtimePackId) `
            -RequiredThirdPartyLockSha256 ([string]$requiredRuntime.thirdPartyLockSha256) `
            -RequiredRuntimeRequirementsSha256 ([string]$requiredRuntime.runtimeRequirementsSha256) `
            -ModelState $modelState -ModelManifest $modelManifest `
            -RequiredModelPackId ([string]$requiredModel.modelPackId) `
            -RequiredModelId ([string]$requiredModel.modelId) `
            -RequiredCheckpointSha256 ([string]$requiredModel.checkpointSha256) `
            -RequiredResolvedConfigSha256 ([string]$requiredModel.resolvedConfigSha256)
        Add-Check -Name "Vision component compatibility" -Passed ([bool]$compatible) -Detail "Runtime Pack + Model Pack match current application overlay"
    }
    catch {
        Add-Check -Name "Vision component compatibility" -Passed $false -Detail $_.Exception.Message
    }
}
else {
    $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    Add-Check -Name "IIS" -Passed (Test-Path -LiteralPath $appCmd -PathType Leaf) -Detail $appCmd
    $hostingModule = Join-Path $env:ProgramFiles "IIS\Asp.Net Core Module\V2\aspnetcorev2.dll"
    Add-Check -Name "ASP.NET Core Module" -Passed (Test-Path -LiteralPath $hostingModule -PathType Leaf) -Detail $hostingModule
    if ($HttpPort -eq 0) { $HttpPort = [int]$profileDefaults.httpPort }
    $baseUrl = "http://127.0.0.1:$HttpPort"
    try {
        $health = Invoke-RestMethod -Uri ($baseUrl + "/api/health") -Method Get -TimeoutSec 5
        Add-Check -Name "MAVI health" -Passed ([string]$health.status -eq "ok") -Detail "$baseUrl / $($health.build)"
    }
    catch { Add-Check -Name "MAVI health" -Passed $false -Detail $_.Exception.Message }
}

$checks | Format-Table -AutoSize
$failed = @($checks | Where-Object { -not $_.Passed })
if ($failed.Count -gt 0) {
    Write-Error "MAVI $Profile environment verification failed: $($failed.Count) check(s) failed."
    exit 1
}
Write-Host ""
Write-Host "MAVI $Profile environment verification PASSED."
