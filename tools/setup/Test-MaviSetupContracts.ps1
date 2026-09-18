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

    # PostgreSQL's standard Windows version text includes parentheses:
    #   postgres (PostgreSQL) 18.6
    # Keep this as a regression contract so setup/staging scripts do not
    # reintroduce the earlier overly strict "PostgreSQL 18.x" match.
    if (-not (Test-MaviPostgreSqlMajorVersionOutput -VersionOutput "postgres (PostgreSQL) 18.6" -Major 18)) {
        throw "PostgreSQL version parser rejected standard PostgreSQL 18 version output."
    }
    if (Test-MaviPostgreSqlMajorVersionOutput -VersionOutput "postgres (PostgreSQL) 17.9" -Major 18) {
        throw "PostgreSQL version parser accepted the wrong major version."
    }

    # Regression guard: the disconnected Development test pass imports packages
    # from tools/requirements.txt (for example jsonschema). The connected cache
    # builder must acquire that closure, and offline setup must install it before
    # invoking pytest.
    $cacheBuilderText = Get-Content -LiteralPath (Join-Path $repoRoot "tools\setup\Prepare-MaviDeveloperOfflineCache.ps1") -Raw
    if ($cacheBuilderText -notmatch '(?s)pip\s+download.*-r\s+\$toolsRequirements') {
        throw "Developer offline-cache preparation does not include tools/requirements.txt."
    }

    $windowsSetupText = Get-Content -LiteralPath (Join-Path $repoRoot "tools\setup\Mavi.Setup.Windows.psm1") -Raw
    if ($windowsSetupText -notmatch '(?s)pip.*install.*--no-index.*-r.*\$toolsRequirements') {
        throw "Development setup does not install tools/requirements.txt from the offline wheelhouse."
    }

    $visionInstallerText = Get-Content -LiteralPath (Join-Path $repoRoot "tools\setup\Install-MaviVisionRuntime.ps1") -Raw
    foreach ($requiredFragment in @(
        "runtime-pack-manifest.json",
        "mavi-vision-runtime-pack-v2",
        "mavi-vision-runtime-install-v2",
        "windows-x86_64-cpu",
        "windows-x86_64-cuda",
        "Python 3.12.10",
        "--no-index",
        "--only-binary=:all:",
        "--require-hashes",
        "runtimePackId",
        "thirdPartyLockSha256",
        "runtimeRequirementsSha256",
        "Test-MaviVisionRuntimePackReuse",
        "Get-AuthenticodeSignature"
    )) {
        if ($visionInstallerText -notmatch [regex]::Escape($requiredFragment)) {
            throw "Vision runtime installer is missing required contract fragment: $requiredFragment"
        }
    }
    foreach ($forbiddenFragment in @(
        "Assert-MaviVisionRuntimeSourceCompatible",
        "BundleSourceCommit"
    )) {
        if ($visionInstallerText -match [regex]::Escape($forbiddenFragment)) {
            throw "Vision runtime installer still uses obsolete commit-coupled contract: $forbiddenFragment"
        }
    }

    $visionLauncherText = Get-Content -LiteralPath (Join-Path $repoRoot "tools\setup\Start-MaviVisionWorker.ps1") -Raw
    foreach ($requiredFragment in @(
        "MAVI_VISION_RUNTIME_ROOT",
        "MAVI_VISION_RUNTIME_WINDOWS_CPU_ROOT",
        "MAVI_VISION_RUNTIME_WINDOWS_CUDA_ROOT",
        "DevicePolicy = \"auto\"",
        "MAVI_MODEL_ROOT",
        "MAVI_RUNTIME_PROFILE_PATH",
        "MAVI_QUALIFICATION_RECORD_PATH",
        "mavi_vision.worker.main"
    )) {
        if ($visionLauncherText -notmatch [regex]::Escape($requiredFragment)) {
            throw "Vision worker launcher is missing required contract fragment: $requiredFragment"
        }
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


    # Companion binary-kit contract: nested manifests, catalog binding and tamper rejection.
    $kitRoot = Join-Path $tempRoot "binary-kit"
    $kitCatalogRoot = Join-Path $kitRoot "catalog"
    $kitPostgresRoot = Join-Path $kitRoot "vendor\postgresql\pg18\win-x64"
    $kitFfmpegRoot = Join-Path $kitRoot "vendor\ffmpeg"
    $kitFfmpegRuntime = Join-Path $kitFfmpegRoot "win-x64"
    $kitInstallerRoot = Join-Path $kitRoot "vendor\installers\win-x64"
    $kitCacheRoot = Join-Path $kitRoot "vendor\developer-cache\win-x64"
    foreach ($directory in @(
        $kitCatalogRoot,
        (Join-Path $kitPostgresRoot "bin"),
        (Join-Path $kitPostgresRoot "share\extension"),
        $kitFfmpegRuntime,
        $kitInstallerRoot,
        (Join-Path $kitCacheRoot "nuget-packages"),
        (Join-Path $kitCacheRoot "npm-cache"),
        (Join-Path $kitCacheRoot "python-wheelhouse")
    )) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $kitCatalogPath = Join-Path $kitCatalogRoot "offline-binary-catalog-v1.json"
    Copy-Item -LiteralPath (Join-Path $repoRoot "config\dependencies\offline-binary-catalog-v1.json") -Destination $kitCatalogPath
    $kitCatalog = Read-MaviJson -Path $kitCatalogPath

    $postgresFixture = Join-Path $kitPostgresRoot "bin\postgres.exe"
    $vectorFixture = Join-Path $kitPostgresRoot "share\extension\vector.control"
    [IO.File]::WriteAllText($postgresFixture, "postgres-18-fixture", [Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText($vectorFixture, "vector-fixture", [Text.UTF8Encoding]::new($false))
    $postgresManifest = [ordered]@{
        schemaVersion = "mavi-postgresql-runtime-pack-v1"
        runtimeId = "win-x64"
        postgresqlMajorVersion = 18
        postgresqlVersion = "18.99-test"
        pgvectorVersion = "0.99-test"
        artifacts = @(
            [ordered]@{
                relativePath = "bin/postgres.exe"
                sha256 = (Get-MaviSha256 -Path $postgresFixture)
                sizeBytes = [long](Get-Item $postgresFixture).Length
            },
            [ordered]@{
                relativePath = "share/extension/vector.control"
                sha256 = (Get-MaviSha256 -Path $vectorFixture)
                sizeBytes = [long](Get-Item $vectorFixture).Length
            }
        )
    }
    Write-MaviJson -Value $postgresManifest -Path (Join-Path $kitPostgresRoot "manifest.json") -Depth 6

    $ffmpegFixture = Join-Path $kitFfmpegRuntime "ffmpeg.exe"
    [IO.File]::WriteAllText($ffmpegFixture, "ffmpeg-fixture", [Text.UTF8Encoding]::new($false))
    $ffmpegKitManifest = [ordered]@{
        schemaVersion = "1.0"
        runtimeId = "win-x64"
        version = "test-ffmpeg"
        artifacts = @(
            [ordered]@{
                fileName = "ffmpeg.exe"
                sha256 = (Get-MaviSha256 -Path $ffmpegFixture)
                sizeBytes = [long](Get-Item $ffmpegFixture).Length
            }
        )
    }
    Write-MaviJson -Value $ffmpegKitManifest -Path (Join-Path $kitFfmpegRoot "manifest.json") -Depth 6

    foreach ($installer in @("dotnet-hosting.exe", "dotnet-sdk.exe", "node.msi", "python.exe")) {
        [IO.File]::WriteAllText((Join-Path $kitInstallerRoot $installer), "installer-$installer", [Text.UTF8Encoding]::new($false))
    }
    foreach ($cache in @("nuget-packages", "npm-cache", "python-wheelhouse")) {
        [IO.File]::WriteAllText((Join-Path $kitCacheRoot "$cache\fixture.bin"), "cache-$cache", [Text.UTF8Encoding]::new($false))
    }
    $developerCacheManifest = [ordered]@{
        schemaVersion = "mavi-developer-offline-cache-v1"
        sourceInputs = [ordered]@{
            offlineDependencyPolicySha256 = (Get-MaviSha256 -Path (Join-Path $repoRoot "config\dependencies\offline-dependency-policy-v1.json"))
            globalJsonSha256 = (Get-MaviSha256 -Path (Join-Path $repoRoot "global.json"))
            packageLockSha256 = (Get-MaviSha256 -Path (Join-Path $repoRoot "src\web\mavi-web\package-lock.json"))
            visionPyprojectSha256 = (Get-MaviSha256 -Path (Join-Path $repoRoot "src\vision\pyproject.toml"))
            toolsRequirementsSha256 = (Get-MaviSha256 -Path (Join-Path $repoRoot "tools\requirements.txt"))
        }
        nugetPackages = @()
        npmPackages = @()
        pythonArtifacts = @()
    }
    $developerCacheManifestPath = Join-Path $kitCacheRoot "developer-cache-manifest.json"
    Write-MaviJson -Value $developerCacheManifest -Path $developerCacheManifestPath -Depth 6
    [IO.File]::WriteAllText((Join-Path $kitRoot "README-FIRST.txt"), "binary-kit-fixture", [Text.UTF8Encoding]::new($false))

    $kitFiles = @(
        Get-ChildItem -LiteralPath $kitRoot -File -Recurse |
            Where-Object { $_.Name -ne "mavi-offline-binary-kit.json" } |
            Sort-Object FullName
    )
    $kitPrefix = $kitRoot.TrimEnd("\") + "\"
    $kitArtifacts = foreach ($file in $kitFiles) {
        [ordered]@{
            relativePath = $file.FullName.Substring($kitPrefix.Length).Replace("\", "/")
            sha256 = (Get-MaviSha256 -Path $file.FullName)
            sizeBytes = [long]$file.Length
        }
    }
    $kitManifest = [ordered]@{
        schemaVersion = "mavi-offline-binary-kit-v1"
        sourceCatalogSha256 = (Get-MaviSha256 -Path $kitCatalogPath)
        sourceInputs = [ordered]@{
            offlineDependencyPolicy = (Get-MaviSha256 -Path (Join-Path $repoRoot "config\dependencies\offline-dependency-policy-v1.json"))
            offlineBinaryCatalog = (Get-MaviSha256 -Path (Join-Path $repoRoot "config\dependencies\offline-binary-catalog-v1.json"))
            globalJson = (Get-MaviSha256 -Path (Join-Path $repoRoot "global.json"))
            webPackageLock = (Get-MaviSha256 -Path (Join-Path $repoRoot "src\web\mavi-web\package-lock.json"))
            visionPyproject = (Get-MaviSha256 -Path (Join-Path $repoRoot "src\vision\pyproject.toml"))
            toolsRequirements = (Get-MaviSha256 -Path (Join-Path $repoRoot "tools\requirements.txt"))
        }
        versions = [ordered]@{
            postgresql = "18.99-test"
            pgvector = "0.99-test"
            ffmpeg = "test-ffmpeg"
            dotnetHostingBaseline = "10.0.11"
            dotnetSdkBaseline = "10.0.100"
            nodeBaseline = "22.22.2"
            pythonDevelopmentBaseline = "3.13"
            observedInstallers = [ordered]@{
                dotnetHosting = [ordered]@{
                    fileName = "dotnet-hosting.exe"
                    fileVersion = "10.0.11-test"
                    productVersion = "10.0.11-test"
                    sha256 = (Get-MaviSha256 -Path (Join-Path $kitInstallerRoot "dotnet-hosting.exe"))
                    sizeBytes = [long](Get-Item (Join-Path $kitInstallerRoot "dotnet-hosting.exe")).Length
                }
                dotnetSdk = [ordered]@{
                    fileName = "dotnet-sdk.exe"
                    fileVersion = "10.0.100-test"
                    productVersion = "10.0.100-test"
                    sha256 = (Get-MaviSha256 -Path (Join-Path $kitInstallerRoot "dotnet-sdk.exe"))
                    sizeBytes = [long](Get-Item (Join-Path $kitInstallerRoot "dotnet-sdk.exe")).Length
                }
                node = [ordered]@{
                    fileName = "node.msi"
                    productVersion = "22.23.0-test"
                    sha256 = (Get-MaviSha256 -Path (Join-Path $kitInstallerRoot "node.msi"))
                    sizeBytes = [long](Get-Item (Join-Path $kitInstallerRoot "node.msi")).Length
                }
                pythonDevelopment = [ordered]@{
                    fileName = "python.exe"
                    fileVersion = "3.13.0-test"
                    productVersion = "3.13.0-test"
                    sha256 = (Get-MaviSha256 -Path (Join-Path $kitInstallerRoot "python.exe"))
                    sizeBytes = [long](Get-Item (Join-Path $kitInstallerRoot "python.exe")).Length
                }
            }
            developerCacheManifestSha256 = (Get-MaviSha256 -Path $developerCacheManifestPath)
        }
        artifacts = @($kitArtifacts)
    }
    Write-MaviJson -Value $kitManifest -Path (Join-Path $kitRoot "mavi-offline-binary-kit.json") -Depth 8

    $binaryKitVerifier = Join-Path $repoRoot "tools\setup\Test-MaviOfflineBinaryKit.ps1"
    & $binaryKitVerifier -KitRoot $kitRoot

    $binaryKitPlan = & $setupScript -Profile Development -BundleRoot $kitRoot -RepositoryRoot $repoRoot -PlanOnly | Out-String
    if ($binaryKitPlan -notmatch '"port"\s*:\s*55433' -or
        $binaryKitPlan -notmatch 'vendor\\\\postgresql\\\\pg18\\\\win-x64') {
        throw "Development plan did not resolve the verified companion binary kit."
    }

    $nodeFixture = Join-Path $kitInstallerRoot "node.msi"
    [IO.File]::AppendAllText($nodeFixture, "tamper")
    $kitTamperRejected = $false
    try {
        & $binaryKitVerifier -KitRoot $kitRoot
    }
    catch {
        $kitTamperRejected = $true
    }
    if (-not $kitTamperRejected) {
        throw "Offline binary kit verifier accepted a tampered installer."
    }

    Write-Host "MAVI setup contract validation PASSED."
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}