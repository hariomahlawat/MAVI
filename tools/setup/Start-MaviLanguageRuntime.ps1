[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    # A Python able to run tools\language\language_packs.py (standard library only); the PoC uses the embeddings venv.
    [Parameter(Mandatory = $true)][string]$Python,
    # Where tools\language\language_packs.py stage put the runtime (cpu\, cuda\, LICENSE) and the Model Packs.
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    # The bound Language Model Pack directory (models\language\<pack>.json).
    [Parameter(Mandatory = $true)][string]$Pack,
    [int]$Port = 62301,
    # ADR-008: auto prefers CUDA when an NVIDIA GPU answers and records why; cuda fails closed; cpu never touches the GPU.
    [ValidateSet("auto", "cuda", "cpu")][string]$DevicePolicy = "auto",
    [Parameter(Mandatory = $true)][string]$DeviceReportPath,
    # The PTX JIT cache for GPUs without native code (sm_75), kept under the PoC data root, never the user profile.
    [Parameter(Mandatory = $true)][string]$CudaCachePath,
    [int]$ContextSize = 8192,
    [int]$Threads = 4
)

# PoC S10 (ADR-026 §3): the language role. Verifies the Language Runtime Pack variant and the bound Language Model Pack
# byte for byte (tools\language\language_packs.py verify) before every start, resolves the device by policy and records
# it, then runs llama-server on loopback in the foreground (Stop-MaviPoc stops this process tree). One slot, fixed
# context and threads: Ask MAVI decodes greedily with a fixed seed. The role holds no authority; the API validates
# everything it writes.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$RuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot)
$ModelRoot = [IO.Path]::GetFullPath($ModelRoot)
Remove-Item -LiteralPath $DeviceReportPath -Force -ErrorAction SilentlyContinue

$nvidiaSmi = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
$smiLines = $null
if ($nvidiaSmi) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { $smiLines = @(& $nvidiaSmi.Source --query-gpu=index,name,compute_cap,memory.total,memory.used --format=csv,noheader 2>$null) }
    finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { $smiLines = @() }
}
$device = Resolve-MaviPocLanguageDevice -Policy $DevicePolicy -NvidiaSmiLines $smiLines

$verified = & $Python (Join-Path $RepositoryRoot "tools\language\language_packs.py") verify --runtime-root $RuntimeRoot --variant $device.Variant --model-root $ModelRoot --pack $Pack
if ($LASTEXITCODE -ne 0) { throw "The Language Runtime Pack or Model Pack failed verification; the language role does not start." }
$identity = $verified | ConvertFrom-Json

$report = [ordered]@{
    role = "language"
    requestedDevicePolicy = $DevicePolicy
    resolvedDevicePolicy = $device.Variant
    device = $device.Device
    deviceResolutionReason = $device.Reason
    gpuLayerPolicy = if ($device.Variant -eq "cuda") { "fit (llama.cpp --fit on: as many layers as fit in free GPU memory)" } else { "none" }
    runtimeId = $identity.runtimeId
    runtimeVariant = $identity.variant
    modelPackId = $identity.modelPackId
    modelId = $identity.modelId
    quantisation = $identity.quantisation
    port = $Port
    resolvedAtUtc = [DateTime]::UtcNow.ToString("o")
}
New-Item -ItemType Directory -Path (Split-Path -Parent $DeviceReportPath) -Force | Out-Null
$report | ConvertTo-Json | Set-Content -LiteralPath $DeviceReportPath -Encoding UTF8

$server = Join-Path (Join-Path $RuntimeRoot $device.Directory) "llama-server.exe"
$arguments = @(
    "--model", $identity.modelPath,
    "--host", "127.0.0.1", "--port", "$Port",
    "--ctx-size", "$ContextSize", "--parallel", "1", "--threads", "$Threads",
    "--no-webui"
)
if ($device.Variant -eq "cuda") {
    New-Item -ItemType Directory -Path $CudaCachePath -Force | Out-Null
    $env:CUDA_CACHE_PATH = [IO.Path]::GetFullPath($CudaCachePath)
    $env:CUDA_CACHE_MAXSIZE = "4294967296"
    $arguments += @("--fit", "on")
}
else {
    $env:CUDA_VISIBLE_DEVICES = ""
    $arguments += @("--n-gpu-layers", "0")
}

Write-Host "Starting MAVI language role (PoC S10, ADR-026; Development, unverified packs)" -ForegroundColor Yellow
Write-Host "  Runtime     : $($identity.runtimeId) ($($identity.variant))"
Write-Host "  Model Pack  : $($identity.modelPackId) ($($identity.modelId), $($identity.quantisation))"
Write-Host "  Device      : $($device.Device) ($($device.Reason)); requested $DevicePolicy"
Write-Host "  Endpoint    : http://127.0.0.1:$Port (loopback only)"
& $server @arguments
exit $LASTEXITCODE
