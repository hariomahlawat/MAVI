[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Development", "Production")]
    [string]$Profile,

    [string]$BundleRoot,
    [string]$RepositoryRoot,
    [string]$DataRoot,
    [int]$HttpPort = 0,
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Windows.psm1") -Force

Assert-MaviWindows
Assert-MaviAdministrator

if ([string]::IsNullOrWhiteSpace($BundleRoot)) {
    $bundleCandidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
    $repositoryCandidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
    $BundleRoot = if (Test-Path -LiteralPath (Join-Path $bundleCandidate "mavi-offline-bundle.json") -PathType Leaf) {
        $bundleCandidate
    }
    else {
        $repositoryCandidate
    }
}
$BundleRoot = [IO.Path]::GetFullPath($BundleRoot)

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
    if (Test-Path -LiteralPath (Join-Path $candidate "MAVI.sln") -PathType Leaf) {
        $RepositoryRoot = $candidate
    }
}

$bundleManifestPath = Join-Path $BundleRoot "mavi-offline-bundle.json"
if (Test-Path -LiteralPath $bundleManifestPath -PathType Leaf) {
    [void](Test-MaviManifest -Root $BundleRoot -ManifestPath $bundleManifestPath -ExpectedSchemaVersion "mavi-offline-setup-bundle-v1")
    Write-MaviSetupStatus -Name "Offline bundle" -Status "OK" -Detail "SHA-256 verified"
}

$bundleDefaults = Join-Path $BundleRoot "config\mavi-setup-defaults.json"
$repoDefaults = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\config\setup\mavi-setup-defaults.json"))
$defaultsPath = if (Test-Path -LiteralPath $bundleDefaults -PathType Leaf) { $bundleDefaults } else { $repoDefaults }
$defaults = Read-MaviJson -Path $defaultsPath
if ([string]$defaults.schemaVersion -ne "mavi-setup-defaults-v1") {
    throw "Unsupported MAVI setup defaults schema."
}

$profileDefaults = if ($Profile -eq "Development") { $defaults.development } else { $defaults.production }
$port = [int]$profileDefaults.postgresqlPort
$serviceName = [string]$profileDefaults.postgresqlServiceName

if ($Profile -eq "Development") {
    $programRoot = Join-Path $env:ProgramFiles "MAVI\Development"
    $programDataRoot = Join-Path $env:ProgramData "MAVI\Development"
    $postgresInstallRoot = Join-Path $programRoot "PostgreSQL\18"
    $postgresDataRoot = Join-Path $programDataRoot "PostgreSQL\18\data"
    $databaseName = [string]$profileDefaults.databaseName
    $testDatabaseName = [string]$profileDefaults.testDatabaseName
    $databaseUser = [string]$profileDefaults.postgresqlAdminUser
    $adminPassword = [string]$profileDefaults.postgresqlAdminPassword
    $databasePassword = $adminPassword
    $mediaRoot = if ($DataRoot) { Join-Path $DataRoot "Media" } else { [string]$profileDefaults.mediaRoot }
    $evidenceRoot = if ($DataRoot) { Join-Path $DataRoot "Evidence" } else { [string]$profileDefaults.evidenceRoot }
    $machineConfigPath = Join-Path $env:LOCALAPPDATA "MAVI\config\appsettings.development.machine.json"
    $setupRoot = Join-Path $env:LOCALAPPDATA "MAVI\setup"
}
else {
    $programRoot = [string]$profileDefaults.installRoot
    $programDataRoot = [string]$profileDefaults.programDataRoot
    $postgresInstallRoot = Join-Path $programRoot "PostgreSQL\18"
    $postgresDataRoot = Join-Path $programDataRoot "PostgreSQL\18\data"
    $databaseName = [string]$profileDefaults.databaseName
    $databaseUser = [string]$profileDefaults.databaseUser
    $mediaRoot = if ($DataRoot) { Join-Path $DataRoot "Media" } else { Join-Path $programDataRoot "Data" }
    $evidenceRoot = if ($DataRoot) { Join-Path $DataRoot "Evidence" } else { Join-Path $programDataRoot "Evidence" }
    $machineConfigPath = Join-Path $programDataRoot "config\appsettings.machine.json"
    $setupRoot = Join-Path $programDataRoot "setup"
    if ($HttpPort -eq 0) {
        $HttpPort = [int]$profileDefaults.httpPort
    }

    $adminSecretPath = Join-Path $setupRoot "postgres-admin.dpapi"
    $appSecretPath = Join-Path $setupRoot "mavi-app.dpapi"
    $adminPassword = if (Test-Path -LiteralPath $adminSecretPath -PathType Leaf) {
        Unprotect-MaviSecret -Path $adminSecretPath
    }
    else {
        $value = New-MaviPassword
        Protect-MaviSecret -PlainText $value -Path $adminSecretPath
        $value
    }
    $databasePassword = if (Test-Path -LiteralPath $appSecretPath -PathType Leaf) {
        Unprotect-MaviSecret -Path $appSecretPath
    }
    else {
        $value = New-MaviPassword
        Protect-MaviSecret -PlainText $value -Path $appSecretPath
        $value
    }
}

