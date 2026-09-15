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

if (Test-Path -LiteralPath $destinationRoot) {
    Remove-Item -LiteralPath $destinationRoot -Recurse -Force
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
Write-Host "  Output  : $destinationRoot"
Get-Content -LiteralPath $manifestPath
