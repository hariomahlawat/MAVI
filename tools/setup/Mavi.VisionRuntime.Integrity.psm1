Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-MaviVisionIntegritySha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-MaviVisionIntegritySafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or [IO.Path]::IsPathRooted($Value) -or $Value.Contains("\") -or $Value.Contains([char]0)) { return $false }
    foreach ($part in $Value.Split('/')) { if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") { return $false } }
    return $true
}

function Invoke-MaviVisionIntegrityChecked {
    param([Parameter(Mandatory = $true)][string]$FilePath,[Parameter(Mandatory = $true)][string[]]$Arguments,[Parameter(Mandatory = $true)][string]$Description)
    $output = (& $FilePath @Arguments 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "$Description failed with exit code $LASTEXITCODE. $output" }
}

function Assert-MaviVisionInstalledRuntimeClosure {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$RuntimeRoot,[Parameter(Mandatory = $true)][object]$Manifest,[Parameter(Mandatory = $true)][string]$PythonPath)
    $root = [IO.Path]::GetFullPath($RuntimeRoot.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw "Vision Runtime Pack interpreter is missing: $PythonPath" }
    $lockArtifacts = @($Manifest.artifacts | Where-Object { [string]$_.purpose -eq "third-party-runtime-lock" })
    if ($lockArtifacts.Count -ne 1) { throw "Installed Vision Runtime Pack must declare exactly one third-party-runtime-lock artifact." }
    $relative = [string]$lockArtifacts[0].relativePath
    if (-not (Test-MaviVisionIntegritySafeRelativePath $relative)) { throw "Installed Vision Runtime Pack third-party lock path is unsafe." }
    $lockPath = Join-Path $root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $lockPath -PathType Leaf)) { throw "Installed Vision Runtime Pack third-party lock is missing: $relative" }
    $actualSha = Get-MaviVisionIntegritySha256 -Path $lockPath
    $artifactSha = ([string]$lockArtifacts[0].sha256).ToLowerInvariant()
    $manifestSha = ([string]$Manifest.thirdPartyLockSha256).ToLowerInvariant()
    if ($actualSha -ne $artifactSha -or $actualSha -ne $manifestSha) { throw "Installed Vision Runtime Pack third-party lock fingerprint mismatch." }
    Invoke-MaviVisionIntegrityChecked -FilePath $PythonPath -Description "Installed Vision Runtime Pack locked-distribution verification" -Arguments @("-m","pip","install","--no-index","--disable-pip-version-check","--no-deps","--require-hashes","-r",$lockPath)
    Invoke-MaviVisionIntegrityChecked -FilePath $PythonPath -Description "Installed Vision Runtime Pack dependency verification" -Arguments @("-m","pip","check")
    return $true
}

function Assert-MaviVisionInstalledModelPackIntegrity {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$ModelRoot,[Parameter(Mandatory = $true)][object]$Manifest)
    $root = [IO.Path]::GetFullPath($ModelRoot.Trim().Trim('"'))
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "Installed Vision Model Pack root is missing: $root" }
    $declared = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::Ordinal)
    foreach ($artifact in @($Manifest.artifacts)) {
        $relative = [string]$artifact.relativePath
        if (-not (Test-MaviVisionIntegritySafeRelativePath $relative)) { throw "Installed Vision Model Pack artifact path is unsafe: '$relative'." }
        if (-not $declared.Add($relative)) { throw "Installed Vision Model Pack contains duplicate artifact path: '$relative'." }
        $path = Join-Path $root ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Installed Vision Model Pack artifact is missing: '$relative'." }
        $item = Get-Item -LiteralPath $path
        if ([int64]$item.Length -ne [int64]$artifact.sizeBytes) { throw "Installed Vision Model Pack artifact size mismatch: '$relative'." }
        if ((Get-MaviVisionIntegritySha256 -Path $path) -ne ([string]$artifact.sha256).ToLowerInvariant()) { throw "Installed Vision Model Pack artifact SHA-256 mismatch: '$relative'." }
    }
    $prefix = $root.TrimEnd("\") + "\"
    $actual = @(Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object {
        if (-not $_.FullName.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw "Installed Vision Model Pack enumeration escaped its root." }
        $_.FullName.Substring($prefix.Length).Replace("\","/")
    } | Where-Object { $_ -notin @("model-pack-manifest.json","model-install.json") })
    foreach ($relative in $actual) { if (-not $declared.Contains($relative)) { throw "Undeclared file exists in installed Vision Model Pack: '$relative'." } }
    if ($actual.Count -ne $declared.Count) { throw "Installed Vision Model Pack artifact set does not match its manifest." }
    return $true
}

Export-ModuleMember -Function Assert-MaviVisionInstalledRuntimeClosure,Assert-MaviVisionInstalledModelPackIntegrity
