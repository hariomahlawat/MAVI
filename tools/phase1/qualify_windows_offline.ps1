param(
    [Parameter(Mandatory = $true)][string]$CpuBundle,
    [Parameter(Mandatory = $true)][string]$CudaBundle,
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
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (Test-Path -LiteralPath $Output) { throw "windows_offline_evidence_exists" }
New-Item -ItemType Directory -Path $WorkRoot -Force | Out-Null

$cpuOut = Join-Path $WorkRoot "windows-x86_64-cpu.json"
$cudaOut = Join-Path $WorkRoot "windows-x86_64-cuda.json"
$cpuWorker = Join-Path $WorkRoot "windows-x86_64-cpu.worker.json"
$cudaWorker = Join-Path $WorkRoot "windows-x86_64-cuda.worker.json"
$cpuVenv = Join-Path $WorkRoot "venv-cpu"
$cudaVenv = Join-Path $WorkRoot "venv-cuda"

function Invoke-Variant(
    [string]$Bundle,
    [string]$Variant,
    [string]$Venv,
    [string]$WorkerOutput,
    [string]$EvidenceOutput
) {
    $arguments = @(
        "$PSScriptRoot\qualify_offline_variant.py",
        "--bundle-dir", $Bundle,
        "--variant", $Variant,
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
        "--environment-label", "$EnvironmentLabel-$Variant",
        "--expected-mavi-build", $MaviBuild,
        "--corpus-manifest", $CorpusManifest,
        "--ground-truth", $GroundTruth,
        "--worker-flow-output", $WorkerOutput,
        "--venv", $Venv,
        "--network-isolated",
        "--output", $EvidenceOutput
    )
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) { throw "windows_variant_offline_qualification_failed:$Variant" }
}

Invoke-Variant -Bundle $CpuBundle -Variant "windows-x86_64-cpu" -Venv $cpuVenv -WorkerOutput $cpuWorker -EvidenceOutput $cpuOut
Invoke-Variant -Bundle $CudaBundle -Variant "windows-x86_64-cuda" -Venv $cudaVenv -WorkerOutput $cudaWorker -EvidenceOutput $cudaOut

$assembleArguments = @(
    "$PSScriptRoot\assemble_offline_install_evidence.py",
    "--os", "windows",
    "--cpu", $cpuOut,
    "--cuda", $cudaOut,
    "--isolation-method", "disconnected-windows-qualification-host",
    "--output", $Output
)
& $Python @assembleArguments
if ($LASTEXITCODE -ne 0) { throw "windows_offline_evidence_assembly_failed" }

$verifyArguments = @(
    "$PSScriptRoot\verify_phase1_evidence.py",
    "--offline-install", $Output,
    "--expected-source-commit", $SourceCommit
)
& $Python @verifyArguments
if ($LASTEXITCODE -ne 0) { throw "windows_offline_evidence_verification_failed" }

Write-Host "Task-17 Windows CPU+CUDA offline qualification PASSED."
