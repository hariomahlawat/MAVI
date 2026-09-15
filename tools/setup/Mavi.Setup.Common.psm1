Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-MaviWindows {
    if ($env:OS -ne "Windows_NT") { throw "MAVI setup is supported only on Windows." }
}

function Test-MaviAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal -ArgumentList $identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-MaviAdministrator {
    if (-not (Test-MaviAdministrator)) {
        throw "Run MAVI Setup as Administrator."
    }
}

function Get-MaviSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Missing file: $Path" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-MaviPostgreSqlMajorVersionOutput {
    param(
        [Parameter(Mandatory = $true)][string]$VersionOutput,
        [int]$Major = 18
    )

    if ([string]::IsNullOrWhiteSpace($VersionOutput) -or $Major -lt 1) {
        return $false
    }

    $majorText = [regex]::Escape([string]$Major)
    return $VersionOutput -match ("(?i)\bPostgreSQL\b.*\b{0}(?:\.|\b)" -f $majorText)
}

function Read-MaviJson {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Required file not found: $Path" }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-MaviJson {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Depth = 12
    )
    $directory = Split-Path $Path -Parent
    if ($directory) { New-Item -ItemType Directory -Path $directory -Force | Out-Null }
    $json = $Value | ConvertTo-Json -Depth $Depth
    $utf8 = New-Object Text.UTF8Encoding -ArgumentList $false
    [IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8)
}

function Invoke-MaviCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [int[]]$AllowedExitCodes = @(0),
        [switch]$CaptureOutput,
        [hashtable]$Environment
    )
    $command = Get-Command $FilePath -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf) -and -not $command) {
        throw "Required executable not found: $FilePath"
    }
    $previous = @{}
    try {
        if ($Environment) {
            foreach ($key in $Environment.Keys) {
                $name = [string]$key
                $previous[$name] = [Environment]::GetEnvironmentVariable($name, [System.EnvironmentVariableTarget]::Process)
                [Environment]::SetEnvironmentVariable($name, [string]$Environment[$key], [System.EnvironmentVariableTarget]::Process)
            }
        }
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        $textOutput = ($output | Out-String).TrimEnd()
        if ($AllowedExitCodes -notcontains $exitCode) {
            throw ("Command failed ({0}): {1}{2}{3}" -f $exitCode, $FilePath, [Environment]::NewLine, $textOutput)
        }
        if ($CaptureOutput) {
            return [pscustomobject]@{ ExitCode = [int]$exitCode; StandardOutput = $textOutput; StandardError = "" }
        }
    }
    finally {
        foreach ($name in $previous.Keys) {
            [Environment]::SetEnvironmentVariable([string]$name, $previous[$name], [System.EnvironmentVariableTarget]::Process)
        }
    }
}

function New-MaviPassword {
    param([int]$Length = 32)
    if ($Length -lt 24) { throw "Generated MAVI passwords must be at least 24 characters." }
    $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#%+-_"
    $bytes = New-Object byte[] $Length
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $characters = for ($index = 0; $index -lt $Length; $index++) { $alphabet[$bytes[$index] % $alphabet.Length] }
    return -join $characters
}

function Protect-MaviSecret {
    param([Parameter(Mandatory = $true)][string]$PlainText, [Parameter(Mandatory = $true)][string]$Path)
    Add-Type -AssemblyName System.Security
    $bytes = [Text.Encoding]::UTF8.GetBytes($PlainText)
    $protected = [Security.Cryptography.ProtectedData]::Protect($bytes, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine)
    $directory = Split-Path $Path -Parent
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    $utf8 = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, [Convert]::ToBase64String($protected), $utf8)
    & icacls.exe $Path /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to secure MAVI secret file: $Path" }
}

function Unprotect-MaviSecret {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "MAVI secret file was not found: $Path" }
    Add-Type -AssemblyName System.Security
    $protected = [Convert]::FromBase64String((Get-Content -LiteralPath $Path -Raw).Trim())
    $bytes = [Security.Cryptography.ProtectedData]::Unprotect($protected, $null, [Security.Cryptography.DataProtectionScope]::LocalMachine)
    return [Text.Encoding]::UTF8.GetString($bytes)
}

