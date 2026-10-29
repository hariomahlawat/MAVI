[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [string]$WorkerId = "attributes-01",
    # The embeddings-onnx-v1 environment created by tools\setup\Install-MaviEmbeddingsRuntime.ps1: the zero-shot role
    # runs on the same runtime and the same SigLIP 2 Model Pack as the embeddings role (no second copy of the model).
    [Parameter(Mandatory = $true)][string]$Python,
    # The model store the SigLIP 2 pack was staged into.
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    [ValidateSet("cpu", "cuda", "auto")][string]$DevicePolicy = "cpu",
    [string]$CudaDllDirectory
)

# PoC S5 (ADR-021 amendment 2026-10-29): the attributes role with the SigLIP 2 zero-shot inferencer, composed from the
# committed Development release (src\vision\config\attributes). Always Development mode; zero-shot, Development. The
# worker verifies every Model Pack artefact SHA-256 before loading and leases only the identity the release defines.
# The platform must run with the matching configuration:
#   VisualAttributes:Enabled=true
#   VisualAttributes:ComponentBindingPath=<root>\src\vision\config\attributes\development-attributes-siglip2-binding-v1.json
#   VisualAttributes:PipelineProfilePath=<root>\src\vision\config\attributes\development-attributes-siglip2-zero-shot-v1.json

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$head = (Resolve-MaviApplicationRevision -Root $RepositoryRoot).Revision
$release = Join-Path $RepositoryRoot "src\vision\config\attributes"

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_DEVICE_POLICY = $DevicePolicy
$env:MAVI_COMPONENT_BINDING_PATH = Join-Path $release "development-attributes-siglip2-binding-v1.json"
$env:MAVI_PIPELINE_PROFILE_PATH = Join-Path $release "development-attributes-siglip2-zero-shot-v1.json"
$env:MAVI_ATTRIBUTE_MODEL_MANIFEST_PATH = Join-Path $RepositoryRoot "models\manifests\embeddings-siglip2-base-p16-224-dev-v1.json"
$env:MAVI_ATTRIBUTE_RUNTIME_PROFILE_PATH = Join-Path $RepositoryRoot "src\vision\runtime\embeddings-onnx-v1\runtime.json"
$env:MAVI_MODEL_ROOT = [IO.Path]::GetFullPath($ModelRoot)
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head
$env:PYTHONPATH = Join-Path $RepositoryRoot "src\vision"
if ($CudaDllDirectory) { $env:MAVI_CUDA_DLL_DIRECTORY = [IO.Path]::GetFullPath($CudaDllDirectory) }
else { Remove-Item Env:MAVI_CUDA_DLL_DIRECTORY -ErrorAction SilentlyContinue }

Write-Host "Starting MAVI attributes worker (PoC S5, SigLIP 2 zero-shot, Development only)" -ForegroundColor Yellow
Write-Host "  Application : $head"
Write-Host "  Binding     : $env:MAVI_COMPONENT_BINDING_PATH"
Write-Host "  Profile     : $env:MAVI_PIPELINE_PROFILE_PATH"
Write-Host "  Model store : $env:MAVI_MODEL_ROOT"
Write-Host "  Device      : $DevicePolicy"
& $Python -m mavi_vision.attributes.main
exit $LASTEXITCODE
