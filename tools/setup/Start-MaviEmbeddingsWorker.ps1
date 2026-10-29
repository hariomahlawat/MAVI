[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [string]$WorkerId = "embeddings-01",
    # The embeddings-onnx-v1 environment created by tools\setup\Install-MaviEmbeddingsRuntime.ps1.
    [Parameter(Mandatory = $true)][string]$Python,
    # The model store the SigLIP 2 pack was staged into.
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    # cpu (default) or cuda. CUDA needs the CUDA build of ONNX Runtime that S1b pins for the ONNX roles; until that
    # lands the packaged runtime is CPU and explicit cuda fails closed (no silent CPU fallback).
    [ValidateSet("cpu", "cuda", "auto")][string]$DevicePolicy = "cpu",
    [string]$CudaDllDirectory
)

# PoC S4 (ADR-021): the embeddings role on the committed Development manifest and pipeline profile. Always Development
# mode. The worker verifies every Model Pack artefact SHA-256 before loading, derives its identity from the manifest
# and profile bytes, and leases only that identity. The platform must run with the matching configuration:
#   Embeddings:Enabled=true
#   Embeddings:ModelManifestPath=<root>\models\manifests\embeddings-siglip2-base-p16-224-dev-v1.json
#   Embeddings:PipelineProfilePath=<root>\src\vision\config\embeddings\development-embeddings-siglip2-v1.json

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$head = (Resolve-MaviApplicationRevision -Root $RepositoryRoot).Revision

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_DEVICE_POLICY = $DevicePolicy
$env:MAVI_EMBEDDING_MANIFEST_PATH = Join-Path $RepositoryRoot "models\manifests\embeddings-siglip2-base-p16-224-dev-v1.json"
$env:MAVI_PIPELINE_PROFILE_PATH = Join-Path $RepositoryRoot "src\vision\config\embeddings\development-embeddings-siglip2-v1.json"
$env:MAVI_MODEL_ROOT = [IO.Path]::GetFullPath($ModelRoot)
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head
$env:PYTHONPATH = Join-Path $RepositoryRoot "src\vision"
if ($CudaDllDirectory) { $env:MAVI_CUDA_DLL_DIRECTORY = [IO.Path]::GetFullPath($CudaDllDirectory) }
else { Remove-Item Env:MAVI_CUDA_DLL_DIRECTORY -ErrorAction SilentlyContinue }

Write-Host "Starting MAVI embeddings worker (PoC S4, SigLIP 2, unverified Model Pack; Development only)" -ForegroundColor Yellow
Write-Host "  Application : $head"
Write-Host "  Manifest    : $env:MAVI_EMBEDDING_MANIFEST_PATH"
Write-Host "  Profile     : $env:MAVI_PIPELINE_PROFILE_PATH"
Write-Host "  Model store : $env:MAVI_MODEL_ROOT"
Write-Host "  Device      : $DevicePolicy"
& $Python -m mavi_vision.embeddings.main
exit $LASTEXITCODE
