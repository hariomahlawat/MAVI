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
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.VisionRuntime.Common.psm1") -Force

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Resolve-RuntimePackRoot {
    param([Parameter(Mandatory = $true)][string]$Root)
    $candidate = [IO.Path]::GetFullPath($Root.Trim().Trim('"'))
    if (Test-Path -LiteralPath (Join-Path $candidate "runtime-pack-manifest.json") -PathType Leaf) { return $candidate }
    $nested = Join-Path $candidate "windows-x86_64-cpu"
    if (Test-Path -LiteralPath (Join-Path $nested "runtime-pack-manifest.json") -PathType Leaf) { return $nested }
    throw "MAVI Vision Runtime Pack manifest was not found under '$candidate'."
}

function Test-SafeRelativePath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value) -or [IO.Path]::IsPathRooted($Value) -or $Value.Contains("\") -or $Value.Contains([char]0)) { return $false }
    foreach ($part in $Value.Split('/')) {
        if ([string]::IsNullOrWhiteSpace($part) -or $part -eq "." -or $part -eq "..") { return $false }
    }
    return $true
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $FilePath $($Arguments -join ' ')" }
}

function Get-PythonIdentity {
    param([Parameter(Mandatory = $true)][string]$PythonPath)
    $script = @'
import json
import platform
print(json.dumps({
    "version": platform.python_version(),
    "implementation": platform.python_implementation(),
    "build": list(platform.python_build()),
    "compiler": platform.python_compiler(),
}, sort_keys=True))
'@
    $probe = Join-Path ([IO.Path]::GetTempPath()) ("mavi-python-identity-" + [Guid]::NewGuid().ToString("N") + ".py")
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($probe, $script, $utf8NoBom)
    try {
        $output = (& $PythonPath $probe 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($output)) { throw "Unable to read vision runtime Python identity: $output" }
        return $output | ConvertFrom-Json
    }
    finally { Remove-Item -LiteralPath $probe -Force -ErrorAction SilentlyContinue }
}

function Resolve-QualifiedPython31210 {
    param([string]$PreferredRoot)
    $candidates = New-Object System.Collections.Generic.List[string]
    function Add-Candidate {
        param([string]$Path)
        if ([string]::IsNullOrWhiteSpace($Path)) { return }
        try {
            $full = [IO.Path]::GetFullPath($Path)
            if (-not $candidates.Contains($full)) { [void]$candidates.Add($full) }
        }
        catch { }
    }
    Add-Candidate (Join-Path $PreferredRoot "python.exe")
    Add-Candidate (Join-Path $env:ProgramFiles "Python312\python.exe")
    Add-Candidate (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py -and $py.Source) {
        try {
            $resolved = (& $py.Source -3.12 -c "import sys; print(sys.executable)" 2>$null | Out-String).Trim()
            if ($resolved) { Add-Candidate $resolved }
        }
        catch { }
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $version = (& $candidate --version 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0 -and $version -eq "Python 3.12.10") { return $candidate }
        }
        catch { }
    }
    return $null
}

$BundleRoot = Resolve-RuntimePackRoot $BundleRoot
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$InstallRoot = [IO.Path]::GetFullPath($InstallRoot.Trim().Trim('"'))

$manifestPath = Join-Path $BundleRoot "runtime-pack-manifest.json"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
[void](Assert-MaviVisionRuntimePackManifest -Manifest $manifest)
if ([string]$manifest.schemaVersion -ne "mavi-vision-runtime-pack-v2") { throw "Unsupported MAVI Vision Runtime Pack schema '$($manifest.schemaVersion)'." }
if ([string]$manifest.platformVariant -ne "windows-x86_64-cpu") { throw "Expected windows-x86_64-cpu Runtime Pack, found '$($manifest.platformVariant)'." }
if ([string]$manifest.pythonVersion -ne "3.12.10") { throw "Expected qualified CPython 3.12.10 runtime, found '$($manifest.pythonVersion)'." }
$manifestSha = Get-Sha256 $manifestPath

# Verify the complete supplied Runtime Pack before either reuse or installation.
$declared = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::Ordinal)
foreach ($artifact in @($manifest.artifacts)) {
    $relative = [string]$artifact.relativePath
    if (-not (Test-SafeRelativePath $relative)) { throw "Unsafe artifact path in vision Runtime Pack manifest: '$relative'." }
    if (-not $declared.Add($relative)) { throw "Duplicate artifact path in vision Runtime Pack manifest: '$relative'." }
    $path = Join-Path $BundleRoot ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Vision Runtime Pack artifact is missing: '$relative'." }
    $item = Get-Item -LiteralPath $path
    if ([int64]$item.Length -ne [int64]$artifact.sizeBytes) { throw "Vision Runtime Pack artifact size mismatch: '$relative'." }
    if ((Get-Sha256 $path) -ne ([string]$artifact.sha256).ToLowerInvariant()) { throw "Vision Runtime Pack artifact SHA-256 mismatch: '$relative'." }
}

