param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("fresh-install", "offline-update")]
    [string]$Mode,
    [Parameter(Mandatory = $true)][string]$ArtifactDirectory,
    [Parameter(Mandatory = $true)][string]$ApplicationManifestPath,
    [Parameter(Mandatory = $true)][string]$Destination,
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$SupportedUpdatesPath,
    [Parameter(Mandatory = $true)][string]$EvidenceOutput,
    [Parameter(Mandatory = $true)][string]$IisSiteName,
    [Parameter(Mandatory = $true)][string]$AppPoolName,
    [string]$MigrationScriptPath,
    [string]$PreUpdateAcceptanceEvidence,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-HostIdentitySha256 {
    $hostname = ([Environment]::MachineName).Trim().ToLowerInvariant()
    $machineGuid = (Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Cryptography" -Name MachineGuid -ErrorAction Stop).MachineGuid
    $machineGuid = ([string]$machineGuid).Trim().ToLowerInvariant()
    if (-not $hostname -or -not $machineGuid) { throw "windows_host_identity_missing" }
    $canonical = "windows|$hostname|$machineGuid"
    $bytes = [Text.Encoding]::UTF8.GetBytes($canonical)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-", "").ToLowerInvariant()
    } finally {
        $sha.Dispose()
    }
}

function Assert-InternetUnavailable {
    $proxyNames = @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    foreach ($name in $proxyNames) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ($value) { throw "internet_proxy_configured:$name" }
    }

    $probes = @(
        @{ Host = "1.1.1.1"; Port = 443 },
        @{ Host = "8.8.8.8"; Port = 53 },
        @{ Host = "pypi.org"; Port = 443 },
        @{ Host = "github.com"; Port = 443 },
        @{ Host = "www.microsoft.com"; Port = 443 }
    )
    $observations = @()
    foreach ($probe in $probes) {
        $reachable = Test-NetConnection -ComputerName $probe.Host -Port $probe.Port -InformationLevel Quiet -WarningAction SilentlyContinue
        $observations += [ordered]@{
            host = [string]$probe.Host
            port = [int]$probe.Port
            reachable = [bool]$reachable
        }
        if ($reachable) { throw "internet_connectivity_detected:$($probe.Host):$($probe.Port)" }
    }
    return [ordered]@{
        proxyEnvironmentAbsent = $true
        probes = $observations
        passed = $true
    }
}

function Invoke-AppCmd([string[]]$Arguments) {
    $appcmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    if (-not (Test-Path -LiteralPath $appcmd -PathType Leaf)) { throw "iis_appcmd_missing" }
    & $appcmd @Arguments
    if ($LASTEXITCODE -ne 0) { throw "iis_appcmd_failed:$($Arguments -join ' ')" }
}

function Invoke-AppCmdText([string[]]$Arguments) {
    $appcmd = Join-Path $env:windir "System32\inetsrv\appcmd.exe"
    if (-not (Test-Path -LiteralPath $appcmd -PathType Leaf)) { throw "iis_appcmd_missing" }
    $output = & $appcmd @Arguments
    if ($LASTEXITCODE -ne 0) { throw "iis_appcmd_failed:$($Arguments -join ' ')" }
    return ([string]($output | Select-Object -First 1)).Trim()
}

