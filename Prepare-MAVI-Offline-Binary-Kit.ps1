[CmdletBinding()]
param(
    [string]$PostgreSqlRoot = (Join-Path $env:ProgramFiles "PostgreSQL\18"),
    [switch]$InstallMissingToolchain,
    [switch]$KeepWorkingDirectory
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "MAVI.sln") -PathType Leaf)) {
    throw "Place this script in the MAVI repository root (the folder containing MAVI.sln) and run it again."
}

$commonModule = Join-Path $repoRoot "tools\setup\Mavi.Setup.Common.psm1"
Import-Module $commonModule -Force
Assert-MaviWindows

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$workspaceRoot = Split-Path $repoRoot -Parent
$destination = Join-Path $workspaceRoot "MAVI-Offline-Binary-Kit"
$zipPath = Join-Path $workspaceRoot "MAVI-Offline-Binary-Kit.zip"

$workRoot = Join-Path ([IO.Path]::GetTempPath()) ("MAVI-BinaryKit-" + [Guid]::NewGuid().ToString("N"))
$downloads = Join-Path $workRoot "downloads"
$extract = Join-Path $workRoot "extract"

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Download {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    $parent = Split-Path $OutFile -Parent
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }

    Write-Host "Downloading: $Uri"
    Invoke-WebRequest -Uri $Uri -OutFile $OutFile -UseBasicParsing -MaximumRedirection 10

    if (-not (Test-Path -LiteralPath $OutFile -PathType Leaf) -or
        (Get-Item -LiteralPath $OutFile).Length -le 0) {
        throw "Download produced no usable file: $Uri"
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Assert-Authenticode {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$SubjectPattern
    )

    $sig = Get-AuthenticodeSignature -LiteralPath $Path
    if ($sig.Status -ne "Valid") {
        throw "Authenticode validation failed for '$Path': $($sig.Status)"
    }

    $subject = if ($sig.SignerCertificate) { [string]$sig.SignerCertificate.Subject } else { "" }
    if ($SubjectPattern -and $subject -notmatch $SubjectPattern) {
        throw "Unexpected signer for '$Path': $subject"
    }

    Write-Host "Signature OK: $(Split-Path $Path -Leaf) [$subject]"
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::Machine)
    $user = [Environment]::GetEnvironmentVariable("Path", [EnvironmentVariableTarget]::User)
    $env:Path = (($machine, $user) | Where-Object { $_ }) -join ";"
}

function Test-DotNet10 {
    $cmd = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { return $false }
    return ((& $cmd.Source --list-sdks 2>$null | Out-String) -match "(?m)^10\.")
}

function Test-Node22 {
    $cmd = Get-Command node.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { return $false }
    $v = (& $cmd.Source --version 2>$null | Out-String).Trim()
    $m = [regex]::Match($v, "^v(?<major>\d+)\.(?<minor>\d+)\.")
    return $m.Success -and [int]$m.Groups["major"].Value -eq 22 -and [int]$m.Groups["minor"].Value -ge 13
}

function Resolve-Python313 {
    $candidates = @()
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
    $candidates += (Join-Path $env:ProgramFiles "Python313\python.exe")
    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe")

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not $candidate) { continue }
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        $v = (& $candidate --version 2>&1 | Out-String).Trim()
        if ($v -match "^Python\s+3\.13(\.|$)") { return [string]$candidate }
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $p = (& $py.Source -3.13 -c "import sys; print(sys.executable)" 2>$null | Out-String).Trim()
        if ($p -and (Test-Path -LiteralPath $p -PathType Leaf)) { return $p }
    }

    return $null
}

function Install-IfNeeded {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Test,
        [Parameter(Mandatory = $true)][string]$Installer,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    if (& $Test) {
        Write-Host "$Name already satisfies the MAVI baseline."
        return
    }

    if (-not $InstallMissingToolchain) {
        throw "$Name is missing/incompatible. Re-run with -InstallMissingToolchain."
    }

    Write-Host "Installing $Name on the connected preparation PC..."
    $p = Start-Process -FilePath $Installer -ArgumentList $Arguments -Wait -PassThru
    if ($p.ExitCode -notin @(0,3010)) {
        throw "$Name installer failed with exit code $($p.ExitCode)."
    }

    Refresh-ProcessPath
    if (-not (& $Test)) {
        throw "$Name still does not satisfy the MAVI baseline after installation."
    }
}

