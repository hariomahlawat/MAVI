[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BundleRoot,

    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,

    [string]$InstallRoot = "C:\ProgramData\MAVI\Development\VisionRuntime\windows-x86_64-cpu"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-BundleRoot {
    param([Parameter(Mandatory = $true)][string]$Root)

    $candidate = [IO.Path]::GetFullPath($Root.Trim().Trim('"'))
    if (Test-Path -LiteralPath (Join-Path $candidate "bundle-manifest.json") -PathType Leaf) {
        return $candidate
    }

    $nested = Join-Path $candidate "windows-x86_64-cpu"
    if (Test-Path -LiteralPath (Join-Path $nested "bundle-manifest.json") -PathType Leaf) {
        return $nested
    }

    throw "MAVI Vision Runtime bundle manifest was not found under '$candidate'."
}

function Test-SafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value) -or
        [IO.Path]::IsPathRooted($Value) -or
        $Value.Contains("\") -or
        $Value.Contains([char]0)) {
        return $false
    }

    foreach ($part in $Value.Split('/')) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") {
            return $false
        }
    }
    return $true
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')"
    }
}

$BundleRoot = Resolve-BundleRoot $BundleRoot
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot.Trim().Trim('"'))

$manifestPath = Join-Path $BundleRoot "bundle-manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json

if ([string]$manifest.schemaVersion -ne "1.0") {
    throw "Unsupported MAVI Vision Runtime bundle schema '$($manifest.schemaVersion)'."
}
if ([string]$manifest.platformVariant -ne "windows-x86_64-cpu") {
    throw "Expected windows-x86_64-cpu runtime bundle, found '$($manifest.platformVariant)'."
}
if ([string]$manifest.pythonVersion -ne "3.12.10") {
    throw "Expected qualified CPython 3.12.10 runtime, found '$($manifest.pythonVersion)'."
}
if ([string]$manifest.releaseStatus -notin @("qualification-candidate", "production")) {
    throw "Unsupported vision runtime release status '$($manifest.releaseStatus)'."
}

$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw "git.exe is required to bind the runtime bundle to the attached source checkout." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or -not $head) {
    throw "Unable to determine the attached repository HEAD."
}
if ($head -ne [string]$manifest.sourceCommit) {
    throw "Vision runtime bundle source commit '$($manifest.sourceCommit)' does not match repository HEAD '$head'."
}

$declared = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::Ordinal)
foreach ($artifact in @($manifest.artifacts)) {
    $relative = [string]$artifact.relativePath
    if (-not (Test-SafeRelativePath $relative)) {
        throw "Unsafe artifact path in vision runtime manifest: '$relative'."
    }
    if (-not $declared.Add($relative)) {
        throw "Duplicate artifact path in vision runtime manifest: '$relative'."
    }

    $path = Join-Path $BundleRoot ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Vision runtime artifact is missing: '$relative'."
    }
    $item = Get-Item -LiteralPath $path
    if ([int64]$item.Length -ne [int64]$artifact.sizeBytes) {
        throw "Vision runtime artifact size mismatch: '$relative'."
    }
    $actualHash = Get-Sha256 $path
    if ($actualHash -ne ([string]$artifact.sha256).ToLowerInvariant()) {
        throw "Vision runtime artifact SHA-256 mismatch: '$relative'."
    }
}