function Assert-IisHostingBinding([string]$SiteName, [string]$ExpectedPool, [string]$ExpectedDestination) {
    $applicationName = "$SiteName/"
    $physicalRaw = Invoke-AppCmdText @("list", "vdir", $applicationName, "/text:physicalPath")
    if (-not $physicalRaw) { throw "iis_physical_path_missing" }
    $physicalExpanded = [Environment]::ExpandEnvironmentVariables($physicalRaw)
    $physicalFull = [IO.Path]::GetFullPath($physicalExpanded).TrimEnd('\')
    $destinationFull = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $ExpectedDestination).Path).TrimEnd('\')
    if (-not [string]::Equals($physicalFull, $destinationFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "iis_destination_binding_mismatch"
    }

    $observedPool = Invoke-AppCmdText @("list", "app", $applicationName, "/text:applicationPool")
    if (-not [string]::Equals($observedPool, $ExpectedPool, [StringComparison]::Ordinal)) {
        throw "iis_application_pool_binding_mismatch"
    }

    return [ordered]@{
        siteName = $SiteName
        applicationPool = $observedPool
        physicalPath = $destinationFull
        hostIdentitySha256 = Get-HostIdentitySha256
        passed = $true
    }
}

function Invoke-StateCheck([string]$AcceptanceEvidence, [string]$ExpectedCommit, [string]$ExpectedBuild, [string]$Output) {
    & $Python "$PSScriptRoot\verify_authoritative_state.py" --base-url $BaseUrl --acceptance-evidence $AcceptanceEvidence --expected-application-commit $ExpectedCommit --expected-application-build $ExpectedBuild --output $Output
    if ($LASTEXITCODE -ne 0) { throw "authoritative_state_check_failed" }
}

function Invoke-UiSmoke {
    $rootResponse = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + "/") -Method Get -UseBasicParsing
    $rootContent = [string]$rootResponse.Content
    $rootBytes = [Text.Encoding]::UTF8.GetByteCount($rootContent)
    if ([int]$rootResponse.StatusCode -ne 200 -or $rootBytes -le 0) { throw "post_deploy_ui_smoke_failed" }

    if ($rootContent -match '(?i)(?:src|href)="https?://' -or $rootContent -match "(?i)(?:src|href)='https?://") {
        throw "post_deploy_remote_asset_dependency_detected"
    }

    $doubleQuotedAssets = [regex]::Matches($rootContent, '(?i)(?:src|href)="(?<path>/[^"]+\.(?:js|css))"')
    $singleQuotedAssets = [regex]::Matches($rootContent, "(?i)(?:src|href)='(?<path>/[^']+\.(?:js|css))'")
    $assetPaths = @(@($doubleQuotedAssets) + @($singleQuotedAssets) | ForEach-Object { $_.Groups["path"].Value } | Select-Object -Unique)
    if ($assetPaths.Count -lt 1) { throw "post_deploy_static_asset_missing" }

    foreach ($assetPath in $assetPaths) {
        $assetResponse = Invoke-WebRequest -Uri ($BaseUrl.TrimEnd('/') + $assetPath) -Method Get -UseBasicParsing
        $assetBytes = [Text.Encoding]::UTF8.GetByteCount([string]$assetResponse.Content)
        if ([int]$assetResponse.StatusCode -ne 200 -or $assetBytes -le 0) { throw "post_deploy_static_asset_failed:$assetPath" }
    }

    return [ordered]@{
        rootStatusCode = [int]$rootResponse.StatusCode
        rootBytes = $rootBytes
        assetCount = $assetPaths.Count
        passed = $true
    }
}

if ([string]::IsNullOrWhiteSpace($IisSiteName)) { throw "iis_site_name_missing" }
if ([string]::IsNullOrWhiteSpace($AppPoolName)) { throw "iis_app_pool_name_missing" }
if (-not (Test-Path -LiteralPath $ArtifactDirectory -PathType Container)) { throw "application_artifact_directory_missing" }
if (-not (Test-Path -LiteralPath $ApplicationManifestPath -PathType Leaf)) { throw "application_manifest_missing" }
if (-not (Test-Path -LiteralPath $SupportedUpdatesPath -PathType Leaf)) { throw "supported_updates_policy_missing" }
$canonicalSupportedUpdatesPath = (Resolve-Path (Join-Path $PSScriptRoot "..\..\config\acceptance\phase1-supported-updates-v1.json")).Path
$observedSupportedUpdatesPath = (Resolve-Path -LiteralPath $SupportedUpdatesPath).Path
if ($observedSupportedUpdatesPath -ne $canonicalSupportedUpdatesPath) { throw "supported_updates_policy_not_canonical" }
$supportedUpdatesPolicySha256 = Get-Sha256 $canonicalSupportedUpdatesPath
if (Test-Path -LiteralPath $EvidenceOutput) { throw "application_lifecycle_evidence_exists" }

$verifyArgs = @(
    "$PSScriptRoot\build_application_artifact_manifest.py",
    "--artifact-root", $ArtifactDirectory,
    "--source-commit", "0000000000000000000000000000000000000000",
    "--build", "verify-only-placeholder",
    "--output", $ApplicationManifestPath,
    "--verify-only"
)
& $Python @verifyArgs
if ($LASTEXITCODE -ne 0) { throw "application_manifest_verification_failed" }

