Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Install-MaviPostgreSqlInstance {
    param(
        [Parameter(Mandatory = $true)][string]$RuntimePackRoot,
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$DataRoot,
        [Parameter(Mandatory = $true)][string]$ServiceName,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$AdminPassword
    )

    $manifestPath = Join-Path $RuntimePackRoot "manifest.json"
    $manifest = Test-MaviManifest -Root $RuntimePackRoot -ManifestPath $manifestPath -ExpectedSchemaVersion "mavi-postgresql-runtime-pack-v1"

    if ([int]$manifest.postgresqlMajorVersion -ne 18 -or [string]$manifest.runtimeId -ne "win-x64") {
        throw "The MAVI PostgreSQL runtime pack must be PostgreSQL 18 win-x64."
    }

    $existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existingService) {
        $escapedServiceName = $ServiceName.Replace("'", "''")
        $serviceRecord = Get-CimInstance -ClassName Win32_Service -Filter "Name='$escapedServiceName'" -ErrorAction Stop
        if ($serviceRecord.PathName.IndexOf($InstallRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
            $serviceRecord.PathName.IndexOf($DataRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
            throw "Service '$ServiceName' already exists but is not owned by this MAVI PostgreSQL installation."
        }
    }
    if (-not $existingService -and (Test-MaviTcpPortInUse -Port $Port)) {
        throw "Port $Port is already in use. MAVI will not reuse an unknown PostgreSQL instance."
    }

    $installedManifestPath = Join-Path $InstallRoot ".mavi-runtime-manifest.json"
    $sourceManifestHash = Get-MaviSha256 -Path $manifestPath
    $runtimeNeedsCopy = $true
    if (Test-Path -LiteralPath $installedManifestPath -PathType Leaf) {
        $installedManifestHash = Get-MaviSha256 -Path $installedManifestPath
        $runtimeNeedsCopy = $installedManifestHash -ne $sourceManifestHash
    }

    if ($runtimeNeedsCopy) {
        if ($existingService -and $existingService.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force -ErrorAction Stop
            $existingService.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
        }
        New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
        $copyArgs = @(
            $RuntimePackRoot,
            $InstallRoot,
            "/MIR",
            "/COPY:DAT",
            "/DCOPY:DAT",
            "/R:2",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NP",
            "/XF",
            "manifest.json",
            ".mavi-runtime-manifest.json"
        )
        Invoke-MaviCommand -FilePath "robocopy.exe" -Arguments $copyArgs -AllowedExitCodes @(0,1,2,3,4,5,6,7)
        Copy-Item -LiteralPath $manifestPath -Destination $installedManifestPath -Force
    }

    $postgresExe = Join-Path $InstallRoot "bin\postgres.exe"
    $pgCtlExe = Join-Path $InstallRoot "bin\pg_ctl.exe"
    $initDbExe = Join-Path $InstallRoot "bin\initdb.exe"
    $psqlExe = Join-Path $InstallRoot "bin\psql.exe"
    foreach ($required in @($postgresExe, $pgCtlExe, $initDbExe, $psqlExe)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Installed PostgreSQL runtime is incomplete: $required"
        }
    }

    $version = Invoke-MaviCommand -FilePath $postgresExe -Arguments @("--version") -CaptureOutput
    if ($version.StandardOutput -notmatch "PostgreSQL 18\.") {
        throw "Installed MAVI PostgreSQL runtime is not PostgreSQL 18."
    }

    $pgVersionPath = Join-Path $DataRoot "PG_VERSION"
    if (-not (Test-Path -LiteralPath $pgVersionPath -PathType Leaf)) {
        New-Item -ItemType Directory -Path $DataRoot -Force | Out-Null
        $passwordFile = Join-Path ([IO.Path]::GetTempPath()) ("mavi-pg-" + [Guid]::NewGuid().ToString("N") + ".txt")
        try {
            [IO.File]::WriteAllText($passwordFile, $AdminPassword + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
            Invoke-MaviCommand -FilePath $initDbExe -Arguments @(
                "-D", $DataRoot,
                "-U", "postgres",
                "--encoding=UTF8",
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
                "--pwfile=$passwordFile"
            )
        }
        finally {
            Remove-Item -LiteralPath $passwordFile -Force -ErrorAction SilentlyContinue
        }
    }

    $postgresqlConf = Join-Path $DataRoot "postgresql.conf"
    $managedConf = Join-Path $DataRoot "mavi.conf"
    $includeLine = "include_if_exists = 'mavi.conf'"
    $postgresqlText = Get-Content -LiteralPath $postgresqlConf -Raw
    if ($postgresqlText -notmatch "(?m)^\s*include_if_exists\s*=\s*'mavi\.conf'\s*$") {
        Add-Content -LiteralPath $postgresqlConf -Value ([Environment]::NewLine + $includeLine)
    }
    @(
        "# Managed by MAVI Setup. Do not edit manually.",
        "listen_addresses = '127.0.0.1'",
        "port = $Port",
        "password_encryption = 'scram-sha-256'",
        "max_connections = 100"
    ) | Set-Content -LiteralPath $managedConf -Encoding UTF8

    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if (-not $service) {
        Invoke-MaviCommand -FilePath $pgCtlExe -Arguments @("register", "-N", $ServiceName, "-D", $DataRoot, "-S", "auto")
        $service = Get-Service -Name $ServiceName -ErrorAction Stop
    }

    if ($service.Status -ne "Running") {
        Start-Service -Name $ServiceName -ErrorAction Stop
        $service.WaitForStatus("Running", [TimeSpan]::FromSeconds(30))
    }
    Wait-MaviTcpPort -Port $Port -TimeoutSeconds 60

    return [pscustomobject]@{
        Manifest = $manifest
        PsqlPath = $psqlExe
        InstallRoot = $InstallRoot
        DataRoot = $DataRoot
        ServiceName = $ServiceName
        Port = $Port
    }
}

function Initialize-MaviDatabase {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$AdminPassword,
        [Parameter(Mandatory = $true)][string]$DatabaseName,
        [Parameter(Mandatory = $true)][string]$DatabaseUser,
        [Parameter(Mandatory = $true)][string]$DatabasePassword
    )

    $roleIdentifier = ConvertTo-PgIdentifier -Value $DatabaseUser
    $roleLiteral = ConvertTo-PgLiteral -Value $DatabaseUser
    $passwordLiteral = ConvertTo-PgLiteral -Value $DatabasePassword
    $databaseIdentifier = ConvertTo-PgIdentifier -Value $DatabaseName
    $databaseLiteral = ConvertTo-PgLiteral -Value $DatabaseName

    $roleCheck = Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database "postgres" -Sql "select 1 from pg_roles where rolname = $roleLiteral;" -CaptureOutput
    if ($roleCheck.StandardOutput.Trim() -eq "1") {
        Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database "postgres" -Sql "alter role $roleIdentifier with login password $passwordLiteral;"
    }
    else {
        Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database "postgres" -Sql "create role $roleIdentifier with login password $passwordLiteral;"
    }

    $databaseCheck = Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database "postgres" -Sql "select 1 from pg_database where datname = $databaseLiteral;" -CaptureOutput
    if ($databaseCheck.StandardOutput.Trim() -ne "1") {
        Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database "postgres" -Sql "create database $databaseIdentifier owner $roleIdentifier;"
    }
    else {
        Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database "postgres" -Sql "alter database $databaseIdentifier owner to $roleIdentifier;"
    }

    Invoke-MaviPsql -PsqlPath $PsqlPath -Port $Port -User "postgres" -Password $AdminPassword -Database $DatabaseName -Sql "create extension if not exists vector;"
}