function Resolve-PostgresRoot {
    param([string]$Preferred)

    $candidates = New-Object System.Collections.Generic.List[string]

    function Add-Candidate {
        param([string]$Path)

        if ([string]::IsNullOrWhiteSpace($Path)) { return }

        try {
            $full = [IO.Path]::GetFullPath($Path.Trim('"'))
            if (-not $candidates.Contains($full)) {
                [void]$candidates.Add($full)
            }
        }
        catch {
            # Ignore malformed discovery candidates.
        }
    }

    # Explicit/default locations.
    Add-Candidate $Preferred
    Add-Candidate (Join-Path $env:ProgramFiles "PostgreSQL\18")

    $pf86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if ($pf86) {
        Add-Candidate (Join-Path $pf86 "PostgreSQL\18")
    }

    # PATH.
    $postgresCommand = Get-Command postgres.exe -ErrorAction SilentlyContinue
    if ($postgresCommand -and $postgresCommand.Source) {
        Add-Candidate (Split-Path (Split-Path $postgresCommand.Source -Parent) -Parent)
    }

    # Running postgres.exe processes.
    try {
        foreach ($process in @(Get-CimInstance Win32_Process -Filter "Name='postgres.exe'" -ErrorAction Stop)) {
            if ($process.ExecutablePath) {
                Add-Candidate (Split-Path (Split-Path $process.ExecutablePath -Parent) -Parent)
            }
        }
    }
    catch {
        Write-Verbose "Unable to inspect running PostgreSQL processes: $($_.Exception.Message)"
    }

    # Registered PostgreSQL Windows services.
    try {
        foreach ($service in @(Get-CimInstance Win32_Service -ErrorAction Stop | Where-Object {
            $_.Name -match "postgres" -or $_.DisplayName -match "PostgreSQL"
        })) {
            $pathName = [string]$service.PathName
            if (-not $pathName) { continue }

            $exePath = $null

            $quoted = [regex]::Match(
                $pathName,
                '^\s*"(?<exe>[^"]*postgres\.exe)"',
                [Text.RegularExpressions.RegexOptions]::IgnoreCase)

            if ($quoted.Success) {
                $exePath = $quoted.Groups["exe"].Value
            }
            else {
                $plain = [regex]::Match(
                    $pathName,
                    '^\s*(?<exe>\S*postgres\.exe)\b',
                    [Text.RegularExpressions.RegexOptions]::IgnoreCase)

                if ($plain.Success) {
                    $exePath = $plain.Groups["exe"].Value
                }
            }

            if ($exePath) {
                Add-Candidate (Split-Path (Split-Path $exePath -Parent) -Parent)
            }
        }
    }
    catch {
        Write-Verbose "Unable to inspect PostgreSQL Windows services: $($_.Exception.Message)"
    }

    # PostgreSQL installer registry entries.
    foreach ($registryRoot in @(
        "HKLM:\SOFTWARE\PostgreSQL\Installations",
        "HKLM:\SOFTWARE\WOW6432Node\PostgreSQL\Installations"
    )) {
        if (-not (Test-Path -LiteralPath $registryRoot)) { continue }

        foreach ($key in @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)) {
            try {
                $props = Get-ItemProperty -LiteralPath $key.PSPath -ErrorAction Stop

                foreach ($propertyName in @("Base Directory", "BaseDirectory")) {
                    $property = $props.PSObject.Properties[$propertyName]
                    if ($property -and $property.Value) {
                        Add-Candidate ([string]$property.Value)
                    }
                }
            }
            catch {
                Write-Verbose "Unable to inspect PostgreSQL registry key: $($_.Exception.Message)"
            }
        }
    }

    $postgres18Roots = New-Object System.Collections.Generic.List[string]

    foreach ($candidate in $candidates) {
        $postgres = Join-Path $candidate "bin\postgres.exe"
        if (-not (Test-Path -LiteralPath $postgres -PathType Leaf)) { continue }

        $version = (& $postgres --version 2>&1 | Out-String).Trim()
        Write-Host "PostgreSQL candidate: $candidate"
        Write-Host "  postgres.exe reports: $version"

        # Standard postgres output is normally:
        #   postgres (PostgreSQL) 18.x
        # Do not require "PostgreSQL 18.x" to be directly adjacent.
        if ($version -notmatch '(?i)\bPostgreSQL\b.*\b18(?:\.|\b)') {
            Write-Host "  skipped: not PostgreSQL major version 18"
            continue
        }

        [void]$postgres18Roots.Add($candidate)

        $vector = Join-Path $candidate "share\extension\vector.control"
        if (Test-Path -LiteralPath $vector -PathType Leaf) {
            Write-Host "  pgvector control: $vector" -ForegroundColor Green
            Write-Host "Detected PostgreSQL 18 + pgvector: $candidate" -ForegroundColor Green
            return $candidate
        }

        Write-Host "  PostgreSQL 18 found, but pgvector control file is missing:" -ForegroundColor Yellow
        Write-Host "  $vector" -ForegroundColor Yellow
    }

    if ($postgres18Roots.Count -gt 0) {
        $roots = ($postgres18Roots | ForEach-Object { "  - $_" }) -join [Environment]::NewLine

        throw @"
PostgreSQL 18 was found, but pgvector was not found in that PostgreSQL 18 installation.

Expected file:
  share\extension\vector.control

PostgreSQL 18 roots found:
$roots

If pgvector is installed under another PostgreSQL 18 root, run:
  .\Prepare-MAVI-Offline-Binary-Kit.ps1 -InstallMissingToolchain -PostgreSqlRoot "<root>"
"@
    }

    $inspected = if ($candidates.Count -gt 0) {
        ($candidates | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
    }
    else {
        "  (none discovered)"
    }

    throw @"
PostgreSQL 18 with pgvector was not found.

The script checked:
  - the explicit/default PostgreSQL root;
  - Program Files;
  - PATH;
  - running postgres.exe processes;
  - PostgreSQL Windows services; and
  - PostgreSQL installer registry records.

Candidates inspected:
$inspected

If PostgreSQL 18 is installed elsewhere, run:
  .\Prepare-MAVI-Offline-Binary-Kit.ps1 -InstallMissingToolchain -PostgreSqlRoot "<root>"
"@
}