$manifest = Get-Content -LiteralPath $ApplicationManifestPath -Raw | ConvertFrom-Json
$sourceCommit = [string]$manifest.sourceCommit
$build = [string]$manifest.build
if (-not $sourceCommit -or -not $build) { throw "application_manifest_identity_missing" }

$networkIsolation = Assert-InternetUnavailable
$priorRelease = $null
$migrationPolicy = "none"
$preStateOutput = $null
$postStateOutput = $null
$priorManifestEvidence = $null
$priorAcceptanceEvidence = $null
$expectedMigrationScriptSha256 = $null

if ($Mode -eq "fresh-install") {
    if (Test-Path -LiteralPath $Destination) {
        $existing = @(Get-ChildItem -LiteralPath $Destination -Force -ErrorAction Stop)
        if ($existing.Count -ne 0) { throw "fresh_install_destination_not_clean" }
    } else {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }
} else {
    $priorManifestPath = Join-Path $Destination "mavi-application-manifest.json"
    if (-not (Test-Path -LiteralPath $priorManifestPath -PathType Leaf)) { throw "update_prior_manifest_missing" }

    $priorValidationJson = & $Python "$PSScriptRoot\validate_supported_update.py" --policy $SupportedUpdatesPath --prior-manifest $priorManifestPath --prior-root $Destination
    if ($LASTEXITCODE -ne 0) { throw "update_prior_release_validation_failed" }
    $priorValidation = $priorValidationJson | ConvertFrom-Json
    if (-not $priorValidation.ok) { throw "update_prior_release_validation_failed" }

    if ([string]$priorValidation.supportedUpdatesPolicySha256 -ne $supportedUpdatesPolicySha256) { throw "supported_updates_policy_hash_mismatch" }
    $migrationPolicy = [string]$priorValidation.migrationPolicy
    $expectedMigrationScriptSha256 = if ($null -eq $priorValidation.migrationScriptSha256) { $null } else { [string]$priorValidation.migrationScriptSha256 }
    $priorManifestSha = [string]$priorValidation.applicationManifestSha256
    $priorCommit = [string]$priorValidation.sourceCommit
    $priorBuild = [string]$priorValidation.build

    if (-not $PreUpdateAcceptanceEvidence -or -not (Test-Path -LiteralPath $PreUpdateAcceptanceEvidence -PathType Leaf)) { throw "update_pre_state_evidence_missing" }

    $preStateOutput = "$EvidenceOutput.pre-update-state.json"
    $postStateOutput = "$EvidenceOutput.post-update-state.json"
    $priorManifestEvidence = "$EvidenceOutput.prior-application-manifest.json"
    $priorAcceptanceEvidence = "$EvidenceOutput.prior-acceptance-evidence.json"
    if ((Test-Path -LiteralPath $preStateOutput) -or (Test-Path -LiteralPath $postStateOutput) -or (Test-Path -LiteralPath $priorManifestEvidence) -or (Test-Path -LiteralPath $priorAcceptanceEvidence)) { throw "update_state_check_output_exists" }
    Copy-Item -LiteralPath $priorManifestPath -Destination $priorManifestEvidence -ErrorAction Stop
    if ((Get-Sha256 $priorManifestEvidence) -ne $priorManifestSha) { throw "update_prior_manifest_evidence_mismatch" }
    Copy-Item -LiteralPath $PreUpdateAcceptanceEvidence -Destination $priorAcceptanceEvidence -ErrorAction Stop
    if ((Get-Sha256 $priorAcceptanceEvidence) -ne (Get-Sha256 $PreUpdateAcceptanceEvidence)) { throw "update_prior_acceptance_evidence_mismatch" }

    Invoke-StateCheck -AcceptanceEvidence $PreUpdateAcceptanceEvidence -ExpectedCommit $priorCommit -ExpectedBuild $priorBuild -Output $preStateOutput

    $priorRelease = [ordered]@{
        sourceCommit = $priorCommit
        build = $priorBuild
        applicationManifestSha256 = $priorManifestSha
        supported = $true
    }
}

Invoke-AppCmd @("stop", "apppool", "/apppool.name:$AppPoolName")

