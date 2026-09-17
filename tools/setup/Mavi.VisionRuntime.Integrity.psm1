Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-MaviVisionIntegritySha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-MaviVisionIntegritySafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or [IO.Path]::IsPathRooted($Value) -or $Value.Contains("\") -or $Value.Contains([char]0)) { return $false }
    foreach ($part in $Value.Split('/')) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") { return $false }
    }
    return $true
}

function Invoke-MaviVisionIntegrityChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )
    $output = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE. $output"
    }
}

function Assert-MaviVisionInstalledRuntimeClosure {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$RuntimeRoot,
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$PythonPath
    )

    $root = [IO.Path]::GetFullPath($RuntimeRoot.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Vision Runtime Pack interpreter is missing: $PythonPath"
    }

    $lockArtifacts = @($Manifest.artifacts | Where-Object { [string]$_.purpose -eq "third-party-runtime-lock" })
    if ($lockArtifacts.Count -ne 1) {
        throw "Installed Vision Runtime Pack must declare exactly one third-party-runtime-lock artifact."
    }
    $relative = [string]$lockArtifacts[0].relativePath
    if (-not (Test-MaviVisionIntegritySafeRelativePath $relative)) {
        throw "Installed Vision Runtime Pack third-party lock path is unsafe."
    }
    $lockPath = Join-Path $root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) {
        throw "Installed Vision Runtime Pack third-party lock is missing: $relative"
    }
    $actualSha = Get-MaviVisionIntegritySha256 -Path $lockPath
    $artifactSha = ([string]$lockArtifacts[0].sha256).ToLowerInvariant()
    $manifestSha = ([string]$Manifest.thirdPartyLockSha256).ToLowerInvariant()
    if ($actualSha -ne $artifactSha -or $actualSha -ne $manifestSha) {
        throw "Installed Vision Runtime Pack third-party lock fingerprint mismatch."
    }

    # This is verification only. With --no-index and no --find-links/source,
    # pip can succeed only when every exact locked requirement is already
    # satisfied by the installed environment; it cannot repair a damaged venv.
    Invoke-MaviVisionIntegrityChecked -FilePath $PythonPath -Description "Installed Vision Runtime Pack locked-distribution verification" -Arguments @(
        "-m", "pip", "install", "--no-index", "--disable-pip-version-check", "--no-deps", "--require-hashes", "-r", $lockPath
    )
    Invoke-MaviVisionIntegrityChecked -FilePath $PythonPath -Description "Installed Vision Runtime Pack dependency verification" -Arguments @(
        "-m", "pip", "check"
    )
    return $true
}

Export-ModuleMember -Function Assert-MaviVisionInstalledRuntimeClosure
