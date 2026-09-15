[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDirectory,

    [Parameter(Mandatory = $true)]
    [string]$Version,

    [string]$DestinationRoot = (Join-Path $PSScriptRoot "..\..\vendor\ffmpeg")
)

$ErrorActionPreference = "Stop"

$source = (Resolve-Path $SourceDirectory).Path
$destinationRoot = [System.IO.Path]::GetFullPath($DestinationRoot)
$runtimeId = "win-x64"
$runtimeDestination = Join-Path $destinationRoot $runtimeId

$required = @("ffmpeg.exe", "ffprobe.exe")
foreach ($name in $required) {
    $candidate = Join-Path $source $name
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        throw "Required FFmpeg binary not found: $candidate"
    }
}

foreach ($name in $required) {
    $candidate = Join-Path $source $name
    $versionOutput = & $candidate -version 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0 -or
        $versionOutput.IndexOf($Version, [System.StringComparison]::OrdinalIgnoreCase) -lt 0) {
        throw "$name does not report declared FFmpeg version '$Version'."
    }
}

$licenseCandidates = @(
    (Join-Path $source "LICENSE.txt"),
    (Join-Path $source "LICENSE"),
    (Join-Path (Split-Path $source -Parent) "LICENSE.txt"),
    (Join-Path (Split-Path $source -Parent) "LICENSE")
)
$license = $licenseCandidates |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $license) {
    throw "A licence/notices file is required in the approved FFmpeg package."
}

New-Item -ItemType Directory -Path $destinationRoot -Force | Out-Null
if (Test-Path -LiteralPath $runtimeDestination) {
    Remove-Item -LiteralPath $runtimeDestination -Recurse -Force
}
$existingManifest = Join-Path $destinationRoot "manifest.json"
if (Test-Path -LiteralPath $existingManifest) {
    Remove-Item -LiteralPath $existingManifest -Force
}
New-Item -ItemType Directory -Path $runtimeDestination -Force | Out-Null

Copy-Item -LiteralPath (Join-Path $source "ffmpeg.exe") -Destination $runtimeDestination
Copy-Item -LiteralPath (Join-Path $source "ffprobe.exe") -Destination $runtimeDestination
Copy-Item -LiteralPath $license -Destination (Join-Path $runtimeDestination "LICENSE.txt")

$artifacts = @()
foreach ($name in @("ffmpeg.exe", "ffprobe.exe", "LICENSE.txt")) {
    $path = Join-Path $runtimeDestination $name
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    $artifacts += [ordered]@{
        fileName = $name
        sha256 = $hash
    }
}

$manifest = [ordered]@{
    schemaVersion = "1.0"
    runtimeId = $runtimeId
    version = $Version
    artifacts = $artifacts
}

$manifestPath = Join-Path $destinationRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Staged approved FFmpeg dependency pack:"
Write-Host "  Version : $Version"
Write-Host "  Runtime : $runtimeId"
$manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
Write-Host "  Output  : $destinationRoot"
Write-Host "  Manifest SHA-256: $manifestHash"
Get-Content -LiteralPath $manifestPath