function Refresh-MaviProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::Machine)
    $user = [Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)
    $env:Path = (($machine, $user) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }) -join ";"
}

function Test-MaviDotNet10Sdk {
    $dotnet = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if (-not $dotnet) {
        return $false
    }
    $result = Invoke-MaviCommand -FilePath $dotnet.Source -Arguments @("--list-sdks") -CaptureOutput
    return $result.StandardOutput -match "(?m)^10\."
}

function Test-MaviNode22 {
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $node) {
        return $false
    }
    $result = Invoke-MaviCommand -FilePath $node.Source -Arguments @("--version") -CaptureOutput
    $match = [regex]::Match($result.StandardOutput.Trim(), "^v(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)")
    if (-not $match.Success) { return $false }
    $major = [int]$match.Groups["major"].Value
    $minor = [int]$match.Groups["minor"].Value
    return $major -eq 22 -and $minor -ge 13
}

function Test-MaviPython313 {
    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if (-not $python) {
        return $false
    }
    $result = Invoke-MaviCommand -FilePath $python.Source -Arguments @("--version") -CaptureOutput
    $match = [regex]::Match($result.StandardOutput, "Python\s+(?<major>\d+)\.(?<minor>\d+)")
    if (-not $match.Success) {
        return $false
    }
    $major = [int]$match.Groups["major"].Value
    $minor = [int]$match.Groups["minor"].Value
    return $major -eq 3 -and $minor -eq 13
}