New-Item -ItemType Directory -Path $downloads -Force | Out-Null
New-Item -ItemType Directory -Path $extract -Force | Out-Null

try {
    Write-Step "Preflight"
    $postgresRoot = Resolve-PostgresRoot -Preferred $PostgreSqlRoot
    $postgresExe = Join-Path $postgresRoot "bin\postgres.exe"
    $vectorControl = Join-Path $postgresRoot "share\extension\vector.control"

    $postgresVersion = ((& $postgresExe --version | Out-String).Trim() -split "\s+" | Select-Object -Last 1)
    $vectorText = Get-Content -LiteralPath $vectorControl -Raw
    $vectorMatch = [regex]::Match($vectorText, 'default_version\s*=\s*[''"](?<v>[^''"]+)[''"]')
    if (-not $vectorMatch.Success) { throw "Unable to determine pgvector version." }
    $pgvectorVersion = $vectorMatch.Groups["v"].Value

    Write-Host "PostgreSQL : $postgresVersion"
    Write-Host "pgvector   : $pgvectorVersion"
    Write-Host "Source     : $postgresRoot"

    Write-Step "Download controlled external inputs"

    # FFmpeg release essentials (Gyan Windows build) + published SHA-256.
    $ffmpegZip = Join-Path $downloads "ffmpeg-release-essentials.zip"
    $ffmpegSha = Join-Path $downloads "ffmpeg-release-essentials.zip.sha256"
    Invoke-Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $ffmpegZip
    Invoke-Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256" $ffmpegSha

    $expectedFfmpeg = ([regex]::Match((Get-Content $ffmpegSha -Raw), "(?i)\b[0-9a-f]{64}\b")).Value.ToLowerInvariant()
    $actualFfmpeg = Get-Sha256 $ffmpegZip
    if (-not $expectedFfmpeg -or $actualFfmpeg -ne $expectedFfmpeg) {
        throw "FFmpeg SHA-256 verification failed."
    }

    # .NET 10 official Microsoft redirect endpoints; Authenticode checked below.
    $dotnetSdk = Join-Path $downloads "dotnet-sdk.exe"
    $dotnetHosting = Join-Path $downloads "dotnet-hosting.exe"
    Invoke-Download "https://aka.ms/dotnet/10.0/dotnet-sdk-win-x64.exe" $dotnetSdk
    Invoke-Download "https://aka.ms/dotnet/10.0/dotnet-hosting-win.exe" $dotnetHosting
    Assert-Authenticode $dotnetSdk "Microsoft"
    Assert-Authenticode $dotnetHosting "Microsoft"

    # Node baseline is intentionally exact and verified against upstream SHASUMS256.txt.
    $nodeVersion = "22.13.0"
    $nodeName = "node-v$nodeVersion-x64.msi"
    $nodeMsi = Join-Path $downloads $nodeName
    $nodeSums = Join-Path $downloads "node-SHASUMS256.txt"
    Invoke-Download "https://nodejs.org/dist/v$nodeVersion/$nodeName" $nodeMsi
    Invoke-Download "https://nodejs.org/dist/v$nodeVersion/SHASUMS256.txt" $nodeSums
    $nodeLine = Get-Content $nodeSums | Where-Object { $_ -match [regex]::Escape($nodeName) } | Select-Object -First 1
    if (-not $nodeLine) { throw "Node.js checksum entry was not found." }
    $expectedNode = ([regex]::Match($nodeLine, "(?i)^[0-9a-f]{64}")).Value.ToLowerInvariant()
    if ((Get-Sha256 $nodeMsi) -ne $expectedNode) { throw "Node.js SHA-256 verification failed." }

    # Python 3.13 maintained Windows release; Authenticode checked below.
    $pythonVersion = "3.13.14"
    $pythonInstaller = Join-Path $downloads "python-$pythonVersion-amd64.exe"
    Invoke-Download "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe" $pythonInstaller
    Assert-Authenticode $pythonInstaller "Python"

    # Licence files for the staged PostgreSQL/pgvector runtime.
    $pgvectorLicense = Join-Path $downloads "LICENSE-PGVECTOR.txt"
    Invoke-Download "https://raw.githubusercontent.com/pgvector/pgvector/v$pgvectorVersion/LICENSE" $pgvectorLicense

    $postgresLicense = $null
    foreach ($candidate in @(
        (Join-Path $postgresRoot "COPYRIGHT"),
        (Join-Path $postgresRoot "doc\COPYRIGHT"),
        (Join-Path $postgresRoot "doc\copyright")
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $postgresLicense = $candidate
            break
        }
    }
    if (-not $postgresLicense) {
        $postgresLicense = Join-Path $downloads "LICENSE-POSTGRESQL.txt"
        Invoke-Download "https://raw.githubusercontent.com/postgres/postgres/REL_18_STABLE/COPYRIGHT" $postgresLicense
    }

    Write-Step "Stage FFmpeg"
    $ffmpegExtract = Join-Path $extract "ffmpeg"
    Expand-Archive -LiteralPath $ffmpegZip -DestinationPath $ffmpegExtract -Force
    $ffmpegExe = Get-ChildItem $ffmpegExtract -Filter ffmpeg.exe -File -Recurse |
        Where-Object { $_.Directory.Name -eq "bin" } | Select-Object -First 1
    if (-not $ffmpegExe) { throw "ffmpeg.exe was not found after extraction." }

    $ffprobe = Join-Path $ffmpegExe.Directory.FullName "ffprobe.exe"
    if (-not (Test-Path $ffprobe)) { throw "ffprobe.exe was not found beside ffmpeg.exe." }

    $firstLine = (& $ffmpegExe.FullName -version 2>&1 | Select-Object -First 1 | Out-String).Trim()
    $m = [regex]::Match($firstLine, "^ffmpeg version\s+(?<v>\S+)")
    if (-not $m.Success) { throw "Unable to determine FFmpeg version." }
    $ffmpegVersion = $m.Groups["v"].Value

    & (Join-Path $repoRoot "tools\native\stage_ffmpeg_windows.ps1") -SourceDirectory $ffmpegExe.Directory.FullName -Version $ffmpegVersion

    Write-Step "Stage PostgreSQL 18 + pgvector"
    & (Join-Path $repoRoot "tools\native\stage_postgresql_runtime_windows.ps1") `
        -PostgreSqlRoot $postgresRoot `
        -PgVectorLicensePath $pgvectorLicense `
        -PostgreSqlLicensePath $postgresLicense

    Write-Step "Stage toolchain installers"
    $installerRoot = Join-Path $repoRoot "vendor\installers\win-x64"
    if (Test-Path $installerRoot) { Remove-Item $installerRoot -Recurse -Force }
    New-Item -ItemType Directory -Path $installerRoot -Force | Out-Null

    Copy-Item $dotnetHosting (Join-Path $installerRoot "dotnet-hosting.exe")
    Copy-Item $dotnetSdk (Join-Path $installerRoot "dotnet-sdk.exe")
    Copy-Item $nodeMsi (Join-Path $installerRoot "node.msi")
    Copy-Item $pythonInstaller (Join-Path $installerRoot "python.exe")

    Write-Step "Ensure preparation toolchain"
    Install-IfNeeded ".NET 10 SDK" ${function:Test-DotNet10} $dotnetSdk @("/install","/quiet","/norestart")
    Install-IfNeeded "Node.js 22.13+" ${function:Test-Node22} $nodeMsi @("/qn","/norestart")

    $python313 = Resolve-Python313
    if (-not $python313) {
        if (-not $InstallMissingToolchain) { throw "Python 3.13 is missing. Re-run with -InstallMissingToolchain." }

        $p = Start-Process -FilePath $pythonInstaller `
            -ArgumentList @("/quiet","InstallAllUsers=1","PrependPath=1","Include_pip=1") `
            -Wait -PassThru
        if ($p.ExitCode -notin @(0,3010)) { throw "Python installer failed with exit code $($p.ExitCode)." }

        Refresh-ProcessPath
        $python313 = Resolve-Python313
        if (-not $python313) { throw "Python 3.13 could not be resolved after installation." }
    }

    Write-Host "Python source: $python313"

    Write-Step "Build Development offline caches"
    & (Join-Path $repoRoot "tools\setup\Prepare-MaviDeveloperOfflineCache.ps1") -Python $python313

    Write-Step "Build MAVI Offline Binary Kit"
    & (Join-Path $repoRoot "tools\setup\New-MaviOfflineBinaryKit.ps1") -Destination $destination -ZipPath $zipPath

    Write-Step "Verify completed kit"
    & (Join-Path $repoRoot "tools\setup\Test-MaviOfflineBinaryKit.ps1") -KitRoot $destination

    Write-Host ""
    Write-Host "MAVI Offline Binary Kit preparation PASSED." -ForegroundColor Green
    Write-Host "Folder : $destination"
    Write-Host "ZIP    : $zipPath"
    Write-Host "ZIP SHA-256: $(Get-Sha256 $zipPath)"
    Write-Host ""
    Write-Host "Next: keep the extracted MAVI-Offline-Binary-Kit beside the MAVI repository,"
    Write-Host "then run Setup-MAVI-Development.cmd."
}
finally {
    if ($KeepWorkingDirectory) {
        Write-Host "Working directory retained: $workRoot"
    }
    elseif (Test-Path $workRoot) {
        Remove-Item $workRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
