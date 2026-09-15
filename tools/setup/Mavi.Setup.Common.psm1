Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-MaviWindows {
    if ($env:OS -ne "Windows_NT") {
        throw "MAVI Windows setup can run only on Windows."
    }
}

function Test-MaviAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-MaviAdministrator {
    if (-not (Test-MaviAdministrator)) {
        throw "MAVI setup requires an elevated Administrator PowerShell session."
    }
}

function Get-MaviSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-MaviJson {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Required JSON file was not found: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-MaviJson {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$Depth = 12
    )
    $directory = Split-Path $Path -Parent
    if ($directory) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }
    $json = $Value | ConvertTo-Json -Depth $Depth
    [IO.File]::WriteAllText(
        $Path,
        $json + [Environment]::NewLine,
        [Text.UTF8Encoding]::new($false))
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
        throw "Required executable was not found: $FilePath"
    }

    $previousEnvironment = @{}
    try {
        if ($Environment) {
            foreach ($key in $Environment.Keys) {
                $name = [string]$key
                $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
                [Environment]::SetEnvironmentVariable($name, [string]$Environment[$key], "Process")
            }
        }

        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        $textOutput = ($output | Out-String).TrimEnd()
        if ($AllowedExitCodes -notcontains $exitCode) {
            throw ("Command failed ({0}): {1}{2}{3}" -f $exitCode, $FilePath, [Environment]::NewLine, $textOutput)
        }
        if ($CaptureOutput) {
            return [pscustomobject]@{
                ExitCode = $exitCode
                StandardOutput = $textOutput
                StandardError = ""
            }
        }
    }
    finally {
        foreach ($name in $previousEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable(
                [string]$name,
                $previousEnvironment[$name],
                "Process")
        }
    }
}

function New-MaviPassword {
    param([int]$Length = 32)
    if ($Length -lt 24) {
        throw "Generated MAVI passwords must be at least 24 characters."
    }
    $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#%+-_"
    $bytes = New-Object byte[] $Length
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    $characters = for ($index = 0; $index -lt $Length; $index++) {
        $alphabet[$bytes[$index] % $alphabet.Length]
    }
    return -join $characters
}

function Protect-MaviSecret {
    param(
        [Parameter(Mandatory = $true)][string]$PlainText,
        [Parameter(Mandatory = $true)][string]$Path
    )
    Add-Type -AssemblyName System.Security
    $bytes = [Text.Encoding]::UTF8.GetBytes($PlainText)
    $protected = [Security.Cryptography.ProtectedData]::Protect(
        $bytes,
        $null,
        [Security.Cryptography.DataProtectionScope]::LocalMachine)
    $directory = Split-Path $Path -Parent
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    [IO.File]::WriteAllText(
        $Path,
        [Convert]::ToBase64String($protected),
        [Text.UTF8Encoding]::new($false))
    & icacls.exe $Path /inheritance:r /grant:r "SYSTEM:F" "Administrators:F" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to secure MAVI secret file: $Path"
    }
}

function Unprotect-MaviSecret {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "MAVI secret file was not found: $Path"
    }
    Add-Type -AssemblyName System.Security
    $protected = [Convert]::FromBase64String(
        (Get-Content -LiteralPath $Path -Raw).Trim())
    $bytes = [Security.Cryptography.ProtectedData]::Unprotect(
        $protected,
        $null,
        [Security.Cryptography.DataProtectionScope]::LocalMachine)
    return [Text.Encoding]::UTF8.GetString($bytes)
}

function Test-MaviTcpPortInUse {
    param([Parameter(Mandatory = $true)][int]$Port)
    try {
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
        $listener.Start()
        $listener.Stop()
        return $false
    }
    catch [Net.Sockets.SocketException] {
        return $true
    }
}