function Ensure-MaviDeveloperToolchain {
    param([Parameter(Mandatory = $true)][string]$BundleRoot)

    $root = Join-Path $BundleRoot "prerequisites\developer\win-x64"

    if (-not (Test-MaviDotNet10Sdk)) {
        $installer = Join-Path $root "dotnet-sdk.exe"
        if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
            throw ".NET 10 SDK is missing and the offline developer installer was not found: $installer"
        }
        Invoke-MaviCommand -FilePath $installer -Arguments @("/install", "/quiet", "/norestart") -AllowedExitCodes @(0,3010)
        Refresh-MaviProcessPath
        if (-not (Test-MaviDotNet10Sdk)) {
            throw ".NET 10 SDK installation did not become available."
        }
    }

    if (-not (Test-MaviNode22)) {
        $installer = Join-Path $root "node.msi"
        if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
            throw "Node.js 22 is missing and the offline developer installer was not found: $installer"
        }
        Invoke-MaviCommand -FilePath "msiexec.exe" -Arguments @("/i", $installer, "/qn", "/norestart") -AllowedExitCodes @(0,3010)
        Refresh-MaviProcessPath
        if (-not (Test-MaviNode22)) {
            throw "Node.js 22 installation did not become available."
        }
    }

    if (-not (Test-MaviPython313)) {
        $installer = Join-Path $root "python.exe"
        if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
            throw "Python 3.13+ is missing and the offline developer installer was not found: $installer"
        }
        Invoke-MaviCommand -FilePath $installer -Arguments @("/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0") -AllowedExitCodes @(0,3010)
        Refresh-MaviProcessPath
        if (-not (Test-MaviPython313)) {
            throw "Python 3.13+ installation did not become available."
        }
    }

    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw "npm is unavailable after Node.js setup."
    }
}

