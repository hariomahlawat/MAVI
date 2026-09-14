param(
    [Parameter(Mandatory = $true)][string]$CpuBundle,
    [Parameter(Mandatory = $true)][string]$CudaBundle,
    [Parameter(Mandatory = $true)][string]$CpuWorkerEvidence,
    [Parameter(Mandatory = $true)][string]$CudaWorkerEvidence,
    [Parameter(Mandatory = $true)][string]$SourceCommit,
    [Parameter(Mandatory = $true)][string]$TargetVerifiedManifestSha256,
    [Parameter(Mandatory = $true)][string]$AcceptanceProfile,
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
$cpuVenv = Join-Path $WorkRoot "venv-cpu"
$cudaVenv = Join-Path $WorkRoot "venv-cuda"

& $Python "$PSScriptRoot\qualify_offline_variant.py" --bundle-dir $CpuBundle --variant "windows-x86_64-cpu" --source-commit $SourceCommit --target-verified-manifest-sha256 $TargetVerifiedManifestSha256 --worker-flow-evidence $CpuWorkerEvidence --acceptance-profile $AcceptanceProfile --venv $cpuVenv --network-isolated --output $cpuOut
if ($LASTEXITCODE -ne 0) { throw "windows_cpu_offline_qualification_failed" }

& $Python "$PSScriptRoot\qualify_offline_variant.py" --bundle-dir $CudaBundle --variant "windows-x86_64-cuda" --source-commit $SourceCommit --target-verified-manifest-sha256 $TargetVerifiedManifestSha256 --worker-flow-evidence $CudaWorkerEvidence --acceptance-profile $AcceptanceProfile --venv $cudaVenv --network-isolated --output $cudaOut
if ($LASTEXITCODE -ne 0) { throw "windows_cuda_offline_qualification_failed" }

& $Python "$PSScriptRoot\assemble_offline_install_evidence.py" --os windows --cpu $cpuOut --cuda $cudaOut --isolation-method "disconnected-windows-qualification-host" --output $Output
if ($LASTEXITCODE -ne 0) { throw "windows_offline_evidence_assembly_failed" }

& $Python "$PSScriptRoot\verify_phase1_evidence.py" --offline-install $Output --expected-source-commit $SourceCommit
if ($LASTEXITCODE -ne 0) { throw "windows_offline_evidence_verification_failed" }

Write-Host "Task-17 Windows CPU+CUDA offline qualification PASSED."