function Test-MaviTcpPortInUse {
    param([Parameter(Mandatory = $true)][int]$Port)
    $listener = $null
    try {
        $listener = New-Object Net.Sockets.TcpListener -ArgumentList ([Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        return $false
    }
    catch [Net.Sockets.SocketException] { return $true }
    finally { if ($null -ne $listener) { try { $listener.Stop() } catch { } } }
}

function Wait-MaviTcpPort {
    param([Parameter(Mandatory = $true)][int]$Port, [int]$TimeoutSeconds = 60)
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $client = New-Object Net.Sockets.TcpClient
        try {
            $task = $client.ConnectAsync("127.0.0.1", $Port)
            if ($task.Wait(1000) -and $client.Connected) { return }
        } catch { } finally { $client.Dispose() }
        Start-Sleep -Milliseconds 500
    }
    throw "Timed out waiting for PostgreSQL on 127.0.0.1:$Port."
}

function ConvertTo-PgLiteral {
    param([Parameter(Mandatory = $true)][string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function ConvertTo-PgIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ($Value -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") { throw "Unsafe PostgreSQL identifier: $Value" }
    return '"' + $Value.Replace('"', '""') + '"'
}

function Invoke-MaviPsql {
    param(
        [Parameter(Mandatory = $true)][string]$PsqlPath,
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)][string]$User,
        [Parameter(Mandatory = $true)][string]$Password,
        [Parameter(Mandatory = $true)][string]$Database,
        [Parameter(Mandatory = $true)][string]$Sql,
        [switch]$CaptureOutput
    )
    $sqlPath = Join-Path ([IO.Path]::GetTempPath()) ("mavi-sql-" + [Guid]::NewGuid().ToString("N") + ".sql")
    try {
        $utf8 = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($sqlPath, $Sql + [Environment]::NewLine, $utf8)
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $sqlPath /inheritance:r /grant:r ("{0}:F" -f $identity) "SYSTEM:F" | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Failed to secure temporary PostgreSQL command file." }
        $arguments = @("-h","127.0.0.1","-p",[string]$Port,"-U",$User,"-d",$Database,"-v","ON_ERROR_STOP=1","-X","-t","-A","-f",$sqlPath)
        return Invoke-MaviCommand -FilePath $PsqlPath -Arguments $arguments -CaptureOutput:$CaptureOutput -Environment @{ PGPASSWORD = $Password; PGCONNECT_TIMEOUT = "10" }
    }
    finally { Remove-Item -LiteralPath $sqlPath -Force -ErrorAction SilentlyContinue }
}

function Test-MaviManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [string]$ExpectedSchemaVersion
    )
    $rootPath = (Resolve-Path -LiteralPath $Root).Path
    $manifest = Read-MaviJson -Path $ManifestPath
    $schema = $manifest.PSObject.Properties["schemaVersion"]
    $artifactsProperty = $manifest.PSObject.Properties["artifacts"]
    $runtimeProperty = $manifest.PSObject.Properties["runtimeId"]
    $schemaValue = if ($schema) { [string]$schema.Value } else { "" }
    if ($ExpectedSchemaVersion -and $schemaValue -ne $ExpectedSchemaVersion) {
        throw "Unsupported MAVI manifest schema '$schemaValue'."
    }
    if (-not $artifactsProperty) { throw "Manifest has no artifacts: $ManifestPath" }
    $artifacts = @($artifactsProperty.Value)
    if ($artifacts.Count -eq 0) { throw "Manifest has no artifacts: $ManifestPath" }
    $runtimeId = if ($runtimeProperty) { [string]$runtimeProperty.Value } else { "" }
    foreach ($artifact in $artifacts) {
        $relativeProperty = $artifact.PSObject.Properties["relativePath"]
        $fileNameProperty = $artifact.PSObject.Properties["fileName"]
        $shaProperty = $artifact.PSObject.Properties["sha256"]
        $sizeProperty = $artifact.PSObject.Properties["sizeBytes"]
        $relative = if ($relativeProperty) { [string]$relativeProperty.Value } else { "" }
        $fileName = if ($fileNameProperty) { [string]$fileNameProperty.Value } else { "" }
        if ([string]::IsNullOrWhiteSpace($relative) -and $fileName -and $runtimeId) {
            $relative = $runtimeId.TrimEnd("/","\") + "/" + $fileName
        }
        if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or $relative.Contains("..")) {
            throw "Unsafe manifest artifact path: $relative"
        }
        $artifactPath = Join-Path $rootPath ($relative -replace "/", "\")
        if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) { throw "Manifest artifact is missing: $relative" }
        if (-not $shaProperty) { throw "Manifest artifact has no SHA-256: $relative" }
        $expected = ([string]$shaProperty.Value).ToLowerInvariant()
        if ($expected -notmatch "^[0-9a-f]{64}$") { throw "Manifest artifact has invalid SHA-256: $relative" }
        $actual = Get-MaviSha256 -Path $artifactPath
        if ($actual -ne $expected) { throw "Manifest artifact failed SHA-256 verification: $relative" }
        if ($sizeProperty) {
            $actualSize = [long](Get-Item -LiteralPath $artifactPath).Length
            $expectedSize = [long]$sizeProperty.Value
            if ($actualSize -ne $expectedSize) { throw "Manifest artifact size mismatch: $relative" }
        }
    }
    return $manifest
}

function Set-MaviDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Identity,
        [ValidateSet("R","M","F")][string]$Rights = "M"
    )
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    & icacls.exe $Path /grant:r ("{0}:(OI)(CI){1}" -f $Identity, $Rights) | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to grant $Rights ACL to $Identity on $Path." }
}

function Set-MaviPrivateDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$ApplicationIdentity,
        [ValidateSet("R","M","F")][string]$ApplicationRights = "M"
    )
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    $arguments = @($Path, "/inheritance:r", "/grant:r", "SYSTEM:(OI)(CI)F", "Administrators:(OI)(CI)F")
    if (-not [string]::IsNullOrWhiteSpace($ApplicationIdentity)) {
        $arguments += ("{0}:(OI)(CI){1}" -f $ApplicationIdentity, $ApplicationRights)
    }
    & icacls.exe @arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to secure MAVI directory: $Path" }
}
function Write-MaviSetupStatus {
    param([Parameter(Mandatory = $true)][string]$Name, [Parameter(Mandatory = $true)][string]$Status, [string]$Detail)
    $suffix = if ($Detail) { " - $Detail" } else { "" }
    Write-Host ("{0,-26} {1}{2}" -f $Name, $Status, $suffix)
}

Export-ModuleMember -Function *