try {
    $robocopyArgs = @($ArtifactDirectory, $Destination, "/MIR", "/COPY:DAT", "/DCOPY:DAT", "/R:2", "/W:1", "/NFL", "/NDL", "/NP")
    & robocopy.exe @robocopyArgs | Out-Null
    $robocopyCode = $LASTEXITCODE
    if ($robocopyCode -gt 7) { throw "application_copy_failed:$robocopyCode" }

    $deployedManifestPath = Join-Path $Destination "mavi-application-manifest.json"
    if (-not (Test-Path -LiteralPath $deployedManifestPath -PathType Leaf)) { throw "deployed_application_manifest_missing" }
    if ((Get-Sha256 $deployedManifestPath) -ne (Get-Sha256 $ApplicationManifestPath)) { throw "deployed_application_manifest_mismatch" }

    $deployedVerifyArgs = @(
        "$PSScriptRoot\build_application_artifact_manifest.py",
        "--artifact-root", $Destination,
        "--source-commit", "0000000000000000000000000000000000000000",
        "--build", "verify-only-placeholder",
        "--output", $deployedManifestPath,
        "--verify-only"
    )
    & $Python @deployedVerifyArgs
    if ($LASTEXITCODE -ne 0) { throw "deployed_application_integrity_failed" }

    $hosting = Assert-IisHostingBinding -SiteName $IisSiteName -ExpectedPool $AppPoolName -ExpectedDestination $Destination

    $migrationEvidence = $null
    if ($migrationPolicy -eq "required") {
        if (-not $MigrationScriptPath -or -not (Test-Path -LiteralPath $MigrationScriptPath -PathType Leaf)) { throw "required_migration_script_missing" }
        if (-not $expectedMigrationScriptSha256 -or (Get-Sha256 $MigrationScriptPath) -ne $expectedMigrationScriptSha256) { throw "required_migration_script_identity_mismatch" }
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $MigrationScriptPath
        $migrationExit = $LASTEXITCODE
        if ($migrationExit -ne 0) { throw "required_migration_failed:$migrationExit" }
        $migrationEvidence = [ordered]@{
            commandIdentity = Get-Sha256 $MigrationScriptPath
            exitCode = $migrationExit
            passed = $true
        }
    }

    Invoke-AppCmd @("start", "apppool", "/apppool.name:$AppPoolName")

    Start-Sleep -Seconds 2
    $health = Invoke-RestMethod -Uri ($BaseUrl.TrimEnd('/') + "/api/health") -Method Get
    if ($health.status -ne "ok" -or $health.build -ne $build -or $health.commit -ne $sourceCommit) { throw "post_deploy_application_identity_mismatch" }

    $uiSmoke = Invoke-UiSmoke

    $retainedState = $null
    if ($Mode -eq "offline-update") {
        Invoke-StateCheck -AcceptanceEvidence $PreUpdateAcceptanceEvidence -ExpectedCommit $sourceCommit -ExpectedBuild $build -Output $postStateOutput
        $retainedState = [ordered]@{
            acceptanceEvidenceSha256 = Get-Sha256 $PreUpdateAcceptanceEvidence
            preUpdateCheckSha256 = Get-Sha256 $preStateOutput
            postUpdateCheckSha256 = Get-Sha256 $postStateOutput
        }
    }

    $evidence = [ordered]@{
        schemaVersion = "mavi-application-lifecycle-evidence-v1"
        mode = $Mode
        sourceCommit = $sourceCommit
        build = $build
        applicationManifestSha256 = Get-Sha256 $ApplicationManifestPath
        supportedUpdatesPolicySha256 = $supportedUpdatesPolicySha256
        destination = (Resolve-Path -LiteralPath $Destination).Path
        hosting = $hosting
        internetUnavailable = $true
        networkIsolation = $networkIsolation
        priorRelease = $priorRelease
        migrationPolicy = $migrationPolicy
        migration = $migrationEvidence
        retainedState = $retainedState
        uiSmoke = $uiSmoke
        observedHealth = [ordered]@{
            status = [string]$health.status
            build = [string]$health.build
            commit = [string]$health.commit
        }
        result = [ordered]@{
            passed = $true
            failureCodes = @()
        }
    }

    $json = $evidence | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($EvidenceOutput, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Write-Host "Task-17 application $Mode qualification PASSED."
}
catch {
    try { Invoke-AppCmd @("start", "apppool", "/apppool.name:$AppPoolName") } catch { }
    throw
}