$bundlePrefix = $BundleRoot.TrimEnd("\") + "\"
$actualFiles = @(Get-ChildItem -LiteralPath $BundleRoot -Recurse -File | ForEach-Object {
    if (-not $_.FullName.StartsWith($bundlePrefix, [StringComparison]::OrdinalIgnoreCase)) { throw "Vision Runtime Pack enumeration escaped its root." }
    $_.FullName.Substring($bundlePrefix.Length).Replace("\", "/")
} | Where-Object { $_ -ne "runtime-pack-manifest.json" })
foreach ($relative in $actualFiles) {
    if (-not $declared.Contains($relative)) { throw "Undeclared file exists in vision Runtime Pack: '$relative'." }
}
if ($actualFiles.Count -ne $declared.Count) { throw "Vision Runtime Pack artifact set does not match its manifest." }

$lockArtifact = @($manifest.artifacts | Where-Object { [string]$_.purpose -eq "third-party-runtime-lock" })
$requirementsArtifact = @($manifest.artifacts | Where-Object { [string]$_.purpose -eq "application-runtime-requirements" })
$installerArtifact = @($manifest.artifacts | Where-Object { [string]$_.purpose -eq "python-runtime-installer" })
if ($lockArtifact.Count -ne 1 -or $requirementsArtifact.Count -ne 1 -or $installerArtifact.Count -ne 1) {
    throw "Vision Runtime Pack must contain exactly one lock, requirements projection and Python installer."
}
if (([string]$lockArtifact[0].sha256).ToLowerInvariant() -ne ([string]$manifest.thirdPartyLockSha256).ToLowerInvariant()) {
    throw "Vision Runtime Pack third-party lock SHA-256 binding is invalid."
}
if (([string]$requirementsArtifact[0].sha256).ToLowerInvariant() -ne ([string]$manifest.runtimeRequirementsSha256).ToLowerInvariant()) {
    throw "Vision Runtime Pack runtimeRequirementsSha256 binding is invalid."
}

$pythonInstaller = Join-Path $BundleRoot (([string]$installerArtifact[0].relativePath).Replace('/', [IO.Path]::DirectorySeparatorChar))
$signature = Get-AuthenticodeSignature -FilePath $pythonInstaller
if ($signature.Status -ne "Valid") { throw "Bundled CPython installer Authenticode signature is not valid: $($signature.Status)" }
$installerVersion = (Get-Item -LiteralPath $pythonInstaller).VersionInfo.ProductVersion
if (-not $installerVersion.StartsWith("3.12.10")) { throw "Bundled CPython installer product version '$installerVersion' does not match the 3.12.10 release." }

# A valid identical v2 component is a no-op. Candidate manifests may carry a
# different assembledFromCommit provenance while identifying the same material
# Runtime Pack. Installed-state integrity is checked against the installed
# manifest; reuse then compares material component identity with the candidate.
$statePath = Join-Path $InstallRoot "runtime-install.json"
$installedPython = Join-Path $InstallRoot "venv\Scripts\python.exe"
$installedManifestPath = Join-Path $InstallRoot "runtime-pack-manifest.json"
if ((Test-Path -LiteralPath $statePath -PathType Leaf) -and (Test-Path -LiteralPath $installedPython -PathType Leaf) -and (Test-Path -LiteralPath $installedManifestPath -PathType Leaf)) {
    try {
        $installedState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $installedManifestObject = Get-Content -LiteralPath $installedManifestPath -Raw | ConvertFrom-Json
        [void](Assert-MaviVisionRuntimePackManifest -Manifest $installedManifestObject)
        $installedIdentity = Get-PythonIdentity -PythonPath $installedPython
        $installedManifestHash = Get-Sha256 $installedManifestPath
        if ([string]$installedState.runtimePackManifestSha256 -ne $installedManifestHash) {
            throw "Installed Vision Runtime Pack state does not bind the installed manifest."
        }
        if (Test-MaviVisionRuntimePackReuse -InstalledState $installedState -Manifest $manifest -RuntimePackManifestSha256 $installedManifestHash -PythonIdentity $installedIdentity) {
            [Environment]::SetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", $InstallRoot, "Machine")
            Write-Host "MAVI Vision Runtime Pack already installed and verified; reusing existing runtime." -ForegroundColor Green
            Write-Host "  Runtime Pack : $($manifest.runtimePackId)"
            Write-Host "  Runtime      : $InstallRoot"
            Write-Host "  Python       : 3.12.10"
            return
        }
    }
    catch { Write-Host "Existing Vision Runtime cannot be reused and will be replaced: $($_.Exception.Message)" -ForegroundColor Yellow }
}

$runtimeBase = Split-Path $InstallRoot -Parent
$pythonRoot = Join-Path $runtimeBase "Python312"
$pythonExe = Resolve-QualifiedPython31210 -PreferredRoot $pythonRoot
if ([string]::IsNullOrWhiteSpace($pythonExe)) {
    Write-Host "Installing qualified CPython 3.12.10 runtime..."
    New-Item -ItemType Directory -Path $runtimeBase -Force | Out-Null
    $installerLog = Join-Path $runtimeBase "python-3.12.10-install.log"
    Remove-Item -LiteralPath $installerLog -Force -ErrorAction SilentlyContinue
    $arguments = @("/quiet", "/log", $installerLog, "InstallAllUsers=1", "TargetDir=$pythonRoot", "PrependPath=0", "Include_launcher=0", "Include_test=0", "Include_pip=1", "Shortcuts=0")
    $process = Start-Process -FilePath $pythonInstaller -ArgumentList $arguments -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) { throw "CPython 3.12.10 installer failed with exit code $($process.ExitCode). Review '$installerLog'." }
    $pythonExe = Resolve-QualifiedPython31210 -PreferredRoot $pythonRoot
}
if ([string]::IsNullOrWhiteSpace($pythonExe)) { throw "CPython installer completed, but no exact Python 3.12.10 interpreter could be resolved." }

$stageRoot = "$InstallRoot.stage"
if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
try {
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $stageRoot "runtime-pack-manifest.json") -Force
    Copy-Item -LiteralPath (Join-Path $BundleRoot "runtime") -Destination (Join-Path $stageRoot "runtime") -Recurse -Force
    $venvRoot = Join-Path $stageRoot "venv"
    Invoke-Checked $pythonExe @("-m", "venv", $venvRoot)
    $venvPython = Join-Path $venvRoot "Scripts\python.exe"
    $lockPath = Join-Path $BundleRoot (([string]$lockArtifact[0].relativePath).Replace('/', [IO.Path]::DirectorySeparatorChar))
    $wheelhouse = Join-Path $BundleRoot "wheels"
    Invoke-Checked $venvPython @("-m", "pip", "install", "--no-index", "--only-binary=:all:", "--require-hashes", "--find-links", $wheelhouse, "-r", $lockPath)
    Invoke-Checked $venvPython @("-m", "pip", "check")
    $identity = Get-PythonIdentity -PythonPath $venvPython
    if ([string]$identity.version -ne "3.12.10" -or [string]$identity.implementation -ne "CPython") { throw "Installed vision runtime Python identity does not match the qualified Windows CPU baseline." }
    $state = New-MaviVisionRuntimeInstallState -Manifest $manifest -RuntimePackManifestSha256 $manifestSha -RuntimeRoot $InstallRoot -PythonIdentity $identity
    Write-MaviJson -Value $state -Path (Join-Path $stageRoot "runtime-install.json") -Depth 8

    if (Test-Path -LiteralPath $InstallRoot) {
        $backup = "$InstallRoot.previous"
        if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
        Move-Item -LiteralPath $InstallRoot -Destination $backup
        try {
            Move-Item -LiteralPath $stageRoot -Destination $InstallRoot
            Remove-Item -LiteralPath $backup -Recurse -Force
        }
        catch {
            if (Test-Path -LiteralPath $InstallRoot) { Remove-Item -LiteralPath $InstallRoot -Recurse -Force -ErrorAction SilentlyContinue }
            Move-Item -LiteralPath $backup -Destination $InstallRoot -ErrorAction SilentlyContinue
            throw
        }
    }
    else { Move-Item -LiteralPath $stageRoot -Destination $InstallRoot }
}
catch {
    if (Test-Path -LiteralPath $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
}

[Environment]::SetEnvironmentVariable("MAVI_VISION_RUNTIME_ROOT", $InstallRoot, "Machine")
Write-Host ""
Write-Host "MAVI Vision Runtime Pack installed and verified." -ForegroundColor Green
Write-Host "  Runtime Pack : $($manifest.runtimePackId)"
Write-Host "  Runtime      : $InstallRoot"
Write-Host "  Python       : 3.12.10"
Write-Host "  Variant      : windows-x86_64-cpu"
Write-Host "  Schema       : mavi-vision-runtime-install-v2"
