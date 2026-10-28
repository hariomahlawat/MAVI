[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    # A Windows CPU Runtime Pack bundle root (runtime-pack-manifest.json at its root or under
    # windows-x86_64-cpu\): the pack the component binding names for windows-x86_64-cpu.
    [Parameter(Mandatory = $true)][string]$VisionRuntimeCpuSource,
    # Built Model Pack roots (model-pack-manifest.json at each root). Every Model Pack the
    # binding enables for role vision must be among them, and nothing else.
    [Parameter(Mandatory = $true)][string[]]$ModelPackSource,
    # A Windows CUDA Runtime Pack bundle root, when one is retained (S1b produces it).
    [string]$VisionRuntimeCudaSource,
    # The offline cache holding python-plates-pilot-wheelhouse\ and plates-pilot-payloads\
    # (Prepare-MaviDeveloperOfflineCache.ps1). Defaults to the binary kit's developer cache.
    [string]$PlatesCache,
    [string]$BinaryKitRoot,
    # An optional smoke clip shipped under smoke\. Only media whose licence permits
    # redistribution in the kit (CC0 / CC-BY, plan D3) may be shipped.
    [string]$SmokeClip,
    [string]$SmokeClipLicence,
    # The commit to package; default HEAD. The application and the overlay are both built
    # from a `git archive` of this commit, so uncommitted changes never ship.
    [string]$Revision = "HEAD",
    # Working directory for the export and the publish (never C:).
    [string]$WorkRoot
)

# Assembles the PoC setup bundle (PoC S1; ADR-020), MAVI-PoC-Setup\:
#   Install-MAVI-PoC.cmd, README-FIRST.txt, mavi-poc-bundle.json (every file's SHA-256)
#   overlay\       git-free export of the repository subset the workers and setup read,
#                  with mavi-application-overlay.json (revision + per-file SHA-256)
#   application\api\  the published platform (API + UI, app-local FFmpeg from the kit)
#   prerequisites\postgresql\pg18\win-x64\  and  prerequisites\hosting\win-x64\  (from the kit)
#   vision\runtime\<variant>\, vision\models\<packDirectory>\
#   plates\python-plates-pilot-wheelhouse\, plates\plates-pilot-payloads\
#   smoke\ (optional)
# Runs on a connected preparation machine; the target never downloads anything.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force
Assert-MaviWindows

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$git = (Get-Command git.exe -ErrorAction Stop).Source
$revisionSha = (& $git -C $repoRoot rev-parse --verify "$Revision^{commit}" | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $revisionSha -notmatch '^[0-9a-f]{40}$') { throw "Cannot resolve revision '$Revision'." }

if ([string]::IsNullOrWhiteSpace($BinaryKitRoot)) {
    $sibling = [IO.Path]::GetFullPath((Join-Path $repoRoot "..\MAVI-Offline-Binary-Kit"))
    if (Test-Path -LiteralPath (Join-Path $sibling "mavi-offline-binary-kit.json") -PathType Leaf) { $BinaryKitRoot = $sibling }
}
if ([string]::IsNullOrWhiteSpace($BinaryKitRoot)) { throw "The PoC bundle needs MAVI-Offline-Binary-Kit; pass -BinaryKitRoot." }
$BinaryKitRoot = (Resolve-Path -LiteralPath $BinaryKitRoot).Path
& (Join-Path $PSScriptRoot "Test-MaviOfflineBinaryKit.ps1") -KitRoot $BinaryKitRoot

