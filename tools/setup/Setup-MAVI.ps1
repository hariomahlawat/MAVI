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
if (-not $PlanOnly) {
    Assert-MaviAdministrator
}

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
$BundleRoot = [IO.Path]::GetFullPath($BundleRoot.Trim().Trim('"'))

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
    if (Test-Path -LiteralPath (Join-Path $candidate "MAVI.sln") -PathType Leaf) {
        $RepositoryRoot = $candidate
    }
}
elseif ($RepositoryRoot) {
    # Defensive normalization for quoted/trailing-separator arguments from cmd.exe.
    # A quoted Windows path ending in "\" can otherwise arrive with a literal
    # quote and later make Test-Path report "Illegal characters in path".
    $RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
}

$bundleManifestPath = Join-Path $BundleRoot "mavi-offline-bundle.json"
$binaryKitManifestPath = Join-Path $BundleRoot "mavi-offline-binary-kit.json"
if ($Profile -eq "Production" -and -not (Test-Path -LiteralPath $bundleManifestPath -PathType Leaf)) {
    throw "Production setup requires the canonical MAVI offline setup bundle and its manifest."
}
if (Test-Path -LiteralPath $bundleManifestPath -PathType Leaf) {
    [void](Test-MaviManifest -Root $BundleRoot -ManifestPath $bundleManifestPath -ExpectedSchemaVersion "mavi-offline-setup-bundle-v1")
    Write-MaviSetupStatus -Name "Offline bundle" -Status "OK" -Detail "SHA-256 verified"
}
elseif ($Profile -eq "Development" -and -not $PlanOnly -and
        -not (Test-Path -LiteralPath $binaryKitManifestPath -PathType Leaf)) {
    throw "Development setup requires a verified MAVI-Offline-Binary-Kit beside the repository (or a canonical setup bundle). Loose vendor staging is release-preparation input, not a target-machine setup source."
}
elseif (Test-Path -LiteralPath $binaryKitManifestPath -PathType Leaf) {
    if ($Profile -ne "Development") {
        throw "The MAVI offline binary kit is a preparation/Development dependency source, not a Production application bundle."
    }
    & (Join-Path $PSScriptRoot "Test-MaviOfflineBinaryKit.ps1") -KitRoot $BundleRoot

    if ($RepositoryRoot) {
        $kitManifest = Read-MaviJson -Path $binaryKitManifestPath
        $repositoryInputs = [ordered]@{
            offlineDependencyPolicy = (Join-Path $RepositoryRoot "config\dependencies\offline-dependency-policy-v1.json")
            offlineBinaryCatalog = (Join-Path $RepositoryRoot "config\dependencies\offline-binary-catalog-v1.json")
            globalJson = (Join-Path $RepositoryRoot "global.json")
            webPackageLock = (Join-Path $RepositoryRoot "src\web\mavi-web\package-lock.json")
            visionPyproject = (Join-Path $RepositoryRoot "src\vision\pyproject.toml")
            toolsRequirements = (Join-Path $RepositoryRoot "tools\requirements.txt")
        }
        foreach ($entry in $repositoryInputs.GetEnumerator()) {
            $expectedProperty = $kitManifest.sourceInputs.PSObject.Properties[$entry.Key]
            $expected = if ($expectedProperty) { [string]$expectedProperty.Value } else { "" }
            $actual = Get-MaviSha256 -Path $entry.Value
            if ($expected -ne $actual) {
                throw "MAVI-Offline-Binary-Kit is stale for this source repository: $($entry.Key) does not match. Rebuild or obtain the matching binary kit."
            }
        }
    }

    Write-MaviSetupStatus -Name "Offline binary kit" -Status "OK" -Detail "catalog/nested manifests/source inputs/SHA-256 verified"
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
    if ($DataRoot) {
        $mediaRoot = Join-Path $DataRoot "Media"
        $evidenceRoot = Join-Path $DataRoot "Evidence"
    }
    else {
        $configuredMediaRoot = [string]$profileDefaults.mediaRoot
        $configuredEvidenceRoot = [string]$profileDefaults.evidenceRoot
        $configuredDrive = [IO.Path]::GetPathRoot($configuredMediaRoot)
        if ($configuredDrive -and (Test-Path -LiteralPath $configuredDrive -PathType Container)) {
            $mediaRoot = $configuredMediaRoot
            $evidenceRoot = $configuredEvidenceRoot
        }
        else {
            $mediaRoot = Join-Path $programDataRoot "Data"
            $evidenceRoot = Join-Path $programDataRoot "Evidence"
        }
    }
    $machineConfigPath = Join-Path $programDataRoot "config\appsettings.development.machine.json"
    $setupRoot = Join-Path $programDataRoot "setup"
}
else {
    $programRoot = [string]$profileDefaults.installRoot
    $programDataRoot = [string]$profileDefaults.programDataRoot
    $postgresInstallRoot = Join-Path $programRoot "PostgreSQL\18"
    $postgresDataRoot = Join-Path $programDataRoot "PostgreSQL\18\data"
    $databaseName = [string]$profileDefaults.databaseName
    $databaseUser = [string]$profileDefaults.databaseUser
    $productionDataRoot = if ($DataRoot) { $DataRoot } else { $programDataRoot }
    $mediaRoot = Join-Path $productionDataRoot "Data"
    $evidenceRoot = Join-Path $productionDataRoot "Evidence"
    $machineConfigPath = Join-Path $programDataRoot "config\appsettings.machine.json"
    $setupRoot = Join-Path $programDataRoot "setup"
    if ($HttpPort -eq 0) {
        $HttpPort = [int]$profileDefaults.httpPort
    }

    $adminSecretPath = Join-Path $setupRoot "postgres-admin.dpapi"
    $appSecretPath = Join-Path $setupRoot "mavi-app.dpapi"
    if ($PlanOnly) {
        $adminPassword = $null
        $databasePassword = $null
    }
    else {
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
}

$runtimePackRoot = Join-Path $BundleRoot "prerequisites\postgresql\pg18\win-x64"
if (-not (Test-Path -LiteralPath (Join-Path $runtimePackRoot "manifest.json") -PathType Leaf) -and
    (Test-Path -LiteralPath $binaryKitManifestPath -PathType Leaf)) {
    $runtimePackRoot = Join-Path $BundleRoot "vendor\postgresql\pg18\win-x64"
}
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
    $plan["iis"] = [ordered]@{
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
if ($Profile -eq "Production") {
    Set-MaviPrivateDirectoryAcl -Path $setupRoot
}
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
        Ensure-MaviDeveloperToolchain -BundleRoot $BundleRoot -RepositoryRoot $RepositoryRoot
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
    if ($Profile -eq "Development") {
        Set-MaviDirectoryAcl -Path $mediaRoot -Identity "*S-1-5-11" -Rights "M"
        Set-MaviDirectoryAcl -Path $evidenceRoot -Identity "*S-1-5-11" -Rights "M"
    }

    $connectionString = "Host=127.0.0.1;Port=$port;Database=$databaseName;Username=$databaseUser;Password=$databasePassword"
    $developmentFfmpegPack = Join-Path $BundleRoot "application\tools\ffmpeg"
    if (-not (Test-Path -LiteralPath (Join-Path $developmentFfmpegPack "manifest.json") -PathType Leaf) -and
        (Test-Path -LiteralPath $binaryKitManifestPath -PathType Leaf)) {
        $developmentFfmpegPack = Join-Path $BundleRoot "vendor\ffmpeg"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $developmentFfmpegPack "manifest.json") -PathType Leaf) -and $RepositoryRoot) {
        $repositoryFfmpeg = Join-Path $RepositoryRoot "vendor\ffmpeg"
        if (Test-Path -LiteralPath (Join-Path $repositoryFfmpeg "manifest.json") -PathType Leaf) {
            $developmentFfmpegPack = $repositoryFfmpeg
        }
    }
    $hasDevelopmentFfmpegPack = Test-Path -LiteralPath (Join-Path $developmentFfmpegPack "manifest.json") -PathType Leaf
    if ($Profile -eq "Development" -and -not $hasDevelopmentFfmpegPack) {
        throw "The approved FFmpeg dependency pack is missing. Attach MAVI-Offline-Binary-Kit or stage vendor\ffmpeg before Development setup."
    }
    $machineConfig = [ordered]@{
        ConnectionStrings = [ordered]@{ Mavi = $connectionString }
        MediaStorage = [ordered]@{
            RootPath = $mediaRoot
            EvidenceRootPath = $evidenceRoot
        }
    }
    if ($Profile -eq "Development") {
        $machineConfig["MediaProcessing"] = [ordered]@{
            AllowPathFallbackInDevelopment = $false
        }
    }
    Write-MaviJson -Value $machineConfig -Path $machineConfigPath -Depth 8

    if ($Profile -eq "Production") {
        & icacls.exe $machineConfigPath /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to secure Production machine configuration."
        }
    }

    if ($Profile -eq "Development") {
        & icacls.exe $machineConfigPath /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" "*S-1-5-11:R" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to secure Development machine configuration."
        }

        [Environment]::SetEnvironmentVariable(
            "MAVI_TEST_DB_CONNECTION",
            "Host=127.0.0.1;Port=$port;Database=$testDatabaseName;Username=$databaseUser;Password=$databasePassword",
            [System.EnvironmentVariableTarget]::Machine)
        $env:MAVI_TEST_DB_CONNECTION = "Host=127.0.0.1;Port=$port;Database=$testDatabaseName;Username=$databaseUser;Password=$databasePassword"

        if ($RepositoryRoot) {
            $bundleFfmpeg = $developmentFfmpegPack
            $repoFfmpeg = Join-Path $RepositoryRoot "vendor\ffmpeg"
            [void](Test-MaviManifest -Root $bundleFfmpeg -ManifestPath (Join-Path $bundleFfmpeg "manifest.json"))
            New-Item -ItemType Directory -Path $repoFfmpeg -Force | Out-Null
            Invoke-MaviCommand -FilePath "robocopy.exe" -Arguments @($bundleFfmpeg, $repoFfmpeg, "/MIR", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/NFL", "/NDL", "/NP") -AllowedExitCodes @(0,1,2,3,4,5,6,7)
            Write-MaviSetupStatus -Name "FFmpeg / ffprobe" -Status "OK" -Detail "verified and staged app-local dependency pack"
        }

        $developerCacheRoot = Join-Path $BundleRoot "prerequisites\developer\win-x64"
        if (-not (Test-Path -LiteralPath (Join-Path $developerCacheRoot "nuget-packages") -PathType Container) -and
            (Test-Path -LiteralPath $binaryKitManifestPath -PathType Leaf)) {
            $developerCacheRoot = Join-Path $BundleRoot "vendor\developer-cache\win-x64"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $developerCacheRoot "nuget-packages") -PathType Container) -and $RepositoryRoot) {
            $developerCacheRoot = Join-Path $RepositoryRoot "vendor\developer-cache\win-x64"
        }
        $hasOfflineCaches =
            (Test-Path -LiteralPath (Join-Path $developerCacheRoot "nuget-packages") -PathType Container) -and
            (Test-Path -LiteralPath (Join-Path $developerCacheRoot "npm-cache") -PathType Container) -and
            (Test-Path -LiteralPath (Join-Path $developerCacheRoot "python-wheelhouse") -PathType Container)

        if ($RepositoryRoot -and $hasOfflineCaches) {
            Initialize-MaviDeveloperWorkspace -BundleRoot $BundleRoot -RepositoryRoot $RepositoryRoot
            Write-MaviSetupStatus -Name "Offline dependencies" -Status "OK" -Detail "NuGet / npm / Python restored"
            Write-MaviSetupStatus -Name "Workspace validation" -Status "OK" -Detail ".NET / frontend / Python tests"
        }
        elseif (-not $RepositoryRoot) {
            Write-MaviSetupStatus -Name "Workspace validation" -Status "INFO" -Detail "repository not attached; rerun with -RepositoryRoot after copying source"
        }
        else {
            Write-MaviSetupStatus -Name "Workspace validation" -Status "WARN" -Detail "developer dependency cache not present in this non-canonical setup source"
        }

        if ($RepositoryRoot) {
            $visionBundleRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_BUNDLE_ROOT", "Process")
            if ([string]::IsNullOrWhiteSpace($visionBundleRoot)) {
                $visionBundleRoot = [Environment]::GetEnvironmentVariable("MAVI_VISION_BUNDLE_ROOT", "Machine")
            }
            if ([string]::IsNullOrWhiteSpace($visionBundleRoot)) {
                $visionBundleRoot = Join-Path (Split-Path $RepositoryRoot -Parent) "MAVI-Vision-Runtime-Bundle"
            }

            $visionManifest = Join-Path $visionBundleRoot "bundle-manifest.json"
            $nestedCpuVisionManifest = Join-Path $visionBundleRoot "windows-x86_64-cpu\bundle-manifest.json"
            $nestedCudaVisionManifest = Join-Path $visionBundleRoot "windows-x86_64-cuda\bundle-manifest.json"
            if ((Test-Path -LiteralPath $visionManifest -PathType Leaf) -or
                (Test-Path -LiteralPath $nestedCpuVisionManifest -PathType Leaf)) {
                & (Join-Path $PSScriptRoot "Install-MaviVisionRuntime.ps1") -BundleRoot $visionBundleRoot -RepositoryRoot $RepositoryRoot -Variant "windows-x86_64-cpu"
                Write-MaviSetupStatus -Name "Vision runtime CPU" -Status "OK" -Detail "qualified Windows CPU bundle installed"
            }
            else {
                Write-MaviSetupStatus -Name "Vision runtime CPU" -Status "INFO" -Detail "bundle not present; UI/API remain usable but CPU vision jobs stay queued until runtime is installed"
            }
            if (Test-Path -LiteralPath $nestedCudaVisionManifest -PathType Leaf) {
                & (Join-Path $PSScriptRoot "Install-MaviVisionRuntime.ps1") -BundleRoot $visionBundleRoot -RepositoryRoot $RepositoryRoot -Variant "windows-x86_64-cuda"
                Write-MaviSetupStatus -Name "Vision runtime CUDA" -Status "OK" -Detail "qualified Windows CUDA bundle installed"
            }
            else {
                Write-MaviSetupStatus -Name "Vision runtime CUDA" -Status "INFO" -Detail "qualified CUDA bundle not present; Development Auto will use CPU"
            }
        }

        Write-MaviSetupStatus -Name "Machine config" -Status "OK" -Detail $machineConfigPath
        Write-MaviSetupStatus -Name "Test connection" -Status "OK" -Detail "MAVI_TEST_DB_CONNECTION configured for this PC"
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
        Ensure-MaviIisAppPool -AppPoolName $appPoolName

        $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
        $existingPool = Invoke-MaviCommand -FilePath $appCmd -Arguments @("list", "apppool", "/name:$appPoolName") -CaptureOutput
        if (-not [string]::IsNullOrWhiteSpace($existingPool.StandardOutput)) {
            Invoke-MaviCommand -FilePath $appCmd -Arguments @("stop", "apppool", "/apppool.name:$appPoolName") -AllowedExitCodes @(0,183)
        }

        Copy-MaviApplication -Source $applicationSource -Destination $applicationRoot

        & icacls.exe $machineConfigPath /grant:r ("IIS AppPool\{0}:R" -f $appPoolName) | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to grant the MAVI application pool read access to machine configuration."
        }

        Set-MaviDirectoryAcl -Path $applicationRoot -Identity "IIS AppPool\$appPoolName" -Rights "R"
        Set-MaviPrivateDirectoryAcl -Path $mediaRoot -ApplicationIdentity "IIS AppPool\$appPoolName" -ApplicationRights "M"
        Set-MaviPrivateDirectoryAcl -Path $evidenceRoot -ApplicationIdentity "IIS AppPool\$appPoolName" -ApplicationRights "M"
        Set-MaviDirectoryAcl -Path (Split-Path $machineConfigPath -Parent) -Identity "IIS AppPool\$appPoolName" -Rights "R"

        Set-MaviIisSite -SiteName $siteName -AppPoolName $appPoolName -PhysicalPath $applicationRoot -HttpPort $HttpPort
        Ensure-MaviFirewallRule -HttpPort $HttpPort

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
        $result["baseUrl"] = "http://127.0.0.1:$HttpPort"
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