$bundlePrefix = $BundleRoot.TrimEnd("\") + "\"
$actualFiles = Get-ChildItem -LiteralPath $BundleRoot -Recurse -File | ForEach-Object {
    if (-not $_.FullName.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Vision runtime bundle enumeration escaped its root."
    }
    $_.FullName.Substring($bundlePrefix.Length).Replace("\", "/")
} | Where-Object { $_ -ne "bundle-manifest.json" }

foreach ($relative in $actualFiles) {
    if (-not $declared.Contains($relative)) {
        throw "Undeclared file exists in vision runtime bundle: '$relative'."
    }
}
if (@($actualFiles).Count -ne $declared.Count) {
    throw "Vision runtime bundle artifact set does not match its manifest."
}

$installerArtifact = @($manifest.artifacts | Where-Object {
    [string]$_.purpose -eq "python-runtime-installer"
}) | Select-Object -First 1
if (-not $installerArtifact) {
    throw "Vision runtime bundle does not contain its qualified CPython installer."
}
$pythonInstaller = Join-Path $BundleRoot (([string]$installerArtifact.relativePath).Replace('/', [IO.Path]::DirectorySeparatorChar))
$signature = Get-AuthenticodeSignature -FilePath $pythonInstaller
if ($signature.Status -ne "Valid") {
    throw "Bundled CPython installer Authenticode signature is not valid: $($signature.Status)"
}
$installerVersion = (Get-Item -LiteralPath $pythonInstaller).VersionInfo.ProductVersion
# python.org reports CPython 3.12.10 as ProductVersion 3.12.10150.0.
# Bundle SHA-256 and Authenticode are independently verified above.
if (-not $installerVersion.StartsWith("3.12.10")) {
    throw "Bundled CPython installer product version '$installerVersion' does not match the 3.12.10 release."
}

$runtimeBase = Split-Path $InstallRoot -Parent
$pythonRoot = Join-Path $runtimeBase "Python312"
$pythonExe = Join-Path $pythonRoot "python.exe"

$pythonReady = $false
if (Test-Path -LiteralPath $pythonExe -PathType Leaf) {
    $pythonVersion = (& $pythonExe --version 2>&1 | Out-String).Trim()
    $pythonReady = $LASTEXITCODE -eq 0 -and $pythonVersion -eq "Python 3.12.10"
}

if (-not $pythonReady) {
    Write-Host "Installing qualified CPython 3.12.10 runtime..."
    New-Item -ItemType Directory -Path $runtimeBase -Force | Out-Null
    $arguments = @(
        "/quiet",
        "InstallAllUsers=1",
        "TargetDir=$pythonRoot",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_test=0",
        "Include_pip=1",
        "Shortcuts=0"
    )
    $process = Start-Process -FilePath $pythonInstaller -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "CPython 3.12.10 installer failed with exit code $($process.ExitCode)."
    }
}

if (-not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw "Qualified CPython interpreter was not installed at '$pythonExe'."
}
$pythonVersion = (& $pythonExe --version 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $pythonVersion -ne "Python 3.12.10") {
    throw "Installed vision runtime Python identity is '$pythonVersion'; expected Python 3.12.10."
}

$stageRoot = "$InstallRoot.stage"
if (Test-Path -LiteralPath $stageRoot) {
    Remove-Item -LiteralPath $stageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $BundleRoot "release") -Destination (Join-Path $stageRoot "release") -Recurse -Force
Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stageRoot "bundle-manifest.json") -Force

$venvRoot = Join-Path $stageRoot "venv"
Invoke-Checked $pythonExe @("-m", "venv", $venvRoot)
$venvPython = Join-Path $venvRoot "Scripts\python.exe"
$lockPath = Join-Path $stageRoot "release\runtime\mmdetection-phase1-v1\windows-x86_64-cpu.lock"
$wheelhouse = Join-Path $BundleRoot "wheels"

Invoke-Checked $venvPython @(
    "-m", "pip", "install",
    "--no-index",
    "--only-binary=:all:",
    "--require-hashes",
    "--find-links", $wheelhouse,
    "-r", $lockPath
)
Invoke-Checked $venvPython @("-m", "pip", "check")

$identityScript = @'
import json, platform, sys
print(json.dumps({
    "version": platform.python_version(),
    "implementation": platform.python_implementation(),
    "build": list(platform.python_build()),
    "compiler": platform.python_compiler(),
}, sort_keys=True))
'@
$observedIdentity = (& $venvPython -c $identityScript | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read installed vision runtime Python identity."
}
$identity = $observedIdentity | ConvertFrom-Json
if ([string]$identity.version -ne "3.12.10" -or [string]$identity.implementation -ne "CPython") {
    throw "Installed vision runtime Python identity does not match the qualified Windows CPU baseline."
}

$state = [ordered]@{
    schemaVersion = "mavi-vision-runtime-install-v1"
    platformVariant = [string]$manifest.platformVariant
    releaseStatus = [string]$manifest.releaseStatus
    sourceCommit = [string]$manifest.sourceCommit
    bundleId = [string]$manifest.bundleId
    bundleManifestSha256 = Get-Sha256 $manifestPath
    pythonVersion = [string]$identity.version
    installedAtUtc = [DateTime]::UtcNow.ToString("O")
    runtimeRoot = $InstallRoot
}
$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $stageRoot "runtime-install.json") -Encoding UTF8

if (Test-Path -LiteralPath $InstallRoot) {
    $backup = "$InstallRoot.previous"
    if (Test-Path -LiteralPath $backup) {
        Remove-Item -LiteralPath $backup -Recurse -Force
    }
    Move-Item -LiteralPath $InstallRoot -Destination $backup
    try {
        Move-Item -LiteralPath $stageRoot -Destination $InstallRoot
        Remove-Item -LiteralPath $backup -Recurse -Force
    }
    catch {
        if (Test-Path -LiteralPath $InstallRoot) {
            Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
        Move-Item -LiteralPath $backup -Destination $InstallRoot -ErrorAction SilentlyContinue
        throw
    }
}
else {
    Move-Item -LiteralPath $stageRoot -Destination $InstallRoot
}

[Environment]::SetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", $InstallRoot, "Machine")

Write-Host ""
Write-Host "MAVI Vision Runtime installed and verified." -ForegroundColor Green
Write-Host "  Runtime : $InstallRoot"
Write-Host "  Bundle  : $($manifest.bundleId)"
Write-Host "  Source  : $($manifest.sourceCommit)"
Write-Host "  Python  : 3.12.10"
Write-Host "  Variant : windows-x86_64-cpu"
