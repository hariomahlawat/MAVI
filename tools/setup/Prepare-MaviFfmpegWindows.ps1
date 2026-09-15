[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [string]$CacheRoot = (Join-Path $env:LOCALAPPDATA "MAVI\preparation-cache"),
    [switch]$ForceDownload
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Assert-MaviWindows

$repositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$catalogPath = Join-Path $repositoryRoot "config\dependencies\offline-binary-catalog-v1.json"
$catalog = Read-MaviJson -Path $catalogPath

$ffmpeg = @($catalog.applicationAndSetup | Where-Object { [string]$_.id -eq "ffmpeg-win-x64" }) | Select-Object -First 1
if (-not $ffmpeg) {
    throw "FFmpeg is not declared in the offline binary catalog."
}

$sourceProperty = $ffmpeg.PSObject.Properties["acquisitionSource"]
if (-not $sourceProperty) {
    throw "FFmpeg catalog entry has no connected-preparation acquisition source."
}

$source = $sourceProperty.Value
if (-not [bool]$source.connectedPreparationOnly) {
    throw "FFmpeg acquisition source must be marked connectedPreparationOnly."
}

$uri = [string]$source.url
$archiveName = [string]$source.archiveName
$expectedHash = ([string]$source.sha256).ToLowerInvariant()
$version = [string]$ffmpeg.baselineVersion

if ($uri -notmatch "^https://") {
    throw "FFmpeg acquisition URL must use HTTPS."
}
if ($expectedHash -notmatch "^[0-9a-f]{64}$") {
    throw "FFmpeg acquisition SHA-256 is invalid."
}
if ([string]::IsNullOrWhiteSpace($version) -or $version -eq "from-staged-manifest") {
    throw "FFmpeg catalog baselineVersion must be pinned for connected preparation."
}

New-Item -ItemType Directory -Path $CacheRoot -Force | Out-Null
$archivePath = Join-Path $CacheRoot $archiveName

$needsDownload = $ForceDownload -or -not (Test-Path -LiteralPath $archivePath -PathType Leaf)
if (-not $needsDownload) {
    $actualHash = Get-MaviSha256 -Path $archivePath
    if ($actualHash -ne $expectedHash) {
        Remove-Item -LiteralPath $archivePath -Force
        $needsDownload = $true
    }
}

if ($needsDownload) {
    Write-Host "Downloading approved FFmpeg $version preparation archive..."
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $archivePath
}

$actualArchiveHash = Get-MaviSha256 -Path $archivePath
if ($actualArchiveHash -ne $expectedHash) {
    Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
    throw "Downloaded FFmpeg archive failed SHA-256 verification."
}

$extractRoot = Join-Path ([IO.Path]::GetTempPath()) ("mavi-ffmpeg-" + [Guid]::NewGuid().ToString("N"))
try {
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractRoot -Force

    $ffmpegExe = Get-ChildItem -LiteralPath $extractRoot -Filter "ffmpeg.exe" -File -Recurse |
        Select-Object -First 1
    if (-not $ffmpegExe) {
        throw "Approved FFmpeg archive did not contain ffmpeg.exe."
    }

    $binRoot = $ffmpegExe.Directory.FullName
    $ffprobePath = Join-Path $binRoot "ffprobe.exe"
    if (-not (Test-Path -LiteralPath $ffprobePath -PathType Leaf)) {
        throw "Approved FFmpeg archive did not contain ffprobe.exe beside ffmpeg.exe."
    }

    $stageScript = Join-Path $repositoryRoot "tools\native\stage_ffmpeg_windows.ps1"
    $destinationRoot = Join-Path $repositoryRoot "vendor\ffmpeg"

    & $stageScript -SourceDirectory $binRoot -Version $version -DestinationRoot $destinationRoot

    $manifestPath = Join-Path $destinationRoot "manifest.json"
    [void](Test-MaviManifest -Root $destinationRoot -ManifestPath $manifestPath -ExpectedSchemaVersion "1.0")

    $stagedProbe = Join-Path $destinationRoot "win-x64\ffprobe.exe"
    $probe = Invoke-MaviCommand -FilePath $stagedProbe -Arguments @("-version") -CaptureOutput
    if ($probe.StandardOutput.IndexOf($version, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "Staged ffprobe does not report the approved version '$version'."
    }

    Write-Host ""
    Write-Host "MAVI FFmpeg preparation PASSED."
    Write-Host "  Version      : $version"
    Write-Host "  Archive hash : $actualArchiveHash"
    Write-Host "  Staged pack  : $destinationRoot"
    Write-Host ""
    Write-Host "Rebuild Mavi.Api so the app-local tools are copied into the build output."
}
finally {
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
}
