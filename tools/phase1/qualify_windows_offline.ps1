param(
    [Parameter(Mandatory = $true)][ValidateSet("P1","P3")][string]$DeploymentProfile,
    [Parameter(Mandatory = $true)][string]$Bundle,
    [Parameter(Mandatory = $true)][string]$SourceCommit,
    [Parameter(Mandatory = $true)][string]$TargetVerifiedManifestSha256,
    [Parameter(Mandatory = $true)][string]$AcceptanceProfile,
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$MediaRoot,
    [Parameter(Mandatory = $true)][string]$CameraCode,
    [Parameter(Mandatory = $true)][string]$CameraName,
    [Parameter(Mandatory = $true)][string]$CameraTimezone,
    [Parameter(Mandatory = $true)][string]$RecordingLocal,
    [Parameter(Mandatory = $true)][string]$Video,
    [Parameter(Mandatory = $true)][string]$EnvironmentLabel,
    [Parameter(Mandatory = $true)][string]$MaviBuild,
    [Parameter(Mandatory = $true)][string]$CorpusManifest,
    [Parameter(Mandatory = $true)][string]$GroundTruth,
    [Parameter(Mandatory = $true)][string]$WorkRoot,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$DeploymentProfilePolicy = "",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (Test-Path -LiteralPath $Output) { throw "windows_offline_evidence_exists" }
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

$variant = if ($DeploymentProfile -eq "P1") {
    "windows-x86_64-cuda"
} else {
    "windows-x86_64-cpu"
}
$variantOut = Join-Path $WorkRoot "$variant.json"
$workerOut = Join-Path $WorkRoot "$variant.worker.json"
$venv = Join-Path $WorkRoot "venv-$DeploymentProfile"

$qualifyArguments = @(
    "$PSScriptRoot\qualify_offline_variant.py",
    "--bundle-dir", $Bundle,
    "--variant", $variant,
    "--source-commit", $SourceCommit,
    "--target-verified-manifest-sha256", $TargetVerifiedManifestSha256,
    "--acceptance-profile", $AcceptanceProfile,
    "--base-url", $BaseUrl,
    "--media-root", $MediaRoot,
    "--camera-code", $CameraCode,
    "--camera-name", $CameraName,
    "--camera-timezone", $CameraTimezone,
    "--recording-local", $RecordingLocal,
    "--video", $Video,
    "--environment-label", "$EnvironmentLabel-$DeploymentProfile",
    "--expected-mavi-build", $MaviBuild,
    "--corpus-manifest", $CorpusManifest,
    "--ground-truth", $GroundTruth,
    "--worker-flow-output", $workerOut,
    "--venv", $venv,
    "--network-isolated",
    "--output", $variantOut
)
& $Python @qualifyArguments
if ($LASTEXITCODE -ne 0) {
    throw "windows_variant_offline_qualification_failed:$variant"
}

$assembleArguments = @(
    "$PSScriptRoot\assemble_offline_install_evidence.py",
    "--deployment-profile", $DeploymentProfile,
    "--variant", $variantOut,
    "--isolation-method", "disconnected-windows-qualification-host",
    "--output", $Output
)
if (-not [string]::IsNullOrWhiteSpace($DeploymentProfilePolicy)) {
    $assembleArguments += @(
        "--deployment-profile-policy", $DeploymentProfilePolicy
    )
}
& $Python @assembleArguments
if ($LASTEXITCODE -ne 0) {
    throw "windows_offline_evidence_assembly_failed"
}

$verifyArguments = @(
    "$PSScriptRoot\verify_phase1_evidence.py",
    "--offline-install", $Output,
    "--expected-source-commit", $SourceCommit
)
& $Python @verifyArguments
if ($LASTEXITCODE -ne 0) {
    throw "windows_offline_evidence_verification_failed"
}

Write-Host "Task-18 Windows offline qualification PASSED for $DeploymentProfile ($variant)."