function Initialize-MaviDeveloperWorkspace {
    param(
        [Parameter(Mandatory = $true)][string]$BundleRoot,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot
    )

    $solutionPath = Join-Path $RepositoryRoot "MAVI.sln"
    $webRoot = Join-Path $RepositoryRoot "src\web\mavi-web"
    $visionRoot = Join-Path $RepositoryRoot "src\vision"
    foreach ($required in @($solutionPath, (Join-Path $webRoot "package-lock.json"), (Join-Path $visionRoot "pyproject.toml"))) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "MAVI repository is incomplete for Development setup: $required"
        }
    }

    $bundleCacheRoot = Join-Path $BundleRoot "prerequisites\developer\win-x64"
    $localCacheRoot = Join-Path $env:ProgramData "MAVI\Development\developer-cache"
    $nugetSource = Join-Path $bundleCacheRoot "nuget-packages"
    $npmSource = Join-Path $bundleCacheRoot "npm-cache"
    $pythonSource = Join-Path $bundleCacheRoot "python-wheelhouse"

    foreach ($required in @($nugetSource, $npmSource, $pythonSource)) {
        if (-not (Test-Path -LiteralPath $required -PathType Container)) {
            throw "Canonical Development bundle is missing offline dependency cache: $required"
        }
    }

    $nugetLocal = Join-Path $localCacheRoot "nuget-packages"
    $npmLocal = Join-Path $localCacheRoot "npm-cache"
    $pythonLocal = Join-Path $localCacheRoot "python-wheelhouse"
    foreach ($copy in @(
        @{ Source = $nugetSource; Target = $nugetLocal },
        @{ Source = $npmSource; Target = $npmLocal },
        @{ Source = $pythonSource; Target = $pythonLocal }
    )) {
        New-Item -ItemType Directory -Path $copy.Target -Force | Out-Null
        Invoke-MaviCommand -FilePath "robocopy.exe" -Arguments @(
            [string]$copy.Source,
            [string]$copy.Target,
            "/MIR",
            "/COPY:DAT",
            "/DCOPY:DAT",
            "/R:2",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NP"
        ) -AllowedExitCodes @(0,1,2,3,4,5,6,7)
    }

    [Environment]::SetEnvironmentVariable("NUGET_PACKAGES", $nugetLocal, [System.EnvironmentVariableTarget]::Machine)
    $env:NUGET_PACKAGES = $nugetLocal

    Invoke-MaviCommand -FilePath "dotnet.exe" -Arguments @(
        "restore",
        $solutionPath,
        "--packages",
        $nugetLocal,
        "--ignore-failed-sources"
    )

    Push-Location $webRoot
    try {
        Invoke-MaviCommand -FilePath "npm.cmd" -Arguments @(
            "ci",
            "--offline",
            "--cache",
            $npmLocal
        )
        Invoke-MaviCommand -FilePath "npm.cmd" -Arguments @("run", "build")
    }
    finally {
        Pop-Location
    }

    $systemPython = (Get-Command python.exe -ErrorAction Stop).Source
    $venvRoot = Join-Path $RepositoryRoot ".venv"
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Invoke-MaviCommand -FilePath $systemPython -Arguments @("-m", "venv", $venvRoot)
    }

    Invoke-MaviCommand -FilePath $venvPython -Arguments @(
        "-m", "pip", "install",
        "--no-index",
        "--find-links", $pythonLocal,
        "setuptools>=75"
    )

    Push-Location $visionRoot
    try {
        Invoke-MaviCommand -FilePath $venvPython -Arguments @(
            "-m", "pip", "install",
            "--no-index",
            "--find-links", $pythonLocal,
            "--no-build-isolation",
            "-e", ".[dev]"
        )
        Invoke-MaviCommand -FilePath $venvPython -Arguments @("-m", "pytest", "-q")
    }
    finally {
        Pop-Location
    }

    Invoke-MaviCommand -FilePath "dotnet.exe" -Arguments @(
        "build",
        $solutionPath,
        "-c", "Debug",
        "--no-restore"
    )
}

function Enable-MaviIis {
    $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    if (Test-Path -LiteralPath $appCmd -PathType Leaf) {
        return
    }

    $features = @(
        "IIS-WebServerRole",
        "IIS-WebServer",
        "IIS-CommonHttpFeatures",
        "IIS-StaticContent",
        "IIS-DefaultDocument",
        "IIS-HttpErrors",
        "IIS-HttpLogging",
        "IIS-RequestFiltering",
        "IIS-ISAPIExtensions",
        "IIS-ISAPIFilter",
        "IIS-ManagementScriptingTools",
        "IIS-ManagementConsole"
    )
    foreach ($feature in $features) {
        Invoke-MaviCommand -FilePath "dism.exe" -Arguments @("/Online", "/Enable-Feature", "/FeatureName:$feature", "/All", "/NoRestart") -AllowedExitCodes @(0,3010)
    }

    if (-not (Test-Path -LiteralPath $appCmd -PathType Leaf)) {
        throw "IIS installation completed without appcmd.exe. A Windows restart may be required."
    }
}

function Install-MaviHostingBundle {
    param([Parameter(Mandatory = $true)][string]$HostingBundlePath)

    $module = Join-Path $env:ProgramFiles "IIS\Asp.Net Core Module\V2\aspnetcorev2.dll"
    if (Test-Path -LiteralPath $module -PathType Leaf) {
        return
    }
    if (-not (Test-Path -LiteralPath $HostingBundlePath -PathType Leaf)) {
        throw "ASP.NET Core Hosting Bundle is not installed and the offline installer is missing: $HostingBundlePath"
    }

    Invoke-MaviCommand -FilePath $HostingBundlePath -Arguments @("/install", "/quiet", "/norestart") -AllowedExitCodes @(0,3010)

    if (-not (Test-Path -LiteralPath $module -PathType Leaf)) {
        throw "ASP.NET Core Module V2 was not found after Hosting Bundle installation. A restart may be required."
    }
}