function Wait-MaviTcpPort {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [int]$TimeoutSeconds = 60
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $client = [Net.Sockets.TcpClient]::new()
        try {
            $task = $client.ConnectAsync("127.0.0.1", $Port)
            if ($task.Wait(1000) -and $client.Connected) {
                return
            }
        }
        catch {
        }
        finally {
            $client.Dispose()
        }
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
    if ($Value -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') {
        throw "Unsafe PostgreSQL identifier: $Value"
    }
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
        [IO.File]::WriteAllText(
            $sqlPath,
            $Sql + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false))
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $sqlPath /inheritance:r /grant:r ("{0}:F" -f $identity) "SYSTEM:F" | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to secure temporary PostgreSQL command file."
        }

        $arguments = @(
            "-h", "127.0.0.1",
            "-p", [string]$Port,
            "-U", $User,
            "-d", $Database,
            "-v", "ON_ERROR_STOP=1",
            "-X",
            "-t",
            "-A",
            "-f", $sqlPath
        )
        return Invoke-MaviCommand -FilePath $PsqlPath -Arguments $arguments -CaptureOutput:$CaptureOutput -Environment @{
            PGPASSWORD = $Password
            PGCONNECT_TIMEOUT = "10"
        }
    }
    finally {
        Remove-Item -LiteralPath $sqlPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-MaviManifest {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [string]$ExpectedSchemaVersion
    )
    $rootPath = (Resolve-Path -LiteralPath $Root).Path
    $manifest = Read-MaviJson -Path $ManifestPath
    if ($ExpectedSchemaVersion -and
        [string]$manifest.schemaVersion -ne $ExpectedSchemaVersion) {
        throw "Unsupported MAVI manifest schema: $($manifest.schemaVersion)"
    }
    if (-not $manifest.artifacts) {
        throw "Manifest has no artifacts: $ManifestPath"
    }

    foreach ($artifact in $manifest.artifacts) {
        $relativeProperty = $artifact.PSObject.Properties["relativePath"]
        $fileNameProperty = $artifact.PSObject.Properties["fileName"]
        $shaProperty = $artifact.PSObject.Properties["sha256"]
        $sizeProperty = $artifact.PSObject.Properties["sizeBytes"]
        $runtimeProperty = $manifest.PSObject.Properties["runtimeId"]

        $relative = if ($relativeProperty) { [string]$relativeProperty.Value } else { "" }
        $fileName = if ($fileNameProperty) { [string]$fileNameProperty.Value } else { "" }
        $runtimeId = if ($runtimeProperty) { [string]$runtimeProperty.Value } else { "" }

        if ([string]::IsNullOrWhiteSpace($relative) -and
            -not [string]::IsNullOrWhiteSpace($fileName) -and
            -not [string]::IsNullOrWhiteSpace($runtimeId)) {
            $relative = $runtimeId.TrimEnd("/", "\") + "/" + $fileName
        }
        if ([string]::IsNullOrWhiteSpace($relative) -or
            [IO.Path]::IsPathRooted($relative) -or
            $relative.Contains("..")) {
            throw "Unsafe manifest artifact path: $relative"
        }
        $path = Join-Path $rootPath ($relative -replace "/", "\")
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Manifest artifact is missing: $relative"
        }
        if (-not $shaProperty) {
            throw "Manifest artifact has no SHA-256: $relative"
        }
        $expected = ([string]$shaProperty.Value).ToLowerInvariant()
        if ($expected -notmatch '^[0-9a-f]{64}
    return $manifest
}

function Set-MaviDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Identity,
        [ValidateSet("R", "M", "F")][string]$Rights = "M"
    )
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    & icacls.exe $Path /grant:r ("{0}:(OI)(CI){1}" -f $Identity, $Rights) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to grant $Rights ACL to $Identity on $Path."
    }
}

function Write-MaviSetupStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Detail
    )
    $suffix = if ($Detail) { " - $Detail" } else { "" }
    Write-Host ("{0,-26} {1}{2}" -f $Name, $Status, $suffix)
}

Export-ModuleMember -Function *
) {
            throw "Manifest artifact has invalid SHA-256: $relative"
        }
        $actual = Get-MaviSha256 -Path $path
        if ($actual -ne $expected) {
            throw "Manifest artifact failed SHA-256 verification: $relative"
        }
        if ($sizeProperty -and
            [long](Get-Item -LiteralPath $path).Length -ne [long]$sizeProperty.Value) {
            throw "Manifest artifact size mismatch: $relative"
        }
    }
    return $manifest
}

function Set-MaviDirectoryAcl {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Identity,
        [ValidateSet("R", "M", "F")][string]$Rights = "M"
    )
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
    & icacls.exe $Path /grant:r ("{0}:(OI)(CI){1}" -f $Identity, $Rights) | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to grant $Rights ACL to $Identity on $Path."
    }
}

function Write-MaviSetupStatus {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Detail
    )
    $suffix = if ($Detail) { " - $Detail" } else { "" }
    Write-Host ("{0,-26} {1}{2}" -f $Name, $Status, $suffix)
}

Export-ModuleMember -Function *