$runtimePackRoot = Join-Path $BundleRoot "prerequisites\postgresql\pg18\win-x64"
if (-not (Test-Path -LiteralPath (Join-Path $runtimePackRoot "manifest.json") -PathType Leaf) -and $RepositoryRoot) {
    $repoRuntime = Join-Path $RepositoryRoot "vendor\postgresql\pg18\win-x64"
    if (Test-Path -LiteralPath (Join-Path $repoRuntime "manifest.json") -PathType Leaf) {
        $runtimePackRoot = $repoRuntime
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $runtimePackRoot "manifest.json") -PathType Leaf)) {
    throw "MAVI PostgreSQL 18 runtime pack is missing. Build or attach the approved offline setup bundle."
}

$plan = [ordered]@{
    profile = $Profile
    bundleRoot = $BundleRoot
    postgresql = [ordered]@{
        serviceName = $serviceName
        port = $port
        installRoot = $postgresInstallRoot
        dataRoot = $postgresDataRoot
        runtimePack = $runtimePackRoot
    }
    database = $databaseName
    mediaRoot = $mediaRoot
    evidenceRoot = $evidenceRoot
    machineConfig = $machineConfigPath
}
if ($Profile -eq "Production") {
    $plan.iis = [ordered]@{
        siteName = [string]$profileDefaults.iisSiteName
        appPoolName = [string]$profileDefaults.iisAppPoolName
        httpPort = $HttpPort
        applicationRoot = Join-Path $programRoot "app"
    }
}

if ($PlanOnly) {
    $plan | ConvertTo-Json -Depth 8
    return
}

New-Item -ItemType Directory -Path $setupRoot -Force | Out-Null
$logRoot = Join-Path $setupRoot "logs"
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$logPath = Join-Path $logRoot ("setup-" + $Profile.ToLowerInvariant() + "-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")
Start-Transcript -LiteralPath $logPath -Force | Out-Null

