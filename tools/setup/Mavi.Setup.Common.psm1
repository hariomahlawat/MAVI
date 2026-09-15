Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-MaviWindows {
    if (-not $IsWindows -and $env:OS -ne "Windows_NT") {
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

    if (-not (Test-Path -LiteralPath $FilePath -PathType Leaf) -and
        -not (Get-Command $FilePath -ErrorAction SilentlyContinue)) {
        throw "Required executable was not found: $FilePath"
    }

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    foreach ($argument in $Arguments) {
        [void]$startInfo.ArgumentList.Add([string]$argument)
    }
    if ($Environment) {
        foreach ($key in $Environment.Keys) {
            $startInfo.Environment[[string]$key] = [string]$Environment[$key]
        }
    }

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Unable to start command: $FilePath"
        }
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        if ($AllowedExitCodes -notcontains $process.ExitCode) {
            $detail = ($stderr + [Environment]::NewLine + $stdout).Trim()
            throw ("Command failed ({0}): {1} {2}{3}{4}" -f $process.ExitCode, $FilePath, ($Arguments -join " "), [Environment]::NewLine, $detail)
        }
        if ($CaptureOutput) {
            return [pscustomobject]@{
                ExitCode = $process.ExitCode
                StandardOutput = $stdout
                StandardError = $stderr
            }
        }
    }
    finally {
        $process.Dispose()
    }
}

function New-MaviPassword {
    param([int]$Length = 32)
    if ($Length -lt 24) {
        throw "Generated MAVI passwords must be at least 24 characters."
    }
    $alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!#%+-_"
    $bytes = [byte[]]::new($Length)
    [Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
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
    $arguments = @(
        "-h", "127.0.0.1",
        "-p", [string]$Port,
        "-U", $User,
        "-d", $Database,
        "-v", "ON_ERROR_STOP=1",
        "-X",
        "-t",
        "-A",
        "-c", $Sql
    )
    return Invoke-MaviCommand -FilePath $PsqlPath -Arguments $arguments -CaptureOutput:$CaptureOutput -Environment @{
        PGPASSWORD = $Password
        PGCONNECT_TIMEOUT = "10"
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
        $relative = [string]$artifact.relativePath
        if ([string]::IsNullOrWhiteSpace($relative) -or
            [IO.Path]::IsPathRooted($relative) -or
            $relative.Contains("..")) {
            throw "Unsafe manifest artifact path: $relative"
        }
        $path = Join-Path $rootPath ($relative -replace "/", "\")
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Manifest artifact is missing: $relative"
        }
        $expected = ([string]$artifact.sha256).ToLowerInvariant()
        if ($expected -notmatch '^[0-9a-f]{64}$') {
            throw "Manifest artifact has invalid SHA-256: $relative"
        }
        $actual = Get-MaviSha256 -Path $path
        if ($actual -ne $expected) {
            throw "Manifest artifact failed SHA-256 verification: $relative"
        }
        if ($null -ne $artifact.sizeBytes -and
            [long](Get-Item -LiteralPath $path).Length -ne [long]$artifact.sizeBytes) {
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
    & icacls.exe $Path /grant:r "$Identity:(OI)(CI)$Rights" | Out-Null
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