function Copy-MaviApplication {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        throw "MAVI application artifact directory is missing: $Source"
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Invoke-MaviCommand -FilePath "robocopy.exe" -Arguments @(
        $Source,
        $Destination,
        "/MIR",
        "/COPY:DAT",
        "/DCOPY:DAT",
        "/R:2",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NP"
    ) -AllowedExitCodes @(0,1,2,3,4,5,6,7)
}

function Ensure-MaviIisAppPool {
    param([Parameter(Mandatory = $true)][string]$AppPoolName)

    $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    $pool = Invoke-MaviCommand -FilePath $appCmd -Arguments @("list", "apppool", "/name:$AppPoolName") -CaptureOutput
    if ([string]::IsNullOrWhiteSpace($pool.StandardOutput)) {
        Invoke-MaviCommand -FilePath $appCmd -Arguments @("add", "apppool", "/name:$AppPoolName")
    }
    Invoke-MaviCommand -FilePath $appCmd -Arguments @("set", "apppool", "/apppool.name:$AppPoolName", "/managedRuntimeVersion:", "/startMode:AlwaysRunning")
}

function Set-MaviIisSite {
    param(
        [Parameter(Mandatory = $true)][string]$SiteName,
        [Parameter(Mandatory = $true)][string]$AppPoolName,
        [Parameter(Mandatory = $true)][string]$PhysicalPath,
        [Parameter(Mandatory = $true)][int]$HttpPort
    )

    $appCmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    Ensure-MaviIisAppPool -AppPoolName $AppPoolName

    $site = Invoke-MaviCommand -FilePath $appCmd -Arguments @("list", "site", "/name:$SiteName") -CaptureOutput
    if ([string]::IsNullOrWhiteSpace($site.StandardOutput)) {
        Invoke-MaviCommand -FilePath $appCmd -Arguments @("add", "site", "/name:$SiteName", "/bindings:http/*:$HttpPort:", "/physicalPath:$PhysicalPath")
    }
    else {
        $existingPath = Invoke-MaviCommand -FilePath $appCmd -Arguments @("list", "vdir", "$SiteName/", "/text:physicalPath") -CaptureOutput
        $observed = [Environment]::ExpandEnvironmentVariables($existingPath.StandardOutput.Trim())
        if ([string]::IsNullOrWhiteSpace($observed)) {
            throw "Existing IIS site '$SiteName' has no readable physical path."
        }
        $observedFull = [IO.Path]::GetFullPath($observed).TrimEnd("\")
        $expectedFull = [IO.Path]::GetFullPath($PhysicalPath).TrimEnd("\")
        if (-not [string]::Equals($observedFull, $expectedFull, [StringComparison]::OrdinalIgnoreCase)) {
            throw "IIS site '$SiteName' already exists and is not owned by this MAVI installation."
        }

        $bindings = Invoke-MaviCommand -FilePath $appCmd -Arguments @("list", "site", "/name:$SiteName", "/text:bindings") -CaptureOutput
        if ($bindings.StandardOutput -notmatch [regex]::Escape("http/*:$HttpPort:")) {
            throw "IIS site '$SiteName' exists with a different binding. Refusing to rewrite an existing site implicitly."
        }
    }

    Invoke-MaviCommand -FilePath $appCmd -Arguments @("set", "app", "$SiteName/", "/applicationPool:$AppPoolName")
    Invoke-MaviCommand -FilePath $appCmd -Arguments @("start", "apppool", "/apppool.name:$AppPoolName") -AllowedExitCodes @(0,183)
    Invoke-MaviCommand -FilePath $appCmd -Arguments @("start", "site", "/site.name:$SiteName") -AllowedExitCodes @(0,183)
}

function Wait-MaviHealth {
    param(
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [int]$TimeoutSeconds = 90
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = $null
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        try {
            $health = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + "/api/health") -Method Get -TimeoutSec 5
            if ([string]$health.status -eq "ok") {
                $root = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd("/") + "/") -Method Get -UseBasicParsing -TimeoutSec 5
                if ([int]$root.StatusCode -eq 200) {
                    return $health
                }
            }
        }
        catch {
            $lastError = $_
        }
        Start-Sleep -Seconds 2
    }
    $detail = if ($lastError) { $lastError.Exception.Message } else { "No healthy response." }
    throw "MAVI health verification timed out for $BaseUrl. $detail"
}

Export-ModuleMember -Function *
