[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force

$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("mavi-setup-contracts-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

try {
    $genericRoot = Join-Path $tempRoot "generic"
    New-Item -ItemType Directory -Path $genericRoot -Force | Out-Null
    $genericFile = Join-Path $genericRoot "payload.bin"
    [IO.File]::WriteAllText($genericFile, "mavi-setup-contract", [Text.UTF8Encoding]::new($false))
    $genericHash = (Get-FileHash -LiteralPath $genericFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $genericSize = (Get-Item -LiteralPath $genericFile).Length
    $genericManifest = [ordered]@{
        schemaVersion = "mavi-test-manifest-v1"
        artifacts = @(
            [ordered]@{
                relativePath = "payload.bin"
                sha256 = $genericHash
                sizeBytes = [long]$genericSize
            }
        )
    }
    $genericManifestPath = Join-Path $genericRoot "manifest.json"
    $genericManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $genericManifestPath -Encoding UTF8
    [void](Test-MaviManifest -Root $genericRoot -ManifestPath $genericManifestPath -ExpectedSchemaVersion "mavi-test-manifest-v1")

    $ffmpegRoot = Join-Path $tempRoot "ffmpeg"
    $ffmpegRuntime = Join-Path $ffmpegRoot "win-x64"
    New-Item -ItemType Directory -Path $ffmpegRuntime -Force | Out-Null
    $ffprobeFile = Join-Path $ffmpegRuntime "ffprobe.exe"
    [IO.File]::WriteAllText($ffprobeFile, "not-an-executable-contract-fixture", [Text.UTF8Encoding]::new($false))
    $ffprobeHash = (Get-FileHash -LiteralPath $ffprobeFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $ffmpegManifest = [ordered]@{
        schemaVersion = "1.0"
        runtimeId = "win-x64"
        version = "test"
        artifacts = @(
            [ordered]@{
                fileName = "ffprobe.exe"
                sha256 = $ffprobeHash
            }
        )
    }
    $ffmpegManifestPath = Join-Path $ffmpegRoot "manifest.json"
    $ffmpegManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ffmpegManifestPath -Encoding UTF8
    [void](Test-MaviManifest -Root $ffmpegRoot -ManifestPath $ffmpegManifestPath -ExpectedSchemaVersion "1.0")

    [IO.File]::AppendAllText($ffprobeFile, "tamper")
    $tamperRejected = $false
    try {
        [void](Test-MaviManifest -Root $ffmpegRoot -ManifestPath $ffmpegManifestPath -ExpectedSchemaVersion "1.0")
    }
    catch {
        $tamperRejected = $true
    }
    if (-not $tamperRejected) {
        throw "Manifest verifier accepted a tampered FFmpeg artifact."
    }

    $password = New-MaviPassword
    if ($password.Length -ne 32 -or $password.Contains(";") -or $password.Contains("=")) {
        throw "Generated database password does not satisfy the connection-string-safe setup contract."
    }

    $planBundle = Join-Path $tempRoot "plan-bundle"
    $runtimeRoot = Join-Path $planBundle "prerequisites\postgresql\pg18\win-x64"
    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $runtimeManifestPath = Join-Path $runtimeRoot "manifest.json"
    [IO.File]::WriteAllText($runtimeManifestPath, "{}", [Text.UTF8Encoding]::new($false))

    $setupScript = Join-Path $repoRoot "tools\setup\Setup-MAVI.ps1"
    $developmentPlan = & $setupScript -Profile Development -BundleRoot $planBundle -RepositoryRoot $repoRoot -PlanOnly | Out-String
    if ($developmentPlan -notmatch '"port"\s*:\s*55433') {
        throw "Development plan did not resolve the dedicated MAVI PostgreSQL port."
    }

    $relativeRuntimeManifest = "prerequisites/postgresql/pg18/win-x64/manifest.json"
    $runtimeHash = (Get-FileHash -LiteralPath $runtimeManifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $runtimeSize = (Get-Item -LiteralPath $runtimeManifestPath).Length
    $bundleManifest = [ordered]@{
        schemaVersion = "mavi-offline-setup-bundle-v1"
        artifacts = @(
            [ordered]@{
                relativePath = $relativeRuntimeManifest
                sha256 = $runtimeHash
                sizeBytes = [long]$runtimeSize
            }
        )
    }
    $bundleManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $planBundle "mavi-offline-bundle.json") -Encoding UTF8

    $productionPlan = & $setupScript -Profile Production -BundleRoot $planBundle -RepositoryRoot $repoRoot -PlanOnly | Out-String
    if ($productionPlan -notmatch '"port"\s*:\s*55432' -or
        $productionPlan -notmatch '"httpPort"\s*:\s*8080') {
        throw "Production plan did not resolve the canonical MAVI ports."
    }

    Write-Host "MAVI setup contract validation PASSED."
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