$resultPath = Join-Path $setupRoot "last-setup-result.json"
$startedAt = [DateTimeOffset]::UtcNow
try {
    Write-Host ""
    Write-Host "MAVI $Profile environment setup"
    Write-Host "========================================"

    if ($Profile -eq "Development") {
        Ensure-MaviDeveloperToolchain -BundleRoot $BundleRoot
        Write-MaviSetupStatus -Name "Developer toolchain" -Status "OK" -Detail ".NET 10 / Node 22 / Python 3.13+"
    }

    $postgres = Install-MaviPostgreSqlInstance -RuntimePackRoot $runtimePackRoot -InstallRoot $postgresInstallRoot -DataRoot $postgresDataRoot -ServiceName $serviceName -Port $port -AdminPassword $adminPassword
    Write-MaviSetupStatus -Name "PostgreSQL 18" -Status "OK" -Detail "$serviceName @ 127.0.0.1:$port"
    Write-MaviSetupStatus -Name "pgvector" -Status "OK" -Detail ([string]$postgres.Manifest.pgvectorVersion)

    Initialize-MaviDatabase -PsqlPath $postgres.PsqlPath -Port $port -AdminPassword $adminPassword -DatabaseName $databaseName -DatabaseUser $databaseUser -DatabasePassword $databasePassword
    Write-MaviSetupStatus -Name $databaseName -Status "OK" -Detail "database ready"

    if ($Profile -eq "Development") {
        Initialize-MaviDatabase -PsqlPath $postgres.PsqlPath -Port $port -AdminPassword $adminPassword -DatabaseName $testDatabaseName -DatabaseUser $databaseUser -DatabasePassword $databasePassword
        Write-MaviSetupStatus -Name $testDatabaseName -Status "OK" -Detail "test database ready"
    }

    New-Item -ItemType Directory -Path $mediaRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null

    $connectionString = "Host=127.0.0.1;Port=$port;Database=$databaseName;Username=$databaseUser;Password=$databasePassword"
    $developmentFfmpegPack = Join-Path $BundleRoot "prerequisites\ffmpeg"
    $hasDevelopmentFfmpegPack = Test-Path -LiteralPath (Join-Path $developmentFfmpegPack "manifest.json") -PathType Leaf
    $machineConfig = [ordered]@{
        ConnectionStrings = [ordered]@{ Mavi = $connectionString }
        MediaStorage = [ordered]@{
            RootPath = $mediaRoot
            EvidenceRootPath = $evidenceRoot
        }
    }
    if ($Profile -eq "Development") {
        $machineConfig["MediaProcessing"] = [ordered]@{
            AllowPathFallbackInDevelopment = -not $hasDevelopmentFfmpegPack
        }
    }
    Write-MaviJson -Value $machineConfig -Path $machineConfigPath -Depth 8

    if ($Profile -eq "Development") {
        $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $machineConfigPath /inheritance:r /grant:r ("{0}:F" -f $currentIdentity) "Administrators:F" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to secure Development machine configuration."
        }

        [Environment]::SetEnvironmentVariable(
            "MAVI_TEST_DB_CONNECTION",
            "Host=127.0.0.1;Port=$port;Database=$testDatabaseName;Username=$databaseUser;Password=$databasePassword",
            [EnvironmentVariableTarget]::User)
        $env:MAVI_TEST_DB_CONNECTION = "Host=127.0.0.1;Port=$port;Database=$testDatabaseName;Username=$databaseUser;Password=$databasePassword"

        if ($RepositoryRoot) {
            $bundleFfmpeg = $developmentFfmpegPack
            $repoFfmpeg = Join-Path $RepositoryRoot "vendor\ffmpeg"
            if ($hasDevelopmentFfmpegPack) {
                [void](Test-MaviManifest -Root $bundleFfmpeg -ManifestPath (Join-Path $bundleFfmpeg "manifest.json"))
                New-Item -ItemType Directory -Path $repoFfmpeg -Force | Out-Null
                Invoke-MaviCommand -FilePath "robocopy.exe" -Arguments @($bundleFfmpeg, $repoFfmpeg, "/MIR", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/NFL", "/NDL", "/NP") -AllowedExitCodes @(0,1,2,3,4,5,6,7)
                Write-MaviSetupStatus -Name "FFmpeg / ffprobe" -Status "OK" -Detail "staged app-local dependency pack"
            }
            else {
                Write-MaviSetupStatus -Name "FFmpeg / ffprobe" -Status "WARN" -Detail "bundle pack absent; repository Development fallback may use PATH"
            }
        }

        Write-MaviSetupStatus -Name "Machine config" -Status "OK" -Detail $machineConfigPath
        Write-MaviSetupStatus -Name "Test connection" -Status "OK" -Detail "MAVI_TEST_DB_CONNECTION configured for current user"
        Write-Host ""
        Write-Host "Development environment ready. Restart Visual Studio once, then build/run MAVI."
    }
    else {
        $appPoolName = [string]$profileDefaults.iisAppPoolName
        $siteName = [string]$profileDefaults.iisSiteName
        $applicationRoot = Join-Path $programRoot "app"
        $applicationSource = Join-Path $BundleRoot "application"
        $hostingBundle = Join-Path $BundleRoot "prerequisites\hosting\win-x64\dotnet-hosting.exe"

        Enable-MaviIis
        Install-MaviHostingBundle -HostingBundlePath $hostingBundle

        $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
        $existingPool = Invoke-MaviCommand -FilePath $appCmd -Arguments @("list", "apppool", "/name:$appPoolName") -CaptureOutput
        if (-not [string]::IsNullOrWhiteSpace($existingPool.StandardOutput)) {
            Invoke-MaviCommand -FilePath $appCmd -Arguments @("stop", "apppool", "/apppool.name:$appPoolName") -AllowedExitCodes @(0,183)
        }

        Copy-MaviApplication -Source $applicationSource -Destination $applicationRoot

        Set-MaviDirectoryAcl -Path $applicationRoot -Identity "IIS AppPool\$appPoolName" -Rights "R"
        Set-MaviDirectoryAcl -Path $mediaRoot -Identity "IIS AppPool\$appPoolName" -Rights "M"
        Set-MaviDirectoryAcl -Path $evidenceRoot -Identity "IIS AppPool\$appPoolName" -Rights "M"
        Set-MaviDirectoryAcl -Path (Split-Path $machineConfigPath -Parent) -Identity "IIS AppPool\$appPoolName" -Rights "R"

        Set-MaviIisSite -SiteName $siteName -AppPoolName $appPoolName -PhysicalPath $applicationRoot -HttpPort $HttpPort

        $baseUrl = "http://127.0.0.1:$HttpPort"
        $health = Wait-MaviHealth -BaseUrl $baseUrl -TimeoutSeconds 120
        Write-MaviSetupStatus -Name "MAVI application" -Status "OK" -Detail "$($health.build) / $($health.commit)"
        Write-MaviSetupStatus -Name "Web endpoint" -Status "OK" -Detail $baseUrl
        Write-Host ""
        Write-Host "Production environment ready: $baseUrl"
    }

    $result = [ordered]@{
        schemaVersion = "mavi-setup-result-v1"
        profile = $Profile
        startedAtUtc = $startedAt.ToString("O")
        completedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        passed = $true
        postgresqlService = $serviceName
        postgresqlPort = $port
        database = $databaseName
        machineConfigPath = $machineConfigPath
        mediaRoot = $mediaRoot
        evidenceRoot = $evidenceRoot
        logPath = $logPath
    }
    if ($Profile -eq "Production") {
        $result.baseUrl = "http://127.0.0.1:$HttpPort"
    }
    Write-MaviJson -Value $result -Path $resultPath -Depth 8
}
catch {
    $failure = [ordered]@{
        schemaVersion = "mavi-setup-result-v1"
        profile = $Profile
        startedAtUtc = $startedAt.ToString("O")
        completedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        passed = $false
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