# The PoC bundle takes four things from the kit: the PostgreSQL runtime pack (with pgvector
# and pg_trgm), FFmpeg and the ASP.NET Core Hosting Bundle. Their catalogue entries must be
# exactly the repository's. The kit's developer caches are not shipped, so their freshness
# (the Development setup's staleness check) does not bear on this bundle.
$repoCatalog = Read-MaviJson -Path (Join-Path $repoRoot "config\dependencies\offline-binary-catalog-v1.json")
$kitCatalog = Read-MaviJson -Path (Join-Path $BinaryKitRoot "catalog\offline-binary-catalog-v1.json")
foreach ($componentId in @("postgresql-win-x64", "pgvector-pg18-win-x64", "ffmpeg-win-x64", "dotnet-hosting-win-x64")) {
    $repoEntry = @($repoCatalog.applicationAndSetup | Where-Object { $_.id -eq $componentId })
    $kitEntry = @($kitCatalog.applicationAndSetup | Where-Object { $_.id -eq $componentId })
    if ($repoEntry.Count -ne 1 -or $kitEntry.Count -ne 1 -or ($repoEntry[0] | ConvertTo-Json -Depth 8 -Compress) -ne ($kitEntry[0] | ConvertTo-Json -Depth 8 -Compress)) {
        throw "MAVI-Offline-Binary-Kit is stale for the PoC bundle: catalogue entry '$componentId' differs from the repository. Rebuild the kit."
    }
}
$postgresPack = Join-Path $BinaryKitRoot "vendor\postgresql\pg18\win-x64"
$postgresManifest = Test-MaviManifest -Root $postgresPack -ManifestPath (Join-Path $postgresPack "manifest.json") -ExpectedSchemaVersion "mavi-postgresql-runtime-pack-v1"
$postgresFiles = @($postgresManifest.artifacts | ForEach-Object { [string]$_.relativePath })
foreach ($required in @("share/extension/pg_trgm.control", "lib/pg_trgm.dll", "share/extension/vector.control")) {
    if (@($postgresFiles | Where-Object { $_ -like "*$required" }).Count -eq 0) { throw "The kit's PostgreSQL runtime pack lacks $required." }
}
$ffmpegPack = Join-Path $BinaryKitRoot "vendor\ffmpeg"
[void](Test-MaviManifest -Root $ffmpegPack -ManifestPath (Join-Path $ffmpegPack "manifest.json"))
$hostingBundle = Join-Path $BinaryKitRoot "vendor\installers\win-x64\dotnet-hosting.exe"
if (-not (Test-Path -LiteralPath $hostingBundle -PathType Leaf)) { throw "The kit has no ASP.NET Core Hosting Bundle." }

# Vision composition: the binding decides what is shipped (ADR-014), as in Setup.
$binding = Read-MaviJson -Path (Join-Path $repoRoot "src\vision\config\components\phase1-bindings-v2.json")
$variants = $binding.runtimePacks[0].variants
function Resolve-MaviPocRuntimeSource {
    param([string]$Root, [string]$Variant)
    $candidate = [IO.Path]::GetFullPath($Root)
    if (-not (Test-Path -LiteralPath (Join-Path $candidate "runtime-pack-manifest.json") -PathType Leaf)) { $candidate = Join-Path $candidate $Variant }
    $manifestPath = Join-Path $candidate "runtime-pack-manifest.json"
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "No $Variant Runtime Pack manifest under '$Root'." }
    $manifest = Read-MaviJson -Path $manifestPath
    $expected = [string]$variants.$Variant.runtimePackId
    if ([string]$manifest.runtimePackId -ne $expected -or [string]$manifest.platformVariant -ne $Variant) {
        throw "The $Variant Runtime Pack at '$candidate' is '$($manifest.runtimePackId)'; the binding names '$expected'."
    }
    return $candidate
}
$cpuSource = Resolve-MaviPocRuntimeSource -Root $VisionRuntimeCpuSource -Variant "windows-x86_64-cpu"
$cudaSource = if ($VisionRuntimeCudaSource) { Resolve-MaviPocRuntimeSource -Root $VisionRuntimeCudaSource -Variant "windows-x86_64-cuda" } else { $null }
$boundModelPackIds = @($binding.capabilityBindings | Where-Object { $_.roleId -eq "vision" -and $_.enabled } | ForEach-Object { [string]$_.modelPackId } | Sort-Object -Unique)
$modelSources = @{}
foreach ($root in $ModelPackSource) {
    $full = [IO.Path]::GetFullPath($root)
    $manifest = Read-MaviJson -Path (Join-Path $full "model-pack-manifest.json")
    $modelSources[[string]$manifest.modelPackId] = $full
}
foreach ($id in $boundModelPackIds) { if (-not $modelSources.ContainsKey($id)) { throw "Bound Model Pack '$id' was not supplied." } }
foreach ($id in $modelSources.Keys) { if ($boundModelPackIds -notcontains $id) { throw "Model Pack '$id' is not bound for role vision; it would not be used." } }

if ([string]::IsNullOrWhiteSpace($PlatesCache)) { $PlatesCache = Join-Path $BinaryKitRoot "vendor\developer-cache\win-x64" }
$PlatesCache = [IO.Path]::GetFullPath($PlatesCache)
foreach ($name in @("python-plates-pilot-wheelhouse", "plates-pilot-payloads")) {
    if (-not (Test-Path -LiteralPath (Join-Path $PlatesCache $name) -PathType Container)) { throw "The plates cache '$PlatesCache' has no $name\ (Prepare-MaviDeveloperOfflineCache.ps1)." }
}
if ($SmokeClip -and [string]::IsNullOrWhiteSpace($SmokeClipLicence)) { throw "A shipped smoke clip needs -SmokeClipLicence (CC0 / CC-BY attribution text)." }

$destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destination) {
    if (@(Get-ChildItem -LiteralPath $destination -Force).Count -gt 0) { throw "Destination '$destination' is not empty." }
}
if ([string]::IsNullOrWhiteSpace($WorkRoot)) { $WorkRoot = Join-Path (Split-Path $destination -Parent) ("mavi-poc-bundle-work-" + [Guid]::NewGuid().ToString("N")) }
$WorkRoot = [IO.Path]::GetFullPath($WorkRoot)
New-Item -ItemType Directory -Path $destination, $WorkRoot -Force | Out-Null

function Copy-MaviPocTree {
    param([string]$Source, [string]$Target)
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    & robocopy.exe $Source $Target /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NP /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "robocopy failed copying '$Source' with exit code $LASTEXITCODE." }
}

try {
    # 1. One export of the exact commit; both the publish and the overlay come from it.
    $export = Join-Path $WorkRoot "source"
    New-Item -ItemType Directory -Path $export -Force | Out-Null
    $archive = Join-Path $WorkRoot "source.tar"
    & $git -C $repoRoot archive --format=tar -o $archive $revisionSha
    if ($LASTEXITCODE -ne 0) { throw "git archive failed." }
    # Windows bsdtar explicitly: a GNU tar earlier on PATH (Git for Windows) reads "E:" as a remote host.
    & (Join-Path $env:SystemRoot "System32\tar.exe") -xf $archive -C $export
    if ($LASTEXITCODE -ne 0) { throw "Extracting the source archive failed." }

    # 2. Platform publish (framework-dependent; ASP.NET Core 10 comes from the Hosting Bundle).
    $publish = Join-Path $destination "application\api"
    & dotnet publish (Join-Path $export "src\platform\Mavi.Api\Mavi.Api.csproj") -c Release -r win-x64 --self-contained false `
        "-p:MaviBuild=poc-$($revisionSha.Substring(0, 12))" "-p:MaviCommit=$revisionSha" "-p:MaviNativeMediaToolsDirectory=$ffmpegPack" -o $publish
    if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed." }
    if (-not (Test-Path -LiteralPath (Join-Path $publish "wwwroot\index.html") -PathType Leaf)) { throw "The publish has no UI (wwwroot\index.html)." }
    [void](Test-MaviManifest -Root (Join-Path $publish "tools\ffmpeg") -ManifestPath (Join-Path $publish "tools\ffmpeg\manifest.json"))

    # 3. Application overlay: the repository subset the setup scripts and workers read, in
    #    the repository layout, with its revision and per-file hashes.
    $overlay = Join-Path $destination "overlay"
    foreach ($subset in @("config", "contracts", "models", "src\vision", "tools")) {
        Copy-MaviPocTree -Source (Join-Path $export $subset) -Target (Join-Path $overlay $subset)
    }
    $overlayPrefix = $overlay.TrimEnd("\") + "\"
    $overlayArtifacts = @(Get-ChildItem -LiteralPath $overlay -Recurse -File | Sort-Object FullName | ForEach-Object {
        [ordered]@{ relativePath = $_.FullName.Substring($overlayPrefix.Length).Replace("\", "/"); sha256 = (Get-MaviSha256 -Path $_.FullName); sizeBytes = [long]$_.Length }
    })
    Write-MaviJson -Value ([ordered]@{ schemaVersion = "mavi-application-overlay-v1"; revision = $revisionSha; profile = (Get-MaviPocProfile); artifacts = $overlayArtifacts }) -Path (Join-Path $overlay "mavi-application-overlay.json") -Depth 6

    # 4. Prerequisites from the kit.
    Copy-MaviPocTree -Source $postgresPack -Target (Join-Path $destination "prerequisites\postgresql\pg18\win-x64")
    New-Item -ItemType Directory -Path (Join-Path $destination "prerequisites\hosting\win-x64") -Force | Out-Null
    Copy-Item -LiteralPath $hostingBundle -Destination (Join-Path $destination "prerequisites\hosting\win-x64\dotnet-hosting.exe")

    # 5. Vision packs and the plates cache.
    Copy-MaviPocTree -Source $cpuSource -Target (Join-Path $destination "vision\runtime\windows-x86_64-cpu")
    if ($cudaSource) { Copy-MaviPocTree -Source $cudaSource -Target (Join-Path $destination "vision\runtime\windows-x86_64-cuda") }
    foreach ($entry in $modelSources.GetEnumerator()) {
        $manifest = Read-MaviJson -Path (Join-Path $entry.Value "model-pack-manifest.json")
        $packDirectory = @($manifest.artifacts)[0].relativePath.Split("/")[0]
        Copy-MaviPocTree -Source $entry.Value -Target (Join-Path $destination "vision\models\$packDirectory")
    }
    foreach ($name in @("python-plates-pilot-wheelhouse", "plates-pilot-payloads")) {
        Copy-MaviPocTree -Source (Join-Path $PlatesCache $name) -Target (Join-Path $destination "plates\$name")
    }
    if ($SmokeClip) {
        New-Item -ItemType Directory -Path (Join-Path $destination "smoke") -Force | Out-Null
        Copy-Item -LiteralPath $SmokeClip -Destination (Join-Path $destination "smoke\$([IO.Path]::GetFileName($SmokeClip))")
        [IO.File]::WriteAllText((Join-Path $destination "smoke\LICENCE.txt"), $SmokeClipLicence + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    }

    # 6. Launcher and operator note.
    Copy-Item -LiteralPath (Join-Path $overlay "tools\setup\poc\Install-MAVI-PoC.cmd") -Destination (Join-Path $destination "Install-MAVI-PoC.cmd")
    $readme = @(
        "MAVI proof of concept - profile poc-single-host (ADR-020)",
        "",
        (Get-MaviPocDisclosureStatement),
        "This is not a Production installation and never becomes one by configuration.",
        "",
        "Install: double-click Install-MAVI-PoC.cmd and approve the Administrator prompt.",
        "No network is needed or used. Defaults: %ProgramFiles%\MAVI\PoC and %ProgramData%\MAVI\PoC;",
        "from an elevated prompt you may pass -InstallRoot, -DataRoot, -DevicePolicy Auto|CUDA|CPU, -PlanOnly.",
        "Then: Start-MAVI-PoC.cmd and Test-MAVI-PoC.cmd -ClipPath <clip.mp4> in the install folder.",
        "",
        "Application revision: $revisionSha"
    ) -join [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $destination "README-FIRST.txt"), $readme + [Environment]::NewLine, [Text.Encoding]::ASCII)

    # 7. The bundle manifest: every file but itself.
    $prefix = $destination.TrimEnd("\") + "\"
    $artifacts = @(Get-ChildItem -LiteralPath $destination -Recurse -File | Where-Object { $_.Name -ne "mavi-poc-bundle.json" } | Sort-Object FullName | ForEach-Object {
        [ordered]@{ relativePath = $_.FullName.Substring($prefix.Length).Replace("\", "/"); sha256 = (Get-MaviSha256 -Path $_.FullName); sizeBytes = [long]$_.Length }
    })
    $manifest = [ordered]@{
        schemaVersion = "mavi-poc-setup-bundle-v1"
        profile = (Get-MaviPocProfile)
        productionQualified = $false
        evidenceClass = "Development"
        applicationRevision = $revisionSha
        sourceBinaryKitManifestSha256 = (Get-MaviSha256 -Path (Join-Path $BinaryKitRoot "mavi-offline-binary-kit.json"))
        contains = [ordered]@{
            cudaRuntimePack = [bool]$cudaSource
            modelPackIds = @($boundModelPackIds)
            smokeClip = [bool]$SmokeClip
        }
        artifacts = $artifacts
    }
    Write-MaviJson -Value $manifest -Path (Join-Path $destination "mavi-poc-bundle.json") -Depth 8
    Write-Host "MAVI PoC setup bundle created." -ForegroundColor Green
    Write-Host "  Destination : $destination"
    Write-Host "  Revision    : $revisionSha"
    Write-Host "  Files       : $($artifacts.Count)"
    Write-Host "  CUDA pack   : $(if ($cudaSource) { 'included' } else { 'not included (Auto resolves CPU unless -AdoptCudaRuntimeRoot is used at install)' })"
    Write-Host "  Manifest    : $(Get-MaviSha256 -Path (Join-Path $destination 'mavi-poc-bundle.json'))"
}
finally {
    Remove-Item -LiteralPath $WorkRoot -Recurse -Force -ErrorAction SilentlyContinue
}
